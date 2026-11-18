import { useEffect, useRef, useState } from "react";
import { setServer, tokenExpired } from "./api";
import { AuthScreen } from "./components/AuthScreen";
import { ChatPane } from "./components/ChatPane";
import { InfoDialog, KeysDialog, NewChatDialog, TrustDialog } from "./components/Dialogs";
import { Sidebar } from "./components/Sidebar";
import { Toasts } from "./components/Toasts";
import { x25519Supported } from "./crypto";
import { openConversation, startSession, state } from "./engine";
import { useEngine } from "./store";

type Boot = "checking" | "unsupported" | "ready";

function useBoot(): Boot {
  const [boot, setBoot] = useState<Boot>("checking");
  useEffect(() => {
    void (async () => {
      if (!window.isSecureContext || !crypto?.subtle || !(await x25519Supported())) { setBoot("unsupported"); return; }
      setBoot("ready");
      try {
        const saved = JSON.parse(sessionStorage.getItem("dchat:session") ?? "null") as { token: string; username: string } | null;
        if (saved?.token && !tokenExpired(saved.token)) {
          setServer(localStorage.getItem("dchat:server") ?? "auto");
          await startSession(saved.token, saved.username);
        }
      } catch { /* no usable saved session: show sign-in */ }
    })();
  }, []);
  return boot;
}

export function App() {
  const s = useEngine();
  const boot = useBoot();
  const search = useRef<HTMLInputElement>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [prefill, setPrefill] = useState<number | undefined>();
  const [infoOpen, setInfoOpen] = useState(false);
  const [keysOpen, setKeysOpen] = useState(false);

  // Keyboard: Ctrl/Cmd+K focuses chat search; Esc closes the open chat.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); search.current?.focus(); }
      else if (e.key === "Escape" && state.me && !document.querySelector("dialog[open]") && !e.defaultPrevented) {
        const t = e.target as HTMLElement;
        if (t.closest(".find, .emoji-picker")) return;
        openConversation(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Unread count in the tab title; mark the open chat read when the tab regains focus.
  useEffect(() => {
    const total = s.me ? [...s.convs.values()].reduce((n, c) => n + (c.msgs.length ? unread(c.id) : 0), 0) : 0;
    document.title = (total ? `(${total}) ` : "") + "Distributed Chat";
  });
  useEffect(() => {
    const onVis = (): void => { if (document.visibilityState === "visible" && state.activeId != null) openConversation(state.activeId); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  if (boot === "checking") return null;
  if (boot === "unsupported") {
    return (
      <main className="auth"><div className="auth-card">
        <h1>Browser not supported</h1>
        <p>End-to-end encryption needs X25519 support in the Web Crypto API. Use a current Chrome / Edge (133+), Firefox (130+) or Safari (17+), on <code>localhost</code> or HTTPS.</p>
      </div></main>
    );
  }

  return (
    <>
      {s.me ? (
        <div className={`app${s.activeId != null ? " show-chat" : ""}`}>
          <Sidebar ref={search} onNewChat={(id) => { setPrefill(id); setNewOpen(true); }} onKeys={() => setKeysOpen(true)} />
          <ChatPane onInfo={() => setInfoOpen(true)} />
          <NewChatDialog open={newOpen} prefill={prefill} onClose={() => setNewOpen(false)} />
          <InfoDialog open={infoOpen} onClose={() => setInfoOpen(false)} />
          <KeysDialog open={keysOpen} onClose={() => setKeysOpen(false)} />
          <TrustDialog />
        </div>
      ) : <AuthScreen />}
      <Toasts />
    </>
  );
}

import { unreadCount } from "./engine";
const unread = (id: number): number => { const c = state.convs.get(id); return c ? unreadCount(c) : 0; };
