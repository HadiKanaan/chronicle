# Data Model: Living World RPG Simulation

## WorldState

- Represents the current simulation snapshot.
- Fields: region, current_day, current_hour, demon_lord_npc_id,
  player_npc_id, game_started.
- Relationships: owns the active Region and points to key NPC identities.

## Region

- Represents the single playable area.
- Fields: id, name, width, height, biome, tiles, buildings, current_weather,
  season.
- Relationships: contains the tile grid and building layout used by the render
  payload.

## Tile

- Represents one cell in the world grid.
- Fields: x, y, tile_type, passable, building_id, resource.
- Relationships: tiles belong to one Region and may reference a Building.

## Building

- Represents a named structure in the region.
- Fields: id, name, building_type, x, y, width, height, owner_npc_id.
- Relationships: may be owned by an NPC and may occupy multiple tiles.

## CharacterCard

- Represents the persistent identity of an NPC.
- Fields: id, tier, name, age, species, occupation, region_id, x, y,
  appearance, personality_traits, dark_trait, redeeming_quality, trauma,
  skills, current_mood, mood_reason, faction_affiliations, relationships,
  memory_buffer, player_sentiment, rumor_knowledge, current_behavior, path,
  home_x, home_y, work_x, work_y, is_demon_lord, is_player, sprite_id.
- Relationships: references factions, other NPCs, and the player host identity.

## NPCSkills

- Represents the skill profile used for behavior and conversations.
- Fields: combat, negotiation, perception, smithing, farming, magic, stealth,
  leadership.

## NPCRelationship

- Represents a directed relationship between two NPCs.
- Fields: npc_id, name, relationship_type, sentiment, notes.
- Relationships: belongs to a CharacterCard and can influence rumor spread and
  social behavior.

## FactionAffiliation

- Represents membership or allegiance to a faction.
- Fields: faction_id, faction_name, loyalty, role.
- Relationships: belongs to a CharacterCard.

## Faction

- Represents an organized group in the world.
- Fields: id, name, faction_type, description, color, member_npc_ids,
  player_reputation.
- Relationships: linked to NPC memberships and reputation tracking.

## FactionRelationship

- Represents how two factions feel about each other.
- Fields: faction_a_id, faction_b_id, relationship_score.

## Rumor

- Represents information that can spread, distort, and decay over time.
- Fields: id, original_event, current_text, distortion_level, known_by_npc_ids,
  propagation_rate, decay_rate, drama_score, age_days, active.
- Relationships: spreads across NPC social connections and may be influenced by
  drama score and social reach.

## RenderPayload

- Represents the browser-facing snapshot of the world.
- Fields: tiles, npcs, player, time_of_day, weather, dialogue,
  notifications, faction_reputations, current_day, current_hour, fog_map.
- Relationships: assembled from WorldState, CharacterCard, Rumor, and faction
  data, but contains only display-ready values.

## Validation Rules

- WorldState must contain exactly one active row in storage.
- NPCs are keyed by id and tier, with tier used to decide how much detail they
  receive in the simulation.
- CharacterCard memory buffers are rolling and capped to a small recent history.
- Rumors remain active until explicitly retired by the simulation.
- The render payload must never become the source of truth for any entity.