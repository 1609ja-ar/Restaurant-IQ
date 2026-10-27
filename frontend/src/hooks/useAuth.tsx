import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError, setUnauthorizedHandler } from "../lib/api";

export interface AuthUser { id: string; name: string; email: string; is_demo: boolean }
export interface AuthConfig { allow_registration: boolean; demo_available: boolean }

interface AuthState {
  user: AuthUser | null;
  status: "loading" | "ready";
  config: AuthConfig | undefined;
  notice: string | null;                 // e.g. "Your session expired. Please sign in again."
  clearNotice: () => void;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (name: string, email: string, password: string) => Promise<AuthUser>;
  demoLogin: () => Promise<AuthUser>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);
const SESSION_EXPIRED = "Your session expired. Please sign in again.";
const AUTH_PAGES = ["/login", "/signup"];

/** Keeps the signed-in user. The session itself is an HttpOnly cookie set by the backend, so no token is
 *  ever stored in JavaScript. Signing in, out, or losing the session clears the React Query cache so no
 *  previous user's data can stay on screen. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<"loading" | "ready">("loading");
  const [notice, setNotice] = useState<string | null>(null);
  const expiring = useRef(false);

  const config = useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api<AuthConfig>("/auth/config"),
    staleTime: Infinity,
  }).data;

  // Who am I? A 401 here simply means "not signed in".
  useEffect(() => {
    let cancelled = false;
    api<{ user: AuthUser }>("/auth/me")
      .then((r) => { if (!cancelled) setUser(r.user); })
      .catch(() => { if (!cancelled) setUser(null); })
      .finally(() => { if (!cancelled) setStatus("ready"); });
    return () => { cancelled = true; };
  }, []);

  // Any 401 from a protected endpoint: drop the session once, then go to the login page.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (expiring.current) return;
      expiring.current = true;
      qc.clear();
      setUser(null);
      setNotice(SESSION_EXPIRED);
      const path = window.location.pathname;
      if (!AUTH_PAGES.includes(path)) {
        navigate("/login", { replace: true, state: { from: { pathname: path, search: window.location.search } } });
      }
      window.setTimeout(() => { expiring.current = false; }, 500);
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, navigate]);

  const signedIn = useCallback((u: AuthUser) => {
    qc.clear();                      // never show cached data from a previous session
    setNotice(null);
    setUser(u);
    return u;
  }, [qc]);

  const login = useCallback(async (email: string, password: string) =>
    signedIn((await api<{ user: AuthUser }>("/auth/login", { method: "POST", body: { email, password } })).user), [signedIn]);

  const register = useCallback(async (name: string, email: string, password: string) =>
    signedIn((await api<{ user: AuthUser }>("/auth/register", { method: "POST", body: { name, email, password } })).user), [signedIn]);

  const demoLogin = useCallback(async () =>
    signedIn((await api<{ user: AuthUser }>("/auth/demo-login", { method: "POST" })).user), [signedIn]);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;   // the cookie is cleared server-side; ignore network errors here
    }
    qc.clear();
    setUser(null);
    setNotice(null);
    navigate("/login", { replace: true });
  }, [qc, navigate]);

  const clearNotice = useCallback(() => setNotice(null), []);
  const value = useMemo(() => ({ user, status, config, notice, clearNotice, login, register, demoLogin, logout }),
    [user, status, config, notice, clearNotice, login, register, demoLogin, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
