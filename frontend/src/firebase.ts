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
const firebaseConfig = {
  apiKey: "AIzaSyAjUQHuedVhmIwP8gDENv88h7bl3-GqQOU",
  authDomain: "school-improvement-501916.firebaseapp.com",
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
 * Popup rather than redirect: our app origin (run.app / localhost) differs from authDomain
 * (firebaseapp.com), and signInWithRedirect is the flow most broken by third-party-storage
 * partitioning in that split. Popup works in Chromium today; Safari can still be grumpy —
 * accepted for the prototype, and the durable fix (serving /__/auth from our own domain)
 * is a go-live-hardening task, not a today task.
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
