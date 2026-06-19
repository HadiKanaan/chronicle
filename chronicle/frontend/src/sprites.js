// Static sprite atlas. The backend decides WHAT exists (tile_type, sprite_id);
// the frontend only knows how to draw it. This file is the single place that
// touches asset layout, so the renderer stays a dumb blitter.

// Source cell size (px) of the terrain tilesets at the CHRONICLE asset root.
export const SOURCE_TILE = 16;

// tile_type -> one solid 16x16 cell of a tile sheet, picked by scanning the
// sheets for fully-opaque cells (textured interiors preferred over flat fills).
// Terrain comes from the Fan-tasy tileset; building walls/floors come from the
// Pixel Crawler structures kit. `shade` optionally darkens a cell on draw.
export const TILE_ATLAS = {
  grass: { src: '/assets/tiles/ground.png', sx: 32, sy: 16 },
  dirt: { src: '/assets/tiles/ground.png', sx: 176, sy: 112 },
  stone_path: { src: '/assets/tiles/road.png', sx: 16, sy: 128 },
  building_floor: { src: '/assets/tiles/floors.png', sx: 16, sy: 16 },
  building_wall: { src: '/assets/tiles/walls.png', sx: 192, sy: 192 },
  // Open-water cell (no shoreline sand), picked by scanning the Fan-tasy water
  // sheet for a fully-opaque, sand-free, lightly-rippled tile; the river layers
  // a slow shimmer over this in GameCanvas.
  water: { src: '/assets/tiles/water.png', sx: 304, sy: 128 },
};

export const TILE_FALLBACK = { color: '#5c8c48' };

// Dirt road tile from the kenney medieval-RTS spritesheet (the solid-dirt cell
// at 320,64 in the 550x550 sheet, 64px source). Drawn on each generated path
// tile to lay roads between buildings. `size` is the source cell size (64), not
// the 16px Fan-tasy terrain tiles.
export const PATH_TILE = { src: '/assets/tiles/kenney_rts.png', sx: 320, sy: 64, size: 64 };

// building_type -> a front-view structure sprite blitted over the footprint,
// above the wall/floor tiles (the fallback when a sprite is missing). Detailed
// Fan-tasy houses/tavern/smithy; kenney civic landmarks for their distinct
// silhouettes. `house` is an array of variants picked per-building so the
// residential blocks aren't identical.
export const BUILDING_ATLAS = {
  tavern: { src: '/assets/buildings/tavern.png' },
  blacksmith: { src: '/assets/buildings/blacksmith.png' },
  market: { src: '/assets/buildings/market.png' },
  church: { src: '/assets/buildings/church.png' },
  magistrate_hall: { src: '/assets/buildings/magistrate_hall.png' },
  house: [
    { src: '/assets/buildings/house_1.png' },
    { src: '/assets/buildings/house_2.png' },
  ],
};

// A wooden door drawn over each building's entrance tile so the (walkable) gap
// in the wall reads as a doorway. Fades out with the building when the player
// is inside.
export const DOOR_SPRITE = { src: '/assets/buildings/door.png' };

// decoration_type -> a single environment prop sprite. Drawn one-per-tile,
// anchored to the tile's base, beneath characters.
export const DECORATION_ATLAS = {
  tree: { src: '/assets/decorations/tree.png' },
  bush: { src: '/assets/decorations/bush.png' },
  rock: { src: '/assets/decorations/rock.png' },
};

// sprite_id -> a Pixel Crawler 6-frame walk/run sheet (uniform 384x64 = six
// 64px cells). The renderer cycles frames while a character is moving and shows
// frame 0 when idle. `scale` lands each character at ~1.5 tiles tall.
export const CHARACTER_ATLAS = {
  human_base: { src: '/assets/characters/human_base.png', fw: 64, fh: 64, frames: 6, scale: 1.5 },
  npc_knight: { src: '/assets/characters/knight.png', fw: 64, fh: 64, frames: 6, scale: 1.5 },
  npc_rogue: { src: '/assets/characters/rogue.png', fw: 64, fh: 64, frames: 6, scale: 1.5 },
  npc_wizard: { src: '/assets/characters/wizard.png', fw: 64, fh: 64, frames: 6, scale: 1.5 },
};

export const CHARACTER_FALLBACK = CHARACTER_ATLAS.human_base;

// Per-NPC clothing tints (a translucent colour cast applied over the sprite, not
// the player). Index 0 is "no tint" so a share of villagers stay natural; the
// rest spread across muted hues so a crowd of the same base sprite reads as many
// different people. Kept low-alpha so skin doesn't look painted.
export const CHARACTER_TINTS = [
  null,
  'rgba(80, 130, 200, 0.30)',   // blue
  'rgba(70, 150, 90, 0.30)',    // green
  'rgba(170, 70, 80, 0.30)',    // red
  'rgba(150, 100, 180, 0.30)',  // purple
  'rgba(190, 150, 60, 0.30)',   // gold
  'rgba(70, 160, 170, 0.30)',   // teal
  'rgba(190, 110, 60, 0.30)',   // orange
];

// Full-canvas color wash per time_of_day. `null` means draw nothing (full day).
export const DAY_NIGHT_TINT = {
  dawn: 'rgba(255, 158, 92, 0.20)',
  morning: null,
  afternoon: null,
  dusk: 'rgba(247, 120, 58, 0.24)',
  night: 'rgba(18, 28, 78, 0.46)',
};

// Every distinct image the atlases reference, for preloading.
export function allImageSources() {
  const sources = new Set();
  for (const entry of Object.values(TILE_ATLAS)) {
    if (entry.src) sources.add(entry.src);
  }
  for (const entry of Object.values(CHARACTER_ATLAS)) {
    if (entry.src) sources.add(entry.src);
  }
  for (const entry of Object.values(BUILDING_ATLAS)) {
    for (const variant of Array.isArray(entry) ? entry : [entry]) {
      if (variant.src) sources.add(variant.src);
    }
  }
  for (const entry of Object.values(DECORATION_ATLAS)) {
    if (entry.src) sources.add(entry.src);
  }
  if (DOOR_SPRITE.src) sources.add(DOOR_SPRITE.src);
  if (PATH_TILE.src) sources.add(PATH_TILE.src);
  return [...sources];
}
