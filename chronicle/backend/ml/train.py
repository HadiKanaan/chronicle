"""Machine learning hooks for world generation (Day 2) and behavior (Day 4).

These are intentionally small, self-contained scikit-learn models. Day 2 covers
geography: a biome clustering model classifies the region's climate, and a
civilization-seed model scores tile suitability so NPC homes cluster where
settlement would realistically occur. Day 4 covers the living-world layer: a
behavior classifier picks what each NPC does given the hour and their state, a
mood model rolls each NPC's mood forward on the daily tick, and a weather
classifier produces the next day's weather.

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


# --------------------------------------------------------------------------- #
# NPC behavior classifier (Day 4)
# --------------------------------------------------------------------------- #
BEHAVIOR_LABELS = [
    "working",
    "socializing",
    "staying_home",
    "traveling",
    "sleeping",
    "fleeing",
    "seeking_info",
]

# Behavior features, each in [0, 1]:
# (hour_norm, mood_valence, sociability, weather_severity, fear, restlessness, curiosity)


def _behavior_rule(
    hour: int,
    valence: float,
    sociability: float,
    weather_severity: float,
    fear: float,
    restlessness: float,
    curiosity: float,
) -> str:
    """Ground-truth rule used to label synthetic behavior training samples."""
    if fear >= 0.7:
        return "fleeing"
    if hour < 6 or hour >= 22:
        return "sleeping"
    if weather_severity >= 0.75:
        return "staying_home"
    if 8 <= hour < 17:
        if restlessness >= 0.8:
            return "traveling"
        if curiosity >= 0.85 and valence < 0.5:
            return "seeking_info"
        return "working"
    if 17 <= hour < 22:
        if curiosity >= 0.65 and sociability < 0.5:
            return "seeking_info"
        if sociability >= 0.5:
            return "socializing"
        return "staying_home"
    # Dawn hours (6-7): ease into the day at home.
    return "staying_home"


def train_behavior_model(seed: int = 17) -> Optional[Any]:
    """Fit a decision tree mapping NPC state features to a behavior label.

    Samples are drawn uniformly over the feature space and labelled with the
    rule above, so the tree learns an explainable daily routine: sleep at
    night, work the day, socialize or pry in the evening, shelter from storms,
    and flee when terrified. Returns None if scikit-learn is unavailable.
    """
    if not _ML_AVAILABLE:
        return None

    rng = np.random.RandomState(seed)
    n = 3000
    hours = rng.randint(0, 24, size=n)
    features = rng.rand(n, 6)  # valence, sociability, weather, fear, restlessness, curiosity
    labels = [
        _behavior_rule(int(hours[i]), *features[i])
        for i in range(n)
    ]
    matrix = np.column_stack([hours / 23.0, features])

    model = DecisionTreeClassifier(max_depth=8, random_state=seed)
    model.fit(matrix, labels)
    return model


def classify_behavior(
    behavior_model: Optional[Any],
    hour: int,
    mood_valence: float,
    sociability: float,
    weather_severity: float,
    fear: float,
    restlessness: float,
    curiosity: float,
) -> str:
    """Classify an NPC's current behavior state from its features."""
    if behavior_model is None or not _ML_AVAILABLE:
        return _behavior_rule(
            hour, mood_valence, sociability, weather_severity, fear, restlessness, curiosity
        )
    row = np.array(
        [[hour / 23.0, mood_valence, sociability, weather_severity, fear, restlessness, curiosity]]
    )
    label = str(behavior_model.predict(row)[0])
    return label if label in BEHAVIOR_LABELS else "staying_home"


# --------------------------------------------------------------------------- #
# Mood update model (Day 4)
# --------------------------------------------------------------------------- #
MOOD_LABELS = ["happy", "content", "neutral", "anxious", "fearful", "angry"]


def _mood_rule(
    valence_now: float,
    event_valence: float,
    weather_severity: float,
    social_satisfaction: float,
) -> str:
    """Ground-truth rule used to label synthetic mood training samples."""
    # A sharp negative event hitting a stable person reads as anger, not fear.
    if event_valence < 0.2 and valence_now > 0.5:
        return "angry"
    score = (
        0.45 * valence_now
        + 0.30 * event_valence
        + 0.15 * (1.0 - weather_severity)
        + 0.10 * social_satisfaction
    )
    if score >= 0.72:
        return "happy"
    if score >= 0.55:
        return "content"
    if score >= 0.42:
        return "neutral"
    if score >= 0.28:
        return "anxious"
    return "fearful"


