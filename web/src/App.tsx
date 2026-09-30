import { useCallback, useEffect, useRef, useState } from "react";
import { deleteConversation, getConversation, isSignedOut, listConversations, logout, streamChat, whoami } from "./api";
import { Composer } from "./components/Composer";
import { LoginDialog } from "./components/LoginDialog";
import { MessageView } from "./components/MessageView";
import { Sidebar } from "./components/Sidebar";
import { loadMode, saveMode } from "./settings";
import type { ChatEvent, ConversationSummary, Mode, StoredMessage, UiMessage } from "./types";

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
      .then(() => setAuth("signed-in"))
      .catch((err: unknown) => {
        if (isSignedOut(err)) setAuth("signed-out");
        else {
          setAuth("signed-in"); // show the app; requests will report the problem
          handleError(err);
        }
      });
  }, [handleError]);

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

    const onEvent = (event: ChatEvent) => {
      switch (event.type) {
        case "meta":
          setActiveId(event.conversation_id);
          break;
        case "delta":
          update((m) => ({ content: m.content + event.text }));
          break;
        case "done":
          update(() => ({ streaming: false, usage: event.usage, stopReason: event.stop_reason }));
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
          <h1 className="topbar-title">{activeTitle}</h1>
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
              <div className="welcome-mark" aria-hidden="true">mX</div>
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
