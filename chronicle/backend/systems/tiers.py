"""Dynamic NPC tier promotion/demotion - the "LRU of personhood" (Day 8).

A town of ~80 villagers can only afford ~10 deeply-simulated Tier 1 characters
(the conversation + LLM-enrichment budget is built around that number). So which
ten get to be real people is decided by the PLAYER's attention, not fixed at
world generation:

- When the player keeps talking to a background Tier-2/3 villager, that NPC earns
  personhood and is PROMOTED to Tier 1: it is seeded a dark trait / redeeming
  quality / trauma from the names.json pools, flipped to tier 1, linked into the
  Tier-1 social graph with a few reciprocal relationships, and queued for the
  one-off LLM enrichment that sharpens those seeds.
- To hold the ~10 cap, the least-recently-conversed-with Tier 1 is DEMOTED back
  to Tier 2 (LRU). Demotion is *only* a tier flip: the card keeps every memory,
  history line, relationship, and enrichment, so if the player returns to that
  villager later they are re-promoted remembering everything.

is_player and is_demon_lord NPCs stand outside this entirely (the player is never
demoted; the antagonist is never a candidate either way).

Pure where it can be, exactly like rumors.py / relationships.py: the promote /
demote / LRU decisions operate on the plain card dicts stored in SQLite, mutate
them in place, and never touch the database. ``main.py`` wires them into the
conversation flow under its ``_sim_lock`` and persists whatever changed.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
NAMES_PATH = BASE_DIR / "data" / "names.json"

# Enough player conversations with a background villager to earn promotion. The
# count is cumulative and survives demotion, so a returning favourite re-promotes
# fast. ~2-3 keeps the demo snappy ("talk to a farmer a few times").
PROMOTION_THRESHOLD = 3

# Target size of the deeply-simulated Tier-1 roster, counted over PROMOTABLE
# members only (the player and the Demon Lord are Tier 1 but never count toward
# or against this cap). A promotion that would exceed it demotes the LRU member.
TIER1_CAP = 10

# How many edges a freshly-promoted NPC gets wired into the Tier-1 social graph.
RELATIONSHIP_LINKS = 3
RELATIONSHIP_TYPES = ["friend", "rival", "business_partner", "kin", "mentor", "neighbor"]

# Fallback trauma pool if names.json predates the "traumas" key (mirrors the
# world_gen seeds), so seeding never KeyErrors on an older data file.
DEFAULT_TRAUMAS = [
    "lost family to the eastern plague",
    "survived a raid that razed their birth village",
    "betrayed by a partner and never recovered the debt",
]


def load_name_pools() -> dict[str, Any]:
    """Read the names.json trait/trauma pools (the seed source for promotion)."""
    with NAMES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
def is_social(npc: dict[str, Any]) -> bool:
    """The player and the Demon Lord stand outside the dynamic-tier system: the
    player is never demoted, the antagonist is never promoted or demoted."""
    return not npc.get("is_player") and not npc.get("is_demon_lord")


def is_promotable(npc: dict[str, Any]) -> bool:
    """A background (Tier 2/3) villager that is neither player nor Demon Lord."""
    return is_social(npc) and int(npc.get("tier", 3)) in (2, 3)


def should_promote(npc: dict[str, Any], threshold: int = PROMOTION_THRESHOLD) -> bool:
    """True when an eligible NPC has earned promotion through enough talk."""
    return is_promotable(npc) and int(npc.get("player_conversation_count", 0)) >= threshold


# --------------------------------------------------------------------------- #
# Per-conversation bookkeeping
# --------------------------------------------------------------------------- #
def record_conversation(npc: dict[str, Any], stamp: float) -> None:
    """Bump the NPC's player-conversation count and last-talked stamp in place.

    Run for every NPC the player converses with, whatever their tier: a rising
    count earns a background villager promotion, and a fresh stamp keeps an
    already-Tier-1 NPC off the LRU demotion block.
    """
    npc["player_conversation_count"] = int(npc.get("player_conversation_count", 0)) + 1
    npc["last_talked_stamp"] = float(stamp)


# --------------------------------------------------------------------------- #
# Promotion
# --------------------------------------------------------------------------- #
def seed_personhood(npc: dict[str, Any], names: dict[str, Any], rng: random.Random) -> None:
    """Seed the Tier-1 flavor fields from the names.json pools - but only where
    a field is empty, so a re-promoted (previously enriched) card keeps the
    sharper inner life the LLM already gave it."""
    if not npc.get("dark_trait"):
        npc["dark_trait"] = rng.choice(names["dark_traits"])
    if not npc.get("redeeming_quality"):
        npc["redeeming_quality"] = rng.choice(names["redeeming_qualities"])
    if not npc.get("trauma"):
        npc["trauma"] = rng.choice(names.get("traumas") or DEFAULT_TRAUMAS)


def _tier1_peers(npc: dict[str, Any], all_npcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        other
        for other in all_npcs
        if other.get("id") != npc.get("id")
        and is_social(other)
        and int(other.get("tier", 3)) == 1
    ]


def link_into_graph(
    npc: dict[str, Any],
    all_npcs: list[dict[str, Any]],
    rng: random.Random,
    max_links: int = RELATIONSHIP_LINKS,
) -> list[dict[str, Any]]:
    """Wire the newcomer into the existing Tier-1 social graph.

    Adds up to ``max_links`` reciprocal edges between the promoted NPC and random
    established Tier-1 peers it is not already linked to (the reciprocal edge lets
    the relationship-drift + rumor-propagation models see the bond from both
    ends). Mutates the chosen peers in place; returns the peer cards that gained
    an edge so the caller can persist them.
    """
    linked_ids = {rel.get("npc_id") for rel in npc.get("relationships", [])}
    candidates = [peer for peer in _tier1_peers(npc, all_npcs) if peer.get("id") not in linked_ids]
    if not candidates:
        return []
    partners = rng.sample(candidates, min(max_links, len(candidates)))
    npc_rels = npc.setdefault("relationships", [])
    changed: list[dict[str, Any]] = []
    for partner in partners:
        rel_type = rng.choice(RELATIONSHIP_TYPES)
        sentiment = rng.randint(-40, 80)
        npc_rels.append(
            {
                "npc_id": partner["id"],
                "name": partner.get("name", "Unknown"),
                "relationship_type": rel_type,
                "sentiment": sentiment,
                "notes": "",
            }
        )
        partner_rels = partner.setdefault("relationships", [])
        if not any(rel.get("npc_id") == npc["id"] for rel in partner_rels):
            partner_rels.append(
                {
                    "npc_id": npc["id"],
                    "name": npc.get("name", "Unknown"),
                    "relationship_type": rel_type,
                    "sentiment": sentiment,
                    "notes": "",
                }
            )
            changed.append(partner)
    return changed


def promote(
    npc: dict[str, Any],
    all_npcs: list[dict[str, Any]],
    names: dict[str, Any],
    rng: random.Random,
    stamp: float,
) -> list[dict[str, Any]]:
    """Flip an eligible NPC to Tier 1: seed its personhood, link the social
    graph, mark it freshly talked-to. Mutates ``npc`` and the linked peers in
    place; returns the peer cards that were changed (so the caller saves them)."""
    seed_personhood(npc, names, rng)
    partners = link_into_graph(npc, all_npcs, rng)
    npc["tier"] = 1
    npc["last_talked_stamp"] = float(stamp)
    return partners


# --------------------------------------------------------------------------- #
# Demotion (LRU)
# --------------------------------------------------------------------------- #
def select_lru_demotion(
    tier1_npcs: list[dict[str, Any]],
    protect_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Pick the least-recently-conversed-with promotable Tier 1 to demote.

    Considers only social (non-player, non-Demon-Lord) Tier-1 cards, never the
    just-promoted NPC (``protect_id``). Returns the card with the smallest
    last-talked stamp - a never-talked-to Tier 1 (stamp 0) is the first to go -
    or None when there is nothing demotable.
    """
    candidates = [
        npc
        for npc in tier1_npcs
        if is_social(npc)
        and int(npc.get("tier", 3)) == 1
        and npc.get("id") != protect_id
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda npc: float(npc.get("last_talked_stamp", 0.0)))


