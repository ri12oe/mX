// The Memory page: list, edit, delete, and add notes Rio approved (design.md §18).
import { useEffect, useState } from "react";
import { ApiError, createMemory, deleteMemory, listMemories, updateMemory } from "../api";
import type { Memory } from "../types";

interface Props {
  onClose: () => void;
}

export function MemoryPanel({ onClose }: Props) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  async function reload() {
    setMemories(await listMemories());
  }

  useEffect(() => {
    let current = true;
    listMemories()
      .then((rows) => current && setMemories(rows))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't load memories."));
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function add() {
    const text = draft.trim();
    if (!text) return;
    setError(null);
    try {
      await createMemory(text);
      setDraft("");
      await reload();
    } catch (err) {
      setError(memoryError(err));
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="dialog memory-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="memory-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="history-head">
          <h2 id="memory-title">Memory</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>
        <p className="memory-note">These notes are sent to the model with every message.</p>
        {error && <p className="note error" role="alert">{error}</p>}
        {!memories && !error && <p className="readout-empty">Loading…</p>}
        <ul className="memory-list">
          {memories?.map((memory) => (
            <MemoryRow
              key={memory.id}
              memory={memory}
              onChange={async (text) => {
                setError(null);
                try {
                  await updateMemory(memory.id, text);
                  await reload();
                } catch (err) {
                  setError(memoryError(err));
                }
              }}
              onDelete={async () => {
                if (!window.confirm("Delete this memory?")) return;
                await deleteMemory(memory.id);
                await reload();
              }}
            />
          ))}
        </ul>
        {memories?.length === 0 && <p className="readout-empty">No memories yet.</p>}
        <form
          className="memory-add"
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
        >
          <label>
            Add a note
            <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} />
          </label>
          <button type="submit" className="button-primary" disabled={!draft.trim()}>Add</button>
        </form>
      </div>
    </div>
  );
}

function MemoryRow({
  memory, onChange, onDelete,
}: {
  memory: Memory;
  onChange: (text: string) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(memory.text);
  return (
    <li className="memory-row">
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onChange(text).then(() => setEditing(false));
          }}
        >
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={200} aria-label="Edit memory" />
          <button type="submit" className="button-primary">Save</button>
        </form>
      ) : (
        <>
          <span>{memory.text}</span>
          <button type="button" className="button-secondary" onClick={() => setEditing(true)}>Edit</button>
          <button type="button" className="button-secondary" onClick={() => void onDelete()}>Delete</button>
        </>
      )}
    </li>
  );
}

function memoryError(err: unknown): string {
  if (err instanceof ApiError && err.code === "memory_limit") return "The memory list is full (50). Remove one first.";
  if (err instanceof ApiError && err.code === "memory_duplicate") return "That memory is already saved.";
  if (err instanceof ApiError && (err.code === "blank" || err.code === "too_long")) return err.message;
  return err instanceof Error ? err.message : "Couldn't save that.";
}
