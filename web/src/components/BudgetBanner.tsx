import { resetDate, usd, usdLimit } from "../budget";
import type { Budget } from "../types";

interface Props {
  budget: Budget | null;
  overrideArmed: boolean; // the next message will be sent in full despite the limit
  onToggleOverride: () => void;
  warningDismissed: boolean;
  onDismissWarning: () => void;
}

/** The 80% warning (dismissible, once per session) and the 100% notice with a one-message override (design.md §16). */
export function BudgetBanner({ budget, overrideArmed, onToggleOverride, warningDismissed, onDismissWarning }: Props) {
  if (!budget || budget.state === "ok") return null;

  if (budget.state === "warning") {
    if (warningDismissed) return null;
    return (
      <div className="banner budget-banner budget-warning" role="status">
        <span>
          <strong>Budget warning:</strong> {usd(budget.spent_usd)} of this month's {usdLimit(budget.limit_usd)} used
          (80%+). At {usdLimit(budget.limit_usd)}, mX switches to brief mode until {resetDate(budget.resets_at)}.
        </span>
        <button type="button" onClick={onDismissWarning} aria-label="Dismiss budget warning">×</button>
      </div>
    );
  }

  return (
    <div className="banner budget-banner budget-brief" role="status">
      <span>
        <strong>Budget reached:</strong> {usd(budget.spent_usd)} of {usdLimit(budget.limit_usd)}. Brief mode, tools off
        until {resetDate(budget.resets_at)}.
      </span>
      <button type="button" className="override-button" aria-pressed={overrideArmed} onClick={onToggleOverride}>
        {overrideArmed ? "Next message: full answer ✓ (undo)" : "Full answer for this message"}
      </button>
    </div>
  );
}
