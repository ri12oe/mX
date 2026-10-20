// Browser speech, only when the page is a secure context (design.md §19). No server changes.

interface RecognitionResult {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}

interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<RecognitionResult>;
}

export interface SpeechRecognizer {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type RecognitionCtor = new () => SpeechRecognizer;

function recognitionCtor(): RecognitionCtor | null {
  const host = window as Window & { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return host.SpeechRecognition ?? host.webkitSpeechRecognition ?? null;
}

export function speechInputAvailable(): boolean {
  return recognitionCtor() !== null;
}

export function speechOutputAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Drop fenced code so it isn't read aloud. Brief replies rarely have any. */
export function speakable(text: string): string {
  return text.replace(/```[\s\S]*?```/g, " ").replace(/\s+/g, " ").trim();
}

export function startListening(onFinal: (transcript: string) => void): SpeechRecognizer | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;
  const recognition = new Ctor();
  recognition.lang = "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = (event) => {
    const pieces: string[] = [];
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (result.isFinal) pieces.push(result[0].transcript);
    }
    const text = pieces.join(" ").trim();
    if (text) onFinal(text);
  };
  recognition.start();
  return recognition;
}

export function speak(text: string, onEnd?: () => void): void {
  const spoken = speakable(text);
  if (!spoken || !speechOutputAvailable()) {
    onEnd?.();
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(spoken);
  utterance.onend = () => onEnd?.();
  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  if (speechOutputAvailable()) window.speechSynthesis.cancel();
}
