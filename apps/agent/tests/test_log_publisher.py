"""Agent log-publisher tests (phase 1.5)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from dopilot_agent.config.settings import LOG_PUBLISH_RATE_MIN
from dopilot_agent.deps import state_dir
from dopilot_agent.redis.logs import LogPublisher
from dopilot_agent.state.store import StateStore
from dopilot_protocol import LOG_STREAM, AgentLogEvent, from_stream_entry

AGENT_ID = "agent-x"


def _started(workdir: Path, log_path: Path) -> StateStore:
    store = StateStore(state_dir(workdir))
    store.create_reserved(task_id="e1", execution_id="a1", project="demo", spider="phase1")
    store.promote_started("a1", scrapyd_job_id="job-1", log_path=str(log_path))
    return store


def _publisher(workdir: Path, store: StateStore, fake, *, max_bytes=262144) -> LogPublisher:
    return LogPublisher(
        redis=fake,
        agent_id=AGENT_ID,
        store=store,
        cursor_dir=str(workdir / "logpos"),
        max_bytes=max_bytes,
    )


async def _log_events(fake) -> list[AgentLogEvent]:
    return [from_stream_entry(AgentLogEvent, f) for _id, f in await fake.entries(LOG_STREAM)]


async def test_publishes_increments_byte_exact(workdir, fake_redis):
    fake = fake_redis()
    log = workdir / "job.log"
    store = _started(workdir, log)
    pub = _publisher(workdir, store, fake)

    raw = b"line one\n\xff\xfe partial-utf8 \x00\x01\x02 more\n"
    log.write_bytes(raw)
    written = await pub.publish_attempt("a1")
    assert written == len(raw)

    events = await _log_events(fake)
    data_events = [e for e in events if not e.eof]
    assert len(data_events) == 1
    e = data_events[0]
    assert e.offset == 0 and e.size_bytes == len(raw)
    assert base64.b64decode(e.content_b64) == raw  # byte-exact, incl invalid utf-8


async def test_resume_from_cursor_no_duplicate(workdir, fake_redis):
    fake = fake_redis()
    log = workdir / "job.log"
    store = _started(workdir, log)
    pub = _publisher(workdir, store, fake)

    log.write_bytes(b"first chunk\n")
    await pub.publish_attempt("a1")
    # re-publish with nothing new -> no duplicate event
    await pub.publish_attempt("a1")
    assert len([e for e in await _log_events(fake) if not e.eof]) == 1

    # append more -> continues at the correct offset, strictly increasing
    log.write_bytes(b"first chunk\nsecond chunk\n")
    await pub.publish_attempt("a1")
    data = [e for e in await _log_events(fake) if not e.eof]
    assert [e.offset for e in data] == [0, len(b"first chunk\n")]
    # reassembled bytes are contiguous
    assert b"".join(base64.b64decode(e.content_b64) for e in data) == b"first chunk\nsecond chunk\n"


async def test_chunking_by_max_bytes_strictly_increasing(workdir, fake_redis):
    fake = fake_redis()
    log = workdir / "job.log"
    store = _started(workdir, log)
    pub = _publisher(workdir, store, fake, max_bytes=4)

    log.write_bytes(b"abcdefghij")  # 10 bytes -> chunks of 4,4,2
    await pub.publish_attempt("a1")
    data = [e for e in await _log_events(fake) if not e.eof]
    assert [e.offset for e in data] == [0, 4, 8]
    assert [e.size_bytes for e in data] == [4, 4, 2]
    # strictly increasing, contiguous
    assert b"".join(base64.b64decode(e.content_b64) for e in data) == b"abcdefghij"


async def test_terminal_emits_eof_once(workdir, fake_redis):
    fake = fake_redis()
    log = workdir / "job.log"
    store = _started(workdir, log)
    pub = _publisher(workdir, store, fake)

    log.write_bytes(b"done body\n")
    store.mark_done("a1", result="finished", exit_code=0)
    await pub.publish_attempt("a1")
    eofs = [e for e in await _log_events(fake) if e.eof]
    assert len(eofs) == 1
    # publishing again does not re-emit eof
    await pub.publish_attempt("a1")
    assert len([e for e in await _log_events(fake) if e.eof]) == 1


async def test_xadd_failure_does_not_advance_cursor(workdir, fake_redis):
    fake = fake_redis()
    log = workdir / "job.log"
    store = _started(workdir, log)
    pub = _publisher(workdir, store, fake)

    log.write_bytes(b"payload\n")
    fake.fail_xadd = True
    assert await pub.publish_attempt("a1") == 0
    assert await fake.entries(LOG_STREAM) == []

    # Redis recovers -> republish from offset 0 (cursor never advanced)
    fake.fail_xadd = False
    await pub.publish_attempt("a1")
    data = [e for e in await _log_events(fake) if not e.eof]
    assert data[0].offset == 0
    assert base64.b64decode(data[0].content_b64) == b"payload\n"


# --- TC-03: per-execution publish cap --------------------------------------------


async def test_publish_cap_emits_marker_once_then_stops_tailing(workdir, fake_redis):
    fake = fake_redis()
    log = workdir / "job.log"
    store = _started(workdir, log)
    pub = LogPublisher(
        redis=fake, agent_id=AGENT_ID, store=store, cursor_dir=str(workdir / "logpos"),
        max_bytes=1024, max_job_log_bytes=4096, rate_bytes_per_second=0,
    )
    log.write_bytes(b"a" * (10 * 1024))
    await pub.publish_once()
    events = [e for e in await _log_events(fake) if not e.eof]
    def _is_marker(e: AgentLogEvent) -> bool:
        return b"[dopilot:log-truncated" in base64.b64decode(e.content_b64)

    content = [e for e in events if not _is_marker(e)]
    marker = [e for e in events if _is_marker(e)]
    # EVERYTHING published for the execution (content + the one marker) fits
    # inside the cap: the marker room is reserved from the 4096.
    assert sum(e.size_bytes for e in events) <= 4096
    assert len(marker) == 1
    assert sum(e.size_bytes for e in content) == marker[0].offset
    assert marker[0].offset + marker[0].size_bytes <= 4096
    assert events[-1] is marker[0]
    assert store.read("a1").log_capped is True

    with log.open("ab") as fh:
        fh.write(b"b" * (10 * 1024))
    await pub.publish_once()
    assert len(await _log_events(fake)) == len(events)  # nothing new

    store.mark_done("a1", result="finished")
    await pub.publish_once()
    assert (await _log_events(fake))[-1].eof is True


# --- TC-04: agent-wide token bucket with rotation ------------------------------------


async def test_rate_limit_bounds_bytes_per_tick_and_rotates(workdir, fake_redis):
    fake = fake_redis()
    store = StateStore(state_dir(workdir))
    logs = []
    for i in range(3):
        log = workdir / f"job{i}.log"
        log.write_bytes(bytes([65 + i]) * (1024 * 1024))
        store.create_reserved(task_id="e1", execution_id=f"a{i}", project="demo", spider="s")
        store.promote_started(f"a{i}", scrapyd_job_id=f"job-{i}", log_path=str(log))
        logs.append(log)
    clock = {"t": 1000.0}
    rate = 256 * 1024
    pub = LogPublisher(
        redis=fake, agent_id=AGENT_ID, store=store, cursor_dir=str(workdir / "logpos"),
        max_bytes=64 * 1024, rate_bytes_per_second=rate, clock=lambda: clock["t"],
    )
    totals = []
    for _ in range(3):
        clock["t"] += 1.0
        totals.append(await pub.publish_once())
    # each tick pushes at most the bucket capacity (2s of quota)
    assert all(t <= rate * 2 for t in totals)
    assert all(t > 0 for t in totals)
    by_exec: dict[str, int] = {}
    for e in await _log_events(fake):
        by_exec[e.execution_id] = by_exec.get(e.execution_id, 0) + e.size_bytes
    # rotation: every execution made progress, and the stream total equals the sum
    assert set(by_exec) == {"a0", "a1", "a2"}
    assert sum(by_exec.values()) == sum(totals)


async def test_markers_are_bucket_accounted_under_starved_allowance(workdir, fake_redis):
    """R-01 (round 3): truncation markers must not bypass the token bucket.

    A bucket with less than one marker of allowance plus several executions that
    all hit their cap in the same tick must NOT each push a full marker: the
    bytes that actually land in Redis per tick stay within the bucket capacity,
    and the markers arrive once the bucket refilled — each spending its bytes.
    """
    fake = fake_redis()
    store = StateStore(state_dir(workdir))
    cursor_dir = workdir / "logpos"
    cursor_dir.mkdir()
    cap = 4096
    rate = 1024  # bucket capacity = 2048 bytes
    clock = {"t": 1000.0}
    pub = LogPublisher(
        redis=fake, agent_id=AGENT_ID, store=store, cursor_dir=str(cursor_dir),
        max_bytes=64 * 1024, max_job_log_bytes=cap, rate_bytes_per_second=rate,
        clock=lambda: clock["t"],
    )
    marker_len = len(pub._marker())
    content_cap = cap - marker_len
    # "a0" drains the bucket first (scan order is sorted); b0..b2 already sit
    # exactly at their content cap (cursor == content_cap), so their next step
    # is the marker.
    drain = workdir / "a0.log"
    drain.write_bytes(b"d" * (rate * 2))  # exactly one full bucket
    store.create_reserved(task_id="e1", execution_id="a0", project="demo", spider="s")
    store.promote_started("a0", scrapyd_job_id="job-a0", log_path=str(drain))
    for i in range(3):
        log = workdir / f"b{i}.log"
        log.write_bytes(b"x" * (content_cap + 500))
        store.create_reserved(task_id="e1", execution_id=f"b{i}", project="demo", spider="s")
        store.promote_started(f"b{i}", scrapyd_job_id=f"job-b{i}", log_path=str(log))
        (cursor_dir / f"b{i}.logpos").write_text(str(content_cap), encoding="utf-8")

    async def _tick(dt: float) -> tuple[int, int]:
        before = len(await fake.entries(LOG_STREAM))
        clock["t"] += dt
        total = await pub.publish_once()
        landed = sum(e.size_bytes for e in (await _log_events(fake))[before:])
        return total, landed

    # tick 1: full bucket, a0 consumes all 2048 bytes -> b* get nothing
    total, landed = await _tick(1.0)
    assert total == landed == rate * 2
    assert not any(e.execution_id.startswith("b") for e in await _log_events(fake))

    # tick 2: only ~1 byte refilled (< one marker): a0 may push that 1 byte of
    # content, but NO marker may be pushed for any of the capped executions
    total, landed = await _tick(0.001)
    assert total == landed <= 1
    assert not any(e.execution_id.startswith("b") for e in await _log_events(fake))
    assert not any(store.read(f"b{i}").log_capped for i in range(3))

    # tick 3: bucket refilled -> the three markers go out, each spending bytes
    total, landed = await _tick(2.0)
    markers = [
        e for e in await _log_events(fake)
        if b"[dopilot:log-truncated" in base64.b64decode(e.content_b64)
    ]
    assert len(markers) == 3 and {e.execution_id for e in markers} == {"b0", "b1", "b2"}
    assert all(e.offset == content_cap and e.size_bytes == marker_len for e in markers)
    assert all(store.read(f"b{i}").log_capped for i in range(3))
    # Redis-side bytes this tick are exactly the three markers, reported in the
    # publish total AND spent from the bucket (per-tick bytes that actually
    # reached Redis never exceeded the bucket capacity on any tick above).
    assert landed == total == 3 * marker_len <= rate * 2
    assert pub._allowance() == rate * 2 - 3 * marker_len


async def test_marker_never_overshoots_bucket_at_minimum_rate(workdir, fake_redis):
    """R-01 (round 4): no config lets a marker exceed the bucket.

    (a) a rate whose 2s bucket is smaller than one marker is refused by the
    publisher itself (settings refuse it too) — nothing can land in Redis;
    (b) at the smallest legal rate (128 B/s -> 256 B bucket) a capped execution
    waits while the allowance is below one marker and the bytes that actually
    land in Redis per tick never exceed the bucket, marker included.
    """
    fake = fake_redis()
    store = StateStore(state_dir(workdir))
    cursor_dir = workdir / "logpos"
    cursor_dir.mkdir()
    cap = 4096
    log = workdir / "b0.log"
    log.write_bytes(b"x" * (cap + 500))
    store.create_reserved(task_id="e1", execution_id="b0", project="demo", spider="s")
    store.promote_started("b0", scrapyd_job_id="job-b0", log_path=str(log))

    # (a) bucket (2 B) < marker: refused up front
    with pytest.raises(ValueError):
        LogPublisher(
            redis=fake, agent_id=AGENT_ID, store=store, cursor_dir=str(cursor_dir),
            max_job_log_bytes=cap, rate_bytes_per_second=1,
        )
    assert await fake.entries(LOG_STREAM) == []

    # (b) minimum legal rate
    rate = LOG_PUBLISH_RATE_MIN
    clock = {"t": 1000.0}
    pub = LogPublisher(
        redis=fake, agent_id=AGENT_ID, store=store, cursor_dir=str(cursor_dir),
        max_bytes=64 * 1024, max_job_log_bytes=cap, rate_bytes_per_second=rate,
        clock=lambda: clock["t"],
    )
    marker_len = len(pub._marker())
    assert rate * 2 >= marker_len
    content_cap = cap - marker_len
    (cursor_dir / "b0.logpos").write_text(str(content_cap), encoding="utf-8")
    # drain the bucket down to ~10 bytes (< marker) with a second execution
    drain = workdir / "a0.log"
    drain.write_bytes(b"d" * (rate * 2 - 10))
    store.create_reserved(task_id="e1", execution_id="a0", project="demo", spider="s")
    store.promote_started("a0", scrapyd_job_id="job-a0", log_path=str(drain))

    async def _tick(dt: float) -> int:
        before = len(await fake.entries(LOG_STREAM))
        clock["t"] += dt
        await pub.publish_once()
        return sum(e.size_bytes for e in (await _log_events(fake))[before:])

    landed = await _tick(1.0)                     # a0 drains; b0 sees 10 B < marker
    assert landed == rate * 2 - 10 <= rate * 2
    assert store.read("b0").log_capped is False
    landed = await _tick(0.1)                     # +12.8 B -> still < marker: wait
    assert landed == 0 and store.read("b0").log_capped is False
    landed = await _tick(1.0)                     # enough now -> marker lands
    assert landed == marker_len <= rate * 2
    assert store.read("b0").log_capped is True
    markers = [
        e for e in await _log_events(fake)
        if b"[dopilot:log-truncated" in base64.b64decode(e.content_b64)
    ]
    assert len(markers) == 1 and markers[0].size_bytes == marker_len
