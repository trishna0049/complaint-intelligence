import { useEffect, useState } from "react";
import type { SlaState, SlaView } from "@/api/types";

/** The current time, re-rendered every `ms` (the live countdown). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

const WARNING_RATIO = 0.8;

/** The state right now (the server's state can be a few seconds old): crosses into at_risk / breached live. */
export function liveState(sla: SlaView, now: number): { state: SlaState; remaining: number | null } {
  if (sla.state === "none" || !sla.deadline || !sla.target_seconds) return { state: sla.state, remaining: null };
  if (sla.state === "paused" || sla.state === "met") return { state: sla.state, remaining: sla.remaining_seconds };
  const remaining = (new Date(sla.deadline).getTime() - now) / 1000;
  if (sla.state === "breached" || remaining <= 0) return { state: "breached", remaining };
  const used = 1 - remaining / sla.target_seconds;
  return { state: used >= WARNING_RATIO ? "at_risk" : "running", remaining };
}
