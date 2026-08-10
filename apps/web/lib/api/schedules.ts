import client from "./client";
import type {
  CreateScheduleRequest,
  NextRunPreviewRequest,
  NextRunPreviewResponse,
  Schedule,
  ScheduleDisableAllResponse,
  SchedulesResponse,
  TaskRunResponse,
} from "./types";

// Returns the full response: `enabled_total` is the GLOBAL enabled count (the
// `schedules` list itself truncates at 200 rows server-side).
export async function listSchedules(): Promise<SchedulesResponse> {
  const { data } = await client.get<SchedulesResponse>("/schedules");
  return data;
}

export async function getSchedule(id: string): Promise<Schedule> {
  const { data } = await client.get<Schedule>(`/schedules/${id}`);
  return data;
}

export async function createSchedule(
  payload: CreateScheduleRequest,
): Promise<Schedule> {
  const { data } = await client.post<Schedule>("/schedules", payload);
  return data;
}

export async function updateSchedule(
  id: string,
  payload: Partial<CreateScheduleRequest>,
): Promise<Schedule> {
  const { data } = await client.put<Schedule>(`/schedules/${id}`, payload);
  return data;
}

export async function deleteSchedule(id: string): Promise<void> {
  await client.delete(`/schedules/${id}`);
}

// One-shot pre-upgrade brake: atomically disable every enabled schedule.
export async function disableAllSchedules(): Promise<ScheduleDisableAllResponse> {
  const { data } = await client.post<ScheduleDisableAllResponse>(
    "/schedules/disable-all",
  );
  return data;
}

// Immediately create + dispatch a task from the referenced template snapshot.
export async function triggerSchedule(id: string): Promise<TaskRunResponse> {
  const { data } = await client.post<TaskRunResponse>(
    `/schedules/${id}/trigger-now`,
  );
  return data;
}

// Estimate the next run for an unsaved trigger (backs the create-dialog preview).
export async function previewNextRun(
  payload: NextRunPreviewRequest,
): Promise<NextRunPreviewResponse> {
  const { data } = await client.post<NextRunPreviewResponse>(
    "/schedules/preview-next-run",
    payload,
  );
  return data;
}
