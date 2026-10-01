import { useEffect, useMemo, useState } from "react";
import { relativeTime } from "../time";
import type { ConversationSummary } from "../types";

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (conversation: ConversationSummary) => void;
  onClose: () => void;
}

/** Every conversation, searchable, with delete. Opened from the dial's "All chats" spoke. */
export function HistoryPanel({ conversations, activeId, onSelect, onNew, onDelete, onClose }: Props) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? conversations.filter((c) => c.title.toLowerCase().includes(q)) : conversations;
  }, [conversations, query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="dialog history-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="history-head">
          <h2 id="history-title">All chats</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="history-tools">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats…"
            aria-label="Search chats"
            autoFocus
          />
          <button type="button" className="button-primary" onClick={onNew}>
            + Start new chat
          </button>
        </div>
        <ul className="history-list">
          {shown.length === 0 && <li className="history-empty">{conversations.length ? "No chats match." : "No conversations yet."}</li>}
          {shown.map((c) => (
            <li key={c.id} className={`history-row${c.id === activeId ? " active" : ""}`}>
              <button type="button" className="history-open" onClick={() => onSelect(c.id)} title={c.title}>
                <span className="history-title">{c.title}</span>
                <span className="history-time">{relativeTime(c.updated_at)}</span>
              </button>
              <button type="button" className="history-delete" onClick={() => onDelete(c)} aria-label={`Delete "${c.title}"`} title="Delete">
                <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
                  <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
