import client from "./client";
import type {
  ListTasksParams,
  LogSnapshot,
  StreamTokenResponse,
  TasksResponse,
  TaskView,
} from "./types";

// Phase 1.7.1: backend-paginated list. Returns the full response (rows + page /
// page_size / total + known spider values) so the page can render controls.
export async function listTasks(
  params: ListTasksParams = {},
): Promise<TasksResponse> {
  const query: Record<string, string | number> = {
    page: params.page ?? 1,
    page_size: params.pageSize ?? 20,
  };
  if (params.spider) {
    query.spider = params.spider;
  }
  const { data } = await client.get<TasksResponse>("/tasks", {
    params: query,
  });
  return data;
}

export async function getTask(id: string): Promise<TaskView> {
  const { data } = await client.get<TaskView>(`/tasks/${id}`);
  return data;
}

export async function cancelTask(id: string): Promise<TaskView> {
  const { data } = await client.post<TaskView>(`/tasks/${id}/cancel`);
  return data;
}

export interface LogSnapshotQuery {
  executionId?: string;
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
  if (query.executionId) {
    params.execution_id = query.executionId;
  }
  if (query.maxBytes != null) {
    params.max_bytes = query.maxBytes;
  }
  const { data } = await client.get<LogSnapshot>(`/tasks/${id}/logs`, {
    params,
  });
  return data;
}

// Request a short-lived SSE token (only meaningful when web auth is on).
export async function fetchStreamToken(
  id: string,
): Promise<StreamTokenResponse> {
  const { data } = await client.post<StreamTokenResponse>(
    `/tasks/${id}/logs/stream-token`,
  );
  return data;
}

export interface StreamUrlQuery {
  executionId?: string;
  stream?: string;
  streamToken?: string;
}

// Build the absolute EventSource URL for the log stream. EventSource cannot
// attach the bearer header, so an optional short-lived stream_token is passed
// as a query param when web auth is on.
export function buildStreamUrl(id: string, query: StreamUrlQuery = {}): string {
  const params = new URLSearchParams();
  params.set("stream", query.stream ?? "log");
  if (query.executionId) {
    params.set("execution_id", query.executionId);
  }
  if (query.streamToken) {
    params.set("stream_token", query.streamToken);
  }
  return `/api/v1/tasks/${id}/logs/stream?${params.toString()}`;
}
