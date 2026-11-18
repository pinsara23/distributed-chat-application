import type { ReactElement } from "react";

const P = {
  clock: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zm.5 3.5v3.3l2.4 1.4-.5.9L7.5 9V5z",
  check: "M6.2 11.2 3 8l-1 1 4.2 4.2L14 5.4l-1-1z",
  lock: "M12 7V5a4 4 0 0 0-8 0v2H3v7h10V7zM6 5a2 2 0 0 1 4 0v2H6z",
  warn: "M8 1 .5 14h15zM7.2 6h1.6v4H7.2zm0 5h1.6v1.6H7.2z",
} as const;

export function MiniIcon({ name, className = "" }: { name: keyof typeof P; className?: string }): ReactElement {
  return <span className={`ico ${className}`} aria-hidden="true"><svg viewBox="0 0 16 16"><path d={P[name]} /></svg></span>;
}

const BIG = {
  newChat: "M19 3H5a2 2 0 0 0-2 2v14l4-3h12a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-3 8h-3v3h-2v-3H8V9h3V6h2v3h3z",
  logout: "M10 17l1.4-1.4-2.6-2.6H20v-2H8.8l2.6-2.6L10 7l-5 5zM4 5h8V3H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8v-2H4z",
  search: "M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 14 15.5l.3.3v.8l5 5 1.5-1.5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z",
  back: "M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20z",
  info: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2zm0-8h-2V7h2z",
  send: "M2 21l21-9L2 3v7l15 2-15 2z",
  smile: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-3.5 7a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zm7 0a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zM12 18c-2.3 0-4.3-1.4-5.2-3.5h10.4C16.3 16.6 14.3 18 12 18z",
  down: "M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z",
  up: "M7.4 15.4 12 10.8l4.6 4.6L18 14l-6-6-6 6z",
  copy: "M16 1H4a2 2 0 0 0-2 2v14h2V3h12zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11z",
  close: "M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z",
  bell: "M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2zm6-6V11a6 6 0 0 0-5-5.9V4a1 1 0 0 0-2 0v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1z",
  bellOff: "M20 18.7V19H4v-1l2-2v-5c0-.9.2-1.7.5-2.4L3.3 5.4 4.7 4l16 16-1.4 1.4zM18 11v3.2L9.4 5.6A6 6 0 0 1 11 5.1V4a1 1 0 0 1 2 0v1.1A6 6 0 0 1 18 11zm-6 11a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2z",
} as const;

export function Icon({ name }: { name: keyof typeof BIG }): ReactElement {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={BIG[name]} /></svg>;
}
