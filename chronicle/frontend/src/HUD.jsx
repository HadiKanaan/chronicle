import { useEffect, useRef, useState } from 'react';
import { COLORS, FONTS, plate, plateHeading } from './theme';

// Day 10 diegetic game HUD (Part B): edge-anchored overlay plates layered over
// the full-screen canvas, not a sidebar. Every plate reflects existing payload
// fields only; the overlay container is pointer-transparent so only the plates
// themselves catch the mouse. Audio + debug controls have moved to the pause
// menu — this reads as a polished game overlay, not a dashboard.

function formatHour(hour) {
  const h = Number.isFinite(hour) ? ((hour % 24) + 24) % 24 : 0;
  return `${String(h).padStart(2, '0')}:00`;
}

// time_of_day / weather -> a small glyph. Emoji keep it asset-free and graceful;
// an unknown key just falls back to a neutral dot.
const PHASE_ICON = { dawn: '🌅', morning: '☀️', afternoon: '🌤️', dusk: '🌇', night: '🌙' };
const WEATHER_ICON = { clear: '☀️', rain: '🌧️', fog: '🌫️', storm: '⛈️' };

// A collapsible/scrollable card used for the factions, Demon Lord, and rumors
// plates so none of them becomes a wall of text.
function CollapsibleCard({ title, accent, defaultOpen = true, children, slide = 'cv-slide-left' }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section
      className={`cv-plate ${slide}`}
      style={{ ...plate, ...styles.card, ...(accent ? styles.cardEmber : null) }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={styles.cardHeader}
        aria-expanded={open}
      >
        <span style={{ ...plateHeading, color: accent ? COLORS.ember : COLORS.gold }}>{title}</span>
        <span style={{ ...styles.chevron, color: accent ? COLORS.ember : COLORS.gold }}>
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open ? <div className="cv-scroll" style={styles.cardBody}>{children}</div> : null}
    </section>
  );
}

export default function HUD({ gameState }) {
  const factionEntries = Object.entries(gameState.faction_reputations ?? {});
  const factionMorale = gameState.faction_morale ?? {};
  const rumors = gameState.rumors ?? [];
  const demonLordDecisions = gameState.demon_lord_decisions ?? [];

  const phase = gameState.time_of_day ?? 'dawn';
  const weatherKey = gameState.weather ?? 'clear';

  return (
    <>
      {/* Top-left: compact, game-like world status. */}
      <div style={styles.topLeft}>
        <section className="cv-plate cv-slide-right" style={{ ...plate, ...styles.statusPlate }}>
          <div style={styles.statusRow}>
            <span style={styles.dayBadge}>Day {gameState.current_day}</span>
            {gameState.world_paused ? <span style={styles.paused}>⏸</span> : null}
          </div>
          <div style={styles.clockRow}>
            <span style={styles.phaseIcon}>{PHASE_ICON[phase] ?? '•'}</span>
            <span style={styles.clock}>{formatHour(gameState.current_hour)}</span>
            <span style={styles.phaseName}>{phase}</span>
          </div>
          <div style={styles.weatherRow}>
            <span style={styles.weatherIcon}>{WEATHER_ICON[weatherKey] ?? '•'}</span>
            <span style={styles.weatherName}>{weatherKey}</span>
          </div>
        </section>
      </div>

      {/* Top-right: factions, the Demon Lord, town gossip. */}
      <div style={styles.topRight}>
        <CollapsibleCard title="Factions">
          {factionEntries.length === 0 ? (
            <div style={styles.muted}>No factions yet.</div>
          ) : (
            <>
              {factionEntries.map(([name, score]) => (
                <div key={name} style={styles.facRow}>
                  <span style={styles.facName}>{name}</span>
                  <span style={styles.facScore}>
                    {score}
                    {name in factionMorale ? (
                      <span style={styles.muted}> · {factionMorale[name]}♦</span>
                    ) : null}
                  </span>
                </div>
              ))}
              <div style={styles.legend}>standing toward you · morale ♦</div>
            </>
          )}
        </CollapsibleCard>

        <CollapsibleCard title="Demon Lord" accent>
          {demonLordDecisions.length === 0 ? (
            <div style={styles.muted}>No sign of the Demon Lord yet.</div>
          ) : (
            demonLordDecisions.map((item, index) => (
              <div key={`${item}-${index}`} style={styles.demonLord}>{item}</div>
            ))
          )}
        </CollapsibleCard>

        <CollapsibleCard title="Town Gossip">
          {rumors.length === 0 ? (
            <div style={styles.muted}>The town is quiet.</div>
          ) : (
            rumors.map((item, index) => (
              <div key={`${item}-${index}`} style={styles.rumor}>“{item}”</div>
            ))
          )}
        </CollapsibleCard>
      </div>

      {/* Bottom-left: notification toast feed (newest first, auto-trims). */}
      <NotificationFeed notifications={gameState.notifications ?? []} />
    </>
  );
}

