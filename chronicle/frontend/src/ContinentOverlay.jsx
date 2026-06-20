import { useEffect, useMemo, useRef, useState } from 'react';
import { getContinent } from './api';
import { COLORS, FONTS, plate, plateHeading } from './theme';

// Visual-only continent map (press M), reskinned for the Day 10 AA art direction
// as an aged atlas. The backend generates it once; this component fetches it
// exactly once and paints it: deep sea with coastal shallows + a coastline for
// depth, country biomes under a warm parchment wash, ink borders, rivers, gold
// capitals/POIs, a compass rose, and an ember "you are here" pin. Only Aldenmoor
// is deeply simulated — the continent is graphical framing.
const CELL = 11; // px per continent cell on screen (integer → pixel-crisp)

// Layered sea: deep water, then two shallower rings hugging the coast so the
// landmasses read with depth instead of a flat blue field.
const SEA_DEEP = '#15303f';
const SEA_MID = '#1b3d50';
const SEA_SHALLOW = '#26566c';
const COAST_LINE = 'rgba(18, 26, 22, 0.55)';

const STAT_LABELS = {
  naval_power: 'Naval',
  timber: 'Timber',
  agriculture: 'Agriculture',
  mineral_wealth: 'Minerals',
  military: 'Military',
  population: 'Population'
};

