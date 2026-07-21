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

// Two sign-in methods:
//   - "sso"        → an org's own IdP popup (provider set), for domains in DOMAIN_PROVIDERS.
//     Access rides a revocable org identity — the intended path for member organizations.
//   - "emaillink" → a passwordless magic link to that exact address, for ANY other email.
//     The click proves mailbox ownership; the backend ALLOWED_EMAILS gate is still what
//     authorizes them. Routing only, never authorization — the server re-derives everything.
export type SignInRoute =
  | { method: "sso"; provider: string; email: string }
  | { method: "emaillink"; email: string }
  | { error: string };

/** Decide the sign-in route for a typed email. Pure — the unit under test. */
export function routeForEmail(raw: string): SignInRoute {
  const email = raw.trim().toLowerCase();
  const at = email.lastIndexOf("@");
  if (at < 1 || at === email.length - 1) {
    return { error: "Enter your full work email address." };
  }
  const domain = email.slice(at + 1);
  const provider = DOMAIN_PROVIDERS[domain];
  if (provider) return { method: "sso", provider, email };
  // Everyone else gets a magic link to their exact address — no domain is turned away at the
  // door; the backend allowlist decides who actually gets in after the click.
  return { method: "emaillink", email };
}
