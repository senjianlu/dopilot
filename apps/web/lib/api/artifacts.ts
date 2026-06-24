import client from "./client";
import type {
  ArtifactsResponse,
  BuildArtifact,
  UploadEggResponse,
  UploadWheelResponse,
} from "./types";

export interface UploadEggInput {
  file: File;
  project?: string;
  version?: string;
}

export interface UploadWheelInput {
  file: File;
}

export async function listBuildArtifacts(): Promise<BuildArtifact[]> {
  const { data } = await client.get<ArtifactsResponse>("/artifacts");
  return data.artifacts;
}

export async function uploadEgg(
  input: UploadEggInput,
): Promise<UploadEggResponse> {
  const form = new FormData();
  form.append("file", input.file);
  if (input.project) {
    form.append("project", input.project);
  }
  if (input.version) {
    form.append("version", input.version);
  }
  const { data } = await client.post<UploadEggResponse>(
    "/artifacts/scrapy/egg",
    form,
  );
  return data;
}

export async function uploadWheel(
  input: UploadWheelInput,
): Promise<UploadWheelResponse> {
  const form = new FormData();
  form.append("file", input.file);
  const { data } = await client.post<UploadWheelResponse>(
    "/artifacts/python_wheel/wheel",
    form,
  );
  return data;
}

// Idempotently archive a build artifact. Archived artifacts stay visible and
// runnable by existing bindings but cannot be picked for new template bindings.
export async function archiveArtifact(id: string): Promise<BuildArtifact> {
  const { data } = await client.post<BuildArtifact>(
    `/artifacts/${id}/archive`,
  );
  return data;
}

// Idempotently unarchive a build artifact (makes it selectable again).
export async function unarchiveArtifact(id: string): Promise<BuildArtifact> {
  const { data } = await client.post<BuildArtifact>(
    `/artifacts/${id}/unarchive`,
  );
  return data;
}
