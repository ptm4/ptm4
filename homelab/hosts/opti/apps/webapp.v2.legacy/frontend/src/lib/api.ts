// The one fetch wrapper. Mirrors the contracts the v1 app relied on:
//  - JSON in/out, absolute /api paths
//  - non-2xx bodies still carry useful JSON ({ error }) — surfaced via ApiError
//  - a dropped connection or bare 502/504 on /api/agents//api/llama can mean "the
//    thing we restarted is restarting", which callers detect via ApiError.status

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type ApiInit = Omit<RequestInit, 'body'> & { body?: unknown; timeoutMs?: number };

export async function api<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const { body, timeoutMs, headers, ...rest } = init;
  const res = await fetch(path, {
    ...rest,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(headers || {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: timeoutMs ? AbortSignal.timeout(timeoutMs) : undefined,
  });

  const text = await res.text();
  let data: unknown = null;
  try { data = JSON.parse(text); } catch { data = text || null; }

  if (!res.ok) {
    const msg =
      (typeof data === 'object' && data !== null && 'error' in data
        ? String((data as { error: unknown }).error)
        : `HTTP ${res.status}`);
    throw new ApiError(res.status, msg, data);
  }
  return data as T;
}

export const get = <T = unknown>(path: string, timeoutMs?: number) =>
  api<T>(path, { timeoutMs });

export const post = <T = unknown>(path: string, body?: unknown, timeoutMs?: number) =>
  api<T>(path, { method: 'POST', body, timeoutMs });

export const put = <T = unknown>(path: string, body?: unknown, timeoutMs?: number) =>
  api<T>(path, { method: 'PUT', body, timeoutMs });

export const del = <T = unknown>(path: string, timeoutMs?: number) =>
  api<T>(path, { method: 'DELETE', timeoutMs });
