// The mX core: an original reactor-style emblem whose animation shows what mX is doing.
// idle = slow drift · thinking = pulse · streaming = fast spin · error = red flash.

export type CoreState = "idle" | "thinking" | "streaming" | "error";

export const CORE_LABELS: Record<CoreState, string> = {
  idle: "Standby",
  thinking: "Thinking",
  streaming: "Responding",
  error: "Fault",
};

/** SVG path for a circular arc from `start` to `end` degrees (0 = top, clockwise). */
export function arc(r: number, start: number, end: number, c = 100): string {
  const point = (deg: number) => {
    const rad = ((deg - 90) * Math.PI) / 180;
    return `${(c + r * Math.cos(rad)).toFixed(2)} ${(c + r * Math.sin(rad)).toFixed(2)}`;
  };
  const large = end - start > 180 ? 1 : 0;
  return `M ${point(start)} A ${r} ${r} 0 ${large} 1 ${point(end)}`;
}

const OUTER_ARCS: [number, number][] = [[10, 80], [100, 170], [190, 260], [280, 350]];
const INNER_ARCS: [number, number][] = [[0, 50], [70, 160], [180, 230], [250, 340]];

interface Props {
  state: CoreState;
  size?: number;
  showLabel?: boolean;
}

export function Core({ state, size = 180, showLabel = true }: Props) {
  return (
    <div className={`core core-${state}`} style={{ width: size }}>
      <svg viewBox="0 0 200 200" role="img" aria-label={`mX core: ${CORE_LABELS[state]}`}>
        <circle className="core-halo" cx="100" cy="100" r="96" />
        <circle className="core-ticks" cx="100" cy="100" r="90" />
        <g className="core-layer core-outer">
          {OUTER_ARCS.map(([a, b]) => (
            <path key={a} className="core-arc" d={arc(80, a, b)} />
          ))}
        </g>
        <g className="core-layer core-segments">
          <circle className="core-segment-ring" cx="100" cy="100" r="66" />
        </g>
        <g className="core-layer core-inner">
          {INNER_ARCS.map(([a, b]) => (
            <path key={a} className="core-arc core-arc-thin" d={arc(52, a, b)} />
          ))}
        </g>
        <circle className="core-glow" cx="100" cy="100" r="36" />
        <circle className="core-center" cx="100" cy="100" r="27" />
        <text className="core-text" x="100" y="101" textAnchor="middle" dominantBaseline="middle">
          mX
        </text>
      </svg>
      {showLabel && <span className="core-label">{CORE_LABELS[state]}</span>}
    </div>
  );
}
