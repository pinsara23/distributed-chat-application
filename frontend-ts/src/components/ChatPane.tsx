import { useEffect, useMemo, useRef, useState } from "react";
import { assignPeer, displayName, openConversation, reviewKey, toast } from "../engine";
import { useEngine } from "../store";
import { Avatar } from "./Avatar";
import { Composer } from "./Composer";
import { Icon, MiniIcon } from "./Icons";
import { MessageList } from "./MessageList";

function AssignPeer({ convId }: { convId: number }) {
  const [id, setId] = useState("");
  const go = async (): Promise<void> => {
    try { await assignPeer(convId, parseInt(id, 10)); } catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="locked-bar">
      <span>The server doesn't say who this chat is with. Enter their user ID to continue:</span>
      <input inputMode="numeric" value={id} placeholder="Other person's user ID" aria-label="Other person's user ID"
        onChange={(e) => setId(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void go(); } }} />
      <button type="button" className="primary" onClick={() => void go()}>Confirm</button>
    </div>
  );
}

export function ChatPane({ onInfo }: { onInfo: () => void }) {
  const s = useEngine();
  const conv = s.activeId != null ? s.convs.get(s.activeId) : undefined;
  const [finding, setFinding] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const findInput = useRef<HTMLInputElement>(null);

  useEffect(() => { setFinding(false); setQuery(""); setCursor(0); }, [conv?.id]);
  useEffect(() => { if (finding) findInput.current?.focus(); }, [finding]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !conv) return [];
    return conv.msgs.filter((m) => m.text?.toLowerCase().includes(q)).map((m) => m.uuid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, conv, conv?.msgs.length]);
  useEffect(() => { setCursor(matches.length ? matches.length - 1 : 0); }, [query, matches.length]);
  const step = (d: number): void => { if (matches.length) setCursor((c) => (c + d + matches.length) % matches.length); };

  if (!conv) {
    return (
      <section className="chat">
        <div className="empty">
          <div className="logo"><svg viewBox="0 0 32 32" width="84" height="84"><rect width="32" height="32" rx="8" fill="currentColor" /><path d="M8 9h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H15l-5 4v-4H8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z" fill="#fff" /></svg></div>
          <h2>Distributed Chat</h2>
          <p>Select a chat, or start a new one with a user ID.<br />Messages are end-to-end encrypted in your browser.</p>
        </div>
      </section>
    );
  }

  const name = displayName(conv.peerId);
  const presence = conv.peerId ? s.presence.get(conv.peerId) : undefined;
  const blocked = conv.peerId != null && s.blocked.has(conv.peerId);

  return (
    <section className="chat">
      <div className="thread">
        <header className="bar">
          <button className="icon back" type="button" aria-label="Back to chats" onClick={() => openConversation(null)}><Icon name="back" /></button>
          <button className="peer" type="button" onClick={onInfo} title="Contact info & security code">
            <Avatar seed={conv.peerId ?? conv.id} label={conv.peerId ? name : "?"} />
            <span className="peer-text">
              <strong>{name}</strong>
              <small className={presence === "online" ? "online" : ""}>
                {presence === "online" ? "online" : presence === "offline" ? "offline" : conv.peerId ? `ID ${conv.peerId}` : "Unknown contact"}
              </small>
            </span>
          </button>
          <div className="bar-actions">
            <button className={`icon${finding ? " active-btn" : ""}`} type="button" title="Search in chat" aria-label="Search in chat" aria-pressed={finding} onClick={() => setFinding((v) => !v)}><Icon name="search" /></button>
            <button className="icon" type="button" title="Contact info" aria-label="Contact info" onClick={onInfo}><Icon name="info" /></button>
          </div>
        </header>

        {finding && (
          <div className="find">
            <input ref={findInput} value={query} placeholder="Search in this chat" aria-label="Search in this chat"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); } if (e.key === "Escape") { e.stopPropagation(); setFinding(false); setQuery(""); } }} />
            <small>{query.trim() ? (matches.length ? `${cursor + 1} / ${matches.length}` : "No results") : ""}</small>
            <button className="icon" type="button" aria-label="Previous match" onClick={() => step(-1)}><Icon name="up" /></button>
            <button className="icon" type="button" aria-label="Next match" onClick={() => step(1)}><Icon name="down" /></button>
            <button className="icon" type="button" aria-label="Close search" onClick={() => { setFinding(false); setQuery(""); }}><Icon name="close" /></button>
          </div>
        )}

        <MessageList key={`list-${conv.id}`} conv={conv} query={finding ? query.trim() : ""} currentMatch={matches[cursor] ?? null} />

        {!conv.peerId ? <AssignPeer convId={conv.id} /> : blocked ? (
          <div className="locked-bar">
            <MiniIcon name="warn" className="fail" />
            <span>{name}'s security code changed. Sending is paused.</span>
            <button type="button" className="primary" onClick={() => void reviewKey(conv.peerId!)}>Review</button>
          </div>
        ) : <Composer key={`composer-${conv.id}`} convId={conv.id} initial={conv.draft} />}
      </div>
    </section>
  );
}
