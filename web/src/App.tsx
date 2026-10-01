import { useCallback, useEffect, useRef, useState } from "react";
import { deleteConversation, getConversation, isSignedOut, listConversations, logout, streamChat, whoami } from "./api";
import { Composer } from "./components/Composer";
import { LoginDialog } from "./components/LoginDialog";
import { MessageView } from "./components/MessageView";
import { Core, type CoreState } from "./components/Core";
import { Sidebar } from "./components/Sidebar";
import { StatusPanel, type SessionStats } from "./components/StatusPanel";
import { loadMode, saveMode } from "./settings";
import type { ChatEvent, ConversationSummary, Mode, StoredMessage, UiMessage, Usage } from "./types";

const SUGGESTIONS = [
  "Explain integration by parts with a worked example",
  "Why does my Python loop raise 'list index out of range'?",
  "Help me plan a habit-tracker app in React",
  "Invent a gadget that helps students study better",
];

let tempCounter = 0;
const tempId = () => `local-${++tempCounter}`;

function fromStored(m: StoredMessage): UiMessage {
  return { id: m.id, role: m.role, content: m.content, images: [], imageRefs: m.image_refs };
}

type Auth = "checking" | "signed-in" | "signed-out";

export default function App() {
  const [auth, setAuth] = useState<Auth>("checking");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [mode, setMode] = useState<Mode>(loadMode);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [lastUsage, setLastUsage] = useState<Usage | null>(null);
  const [session, setSession] = useState<SessionStats>({ replies: 0, costUsd: 0, unknownCost: false });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const handleError = useCallback((err: unknown) => {
    if (isSignedOut(err)) {
      setAuth("signed-out");
      setBanner("Your session ended. Please sign in again.");
    } else {
      setBanner(err instanceof Error ? err.message : "Something went wrong.");
    }
  }, []);

  // On load: are we already signed in (valid session cookie)?
  useEffect(() => {
    whoami()
      .then((info) => {
        setModel(info.model);
        setAuth("signed-in");
      })
      .catch((err: unknown) => {
        if (isSignedOut(err)) setAuth("signed-out");
        else {
          setAuth("signed-in"); // show the app; requests will report the problem
          handleError(err);
        }
      });
  }, [handleError]);

  // After signing in from the login screen, learn which model is answering (for the HUD).
  useEffect(() => {
    if (auth === "signed-in" && model === null) {
      whoami().then((info) => setModel(info.model)).catch(() => {});
    }
  }, [auth, model]);

  const refreshList = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch (err) {
      handleError(err);
    }
  }, [handleError]);

  useEffect(() => {
    if (auth === "signed-in") void refreshList();
  }, [auth, refreshList]);

  // Keep the newest text in view while a reply streams in.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  function stop() {
    abortRef.current?.abort();
  }

  function startNewChat() {
    stop();
    setActiveId(null);
    setMessages([]);
    setBanner(null);
    setSidebarOpen(false);
  }

  async function openConversation(id: string) {
    if (id === activeId) return setSidebarOpen(false);
    stop();
    setSidebarOpen(false);
    setBanner(null);
    try {
      const detail = await getConversation(id);
      setActiveId(id);
      setMessages(detail.messages.map(fromStored));
    } catch (err) {
      handleError(err);
    }
  }

  async function removeConversation(c: ConversationSummary) {
    if (!window.confirm(`Delete "${c.title}"? This can't be undone.`)) return;
    try {
      await deleteConversation(c.id);
      if (c.id === activeId) startNewChat();
      await refreshList();
    } catch (err) {
      handleError(err);
    }
  }

  async function signOut() {
    stop();
    try {
      await logout();
    } catch {
      // the cookie may already be gone; sign out locally either way
    }
    startNewChat();
    setConversations([]);
    setBanner(null);
    setAuth("signed-out");
  }

  function changeMode(next: Mode) {
    setMode(next);
    saveMode(next);
  }

  async function send(text: string, images: string[]) {
    const assistantId = tempId();
    const update = (patch: (m: UiMessage) => Partial<UiMessage>) =>
      setMessages((all) => all.map((m) => (m.id === assistantId ? { ...m, ...patch(m) } : m)));

    setMessages((all) => [
      ...all,
      { id: tempId(), role: "user", content: text, images, imageRefs: [] },
      { id: assistantId, role: "assistant", content: "", images: [], imageRefs: [], streaming: true },
    ]);
    setDraft("");
    setBanner(null);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    // The server saves a turn only when it completes (design.md §5), so a new
    // conversation's id is adopted on `done`. Adopting it at `meta` would make
    // the next message after a failed or stopped first turn point at an id
    // that was never saved (404).
    let conversationId: string | null = null;
    const onEvent = (event: ChatEvent) => {
      switch (event.type) {
        case "meta":
          conversationId = event.conversation_id;
          break;
        case "delta":
          update((m) => ({ content: m.content + event.text }));
          break;
        case "done":
          update(() => ({ streaming: false, usage: event.usage, stopReason: event.stop_reason }));
          setActiveId(conversationId);
          setLastUsage(event.usage);
          setSession((s) => ({
            replies: s.replies + 1,
            costUsd: s.costUsd + (event.usage.cost_usd ?? 0),
            unknownCost: s.unknownCost || event.usage.cost_usd === null,
          }));
          void refreshList();
          break;
        case "error":
          update(() => ({ streaming: false, error: `${event.message} Nothing from this turn was saved.` }));
          break;
      }
    };

    try {
      await streamChat(
        { message: text, mode, conversation_id: activeId ?? undefined, images: images.length ? images : undefined },
        onEvent,
        controller.signal,
      );
    } catch (err) {
      const stopped = err instanceof DOMException && err.name === "AbortError";
      update(() => ({
        streaming: false,
        error: stopped
          ? "Stopped. This reply wasn't saved."
          : `${err instanceof Error ? err.message : "Request failed."} Nothing from this turn was saved.`,
      }));
      if (!stopped) handleError(err);
    } finally {
      update(() => ({ streaming: false }));
      setStreaming(false);
      abortRef.current = null;
    }
  }

  const activeTitle = conversations.find((c) => c.id === activeId)?.title ?? "New chat";
  const coreState = coreStateFor(messages, streaming);

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        open={sidebarOpen}
        onSelect={(id) => void openConversation(id)}
        onNew={startNewChat}
        onDelete={(c) => void removeConversation(c)}
        onSignOut={() => void signOut()}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />}

      <main className="chat">
        <header className="topbar">
          <button type="button" className="icon-button menu-button" onClick={() => setSidebarOpen(true)} aria-label="Open conversations">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <div className="topbar-core">
            <Core state={coreState} size={34} showLabel={false} />
          </div>
          <h1 className="topbar-title">{activeTitle}</h1>
          <span className={`status-chip status-${coreState}`} aria-hidden="true">
            {streaming ? "Live" : model ? "Online" : "Link"}
          </span>
        </header>

        {banner && (
          <div className="banner" role="alert">
            {banner}
            <button type="button" onClick={() => setBanner(null)} aria-label="Dismiss">×</button>
          </div>
        )}

        <div className="messages">
          {messages.length === 0 ? (
            <div className="welcome">
              <Core state={coreState} size={220} showLabel={false} />
              <h2>How can I help you learn today?</h2>
              <p>Code, math, science, projects, and new ideas, explained step by step.</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => setDraft(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-column">
              {messages.map((m) => (
                <MessageView key={m.id} message={m} />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <div className="composer-area">
          <Composer
            text={draft}
            onTextChange={setDraft}
            mode={mode}
            onModeChange={changeMode}
            streaming={streaming}
            onSend={(text, images) => void send(text, images)}
            onStop={stop}
          />
        </div>
      </main>

      <StatusPanel
        coreState={coreState}
        model={model}
        lastUsage={lastUsage}
        session={session}
        conversationCount={conversations.length}
        mode={mode}
      />

      {auth === "signed-out" && (
        <LoginDialog
          onSignedIn={() => {
            setBanner(null);
            setAuth("signed-in");
          }}
        />
      )}
    </div>
  );
}

/** What the core shows: thinking before the first words, responding while they stream, fault after an error. */
export function coreStateFor(messages: UiMessage[], streaming: boolean): CoreState {
  const last = messages[messages.length - 1];
  if (streaming) return last?.role === "assistant" && last.content ? "streaming" : "thinking";
  if (last?.role === "assistant" && last.error) return "error";
  return "idle";
}
