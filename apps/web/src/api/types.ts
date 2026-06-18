// TS types mirroring the FROZEN WEB-FACING JSON SHAPES exposed by server /api/v1.
// Keep these in lockstep with packages/protocol and the server response models.

export interface HealthInfo {
  status: string;
  service: string;
  version: string;
  database: string; // "ok" | "error"
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

export type NodeStatus = "unknown" | "healthy" | "unhealthy";

export interface NodeInfo {
  id: string | null;
  agent_id: string | null;
  endpoint: string;
  status: NodeStatus;
  capabilities: Record<string, unknown>;
  last_seen_at: string | null;
}

export interface NodesResponse {
  nodes: NodeInfo[];
}

// Universal error envelope: { code, message_key, detail }.
export interface ApiError {
  code: string;
  message_key: string;
  detail: Record<string, unknown>;
}
