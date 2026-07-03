"use client";

import type { ReactNode } from "react";
import { Dialog } from "radix-ui";
import { cn } from "@/lib/cn";
import { Button } from "./Button";
import { MicroLabel } from "./MicroLabel";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  kicker?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive. */
  destructive?: boolean;
  onConfirm: () => void;
  loading?: boolean;
}

/** Centered confirmation modal for destructive/irreversible actions. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  kicker,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  loading = false,
}: ConfirmDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
            "rounded-[14px] border border-border bg-[var(--color-surface-2)] p-5",
            "shadow-[0_30px_80px_-25px_rgba(0,0,0,0.95)]",
          )}
        >
          <div className="flex flex-col gap-1.5">
            {kicker && <MicroLabel className={destructive ? "text-danger" : "text-accent/80"}>{kicker}</MicroLabel>}
            <Dialog.Title className="text-base font-semibold text-ink">{title}</Dialog.Title>
            {description && (
              <Dialog.Description className="text-sm leading-relaxed text-muted">
                {description}
              </Dialog.Description>
            )}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm">
                {cancelLabel}
              </Button>
            </Dialog.Close>
            <Button
              variant={destructive ? "danger" : "primary"}
              size="sm"
              loading={loading}
              onClick={onConfirm}
            >
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
