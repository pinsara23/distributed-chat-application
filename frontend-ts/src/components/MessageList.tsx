import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { discardFailed, displayName, state } from "../engine";
import { dayLabel, formatTime, renderText, sameDay } from "../format";
import type { Conversation, Msg } from "../types";
import { Icon, MiniIcon } from "./Icons";

interface Props { conv: Conversation; query: string; currentMatch: string | null }

function Bubble({ conv, m, query, current }: { conv: Conversation; m: Msg; query: string; current: boolean }) {
  const mine = m.senderId === state.me!.id;
  const copy = (): void => { if (m.text) void navigator.clipboard?.writeText(m.text); };
  return (
    <div className={`msg ${mine ? "out" : "in"}${m.status === "failed" ? " failed" : ""}${current ? " match-current" : ""}`} data-uuid={m.uuid}>
      {m.text != null ? (
        <span className="text">{renderText(m.text, query, current)}</span>
      ) : m.status === "bad" ? (
        <span className="text sys"><MiniIcon name="warn" />This message couldn't be decrypted.</span>
      ) : (
        <span className="text sys"><MiniIcon name="lock" />{conv.peerId ? "Waiting for encryption key…" : "Set the contact to read this message."}</span>
      )}
      <span className="meta">
        <time>{formatTime(m.ts)}</time>
        {mine && (m.status === "sending" ? <MiniIcon name="clock" className="tick" /> : m.status === "failed" ? <MiniIcon name="warn" className="fail" /> : <MiniIcon name="check" className="tick" />)}
      </span>
      {m.text != null && <button type="button" className="copy" onClick={copy} aria-label="Copy message" title="Copy"><Icon name="copy" /></button>}
      {m.status === "failed" && (
        <div className="fail-actions">
          {m.error ?? "Not sent."}
          <button type="button" className="link" onClick={() => discardFailed(conv.id, m.uuid, true)}>Retry</button>
          <button type="button" className="link" onClick={() => discardFailed(conv.id, m.uuid, false)}>Delete</button>
        </div>
      )}
    </div>
  );
}

export function MessageList({ conv, query, currentMatch }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const lastLen = useRef(0);
  const [away, setAway] = useState(0); // messages that arrived while scrolled up
  const [showFab, setShowFab] = useState(false);

  const toBottom = useCallback((smooth = false): void => {
    const el = box.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  useLayoutEffect(() => { stick.current = true; lastLen.current = conv.msgs.length; setAway(0); toBottom(); }, [conv.id, toBottom]);

  useLayoutEffect(() => {
    const added = conv.msgs.length - lastLen.current;
    lastLen.current = conv.msgs.length;
    const last = conv.msgs[conv.msgs.length - 1];
    if (stick.current || (last && last.senderId === state.me!.id)) toBottom(true);
    else if (added > 0) setAway((n) => n + added);
  });

  useEffect(() => {
    if (!currentMatch) return;
    box.current?.querySelector(`[data-uuid="${CSS.escape(currentMatch)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [currentMatch]);

  const onScroll = (): void => {
    const el = box.current!;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    stick.current = near;
    setShowFab(!near);
    if (near) setAway(0);
  };

  let day: Date | null = null;
  return (
    <div className="chat-wrap">
      <div className="messages" ref={box} onScroll={onScroll} tabIndex={0} aria-live="polite">
        <div className="e2ee-note"><MiniIcon name="lock" /> Messages are end-to-end encrypted. Only you and {displayName(conv.peerId)} can read them.</div>
        {conv.msgs.map((m) => {
          const sep = !day || !sameDay(day, m.ts);
          day = m.ts;
          return (
            <Fragment key={m.uuid}>
              {sep && <div className="day"><span>{dayLabel(m.ts)}</span></div>}
              <Bubble conv={conv} m={m} query={query} current={m.uuid === currentMatch} />
            </Fragment>
          );
        })}
      </div>
      {showFab && (
        <button type="button" className="fab" onClick={() => toBottom(true)} aria-label="Scroll to latest message">
          <Icon name="down" />
          {away > 0 && <span className="badge">{away}</span>}
        </button>
      )}
    </div>
  );
}
