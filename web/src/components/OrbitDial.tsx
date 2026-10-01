// The orbit dial: a circular navigator. "+ New" in the center; the most recent
// chats fan out on elbow spokes (labels aligned in a column so they stay
// readable); the last spoke opens the full history panel.
import type { ConversationSummary } from "../types";
import { arc } from "./Core";

export const MAX_SPOKES = 5;
export const DIAL = { radius: 62, center: 76, spacing: 32, labelGap: 40 };

export interface SpokeGeometry {
  y: number; // label row
  edge: [number, number]; // where the spoke leaves the circle
  elbow: [number, number]; // where it bends to horizontal
  end: [number, number]; // just before the label
}

/** Evenly spaced label rows centered on the dial, each joined to the ring by an elbow line. */
export function spokeGeometry(count: number, height: number): SpokeGeometry[] {
  const { radius: r, center: cx, spacing, labelGap } = DIAL;
  const cy = height / 2;
  const labelX = cx + r + labelGap;
  return Array.from({ length: count }, (_, i) => {
    const y = cy + (i - (count - 1) / 2) * spacing;
    const ratio = Math.max(-0.92, Math.min(0.92, (y - cy) / (r + 16)));
    const angle = Math.asin(ratio);
    const at = (radius: number): [number, number] => [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
    const elbow = at(r + 16);
    return { y, edge: at(r), elbow: [elbow[0], y], end: [labelX - 8, y] };
  });
}

export function dialHeight(spokes: number): number {
  return Math.max(DIAL.center * 2, spokes * DIAL.spacing + 24);
}

interface Props {
  conversations: ConversationSummary[]; // newest first
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onOpenHistory: () => void;
}

export function OrbitDial({ conversations, activeId, onSelect, onNew, onOpenHistory }: Props) {
  const recent = conversations.slice(0, MAX_SPOKES);
  const spokes = recent.length + 1; // + "All chats"
  const height = dialHeight(spokes);
  const geometry = spokeGeometry(spokes, height);
  const cy = height / 2;
  const { radius: r, center: cx } = DIAL;

  return (
    <aside className="orbit" aria-label="Conversations">
      <div className="orbit-stage" style={{ height }}>
        <svg className="orbit-lines" width="100%" height={height} aria-hidden="true">
          <circle className="orbit-ring" cx={cx} cy={cy} r={r} />
          <circle className="orbit-ticks" cx={cx} cy={cy} r={r - 7} />
          <g className="orbit-spin" style={{ transformOrigin: `${cx}px ${cy}px` }}>
            {[[20, 110], [200, 290]].map(([a, b]) => (
              <path key={a} className="orbit-arc" d={arc(r + 6, a, b, cx, cy)} />
            ))}
          </g>
          {geometry.map((g, i) => (
            <g key={i} className={i === spokes - 1 ? "spoke-line spoke-line-all" : "spoke-line"}>
              <polyline points={`${g.edge.join(",")} ${g.elbow.join(",")} ${g.end.join(",")}`} />
              <circle cx={g.edge[0]} cy={g.edge[1]} r="2.5" />
            </g>
          ))}
        </svg>

        <button type="button" className="orbit-new" style={{ left: cx - 38, top: cy - 38 }} onClick={onNew} aria-label="New chat" title="New chat">
          <span className="orbit-plus" aria-hidden="true">+</span>
          <span className="orbit-new-label" aria-hidden="true">New</span>
        </button>

        {recent.map((c, i) => (
          <button
            key={c.id}
            type="button"
            className={`spoke${c.id === activeId ? " active" : ""}`}
            style={{ top: geometry[i].y, left: geometry[i].end[0] + 8 }}
            onClick={() => onSelect(c.id)}
            title={c.title}
          >
            {c.title}
          </button>
        ))}
        <button
          type="button"
          className="spoke spoke-all"
          style={{ top: geometry[spokes - 1].y, left: geometry[spokes - 1].end[0] + 8 }}
          onClick={onOpenHistory}
          aria-label="All chats"
        >
          All chats · {conversations.length}
        </button>
      </div>
    </aside>
  );
}
