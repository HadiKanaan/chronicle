import { useEffect, useState } from 'react';
import { getState, getConversationContext, sendConversation, sendInput, sendVoice } from './api';
import { audioManager } from './audio';
import GameCanvas from './GameCanvas';
import DialogueBox from './DialogueBox';
import HUD from './HUD';
import Minimap from './Minimap';
import RelationshipsPanel from './RelationshipsPanel';
import ContinentOverlay from './ContinentOverlay';
import PauseMenu from './PauseMenu';
import TitleSplash from './TitleSplash';
import { COLORS, FONTS, plate } from './theme';

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
  recent_contacts: [],
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
  // Day 10 title splash: shown until the player clicks "begin", which also
  // unlocks audio. Unmounted after its fade-out settles.
  const [splashGone, setSplashGone] = useState(false);

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
        setNotifications((nextState.notifications ?? []).slice(-6));
        // Audio reacts to the authoritative payload (time_of_day, weather). The
        // manager no-ops until unlocked by the title splash below.
        audioManager.update(nextState);
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

  // Day 10: audio unlocks intentionally on the title-splash "begin" gesture
  // (Part F), replacing the old invisible first-gesture listener. Browsers block
  // autoplay before a gesture, so the OST starts exactly here.
  const beginGame = () => {
    audioManager.unlock();
    window.setTimeout(() => setSplashGone(true), 850); // unmount after the fade
  };

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
      // Decoupled voice pass: the reply text is already on screen; fetch the TTS
      // clip and play it a beat later. Fully best-effort — sendVoice never
      // throws, and {voiced:false} (no creds / disabled / outage) just stays
      // silent. Only voice the reply if this NPC's dialogue is still open.
      if (result.npc_response) {
        sendVoice(npcId, result.npc_response).then((voiceResult) => {
          if (voiceResult?.voiced && dialogue?.npcId === npcId) {
            audioManager.playVoiceBase64(voiceResult.audio_b64, voiceResult.format);
          }
        });
      }
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
      {/* Full-bleed world canvas fills the viewport. */}
      <div style={styles.canvasLayer}>
        <GameCanvas gameState={visibleState} onNpcClick={openDialogue} />
      </div>

      {/* Tasteful screen vignette (pure CSS, non-interactive). */}
      <div className="cv-vignette" />

      {/* Diegetic edge-anchored HUD plates. */}
      <HUD gameState={visibleState} />

      {/* Acquaintances plate, top-left under the world-status plate. */}
      <div style={styles.acquaintances}>
        <RelationshipsPanel contacts={gameState.recent_contacts} />
      </div>

      {/* Village minimap, bottom-right corner. */}
      <div style={styles.minimapWrap}>
        <Minimap gameState={visibleState} />
      </div>

      {/* Bottom-center controls strip. */}
      <div style={styles.bottomCenter}>
        <button
          className="cv-btn"
          style={revealInteriors ? styles.revealOn : styles.revealBtn}
          onClick={() => setRevealInteriors((on) => !on)}
        >
          {revealInteriors ? '🏠 Hide interiors' : '🏠 Reveal interiors'}
        </button>
        <span style={styles.hint}>Esc menu · M map · R fog · P pause · B interiors</span>
      </div>

      {/* Sticky manual-pause indicator (when paused outside the menu). */}
      {gameState.manually_paused && !showPauseMenu ? (
        <div style={styles.pauseOverlay}>
          <div className="cv-plate cv-fade-in" style={{ ...plate, ...styles.pausePlate }}>
            <div style={styles.pauseTitle}>⏸ Paused</div>
            <div style={styles.pauseHint}>The world clock is held. You can still walk around.</div>
            <button
              className="cv-btn cv-btn-primary"
              style={styles.resumeBtn}
              onClick={() => sendInput({ type: 'toggle_pause', payload: { paused: false } }).catch(() => {})}
            >
              ▶ Resume (P)
            </button>
          </div>
        </div>
      ) : null}

      <DialogueBox dialogue={dialogue} onSend={sendLine} onClose={closeDialogue} />
      {showContinent ? <ContinentOverlay onClose={() => setShowContinent(false)} /> : null}
      <PauseMenu open={showPauseMenu} onResume={resumeFromPauseMenu} gameState={visibleState} />
      {!splashGone ? <TitleSplash onBegin={beginGame} /> : null}
    </div>
  );
}

const styles = {
  shell: {
    position: 'fixed',
    inset: 0,
    background: COLORS.ink,
    color: COLORS.cream,
    fontFamily: FONTS.body,
    overflow: 'hidden',
  },
  canvasLayer: {
    position: 'absolute',
    inset: 0,
  },
  acquaintances: {
    position: 'fixed',
    top: '108px',
    left: '12px',
    zIndex: 10,
  },
  minimapWrap: {
    position: 'fixed',
    bottom: '12px',
    right: '12px',
    zIndex: 10,
  },
  bottomCenter: {
    position: 'fixed',
    bottom: '12px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 10,
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  revealBtn: { fontSize: '12px', padding: '6px 12px' },
  revealOn: {
    fontSize: '12px',
    padding: '6px 12px',
    background: '#2c2410',
    color: COLORS.goldBright,
    borderColor: '#6b5520',
  },
  hint: {
    fontSize: '11px',
    color: COLORS.creamDim,
    background: 'rgba(11, 14, 18, 0.6)',
    padding: '5px 10px',
    borderRadius: '3px',
  },
  pauseOverlay: {
    position: 'fixed',
    inset: 0,
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingTop: '28px',
    pointerEvents: 'none',
    zIndex: 20,
  },
  pausePlate: {
    pointerEvents: 'auto',
    padding: '14px 20px',
    textAlign: 'center',
  },
  pauseTitle: {
    fontFamily: FONTS.display,
    fontSize: '16px',
    color: COLORS.goldBright,
    marginBottom: '4px',
  },
  pauseHint: {
    fontSize: '12px',
    color: COLORS.creamDim,
    marginBottom: '12px',
  },
  resumeBtn: { fontSize: '13px' },
};
