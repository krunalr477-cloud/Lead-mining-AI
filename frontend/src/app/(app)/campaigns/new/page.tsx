"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Send,
  Rocket,
  FlaskConical,
  Clock,
  Eye,
  MousePointerClick,
  MessageSquare,
  AlertOctagon,
} from "lucide-react";
import type { ReactNode } from "react";
import {
  Panel,
  PanelHeader,
  Field,
  Input,
  Select,
  Button,
  MicroLabel,
  StatusChip,
  ConfirmDialog,
  useToast,
} from "@/components/ui";
import {
  useContacts,
  useCompanyMap,
  useJobs,
  useCreateCampaign,
  useTestSend,
  useLaunch,
} from "@/lib/api/hooks";
import { useDemoMode } from "@/lib/demo";
import type {
  Contact,
  EligibilitySummary as EligibilityData,
} from "@/lib/api/schema";
import { formatDuration, formatNumber } from "@/lib/format";
import { VariableMenu } from "@/components/outreach/VariableMenu";
import { ContactPreview } from "@/components/outreach/ContactPreview";
import { EligibilitySummary } from "@/components/outreach/EligibilitySummary";
import { UnsubscribeFooter } from "@/components/outreach/UnsubscribeFooter";
import { Switch } from "@/components/outreach/Switch";
import { NumberStepper } from "@/components/outreach/NumberStepper";
import {
  extractTokens,
  type PreviewContext,
} from "@/components/outreach/template";

/**
 * §13 / §20 Campaign Builder — two-pane. LEFT: subject/body editor with a
 * variable-insertion menu, AI-opener toggle, from-account, unsubscribe footer.
 * RIGHT: live contact preview + recipient eligibility summary (VERIFIED-only)
 * + rate-limit / send-window / tracking controls. Footer sends a test email and
 * launches (or, in demo mode, "Simulate send").
 */

const FROM_ACCOUNTS = [
  { value: "outreach@leadmine.ai", label: "outreach@leadmine.ai" },
  { value: "sales@leadmine.ai", label: "sales@leadmine.ai" },
  { value: "hello@leadmine.ai", label: "hello@leadmine.ai" },
];

const TIMEZONES = [
  { value: "Asia/Kolkata", label: "Asia/Kolkata (IST)" },
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "America/New_York (ET)" },
  { value: "Europe/London", label: "Europe/London (GMT)" },
];

const DEFAULT_BODY =
  "Hi {{FirstName}},\n\nI came across {{Company}} in {{City}} and wanted to reach out about {{Services}}. As {{Designation}}, you're likely the right person to talk to.\n\nWould you be open to a quick chat?\n\nBest,\nThe LeadMine team";

