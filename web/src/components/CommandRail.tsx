// Left command rail: navigation and the real voice status. Recent chats stay
// here; the full archive still opens in the history panel.
import type { ConversationSummary } from "../types";
import { Core, type CoreState } from "./Core";

export const RECENT_CHATS = 5;

export type VoiceStatus = "listening" | "speaking" | "online" | "unavailable";

const VOICE_LABEL: Record<VoiceStatus, string> = {
  listening: "Listening",
  speaking: "Speaking",
  online: "Online",
  unavailable: "Unavailable",
};

interface Props {
  coreState: CoreState;
  conversations: ConversationSummary[];
  activeId: string | null;
  voice: VoiceStatus;
  canSpeak: boolean;
  onCommand: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onOpenHistory: () => void;
  onOpenMemory: () => void;
  onOpenCost: () => void;
  onSpeak: () => void;
  onSignOut: () => void;
}

export function CommandRail({
  coreState, conversations, activeId, voice, canSpeak, onCommand, onNew, onSelect, onOpenHistory,
  onOpenMemory, onOpenCost, onSpeak, onSignOut,
}: Props) {
  const recent = conversations.slice(0, RECENT_CHATS);
  return (
    <nav className="rail" aria-label="Command">
      <div className="rail-brand">
        <Core state={coreState} size={52} showLabel={false} />
        <div>
          <div className="rail-name">mX</div>
          <div className="rail-sub">Command center</div>
        </div>
      </div>

      <div className="rail-nav">
        <button type="button" className="rail-link current" aria-current="page" onClick={onCommand}>
          Command
        </button>
        <button type="button" className="rail-link" onClick={onNew}>
          New chat
        </button>
        <button type="button" className="rail-link" onClick={onOpenMemory}>
          Memory
        </button>
        <button type="button" className="rail-link" onClick={onOpenCost}>
          Cost
        </button>
      </div>

      <aside className="rail-recent" aria-label="Conversations">
        <h2 className="rail-recent-title">Conversations</h2>
        <ul className="rail-chats">
          {recent.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={`rail-chat${c.id === activeId ? " active" : ""}`}
                onClick={() => onSelect(c.id)}
                title={c.title}
              >
                {c.title}
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="rail-all" onClick={onOpenHistory} aria-label="All chats">
          All chats · {conversations.length}
        </button>
      </aside>

      <div className="rail-voice">
        <div className="rail-voice-row">
          <span className="rail-voice-kicker">Voice</span>
          <strong className={`rail-voice-state voice-${voice}`}>{VOICE_LABEL[voice]}</strong>
        </div>
        <button
          type="button"
          className="rail-speak"
          onClick={onSpeak}
          disabled={!canSpeak}
          aria-label={voice === "listening" ? "Stop listening" : "Tap to speak"}
        >
          {voice === "listening" ? "Stop" : "Tap to speak"}
        </button>
      </div>

      <button type="button" className="signout-button" onClick={onSignOut}>
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M15 4h4v16h-4M10 16l4-4-4-4M14 12H4" />
        </svg>
        Sign out
      </button>
    </nav>
  );
}
