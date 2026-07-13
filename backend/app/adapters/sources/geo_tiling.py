"""Geographic tiling for deep discovery (spec §C2).

A single Places (New) text search returns at most ~60 results regardless of the
search radius, so a 25 km metro query undercounts badly. ``tile_circle`` covers
the requested circle with 7 smaller disks (a classic hex cover: one center disk
plus six around it), each searched independently — turning the per-query cap
into a per-tile cap. Pure math, no I/O.
"""

from __future__ import annotations

import math

__all__ = ["haversine_km", "tile_circle"]

_KM_PER_DEG_LAT = 110.574


def _km_per_deg_lng(lat: float) -> float:
    return 111.320 * max(0.01, math.cos(math.radians(lat)))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def tile_circle(lat: float, lng: float, radius_km: float) -> list[tuple[float, float, float]]:
    """Cover a circle with 7 disks of radius ``radius_km / 2``.

    Returns ``[(lat, lng, tile_radius_km), ...]`` — the center tile plus six at
    bearings k*60°, distance (√3/2)·r from the center. Every point of the
    original circle is within one of the tiles (hex-cover property). Degenerate
    radii (≤ 1 km) return the single original circle — tiling adds nothing.
    """
    if radius_km <= 1.0:
        return [(lat, lng, max(0.1, radius_km))]
    tile_r = radius_km / 2.0
    ring_d = (math.sqrt(3) / 2.0) * radius_km
    tiles = [(lat, lng, tile_r)]
    for k in range(6):
        bearing = math.radians(k * 60.0)
        dlat = (ring_d * math.cos(bearing)) / _KM_PER_DEG_LAT
        dlng = (ring_d * math.sin(bearing)) / _km_per_deg_lng(lat)
        tiles.append((lat + dlat, lng + dlng, tile_r))
    return tiles
