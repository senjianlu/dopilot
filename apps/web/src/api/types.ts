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
}

export interface NodesResponse {
  nodes: NodeInfo[];
}

// node_strategy decides which healthy agents an execution targets.
export type NodeStrategy = "all" | "random" | "selected";

// Phase 1 only really supports the scrapy task type.
export type TaskType = "scrapy";

export type ExecutionStatus =
  | "queued"
  | "running"
  | "finalizing"
  | "complete"
  | "failed"
  | "canceled"
  | "lost"
  // Phase 1.7: a run (task) that found no healthy target node, so it has zero
  // child executions. Terminal; status_reason/status_detail carry the why.
  | "no_target";

// Egg upload artifact metadata.
export interface ScrapyArtifact {
  id: string;
  project: string;
  version: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  spiders: string[];
  valid: boolean;
  uploaded_at: string | null;
  created_at: string | null;
}

export interface ArtifactsResponse {
  artifacts: ScrapyArtifact[];
}

export interface UploadEggResponse {
  artifact: ScrapyArtifact;
  spiders: string[];
  agent_id: string | null;
  endpoint: string | null;
}

// Parameters for a scrapy run.
export interface ScrapyRunParams {
  project?: string;
  spider: string;
  version?: string;
  artifact?: {
    hash: string;
    sha256?: string;
    filename: string;
    project: string;
    version: string;
    size_bytes: number;
    fetch_path: string;
  };
  settings?: Record<string, string>;
  args?: Record<string, string>;
}

export interface RunExecutionRequest {
  task_type: TaskType;
  target: string;
  node_strategy: NodeStrategy;
  node_ids: string[];
  params: ScrapyRunParams;
}

export interface RunExecutionResponse {
  execution_id: string;
  status: string;
}

// How a task was created. manual covers ad-hoc + run-from-template.
export type TaskSource = "manual" | "schedule_trigger_now" | "schedule_timer";

// Row shape for the executions (runs/tasks) list.
export interface ExecutionSummary {
  id: string;
  task_type: string;
  target: string;
  status: ExecutionStatus;
  status_reason?: string | null;
  node_strategy: NodeStrategy;
  source?: TaskSource;
  template_id?: string | null;
  schedule_id?: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  attempt_count: number;
}

export interface ExecutionsResponse {
  executions: ExecutionSummary[];
}

// A single attempt against an agent/node.
export interface AttemptView {
  id: string;
  execution_id: string;
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

export interface ExecutionView {
  id: string;
  task_type: string;
  target: string;
  status: ExecutionStatus;
  // Phase 1.7: present on a no_target (or other non-business) terminal.
  status_reason?: string | null;
  status_detail?: Record<string, unknown>;
  node_strategy: NodeStrategy;
  params: Record<string, unknown>;
  source?: TaskSource;
  template_id?: string | null;
  schedule_id?: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  attempts: AttemptView[];
}

// ---------------------------------------------------------------------------
// phase 1.7 packet 2: task templates + schedules
// ---------------------------------------------------------------------------

export interface TaskTemplate {
  id: string;
  name: string;
  description: string | null;
  task_type: string;
  project: string | null;
  version: string | null;
  spider: string | null;
  artifact: Record<string, unknown>;
  settings: Record<string, string>;
  args: Record<string, string>;
  node_strategy: NodeStrategy;
  node_ids: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface TemplatesResponse {
  templates: TaskTemplate[];
}

export interface CreateTemplateRequest {
  name: string;
  description?: string | null;
  task_type?: TaskType;
  project?: string | null;
  version?: string | null;
  spider?: string | null;
  artifact?: Record<string, unknown>;
  settings?: Record<string, string>;
  args?: Record<string, string>;
  node_strategy?: NodeStrategy;
  node_ids?: string[];
}

export type TriggerType = "interval" | "cron";

export interface Schedule {
  id: string;
  name: string;
  description: string | null;
  template_id: string;
  trigger_type: TriggerType;
  interval_seconds: number | null;
  cron: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SchedulesResponse {
  schedules: Schedule[];
}

export interface CreateScheduleRequest {
  name: string;
  description?: string | null;
  template_id: string;
  trigger_type?: TriggerType;
  interval_seconds?: number | null;
  cron?: string | null;
}

// A snapshot pull of a log stream from a known offset.
export interface LogSnapshot {
  execution_id: string;
  attempt_id: string | null;
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

// Universal error envelope: { code, message_key, detail }.
export interface ApiError {
  code: string;
  message_key: string;
  detail: Record<string, unknown>;
}
