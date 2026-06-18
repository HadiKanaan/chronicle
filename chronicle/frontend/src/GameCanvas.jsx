import { useEffect, useRef, useState } from 'react';
import { sendInput } from './api';
import {
  SOURCE_TILE,
  TILE_ATLAS,
  TILE_FALLBACK,
  BUILDING_ATLAS,
  DECORATION_ATLAS,
  CHARACTER_ATLAS,
  CHARACTER_FALLBACK,
  DAY_NIGHT_TINT,
  allImageSources,
} from './sprites';

const SCALE = 2;
const DISPLAY_TILE = SOURCE_TILE * SCALE; // 32px tiles on screen
// Viewport measured in tiles. The camera follows the player across the (larger)
// world, so this stays fixed regardless of region size.
const VIEW_COLS = 25;
const VIEW_ROWS = 19;
const CANVAS_W = VIEW_COLS * DISPLAY_TILE;
const CANVAS_H = VIEW_ROWS * DISPLAY_TILE;

// NPCs glide toward their authoritative tile over roughly one poll interval, so
// stepping reads as walking. Backend stays the source of truth for position;
// this only governs how the drawn dot catches up to it.
const LERP_MS = 500;

// Pixel extent of the world, derived from the tiles the backend sent.
function worldTileExtent(tiles) {
  let cols = 0;
  let rows = 0;
  for (const tile of tiles) {
    if (tile.x + 1 > cols) cols = tile.x + 1;
    if (tile.y + 1 > rows) rows = tile.y + 1;
  }
  return { cols: cols || VIEW_COLS, rows: rows || VIEW_ROWS };
}

// Clamp the camera so it follows the focus point but never scrolls past the
// world edges. If the world is smaller than the viewport, it is centered.
function cameraOrigin(focusPx, worldPx, viewPx) {
  if (worldPx <= viewPx) {
    return (worldPx - viewPx) / 2;
  }
  return Math.max(0, Math.min(focusPx - viewPx / 2, worldPx - viewPx));
}

const characterId = (c) => c.id ?? c.npc_id;

// Deterministic rain streaks, precomputed once so the storm/rain overlay never
// flickers frame-to-frame (no Math.random in the draw loop).
function makeStreaks(count) {
  let seed = 0x1a2b3c;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  const streaks = [];
  for (let i = 0; i < count; i += 1) {
    streaks.push({
      x: rnd() * CANVAS_W,
      y: rnd() * CANVAS_H,
      len: 9 + rnd() * 13,
      speed: 240 + rnd() * 220,
      drift: 0.22 + rnd() * 0.16,
    });
  }
  return streaks;
}
const RAIN_STREAKS = makeStreaks(150);

