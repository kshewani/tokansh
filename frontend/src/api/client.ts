/**
 * HTTP client for the TokANSH Python API. All DRUNIX operations go through the
 * backend; the frontend never talks to the ledger and never simulates it.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

let demoUserId: string | null = null;
export function setDemoUser(id: string | null) { demoUserId = id; }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}
export type ApiResponse<T> = {status: number; data: T; replay: boolean};

export function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID()
    : 'k-' + Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export async function api<T>(path: string, opts: {method?: 'GET' | 'POST' | 'PUT'; body?: unknown; idempotencyKey?: string; signal?: AbortSignal} = {}): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {Accept: 'application/json'};
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (demoUserId) headers['X-Demo-User-Id'] = demoUserId;
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;
  let res: Response;
  try {
    res = await fetch(API_BASE_URL + path, {method: opts.method || 'GET', headers, signal: opts.signal,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body)});
  } catch {
    throw new ApiError(0, 'BACKEND_UNAVAILABLE', 'The TokANSH API cannot be reached. Start the backend and try again.');
  }
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = json?.error || {};
    throw new ApiError(res.status, err.code || 'HTTP_' + res.status, err.message || 'Request failed.', err.details || {});
  }
  return {status: res.status, data: (json?.data ?? json) as T, replay: !!json?.meta?.idempotent_replay};
}
