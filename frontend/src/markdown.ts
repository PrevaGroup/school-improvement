import { Marked } from "marked";

// Render the model's Markdown for the chat pane — WITHOUT letting it emit live HTML.
//
// Why this file exists rather than a bare `marked.parse()`:
//
// The chat reply is Markdown by design (the system prompt asks for light Markdown), and it is
// injected with dangerouslySetInnerHTML. It is tempting to call that safe because "the output
// is from our own model over our own tools". It isn't:
//
//   1. chat's system prompt explicitly tells the model to quote **verbatim plan text** with
//      page cites — quoting source text is the feature.
//   2. That text comes from `plan_extraction`, which comes from district SPSA **PDFs we do not
//      author**.
//   3. `marked` passes raw HTML straight through (the `sanitize` option was removed in v5), so
//      `<img src=x onerror=...>` in a PDF could ride the quote all the way into the DOM.
//
// So the untrusted input is the PDF, not the model, and the model is an obedient courier. The
// diagnostic pane is safe already because JSX escapes its interpolations; this pane is the only
// HTML sink in the app.
//
// The fix has TWO halves, because there are two ways untrusted text reaches the DOM here:
//
//   a. Raw HTML tokens — escaped in the `html` renderer below, and nothing else. Blunter
//      alternatives were tried and rejected:
//        - escaping `<` in the source first: breaks fenced code blocks (they render
//          double-escaped, e.g. `&lt;div>`), and formatting is the whole point of this pane;
//        - escaping `>` too: kills Markdown blockquotes;
//        - DOMPurify: correct, but a new runtime dependency to do what these lines do here.
//
//   b. URL SCHEMES on Markdown-native links/images — `[x](javascript:…)`, `![x](data:…)`.
//      marked removed its `sanitize` option in v5 and does NOT scheme-filter hrefs, so a
//      Markdown link in a quoted PDF is a live `javascript:` anchor the `html` escape never
//      touches (it isn't a raw-HTML token). `walkTokens` neutralises the href/src of any
//      link/image whose scheme isn't explicitly safe, BEFORE the default renderer emits it —
//      version-robust (token shape is stable across marked majors) and it never has to
//      reproduce marked's HTML by hand.
//
// Verified against: <script>, <img onerror>, inline <b>, `[x](javascript:)`, `![x](data:…)`,
// tab-obfuscated `java\tscript:`, bold/code, lists, blockquotes, fenced code containing HTML,
// `a < b` in prose, and ordinary https links — all render correctly, none execute.

const escapeHtml = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// A URL is safe iff it is relative/anchor (no scheme) or carries an explicitly allowed scheme.
// Whitespace and control chars (code <= 0x20) are dropped first: browsers ignore tabs/newlines
// inside a scheme, so `java<TAB>script:` would otherwise slip past. Anything left with a scheme
// not on the allowlist (javascript:, data:, vbscript:, file:, …) is rejected — deny by default.
const isSafeUrl = (href: unknown): boolean => {
  const u = String(href ?? "")
    .split("")
    .filter((c) => c.charCodeAt(0) > 0x20)
    .join("")
    .toLowerCase();
  if (/^(https?:|mailto:|tel:)/.test(u)) return true; // allowed explicit schemes
  return !/^[a-z][a-z0-9+.-]*:/.test(u); // no scheme at all → relative/anchor, safe
};

const marked = new Marked({
  breaks: true,
  gfm: true,
  // Runs on every parsed token before rendering. Mutating the token's href/src here means the
  // stock link/image renderers emit an inert URL, with no HTML to hand-reproduce.
  walkTokens(token: { type?: string; href?: string }) {
    if ((token.type === "link" || token.type === "image") && !isSafeUrl(token.href)) {
      token.href = "#";
    }
  },
  renderer: {
    // marked v12 hands this a string; v13+ hands a token. Accept either so a minor bump can't
    // silently turn escaping back off — the failure mode would be invisible and exploitable.
    html(token: unknown): string {
      if (typeof token === "string") return escapeHtml(token);
      const t = token as { raw?: string; text?: string };
      return escapeHtml(t.raw ?? t.text ?? "");
    },
  },
});

/** Model Markdown -> HTML safe to inject. Never bypass this for chat content. */
export function renderMarkdown(src: string | null | undefined): string {
  return marked.parse(String(src ?? "")) as string;
}
