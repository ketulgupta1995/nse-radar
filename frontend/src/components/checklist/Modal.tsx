import type { ReactNode } from "react";
import { useIsPhone } from "@/lib/useIsPhone";
import { cn } from "@/lib/utils";

/** A dialog on a laptop; a full-screen sheet on a phone (SPEC §17.9). */
export default function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const phone = useIsPhone();
  return (
    <div
      className={cn("modal-backdrop", phone && "bg-background p-0")}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-sheet={phone ? "full" : undefined}
    >
      <div
        className={cn(
          "modal card",
          phone &&
            "min-h-full w-full rounded-none border-0 pb-[calc(1rem+env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-[calc(1rem+env(safe-area-inset-top))]",
        )}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button type="button" aria-label="Close" onClick={onClose} className={phone ? "min-h-11 min-w-11" : undefined}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}
