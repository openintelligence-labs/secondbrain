// Thin client over the SecondBrain HTTP gateway.
// Single source of truth for endpoint paths + types.

const BASE =
  (import.meta as any).env?.VITE_SECONDBRAIN_BASE ?? "http://127.0.0.1:7821";

export interface Hit {
  chunk_uid: string;
  capture_id: string;
  chunk_index: number;
  snippet: string;
  rrf_score: number;
  bm25_rank: number | null;
  dense_rank: number | null;
}
export interface SearchResponse { hits: Hit[]; }

export interface Event {
  memory_id: string;
  content: string;
  valid_from: string | null;
  importance: number;
}
export interface TimelineResponse { events: Event[]; }

export interface DigestResponse {
  period: string;
  period_start: string;
  themes: string[];
  broken_promises: string[];
  suggested_followups: string[];
  cited: string[];
  importance_sum: number;
}

export interface Commitment {
  id: string;
  content: string;
  due_at: string | null;
  status: string;
  owner_pid: string | null;
}
export interface CommitmentsResponse { commitments: Commitment[]; }

export interface StatusResponse {
  running: boolean;
  metrics?: {
    seen: number;
    persisted: number;
    by_gate: Record<string, number>;
    ax_text_ratio: number;
    paused?: boolean;
  };
  ts?: string;
}

export interface AuditEntry {
  id: number;
  ts: number;
  actor: string;
  action: string;
  query: string | null;
  cited: string[];
  detail: Record<string, any>;
}
export interface AuditLogResponse { entries: AuditEntry[]; }

export interface LLMConfigResponse {
  provider: string | null;
  model: string | null;
  base_url: string | null;
  api_key_set: boolean;
  sdk_state: string;
  description: string;
}

async function post<T>(path: string, body: object): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`${path} ${r.status}: ${text}`);
  }
  return r.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => get<{ ok: boolean }>("/health"),
  status: () => get<StatusResponse>("/status"),
  search: (query: string, limit = 25) =>
    post<SearchResponse>("/search", { query, limit }),
  timeline: (startIso: string, endIso: string) =>
    post<TimelineResponse>("/timeline", { start: startIso, end: endIso }),
  who: (name: string) =>
    post<{ person_id: string; facts: Event[] }>("/who", { name }),
  digest: (date: string, period: "day" | "week" | "month" = "day") =>
    post<DigestResponse>("/digest", { date, period }),
  commitments: (status: "open" | "done" | "broken" = "open") =>
    post<CommitmentsResponse>("/commitments", { status }),
  forget: (capture_id: string | undefined, reason: string, entity_id?: string) =>
    post<{ deleted: number }>("/forget", { capture_id, entity_id, reason }),
  addNote: (text: string, tags: string[] = []) =>
    post<{ memory_id: string }>("/add-note", { text, tags }),
  auditLog: (limit = 200) => get<AuditLogResponse>(`/audit-log?limit=${limit}`),
  llmConfig: () => get<LLMConfigResponse>("/llm-config"),
  daemonControl: (action: "pause" | "resume") =>
    post<{ ok: boolean; state?: string; reason?: string }>("/daemon", { action }),
};
