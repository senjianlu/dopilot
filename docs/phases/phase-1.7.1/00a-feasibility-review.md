# 00a · Phase 1.7.1 feasibility review

Date: 2026-06-20

## Proposed Work

Phase 1.7.1 optimizes the current Vue UI and adds the backend support required
for the new UI behavior:

- reversible node offline/online state;
- node soft delete;
- execution-list backend pagination and spider filtering;
- dashboard service-health presentation and 30-day run chart;
- template node selection UI and artifact/spider selection;
- schedule next-run display.

## Claude Feasibility Verdict

Claude returned: **feasible with changes**.

There are no hard blockers. The work is not UI-only; it needs schema, API,
service, and tests for node scheduling state, node deletion, pagination,
statistics, and schedule next-run metadata.

## Feasibility Findings

- Node operations are net-new backend surface. Current node API only lists
  nodes, and `nodes` has no scheduling-state or soft-delete columns.
- The existing nodes refresh bug is straightforward: web calls removed
  `POST /nodes/refresh`; phase 1.5 uses heartbeat-sourced `GET /nodes`.
- Execution pagination must replace the current fixed `limit=200` list and
  avoid per-task child-count N+1 queries.
- Spider filtering is currently based on task params/snapshots. At the expected
  history volume, the filter needs a queryable task-level value or an
  equivalent indexed strategy.
- Schedule `next_run_at` is deterministic for cron, but interval schedules
  have no persisted last-fire time. A computed preview from "now" is feasible
  but should not be described as the persisted scheduler's exact next fire.
- The frontend currently has no chart dependency. A small native SVG/CSS bar
  chart avoids adding a dependency for a narrow dashboard statistic.

## Codex Decisions

- Node delete is **soft delete**. Deleted nodes remain in the database so
  historical templates/tasks/executions can render them as deleted.
- Badge precedence is:
  1. deleted = gray;
  2. offline = red;
  3. healthy = green;
  4. degraded/unhealthy/unknown = yellow.
- Offline nodes still receive heartbeat updates and display real health detail,
  but are excluded from dispatch target selection and dashboard scheduling
  health aggregates.
- Deleted nodes are excluded from normal node lists used for scheduling, but
  can be returned or resolved where historical references need display labels.
- Existing selected templates that reference an offline/deleted node are not
  silently mutated. Runtime target resolution skips unschedulable nodes; if no
  selected target remains, the task becomes `no_target`.
- Backend pagination is required for executions in this phase. Templates,
  schedules, and nodes may stay unpaginated unless implementation reuse is
  cheap and low-risk.
- Execution pagination contract uses `page`, `page_size`, and `total`, with
  allowed page sizes `5, 10, 20, 50, 100`.
- The UI may choose page size from table height, but must only request one of
  the allowed sizes.
- Dashboard 30-day chart counts parent tasks/runs per local calendar day using
  the scheduler timezone setting when available; otherwise UTC.
- Chart implementation should avoid adding a heavyweight chart dependency.
- Template creation must use artifact selection to derive Scrapy project/version
  details. The user-facing Project field is removed.
- Config-seeded nodes that have no DB id cannot be offlined/deleted until first
  heartbeat creates/adopts a DB row; their operation buttons should be disabled
  or hidden.

## Scope / Sequencing Decision

Implement backend first:

1. node schema/API/service changes;
2. target-selection filtering for offline/deleted nodes;
3. execution pagination and spider filter;
4. dashboard stats and schedule next-run metadata;
5. frontend UI updates and tests.

No user escalation is required after feasibility review because the open points
were implementation-contract choices within the confirmed product direction.
