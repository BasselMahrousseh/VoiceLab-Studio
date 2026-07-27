const TOKEN_KEY = "lahja_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** Called when the server reports the session is no longer valid. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

/** Build a URL for browser-loaded resources (audio/download) that cannot send
 * an Authorization header — the token rides in a query param instead. */
export function mediaUrl(path: string): string {
  const token = getToken();
  if (!token) return path;
  return `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

async function handle<T>(resp: Response): Promise<T> {
  if (resp.status === 401 && onUnauthorized) onUnauthorized();
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export function get<T>(url: string): Promise<T> {
  return fetch(url, { headers: authHeaders() }).then((r) => handle<T>(r));
}

export function post<T>(url: string, body?: unknown): Promise<T> {
  return fetch(url, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

/** Consume a newline-delimited JSON response as it arrives. */
export async function streamPost<T>(
  url: string,
  body: unknown,
  onEvent: (event: T) => void,
  signal?: AbortSignal
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    signal,
  });
  if (resp.status === 401 && onUnauthorized) onUnauthorized();
  if (!resp.ok) {
    await handle<never>(resp);
    return;
  }
  if (!resp.body) throw new Error("The browser could not read the generation stream.");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line) as T);
    }
    if (done) break;
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as T);
}

export function patch<T>(url: string, body: unknown): Promise<T> {
  return fetch(url, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

export function upload<T>(url: string, blob: Blob, filename: string, fields: Record<string, string | number> = {}): Promise<T> {
  const form = new FormData();
  form.append("file", blob, filename);
  for (const [k, v] of Object.entries(fields)) form.append(k, String(v));
  return fetch(url, { method: "POST", headers: authHeaders(), body: form }).then((r) => handle<T>(r));
}
