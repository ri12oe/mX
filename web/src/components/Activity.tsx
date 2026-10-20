// This session's real tool steps and sources, plus the suggestion prompts.
import type { UiMessage } from "../types";
import { Sources } from "./Sources";
import { ToolSteps } from "./ToolSteps";

interface Props {
  message: UiMessage | undefined;
  suggestions: readonly string[];
  onSuggest: (text: string) => void;
}

export function Activity({ message, suggestions, onSuggest }: Props) {
  const steps = message?.steps ?? [];
  const citations = message?.citations;
  const hasWork = steps.length > 0 || (citations?.length ?? 0) > 0;
  return (
    <aside className="activity" aria-label="This session">
      <section className="activity-feed">
        <h2 className="activity-title">This session</h2>
        {hasWork ? (
          <>
            {steps.length > 0 && <ToolSteps steps={steps} />}
            <Sources citations={citations} steps={steps} />
          </>
        ) : (
          <p className="readout-empty">No activity this session.</p>
        )}
      </section>
      <section className="quick" aria-label="Quick commands">
        <h2 className="activity-title">Quick commands</h2>
        <div className="suggestions">
          {suggestions.map((s) => (
            <button key={s} type="button" onClick={() => onSuggest(s)}>
              {s}
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}

/** The latest assistant turn, which is what the side column reports. */
export function latestAssistant(messages: UiMessage[]): UiMessage | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") return messages[i];
  }
  return undefined;
}
