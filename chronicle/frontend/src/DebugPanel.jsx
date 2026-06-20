import { useState } from 'react';
import { sendDebug, sendInput } from './api';
import { COLORS, FONTS } from './theme';

// Demo/debug controls, themed for the Day 10 pause-menu Debug tab. Set time and
// faction scores, fire a dawn tick on cue (to show the ML batch react live),
// switch the LLM provider, and clear chat history. Inputs use LOCAL state,
// snapshotted from the world when the tab mounts, so the 200ms /api/state poll
// never clobbers what you're typing. Backend stays authoritative — every button
// only posts an existing intent.
export default function DebugPanel({ gameState }) {
  const factionNames = Object.keys(gameState.faction_reputations ?? {});
  const paused = Boolean(gameState.manually_paused);

  const [day, setDay] = useState(String(gameState.current_day ?? 1));
  const [hour, setHour] = useState(String(gameState.current_hour ?? 6));
  const [facValues, setFacValues] = useState(() => {
    const snapshot = {};
    for (const name of factionNames) {
      snapshot[name] = {
        rep: String(gameState.faction_reputations?.[name] ?? 50),
        morale: String(gameState.faction_morale?.[name] ?? 60),
      };
    }
    return snapshot;
  });

  const setField = (name, key, value) =>
    setFacValues((current) => ({ ...current, [name]: { ...current[name], [key]: value } }));

  return (
    <div style={styles.panel}>
      <div style={styles.group}>
        <div style={styles.label}>Conversation engine</div>
        <div style={styles.row}>
          <span style={styles.providerName}>
            LLM: <strong style={styles.accentText}>{gameState.llm_provider ?? 'local'}</strong>
            {gameState.llm_last_seconds ? (
              <span style={styles.muted}> · {gameState.llm_last_seconds}s last</span>
            ) : null}
          </span>
          <button
            className="cv-btn"
            style={styles.btn}
            onClick={() => sendInput({ type: 'toggle_provider', payload: {} }).catch(() => {})}
          >
            switch
          </button>
        </div>
        {gameState.azure_available === false ? (
          <div style={styles.legend}>Azure not configured — toggle stays local</div>
        ) : null}
      </div>

      <div style={styles.group}>
        <div style={styles.label}>Time</div>
        <div style={styles.row}>
          <button
            className={paused ? 'cv-btn cv-btn-primary' : 'cv-btn'}
            style={styles.btn}
            onClick={() =>
              sendInput({ type: 'toggle_pause', payload: { paused: !paused } }).catch(() => {})
            }
          >
            {paused ? '▶ Resume time' : '⏸ Pause time'}
          </button>
        </div>
        <div style={styles.row}>
          <label style={styles.inline}>
            Day <input style={styles.num} value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
          <label style={styles.inline}>
            Hour <input style={styles.num} value={hour} onChange={(e) => setHour(e.target.value)} />
          </label>
          <button
            className="cv-btn"
            style={styles.btn}
            onClick={() => sendDebug('set_time', { day: Number(day), hour: Number(hour) }).catch(() => {})}
          >
            Set
          </button>
        </div>
        <div style={styles.row}>
          <button className="cv-btn" style={styles.btn} onClick={() => sendDebug('advance_hour').catch(() => {})}>
            Advance hour
          </button>
          <button className="cv-btn cv-btn-primary" style={styles.btn} onClick={() => sendDebug('trigger_dawn').catch(() => {})}>
            Trigger dawn (run ML)
          </button>
        </div>
      </div>

      <div style={styles.group}>
        <div style={styles.label}>Faction scores — reputation / morale</div>
        {factionNames.map((name) => (
          <div key={name} style={styles.row}>
            <span style={styles.fname}>{name}</span>
            <input
              style={styles.num}
              value={facValues[name]?.rep ?? ''}
              onChange={(e) => setField(name, 'rep', e.target.value)}
            />
            <input
              style={styles.num}
              value={facValues[name]?.morale ?? ''}
              onChange={(e) => setField(name, 'morale', e.target.value)}
            />
            <button
              className="cv-btn"
              style={styles.btn}
              onClick={() =>
                sendDebug('set_faction', {
                  faction: name,
                  reputation: Number(facValues[name]?.rep),
                  morale: Number(facValues[name]?.morale),
                }).catch(() => {})
              }
            >
              Set
            </button>
          </div>
        ))}
      </div>

      <div style={styles.group}>
        <div style={styles.label}>Conversations</div>
        <button className="cv-btn" style={styles.btn} onClick={() => sendDebug('clear_history').catch(() => {})}>
          Clear all NPC chat history
        </button>
      </div>
    </div>
  );
}

const styles = {
  panel: { display: 'flex', flexDirection: 'column', gap: '4px', fontFamily: FONTS.body },
  group: { marginTop: '6px' },
  label: {
    color: COLORS.gold,
    fontSize: '10px',
    marginBottom: '5px',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    fontFamily: FONTS.display,
  },
  row: { display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', flexWrap: 'wrap' },
  inline: { display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', color: COLORS.creamDim },
  providerName: { fontSize: '12px', color: COLORS.creamDim, flex: '1 1 auto' },
  accentText: { color: COLORS.goldBright },
  fname: { flex: '1 1 120px', fontSize: '12px', color: COLORS.creamDim },
  num: {
    width: '48px',
    background: '#0e1118',
    color: COLORS.cream,
    border: `1px solid ${COLORS.frameDark}`,
    borderRadius: '3px',
    padding: '3px 4px',
    fontFamily: FONTS.body,
  },
  btn: { fontSize: '12px', padding: '4px 10px' },
  muted: { color: COLORS.muted },
  legend: { color: COLORS.muted, fontSize: '11px', marginTop: '2px' },
};
