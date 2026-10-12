// Remembers the answer mode and the Tools toggle in this browser. (Sign-in is an
// HttpOnly cookie set by the server, so no key or password is stored here.)
// Storage may be unavailable, so every access is guarded.
import type { Mode } from "./types";

const MODE_KEY = "mx.mode";
const TOOLS_KEY = "mx.tools";

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

/** Tools are on unless turned off in this browser (design.md §17). */
export function loadTools(): boolean {
  try {
    return localStorage.getItem(TOOLS_KEY) !== "off";
  } catch {
    return true;
  }
}

export function saveTools(on: boolean): void {
  try {
    localStorage.setItem(TOOLS_KEY, on ? "on" : "off");
  } catch {
    // ignore
  }
}
