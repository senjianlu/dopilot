import client from "./client";
import type { LoginResponse, MeResponse } from "./types";

export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const { data } = await client.post<LoginResponse>("/auth/login", {
    username,
    password,
  });
  return data;
}

export async function me(): Promise<MeResponse> {
  const { data } = await client.get<MeResponse>("/auth/me");
  return data;
}
