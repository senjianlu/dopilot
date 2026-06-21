import axios, {
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";
import { clearToken, getToken } from "./token";

// Optional navigation hook, registered by the app once a Next router is
// available. Avoids importing next/navigation here (the client module is also
// imported by non-React code paths and unit tests).
let onUnauthorized: (() => void) | null = null;

export function registerUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

// Base URL is same-origin in production (FastAPI serves both the static web
// assets and /api/v1). NEXT_PUBLIC_API_BASE lets a dev point the SPA at a
// separately running server (the old Vite dev proxy is gone with static export).
const baseURL = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

export const client: AxiosInstance = axios.create({ baseURL });

// Request interceptor: attach the bearer token when present.
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// Response interceptor: on 401 clear the token and bounce to /login.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearToken();
      if (onUnauthorized) {
        onUnauthorized();
      }
    }
    return Promise.reject(error);
  },
);

export default client;
