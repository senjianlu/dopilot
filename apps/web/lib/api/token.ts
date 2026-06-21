// Single source of truth for the persisted bearer token.
// Kept separate from the auth hook and the axios client so the request
// interceptor can read the token without importing React state.

const TOKEN_KEY = "dopilot.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // ignore storage errors (e.g. private mode / SSR)
  }
}

export function clearToken(): void {
  setToken(null);
}
