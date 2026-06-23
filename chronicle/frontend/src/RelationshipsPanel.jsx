import { useRef } from 'react';
import SpritePortrait from './SpritePortrait';
import { COLORS, FONTS, plate, plateHeading } from './theme';

// Day 10 Acquaintances plate (Part D). Display-only: it renders the backend's
// `recent_contacts` projection (the last ~5 NPCs the player has spoken to),
// already display-ready and DL/player-filtered backend-side. No new gameplay,
// no intents — just a mirror of payload state. Each row shows the NPC's idle
// sprite as a small tinted portrait, name, occupation, mood, disposition toward
// the player, and how many times you've spoken.

// How long a freshly-added acquaintance shows the "new" pulse.
const NEW_MS = 5000;

export default function RelationshipsPanel({ contacts }) {
  const list = contacts ?? [];

  // Track when each acquaintance first appeared so a genuinely new one pulses
  // briefly. Contacts present on the first render are seeded as pre-existing
  // (never pulse); only ids added afterwards are "new". The 200ms poll re-renders
  // the panel, so the badge naturally clears after NEW_MS.
  const firstSeenRef = useRef(new Map());
  const initRef = useRef(false);
  const now = typeof performance !== 'undefined' ? performance.now() : 0;
  const seen = firstSeenRef.current;
  if (!initRef.current) {
    for (const c of list) seen.set(c.npc_id, 0);
    initRef.current = true;
  }
  for (const c of list) {
    if (!seen.has(c.npc_id)) seen.set(c.npc_id, now);
  }

  return (
    <section className="cv-plate cv-slide-right" style={{ ...plate, ...styles.panel }}>
      <h2 style={plateHeading}>Acquaintances</h2>
      {list.length === 0 ? (
        <div style={styles.empty}>No one yet. Walk up and speak to a villager.</div>
      ) : (
        <div style={styles.rows}>
          {list.map((c) => {
            const isNew = now - (seen.get(c.npc_id) ?? 0) < NEW_MS;
            return (
              <div key={c.npc_id} style={styles.row} className={isNew ? 'cv-toast-in' : undefined}>
                <SpritePortrait spriteId={c.sprite_id} occupation={c.occupation} tintId={c.npc_id} name={c.name} />
                <div style={styles.meta}>
                  <div style={styles.nameRow}>
                    <span style={styles.name}>{c.name}</span>
                    {isNew ? <span style={styles.newBadge}>✦ new</span> : <span style={styles.count}>×{c.times_talked}</span>}
                  </div>
                  {c.occupation ? <div style={styles.occupation}>{c.occupation}</div> : null}
                  <div style={styles.disposition}>
                    <span style={styles.mood}>{c.mood}</span>
                    <span style={styles.sep}> · </span>
                    {c.disposition}
                  </div>
                </div>
              </div>
            );
          })}
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
  newBadge: {
    flex: '0 0 auto',
    fontSize: '10px',
    color: COLORS.goldBright,
    fontFamily: FONTS.display,
    background: 'rgba(201,162,75,0.18)',
    border: `1px solid ${COLORS.gold}`,
    borderRadius: '3px',
    padding: '1px 5px',
    animation: 'cvFadeIn 0.7s ease-in-out infinite alternate',
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
