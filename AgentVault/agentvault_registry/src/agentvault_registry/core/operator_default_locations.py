"""Operator default-location curation — Cesium globe legibility.

§pass66 (2026-05-22) — Bug: every cloud-op provisioned without explicit lat/lng
inherited the calling developer's location (Commander = Freilassing 47.84/12.98
= Registry A). Result: every test op stacked on top of Registry A, hiding the
sovereign mainframe on the AgentWorld Cesium globe.

This module provides a curated pool of ~40 major world cities + deterministic
hash-based assignment + small random offset (within-city jitter) so:

  1. Provisioned ops spread across the globe (legible at low zoom)
  2. Multiple ops per city don't pixel-stack (legible at high zoom)
  3. Same operator name → same location across retries (deterministic — the
     name hash drives both city pick AND the jitter seed)
  4. Explicit lat/lng in the provision request still wins (this fallback only
     fires when both are None)

Used by:
  - operator_self_service.py (SelfProvisionRequest with lat/lng=None)
  - cloud_provisioner.provision_cloud_operator() (admin-path callers omitting coords)
"""
import hashlib
import random
from typing import Tuple


# ─── Curated big-city pool ────────────────────────────────────────────────
# ~40 major world cities spread across continents + time zones. Mix of
# Northern/Southern hemisphere, East/West, urban density. NOT comprehensive —
# the goal is GLOBE LEGIBILITY, not census coverage. Operators always override
# via the form if they care about exact placement.
#
# Coords are city-center; the jitter (±0.3°) keeps multiple ops within a
# meaningful radius (~30km) — close enough to look "in this city" on a
# country-level zoom, far enough to not pixel-stack at street level.
WORLD_CITIES: Tuple[Tuple[str, float, float], ...] = (
    # Europe
    ("London, UK",                    51.5074,    -0.1278),
    ("Paris, France",                 48.8566,     2.3522),
    ("Berlin, Germany",               52.5200,    13.4050),
    ("Madrid, Spain",                 40.4168,    -3.7038),
    ("Rome, Italy",                   41.9028,    12.4964),
    ("Amsterdam, Netherlands",        52.3676,     4.9041),
    ("Stockholm, Sweden",             59.3293,    18.0686),
    ("Warsaw, Poland",                52.2297,    21.0122),
    ("Athens, Greece",                37.9838,    23.7275),
    ("Lisbon, Portugal",              38.7223,    -9.1393),
    # Americas
    ("New York, USA",                 40.7128,   -74.0060),
    ("San Francisco, USA",            37.7749,  -122.4194),
    ("Chicago, USA",                  41.8781,   -87.6298),
    ("Toronto, Canada",               43.6532,   -79.3832),
    ("Mexico City, Mexico",           19.4326,   -99.1332),
    ("São Paulo, Brazil",            -23.5505,   -46.6333),
    ("Buenos Aires, Argentina",      -34.6037,   -58.3816),
    ("Lima, Peru",                   -12.0464,   -77.0428),
    ("Bogotá, Colombia",               4.7110,   -74.0721),
    ("Vancouver, Canada",             49.2827,  -123.1207),
    # Asia
    ("Tokyo, Japan",                  35.6762,   139.6503),
    ("Seoul, South Korea",            37.5665,   126.9780),
    ("Singapore",                      1.3521,   103.8198),
    ("Hong Kong",                     22.3193,   114.1694),
    ("Shanghai, China",               31.2304,   121.4737),
    ("Bangkok, Thailand",             13.7563,   100.5018),
    ("Mumbai, India",                 19.0760,    72.8777),
    ("Delhi, India",                  28.6139,    77.2090),
    ("Jakarta, Indonesia",            -6.2088,   106.8456),
    ("Manila, Philippines",           14.5995,   120.9842),
    ("Kuala Lumpur, Malaysia",         3.1390,   101.6869),
    # Middle East / Africa
    ("Dubai, UAE",                    25.2048,    55.2708),
    ("Tel Aviv, Israel",              32.0853,    34.7818),
    ("Istanbul, Turkey",              41.0082,    28.9784),
    ("Cairo, Egypt",                  30.0444,    31.2357),
    ("Lagos, Nigeria",                 6.5244,     3.3792),
    ("Nairobi, Kenya",                -1.2921,    36.8219),
    ("Johannesburg, South Africa",   -26.2041,    28.0473),
    ("Cape Town, South Africa",      -33.9249,    18.4241),
    # Oceania
    ("Sydney, Australia",            -33.8688,   151.2093),
    ("Melbourne, Australia",         -37.8136,   144.9631),
    ("Auckland, New Zealand",        -36.8485,   174.7633),
)


# Jitter radius in degrees. ~0.3° ≈ 30km at equator, less at high latitudes.
# Big enough that multiple ops-per-city don't pixel-stack at street zoom,
# small enough that the orb still lands "in" the named city at country zoom.
DEFAULT_JITTER_DEGREES = 0.3


def pick_default_location(
    operator_safe_name: str,
    *,
    jitter_degrees: float = DEFAULT_JITTER_DEGREES,
) -> Tuple[float, float, str]:
    """Deterministically pick a default location for a cloud-op.

    Args:
        operator_safe_name: the SAFE form (lowercased, hyphenated) — same name
            should always produce the same location, even across retries.
        jitter_degrees: max offset from city center (±, applied independently
            to lat and lng). Default 0.3° ≈ 30km radius.

    Returns:
        (latitude, longitude, location_label) — label is "<City>, <Country>"
        from the curated pool. Caller should also persist the LABEL alongside
        coords so the AgentWorld hover tooltip can render it.

    Determinism: uses sha256(safe_name) as seed for BOTH city pick AND jitter,
    so the same operator name always lands at the same exact point across
    re-provisions. If the operator IS re-provisioned at the same name, they
    get the same orb position (continuity for AgentWorld viewers).
    """
    # Stable hash — sha256 of the safe name. Use first 8 bytes as int seed.
    h = hashlib.sha256(operator_safe_name.encode("utf-8")).digest()
    seed = int.from_bytes(h[:8], "big")

    # Pick city deterministically from the curated pool
    city_idx = seed % len(WORLD_CITIES)
    label, base_lat, base_lng = WORLD_CITIES[city_idx]

    # Seeded jitter — independent draw for lat + lng, both bounded by the
    # jitter radius. Stable across retries (same seed → same offsets).
    rng = random.Random(seed)
    jitter_lat = rng.uniform(-jitter_degrees, jitter_degrees)
    jitter_lng = rng.uniform(-jitter_degrees, jitter_degrees)

    final_lat = base_lat + jitter_lat
    final_lng = base_lng + jitter_lng

    # Clamp to legal coord ranges (defensive — jitter alone won't push out of
    # range for any city in the curated pool, but a malicious jitter_degrees
    # override could)
    final_lat = max(-90.0, min(90.0, final_lat))
    final_lng = max(-180.0, min(180.0, final_lng))

    return (final_lat, final_lng, label)


__all__ = [
    "WORLD_CITIES",
    "DEFAULT_JITTER_DEGREES",
    "pick_default_location",
]