// Newest-first toast log: new notifications fade in at the top and the feed is
// trimmed to the most recent few so it never grows into a static wall.
function NotificationFeed({ notifications }) {
  const recent = notifications.slice(-4).reverse();
  // Stable keys so React only animates genuinely-new toasts (the payload resends
  // the same strings every poll).
  const seenRef = useRef(new Map());
  const keyed = recent.map((text, i) => {
    const map = seenRef.current;
    const k = `${text}#${notifications.length - i}`;
    if (!map.has(k)) map.set(k, true);
    return { k, text };
  });
  // Keep the seen-map from growing unbounded.
  useEffect(() => {
    if (seenRef.current.size > 64) seenRef.current = new Map();
  });

  if (keyed.length === 0) return null;
  return (
    <div style={styles.bottomLeft}>
      {keyed.map(({ k, text }) => (
        <div key={k} className="cv-plate cv-toast-in" style={{ ...plate, ...styles.toast }}>
          {text}
        </div>
      ))}
    </div>
  );
}

const OVERLAY_Z = 10;

const styles = {
  topLeft: {
    position: 'fixed',
    top: '12px',
    left: '12px',
    zIndex: OVERLAY_Z,
    pointerEvents: 'auto',
  },
  topRight: {
    position: 'fixed',
    top: '12px',
    right: '12px',
    zIndex: OVERLAY_Z,
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    width: '244px',
    maxHeight: 'calc(100vh - 24px)',
    pointerEvents: 'auto',
  },
  bottomLeft: {
    position: 'fixed',
    bottom: '12px',
    left: '12px',
    zIndex: OVERLAY_Z,
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    width: '300px',
    pointerEvents: 'none',
  },
  statusPlate: {
    padding: '8px 12px',
    minWidth: '150px',
  },
  statusRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  dayBadge: {
    fontFamily: FONTS.display,
    fontSize: '12px',
    color: COLORS.goldBright,
    letterSpacing: '0.03em',
  },
  paused: {
    color: COLORS.gold,
    fontSize: '13px',
  },
  clockRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '7px',
    marginTop: '5px',
  },
  phaseIcon: {
    fontSize: '15px',
    lineHeight: 1,
  },
  clock: {
    fontFamily: FONTS.display,
    fontSize: '15px',
    color: COLORS.cream,
    fontVariantNumeric: 'tabular-nums',
  },
  phaseName: {
    fontSize: '12px',
    color: COLORS.creamDim,
    textTransform: 'capitalize',
  },
  weatherRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '7px',
    marginTop: '3px',
  },
  weatherIcon: {
    fontSize: '13px',
    lineHeight: 1,
  },
  weatherName: {
    fontSize: '12px',
    color: COLORS.creamDim,
    textTransform: 'capitalize',
  },
  card: {
    padding: '0',
    overflow: 'hidden',
  },
  cardEmber: {
    boxShadow: `inset 0 0 0 2px ${COLORS.emberDim}, inset 0 0 16px rgba(0,0,0,0.55), 0 4px 16px rgba(0,0,0,0.5)`,
    borderColor: '#2a140e',
  },
  cardHeader: {
    width: '100%',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    padding: '8px 12px',
  },
  chevron: {
    fontSize: '11px',
  },
  cardBody: {
    padding: '0 12px 10px',
    maxHeight: '210px',
    overflowY: 'auto',
  },
  facRow: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '10px',
    padding: '3px 0',
    fontSize: '12px',
    color: COLORS.cream,
  },
  facName: {
    color: COLORS.cream,
  },
  facScore: {
    color: COLORS.goldBright,
    fontVariantNumeric: 'tabular-nums',
  },
  legend: {
    color: COLORS.muted,
    fontSize: '10px',
    marginTop: '6px',
  },
  demonLord: {
    padding: '5px 0',
    borderBottom: '1px solid rgba(124, 51, 36, 0.4)',
    color: COLORS.emberBright,
    fontSize: '12px',
    lineHeight: 1.4,
  },
  rumor: {
    padding: '5px 0',
    borderBottom: '1px solid rgba(201, 162, 75, 0.2)',
    color: COLORS.creamDim,
    fontStyle: 'italic',
    fontSize: '12px',
    lineHeight: 1.4,
  },
  muted: {
    color: COLORS.muted,
    fontSize: '12px',
  },
  toast: {
    pointerEvents: 'auto',
    padding: '7px 11px',
    fontSize: '12px',
    color: COLORS.cream,
    lineHeight: 1.4,
    borderLeft: `3px solid ${COLORS.gold}`,
  },
};