export default function ContinentOverlay({ onClose }) {
  const canvasRef = useRef(null);
  const [continent, setContinent] = useState(null);
  const [error, setError] = useState(false);
  const [hover, setHover] = useState(null);

  // Fetch ONCE on mount (never polled).
  useEffect(() => {
    let cancelled = false;
    getContinent()
      .then((data) => {
        if (!cancelled) setContinent(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Lookup of cell -> country id for hover tooltips.
  const countryAt = useMemo(() => {
    const map = new Map();
    if (continent) {
      for (const cell of continent.cells) {
        if (cell.country !== null && cell.country !== undefined) {
          map.set(`${cell.x},${cell.y}`, cell.country);
        }
      }
    }
    return map;
  }, [continent]);

  const countriesById = useMemo(() => {
    const map = new Map();
    if (continent) {
      for (const c of continent.countries) map.set(c.id, c);
    }
    return map;
  }, [continent]);

  // Biomes present, for the legend.
  const biomeLegend = useMemo(() => {
    if (!continent) return [];
    const colors = continent.biome_colors ?? {};
    const seen = new Set();
    for (const cell of continent.cells) {
      if (cell.land && cell.biome) seen.add(cell.biome);
    }
    return [...seen].sort().map((b) => [b, colors[b] ?? '#6a7b4a']);
  }, [continent]);

  useEffect(() => {
    if (!continent) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = continent.width * CELL;
    const H = continent.height * CELL;
    if (canvas.width !== W) canvas.width = W;
    if (canvas.height !== H) canvas.height = H;
    ctx.imageSmoothingEnabled = false;
    const biomeColors = continent.biome_colors ?? {};

    const cellAt = new Map();
    for (const cell of continent.cells) cellAt.set(`${cell.x},${cell.y}`, cell);
    const isLand = (x, y) => Boolean(cellAt.get(`${x},${y}`)?.land);

    // Distance (Chebyshev, capped at 2) from each sea cell to the nearest land,
    // for the coastal-shallows rings. Cheap one-pass over the small grid.
    const shallowOf = (x, y) => {
      for (let r = 1; r <= 2; r += 1) {
        for (let dy = -r; dy <= r; dy += 1) {
          for (let dx = -r; dx <= r; dx += 1) {
            if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
            if (isLand(x + dx, y + dy)) return r;
          }
        }
      }
      return 0;
    };

    // Sea + land base fill.
    for (const cell of continent.cells) {
      if (!cell.land) {
        const ring = shallowOf(cell.x, cell.y);
        ctx.fillStyle = ring === 1 ? SEA_SHALLOW : ring === 2 ? SEA_MID : SEA_DEEP;
      } else {
        ctx.fillStyle = biomeColors[cell.biome] ?? '#6a7b4a';
      }
      ctx.fillRect(cell.x * CELL, cell.y * CELL, CELL, CELL);
    }

    // Warm parchment wash over the whole map to age it and unify the palette.
    ctx.fillStyle = 'rgba(198, 168, 112, 0.10)';
    ctx.fillRect(0, 0, W, H);

    // Crisp coastline: a dark edge on every land side that meets the sea.
    ctx.fillStyle = COAST_LINE;
    const t = Math.max(1, Math.round(CELL * 0.16));
    for (const cell of continent.cells) {
      if (!cell.land) continue;
      const x = cell.x * CELL;
      const y = cell.y * CELL;
      if (!isLand(cell.x, cell.y - 1)) ctx.fillRect(x, y, CELL, t);
      if (!isLand(cell.x, cell.y + 1)) ctx.fillRect(x, y + CELL - t, CELL, t);
      if (!isLand(cell.x - 1, cell.y)) ctx.fillRect(x, y, t, CELL);
      if (!isLand(cell.x + 1, cell.y)) ctx.fillRect(x + CELL - t, y, t, CELL);
    }

    // Country borders: soft ink where a land cell's right/bottom neighbor is a
    // different country.
    ctx.strokeStyle = 'rgba(36, 26, 16, 0.75)';
    ctx.lineWidth = 1.5;
    for (const cell of continent.cells) {
      if (!cell.land) continue;
      const right = cellAt.get(`${cell.x + 1},${cell.y}`);
      const down = cellAt.get(`${cell.x},${cell.y + 1}`);
      if (right && right.land && right.country !== cell.country) {
        ctx.beginPath();
        ctx.moveTo((cell.x + 1) * CELL, cell.y * CELL);
        ctx.lineTo((cell.x + 1) * CELL, (cell.y + 1) * CELL);
        ctx.stroke();
      }
      if (down && down.land && down.country !== cell.country) {
        ctx.beginPath();
        ctx.moveTo(cell.x * CELL, (cell.y + 1) * CELL);
        ctx.lineTo((cell.x + 1) * CELL, (cell.y + 1) * CELL);
        ctx.stroke();
      }
    }

    // Rivers: muted blue polylines tracing downhill to the sea.
    ctx.strokeStyle = 'rgba(96, 168, 210, 0.85)';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    for (const river of continent.rivers ?? []) {
      ctx.beginPath();
      river.forEach(([x, y], i) => {
        const px = (x + 0.5) * CELL;
        const py = (y + 0.5) * CELL;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();
    }

    // POIs: small gold hollow diamonds.
    ctx.strokeStyle = COLORS.gold;
    ctx.lineWidth = 1.5;
    for (const poi of continent.pois ?? []) {
      const px = (poi.x + 0.5) * CELL;
      const py = (poi.y + 0.5) * CELL;
      ctx.beginPath();
      ctx.moveTo(px - 3, py);
      ctx.lineTo(px, py - 3);
      ctx.lineTo(px + 3, py);
      ctx.lineTo(px, py + 3);
      ctx.closePath();
      ctx.stroke();
    }

    // Country capitals: a gold star-dot + the capital name with a dark plate.
    ctx.font = '11px "Courier New", monospace';
    ctx.textBaseline = 'middle';
    for (const country of continent.countries) {
      const cap = country.capital;
      const px = (cap.x + 0.5) * CELL;
      const py = (cap.y + 0.5) * CELL;
      ctx.fillStyle = '#1a130a';
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = COLORS.goldBright;
      ctx.beginPath();
      ctx.arc(px, py, 2.4, 0, Math.PI * 2);
      ctx.fill();
      // Label with a 1px dark outline so it reads over any biome.
      ctx.fillStyle = 'rgba(12, 10, 6, 0.85)';
      ctx.fillText(country.name, px + 7, py + 1);
      ctx.fillStyle = '#f3e6c4';
      ctx.fillText(country.name, px + 6, py);
    }

    // "Aldenmoor — you are here": an ember pin, the one warm beacon on the map.
    const pin = continent.aldenmoor;
    if (pin) {
      const px = (pin.x + 0.5) * CELL;
      const py = (pin.y + 0.5) * CELL;
      ctx.fillStyle = 'rgba(210, 86, 60, 0.25)';
      ctx.beginPath();
      ctx.arc(px, py, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = COLORS.ember;
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#f3e6c4';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.font = 'bold 12px "Courier New", monospace';
      ctx.fillStyle = 'rgba(12, 10, 6, 0.85)';
      ctx.fillText(pin.label, px + 11, py + 1);
      ctx.fillStyle = '#ffd9c8';
      ctx.fillText(pin.label, px + 10, py);
    }

    // Compass rose, top-right corner of the parchment.
    drawCompass(ctx, W - 30, 30, 16);
  }, [continent]);

  const handleMove = (event) => {
    if (!continent) return;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const cx = Math.floor(((event.clientX - rect.left) * scaleX) / CELL);
    const cy = Math.floor(((event.clientY - rect.top) * scaleY) / CELL);
    const id = countryAt.get(`${cx},${cy}`);
    if (id === undefined) {
      setHover(null);
      return;
    }
    setHover({ country: countriesById.get(id), x: event.clientX, y: event.clientY });
  };

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div
        className="cv-plate cv-slide-up"
        style={{ ...plate, ...styles.panel }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={styles.header}>
          <div>
            <div style={plateHeading}>The Known Continent</div>
            <div style={styles.subtitle}>a cartographer&apos;s sketch · only Aldenmoor is truly simulated</div>
          </div>
          <button className="cv-btn" style={styles.close} onClick={onClose}>
            close (M)
          </button>
        </div>
        {error ? (
          <div style={styles.message}>The cartographer&apos;s map is unavailable.</div>
        ) : !continent ? (
          <div style={styles.message}>Unrolling the map…</div>
        ) : (
          <>
            <div style={styles.canvasFrame}>
              <canvas
                ref={canvasRef}
                className="cv-pixel"
                style={styles.canvas}
                onMouseMove={handleMove}
                onMouseLeave={() => setHover(null)}
              />
              <div style={styles.mapVignette} />
            </div>
            {biomeLegend.length > 0 ? (
              <div style={styles.legend}>
                {biomeLegend.map(([name, color]) => (
                  <span key={name} style={styles.legendItem}>
                    <span style={{ ...styles.swatch, background: color }} />
                    {name.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            ) : null}
          </>
        )}
        {hover && hover.country ? (
          <div className="cv-plate" style={{ ...plate, ...styles.tooltip }}>
            <div style={styles.tipName}>{hover.country.name}</div>
            <div style={styles.tipMuted}>
              {hover.country.dominant_biome?.replace(/_/g, ' ')} ·{' '}
              {hover.country.is_coastal ? 'coastal' : 'landlocked'}
            </div>
            {Object.entries(hover.country.properties ?? {}).map(([key, value]) => (
              <div key={key} style={styles.tipRow}>
                <span style={styles.tipKey}>{STAT_LABELS[key] ?? key}</span>
                <span style={styles.tipVal}>{value}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// A small parchment compass rose: a ringed N-pointer in the corner of the map.
function drawCompass(ctx, cx, cy, r) {
  ctx.save();
  ctx.strokeStyle = 'rgba(201, 162, 75, 0.85)';
  ctx.fillStyle = 'rgba(11, 14, 18, 0.45)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  // N/S/E/W spokes.
  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx, cy + r);
  ctx.moveTo(cx - r, cy);
  ctx.lineTo(cx + r, cy);
  ctx.stroke();
  // North needle (gold diamond pointing up).
  ctx.fillStyle = COLORS.goldBright;
  ctx.beginPath();
  ctx.moveTo(cx, cy - r + 1);
  ctx.lineTo(cx - 3, cy);
  ctx.lineTo(cx, cy + 3);
  ctx.lineTo(cx + 3, cy);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = '#f3e6c4';
  ctx.font = 'bold 9px "Courier New", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('N', cx, cy - r - 5);
  ctx.restore();
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(6, 8, 12, 0.84)',
    backdropFilter: 'blur(2px)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 60
  },
  panel: {
    padding: '16px 18px',
    maxWidth: '94vw',
    maxHeight: '94vh',
    overflow: 'auto',
    position: 'relative'
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '16px',
    marginBottom: '12px'
  },
  subtitle: {
    marginTop: '4px',
    color: COLORS.creamDim,
    fontSize: '11px',
    fontStyle: 'italic',
    fontFamily: FONTS.body
  },
  close: { fontSize: '12px', padding: '5px 12px' },
  canvasFrame: {
    position: 'relative',
    display: 'inline-block',
    border: `2px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 0 0 2px ${COLORS.frameGold}, 0 6px 20px rgba(0,0,0,0.5)`,
    background: SEA_DEEP,
    lineHeight: 0
  },
  canvas: {
    display: 'block',
    maxWidth: '100%',
    maxHeight: '78vh',
    imageRendering: 'pixelated'
  },
  // Aged edges over the map without touching the pixels themselves.
  mapVignette: {
    position: 'absolute',
    inset: 0,
    pointerEvents: 'none',
    boxShadow: 'inset 0 0 60px 12px rgba(20, 12, 4, 0.45)'
  },
  legend: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px 14px',
    marginTop: '10px',
    fontFamily: FONTS.body,
    fontSize: '11px',
    color: COLORS.creamDim
  },
  legendItem: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '5px',
    textTransform: 'capitalize'
  },
  swatch: {
    width: '11px',
    height: '11px',
    borderRadius: '2px',
    border: '1px solid rgba(0,0,0,0.4)'
  },
  message: {
    color: COLORS.creamDim,
    padding: '40px',
    textAlign: 'center',
    fontFamily: FONTS.body
  },
  tooltip: {
    position: 'fixed',
    right: '28px',
    bottom: '28px',
    padding: '10px 12px',
    minWidth: '184px',
    fontSize: '12px',
    fontFamily: FONTS.body,
    pointerEvents: 'none'
  },
  tipName: {
    fontFamily: FONTS.display,
    fontSize: '12px',
    color: COLORS.goldBright,
    marginBottom: '3px'
  },
  tipMuted: {
    color: COLORS.creamDim,
    marginBottom: '6px',
    textTransform: 'capitalize'
  },
  tipRow: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '14px',
    padding: '1px 0'
  },
  tipKey: { color: COLORS.creamDim },
  tipVal: { color: COLORS.cream, fontVariantNumeric: 'tabular-nums' }
};
