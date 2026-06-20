import { useEffect, useRef, useState } from 'react';
import { COLORS, FONTS } from './theme';

export default function DialogueBox({ dialogue, onSend, onClose }) {
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

  return (
    <div style={styles.wrapper} className="cv-slide-up">
      <div style={styles.panel}>
        <div style={styles.headerRow}>
          <div>
            <h2 style={styles.title}>{dialogue.npcName}</h2>
            <span style={styles.subtitle}>
              {dialogue.occupation ? `${dialogue.occupation} · ` : ''}
              <span style={styles.mood}>{dialogue.mood}</span>
              {dialogue.disposition ? ` · ${dialogue.disposition} toward you` : ''}
            </span>
          </div>
          <button type="button" className="cv-btn" style={styles.closeButton} onClick={onClose}>
            Close (Esc)
          </button>
        </div>

        {dialogue.remembered.length > 0 ? (
          <p style={styles.remembered}>
            ❧ They recall: {dialogue.remembered[dialogue.remembered.length - 1]}
          </p>
        ) : null}

        <div ref={transcriptRef} className="cv-scroll" style={styles.transcript}>
          {dialogue.lines.length === 0 && !dialogue.busy ? (
            <p style={styles.placeholder}>{dialogue.npcName} waits for you to speak.</p>
          ) : null}
          {dialogue.lines.map((line, index) => (
            <p
              key={index}
              style={line.speaker === 'player' ? styles.playerLine : styles.npcLine}
            >
              <strong style={line.speaker === 'player' ? styles.playerName : styles.npcName}>
                {line.speaker === 'player' ? 'You' : dialogue.npcName}:
              </strong>{' '}
              {line.text}
            </p>
          ))}
          {dialogue.busy ? (
            <p style={styles.thinking}>{dialogue.npcName} is thinking…</p>
          ) : null}
        </div>

        <form style={styles.inputRow} onSubmit={submit}>
          <input
            style={styles.input}
            type="text"
            value={draft}
            maxLength={300}
            placeholder="Say something…"
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
    background: 'linear-gradient(180deg, rgba(16,19,25,0.94) 0%, rgba(11,14,18,0.97) 100%)',
    borderTop: `2px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 2px 0 ${COLORS.frameGold}, 0 -8px 28px rgba(0,0,0,0.5)`,
    color: COLORS.cream,
    fontFamily: FONTS.body,
    padding: '14px 16px 16px',
    boxSizing: 'border-box'
  },
  panel: {
    maxWidth: '1100px',
    margin: '0 auto'
  },
  headerRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '12px'
  },
  title: {
    margin: 0,
    fontFamily: FONTS.display,
    fontSize: '18px',
    color: COLORS.goldBright,
    textShadow: '0 2px 0 rgba(0,0,0,0.6)'
  },
  subtitle: {
    fontSize: '12px',
    color: COLORS.creamDim,
    textTransform: 'capitalize'
  },
  mood: {
    color: COLORS.goldBright
  },
  closeButton: {
    flex: '0 0 auto',
    fontSize: '12px'
  },
  remembered: {
    margin: '10px 0 0',
    fontSize: '12px',
    fontStyle: 'italic',
    color: COLORS.gold
  },
  transcript: {
    margin: '12px 0 0',
    maxHeight: '190px',
    overflowY: 'auto',
    padding: '10px 12px',
    background: 'rgba(8, 10, 14, 0.5)',
    border: `1px solid ${COLORS.frameDark}`,
    boxShadow: `inset 0 0 0 1px ${COLORS.frameGold}`,
    borderRadius: '3px'
  },
  placeholder: {
    margin: 0,
    color: COLORS.muted,
    fontStyle: 'italic'
  },
  playerLine: {
    margin: '6px 0',
    lineHeight: 1.55,
    color: COLORS.creamDim
  },
  npcLine: {
    margin: '6px 0',
    lineHeight: 1.55,
    color: COLORS.cream
  },
  playerName: {
    color: COLORS.gold
  },
  npcName: {
    color: COLORS.goldBright
  },
  thinking: {
    margin: '6px 0',
    color: COLORS.muted,
    fontStyle: 'italic'
  },
  inputRow: {
    display: 'flex',
    gap: '8px',
    marginTop: '12px'
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
    outline: 'none'
  },
  sendButton: {
    flex: '0 0 auto',
    fontSize: '14px',
    padding: '8px 18px'
  }
};
