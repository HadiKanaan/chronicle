import { useEffect, useRef, useState } from 'react';
import { sendInput } from './api';
import {
  SOURCE_TILE,
  TILE_ATLAS,
  TILE_FALLBACK,
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

export default function GameCanvas({ gameState, onNpcClick }) {
  const canvasRef = useRef(null);
  const imagesRef = useRef({});
  const [imagesReady, setImagesReady] = useState(false);

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

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    if (canvas.width !== CANVAS_W) canvas.width = CANVAS_W;
    if (canvas.height !== CANVAS_H) canvas.height = CANVAS_H;
    ctx.imageSmoothingEnabled = false;

    const images = imagesRef.current;
    const tiles = gameState.tiles ?? [];

    ctx.fillStyle = '#10131a';
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

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

    // Center the camera on the player (or the world center before one exists).
    const focus = gameState.player ?? { x: cols / 2, y: rows / 2 };
    const focusX = (focus.x + 0.5) * DISPLAY_TILE;
    const focusY = (focus.y + 0.5) * DISPLAY_TILE;
    const camX = cameraOrigin(focusX, worldW, CANVAS_W);
    const camY = cameraOrigin(focusY, worldH, CANVAS_H);

    // tile_type lookup by coordinate (tiles arrive as a flat list).
    const tileMap = new Map();
    for (const tile of tiles) {
      tileMap.set(`${tile.x},${tile.y}`, tile.tile_type);
    }

    // Only draw the tiles inside the viewport (plus a one-tile margin).
    const startCol = Math.max(0, Math.floor(camX / DISPLAY_TILE));
    const startRow = Math.max(0, Math.floor(camY / DISPLAY_TILE));
    const endCol = Math.min(cols - 1, startCol + VIEW_COLS);
    const endRow = Math.min(rows - 1, startRow + VIEW_ROWS);

    for (let ty = startRow; ty <= endRow; ty += 1) {
      for (let tx = startCol; tx <= endCol; tx += 1) {
        const type = tileMap.get(`${tx},${ty}`);
        if (type === undefined) continue;
        const screenX = Math.round(tx * DISPLAY_TILE - camX);
        const screenY = Math.round(ty * DISPLAY_TILE - camY);
        drawTile(ctx, images, type, screenX, screenY);
      }
    }

    // Characters: draw back-to-front so nearer ones overlap farther ones.
    const characters = [...(gameState.npcs ?? [])];
    if (gameState.player) {
      characters.push({ ...gameState.player, isPlayer: true });
    }
    characters.sort((a, b) => a.y - b.y);
    for (const character of characters) {
      drawCharacter(ctx, images, character, camX, camY);
    }

    // Day/night wash over the whole scene.
    const tint = DAY_NIGHT_TINT[gameState.time_of_day];
    if (tint) {
      ctx.fillStyle = tint;
      ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    }
  }, [gameState, imagesReady]);

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
    const tiles = gameState.tiles ?? [];
    if (tiles.length === 0) return;

    const { cols, rows } = worldTileExtent(tiles);
    const focus = gameState.player ?? { x: cols / 2, y: rows / 2 };
    const camX = cameraOrigin((focus.x + 0.5) * DISPLAY_TILE, cols * DISPLAY_TILE, CANVAS_W);
    const camY = cameraOrigin((focus.y + 0.5) * DISPLAY_TILE, rows * DISPLAY_TILE, CANVAS_H);

    // Map the displayed (CSS-scaled) click back into world tile coordinates.
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const worldX = ((event.clientX - rect.left) * scaleX + camX) / DISPLAY_TILE;
    const worldY = ((event.clientY - rect.top) * scaleY + camY) / DISPLAY_TILE;

    let nearest = null;
    let nearestDist = Infinity;
    for (const npc of gameState.npcs ?? []) {
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

function drawCharacter(ctx, images, character, camX, camY) {
  const entry = CHARACTER_ATLAS[character.sprite_id] ?? CHARACTER_FALLBACK;
  // Tile center on screen, and the bottom of the tile (where feet rest).
  const centerX = (character.x + 0.5) * DISPLAY_TILE - camX;
  const feetY = (character.y + 1) * DISPLAY_TILE - camY;

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
