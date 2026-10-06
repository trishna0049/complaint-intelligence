import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import type { AppNotification } from "@/api/types";
import { useAuth } from "@/auth/useAuth";
import { NotificationsContext } from "@/notifications/context";
import { readStream } from "@/notifications/stream";

const TOAST_MS = 7000;
const MAX_BACKOFF_MS = 30_000;

/** Keeps one live notification stream open while signed in: unread count for the bell, toasts for new alerts. */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [unread, setUnread] = useState(0);
  const [connected, setConnected] = useState(false);
  const [toasts, setToasts] = useState<AppNotification[]>([]);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    let backoff = 1000;
    let timer: number | undefined;

    async function connect() {
      try {
        const result = await readStream(controller.signal, (e) => {
          if (e.event === "ready" || e.event === "unread") {
            setUnread((e.data as { unread: number }).unread);
            setConnected(true);
            backoff = 1000;
            if (e.event === "unread") void qc.invalidateQueries({ queryKey: ["notifications"] });
          } else if (e.event === "notification") {
            const n = e.data as AppNotification;
            setUnread((u) => u + 1);
            setToasts((t) => [n, ...t].slice(0, 4));
            window.setTimeout(() => dismiss(n.id), TOAST_MS);
            void qc.invalidateQueries({ queryKey: ["notifications"] });
            if (n.ticket_id) void qc.invalidateQueries({ queryKey: ["ticket", n.ticket_id] });
          }
        });
        if (result === "unavailable") backoff = MAX_BACKOFF_MS;
      } catch {
        /* network error or abort: reconnect below */
      }
      setConnected(false);
      if (controller.signal.aborted) return;
      timer = window.setTimeout(() => void connect(), backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    }

    void connect();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      setConnected(false);
    };
  }, [user, qc, dismiss]);

  const value = useMemo(() => ({ unread, connected, toasts, dismiss }), [unread, connected, toasts, dismiss]);
  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
}
