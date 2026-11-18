// Chat engine: session, conversations, E2EE send/receive, WebSocket reconnect + sync.
// Framework-free. React reads `state` through useEngine() (see store.ts).

import { api, ApiError, canFailover, openSocket, rotateServer, tokenExpired, tokenUserId } from "./api";
import { buildAad, decryptMessage, deriveSharedKey, encryptMessage, fingerprint, identities, importIdentity, loadIdentity, type IdentityRecord } from "./crypto";
import type { ConnState, Conversation, Msg, Presence, RawMessage, Toast, TrustPrompt, WireMessage } from "./types";

export const MAX_TEXT_BYTES = 30000; // server cap is 32 KiB of ciphertext
const SYNC_OVERLAP = 20;
const PAGE = 100;

interface State {
  me: { id: number; username: string } | null;
  token: string | null;
  convs: Map<number, Conversation>;
  activeId: number | null;
  conn: ConnState;
  presence: Map<number, Presence>;
  usernames: Map<number, string>; // registered names, from the server
  blocked: Set<number>;
  myFingerprint: string | null;
  myKeyVersion: number;
  keyCount: number;
  loading: boolean;
  toasts: Toast[];
  trust: TrustPrompt | null;
  authMessage: string | null;
  notifications: boolean;
}

export const state: State = {
  me: null, token: null, convs: new Map(), activeId: null, conn: "offline", presence: new Map(), usernames: new Map(),
  blocked: new Set(), myFingerprint: null, myKeyVersion: 1, keyCount: 0, loading: false, toasts: [], trust: null, authMessage: null,
  notifications: typeof Notification !== "undefined" && Notification.permission === "granted",
};

// ---- store plumbing ------------------------------------------------------------
let version = 0;
const listeners = new Set<() => void>();
export const subscribe = (fn: () => void): (() => void) => { listeners.add(fn); return () => listeners.delete(fn); };
export const getVersion = (): number => version;
let queued = false;
function emit(): void {
  version++;
  if (queued) return;
  queued = true;
  queueMicrotask(() => { queued = false; listeners.forEach((fn) => fn()); });
}

let toastId = 0;
export function toast(text: string, kind: Toast["kind"] = "info"): void {
  const t = { id: ++toastId, text, kind };
  state.toasts = [...state.toasts, t];
  emit();
  setTimeout(() => { state.toasts = state.toasts.filter((x) => x.id !== t.id); emit(); }, 4500);
}

// ---- per-user local storage (names, peers, TOFU fingerprints, read marks) ----------
type Store = {
  names: Record<string, string>; peers: Record<string, number>; read: Record<string, number>;
  tofu: Record<string, { fingerprint: string; version: number }>;
  pins: Record<string, Record<string, string>>; // userId -> key_version -> fingerprint, for old keys
};
const lsKey = (name: keyof Store): string => `dchat:${state.me!.id}:${name}`;
function lsGet<K extends keyof Store>(name: K): Store[K] {
  try { return (JSON.parse(localStorage.getItem(lsKey(name)) ?? "null") ?? {}) as Store[K]; } catch { return {} as Store[K]; }
}
function lsSet<K extends keyof Store>(name: K, value: Store[K]): void {
  try { localStorage.setItem(lsKey(name), JSON.stringify(value)); } catch { /* storage unavailable */ }
}

/** Your own nickname for the contact if you set one, else their registered username. */
export const displayName = (peerId: number | null): string =>
  (peerId ? lsGet("names")[peerId] || state.usernames.get(peerId) || `User ${peerId}` : "Unknown contact");
export const nickname = (peerId: number | null): string => (peerId ? lsGet("names")[peerId] ?? "" : "");
export const username = (peerId: number | null): string | null => (peerId ? state.usernames.get(peerId) ?? null : null);
export function setContactName(peerId: number, name: string): void {
  const names = lsGet("names");
  if (name.trim()) names[peerId] = name.trim().slice(0, 40); else delete names[peerId];
  lsSet("names", names);
  emit();
}

