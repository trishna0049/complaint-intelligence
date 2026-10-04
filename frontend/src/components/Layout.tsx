import clsx from "clsx";
import { BarChart3, Bot, Inbox, Plus } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useHealth } from "@/api/client";

const NAV = [
  { to: "/", label: "Dashboard", icon: BarChart3, end: true },
  { to: "/tickets", label: "Tickets", icon: Inbox, end: true },
  { to: "/tickets/new", label: "New ticket", icon: Plus, end: true },
];

export function Layout() {
  const health = useHealth();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-6 px-6">
          <div className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <span className="text-sm font-semibold text-slate-900">Complaint Intelligence</span>
          </div>
          <nav className="flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                  )
                }
              >
                <n.icon className="h-4 w-4" />
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-1.5 text-xs text-slate-500 md:flex" title="Models in use">
            <Bot className="h-3.5 w-3.5" />
            {health.data ? (
              <span>
                {health.data.classifier ?? "classifier not trained"} · LLM: {health.data.llm_provider}
              </span>
            ) : health.isError ? (
              <span className="text-rose-600">API unreachable</span>
            ) : (
              <span>connecting…</span>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
