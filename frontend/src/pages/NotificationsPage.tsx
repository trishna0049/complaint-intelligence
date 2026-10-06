import clsx from "clsx";
import { Bell, CheckCheck } from "lucide-react";
import { useState } from "react";
import { useMarkAllNotificationsRead, useNotificationList, useNotificationPreferences, useSetNotificationPreferences } from "@/api/client";
import { NotificationRow } from "@/components/Notifications";
import { Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { useLiveNotifications } from "@/notifications/context";

export function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const list = useNotificationList(unreadOnly, 50);
  const markAll = useMarkAllNotificationsRead();
  const prefs = useNotificationPreferences();
  const setPrefs = useSetNotificationPreferences();
  const { connected, unread } = useLiveNotifications();

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Assignments, escalations and SLA alerts — live while this tab is open."
        actions={<Button variant="secondary" icon={<CheckCheck className="h-4 w-4" />} loading={markAll.isPending} disabled={unread === 0}
          onClick={() => markAll.mutate(undefined)}>Mark all read</Button>}
      />
      <Card className="mb-4 flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
        <span className="flex items-center gap-2 text-slate-600">
          <span className={clsx("h-2 w-2 rounded-full", connected ? "bg-emerald-500" : "bg-slate-300")} aria-hidden />
          {connected ? "Live updates on" : "Reconnecting to live updates…"}
        </span>
        <label className="flex items-center gap-2 text-slate-700">
          <input type="checkbox" className="rounded text-brand-600" checked={prefs.data?.email ?? true} disabled={!prefs.data || setPrefs.isPending}
            onChange={(e) => setPrefs.mutate(e.target.checked)} />
          Also e-mail me escalations and SLA alerts
        </label>
      </Card>
      <Card>
        <div className="flex gap-1 border-b border-slate-100 px-3 pt-2" role="tablist" aria-label="Notification filter">
          {[["all", "All"], ["unread", `Unread${unread ? ` (${unread})` : ""}`]].map(([id, label]) => (
            <button key={id} role="tab" aria-selected={unreadOnly === (id === "unread")} onClick={() => setUnreadOnly(id === "unread")}
              className={clsx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", unreadOnly === (id === "unread") ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
              {label}
            </button>
          ))}
        </div>
        {list.error ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : list.isLoading || !list.data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : list.data.items.length === 0 ? (
          <EmptyState title={unreadOnly ? "All caught up" : "No notifications yet"} icon={<Bell className="h-6 w-6" />} />
        ) : (
          <ul className="divide-y divide-slate-100" aria-label="Notifications list">{list.data.items.map((n) => <NotificationRow key={n.id} n={n} />)}</ul>
        )}
      </Card>
    </>
  );
}
