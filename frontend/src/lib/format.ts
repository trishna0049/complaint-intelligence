import { formatDistanceToNowStrict, format } from "date-fns";

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return format(new Date(iso), "d MMM yyyy, HH:mm");
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return format(new Date(iso), "d MMM yyyy");
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${formatDistanceToNowStrict(new Date(iso))} ago`;
}

export function fmtInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** "1h 05m", "4m 12s", "2d 3h" */
export function fmtDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(Math.abs(totalSeconds)));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

export function fmtMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  if (minutes < 60 * 24) return `${(minutes / 60).toFixed(minutes % 60 === 0 ? 0 : 1)} h`;
  return `${(minutes / 1440).toFixed(minutes % 1440 === 0 ? 0 : 1)} d`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}
