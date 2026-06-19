"""Server-side Redis Streams transport (phase 1.5).

Redis is a message bus / transient transport only — never a dopilot database.
PostgreSQL remains the business-state authority. This package holds the thin
async client wrapper plus the command producer, dispatcher, and event/log
consumers built on top of it.
"""
