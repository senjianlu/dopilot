"""Unit tests for short-lived SSE stream tokens."""

from __future__ import annotations

from dopilot_server.logs.stream_token import (
    issue_stream_token,
    verify_stream_token,
)

SECRET = "test-secret-key"


def test_issue_and_verify():
    token, exp = issue_stream_token(SECRET, "exec1", 60, now=1000)
    assert exp == 1060
    assert verify_stream_token(SECRET, token, "exec1", now=1000) is True


def test_rejects_other_execution():
    token, _ = issue_stream_token(SECRET, "exec1", 60, now=1000)
    assert verify_stream_token(SECRET, token, "exec2", now=1000) is False


def test_rejects_expired():
    token, _ = issue_stream_token(SECRET, "exec1", 60, now=1000)
    assert verify_stream_token(SECRET, token, "exec1", now=2000) is False


def test_rejects_tampered_signature():
    token, _ = issue_stream_token(SECRET, "exec1", 60, now=1000)
    payload, _sig = token.split(".", 1)
    forged = f"{payload}.deadbeef"
    assert verify_stream_token(SECRET, forged, "exec1", now=1000) is False


def test_rejects_wrong_secret():
    token, _ = issue_stream_token(SECRET, "exec1", 60, now=1000)
    assert verify_stream_token("other-secret", token, "exec1", now=1000) is False


def test_rejects_garbage():
    assert verify_stream_token(SECRET, "not-a-token", "exec1") is False
    assert verify_stream_token(SECRET, "", "exec1") is False
