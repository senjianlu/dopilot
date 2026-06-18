import axios, {
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";
import { clearToken, getToken } from "./token";

// Optional navigation hook, registered by the router after it is created.
// Avoids a static import of the router here (which would create a circular
// import: router -> pages -> api/client -> router).
let onUnauthorized: (() => void) | null = null;

export function registerUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export const client: AxiosInstance = axios.create({
  baseURL: "/api/v1",
});

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
