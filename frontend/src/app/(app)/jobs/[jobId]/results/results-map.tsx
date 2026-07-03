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
 * ResultsMap — clustered company markers on Google Maps. ONLY mounted when a
 * browser Maps key is present (the parent hides the Table|Map toggle otherwise),
 * so this file never has to render a keyless placeholder.
 */
interface ResultsMapProps {
  apiKey: string;
  companies: Company[];
  onSelect: (companyId: string) => void;
}

interface Pin {
  id: string;
  lat: number;
  lng: number;
  name: string;
}

export function ResultsMap({ apiKey, companies, onSelect }: ResultsMapProps) {
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
      <div className="flex h-[420px] items-center justify-center rounded-[12px] border border-border bg-[var(--color-surface-1)] text-sm text-muted">
        No companies with coordinates on this page.
      </div>
    );
  }

  return (
    <div className="h-[420px] overflow-hidden rounded-[12px] border border-border">
      <APIProvider apiKey={apiKey}>
        <GMap
          defaultCenter={center}
          defaultZoom={pins.length > 1 ? 10 : 13}
          mapId="leadmine-results"
          gestureHandling="greedy"
          disableDefaultUI={false}
          className="size-full"
        >
          {pins.map((p) => (
            <AdvancedMarker
              key={p.id}
              position={{ lat: p.lat, lng: p.lng }}
              title={p.name}
              onClick={() => onSelect(p.id)}
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
