// Sources under an answer (design.md §10.1, §17). Titles are plain text.
// Only http(s) URLs become links; anything else is shown as text so a bad
// scheme cannot navigate or run script.
import type { Citation, ToolStep } from "../types";

export type SourceKind = "cited" | "searched";

export interface SourceList {
  kind: SourceKind;
  items: Citation[];
}

/** http and https only. `javascript:`, `data:`, and malformed URLs are not links. */
export function isHttpUrl(url: string): boolean {
  try {
    const protocol = new URL(url).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function dedupe(items: Citation[]): Citation[] {
  const seen = new Set<string>();
  const out: Citation[] = [];
  for (const item of items) {
    const url = item.url.trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    out.push({ url, title: item.title });
  }
  return out;
}

/** Citations win. With none, use the web-search steps' sources (dynamic filtering often cites nothing). */
export function answerSources(citations: Citation[] | undefined, steps: ToolStep[] | undefined): SourceList | null {
  const cited = dedupe(citations ?? []);
  if (cited.length > 0) return { kind: "cited", items: cited };
  const searched: Citation[] = [];
  for (const step of steps ?? []) {
    if (step.tool !== "web_search") continue;
    searched.push(...(step.output?.sources ?? []));
  }
  const items = dedupe(searched);
  return items.length > 0 ? { kind: "searched", items } : null;
}

export function Sources({ citations, steps }: { citations?: Citation[]; steps?: ToolStep[] }) {
  const list = answerSources(citations, steps);
  if (!list) return null;
  const label = list.kind === "cited" ? "Cited" : "Searched";
  return (
    <section className="sources" aria-label={list.kind === "cited" ? "Cited sources" : "Searched sources"}>
      <h3 className="sources-label">{label}</h3>
      <ol>
        {list.items.map((item) => (
          <li key={item.url}>
            {isHttpUrl(item.url) ? (
              <a href={item.url} target="_blank" rel="noopener noreferrer">
                {item.title || item.url}
              </a>
            ) : (
              <span>{item.title || item.url}</span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
