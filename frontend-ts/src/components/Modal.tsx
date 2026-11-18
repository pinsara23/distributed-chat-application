import { useEffect, useRef, type ReactNode } from "react";

interface Props { open: boolean; onClose: () => void; dismissable?: boolean; children: ReactNode }

/** Thin wrapper over the native <dialog> (focus trap, Esc, backdrop for free). */
export function Modal({ open, onClose, dismissable = true, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => { if (!dismissable) e.preventDefault(); }}
      onMouseDown={(e) => { if (dismissable && e.target === ref.current) onClose(); }}
    >
      {open && children}
    </dialog>
  );
}