export default function CampaignBuilderPage() {
  const router = useRouter();
  const toast = useToast();
  const { demoMode } = useDemoMode();

  // ── Left editor state ──────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [jobId, setJobId] = useState("");
  const [fromAccount, setFromAccount] = useState(FROM_ACCOUNTS[0].value);
  const [subject, setSubject] = useState("Quick question about {{Company}}");
  const [body, setBody] = useState(DEFAULT_BODY);
  const [aiOpener, setAiOpener] = useState(false);
  const [bodyBlurred, setBodyBlurred] = useState(false);

  // ── Right controls state ───────────────────────────────────────────────
  const [perHour, setPerHour] = useState(60);
  const [perDay, setPerDay] = useState(400);
  const [windowStart, setWindowStart] = useState("09:00");
  const [windowEnd, setWindowEnd] = useState("17:00");
  const [timezone, setTimezone] = useState(TIMEZONES[0].value);
  const [tracking, setTracking] = useState({
    opens: true,
    clicks: true,
    replies: true,
    bounces: true,
  });

  const [previewIndex, setPreviewIndex] = useState(0);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const bodyRef = useRef<HTMLTextAreaElement>(null);

  // ── Data ───────────────────────────────────────────────────────────────
  const { data: jobs } = useJobs();
  // Eligible = VERIFIED emails only (§13 hard rule). We fetch verified contacts
  // scoped to the chosen job; the eligibility panel then classifies every
  // non-verified contact under an excluded reason.
  const { data: eligibleContacts } = useContacts({
    job_id: jobId || undefined,
    status: "VERIFIED",
  });
  const { data: allJobContacts } = useContacts({
    job_id: jobId || undefined,
  });
  const { data: companyMap } = useCompanyMap(jobId || undefined);

  const createCampaign = useCreateCampaign();
  const testSend = useTestSend();
  const launch = useLaunch();

  const jobOptions = useMemo(
    () => [
      { value: "", label: "Select a mining job…" },
      ...(jobs ?? []).map((j) => ({ value: j.id, label: j.name })),
    ],
    [jobs],
  );

  // Build preview contexts from verified contacts joined with company data.
  const previewContexts = useMemo<PreviewContext[]>(() => {
    const list = (eligibleContacts ?? []).filter(
      (c) => c.final_email_status === "VERIFIED" && c.email,
    );
    return list.map((c: Contact) => {
      const company = c.company_id ? companyMap?.[c.company_id] : undefined;
      return {
        contact: c,
        company: company?.canonical_name ?? null,
        industry: company?.industry ?? null,
        city: company?.city ?? null,
        state: company?.state ?? null,
        country: company?.country ?? null,
        services: company?.services?.join(", ") ?? null,
        website: company?.website ?? null,
        hiringSignal: null,
      };
    });
  }, [eligibleContacts, companyMap]);

  // Eligibility summary: eligible = verified; excluded classified by reason.
  const eligibility = useMemo<EligibilityData>(() => {
    const all = allJobContacts ?? [];
    const eligible = previewContexts.length;
    const excluded = {
      not_verified: 0,
      suppressed: 0,
      bounced: 0,
      unsubscribed: 0,
      role_based: 0,
    };
    for (const c of all) {
      if (c.final_email_status === "VERIFIED" && c.email) continue;
      // Everything that is not a verified, addressable contact is excluded.
      const role = (c.role_category ?? "").toLowerCase();
      if (["support", "info", "careers", "hr", "jobs"].includes(role)) {
        excluded.role_based += 1;
      } else {
        excluded.not_verified += 1;
      }
    }
    return { eligible, excluded, total: all.length };
  }, [allJobContacts, previewContexts]);

  const unknownTokens = useMemo(() => {
    const s = extractTokens(subject).unknown;
    const b = extractTokens(body).unknown;
    return [...new Set([...s, ...b])];
  }, [subject, body]);

  // Estimated completion ~ recipients / per-hour rate.
  const estimatedMs = useMemo(() => {
    const recipients = eligibility.eligible;
    if (recipients <= 0 || perHour <= 0) return 0;
    return Math.ceil(recipients / perHour) * 60 * 60 * 1000;
  }, [eligibility.eligible, perHour]);

  // ── Variable insertion at caret ─────────────────────────────────────────
  const insertVariable = (variable: string) => {
    const token = `{{${variable}}}`;
    const el = bodyRef.current;
    if (!el) {
      setBody((b) => b + token);
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    const next = body.slice(0, start) + token + body.slice(end);
    setBody(next);
    // Restore caret just after the inserted token.
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + token.length;
      el.setSelectionRange(pos, pos);
    });
  };

  const canSubmit = Boolean(name.trim() && subject.trim() && body.trim() && jobId);

  // Create the draft campaign, returning its id (reused by test + launch).
  async function ensureCampaign(): Promise<string | null> {
    try {
      const campaign = await createCampaign.mutateAsync({
        name: name.trim(),
        job_id: jobId,
        from_account: fromAccount,
        subject,
        body,
        ai_opener_enabled: aiOpener,
        tracking,
        rate_limit: {
          per_hour: perHour,
          per_day: perDay,
          window_start: windowStart,
          window_end: windowEnd,
          timezone,
        },
      });
      return campaign.id;
    } catch (e) {
      toast.error(
        "Could not save campaign",
        e instanceof Error ? e.message : "The campaigns API may not be available yet.",
      );
      return null;
    }
  }

  async function handleTest() {
    const id = await ensureCampaign();
    if (!id) return;
    const contact = previewContexts[Math.min(previewIndex, previewContexts.length - 1)];
    try {
      await testSend.mutateAsync({
        campaignId: id,
        body: { contact_id: contact?.contact.id },
      });
      toast.success(
        "Test email sent",
        `Compiled against ${contact?.contact.full_name ?? "a contact"}.`,
      );
    } catch (e) {
      toast.error("Test send failed", e instanceof Error ? e.message : undefined);
    }
  }

  async function handleLaunch() {
    setConfirmOpen(false);
    const id = await ensureCampaign();
    if (!id) return;
    if (demoMode) {
      // Demo mode: no real Gmail send — the campaign is created as a draft and
      // we route to its detail where a simulated send runs.
      toast.warn("Simulated send", "Demo mode is active — no real emails are dispatched.");
      router.push(`/campaigns/${id}`);
      return;
    }
    try {
      await launch.mutateAsync(id);
      toast.success(
        "Campaign launched",
        `${formatNumber(eligibility.eligible)} recipients queued.`,
      );
      router.push(`/campaigns/${id}`);
    } catch (e) {
      toast.error("Launch failed", e instanceof Error ? e.message : undefined);
    }
  }

  const busy = createCampaign.isPending || testSend.isPending || launch.isPending;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <MicroLabel className="text-accent/80">Reach · Campaign Builder</MicroLabel>
          <h1 className="text-lg font-semibold text-ink">New Campaign</h1>
        </div>
        <Button variant="ghost" size="sm" onClick={() => router.push("/campaigns")}>
          Cancel
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* ── LEFT: editor ─────────────────────────────────────────────── */}
        <Panel className="flex flex-col gap-4">
          <PanelHeader>Compose</PanelHeader>

          <Field label="Campaign name" required>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Q3 CA Firms — Ahmedabad"
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              label="Audience (job)"
              required
              hint={
                jobId
                  ? `${formatNumber(eligibility.eligible)} eligible recipients`
                  : "Pick the mining job to target"
              }
            >
              <Select
                options={jobOptions}
                value={jobId}
                onChange={(e) => {
                  setJobId(e.target.value);
                  setPreviewIndex(0);
                }}
              />
            </Field>
            <Field label="From account" required>
              <Select
                options={FROM_ACCOUNTS}
                value={fromAccount}
                onChange={(e) => setFromAccount(e.target.value)}
              />
            </Field>
          </div>

          <Field label="Subject" required>
            <Input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Quick question about {{Company}}"
            />
          </Field>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <MicroLabel>Body</MicroLabel>
              <VariableMenu onInsert={insertVariable} />
            </div>
            <textarea
              ref={bodyRef}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              onBlur={() => setBodyBlurred(true)}
              rows={10}
              className="w-full resize-y rounded-[8px] border border-border bg-[var(--color-surface-1)] px-3 py-2 font-mono text-[13px] leading-relaxed text-ink outline-none transition-colors placeholder:text-muted/70 hover:border-[var(--color-border-strong)] focus:border-[var(--color-accent)]/60 focus:bg-[var(--color-surface-2)] lm-focus"
              placeholder="Write your email… use the variable menu to insert {{FirstName}} etc."
            />
            {bodyBlurred && unknownTokens.length > 0 && (
              <p className="text-xs text-danger">
                Unknown token{unknownTokens.length > 1 ? "s" : ""}:{" "}
                <span className="font-mono underline decoration-danger decoration-wavy">
                  {unknownTokens.map((t) => `{{${t}}}`).join(", ")}
                </span>{" "}
                — not one of the 12 supported variables.
              </p>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 rounded-[8px] border border-border px-3 py-2.5">
            <div className="flex flex-col">
              <span className="text-sm font-medium text-ink">AI-generated opener</span>
              <span className="text-xs text-muted">
                Prepend a personalized first paragraph per contact.
              </span>
            </div>
            <Switch checked={aiOpener} onCheckedChange={setAiOpener} aria-label="AI opener" />
          </div>

          <div className="flex flex-col gap-1.5">
            <MicroLabel>Unsubscribe footer (read-only)</MicroLabel>
            <div className="rounded-[8px] border border-border bg-[var(--color-surface-1)] px-3 py-2">
              <UnsubscribeFooter className="mt-0 border-t-0 pt-0" />
            </div>
          </div>
        </Panel>

        {/* ── RIGHT: preview + controls ────────────────────────────────── */}
        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader>Preview</PanelHeader>
            <div className="mt-3">
              <ContactPreview
                subject={subject}
                body={body}
                aiOpener={aiOpener}
                contexts={previewContexts}
                index={previewIndex}
                onIndex={setPreviewIndex}
              />
            </div>
          </Panel>

          <Panel>
            <PanelHeader>Recipient eligibility</PanelHeader>
            <div className="mt-3">
              <EligibilitySummary data={eligibility} />
            </div>
          </Panel>

          <Panel className="flex flex-col gap-4">
            <PanelHeader>Rate limits & send window</PanelHeader>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Per hour">
                <NumberStepper value={perHour} onChange={setPerHour} min={1} max={2000} step={10} suffix="/h" />
              </Field>
              <Field label="Per day">
                <NumberStepper value={perDay} onChange={setPerDay} min={1} max={20000} step={50} suffix="/d" />
              </Field>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field label="Window start">
                <Input type="time" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
              </Field>
              <Field label="Window end">
                <Input type="time" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
              </Field>
              <Field label="Timezone">
                <Select options={TIMEZONES} value={timezone} onChange={(e) => setTimezone(e.target.value)} />
              </Field>
            </div>
            <div className="flex items-center gap-2 rounded-[8px] border border-info/25 bg-info/5 px-3 py-2">
              <Clock className="size-4 shrink-0 text-info" />
              <span className="text-xs text-muted">
                Estimated completion{" "}
                <span className="font-mono text-ink">
                  ~{estimatedMs > 0 ? formatDuration(estimatedMs) : "—"}
                </span>{" "}
                at {formatNumber(perHour)}/hour for {formatNumber(eligibility.eligible)} recipients.
              </span>
            </div>
          </Panel>

          <Panel className="flex flex-col gap-3">
            <PanelHeader>Tracking</PanelHeader>
            <TrackingToggle
              icon={<Eye className="size-4" />}
              label="Opens"
              hint="Where technically available"
              checked={tracking.opens}
              onChange={(v) => setTracking((t) => ({ ...t, opens: v }))}
            />
            <TrackingToggle
              icon={<MousePointerClick className="size-4" />}
              label="Clicks"
              hint="Where technically available"
              checked={tracking.clicks}
              onChange={(v) => setTracking((t) => ({ ...t, clicks: v }))}
            />
            <TrackingToggle
              icon={<MessageSquare className="size-4" />}
              label="Replies"
              checked={tracking.replies}
              onChange={(v) => setTracking((t) => ({ ...t, replies: v }))}
            />
            <TrackingToggle
              icon={<AlertOctagon className="size-4" />}
              label="Bounces"
              checked={tracking.bounces}
              onChange={(v) => setTracking((t) => ({ ...t, bounces: v }))}
            />
          </Panel>
        </div>
      </div>

      {/* ── Footer actions ───────────────────────────────────────────────── */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {demoMode && <StatusChip variant="warn" label="Demo mode" />}
            <span className="text-xs text-muted">
              {formatNumber(eligibility.eligible)} verified recipients · from{" "}
              <span className="font-mono text-ink">{fromAccount}</span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleTest}
              loading={testSend.isPending}
              disabled={!canSubmit || busy}
            >
              <FlaskConical className="size-4" />
              Send test email
            </Button>
            {demoMode ? (
              <Button
                onClick={handleLaunch}
                loading={createCampaign.isPending}
                disabled={!canSubmit || busy}
                className="bg-warn text-[#1A1206] hover:bg-warn/90 shadow-[0_0_0_1px_rgba(248,198,78,0.25),0_6px_20px_-8px_rgba(248,198,78,0.55)]"
              >
                <Rocket className="size-4" />
                Simulate send
              </Button>
            ) : (
              <Button onClick={() => setConfirmOpen(true)} disabled={!canSubmit || busy}>
                <Send className="size-4" />
                Launch
              </Button>
            )}
          </div>
        </div>
      </Panel>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        kicker="Launch campaign"
        title={`Send to ${formatNumber(eligibility.eligible)} verified recipients?`}
        description={
          <span className="flex flex-col gap-1">
            <span>
              From <span className="font-mono text-ink">{fromAccount}</span> at{" "}
              {formatNumber(perHour)}/hour ({formatNumber(perDay)}/day), {windowStart}–
              {windowEnd} {timezone}.
            </span>
            <span>
              Estimated completion ~{estimatedMs > 0 ? formatDuration(estimatedMs) : "—"}. Only
              VERIFIED contacts are targeted.
            </span>
          </span>
        }
        confirmLabel="Launch now"
        onConfirm={handleLaunch}
        loading={launch.isPending || createCampaign.isPending}
      />
    </div>
  );
}

function TrackingToggle({
  icon,
  label,
  hint,
  checked,
  onChange,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <span className="text-muted">{icon}</span>
        <div className="flex flex-col">
          <span className="text-sm text-ink">{label}</span>
          {hint && <span className="text-[11px] text-muted">{hint}</span>}
        </div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
    </div>
  );
}
