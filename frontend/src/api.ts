// The one place the SPA talks to the backend.
//
// Relative paths only — never an absolute URL, never a VITE_API_BASE_URL. FastAPI serves this
// bundle and the API from the same origin in prod; `vite.config.ts` proxies /api in dev. That
// is the invariant (see ../../CLAUDE.md), and it's why no CORS middleware exists anywhere.
//
// It is also the seam where the Identity Platform ID token will be attached at go-live
// (docs/GO_LIVE_PLAN.md §3.5) — one wrapper to change, not N call sites.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** FastAPI's `detail` — the server's own sentence, when it sent one. Undefined for a
     *  network failure or a body that isn't JSON, which is why callers must still cope
     *  with `message` being the wire summary. */
    readonly detail?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // The ONE place the ID token is attached — this is why every call goes through this
  // wrapper. The SDK refreshes the token automatically; signed out -> no header -> the
  // backend 401s -> the AuthGate shows sign-in. Imported lazily so unit tests of pure
  // helpers never touch the Firebase SDK.
  const { idToken } = await import("./firebase");
  const token = await idToken();
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    // A JSON 404 here means a mistyped API path. It is NOT the SPA fallback returning
    // index.html — that can't happen, because /api is a separate namespace from the catch-all.
    // That separation is the whole reason the prefix exists.
    //
    // Read the body for FastAPI's `detail` before throwing. The backend writes sentences
    // meant for the person reading them — "signed in more than 7 days ago — please sign in
    // again" — and this wrapper used to discard every one of them in favour of the wire
    // summary. A routine session expiry then reached the user as `GET /api/me -> 401`,
    // which reads as an outage rather than as an instruction. One place to read it, so
    // every call site can show the server's own words.
    const detail = await res.json().then(
      (b) => (typeof b?.detail === "string" && b.detail.trim() ? b.detail : undefined),
      () => undefined, // empty body, or not JSON at all — the summary is all there is
    );
    const wire = `${init?.method ?? "GET"} /api${path} -> ${res.status}`;
    throw new ApiError(res.status, detail ?? wire, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
