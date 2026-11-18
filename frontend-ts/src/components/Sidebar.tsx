import { forwardRef, useState } from "react";
import { displayName, lastMessage, logout, openConversation, reconnectNow, sortedConversations, toggleNotifications, unreadCount } from "../engine";
import { listTime } from "../format";
import { useEngine } from "../store";
import { Avatar } from "./Avatar";
import { Icon, MiniIcon } from "./Icons";

interface Props { onNewChat: (prefillId?: number) => void; onKeys: () => void }

export const Sidebar = forwardRef<HTMLInputElement, Props>(function Sidebar({ onNewChat, onKeys }, searchRef) {
  const s = useEngine();
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const rows = sortedConversations().filter((c) => !needle || displayName(c.peerId).toLowerCase().includes(needle) || String(c.peerId ?? "").includes(needle));
  const numeric = /^\d+$/.test(q.trim());
  const me = s.me!;

  return (
    <aside className="sidebar">
      <header className="bar">
        <div className="me" title={`${me.username} · user ID ${me.id}`}>
          <Avatar seed={me.id} label={me.username} />
          <span className="me-text"><strong>{me.username}</strong><small>ID {me.id}</small></span>
        </div>
        <div className="bar-actions">
          <button className={`icon${s.notifications ? " active-btn" : ""}`} type="button" onClick={() => void toggleNotifications()} aria-pressed={s.notifications}
            title={s.notifications ? "Notifications on" : "Turn on notifications"} aria-label="Toggle notifications"><Icon name={s.notifications ? "bell" : "bellOff"} /></button>
          <button className="icon" type="button" onClick={onKeys} title="Message keys" aria-label="Message keys"><Icon name="key" /></button>
          <button className="icon" type="button" onClick={() => onNewChat()} title="New chat" aria-label="New chat"><Icon name="newChat" /></button>
          <button className="icon" type="button" onClick={() => logout()} title="Sign out" aria-label="Sign out"><Icon name="logout" /></button>
        </div>
      </header>

      {s.conn !== "online" && (
        <div className={`conn-banner ${s.conn}`}>
          {s.conn === "replaced" ? (
            <>Signed in on another window. <button type="button" onClick={reconnectNow}>Use here</button></>
          ) : (
            <><span className="spin" />{s.conn === "connecting" ? "Connecting…" : "Reconnecting… messages will send when you're back online."}</>
          )}
        </div>
      )}

      <div className="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 14 15.5l.3.3v.8l5 5 1.5-1.5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z" /></svg>
        <input ref={searchRef} type="search" value={q} placeholder="Search or start a new chat" aria-label="Search chats"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && numeric && !rows.length) onNewChat(parseInt(q, 10)); if (e.key === "Escape") setQ(""); }} />
      </div>

      <ul className="conv-list" role="listbox" aria-label="Chats">
        {!rows.length && (
          <li className="list-empty">
            {s.loading ? "Loading chats…" : q ? "No chats found." : "No chats yet."}
            {!s.loading && (numeric
              ? <button type="button" className="link" onClick={() => onNewChat(parseInt(q, 10))}>Start a chat with user {q.trim()}</button>
              : <button type="button" className="link" onClick={() => onNewChat()}>Start a new chat</button>)}
          </li>
        )}
        {rows.map((c) => {
          const name = displayName(c.peerId);
          const last = lastMessage(c);
          const unread = unreadCount(c);
          const online = c.peerId != null && s.presence.get(c.peerId) === "online";
          const preview = last ? (last.text != null ? last.text.replace(/\s+/g, " ") : last.status === "failed" ? "Failed to send" : "🔒 Encrypted message") : "No messages yet";
          return (
            <li key={c.id} role="option" aria-selected={c.id === s.activeId}>
              <button type="button" className={`conv${c.id === s.activeId ? " active" : ""}`} onClick={() => openConversation(c.id)}>
                <span className="avatar-wrap"><Avatar seed={c.peerId ?? c.id} label={c.peerId ? name : "?"} />{online && <i className="dot" title="Online" />}</span>
                <span className="conv-main">
                  <span className="conv-top"><strong>{name}</strong><time className={unread ? "unread-time" : ""}>{listTime(last ? last.ts : c.createdAt)}</time></span>
                  <span className="conv-bottom">
                    <span className="preview">
                      {last && last.senderId === me.id && last.status !== "failed" && <MiniIcon name={last.status === "sending" ? "clock" : "check"} className="tick" />}
                      {last?.status === "failed" && <MiniIcon name="warn" className="fail" />}
                      {c.draft.trim() && c.id !== s.activeId ? <><em className="draft">Draft:</em> {c.draft}</> : preview}
                    </span>
                    {unread > 0 && <span className="badge" aria-label={`${unread} unread`}>{unread > 99 ? "99+" : unread}</span>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
});