// ---- helpers ---------------------------------------------------------------------
const sortMsgs = (a: Msg, b: Msg): number => (a.id ?? Infinity) - (b.id ?? Infinity) || a.ts.getTime() - b.ts.getTime();
const parseTs = (iso: string | null): Date => (iso ? new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z") : new Date());

export const lastMessage = (conv: Conversation): Msg | null => conv.msgs[conv.msgs.length - 1] ?? null;

export function unreadCount(conv: Conversation): number {
  const read = lsGet("read")[conv.id] ?? 0;
  return conv.msgs.reduce((n, m) => n + (m.senderId !== state.me?.id && m.id != null && m.id > read ? 1 : 0), 0);
}
export function markRead(convId: number): void {
  const conv = state.convs.get(convId);
  if (!conv || !conv.lastId || !state.me) return;
  const read = lsGet("read");
  if ((read[convId] ?? 0) >= conv.lastId) return;
  read[convId] = conv.lastId;
  lsSet("read", read);
  emit();
}

export function sortedConversations(): Conversation[] {
  return [...state.convs.values()].sort((a, b) => {
    const la = lastMessage(a), lb = lastMessage(b);
    return (lb ? lb.ts : b.createdAt).getTime() - (la ? la.ts : a.createdAt).getTime();
  });
}

export function setDraft(convId: number, text: string): void {
  const c = state.convs.get(convId);
  if (c) c.draft = text; // no re-render needed: the composer owns its value
}

function makeConv(id: number, createdAt: string): Conversation {
  return { id, createdAt: parseTs(createdAt), peerId: lsGet("peers")[id] ?? null, msgs: [], byUuid: new Map(), lastId: 0, draft: "" };
}

function setPeer(conv: Conversation, peerId: number): void {
  if (conv.peerId === peerId) return;
  conv.peerId = peerId;
  const peers = lsGet("peers");
  peers[conv.id] = peerId;
  lsSet("peers", peers);
  void refreshPresence();
  void retryLocked(conv);
}

// ---- key management (TOFU) -------------------------------------------------------
const keyCache = new Map<number, { key: CryptoKey; version: number; fetchedAt: number }>();
const keyInflight = new Map<number, Promise<CryptoKey | null>>();
let trustResolvers: Array<(accept: boolean) => void> = [];

export class NoKeyError extends Error {}

export function getPeerKey(peerId: number, force = false): Promise<CryptoKey | null> {
  const cached = keyCache.get(peerId);
  if (!force && cached) return Promise.resolve(cached.key);
  if (!force && state.blocked.has(peerId)) return Promise.resolve(null);
  let p = keyInflight.get(peerId);
  if (!p) {
    p = fetchPeerKey(peerId).finally(() => keyInflight.delete(peerId));
    keyInflight.set(peerId, p);
  }
  return p;
}

async function fetchPeerKey(peerId: number): Promise<CryptoKey | null> {
  let data: { public_key_pem: string; key_version: number };
  try {
    data = await api(`/keys/${peerId}`, { token: state.token });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) throw new NoKeyError();
    throw err;
  }
  const fp = await fingerprint(data.public_key_pem);
  const tofu = lsGet("tofu");
  const known = tofu[peerId];
  if (known && known.fingerprint !== fp) {
    const accepted = await askTrust(peerId, known.fingerprint, fp);
    if (!accepted) { state.blocked.add(peerId); keyCache.delete(peerId); emit(); return null; }
  }
  tofu[peerId] = { fingerprint: fp, version: data.key_version };
  lsSet("tofu", tofu);
  state.blocked.delete(peerId);
  const key = await deriveSharedKey(data.public_key_pem);
  keyCache.set(peerId, { key, version: data.key_version, fetchedAt: Date.now() });
  emit();
  return key;
}

function askTrust(peerId: number, oldFp: string, newFp: string): Promise<boolean> {
  return new Promise((resolve) => {
    trustResolvers.push(resolve);
    state.trust = { peerId, oldFp, newFp };
    emit();
  });
}
export function answerTrust(accept: boolean): void {
  const rs = trustResolvers;
  trustResolvers = [];
  state.trust = null;
  emit();
  rs.forEach((r) => r(accept));
}

const convForPeer = (peerId: number): Conversation | undefined => [...state.convs.values()].find((c) => c.peerId === peerId);

/** Re-run the key check for a blocked peer (shows the prompt again). */
export async function reviewKey(peerId: number): Promise<void> {
  state.blocked.delete(peerId);
  keyCache.delete(peerId);
  try {
    if (await getPeerKey(peerId, true)) await retryLocked(convForPeer(peerId));
  } catch (err) {
    toast(err instanceof NoKeyError ? "That user has no encryption key yet." : (err as Error).message, "error");
  }
  emit();
}

