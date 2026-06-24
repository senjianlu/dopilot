// TS types mirroring the FROZEN WEB-FACING JSON SHAPES exposed by server /api/v1.
// Keep these in lockstep with packages/protocol and the server response models.

export interface HealthInfo {
  status: string;
  service: string;
  version: string;
  database: string; // "ok" | "error"
  postgresql?: {
    status: string;
    version: string | null;
  };
  redis?: {
    status: string;
    version: string | null;
  };
  nodes?: {
    total: number;
    online: number;
    healthy: number;
  };
  // Phase 1.7.1: dashboard scheduling-health light over schedulable nodes.
  agent?: {
    status: "green" | "yellow" | "red";
    schedulable: number;
    healthy: number;
  };
}

export interface LoginResponse {
  mode: string; // "on" | "off"
  access_token: string | null;
  token_type: string;
  expires_at: string | null;
}

export interface MeResponse {
  authenticated: boolean;
  mode: string; // "on" | "off"
  username: string | null;
  expires_at: string | null;
}

export type NodeStatus = "unknown" | "healthy" | "degraded" | "unhealthy";

export interface NodeInfo {
  id: string | null;
  agent_id: string | null;
  endpoint: string;
  status: NodeStatus;
  capabilities: Record<string, unknown>;
  // health.scrapyd carries { running, port, pid } when the agent reports it.
  health: Record<string, unknown>;
  last_seen_at: string | null;
  // Phase 1.7.1: scheduling-control state, independent of health `status`.
  // offline = !scheduling_enabled; deleted = deleted_at != null.
  scheduling_enabled: boolean;
  scheduling_disabled_at: string | null;
  deleted_at: string | null;
}

// Phase 1.7.1 badge state. Precedence: deleted > offline > healthy > warning.
export type NodeBadge = "deleted" | "offline" | "healthy" | "warning" | "unknown";

export interface NodesResponse {
  nodes: NodeInfo[];
}

// node_strategy decides which healthy agents a task targets.
export type NodeStrategy = "all" | "random" | "selected";

// Runnable artifact types: scrapy (phase 1.8) + python_wheel (phase 2b).
export type ArtifactType = "scrapy" | "python_wheel";

export type TaskStatus =
  | "queued"
  | "running"
  | "finalizing"
  | "complete"
  | "failed"
  | "canceled"
  | "lost"
  // Phase 1.7: a task that found no healthy target node, so it has zero
  // child executions. Terminal; status_reason/status_detail carry the why.
  | "no_target";

// Kept as an alias for back-compatible call sites (status enum is unchanged).
export type ExecutionStatus = TaskStatus;

// ---------------------------------------------------------------------------
// Build artifacts (was scrapy artifacts / "crawlers")
// ---------------------------------------------------------------------------

