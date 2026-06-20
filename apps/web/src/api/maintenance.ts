import client from "./client";
import type {
  MarkTaskLostResponse,
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

// Manually mark a stuck active task lost (no hard delete).
export async function markTaskLost(
  taskId: string,
): Promise<MarkTaskLostResponse> {
  const { data } = await client.post<MarkTaskLostResponse>(
    `/tasks/${taskId}/mark-lost`,
  );
  return data;
}
