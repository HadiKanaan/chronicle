import { useEffect, useRef, useState } from 'react';
import { sendInput } from './api';
import {
  SOURCE_TILE,
  TILE_ATLAS,
  TILE_FALLBACK,
  PATH_TILE,
  BUILDING_ATLAS,
  DOOR_SPRITE,
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

// Per-entity glide durations. The player snaps quickly so input feels direct;
// simulated NPCs step one tile/second on the backend, so a ~1s glide makes a
// walking villager flow continuously tile-to-tile instead of step-pausing.
const PLAYER_LERP_MS = 110;
const NPC_LERP_MS = 950;
// After the player stops driving, reconcile the predicted position back to the
// backend's authoritative tile (covers any dropped move intent).
const RECONCILE_IDLE_MS = 400;

const MOVE_DELTAS = {
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0],
};

// Mirror of the backend's tile.passable for the tiles we draw: only water and
// building walls block. Used purely to validate optimistic player moves so a
// prediction can never disagree with what the backend will accept.
function passableType(type) {
  return type !== undefined && type !== 'water' && type !== 'building_wall';
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

// Decoration on-screen size, in tiles tall, with width derived from each
// (trimmed) sprite's own aspect so nothing is squashed. Trees stand well above
// their tile so the town reads with depth.
const DECORATION_TILES_TALL = { tree: 1.9, bush: 0.85, rock: 0.8 };

export default function GameCanvas({ gameState, onNpcClick }) {
  const canvasRef = useRef(null);
  const imagesRef = useRef({});
  const [imagesReady, setImagesReady] = useState(false);
  // Latest payload + derived lookups, read by the animation loop and the
  // keyboard handler without re-subscribing them every poll.
  const gameStateRef = useRef(gameState);
  const tileMapRef = useRef(new Map()); // "x,y" -> tile_type
  const fogMapRef = useRef(new Map()); // "x,y" -> fog_tier
  const dimsRef = useRef({ cols: VIEW_COLS, rows: VIEW_ROWS });
  // Per-character interpolation: id -> {fromX,fromY,toX,toY,t0,x,y,dur,isPlayer}.
  const posRef = useRef(new Map());
  // Optimistic player tile: where we've told the player they are, ahead of the
  // next poll. Reconciled against the authoritative position once idle.
  const predictRef = useRef(null);
  const lastMoveAtRef = useRef(0);

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

  // On each poll: refresh derived lookups and retarget every character's glide.
  // NPCs ease toward their new authoritative tile; the player keeps its
  // optimistic target unless the backend has caught up or the player went idle.
  useEffect(() => {
    gameStateRef.current = gameState;
    const now = performance.now();
    const positions = posRef.current;

    const tiles = gameState.tiles ?? [];
    const tileMap = new Map();
    let cols = 0;
    let rows = 0;
    for (const tile of tiles) {
      tileMap.set(`${tile.x},${tile.y}`, tile.tile_type);
      if (tile.x + 1 > cols) cols = tile.x + 1;
      if (tile.y + 1 > rows) rows = tile.y + 1;
    }
    tileMapRef.current = tileMap;
    dimsRef.current = { cols: cols || VIEW_COLS, rows: rows || VIEW_ROWS };
    const fogMap = new Map();
    for (const cell of gameState.fog_map ?? []) {
      fogMap.set(`${cell.x},${cell.y}`, cell.fog_tier);
    }
    fogMapRef.current = fogMap;

    const retarget = (id, tx, ty, dur, isPlayer) => {
      const prev = positions.get(id);
      if (!prev) {
        positions.set(id, { fromX: tx, fromY: ty, toX: tx, toY: ty, t0: now, x: tx, y: ty, dur, isPlayer });
      } else if (prev.toX !== tx || prev.toY !== ty) {
        positions.set(id, { fromX: prev.x, fromY: prev.y, toX: tx, toY: ty, t0: now, x: prev.x, y: prev.y, dur, isPlayer });
      } else {
        prev.dur = dur;
        prev.isPlayer = isPlayer;
      }
    };

    const seen = new Set();
    for (const npc of gameState.npcs ?? []) {
      const id = characterId(npc);
      if (id === undefined) continue;
      seen.add(id);
      retarget(id, npc.x, npc.y, NPC_LERP_MS, false);
    }

    const player = gameState.player;
    if (player) {
      const id = player.npc_id;
      seen.add(id);
      const auth = { x: player.x, y: player.y };
      const pred = predictRef.current;
      if (!pred || (pred.x === auth.x && pred.y === auth.y)) {
        predictRef.current = auth; // in sync
        retarget(id, auth.x, auth.y, PLAYER_LERP_MS, true);
      } else if (now - lastMoveAtRef.current > RECONCILE_IDLE_MS) {
        predictRef.current = auth; // player idle: trust the backend again
        retarget(id, auth.x, auth.y, PLAYER_LERP_MS, true);
      } else if (!positions.has(id)) {
        positions.set(id, { fromX: pred.x, fromY: pred.y, toX: pred.x, toY: pred.y, t0: now, x: pred.x, y: pred.y, dur: PLAYER_LERP_MS, isPlayer: true });
      }
    }

    for (const id of [...positions.keys()]) {
      if (!seen.has(id)) positions.delete(id);
    }
  }, [gameState]);

  // Single animation loop: advances each glide by its own duration, animates
  // water/weather, redraws. Runs continuously for smooth motion + effects.
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
        const dur = entry.dur || NPC_LERP_MS;
        const t = Math.min(1, (now - entry.t0) / dur);
        entry.x = entry.fromX + (entry.toX - entry.fromX) * t;
        entry.y = entry.fromY + (entry.toY - entry.fromY) * t;
      }
      drawScene(
        ctx, imagesRef.current, gameStateRef.current, positions,
        tileMapRef.current, fogMapRef.current, dimsRef.current, now,
      );
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
      // Debug demo toggle: 'r' reveals the whole map (fog on/off) backend-side.
      if (event.key === 'r' || event.key === 'R') {
        event.preventDefault();
        sendInput({ type: 'toggle_reveal', payload: {} }).catch(() => {});
        return;
      }
      const directionMap = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' };
      const direction = directionMap[event.key];
      if (!direction) return;
      event.preventDefault();

      // Optimistic move: glide the player immediately toward the next tile if it
      // is passable (same rule the backend uses), then post the intent. The
      // backend stays authoritative; the next poll reconciles. This removes the
      // up-to-one-poll input lag that made stepping feel rigid.
      const player = gameStateRef.current?.player;
      if (player) {
        const base = predictRef.current ?? { x: player.x, y: player.y };
        const [dx, dy] = MOVE_DELTAS[direction];
        const nx = base.x + dx;
        const ny = base.y + dy;
        const { cols, rows } = dimsRef.current;
        const inBounds = nx >= 0 && ny >= 0 && nx < cols && ny < rows;
        if (inBounds && passableType(tileMapRef.current.get(`${nx},${ny}`))) {
          predictRef.current = { x: nx, y: ny };
          lastMoveAtRef.current = performance.now();
          const id = player.npc_id;
          const e = posRef.current.get(id);
          const fromX = e ? e.x : base.x;
          const fromY = e ? e.y : base.y;
          posRef.current.set(id, {
            fromX, fromY, toX: nx, toY: ny, t0: performance.now(), x: fromX, y: fromY,
            dur: PLAYER_LERP_MS, isPlayer: true,
          });
        }
      }
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

    const { cols, rows } = dimsRef.current;
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

// Clamp the camera so it follows the focus point but never scrolls past the
// world edges. If the world is smaller than the viewport, it is centered.
function cameraOrigin(focusPx, worldPx, viewPx) {
  if (worldPx <= viewPx) {
    return (worldPx - viewPx) / 2;
  }
  return Math.max(0, Math.min(focusPx - viewPx / 2, worldPx - viewPx));
}

function drawScene(ctx, images, gameState, positions, tileMap, fogMap, dims, now) {
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = '#10131a';
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  if ((gameState.tiles ?? []).length === 0) {
    ctx.fillStyle = '#f5f5f5';
    ctx.font = '20px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('World not generated', CANVAS_W / 2, CANVAS_H / 2);
    return;
  }

  const { cols, rows } = dims;
  const worldW = cols * DISPLAY_TILE;
  const worldH = rows * DISPLAY_TILE;

  // Camera follows the player's interpolated position so the scroll is as
  // smooth as the glide (falls back to the raw tile, then world center).
  const playerId = gameState.player?.npc_id;
  const playerPos = playerId !== undefined ? positions.get(playerId) : undefined;
  const focus = playerPos ?? gameState.player ?? { x: cols / 2, y: rows / 2 };
  const camX = cameraOrigin((focus.x + 0.5) * DISPLAY_TILE, worldW, CANVAS_W);
  const camY = cameraOrigin((focus.y + 0.5) * DISPLAY_TILE, worldH, CANVAS_H);

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
        ctx.fillStyle = `rgba(120, 196, 226, ${0.10 + 0.12 * (0.5 + 0.5 * phase)})`;
        ctx.fillRect(screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
      }
    }
  }

  // Road network (static), drawn over the base ground and under everything
  // else. The full tile set is collected first so decorations yield to roads
  // (no tree sitting in the middle of a path).
  const pathImg = images[PATH_TILE.src];
  const pathSet = new Set();
  for (const road of gameState.paths ?? []) {
    pathSet.add(`${road.x},${road.y}`);
    if (road.x < startCol - 1 || road.x > endCol + 1 || road.y < startRow - 1 || road.y > endRow + 1) continue;
    if (!pathImg) continue;
    const screenX = Math.round(road.x * DISPLAY_TILE - camX);
    const screenY = Math.round(road.y * DISPLAY_TILE - camY);
    ctx.drawImage(pathImg, PATH_TILE.sx, PATH_TILE.sy, PATH_TILE.size, PATH_TILE.size, screenX, screenY, DISPLAY_TILE, DISPLAY_TILE);
  }

  // Decoration scatter (static, beneath characters), aspect-correct + sized up.
  for (const dec of gameState.decorations ?? []) {
    if (pathSet.has(`${dec.x},${dec.y}`)) continue; // roads take precedence
    if (dec.x < startCol - 1 || dec.x > endCol + 1 || dec.y < startRow - 1 || dec.y > endRow + 1) {
      continue;
    }
    drawDecoration(ctx, images, dec, camX, camY);
  }

  // Depth-sorted world layer: NPCs and buildings interleave by their base row
  // so a villager standing inside a building is hidden by its roof from the
  // outside, while one in front of it draws over it. Buildings sort half a tile
  // below their footprint bottom so an NPC on the entrance/wall row counts as
  // "inside" (occluded) and one a tile south counts as "in front" (on top).
  // NPCs on a fogged tile are hidden (fog test uses the authoritative tile).
  // The player is NOT in this layer - it is drawn last so it stays visible;
  // entering a building fades that roof so the player and any NPCs inside show
  // through. The "reveal interiors" toggle fades every roof at once.
  const pTile = playerPos
    ? { x: Math.round(playerPos.x), y: Math.round(playerPos.y) }
    : (gameState.player ? { x: Math.round(gameState.player.x), y: Math.round(gameState.player.y) } : null);
  const reveal = Boolean(gameState.revealInteriors);

  const worldItems = [];
  for (const npc of gameState.npcs ?? []) {
    if (fogMap.has(`${Math.round(npc.x)},${Math.round(npc.y)}`)) continue;
    const pos = positions.get(characterId(npc));
    const drawX = pos ? pos.x : npc.x;
    const drawY = pos ? pos.y : npc.y;
    worldItems.push({ sortY: drawY + 1, kind: 'npc', npc, drawX, drawY });
  }
  for (const building of gameState.buildings ?? []) {
    const bw = building.width ?? 1;
    const bh = building.height ?? 1;
    if (building.x > endCol + 1 || building.x + bw < startCol - 1 || building.y > endRow + 1 || building.y + bh < startRow - 1) {
      continue;
    }
    const inside = pTile
      && pTile.x >= building.x && pTile.x <= building.x + bw - 1
      && pTile.y >= building.y && pTile.y <= building.y + bh - 1;
    const alpha = (inside || reveal) ? 0.18 : 1;
    worldItems.push({ sortY: building.y + bh + 0.5, kind: 'building', building, alpha });
  }
  worldItems.sort((a, b) => a.sortY - b.sortY);
  for (const item of worldItems) {
    if (item.kind === 'npc') {
      drawCharacter(ctx, images, item.npc, item.drawX, item.drawY, camX, camY);
    } else {
      drawBuilding(ctx, images, item.building, camX, camY, item.alpha);
      drawDoor(ctx, images, item.building, camX, camY, item.alpha);
    }
  }

  // Player drawn last so it is never hidden behind a roof; the inside-fade above
  // is what reveals it (and fellow occupants) once you step in.
  if (gameState.player) {
    const pos = positions.get(gameState.player.npc_id);
    const drawX = pos ? pos.x : gameState.player.x;
    const drawY = pos ? pos.y : gameState.player.y;
    drawCharacter(ctx, images, { ...gameState.player, isPlayer: true }, drawX, drawY, camX, camY);
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

function drawBuilding(ctx, images, building, camX, camY, alpha = 1) {
  const entry = BUILDING_ATLAS[building.building_type];
  const image = entry ? images[entry.src] : undefined;
  if (!image) return; // wall/floor tiles remain the fallback
  // The sprite is pre-trimmed to its art, so filling the footprint reads as the
  // building sitting on its plot (no transparent padding, no neighbor spill).
  const drawW = building.width * DISPLAY_TILE;
  const drawH = building.height * DISPLAY_TILE;
  const screenX = Math.round(building.x * DISPLAY_TILE - camX);
  const screenY = Math.round(building.y * DISPLAY_TILE - camY);
  if (alpha !== 1) ctx.globalAlpha = alpha;
  ctx.drawImage(image, screenX, screenY, drawW, drawH);
  if (alpha !== 1) ctx.globalAlpha = 1;
}

function drawDoor(ctx, images, building, camX, camY, alpha = 1) {
  const image = images[DOOR_SPRITE.src];
  if (!image) return;
  // Backend surfaces the entrance tile; fall back to bottom-centre if absent.
  const doorX = building.door_x ?? building.x + Math.floor(building.width / 2);
  const doorY = building.door_y ?? building.y + building.height - 1;
  const drawH = DISPLAY_TILE * 1.1;
  const aspect = image.naturalWidth / image.naturalHeight || 0.6;
  const drawW = drawH * aspect;
  const centerX = (doorX + 0.5) * DISPLAY_TILE - camX;
  const feetY = (doorY + 1) * DISPLAY_TILE - camY;
  if (alpha !== 1) ctx.globalAlpha = alpha;
  ctx.drawImage(image, Math.round(centerX - drawW / 2), Math.round(feetY - drawH), drawW, drawH);
  if (alpha !== 1) ctx.globalAlpha = 1;
}

function drawDecoration(ctx, images, dec, camX, camY) {
  const entry = DECORATION_ATLAS[dec.decoration_type];
  const image = entry ? images[entry.src] : undefined;
  if (!image) return;
  // Preserve the trimmed sprite's aspect; size by a per-type target height so
  // trees read tall and rocks stay low. Anchored at the tile base, centered.
  const tilesTall = DECORATION_TILES_TALL[dec.decoration_type] ?? 1.0;
  const drawH = tilesTall * DISPLAY_TILE;
  const aspect = image.naturalWidth / image.naturalHeight || 1;
  const drawW = drawH * aspect;
  const centerX = (dec.x + 0.5) * DISPLAY_TILE - camX;
  const feetY = (dec.y + 1) * DISPLAY_TILE - camY;
  ctx.drawImage(image, Math.round(centerX - drawW / 2), Math.round(feetY - drawH), drawW, drawH);
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
