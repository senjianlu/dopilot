import client from "./client";
import type {
  ArtifactsResponse,
  BuildArtifact,
  UploadEggResponse,
} from "./types";

export interface UploadEggInput {
  file: File;
  project?: string;
  version?: string;
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
