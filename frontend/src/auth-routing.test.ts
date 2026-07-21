import { describe, expect, it } from "vitest";
import { routeForEmail } from "./auth-routing";

// The pure half of the email-first sign-in screen. Two methods:
//   - member-org domains (DOMAIN_PROVIDERS) → their own IdP popup ("sso");
//   - any other email → a passwordless magic link ("emaillink"), whose click proves the
//     mailbox is theirs. Authorization is NOT decided here — the backend allowlist is the
//     gate (backend/app/security.py, with its own tests). These pin the routing contract.
describe("routeForEmail", () => {
  it("routes a member-org domain to its IdP (Google for prevagroup)", () => {
    expect(routeForEmail("tim@prevagroup.com")).toEqual({
      method: "sso",
      provider: "google.com",
      email: "tim@prevagroup.com",
    });
  });

  it("is indifferent to case and whitespace", () => {
    expect(routeForEmail("  Tim@PrevaGroup.COM ")).toEqual({
      method: "sso",
      provider: "google.com",
      email: "tim@prevagroup.com",
    });
  });

  it("sends any non-member email to a magic link — no domain is turned away at the door", () => {
    // gmail, a work domain, an outlook address — all get a one-time link; the BACKEND
    // allowlist decides who actually gets in after the click.
    for (const addr of ["me@gmail.com", "investor@acme.com", "someone@outlook.com"]) {
      expect(routeForEmail(addr)).toEqual({ method: "emaillink", email: addr });
    }
  });

  it("does not gate lookalike domains itself — that's the server's job now", () => {
    // The frontend no longer mirrors the invite list; a lookalike gets a link, then the
    // server refuses the token. Routing is UX only.
    for (const email of [
      "evil@notprevagroup.com",
      "evil@prevagroup.com.attack.io",
      "evil@mail.prevagroup.com",
    ]) {
      expect(routeForEmail(email)).toEqual({ method: "emaillink", email });
    }
  });

  it("asks for a complete address when given fragments", () => {
    for (const bad of ["", "tim", "tim@", "@prevagroup.com", "   "]) {
      const r = routeForEmail(bad);
      expect(r).toHaveProperty("error");
      expect((r as { error: string }).error).toContain("full");
    }
  });
});
