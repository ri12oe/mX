// Phone layout rules for the panels added in Phase 2 (design.md §19).
// @ts-expect-error vitest runs in Node; the web tsconfig doesn't include Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const phone = css.slice(css.indexOf("@media (max-width: 960px)"));

describe("phone width", () => {
  it("keeps tool chips, sources, and the memory card inside a narrow screen", () => {
    expect(phone).toContain(".memory-card");
    expect(phone).toContain(".sources");
    expect(phone).toContain(".tool-step-label");
    expect(phone).toContain(".memory-panel");
    expect(phone).toContain(".cost-panel");
  });
});
