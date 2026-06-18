import { beforeEach, describe, expect, it } from "vitest";
import type { InternalAxiosRequestConfig } from "axios";
import { AxiosHeaders } from "axios";
import client from "@/api/client";
import { clearToken, setToken } from "@/api/token";

// Invoke the registered request interceptor directly so we can assert it
// attaches the Authorization header from the persisted token.
function runRequestInterceptors(
  config: InternalAxiosRequestConfig,
): InternalAxiosRequestConfig {
  let result = config;
  for (const handler of (
    client.interceptors.request as unknown as {
      handlers: Array<{
        fulfilled?: (
          c: InternalAxiosRequestConfig,
        ) => InternalAxiosRequestConfig;
      }>;
    }
  ).handlers) {
    if (handler?.fulfilled) {
      result = handler.fulfilled(result);
    }
  }
  return result;
}

function makeConfig(): InternalAxiosRequestConfig {
  return {
    headers: new AxiosHeaders(),
  } as InternalAxiosRequestConfig;
}

describe("api client request interceptor", () => {
  beforeEach(() => {
    clearToken();
  });

  it("adds a bearer Authorization header when a token is present", () => {
    setToken("secret-token");
    const config = runRequestInterceptors(makeConfig());
    expect(config.headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("does not set an Authorization header when no token is present", () => {
    const config = runRequestInterceptors(makeConfig());
    expect(config.headers.get("Authorization")).toBeUndefined();
  });
});
