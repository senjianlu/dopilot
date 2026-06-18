import client from "./client";
import type { NodeStrategy, UploadEggResponse } from "./types";

export interface UploadEggInput {
  file: File;
  project: string;
  version: string;
  nodeStrategy?: NodeStrategy;
  nodeIds?: string[];
}

export async function uploadEgg(
  input: UploadEggInput,
): Promise<UploadEggResponse> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("project", input.project);
  form.append("version", input.version);
  if (input.nodeStrategy) {
    form.append("node_strategy", input.nodeStrategy);
  }
  for (const nodeId of input.nodeIds ?? []) {
    form.append("node_ids", nodeId);
  }
  const { data } = await client.post<UploadEggResponse>(
    "/artifacts/scrapy/egg",
    form,
  );
  return data;
}
