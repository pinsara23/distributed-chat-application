import { avatarColor } from "../format";

export function Avatar({ seed, label, big }: { seed: number; label: string; big?: boolean }) {
  return (
    <span className={`avatar${big ? " big" : ""}`} style={{ background: avatarColor(seed) }} aria-hidden="true">
      {(label.trim().charAt(0) || "?").toUpperCase()}
    </span>
  );
}
