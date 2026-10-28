/** Minimal API client. Same-origin; session cookie; CSRF header on every request. */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function qs(params?: Params): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "finance-tracker" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}${qs(params)}`, { method, headers, body: payload, credentials: "same-origin" });
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    let details: unknown;
    try {
      const j = await res.json();
      code = j.error?.code ?? code;
      message = j.error?.message ?? message;
      details = j.error?.details;
    } catch {
      /* non-JSON error */
    }
    if (res.status === 401 && !path.startsWith("/auth")) window.dispatchEvent(new Event("ft:unauthorized"));
    throw new ApiError(res.status, code, message, details);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown, params?: Params) => request<T>("POST", path, body, params),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string, params?: Params) => request<T>("DELETE", path, undefined, params),
};

/** Download a file from an authenticated GET endpoint. */
export async function download(path: string, params?: Params, fallbackName = "export") {
  const res = await fetch(`/api${path}${qs(params)}`, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "download_failed", "Download failed");
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
