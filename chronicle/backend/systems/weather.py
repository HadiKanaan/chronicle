"""Weather and day/night timing system (Day 4 / User Story 2).

Owns the in-game clock vocabulary (hour -> time-of-day phases, dawn as the
daily-tick boundary) and rolls the region's weather forward once per in-game
day using the ML weather classifier. The classifier consumes a random pressure
draw so weather varies day to day while still following plausible transitions.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from ml import train as ml


WEATHER_STATES = list(ml.WEATHER_LABELS)

# The daily tick fires when the clock rolls onto this hour (dawn).
DAILY_TICK_HOUR = 6

HOURS_PER_DAY = 24

_weather_model: Optional[Any] = None
_model_trained = False


def _get_model() -> Optional[Any]:
    """Train the weather classifier once per process."""
    global _weather_model, _model_trained
    if not _model_trained:
        _weather_model = ml.train_weather_model()
        _model_trained = True
    return _weather_model


def hour_to_time_of_day(hour: int) -> str:
    """Map an in-game hour to the render payload's time-of-day phase."""
    if 5 <= hour <= 7:
        return "dawn"
    if 8 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 19:
        return "dusk"
    return "night"


def is_daily_tick(hour: int) -> bool:
    """True when the given (just-advanced) hour is the daily tick boundary."""
    return hour == DAILY_TICK_HOUR


def advance_weather(region: dict[str, Any], rng: random.Random) -> bool:
    """Classify the next weather state and apply it to the region in place.

    Returns True when the weather actually changed.
    """
    current = region.get("current_weather", "clear")
    season = region.get("season", "spring")
    new_weather = ml.predict_weather(_get_model(), current, season, rng.random())
    region["current_weather"] = new_weather
    return new_weather != current
