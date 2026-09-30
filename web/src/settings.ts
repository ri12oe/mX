// Remembers the answer mode in this browser. (Sign-in is an HttpOnly cookie
// set by the server, so no key or password is stored here.) Storage may be
// unavailable, so every access is guarded.
import type { Mode } from "./types";

const MODE_KEY = "mx.mode";

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
