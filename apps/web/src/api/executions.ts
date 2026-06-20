import client from "./client";
import type {
  ExecutionsResponse,
  ExecutionView,
  ListExecutionsParams,
  LogSnapshot,
  RunExecutionRequest,
  RunExecutionResponse,
  StreamTokenResponse,
} from "./types";

// Phase 1.7.1: backend-paginated list. Returns the full response (rows + page /
// page_size / total + known spider values) so the page can render controls.
export async function listExecutions(
  params: ListExecutionsParams = {},
): Promise<ExecutionsResponse> {
  const query: Record<string, string | number> = {
    page: params.page ?? 1,
    page_size: params.pageSize ?? 20,
  };
  if (params.spider) {
    query.spider = params.spider;
  }
  const { data } = await client.get<ExecutionsResponse>("/executions", {
    params: query,
  });
  return data;
}

export async function getExecution(id: string): Promise<ExecutionView> {
  const { data } = await client.get<ExecutionView>(`/executions/${id}`);
  return data;
}

export async function runExecution(
  payload: RunExecutionRequest,
): Promise<RunExecutionResponse> {
  const { data } = await client.post<RunExecutionResponse>(
    "/executions/run",
    payload,
  );
  return data;
}

export async function cancelExecution(id: string): Promise<ExecutionView> {
  const { data } = await client.post<ExecutionView>(`/executions/${id}/cancel`);
  return data;
}

export interface LogSnapshotQuery {
  attemptId?: string;
  stream?: string;
  offset?: number;
  maxBytes?: number;
}

export async function getLogSnapshot(
  id: string,
  query: LogSnapshotQuery = {},
): Promise<LogSnapshot> {
  const params: Record<string, string | number> = {
    stream: query.stream ?? "log",
    offset: query.offset ?? 0,
  };
  if (query.attemptId) {
    params.attempt_id = query.attemptId;
  }
  if (query.maxBytes != null) {
    params.max_bytes = query.maxBytes;
  }
  const { data } = await client.get<LogSnapshot>(`/executions/${id}/logs`, {
    params,
  });
  return data;
}

// Request a short-lived SSE token (only meaningful when web auth is on).
export async function fetchStreamToken(
  id: string,
): Promise<StreamTokenResponse> {
  const { data } = await client.post<StreamTokenResponse>(
    `/executions/${id}/logs/stream-token`,
  );
  return data;
}

export interface StreamUrlQuery {
  attemptId?: string;
  stream?: string;
  streamToken?: string;
}

// Build the absolute EventSource URL for the log stream. EventSource cannot
// attach the bearer header, so an optional short-lived stream_token is passed
// as a query param when web auth is on.
export function buildStreamUrl(id: string, query: StreamUrlQuery = {}): string {
  const params = new URLSearchParams();
  params.set("stream", query.stream ?? "log");
  if (query.attemptId) {
    params.set("attempt_id", query.attemptId);
  }
  if (query.streamToken) {
    params.set("stream_token", query.streamToken);
  }
  return `/api/v1/executions/${id}/logs/stream?${params.toString()}`;
}
