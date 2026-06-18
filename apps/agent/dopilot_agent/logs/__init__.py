"""Log tail provider package (phase-1+).

Empty in phase 0. Phase 1+ adds the agent-side tail provider: a ``LogSource``
implementation that reads byte-range increments from execution log files under
the agent workdir and serves them to the server's pull loop.
"""
