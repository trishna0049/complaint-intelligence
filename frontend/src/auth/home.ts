import type { Role } from "@/api/types";

/** Where each role lands after signing in: admins on the dashboard, agents on their own work. */
export function homeFor(role: Role): string {
  return role === "ADMIN" ? "/" : "/my-work";
}
