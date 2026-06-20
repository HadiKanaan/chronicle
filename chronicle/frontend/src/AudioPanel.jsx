import { useState } from 'react';
import { sendInput } from './api';
import { audioManager } from './audio';
import { COLORS, FONTS } from './theme';

// Per-channel sound controls, themed for the Day 10 pause-menu Sound tab. The
// master mute + master volume live one level up in PauseMenu; this panel owns the
// four channel sliders (music/ambient/voice/sfx), the NPC-voice on/off toggle
// (wired to the backend toggle_voice), and the required Ivan Duch credit. The
// AudioManager singleton is the source of audio truth; this just drives it.
// Voice availability/enabled come from the render payload so the control reflects
// the backend's authoritative state.
export default function AudioPanel({ gameState }) {
  const [volumes, setVolumes] = useState({ ...audioManager.volumes });

  const voiceAvailable = gameState.voice_available ?? false;
  const voiceEnabled = gameState.voice_enabled ?? true;

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
    <div style={styles.wrap}>
      {['music', 'ambient', 'voice', 'sfx'].map((channel) => (
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
          <span style={styles.readout}>{Math.round(volumes[channel] * 100)}%</span>
        </label>
      ))}

      <div style={styles.voiceRow}>
        <span style={styles.voiceLabel}>
          NPC voices:{' '}
          <strong style={styles.voiceState}>
            {voiceAvailable ? (voiceEnabled ? 'on' : 'off') : 'unavailable'}
          </strong>
        </span>
        <button
          className="cv-btn"
          onClick={onToggleVoice}
          disabled={!voiceAvailable}
          title={voiceAvailable ? 'Toggle Azure NPC voices' : 'Azure Speech not configured'}
          style={styles.voiceBtn}
        >
          {voiceEnabled ? '🗣 mute voices' : '🗣 unmute voices'}
        </button>
      </div>
      {!voiceAvailable ? (
        <div style={styles.legend}>Azure Speech not configured — NPCs stay silent</div>
      ) : null}

      <div style={styles.credit}>Music by Ivan Duch</div>
    </div>
  );
}

const styles = {
  wrap: { display: 'flex', flexDirection: 'column', gap: '4px' },
  sliderRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '3px 0',
  },
  sliderLabel: {
    width: '64px',
    fontSize: '12px',
    color: COLORS.creamDim,
    textTransform: 'capitalize',
    fontFamily: FONTS.body,
  },
  slider: { flex: 1, accentColor: COLORS.gold },
  readout: {
    width: '38px',
    textAlign: 'right',
    fontSize: '11px',
    color: COLORS.muted,
    fontVariantNumeric: 'tabular-nums',
  },
  voiceRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '8px',
    marginTop: '8px',
    fontSize: '13px',
  },
  voiceLabel: { color: COLORS.creamDim, fontSize: '12px' },
  voiceState: { color: COLORS.goldBright },
  voiceBtn: { fontSize: '11px', padding: '4px 9px' },
  legend: {
    color: COLORS.muted,
    fontSize: '11px',
    marginTop: '6px',
  },
  credit: {
    marginTop: '10px',
    color: COLORS.muted,
    fontSize: '11px',
    fontStyle: 'italic',
  },
};
