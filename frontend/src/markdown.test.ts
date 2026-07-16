import { describe, expect, it } from "vitest";

import { renderMarkdown } from "./markdown";

// The chat pane is the only dangerouslySetInnerHTML in the app, and the model is instructed to
// quote plan text VERBATIM — text that originates in district SPSA PDFs we do not author. So
// the untrusted input here is the PDF, not the model.
//
// Two halves, and both must hold at once. Kill the HTML and you break the formatting the pane
// exists for; keep the formatting the lazy way (bare marked.parse) and a crafted PDF can put
// live HTML in the DOM. See markdown.ts for the alternatives that were tried and rejected.

describe("renderMarkdown — raw HTML never survives", () => {
  it.each([
    ["script tag", "<script>alert(1)</script>"],
    ["img onerror", "The plan says: <img src=x onerror=alert(document.domain)>"],
    ["inline tag", "text <b>bold?</b> more"],
    ["svg onload", "<svg onload=alert(1)>"],
    ["iframe", '<iframe src="javascript:alert(1)"></iframe>'],
    ["quoted from a plan", 'Goal 3 states: "<img src=x onerror=fetch(`/api/chat`)>"'],
  ])("neutralises %s", (_label, hostile) => {
    const out = renderMarkdown(hostile);
    // No live element may reach the DOM. Checked on the UNESCAPED text so that an escaped
    // "&lt;script&gt;" (which is the correct, inert output) doesn't read as a failure.
    const unescaped = out.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
    expect(out).not.toMatch(/<script|<img|<svg|<iframe|<b>/i);
    // ...and the text itself is preserved, just inert — the reader still sees what the plan said.
    expect(unescaped).toContain(hostile.slice(hostile.indexOf("<"), hostile.indexOf("<") + 6));
  });
});

describe("renderMarkdown — formatting still works (the point of the pane)", () => {
  it("renders bold and inline code", () => {
    const out = renderMarkdown("**bold** and `code`");
    expect(out).toContain("<strong>bold</strong>");
    expect(out).toContain("<code>code</code>");
  });

  it("renders bullet lists", () => {
    const out = renderMarkdown("- one\n- two");
    expect(out).toContain("<ul>");
    expect(out).toContain("<li>one</li>");
  });

  it("renders blockquotes", () => {
    // Why `>` is deliberately NOT escaped: doing so was the obvious way to kill tags, and it
    // silently breaks every blockquote. A tag must start with `<`, so `>` can stay.
    expect(renderMarkdown("> quoted plan text")).toContain("<blockquote>");
  });

  it("renders headings and links", () => {
    expect(renderMarkdown("### Attendance")).toMatch(/<h3[^>]*>Attendance<\/h3>/);
    expect(renderMarkdown("[CDE](https://cde.ca.gov)")).toContain('href="https://cde.ca.gov"');
  });

  it("keeps fenced code readable when it contains HTML", () => {
    // The regression that killed the simpler fixes: pre-escaping `<` in the source made this
    // render as "&lt;div>" — visibly broken. The renderer-level escape leaves code alone.
    const out = renderMarkdown("```\n<div>x</div>\n```");
    expect(out).toContain("<pre>");
    expect(out).toContain("&lt;div&gt;x&lt;/div&gt;");
    expect(out).not.toContain("&amp;lt;");
  });

  it("handles an angle bracket in ordinary prose", () => {
    expect(renderMarkdown("attendance a < b comparison")).toContain("a &lt; b");
  });

  it("honours breaks:true, as the old UI did", () => {
    expect(renderMarkdown("line one\nline two")).toContain("<br>");
  });
});

describe("renderMarkdown — degenerate input", () => {
  it.each([
    ["null", null],
    ["undefined", undefined],
    ["empty string", ""],
  ])("returns something renderable for %s", (_label, input) => {
    expect(typeof renderMarkdown(input)).toBe("string");
  });
});
