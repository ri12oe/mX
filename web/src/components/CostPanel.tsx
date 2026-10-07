import { useEffect, useState } from "react";
import { getUsageSummary } from "../api";
import { BUDGET_LABELS, monthName, percent, percentUsed, resetDate, shiftMonth, usd, usdLimit } from "../budget";
import type { UsageSummary } from "../types";

interface Props {
  onClose: () => void;
}

/** Spend per month and per local day (design.md §16). Opened from the status card or the top bar. */
export function CostPanel({ onClose }: Props) {
  const [month, setMonth] = useState<string | undefined>(undefined); // undefined = this month
  const [thisMonth, setThisMonth] = useState<string | null>(null);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setError(null);
    getUsageSummary(month)
      .then((s) => {
        if (!current) return;
        setSummary(s);
        setThisMonth((m) => m ?? s.month);
      })
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't load costs."));
    return () => {
      current = false;
    };
  }, [month]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const shown = summary?.month ?? month;
  const go = (by: number) => shown && setMonth(shiftMonth(shown, by));

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="dialog cost-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cost-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="history-head">
          <h2 id="cost-title">Cost</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="cost-month">
          <button type="button" className="icon-button" onClick={() => go(-1)} aria-label="Previous month" disabled={!shown}>‹</button>
          <span className="cost-month-name">{shown ? monthName(shown) : "This month"}</span>
          <button
            type="button"
            className="icon-button"
            onClick={() => go(1)}
            aria-label="Next month"
            disabled={!shown || shown === thisMonth}
          >
            ›
          </button>
        </div>

        {error && <p className="cost-error" role="alert">{error}</p>}
        {!summary && !error && <p className="readout-empty">Loading…</p>}
        {summary && <SummaryView summary={summary} isThisMonth={summary.month === thisMonth} />}
      </div>
    </div>
  );
}

function SummaryView({ summary, isThisMonth }: { summary: UsageSummary; isThisMonth: boolean }) {
  const { totals, days } = summary;
  const maxDay = Math.max(...days.map((d) => d.cost_usd), 0);
  return (
    <>
      <div className={`cost-total budget-${summary.state}`}>
        <div className="cost-total-figure">
          <span className="cost-spent">{usd(summary.spent_usd)}</span>
          <span className="cost-limit">of {usdLimit(summary.limit_usd)}</span>
          <span className="budget-state-label">{BUDGET_LABELS[summary.state]}</span>
        </div>
        <div className="budget-bar" role="meter" aria-label="Month budget used" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={Math.round(percentUsed(summary))}>
          <div className="budget-bar-fill" style={{ width: `${percentUsed(summary)}%` }} />
        </div>
        {isThisMonth && <p className="cost-note">Resets {resetDate(summary.resets_at)}. Failed and stopped replies count too.</p>}
      </div>

      {days.length === 0 ? (
        <p className="readout-empty">No usage this month.</p>
      ) : (
        <table className="cost-days">
          <caption className="sr-only">Spend per day</caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Spend</th>
              <th scope="col">Replies</th>
              <th scope="col">Cache</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.date} title={`${dayLabel(d.date)}: ${usd(d.cost_usd, 4)}, ${d.replies} replies, ` +
                `${d.web_searches} searches, ${d.code_runs} code runs, cache ${percent(d.cache_hit_rate)}`}>
                <th scope="row">{dayLabel(d.date)}</th>
                <td className="cost-day-spend">
                  <div className="cost-day-cell">
                    <span className="cost-day-track" aria-hidden="true">
                      <span className="cost-day-bar" style={{ width: `${maxDay ? (d.cost_usd / maxDay) * 100 : 0}%` }} />
                    </span>
                    <span className="cost-day-value">{usd(d.cost_usd)}</span>
                  </div>
                </td>
                <td>{d.replies}</td>
                <td>{percent(d.cache_hit_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="readout cost-totals" aria-label="Month totals">
        <h3 className="readout-title">Totals</h3>
        <Total label="Replies" value={totals.replies} />
        <Total label="Failed / stopped" value={totals.failed_turns} />
        <Total label="Tokens in" value={totals.input_tokens} />
        <Total label="Tokens out" value={totals.output_tokens} />
        <Total label="Cache read" value={totals.cache_read_tokens} />
        <Total label="Cache write" value={totals.cache_write_tokens} />
        <Total label="Cache hit rate" value={percent(totals.cache_hit_rate)} />
        <Total label="Web searches" value={totals.web_searches} />
        <Total label="Code runs" value={totals.code_runs} />
        {totals.unknown_cost_replies > 0 && <Total label="Unpriced replies" value={totals.unknown_cost_replies} />}
      </section>
    </>
  );
}

function Total({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="readout-row">
      <span className="readout-label">{label}</span>
      <span className="readout-value mono">{typeof value === "number" ? value.toLocaleString() : value}</span>
    </div>
  );
}

function dayLabel(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}