export function securityInfo(peerId: number | null): { mine: string | null; theirs: string | null } {
  return { mine: state.myFingerprint, theirs: peerId ? lsGet("tofu")[peerId]?.fingerprint ?? null : null };
}

// ---- old keys (key history) ---------------------------------------------------------
// Messages are encrypted with whatever keys were current when they were sent. After a
// key change (new browser, imported key, Python client) they need the old public keys.
type KeyHistory = { pems: Map<number, string>; fetchedAt: number };
const historyCache = new Map<number, KeyHistory>();
const historyInflight = new Map<number, Promise<KeyHistory>>();
const pairCache = new Map<string, Promise<CryptoKey>>();

function getKeyHistory(userId: number, force = false): Promise<KeyHistory> {
  const cached = historyCache.get(userId);
  if (cached && !force) return Promise.resolve(cached);
  let p = historyInflight.get(userId);
  if (!p) {
    p = fetchKeyHistory(userId).finally(() => historyInflight.delete(userId));
    historyInflight.set(userId, p);
  }
  return p;
}

async function fetchKeyHistory(userId: number): Promise<KeyHistory> {
  let rows: { key_version: number; public_key_pem: string }[] = [];
  try {
    rows = await api(`/keys/${userId}/history`, { token: state.token });
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) throw err; // older server: no history
  }
  const pins = lsGet("pins");
  const pinned = pins[userId] ?? {};
  const pems = new Map<number, string>();
  for (const r of rows) {
    const fp = await fingerprint(r.public_key_pem);
    // A past key must never change. If the server now reports a different one, ignore it.
    if (pinned[r.key_version] && pinned[r.key_version] !== fp) continue;
    pinned[r.key_version] = fp;
    pems.set(r.key_version, r.public_key_pem);
  }
  pins[userId] = pinned;
  lsSet("pins", pins);
  const hist = { pems, fetchedAt: Date.now() };
  historyCache.set(userId, hist);
  return hist;
}

function pairKey(mine: IdentityRecord, peerPem: string): Promise<CryptoKey> {
  const id = `${mine.publicPem}|${peerPem}`;
  let p = pairCache.get(id);
  if (!p) { p = deriveSharedKey(peerPem, mine); pairCache.set(id, p); p.catch(() => pairCache.delete(id)); }
  return p;
}

/** Every (my private key, their public key) pair worth trying, the tagged versions first. */
async function candidatePairs(peerId: number, myVer: number | null | undefined, peerVer: number | null | undefined, force: boolean): Promise<Array<[IdentityRecord, string]>> {
  const [peerHist, myHist] = await Promise.all([getKeyHistory(peerId, force), getKeyHistory(state.me!.id, force)]);
  const peerPems = [...peerHist.pems.values()].reverse(); // newest first
  const preferredPeer = peerVer != null ? peerHist.pems.get(peerVer) : undefined;
  if (preferredPeer) peerPems.unshift(preferredPeer);
  const mineList = identities();
  const myPem = myVer != null ? myHist.pems.get(myVer) : undefined;
  const preferredMine = mineList.find((r) => r.publicPem === myPem);
  if (preferredMine) mineList.unshift(preferredMine);
  const seen = new Set<string>();
  const out: Array<[IdentityRecord, string]> = [];
  for (const m of mineList) for (const pem of peerPems) {
    const id = `${m.publicPem}|${pem}`;
    if (!seen.has(id)) { seen.add(id); out.push([m, pem]); }
  }
  return out;
}

// ---- decrypt / ingest ------------------------------------------------------------
async function decryptInto(conv: Conversation, msg: Msg): Promise<void> {
  const raw = msg.raw;
  if (!conv.peerId || !raw) { msg.status = "locked"; return; }
  const peerId = conv.peerId;
  const mine = msg.senderId === state.me!.id;
  const aad = buildAad(raw.message_uuid, conv.id, raw.sender_id);
  const tryKey = async (key: CryptoKey): Promise<boolean> => {
    try {
      msg.text = await decryptMessage(raw.ciphertext, raw.nonce, key, aad);
      msg.status = mine ? "sent" : "received";
      return true;
    } catch { return false; } // wrong key: AES-GCM authentication fails
  };

  // Current keys first (also runs the security-code check for this contact).
  let current: CryptoKey | null = null;
  try { current = await getPeerKey(peerId); } catch { /* no current key: older keys may still work */ }
  if (!current && state.blocked.has(peerId)) { msg.status = "locked"; return; }
  if (current && await tryKey(current)) return;

  // Then older keys, by the versions the message was tagged with. Refetch once if stale.
  const myVer = mine ? raw.key_version : raw.recipient_key_version;
  const peerVer = mine ? raw.recipient_key_version : raw.key_version;
  let tried = 0;
  for (const force of [false, true]) {
    if (force) {
      if (Date.now() - (historyCache.get(peerId)?.fetchedAt ?? 0) < 5000) break;
      // The contact may have changed keys since we cached them (shows the security prompt).
      try { const k = await getPeerKey(peerId, true); if (k && await tryKey(k)) return; } catch { /* no key */ }
    }
    let pairs: Array<[IdentityRecord, string]>;
    try { pairs = await candidatePairs(peerId, myVer, peerVer, force); } catch { break; }
    for (const [me, pem] of pairs) {
      tried++;
      try { if (await tryKey(await pairKey(me, pem))) return; } catch { /* unusable key */ }
    }
  }
  msg.status = current || tried ? "bad" : "locked";
}

