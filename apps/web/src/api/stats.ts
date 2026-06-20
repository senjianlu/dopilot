import client from "./client";
import type { DailyTaskStatsResponse } from "./types";

// Phase 1.7.1: last `days` of daily parent-task + execution counts (dashboard).
export async function getDailyTaskStats(
  days = 30,
): Promise<DailyTaskStatsResponse> {
  const { data } = await client.get<DailyTaskStatsResponse>(
    "/stats/tasks/daily",
    { params: { days } },
  );
  return data;
}