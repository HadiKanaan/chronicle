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
  water: { src: '/assets/tiles/water.png', sx: 96, sy: 128 },
};

export const TILE_FALLBACK = { color: '#5c8c48' };

// sprite_id -> first idle frame of a Pixel Crawler character sheet. `scale`
// normalizes the differing frame paddings so every character lands at roughly
// one-and-a-half tiles tall on screen.
export const CHARACTER_ATLAS = {
  human_base: { src: '/assets/characters/human_base.png', sx: 0, sy: 0, fw: 64, fh: 64, scale: 1.5 },
  npc_knight: { src: '/assets/characters/knight.png', sx: 0, sy: 0, fw: 32, fh: 32, scale: 1.7 },
  npc_rogue: { src: '/assets/characters/rogue.png', sx: 0, sy: 0, fw: 32, fh: 32, scale: 1.7 },
  npc_wizard: { src: '/assets/characters/wizard.png', sx: 0, sy: 0, fw: 32, fh: 32, scale: 1.7 },
};

export const CHARACTER_FALLBACK = CHARACTER_ATLAS.human_base;

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
  return [...sources];
}
