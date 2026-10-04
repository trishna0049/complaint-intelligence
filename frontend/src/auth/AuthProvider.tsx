import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, onSessionExpired, onSessionRenewed, refreshSession, setAccessToken } from "@/api/http";
import type { AuthSession, User } from "@/api/types";
import { AuthContext, type AuthState, type Status } from "./useAuth";

/** Renew the access token this many seconds before it expires (it lives 15 minutes). */
const RENEW_EARLY_S = 60;

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [endedReason, setEndedReason] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const schedule = useCallback((session: AuthSession) => {
    window.clearTimeout(timer.current);
    const ms = Math.max(5, session.expires_in - RENEW_EARLY_S) * 1000;
    timer.current = window.setTimeout(() => void refreshSession(), ms);
  }, []);

  const accept = useCallback(
    (session: AuthSession) => {
      setAccessToken(session.access_token);
      setUser(session.user);
      setStatus("authenticated");
      setEndedReason(null);
      schedule(session);
    },
    [schedule],
  );

  const end = useCallback(
    (reason: string | null) => {
      window.clearTimeout(timer.current);
      setAccessToken(null);
      setUser(null);
      setStatus("anonymous");
      setEndedReason(reason);
      qc.clear();
    },
    [qc],
  );

  // Restore the session from the refresh cookie on first load.
  useEffect(() => {
    let cancelled = false;
    void refreshSession().then((session) => {
      if (cancelled) return;
      if (session) accept(session);
      else end(null);
    });
    return () => {
      cancelled = true;
    };
  }, [accept, end]);

  useEffect(() => onSessionRenewed(accept), [accept]);
  useEffect(() => onSessionExpired(() => end("Your session has ended. Please sign in again.")), [end]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await api<AuthSession>("/auth/login", { method: "POST", body: { email, password }, auth: false });
      qc.clear();
      accept(session);
      return session.user;
    },
    [accept, qc],
  );

  const logout = useCallback(async () => {
    try {
      await api<void>("/auth/logout", { method: "POST", auth: false });
    } finally {
      end(null);
    }
  }, [end]);

  const value = useMemo<AuthState>(
    () => ({ status, user, endedReason, login, logout, hasRole: (role) => user?.role === role }),
    [status, user, endedReason, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
