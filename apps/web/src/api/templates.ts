import client from "./client";
import type {
  CreateExecutionTemplateRequest,
  ExecutionTemplate,
  TaskRunResponse,
  TemplatesResponse,
} from "./types";

export async function listTemplates(): Promise<ExecutionTemplate[]> {
  const { data } = await client.get<TemplatesResponse>("/templates");
  return data.templates;
}

export async function getTemplate(id: string): Promise<ExecutionTemplate> {
  const { data } = await client.get<ExecutionTemplate>(`/templates/${id}`);
  return data;
}

export async function createTemplate(
  payload: CreateExecutionTemplateRequest,
): Promise<ExecutionTemplate> {
  const { data } = await client.post<ExecutionTemplate>("/templates", payload);
  return data;
}

export async function updateTemplate(
  id: string,
  payload: Partial<CreateExecutionTemplateRequest>,
): Promise<ExecutionTemplate> {
  const { data } = await client.put<ExecutionTemplate>(
    `/templates/${id}`,
    payload,
  );
  return data;
}

export async function deleteTemplate(id: string): Promise<void> {
  await client.delete(`/templates/${id}`);
}

// Create + dispatch a task from this template's immutable snapshot.
export async function runTemplate(id: string): Promise<TaskRunResponse> {
  const { data } = await client.post<TaskRunResponse>(`/templates/${id}/run`);
  return data;
}
