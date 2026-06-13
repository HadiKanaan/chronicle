"""Continent overlay generation (Day 7, added scope - visual only).

This builds a graphical world map that frames the deeply-simulated town of
Aldenmoor inside a wider continent. It is generated ONCE, persisted to SQLite by
the caller, and fetched a single time by the frontend (never in the 500ms poll).
It is intentionally decoupled from the simulation loop: nothing here touches NPC
state, and the playable region is never regenerated.

Pipeline:
  1. numpy/scipy elevation + moisture fields, with a radial falloff so the
     landmass is ringed by sea (a real coastline).
  2. a sea-level threshold splits land from water.
  3. the EXISTING biome KMeans (ml.train_biome_model) labels every land cell.
  4. the EXISTING civ-seed model (ml.train_civilization_seed_model) scores each
     land cell's settlement suitability; the high-suitability cells are KMeans-
     clustered into countries, and every land cell is assigned to its nearest
     country centroid (giving borders for free where neighbors differ).
  5. a few rivers are traced downhill from the highest peaks to the sea.
  6. capitals (each country's most-suitable cell), scattered POIs, and an
     "Aldenmoor - you are here" pin are placed.
  7. the Country Property Generator (ml.generate_country_properties) produces
     correlated nation stats for the map tooltips.

Everything degrades to a deterministic fallback if numpy/scipy/scikit-learn are
unavailable, so the endpoint never hard-fails on an optional dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ml import train as ml

try:  # pragma: no cover - exercised by environment, not unit tests
    import numpy as np
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    from sklearn.cluster import KMeans

    _GEO_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means we use the fallback
    np = None  # type: ignore[assignment]
    distance_transform_edt = None  # type: ignore[assignment]
    gaussian_filter = None  # type: ignore[assignment]
    KMeans = None  # type: ignore[assignment]
    _GEO_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent.parent
NAMES_PATH = BASE_DIR / "data" / "names.json"

# Overlay grid. Kept modest so the once-fetched payload stays reasonable.
CONT_W = 80
CONT_H = 52
SEA_LEVEL = 0.40
NUM_COUNTRIES = 6
RIVER_COUNT = 4
POI_COUNT = 6
SEED = 1337

# Distinct country fills (the frontend tints cells and draws borders).
COUNTRY_COLORS = [
    "#c2603d", "#3d7bc2", "#5fa05f", "#b08fd0",
    "#d0b34f", "#4fb0a8", "#c2557f", "#8a8f9c",
]

# Biome -> overlay fill. Land only; sea is painted separately by the frontend.
BIOME_COLORS = {
    "temperate_forest": "#2f6b3a",
    "grassland": "#8fae54",
    "wetland": "#4f8f7a",
    "highland": "#9a8f7a",
}


def _load_names() -> dict[str, Any]:
    with NAMES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize(field: "np.ndarray") -> "np.ndarray":
    lo, hi = float(field.min()), float(field.max())
    if hi - lo < 1e-9:
        return np.zeros_like(field)
    return (field - lo) / (hi - lo)


# --------------------------------------------------------------------------- #
# Fields
# --------------------------------------------------------------------------- #
def _base_field(rng: "np.ndarray") -> "np.ndarray":
    """Smoothed noise in [0, 1]. Drives terrain altitude AND biome climate, so
    biome variety is independent of the coastline carved by the radial falloff."""
    return _normalize(gaussian_filter(rng.rand(CONT_H, CONT_W), sigma=5.0, mode="reflect"))


def _landmass(base: "np.ndarray") -> "np.ndarray":
    """Apply a radial falloff so the continent is ringed by sea (a coastline)."""
    yy, xx = np.mgrid[0:CONT_H, 0:CONT_W]
    dy = (yy - CONT_H / 2.0) / (CONT_H / 2.0)
    dx = (xx - CONT_W / 2.0) / (CONT_W / 2.0)
    dist = np.sqrt(dx * dx + dy * dy)
    return _normalize(np.clip(base - 0.42 * dist, 0.0, None))


def _moisture_field(rng: "np.ndarray") -> "np.ndarray":
    return _normalize(gaussian_filter(rng.rand(CONT_H, CONT_W), sigma=7.0, mode="reflect"))


# --------------------------------------------------------------------------- #
# Biomes (reuse the Day 2 biome KMeans over every land cell)
# --------------------------------------------------------------------------- #
def _classify_biomes(
    relief: "np.ndarray",
    moisture: "np.ndarray",
    land_yx: "np.ndarray",
) -> list[str]:
    """Label each land cell using the existing biome clustering model.

    The relief/moisture inputs are normalized over the LAND cells so all four
    archetypes (cold highland, wet wetland, dry grassland, mild forest) stay
    reachable - otherwise the central landmass reads as one uniform biome.
    """
    ys, xs = land_yx[:, 0], land_yx[:, 1]
    elev = _normalize(relief[ys, xs])
    moist = _normalize(moisture[ys, xs])
    latitude = ys / max(1, CONT_H - 1)
    # Climate features matched to the biome model's archetype scale (Day 2).
    # Temperature spans the full archetype range (6..18) by latitude so the
    # KMeans resolves all four biomes - cold highland in the north, mild forest
    # mid-continent, warm grassland in the south, wetland in the wettest cells.
    temperature = 6.0 + 12.0 * (1.0 - latitude)
    precipitation = 0.2 + 0.7 * moist
    features = np.column_stack([temperature, precipitation, elev])

    biome_model = ml.train_biome_model()
    if biome_model is None:
        # Threshold fallback mirroring the archetypes.
        labels = []
        for t, p, e in zip(temperature, precipitation, elev):
            if e > 0.7:
                labels.append("highland")
            elif p > 0.7:
                labels.append("wetland")
            elif t > 15.0:
                labels.append("grassland")
            else:
                labels.append("temperate_forest")
        return labels
    clusters = biome_model["model"].predict(features)
    mapping = biome_model["cluster_to_biome"]
    return [mapping.get(int(c), "temperate_forest") for c in clusters]


# --------------------------------------------------------------------------- #
# Settlement suitability (reuse the Day 2 civ-seed model)
# --------------------------------------------------------------------------- #
def _suitability(
    elevation: "np.ndarray",
    moisture: "np.ndarray",
    land_mask: "np.ndarray",
    land_yx: "np.ndarray",
) -> "np.ndarray":
    ys, xs = land_yx[:, 0], land_yx[:, 1]
    elev = elevation[ys, xs]
    fertility = moisture[ys, xs]
    # Distance to the nearest sea cell -> water proximity.
    dist_to_sea = distance_transform_edt(land_mask)[ys, xs]
    water_proximity = np.clip(1.0 - dist_to_sea / 12.0, 0.0, 1.0)
    # Openness: flat ground (low local slope) reads as open.
    gy, gx = np.gradient(elevation)
    slope = _normalize(np.sqrt(gy * gy + gx * gx))
    openness = 1.0 - slope[ys, xs]

    civ_model = ml.train_civilization_seed_model()
    if civ_model is None or not ml.ml_available():
        return np.array(
            [
                ml.settlement_suitability(None, float(f), float(w), float(e), float(o))
                for f, w, e, o in zip(fertility, water_proximity, elev, openness)
            ]
        )
    feats = np.column_stack([fertility, water_proximity, elev, openness])
    proba = civ_model.predict_proba(feats)
    return proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]


# --------------------------------------------------------------------------- #
# Countries (KMeans over high-suitability land, then nearest-centroid Voronoi)
# --------------------------------------------------------------------------- #
def _assign_countries(
    land_yx: "np.ndarray",
    suitability: "np.ndarray",
) -> "np.ndarray":
    """Return a country id per land cell (index-aligned with land_yx)."""
    n_land = len(land_yx)
    if n_land == 0:
        return np.array([], dtype=int)
    threshold = float(np.percentile(suitability, 55))
    seeds = land_yx[suitability >= threshold]
    n_clusters = min(NUM_COUNTRIES, max(1, len(seeds)))
    if KMeans is None or len(seeds) < n_clusters:
        # Fallback: a coarse vertical banding into NUM_COUNTRIES strips.
        bands = np.clip((land_yx[:, 1] * NUM_COUNTRIES) // CONT_W, 0, NUM_COUNTRIES - 1)
        return bands.astype(int)
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=SEED)
    km.fit(seeds.astype(float))
    return km.predict(land_yx.astype(float)).astype(int)


def _trace_rivers(elevation: "np.ndarray", land_mask: "np.ndarray") -> list[list[list[int]]]:
    """Steepest-descent rivers from the highest peaks down to the sea."""
    rivers: list[list[list[int]]] = []
    land_yx = np.argwhere(land_mask)
    if len(land_yx) == 0:
        return rivers
    peaks = sorted(land_yx, key=lambda c: float(elevation[c[0], c[1]]), reverse=True)
    step = max(1, len(peaks) // (RIVER_COUNT * 4))
    sources = peaks[: RIVER_COUNT * step : step][:RIVER_COUNT]
    for sy, sx in sources:
        path: list[list[int]] = []
        cy, cx = int(sy), int(sx)
        for _ in range(CONT_W + CONT_H):
            path.append([cx, cy])
            if not land_mask[cy, cx]:
                break  # reached the sea
            best = (cy, cx)
            best_e = float(elevation[cy, cx])
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < CONT_H and 0 <= nx < CONT_W and float(elevation[ny, nx]) < best_e:
                    best_e = float(elevation[ny, nx])
                    best = (ny, nx)
            if best == (cy, cx):
                break  # local minimum (inland lake)
            cy, cx = best
        if len(path) > 2:
            rivers.append(path)
    return rivers


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _fallback_continent() -> dict[str, Any]:
    """A tiny static continent when numpy/scipy are unavailable."""
    cells = []
    for y in range(CONT_H):
        for x in range(CONT_W):
            land = 8 < x < CONT_W - 8 and 6 < y < CONT_H - 6
            cells.append(
                {"x": x, "y": y, "land": land,
                 "biome": "grassland" if land else None,
                 "country": 0 if land else None}
            )
    return {
        "width": CONT_W, "height": CONT_H, "sea_level": SEA_LEVEL,
        "cells": cells, "countries": [], "rivers": [], "pois": [],
        "aldenmoor": {"x": CONT_W // 2, "y": CONT_H // 2,
                      "label": "Aldenmoor - you are here", "country_id": 0},
        "ml_available": False,
    }


def generate_continent() -> dict[str, Any]:
    """Build the full continent payload (the caller persists it once)."""
    if not _GEO_AVAILABLE:
        return _fallback_continent()

    names = _load_names()
    country_names = list(names.get("country_names", []))
    capital_names = list(names.get("country_capitals", []))
    poi_names = list(names.get("poi_names", []))

    rng = np.random.RandomState(SEED)
    base = _base_field(rng)            # shapes the landmass via the falloff
    relief = _base_field(rng)          # independent altitude for biome climate
    moisture = _moisture_field(rng)
    elevation = _landmass(base)
    land_mask = elevation > SEA_LEVEL
    land_yx = np.argwhere(land_mask)

    if len(land_yx) == 0:  # degenerate field; fall back to a solid landmass
        return _fallback_continent()

    # Biomes read an independent relief field so the climate varies regardless
    # of the coastline; rivers/suitability use the actual landmass elevation.
    biomes = _classify_biomes(relief, moisture, land_yx)
    suitability = _suitability(elevation, moisture, land_mask, land_yx)
    country_ids = _assign_countries(land_yx, suitability)

    # Land-relative moisture so country aridity spreads across the full range
    # (otherwise the whole central landmass reads uniformly dry and every
    # nation's timber gets clamped, hiding the correlated-stat variety).
    land_moist = _normalize(moisture[land_yx[:, 0], land_yx[:, 1]])

    # Per-cell lookups for assembly.
    land_index = {(int(y), int(x)): i for i, (y, x) in enumerate(land_yx)}

    # Cells payload (sea cells carry no biome/country).
    cells: list[dict[str, Any]] = []
    for y in range(CONT_H):
        for x in range(CONT_W):
            i = land_index.get((y, x))
            if i is None:
                cells.append({"x": x, "y": y, "land": False, "biome": None, "country": None})
            else:
                cells.append(
                    {"x": x, "y": y, "land": True,
                     "biome": biomes[i], "country": int(country_ids[i])}
                )

    # Sea-adjacency (coastline) test for the landlocked/naval constraint.
    def _is_coastal_cell(y: int, x: int) -> bool:
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if not (0 <= ny < CONT_H and 0 <= nx < CONT_W) or not land_mask[ny, nx]:
                return True
        return False

    country_model = ml.train_country_property_model()
    unique_ids = sorted({int(c) for c in country_ids})
    countries: list[dict[str, Any]] = []
    for slot, cid in enumerate(unique_ids):
        member_mask = country_ids == cid
        members = land_yx[member_mask]
        member_suit = suitability[member_mask]
        member_biomes = [biomes[i] for i in np.where(member_mask)[0]]

        # Capital: the most settlement-suitable cell in the country.
        cap_local = int(np.argmax(member_suit))
        cap_y, cap_x = int(members[cap_local][0]), int(members[cap_local][1])

        dominant_biome = max(set(member_biomes), key=member_biomes.count)
        is_coastal = any(_is_coastal_cell(int(y), int(x)) for y, x in members)
        mean_elev = float(elevation[members[:, 0], members[:, 1]].mean())
        mean_moist = float(land_moist[member_mask].mean())
        aridity = 1.0 - mean_moist
        size_norm = float(len(members)) / float(len(land_yx))
        forest_factor = 1.0 if dominant_biome in ("temperate_forest", "wetland") else 0.3

        properties = ml.generate_country_properties(
            country_model, is_coastal, aridity, mean_elev, min(1.0, size_norm * 3.0), forest_factor
        )
        countries.append(
            {
                "id": cid,
                "name": country_names[slot % len(country_names)] if country_names else f"Country {cid}",
                "color": COUNTRY_COLORS[slot % len(COUNTRY_COLORS)],
                "capital": {
                    "x": cap_x, "y": cap_y,
                    "name": capital_names[slot % len(capital_names)] if capital_names else "Capital",
                },
                "dominant_biome": dominant_biome,
                "is_coastal": is_coastal,
                "size_cells": int(len(members)),
                "properties": properties,
            }
        )

    rivers = _trace_rivers(elevation, land_mask)

    # POIs: scattered high-suitability inland cells (ruins, landmarks).
    pois: list[dict[str, Any]] = []
    if poi_names:
        order = np.argsort(-suitability)
        picked = 0
        used: set[tuple[int, int]] = set()
        for idx in order:
            y, x = int(land_yx[idx][0]), int(land_yx[idx][1])
            if any(abs(y - py) + abs(x - px) < 6 for py, px in used):
                continue
            used.add((y, x))
            pois.append({"x": x, "y": y, "name": poi_names[picked % len(poi_names)], "kind": "ruin"})
            picked += 1
            if picked >= min(POI_COUNT, len(poi_names)):
                break

    # "Aldenmoor - you are here": pin near a temperate, coastal capital.
    pin_country = next(
        (c for c in countries if c["dominant_biome"] == "temperate_forest"),
        countries[0] if countries else None,
    )
    if pin_country is not None:
        aldenmoor = {
            "x": pin_country["capital"]["x"],
            "y": pin_country["capital"]["y"],
            "label": "Aldenmoor - you are here",
            "country_id": pin_country["id"],
        }
    else:
        aldenmoor = {"x": CONT_W // 2, "y": CONT_H // 2,
                     "label": "Aldenmoor - you are here", "country_id": None}

    return {
        "width": CONT_W,
        "height": CONT_H,
        "sea_level": SEA_LEVEL,
        "biome_colors": BIOME_COLORS,
        "cells": cells,
        "countries": countries,
        "rivers": rivers,
        "pois": pois,
        "aldenmoor": aldenmoor,
        "ml_available": ml.ml_available(),
    }