async function retryLocked(conv: Conversation | undefined): Promise<void> {
  if (!conv) return;
  for (const m of conv.msgs) if (m.raw && (m.status === "locked" || m.status === "bad") && m.text == null) await decryptInto(conv, m);
  emit();
}

async function ingest(raw: RawMessage): Promise<void> {
  if (!state.me || raw?.id == null || !raw.message_uuid) return;
  let conv = state.convs.get(raw.conversation_id);
  if (!conv) {
    await loadConversations(); // a brand-new chat started by someone else
    conv = state.convs.get(raw.conversation_id);
    if (!conv) return;
  }
  const mine = raw.sender_id === state.me.id;
  if (!mine && conv.peerId !== raw.sender_id) setPeer(conv, raw.sender_id);

  const existing = conv.byUuid.get(raw.message_uuid);
  if (existing && existing.id != null) return; // already processed (dedupe)
  const isNew = !existing;
  const msg: Msg = existing ?? { uuid: raw.message_uuid, id: null, convId: conv.id, senderId: raw.sender_id, text: null, status: "locked", ts: parseTs(raw.created_at) };
  if (!existing) { conv.byUuid.set(msg.uuid, msg); conv.msgs.push(msg); }
  const ownPending = msg.text != null && mine; // echo of our optimistic message: keep plaintext
  msg.id = raw.id;
  msg.ts = parseTs(raw.created_at);
  msg.raw = raw;
  conv.lastId = Math.max(conv.lastId, raw.id);
  pending.delete(msg.uuid);
  reencrypts.delete(msg.uuid);
  if (ownPending) msg.status = "sent"; else await decryptInto(conv, msg);
  conv.msgs.sort(sortMsgs);
  const visible = document.visibilityState === "visible" && conv.id === state.activeId;
  if (isNew && !mine) { if (visible) markRead(conv.id); else notify(conv, msg); }
  emit();
}

function notify(conv: Conversation, msg: Msg): void {
  if (!state.notifications || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    const n = new Notification(displayName(conv.peerId), { body: msg.text ?? "🔒 Encrypted message", tag: `conv-${conv.id}` });
    n.onclick = () => { window.focus(); openConversation(conv.id); n.close(); };
  } catch { /* notifications unsupported */ }
}

export async function toggleNotifications(): Promise<void> {
  if (typeof Notification === "undefined") return toast("Notifications aren't supported in this browser.", "error");
  if (state.notifications) { state.notifications = false; emit(); return; }
  const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  state.notifications = perm === "granted";
  if (perm !== "granted") toast("Notifications are blocked in your browser settings.", "error");
  emit();
}

// ---- REST: conversations & history -------------------------------------------------
async function loadHistory(conv: Conversation): Promise<void> {
  const url = `/conversations/${conv.id}/messages`;
  if (conv.lastId > 0) {
    const rows = await api<RawMessage[]>(url, { token: state.token, query: { after_id: Math.max(1, conv.lastId - SYNC_OVERLAP) } });
    for (const r of rows) await ingest(r);
    return;
  }
  for (let page = 1; ; page++) {
    const rows = await api<RawMessage[]>(url, { token: state.token, query: { page, limit: PAGE } });
    for (const r of rows) await ingest(r);
    if (rows.length < PAGE) break;
  }
}

type ConvPayload = { id: number; created_at: string; participants?: { id: number; username: string }[] };

