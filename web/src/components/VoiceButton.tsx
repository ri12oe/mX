// Push-to-talk. Hidden when the browser has no speech recognition (design.md §19).
import { useState } from "react";
import { speechInputAvailable, startListening, type SpeechRecognizer } from "../voice";

interface Props {
  disabled: boolean;
  onTranscript: (text: string) => void;
}

export function VoiceButton({ disabled, onTranscript }: Props) {
  const [recognition, setRecognition] = useState<SpeechRecognizer | null>(null);
  if (!speechInputAvailable()) return null;
  const listening = recognition !== null;

  function toggle() {
    if (recognition) {
      recognition.stop();
      setRecognition(null);
      return;
    }
    const next = startListening((text) => {
      onTranscript(text);
      setRecognition(null);
    });
    if (!next) return;
    next.onerror = () => setRecognition(null);
    next.onend = () => setRecognition(null);
    setRecognition(next);
  }

  return (
    <button
      type="button"
      className={`icon-button voice-button${listening ? " active" : ""}`}
      aria-pressed={listening}
      aria-label={listening ? "Stop listening" : "Speak"}
      disabled={disabled}
      onClick={toggle}
    >
      <span aria-hidden="true">{listening ? "●" : "🎤"}</span>
    </button>
  );
}
