import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const badgeVariants = cva("inline-flex items-center rounded-full border px-2 text-xs font-medium", {
  variants: {
    variant: {
      neutral: "border-border bg-muted text-muted-foreground",
      info: "border-transparent bg-info/15 text-info",
      success: "border-transparent bg-success/15 text-success",
      danger: "border-transparent bg-danger/15 text-danger",
      warning: "border-transparent bg-warning/15 text-warning",
    },
  },
  defaultVariants: { variant: "neutral" },
});

export function Badge({ className, variant, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

type Variant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;
const STATUS: Record<string, Variant> = {
  running: "info",
  done: "success",
  failed: "danger",
  cancelled: "warning",
  interrupted: "warning",
};

export function statusVariant(status: string): Variant {
  return STATUS[status] ?? "neutral";
}

/** Job or run status as a coloured chip: running = info, done = success, failed = danger, cancelled / interrupted = warning. */
export function StatusChip({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant={statusVariant(status)} className={className}>
      {status}
    </Badge>
  );
}
