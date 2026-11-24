import { useState } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export default function Explain({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider delayDuration={100}>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="Explain"
            onClick={() => setOpen((o) => !o)}
            className="ml-1 cursor-pointer border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
            style={{ font: "inherit" }}
          >
            ⓘ
          </button>
        </TooltipTrigger>
        <TooltipContent>{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