/** Record members' usernames and set the chat's other member (the server now says who it is). */
function applyParticipants(conv: Conversation, c: ConvPayload): void {
  for (const p of c.participants ?? []) state.usernames.set(p.id, p.username);
  const other = c.participants?.find((p) => p.id !== state.me?.id);
  if (other) setPeer(conv, other.id);
}

export async function loadConversations(): Promise<void> {
  const list = await api<ConvPayload[]>("/conversations/", { token: state.token });
  const fresh: Conversation[] = [];
  for (const c of list) {
    let conv = state.convs.get(c.id);
    if (!conv) { conv = makeConv(c.id, c.created_at); state.convs.set(c.id, conv); fresh.push(conv); }
    applyParticipants(conv, c);
  }
  emit();
  await Promise.all(fresh.map((c) => loadHistory(c).catch((e: Error) => toast(`Could not load chat ${c.id}: ${e.message}`, "error"))));
  void refreshPresence();
}

const syncAll = (): Promise<unknown> => Promise.all([...state.convs.values()].map((c) => loadHistory(c).catch(() => undefined)));

export async function startChat(peerId: number): Promise<void> {
  if (!Number.isInteger(peerId) || peerId < 1) throw new Error("Enter a valid user ID.");
  if (peerId === state.me!.id) throw new Error("You can't chat with yourself.");
  const c = await api<ConvPayload>("/conversations/", { method: "POST", token: state.token, json: { user_id: peerId } });
  let conv = state.convs.get(c.id);
  if (!conv) { conv = makeConv(c.id, c.created_at); state.convs.set(c.id, conv); }
  applyParticipants(conv, c);
  setPeer(conv, peerId);
  emit();
  await loadHistory(conv).catch(() => undefined);
  openConversation(conv.id);
}

/** For a chat whose other member can't be inferred: verify the user's guess with the server. */
export async function assignPeer(convId: number, peerId: number): Promise<void> {
  if (!Number.isInteger(peerId) || peerId < 1 || peerId === state.me!.id) throw new Error("Enter the other person's user ID.");
  const c = await api<{ id: number }>("/conversations/", { method: "POST", token: state.token, json: { user_id: peerId } });
  if (c.id !== convId) throw new Error("That user is not in this chat.");
  setPeer(state.convs.get(convId)!, peerId);
  emit();
}

export function openConversation(id: number | null): void {
  state.activeId = id;
  if (id != null) markRead(id);
  emit();
}

// ---- presence ----------------------------------------------------------------------
let presenceTimer: number | undefined;
export async function refreshPresence(): Promise<void> {
  if (!state.me) return;
  const peers = [...new Set([...state.convs.values()].map((c) => c.peerId).filter((p): p is number => !!p))];
  await Promise.all(peers.map(async (id) => {
    try { state.presence.set(id, (await api<{ status: Presence }>(`/users/${id}/presence`, { token: state.token })).status); }
    catch { state.presence.set(id, "unknown"); }
  }));
  emit();
}

// ---- sending -----------------------------------------------------------------------
const pending = new Map<string, WireMessage>(); // uuid -> payload awaiting the server's echo

export async function sendText(convId: number, text: string): Promise<boolean> {
  const conv = state.convs.get(convId);
  text = text.replace(/\s+$/, "");
  if (!conv || !text) return false;
  if (!conv.peerId) { toast("Set who this chat is with first.", "error"); return false; }
  if (new TextEncoder().encode(text).length > MAX_TEXT_BYTES) { toast("Message is too long.", "error"); return false; }
  let key: CryptoKey | null;
  try { key = await getPeerKey(conv.peerId); }
  catch (err) {
    toast(err instanceof NoKeyError ? `${displayName(conv.peerId)} hasn't set up encryption yet. They need to sign in once.` : (err as Error).message, "error");
    return false;
  }
  if (!key) { toast("Message not sent: review the changed security code first.", "error"); return false; }

  const uuid = crypto.randomUUID();
  const { ciphertext, nonce } = await encryptMessage(text, key, buildAad(uuid, conv.id, state.me!.id));
  const payload: WireMessage = { message_id: uuid, conversation_id: conv.id, target_user_id: conv.peerId, ciphertext, nonce,
    key_version: state.myKeyVersion, recipient_key_version: keyCache.get(conv.peerId)?.version };
  const msg: Msg = { uuid, id: null, convId: conv.id, senderId: state.me!.id, text, status: "sending", ts: new Date() };
  conv.byUuid.set(uuid, msg);
  conv.msgs.push(msg);
  conv.msgs.sort(sortMsgs);
  pending.set(uuid, payload);
  emit();
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  return true;
}

