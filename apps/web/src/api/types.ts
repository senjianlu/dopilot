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
  | "lost";

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

// Row shape for the executions list.
export interface ExecutionSummary {
  id: string;
  task_type: string;
  target: string;
  status: ExecutionStatus;
  node_strategy: NodeStrategy;
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
  node_strategy: NodeStrategy;
  params: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  attempts: AttemptView[];
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
