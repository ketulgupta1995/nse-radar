import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** A styled native select: keyboard and screen-reader behaviour for free. */
export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-8 rounded-control border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
