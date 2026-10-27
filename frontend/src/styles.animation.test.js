import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// A page-wrapper animation that retains `transform` after it finishes (fill
// mode `forwards`/`both`) makes that wrapper the containing block for every
// `position: fixed` descendant. That pushed the Query Tracer modal and the
// finding drawer off-screen and left the sidebar undimmed.
const STYLESHEETS = ["index.css", "App.css"];

function animateFadeInRules(css) {
  return [...css.matchAll(/\.animate-fade-in\s*\{([^}]*)\}/g)].map((m) => m[1]);
}

describe("page fade-in animation", () => {
  it.each(STYLESHEETS)("%s never retains a transform after the animation ends", (file) => {
    const css = readFileSync(resolve(__dirname, file), "utf8");
    const rules = animateFadeInRules(css);
    expect(rules.length).toBeGreaterThan(0);
    for (const body of rules) {
      expect(body).not.toMatch(/\b(forwards|both)\b/);
      expect(body).not.toMatch(/animation-fill-mode/);
    }
  });
});
