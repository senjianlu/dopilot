"""SEAM: ``node_strategy``.

One of the three phase-0/1 "abstract-first" seams (alongside ``BaseExecutor``
and ``LogSource``). Picking *which* node(s) a task runs on lives here so the
three executor types never reimplement selection. Phase 0 ships a minimal but
real implementation; richer policies (load-aware, capability-aware) extend
:func:`reduce_nodes` without touching call sites.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class NodeStrategy(str, Enum):
    ALL = "all"
    RANDOM = "random"
    SPECIFIED = "specified"


def reduce_nodes(
    strategy: NodeStrategy | str,
    nodes: Sequence[T],
    node_ids: list[str] | None = None,
) -> list[T]:
    """Reduce a node set per ``strategy``.

    - ``all``: every node.
    - ``random``: a single randomly chosen node (empty list if none).
    - ``specified``: nodes whose ``agent_id`` or ``id`` is in ``node_ids``.

    ``specified`` matches on either ``agent_id`` or ``id`` attributes when
    present so it works against both ORM rows and dicts that carry those keys.
    """
    strategy = NodeStrategy(strategy)
    items = list(nodes)

    if strategy is NodeStrategy.ALL:
        return items
    if strategy is NodeStrategy.RANDOM:
        return [random.choice(items)] if items else []

    wanted = set(node_ids or [])

    def _matches(node: T) -> bool:
        for attr in ("agent_id", "id"):
            value = (
                getattr(node, attr, None)
                if not isinstance(node, dict)
                else node.get(attr)
            )
            if value is not None and str(value) in wanted:
                return True
        return False

    return [node for node in items if _matches(node)]
