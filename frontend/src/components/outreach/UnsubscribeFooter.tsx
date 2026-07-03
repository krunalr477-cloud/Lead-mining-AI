import { cn } from "@/lib/cn";

/**
 * Read-only compliance footer appended to every outreach email (§13). Renders
 * the mandatory unsubscribe/opt-out line; the sender address and link are
 * injected server-side at send time — this is a preview of the fixed footer.
 */
export function UnsubscribeFooter({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "mt-1 border-t border-border pt-3 text-[11px] leading-relaxed text-muted/70",
        className,
      )}
    >
      <p>
        You are receiving this because your business was identified as a potential
        fit. If you would rather not hear from us,{" "}
        <span className="underline">unsubscribe</span> or reply STOP.
      </p>
      <p className="mt-1 font-mono uppercase tracking-wider text-muted/50">
        Sent via LeadMine AI · Opt-out honored automatically
      </p>
    </div>
  );
}
