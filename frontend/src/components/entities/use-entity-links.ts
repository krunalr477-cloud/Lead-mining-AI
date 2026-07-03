"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * URL-driven open/close for the entity drawers. Setting ?company= or ?contact=
 * opens the corresponding drawer; because both live in the URL a contact opened
 * from inside a company drawer keeps ?company set, so the drawers STACK.
 */
export function useEntityLinks() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const setParam = useCallback(
    (key: "company" | "contact", value: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  return {
    companyId: params.get("company"),
    contactId: params.get("contact"),
    openCompany: (id: string) => setParam("company", id),
    openContact: (id: string) => setParam("contact", id),
    closeCompany: () => setParam("company", null),
    closeContact: () => setParam("contact", null),
  };
}
