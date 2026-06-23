import { useEffect, useRef, useState } from 'react';
import { CHARACTER_ATLAS, CHARACTER_FALLBACK, characterTint } from './sprites';
import { COLORS, FONTS } from './theme';

// A pixel-crisp character portrait: frame 0 (idle) of a walk sheet, cropped to the
// upper body, recolored with the SAME occupation+id tint the world renderer uses
// (pass occupation + tintId; omit tintId for the untinted player). Falls back to a
// monogram chip if the sheet is missing - never a blank or a crash. Optional
// `glow` adds a pulsing ring (used to show an NPC is speaking). Shared by the
// dialogue avatars and the Acquaintances panel.
export default function SpritePortrait({ spriteId, occupation, tintId, name, size = 38, glow = false }) {
  const canvasRef = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const entry = CHARACTER_ATLAS[spriteId] ?? CHARACTER_FALLBACK;
    const tint = tintId == null ? null : characterTint(occupation, tintId);

    const draw = () => {
      const cur = canvasRef.current;
      if (!cur) return;
      const rec = _sheets.get(entry.src);
      const cx = cur.getContext('2d');
      cx.imageSmoothingEnabled = false;
      cx.clearRect(0, 0, cur.width, cur.height);
      if (!rec || !rec.ready || rec.error) {
        setReady(false);
        return;
      }
      // Upper-body crop of frame 0 (the sprite stands at the bottom of its cell).
      const cropH = Math.round(entry.fh * 0.62);
      const sy = Math.round(entry.fh * 0.16);
      cx.drawImage(rec.img, 0, sy, entry.fw, cropH, 0, 0, cur.width, cur.height);
      if (tint) {
        // Multiply recolor, masked to the sprite's pixels (matches the world).
        cx.globalCompositeOperation = 'multiply';
        cx.fillStyle = tint;
        cx.fillRect(0, 0, cur.width, cur.height);
        cx.globalCompositeOperation = 'destination-in';
        cx.drawImage(rec.img, 0, sy, entry.fw, cropH, 0, 0, cur.width, cur.height);
        cx.globalCompositeOperation = 'source-over';
      }
      setReady(true);
    };

    const rec = getSheet(entry.src, draw);
    if (rec.ready) draw();
    else if (rec.error) setReady(false);
  }, [spriteId, occupation, tintId, size]);

  const initial = (name || '?').trim().charAt(0).toUpperCase() || '?';
  return (
    <div style={{ ...styles.frame, width: size, height: size, ...(glow ? styles.glow : null) }}>
      {!ready ? <span style={{ ...styles.initial, fontSize: Math.round(size * 0.4) }}>{initial}</span> : null}
      <canvas ref={canvasRef} width={size} height={size} className="cv-pixel" style={styles.canvas} />
    </div>
  );
}

// Module-level sheet cache keyed by src; every portrait waiting on a sheet is
// redrawn once it resolves (so portraits sharing a base sheet all paint).
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
    rec.error = true;
    rec.waiters.splice(0).forEach((cb) => cb());
  };
  rec.img.src = src;
  return rec;
}

const styles = {
  frame: {
    position: 'relative',
    flex: '0 0 auto',
    borderRadius: '4px',
    overflow: 'hidden',
    background: 'linear-gradient(180deg, #2a2415 0%, #16180f 100%)',
    border: `1px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 0 0 1px ${COLORS.frameGold}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'box-shadow 0.2s ease',
  },
  glow: {
    boxShadow: `inset 0 0 0 1px ${COLORS.frameGold}, 0 0 0 2px rgba(232,198,106,0.7), 0 0 14px 2px rgba(232,198,106,0.55)`,
    animation: 'cvFadeIn 0.7s ease-in-out infinite alternate',
  },
  initial: {
    position: 'absolute',
    fontFamily: FONTS.display,
    color: COLORS.gold,
    opacity: 0.7,
  },
  canvas: {
    position: 'relative',
    width: '100%',
    height: '100%',
  },
};
