import client from "./client";
import type {
  MarkTaskLostResponse,
  ResourceStatsResponse,
  RewriteAofResponse,
  SweepNowResponse,
  TerminalCleanupRequest,
  TerminalCleanupResponse,
} from "./types";

// Delete (or dry-run preview) old terminal task data before a cutoff.
export async function terminalCleanup(
  body: TerminalCleanupRequest,
): Promise<TerminalCleanupResponse> {
  const { data } = await client.post<TerminalCleanupResponse>(
    "/maintenance/terminal-cleanup",
    body,
  );
  return data;
}

// Latest cached resource snapshot (server samples on a timer; this only reads).
export async function getResourceStats(): Promise<ResourceStatsResponse> {
  const { data } = await client.get<ResourceStatsResponse>(
    "/maintenance/resource-stats",
  );
  return data;
}

// Trigger one retention sweep now (per-step report; always 200).
export async function sweepNow(): Promise<SweepNowResponse> {
  const { data } = await client.post<SweepNowResponse>(
    "/maintenance/sweep-now",
  );
  return data;
}

// Trigger a Redis background AOF rewrite (reclaim AOF now).
export async function rewriteAof(): Promise<RewriteAofResponse> {
  const { data } = await client.post<RewriteAofResponse>(
    "/maintenance/redis-rewrite-aof",
  );
  return data;
}

// Manually mark a stuck active task lost (no hard delete).
export async function markTaskLost(
  taskId: string,
): Promise<MarkTaskLostResponse> {
  const { data } = await client.post<MarkTaskLostResponse>(
    `/tasks/${taskId}/mark-lost`,
  );
  return data;
}
