import type { Status, TicketAction } from "@/api/types";

const LABELS: Record<Status, string> = {
  NEW: "New",
  TRIAGED: "Triaged",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In progress",
  WAITING_CUSTOMER: "Waiting on customer",
  ESCALATED: "Escalated",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};

export const statusLabel = (status: Status | string) => LABELS[status as Status] ?? status;

export const ACTION_LABELS: Record<TicketAction, string> = {
  assign: "Assign",
  auto_assign: "Auto-assign",
  start: "Start work",
  wait_customer: "Wait on customer",
  resume: "Customer replied",
  escalate: "Escalate",
  resolve: "Resolve",
  close: "Close",
  reopen: "Reopen",
};
