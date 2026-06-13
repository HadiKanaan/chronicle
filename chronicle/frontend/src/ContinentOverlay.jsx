import { useEffect, useMemo, useRef, useState } from 'react';
import { getContinent } from './api';

// Visual-only continent map (press M). The backend generates it once; this
// component fetches it exactly once and paints colored biome/country cells,
// borders, rivers, capitals, POIs, and the "you are here" pin. Only Aldenmoor
// is deeply simulated - the continent is graphical framing.
const CELL = 9; // px per continent cell on screen
const SEA_COLOR = '#1b3a5c';

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
    const biomeColors = continent.biome_colors ?? {};
    const countryColor = new Map(continent.countries.map((c) => [c.id, c.color]));

    // Cells: sea, or biome-colored land tinted toward its country color.
    const cellAt = new Map();
    for (const cell of continent.cells) cellAt.set(`${cell.x},${cell.y}`, cell);
    for (const cell of continent.cells) {
      if (!cell.land) {
        ctx.fillStyle = SEA_COLOR;
      } else {
        ctx.fillStyle = biomeColors[cell.biome] ?? '#6a7b4a';
      }
      ctx.fillRect(cell.x * CELL, cell.y * CELL, CELL, CELL);
    }

    // Country borders: where a land cell's right/bottom neighbor differs.
    ctx.strokeStyle = 'rgba(10, 10, 14, 0.85)';
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

    // Rivers: thin blue polylines tracing downhill to the sea.
    ctx.strokeStyle = '#5aa9e6';
    ctx.lineWidth = 2;
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

    // Country capitals: a dot + the capital name.
    ctx.font = '11px sans-serif';
    ctx.textBaseline = 'middle';
    for (const country of continent.countries) {
      const cap = country.capital;
      const px = (cap.x + 0.5) * CELL;
      const py = (cap.y + 0.5) * CELL;
      ctx.fillStyle = '#fff7e0';
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#0a0a0e';
      ctx.fillText(country.name, px + 6, py + 1);
      ctx.fillStyle = '#f5e7c5';
      ctx.fillText(country.name, px + 5, py);
    }

    // POIs: small hollow markers.
    ctx.strokeStyle = '#d8c08a';
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

    // "Aldenmoor - you are here" pin.
    const pin = continent.aldenmoor;
    if (pin) {
      const px = (pin.x + 0.5) * CELL;
      const py = (pin.y + 0.5) * CELL;
      ctx.fillStyle = '#ff5252';
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = '#0a0a0e';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText(pin.label, px + 9, py + 1);
      ctx.fillStyle = '#ffd0d0';
      ctx.fillText(pin.label, px + 8, py);
    }
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
      <div style={styles.panel} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <span>The Known Continent — graphical overview (only Aldenmoor is simulated)</span>
          <button style={styles.close} onClick={onClose}>
            close (M)
          </button>
        </div>
        {error ? (
          <div style={styles.message}>The cartographer&apos;s map is unavailable.</div>
        ) : !continent ? (
          <div style={styles.message}>Unrolling the map…</div>
        ) : (
          <div style={styles.canvasWrap}>
            <canvas
              ref={canvasRef}
              style={styles.canvas}
              onMouseMove={handleMove}
              onMouseLeave={() => setHover(null)}
            />
          </div>
        )}
        {hover && hover.country ? (
          <div style={styles.tooltip}>
            <div style={styles.tipName}>{hover.country.name}</div>
            <div style={styles.tipMuted}>
              {hover.country.dominant_biome} · {hover.country.is_coastal ? 'coastal' : 'landlocked'}
            </div>
            {Object.entries(hover.country.properties ?? {}).map(([key, value]) => (
              <div key={key} style={styles.tipRow}>
                <span>{STAT_LABELS[key] ?? key}</span>
                <span>{value}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(6, 8, 12, 0.82)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 50
  },
  panel: {
    background: '#0e1118',
    border: '1px solid #2c313a',
    borderRadius: '6px',
    padding: '12px',
    maxWidth: '94vw',
    maxHeight: '94vh',
    overflow: 'auto',
    position: 'relative'
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '16px',
    marginBottom: '10px',
    color: '#d6dae1',
    fontSize: '13px'
  },
  close: {
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '4px',
    padding: '4px 10px',
    cursor: 'pointer'
  },
  canvasWrap: {
    display: 'flex',
    justifyContent: 'center'
  },
  canvas: {
    imageRendering: 'pixelated',
    maxWidth: '100%',
    maxHeight: '80vh',
    border: '1px solid #2c313a'
  },
  message: {
    color: '#9ca3af',
    padding: '40px',
    textAlign: 'center'
  },
  tooltip: {
    position: 'fixed',
    right: '28px',
    bottom: '28px',
    background: '#171b22',
    border: '1px solid #39414d',
    borderRadius: '5px',
    padding: '10px 12px',
    minWidth: '180px',
    color: '#e6e9ee',
    fontSize: '12px',
    pointerEvents: 'none'
  },
  tipName: {
    fontWeight: 'bold',
    marginBottom: '2px'
  },
  tipMuted: {
    color: '#9ca3af',
    marginBottom: '6px'
  },
  tipRow: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '14px',
    padding: '1px 0'
  }
};
