"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Building2, User as UserIcon } from "lucide-react";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { CopyButton } from "@/components/ui/CopyButton";

/**
 * EntityDrawerHost — mounted once in the (app) layout. Watches the URL for
 * ?company= and ?contact= params and opens the corresponding detail drawer.
 * Because state lives in the URL, drawers are deep-linkable and stack: a
 * contact opened from within a company drawer keeps ?company set.
 *
 * Content is stubbed for the foundation; the real evidence panels land later.
 */
export function EntityDrawerHost() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const companyId = params.get("company");
  const contactId = params.get("contact");

  const closeParam = useCallback(
    (key: "company" | "contact") => {
      const next = new URLSearchParams(params.toString());
      next.delete(key);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  return (
    <>
      <Drawer open={Boolean(companyId)} onOpenChange={(o) => !o && closeParam("company")}>
        {companyId && (
          <Drawer.Content
            kicker="Company"
            title={`Company ${companyId}`}
            width="lg"
            actions={<CopyButton value={companyId} label="ID" />}
          >
            <div className="flex flex-col gap-4">
              <MicroLabel>Entity Reference</MicroLabel>
              <EmptyState
                icon={Building2}
                title="Company detail lands here"
                description="Mining evidence, discovered contacts, source URLs, website status, and compliance posture for this company will render in this drawer."
              />
            </div>
          </Drawer.Content>
        )}
      </Drawer>

      <Drawer open={Boolean(contactId)} onOpenChange={(o) => !o && closeParam("contact")}>
        {contactId && (
          <Drawer.Content
            kicker="Contact"
            title={`Contact ${contactId}`}
            width="lg"
            actions={<CopyButton value={contactId} label="ID" />}
          >
            <div className="flex flex-col gap-4">
              <MicroLabel>Entity Reference</MicroLabel>
              <EmptyState
                icon={UserIcon}
                title="Contact detail lands here"
                description="Role, seniority, validated email with per-stage results, enrichment provenance, and sales disposition fields will render in this drawer."
              />
            </div>
          </Drawer.Content>
        )}
      </Drawer>
    </>
  );
}
