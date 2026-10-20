// A memory mX suggested. It lives only in this card until Rio taps Save (design.md §18).
import { useState } from "react";
import { ApiError, createMemory } from "../api";
import type { MemorySuggestion as Suggestion } from "../types";

interface Props {
  suggestion: Suggestion;
  onDismiss: (suggestionId: string) => void;
}

export function MemorySuggestion({ suggestion, onDismiss }: Props) {
  const [state, setState] = useState<"open" | "saving" | "saved">("open");
  const [problem, setProblem] = useState<string | null>(null);

  async function save() {
    setState("saving");
    setProblem(null);
    try {
      await createMemory(suggestion.text, suggestion.conversationId);
      setState("saved");
    } catch (err) {
      setState("open");
      if (err instanceof ApiError && err.code === "memory_limit") {
        setProblem("The memory list is full. Remove one on the Memory page, then save this again.");
      } else if (err instanceof ApiError && err.code === "memory_duplicate") {
        setProblem("That's already in your memories.");
      } else {
        setProblem(err instanceof Error ? err.message : "Couldn't save that.");
      }
    }
  }

  return (
    <div className="memory-card" role="group" aria-label="Memory suggestion">
      {state === "saved" ? (
        <p>Saved. mX will see this note on later messages.</p>
      ) : (
        <>
          <p>Remember: {suggestion.text}</p>
          <div className="memory-card-actions">
            <button type="button" className="button-primary" onClick={() => void save()} disabled={state === "saving"}>
              Save
            </button>
            <button type="button" className="button-secondary" onClick={() => onDismiss(suggestion.suggestion_id)}>
              Dismiss
            </button>
          </div>
          {problem && <p className="note error" role="alert">{problem}</p>}
        </>
      )}
    </div>
  );
}
