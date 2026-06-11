"""Machine learning hooks for world generation (Day 2).

These are intentionally small, self-contained scikit-learn models. They exist to
satisfy the geography-first design pillar in a demo-sized way: a biome clustering
model classifies the region's climate, and a civilization-seed model scores tile
suitability so NPC homes cluster where settlement would realistically occur.

All training data is generated synthetically in-process, so there is no external
dataset dependency. Every entry point degrades gracefully if numpy/scikit-learn
are unavailable, returning deterministic fallbacks so world generation never
hard-fails on an optional dependency.
"""

from __future__ import annotations

from typing import Any, Optional

try:  # pragma: no cover - exercised by environment, not unit tests
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.tree import DecisionTreeClassifier

    _ML_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means we use fallbacks
    np = None  # type: ignore[assignment]
    KMeans = None  # type: ignore[assignment]
    DecisionTreeClassifier = None  # type: ignore[assignment]
    _ML_AVAILABLE = False


# Canonical biomes the clustering model can resolve a region to.
BIOME_LABELS = ["temperate_forest", "grassland", "wetland", "highland"]

# Reference climate profile for the single demo region: a temperate river valley.
# Features are (temperature_c, precipitation_index, elevation_index).
REGION_CLIMATE = (14.0, 0.62, 0.30)


def ml_available() -> bool:
    """Return True when numpy + scikit-learn are importable."""
    return _ML_AVAILABLE


# --------------------------------------------------------------------------- #
# Biome assignment model
# --------------------------------------------------------------------------- #
def train_biome_model(seed: int = 7) -> Optional[dict[str, Any]]:
    """Fit a KMeans model over synthetic climate samples and label its clusters.

    Returns a dict with the fitted model and a cluster->biome mapping, or None if
    scikit-learn is unavailable.
    """
    if not _ML_AVAILABLE:
        return None

    rng = np.random.RandomState(seed)
    # Synthetic archetypes: (temperature, precipitation, elevation) per biome.
    archetypes = {
        "temperate_forest": (13.0, 0.65, 0.30),
        "grassland": (18.0, 0.35, 0.20),
        "wetland": (16.0, 0.85, 0.10),
        "highland": (6.0, 0.50, 0.80),
    }
    samples = []
    for centre in archetypes.values():
        cloud = rng.normal(loc=centre, scale=(2.5, 0.08, 0.08), size=(60, 3))
        samples.append(cloud)
    features = np.vstack(samples)

    model = KMeans(n_clusters=len(archetypes), n_init=10, random_state=seed)
    model.fit(features)

    # Map each learned cluster to the nearest archetype by centroid distance.
    arch_names = list(archetypes.keys())
    arch_points = np.array(list(archetypes.values()))
    cluster_to_biome: dict[int, str] = {}
    for cluster_idx, centroid in enumerate(model.cluster_centers_):
        distances = np.linalg.norm(arch_points - centroid, axis=1)
        cluster_to_biome[cluster_idx] = arch_names[int(distances.argmin())]

    return {"model": model, "cluster_to_biome": cluster_to_biome}


def assign_region_biome(
    biome_model: Optional[dict[str, Any]],
    climate: tuple[float, float, float] = REGION_CLIMATE,
) -> str:
    """Classify the region's climate into a biome label."""
    if not biome_model or not _ML_AVAILABLE:
        return "temperate_forest"
    cluster = int(biome_model["model"].predict(np.array([climate]))[0])
    return biome_model["cluster_to_biome"].get(cluster, "temperate_forest")


# --------------------------------------------------------------------------- #
# Civilization seed model
# --------------------------------------------------------------------------- #
def train_civilization_seed_model(seed: int = 11) -> Optional[Any]:
    """Fit a small classifier that scores tile settlement suitability.

    Features are (fertility, water_proximity, elevation, openness), each in [0, 1].
    Label is 1 when a tile is a plausible place to settle. Returns the fitted
    classifier, or None if scikit-learn is unavailable.
    """
    if not _ML_AVAILABLE:
        return None

    rng = np.random.RandomState(seed)
    features = rng.rand(400, 4)
    fertility, water, elevation, openness = (
        features[:, 0],
        features[:, 1],
        features[:, 2],
        features[:, 3],
    )
    # Settle where land is fertile, water is near, terrain is low, and space is open.
    suitable = (
        (fertility > 0.45)
        & (water > 0.4)
        & (elevation < 0.7)
        & (openness > 0.35)
    ).astype(int)

    model = DecisionTreeClassifier(max_depth=4, random_state=seed)
    model.fit(features, suitable)
    return model


def settlement_suitability(
    civ_model: Optional[Any],
    fertility: float,
    water_proximity: float,
    elevation: float,
    openness: float,
) -> float:
    """Return a 0..1 suitability score for placing settlement at a tile."""
    if civ_model is None or not _ML_AVAILABLE:
        # Deterministic fallback mirroring the training rule.
        score = 0.0
        score += 0.35 if fertility > 0.45 else 0.0
        score += 0.30 if water_proximity > 0.4 else 0.0
        score += 0.20 if elevation < 0.7 else 0.0
        score += 0.15 if openness > 0.35 else 0.0
        return score
    proba = civ_model.predict_proba(
        np.array([[fertility, water_proximity, elevation, openness]])
    )[0]
    # predict_proba returns [P(class=0), P(class=1)]; guard single-class edge case.
    return float(proba[1]) if len(proba) > 1 else float(proba[0])
