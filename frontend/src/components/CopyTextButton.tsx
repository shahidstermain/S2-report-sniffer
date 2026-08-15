import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { toast } from "sonner";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

/**
 * Copy arbitrary text to the clipboard with desktop/browser fallbacks.
 */
export default function CopyTextButton({
  text,
  label = "Copy",
  copiedLabel = "Copied",
  className,
  iconSize = 14,
  testId,
  onCopied,
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (event) => {
    event?.preventDefault();
    event?.stopPropagation();
    try {
      await copyTextToClipboard(text);
      setCopied(true);
      onCopied?.();
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Copy failed — try Edit → Copy or check clipboard permissions");
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={cn(
        "inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-widest",
        "text-muted-foreground hover:text-foreground transition-colors",
        className,
      )}
      data-testid={testId}
      title={copied ? copiedLabel : label}
      aria-label={copied ? copiedLabel : label}
    >
      {copied ? <Check size={iconSize} /> : <Copy size={iconSize} />}
      <span>{copied ? copiedLabel : label}</span>
    </button>
  );
}
