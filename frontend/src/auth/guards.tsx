import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { Role } from "@/api/types";
import { Card, EmptyState } from "@/components/ui";
import { useAuth } from "./useAuth";
import { ShieldAlert } from "lucide-react";

export function FullPageSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50" role="status">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
        {label}
      </div>
    </div>
  );
}

/** Only signed-in users get past this; others go to /login and come back afterwards. */
export function RequireAuth({ children }: { children?: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <FullPageSpinner label="Restoring your session…" />;
  if (status === "anonymous") {
    const next = location.pathname + location.search;
    return <Navigate to={next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login"} replace />;
  }
  return children ? <>{children}</> : <Outlet />;
}

/** Role gate inside the app shell. The API enforces the same rule; this only avoids showing a broken page. */
export function RequireRole({ role, children }: { role: Role; children?: ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== role) {
    return (
      <Card>
        <EmptyState
          icon={<ShieldAlert className="h-6 w-6" />}
          title="You don't have access to this page"
          description={`This page is available to the ${role === "ADMIN" ? "Admin" : "Agent"} role only.`}
        />
      </Card>
    );
  }
  return children ? <>{children}</> : <Outlet />;
}
