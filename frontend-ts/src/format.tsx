import type { ReactNode } from "react";

const timeFmt = new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit" });
export const formatTime = (d: Date): string => timeFmt.format(d);
export const sameDay = (a: Date, b: Date): boolean => a.toDateString() === b.toDateString();

export function dayLabel(d: Date): string {
  const now = new Date();
  if (sameDay(d, now)) return "Today";
  if (sameDay(d, new Date(now.getTime() - 864e5))) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

export function listTime(d: Date): string {
  const now = new Date();
  if (sameDay(d, now)) return formatTime(d);
  if (sameDay(d, new Date(now.getTime() - 864e5))) return "Yesterday";
  return d.toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "2-digit" });
}

const PALETTE = ["#00a884", "#53bdeb", "#a05bd8", "#e0667a", "#e8a13a", "#4f8cff", "#5aa469", "#d9704a"];
export const avatarColor = (seed: number): string => PALETTE[Math.abs(seed) % PALETTE.length];

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Linkify URLs and highlight search matches. Returns React nodes (never raw HTML). */
export function renderText(text: string, query: string, isCurrent: boolean): ReactNode[] {
  const out: ReactNode[] = [];
  let key = 0;
  const highlight = (chunk: string): ReactNode[] => {
    if (!query) return [chunk];
    return chunk.split(new RegExp(`(${escapeRe(query)})`, "i")).map((part, i) =>
      i % 2 ? <mark key={`${key}-${i}`} className={isCurrent ? "current" : undefined}>{part}</mark> : part);
  };
  text.split(/(https?:\/\/[^\s<>"]+)/g).forEach((part, i) => {
    key++;
    if (i % 2) out.push(<a key={key} href={part} target="_blank" rel="noopener noreferrer">{highlight(part)}</a>);
    else out.push(...highlight(part));
  });
  return out;
}
