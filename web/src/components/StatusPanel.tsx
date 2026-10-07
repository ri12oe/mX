import { useEffect, useState, type ReactNode } from "react";
import { BUDGET_LABELS, cacheShare, percent, percentUsed, usd } from "../budget";
import type { Budget, Mode, Usage } from "../types";
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
  budget: Budget | null;
  onOpenCost: () => void;
  onSignOut: () => void;
}

/** Right-hand HUD: the core plus real readouts only (no decorative fake data). */
export function StatusPanel({
  coreState, model, lastUsage, session, conversationCount, mode, budget, onOpenCost, onSignOut,
}: Props) {
  return (
    <aside className="status-panel" aria-label="System status">
      <Core state={coreState} size={170} />
      <Clock />
      <Readout title="Link">
        <Row label="Status" value={model ? "Online" : "Connecting"} accent={model ? "ok" : undefined} />
        <Row label="Model" value={model ?? "—"} mono />
        <Row label="Mode" value={mode === "brief" ? "Brief" : "Normal"} />
      </Readout>
      <MonthReadout budget={budget} onOpenCost={onOpenCost} />
      <Readout title="Last reply">
        {lastUsage ? (
          <>
            <Row label="Tokens in" value={lastUsage.input_tokens.toLocaleString()} mono />
            <Row label="Tokens out" value={lastUsage.output_tokens.toLocaleString()} mono />
            <Row label="Cache" value={percent(cacheShare(lastUsage))} mono />
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
      <button type="button" className="signout-button" onClick={onSignOut}>
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M15 4h4v16h-4M10 16l4-4-4-4M14 12H4" />
        </svg>
        Sign out
      </button>
    </aside>
  );
}

/** This month's spend against the limit, with a bar colored (and labeled) by state (design.md §16). */
function MonthReadout({ budget, onOpenCost }: { budget: Budget | null; onOpenCost: () => void }) {
  return (
    <Readout title="Month">
      {budget ? (
        <div className={`budget budget-${budget.state}`}>
          <Row label="Spend" value={`${usd(budget.spent_usd)} / ${usd(budget.limit_usd)}`} mono />
          <div className="budget-bar" role="meter" aria-label="Month budget used" aria-valuemin={0}
            aria-valuemax={100} aria-valuenow={Math.round(percentUsed(budget))}>
            <div className="budget-bar-fill" style={{ width: `${percentUsed(budget)}%` }} />
          </div>
          <Row label="State" value={BUDGET_LABELS[budget.state]} />
        </div>
      ) : (
        <p className="readout-empty">Loading…</p>
      )}
      <button type="button" className="cost-link" onClick={onOpenCost}>Cost details</button>
    </Readout>
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
