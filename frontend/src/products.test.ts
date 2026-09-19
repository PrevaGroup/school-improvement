import { describe, expect, it } from "vitest";
import { offered, pathFor, placeFromPath, PRODUCTS, sectionsFor } from "./products";

const BOTH = offered(["sip", "writing"]);

describe("which tabs a product shows", () => {
  it("keeps each product's tabs to itself", () => {
    expect(sectionsFor("sip", true)).not.toContain("review");
    expect(sectionsFor("writing", true)).not.toContain("workspace");
  });

  it("adds admin tabs only for admins, and puts Release in writing", () => {
    expect(sectionsFor("writing", false)).toEqual(["folders", "review"]);
    expect(sectionsFor("writing", true)).toEqual(["folders", "review", "release"]);
    expect(sectionsFor("sip", false)).toEqual(["workspace"]);
    expect(sectionsFor("sip", true)).toContain("traces");
  });

  it("names both products the way the UI says them", () => {
    expect(PRODUCTS.sip.label).toBe("School Improvement");
    expect(PRODUCTS.writing.label).toBe("Student Writing");
  });
});

describe("what the server offers", () => {
  it("keeps switcher order and drops names it does not know", () => {
    expect(offered(["writing", "sip", "grades"])).toEqual(["sip", "writing"]);
    expect(offered(undefined)).toEqual([]);
  });
});

describe("where a URL puts you", () => {
  it("honours an exact path", () => {
    expect(placeFromPath("/writing/review", BOTH, false, "sip"))
      .toEqual({ product: "writing", section: "review" });
  });

  it("opens a product's first tab from its bare path", () => {
    expect(placeFromPath("/writing", BOTH, false, "sip"))
      .toEqual({ product: "writing", section: "folders" });
  });

  it("falls back from the root and from unknown paths", () => {
    expect(placeFromPath("/", BOTH, false, "writing"))
      .toEqual({ product: "writing", section: "folders" });
    expect(placeFromPath("/marts/typo", BOTH, false, "sip"))
      .toEqual({ product: "sip", section: "workspace" });
  });

  it("never lands on a product it was not offered", () => {
    expect(placeFromPath("/writing/review", ["sip"], false, "sip"))
      .toEqual({ product: "sip", section: "workspace" });
  });

  it("never lands a non-admin on an admin tab", () => {
    expect(placeFromPath("/writing/release", BOTH, false, "sip"))
      .toEqual({ product: "writing", section: "folders" });
    expect(placeFromPath("/writing/release", BOTH, true, "sip"))
      .toEqual({ product: "writing", section: "release" });
  });

  it("round-trips through the path it writes", () => {
    const place = { product: "writing" as const, section: "review" as const };
    expect(placeFromPath(pathFor(place), BOTH, false, "sip")).toEqual(place);
  });
});
