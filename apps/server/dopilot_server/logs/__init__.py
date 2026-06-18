"""Log-source seam.

Realtime logs (decision #11): the server PULLS log increments from the agent
tail API — no WebSocket in v1. Bodies are written to ``/server-data/logs``;
only the index/offset/status lives in PostgreSQL. The :class:`LogSource`
abstraction here is the seam that implementation sits behind.
"""
