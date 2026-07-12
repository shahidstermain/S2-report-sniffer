import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface InfoHintProps {
  content: string;
  label?: string;
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
}

/**
 * Displays contextual help for parsed report data on pointer hover or keyboard focus.
 */
export default function InfoHint({
  content,
  label = "this data",
  className,
  side = "top",
}: InfoHintProps) {
  return (
    <TooltipPrimitive.Provider delayDuration={150}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>
          <button
            type="button"
            aria-label={`About ${label}`}
            className={cn(
              "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
              "text-muted-foreground/70 transition-colors hover:text-primary",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              className
            )}
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            sideOffset={4}
            className={cn(
              "z-50 max-w-xs overflow-hidden rounded-md border border-border bg-popover",
              "px-3 py-2 text-xs leading-relaxed text-popover-foreground",
              "animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out",
              "data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
            )}
          >
            {content}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
