import { useState, type FormEvent } from "react";
import { ApiError, DEFAULT_BASE_URL, checkConnection, type ApiConfig } from "../api";

interface Props {
  initial: ApiConfig | null;
  onSave: (config: ApiConfig) => void;
  onCancel?: () => void;
}

export function KeyDialog({ initial, onSave, onCancel }: Props) {
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? DEFAULT_BASE_URL);
  const [apiKey, setApiKey] = useState(initial?.apiKey ?? "");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const config = { baseUrl: baseUrl.trim(), apiKey: apiKey.trim() };
    setChecking(true);
    setError(null);
    try {
      await checkConnection(config);
      onSave(config);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That key was rejected. Use the MX_API_KEY value from your .env file."
          : err instanceof Error ? err.message : "Couldn't connect.",
      );
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="key-title" onSubmit={submit}>
        <h2 id="key-title">Connect to mX</h2>
        <p className="dialog-text">
          Enter your mX API address and the <code>MX_API_KEY</code> from your <code>.env</code>. They're saved in
          this browser only.
        </p>
        <label>
          API address
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required spellCheck={false} />
        </label>
        <label>
          API key
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            required
            autoComplete="off"
            autoFocus
          />
        </label>
        {error && <div className="note error">{error}</div>}
        <div className="dialog-actions">
          {onCancel && (
            <button type="button" className="button-secondary" onClick={onCancel}>
              Cancel
            </button>
          )}
          <button type="submit" className="button-primary" disabled={checking}>
            {checking ? "Checking…" : "Connect"}
          </button>
        </div>
      </form>
    </div>
  );
}
