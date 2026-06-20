import { useEffect, useRef } from 'react';
import { CHARACTER_ATLAS, CHARACTER_FALLBACK, CHARACTER_TINTS } from './sprites';
import { COLORS, FONTS, plate, plateHeading } from './theme';

// Day 10 Acquaintances plate (Part D). Display-only: it renders the backend's
// `recent_contacts` projection (the last ~5 NPCs the player has spoken to),
// already display-ready and DL/player-filtered backend-side. No new gameplay,
// no intents — just a mirror of payload state. Each row shows the NPC's idle
// sprite as a small tinted portrait, name, occupation, mood, disposition toward
// the player, and how many times you've spoken.

// Stable per-id tint choice (0 = no tint), mirroring the world renderer so an
// acquaintance's portrait matches how they look in the world.
function tintIndexFor(id) {
  if (id == null) return 0;
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) & 0x7fffffff;
  return h % CHARACTER_TINTS.length;
}

// Module-level cache of character sheets, keyed by src. A sheet loads at most
// once across the whole panel; every portrait waiting on it is redrawn when it
// resolves (so multiple NPCs sharing one base sheet all paint, not just the
// first to request it).
const _sheets = new Map(); // src -> { img, ready, error, waiters: [] }
function getSheet(src, onReady) {
  let rec = _sheets.get(src);
  if (rec) {
    if (!rec.ready && !rec.error) rec.waiters.push(onReady);
    return rec;
  }
  rec = { img: new Image(), ready: false, error: false, waiters: [onReady] };
  _sheets.set(src, rec);
  rec.img.onload = () => {
    rec.ready = true;
    rec.waiters.splice(0).forEach((cb) => cb());
  };
  rec.img.onerror = () => {
    rec.error = true; // graceful: portrait falls back to a monogram chip
    rec.waiters.splice(0).forEach((cb) => cb());
  };
  rec.img.src = src;
  return rec;
}

// One pixel-crisp portrait: frame 0 (idle) of the NPC's walk sheet, per-NPC
// tint, drawn into a small canvas. If the sheet is missing it falls back to a
// monogrammed parchment chip — never a blank or a crash.
function SpritePortrait({ spriteId, npcId, name, size = 38 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const entry = CHARACTER_ATLAS[spriteId] ?? CHARACTER_FALLBACK;

    const draw = () => {
      const cur = canvasRef.current;
      if (!cur) return;
      const cx = cur.getContext('2d');
      cx.imageSmoothingEnabled = false;
      cx.clearRect(0, 0, cur.width, cur.height);
      const rec = _sheets.get(entry.src);
      if (!rec || !rec.ready || rec.error) return; // CSS fallback shows through
      // Source frame 0; show the head-and-shoulders region (the sprite stands at
      // the bottom of its cell), centered, scaled to fill the portrait.
      const cropH = Math.round(entry.fh * 0.62); // upper body
      const sy = Math.round(entry.fh * 0.16);
      cx.drawImage(rec.img, 0, sy, entry.fw, cropH, 0, 0, cur.width, cur.height);
    };

    const rec = getSheet(entry.src, draw);
    if (rec.ready) draw();
  }, [spriteId, npcId]);

  const tint = CHARACTER_TINTS[tintIndexFor(npcId)];
  const initial = (name || '?').trim().charAt(0).toUpperCase() || '?';
  return (
    <div style={{ ...styles.portrait, width: size, height: size }}>
      <span style={styles.portraitInitial}>{initial}</span>
      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        className="cv-pixel"
        style={styles.portraitCanvas}
      />
      {tint ? <div style={{ ...styles.portraitTint, background: tint }} /> : null}
    </div>
  );
}

export default function RelationshipsPanel({ contacts }) {
  const list = contacts ?? [];
  return (
    <section className="cv-plate cv-slide-right" style={{ ...plate, ...styles.panel }}>
      <h2 style={plateHeading}>Acquaintances</h2>
      {list.length === 0 ? (
        <div style={styles.empty}>No one yet. Walk up and speak to a villager.</div>
      ) : (
        <div style={styles.rows}>
          {list.map((c) => (
            <div key={c.npc_id} style={styles.row}>
              <SpritePortrait spriteId={c.sprite_id} npcId={c.npc_id} name={c.name} />
              <div style={styles.meta}>
                <div style={styles.nameRow}>
                  <span style={styles.name}>{c.name}</span>
                  <span style={styles.count}>×{c.times_talked}</span>
                </div>
                {c.occupation ? <div style={styles.occupation}>{c.occupation}</div> : null}
                <div style={styles.disposition}>
                  <span style={styles.mood}>{c.mood}</span>
                  <span style={styles.sep}> · </span>
                  {c.disposition}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const styles = {
  panel: {
    width: '232px',
    padding: '10px 12px',
  },
  empty: {
    marginTop: '8px',
    fontSize: '12px',
    color: COLORS.muted,
    fontFamily: FONTS.body,
    lineHeight: 1.5,
  },
  rows: {
    marginTop: '8px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  portrait: {
    position: 'relative',
    flex: '0 0 auto',
    borderRadius: '3px',
    overflow: 'hidden',
    background: 'linear-gradient(180deg, #2a2415 0%, #1a1c12 100%)',
    border: `1px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 0 0 1px ${COLORS.frameGold}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  portraitInitial: {
    position: 'absolute',
    fontFamily: FONTS.display,
    fontSize: '14px',
    color: COLORS.gold,
    opacity: 0.7,
  },
  portraitCanvas: {
    position: 'relative',
    width: '100%',
    height: '100%',
  },
  portraitTint: {
    position: 'absolute',
    inset: 0,
    mixBlendMode: 'multiply',
    opacity: 0.5,
    pointerEvents: 'none',
  },
  meta: {
    minWidth: 0,
    flex: 1,
  },
  nameRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: '6px',
  },
  name: {
    fontFamily: FONTS.body,
    fontSize: '13px',
    color: COLORS.cream,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  count: {
    flex: '0 0 auto',
    fontSize: '11px',
    color: COLORS.gold,
    fontVariantNumeric: 'tabular-nums',
  },
  occupation: {
    fontSize: '11px',
    color: COLORS.creamDim,
    textTransform: 'capitalize',
  },
  disposition: {
    fontSize: '11px',
    color: COLORS.creamDim,
    fontStyle: 'italic',
  },
  mood: {
    color: COLORS.goldBright,
    fontStyle: 'normal',
    textTransform: 'capitalize',
  },
  sep: {
    color: COLORS.muted,
  },
};
