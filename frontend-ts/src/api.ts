// REST + WebSocket access to the backend through the same-origin /backend/<port> proxy.
import type { ServerChoice } from "./types";

export const SERVER_CHOICES: ServerChoice[] = [
  { value: "auto", label: "Auto (failover 8001–8003)", ports: ["8001", "8002", "8003"] },
  { value: "8001", label: "chat-server-1 (8001)", ports: ["8001"] },
  { value: "8002", label: "chat-server-2 (8002)", ports: ["8002"] },
  { value: "8003", label: "chat-server-3 (8003)", ports: ["8003"] },
  { value: "8000", label: "Nginx load balancer (8000)", ports: ["8000"] },
];

let ports = SERVER_CHOICES[0].ports;
let index = 0;

export function setServer(choice: string): void {
  ports = (SERVER_CHOICES.find((c) => c.value === choice) ?? SERVER_CHOICES[0]).ports;
  index = 0;
}
export const currentPort = (): string => ports[index % ports.length];
export const rotateServer = (): string => { index = (index + 1) % ports.length; return currentPort(); };
export const canFailover = (): boolean => ports.length > 1;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function detailText(body: unknown): string | null {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e: { msg?: string }) => e.msg ?? "").filter(Boolean).join("; ");
  return null;
}

export interface RequestOptions {
  method?: string;
  token?: string | null;
  json?: unknown;
  form?: Record<string, string>;
  query?: Record<string, string | number>;
}

/** Request with automatic server failover on network errors / 502. */
export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", token, json, form, query } = opts;
  const qs = query ? "?" + new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)])) : "";
  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) { headers["Content-Type"] = "application/x-www-form-urlencoded"; body = new URLSearchParams(form).toString(); }

  let lastError: ApiError = new ApiError(0, "Cannot reach the chat service.");
  for (let attempt = 0; attempt < ports.length; attempt++) {
    try {
      const res = await fetch(`/backend/${currentPort()}${path}${qs}`, { method, headers, body });
      if (res.status === 502 && canFailover()) { rotateServer(); lastError = new ApiError(502, "Server unreachable"); continue; }
      const text = await res.text();
      let data: unknown = null;
      try { data = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
      if (!res.ok) throw new ApiError(res.status, detailText(data) ?? `HTTP ${res.status}`);
      return data as T;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      lastError = new ApiError(0, "Cannot reach the chat service. Is the frontend server running?");
      if (canFailover()) rotateServer();
    }
  }
  throw lastError;
}

export function openSocket(token: string): WebSocket {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${scheme}://${location.host}/backend/${currentPort()}/ws/chat?token=${encodeURIComponent(token)}`);
}

function tokenPayload(token: string): { sub?: string; exp?: number } | null {
  try { return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); } catch { return null; }
}
export const tokenUserId = (token: string): number | null => {
  const sub = tokenPayload(token)?.sub;
  return sub ? parseInt(sub, 10) : null;
};
export const tokenExpired = (token: string): boolean => {
  const p = tokenPayload(token);
  return !p || (p.exp ? p.exp * 1000 < Date.now() + 5000 : false);
};
