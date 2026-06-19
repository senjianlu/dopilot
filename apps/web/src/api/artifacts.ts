import client from "./client";
import type { ArtifactsResponse, ScrapyArtifact, UploadEggResponse } from "./types";

export interface UploadEggInput {
  file: File;
  project?: string;
}

export async function listScrapyArtifacts(): Promise<ScrapyArtifact[]> {
  const { data } = await client.get<ArtifactsResponse>("/artifacts/scrapy");
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
  const { data } = await client.post<UploadEggResponse>(
    "/artifacts/scrapy/egg",
    form,
  );
  return data;
}
