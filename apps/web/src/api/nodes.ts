import client from "./client";
import type { NodeInfo, NodesResponse } from "./types";

export async function listNodes(): Promise<NodeInfo[]> {
  const { data } = await client.get<NodesResponse>("/nodes");
  return data.nodes;
}

export async function refreshNodes(): Promise<NodeInfo[]> {
  const { data } = await client.post<NodesResponse>("/nodes/refresh");
  return data.nodes;
}
