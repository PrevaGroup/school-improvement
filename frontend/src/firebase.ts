import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  OAuthProvider,
  getAuth,
  isSignInWithEmailLink,
  onAuthStateChanged,
  sendSignInLinkToEmail,
  signInWithEmailLink,
  signInWithPopup,
  signOut as fbSignOut,
  type User,
} from "firebase/auth";

// Identity Platform client config — PUBLIC BY DESIGN, and deliberately committed.
//
// The apiKey is a client identifier, not a credential: it ships in this bundle to every
// browser and is visible in DevTools to anyone who loads the page. Do not move it to Secret
// Manager (the SPA is static files and couldn't read one) and do not treat a git history hit
// on it as a leak. The controls that actually gate access live elsewhere:
//   - the backend verifies every token's signature/issuer/audience (app/security.py),
//   - the domain allowlist decides who is invited (ALLOWED_EMAIL_DOMAINS),
//   - Identity Platform's authorized-domains list decides where sign-in may run.
// authDomain is OUR domain, not <project>.firebaseapp.com: the backend reverse-proxies
// Firebase's reserved /__/* namespace (backend/app/auth_proxy.py), so the OAuth screen says
// "to continue to sip.prevagroup.com" and the auth handler is first-party (no Safari/ITP
// third-party-storage flakiness). Requires https://sip.prevagroup.com/__/auth/handler as an
// authorized redirect URI on the OAuth client — provisioning steps in backend/DEPLOY.md.
// Local dev signs in through the DEPLOYED handler at this domain; that's fine — the popup
// result still returns to whatever origin opened it (localhost included, it's authorized).
const firebaseConfig = {
  apiKey: "AIzaSyAjUQHuedVhmIwP8gDENv88h7bl3-GqQOU",
  authDomain: "sip.prevagroup.com",
  projectId: "school-improvement-501916",
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

/** Sign in via the given Identity Platform provider id ("google.com", "microsoft.com").
 *
 * The provider comes from the email-first routing table (auth-routing.ts) — access rides
 * on an identity the employer can revoke, so each org signs in through ITS OWN IdP and
 * the backend rejects any other arrival (provider binding in security.py). login_hint
 * pre-fills the account chooser with the address the user already typed.
 *
 * Popup rather than redirect, still: redirect flows reload the whole app around the
 * round-trip, and popup UX is what testers expect. The old caveat here (Safari/ITP
 * flakiness from a third-party authDomain) was retired when authDomain moved to our own
 * domain via the /__/* reverse proxy — the handler is first-party now.
 */
export function signInWithProvider(providerId: string, loginHint?: string): Promise<unknown> {
  const provider =
    providerId === "google.com" ? new GoogleAuthProvider() : new OAuthProvider(providerId);
  if (loginHint) provider.setCustomParameters({ login_hint: loginHint });
  return signInWithPopup(auth, provider);
}

export function signOut(): Promise<void> {
  return fbSignOut(auth);
}

// --- Who signed in last, on this device only ------------------------------------------- //
// Sessions age out after `session_max_age_days` (7, backend/app/config.py), so a returning
// user is asked to sign in again on a schedule. Pre-filling the address they last used makes
// that a click instead of a retype — the sign-in they are being asked to repeat is one they
// already completed, and the backend re-derives everything from the token regardless.
//
// This never leaves the browser: not sent to the API, not attached to any activity, not shown
// anywhere in the app — which is exactly what the sign-in screen's privacy note promises, and
// the same footing as EMAIL_KEY below. Cleared on a DELIBERATE sign-out, because that is the
// one case where the next person at this machine may not be the same person.
const LAST_SIGNIN_KEY = "sip.lastSignIn";

/** Remember an address for the next forced sign-in. No-ops on a falsy email. */
export function rememberSignIn(email: string | null | undefined): void {
  try {
    if (email) window.localStorage.setItem(LAST_SIGNIN_KEY, email);
  } catch {
    // Storage disabled or full. Pre-filling is a convenience and never a requirement —
    // failing here must not cost anyone the ability to sign in.
  }
}

/** The address to pre-fill, or "" when there isn't one. */
export function lastSignIn(): string {
  try {
    return window.localStorage.getItem(LAST_SIGNIN_KEY) ?? "";
  } catch {
    return "";
  }
}

/** Forget it — a deliberate sign-out, or an explicit "different account". */
export function forgetSignIn(): void {
  try {
    window.localStorage.removeItem(LAST_SIGNIN_KEY);
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}

// --- Passwordless email magic-link (any email; the click proves ownership) ------------- //
// The confirmation step for "any email can be added": Identity Platform emails a one-time
// link to the EXACT address; clicking it verifies the mailbox (`email_verified: true`) and
// signs the user in. Authorization is still the backend `ALLOWED_EMAILS` gate — owning the
// mailbox is necessary, not sufficient. Requires the Email-Link provider enabled in the
// Identity Platform console (see backend/DEPLOY.md).
const EMAIL_KEY = "sip.emailForSignIn";

/** Send a sign-in link to `email`. The link returns to this same origin (an authorized
 *  domain), where completeEmailLinkSignIn() finishes it. We stash the email so the common
 *  case (link opened in the same browser) needs no re-typing. */
export function sendEmailSignInLink(email: string): Promise<void> {
  window.localStorage.setItem(EMAIL_KEY, email);
  return sendSignInLinkToEmail(auth, email, {
    url: window.location.origin + "/",
    handleCodeInApp: true,
  });
}

/** If the current URL is a completed magic link, finish sign-in. Returns true if it handled
 *  one (and cleans the oobCode params off the URL), false otherwise. Never throws to the
 *  caller for a non-link URL. */
export async function completeEmailLinkSignIn(): Promise<boolean> {
  if (!isSignInWithEmailLink(auth, window.location.href)) return false;
  let email = window.localStorage.getItem(EMAIL_KEY);
  if (!email) {
    // Link opened on a different device/browser than it was requested from — confirm the
    // address (Identity Platform requires the same email that the link was issued for).
    email = window.prompt("Confirm the email this sign-in link was sent to") || "";
  }
  await signInWithEmailLink(auth, email, window.location.href);
  window.localStorage.removeItem(EMAIL_KEY);
  window.history.replaceState({}, "", window.location.origin + "/"); // drop oobCode from the URL
  return true;
}

/** Subscribe to auth state. Returns the unsubscribe fn. `null` = signed out. */
export function watchUser(cb: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth, cb);
}

/** Current ID token, refreshed automatically by the SDK when near expiry.
 *  `null` when signed out — the API then 401s, and the gate shows sign-in. */
export async function idToken(): Promise<string | null> {
  const u = auth.currentUser;
  return u ? u.getIdToken() : null;
}

export type { User };
