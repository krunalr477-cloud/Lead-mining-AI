import type { Contact, TemplateVariable } from "@/lib/api/schema";

/** The 12 supported template variables in menu order (§13). */
export const TEMPLATE_VARIABLES: readonly TemplateVariable[] = [
  "FirstName",
  "LastName",
  "FullName",
  "Company",
  "Industry",
  "City",
  "State",
  "Country",
  "Services",
  "Designation",
  "Website",
  "HiringSignal",
];

const VARIABLE_SET = new Set<string>(TEMPLATE_VARIABLES);

/** A contact plus the company-scoped context needed to resolve every variable. */
export interface PreviewContext {
  contact: Contact;
  company?: string | null;
  industry?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  services?: string | null;
  website?: string | null;
  hiringSignal?: string | null;
}

/** Resolve one variable name against a preview context. Returns null if unknown/missing. */
export function resolveVariable(
  name: string,
  ctx: PreviewContext,
): string | null {
  const c = ctx.contact;
  switch (name as TemplateVariable) {
    case "FirstName":
      return c.first_name ?? null;
    case "LastName":
      return c.last_name ?? null;
    case "FullName":
      return c.full_name ?? null;
    case "Company":
      return ctx.company ?? null;
    case "Industry":
      return ctx.industry ?? null;
    case "City":
      return ctx.city ?? null;
    case "State":
      return ctx.state ?? null;
    case "Country":
      return ctx.country ?? null;
    case "Services":
      return ctx.services ?? null;
    case "Designation":
      return c.designation ?? null;
    case "Website":
      return ctx.website ?? null;
    case "HiringSignal":
      return ctx.hiringSignal ?? null;
    default:
      return null;
  }
}

const TOKEN_RE = /\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g;

export interface CompileResult {
  text: string;
  /** Variables referenced in the template that had no value for this contact. */
  missing: string[];
  /** Tokens that are not one of the 12 known variables. */
  unknown: string[];
}

/** Compile a template string against a contact context, tracking gaps. */
export function compileTemplate(
  template: string,
  ctx: PreviewContext,
): CompileResult {
  const missing = new Set<string>();
  const unknown = new Set<string>();
  const text = template.replace(TOKEN_RE, (_m, rawName: string) => {
    const name = rawName.trim();
    if (!VARIABLE_SET.has(name)) {
      unknown.add(name);
      return `{{${name}}}`;
    }
    const value = resolveVariable(name, ctx);
    if (value == null || value === "") {
      missing.add(name);
      return `{{${name}}}`;
    }
    return value;
  });
  return { text, missing: [...missing], unknown: [...unknown] };
}

/** Extract the distinct tokens (known + unknown) referenced by a template. */
export function extractTokens(template: string): {
  known: string[];
  unknown: string[];
} {
  const known = new Set<string>();
  const unknown = new Set<string>();
  for (const m of template.matchAll(TOKEN_RE)) {
    const name = m[1].trim();
    if (VARIABLE_SET.has(name)) known.add(name);
    else unknown.add(name);
  }
  return { known: [...known], unknown: [...unknown] };
}

/** True when `name` is one of the 12 supported variables. */
export function isKnownVariable(name: string): boolean {
  return VARIABLE_SET.has(name.trim());
}
