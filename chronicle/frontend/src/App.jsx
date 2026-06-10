import { useEffect, useState } from 'react';
import { getState } from './api';
import GameCanvas from './GameCanvas';
import DialogueBox from './DialogueBox';
import HUD from './HUD';

const EMPTY_STATE = {
  tiles: [],
  npcs: [],
  player: null,
  time_of_day: 'dawn',
  weather: 'clear',
  dialogue: null,
  notifications: [],
  faction_reputations: {},
  current_day: 1,
  current_hour: 6,
  fog_map: []
};

export default function App() {
  const [gameState, setGameState] = useState(EMPTY_STATE);
  const [dialogueState, setDialogueState] = useState(null);
  const [notifications, setNotifications] = useState([]);

  useEffect(() => {
    let cancelled = false;

    const loadState = async () => {
      try {
        const nextState = await getState();
        if (cancelled) {
          return;
        }
        setGameState(nextState);
        setDialogueState(nextState.dialogue ?? null);
        setNotifications((nextState.notifications ?? []).slice(-5));
      } catch (error) {
        if (!cancelled) {
          setGameState(EMPTY_STATE);
        }
      }
    };

    loadState();
    const intervalId = window.setInterval(loadState, 500);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const visibleState = {
    ...gameState,
    notifications
  };

  return (
    <div style={styles.shell}>
      <div style={styles.canvasPanel}>
        <GameCanvas gameState={visibleState} />
      </div>
      <div style={styles.sidebar}>
        <HUD gameState={visibleState} />
      </div>
      <DialogueBox dialogue={dialogueState} onClose={() => setDialogueState(null)} />
    </div>
  );
}

const styles = {
  shell: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 320px',
    gap: '16px',
    minHeight: '100vh',
    padding: '16px',
    background: '#111318',
    color: '#f5f5f5',
    boxSizing: 'border-box'
  },
  canvasPanel: {
    minHeight: '0'
  },
  sidebar: {
    minHeight: '0'
  }
};