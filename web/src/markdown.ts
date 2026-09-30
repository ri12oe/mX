// Text fixes applied before rendering mX's markdown.

const CODE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g;

/**
 * Escape `$` signs that aren't inline math, so prices like "$0.05 + $1.05"
 * don't get paired into an equation. Uses Pandoc's rule for inline math:
 * the opening `$` is followed by a non-space, and the closing `$` (on the same
 * line) is preceded by a non-space and not followed by a digit. Any `$` without
 * such a partner is literal. `$$...$$` display math and code are left untouched.
 */
export function escapeCurrency(text: string): string {
  return text
    .split(CODE)
    .map((part, i) => (i % 2 === 1 ? part : escapeLooseDollars(part)))
    .join("");
}

function escapeLooseDollars(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\") {
      out += text.slice(i, i + 2); // keep escapes such as \$ as they are
      i += 2;
    } else if (ch !== "$") {
      out += ch;
      i += 1;
    } else if (text[i + 1] === "$") {
      const end = text.indexOf("$$", i + 2); // display math: copy through its closing $$
      const stop = end === -1 ? i + 2 : end + 2;
      out += text.slice(i, stop);
      i = stop;
    } else {
      const close = findInlineClose(text, i);
      if (close === -1) {
        out += "\\$";
        i += 1;
      } else {
        out += text.slice(i, close + 1);
        i = close + 1;
      }
    }
  }
  return out;
}

/** Index of the `$` that closes inline math opened at `open`, or -1. */
function findInlineClose(text: string, open: number): number {
  const first = text[open + 1];
  if (first === undefined || /\s/.test(first)) return -1;
  for (let j = open + 1; j < text.length; j++) {
    const ch = text[j];
    if (ch === "\n") return -1;
    if (ch === "\\") {
      j += 1;
      continue;
    }
    if (ch === "$" && !/\s/.test(text[j - 1]) && !/\d/.test(text[j + 1] ?? "")) return j;
  }
  return -1;
}