# --------------------------------------------------------------------------- #
# Orchestration (one entry point for the conversation flow)
# --------------------------------------------------------------------------- #
def apply_conversation_tiering(
    npc: dict[str, Any],
    all_npcs: list[dict[str, Any]],
    names: dict[str, Any],
    rng: random.Random,
    stamp: float,
    *,
    threshold: int = PROMOTION_THRESHOLD,
    cap: int = TIER1_CAP,
) -> dict[str, Any]:
    """Apply one conversation's worth of tier bookkeeping to ``npc``.

    Bumps its conversation count + last-talked stamp, then - if it has earned
    personhood - promotes it to Tier 1 and demotes the LRU Tier 1 to hold the
    cap. All mutation is in place on ``npc`` and on cards drawn from ``all_npcs``
    (which the caller fetched under its lock and will persist).

    ``all_npcs`` may contain a stale copy of ``npc``; the live ``npc`` dict is
    treated as authoritative and de-duplicated by id. Returns::

        {"changed": [cards...],   # every card to persist, ``npc`` first
         "promoted": npc|None,    # the card that became Tier 1 this turn
         "demoted": npc|None,     # the Tier 1 bumped down to hold the cap
         "enrich": npc|None}      # a promoted, not-yet-enriched card to queue

    A no-op (the player/Demon-Lord guard) returns empty fields.
    """
    empty = {"changed": [], "promoted": None, "demoted": None, "enrich": None}
    if not is_social(npc):
        return empty

    record_conversation(npc, stamp)

    # Authoritative roster: the live npc plus the fresh others (never the stale
    # duplicate of npc that all_npcs may carry).
    others = [other for other in all_npcs if other.get("id") != npc.get("id")]
    changed: list[dict[str, Any]] = [npc]
    promoted: Optional[dict[str, Any]] = None
    demoted: Optional[dict[str, Any]] = None
    enrich: Optional[dict[str, Any]] = None

    if should_promote(npc, threshold):
        was_enriched = bool(npc.get("llm_enriched"))
        changed.extend(promote(npc, others, names, rng, stamp))
        promoted = npc
        # A never-enriched promotee serves its seeded placeholders until the
        # one-off LLM pass lands; flag it for the caller to queue.
        if not was_enriched:
            enrich = npc
        # Count promotable Tier-1s over the post-promotion roster (npc is now
        # tier 1) and demote the LRU if we are over the cap.
        tier1 = [c for c in [npc, *others] if is_social(c) and int(c.get("tier", 3)) == 1]
        if len(tier1) > cap:
            demoted = select_lru_demotion(tier1, protect_id=npc.get("id"))
            if demoted is not None:
                demoted["tier"] = 2
                changed.append(demoted)

    # De-duplicate by id, keeping the first (authoritative) occurrence.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for card in changed:
        cid = str(card.get("id"))
        if cid not in seen:
            seen.add(cid)
            deduped.append(card)

    return {"changed": deduped, "promoted": promoted, "demoted": demoted, "enrich": enrich}
