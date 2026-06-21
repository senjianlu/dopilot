import client from "./client";
import type { HealthInfo } from "./types";

export async function getHealth(): Promise<HealthInfo> {
  const { data } = await client.get<HealthInfo>("/health");
  return data;
}
