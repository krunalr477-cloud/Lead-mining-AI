"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Plug,
  CheckCircle2,
  XCircle,
  Loader2,
  KeyRound,
  Info,
  Trash2,
} from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import {
  useIntegrations,
  useTestIntegration,
  useSaveIntegration,
  useDeleteIntegration,
} from "@/lib/api/hooks";
import { useDemoMode } from "@/lib/demo";
import { useSession } from "@/lib/auth/session";
import { formatRelative } from "@/lib/format";
import type {
  Integration,
  IntegrationSecretInput,
  ProviderKey,
  ProviderStatus,
} from "@/lib/api/schema";

/**
 * The provider catalog (spec §17). `providerKey` links to the /me provider map
 * for live/mock status when the /integrations endpoint is unavailable. `kind`
 * selects the key-entry shape rendered on the card.
 */
type CredKind = "api_key" | "oauth" | "base_url_key";

interface ProviderDef {
  provider: string;
  label: string;
  providerKey?: ProviderKey;
  note: string;
  kind: CredKind;
}

const PROVIDERS: ProviderDef[] = [
  { provider: "google_oauth", label: "Google OAuth", kind: "oauth", note: "Sign-in and Sheets/Gmail authorization for the tenant." },
  { provider: "google_maps", label: "Google Maps", providerKey: "google_maps", kind: "api_key", note: "Places, geocoding, and company discovery." },
  { provider: "sheets", label: "Google Sheets", providerKey: "sheets", kind: "api_key", note: "Sales-facing system of record mirror." },
  { provider: "gmail", label: "Gmail", providerKey: "gmail", kind: "api_key", note: "Outreach sending and bounce/reply monitoring." },
  { provider: "rocketreach", label: "RocketReach", providerKey: "rocketreach", kind: "api_key", note: "Contact enrichment (emails, titles)." },
  { provider: "millionverifier", label: "MillionVerifier", providerKey: "millionverifier", kind: "api_key", note: "Provider-grade email deliverability check." },
  { provider: "groq", label: "Groq / LLM", providerKey: "groq", kind: "api_key", note: "LLM confidence scoring for email validation." },
  { provider: "serp", label: "SERP / Jobs", providerKey: "serp", kind: "api_key", note: "Job discovery and hiring-signal mining." },
  { provider: "approved_providers", label: "Approved data providers", kind: "base_url_key", note: "Licensed third-party datasets for gated sources." },
];

function statusLabel(s: string): string {
  if (s === "not_configured") return "Not configured";
  if (s === "configured") return "Configured";
  if (s === "mock") return "Mock";
  if (s === "live") return "Live";
  return s;
}

function statusVariant(s: string): "live" | "review" | "muted" {
  if (s === "live" || s === "configured") return "live";
  if (s === "mock") return "review";
  return "muted";
}

interface CardData extends ProviderDef {
  status: string;
  masked_key?: string | null;
  last_verified_at?: string | null;
  serverNote?: string | null;
}

/** True once the provider has a stored secret (server-configured or live). */
function isConfigured(card: CardData): boolean {
  return (
    card.status === "configured" ||
    card.status === "live" ||
    Boolean(card.masked_key)
  );
}

