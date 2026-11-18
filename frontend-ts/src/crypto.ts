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

// ---- identity storage: IndexedDB, private key is NON-extractable ----
interface IdentityRecord { privateKey: CryptoKey; publicPem: string }

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("dchat", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("identity");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(key: string): Promise<IdentityRecord | undefined> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const r = db.transaction("identity").objectStore("identity").get(key);
    r.onsuccess = () => resolve(r.result as IdentityRecord | undefined);
    r.onerror = () => reject(r.error);
  });
}

async function idbPut(key: string, value: IdentityRecord): Promise<void> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("identity", "readwrite");
    tx.objectStore("identity").put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

let identity: IdentityRecord | null = null;

export async function loadIdentity(userId: number): Promise<{ publicPem: string; fingerprint: string }> {
  let rec = await idbGet(`user:${userId}`);
  if (!rec) {
    const pair = (await crypto.subtle.generateKey({ name: "X25519" }, false, ["deriveBits"])) as CryptoKeyPair;
    const spki = new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey));
    rec = { privateKey: pair.privateKey, publicPem: spkiToPem(spki) };
    await idbPut(`user:${userId}`, rec);
  }
  identity = rec;
  return { publicPem: rec.publicPem, fingerprint: await fingerprint(rec.publicPem) };
}

export async function deriveSharedKey(peerPem: string): Promise<CryptoKey> {
  if (!identity) throw new Error("Identity not loaded");
  const peerKey = await crypto.subtle.importKey("spki", pemToSpki(peerPem), { name: "X25519" }, false, []);
  const secret = await crypto.subtle.deriveBits({ name: "X25519", public: peerKey }, identity.privateKey, 256);
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
