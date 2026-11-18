import { useEngine } from "../store";

export function Toasts() {
  const { toasts } = useEngine();
  return (
    <div className="toasts" aria-live="assertive">
      {toasts.map((t) => <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`} role="status">{t.text}</div>)}
    </div>
  );
}
