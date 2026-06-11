import { useEffect, useRef, useState } from 'react';

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
    <div style={styles.wrapper}>
      <div style={styles.panel}>
        <div style={styles.headerRow}>
          <div>
            <h2 style={styles.title}>{dialogue.npcName}</h2>
            <span style={styles.subtitle}>
              {dialogue.occupation ? `${dialogue.occupation} · ` : ''}
              {dialogue.mood}
              {dialogue.disposition ? ` · ${dialogue.disposition} toward you` : ''}
            </span>
          </div>
          <button type="button" style={styles.closeButton} onClick={onClose}>
            Close
          </button>
        </div>

        {dialogue.remembered.length > 0 ? (
          <p style={styles.remembered}>
            They recall: {dialogue.remembered[dialogue.remembered.length - 1]}
          </p>
        ) : null}

        <div ref={transcriptRef} style={styles.transcript}>
          {dialogue.lines.length === 0 && !dialogue.busy ? (
            <p style={styles.placeholder}>{dialogue.npcName} waits for you to speak.</p>
          ) : null}
          {dialogue.lines.map((line, index) => (
            <p
              key={index}
              style={line.speaker === 'player' ? styles.playerLine : styles.npcLine}
            >
              <strong>{line.speaker === 'player' ? 'You' : dialogue.npcName}:</strong>{' '}
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
          <button type="submit" style={styles.sendButton} disabled={dialogue.busy || !draft.trim()}>
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
    background: 'rgba(9, 11, 16, 0.95)',
    borderTop: '1px solid #2e3540',
    color: '#f5f5f5',
    padding: '16px',
    boxSizing: 'border-box'
  },
  panel: {
    maxWidth: '1200px',
    margin: '0 auto'
  },
  headerRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '12px'
  },
  title: {
    margin: 0,
    fontSize: '20px'
  },
  subtitle: {
    fontSize: '13px',
    color: '#9fb0c3'
  },
  closeButton: {
    border: '1px solid #526070',
    background: '#18202a',
    color: '#f5f5f5',
    padding: '8px 12px',
    cursor: 'pointer'
  },
  remembered: {
    margin: '10px 0 0',
    fontSize: '13px',
    fontStyle: 'italic',
    color: '#c9b97e'
  },
  transcript: {
    margin: '12px 0 0',
    maxHeight: '180px',
    overflowY: 'auto',
    paddingRight: '8px'
  },
  placeholder: {
    margin: 0,
    color: '#7d8a99',
    fontStyle: 'italic'
  },
  playerLine: {
    margin: '6px 0',
    lineHeight: 1.5,
    color: '#9fd0ff'
  },
  npcLine: {
    margin: '6px 0',
    lineHeight: 1.5
  },
  thinking: {
    margin: '6px 0',
    color: '#7d8a99',
    fontStyle: 'italic'
  },
  inputRow: {
    display: 'flex',
    gap: '8px',
    marginTop: '12px'
  },
  input: {
    flex: 1,
    border: '1px solid #526070',
    background: '#10141a',
    color: '#f5f5f5',
    padding: '10px 12px',
    fontSize: '15px',
    outline: 'none'
  },
  sendButton: {
    border: '1px solid #526070',
    background: '#1a232d',
    color: '#f5f5f5',
    padding: '8px 16px',
    cursor: 'pointer'
  }
};
