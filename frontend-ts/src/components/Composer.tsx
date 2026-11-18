import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { sendText, setDraft } from "../engine";
import { EmojiPicker } from "./EmojiPicker";
import { Icon } from "./Icons";

/** Mounted with key={conversationId}: each chat keeps its own unsent draft. */
export function Composer({ convId, initial }: { convId: number; initial: string }) {
  const [text, setText] = useState(initial);
  const [emoji, setEmoji] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  const grow = (): void => {
    const t = area.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 140)}px`;
  };
  useEffect(() => { grow(); area.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => { setDraft(convId, text); grow(); }, [convId, text]);
  useEffect(() => {
    if (!emoji) return;
    const onKey = (e: globalThis.KeyboardEvent): void => { if (e.key === "Escape") setEmoji(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [emoji]);

  const submit = (e?: FormEvent): void => {
    e?.preventDefault();
    if (!text.trim()) return;
    void sendText(convId, text);
    setText("");
    setEmoji(false);
    area.current?.focus();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };
  const insert = (em: string): void => {
    const t = area.current;
    const start = t?.selectionStart ?? text.length, end = t?.selectionEnd ?? text.length;
    setText(text.slice(0, start) + em + text.slice(end));
    requestAnimationFrame(() => { t?.focus(); t?.setSelectionRange(start + em.length, start + em.length); });
  };

  return (
    <form className="composer" onSubmit={submit} autoComplete="off">
      {emoji && <EmojiPicker onPick={insert} />}
      <button type="button" className={`icon${emoji ? " on" : ""}`} aria-label="Emoji" aria-pressed={emoji} title="Emoji" onClick={() => setEmoji((v) => !v)}>
        <Icon name="smile" />
      </button>
      <textarea ref={area} rows={1} value={text} maxLength={8000} placeholder="Type a message" aria-label="Message"
        onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown} />
      <button className="send" type="submit" aria-label="Send" title="Send (Enter)"><Icon name="send" /></button>
    </form>
  );
}
