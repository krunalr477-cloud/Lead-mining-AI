"use client";

import { useEffect, useRef } from "react";
import {
  APIProvider,
  Map,
  AdvancedMarker,
  useMap,
} from "@vis.gl/react-google-maps";
import { MapPinned } from "lucide-react";
import { MicroLabel } from "@/components/ui";

export interface RadiusValue {
  latitude: number | null;
  longitude: number | null;
  radiusKm: number;
}

interface RadiusEditorProps {
  value: RadiusValue;
  /** Called on any interactive change (drag pin, drag circle edge). */
  onChange: (next: RadiusValue) => void;
  className?: string;
}

const BROWSER_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY ?? "";
const MAP_ID = process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID || undefined;

/** Fallback center (India — matches the seeded demo geography). */
const DEFAULT_CENTER = { lat: 19.076, lng: 72.8777 };

/**
 * RadiusEditor — interactive Google map with a draggable pin and an editable
 * radius circle. If NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY is empty this component
 * is never mounted (the page renders MapPlaceholder instead), but we still
 * guard here so a stray mount degrades to a note rather than crashing.
 */
export function RadiusEditor({ value, onChange, className }: RadiusEditorProps) {
  if (!BROWSER_KEY) {
    return <MapUnavailable className={className} />;
  }

  const center = {
    lat: value.latitude ?? DEFAULT_CENTER.lat,
    lng: value.longitude ?? DEFAULT_CENTER.lng,
  };

  return (
    <div className={className}>
      <APIProvider apiKey={BROWSER_KEY}>
        <Map
          mapId={MAP_ID}
          defaultCenter={center}
          defaultZoom={11}
          gestureHandling="greedy"
          disableDefaultUI={false}
          className="h-full w-full overflow-hidden rounded-[12px]"
          style={{ minHeight: 320 }}
          colorScheme="DARK"
        >
          <AdvancedMarker
            position={center}
            draggable
            onDragEnd={(e) => {
              const lat = e.latLng?.lat();
              const lng = e.latLng?.lng();
              if (lat != null && lng != null) {
                onChange({ ...value, latitude: lat, longitude: lng });
              }
            }}
          >
            <PinGlyph />
          </AdvancedMarker>
          <RadiusCircle value={value} onChange={onChange} />
        </Map>
      </APIProvider>
    </div>
  );
}

function PinGlyph() {
  return (
    <div className="relative flex size-6 items-center justify-center">
      <span className="absolute inset-0 animate-ping rounded-full bg-[var(--color-accent)]/30" />
      <span className="relative block size-3 rounded-full border-2 border-[#04120C] bg-[var(--color-accent)] shadow-[0_0_10px_var(--color-accent)]" />
    </div>
  );
}

/**
 * Imperatively-managed google.maps.Circle bound to the current pin + radius.
 * Two-way sync with update-loop protection:
 *  - Props change -> we set center/radius on the circle, marking `internal` so
 *    the resulting `radius_changed`/`center_changed` events are ignored.
 *  - User drags the circle edge/center -> we read back and call onChange.
 */
function RadiusCircle({
  value,
  onChange,
}: {
  value: RadiusValue;
  onChange: (next: RadiusValue) => void;
}) {
  const map = useMap();
  const circleRef = useRef<google.maps.Circle | null>(null);
  const internal = useRef(false);
  // Keep latest onChange without re-binding listeners (updated in an effect,
  // never during render).
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const lat = value.latitude ?? DEFAULT_CENTER.lat;
  const lng = value.longitude ?? DEFAULT_CENTER.lng;
  const radiusMeters = Math.max(value.radiusKm, 0.1) * 1000;

  // Create the circle once the map + google namespace are ready.
  useEffect(() => {
    if (!map || typeof google === "undefined") return;

    const circle = new google.maps.Circle({
      map,
      center: { lat, lng },
      radius: radiusMeters,
      editable: true,
      draggable: true,
      strokeColor: "#00F0A8",
      strokeOpacity: 0.9,
      strokeWeight: 1.5,
      fillColor: "#00F0A8",
      fillOpacity: 0.08,
    });
    circleRef.current = circle;

    const emit = () => {
      if (internal.current) return;
      const c = circle.getCenter();
      const r = circle.getRadius();
      if (!c) return;
      onChangeRef.current({
        latitude: c.lat(),
        longitude: c.lng(),
        radiusKm: Math.round((r / 1000) * 10) / 10,
      });
    };

    const l1 = circle.addListener("radius_changed", emit);
    const l2 = circle.addListener("center_changed", emit);

    return () => {
      l1.remove();
      l2.remove();
      circle.setMap(null);
      circleRef.current = null;
    };
    // Create once per map instance; prop sync handled in the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // Push external prop changes onto the circle without triggering emit().
  useEffect(() => {
    const circle = circleRef.current;
    if (!circle) return;
    internal.current = true;
    const c = circle.getCenter();
    if (!c || c.lat() !== lat || c.lng() !== lng) {
      circle.setCenter({ lat, lng });
    }
    if (circle.getRadius() !== radiusMeters) {
      circle.setRadius(radiusMeters);
    }
    // Release the guard after the events have flushed.
    const t = setTimeout(() => {
      internal.current = false;
    }, 0);
    return () => clearTimeout(t);
  }, [lat, lng, radiusMeters]);

  return null;
}

function MapUnavailable({ className }: { className?: string }) {
  return (
    <div
      className={className}
      style={{ minHeight: 320 }}
    >
      <div className="flex h-full min-h-[320px] flex-col items-center justify-center gap-3 rounded-[12px] border border-dashed border-border bg-[var(--color-surface-1)] p-6 text-center">
        <MapPinned className="size-8 text-muted/60" aria-hidden />
        <MicroLabel>Map unavailable</MicroLabel>
        <p className="max-w-xs text-xs leading-relaxed text-muted">
          Add a Maps browser key to enable the map. Use the manual latitude,
          longitude, and radius inputs to set the search area.
        </p>
      </div>
    </div>
  );
}

export default RadiusEditor;
