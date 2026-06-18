import { defineStore } from "pinia";
import { login as loginApi, me as meApi } from "@/api/auth";
import { clearToken, getToken, setToken } from "@/api/token";

interface AuthState {
  token: string | null;
  mode: string;
  username: string | null;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    token: getToken(),
    mode: "off",
    username: null,
  }),
  getters: {
    isAuthenticated: (state): boolean => state.token !== null,
    isAuthOff: (state): boolean => state.mode === "off",
  },
  actions: {
    async login(username: string, password: string): Promise<void> {
      const res = await loginApi(username, password);
      this.mode = res.mode;
      if (res.access_token) {
        this.token = res.access_token;
        setToken(res.access_token);
      }
      this.username = username;
    },
    async fetchMe(): Promise<void> {
      const res = await meApi();
      this.mode = res.mode;
      this.username = res.username;
      if (!res.authenticated) {
        this.token = null;
        clearToken();
      }
    },
    logout(): void {
      this.token = null;
      this.username = null;
      clearToken();
    },
  },
});