export function discardFailed(convId: number, uuid: string, resend: boolean): void {
  const conv = state.convs.get(convId);
  const msg = conv?.byUuid.get(uuid);
  if (!conv || !msg || msg.status !== "failed") return;
  conv.byUuid.delete(uuid);
  conv.msgs = conv.msgs.filter((m) => m !== msg);
  emit();
  if (resend && msg.text) void sendText(convId, msg.text);
}

/** The server says the contact's key changed since we encrypted: fetch it and re-encrypt (same id). */
const reencrypts = new Map<string, number>();
async function reencrypt(uuid: string): Promise<void> {
  const p = pending.get(uuid);
  const conv = p ? state.convs.get(p.conversation_id) : undefined;
  const msg = conv?.byUuid.get(uuid);
  if (!p || !conv || !msg || msg.text == null) return;
  const attempts = (reencrypts.get(uuid) ?? 0) + 1;
  reencrypts.set(uuid, attempts);
  if (attempts > 3) { reencrypts.delete(uuid); failMessage(uuid, "Your contact's key keeps changing. Try again."); return; }
  let key: CryptoKey | null;
  try { key = await getPeerKey(p.target_user_id, true); } catch { failMessage(uuid, "Your contact has no encryption key."); return; }
  if (!key) { failMessage(uuid, "Not sent: review the changed security code first."); return; }
  const { ciphertext, nonce } = await encryptMessage(msg.text, key, buildAad(uuid, conv.id, state.me!.id));
  const next: WireMessage = { ...p, ciphertext, nonce, key_version: state.myKeyVersion, recipient_key_version: keyCache.get(p.target_user_id)?.version };
  if (!pending.has(uuid)) return; // delivered or discarded meanwhile
  pending.set(uuid, next);
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(next));
}

function failMessage(uuid: string, reason: string): void {
  pending.delete(uuid);
  for (const conv of state.convs.values()) {
    const m = conv.byUuid.get(uuid);
    if (m && m.id == null) { m.status = "failed"; m.error = reason; }
  }
  emit();
}

// ---- WebSocket lifecycle -------------------------------------------------------------
let ws: WebSocket | null = null;
let retryDelay = 1000;
let retryTimer: number | undefined;
let heartbeat: number | undefined;
let stopped = true;

function setConn(conn: ConnState): void { state.conn = conn; emit(); }

export function connect(): void {
  if (stopped || !state.token) return;
  clearTimeout(retryTimer);
  if (tokenExpired(state.token)) return logout("Your session expired. Please sign in again.");
  setConn("connecting");
  if (ws) { // never keep two sockets: each would deliver (and sync) everything again
    const old = ws;
    ws = null;
    old.onclose = null; old.onmessage = null; old.onopen = null;
    try { old.close(1000); } catch { /* already closed */ }
  }
  let socket: WebSocket;
  try { socket = openSocket(state.token); } catch { scheduleReconnect(); return; }
  ws = socket;
  let opened = false;

  socket.onopen = () => {
    opened = true;
    retryDelay = 1000;
    setConn("online");
    clearInterval(heartbeat);
    heartbeat = window.setInterval(() => socket.readyState === WebSocket.OPEN && socket.send(JSON.stringify({ type: "ping" })), 10000);
    for (const p of pending.values()) socket.send(JSON.stringify(p)); // idempotent by message_id
    void syncAll().then(refreshPresence);
  };
  socket.onmessage = (ev) => {
    let data: Record<string, unknown>;
    try { data = JSON.parse(ev.data as string); } catch { return; }
    if (data.type === "pong") return;
    if (data.error) {
      const id = data.message_id as string | undefined;
      if (data.code === "stale_recipient_key" && id) { void reencrypt(id); return; } // handled silently
      if (id && data.retryable === false) failMessage(id, String(data.error));
      else if (id) setTimeout(() => { const p = pending.get(id); if (p && ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(p)); }, 3000);
      toast(String(data.error), "error");
      return;
    }
    void ingest(data as unknown as RawMessage);
  };
  socket.onclose = (ev) => {
    if (socket !== ws) return;
    clearInterval(heartbeat);
    if (stopped) return;
    if (ev.code === 1000 && /replaced/i.test(ev.reason)) { setConn("replaced"); return; } // signed in elsewhere
    if (ev.code === 1008) return logout("Your session is no longer valid. Please sign in again.");
    setConn("offline");
    if (!opened && canFailover()) rotateServer(); // this server is down: try the next one
    scheduleReconnect();
  };
}

