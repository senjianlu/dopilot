"""Per-attempt state persistence (phase 1).

Each Scrapy execution the agent launches gets a small JSON state file at
``{workdir}/state/executions/{execution_id}.json`` that maps the server's
``execution_id`` onto the local scrapyd job id, project/spider/version, and the
resolved job.log path. The state file is the **source of truth** the agent uses
to resolve status and log publishing across restarts, so writes are atomic
(write tmp + ``os.replace``) and corrupt/half-written files are treated as
missing rather than raising.
"""
