"use client";

import { useState } from "react";
import { SlidersHorizontal, X, Plus, Save } from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useValidationRules, usePatchValidationRules } from "@/lib/api/hooks";
import { useSession } from "@/lib/auth/session";
import type { ValidationRules } from "@/lib/api/schema";

const CATCH_ALL = [
  { value: "review", label: "Route to review" },
  { value: "reject", label: "Reject" },
  { value: "accept", label: "Accept (admin allowed)" },
];
const RISK = [
  { value: "review", label: "Route to review" },
  { value: "reject", label: "Reject" },
  { value: "accept", label: "Accept" },
];
const UNKNOWN = [
  { value: "retry", label: "Retry later" },
  { value: "review", label: "Route to review" },
  { value: "reject", label: "Reject" },
];

function ChipEditor({
  label,
  hint,
  items,
  onChange,
  placeholder,
  disabled,
}: {
  label: string;
  hint?: string;
  items: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim().toLowerCase();
    if (!v || items.includes(v)) {
      setDraft("");
      return;
    }
    onChange([...items, v]);
    setDraft("");
  }

  return (
    <Field label={label} hint={hint}>
      <div className="flex flex-wrap gap-1.5 rounded-[10px] border border-border bg-[var(--color-surface-1)] p-2">
        {items.length === 0 ? (
          <span className="px-1 py-0.5 text-xs text-muted">None configured</span>
        ) : (
          items.map((it) => (
            <span
              key={it}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-panel-strong px-2 py-0.5 font-mono text-[11px] text-ink"
            >
              {it}
              {!disabled ? (
                <button
                  type="button"
                  aria-label={`Remove ${it}`}
                  className="text-muted hover:text-danger lm-focus"
                  onClick={() => onChange(items.filter((x) => x !== it))}
                >
                  <X className="size-3" />
                </button>
              ) : null}
            </span>
          ))
        )}
      </div>
      {!disabled ? (
        <div className="mt-2 flex gap-2">
          <Input
            value={draft}
            placeholder={placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
          <Button size="sm" variant="secondary" onClick={add} type="button">
            <Plus className="size-4" /> Add
          </Button>
        </div>
      ) : null}
    </Field>
  );
}

export default function ValidationSettingsPage() {
  const { data, isLoading } = useValidationRules();
  const patch = usePatchValidationRules();
  const { can } = useSession();
  const { toast } = useToast();
  const canManage = can("settings.manage");

  // Local edit buffer keyed to the last server snapshot. When the server data
  // changes identity, we adopt it as the new baseline during render (no effect).
  const [local, setLocal] = useState<{ base: ValidationRules; edits: ValidationRules } | null>(
    null,
  );
  const draft = data && local?.base === data ? local.edits : (data ?? null);
  if (data && local?.base !== data) {
    setLocal({ base: data, edits: data });
  }
  const setDraft = (next: ValidationRules) => {
    if (data) setLocal({ base: data, edits: next });
  };

  async function save() {
    if (!draft) return;
    try {
      await patch.mutateAsync(draft);
      toast({ tone: "success", title: "Validation rules saved" });
    } catch (e) {
      toast({ tone: "error", title: "Save failed", description: (e as Error).message });
    }
  }

  if (isLoading) {
    return (
      <Panel>
        <Skeleton className="h-64 w-full" />
      </Panel>
    );
  }

  if (!draft) {
    return (
      <Panel>
        <EmptyState
          icon={SlidersHorizontal}
          kicker="Not available yet"
          title="Validation rules unavailable"
          description="The validation-rules endpoint is not responding yet. Once the backend exposes /validation-rules, the disposable list, keyword chips, and thresholds appear here."
        />
      </Panel>
    );
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(data);

  return (
    <Panel>
      <PanelHeader
        actions={
          canManage ? (
            <Button size="sm" onClick={save} disabled={!dirty || patch.isPending}>
              <Save className="size-4" /> {patch.isPending ? "Saving…" : "Save changes"}
            </Button>
          ) : null
        }
      >
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Validation Rules</h2>
      </PanelHeader>

      <PanelSection>
        <div className="flex flex-col gap-5">
          <ChipEditor
            label="Disposable domains"
            hint="Emails on these domains are rejected as invalid."
            items={draft.disposable_domains}
            onChange={(v) => setDraft({ ...draft, disposable_domains: v })}
            placeholder="mailinator.com"
            disabled={!canManage}
          />

          <ChipEditor
            label="Role-based keywords"
            hint="Local-parts containing these are treated as role-based (e.g. info, sales, support)."
            items={draft.role_based_keywords}
            onChange={(v) => setDraft({ ...draft, role_based_keywords: v })}
            placeholder="info"
            disabled={!canManage}
          />

          <Field
            label={`LLM confidence threshold — ${(draft.llm_threshold ?? 0).toFixed(2)}`}
            hint="Minimum LLM score for an email to pass the confidence stage. Higher is stricter."
          >
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              disabled={!canManage}
              value={draft.llm_threshold ?? 0}
              onChange={(e) =>
                setDraft({ ...draft, llm_threshold: Number(e.target.value) })
              }
              className="w-full accent-[var(--color-accent)] disabled:opacity-50"
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Catch-all handling" hint="Servers that accept any address.">
              <Select
                options={CATCH_ALL}
                value={String(draft.catch_all_handling)}
                disabled={!canManage}
                onChange={(e) => setDraft({ ...draft, catch_all_handling: e.target.value })}
              />
            </Field>
            <Field label="Risk handling" hint="Provider-flagged risky addresses.">
              <Select
                options={RISK}
                value={String(draft.risk_handling)}
                disabled={!canManage}
                onChange={(e) => setDraft({ ...draft, risk_handling: e.target.value })}
              />
            </Field>
            <Field label="Unknown retry policy" hint="Indeterminate provider results.">
              <Select
                options={UNKNOWN}
                value={String(draft.unknown_retry_policy)}
                disabled={!canManage}
                onChange={(e) => setDraft({ ...draft, unknown_retry_policy: e.target.value })}
              />
            </Field>
          </div>

          {!canManage ? (
            <p className="text-xs text-muted">Read-only — admin required to edit validation rules.</p>
          ) : null}
        </div>
      </PanelSection>
    </Panel>
  );
}