def train_mood_model(seed: int = 23) -> Optional[Any]:
    """Fit a decision tree that rolls an NPC's mood forward one day.

    Features are (current mood valence, valence of yesterday's most significant
    event, weather severity, social satisfaction), each in [0, 1]. Returns None
    if scikit-learn is unavailable.
    """
    if not _ML_AVAILABLE:
        return None

    rng = np.random.RandomState(seed)
    features = rng.rand(2500, 4)
    labels = [_mood_rule(*row) for row in features]

    model = DecisionTreeClassifier(max_depth=6, random_state=seed)
    model.fit(features, labels)
    return model


def predict_mood(
    mood_model: Optional[Any],
    valence_now: float,
    event_valence: float,
    weather_severity: float,
    social_satisfaction: float,
) -> str:
    """Predict the NPC's next mood label for the new day."""
    if mood_model is None or not _ML_AVAILABLE:
        return _mood_rule(valence_now, event_valence, weather_severity, social_satisfaction)
    row = np.array([[valence_now, event_valence, weather_severity, social_satisfaction]])
    label = str(mood_model.predict(row)[0])
    return label if label in MOOD_LABELS else "neutral"


# --------------------------------------------------------------------------- #
# Weather classifier (Day 4)
# --------------------------------------------------------------------------- #
WEATHER_LABELS = ["clear", "rain", "fog", "storm"]
SEASON_LABELS = ["spring", "summer", "autumn", "winter"]

# Per-weather transition probabilities over (clear, rain, fog, storm). Spring
# baseline; other seasons shift the same table slightly via the season feature.
_WEATHER_TRANSITIONS = {
    "clear": (0.65, 0.20, 0.10, 0.05),
    "rain": (0.35, 0.35, 0.15, 0.15),
    "fog": (0.50, 0.20, 0.25, 0.05),
    "storm": (0.30, 0.40, 0.10, 0.20),
}


def _weather_rule(current_idx: int, season_idx: int, pressure: float) -> str:
    """Pick tomorrow's weather from the transition CDF at a pressure draw."""
    current = WEATHER_LABELS[current_idx % len(WEATHER_LABELS)]
    probs = list(_WEATHER_TRANSITIONS[current])
    # Wetter shoulder seasons: autumn/winter shift weight from clear to rain.
    if season_idx >= 2:
        shift = min(0.10, probs[0])
        probs[0] -= shift
        probs[1] += shift
    cumulative = 0.0
    for label, prob in zip(WEATHER_LABELS, probs):
        cumulative += prob
        if pressure <= cumulative:
            return label
    return WEATHER_LABELS[-1]


def train_weather_model(seed: int = 29) -> Optional[Any]:
    """Fit a decision tree over synthetic weather transitions.

    Features are (current weather index, season index, pressure in [0, 1]); the
    pressure input lets the tree learn the transition CDF so a random draw at
    prediction time yields varied but plausible weather. Returns None if
    scikit-learn is unavailable.
    """
    if not _ML_AVAILABLE:
        return None

    rng = np.random.RandomState(seed)
    n = 4000
    current = rng.randint(0, len(WEATHER_LABELS), size=n)
    season = rng.randint(0, len(SEASON_LABELS), size=n)
    pressure = rng.rand(n)
    labels = [
        _weather_rule(int(current[i]), int(season[i]), float(pressure[i]))
        for i in range(n)
    ]
    matrix = np.column_stack([current, season, pressure])

    model = DecisionTreeClassifier(max_depth=8, random_state=seed)
    model.fit(matrix, labels)
    return model


def predict_weather(
    weather_model: Optional[Any],
    current_weather: str,
    season: str,
    pressure: float,
) -> str:
    """Classify the next weather state from current conditions and a pressure draw."""
    current_idx = WEATHER_LABELS.index(current_weather) if current_weather in WEATHER_LABELS else 0
    season_idx = SEASON_LABELS.index(season) if season in SEASON_LABELS else 0
    if weather_model is None or not _ML_AVAILABLE:
        return _weather_rule(current_idx, season_idx, pressure)
    row = np.array([[current_idx, season_idx, pressure]])
    label = str(weather_model.predict(row)[0])
    return label if label in WEATHER_LABELS else "clear"


# --------------------------------------------------------------------------- #
# Conversation card-delta mood fallback (Day 5)
# --------------------------------------------------------------------------- #
_conversation_mood_model: Optional[Any] = None
_conversation_mood_trained = False


def predict_conversation_mood(valence_now: float, event_valence: float) -> str:
    """Arbitrate an NPC's post-conversation mood when the LLM's card delta
    proposes an invalid label.

    The LLM proposes, the ML mood model validates: the conversation's tone
    (its sentiment delta mapped to event valence) is scored like any other
    daily event, with neutral weather and average social satisfaction so only
    the exchange itself moves the needle.
    """
    global _conversation_mood_model, _conversation_mood_trained
    if not _conversation_mood_trained:
        _conversation_mood_model = train_mood_model()
        _conversation_mood_trained = True
    return predict_mood(_conversation_mood_model, valence_now, event_valence, 0.0, 0.5)
