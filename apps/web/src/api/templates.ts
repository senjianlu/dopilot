import client from "./client";
import type {
  CreateTemplateRequest,
  RunExecutionResponse,
  TaskTemplate,
  TemplatesResponse,
} from "./types";

export async function listTemplates(): Promise<TaskTemplate[]> {
  const { data } = await client.get<TemplatesResponse>("/templates");
  return data.templates;
}

export async function getTemplate(id: string): Promise<TaskTemplate> {
  const { data } = await client.get<TaskTemplate>(`/templates/${id}`);
  return data;
}

export async function createTemplate(
  payload: CreateTemplateRequest,
): Promise<TaskTemplate> {
  const { data } = await client.post<TaskTemplate>("/templates", payload);
  return data;
}

export async function updateTemplate(
  id: string,
  payload: Partial<CreateTemplateRequest>,
): Promise<TaskTemplate> {
  const { data } = await client.put<TaskTemplate>(`/templates/${id}`, payload);
  return data;
}

export async function deleteTemplate(id: string): Promise<void> {
  await client.delete(`/templates/${id}`);
}

// Create + dispatch a task from this template's immutable snapshot.
export async function runTemplate(id: string): Promise<RunExecutionResponse> {
  const { data } = await client.post<RunExecutionResponse>(
    `/templates/${id}/run`,
  );
  return data;
}