function scheduleReconnect(): void {
  clearTimeout(retryTimer);
  emit();
  retryTimer = window.setTimeout(connect, retryDelay);
  retryDelay = Math.min(retryDelay * 1.5, 15000);
}

export function reconnectNow(): void { retryDelay = 1000; connect(); }

// ---- session -------------------------------------------------------------------------
export async function login(username: string, password: string): Promise<string> {
  return (await api<{ access_token: string }>("/auth/login", { method: "POST", form: { username, password } })).access_token;
}
export async function register(username: string, email: string, password: string): Promise<void> {
  await api("/auth/register", { method: "POST", json: { username, email, password } });
}

// React StrictMode (dev) runs the boot effect twice: share one in-flight start per token
// instead of racing two sessions (two sockets, two history loads).
let starting: { token: string; p: Promise<void> } | null = null;
export function startSession(token: string, username: string): Promise<void> {
  if (starting?.token === token) return starting.p;
  const p = doStartSession(token, username).finally(() => { if (starting?.p === p) starting = null; });
  starting = { token, p };
  return p;
}

async function doStartSession(token: string, username: string): Promise<void> {
  const id = tokenUserId(token);
  if (!id) throw new Error("Invalid session token.");
  stopped = false;
  state.token = token;
  state.me = { id, username };
  state.convs = new Map();
  state.presence = new Map();
  state.usernames = new Map();
  state.blocked = new Set();
  state.activeId = null;
  state.authMessage = null;
  keyCache.clear();
  historyCache.clear();
  pairCache.clear();
  pending.clear();
  retryDelay = 1000;

  try {
    const identity = await loadIdentity(id);
    state.myFingerprint = identity.fingerprint;
    // Publishing the same key again is a no-op server side; a new key bumps key_version.
    const published = await api<{ key_version: number }>("/keys/", { method: "POST", token, json: { public_key_pem: identity.publicPem } });
    state.myKeyVersion = published.key_version;
    state.keyCount = identities().length;
    state.loading = true;
    emit();
    await loadConversations();
  } catch (err) {
    logout();
    throw err;
  }
  state.loading = false;
  emit();
  connect();
  clearInterval(presenceTimer);
  presenceTimer = window.setInterval(() => void refreshPresence(), 15000);
}

/**
 * Import a private key file (e.g. the Python client's user<N>_identity.key) so messages
 * encrypted with it become readable. With `makeActive`, it is also used for new messages,
 * so this browser and the Python client share one key.
 */
export async function importKeyFile(pemText: string, makeActive: boolean): Promise<string> {
  const me = state.me;
  if (!me) throw new Error("Not signed in.");
  const r = await importIdentity(me.id, pemText, makeActive);
  keyCache.clear();
  pairCache.clear();
  historyCache.delete(me.id);
  if (makeActive) {
    const published = await api<{ key_version: number }>("/keys/", { method: "POST", token: state.token, json: { public_key_pem: r.publicPem } });
    state.myKeyVersion = published.key_version;
    state.myFingerprint = r.fingerprint;
  }
  state.keyCount = identities().length;
  emit();
  let before = 0, after = 0;
  for (const conv of state.convs.values()) {
    before += conv.msgs.filter((m) => m.text == null && m.raw).length;
    await retryLocked(conv);
    after += conv.msgs.filter((m) => m.text == null && m.raw).length;
  }
  const opened = before - after;
  return `${r.isNew ? "Key imported" : "Key was already in this browser"}${makeActive ? " and set as your active key" : ""}. ${opened} message${opened === 1 ? "" : "s"} unlocked.`;
}

export function logout(message?: string): void {
  stopped = true;
  clearTimeout(retryTimer);
  clearInterval(heartbeat);
  clearInterval(presenceTimer);
  if (ws) { const s = ws; ws = null; s.onclose = null; try { s.close(1000); } catch { /* already closed */ } }
  try { sessionStorage.removeItem("dchat:session"); } catch { /* ignore */ }
  state.me = null;
  state.token = null;
  state.convs = new Map();
  state.activeId = null;
  state.conn = "offline";
  state.loading = false;
  state.trust = null;
  state.authMessage = message ?? null;
  emit();
}
