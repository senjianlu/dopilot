"""ORM models.

Importing this package registers every model on ``Base.metadata`` so Alembic
autogenerate and the test ``create_all`` see the full schema.
"""

from .auth_token import AuthToken
from .command_outbox import CommandOutbox
from .event_audit import EventAudit
from .execution import (
    Execution,
    ExecutionLogFile,
    ScrapyArtifact,
    Task,
)
from .node import Node
from .scheduling import Schedule, TaskTemplate

__all__ = [
    "AuthToken",
    "Node",
    "Task",
    "Execution",
    "ExecutionLogFile",
    "ScrapyArtifact",
    "CommandOutbox",
    "EventAudit",
    "TaskTemplate",
    "Schedule",
]
