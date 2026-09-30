import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_BASE_URL } from "./api";
import { loadConfig, loadMode, saveConfig, saveMode } from "./settings";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

const brokenStorage = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

afterEach(() => vi.unstubAllGlobals());

describe("config", () => {
  it("round-trips a saved config", () => {
    vi.stubGlobal("localStorage", memoryStorage());
    saveConfig({ baseUrl: "http://x.test", apiKey: "k" });
    expect(loadConfig()).toEqual({ baseUrl: "http://x.test", apiKey: "k" });
  });

  it("fills in the default address and rejects configs without a key", () => {
    vi.stubGlobal("localStorage", memoryStorage({ "mx.config": JSON.stringify({ apiKey: "k" }) }));
    expect(loadConfig()).toEqual({ baseUrl: DEFAULT_BASE_URL, apiKey: "k" });

    vi.stubGlobal("localStorage", memoryStorage({ "mx.config": JSON.stringify({ baseUrl: "http://x.test" }) }));
    expect(loadConfig()).toBeNull();
  });

  it("survives missing, corrupt, or blocked storage", () => {
    vi.stubGlobal("localStorage", memoryStorage());
    expect(loadConfig()).toBeNull();
    vi.stubGlobal("localStorage", memoryStorage({ "mx.config": "{not json" }));
    expect(loadConfig()).toBeNull();
    vi.stubGlobal("localStorage", brokenStorage);
    expect(loadConfig()).toBeNull();
    expect(() => saveConfig({ baseUrl: "a", apiKey: "b" })).not.toThrow();
  });
});

describe("mode", () => {
  it("remembers brief and defaults to normal", () => {
    vi.stubGlobal("localStorage", memoryStorage());
    expect(loadMode()).toBe("normal");
    saveMode("brief");
    expect(loadMode()).toBe("brief");
  });

  it("falls back to normal when storage is blocked", () => {
    vi.stubGlobal("localStorage", brokenStorage);
    expect(loadMode()).toBe("normal");
    expect(() => saveMode("brief")).not.toThrow();
  });
});
