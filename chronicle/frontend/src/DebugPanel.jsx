import { useState } from 'react';
import { sendDebug } from './api';

// Demo/debug control panel: set time and faction scores, and fire a dawn tick
// on cue (to show the ML batch react live). Inputs use LOCAL state, snapshotted
// from the world when the panel opens, so the 500ms /api/state poll never
// clobbers what you're typing.
export default function DebugPanel({ gameState }) {
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState('1');
  const [hour, setHour] = useState('6');
  const [facValues, setFacValues] = useState({});

  const factionNames = Object.keys(gameState.faction_reputations ?? {});

  const openPanel = () => {
    setDay(String(gameState.current_day ?? 1));
    setHour(String(gameState.current_hour ?? 6));
    const snapshot = {};
    for (const name of factionNames) {
      snapshot[name] = {
        rep: String(gameState.faction_reputations?.[name] ?? 50),
        morale: String(gameState.faction_morale?.[name] ?? 60)
      };
    }
    setFacValues(snapshot);
    setOpen(true);
  };

  const setField = (name, key, value) =>
    setFacValues((current) => ({ ...current, [name]: { ...current[name], [key]: value } }));

  if (!open) {
    return (
      <button style={styles.toggle} onClick={openPanel}>
        ⚙ Debug controls
      </button>
    );
  }

  return (
    <section style={styles.panel}>
      <div style={styles.header}>
        <strong>Debug controls</strong>
        <button style={styles.close} onClick={() => setOpen(false)}>
          hide
        </button>
      </div>

      <div style={styles.group}>
        <div style={styles.label}>Time</div>
        <div style={styles.row}>
          <label style={styles.inline}>
            Day <input style={styles.num} value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
          <label style={styles.inline}>
            Hour <input style={styles.num} value={hour} onChange={(e) => setHour(e.target.value)} />
          </label>
          <button
            style={styles.btn}
            onClick={() => sendDebug('set_time', { day: Number(day), hour: Number(hour) }).catch(() => {})}
          >
            Set
          </button>
        </div>
        <div style={styles.row}>
          <button style={styles.btn} onClick={() => sendDebug('advance_hour').catch(() => {})}>
            Advance hour
          </button>
          <button style={styles.btnAccent} onClick={() => sendDebug('trigger_dawn').catch(() => {})}>
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
              style={styles.btn}
              onClick={() =>
                sendDebug('set_faction', {
                  faction: name,
                  reputation: Number(facValues[name]?.rep),
                  morale: Number(facValues[name]?.morale)
                }).catch(() => {})
              }
            >
              Set
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

const styles = {
  toggle: {
    marginTop: '16px',
    width: '100%',
    background: '#1b2030',
    color: '#9aa4b2',
    border: '1px dashed #39414d',
    borderRadius: '4px',
    padding: '6px',
    cursor: 'pointer',
    fontSize: '12px'
  },
  panel: {
    marginTop: '16px',
    background: '#15171f',
    border: '1px solid #39414d',
    borderRadius: '5px',
    padding: '10px'
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '8px',
    color: '#d6dae1'
  },
  close: {
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '4px',
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: '11px'
  },
  group: { marginTop: '8px' },
  label: { color: '#8a93a3', fontSize: '11px', marginBottom: '4px', textTransform: 'uppercase' },
  row: { display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', flexWrap: 'wrap' },
  inline: { display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', color: '#c9cfd8' },
  fname: { flex: '1 1 120px', fontSize: '12px', color: '#c9cfd8' },
  num: {
    width: '48px',
    background: '#0e1118',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '3px',
    padding: '2px 4px'
  },
  btn: {
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '4px',
    padding: '2px 10px',
    cursor: 'pointer',
    fontSize: '12px'
  },
  btnAccent: {
    background: '#3a2f12',
    color: '#f0d9a0',
    border: '1px solid #6b5520',
    borderRadius: '4px',
    padding: '2px 10px',
    cursor: 'pointer',
    fontSize: '12px'
  }
};
