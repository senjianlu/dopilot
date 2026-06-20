import client from "./client";
import type {
  CreateScheduleRequest,
  NextRunPreviewRequest,
  NextRunPreviewResponse,
  RunExecutionResponse,
  Schedule,
  SchedulesResponse,
} from "./types";

export async function listSchedules(): Promise<Schedule[]> {
  const { data } = await client.get<SchedulesResponse>("/schedules");
  return data.schedules;
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

// Immediately create + dispatch a task from the referenced template snapshot.
export async function triggerSchedule(
  id: string,
): Promise<RunExecutionResponse> {
  const { data } = await client.post<RunExecutionResponse>(
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
