"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/cn";

interface CopyButtonProps {
  value: string;
  className?: string;
  /** Optional label rendered next to the icon. */
  label?: string;
}

/** Copy-to-clipboard button with a transient check confirmation. */
export function CopyButton({ value, className, label }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — no-op */
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? "Copied" : "Copy"}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[6px] px-1.5 py-1 text-muted transition-colors hover:bg-panel hover:text-ink lm-focus",
        className,
      )}
    >
      {copied ? (
        <Check className="size-3.5 text-accent" />
      ) : (
        <Copy className="size-3.5" />
      )}
      {label && <span className="font-mono text-[11px] uppercase tracking-wider">{label}</span>}
    </button>
  );
}
