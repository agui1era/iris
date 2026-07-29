import { createContext } from "react";

export interface AuthUser {
  username: string;
  role: string;
}

export interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  /** True only while rehydrating from localStorage on first load. */
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

// Split from AuthContext.tsx/useAuth.ts on purpose: a file that exports a
// component (AuthProvider) or a hook (useAuth) alongside a context object
// breaks Fast Refresh, so the context itself lives here on its own.
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
