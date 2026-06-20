import client from "./client";
import type { NodeInfo, NodesResponse } from "./types";

export async function listNodes(): Promise<NodeInfo[]> {
  const { data } = await client.get<NodesResponse>("/nodes");
  return data.nodes;
}

// Phase 1.7.1: the old POST /nodes/refresh is gone; "refresh" is just re-listing.
export const refreshNodes = listNodes;

export async function offlineNode(nodeId: string): Promise<NodeInfo> {
  const { data } = await client.post<NodeInfo>(`/nodes/${nodeId}/offline`);
  return data;
}

export async function onlineNode(nodeId: string): Promise<NodeInfo> {
  const { data } = await client.post<NodeInfo>(`/nodes/${nodeId}/online`);
  return data;
}

export async function deleteNode(nodeId: string): Promise<NodeInfo> {
  const { data } = await client.delete<NodeInfo>(`/nodes/${nodeId}`);
  return data;
}