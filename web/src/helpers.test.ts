import { describe, expect, it } from "vitest";
import { relativeTime } from "./time";
import { MAX_IMAGE_BYTES, checkImage } from "./images";
import { escapeCurrency } from "./markdown";

describe("escapeCurrency", () => {
  it("keeps prices from turning into math", () => {
    expect(escapeCurrency("The ball costs $0.05 and the bat $1.05.")).toBe("The ball costs \\$0.05 and the bat \\$1.05.");
  });

  it("handles several prices on one line, including bold ones", () => {
    expect(escapeCurrency("Total: $0.05 + $1.05 = **$1.10** ✓")).toBe("Total: \\$0.05 + \\$1.05 = **\\$1.10** ✓");
  });

  it("keeps inline math that starts with a digit (from a real reply)", () => {
    const text = "At $x = \\pi$: the derivative is $3\\pi^2(0) + \\pi^3(-1) = -\\pi^3$. Same: $\\pi^2(0 - \\pi) = -\\pi^3$.";
    expect(escapeCurrency(text)).toBe(text);
  });

  it("doesn't pair dollars across lines", () => {
    expect(escapeCurrency("It costs $5\nand $x$ is math")).toBe("It costs \\$5\nand $x$ is math");
  });

  it("leaves real math alone", () => {
    expect(escapeCurrency("Let $x$ be the distance.")).toBe("Let $x$ be the distance.");
    expect(escapeCurrency("$$\n2x + 1.00 = 1.10\n$$")).toBe("$$\n2x + 1.00 = 1.10\n$$");
    expect(escapeCurrency("$$2 = \\frac{p^2}{q^2}$$")).toBe("$$2 = \\frac{p^2}{q^2}$$");
  });

  it("doesn't touch code or already-escaped dollars", () => {
    expect(escapeCurrency("Run `echo $1` then:\n```sh\nprice=$5\n```\n")).toBe("Run `echo $1` then:\n```sh\nprice=$5\n```\n");
    expect(escapeCurrency("It costs \\$5.")).toBe("It costs \\$5.");
  });
});

describe("checkImage", () => {
  it("accepts supported images under 5 MB", () => {
    expect(checkImage({ name: "a.png", type: "image/png", size: 1000 })).toBeNull();
  });

  it("rejects other types and big files", () => {
    expect(checkImage({ name: "a.pdf", type: "application/pdf", size: 10 })).toMatch(/JPEG, PNG, GIF, or WebP/);
    expect(checkImage({ name: "big.jpg", type: "image/jpeg", size: MAX_IMAGE_BYTES + 1 })).toMatch(/5 MB/);
  });
});

describe("relativeTime", () => {
  const now = new Date("2026-10-01T12:00:00Z");
  it.each([
    ["2026-10-01T11:59:30Z", "just now"],
    ["2026-10-01T11:45:00Z", "15m ago"],
    ["2026-10-01T09:00:00Z", "3h ago"],
    ["2026-09-28T12:00:00Z", "3d ago"],
  ])("%s -> %s", (iso, expected) => {
    expect(relativeTime(iso, now)).toBe(expected);
  });
});
