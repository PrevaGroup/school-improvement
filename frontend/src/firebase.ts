import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  getAuth,
  onAuthStateChanged,
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

// Access rides on an identity the employer can revoke (see the allowlist rationale in
// security.py). prevagroup.com is Workspace-managed, so its Google identities die with
// offboarding. gatesfoundation.org waits for Entra — a personal Google account on a work
// email survives offboarding and is exactly the identity Tim ruled out.
const provider = new GoogleAuthProvider();

/** Google sign-in via popup.
 *
 * Popup rather than redirect, still: redirect flows reload the whole app around the
 * round-trip, and popup UX is what testers expect. The old caveat here (Safari/ITP
 * flakiness from a third-party authDomain) was retired when authDomain moved to our own
 * domain via the /__/* reverse proxy — the handler is first-party now.
 */
export function signInWithGoogle(): Promise<unknown> {
  return signInWithPopup(auth, provider);
}

export function signOut(): Promise<void> {
  return fbSignOut(auth);
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
