"use client";

import { useMemo, useState } from "react";
import { Plug, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useIntegrations, useTestIntegration } from "@/lib/api/hooks";
import { useDemoMode } from "@/lib/demo";
import { useSession } from "@/lib/auth/session";
import { formatRelative } from "@/lib/format";
import type { Integration, ProviderKey, ProviderStatus } from "@/lib/api/schema";

/**
 * The provider catalog (spec §17). `providerKey` links to the /me provider map
 * for live/mock status when the /integrations endpoint is unavailable.
 */
interface ProviderDef {
  provider: string;
  label: string;
  providerKey?: ProviderKey;
  note: string;
}

const PROVIDERS: ProviderDef[] = [
  { provider: "google_oauth", label: "Google OAuth", note: "Sign-in and Sheets/Gmail authorization for the tenant." },
  { provider: "google_maps", label: "Google Maps", providerKey: "google_maps", note: "Places, geocoding, and company discovery." },
  { provider: "sheets", label: "Google Sheets", providerKey: "sheets", note: "Sales-facing system of record mirror." },
  { provider: "gmail", label: "Gmail", providerKey: "gmail", note: "Outreach sending and bounce/reply monitoring." },
  { provider: "rocketreach", label: "RocketReach", providerKey: "rocketreach", note: "Contact enrichment (emails, titles)." },
  { provider: "millionverifier", label: "MillionVerifier", providerKey: "millionverifier", note: "Provider-grade email deliverability check." },
  { provider: "groq", label: "Groq / LLM", providerKey: "groq", note: "LLM confidence scoring for email validation." },
  { provider: "serp", label: "SERP / Jobs", providerKey: "serp", note: "Job discovery and hiring-signal mining." },
  { provider: "approved_providers", label: "Approved data providers", note: "Licensed third-party datasets for gated sources." },
];

function statusLabel(s: string): string {
  if (s === "not_configured") return "Not configured";
  if (s === "mock") return "Mock";
  if (s === "live") return "Live";
  return s;
}

function statusVariant(s: string): "live" | "review" | "muted" {
  if (s === "live") return "live";
  if (s === "mock") return "review";
  return "muted";
}

interface CardData extends ProviderDef {
  status: string;
  masked_key?: string | null;
  last_verified_at?: string | null;
  serverNote?: string | null;
}

function ProviderCard({
  card,
  onTest,
  testing,
  canManage,
}: {
  card: CardData;
  onTest: (provider: string) => void;
  testing: boolean;
  canManage: boolean;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-[12px] border border-border bg-panel-strong p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{card.label}</p>
          <p className="mt-0.5 font-mono text-[11px] text-muted">{card.provider}</p>
        </div>
        <StatusChip
          status={card.status === "not_configured" ? "muted" : statusVariant(card.status)}
          label={statusLabel(card.status)}
        />
      </div>

      <p className="text-xs leading-relaxed text-muted">{card.serverNote ?? card.note}</p>

      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <MicroLabel>API key</MicroLabel>
          {/* Only ever a server-masked value like ****ab12 — never a secret. */}
          <code className="font-mono text-xs text-ink">
            {card.masked_key
              ? card.masked_key
              : card.status === "not_configured"
                ? "—"
                : "•••• hidden"}
          </code>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <MicroLabel>Last verified</MicroLabel>
          <span className="text-xs text-muted">
            {card.last_verified_at ? formatRelative(card.last_verified_at) : "Never"}
          </span>
        </div>
      </div>

      {canManage ? (
        <Button
          size="sm"
          variant="secondary"
          className="w-full"
          disabled={testing}
          onClick={() => onTest(card.provider)}
        >
          {testing ? <Loader2 className="size-4 animate-spin" /> : <Plug className="size-4" />}
          Test connection
        </Button>
      ) : null}
    </div>
  );
}

export default function IntegrationsSettingsPage() {
  const { data: integrations = [], isLoading } = useIntegrations();
  const { providers, demoMode } = useDemoMode();
  const test = useTestIntegration();
  const { can } = useSession();
  const { toast } = useToast();
  const [testingProvider, setTestingProvider] = useState<string | null>(null);

  const canManage = can("settings.manage");

  const cards = useMemo<CardData[]>(() => {
    const byProvider = new Map<string, Integration>(
      integrations.map((i) => [i.provider, i]),
    );
    return PROVIDERS.map((p) => {
      const server = byProvider.get(p.provider);
      // Prefer server integration row; else fall back to the /me provider map;
      // else mark not-configured.
      let status: string;
      if (server) status = String(server.status);
      else if (p.providerKey)
        status = (providers[p.providerKey] as ProviderStatus) ?? "not_configured";
      else status = "not_configured";
      return {
        ...p,
        status,
        masked_key: server?.masked_key ?? null,
        last_verified_at: server?.last_verified_at ?? null,
        serverNote: server?.note ?? null,
      };
    });
  }, [integrations, providers]);

  async function handleTest(provider: string) {
    setTestingProvider(provider);
    try {
      const res = await test.mutateAsync(provider);
      toast({
        tone: res.ok ? "success" : "error",
        title: res.ok ? "Connection OK" : "Connection failed",
        description: res.message ?? undefined,
      });
    } catch (e) {
      toast({ tone: "error", title: "Test failed", description: (e as Error).message });
    } finally {
      setTestingProvider(null);
    }
  }

  return (
    <Panel>
      <PanelHeader
        actions={demoMode ? <StatusChip status="review" label="Demo — mock adapters" /> : null}
      >
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Integrations & API Keys</h2>
      </PanelHeader>

      <PanelSection>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-40 w-full" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {cards.map((card) => (
              <ProviderCard
                key={card.provider}
                card={card}
                onTest={handleTest}
                testing={testingProvider === card.provider}
                canManage={canManage}
              />
            ))}
          </div>
        )}

        <p className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted">
          <CheckCircle2 className="size-3.5 text-accent" />
          Secrets are stored server-side only. The UI receives a masked suffix (e.g. ****ab12) and never a full key.
          {!canManage ? (
            <span className="flex items-center gap-1 text-muted">
              <XCircle className="size-3.5" /> Admin required to test connections.
            </span>
          ) : null}
        </p>
      </PanelSection>
    </Panel>
  );
}
