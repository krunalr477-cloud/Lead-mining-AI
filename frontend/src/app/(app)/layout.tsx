import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { EntityDrawerHost } from "@/components/shell/EntityDrawerHost";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell>
      {children}
      {/* URL-driven company/contact drawers; Suspense for useSearchParams. */}
      <Suspense fallback={null}>
        <EntityDrawerHost />
      </Suspense>
    </AppShell>
  );
}
