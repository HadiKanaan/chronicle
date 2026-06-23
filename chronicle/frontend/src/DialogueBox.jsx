import { useEffect, useRef, useState } from 'react';
import SpritePortrait from './SpritePortrait';
import { COLORS, FONTS } from './theme';

// Chat-app style conversation panel (Day 10 QoL): a self-contained framed box that
// sits over the world. The two speakers face each other at the top - the NPC's
// enlarged sprite on the left, the player's on the right - and the transcript
// below reads like a messaging thread: NPC lines as bubbles on the left, the
// player's on the right, one per row. Presentational only; the dialogue flow,
// memory, and sentiment are unchanged.

// A small mood glyph for the NPC's portrait caption (emoji = asset-free, graceful;
// an unknown mood just shows none).
const MOOD_EMOJI = {
  happy: '😊', content: '🙂', neutral: '😐', proud: '😌', hopeful: '🙂',
  sad: '😔', grieving: '😢', angry: '😠', fearful: '😨', suspicious: '🤨',
  wary: '🤨', annoyed: '😒', tired: '😪',
};

export default function DialogueBox({ dialogue, onSend, onClose, playerSpriteId, playerName }) {
  const [draft, setDraft] = useState('');
  const transcriptRef = useRef(null);

  useEffect(() => {
    const el = transcriptRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [dialogue?.lines?.length, dialogue?.busy]);

  useEffect(() => {
    setDraft('');
  }, [dialogue?.npcId]);

  // Escape closes the dialogue. Registered only while a dialogue is open, in the
  // capture phase with stopPropagation, so it pre-empts App's Escape handler
  // (which would otherwise open the pause menu) and works whether or not focus
  // is in the text input.
  useEffect(() => {
    if (!dialogue) {
      return undefined;
    }
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [dialogue, onClose]);

  if (!dialogue) {
    return null;
  }

  const submit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || dialogue.busy) {
      return;
    }
    setDraft('');
    onSend(text);
  };

  const moodGlyph = MOOD_EMOJI[(dialogue.mood || '').toLowerCase()] ?? '';

  return (
    <div style={styles.wrapper}>
      <div style={styles.box} className="cv-plate cv-slide-up">
        <button type="button" className="cv-btn" style={styles.close} onClick={onClose} aria-label="Close">
          ✕
        </button>

        {/* The two speakers, facing each other. */}
        <div style={styles.stage}>
          <div style={styles.speakerLeft}>
            <SpritePortrait spriteId={dialogue.npcSpriteId} tintId={dialogue.npcId} name={dialogue.npcName} size={72} />
            <div style={styles.speakerMeta}>
              <div style={styles.npcName}>{dialogue.npcName}</div>
              {dialogue.occupation ? <div style={styles.occupation}>{dialogue.occupation}</div> : null}
              <div style={styles.mood}>
                {moodGlyph ? `${moodGlyph} ` : ''}{dialogue.mood}
              </div>
            </div>
          </div>

          <div style={styles.speakerRight}>
            <div style={{ ...styles.speakerMeta, ...styles.speakerMetaRight }}>
              <div style={styles.youName}>{playerName || 'You'}</div>
              {dialogue.disposition ? (
                <div style={styles.disposition}>{dialogue.disposition} toward you</div>
              ) : null}
            </div>
            <SpritePortrait spriteId={playerSpriteId} name={playerName || 'You'} size={72} />
          </div>
        </div>

        {dialogue.remembered.length > 0 ? (
          <div style={styles.remembered}>
            ❧ {dialogue.npcName} recalls: {dialogue.remembered[dialogue.remembered.length - 1]}
          </div>
        ) : null}

        {/* The thread. */}
        <div ref={transcriptRef} className="cv-scroll" style={styles.transcript}>
          {dialogue.lines.length === 0 && !dialogue.busy ? (
            <div style={styles.placeholder}>{dialogue.npcName} waits for you to speak.</div>
          ) : null}
          {dialogue.lines.map((line, index) => {
            const isPlayer = line.speaker === 'player';
            return (
              <div
                key={index}
                style={isPlayer ? styles.rowRight : styles.rowLeft}
                className="cv-slide-up"
              >
                <div style={isPlayer ? styles.bubblePlayer : styles.bubbleNpc}>{line.text}</div>
              </div>
            );
          })}
          {dialogue.busy ? (
            <div style={styles.rowLeft}>
              <div style={styles.bubbleNpc}>
                <span style={styles.typing}>
                  <span style={{ ...styles.dot, animationDelay: '0ms' }}>•</span>
                  <span style={{ ...styles.dot, animationDelay: '160ms' }}>•</span>
                  <span style={{ ...styles.dot, animationDelay: '320ms' }}>•</span>
                </span>
              </div>
            </div>
          ) : null}
        </div>

        <form style={styles.inputRow} onSubmit={submit}>
          <input
            style={styles.input}
            type="text"
            value={draft}
            maxLength={300}
            placeholder={`Say something to ${dialogue.npcName}…`}
            onChange={(event) => setDraft(event.target.value)}
            autoFocus
          />
          <button
            type="submit"
            className="cv-btn cv-btn-primary"
            style={styles.sendButton}
            disabled={dialogue.busy || !draft.trim()}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

const styles = {
  wrapper: {
    position: 'fixed',
    left: 0,
    right: 0,
    bottom: 0,
    // Above the HUD overlay plates (z 10) and the manual-pause indicator (z 20),
    // but below the pause menu / continent overlay (z 60) and the splash (z 80).
    zIndex: 40,
    display: 'flex',
    justifyContent: 'center',
    padding: '0 16px 16px',
    pointerEvents: 'none',
  },
  box: {
    pointerEvents: 'auto',
    position: 'relative',
    width: 'min(760px, 96vw)',
    maxHeight: '74vh',
    display: 'flex',
    flexDirection: 'column',
    // A near-opaque dark-parchment backing so the thread reads clearly over the
    // bright live world.
    background: 'linear-gradient(180deg, rgba(20,23,30,0.97) 0%, rgba(13,16,21,0.98) 100%)',
    border: `2px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 0 0 2px ${COLORS.frameGold}, 0 10px 32px rgba(0,0,0,0.6)`,
    borderRadius: '4px',
    color: COLORS.cream,
    fontFamily: FONTS.body,
    padding: '14px 16px 16px',
  },
  close: {
    position: 'absolute',
    top: '8px',
    right: '8px',
    fontSize: '12px',
    padding: '3px 9px',
    lineHeight: 1,
  },
  stage: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '12px',
    paddingBottom: '12px',
    borderBottom: `1px solid ${COLORS.frameDark}`,
  },
  speakerLeft: {
    display: 'flex',
    gap: '10px',
    alignItems: 'center',
    minWidth: 0,
  },
  speakerRight: {
    display: 'flex',
    gap: '10px',
    alignItems: 'center',
    minWidth: 0,
  },
  speakerMeta: { minWidth: 0 },
  speakerMetaRight: { textAlign: 'right' },
  npcName: {
    fontFamily: FONTS.display,
    fontSize: '14px',
    color: COLORS.goldBright,
    textShadow: '0 2px 0 rgba(0,0,0,0.6)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  youName: {
    fontFamily: FONTS.display,
    fontSize: '14px',
    color: COLORS.cream,
    textShadow: '0 2px 0 rgba(0,0,0,0.6)',
  },
  occupation: {
    fontSize: '11px',
    color: COLORS.creamDim,
    textTransform: 'capitalize',
  },
  mood: {
    fontSize: '12px',
    color: COLORS.goldBright,
    textTransform: 'capitalize',
    marginTop: '2px',
  },
  disposition: {
    fontSize: '11px',
    color: COLORS.creamDim,
    fontStyle: 'italic',
    marginTop: '2px',
  },
  remembered: {
    margin: '10px 0 0',
    fontSize: '12px',
    fontStyle: 'italic',
    color: COLORS.gold,
  },
  transcript: {
    flex: 1,
    minHeight: '90px',
    margin: '12px 0',
    overflowY: 'auto',
    paddingRight: '6px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  placeholder: {
    color: COLORS.muted,
    fontStyle: 'italic',
    textAlign: 'center',
    margin: 'auto',
  },
  rowLeft: {
    display: 'flex',
    justifyContent: 'flex-start',
  },
  rowRight: {
    display: 'flex',
    justifyContent: 'flex-end',
  },
  bubbleNpc: {
    maxWidth: '72%',
    background: 'rgba(42, 36, 22, 0.92)',
    border: '1px solid #4a3c1f',
    borderRadius: '10px 10px 10px 2px',
    padding: '8px 12px',
    fontSize: '14px',
    lineHeight: 1.45,
    color: COLORS.cream,
  },
  bubblePlayer: {
    maxWidth: '72%',
    background: 'rgba(28, 42, 58, 0.92)',
    border: '1px solid #2f4a63',
    borderRadius: '10px 10px 2px 10px',
    padding: '8px 12px',
    fontSize: '14px',
    lineHeight: 1.45,
    color: '#dce8ff',
  },
  typing: {
    display: 'inline-flex',
    gap: '3px',
    fontSize: '18px',
    lineHeight: 1,
    color: COLORS.gold,
  },
  dot: {
    animation: 'cvFadeIn 0.6s ease-in-out infinite alternate',
  },
  inputRow: {
    display: 'flex',
    gap: '8px',
  },
  input: {
    flex: 1,
    border: `2px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 0 0 1px ${COLORS.frameGold}`,
    background: '#0e1118',
    color: COLORS.cream,
    padding: '10px 12px',
    fontSize: '15px',
    fontFamily: FONTS.body,
    borderRadius: '3px',
    outline: 'none',
  },
  sendButton: {
    flex: '0 0 auto',
    fontSize: '14px',
    padding: '8px 18px',
  },
};
