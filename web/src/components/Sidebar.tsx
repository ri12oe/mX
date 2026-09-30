import type { ConversationSummary } from "../types";

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  open: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (conversation: ConversationSummary) => void;
  onSignOut: () => void;
}

export function Sidebar({ conversations, activeId, open, onSelect, onNew, onDelete, onSignOut }: Props) {
  return (
    <aside className={`sidebar${open ? " open" : ""}`} aria-label="Conversations">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">mX</span>
        <span className="brand-name">mX</span>
      </div>

      <button type="button" className="new-chat" onClick={onNew}>
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" d="M12 5v14M5 12h14" />
        </svg>
        New chat
      </button>

      <nav className="conversation-list">
        {conversations.length === 0 && <p className="empty-list">No conversations yet.</p>}
        {conversations.map((c) => (
          <div key={c.id} className={`conversation${c.id === activeId ? " active" : ""}`}>
            <button type="button" className="conversation-open" onClick={() => onSelect(c.id)} title={c.title}>
              <span className="conversation-title">{c.title}</span>
              <span className="conversation-time">{relativeTime(c.updated_at)}</span>
            </button>
            <button
              type="button"
              className="conversation-delete"
              onClick={() => onDelete(c)}
              aria-label={`Delete "${c.title}"`}
              title="Delete"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
                <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
              </svg>
            </button>
          </div>
        ))}
      </nav>

      <button type="button" className="settings-button" onClick={onSignOut}>
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            d="M15 4h4v16h-4M10 16l4-4-4-4M14 12H4" />
        </svg>
        Sign out
      </button>
    </aside>
  );
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
