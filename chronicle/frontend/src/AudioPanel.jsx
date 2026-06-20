import { useState } from 'react';
import { sendInput } from './api';
import { audioManager } from './audio';

// Day 9 HUD audio panel: master mute, the three channel volume sliders, the
// NPC-voice on/off toggle (wired to the backend toggle_voice), and the required
// Ivan Duch credit. The manager is the single source of audio truth; this panel
// just drives it. Voice availability/enabled come from the render payload so the
// control reflects the backend's authoritative state.
export default function AudioPanel({ gameState }) {
  const [muted, setMuted] = useState(audioManager.masterMuted);
  const [volumes, setVolumes] = useState({ ...audioManager.volumes });

  const voiceAvailable = gameState.voice_available ?? false;
  const voiceEnabled = gameState.voice_enabled ?? true;

  const onMute = () => setMuted(audioManager.toggleMasterMute());

  const onVolume = (channel, value) => {
    const v = Number(value);
    audioManager.setVolume(channel, v);
    setVolumes((prev) => ({ ...prev, [channel]: v }));
  };

  const onToggleVoice = () => {
    // Backend stays authoritative — post the intent; the payload flips next poll.
    sendInput({ type: 'toggle_voice', payload: {} }).catch(() => {});
  };

  return (
    <section style={styles.section}>
      <div style={styles.headerRow}>
        <h2 style={styles.heading}>Audio</h2>
        <button style={muted ? styles.muteOn : styles.muteBtn} onClick={onMute}>
          {muted ? '🔇 Muted' : '🔊 Sound'}
        </button>
      </div>

      {['music', 'ambient', 'voice'].map((channel) => (
        <label key={channel} style={styles.sliderRow}>
          <span style={styles.sliderLabel}>{channel}</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={volumes[channel]}
            onChange={(event) => onVolume(channel, event.target.value)}
            style={styles.slider}
          />
        </label>
      ))}

      <div style={styles.voiceRow}>
        <span>
          NPC voices:{' '}
          <strong>{voiceAvailable ? (voiceEnabled ? 'on' : 'off') : 'unavailable'}</strong>
        </span>
        <button
          style={styles.voiceBtn}
          onClick={onToggleVoice}
          disabled={!voiceAvailable}
          title={voiceAvailable ? 'Toggle Azure NPC voices' : 'Azure Speech not configured'}
        >
          {voiceEnabled ? '🗣 mute voices' : '🗣 unmute voices'}
        </button>
      </div>
      {!voiceAvailable ? (
        <div style={styles.legend}>Azure Speech not configured — NPCs stay silent</div>
      ) : null}

      <div style={styles.credit}>Music by Ivan Duch</div>
    </section>
  );
}

const styles = {
  section: { marginTop: '20px' },
  headerRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center'
  },
  heading: { margin: '0 0 8px', fontSize: '16px' },
  muteBtn: {
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '4px',
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: '11px'
  },
  muteOn: {
    background: '#3a2026',
    color: '#e08a8a',
    border: '1px solid #5a2a32',
    borderRadius: '4px',
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: '11px'
  },
  sliderRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '3px 0'
  },
  sliderLabel: {
    width: '64px',
    fontSize: '12px',
    color: '#9ca3af',
    textTransform: 'capitalize'
  },
  slider: { flex: 1 },
  voiceRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '8px',
    marginTop: '8px',
    fontSize: '13px'
  },
  voiceBtn: {
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #39414d',
    borderRadius: '4px',
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: '11px'
  },
  legend: {
    color: '#6b7280',
    fontSize: '11px',
    marginTop: '6px'
  },
  credit: {
    marginTop: '10px',
    color: '#8a93a3',
    fontSize: '11px',
    fontStyle: 'italic'
  }
};
