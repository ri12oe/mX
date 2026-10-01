import { useState, type FormEvent } from "react";
import { ApiError, login } from "../api";
import { Core } from "./Core";

/** Sign in with MX_PASSWORD; the server answers with an HttpOnly session cookie. */
export function LoginDialog({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setChecking(true);
    setError(null);
    try {
      await login(password);
      setPassword("");
      onSignedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign in.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="login-title" onSubmit={submit}>
        <div className="dialog-core">
          <Core state={checking ? "thinking" : error ? "error" : "idle"} size={96} showLabel={false} />
        </div>
        <h2 id="login-title">Sign in to mX</h2>
        <p className="dialog-text">Enter your mX password. You'll stay signed in on this device for 30 days.</p>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            autoFocus
          />
        </label>
        {error && <div className="note error">{error}</div>}
        <div className="dialog-actions">
          <button type="submit" className="button-primary" disabled={checking || !password}>
            {checking ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
