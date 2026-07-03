import { cn } from "@/lib/cn";

interface SkeletonProps {
  className?: string;
}

/** Shimmering placeholder block. Compose with width/height utilities. */
export function Skeleton({ className }: SkeletonProps) {
  return <div className={cn("lm-skeleton rounded-[6px]", className)} aria-hidden />;
}

/** Common preset: a few text lines. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-3", i === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}
