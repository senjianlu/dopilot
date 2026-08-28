import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxiosAdapter } from "axios";
import client, { registerUnauthorizedHandler } from "@/lib/api/client";
import { clearToken, getToken, setToken } from "@/lib/api/token";
import { buildStreamUrl, listTasks } from "@/lib/api/tasks";

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

describe("listTasks query serialization", () => {
  // Goes through the REAL axios instance (only the transport is swapped), so
  // it catches a camelCase param that never gets mapped to its snake_case wire
  // name — something the page-level tests cannot see, since they mock
  // listTasks itself.
  async function capture(params: Parameters<typeof listTasks>[0]) {
    const original = client.defaults.adapter;
    let seen: Record<string, unknown> = {};
    client.defaults.adapter = async (config) => {
      seen = (config.params ?? {}) as Record<string, unknown>;
      return {
        data: {
          tasks: [],
          page: 1,
          page_size: 20,
          total: 0,
          build_artifacts: [],
        },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      };
    };
    try {
      await listTasks(params);
    } finally {
      client.defaults.adapter = original;
    }
    return seen;
  }

  it("sends schedule_id and q using their wire names", async () => {
    const params = await capture({
      page: 2,
      scheduleId: "s1",
      q: "alpha",
    });
    expect(params).toMatchObject({
      page: 2,
      schedule_id: "s1",
      q: "alpha",
    });
  });

  it("omits both keys entirely when unset", async () => {
    const params = await capture({});
    expect(params).not.toHaveProperty("schedule_id");
    expect(params).not.toHaveProperty("q");
  });

  it("omits them for null and empty-string values too", async () => {
    const params = await capture({ scheduleId: null, q: "" });
    expect(params).not.toHaveProperty("schedule_id");
    expect(params).not.toHaveProperty("q");
  });
});
