export default function DialogueBox({ dialogue, onClose }) {
  if (!dialogue) {
    return null;
  }

  return (
    <div style={styles.wrapper}>
      <div style={styles.panel}>
        <div style={styles.headerRow}>
          <h2 style={styles.title}>{dialogue.npc_name}</h2>
          <button type="button" style={styles.closeButton} onClick={onClose}>
            Close
          </button>
        </div>
        <p style={styles.text}>{dialogue.text}</p>
        {Array.isArray(dialogue.options) && dialogue.options.length > 0 ? (
          <div style={styles.options}>
            {dialogue.options.map((option) => (
              <button key={option} type="button" style={styles.optionButton}>
                {option}
              </button>
            ))}
          </div>
        ) : null}
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
  closeButton: {
    border: '1px solid #526070',
    background: '#18202a',
    color: '#f5f5f5',
    padding: '8px 12px',
    cursor: 'pointer'
  },
  text: {
    margin: '12px 0 0',
    lineHeight: 1.5
  },
  options: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
    marginTop: '12px'
  },
  optionButton: {
    border: '1px solid #526070',
    background: '#1a232d',
    color: '#f5f5f5',
    padding: '8px 12px',
    cursor: 'pointer'
  }
};