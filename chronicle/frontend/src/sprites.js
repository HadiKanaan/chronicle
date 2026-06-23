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
  // River body: a textured solid-water cell from the Pixel Crawler water
  // tileset; GameCanvas layers a slow shimmer over it and shades the banks
  // where it meets land.
  water: { src: '/assets/tiles/water_pc.png', sx: 16, sy: 192 },
};

export const TILE_FALLBACK = { color: '#5c8c48' };

// Fallback solid-dirt tile (kenney) for any road piece that fails to load.
export const PATH_TILE = { src: '/assets/tiles/kenney_rts.png', sx: 320, sy: 64, size: 64 };

// Winding dirt-road autotile (Fan-tasy Tileset_Road, 16px cells). Indexed by a
// 4-bit connection mask of which orthogonal neighbours are also road
// (N=1, E=2, S=4, W=8); the value is the source cell offset. Built from the
// tileset's 4x4 connection block (cols 0-3, rows 0-3).
export const ROAD_TILES = { src: '/assets/tiles/road_tiles.png', size: 16 };
export const ROAD_ATLAS = [
  { sx: 0, sy: 48 },  // 0  none
  { sx: 0, sy: 32 },  // 1  N
  { sx: 16, sy: 48 }, // 2  E
  { sx: 16, sy: 32 }, // 3  NE
  { sx: 0, sy: 0 },   // 4  S
  { sx: 0, sy: 16 },  // 5  NS
  { sx: 16, sy: 0 },  // 6  ES
  { sx: 16, sy: 16 }, // 7  NES
  { sx: 48, sy: 48 }, // 8  W
  { sx: 48, sy: 32 }, // 9  NW
  { sx: 32, sy: 48 }, // 10 EW
  { sx: 32, sy: 32 }, // 11 NEW
  { sx: 48, sy: 0 },  // 12 SW
  { sx: 48, sy: 16 }, // 13 NSW
  { sx: 32, sy: 0 },  // 14 ESW
  { sx: 32, sy: 16 }, // 15 NESW
];

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

// prop_type -> a Fan-tasy town-dressing sprite, with how tall it should draw (in
// tiles); width follows each trimmed sprite's own aspect. Anchored at the tile
// base, beneath characters, like decorations.
export const PROP_ATLAS = {
  lamp: { src: '/assets/props/lamp.png', tilesTall: 1.7 },
  well: { src: '/assets/props/well.png', tilesTall: 1.5 },
  sign: { src: '/assets/props/sign.png', tilesTall: 0.9 },
  barrel: { src: '/assets/props/barrel.png', tilesTall: 0.85 },
  haystack: { src: '/assets/props/haystack.png', tilesTall: 0.95 },
  crate: { src: '/assets/props/crate.png', tilesTall: 0.9 },
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

// Per-character RECOLOR tints. Applied as a MULTIPLY pass over the sprite,
// preserving its shading, and masked to the sprite's own opaque pixels - so they
// recolor robes/armour instead of washing them out. Strong enough to read as
// different people from one base sheet: a green vs blue wizard, a black knight, an
// earthy herbalist. Alpha = recolor strength per colour.
const TINT = {
  none: null,
  blue: 'rgba(70, 120, 210, 0.60)',
  green: 'rgba(60, 150, 80, 0.60)',
  crimson: 'rgba(185, 60, 60, 0.58)',
  purple: 'rgba(145, 90, 190, 0.58)',
  gold: 'rgba(200, 160, 60, 0.52)',
  teal: 'rgba(55, 165, 175, 0.58)',
  orange: 'rgba(200, 115, 50, 0.58)',
  black: 'rgba(40, 42, 58, 0.66)',
  earthy: 'rgba(120, 120, 80, 0.55)',
  brown: 'rgba(120, 80, 50, 0.60)',
  cream: 'rgba(214, 198, 150, 0.45)',
};

// Per-occupation tint families: the hue set an NPC of that role draws from (chosen
// stably by an id hash). Layers occupation-readable colour on top of the
// occupation->sprite mapping the backend already applies, so the shared
// wizard/knight/rogue sheets read as many distinct people - e.g. a herbalist in
// earthy greens vs a priest in pale gold, both on the wizard sheet.
const OCC_TINT_FAMILY = {
  herbalist: ['green', 'earthy', 'teal'],
  priest: ['cream', 'gold', 'purple'],
  guard: ['blue', 'black', 'teal'],
  guard_captain: ['black', 'crimson', 'blue'],
  magistrate: ['purple', 'gold', 'crimson'],
  merchant: ['crimson', 'orange', 'gold'],
  trader: ['orange', 'teal', 'green'],
  tavern_keeper: ['brown', 'crimson', 'gold'],
  courier: ['teal', 'green', 'blue'],
};

// Everyone else (including the base villager): a broad spread, with a share left
// natural so a crowd of one sheet still reads as many different folk.
const DEFAULT_TINT_FAMILY = [
  'none', 'blue', 'green', 'crimson', 'purple', 'gold', 'teal', 'orange', 'brown', 'earthy', 'none',
];

function _hashId(id) {
  const s = String(id ?? '');
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) & 0x7fffffff;
  return h;
}

// Stable recolor tint for a character from its occupation + id. Returns an rgba
// string to multiply over the sprite, or null for "natural". Used by both the
// world renderer and the dialogue/acquaintance portraits so they always match.
export function characterTint(occupation, id) {
  const family = OCC_TINT_FAMILY[occupation] ?? DEFAULT_TINT_FAMILY;
  const key = family[_hashId(id) % family.length];
  return TINT[key] ?? null;
}

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
  for (const entry of Object.values(PROP_ATLAS)) {
    if (entry.src) sources.add(entry.src);
  }
  if (DOOR_SPRITE.src) sources.add(DOOR_SPRITE.src);
  if (PATH_TILE.src) sources.add(PATH_TILE.src);
  if (ROAD_TILES.src) sources.add(ROAD_TILES.src);
  return [...sources];
}
