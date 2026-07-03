"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";

export default function LoginPage() {
  // useSearchParams() requires a Suspense boundary for static prerender.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [loading, setLoading] = useState<"google" | "dev" | null>(null);

  const next = params.get("next") || "/dashboard";

  const devLogin = async () => {
    setLoading("dev");
    try {
      const { response } = await api.POST("/api/v1/auth/dev-login");
      if (!response.ok) throw new Error(String(response.status));
      await queryClient.invalidateQueries({ queryKey: queryKeys.me() });
      router.replace(next);
    } catch {
      toast.error("Dev login failed", "Is the backend running on :8000?");
      setLoading(null);
    }
  };

  const googleLogin = () => {
    setLoading("google");
    // Backend owns the OAuth handshake; it redirects back with the cookie set.
    window.location.href = "/api/v1/auth/google/start";
  };

  return (
    <div className="relative z-10 flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <span className="flex size-11 items-center justify-center rounded-[10px] bg-accent text-[#04120C] shadow-[0_0_24px_-4px_rgba(0,240,168,0.7)]">
            <span className="font-mono text-lg font-bold">L</span>
          </span>
          <div>
            <h1 className="text-lg font-semibold text-ink">LeadMine AI</h1>
            <MicroLabel className="text-accent/70">Command Center</MicroLabel>
          </div>
        </div>

        <Panel>
          <Panel.Header>
            <MicroLabel>Sign In</MicroLabel>
            <p className="text-sm text-muted">Access your lead-mining workspace.</p>
          </Panel.Header>

          <div className="flex flex-col gap-3">
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              loading={loading === "google"}
              onClick={googleLogin}
            >
              <LogIn className="size-4" />
              Continue with Google
            </Button>

            <div className="flex items-center gap-3 py-1">
              <span className="h-px flex-1 bg-border" />
              <MicroLabel>or</MicroLabel>
              <span className="h-px flex-1 bg-border" />
            </div>

            <Button
              variant="secondary"
              size="lg"
              className="w-full"
              loading={loading === "dev"}
              onClick={devLogin}
            >
              Dev Login (Demo)
            </Button>
          </div>

          <Panel.Section divided className="mt-4">
            <p className="text-xs leading-relaxed text-muted">
              Dev login issues a demo session with mock adapters. Real Google OAuth requires the
              backend to be configured with Workspace credentials.
            </p>
          </Panel.Section>
        </Panel>
      </div>
    </div>
  );
}