export default function GameCanvas({ gameState, onNpcClick }) {
  const canvasRef = useRef(null);
  const imagesRef = useRef({});
  const [imagesReady, setImagesReady] = useState(false);
  // Latest payload, read by the animation loop without re-subscribing it.
  const gameStateRef = useRef(gameState);
  // Per-character interpolation state: id -> {fromX,fromY,toX,toY,t0,x,y}.
  const posRef = useRef(new Map());

  // Preload every atlas image once. A redraw is triggered via imagesReady.
  useEffect(() => {
    let cancelled = false;
    const sources = allImageSources();
    let remaining = sources.length;
    if (remaining === 0) {
      setImagesReady(true);
      return undefined;
    }
    for (const src of sources) {
      const image = new Image();
      image.onload = () => {
        if (cancelled) return;
        imagesRef.current[src] = image;
        remaining -= 1;
        if (remaining === 0) setImagesReady(true);
      };
      image.onerror = () => {
        if (cancelled) return;
        remaining -= 1;
        if (remaining === 0) setImagesReady(true);
      };
      image.src = src;
    }
    return () => {
      cancelled = true;
    };
  }, []);

  // On each poll, refresh the latest state and retarget the glide for every
  // character: it starts from where it is currently drawn and eases to the new
  // authoritative tile. New NPCs snap into place; departed NPCs are dropped.
  useEffect(() => {
    gameStateRef.current = gameState;
    const now = performance.now();
    const positions = posRef.current;
    const seen = new Set();

    const characters = [...(gameState.npcs ?? [])];
    if (gameState.player) {
      characters.push({ ...gameState.player, id: gameState.player.npc_id });
    }
    for (const character of characters) {
      const id = characterId(character);
      if (id === undefined) continue;
      seen.add(id);
      const tx = character.x;
      const ty = character.y;
      const prev = positions.get(id);
      if (!prev) {
        positions.set(id, { fromX: tx, fromY: ty, toX: tx, toY: ty, t0: now, x: tx, y: ty });
      } else if (prev.toX !== tx || prev.toY !== ty) {
        positions.set(id, { fromX: prev.x, fromY: prev.y, toX: tx, toY: ty, t0: now, x: prev.x, y: prev.y });
      }
    }
    for (const id of [...positions.keys()]) {
      if (!seen.has(id)) positions.delete(id);
    }
  }, [gameState]);

  // Single animation loop: advances the glide, animates water/weather, redraws.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;
    if (canvas.width !== CANVAS_W) canvas.width = CANVAS_W;
    if (canvas.height !== CANVAS_H) canvas.height = CANVAS_H;

    let running = true;
    const frame = (now) => {
      if (!running) return;
      const positions = posRef.current;
      for (const entry of positions.values()) {
        const t = Math.min(1, (now - entry.t0) / LERP_MS);
        entry.x = entry.fromX + (entry.toX - entry.fromX) * t;
        entry.y = entry.fromY + (entry.toY - entry.fromY) * t;
      }
      drawScene(ctx, imagesRef.current, gameStateRef.current, positions, now);
      requestAnimationFrame(frame);
    };
    const handle = requestAnimationFrame(frame);
    return () => {
      running = false;
      cancelAnimationFrame(handle);
    };
  }, [imagesReady]);

  useEffect(() => {
    const onKeyDown = (event) => {
      // Arrow keys steer the player, not the dialogue input's cursor.
      const tag = event.target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      const directionMap = {
        ArrowUp: 'up',
        ArrowDown: 'down',
        ArrowLeft: 'left',
        ArrowRight: 'right',
      };
      // Debug demo toggle: 'r' reveals the whole map (fog on/off) backend-side.
      if (event.key === 'r' || event.key === 'R') {
        event.preventDefault();
        sendInput({ type: 'toggle_reveal', payload: {} }).catch(() => {});
        return;
      }
      const direction = directionMap[event.key];
      if (!direction) return;
      event.preventDefault();
      sendInput({ type: 'move', payload: { direction } }).catch(() => {});
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleClick = (event) => {
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const gs = gameStateRef.current;
    const tiles = gs.tiles ?? [];
    if (tiles.length === 0) return;

    const { cols, rows } = worldTileExtent(tiles);
    const focus = gs.player ?? { x: cols / 2, y: rows / 2 };
    const camX = cameraOrigin((focus.x + 0.5) * DISPLAY_TILE, cols * DISPLAY_TILE, CANVAS_W);
    const camY = cameraOrigin((focus.y + 0.5) * DISPLAY_TILE, rows * DISPLAY_TILE, CANVAS_H);

    // Map the displayed (CSS-scaled) click back into world tile coordinates.
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const worldX = ((event.clientX - rect.left) * scaleX + camX) / DISPLAY_TILE;
    const worldY = ((event.clientY - rect.top) * scaleY + camY) / DISPLAY_TILE;

    let nearest = null;
    let nearestDist = Infinity;
    for (const npc of gs.npcs ?? []) {
      const dist = Math.hypot(worldX - (npc.x + 0.5), worldY - (npc.y + 0.5));
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = npc;
      }
    }
    if (nearest && nearestDist <= 1.0 && onNpcClick) {
      onNpcClick(nearest);
    }
  };

  return (
    <canvas
      ref={canvasRef}
      onClick={handleClick}
      style={styles.canvas}
      aria-label="Game world canvas"
    />
  );
}

function drawScene(ctx, images, gameState, positions, now) {
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = '#10131a';
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  const tiles = gameState.tiles ?? [];
  if (tiles.length === 0) {
    ctx.fillStyle = '#f5f5f5';
    ctx.font = '20px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('World not generated', CANVAS_W / 2, CANVAS_H / 2);
    return;
  }

  const { cols, rows } = worldTileExtent(tiles);
  const worldW = cols * DISPLAY_TILE;
  const worldH = rows * DISPLAY_TILE;

  // Camera follows the player's *interpolated* position so the scroll is as
  // smooth as the NPC glide (falls back to the raw tile, then world center).
  const playerId = gameState.player?.npc_id;
  const playerPos = playerId !== undefined ? positions.get(playerId) : undefined;
  const focus = playerPos ?? gameState.player ?? { x: cols / 2, y: rows / 2 };
  const focusX = (focus.x + 0.5) * DISPLAY_TILE;
  const focusY = (focus.y + 0.5) * DISPLAY_TILE;
  const camX = cameraOrigin(focusX, worldW, CANVAS_W);
  const camY = cameraOrigin(focusY, worldH, CANVAS_H);

  // tile_type lookup by coordinate (tiles arrive as a flat list).
  const tileMap = new Map();
  for (const tile of tiles) {
    tileMap.set(`${tile.x},${tile.y}`, tile.tile_type);
  }

  // Fog of war: the backend is authoritative. fog_map lists only non-visible
  // tiles ('explored' = dimmed, 'unexplored' = black); any tile absent from it
  // is fully visible. The frontend just paints what it is told.
  const fogMap = new Map();
  for (const cell of gameState.fog_map ?? []) {
    fogMap.set(`${cell.x},${cell.y}`, cell.fog_tier);
  }

  const startCol = Math.max(0, Math.floor(camX / DISPLAY_TILE));
  const startRow = Math.max(0, Math.floor(camY / DISPLAY_TILE));
  const endCol = Math.min(cols - 1, startCol + VIEW_COLS);
  const endRow = Math.min(rows - 1, startRow + VIEW_ROWS);

  // Terrain. Water tiles get a slow shimmer cycle layered on the sprite.
  for (let ty = startRow; ty <= endRow; ty += 1) {
    for (let tx = startCol; tx <= endCol; tx += 1) {
      const type = tileMap.get(`${tx},${ty}`);
      if (type === undefined) continue;
      const screenX = Math.round(tx * DISPLAY_TILE - camX);
      const screenY = Math.round(ty * DISPLAY_TILE - camY);
      drawTile(ctx, images, type, screenX, screenY);
      if (type === 'water') {
        const phase = Math.sin(now / 900 + tx * 0.6 + ty * 0.9);
        ctx.fillStyle = `rgba(96, 174, 214, ${0.08 + 0.09 * (0.5 + 0.5 * phase)})`;
        ctx.fillRect(screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
      }
    }
  }

  // Decoration scatter (static, beneath characters). Trees rise a little above
  // their tile so the town reads with depth.
  for (const dec of gameState.decorations ?? []) {
    if (dec.x < startCol - 1 || dec.x > endCol + 1 || dec.y < startRow - 1 || dec.y > endRow + 1) {
      continue;
    }
    drawDecoration(ctx, images, dec, camX, camY);
  }

  // Building sprites blitted over their footprint, above tiles, beneath
  // characters. The wall/floor tiles already drawn remain the fallback.
  for (const building of gameState.buildings ?? []) {
    const bx = building.x;
    const by = building.y;
    const bw = building.width ?? 1;
    const bh = building.height ?? 1;
    if (bx > endCol + 1 || bx + bw < startCol - 1 || by > endRow + 1 || by + bh < startRow - 1) {
      continue;
    }
    drawBuilding(ctx, images, building, camX, camY);
  }

  // Characters: back-to-front so nearer ones overlap farther ones. NPCs on a
  // fogged tile are hidden (fog test uses the authoritative tile); the player
  // host is always drawn. Drawing uses the interpolated position.
  const characters = (gameState.npcs ?? []).filter(
    (npc) => !fogMap.has(`${Math.round(npc.x)},${Math.round(npc.y)}`)
  );
  if (gameState.player) {
    characters.push({ ...gameState.player, id: gameState.player.npc_id, isPlayer: true });
  }
  characters.sort((a, b) => a.y - b.y);
  for (const character of characters) {
    const pos = positions.get(characterId(character));
    const drawX = pos ? pos.x : character.x;
    const drawY = pos ? pos.y : character.y;
    drawCharacter(ctx, images, character, drawX, drawY, camX, camY);
  }

  // Fog overlays painted on top: explored tiles get a dim wash, unexplored go
  // solid black. Drawn after the world so fog also dims buildings + characters.
  if (fogMap.size > 0) {
    for (let ty = startRow; ty <= endRow; ty += 1) {
      for (let tx = startCol; tx <= endCol; tx += 1) {
        const tier = fogMap.get(`${tx},${ty}`);
        if (!tier) continue;
        const screenX = Math.round(tx * DISPLAY_TILE - camX);
        const screenY = Math.round(ty * DISPLAY_TILE - camY);
        ctx.fillStyle = tier === 'unexplored' ? '#05070b' : 'rgba(5, 7, 11, 0.55)';
        ctx.fillRect(screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
      }
    }
  }

  // Day/night wash, then the weather overlay on top of everything.
  const tint = DAY_NIGHT_TINT[gameState.time_of_day];
  if (tint) {
    ctx.fillStyle = tint;
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  }
  drawWeather(ctx, gameState.weather, now);
}

function drawTile(ctx, images, type, screenX, screenY) {
  const entry = TILE_ATLAS[type] ?? TILE_FALLBACK;
  if (entry.color) {
    ctx.fillStyle = entry.color;
    ctx.fillRect(screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
    return;
  }
  const image = images[entry.src];
  if (!image) {
    ctx.fillStyle = TILE_FALLBACK.color;
    ctx.fillRect(screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
    return;
  }
  ctx.drawImage(
    image,
    entry.sx, entry.sy, SOURCE_TILE, SOURCE_TILE,
    screenX, screenY, DISPLAY_TILE, DISPLAY_TILE,
  );
  if (entry.shade) {
    ctx.fillStyle = `rgba(0, 0, 0, ${entry.shade})`;
    ctx.fillRect(screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
  }
}

function drawBuilding(ctx, images, building, camX, camY) {
  const entry = BUILDING_ATLAS[building.building_type];
  const image = entry ? images[entry.src] : undefined;
  if (!image) return; // wall/floor tiles remain the fallback
  const drawW = building.width * DISPLAY_TILE;
  const drawH = building.height * DISPLAY_TILE;
  const screenX = Math.round(building.x * DISPLAY_TILE - camX);
  const screenY = Math.round(building.y * DISPLAY_TILE - camY);
  ctx.drawImage(image, screenX, screenY, drawW, drawH);
}

function drawDecoration(ctx, images, dec, camX, camY) {
  const entry = DECORATION_ATLAS[dec.decoration_type];
  const image = entry ? images[entry.src] : undefined;
  if (!image) return;
  // Anchor to the tile base; trees stand a touch taller than their tile.
  const drawW = DISPLAY_TILE;
  const drawH = DISPLAY_TILE * (dec.decoration_type === 'tree' ? 1.2 : 1.0);
  const screenX = Math.round(dec.x * DISPLAY_TILE - camX);
  const feetY = (dec.y + 1) * DISPLAY_TILE - camY;
  ctx.drawImage(image, screenX, Math.round(feetY - drawH), drawW, drawH);
}

function drawCharacter(ctx, images, character, worldX, worldY, camX, camY) {
  const entry = CHARACTER_ATLAS[character.sprite_id] ?? CHARACTER_FALLBACK;
  // Tile center on screen, and the bottom of the tile (where feet rest).
  const centerX = (worldX + 0.5) * DISPLAY_TILE - camX;
  const feetY = (worldY + 1) * DISPLAY_TILE - camY;

  if (character.isPlayer) {
    // A soft ring under the player so the inherited host identity is findable.
    ctx.fillStyle = 'rgba(255, 224, 120, 0.45)';
    ctx.beginPath();
    ctx.ellipse(centerX, feetY - DISPLAY_TILE * 0.12, DISPLAY_TILE * 0.5, DISPLAY_TILE * 0.22, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  const image = images[entry.src];
  if (!image) {
    ctx.fillStyle = character.isPlayer ? '#f76c6c' : '#f4d35e';
    ctx.fillRect(centerX - DISPLAY_TILE * 0.3, feetY - DISPLAY_TILE * 0.8, DISPLAY_TILE * 0.6, DISPLAY_TILE * 0.8);
    return;
  }
  const drawW = entry.fw * entry.scale;
  const drawH = entry.fh * entry.scale;
  ctx.drawImage(
    image,
    entry.sx, entry.sy, entry.fw, entry.fh,
    Math.round(centerX - drawW / 2), Math.round(feetY - drawH),
    drawW, drawH,
  );
}

// Cheap canvas weather, layered over the day/night tint. No assets: rain and
// storm are animated streaks; fog is a drifting grey wash; storm also darkens
// the scene and adds a few bright flecks. 'clear' draws nothing.
function drawWeather(ctx, weather, now) {
  if (weather === 'rain' || weather === 'storm') {
    const storm = weather === 'storm';
    if (storm) {
      ctx.fillStyle = 'rgba(12, 16, 30, 0.34)';
      ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    }
    ctx.strokeStyle = storm ? 'rgba(176, 196, 222, 0.55)' : 'rgba(168, 192, 214, 0.40)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    const t = now / 1000;
    for (const streak of RAIN_STREAKS) {
      const speed = storm ? streak.speed * 1.5 : streak.speed;
      const y = (streak.y + t * speed) % CANVAS_H;
      const x = (streak.x + t * speed * streak.drift) % CANVAS_W;
      ctx.moveTo(x, y);
      ctx.lineTo(x - streak.len * streak.drift, y + streak.len);
    }
    ctx.stroke();
    if (storm) {
      // Sparse wind-blown flecks for extra texture.
      ctx.fillStyle = 'rgba(210, 220, 235, 0.5)';
      for (let i = 0; i < RAIN_STREAKS.length; i += 6) {
        const s = RAIN_STREAKS[i];
        const y = (s.y * 1.7 + t * s.speed * 1.8) % CANVAS_H;
        const x = (s.x * 1.3 + t * s.speed) % CANVAS_W;
        ctx.fillRect(x, y, 2, 2);
      }
    }
    return;
  }
  if (weather === 'fog') {
    // A pale wash plus two slowly drifting bands for a soft rolling-fog feel.
    const drift = (Math.sin(now / 4000) + 1) * 0.5;
    ctx.fillStyle = 'rgba(204, 209, 217, 0.16)';
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    ctx.fillStyle = 'rgba(214, 219, 226, 0.12)';
    ctx.fillRect(0, CANVAS_H * (0.15 + drift * 0.1), CANVAS_W, CANVAS_H * 0.3);
    ctx.fillRect(0, CANVAS_H * (0.55 - drift * 0.1), CANVAS_W, CANVAS_H * 0.3);
  }
}

const styles = {
  canvas: {
    width: 'auto',
    height: 'auto',
    maxWidth: '100%',
    maxHeight: '88vh',
    border: '1px solid #2c313a',
    background: '#10131a',
    display: 'block',
    margin: '0 auto',
    imageRendering: 'pixelated',
  },
};
