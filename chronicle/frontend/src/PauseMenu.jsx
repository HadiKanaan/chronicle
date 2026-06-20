import { useState, useEffect } from 'react';
import { generateWorld } from './api';
import { audioManager } from './audio';

// Full pause menu (Esc). Opening it freezes the world clock; Resume / Esc
// release it. Besides resuming it offers a guarded world regeneration and a
// controls + how-to-play reference. Backend stays authoritative throughout -
// this only sends intents (pause, regenerate) and reads payload state.
const CONTROLS = [
  ['Arrow keys', 'Walk around the town'],
  ['Click a villager', 'Talk to them (they remember you)'],
  ['M', 'Continent map overlay'],
  ['R', 'Toggle fog of war'],
  ['P', 'Pause / resume time'],
  ['Esc', 'Open / close this menu'],
];

export default function PauseMenu({ open, onResume }) {
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  // Master sound controls mirror the AudioManager singleton. Re-sync from it
  // each time the menu opens so the toggle reflects a mute set elsewhere (the
  // HUD panel) while the menu was closed.
  const [muted, setMuted] = useState(audioManager.masterMuted);
  const [masterVolume, setMasterVolume] = useState(audioManager.getMasterVolume());

  useEffect(() => {
    if (open) {
      setMuted(audioManager.masterMuted);
      setMasterVolume(audioManager.getMasterVolume());
    }
  }, [open]);

  if (!open) return null;

  const onToggleMute = () => setMuted(audioManager.toggleMasterMute());

  const onMasterVolume = (event) => {
    const value = Number(event.target.value);
    audioManager.setMasterVolume(value);
    setMasterVolume(value);
  };

  const handleRegenerate = async () => {
    if (!confirmRegen) {
      setConfirmRegen(true);
      return;
    }
    setRegenerating(true);
    try {
      await generateWorld();
    } catch (error) {
      // The next /api/state poll will reflect whatever the backend did.
    } finally {
      setRegenerating(false);
      setConfirmRegen(false);
      onResume(); // drop back into the fresh world, clock running
    }
  };

  return (
    <div style={styles.backdrop}>
      <div style={styles.menu}>
        <div style={styles.title}>⏸ Paused</div>

        <button style={styles.primary} onClick={onResume}>▶ Resume</button>

        <div style={styles.sectionLabel}>Sound</div>
        <div style={styles.soundRow}>
          <button
            style={muted ? styles.muteOn : styles.muteBtn}
            onClick={onToggleMute}
          >
            {muted ? '🔇 Muted' : '🔊 Mute all'}
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={masterVolume}
            onChange={onMasterVolume}
            disabled={muted}
            aria-label="Master volume"
            style={styles.masterSlider}
          />
          <span style={styles.volReadout}>{Math.round(masterVolume * 100)}%</span>
        </div>

        <button
          style={regenerating ? styles.dangerBusy : styles.danger}
          onClick={handleRegenerate}
          disabled={regenerating}
        >
          {regenerating
            ? 'Regenerating world…'
            : confirmRegen
              ? '⚠ Confirm — wipes all NPCs & memories'
              : '↻ Regenerate entire world'}
        </button>
        {confirmRegen && !regenerating ? (
          <button style={styles.cancel} onClick={() => setConfirmRegen(false)}>
            Cancel
          </button>
        ) : null}

        <div style={styles.sectionLabel}>How to play</div>
        <p style={styles.blurb}>
          You inherit a villager&apos;s life in Aldenmoor, a living town. Walk
          around and talk to people — their moods, memories, and opinions of you
          persist, and rumors spread between them. A Demon Lord stirs beyond the
          eastern hills; the town&apos;s factions react as the days pass.
        </p>

        <div style={styles.sectionLabel}>Controls</div>
        <div style={styles.controls}>
          {CONTROLS.map(([key, desc]) => (
            <div key={key} style={styles.controlRow}>
              <span style={styles.key}>{key}</span>
              <span style={styles.desc}>{desc}</span>
            </div>
          ))}
        </div>

        <div style={styles.footer}>Press Esc or Resume to return</div>
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(8, 10, 16, 0.72)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 50,
  },
  menu: {
    width: '420px',
    maxWidth: '92vw',
    maxHeight: '88vh',
    overflowY: 'auto',
    background: '#171b22',
    border: '1px solid #39414d',
    borderRadius: '10px',
    padding: '24px',
    boxShadow: '0 16px 48px rgba(0, 0, 0, 0.55)',
    color: '#f5f5f5',
  },
  title: {
    fontSize: '26px',
    color: '#8ab4f8',
    textAlign: 'center',
    marginBottom: '18px',
  },
  primary: {
    width: '100%',
    background: '#1d2a40',
    color: '#dce8ff',
    border: '1px solid #4a76c4',
    borderRadius: '6px',
    padding: '10px',
    cursor: 'pointer',
    fontSize: '15px',
    marginBottom: '10px',
  },
  danger: {
    width: '100%',
    background: '#2a1517',
    color: '#f0b4b4',
    border: '1px solid #7a3a3a',
    borderRadius: '6px',
    padding: '10px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  dangerBusy: {
    width: '100%',
    background: '#2a1517',
    color: '#a98484',
    border: '1px solid #7a3a3a',
    borderRadius: '6px',
    padding: '10px',
    fontSize: '14px',
    cursor: 'wait',
  },
  cancel: {
    width: '100%',
    background: 'transparent',
    color: '#9ca3af',
    border: '1px solid #39414d',
    borderRadius: '6px',
    padding: '6px',
    cursor: 'pointer',
    fontSize: '12px',
    marginTop: '6px',
  },
  sectionLabel: {
    marginTop: '20px',
    marginBottom: '6px',
    fontSize: '12px',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: '#8a93a3',
  },
  soundRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  muteBtn: {
    flex: '0 0 auto',
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '6px',
    padding: '8px 12px',
    cursor: 'pointer',
    fontSize: '13px',
  },
  muteOn: {
    flex: '0 0 auto',
    background: '#3a2026',
    color: '#e08a8a',
    border: '1px solid #5a2a32',
    borderRadius: '6px',
    padding: '8px 12px',
    cursor: 'pointer',
    fontSize: '13px',
  },
  masterSlider: {
    flex: 1,
  },
  volReadout: {
    flex: '0 0 40px',
    textAlign: 'right',
    fontSize: '12px',
    color: '#9ca3af',
    fontVariantNumeric: 'tabular-nums',
  },
  blurb: {
    margin: 0,
    fontSize: '13px',
    lineHeight: 1.5,
    color: '#c4cbd5',
  },
  controls: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  controlRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '12px',
  },
  key: {
    flex: '0 0 110px',
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#f0d9a0',
  },
  desc: {
    fontSize: '13px',
    color: '#c4cbd5',
  },
  footer: {
    marginTop: '20px',
    textAlign: 'center',
    fontSize: '11px',
    color: '#6b7280',
  },
};
