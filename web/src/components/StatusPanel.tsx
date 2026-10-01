import { useEffect, useState, type ReactNode } from "react";
import type { Mode, Usage } from "../types";
import { Core, type CoreState } from "./Core";

export interface SessionStats {
  replies: number;
  costUsd: number;
  unknownCost: boolean; // a reply had no price, so the total is a lower bound
}

interface Props {
  coreState: CoreState;
  model: string | null;
  lastUsage: Usage | null;
  session: SessionStats;
  conversationCount: number;
  mode: Mode;
}

/** Right-hand HUD: the core plus real readouts only (no decorative fake data). */
export function StatusPanel({ coreState, model, lastUsage, session, conversationCount, mode }: Props) {
  return (
    <aside className="status-panel" aria-label="System status">
      <Core state={coreState} size={170} />
      <Clock />
      <Readout title="Link">
        <Row label="Status" value={model ? "Online" : "Connecting"} accent={model ? "ok" : undefined} />
        <Row label="Model" value={model ?? "—"} mono />
        <Row label="Mode" value={mode === "brief" ? "Brief" : "Normal"} />
      </Readout>
      <Readout title="Last reply">
        {lastUsage ? (
          <>
            <Row label="Tokens in" value={lastUsage.input_tokens.toLocaleString()} mono />
            <Row label="Tokens out" value={lastUsage.output_tokens.toLocaleString()} mono />
            <Row label="Cost" value={formatCost(lastUsage.cost_usd)} mono />
          </>
        ) : (
          <p className="readout-empty">No replies yet this session.</p>
        )}
      </Readout>
      <Readout title="Session">
        <Row label="Replies" value={String(session.replies)} mono />
        <Row label="Spend" value={`${session.unknownCost ? "≥ " : ""}$${session.costUsd.toFixed(4)}`} mono />
        <Row label="Archive" value={`${conversationCount} chat${conversationCount === 1 ? "" : "s"}`} mono />
      </Readout>
    </aside>
  );
}

export function formatCost(cost: number | null): string {
  return cost === null ? "unknown" : `$${cost.toFixed(4)}`;
}

function Readout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="readout" aria-label={title}>
      <h2 className="readout-title">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, value, mono, accent }: { label: string; value: string; mono?: boolean; accent?: "ok" }) {
  return (
    <div className="readout-row">
      <span className="readout-label">{label}</span>
      <span className={`readout-value${mono ? " mono" : ""}${accent ? ` ${accent}` : ""}`}>{value}</span>
    </div>
  );
}

/** Live local clock, updated every second. */
export function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const time = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const date = now.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  return (
    <div className="clock" role="timer" aria-label="Local time">
      <div className="clock-time">{time}</div>
      <div className="clock-date">{date}</div>
    </div>
  );
}
