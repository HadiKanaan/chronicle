import SpritePortrait from './SpritePortrait';
import { COLORS, FONTS, plate, plateHeading } from './theme';

// Day 10 Acquaintances plate (Part D). Display-only: it renders the backend's
// `recent_contacts` projection (the last ~5 NPCs the player has spoken to),
// already display-ready and DL/player-filtered backend-side. No new gameplay,
// no intents — just a mirror of payload state. Each row shows the NPC's idle
// sprite as a small tinted portrait, name, occupation, mood, disposition toward
// the player, and how many times you've spoken.

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
              <SpritePortrait spriteId={c.sprite_id} tintId={c.npc_id} name={c.name} />
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
