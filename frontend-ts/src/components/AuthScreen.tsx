import { useState, type FormEvent } from "react";
import { SERVER_CHOICES, setServer } from "../api";
import { login, register, startSession } from "../engine";
import { useEngine } from "../store";

function savedServer(): string {
  try { return localStorage.getItem("dchat:server") ?? "auto"; } catch { return "auto"; }
}

export function AuthScreen() {
  const { authMessage } = useEngine();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [server, setServerValue] = useState(savedServer);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const u = username.trim();
    if (!u || !password || (mode === "register" && !email.trim())) { setError("Please fill in all fields."); return; }
    setBusy(true);
    setError("");
    setServer(server);
    try { localStorage.setItem("dchat:server", server); } catch { /* ignore */ }
    try {
      if (mode === "register") await register(u, email.trim(), password);
      const token = await login(u, password);
      try { sessionStorage.setItem("dchat:session", JSON.stringify({ token, username: u })); } catch { /* ignore */ }
      setPassword("");
      await startSession(token, u);
    } catch (err) {
      setError((err as Error).message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const shown = error || authMessage || "";
  return (
    <main className="auth">
      <div className="auth-card">
        <div className="logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="56" height="56"><rect width="32" height="32" rx="8" fill="currentColor" /><path d="M8 9h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H15l-5 4v-4H8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z" fill="#fff" /></svg>
        </div>
        <h1>Distributed Chat</h1>
        <p className="muted">End-to-end encrypted messaging</p>
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => { setMode("login"); setError(""); }}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === "register"} onClick={() => { setMode("register"); setError(""); }}>Create account</button>
        </div>
        <form onSubmit={(e) => void submit(e)} noValidate>
          <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" maxLength={50} autoFocus /></label>
          {mode === "register" && <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={120} /></label>}
          <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} /></label>
          <label>Server
            <select value={server} onChange={(e) => setServerValue(e.target.value)}>
              {SERVER_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          {shown && <p className="error" role="alert">{shown}</p>}
          <button className="primary" type="submit" disabled={busy}>{busy ? "Please wait…" : mode === "register" ? "Create account" : "Sign in"}</button>
        </form>
        <p className="fine">Your messages are encrypted in this browser. The server only ever sees ciphertext.</p>
      </div>
    </main>
  );
}
