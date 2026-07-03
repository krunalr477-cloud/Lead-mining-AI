"use client";

import { useSearchParams } from "next/navigation";
import { CompanyDrawer } from "@/components/entities/company-drawer";
import { ContactDrawer } from "@/components/entities/contact-drawer";
import { useEntityLinks } from "@/components/entities/use-entity-links";

/**
 * EntityDrawerHost — mounted once in the (app) layout. Watches the URL for
 * ?company= and ?contact= params and opens the corresponding detail drawer.
 * Because state lives in the URL, drawers are deep-linkable and STACK: a
 * contact opened from within a company drawer keeps ?company set, so both
 * sheets render (the second offset over the first via the Drawer depth
 * context). `?tab=history` deep-links the contact drawer to its History tab.
 */
export function EntityDrawerHost() {
  const params = useSearchParams();
  const { companyId, contactId, closeCompany, closeContact } = useEntityLinks();
  const contactTab = params.get("tab") === "history" ? "history" : "profile";

  return (
    <>
      {companyId && (
        <CompanyDrawer
          companyId={companyId}
          open={Boolean(companyId)}
          onClose={closeCompany}
        />
      )}
      {contactId && (
        <ContactDrawer
          contactId={contactId}
          open={Boolean(contactId)}
          onClose={closeContact}
          defaultTab={contactTab}
        />
      )}
    </>
  );
}
