// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { User } from "../firebase";

// The gate's whole job is to keep the client's idea of "signed in" in step with the server's.
// These pin the path that got that wrong in production: a session aged past
// `session_max_age_days` came back 401, the app showed a sign-in screen, and the Firebase
// session stayed alive underneath — so a reload reproduced the failure forever, under a
// message (`GET /api/me -> 401`) that read as an outage.

const fb = vi.hoisted(() => ({
  watchUser: vi.fn(),
  signOut: vi.fn(async () => {}),
  completeEmailLinkSignIn: vi.fn(async () => false),
  sendEmailSignInLink: vi.fn(async () => {}),
  signInWithProvider: vi.fn(async () => {}),
  rememberSignIn: vi.fn(),
  lastSignIn: vi.fn(() => ""),
  forgetSignIn: vi.fn(),
}));
vi.mock("../firebase", () => fb);

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("../api", async (actual) => ({
  ...(await actual<typeof import("../api")>()),
  api: { get: apiGet, post: vi.fn() },
}));

import { ApiError } from "../api";
import { AuthGate } from "./AuthGate";

const EXPIRED = "signed in more than 7 days ago — please sign in again";
const USER = { email: "tkinkead@prevagroup.com" } as User;

/** Hand back the callback AuthGate registered, so a test can drive auth state changes. */
function signedInAs(user: User | null) {
  let cb: (u: User | null) => void = () => {};
  fb.watchUser.mockImplementation((f: (u: User | null) => void) => {
    cb = f;
    f(user);
    return () => {};
  });
  return { fire: (u: User | null) => cb(u) };
}

beforeEach(() => vi.clearAllMocks());
// Explicit: testing-library only auto-registers cleanup when vitest globals are on, and this
// suite imports its helpers by name. Without it, renders stack and every getByText sees two.
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("AuthGate, when the server rejects the session", () => {
  it("shows the server's sentence, signs out, and pre-fills the address", async () => {
    signedInAs(USER);
    apiGet.mockRejectedValue(new ApiError(401, EXPIRED, EXPIRED));

    render(<AuthGate>app</AuthGate>);

    // The server's words, not the wire summary.
    await waitFor(() => expect(screen.getByText(EXPIRED)).toBeTruthy());
    expect(screen.queryByText(/-> 401/)).toBeNull();

    // The client stops holding a session the backend rejects — otherwise a reload repeats it.
    await waitFor(() => expect(fb.signOut).toHaveBeenCalled());

    // The person has been away a week, not become someone else.
    expect(fb.rememberSignIn).toHaveBeenCalledWith(USER.email);
    const box = screen.getByLabelText("Email address") as HTMLInputElement;
    expect(box.value).toBe(USER.email);
  });

  it("keeps the explanation when its own sign-out fires the auth callback", async () => {
    // The race the phase guard exists for: signOut() triggers watchUser(null), whose handler
    // used to reset the phase unconditionally and wipe the message off the screen.
    const auth = signedInAs(USER);
    apiGet.mockRejectedValue(new ApiError(401, EXPIRED, EXPIRED));

    render(<AuthGate>app</AuthGate>);
    await waitFor(() => expect(screen.getByText(EXPIRED)).toBeTruthy());

    auth.fire(null);

    await waitFor(() => expect(screen.getByText(EXPIRED)).toBeTruthy());
  });

  it("falls back to a plain sentence when there is no detail to show", async () => {
    signedInAs(USER);
    apiGet.mockRejectedValue(new TypeError("Failed to fetch"));

    render(<AuthGate>app</AuthGate>);

    await waitFor(() => expect(screen.getByText(/Couldn't reach the server/)).toBeTruthy());
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
  });
});

describe("AuthGate, on a deliberate sign-out", () => {
  it("forgets the remembered address", async () => {
    signedInAs(USER);
    apiGet.mockResolvedValue({ is_admin: false });

    render(<AuthGate>app</AuthGate>);

    const out = await screen.findByText("Sign out");
    out.click();

    // Unlike an aged-out session, this may be a handover — don't leave the address behind.
    await waitFor(() => expect(fb.forgetSignIn).toHaveBeenCalled());
    expect(fb.signOut).toHaveBeenCalled();
  });
});
