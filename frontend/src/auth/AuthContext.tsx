import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  ApiError,
  fetchMe,
  login as apiLogin,
  setAuthToken,
  setUnauthorizedHandler,
} from "../api/client";
import { AuthContext, type AuthContextValue, type AuthUser } from "./context";

const STORAGE_KEY = "iris.auth";

interface StoredAuth extends AuthUser {
  token: string;
}

function readStoredAuth(): StoredAuth | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredAuth>;
    if (!parsed.token || !parsed.username || !parsed.role) return null;
    return { token: parsed.token, username: parsed.username, role: parsed.role };
  } catch {
    return null;
  }
}

function writeStoredAuth(auth: StoredAuth | null): void {
  if (auth) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Rehydrate from localStorage on load, then re-validate the token against
  // /auth/me in the background (it may have expired or the user may have
  // been deactivated since); log out silently if it's no longer valid.
  useEffect(() => {
    const stored = readStoredAuth();
    if (!stored) {
      setIsLoading(false);
      return;
    }
    setAuthToken(stored.token);
    setToken(stored.token);
    setUser({ username: stored.username, role: stored.role });

    fetchMe()
      .then((me) => setUser({ username: me.username, role: me.role }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          setAuthToken(null);
          writeStoredAuth(null);
          setToken(null);
          setUser(null);
        }
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const response = await apiLogin(username, password);
    const nextAuth: StoredAuth = {
      token: response.access_token,
      username: response.username,
      role: response.role,
    };
    setAuthToken(nextAuth.token);
    writeStoredAuth(nextAuth);
    setToken(nextAuth.token);
    setUser({ username: nextAuth.username, role: nextAuth.role });
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    writeStoredAuth(null);
    setToken(null);
    setUser(null);
  }, []);

  // Any request anywhere in the app can come back 401 once a token goes
  // stale mid-session (expiry, deactivation) — force the same clean logout
  // the initial /auth/me check already does, instead of letting the raw
  // backend error text sit in whatever page triggered the request.
  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, isLoading, login, logout }),
    [user, token, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
