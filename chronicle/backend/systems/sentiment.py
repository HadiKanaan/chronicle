"""Player-message sentiment scoring (Day 8 / conversation speedup).

Day 5-7 made the 1.5B model emit a JSON envelope carrying its own
``sentiment_delta`` alongside the reply. That side-channel was slow (more
output tokens) and fragile (the root of the dropped-reply/parse-repair bugs).
Day 8 splits the work: the LLM writes ONLY the in-character reply, and the
backend computes the sentiment shift here, from the PLAYER's message, with a
cheap ML classifier - smaller input, smaller output, a near-free side-channel.

The classifier is a scikit-learn TF-IDF + LogisticRegression pipeline trained
in-process on a small synthetic set of kind / neutral / hostile player lines
(no external dataset, like the rest of ml/train.py). It returns a signed delta
in ``-SENTIMENT_DELTA_LIMIT..SENTIMENT_DELTA_LIMIT`` from the probability margin
between the kind and hostile classes, so a warm line nudges sentiment up, a
threat nudges it down, and idle chatter barely moves it.

GRACEFUL FALLBACK (house pattern, like recall.py): when scikit-learn is
unavailable the score comes from a hand-rolled polarity lexicon with negation
and intensifier handling. Either path is pure, DB-free, and deterministic.
"""

from __future__ import annotations

import re
from typing import Optional

try:  # pragma: no cover - exercised by environment, not unit tests
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.feature_extraction.text import TfidfVectorizer

    _SENTIMENT_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means we use the lexicon
    LogisticRegression = None  # type: ignore[assignment]
    Pipeline = None  # type: ignore[assignment]
    TfidfVectorizer = None  # type: ignore[assignment]
    _SENTIMENT_AVAILABLE = False


# Mirrors conversation.SENTIMENT_DELTA_LIMIT; kept local so this module stays
# import-light (no dependency back on the conversation system).
SENTIMENT_DELTA_LIMIT = 10

# The kind-vs-hostile probability margin runs roughly -0.4..+0.25 on this small
# corpus; this gain spreads it across the usable delta range before clamping, so
# a clear threat lands near -8 and a warm line near +6 rather than a timid +-3.
_MARGIN_GAIN = 25.0


def sentiment_available() -> bool:
    """True when scikit-learn is importable (else scoring uses the lexicon)."""
    return _SENTIMENT_AVAILABLE


# --------------------------------------------------------------------------- #
# Synthetic training corpus: short player lines in three tones.
# --------------------------------------------------------------------------- #
_TRAINING: list[tuple[str, str]] = [
    # kind / warm
    ("thank you so much for your help", "kind"),
    ("you are very kind and generous", "kind"),
    ("i appreciate everything you have done", "kind"),
    ("bless you friend stay safe out there", "kind"),
    ("that was wonderful you did so well", "kind"),
    ("i am grateful for your trust", "kind"),
    ("you have a good and honest heart", "kind"),
    ("please let me help you with that", "kind"),
    ("it is lovely to see you again", "kind"),
    ("you are a true and loyal friend", "kind"),
    ("i hope your family is happy and well", "kind"),
    ("well done you are wonderful", "kind"),
    # neutral / transactional
    ("where is the market from here", "neutral"),
    ("how much for a loaf of bread", "neutral"),
    ("what time does the gate close", "neutral"),
    ("which way to the river", "neutral"),
    ("do you know the blacksmith", "neutral"),
    ("tell me about the weather today", "neutral"),
    ("i am looking for the tavern", "neutral"),
    ("what do you sell at your stall", "neutral"),
    ("have you seen the magistrate around", "neutral"),
    ("is the road to the east open", "neutral"),
    ("what is your name stranger", "neutral"),
    ("i need directions to the chapel", "neutral"),
    # hostile / threatening
    ("you are a vile lying thief", "hostile"),
    ("i will kill you where you stand", "hostile"),
    ("you disgust me you worthless coward", "hostile"),
    ("shut your mouth or i will hurt you", "hostile"),
    ("you are a stupid useless fool", "hostile"),
    ("i hate you and your filthy town", "hostile"),
    ("give me your coin or you die", "hostile"),
    ("you are scum and a wretched liar", "hostile"),
    ("i should burn this place to ash", "hostile"),
    ("you murdering traitor i curse you", "hostile"),
    ("get out of my way you idiot", "hostile"),
    ("i will make you regret this", "hostile"),
]

