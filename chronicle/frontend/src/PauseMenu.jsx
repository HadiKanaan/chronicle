import { useState, useEffect } from 'react';
import { generateWorld } from './api';
import { audioManager } from './audio';
import AudioPanel from './AudioPanel';
import DebugPanel from './DebugPanel';
import { COLORS, FONTS, plate } from './theme';

// Day 10 pause menu (Part C). Opening it freezes the world clock; Resume / Esc
// release it. All settings now live here as themed tabs — Sound (master mute +
// volume + the per-channel AudioPanel), Debug (the DebugPanel), How to Play
// (controls + blurb), and a guarded Regenerate. Backend stays authoritative
// throughout: this only sends intents (pause, regenerate, debug) and reads
// payload state.
const CONTROLS = [
  ['Arrow keys', 'Walk around the town'],
  ['Click a villager', 'Talk to them (they remember you)'],
  ['M', 'Continent map overlay'],
  ['R', 'Toggle fog of war'],
  ['B', 'Reveal building interiors'],
  ['F', 'Toggle fullscreen'],
  ['P', 'Pause / resume time'],
  ['Esc', 'Open / close this menu'],
];

const TABS = [
  ['sound', 'Sound'],
  ['debug', 'Debug'],
  ['howto', 'How to Play'],
  ['regen', 'Regenerate'],
];

export default function PauseMenu({ open, onResume, gameState }) {
  const [tab, setTab] = useState('howto');
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  // Master sound controls mirror the AudioManager singleton. Re-sync from it
  // each time the menu opens so the toggle reflects a mute set elsewhere while
  // the menu was closed.
  const [muted, setMuted] = useState(audioManager.masterMuted);
  const [masterVolume, setMasterVolume] = useState(audioManager.getMasterVolume());

  useEffect(() => {
    if (open) {
      setMuted(audioManager.masterMuted);
      setMasterVolume(audioManager.getMasterVolume());
      setConfirmRegen(false);
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
      // The next /api/state poll reflects whatever the backend did.
    } finally {
      setRegenerating(false);
      setConfirmRegen(false);
      onResume(); // drop back into the fresh world, clock running
    }
  };

  return (
    <div style={styles.backdrop}>
      <div className="cv-plate cv-slide-up cv-scroll" style={{ ...plate, ...styles.menu }}>
        <div style={styles.titleRow}>
          <div style={styles.title}>⏸ Paused</div>
          <button className="cv-btn cv-btn-primary" style={styles.resume} onClick={onResume}>
            ▶ Resume
          </button>
        </div>

        <div style={styles.tabs}>
          {TABS.map(([id, label]) => (
            <button
              key={id}
              className="cv-btn"
              style={{ ...styles.tab, ...(tab === id ? styles.tabActive : null) }}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        <div style={styles.content}>
          {tab === 'sound' ? (
            <>
              <div style={styles.sectionLabel}>Master</div>
              <div style={styles.soundRow}>
                <button
                  className={muted ? 'cv-btn cv-btn-ember' : 'cv-btn'}
                  style={styles.muteBtn}
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
              <div style={styles.sectionLabel}>Channels</div>
              <AudioPanel gameState={gameState} />
            </>
          ) : null}

          {tab === 'debug' ? <DebugPanel gameState={gameState} /> : null}

          {tab === 'howto' ? (
            <>
              <p style={styles.blurb}>
                You inherit a villager&apos;s life in Aldenmoor, a living town. Walk
                around and talk to people — their moods, memories, and opinions of
                you persist, and rumors spread between them. A Demon Lord stirs
                beyond the eastern hills; the town&apos;s factions react as the days
                pass.
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
            </>
          ) : null}

          {tab === 'regen' ? (
            <>
              <p style={styles.blurb}>
                Regenerating wipes every NPC, memory, faction, and the whole map,
                then builds a fresh world from scratch. There is no undo.
              </p>
              <button
                className={regenerating ? 'cv-btn cv-btn-ember' : 'cv-btn cv-btn-ember'}
                style={styles.danger}
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
                <button className="cv-btn" style={styles.cancel} onClick={() => setConfirmRegen(false)}>
                  Cancel
                </button>
              ) : null}
            </>
          ) : null}
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
    background: 'rgba(6, 8, 12, 0.74)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 60,
  },
  menu: {
    width: '440px',
    maxWidth: '92vw',
    maxHeight: '88vh',
    overflowY: 'auto',
    padding: '20px 22px',
  },
  titleRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  },
  title: {
    fontFamily: FONTS.display,
    fontSize: '20px',
    color: COLORS.goldBright,
    textShadow: '0 2px 0 rgba(0,0,0,0.6)',
  },
  resume: { fontSize: '14px' },
  tabs: {
    display: 'flex',
    gap: '6px',
    flexWrap: 'wrap',
    marginBottom: '16px',
  },
  tab: {
    fontSize: '12px',
    padding: '6px 10px',
    flex: '1 1 auto',
  },
  tabActive: {
    background: '#2c2410',
    color: COLORS.goldBright,
    borderColor: '#6b5520',
    boxShadow: 'inset 0 0 0 1px rgba(232, 198, 106, 0.55)',
  },
  content: {
    minHeight: '180px',
  },
  sectionLabel: {
    marginTop: '14px',
    marginBottom: '8px',
    fontSize: '10px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: COLORS.gold,
    fontFamily: FONTS.display,
  },
  soundRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  muteBtn: { flex: '0 0 auto', fontSize: '13px' },
  masterSlider: { flex: 1, accentColor: COLORS.gold },
  volReadout: {
    flex: '0 0 40px',
    textAlign: 'right',
    fontSize: '12px',
    color: COLORS.creamDim,
    fontVariantNumeric: 'tabular-nums',
  },
  danger: { width: '100%', fontSize: '14px' },
  cancel: { width: '100%', fontSize: '12px', marginTop: '6px' },
  blurb: {
    margin: 0,
    fontSize: '13px',
    lineHeight: 1.55,
    color: COLORS.creamDim,
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
    flex: '0 0 116px',
    fontFamily: FONTS.body,
    fontSize: '12px',
    color: COLORS.goldBright,
  },
  desc: {
    fontSize: '13px',
    color: COLORS.creamDim,
  },
  footer: {
    marginTop: '18px',
    textAlign: 'center',
    fontSize: '11px',
    color: COLORS.muted,
    fontFamily: FONTS.body,
  },
};