export interface BuildArtifact {
  id: string;
  artifact_type: string;
  package_format: string;
  name: string;
  filename: string | null;
  content_hash: string | null;
  size_bytes: number;
  project: string | null;
  version: string | null;
  spiders: string[];
  // Phase 2b: the wheel distribution name (python_wheel artifacts only).
  distribution?: string | null;
  fetch_path: string | null;
  runnable: boolean;
  // Phase task-artifact-archive: reversible archive state. `archived` is derived
  // from `archived_at` (null => false). Archived artifacts stay visible and
  // runnable by existing template bindings, but are not selectable for new ones.
  archived: boolean;
  archived_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ArtifactsResponse {
  artifacts: BuildArtifact[];
}

export interface UploadEggResponse {
  artifact: BuildArtifact;
  spiders: string[];
}

// The wheel upload response mirrors the egg upload shape (spiders is empty).
export type UploadWheelResponse = UploadEggResponse;

// Result of creating + dispatching a task (template run / schedule trigger).
export interface TaskRunResponse {
  task_id: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Tasks (parent runs; was "executions") + Executions (atomic per-node)
// ---------------------------------------------------------------------------

// How a task was created.
export type TaskSource =
  | "direct_artifact"
  | "template"
  | "schedule_trigger_now"
  | "schedule_timer"
  | "manual";

// A build artifact descriptor: a task-list column source + a distinct filter
// option. Derived from the immutable Task snapshot, so it works for any artifact
// type (scrapy, python_wheel). `label` is a human-readable name+version.
export interface BuildArtifactOption {
  id: string;
  name?: string | null;
  artifact_type?: string | null;
  version?: string | null;
  distribution?: string | null;
  project?: string | null;
  label?: string | null;
}

// Row shape for the tasks list.
export interface TaskSummary {
  id: string;
  artifact_type: string;
  target: string;
  // Legacy derived scrapy spider; the list filter is by build artifact now.
  spider?: string | null;
  // The build artifact this run executed (immutable snapshot); null for a
  // legacy/direct task created without a snapshot.
  build_artifact?: BuildArtifactOption | null;
  status: TaskStatus;
  status_reason?: string | null;
  node_strategy: NodeStrategy;
  source?: TaskSource;
  execution_template_id?: string | null;
  schedule_id?: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  execution_count: number;
}

export interface TasksResponse {
  tasks: TaskSummary[];
  // Phase 1.7.1: server-side pagination metadata + distinct build-artifact
  // filter options referenced by existing tasks.
  page: number;
  page_size: number;
  total: number;
  build_artifacts: BuildArtifactOption[];
}

// Allowed backend page sizes. The UI picks the closest from table height but
// may only request one of these.
export const TASK_PAGE_SIZES = [5, 10, 20, 50, 100] as const;
export type TaskPageSize = (typeof TASK_PAGE_SIZES)[number];

export interface ListTasksParams {
  page?: number;
  pageSize?: TaskPageSize;
  buildArtifactId?: string | null;
  status?: TaskStatus | null;
}

// A single atomic execution against an agent/node.
export interface ExecutionView {
  id: string;
  task_id: string;
  agent_id: string | null;
  node_id: string | null;
  endpoint: string | null;
  remote_job_id: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error_code: string | null;
  error_detail: Record<string, unknown> | null;
}

export interface TaskView {
  id: string;
  artifact_type: string;
  target: string;
  status: TaskStatus;
  // Phase 1.7: present on a no_target (or other non-business) terminal.
  status_reason?: string | null;
  status_detail?: Record<string, unknown>;
  node_strategy: NodeStrategy;
  params: Record<string, unknown>;
  build_artifact: Record<string, unknown>;
  source?: TaskSource;
  execution_template_id?: string | null;
  schedule_id?: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  executions: ExecutionView[];
}

// ---------------------------------------------------------------------------
// Execution templates (was "task templates")
// ---------------------------------------------------------------------------

export interface ExecutionTemplate {
  id: string;
  name: string;
  description: string | null;
  build_artifact_id: string | null;
  artifact_type: string;
  project: string | null;
  version: string | null;
  // Command-first input. For scrapy this is a `scrapy crawl ...` command; for
  // python_wheel (phase 2b) it is a free-form shell command (sent to the agent
  // as `shell_command`). `artifact_type` selects the interpretation.
  command: string | null;
  node_strategy: NodeStrategy;
  node_ids: string[];
  // Phase task-web-archive-indicators: LIVE archive state of the bound build
  // artifact (derived from the artifact, not a frozen snapshot). Required to
  // mirror the backend, which always populates it. A dangling/legacy binding
  // is reported as archived=false / archived_at=null. Archiving never blocks an
  // already-bound template's runs or schedule dispatch.
  build_artifact_archived: boolean;
  build_artifact_archived_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TemplatesResponse {
  templates: ExecutionTemplate[];
}

export interface CreateExecutionTemplateRequest {
  name: string;
  description?: string | null;
  build_artifact_id: string;
  command: string;
  node_strategy?: NodeStrategy;
  node_ids?: string[];
}

export type TriggerType = "interval" | "cron";

// Schedule overrides applied to the bound execution template at fire time
// (phase 1.8.1, command-first). A `command` override FULLY replaces the template
// command. It may NOT override the build artifact.
export interface ScheduleOverrides {
  command?: string | null;
  node_strategy?: NodeStrategy;
  node_ids?: string[];
}

export interface Schedule {
  id: string;
  name: string;
  description: string | null;
  // Phase 2.2: row-level timer gate. Disabled schedules stay editable and
  // remain manually runnable via trigger-now.
  enabled: boolean;
  execution_template_id: string;
  trigger_type: TriggerType;
  interval_seconds: number | null;
  cron: string | null;
  overrides: Record<string, unknown>;
  // Phase 1.7.1: estimated next fire time (interval = estimate, cron = exact).
  next_run_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SchedulesResponse {
  schedules: Schedule[];
}

export interface NextRunPreviewRequest {
  trigger_type: TriggerType;
  interval_seconds?: number | null;
  cron?: string | null;
}

export interface NextRunPreviewResponse {
  next_run_at: string | null;
}

export interface CreateScheduleRequest {
  name: string;
  description?: string | null;
  // Phase 2.2: new schedules default disabled; pass true to enable timer firing.
  enabled?: boolean;
  execution_template_id: string;
  trigger_type?: TriggerType;
  interval_seconds?: number | null;
  cron?: string | null;
  overrides?: ScheduleOverrides;
}

// ---------------------------------------------------------------------------
// phase 1.7.1: dashboard daily task/run stats
// ---------------------------------------------------------------------------

export interface DailyTaskCount {
  date: string; // YYYY-MM-DD
  tasks: number;
  executions: number;
}

export interface DailyTaskStatsResponse {
  days: number;
  timezone: string;
  buckets: DailyTaskCount[];
}

// A snapshot pull of a log stream from a known offset. The log atomic id is now
// `execution_id`; the parent is `task_id`.
export interface LogSnapshot {
  task_id: string;
  execution_id: string | null;
  stream: string;
  start_offset: number;
  end_offset: number;
  content: string;
  status: string;
  finished: boolean;
}

// Short-lived token issued for an SSE log stream when web auth is on.
export interface StreamTokenResponse {
  stream_token: string;
  expires_at: string | null;
}

// ---------------------------------------------------------------------------
// Manual maintenance (phase 1.8.2)
// ---------------------------------------------------------------------------

export interface TerminalCleanupRequest {
  older_than_days?: number | null;
  before?: string | null;
  dry_run?: boolean;
}

export interface TerminalCleanupResponse {
  dry_run: boolean;
  cutoff: string;
  tasks: number;
  executions: number;
  log_files: number;
  log_files_removed: number;
  log_bytes: number;
  command_outbox: number;
}

export interface MarkTaskLostResponse {
  task_id: string;
  task_status: string;
  executions_marked: number;
  already_terminal: string[];
}

// Universal error envelope: { code, message_key, detail }.
export interface ApiError {
  code: string;
  message_key: string;
  detail: Record<string, unknown>;
}
