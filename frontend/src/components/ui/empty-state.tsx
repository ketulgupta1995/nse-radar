import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function EmptyState({ title, children, className }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center gap-1 rounded-card border border-dashed border-border px-4 py-8 text-center", className)}>
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}
