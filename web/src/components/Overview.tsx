// Real readouts only: core, memory, voice, tools, model, and this month's budget.
import { BUDGET_LABELS, percentUsed, usd } from "../budget";
import type { Budget } from "../types";
import { CORE_LABELS, type CoreState } from "./Core";
import type { VoiceStatus } from "./CommandRail";

const VOICE_LABEL: Record<VoiceStatus, string> = {
  listening: "Listening",
  speaking: "Speaking",
  online: "Online",
  unavailable: "Unavailable",
};

interface Props {
  coreState: CoreState;
  memoryCount: number | null;
  voice: VoiceStatus;
  toolsOn: boolean;
  toolsAvailable: boolean;
  model: string | null;
  budget: Budget | null;
  onOpenCost: () => void;
}

export function Overview({
  coreState, memoryCount, voice, toolsOn, toolsAvailable, model, budget, onOpenCost,
}: Props) {
  const toolsLabel = !toolsAvailable ? "Off" : toolsOn ? "On" : "Off";
  return (
    <div className="overview" aria-label="Overview">
      <Tile kicker="Core" value={CORE_LABELS[coreState]} />
      <Tile kicker="Memory" value={memoryCount === null ? "—" : String(memoryCount)} />
      <Tile kicker="Voice" value={VOICE_LABEL[voice]} />
      <Tile kicker="Tools" value={toolsLabel} />
      <Tile kicker="Model" value={model ?? "—"} mono />
      <section className={`tile budget budget-${budget?.state ?? "ok"}`} aria-label="Month">
        <h2 className="tile-kicker">Month</h2>
        {budget ? (
          <>
            <p className="tile-value">{usd(budget.spent_usd)} / {usd(budget.limit_usd)}</p>
            <div
              className="budget-bar"
              role="meter"
              aria-label="Month budget used"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(percentUsed(budget))}
            >
              <div className="budget-bar-fill" style={{ width: `${percentUsed(budget)}%` }} />
            </div>
            <p className="tile-state">{BUDGET_LABELS[budget.state]}</p>
          </>
        ) : (
          <p className="tile-value">—</p>
        )}
        <button type="button" className="cost-link" onClick={onOpenCost}>Cost details</button>
      </section>
    </div>
  );
}

function Tile({ kicker, value, mono }: { kicker: string; value: string; mono?: boolean }) {
  return (
    <section className="tile" aria-label={kicker}>
      <h2 className="tile-kicker">{kicker}</h2>
      <p className={`tile-value${mono ? " mono" : ""}`}>{value}</p>
    </section>
  );
}
