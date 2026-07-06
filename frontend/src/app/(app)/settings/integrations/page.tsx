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
  Eye,
  EyeOff,
  Copy,
  Check,
  Pencil,
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
  useEnvKeys,
  useRevealEnvKey,
  useUpdateEnvKeys,
} from "@/lib/api/hooks";
import { useDemoMode } from "@/lib/demo";
import { useSession } from "@/lib/auth/session";
import { formatRelative } from "@/lib/format";
import type {
  EnvKey,
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
  /**
   * OAuth providers configured through the `.env` section above rather than
   * per-tenant stored secrets. The card shows a jump-to-env link instead of
   * Client ID/Secret inputs.
   */
  envManaged?: boolean;
}

const PROVIDERS: ProviderDef[] = [
  { provider: "google_oauth", label: "Google OAuth", kind: "oauth", note: "Sign-in and Sheets/Gmail authorization for the tenant." },
  { provider: "microsoft", label: "Microsoft OAuth", kind: "oauth", envManaged: true, note: "Microsoft / Entra ID sign-in. Configure via the Microsoft .env keys above." },
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

      {card.envManaged ? (
        // OAuth configured through the .env section above — no stored secret to
        // paste here, just a jump to where the keys live plus Help.
        <div className="flex items-center gap-2">
          <Button
            asChild
            size="sm"
            variant="secondary"
            className="flex-1"
          >
            <a href="#env-keys">
              <KeyRound className="size-4" />
              Manage .env keys
            </a>
          </Button>
          <Button asChild size="sm" variant="ghost">
            <Link href="/help">
              <Info className="size-4" />
              Help
            </Link>
          </Button>
        </div>
      ) : canManage ? (
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

/* ── Environment keys (.env) ─────────────────────────────────────────── */

/** Preferred display order for the env-key groups. Unknown groups sort last. */
const ENV_GROUP_ORDER = ["Google", "Microsoft", "Providers", "Runtime"];

function groupOrder(group: string): number {
  const i = ENV_GROUP_ORDER.indexOf(group);
  return i === -1 ? ENV_GROUP_ORDER.length : i;
}

function EnvKeyRow({
  row,
  onReveal,
  onSave,
  canManage,
}: {
  row: EnvKey;
  onReveal: (key: string) => Promise<string>;
  onSave: (key: string, value: string) => Promise<void>;
  canManage: boolean;
}) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  // The value shown when not revealed: masked hint for secrets, plaintext else.
  const display = row.is_secret
    ? row.masked || (row.is_set ? "•••• hidden" : "—")
    : row.value || (row.is_set ? "(set)" : "—");

  async function handleReveal() {
    if (revealed !== null) {
      setRevealed(null);
      return;
    }
    setRevealing(true);
    try {
      const value = await onReveal(row.key);
      setRevealed(value);
    } finally {
      setRevealing(false);
    }
  }

  async function handleCopy() {
    if (revealed == null) return;
    try {
      await navigator.clipboard.writeText(revealed);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — no-op */
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(row.key, draft);
      setEditing(false);
      setDraft("");
      setRevealed(null);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 border-b border-border py-3 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">{row.label}</p>
          <p className="font-mono text-[11px] text-muted">{row.key}</p>
        </div>
        <div className="flex items-center gap-2">
          {row.source ? (
            <span className="font-mono text-[10px] uppercase tracking-wide text-muted">
              {row.source}
            </span>
          ) : null}
          <StatusChip
            status={row.is_set ? "live" : "muted"}
            label={row.is_set ? "Set" : "Unset"}
          />
        </div>
      </div>

      {editing ? (
        <div className="flex flex-col gap-2 rounded-[8px] border border-border bg-[var(--color-surface-1)] p-3 sm:flex-row sm:items-center">
          <Input
            type={row.is_secret ? "password" : "text"}
            autoComplete="off"
            className="flex-1"
            placeholder={`New value for ${row.key}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={saving || !draft.trim()}
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
                setEditing(false);
                setDraft("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-[6px] bg-[var(--color-surface-1)] px-2 py-1 font-mono text-xs text-ink">
            {revealed !== null ? revealed : display}
          </code>
          {row.is_secret && row.is_set ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={revealing}
              onClick={handleReveal}
              aria-label={revealed !== null ? "Hide value" : "Reveal value"}
              title={revealed !== null ? "Hide value" : "Reveal value"}
            >
              {revealing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : revealed !== null ? (
                <EyeOff className="size-4" />
              ) : (
                <Eye className="size-4" />
              )}
            </Button>
          ) : null}
          {revealed !== null ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={handleCopy}
              aria-label="Copy value"
              title="Copy value"
            >
              {copied ? (
                <Check className="size-4 text-accent" />
              ) : (
                <Copy className="size-4" />
              )}
            </Button>
          ) : null}
          {canManage ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setDraft("");
                setEditing(true);
              }}
            >
              <Pencil className="size-4" />
              Edit
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}

function EnvKeysSection({ canManage }: { canManage: boolean }) {
  const { data: envKeys = [], isLoading } = useEnvKeys();
  const reveal = useRevealEnvKey();
  const update = useUpdateEnvKeys();
  const { toast } = useToast();

  const grouped = useMemo(() => {
    const map = new Map<string, EnvKey[]>();
    for (const row of envKeys) {
      const g = row.group || "Other";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(row);
    }
    return Array.from(map.entries()).sort(
      (a, b) => groupOrder(a[0]) - groupOrder(b[0]),
    );
  }, [envKeys]);

  async function handleReveal(key: string): Promise<string> {
    try {
      const res = await reveal.mutateAsync(key);
      return res.value;
    } catch (e) {
      toast({ tone: "error", title: "Reveal failed", description: (e as Error).message });
      throw e;
    }
  }

  async function handleSave(key: string, value: string): Promise<void> {
    try {
      await update.mutateAsync({ [key]: value });
      toast({
        tone: "success",
        title: "Saved to .env",
        description: `${key} updated. Restart workers for running jobs to pick it up.`,
      });
    } catch (e) {
      toast({ tone: "error", title: "Save failed", description: (e as Error).message });
      throw e;
    }
  }

  // Nothing to show and not loading → the backend route isn't live yet; hide the
  // whole section rather than render an empty shell.
  if (!isLoading && envKeys.length === 0) return null;

  return (
    <div
      id="env-keys"
      className="mb-6 scroll-mt-24 rounded-[12px] border border-border bg-panel-strong p-4"
    >
      <div className="mb-3 flex flex-col gap-1">
        <MicroLabel className="text-accent/70">Environment keys (.env)</MicroLabel>
        <p className="text-xs leading-relaxed text-muted">
          Read from and written to the repo{" "}
          <code className="font-mono text-[11px]">.env</code> file — the primary
          path for Google, Microsoft, and provider credentials. Changes to keys
          used by running mining jobs apply after a worker restart.
        </p>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {grouped.map(([group, rows]) => (
            <div key={group}>
              <MicroLabel>{group}</MicroLabel>
              <div className="mt-1">
                {rows.map((row) => (
                  <EnvKeyRow
                    key={row.key}
                    row={row}
                    onReveal={handleReveal}
                    onSave={handleSave}
                    canManage={canManage}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {!canManage ? (
        <p className="mt-3 flex items-center gap-1 text-xs text-muted">
          <XCircle className="size-3.5" /> Admin required to reveal or edit .env keys.
        </p>
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

        {/* Primary path: keys live in .env. Per-tenant cards below still work. */}
        <EnvKeysSection canManage={canManage} />

        <div className="mb-2 flex flex-col gap-0.5">
          <MicroLabel>Per-tenant connections</MicroLabel>
          <p className="text-xs leading-relaxed text-muted">
            Optional per-tenant overrides stored server-side (encrypted). The
            <code className="mx-1 font-mono text-[11px]">.env</code>
            keys above are the primary path.
          </p>
        </div>

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
