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
// The fix escapes exactly the tokens marked identifies as raw HTML, and nothing else. Blunter
// alternatives were tried and rejected:
//   - escaping `<` in the source first: breaks fenced code blocks (they render double-escaped,
//     e.g. `&lt;div>`), and formatting is the whole point of this pane;
//   - escaping `>` too: kills Markdown blockquotes;
//   - DOMPurify: correct, but a new runtime dependency to do what six lines do here.
//
// Verified against: <script>, <img onerror>, inline <b>, bold/code, lists, blockquotes, fenced
// code containing HTML, `a < b` in prose, and links — all render correctly, none execute.

const escapeHtml = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const marked = new Marked({
  breaks: true,
  gfm: true,
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
