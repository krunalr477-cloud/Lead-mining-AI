"use client";

import { useMe } from "./api/hooks/useMe";
import type { ProviderKey, ProviderStatus } from "./api/schema";

export interface DemoState {
  /** True when the backend reports demo_mode (mock adapters active). */
  demoMode: boolean;
  /** Per-provider live/mock status. */
  providers: Record<ProviderKey, ProviderStatus>;
  /** Providers currently backed by mock adapters. */
  mockProviders: ProviderKey[];
  isLoading: boolean;
}

const EMPTY_PROVIDERS: Record<ProviderKey, ProviderStatus> = {
  google_maps: "mock",
  rocketreach: "mock",
  millionverifier: "mock",
  groq: "mock",
  serp: "mock",
  gmail: "mock",
  sheets: "mock",
};

/**
 * Demo-mode signal derived from /me. Drives the DemoRibbon and any UI that
 * warns "this data is mock". Never blocks rendering — defaults to demo on while
 * loading so we fail safe toward the honest label.
 */
export function useDemoMode(): DemoState {
  const { data, isLoading } = useMe();

  const providers = data?.providers ?? EMPTY_PROVIDERS;
  const mockProviders = (Object.keys(providers) as ProviderKey[]).filter(
    (k) => providers[k] === "mock",
  );

  return {
    demoMode: data?.demo_mode ?? isLoading,
    providers,
    mockProviders,
    isLoading,
  };
}
