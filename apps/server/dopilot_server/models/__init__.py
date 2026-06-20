"""ORM models.

Importing this package registers every model on ``Base.metadata`` so Alembic
autogenerate and the test ``create_all`` see the full schema.
"""

from .auth_token import AuthToken
from .command_outbox import CommandOutbox
from .event_audit import EventAudit
from .execution import (
    BuildArtifact,
    Execution,
    ExecutionLogFile,
    ScrapyArtifact,
    Task,
)
from .node import Node
from .scheduling import ExecutionTemplate, Schedule

__all__ = [
    "AuthToken",
    "Node",
    "Task",
    "Execution",
    "ExecutionLogFile",
    "BuildArtifact",
    "ScrapyArtifact",
    "CommandOutbox",
    "EventAudit",
    "ExecutionTemplate",
    "Schedule",
]
