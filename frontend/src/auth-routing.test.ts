import { describe, expect, it } from "vitest";
import { routeForEmail } from "./auth-routing";

// The pure half of the email-first sign-in screen. The security-relevant version of this
// logic lives server-side (domain + provider binding in backend/app/security.py, with its
// own tests); these pin the UX contract — right popup for invited domains, honest message
// for everyone else.
describe("routeForEmail", () => {
  it("routes a prevagroup address to Google", () => {
    expect(routeForEmail("tim@prevagroup.com")).toEqual({
      provider: "google.com",
      email: "tim@prevagroup.com",
    });
  });

  it("is indifferent to case and whitespace", () => {
    expect(routeForEmail("  Tim@PrevaGroup.COM ")).toEqual({
      provider: "google.com",
      email: "tim@prevagroup.com",
    });
  });

  it("tells an uninvited domain it isn't invited — before any popup", () => {
    const r = routeForEmail("someone@gmail.com");
    expect(r).toHaveProperty("error");
    expect((r as { error: string }).error).toContain("gmail.com");
    expect((r as { error: string }).error).toContain("invite list");
  });

  it("rejects lookalike domains exactly like the server does", () => {
    for (const email of [
      "evil@notprevagroup.com",
      "evil@prevagroup.com.attack.io",
      "evil@mail.prevagroup.com",
    ]) {
      expect(routeForEmail(email)).toHaveProperty("error");
    }
  });

  it("asks for a complete address when given fragments", () => {
    for (const bad of ["", "tim", "tim@", "@prevagroup.com", "   "]) {
      const r = routeForEmail(bad);
      expect(r).toHaveProperty("error");
      expect((r as { error: string }).error).toContain("full work email");
    }
  });
});
