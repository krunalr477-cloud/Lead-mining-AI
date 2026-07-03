"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDownToLine, Terminal } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui";
import { statusColor, type StatusVariant } from "@/lib/status";
import type { JobEvent, JobEventLevel } from "@/lib/api/schema";

/**
 * Virtualized EVENT LOG — mono log rows (timestamp · level chip · stage · msg)
 * fed by the SSE-populated events cache. Auto-scrolls to the newest row while
 * "stick to bottom" is on; the toggle flips off automatically when the user
 * scrolls up to inspect history, and back on when they return to the bottom.
 */

const LEVEL_VARIANT: Record<JobEventLevel, StatusVariant> = {
  info: "info",
  success: "accent",
  warning: "warn",
  error: "danger",
  debug: "muted",
};

const LEVEL_LABEL: Record<JobEventLevel, string> = {
  info: "INFO",
  success: "OK",
  warning: "WARN",
  error: "ERROR",
  debug: "DEBUG",
};

function timeOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toISOString().slice(11, 19);
}

const ROW_HEIGHT = 26;

export function EventLog({ events }: { events: JobEvent[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);

  const virtualizer = useVirtualizer({
    count: events.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  // Auto-scroll to the newest row whenever events grow and stick is on.
  useEffect(() => {
    if (stick && events.length > 0) {
      virtualizer.scrollToIndex(events.length - 1, { align: "end" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length, stick]);

  // Detect manual scroll-away vs. return-to-bottom to toggle stick.
  const onScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const atBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < ROW_HEIGHT * 1.5;
    setStick(atBottom);
  }, []);

  const jumpToBottom = () => {
    setStick(true);
    if (events.length > 0) {
      virtualizer.scrollToIndex(events.length - 1, { align: "end" });
    }
  };

  const items = virtualizer.getVirtualItems();

  return (
    <div className="relative flex flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <MicroLabel className="flex items-center gap-1.5">
          <Terminal className="size-3.5" /> Event Log
          <span className="text-muted/60">· {events.length}</span>
        </MicroLabel>
        <button
          type="button"
          onClick={jumpToBottom}
          className={cn(
            "inline-flex items-center gap-1 rounded-[6px] border px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors lm-focus",
            stick
              ? "border-accent/40 bg-accent/10 text-accent"
              : "border-border bg-panel text-muted hover:text-ink",
          )}
          aria-pressed={stick}
        >
          <ArrowDownToLine className="size-3" />
          {stick ? "Live" : "Follow"}
        </button>
      </div>

      <div
        ref={parentRef}
        onScroll={onScroll}
        className="lm-scroll h-[340px] overflow-y-auto rounded-[8px] border border-border bg-[var(--color-surface-1)]"
      >
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="font-mono text-xs text-muted">
              Waiting for events…
            </p>
          </div>
        ) : (
          <div
            style={{ height: virtualizer.getTotalSize(), position: "relative" }}
          >
            {items.map((vi) => {
              const ev = events[vi.index];
              const variant = LEVEL_VARIANT[ev.level] ?? "muted";
              const color = statusColor(variant);
              return (
                <div
                  key={ev.seq}
                  data-index={vi.index}
                  ref={virtualizer.measureElement}
                  className="absolute left-0 top-0 flex w-full items-baseline gap-2 px-3 py-1 font-mono text-[11px] leading-tight"
                  style={{ transform: `translateY(${vi.start}px)` }}
                >
                  <span className="shrink-0 tabular-nums text-muted/70">
                    {timeOf(ev.created_at)}
                  </span>
                  <span
                    className="w-11 shrink-0 text-right font-medium uppercase"
                    style={{ color }}
                  >
                    {LEVEL_LABEL[ev.level] ?? ev.level}
                  </span>
                  {ev.stage && (
                    <span className="shrink-0 text-info/80">[{ev.stage}]</span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-ink/90">
                    {ev.message ?? ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
