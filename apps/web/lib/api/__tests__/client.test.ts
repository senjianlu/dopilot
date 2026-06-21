import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxiosAdapter } from "axios";
import client, { registerUnauthorizedHandler } from "@/lib/api/client";
import { clearToken, getToken, setToken } from "@/lib/api/token";
import { buildStreamUrl } from "@/lib/api/tasks";

describe("token storage", () => {
  beforeEach(() => clearToken());

  it("round-trips and clears the bearer token", () => {
    expect(getToken()).toBeNull();
    setToken("abc");
    expect(getToken()).toBe("abc");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

describe("api client interceptors", () => {
  afterEach(() => {
    clearToken();
    vi.restoreAllMocks();
  });

  it("attaches the bearer token to outgoing requests", async () => {
    setToken("tok-123");
    let seenAuth: unknown;
    const adapter: AxiosAdapter = async (config) => {
      seenAuth = config.headers?.get?.("Authorization");
      return {
        data: { ok: true },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      };
    };
    await client.get("/health", { adapter });
    expect(seenAuth).toBe("Bearer tok-123");
  });

  it("clears the token and invokes the unauthorized handler on 401", async () => {
    setToken("expired");
    const onUnauthorized = vi.fn();
    registerUnauthorizedHandler(onUnauthorized);
    const adapter: AxiosAdapter = async (_config) => {
      const error = new Error("unauthorized") as Error & {
        response?: { status: number };
      };
      error.response = { status: 401 };
      throw error;
    };
    await expect(client.get("/me", { adapter })).rejects.toThrow();
    expect(getToken()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe("buildStreamUrl", () => {
  it("builds the SSE url with stream, execution_id, and stream_token", () => {
    const url = buildStreamUrl("task-1", {
      executionId: "ex-1",
      streamToken: "tok",
    });
    expect(url).toBe(
      "/api/v1/tasks/task-1/logs/stream?stream=log&execution_id=ex-1&stream_token=tok",
    );
  });

  it("defaults the stream name to log with no token", () => {
    expect(buildStreamUrl("task-2")).toBe(
      "/api/v1/tasks/task-2/logs/stream?stream=log",
    );
  });
});
