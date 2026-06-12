import { useEffect, useState } from 'react';
import { getState, getConversationContext, sendConversation, sendInput } from './api';
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
  // Dialogue is temporary UI state only: the backend owns the cards and the
  // conversation outcome; this just holds the open panel's transcript.
  const [dialogue, setDialogue] = useState(null);
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

  const openDialogue = async (npc) => {
    // Tell the backend the dialogue window is open: the world clock freezes
    // so the NPC's mood and the town stay consistent mid-conversation.
    sendInput({ type: 'dialogue_open', payload: {} }).catch(() => {});
    setDialogue({
      npcId: npc.id,
      npcName: npc.name,
      occupation: '',
      mood: npc.mood ?? 'neutral',
      disposition: '',
      remembered: [],
      lines: [],
      busy: true
    });
    try {
      const context = await getConversationContext(npc.id);
      setDialogue((current) => {
        if (!current || current.npcId !== npc.id) {
          return current;
        }
        return {
          ...current,
          npcName: context.npc_name,
          occupation: context.occupation,
          mood: context.mood,
          disposition: context.disposition,
          remembered: context.remembered ?? [],
          lines: (context.history ?? []).flatMap((entry) => [
            { speaker: 'player', text: entry.player_text },
            { speaker: 'npc', text: entry.npc_response }
          ]),
          busy: false
        };
      });
    } catch (error) {
      setDialogue((current) =>
        current && current.npcId === npc.id ? { ...current, busy: false } : current
      );
    }
  };

  const sendLine = async (text) => {
    const npcId = dialogue?.npcId;
    if (!npcId || !text.trim()) {
      return;
    }
    setDialogue((current) =>
      current && current.npcId === npcId
        ? {
            ...current,
            lines: [...current.lines, { speaker: 'player', text }],
            busy: true
          }
        : current
    );
    try {
      const result = await sendConversation(npcId, text);
      setDialogue((current) =>
        current && current.npcId === npcId
          ? {
              ...current,
              mood: result.mood,
              lines: [...current.lines, { speaker: 'npc', text: result.npc_response }],
              busy: false
            }
          : current
      );
    } catch (error) {
      setDialogue((current) =>
        current && current.npcId === npcId
          ? {
              ...current,
              lines: [...current.lines, { speaker: 'npc', text: '...gives no answer.' }],
              busy: false
            }
          : current
      );
    }
  };

  const visibleState = {
    ...gameState,
    notifications
  };

  const closeDialogue = () => {
    setDialogue(null);
    // Resume the world clock when the dialogue window closes.
    sendInput({ type: 'dialogue_close', payload: {} }).catch(() => {});
  };

  return (
    <div style={styles.shell}>
      <div style={styles.canvasPanel}>
        <GameCanvas gameState={visibleState} onNpcClick={openDialogue} />
      </div>
      <div style={styles.sidebar}>
        <HUD gameState={visibleState} />
      </div>
      <DialogueBox dialogue={dialogue} onSend={sendLine} onClose={closeDialogue} />
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
