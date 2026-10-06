import clsx from "clsx";
import { AlarmClock, ArrowUpCircle, Bell, CheckCheck, UserPlus, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotificationList } from "@/api/client";
import type { AppNotification } from "@/api/types";
import { Spinner } from "@/components/ui";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useLiveNotifications } from "@/notifications/context";

const ICON: Record<string, ReactNode> = {
  ticket_assigned: <UserPlus className="h-4 w-4" />,
  ticket_escalated: <ArrowUpCircle className="h-4 w-4" />,
  sla_warning: <AlarmClock className="h-4 w-4" />,
  sla_breached: <AlarmClock className="h-4 w-4" />,
};
const SEVERITY = {
  info: { ring: "bg-brand-50 text-brand-700", label: "Info" },
  warning: { ring: "bg-amber-50 text-amber-700", label: "Warning" },
  critical: { ring: "bg-rose-50 text-rose-700", label: "Critical" },
} as const;

export function NotificationIcon({ n }: { n: AppNotification }) {
  const s = SEVERITY[n.severity] ?? SEVERITY.info;
  return (
    <span className={clsx("flex h-8 w-8 shrink-0 items-center justify-center rounded-full", s.ring)} title={s.label}>
      {ICON[n.type] ?? <Bell className="h-4 w-4" />}
      <span className="sr-only">{s.label}</span>
    </span>
  );
}

/** Header bell: live unread count, the latest notifications, mark one / all as read. */
export function NotificationBell() {
  const { unread } = useLiveNotifications();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className="relative rounded-md p-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900">
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-rose-600 px-1 text-center text-[10px] font-semibold leading-[18px] text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && <BellPanel onClose={() => setOpen(false)} />}
    </div>
  );
}

function BellPanel({ onClose }: { onClose: () => void }) {
  const list = useNotificationList(false, 8);
  const markAll = useMarkAllNotificationsRead();
  return (
    <div className="absolute right-0 z-30 mt-2 w-96 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl" role="dialog" aria-label="Notifications">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <p className="text-sm font-semibold text-slate-900">Notifications</p>
        <button className="flex items-center gap-1 text-xs text-brand-600 hover:underline disabled:opacity-50" disabled={markAll.isPending}
          onClick={() => markAll.mutate(undefined)}>
          <CheckCheck className="h-3.5 w-3.5" /> Mark all read
        </button>
      </div>
      {list.isLoading ? <div className="flex justify-center p-6"><Spinner className="h-5 w-5" /></div>
        : !list.data?.items?.length ? <p className="px-4 py-6 text-center text-sm text-slate-500">Nothing yet.</p>
          : <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">{list.data.items.map((n) => <NotificationRow key={n.id} n={n} compact onOpen={onClose} />)}</ul>}
      <Link to="/notifications" onClick={onClose} className="block border-t border-slate-100 px-4 py-2 text-center text-xs text-brand-600 hover:bg-slate-50">
        All notifications
      </Link>
    </div>
  );
}

export function NotificationRow({ n, compact = false, onOpen }: { n: AppNotification; compact?: boolean; onOpen?: () => void }) {
  const markRead = useMarkNotificationRead();
  const navigate = useNavigate();
  function open() {
    if (!n.read_at) markRead.mutate(n.id);
    onOpen?.();
    if (n.ticket_id) navigate(`/tickets/${n.ticket_id}`);
  }
  return (
    <li className={clsx("flex gap-3 px-4 py-3", !n.read_at && "bg-brand-50/40")}>
      <NotificationIcon n={n} />
      <button className="min-w-0 flex-1 text-left" onClick={open}>
        <p className={clsx("text-sm text-slate-900", !n.read_at && "font-semibold")}>{n.title}</p>
        <p className={clsx("text-xs text-slate-600", compact && "line-clamp-2")}>{n.message}</p>
        <p className="mt-0.5 text-[11px] text-slate-400" title={fmtDateTime(n.created_at)}>{fmtRelative(n.created_at)}</p>
      </button>
      {!n.read_at && !compact && (
        <button className="self-start text-xs text-brand-600 hover:underline" onClick={() => markRead.mutate(n.id)}>Mark read</button>
      )}
    </li>
  );
}

/** New notifications pop up bottom-right for a few seconds (warning / critical in their colours, with a label). */
export function Toaster() {
  const { toasts, dismiss } = useLiveNotifications();
  const navigate = useNavigate();
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2" role="region" aria-label="New notifications" aria-live="polite">
      {toasts.map((n) => (
        <div key={n.id} role="status" className={clsx("flex gap-3 rounded-lg border bg-white p-3 shadow-lg",
          n.severity === "critical" ? "border-rose-200" : n.severity === "warning" ? "border-amber-200" : "border-slate-200")}>
          <NotificationIcon n={n} />
          <button className="min-w-0 flex-1 text-left" onClick={() => { dismiss(n.id); if (n.ticket_id) navigate(`/tickets/${n.ticket_id}`); }}>
            <p className="text-sm font-semibold text-slate-900">{n.title}</p>
            <p className="line-clamp-2 text-xs text-slate-600">{n.message}</p>
          </button>
          <button aria-label="Dismiss" className="self-start text-slate-400 hover:text-slate-700" onClick={() => dismiss(n.id)}><X className="h-4 w-4" /></button>
        </div>
      ))}
    </div>
  );
}
