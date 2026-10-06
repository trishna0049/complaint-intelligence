import { createContext, useContext } from "react";
import type { AppNotification } from "@/api/types";

export interface NotificationsState {
  unread: number;
  connected: boolean;
  toasts: AppNotification[];
  dismiss: (id: number) => void;
}

export const NotificationsContext = createContext<NotificationsState>({ unread: 0, connected: false, toasts: [], dismiss: () => {} });

export const useLiveNotifications = () => useContext(NotificationsContext);
