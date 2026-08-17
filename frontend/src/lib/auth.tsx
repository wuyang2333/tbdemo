import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import http, { TOKEN_KEY, USER_KEY } from "./api";
import type { AuthResponse, AuthUser } from "../types";

type RegisterPayload = {
  username: string;
  password: string;
  nickname?: string;
  inviteCode?: string;
};

type AuthContextValue = {
  user: AuthUser | null;
  login: (username: string, password: string) => Promise<AuthUser>;
  register: (
    payload: RegisterPayload
  ) => Promise<{ pending: true; message: string } | { pending: false; user: AuthUser }>;
  logout: () => void;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => readUser());

  const persist = (token: string, nextUser: AuthUser) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
    setUser(nextUser);
  };

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await http.post<AuthResponse>("/auth/login", { username, password });
    persist(data.token, data.user);
    return data.user;
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    const { data } = await http.post<
      AuthResponse | { ok: true; pending: true; message: string }
    >("/auth/register", {
      username: payload.username,
      password: payload.password,
      nickname: payload.nickname,
      invite_code: payload.inviteCode ?? "",
    });
    if ("pending" in data && data.pending) {
      return { pending: true as const, message: data.message };
    }
    const authData = data as AuthResponse;
    persist(authData.token, authData.user);
    return { pending: false as const, user: authData.user };
  }, []);

  const logout = useCallback(() => {
    http.post("/auth/logout").catch(() => undefined);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    const { data } = await http.get<{ user: AuthUser }>("/auth/me");
    persist(token, data.user);
  }, []);

  const value = useMemo(
    () => ({ user, login, register, logout, refresh }),
    [user, login, register, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
