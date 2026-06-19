"""Agent log-publisher tests (phase 1.5)."""

from __future__ import annotations

import base64
from pathlib import Path

from dopilot_agent.deps import state_dir
from dopilot_agent.redis.logs import LogPublisher
from dopilot_agent.state.store import StateStore
from dopilot_protocol import LOG_STREAM, AgentLogEvent, from_stream_entry

AGENT_ID = "agent-x"


def _started(workdir: Path, log_path: Path) -> StateStore:
    store = StateStore(state_dir(workdir))
    store.create_reserved(execution_id="e1", attempt_id="a1", project="demo", spider="phase1")
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