function ProviderCard({
  card,
  onTest,
  onSave,
  onRemove,
  testing,
  saving,
  removing,
  canManage,
}: {
  card: CardData;
  onTest: (provider: string) => void;
  onSave: (provider: string, body: IntegrationSecretInput) => Promise<void>;
  onRemove: (provider: string) => void;
  testing: boolean;
  saving: boolean;
  removing: boolean;
  canManage: boolean;
}) {
  const [open, setOpen] = useState(false);
  // Local, never-persisted secret inputs. Cleared after a successful save.
  const [apiKey, setApiKey] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  const configured = isConfigured(card);

  function reset() {
    setApiKey("");
    setClientId("");
    setClientSecret("");
    setBaseUrl("");
  }

  function buildBody(): IntegrationSecretInput | null {
    if (card.kind === "oauth") {
      if (!clientId.trim() || !clientSecret.trim()) return null;
      return { client_id: clientId.trim(), client_secret: clientSecret.trim() };
    }
    if (card.kind === "base_url_key") {
      if (!apiKey.trim()) return null;
      return {
        api_key: apiKey.trim(),
        base_url: baseUrl.trim() || undefined,
      };
    }
    if (!apiKey.trim()) return null;
    return { api_key: apiKey.trim() };
  }

  async function handleSave() {
    const body = buildBody();
    if (!body) return;
    await onSave(card.provider, body);
    reset();
    setOpen(false);
  }

  const saveDisabled = saving || !buildBody();

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
              : configured
                ? "•••• hidden"
                : "—"}
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
        <>
          {open ? (
            <div className="flex flex-col gap-2 rounded-[8px] border border-border bg-[var(--color-surface-1)] p-3">
              {card.kind === "oauth" ? (
                <>
                  <div className="flex flex-col gap-1">
                    <MicroLabel>Client ID</MicroLabel>
                    <Input
                      type="text"
                      autoComplete="off"
                      placeholder="1234-abc.apps.googleusercontent.com"
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <MicroLabel>Client Secret</MicroLabel>
                    <Input
                      type="password"
                      autoComplete="off"
                      placeholder="GOCSPX-…"
                      value={clientSecret}
                      onChange={(e) => setClientSecret(e.target.value)}
                    />
                  </div>
                </>
              ) : card.kind === "base_url_key" ? (
                <>
                  <div className="flex flex-col gap-1">
                    <MicroLabel>Base URL</MicroLabel>
                    <Input
                      type="text"
                      autoComplete="off"
                      placeholder="https://api.provider.com/v1"
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <MicroLabel>API key</MicroLabel>
                    <Input
                      type="password"
                      autoComplete="off"
                      placeholder="Paste key"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                    />
                  </div>
                </>
              ) : (
                <div className="flex flex-col gap-1">
                  <MicroLabel>API key</MicroLabel>
                  <Input
                    type="password"
                    autoComplete="off"
                    placeholder="Paste key"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </div>
              )}
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  className="flex-1"
                  disabled={saveDisabled}
                  onClick={handleSave}
                >
                  {saving ? <Loader2 className="size-4 animate-spin" /> : null}
                  Save
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={saving}
                  onClick={() => {
                    reset();
                    setOpen(false);
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              className="w-full"
              onClick={() => setOpen(true)}
            >
              <KeyRound className="size-4" />
              {configured ? "Update key" : "Add key"}
            </Button>
          )}

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              className="flex-1"
              disabled={testing}
              onClick={() => onTest(card.provider)}
            >
              {testing ? <Loader2 className="size-4 animate-spin" /> : <Plug className="size-4" />}
              Test connection
            </Button>
            {configured ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={removing}
                onClick={() => onRemove(card.provider)}
                aria-label="Remove stored key"
                title="Remove stored key"
              >
                {removing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Trash2 className="size-4" />
                )}
              </Button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function IntegrationsSettingsPage() {
  const { data: integrations = [], isLoading } = useIntegrations();
  const { providers, demoMode } = useDemoMode();
  const test = useTestIntegration();
  const save = useSaveIntegration();
  const remove = useDeleteIntegration();
  const { can } = useSession();
  const { toast } = useToast();
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [savingProvider, setSavingProvider] = useState<string | null>(null);
  const [removingProvider, setRemovingProvider] = useState<string | null>(null);

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
      const latency =
        res.latency_ms != null ? ` (${Math.round(res.latency_ms)} ms)` : "";
      toast({
        tone: res.ok ? "success" : "error",
        title: res.ok ? `Connection OK${latency}` : "Connection failed",
        description: res.message ?? undefined,
      });
    } catch (e) {
      toast({ tone: "error", title: "Test failed", description: (e as Error).message });
    } finally {
      setTestingProvider(null);
    }
  }

  async function handleSave(provider: string, body: IntegrationSecretInput) {
    setSavingProvider(provider);
    try {
      await save.mutateAsync({ provider, body });
      toast({
        tone: "success",
        title: "Key saved",
        description: "Stored server-side. Run Test connection to verify.",
      });
    } catch (e) {
      toast({ tone: "error", title: "Save failed", description: (e as Error).message });
      throw e; // keep the reveal open so the user can retry
    } finally {
      setSavingProvider(null);
    }
  }

  async function handleRemove(provider: string) {
    setRemovingProvider(provider);
    try {
      await remove.mutateAsync(provider);
      toast({ tone: "success", title: "Key removed", description: `${provider} reset to not configured.` });
    } catch (e) {
      toast({ tone: "error", title: "Remove failed", description: (e as Error).message });
    } finally {
      setRemovingProvider(null);
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
        {demoMode ? (
          <div className="mb-4 flex flex-col gap-1 rounded-[10px] border border-[color-mix(in_srgb,var(--color-accent)_28%,transparent)] bg-[color-mix(in_srgb,var(--color-accent)_8%,transparent)] p-3 text-xs leading-relaxed text-ink sm:flex-row sm:items-start sm:gap-2">
            <Info className="mt-0.5 size-4 shrink-0 text-accent" />
            <p>
              <span className="font-semibold">Demo mode is ON</span> — jobs run on
              mock data. Save your keys here, then set{" "}
              <code className="font-mono text-[11px]">DEMO_MODE=false</code> in{" "}
              <code className="font-mono text-[11px]">.env</code> and restart to run
              live.{" "}
              <Link href="/help" className="text-accent underline-offset-2 hover:underline">
                See Help
              </Link>
              .
            </p>
          </div>
        ) : null}

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
                onSave={handleSave}
                onRemove={handleRemove}
                testing={testingProvider === card.provider}
                saving={savingProvider === card.provider}
                removing={removingProvider === card.provider}
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
              <XCircle className="size-3.5" /> Admin required to manage connections.
            </span>
          ) : null}
        </p>
      </PanelSection>
    </Panel>
  );
}
