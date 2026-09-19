// Two products in one app: School Improvement (SIP) and Student Writing. They share sign-in and
// this shell, and nothing else — each has its own name, colour, tabs and URL space, so a link or a
// bookmark says which product it is for, and nobody has to guess from the screen.
//
// Which products a person is offered comes from the server (`/api/me` -> `products`), and is a UI
// hint only: student work is enforced by the database whatever this file shows.

export type Product = "sip" | "writing";

export type Section =
  | "workspace" | "traces" | "evals" | "results" | "graders"   // School Improvement
  | "folders" | "review" | "release";                          // Student Writing

interface ProductSpec {
  label: string;
  // Everyone with the product. Order is the order the work happens in: for writing, a folder is
  // read and confirmed before there is anything to review.
  sections: Section[];
  // Administrators additionally. Release leads writing's list: whether scores may reach students
  // at all is the question the other screens exist to answer.
  adminSections: Section[];
}

export const PRODUCTS: Record<Product, ProductSpec> = {
  sip: {
    label: "School Improvement",
    sections: ["workspace"],
    adminSections: ["traces", "evals", "results", "graders"],
  },
  writing: {
    label: "Student Writing",
    sections: ["folders", "review"],
    adminSections: ["release"],
  },
};

export const SECTION_LABEL: Record<Section, string> = {
  workspace: "Workspace", traces: "Traces", evals: "Evals", results: "Results",
  graders: "Graders", folders: "Folders", review: "Student work", release: "Release",
};

export const ORDER: Product[] = ["sip", "writing"];

export function isProduct(v: unknown): v is Product {
  return v === "sip" || v === "writing";
}

/** The tabs one product shows this person. */
export function sectionsFor(product: Product, isAdmin: boolean): Section[] {
  const p = PRODUCTS[product];
  return isAdmin ? [...p.sections, ...p.adminSections] : [...p.sections];
}

/** Keep only products the server named, in switcher order. Unknown names are dropped. */
export function offered(fromServer: unknown): Product[] {
  const names = Array.isArray(fromServer) ? fromServer : [];
  return ORDER.filter((p) => names.includes(p));
}

export interface Place {
  product: Product;
  section: Section;
}

/**
 * Where a URL path puts you. `/writing/review` is exact; `/writing` is that product's first tab;
 * anything else — `/`, an old bookmark, a product you are not offered, an admin tab you cannot
 * see — falls back to `fallback`'s first tab rather than to an empty or forbidden screen.
 */
export function placeFromPath(
  path: string, available: Product[], isAdmin: boolean, fallback: Product,
): Place {
  const [first, second] = path.split("/").filter(Boolean);
  const product = isProduct(first) && available.includes(first) ? first : fallback;
  const tabs = sectionsFor(product, isAdmin);
  const section = product === first && tabs.includes(second as Section)
    ? (second as Section) : tabs[0];
  return { product, section };
}

export function pathFor(place: Place): string {
  return `/${place.product}/${place.section}`;
}
