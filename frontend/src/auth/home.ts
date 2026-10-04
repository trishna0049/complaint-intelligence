import type { Role } from "@/api/types";

/** Where each role lands after signing in: admins on the dashboard, agents on the ticket queue. */
export function homeFor(role: Role): string {
  return role === "ADMIN" ? "/" : "/tickets";
}
