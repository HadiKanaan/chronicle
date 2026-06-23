import { useEffect, useRef, useState } from 'react';
import { COLORS, FONTS, plate, plateHeading } from './theme';

// Day 10 village minimap (Part E). A tiny pixel-crisp canvas that downscales the
// region into one cell per tile, honouring fog-of-war, and overlays building
// blips, the player as a bright pulsing dot, and the current camera viewport
// rectangle. Everything is derived from EXISTING payload data (tiles, buildings,
// paths, player, fog_map) — no new backend field. Redrawn on a throttled rAF
// (~12fps) reading the latest payload from a ref, so it animates the player
// pulse without thrashing React or coupling to the world's 60fps draw loop.

// Matches GameCanvas DISPLAY_TILE so the viewport rectangle lines up with what
// the camera actually shows.
const DISPLAY_TILE = 32;
const MAX_PX = 168; // largest minimap edge on screen (before integer scaling)
const REDRAW_MS = 80;

// tile_type -> minimap cell colour. Muted so building/player blips read on top.
const TILE_COLORS = {
  grass: '#3c5a31',
  dirt: '#6a5436',
  stone_path: '#867a57',
  water: '#2c577a',
  building_floor: '#5a4d3a',
  building_wall: '#39301f',
};

function cameraOrigin(focusPx, worldPx, viewPx) {
  if (worldPx <= viewPx) return (worldPx - viewPx) / 2;
  return Math.max(0, Math.min(focusPx - viewPx / 2, worldPx - viewPx));
}

