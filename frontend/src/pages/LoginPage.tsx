import { AlertTriangle, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/http";
import { useAuth } from "@/auth/useAuth";
import { FullPageSpinner } from "@/auth/guards";
import { homeFor } from "@/auth/home";
import { Button, Field, Input } from "@/components/ui";

export function LoginPage() {
  const { status, user, login, endedReason } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : null;

  if (status === "loading") return <FullPageSpinner label="Restoring your session…" />;
  if (status === "authenticated" && user) return <Navigate to={safeNext ?? homeFor(user.role)} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const u = await login(email.trim(), password);
      navigate(safeNext ?? homeFor(u.role), { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-b from-slate-50 to-brand-50/40 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <img src="/favicon.svg" alt="" className="mb-3 h-11 w-11" />
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Complaint Intelligence</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to the support workspace</p>
        </div>
        <form onSubmit={onSubmit} noValidate className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
          {(error || endedReason) && (
            <div className="mb-4 flex gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{error ?? endedReason}</span>
            </div>
          )}
          <div className="space-y-4">
            <Field label="Email" htmlFor="email">
              <Input id="email" type="email" autoComplete="username" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" className="mt-6 w-full" loading={busy} icon={<LogIn className="h-4 w-4" />}>
            Sign in
          </Button>
        </form>
        {import.meta.env.DEV && (
          <p className="mt-4 text-center text-xs text-slate-500">
            Demo accounts are printed by <span className="kbd">scripts\dev.ps1 seed</span> (see README).
          </p>
        )}
      </div>
    </div>
  );
}
