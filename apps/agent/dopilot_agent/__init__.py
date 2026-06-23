"""dopilot agent - outbound-only worker executor daemon.

The agent consumes commands from Redis, publishes status events / log increments
to the server's Redis streams, and POSTs heartbeats to the server. It exposes no
inbound HTTP API and binds no listening port (phase 2.2.7).
"""

__version__ = "0.0.0"
