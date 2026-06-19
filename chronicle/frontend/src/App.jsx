import { useEffect, useState } from 'react';
import { getState, getConversationContext, sendConversation, sendInput } from './api';
import GameCanvas from './GameCanvas';
import DialogueBox from './DialogueBox';
import HUD from './HUD';
import ContinentOverlay from './ContinentOverlay';
import PauseMenu from './PauseMenu';

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
  fog_map: [],
  buildings: [],
  decorations: [],
  paths: [],
  props: [],
  manually_paused: false
};

export default function App() {
  const [gameState, setGameState] = useState(EMPTY_STATE);
  // Dialogue is temporary UI state only: the backend owns the cards and the
  // conversation outcome; this just holds the open panel's transcript.
  const [dialogue, setDialogue] = useState(null);
  const [notifications, setNotifications] = useState([]);
  // Continent map overlay (press M). Purely a UI panel; the data is fetched
  // once by the overlay component, never in the state poll.
  const [showContinent, setShowContinent] = useState(false);
  // Full pause menu (Esc). Opening it freezes the world clock; resuming releases
  // it. Backend stays authoritative - this only posts the pause intent.
  const [showPauseMenu, setShowPauseMenu] = useState(false);
  // Frontend-only X-ray: ghost every building roof so the NPCs inside are
  // visible at once. Purely a render toggle (the backend never sees it).
  const [revealInteriors, setRevealInteriors] = useState(false);

  const setPaused = (paused) => {
    sendInput({ type: 'toggle_pause', payload: { paused } }).catch(() => {});
  };

  const resumeFromPauseMenu = () => {
    setShowPauseMenu(false);
    setPaused(false);
  };

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
    // Poll fast (200ms) so player input latency and NPC retargeting stay tight;
    // the canvas itself redraws every animation frame and tweens between polls.
    const intervalId = window.setInterval(loadState, 200);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const dialogueOpen = Boolean(dialogue);

  // Heartbeat while a dialogue is open: re-arm the backend's rolling freeze
  // window (180s) every 60s so slow reading/typing never lets time resume
  // mid-conversation. If the tab dies, the window still self-expires after
  // ~3 missed beats - the world can never be frozen forever.
  useEffect(() => {
    if (!dialogueOpen) {
      return undefined;
    }
    const heartbeatId = window.setInterval(() => {
      sendInput({ type: 'dialogue_open', payload: {} }).catch(() => {});
    }, 60000);
    return () => window.clearInterval(heartbeatId);
  }, [dialogueOpen]);

  // Press M to toggle the continent map overlay (ignored while typing in the
  // dialogue input so it never eats a letter mid-sentence).
  useEffect(() => {
    const onKeyDown = (event) => {
      const tag = event.target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (event.key === 'm' || event.key === 'M') {
        event.preventDefault();
        setShowContinent((open) => !open);
      } else if (event.key === 'p' || event.key === 'P') {
        // Quick sticky pause of the world clock, no menu (backend authoritative).
        event.preventDefault();
        sendInput({ type: 'toggle_pause', payload: {} }).catch(() => {});
      } else if (event.key === 'b' || event.key === 'B') {
        event.preventDefault();
        setRevealInteriors((on) => !on);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        // Esc closes the continent map first if it's up; otherwise it toggles
        // the pause menu (which freezes / releases the world clock).
        if (showContinent) {
          setShowContinent(false);
        } else {
          const next = !showPauseMenu;
          setShowPauseMenu(next);
          setPaused(next);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showContinent, showPauseMenu]);

  const openDialogue = async (npc) => {
    // Tell the backend the dialogue window is open: the world clock freezes so
    // the NPC's mood and the town stay consistent mid-conversation. Sending the
    // npc_id also warms that NPC's LLM prefix now, while the player reads/types,
    // so the first reply skips the cold prompt-eval. (The freeze heartbeat below
    // re-sends dialogue_open WITHOUT an id, so it never re-warms.)
    sendInput({ type: 'dialogue_open', payload: { npc_id: npc.id } }).catch(() => {});
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
    notifications,
    revealInteriors
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
        {gameState.manually_paused && !showPauseMenu ? (
          <div style={styles.pauseOverlay}>
            <div style={styles.pauseMenu}>
              <div style={styles.pauseTitle}>⏸ Paused</div>
              <div style={styles.pauseHint}>The world clock is held. You can still walk around.</div>
              <button
                style={styles.resumeBtn}
                onClick={() => sendInput({ type: 'toggle_pause', payload: { paused: false } }).catch(() => {})}
              >
                ▶ Resume (P)
              </button>
            </div>
          </div>
        ) : null}
      </div>
      <div style={styles.sidebar}>
        <HUD gameState={visibleState} />
        <button
          style={revealInteriors ? styles.revealBtnOn : styles.revealBtn}
          onClick={() => setRevealInteriors((on) => !on)}
        >
          {revealInteriors ? '🏠 Hide building interiors' : '🏠 Reveal building interiors'}
        </button>
        <div style={styles.hint}>Esc menu · M map · R fog · P pause · B interiors</div>
      </div>
      <DialogueBox dialogue={dialogue} onSend={sendLine} onClose={closeDialogue} />
      {showContinent ? <ContinentOverlay onClose={() => setShowContinent(false)} /> : null}
      <PauseMenu open={showPauseMenu} onResume={resumeFromPauseMenu} />
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
    minHeight: '0',
    position: 'relative'
  },
  pauseOverlay: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingTop: '24px',
    background: 'rgba(10, 13, 20, 0.32)',
    pointerEvents: 'none'
  },
  pauseMenu: {
    pointerEvents: 'auto',
    background: 'rgba(21, 25, 33, 0.94)',
    border: '1px solid #39414d',
    borderRadius: '8px',
    padding: '16px 20px',
    textAlign: 'center',
    boxShadow: '0 8px 24px rgba(0, 0, 0, 0.45)'
  },
  pauseTitle: {
    fontSize: '20px',
    color: '#8ab4f8',
    marginBottom: '4px'
  },
  pauseHint: {
    fontSize: '12px',
    color: '#9ca3af',
    marginBottom: '12px'
  },
  resumeBtn: {
    background: '#222833',
    color: '#f5f5f5',
    border: '1px solid #4a76c4',
    borderRadius: '5px',
    padding: '6px 16px',
    cursor: 'pointer',
    fontSize: '13px'
  },
  sidebar: {
    minHeight: '0'
  },
  revealBtn: {
    marginTop: '12px',
    width: '100%',
    background: '#1b2030',
    color: '#9aa4b2',
    border: '1px solid #39414d',
    borderRadius: '4px',
    padding: '8px',
    cursor: 'pointer',
    fontSize: '13px'
  },
  revealBtnOn: {
    marginTop: '12px',
    width: '100%',
    background: '#12233a',
    color: '#a8c7f0',
    border: '1px solid #4a76c4',
    borderRadius: '4px',
    padding: '8px',
    cursor: 'pointer',
    fontSize: '13px'
  },
  hint: {
    marginTop: '10px',
    color: '#6b7280',
    fontSize: '12px',
    textAlign: 'center'
  }
};
