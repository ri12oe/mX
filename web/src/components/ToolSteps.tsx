// Tool steps behind an answer (design.md §17): a chip per code run or web search that
// expands to show what ran. Code and output are shown as plain text, never as markdown.
import type { ToolStep } from "../types";

const ERROR_LABELS: Record<string, string> = {
  execution_time_exceeded: "time limit reached",
  too_many_requests: "too many requests",
  unavailable: "tool unavailable",
  invalid_tool_input: "invalid input",
  max_uses_exceeded: "search limit reached",
  query_too_long: "query too long",
  incomplete: "didn't finish",
  output_file_too_large: "output too large",
};

export function ToolSteps({ steps }: { steps: ToolStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ul className="tool-steps" aria-label="Tool steps">
      {steps.map((step) => (
        <li key={step.id}>
          <StepChip step={step} />
        </li>
      ))}
    </ul>
  );
}

/** "Running code…", "Ran code", "Code failed: time limit reached", "Searched: …". */
export function stepLabel(step: ToolStep): string {
  const search = step.tool === "web_search";
  const query = step.input.query ? `: ${step.input.query}` : "";
  if (step.status === "running") return search ? `Searching${query}…` : "Running code…";
  if (step.status === "error") {
    const why = ERROR_LABELS[step.error_code ?? ""] ?? step.error_code ?? "error";
    return search ? `Search failed: ${why}` : `Code failed: ${why}`;
  }
  if (search) {
    const count = step.output?.sources?.length ?? 0;
    return `Searched${query} (${count} source${count === 1 ? "" : "s"})`;
  }
  const code = step.output?.return_code;
  return code ? `Ran code (exit ${code})` : "Ran code";
}

function StepChip({ step }: { step: ToolStep }) {
  const tone = step.status === "error" || (step.output?.return_code ?? 0) !== 0 ? "warn" : step.status;
  return (
    <details className={`tool-step tool-step-${tone}`}>
      <summary>
        <span className="tool-step-icon" aria-hidden="true">{step.tool === "web_search" ? "⌕" : "›_"}</span>
        <span className="tool-step-label">{stepLabel(step)}</span>
        {step.status === "running" && <span className="tool-step-spinner" aria-hidden="true" />}
      </summary>
      <div className="tool-step-body">
        {step.tool === "web_search" ? <SearchDetails step={step} /> : <CodeDetails step={step} />}
      </div>
    </details>
  );
}

function CodeDetails({ step }: { step: ToolStep }) {
  const out = step.output;
  return (
    <>
      <Block title={step.input.language === "bash" ? "Command" : step.input.language === "file" ? "File" : "Code"}
        text={step.input.code ?? ""} cut={step.input.code_truncated} />
      {out?.stdout ? <Block title="Output" text={out.stdout} cut={out.stdout_truncated} /> : null}
      {out?.stderr ? <Block title="Errors" text={out.stderr} cut={out.stderr_truncated} /> : null}
      {out && !out.stdout && !out.stderr && step.status === "ok" && <p className="tool-step-note">No output.</p>}
    </>
  );
}

function SearchDetails({ step }: { step: ToolStep }) {
  const sources = step.output?.sources ?? [];
  return sources.length === 0 ? (
    <p className="tool-step-note">{step.status === "running" ? "Searching…" : "No sources."}</p>
  ) : (
    <ol className="tool-step-sources">
      {sources.map((s) => (
        <li key={s.url}>
          <span className="tool-step-source-title">{s.title || s.url}</span>{" "}
          <span className="tool-step-source-host">{hostOf(s.url)}</span>
        </li>
      ))}
    </ol>
  );
}

function Block({ title, text, cut }: { title: string; text: string; cut?: boolean }) {
  return (
    <div className="tool-step-block">
      <div className="tool-step-block-title">{title}</div>
      <pre>{text}</pre>
      {cut && <p className="tool-step-note">Cut short to keep the chat small.</p>}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}
