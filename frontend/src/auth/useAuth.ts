import { createContext, useContext } from "react";
import type { Role, User } from "@/api/types";

export type Status = "loading" | "authenticated" | "anonymous";

export interface AuthState {
  status: Status;
  user: User | null;
  /** Set when the session ended on its own (expired / revoked), so the login page can explain why. */
  endedReason: string | null;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  hasRole: (role: Role) => boolean;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
