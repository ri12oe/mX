// Remembers the API URL, key, and mode in this browser (localStorage).
// Fine for a personal app on your own machine; anyone with access to this
// browser profile can read the key. Storage may be unavailable, so every
// access is guarded.
import { DEFAULT_BASE_URL, type ApiConfig } from "./api";
import type { Mode } from "./types";

const CONFIG_KEY = "mx.config";
const MODE_KEY = "mx.mode";

export function loadConfig(): ApiConfig | null {
  try {
    const saved = JSON.parse(localStorage.getItem(CONFIG_KEY) ?? "null");
    if (saved && typeof saved.apiKey === "string" && saved.apiKey) {
      return { baseUrl: saved.baseUrl || DEFAULT_BASE_URL, apiKey: saved.apiKey };
    }
  } catch {
    // unavailable or corrupt: fall through
  }
  return null;
}

export function saveConfig(config: ApiConfig): void {
  try {
    localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
  } catch {
    // not persisted; still works for this session
  }
}

export function loadMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === "brief" ? "brief" : "normal";
  } catch {
    return "normal";
  }
}

export function saveMode(mode: Mode): void {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    // ignore
  }
}
