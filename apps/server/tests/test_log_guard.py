"""Log-flood guard (server): size cap + dir budget + gauge + stream guard + sent reconcile.

TC-10 / TC-11 / TC-11b / TC-11c / TC-12 / TC-20e.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dopilot_protocol import LOG_STREAM, command_stream
from dopilot_server.config.settings import RedisSettings
from dopilot_server.logs.dir_gauge import LogsDirGauge, walk_size
from dopilot_server.models.command_outbox import OUTBOX_PENDING, OUTBOX_SENT, CommandOutbox
from dopilot_server.models.notification import (
    TYPE_LOG_TRUNCATED,
    TYPE_REDIS_STREAM_OVER_BUDGET,
    TYPE_SENT_COMMANDS_REQUEUED,
    Notification,
)
from dopilot_server.redis.commands import CommandProducer
from dopilot_server.redis.dispatcher import CommandDispatcher
from dopilot_server.redis.stream_guard import StreamGuardLoop
from dopilot_server.services import states
from dopilot_server.services.logs import (
    OUTCOME_APPENDED,
    OUTCOME_TRUNCATED,
    OUTCOME_TRUNCATED_DROPPED,
    TRUNCATION_DIR_BUDGET,
    TRUNCATION_SIZE_CAP,
    apply_log_event,
)
from sqlalchemy import select

from .conftest import make_settings
from .test_dispatcher import _seed_run
from .test_log_consumer import _log_event, _reload_lf, _seed


async def _notifications(session, type_: str) -> list[Notification]:
    return list(
        (await session.execute(select(Notification).where(Notification.type == type_)))
        .scalars().all()
    )


async def _stop_logs_rows(session, execution_id: str) -> list[CommandOutbox]:
    return list(
        (
            await session.execute(
                select(CommandOutbox).where(
                    CommandOutbox.execution_id == execution_id,
                    CommandOutbox.type == "stop_logs",
                )
            )
        ).scalars().all()
    )


def _marker(cap: int, reason: str) -> bytes:
    return f"\n[dopilot:log-truncated max_bytes={cap} reason={reason}]\n".encode()


# --- TC-10: per-file size cap -> marker, stop_logs once, notification, gauge ---------


async def test_size_cap_truncates_once_with_backpressure(db_session, exec_settings):
    exec_settings.logs.max_file_bytes = 1024
    gauge = LogsDirGauge(exec_settings.logs.root_dir, budget=0)
    _t, execution, lf = await _seed(db_session, exec_settings)

    out = await apply_log_event(
        db_session, exec_settings, _log_event(execution, 0, b"a" * 2048), gauge=gauge
    )
    await db_session.commit()
    assert out == OUTCOME_TRUNCATED
    lf = await _reload_lf(db_session, lf)
    body = Path(lf.storage_path).read_bytes()
    assert body == b"a" * 1024 + _marker(1024, TRUNCATION_SIZE_CAP)
    assert lf.log_integrity == "truncated" and lf.truncation_reason == TRUNCATION_SIZE_CAP
    assert lf.size_bytes == len(body) and lf.last_pulled_offset == 2048
    assert gauge.value == len(body)  # gauge == actual bytes written (prefix + marker)
    assert len(await _stop_logs_rows(db_session, execution.id)) == 1
    notes = await _notifications(db_session, TYPE_LOG_TRUNCATED)
    assert len(notes) == 1 and notes[0].payload["reason"] == TRUNCATION_SIZE_CAP

    # Second increment: dropped, no new stop_logs, notification count unchanged
    out = await apply_log_event(
        db_session, exec_settings, _log_event(execution, 2048, b"b" * 1024), gauge=gauge
    )
    await db_session.commit()
    assert out == OUTCOME_TRUNCATED_DROPPED
    assert len(await _stop_logs_rows(db_session, execution.id)) == 1
    assert Path(lf.storage_path).read_bytes() == body
    assert gauge.value == len(body)


# --- TC-11: logs-dir budget is an admission hard limit ---------------------------------


async def test_dir_budget_admission_hard_limit(db_session, exec_settings):
    exec_settings.logs.max_file_bytes = 0
    exec_settings.logs.max_total_bytes = 3000
    root = Path(exec_settings.logs.root_dir)
    gauge = LogsDirGauge(root, budget=3000)
    # (a) gauge at 2500 (all "active" logs): body does not fit, marker does
    filler = root / "filler.bin"
    root.mkdir(parents=True, exist_ok=True)
    filler.write_bytes(b"f" * 2500)
    await gauge.calibrate()
    assert gauge.value == 2500
    _t, execution, lf = await _seed(db_session, exec_settings)
    out = await apply_log_event(
        db_session, exec_settings, _log_event(execution, 0, b"x" * 1024), gauge=gauge
    )
    await db_session.commit()
    assert out == OUTCOME_TRUNCATED
    lf = await _reload_lf(db_session, lf)
    assert Path(lf.storage_path).read_bytes() == _marker(3000, TRUNCATION_DIR_BUDGET)
    assert lf.log_integrity == "truncated" and lf.truncation_reason == TRUNCATION_DIR_BUDGET
    assert gauge.value == walk_size(root) <= 3000
    assert len(await _stop_logs_rows(db_session, execution.id)) == 1
    out = await apply_log_event(
        db_session, exec_settings, _log_event(execution, 1024, b"y" * 1024), gauge=gauge
    )
    assert out == OUTCOME_TRUNCATED_DROPPED

    # (b) gauge at 2990: not even a marker fits -> five executions write NOTHING
    filler.write_bytes(b"f" * 2990)
    for p in root.rglob("*.log"):
        p.unlink()
    await gauge.calibrate()
    assert gauge.value == 2990
    execs = [await _seed(db_session, exec_settings) for _ in range(5)]
    for _t, execution, _lf in execs:
        out = await apply_log_event(
            db_session, exec_settings, _log_event(execution, 0, b"z" * 1024), gauge=gauge
        )
        assert out == OUTCOME_TRUNCATED
    await db_session.commit()
    assert walk_size(root) == 2990
    assert gauge.value == 2990
    for _t, execution, lf in execs:
        lf = await _reload_lf(db_session, lf)
        assert lf.log_integrity == "truncated" and lf.truncation_reason == TRUNCATION_DIR_BUDGET
        assert not Path(lf.storage_path).exists()
        assert len(await _stop_logs_rows(db_session, execution.id)) == 1
    notes = await _notifications(db_session, TYPE_LOG_TRUNCATED)
    assert len(notes) == 6  # one per execution (dedupe per execution)

    # (c) budget 0 -> normal append
    exec_settings.logs.max_total_bytes = 0
    free = LogsDirGauge(root, budget=0)
    _t, execution, lf = await _seed(db_session, exec_settings)
    out = await apply_log_event(
        db_session, exec_settings, _log_event(execution, 0, b"n" * 1024), gauge=free
    )
    assert out == OUTCOME_APPENDED
    lf = await _reload_lf(db_session, lf)
    assert Path(lf.storage_path).stat().st_size == 1024


# --- TC-11b / TC-11c: the gauge serialises writes, truncation and calibration ----------


async def test_gauge_serialises_write_truncate_and_calibrate(tmp_path, monkeypatch):
    import dopilot_server.logs.dir_gauge as gauge_mod

    root = tmp_path / "logs"
    root.mkdir()
    big = root / "a.log"
    big.write_bytes(b"a" * 6000)
    gauge = LogsDirGauge(root, budget=10000)

    walk_started = asyncio.Event()
    release_walk = asyncio.Event()
    real_walk = gauge_mod.walk_size

    def slow_walk(path):
        walk_started.set()
        # block the worker thread until the test releases it
        while not release_walk.is_set():
            pass
        return real_walk(path)

    monkeypatch.setattr(gauge_mod, "walk_size", slow_walk)
    timeline: list[tuple[str, float]] = []
    loop = asyncio.get_running_loop()

    async def writer_3000() -> None:
        async with gauge.writer():
            timeline.append(("write-enter", loop.time()))
            p = root / "b.log"
            p.write_bytes(b"b" * 3000)
            gauge.add(3000)

    async def truncate_1000() -> None:
        async with gauge.writer():
            timeline.append(("truncate-enter", loop.time()))
            with big.open("r+b") as fh:
                fh.truncate(5000)
            gauge.sub(1000)

    cal = asyncio.create_task(gauge.calibrate())
    await walk_started.wait()
    w = asyncio.create_task(writer_3000())
    t = asyncio.create_task(truncate_1000())
    await asyncio.sleep(0.05)
    assert timeline == []  # both blocked behind the calibration lock
    t_release = loop.time()
    release_walk.set()
    await asyncio.gather(cal, w, t)
    assert all(ts >= t_release for _n, ts in timeline)
    assert gauge.value == 8000 == walk_size(root)
    assert not gauge.fits(2001) and gauge.fits(2000)

    # TC-11c: a physical truncate already done but not yet settled can never be
    # observed by calibration — both happen inside one critical section.
    monkeypatch.setattr(gauge_mod, "walk_size", real_walk)
    entered = asyncio.Event()
    go = asyncio.Event()

    async def truncate_then_settle() -> None:
        async with gauge.writer():
            with big.open("r+b") as fh:
                fh.truncate(4000)
            entered.set()
            await go.wait()
            gauge.sub(1000)

    t2 = asyncio.create_task(truncate_then_settle())
    await entered.wait()
    cal2 = asyncio.create_task(gauge.calibrate())
    await asyncio.sleep(0.05)
    assert not cal2.done()  # calibrate blocks until the truncation settles
    go.set()
    await asyncio.gather(t2, cal2)
    assert gauge.value == 7000 == walk_size(root)

    # partial write then exception: value follows the physical bytes
    from dopilot_server.services.logs import _write_settled

    class Boom(Exception):
        pass

    p = root / "c.log"
    # simulate a write that lands 700 bytes then raises at flush/close
    class PartialFile:
        def __init__(self, path):
            self._fh = open(path, "ab")

        def write(self, data):
            self._fh.write(data[:700])
            self._fh.flush()
            raise Boom()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()
            return False

    import builtins

    real_open = builtins.open
    def patched_open(path, mode="r", *a, **k):
        return PartialFile(path) if "a" in mode else real_open(path, mode, *a, **k)

    monkeypatch.setattr("dopilot_server.services.logs.open", patched_open, raising=False)
    before = gauge.value
    try:
        _write_settled(str(p), b"c" * 2000, gauge)
    except Boom:
        pass
    assert gauge.value == before + 700 == walk_size(root)


# --- TC-12: stream guard converges, notifies, and clears when it cannot ---------------


def _guard(fake, settings, sessionmaker=None, **kw) -> StreamGuardLoop:
    return StreamGuardLoop(
        fake, settings, sessionmaker, stream=LOG_STREAM, interval_seconds=0,
        now=lambda: datetime(2026, 8, 21, 12, 0, tzinfo=UTC), **kw,
    )


async def _fill(fake, count: int, size: int) -> None:
    for _ in range(count):
        await fake.xadd(LOG_STREAM, {b"data": b"x" * size})


async def test_stream_guard_uniform_converges(fake_redis, test_sessionmaker, db_session):
    fake = fake_redis()
    settings = make_settings()
    settings.redis.stream_max_bytes_logs = 200 * 1024
    await _fill(fake, 300, 2048)
    guard = _guard(fake, settings, test_sessionmaker)
    res = await guard.enforce_once()
    usage, length = await guard.measure()
    assert res["trimmed"] > 0 and res["cleared"] is False and res["iterations"] <= 8
    assert usage <= settings.redis.stream_max_bytes_logs and length > 0
    notes = await _notifications(db_session, TYPE_REDIS_STREAM_OVER_BUDGET)
    assert len(notes) == 1 and notes[0].severity == "warning" and notes[0].count == 1
    # under budget now: nothing trimmed, no new notification
    res2 = await guard.enforce_once()
    assert res2["trimmed"] == 0
    db_session.expire_all()
    notes = await _notifications(db_session, TYPE_REDIS_STREAM_OVER_BUDGET)
    assert len(notes) == 1 and notes[0].count == 1


async def test_stream_guard_uneven_entries_converge(fake_redis, test_sessionmaker):
    fake = fake_redis()
    settings = make_settings()
    settings.redis.stream_max_bytes_logs = 300 * 1024
    await _fill(fake, 5, 200 * 1024)
    await _fill(fake, 500, 1024)
    guard = _guard(fake, settings, test_sessionmaker)
    res = await guard.enforce_once()
    usage, _length = await guard.measure()
    assert usage <= settings.redis.stream_max_bytes_logs
    assert res["cleared"] is False and res["trimmed"] > 0


async def test_stream_guard_clears_when_it_cannot_converge(
    fake_redis, test_sessionmaker, db_session
):
    fake = fake_redis()
    settings = make_settings()
    settings.redis.stream_max_bytes_logs = 100 * 1024
    await _fill(fake, 100, 4096)
    fake.memory_usage_override = 10 * 1024 * 1024  # usage "never" drops
    guard = _guard(fake, settings, test_sessionmaker)
    res = await guard.enforce_once()
    assert res["cleared"] is True
    assert await fake.xlen(LOG_STREAM) == 0
    notes = await _notifications(db_session, TYPE_REDIS_STREAM_OVER_BUDGET)
    assert len(notes) == 1 and notes[0].severity == "error"
    assert notes[0].payload["cleared"] is True and notes[0].dedupe_key.startswith("cleared:")


async def test_stream_guard_budget_zero_is_off(fake_redis):
    fake = fake_redis()
    settings = make_settings()
    settings.redis.stream_max_bytes_logs = 0
    await _fill(fake, 50, 4096)
    res = await _guard(fake, settings).enforce_once()
    assert res["trimmed"] == 0 and await fake.xlen(LOG_STREAM) == 50


# --- TC-20e: sent reconcile ------------------------------------------------------------


async def test_sent_reconcile_requeues_vanished_commands(
    db_session, fake_redis, test_sessionmaker
):
    fake = fake_redis()
    settings = make_settings()
    settings.redis.sent_reconcile_interval_seconds = 300
    settings.redis.sent_reconcile_min_age_seconds = 60
    clock = {"t": 1000.0}
    dispatcher = CommandDispatcher(
        test_sessionmaker, CommandProducer(fake, RedisSettings()),
        settings=settings, clock=lambda: clock["t"],
    )
    old = datetime.now(UTC) - timedelta(seconds=120)
    fresh = datetime.now(UTC)

    async def sent_row(*, agent, updated_at, task_status=states.TASK_QUEUED):
        task, execution, row = await _seed_run(
            db_session, agent_id=agent, task_status=task_status, manual=False
        )
        cmd = dispatcher._build_command(row)
        from dopilot_protocol import to_stream_entry

        msg_id = await fake.xadd(command_stream(agent), to_stream_entry(cmd))
        row.status = OUTBOX_SENT
        row.redis_msg_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
        row.updated_at = updated_at
        await db_session.commit()
        return row

    a = await sent_row(agent="agent-a", updated_at=old)               # still in stream
    b = await sent_row(agent="agent-b", updated_at=old)               # stream wiped, old
    c = await sent_row(agent="agent-c", updated_at=fresh)             # stream wiped, too new
    d = await sent_row(agent="agent-d", updated_at=old, task_status=states.TASK_COMPLETE)
    for agent in ("agent-b", "agent-c", "agent-d"):
        await fake.delete(command_stream(agent))

    requeued = await dispatcher.reconcile_sent_once(db_session)
    await db_session.commit()
    ids = {k: r.command_id for k, r in (("a", a), ("b", b), ("c", c), ("d", d))}
    assert requeued == [ids["b"]]
    db_session.expire_all()
    expectations = (
        ("a", OUTBOX_SENT), ("b", OUTBOX_PENDING), ("c", OUTBOX_SENT), ("d", OUTBOX_SENT),
    )
    for key, expected in expectations:
        row = await db_session.get(CommandOutbox, ids[key])
        assert row.status == expected, key
    notes = await _notifications(db_session, TYPE_SENT_COMMANDS_REQUEUED)
    assert len(notes) == 1 and notes[0].payload["count"] == 1

    # next dispatch tick re-XADDs b with a new message id
    await dispatcher._tick()
    db_session.expire_all()
    b2 = await db_session.get(CommandOutbox, ids["b"])
    assert b2.status == OUTBOX_SENT and b2.redis_msg_id
    assert len(await fake.entries(command_stream("agent-b"))) == 1

    # c becomes old enough later -> requeued on a later pass
    c_row = await db_session.get(CommandOutbox, ids["c"])
    c_row.updated_at = old
    await db_session.commit()
    assert await dispatcher.reconcile_sent_once(db_session) == [ids["c"]]
    await db_session.commit()

    # (b) wiring: a dispatcher's FIRST tick reconciles immediately, then only
    # once per ``sent_reconcile_interval_seconds``.
    fresh_dispatcher = CommandDispatcher(
        test_sessionmaker, CommandProducer(fake, RedisSettings()),
        settings=settings, clock=lambda: clock["t"],
    )
    await fresh_dispatcher._tick()
    assert fresh_dispatcher.sent_reconcile_calls == 1
    clock["t"] += 100
    await fresh_dispatcher._tick()
    assert fresh_dispatcher.sent_reconcile_calls == 1
    clock["t"] += 250
    await fresh_dispatcher._tick()
    assert fresh_dispatcher.sent_reconcile_calls == 2
    # interval 0 / no settings -> never
    off = CommandDispatcher(test_sessionmaker, CommandProducer(fake, RedisSettings()))
    await off._tick()
    assert off.sent_reconcile_calls == 0


async def test_sent_reconcile_requeues_past_give_up_deadline(
    db_session, fake_redis, test_sessionmaker
):
    """R-02 (round 4): a vanished ``sent`` command whose ORIGINAL give-up
    deadline is long past (server down / Redis volume restored > 15 min later)
    is re-XADDed with a fresh window — never failed as ``dispatch_timeout`` by
    the same tick's ``_process_row``."""
    fake = fake_redis()
    settings = make_settings()
    settings.redis.sent_reconcile_interval_seconds = 300
    settings.redis.sent_reconcile_min_age_seconds = 60
    dispatcher = CommandDispatcher(
        test_sessionmaker, CommandProducer(fake, RedisSettings()), settings=settings,
    )
    task, execution, row = await _seed_run(
        db_session, agent_id="agent-z", task_status=states.TASK_QUEUED, manual=False
    )
    from dopilot_protocol import to_stream_entry

    msg_id = await fake.xadd(
        command_stream("agent-z"), to_stream_entry(dispatcher._build_command(row))
    )
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    row.status = OUTBOX_SENT
    row.redis_msg_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
    row.updated_at = long_ago
    row.give_up_at = long_ago + timedelta(minutes=15)   # expired ~2h45m ago
    row.expire_at = row.give_up_at
    row.retry_count = 3
    await db_session.commit()
    await fake.delete(command_stream("agent-z"))          # volume wiped
    command_id, task_id, execution_id = row.command_id, task.id, execution.id

    before = datetime.now(UTC)
    await dispatcher._tick()                              # reconcile + dispatch in ONE tick
    db_session.expire_all()
    row = await db_session.get(CommandOutbox, command_id)
    assert row.status == OUTBOX_SENT and row.redis_msg_id
    assert row.last_error == "sent_message_missing"
    assert row.retry_count == 0
    assert row.give_up_at.replace(tzinfo=UTC) >= before + timedelta(minutes=14)
    assert len(await fake.entries(command_stream("agent-z"))) == 1
    task = await db_session.get(type(task), task_id)
    execution = await db_session.get(type(execution), execution_id)
    assert task.status == states.TASK_QUEUED and execution.status == states.EXEC_PENDING