// Prettify a building_type slug for the hover label ("magistrate_hall" → "Magistrate Hall").
function prettyType(type) {
  return (type || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function Minimap({ gameState }) {
  const canvasRef = useRef(null);
  const stateRef = useRef(gameState);
  stateRef.current = gameState;
  // Live cell size / grid extent, written each draw, read by the hover handler.
  const dimsRef = useRef({ cell: 1, cols: 0, rows: 0 });
  const [hover, setHover] = useState(null); // { label, x, y } in client coords

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    let running = true;
    let lastDraw = 0;

    const draw = (now) => {
      const gs = stateRef.current;
      const tiles = gs.tiles ?? [];
      if (tiles.length === 0) return;

      // World dimensions from the tile extent.
      let cols = 0;
      let rows = 0;
      for (const t of tiles) {
        if (t.x + 1 > cols) cols = t.x + 1;
        if (t.y + 1 > rows) rows = t.y + 1;
      }
      if (cols === 0 || rows === 0) return;

      // Integer cell size keeps the minimap pixel-crisp (no fractional cells).
      const cell = Math.max(1, Math.floor(MAX_PX / Math.max(cols, rows)));
      const w = cols * cell;
      const h = rows * cell;
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      dimsRef.current = { cell, cols, rows };
      ctx.imageSmoothingEnabled = false;

      // Fog lookup: tiles in fog_map are 'explored' (dim) or 'unexplored'
      // (hidden); tiles absent from it are currently visible (bright).
      const fog = new Map();
      for (const f of gs.fog_map ?? []) fog.set(`${f.x},${f.y}`, f.fog_tier);

      ctx.fillStyle = '#070a0e';
      ctx.fillRect(0, 0, w, h);

      // Base terrain, dimmed/hidden per fog.
      for (const t of tiles) {
        const tier = fog.get(`${t.x},${t.y}`);
        if (tier === 'unexplored') continue; // leave it as the dark backing
        const base = TILE_COLORS[t.tile_type] ?? '#3c5a31';
        ctx.globalAlpha = tier === 'explored' ? 0.5 : 1;
        ctx.fillStyle = base;
        ctx.fillRect(t.x * cell, t.y * cell, cell, cell);
      }
      ctx.globalAlpha = 1;

      // Paths over terrain (only where not hidden).
      ctx.fillStyle = '#a8935f';
      for (const p of gs.paths ?? []) {
        if (fog.get(`${p.x},${p.y}`) === 'unexplored') continue;
        ctx.fillRect(p.x * cell, p.y * cell, cell, cell);
      }

      // Building footprints as gold blips (skip fully-hidden ones).
      for (const b of gs.buildings ?? []) {
        const bw = b.width ?? 1;
        const bh = b.height ?? 1;
        if (fog.get(`${b.x},${b.y}`) === 'unexplored') continue;
        ctx.fillStyle = COLORS.gold;
        ctx.fillRect(b.x * cell, b.y * cell, Math.max(cell, bw * cell), Math.max(cell, bh * cell));
        ctx.fillStyle = 'rgba(0,0,0,0.35)';
        ctx.fillRect(b.x * cell, b.y * cell, Math.max(cell, bw * cell), 1);
      }

      // Current camera viewport rectangle (parchment outline). Derived from the
      // live window size the same way GameCanvas clamps its camera.
      const player = gs.player;
      if (player) {
        const viewW = window.innerWidth;
        const viewH = window.innerHeight;
        const camX = cameraOrigin((player.x + 0.5) * DISPLAY_TILE, cols * DISPLAY_TILE, viewW);
        const camY = cameraOrigin((player.y + 0.5) * DISPLAY_TILE, rows * DISPLAY_TILE, viewH);
        const rx = (camX / DISPLAY_TILE) * cell;
        const ry = (camY / DISPLAY_TILE) * cell;
        const rw = Math.min(w - rx, (viewW / DISPLAY_TILE) * cell);
        const rh = Math.min(h - ry, (viewH / DISPLAY_TILE) * cell);
        ctx.strokeStyle = 'rgba(236, 227, 207, 0.7)';
        ctx.lineWidth = 1;
        ctx.strokeRect(Math.round(rx) + 0.5, Math.round(ry) + 0.5, Math.round(rw), Math.round(rh));

        // Player blip: a bright pulsing dot on top of everything.
        const pulse = 0.55 + 0.45 * (0.5 + 0.5 * Math.sin(now / 360));
        const px = (player.x + 0.5) * cell;
        const py = (player.y + 0.5) * cell;
        const r = Math.max(2, cell * 0.9);
        ctx.fillStyle = `rgba(255, 224, 120, ${0.25 * pulse})`;
        ctx.beginPath();
        ctx.arc(px, py, r * 1.8, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = `rgba(255, 236, 170, ${0.85 + 0.15 * pulse})`;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const frame = (now) => {
      if (!running) return;
      if (now - lastDraw >= REDRAW_MS) {
        lastDraw = now;
        draw(now);
      }
      requestAnimationFrame(frame);
    };
    const handle = requestAnimationFrame(frame);
    return () => {
      running = false;
      cancelAnimationFrame(handle);
    };
  }, []);

  // Map the cursor to a tile cell and find the building under it (if any) so the
  // village landmarks are identifiable from the minimap.
  const handleMove = (event) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { cell } = dimsRef.current;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const cx = Math.floor(((event.clientX - rect.left) * scaleX) / cell);
    const cy = Math.floor(((event.clientY - rect.top) * scaleY) / cell);
    const fog = new Map();
    for (const f of stateRef.current.fog_map ?? []) fog.set(`${f.x},${f.y}`, f.fog_tier);
    const found = (stateRef.current.buildings ?? []).find((b) => {
      const bw = b.width ?? 1;
      const bh = b.height ?? 1;
      return cx >= b.x && cx < b.x + bw && cy >= b.y && cy < b.y + bh
        && fog.get(`${b.x},${b.y}`) !== 'unexplored'; // don't reveal hidden ones
    });
    if (found) setHover({ label: prettyType(found.building_type), x: event.clientX, y: event.clientY });
    else setHover(null);
  };

  return (
    <section className="cv-plate cv-slide-up" style={{ ...plate, ...styles.panel }}>
      <h2 style={{ ...plateHeading, ...styles.heading }}>Aldenmoor</h2>
      <div style={styles.canvasWrap}>
        <canvas
          ref={canvasRef}
          className="cv-pixel"
          style={styles.canvas}
          aria-label="Village minimap"
          onMouseMove={handleMove}
          onMouseLeave={() => setHover(null)}
        />
      </div>
      {hover ? (
        <div className="cv-plate" style={{ ...plate, ...styles.tooltip, left: hover.x + 12, top: hover.y - 28 }}>
          {hover.label}
        </div>
      ) : null}
    </section>
  );
}

const styles = {
  panel: {
    padding: '8px 8px 9px',
  },
  heading: {
    fontSize: '10px',
    marginBottom: '6px',
    textAlign: 'center',
  },
  canvasWrap: {
    display: 'flex',
    justifyContent: 'center',
  },
  canvas: {
    display: 'block',
    width: 'auto',
    height: 'auto',
    maxWidth: `${MAX_PX}px`,
    border: `1px solid ${COLORS.frameDark}`,
    background: '#070a0e',
    fontFamily: FONTS.body,
  },
  tooltip: {
    position: 'fixed',
    padding: '4px 9px',
    fontSize: '11px',
    fontFamily: FONTS.body,
    color: COLORS.cream,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
    zIndex: 30,
  },
};
