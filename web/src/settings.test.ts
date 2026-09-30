import { afterEach, describe, expect, it, vi } from "vitest";
import { loadMode, saveMode } from "./settings";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("mode", () => {
  it("remembers brief and defaults to normal", () => {
    vi.stubGlobal("localStorage", memoryStorage());
    expect(loadMode()).toBe("normal");
    saveMode("brief");
    expect(loadMode()).toBe("brief");
  });

  it("falls back to normal when storage is blocked", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(loadMode()).toBe("normal");
    expect(() => saveMode("brief")).not.toThrow();
  });
});
