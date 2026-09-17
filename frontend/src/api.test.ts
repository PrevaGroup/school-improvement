import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

// `request` lazily imports ./firebase to attach the ID token. Stub it so these tests never
// pull in the Firebase SDK — the same reason the import is lazy in the first place.
vi.mock("./firebase", () => ({ idToken: async () => "test-token" }));

function respondWith(status: number, body: string, contentType = "application/json") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body, { status, headers: { "content-type": contentType } })),
  );
}

afterEach(() => vi.unstubAllGlobals());

/** Await a call that must reject, and hand back the ApiError typed. */
async function failure(p: Promise<unknown>): Promise<ApiError> {
  const e = await p.then(
    () => null,
    (err: unknown) => err,
  );
  if (!(e instanceof ApiError)) throw new Error(`expected an ApiError, got ${String(e)}`);
  return e;
}

// The regression these pin: an expired session reached the user as `GET /api/me -> 401`,
// because this wrapper built its message from the method/path/status and never read the
// body. The backend had written a sentence for that person and it was discarded here.
describe("ApiError carries the server's own words", () => {
  it("uses FastAPI's `detail` as the message, and exposes it separately", async () => {
    const detail = "signed in more than 7 days ago — please sign in again";
    respondWith(401, JSON.stringify({ detail }));

    const err = await failure(api.get("/me"));

    expect(err.status).toBe(401);
    expect(err.detail).toBe(detail);
    expect(err.message).toBe(detail);
  });

  it("falls back to the wire summary when the body is not JSON", async () => {
    respondWith(502, "<html>upstream boom</html>", "text/html");

    const err = await failure(api.get("/me"));

    expect(err.detail).toBeUndefined();
    expect(err.message).toBe("GET /api/me -> 502");
  });

  it("falls back when the body is JSON without a usable `detail`", async () => {
    // A blank detail is not a sentence worth showing — it would render as an empty error.
    respondWith(500, JSON.stringify({ detail: "   " }));

    const err = await failure(api.get("/me"));

    expect(err.detail).toBeUndefined();
    expect(err.message).toBe("GET /api/me -> 500");
  });

  it("names the method it actually used in the fallback", async () => {
    respondWith(404, "", "text/plain");

    const err = await failure(api.post("/nope", { a: 1 }));

    expect(err.message).toBe("POST /api/nope -> 404");
  });
});
