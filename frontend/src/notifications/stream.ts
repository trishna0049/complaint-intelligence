import { API_BASE, getAccessToken, refreshSession } from "@/api/http";

export interface StreamEvent {
  event: string;
  data: unknown;
}

/** Parse a text/event-stream buffer into complete events; returns the events and the unfinished remainder. */
export function parseEvents(buffer: string): { events: StreamEvent[]; rest: string } {
  const events: StreamEvent[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue; // comment / keep-alive
      const [field, ...value] = line.split(":");
      const v = value.join(":").replace(/^ /, "");
      if (field === "event") event = v;
      else if (field === "data") data.push(v);
    }
    if (data.length === 0) continue;
    try {
      events.push({ event, data: JSON.parse(data.join("\n")) });
    } catch {
      events.push({ event, data: data.join("\n") });
    }
  }
  return { events, rest };
}

/**
 * Read the user's notification stream until it ends or `signal` aborts. EventSource can't send headers, so the stream
 * is read with fetch: the access token stays in the Authorization header (never in a URL or a log line). A 401
 * renews the session once. Resolves when the stream closes; the caller reconnects with backoff.
 */
export async function readStream(signal: AbortSignal, onEvent: (e: StreamEvent) => void): Promise<"closed" | "unavailable"> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const token = getAccessToken();
    const res = await fetch(`${API_BASE}/notifications/stream`, {
      headers: { Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      credentials: "same-origin",
      signal,
    });
    if (res.status === 401 && attempt === 0 && (await refreshSession())) continue;
    if (!res.ok || !res.body || !(res.headers.get("content-type") ?? "").startsWith("text/event-stream")) return "unavailable";
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseEvents(buffer);
      buffer = parsed.rest;
      parsed.events.forEach(onEvent);
    }
    return "closed";
  }
  return "unavailable";
}
