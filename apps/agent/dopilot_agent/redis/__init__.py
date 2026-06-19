"""Agent-side Redis Streams transport (phase 1.5).

The agent consumes its per-agent command stream and publishes status events and
log increments to the shared server streams. It never connects to PostgreSQL;
Redis is its only path to the server for execution control (heartbeat stays
HTTP). This package holds the thin async client wrapper plus the command
consumer, event publisher, and log publisher.
"""
