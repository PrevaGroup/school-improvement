// Home Realm Discovery: the user types their email; this table decides which identity
// provider their organization signs in through. Users know their email — they mostly do
// NOT know (or care) whether their employer is "a Google shop" or "a Microsoft shop", and
// asking them to pick a provider button invites exactly the wrong-identity mistake the
// backend bans.
//
// This is the FRONTEND MIRROR of the server's ALLOWED_DOMAIN_PROVIDERS map
// (backend/app/config.py) — routing only, never authorization. The server re-derives
// everything from the verified token: domain allowlisted, email verified, AND
// sign_in_provider matching this same table. Someone who edits this file in DevTools can
// route themselves to any popup they like; the token they come back with still won't pass.
// Keep the two maps in step when an org is added — the deploy checklist in
// backend/DEPLOY.md pairs them.
export const DOMAIN_PROVIDERS: Record<string, string> = {
  "prevagroup.com": "google.com",
  // "gatesfoundation.org": "microsoft.com",  // Phase B: flips on when the Entra app
  //                                          // registration + Identity Platform provider land.
};

export type SignInRoute = { provider: string; email: string } | { error: string };

/** Decide the sign-in route for a typed email. Pure — the unit under test. */
export function routeForEmail(raw: string): SignInRoute {
  const email = raw.trim().toLowerCase();
  const at = email.lastIndexOf("@");
  if (at < 1 || at === email.length - 1) {
    return { error: "Enter your full work email address." };
  }
  const domain = email.slice(at + 1);
  const provider = DOMAIN_PROVIDERS[domain];
  if (!provider) {
    // Mirrors the backend's own wording for an uninvited domain. Saying it here saves an
    // uninvited visitor a pointless provider round-trip; the server still says no if they
    // find a way to sign in anyway.
    return { error: `${domain} isn't on the invite list for this application.` };
  }
  return { provider, email };
}
