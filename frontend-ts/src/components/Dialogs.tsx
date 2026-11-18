import { useEffect, useState, type FormEvent } from "react";
import { answerTrust, displayName, importKeyFile, securityInfo, reviewKey, setContactName, startChat } from "../engine";
import { useEngine } from "../store";
import { Avatar } from "./Avatar";
import { Modal } from "./Modal";

export function NewChatDialog({ open, prefill, onClose }: { open: boolean; prefill?: number; onClose: () => void }) {
  const s = useEngine();
  const [id, setId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setId(prefill ? String(prefill) : ""); setError(""); } }, [open, prefill]);

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    setBusy(true);
    try { await startChat(parseInt(id, 10)); onClose(); }
    catch (err) { setError((err as Error).message || "Couldn't start a chat with that user ID."); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose}>
      <form onSubmit={(e) => void submit(e)}>
        <h3>New chat</h3>
        <p className="muted">Enter the user ID of the person you want to message. Your own ID is <strong>{s.me?.id}</strong> — share it so others can start a chat with you.</p>
        <label>User ID
          <input autoFocus inputMode="numeric" pattern="[0-9]*" required value={id} onChange={(e) => setId(e.target.value.replace(/\D/g, ""))} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="dlg-actions">
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={busy || !id}>{busy ? "Starting…" : "Start chat"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function InfoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useEngine();
  const conv = s.activeId != null ? s.convs.get(s.activeId) : undefined;
  const peerId = conv?.peerId ?? null;
  const name = displayName(peerId);
  const [draft, setDraft] = useState("");
  useEffect(() => { if (open) setDraft(peerId && name !== `User ${peerId}` ? name : ""); }, [open, peerId, name]);
  if (!conv) return <Modal open={false} onClose={onClose}>{null}</Modal>;
  const info = securityInfo(peerId);
  return (
    <Modal open={open} onClose={onClose}>
      <div className="info">
        <h3>Contact info</h3>
        <div className="info-head">
          <Avatar big seed={peerId ?? conv.id} label={peerId ? name : "?"} />
          <div><strong>{name}</strong><small>{peerId ? `User ID ${peerId}` : `Chat ${conv.id}`}</small></div>
        </div>
        <label>Name (only visible to you)
          <input value={draft} maxLength={40} placeholder="e.g. Alice" disabled={!peerId}
            onChange={(e) => setDraft(e.target.value)} onBlur={() => peerId && setContactName(peerId, draft)}
            onKeyDown={(e) => { if (e.key === "Enter" && peerId) { setContactName(peerId, draft); e.currentTarget.blur(); } }} />
        </label>
        <h4>Security code</h4>
        <p className="muted">Compare these codes with your contact on another channel. If they match, nobody is intercepting your messages.</p>
        <div className="fp"><small>Their code</small><code>{info.theirs ?? "Not available yet — they haven't signed in on an encrypted client."}</code></div>
        <div className="fp"><small>Your code</small><code>{info.mine}</code></div>
        <div className="dlg-actions">
          <button type="button" className="ghost" disabled={!peerId} onClick={() => { onClose(); if (peerId) void reviewKey(peerId); }}>Recheck key</button>
          <button type="button" className="primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </Modal>
  );
}

export function TrustDialog() {
  const { trust } = useEngine();
  return (
    <Modal open={!!trust} onClose={() => undefined} dismissable={false}>
      {trust && (
        <div className="info">
          <h3 className="danger">⚠ Security code changed</h3>
          <p><strong>{displayName(trust.peerId)}</strong>'s encryption key is different from the one you saw before. This can happen when they sign in on a new device or browser — or if someone is intercepting your messages.</p>
          <div className="fp"><small>Previous code</small><code>{trust.oldFp}</code></div>
          <div className="fp"><small>New code</small><code>{trust.newFp}</code></div>
          <p className="muted">Only continue if you've confirmed the new code with them.</p>
          <div className="dlg-actions">
            <button type="button" className="ghost" onClick={() => answerTrust(false)}>Don't trust</button>
            <button type="button" className="danger-btn" onClick={() => answerTrust(true)}>Trust new key</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

/** Import a private key file (e.g. the Python client's user<N>_identity.key) to read older messages. */
export function KeysDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useEngine();
  const [file, setFile] = useState<File | null>(null);
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { if (open) { setFile(null); setResult(""); setError(""); setActive(true); } }, [open]);

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError(""); setResult("");
    try {
      if (file.size > 16 * 1024) throw new Error("That file is too large to be a key file.");
      setResult(await importKeyFile(await file.text(), active));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose}>
      <form className="info" onSubmit={(e) => void submit(e)}>
        <h3>Message keys</h3>
        <p className="muted">Messages can only be read with the key they were encrypted with. If you used another browser or the Python client before, import that key file (for example <code>user{s.me?.id}_identity.key</code>) to read those messages here.</p>
        <div className="fp"><small>Your security code (key version {s.myKeyVersion})</small><code>{s.myFingerprint}</code></div>
        <p className="muted">Keys stored in this browser: <strong>{s.keyCount}</strong></p>
        <label>Key file
          <input type="file" accept=".key,.pem,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="check">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Also use this key for new messages (same key as the Python client). Your contacts will see your security code change once.
        </label>
        <p className="muted">The key never leaves this browser. It is stored so it can't be read back out.</p>
        {error && <p className="error" role="alert">{error}</p>}
        {result && <p role="status">{result}</p>}
        <div className="dlg-actions">
          <button type="button" className="ghost" onClick={onClose}>Close</button>
          <button type="submit" className="primary" disabled={busy || !file}>{busy ? "Importing…" : "Import key"}</button>
        </div>
      </form>
    </Modal>
  );
}
