import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { ACCEPTED_TYPES, MAX_IMAGES, checkImage, readAsDataUrl } from "../images";
import type { Mode } from "../types";

interface Props {
  text: string;
  onTextChange: (text: string) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  streaming: boolean;
  onSend: (text: string, images: string[]) => void;
  onStop: () => void;
}

export function Composer({ text, onTextChange, mode, onModeChange, streaming, onSend, onStop }: Props) {
  const [images, setImages] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Grow the box with its content, up to the CSS max-height. Empty = one line
  // (the placeholder must not count), and re-measure when the width changes.
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    const fit = () => {
      el.style.height = "auto";
      if (el.value) el.style.height = `${el.scrollHeight}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [text]);

  const canSend = !streaming && text.trim().length > 0;

  function send() {
    if (!canSend) return;
    onSend(text.trim(), images);
    setImages([]);
    setProblem(null);
  }

  async function addFiles(files: Iterable<File>) {
    const list = [...files];
    const room = MAX_IMAGES - images.length;
    const errors: string[] = [];
    if (list.length > room) errors.push(`Up to ${MAX_IMAGES} images per message.`);
    const added: string[] = [];
    for (const file of list.slice(0, Math.max(room, 0))) {
      const error = checkImage(file);
      if (error) errors.push(error);
      else added.push(await readAsDataUrl(file));
    }
    setImages((current) => [...current, ...added]);
    setProblem(errors.length ? errors.join(" ") : null);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  function onPaste(e: ClipboardEvent) {
    const files = [...e.clipboardData.files].filter((f) => f.type.startsWith("image/"));
    if (files.length) {
      e.preventDefault();
      void addFiles(files);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    void addFiles(e.dataTransfer.files);
  }

  return (
    <div
      className={`composer${dragging ? " dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      {images.length > 0 && (
        <div className="thumbs composer-thumbs">
          {images.map((src, i) => (
            <div key={i} className="thumb-wrap">
              <img className="thumb" src={src} alt={`Image ${i + 1} to send`} />
              <button
                type="button"
                className="thumb-remove"
                aria-label={`Remove image ${i + 1}`}
                onClick={() => setImages((current) => current.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      {problem && <div className="note error composer-note">{problem}</div>}

      <textarea
        ref={textarea}
        value={text}
        onChange={(e) => onTextChange(e.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        placeholder="Ask mX anything…"
        rows={1}
        aria-label="Message"
      />

      <div className="composer-bar">
        <div className="composer-tools">
          <button
            type="button"
            className="icon-button"
            onClick={() => fileInput.current?.click()}
            disabled={images.length >= MAX_IMAGES}
            aria-label="Attach images"
            title="Attach images (or paste / drop them)"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                d="M21 12.5 12.6 20.9a5.5 5.5 0 0 1-7.8-7.8l8.5-8.5a3.7 3.7 0 0 1 5.2 5.2l-8.5 8.5a1.8 1.8 0 0 1-2.6-2.6l7.8-7.8" />
            </svg>
          </button>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPTED_TYPES.join(",")}
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) void addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <div className="segmented" role="radiogroup" aria-label="Answer length">
            {(["normal", "brief"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                className={mode === m ? "active" : ""}
                onClick={() => onModeChange(m)}
                title={m === "normal" ? "Full answers with steps" : "1–2 sentences, for quick answers"}
              >
                {m === "normal" ? "Normal" : "Brief"}
              </button>
            ))}
          </div>
        </div>

        {streaming ? (
          <button type="button" className="send-button stop" onClick={onStop} aria-label="Stop generating">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" /></svg>
            Stop
          </button>
        ) : (
          <button type="button" className="send-button" onClick={send} disabled={!canSend} aria-label="Send">
            Send
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path fill="currentColor" d="M3.4 20.4 21 12 3.4 3.6 3.4 10l12.6 2-12.6 2z" />
            </svg>
          </button>
        )}
      </div>
      <div className="composer-hint">Enter to send · Shift+Enter for a new line</div>
    </div>
  );
}
