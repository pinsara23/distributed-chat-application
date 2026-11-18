// End-to-end encryption, wire-compatible with client/crypto.py:
//   X25519 ECDH -> HKDF-SHA256 (salt none, info "distributed-chat-e2ee-v1") -> AES-256-GCM,
//   96-bit random nonce, AAD "dchat-e2ee|v1|<message_id>|<conversation_id>|<sender_id>".

export const PROTOCOL_VERSION = 1;
const HKDF_INFO = new TextEncoder().encode("distributed-chat-e2ee-v1");
const SPKI_PREFIX = Uint8Array.from([0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x6e, 0x03, 0x21, 0x00]);
const enc = new TextEncoder();
const dec = new TextDecoder("utf-8", { fatal: true });

export function b64encode(bytes: ArrayBuffer | Uint8Array): string {
  const u = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = "";
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s);
}

export function b64decode(str: string): Uint8Array {
  const s = atob(str);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

export async function x25519Supported(): Promise<boolean> {
  try {
    await crypto.subtle.generateKey({ name: "X25519" }, false, ["deriveBits"]);
    return true;
  } catch {
    return false;
  }
}

export function buildAad(messageId: string, conversationId: number, senderId: number, version = PROTOCOL_VERSION): Uint8Array {
  const fields: [string, number][] = [["conversation_id", conversationId], ["sender_id", senderId], ["protocol_version", version]];
  for (const [name, v] of fields) {
    if (!Number.isInteger(v) || v < 1) throw new Error(`${name} must be a positive integer`);
  }
  return enc.encode(`dchat-e2ee|v${version}|${messageId.toLowerCase()}|${conversationId}|${senderId}`);
}

// PEM text must match the Python client's output: fingerprints are SHA-256 of the PEM string.
function spkiToPem(spki: Uint8Array): string {
  return `-----BEGIN PUBLIC KEY-----\n${(b64encode(spki).match(/.{1,64}/g) ?? []).join("\n")}\n-----END PUBLIC KEY-----\n`;
}

function pemToSpki(pem: string): Uint8Array {
  const der = b64decode(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""));
  if (der.length !== SPKI_PREFIX.length + 32 || !SPKI_PREFIX.every((b, i) => der[i] === b)) {
    throw new Error("Not an X25519 public key");
  }
  return der;
}

export async function fingerprint(pem: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(pem)));
  return [...digest].map((b) => b.toString(16).padStart(2, "0").toUpperCase()).join(":");
}

// ---- identity storage: IndexedDB, private keys are NON-extractable ----
// A keyring keeps every private key this browser has used (generated or imported),
// so messages encrypted under an older key stay readable after a key change.
export interface IdentityRecord { privateKey: CryptoKey; publicPem: string }
interface KeyringRecord { active: IdentityRecord; all: IdentityRecord[] }

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("dchat", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("identity");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet<T>(key: string): Promise<T | undefined> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const r = db.transaction("identity").objectStore("identity").get(key);
    r.onsuccess = () => resolve(r.result as T | undefined);
    r.onerror = () => reject(r.error);
  });
}

async function idbPut(key: string, value: unknown): Promise<void> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("identity", "readwrite");
    tx.objectStore("identity").put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

let ring: KeyringRecord | null = null;

/** Every private key this browser holds for the signed-in user, active one first. */
export function identities(): IdentityRecord[] {
  if (!ring) return [];
  return [ring.active, ...ring.all.filter((r) => r.publicPem !== ring!.active.publicPem)];
}

export async function loadIdentity(userId: number): Promise<{ publicPem: string; fingerprint: string }> {
  let rec = await idbGet<KeyringRecord>(`keyring:${userId}`);
  if (!rec) {
    let first = await idbGet<IdentityRecord>(`user:${userId}`); // single-key format from older builds
    if (!first) {
      const pair = (await crypto.subtle.generateKey({ name: "X25519" }, false, ["deriveBits"])) as CryptoKeyPair;
      const spki = new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey));
      first = { privateKey: pair.privateKey, publicPem: spkiToPem(spki) };
    }
    rec = { active: first, all: [first] };
    await idbPut(`keyring:${userId}`, rec);
  }
  ring = rec;
  return { publicPem: rec.active.publicPem, fingerprint: await fingerprint(rec.active.publicPem) };
}

/**
 * Import a PEM (PKCS#8) X25519 private key, e.g. the Python client's `user<N>_identity.key`.
 * The key is added to the keyring; with `makeActive` it also becomes the key used for new messages.
 */
export async function importIdentity(userId: number, pemText: string, makeActive: boolean): Promise<{ publicPem: string; fingerprint: string; isNew: boolean }> {
  if (!ring) throw new Error("Identity not loaded");
  const m = /-----BEGIN PRIVATE KEY-----([\s\S]+?)-----END PRIVATE KEY-----/.exec(pemText);
  if (!m) throw new Error("That file isn't an unencrypted PEM private key (expected \"BEGIN PRIVATE KEY\").");
  let jwk: JsonWebKey;
  try {
    const tmp = await crypto.subtle.importKey("pkcs8", b64decode(m[1].replace(/\s+/g, "")), { name: "X25519" }, true, ["deriveBits"]);
    jwk = await crypto.subtle.exportKey("jwk", tmp);
  } catch {
    throw new Error("That file isn't an X25519 private key.");
  }
  if (!jwk.x) throw new Error("Could not read the public half of that key.");
  const x = b64decode(jwk.x.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (jwk.x.length % 4)) % 4));
  const spki = new Uint8Array(SPKI_PREFIX.length + x.length);
  spki.set(SPKI_PREFIX);
  spki.set(x, SPKI_PREFIX.length);
  const publicPem = spkiToPem(spki);
  // Re-import as non-extractable so the stored copy can never be read back out.
  const privateKey = await crypto.subtle.importKey("jwk", { ...jwk, ext: false, key_ops: ["deriveBits"] }, { name: "X25519" }, false, ["deriveBits"]);

  const existing = ring.all.find((r) => r.publicPem === publicPem);
  const rec = existing ?? { privateKey, publicPem };
  const next: KeyringRecord = { active: makeActive ? rec : ring.active, all: existing ? ring.all : [...ring.all, rec] };
  await idbPut(`keyring:${userId}`, next);
  ring = next;
  return { publicPem, fingerprint: await fingerprint(publicPem), isNew: !existing };
}

/** AES key for the pair (one of my private keys, a peer public key). Defaults to the active key. */
export async function deriveSharedKey(peerPem: string, mine?: IdentityRecord): Promise<CryptoKey> {
  const me = mine ?? ring?.active;
  if (!me) throw new Error("Identity not loaded");
  const peerKey = await crypto.subtle.importKey("spki", pemToSpki(peerPem), { name: "X25519" }, false, []);
  const secret = await crypto.subtle.deriveBits({ name: "X25519", public: peerKey }, me.privateKey, 256);
  const hkdfKey = await crypto.subtle.importKey("raw", secret, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: HKDF_INFO },
    hkdfKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function encryptMessage(plaintext: string, key: CryptoKey, aad: Uint8Array): Promise<{ ciphertext: string; nonce: string }> {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData: aad, tagLength: 128 }, key, enc.encode(plaintext));
  return { ciphertext: b64encode(ct), nonce: b64encode(nonce) };
}

export async function decryptMessage(ciphertextB64: string, nonceB64: string, key: CryptoKey, aad: Uint8Array): Promise<string> {
  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: b64decode(nonceB64), additionalData: aad, tagLength: 128 },
    key,
    b64decode(ciphertextB64),
  );
  return dec.decode(pt);
}
