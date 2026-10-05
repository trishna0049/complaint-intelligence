/**
 * Low-level HTTP client for /api/v1.
 *
 * Auth model: the short-lived access token lives only in memory (never localStorage). The refresh token is an
 * HttpOnly cookie the browser sends to /api/v1/auth/*. When a call returns 401, the client refreshes once (a single
 * in-flight refresh shared by all callers) and retries; if the refresh fails the session is over and listeners are
 * told so the app can show the login page.
 */
import type { AuthSession } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown,
    /** Machine-readable error code from the API, e.g. "llm_rate_limited". */
    public code?: string,
    /** Seconds to wait before retrying (from the Retry-After header), when the API sends one. */
    public retryAfter?: number,
  ) {
    super(message);
  }
}

/** Every request goes to the versioned API. */
export const API_BASE = "/api/v1";

export type Query = Record<string, string | number | boolean | undefined | null>;

let accessToken: string | null = null;
let refreshing: Promise<AuthSession | null> | null = null;
const expiredListeners = new Set<() => void>();
const sessionListeners = new Set<(s: AuthSession) => void>();

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

/** Called when the session can't be renewed (refresh token missing, expired, revoked or reused). */
export function onSessionExpired(fn: () => void) {
  expiredListeners.add(fn);
  return () => void expiredListeners.delete(fn);
}

/** Called whenever a refresh produced a new session (so the UI can keep the user and timer up to date). */
export function onSessionRenewed(fn: (s: AuthSession) => void) {
  sessionListeners.add(fn);
  return () => void sessionListeners.delete(fn);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function doRefresh(): Promise<AuthSession | null> {
  for (let attempt = 0; attempt < 3; attempt++) {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" });
    } catch {
      return null;
    }
    if (res.ok) {
      const session = (await res.json()) as AuthSession;
      accessToken = session.access_token;
      sessionListeners.forEach((fn) => fn(session));
      return session;
    }
    // 409 = another tab rotated the cookie a moment ago; the browser now holds the newer cookie, so try again.
    if (res.status === 409) {
      await sleep(250 * (attempt + 1));
      continue;
    }
    return null;
  }
  return null;
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<AuthSession | null> {
  refreshing ??= doRefresh().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function toError(res: Response): Promise<ApiError> {
  let message = res.statusText || "Request failed";
  let details: unknown;
  let code: string | undefined;
  try {
    const body = await res.json();
    details = body.detail;
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    else if (body.detail && typeof body.detail.message === "string") {
      // Typed errors: {detail: {code, message}}
      message = body.detail.message;
      code = body.detail.code;
    }
  } catch {
    /* not JSON */
  }
  const retry = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, message, details, code, Number.isFinite(retry) && retry > 0 ? retry : undefined);
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; query?: Query; form?: FormData; auth?: boolean; raw?: boolean } = {},
): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(init.query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const url = `${API_BASE}${path}${qs.toString() ? `?${qs}` : ""}`;
  const useAuth = init.auth !== false;

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {};
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (useAuth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
    try {
      return await fetch(url, {
        method: init.method ?? "GET",
        headers,
        body: init.form ?? (init.body !== undefined ? JSON.stringify(init.body) : undefined),
        credentials: "same-origin",
      });
    } catch {
      throw new ApiError(0, "Can't reach the API. Is the backend running?", undefined, "network_error");
    }
  };

  let res = await send();
  if (res.status === 401 && useAuth) {
    const renewed = await refreshSession();
    if (renewed) res = await send();
    else {
      expiredListeners.forEach((fn) => fn());
    }
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  if (init.raw) return (await res.blob()) as T;
  return (await res.json()) as T;
}
