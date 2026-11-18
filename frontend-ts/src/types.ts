export interface RawMessage {
  id: number;
  message_uuid: string;
  conversation_id: number;
  sender_id: number;
  ciphertext: string;
  nonce: string;
  key_version: number;
  created_at: string | null;
}

export type MsgStatus = "sending" | "sent" | "received" | "failed" | "locked" | "bad";

export interface Msg {
  uuid: string;
  id: number | null;
  convId: number;
  senderId: number;
  text: string | null;
  status: MsgStatus;
  ts: Date;
  raw?: RawMessage;
  error?: string;
}

export interface Conversation {
  id: number;
  createdAt: Date;
  peerId: number | null;
  msgs: Msg[];
  byUuid: Map<string, Msg>;
  lastId: number;
  draft: string;
}

export type ConnState = "offline" | "connecting" | "online" | "replaced";
export type Presence = "online" | "offline" | "unknown";

export interface Toast { id: number; text: string; kind: "info" | "error" }
export interface TrustPrompt { peerId: number; oldFp: string; newFp: string }

export interface WireMessage {
  message_id: string;
  conversation_id: number;
  target_user_id: number;
  ciphertext: string;
  nonce: string;
  key_version: number;
}

export interface ServerChoice { value: string; label: string; ports: string[] }
