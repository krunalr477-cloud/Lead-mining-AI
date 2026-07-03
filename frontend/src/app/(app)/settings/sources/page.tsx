"use client";

import { useState } from "react";
import { ShieldCheck, Gavel, Check } from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { ComplianceBadge, type CompliancePosture } from "@/components/ui/ComplianceBadge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { useSources, usePatchSource, useSignoffSource } from "@/lib/api/hooks";
import { useSession } from "@/lib/auth/session";
import { formatRelative } from "@/lib/format";
import type { DataSource } from "@/lib/api/schema";

/** Map backend posture (green/amber/red) to the ComplianceBadge posture. */
function toPosture(p: string): CompliancePosture {
  const s = p.toLowerCase();
  if (s === "green" || s === "official") return "official";
  if (s === "red" || s === "disabled") return "disabled";
  return "gated";
}

/** Amber/red sources require sign-off before they can be enabled (mirrors backend gating). */
function requiresSignoff(src: DataSource): boolean {
  if (src.requires_signoff != null) return src.requires_signoff;
  return toPosture(String(src.posture)) !== "official";
}

function SourceRow({
  src,
  canManage,
  onToggle,
  onSignoff,
  toggling,
}: {
  src: DataSource;
  canManage: boolean;
  onToggle: (src: DataSource) => void;
  onSignoff: (src: DataSource) => void;
  toggling: boolean;
}) {
  const posture = toPosture(String(src.posture));
  const needsSignoff = requiresSignoff(src);
  const signedOff = Boolean(src.signed_off);
  // Gate: amber/red require sign-off before enable.
  const enableBlocked = needsSignoff && !signedOff;

  const quota =
    src.quota_used != null && src.quota_limit != null
      ? `${src.quota_used.toLocaleString()} / ${src.quota_limit.toLocaleString()}`
      : src.quota_used != null
        ? src.quota_used.toLocaleString()
        : "—";

  return (
    <div className="flex flex-col gap-3 py-4 lg:flex-row lg:items-start lg:justify-between lg:gap-6">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink">
            {src.display_name ?? src.name}
          </span>
          <ComplianceBadge posture={posture} note={src.legal_note ?? undefined} />
          {src.enabled ? (
            <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent">
              Enabled
            </span>
          ) : null}
        </div>
        <p className="mt-1 font-mono text-[11px] text-muted">
          {src.access_method ?? src.source_type ?? "—"}
          {src.rate_limit ? ` · ${src.rate_limit}` : ""}
        </p>
        {src.legal_note ? (
          <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-muted">{src.legal_note}</p>
        ) : null}

        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-muted">
          <span>
            <MicroLabel>Last success</MicroLabel>{" "}
            {src.last_success_at ? formatRelative(src.last_success_at) : "—"}
          </span>
          <span>
            <MicroLabel>Last failure</MicroLabel>{" "}
            {src.last_failure_at ? formatRelative(src.last_failure_at) : "—"}
          </span>
          <span>
            <MicroLabel>Quota</MicroLabel> {quota}
          </span>
          {needsSignoff ? (
            <span>
              <MicroLabel>Sign-off</MicroLabel>{" "}
              {signedOff ? (
                <span className="text-accent">
                  {src.signed_off_by ? `by ${src.signed_off_by}` : "granted"}
                  {src.signed_off_at ? ` · ${formatRelative(src.signed_off_at)}` : ""}
                </span>
              ) : (
                <span className="text-warn">required</span>
              )}
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {needsSignoff && !signedOff && canManage ? (
          <Button size="sm" variant="secondary" onClick={() => onSignoff(src)}>
            <Gavel className="size-4" /> Admin sign-off
          </Button>
        ) : null}
        <Button
          size="sm"
          variant={src.enabled ? "danger" : "primary"}
          disabled={!canManage || toggling || (!src.enabled && enableBlocked)}
          onClick={() => onToggle(src)}
          title={
            !src.enabled && enableBlocked
              ? "Sign-off required before this source can be enabled"
              : undefined
          }
        >
          {src.enabled ? "Disable" : "Enable"}
        </Button>
      </div>
    </div>
  );
}

export default function SourcesSettingsPage() {
  const { data: sources = [], isLoading } = useSources();
  const patch = usePatchSource();
  const signoff = useSignoffSource();
  const { can } = useSession();
  const { toast } = useToast();
  const canManage = can("settings.manage");

  const [confirmSignoff, setConfirmSignoff] = useState<DataSource | null>(null);

  async function toggle(src: DataSource) {
    try {
      await patch.mutateAsync({ name: src.name, patch: { enabled: !src.enabled } });
      toast({
        tone: "success",
        title: `${src.display_name ?? src.name} ${src.enabled ? "disabled" : "enabled"}`,
      });
    } catch (e) {
      toast({ tone: "error", title: "Update failed", description: (e as Error).message });
    }
  }

  async function doSignoff() {
    if (!confirmSignoff) return;
    const src = confirmSignoff;
    setConfirmSignoff(null);
    try {
      await signoff.mutateAsync(src.name);
      toast({
        tone: "success",
        title: "Sign-off recorded",
        description: `${src.display_name ?? src.name} may now be enabled.`,
      });
    } catch (e) {
      toast({ tone: "error", title: "Sign-off failed", description: (e as Error).message });
    }
  }

  return (
    <Panel flush>
      <PanelHeader
        className="px-4 pt-4 sm:px-5"
        actions={
          <div className="hidden items-center gap-2 sm:flex">
            <ComplianceBadge posture="official" />
            <ComplianceBadge posture="gated" />
            <ComplianceBadge posture="disabled" />
          </div>
        }
      >
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Data Source Compliance</h2>
      </PanelHeader>

      <PanelSection className="px-4 sm:px-5">
        {isLoading ? (
          <div className="flex flex-col gap-3 py-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : sources.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            kicker="Not available yet"
            title="No data sources configured"
            description="Once the /sources endpoint responds, each source shows its compliance posture, legal note, enable toggle, and admin sign-off gate. Amber/red sources stay disabled until legal review."
          />
        ) : (
          <div className="divide-y divide-border">
            {sources.map((src) => (
              <SourceRow
                key={src.name}
                src={src}
                canManage={canManage}
                toggling={patch.isPending}
                onToggle={toggle}
                onSignoff={setConfirmSignoff}
              />
            ))}
          </div>
        )}

        <p className="flex items-center gap-2 pt-4 text-xs text-muted">
          <Check className="size-3.5 text-accent" />
          Commercial scraping from amber/red sources stays disabled until an admin signs off after legal review.
          No authenticated or private scraping is ever permitted.
        </p>
      </PanelSection>

      <ConfirmDialog
        open={!!confirmSignoff}
        onOpenChange={(o) => !o && setConfirmSignoff(null)}
        kicker="Admin / legal sign-off"
        title={`Sign off ${confirmSignoff?.display_name ?? confirmSignoff?.name ?? "source"}?`}
        description={
          <>
            {confirmSignoff?.legal_note ? (
              <span className="mb-2 block">{confirmSignoff.legal_note}</span>
            ) : null}
            You confirm this compliance-gated source has passed legal review for this tenant. This
            action is recorded in the audit log with your identity and timestamp.
          </>
        }
        confirmLabel="Record sign-off"
        onConfirm={doSignoff}
        loading={signoff.isPending}
      />
    </Panel>
  );
}
