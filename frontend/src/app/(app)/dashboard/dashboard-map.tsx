"use client";

import { useMemo } from "react";
import {
  AdvancedMarker,
  APIProvider,
  Map as GMap,
} from "@vis.gl/react-google-maps";
import type { Company } from "@/lib/api/schema";
import { num } from "@/lib/entities";

/**
 * DashboardMap — a lightweight clustered-marker preview of the newest job's
 * companies, ONLY mounted by the dashboard when a browser Maps key is present.
 * Mirrors the Results map treatment (accent LED pins) but read-only.
 */
interface DashboardMapProps {
  apiKey: string;
  companies: Company[];
  height?: number;
}

interface Pin {
  id: string;
  lat: number;
  lng: number;
  name: string;
}

export function DashboardMap({ apiKey, companies, height = 300 }: DashboardMapProps) {
  const pins = useMemo<Pin[]>(() => {
    const seen = new Set<string>();
    const out: Pin[] = [];
    for (const c of companies) {
      if (seen.has(c.id)) continue;
      const lat = num(c.latitude);
      const lng = num(c.longitude);
      if (lat == null || lng == null) continue;
      seen.add(c.id);
      out.push({ id: c.id, lat, lng, name: c.canonical_name });
    }
    return out;
  }, [companies]);

  const center = useMemo(() => {
    if (!pins.length) return { lat: 20.5937, lng: 78.9629 }; // India centroid
    const sum = pins.reduce(
      (acc, p) => ({ lat: acc.lat + p.lat, lng: acc.lng + p.lng }),
      { lat: 0, lng: 0 },
    );
    return { lat: sum.lat / pins.length, lng: sum.lng / pins.length };
  }, [pins]);

  if (!pins.length) {
    return (
      <div
        className="flex items-center justify-center rounded-[12px] border border-border bg-[var(--color-surface-1)] text-sm text-muted"
        style={{ height }}
      >
        No companies with coordinates yet.
      </div>
    );
  }

  return (
    <div
      className="overflow-hidden rounded-[12px] border border-border"
      style={{ height }}
    >
      <APIProvider apiKey={apiKey}>
        <GMap
          defaultCenter={center}
          defaultZoom={pins.length > 1 ? 10 : 13}
          mapId="leadmine-dashboard"
          gestureHandling="greedy"
          disableDefaultUI
          className="size-full"
        >
          {pins.map((p) => (
            <AdvancedMarker
              key={p.id}
              position={{ lat: p.lat, lng: p.lng }}
              title={p.name}
            >
              <span
                className="block size-3 rounded-full border-2 border-black/60"
                style={{
                  backgroundColor: "var(--color-accent)",
                  boxShadow: "0 0 8px var(--color-accent)",
                }}
              />
            </AdvancedMarker>
          ))}
        </GMap>
      </APIProvider>
    </div>
  );
}
