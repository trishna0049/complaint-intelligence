import clsx from "clsx";
import { BarChart3, Bot, Inbox, LogOut, Menu, Plus, Shapes, Users, UsersRound, X } from "lucide-react";
import { useState, type ComponentType } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useHealth } from "@/api/client";
import type { Role } from "@/api/types";
import { useAuth } from "@/auth/useAuth";
import { Avatar, Badge } from "@/components/ui";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  end?: boolean;
  roles?: Role[];
}

const SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Workspace",
    items: [
      { to: "/", label: "Dashboard", icon: BarChart3, end: true, roles: ["ADMIN"] },
      { to: "/tickets", label: "Ticket queue", icon: Inbox, end: true },
      { to: "/tickets/new", label: "Create ticket", icon: Plus, end: true },
    ],
  },
  {
    title: "Admin",
    items: [
      { to: "/admin/users", label: "Users", icon: Users, roles: ["ADMIN"] },
      { to: "/admin/teams", label: "Teams", icon: UsersRound, roles: ["ADMIN"] },
      { to: "/admin/categories", label: "Categories", icon: Shapes, roles: ["ADMIN"] },
    ],
  },
];

export function Layout() {
  const { user, logout } = useAuth();
  const health = useHealth();
  const [open, setOpen] = useState(false);
  const role = user?.role ?? "AGENT";
  const sections = SECTIONS.map((s) => ({ ...s, items: s.items.filter((i) => !i.roles || i.roles.includes(role)) })).filter(
    (s) => s.items.length > 0,
  );

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2 border-b border-slate-200 px-4">
        <img src="/favicon.svg" alt="" className="h-7 w-7" />
        <span className="text-sm font-semibold text-slate-900">Complaint Intelligence</span>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{section.title}</p>
            <ul className="space-y-0.5">
              {section.items.map((n) => (
                <li key={n.to}>
                  <NavLink
                    to={n.to}
                    end={n.end}
                    onClick={() => setOpen(false)}
                    className={({ isActive }) =>
                      clsx(
                        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                        isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                      )
                    }
                  >
                    <n.icon className="h-4 w-4" />
                    {n.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-slate-200 px-4 py-3 text-[11px] text-slate-500" title="Models in use">
        <div className="flex items-center gap-1.5">
          <Bot className="h-3.5 w-3.5 shrink-0" />
          {health.data ? (
            <span className="truncate">{health.data.classifier ?? "classifier not trained"} · LLM: {health.data.llm_provider}</span>
          ) : health.isError ? (
            <span className="text-rose-600">API unreachable</span>
          ) : (
            <span>connecting…</span>
          )}
        </div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-slate-200 bg-white lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-white shadow-xl">{sidebar}</aside>
        </div>
      )}
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur lg:px-6">
        <button className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden" aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((o) => !o)}>
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
        <div className="ml-auto flex items-center gap-3">
          {user && (
            <div className="flex items-center gap-2" data-testid="user-menu">
              <Avatar name={user.name} size="sm" />
              <div className="hidden text-right leading-tight sm:block">
                <p className="text-sm font-medium text-slate-900">{user.name}</p>
                <p className="text-[11px] text-slate-500">{user.team?.name ?? (user.role === "ADMIN" ? "All teams" : "No team")}</p>
              </div>
              <Badge tone={user.role === "ADMIN" ? "violet" : "slate"}>{user.role === "ADMIN" ? "Admin" : "Agent"}</Badge>
            </div>
          )}
          <button onClick={() => void logout()} className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-900">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-6 lg:px-6">
        <Outlet />
      </main>
    </div>
  );
}