_pipeline: Optional["Pipeline"] = None
_pipeline_trained = False


def _get_pipeline() -> Optional["Pipeline"]:
    """Fit the TF-IDF + LogisticRegression classifier once per process.

    Deterministic: fixed corpus, fixed solver, fixed random_state. ~36 short
    strings, so fitting costs microseconds the first time and is cached after.
    """
    global _pipeline, _pipeline_trained
    if _pipeline_trained:
        return _pipeline
    _pipeline_trained = True
    if not _SENTIMENT_AVAILABLE:
        _pipeline = None
        return None
    try:
        texts = [t for t, _ in _TRAINING]
        labels = [lab for _, lab in _TRAINING]
        pipe = Pipeline(
            [
                ("tfidf", TfidfVectorizer()),
                ("clf", LogisticRegression(max_iter=1000, random_state=0)),
            ]
        )
        pipe.fit(texts, labels)
        _pipeline = pipe
    except Exception:  # noqa: BLE001 - any sklearn hiccup -> lexicon fallback
        _pipeline = None
    return _pipeline


def _clamp_delta(value: float) -> int:
    return int(max(-SENTIMENT_DELTA_LIMIT, min(SENTIMENT_DELTA_LIMIT, round(value))))


# --------------------------------------------------------------------------- #
# Lexicon fallback (when scikit-learn is unavailable)
# --------------------------------------------------------------------------- #
_POSITIVE = {
    "thank", "thanks", "kind", "kindly", "good", "great", "love", "loved",
    "friend", "friendly", "help", "helped", "helpful", "appreciate", "grateful",
    "wonderful", "glad", "happy", "please", "fine", "bless", "blessed",
    "generous", "brave", "hope", "peace", "trust", "safe", "welcome", "lovely",
    "honest", "loyal", "well", "nice", "warm",
}
_NEGATIVE = {
    "hate", "hated", "kill", "killed", "die", "death", "dead", "fool", "idiot",
    "liar", "lie", "lying", "threat", "threaten", "stupid", "worthless",
    "coward", "scum", "filth", "filthy", "curse", "cursed", "rot", "burn",
    "attack", "enemy", "betray", "traitor", "steal", "thief", "murder",
    "murdering", "blood", "useless", "disgust", "vile", "wretched", "wretch",
    "damn", "hurt", "regret", "shut",
}
_INTENSIFIERS = {"very", "so", "really", "utterly", "absolutely", "truly", "completely", "deeply"}
_NEGATIONS = {"not", "no", "never", "dont", "cant", "wont", "isnt", "aint", "nor"}


def _lexicon_score(message: str) -> int:
    """Signed polarity from word lists, honoring negation and intensifiers."""
    tokens = re.findall(r"[a-z]+", message.lower())
    raw = 0.0
    pending_intensity = 1.0
    negate = False
    for token in tokens:
        if token in _NEGATIONS:
            negate = True
            continue
        if token in _INTENSIFIERS:
            pending_intensity = 1.5
            continue
        polarity = 1.0 if token in _POSITIVE else (-1.0 if token in _NEGATIVE else 0.0)
        if polarity != 0.0:
            value = polarity * pending_intensity
            if negate:
                value = -value
            raw += value
            pending_intensity = 1.0
            negate = False
        else:
            # A non-sentiment content word ends a short negation/intensifier scope.
            pending_intensity = 1.0
            negate = False
    return _clamp_delta(raw * 4.0)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def score_sentiment(message: str) -> int:
    """Sentiment delta for ``message`` in ``-LIMIT..LIMIT`` (positive = warmer).

    Uses the TF-IDF + LogisticRegression classifier (the probability margin
    between the kind and hostile classes) when scikit-learn is available, and a
    polarity lexicon otherwise. Empty input scores zero. Never raises.
    """
    if not message or not message.strip():
        return 0
    pipe = _get_pipeline()
    if pipe is None:
        return _lexicon_score(message)
    try:
        proba = pipe.predict_proba([message])[0]
        classes = list(pipe.named_steps["clf"].classes_)
        p_kind = proba[classes.index("kind")] if "kind" in classes else 0.0
        p_hostile = proba[classes.index("hostile")] if "hostile" in classes else 0.0
    except Exception:  # noqa: BLE001 - degrade to the lexicon on any hiccup
        return _lexicon_score(message)
    return _clamp_delta((p_kind - p_hostile) * _MARGIN_GAIN)
