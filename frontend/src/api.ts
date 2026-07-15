// The one place the SPA talks to the backend.
//
// Relative paths only — never an absolute URL, never a VITE_API_BASE_URL. FastAPI serves this
// bundle and the API from the same origin in prod; `vite.config.ts` proxies /api in dev. That
// is the invariant (see ../../CLAUDE.md), and it's why no CORS middleware exists anywhere.
//
// It is also the seam where the GCIP ID token will be attached at go-live
// (docs/GO_LIVE_PLAN.md §3.5) — one wrapper to change, not N call sites.

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  if (!res.ok) {
    // A JSON 404 here means a mistyped API path. It is NOT the SPA fallback returning
    // index.html — that can't happen, because /api is a separate namespace from the catch-all.
    // That separation is the whole reason the prefix exists.
    throw new ApiError(res.status, `${init?.method ?? "GET"} /api${path} -> ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
