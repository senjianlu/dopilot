"""Resource hard-limits tests (server side): task-resource-hard-limits.

Covers TC-01..07, TC-13 (server env/TOML loader), TC-18 from the plan. Each test
docstring names its TC id.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dopilot_protocol import (
    EVENT_STREAM,
    LOG_STREAM,
    AgentLogEvent,
    to_stream_entry,
)
from dopilot_server.artifacts.upload import (
    _in_flight,
    release_quota,
    reserve_quota,
    stream_to_staging,
)
from dopilot_server.errors import ApiError
from dopilot_server.logs.sse import CLOSE, SubscriptionManager
from dopilot_server.models.event_audit import EventAudit
from dopilot_server.models.execution import (
    BuildArtifact,
    Execution,
    ExecutionLogFile,
    Task,
)
from dopilot_server.redis.reconcile import finalize_drained_logs
from dopilot_server.services import maintenance as maint
from dopilot_server.services import states
from dopilot_server.services.executions import new_id
from dopilot_server.services.logs import (
    INTEGRITY_TRUNCATED,
    OUTCOME_TRUNCATED,
    OUTCOME_TRUNCATED_DROPPED,
    apply_log_event,
)
from sqlalchemy import func, select


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def _seed(session, settings, *, agent_id="agent-1"):
    from dopilot_server.services import executions as svc

    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:caps",
        status=states.TASK_RUNNING, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id=agent_id,
        status=states.EXEC_RUNNING, error_detail={},
    )
    session.add(execution)
    log_file = svc.create_log_file(session, settings, task, execution)
    await session.commit()
    return task, execution, log_file


def _event(execution, offset, content: bytes):
    return AgentLogEvent(
        agent_id=execution.agent_id,
        task_id=execution.task_id,
        execution_id=execution.id,
        offset=offset,
        content_b64=base64.b64encode(content).decode("ascii"),
        size_bytes=len(content),
        eof=False,
        created_at=datetime.now(UTC).isoformat(),
    )


async def _reload(session, lf):
    return (
        await session.execute(
            select(ExecutionLogFile).where(
                ExecutionLogFile.task_id == lf.task_id,
                ExecutionLogFile.execution_id == lf.execution_id,
                ExecutionLogFile.stream == lf.stream,
            )
        )
    ).scalar_one()


# --------------------------------------------------------------------------
# TC-01 / TC-02 — per-execution log-file size cap + truncated sticky
# --------------------------------------------------------------------------
async def test_tc01_log_file_size_cap_truncates_and_keeps_consuming(
    db_session, exec_settings
):
    """TC-01: past max_file_bytes the file stops growing (+ one marker), the row
    is log_integrity=truncated, and further increments are still consumed."""
    exec_settings.logs.max_file_bytes = 64
    _t, execution, lf = await _seed(db_session, exec_settings)

    # First increment (under the cap) appends normally.
    out = await apply_log_event(db_session, exec_settings, _event(execution, 0, b"a" * 40))
    await db_session.commit()
    assert out != OUTCOME_TRUNCATED

    # Second increment crosses the cap -> truncated now.
    out = await apply_log_event(db_session, exec_settings, _event(execution, 40, b"b" * 100))
    await db_session.commit()
    assert out == OUTCOME_TRUNCATED
    lf = await _reload(db_session, lf)
    assert lf.log_integrity == INTEGRITY_TRUNCATED

    body = Path(lf.storage_path).read_bytes()
    # file body is bounded to cap + exactly one truncation marker line.
    assert body.count(b"dopilot:log-truncated") == 1
    assert len(body) <= 64 + 64  # cap + marker slack

    # A THIRD increment after truncation: dropped body but still "consumed"
    # (the consumer would ACK), and the marker stays a single line.
    out = await apply_log_event(db_session, exec_settings, _event(execution, 140, b"c" * 50))
    await db_session.commit()
    assert out == OUTCOME_TRUNCATED_DROPPED
    lf = await _reload(db_session, lf)
    assert lf.last_pulled_offset == 190  # cursor advanced by full agent range
    body2 = Path(lf.storage_path).read_bytes()
    assert body2 == body  # no more bytes written
    assert body2.count(b"dopilot:log-truncated") == 1


async def test_tc01_consumer_keeps_acking_past_the_cap(
    db_session, exec_settings, fake_redis, test_sessionmaker
):
    """TC-01 (consume path): the real LogConsumer drains + ACKs every log event
    past the size cap — the stream is never stalled by truncation."""
    from dopilot_server.redis.consumers import LogConsumer

    exec_settings.logs.max_file_bytes = 64
    _t, execution, lf = await _seed(db_session, exec_settings)
    fake = fake_redis()
    consumer = LogConsumer(
        test_sessionmaker, fake, exec_settings, SubscriptionManager()
    )
    await consumer.setup()

    # Publish increments whose total (200 bytes) far exceeds the 64-byte cap.
    offset = 0
    for _ in range(10):
        await fake.xadd(
            LOG_STREAM, to_stream_entry(_event(execution, offset, b"z" * 20))
        )
        offset += 20
    n = await consumer.drain_once()
    assert n == 10  # every event consumed, none stalled by the cap

    # All ACKed: no pending entries remain in the group.
    from dopilot_protocol import LOG_GROUP

    assert await fake.pending_count(LOG_STREAM, LOG_GROUP) == 0
    async with test_sessionmaker() as s:
        row = (
            await s.execute(
                select(ExecutionLogFile).where(
                    ExecutionLogFile.task_id == lf.task_id,
                    ExecutionLogFile.execution_id == lf.execution_id,
                )
            )
        ).scalar_one()
        assert row.log_integrity == INTEGRITY_TRUNCATED
        assert row.last_pulled_offset == 200  # cursor advanced through all events


async def test_tc02_truncated_sticky_through_finalize(db_session, exec_settings):
    """TC-02: a truncated log stays truncated when the execution finalizes; the
    execution still converges to its terminal lifecycle state."""
    exec_settings.logs.max_file_bytes = 32
    task, execution, lf = await _seed(db_session, exec_settings)
    await apply_log_event(db_session, exec_settings, _event(execution, 0, b"x" * 100))
    await db_session.commit()
    lf = await _reload(db_session, lf)
    assert lf.log_integrity == INTEGRITY_TRUNCATED

    # Drive the drain finalize: execution terminal + finished well in the past.
    execution.status = states.EXEC_FINISHED
    execution.finished_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    count = await finalize_drained_logs(db_session, exec_settings)
    await db_session.commit()
    assert count == 1
    lf = await _reload(db_session, lf)
    assert lf.status == states.LOG_COMPLETE      # lifecycle converged
    assert lf.log_integrity == INTEGRITY_TRUNCATED  # completeness stays truncated
    assert lf.retained_until is not None          # retention deadline stamped


# --------------------------------------------------------------------------
# TC-03 — automatic retention sweep + failure-safe two-phase
# --------------------------------------------------------------------------
async def _seed_terminal_task(session, settings, *, finished_delta_days: int):
    from dopilot_server.services import executions as svc

    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:old",
        status=states.TASK_COMPLETE, params={},
        finished_at=datetime.now(UTC) - timedelta(days=finished_delta_days),
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id="agent-1",
        status=states.EXEC_FINISHED, error_detail={},
    )
    session.add(execution)
    lf = svc.create_log_file(session, settings, task, execution)
    # A terminal task past its drain window has SEALED logs (finalize_drained_logs
    # / the outcome recorder); retention only ever touches sealed files
    # (log-flood guard single-writer invariant).
    lf.status = states.LOG_COMPLETE
    lf.final_offset = 0
    await session.commit()
    Path(lf.storage_path).parent.mkdir(parents=True, exist_ok=True)
    Path(lf.storage_path).write_bytes(b"log body\n")
    return task, execution, lf


async def test_tc03_retention_sweep_deletes_old_terminal_only(
    db_session, exec_settings
):
    """TC-03 (happy path): terminal data older than the cutoff is deleted; newer
    terminal data is kept."""
    old_task, _e1, old_lf = await _seed_terminal_task(
        db_session, exec_settings, finished_delta_days=40
    )
    new_task, _e2, new_lf = await _seed_terminal_task(
        db_session, exec_settings, finished_delta_days=1
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    summary = await maint.cleanup_terminal_data(
        db_session, exec_settings, cutoff=cutoff
    )
    assert summary.tasks == 1
    assert not Path(old_lf.storage_path).exists()
    assert Path(new_lf.storage_path).exists()
    remaining = (await db_session.execute(select(Task.id))).scalars().all()
    assert old_task.id not in remaining
    assert new_task.id in remaining


async def test_tc03_retention_sweep_unlink_failure_retries_next_sweep(
    db_session, exec_settings, monkeypatch
):
    """TC-03 (fault path): when a body unlink fails, its row/task are NOT deleted
    (never orphan the file); the row stays expired and the body stays on disk, and
    the next sweep (unlink restored) deletes both. Invariant: an index is deleted
    only after its body is gone."""
    task, _e, lf = await _seed_terminal_task(
        db_session, exec_settings, finished_delta_days=40
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)

    async def boom(_path):
        raise OSError("injected unlink failure")

    monkeypatch.setattr(maint.files, "aremove", boom)
    await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)

    # Failed unlink -> row kept as expired, task kept, body still present.
    row = (
        await db_session.execute(
            select(ExecutionLogFile.status).where(
                ExecutionLogFile.task_id == lf.task_id,
                ExecutionLogFile.execution_id == lf.execution_id,
            )
        )
    ).one_or_none()
    assert row is not None and row[0] == states.LOG_EXPIRED  # no orphan file
    assert Path(lf.storage_path).exists()
    assert task.id in (await db_session.execute(select(Task.id))).scalars().all()

    # Next sweep with unlink working: body removed, rows + task deleted.
    monkeypatch.undo()
    await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)
    assert not Path(lf.storage_path).exists()
    left = (
        await db_session.execute(
            select(func.count()).select_from(ExecutionLogFile)
        )
    ).scalar_one()
    assert left == 0
    assert task.id not in (await db_session.execute(select(Task.id))).scalars().all()


async def test_tc03_retention_sweep_commit_failure_no_dangling_and_retries(
    db_session, exec_settings, monkeypatch
):
    """TC-03 (genuine commit-fault path): the STEP-3 commit itself raises; STEP 1
    (mark expired) already committed, so there is never an unmarked dangling
    index, and the next sweep completes the deletion."""
    from sqlalchemy.ext.asyncio import AsyncSession

    task, _e, lf = await _seed_terminal_task(
        db_session, exec_settings, finished_delta_days=40
    )
    # Capture ids as plain strings up front — after the fault+rollback the ORM
    # objects are expired, and touching their attributes would trigger a lazy
    # load that fails outside a transaction; column selects avoid that.
    task_id, lf_task_id, lf_exec_id = task.id, lf.task_id, lf.execution_id
    cutoff = datetime.now(UTC) - timedelta(days=30)

    orig_commit = AsyncSession.commit
    calls = {"n": 0}

    async def flaky_commit(self):
        calls["n"] += 1
        if calls["n"] == 2:  # STEP 3 commit: fail after the tx is discarded.
            await AsyncSession.rollback(self)
            raise RuntimeError("injected commit failure")
        return await orig_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", flaky_commit)
    with pytest.raises(RuntimeError):
        await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)
    monkeypatch.undo()

    # STEP 1 committed -> the log row is expired (auditable), never a live dangling
    # index. Query columns (no ORM attribute access on the expired objects).
    status = (
        await db_session.execute(
            select(ExecutionLogFile.status).where(
                ExecutionLogFile.task_id == lf_task_id,
                ExecutionLogFile.execution_id == lf_exec_id,
            )
        )
    ).scalar_one_or_none()
    assert status == states.LOG_EXPIRED

    # Next sweep (commit healthy) converges: rows + task deleted.
    await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)
    assert (
        await db_session.execute(select(func.count()).select_from(ExecutionLogFile))
    ).scalar_one() == 0
    assert task_id not in (await db_session.execute(select(Task.id))).scalars().all()


async def test_tc03_retention_sweep_step3_failure_no_dangling_and_retries(
    db_session, exec_settings, monkeypatch
):
    """TC-03 (STEP-3 fault path, incl. commit): a failure during STEP 3 (row
    delete OR its commit) leaves the log row marked expired (STEP 1 already
    committed) — never an unmarked dangling index — and the next sweep completes
    the deletion.

    Injecting the fault at the STEP-3 delete is equivalent to a commit-phase
    failure for this invariant: in both cases STEP 3 does not persist while STEP 1
    did. A true driver-level commit fault cannot be simulated on the in-memory
    aiosqlite StaticPool without corrupting the shared connection, so the fault is
    injected at the delete statement, which exercises the same failure-safe path.
    """
    task, _e, lf = await _seed_terminal_task(
        db_session, exec_settings, finished_delta_days=40
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)

    def boom_delete(*_a, **_k):
        raise RuntimeError("injected SQL delete failure")

    monkeypatch.setattr(maint, "delete", boom_delete)
    with pytest.raises(RuntimeError):
        await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)
    await db_session.rollback()

    row = (
        await db_session.execute(
            select(ExecutionLogFile.status).where(
                ExecutionLogFile.task_id == lf.task_id,
                ExecutionLogFile.execution_id == lf.execution_id,
            )
        )
    ).one_or_none()
    assert row is not None and row[0] == states.LOG_EXPIRED

    monkeypatch.undo()
    await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)
    assert (
        await db_session.execute(select(func.count()).select_from(ExecutionLogFile))
    ).scalar_one() == 0
    assert task.id not in (await db_session.execute(select(Task.id))).scalars().all()


# --------------------------------------------------------------------------
# TC-04 — event_audit batch prune
# --------------------------------------------------------------------------
async def test_tc04_event_audit_batch_prune(db_session, exec_settings):
    """TC-04: event_audit rows older than the window are deleted in bounded
    batches; newer rows are kept."""
    exec_settings.maintenance.event_audit_retention_days = 30
    exec_settings.maintenance.event_audit_delete_batch = 5
    now = datetime.now(UTC)
    for i in range(12):  # >1 batch of old rows
        db_session.add(EventAudit(
            stream=EVENT_STREAM, redis_msg_id=f"old-{i}", execution_id=new_id(),
            event_type="finished", outcome="applied",
            processed_at=now - timedelta(days=40),
        ))
    for i in range(3):
        db_session.add(EventAudit(
            stream=EVENT_STREAM, redis_msg_id=f"new-{i}", execution_id=new_id(),
            event_type="finished", outcome="applied",
            processed_at=now - timedelta(days=1),
        ))
    await db_session.commit()

    deleted = await maint.prune_event_audit(db_session, exec_settings, now=now)
    assert deleted == 12
    left = (
        await db_session.execute(select(func.count()).select_from(EventAudit))
    ).scalar_one()
    assert left == 3


# --------------------------------------------------------------------------
# TC-05 — Redis stream time-trim (XTRIM MINID)
# --------------------------------------------------------------------------
class _StubRedis:
    def __init__(self):
        self.calls = []

    async def xtrim(self, stream, *, minid=None, maxlen=None, approximate=True):
        self.calls.append((stream, minid, approximate))
        return 0


async def test_tc05_trim_log_streams_xtrim_minid(exec_settings):
    """TC-05: the sweep calls XTRIM MINID on the log + event streams with the
    correct millisecond minid (now - log_retention_seconds)."""
    exec_settings.redis.log_retention_seconds = 3600
    now = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)
    stub = _StubRedis()
    await maint.trim_log_streams(stub, exec_settings, now=now)
    expected_minid = int((now.timestamp() - 3600) * 1000)
    streams = {s: minid for (s, minid, _a) in stub.calls}
    assert streams[LOG_STREAM] == expected_minid
    assert streams[EVENT_STREAM] == expected_minid

    # retention 0 disables the time trim.
    exec_settings.redis.log_retention_seconds = 0
    stub2 = _StubRedis()
    await maint.trim_log_streams(stub2, exec_settings, now=now)
    assert stub2.calls == []


# --------------------------------------------------------------------------
# TC-06 — chunked upload + 413 cap
# --------------------------------------------------------------------------
class _FakeUpload:
    """UploadFile double whose read REQUIRES a bounded size (a full read raises),
    so the test proves the endpoint streams in chunks."""

    def __init__(self, data: bytes, filename: str = "pkg.whl"):
        self._buf = data
        self._pos = 0
        self.filename = filename
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        assert size is not None and size >= 0, "chunked read required (no full read)"
        self.read_sizes.append(size)
        chunk = self._buf[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def _staging(root: str) -> Path:
    return Path(root) / "staging"


async def test_tc06_stream_upload_413_over_cap_no_residue(tmp_path):
    """TC-06: an upload over max_upload_bytes raises 413, reads in chunks, and
    leaves no residual file in staging."""
    root = str(tmp_path)
    big = _FakeUpload(b"x" * (5 * 1024 * 1024 + 1))  # > 5 MiB cap
    with pytest.raises(ApiError) as exc:
        await stream_to_staging(big, root, max_upload_bytes=5 * 1024 * 1024)
    assert exc.value.status_code == 413
    assert len(big.read_sizes) > 1  # streamed, not one full read
    assert list(_staging(root).glob("*.tmp")) == []


async def test_tc06_stream_upload_under_cap_ok(tmp_path):
    """TC-06 (companion): a small upload streams to a temp file with correct
    size + sha and is chunk-read."""
    import hashlib

    root = str(tmp_path)
    data = b"hello wheel bytes"
    up = _FakeUpload(data)
    tmp, size, sha = await stream_to_staging(up, root, max_upload_bytes=1024)
    assert size == len(data)
    assert sha == hashlib.sha256(data).hexdigest()
    assert Path(tmp).read_bytes() == data
    assert up.read_sizes and all(s > 0 for s in up.read_sizes)


# --------------------------------------------------------------------------
# TC-06 (endpoint) — streamed upload through the real egg/wheel endpoints
# --------------------------------------------------------------------------
def _egg_bytes(marker: str = "phase1") -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo-1.0.0.egg-info/PKG-INFO", "Name: demo\nVersion: 1.0.0\n")
        zf.writestr(
            "demo/spiders/s.py",
            f"import scrapy\nclass S(scrapy.Spider):\n    name = {marker!r}\n",
        )
    return buf.getvalue()


def _wheel_bytes(marker: str = "1.0.0") -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"demo-{marker}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: demo\nVersion: {marker}\n",
        )
        zf.writestr("demo/__init__.py", "")
    return buf.getvalue()


def _staging_files(root: str) -> list[Path]:
    d = Path(root) / "staging"
    return list(d.glob("*")) if d.is_dir() else []


async def _artifact_count(session) -> int:
    return (
        await session.execute(select(func.count()).select_from(BuildArtifact))
    ).scalar_one()


async def test_tc06_endpoint_upload_success_and_failures_no_residue(
    exec_client, exec_settings, db_session
):
    """TC-06 (endpoint): a valid egg uploads via the real endpoint (streamed to
    staging -> save_from_path -> DB row); an invalid egg returns 400 with no DB
    row; an oversized upload returns 413. No staging temp files leak in any case."""
    root = exec_settings.artifacts.root_dir

    # 1) success -> 200 + one DB row + no residue.
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("demo.egg", _egg_bytes(), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 200, r.text
    assert await _artifact_count(db_session) == 1
    assert _staging_files(root) == []

    # 2) invalid (not a zip) -> 400, still exactly one row, no residue.
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("bad.egg", b"not a zip", "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 400, r.text
    assert await _artifact_count(db_session) == 1
    assert _staging_files(root) == []

    # 3) oversized -> 413, no new row, no residue.
    exec_settings.artifacts.max_upload_bytes = 32
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("big.egg", _egg_bytes("big"), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 413, r.text
    assert await _artifact_count(db_session) == 1
    assert _staging_files(root) == []


async def test_tc06_endpoint_wheel_upload_success_and_413(
    exec_client, exec_settings, db_session
):
    """TC-06 (wheel endpoint): a valid wheel uploads through the streamed
    endpoint (save_from_path -> DB row) with no staging residue; an oversized
    wheel returns 413 and creates no row."""
    root = exec_settings.artifacts.root_dir
    r = await exec_client.post(
        "/api/v1/artifacts/python_wheel/wheel",
        files={"file": ("demo-1.0.0-py3-none-any.whl", _wheel_bytes(),
                        "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()["artifact"]
    assert body["artifact_type"] == "python_wheel"
    assert await _artifact_count(db_session) == 1
    assert _staging_files(root) == []
    # download round-trips the published body.
    dl = await exec_client.get(
        f"/api/v1/artifacts/python_wheel/{body['content_hash']}/wheel"
    )
    assert dl.status_code == 200

    exec_settings.artifacts.max_upload_bytes = 16
    r = await exec_client.post(
        "/api/v1/artifacts/python_wheel/wheel",
        files={"file": ("demo-2.0.0-py3-none-any.whl", _wheel_bytes("2.0.0"),
                        "application/octet-stream")},
    )
    assert r.status_code == 413, r.text
    assert await _artifact_count(db_session) == 1
    assert _staging_files(root) == []


async def test_tc18_endpoint_quota_507_no_residue_and_total(
    exec_client, exec_settings, db_session
):
    """TC-18 (endpoint): once the stored total would exceed max_total_bytes a new
    distinct upload returns 507, leaves no staging/stored residue and no DB row,
    and the reported stored total matches the one accepted artifact."""
    from dopilot_server.services.artifacts import stored_total_bytes

    root = exec_settings.artifacts.root_dir
    exec_settings.artifacts.max_total_bytes = len(_egg_bytes()) + 10

    # First distinct egg fits.
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("a.egg", _egg_bytes("aaa"), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 200, r.text
    total_after_one = await stored_total_bytes(db_session)
    assert total_after_one == len(_egg_bytes("aaa"))

    # A second DISTINCT egg would exceed the aggregate quota -> 507.
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("b.egg", _egg_bytes("bbb"), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 507, r.text
    # No residue: staging empty, still one artifact, total unchanged, and the
    # rejected egg body was NOT left on disk (would bypass the quota otherwise).
    assert _staging_files(root) == []
    assert await _artifact_count(db_session) == 1
    assert await stored_total_bytes(db_session) == total_after_one
    scrapy_eggs = list((Path(root) / "scrapy").glob("*.egg"))
    assert len(scrapy_eggs) == 1


# --------------------------------------------------------------------------
# TC-18 (unit) — aggregate quota reservation + concurrency mutex
# --------------------------------------------------------------------------
def _artifact(size: int) -> BuildArtifact:
    return BuildArtifact(
        id=new_id(), artifact_type="scrapy", package_format="egg",
        name="demo", filename="demo.egg", content_hash=new_id(),
        size_bytes=size, artifact_metadata={},
    )


@pytest.fixture(autouse=True)
def _clear_inflight():
    _in_flight.clear()
    yield
    _in_flight.clear()


async def test_tc18_manifest_publish_failure_rolls_back_body(
    exec_client, exec_settings, db_session, monkeypatch
):
    """TC-18 (R-02): if the manifest replace fails AFTER the body was published,
    save_from_path self-rolls-back the body — no orphan egg, no staging residue,
    no DB row, so the aggregate quota can never be bypassed."""
    import dopilot_server.artifacts.scrapy_store as ss

    root = exec_settings.artifacts.root_dir
    real_replace = os.replace

    def flaky_replace(src, dst, *a, **k):
        if str(dst).endswith(".json"):  # the manifest publish step
            raise OSError("injected manifest replace failure")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(ss.os, "replace", flaky_replace)
    with pytest.raises(Exception):  # noqa: B017 - endpoint surfaces the OSError
        await exec_client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("m.egg", _egg_bytes("m"), "application/octet-stream")},
            data={"project": "demo"},
        )
    monkeypatch.undo()
    assert list((Path(root) / "scrapy").glob("*.egg")) == []   # body rolled back
    assert list((Path(root) / "scrapy").glob("*.json")) == []  # no manifest
    assert _staging_files(root) == []
    assert await _artifact_count(db_session) == 0


async def test_tc18_reupload_manifest_failure_keeps_existing_artifact(
    exec_client, exec_settings, db_session, monkeypatch
):
    """TC-18 (R-02): re-uploading an ALREADY-STORED sha and hitting a manifest
    replace failure must NOT delete the pre-existing artifact — the store rolls
    back only brand-new bytes. The original body, manifest and DB row stay usable."""
    import dopilot_server.artifacts.scrapy_store as ss

    root = exec_settings.artifacts.root_dir
    content = _egg_bytes("keepme")

    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("a.egg", content, "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 200, r.text
    sha = r.json()["artifact"]["content_hash"]
    egg_path = Path(root) / "scrapy" / f"{sha}.egg"
    json_path = Path(root) / "scrapy" / f"{sha}.json"
    assert egg_path.exists() and json_path.exists()

    # Re-upload identical content; force the manifest replace to fail.
    real_replace = os.replace

    def flaky_replace(src, dst, *a, **k):
        if str(dst).endswith(".json"):
            raise OSError("injected manifest replace failure")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(ss.os, "replace", flaky_replace)
    with pytest.raises(Exception):  # noqa: B017
        await exec_client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("b.egg", content, "application/octet-stream")},
            data={"project": "demo"},
        )
    monkeypatch.undo()
    # The pre-existing artifact survived (body + manifest + DB row + download).
    assert egg_path.exists()
    assert json_path.exists()
    assert await _artifact_count(db_session) == 1
    dl = await exec_client.get(f"/api/v1/artifacts/scrapy/{sha}/egg")
    assert dl.status_code == 200


async def test_tc18_same_sha_failure_keeps_committed_artifact(
    exec_client, exec_settings, db_session, monkeypatch
):
    """TC-18 (R-03): once a sha is committed, a second same-content upload that
    fails must NOT delete the already-committed body/row (already_stored guard
    under the per-sha publish lock)."""
    import dopilot_server.api.v1.artifacts as art_mod

    root = exec_settings.artifacts.root_dir
    content = _egg_bytes("shared")

    # First upload commits sha X.
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("a.egg", content, "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 200, r.text
    sha = r.json()["artifact"]["content_hash"]
    assert (Path(root) / "scrapy" / f"{sha}.egg").exists()

    # Second upload of the SAME content fails at upsert; because the body already
    # exists (already_stored=True), rollback must NOT delete the shared body.
    async def boom(*a, **k):
        raise RuntimeError("injected DB failure on same-sha re-upload")

    monkeypatch.setattr(art_mod.svc, "upsert_scrapy", boom)
    with pytest.raises(RuntimeError):
        await exec_client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("b.egg", content, "application/octet-stream")},
            data={"project": "demo"},
        )
    monkeypatch.undo()
    # The first upload's committed body + row survive.
    assert (Path(root) / "scrapy" / f"{sha}.egg").exists()
    assert await _artifact_count(db_session) == 1


async def test_tc18_endpoint_rollback_on_db_failure_no_orphan_body(
    exec_client, exec_settings, db_session, monkeypatch
):
    """TC-18 (R-04): if the DB upsert fails AFTER the body is published, the body
    is rolled back off disk so it is never left uncounted by the quota."""
    import dopilot_server.api.v1.artifacts as art_mod

    root = exec_settings.artifacts.root_dir

    async def boom(*a, **k):
        raise RuntimeError("injected DB failure after publish")

    monkeypatch.setattr(art_mod.svc, "upsert_scrapy", boom)
    with pytest.raises(RuntimeError):
        await exec_client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("x.egg", _egg_bytes("x"), "application/octet-stream")},
            data={"project": "demo"},
        )
    # Published body rolled back; nothing left on disk, no staging residue.
    assert list((Path(root) / "scrapy").glob("*.egg")) == []
    assert _staging_files(root) == []
    assert await _artifact_count(db_session) == 0


async def test_tc18_quota_507_at_boundary_and_concurrency(db_session):
    """TC-18: over-quota reservation raises 507; two concurrent reservations that
    together exceed the quota admit at most one; quota=0 disables."""
    db_session.add(_artifact(900))
    await db_session.commit()
    cap = 1000

    # 900 stored + 100 fits exactly.
    tok = await reserve_quota(
        db_session, size_bytes=100, max_total_bytes=cap, already_stored=False
    )
    assert tok is not None
    # A second concurrent 100 now exceeds (900 + 100 reserved + 100) -> 507.
    with pytest.raises(ApiError) as exc:
        await reserve_quota(
            db_session, size_bytes=100, max_total_bytes=cap, already_stored=False
        )
    assert exc.value.status_code == 507
    release_quota(tok)

    # After release, a single 100 fits again.
    tok2 = await reserve_quota(
        db_session, size_bytes=100, max_total_bytes=cap, already_stored=False
    )
    assert tok2 is not None
    release_quota(tok2)

    # already_stored (dedup) -> no new bytes -> no reservation, never 507.
    assert await reserve_quota(
        db_session, size_bytes=10_000, max_total_bytes=cap, already_stored=True
    ) is None
    # quota disabled (0) -> no reservation.
    assert await reserve_quota(
        db_session, size_bytes=10_000, max_total_bytes=0, already_stored=False
    ) is None


# --------------------------------------------------------------------------
# TC-07 — SSE bounded queue force-close
# --------------------------------------------------------------------------
async def test_tc07_sse_bounded_queue_force_closes_slow_subscriber():
    """TC-07: publishing past a full bounded queue force-closes the subscriber
    (queue drained + CLOSE pushed, unsubscribed); later publish/close are
    idempotent and never raise; the publisher never blocks."""
    mgr = SubscriptionManager(queue_maxsize=2)
    q = mgr.subscribe("exec-1")
    # Fill to maxsize, then overflow.
    mgr.publish("exec-1", {"type": "log", "end_offset": 1})
    mgr.publish("exec-1", {"type": "log", "end_offset": 2})
    mgr.publish("exec-1", {"type": "log", "end_offset": 3})  # overflow -> close

    # Overflow drained the backlog and pushed exactly CLOSE; the generator would
    # wake on it and end. The subscriber is unsubscribed.
    assert q.get_nowait() is CLOSE
    assert mgr.subscriber_count("exec-1") == 0

    # Idempotent: further publish/close on the gone subscription do not raise.
    mgr.publish("exec-1", {"type": "log", "end_offset": 4})
    mgr.close("exec-1")


# --------------------------------------------------------------------------
# TC-07 (real generator) — the SSE endpoint stream ends on queue overflow
# --------------------------------------------------------------------------
async def test_tc07_real_sse_generator_ends_on_overflow(
    exec_client, seeder, subscriptions
):
    """TC-07 (real generator): overflowing the bounded subscriber queue force-
    closes the live SSE endpoint — the StreamingResponse generator actually ends
    (its `async for` completes) and its finally unsubscribes the connection."""
    task, execution, _l = await seeder.running_task()
    url = f"/api/v1/tasks/{task.id}/logs/stream"
    ended = asyncio.Event()

    async def consume():
        async with exec_client.stream("GET", url) as resp:
            assert resp.status_code == 200
            async for _line in resp.aiter_lines():
                pass  # drain until the generator ends
        ended.set()

    task_h = asyncio.create_task(consume())
    try:
        # Wait until the stream has subscribed.
        for _ in range(300):
            if subscriptions.subscriber_count(execution.id) > 0:
                break
            await asyncio.sleep(0.01)
        assert subscriptions.subscriber_count(execution.id) > 0
        # Synchronous burst (no await between publishes, so the generator cannot
        # drain): overflow the default 1000-deep bounded queue -> force-close.
        for i in range(1100):
            subscriptions.publish(
                execution.id,
                {"type": "log", "start_offset": i, "end_offset": i + 1, "content": "x"},
            )
        # The real generator wakes on the CLOSE sentinel and ends; finally
        # unsubscribes so the registry drops the connection.
        await asyncio.wait_for(ended.wait(), timeout=6.0)
        assert subscriptions.subscriber_count(execution.id) == 0
    finally:
        if not task_h.done():
            task_h.cancel()
        # Await the task so the generator's finally (and its DB preflight session)
        # is fully unwound before the test exits — no lingering background task.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task_h


# --------------------------------------------------------------------------
# TC-18 (concurrent endpoint) — two concurrent same-content uploads are safe
# --------------------------------------------------------------------------
async def test_tc18_concurrent_same_content_uploads_are_safe(
    exec_settings, tmp_path, monkeypatch
):
    """TC-18 (concurrent endpoint): two overlapping uploads of the SAME content,
    each on its OWN DB session/connection, hit the real egg endpoint concurrently.
    A barrier holds request A inside the per-sha publish lock (before its commit)
    so request B provably BLOCKS on the same lock (serialized, no interleaved
    publish/rollback); once A commits, B dedups. Both succeed, leaving exactly one
    artifact + body and no residue. The barrier makes the overlap deterministic
    (no reliance on thread/loop timing) so the test is not flaky."""
    import dopilot_server.api.v1.artifacts as art_mod
    from dopilot_server.app import create_app
    from dopilot_server.artifacts.upload import _publish_locks
    from dopilot_server.config.loader import get_settings
    from dopilot_server.db.base import Base
    from dopilot_server.db.engine import get_session
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # File-backed engine so each request session has an INDEPENDENT connection.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/concurrent.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def _client(session):
        app = create_app(exec_settings)
        app.dependency_overrides[get_settings] = lambda: exec_settings

        async def _sess():
            yield session

        app.dependency_overrides[get_session] = _sess
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    # Barrier: the FIRST upsert (request A, inside the publish lock, pre-commit)
    # signals entry and waits until we release it — while B is trying to acquire
    # the same per-sha lock.
    orig_upsert = art_mod.svc.upsert_scrapy
    a_inside = asyncio.Event()
    release_a = asyncio.Event()
    calls = {"n": 0}

    async def barrier_upsert(session, manifest):
        calls["n"] += 1
        if calls["n"] == 1:
            a_inside.set()
            await release_a.wait()
        return await orig_upsert(session, manifest)

    monkeypatch.setattr(art_mod.svc, "upsert_scrapy", barrier_upsert)

    content = _egg_bytes("concurrent")

    async def post(client):
        return await client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("x.egg", content, "application/octet-stream")},
            data={"project": "demo"},
        )

    try:
        async with maker() as s1, maker() as s2:
            c1, c2 = _client(s1), _client(s2)
            async with c1, c2:
                ta = asyncio.create_task(post(c1))
                await asyncio.wait_for(a_inside.wait(), timeout=5.0)
                # A holds the per-sha lock (paused pre-commit). Start B; it must
                # block on the SAME lock rather than interleave.
                tb = asyncio.create_task(post(c2))
                await asyncio.sleep(0.05)
                assert not tb.done()  # serialized: B is blocked on the sha lock
                sha = next(iter(_publish_locks))
                assert _publish_locks[sha][1] == 2  # A holds + B waits
                # Release A -> it commits + frees the lock -> B proceeds (dedup).
                release_a.set()
                r1, r2 = await asyncio.gather(ta, tb)
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        async with maker() as s:
            assert (await s.execute(
                select(func.count()).select_from(BuildArtifact)
            )).scalar_one() == 1
        root = exec_settings.artifacts.root_dir
        assert len(list((Path(root) / "scrapy").glob("*.egg"))) == 1
        assert _staging_files(root) == []
        assert not _publish_locks  # lock registry fully drained (no leak)
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------
# TC-13 (server) — env/TOML loader for the new fields
# --------------------------------------------------------------------------
def test_tc13_server_defaults_and_env_overrides(monkeypatch, tmp_path):
    """TC-13 (server): new fields load from TOML defaults and DOPILOT_* env
    overrides win, including retention_days=30 and stream_maxlen_logs=100000."""
    from dopilot_server.config.loader import load_settings

    toml = tmp_path / "server.toml"
    toml.write_text(
        "[auth]\ndisabled = true\n", encoding="utf-8"
    )
    s = load_settings(str(toml))
    # Defaults from the models.
    assert s.logs.retention_days == 30
    assert s.logs.max_file_bytes == 33554432  # 32MiB (log-flood guard)
    assert s.redis.stream_maxlen_logs == 100000
    assert s.maintenance.enabled is True
    assert s.maintenance.event_audit_retention_days == 30
    assert s.artifacts.max_upload_bytes == 209715200
    assert s.artifacts.max_total_bytes == 21474836480

    # Env overrides win.
    monkeypatch.setenv("DOPILOT_LOG_RETENTION_DAYS", "7")
    monkeypatch.setenv("DOPILOT_LOG_MAX_FILE_BYTES", "123")
    monkeypatch.setenv("DOPILOT_MAINTENANCE_ENABLED", "false")
    monkeypatch.setenv("DOPILOT_MAINTENANCE_EVENT_AUDIT_RETENTION_DAYS", "9")
    monkeypatch.setenv("DOPILOT_ARTIFACTS_MAX_UPLOAD_BYTES", "456")
    monkeypatch.setenv("DOPILOT_ARTIFACTS_MAX_TOTAL_BYTES", "789")
    monkeypatch.setenv("DOPILOT_REDIS_STREAM_MAXLEN_LOGS", "222")
    s2 = load_settings(str(toml))
    assert s2.logs.retention_days == 7
    assert s2.logs.max_file_bytes == 123
    assert s2.maintenance.enabled is False
    assert s2.maintenance.event_audit_retention_days == 9
    assert s2.artifacts.max_upload_bytes == 456
    assert s2.artifacts.max_total_bytes == 789
    assert s2.redis.stream_maxlen_logs == 222
