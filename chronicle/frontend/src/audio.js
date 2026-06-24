// Day 9 AudioManager: the frontend's entire audio layer, built on Howler.js.
//
// The backend stays authoritative — this manager NEVER decides game state. It
// only reacts to the RenderPayload fields (time_of_day, weather) and to user
// controls, layering three independent channels:
//
//   * music   — the Ivan Duch OST. Two shuffled pools (PEACEFUL by day,
//               OMINOUS by night) chosen from payload.time_of_day, crossfading
//               on track-end and on day<->night flips. Low default volume.
//   * ambient — looped weather + diurnal beds (rain/storm/wind, birds/night),
//               diffed each poll and faded in/out. Storm also fires periodic
//               thunder one-shots. EVERY file is optional: a missing clip simply
//               never plays (onloaderror no-ops), so a fresh checkout is silent
//               where clips are absent rather than broken.
//   * voice   — one-shot NPC TTS clips (base64 mp3 from /api/voice), played on
//               their own volume channel after a reply renders.
//
// Browsers block autoplay until a user gesture, so nothing sounds until
// unlock() is called from the first click/keypress; the OST starts there.
import { Howl, Howler } from 'howler';

const BASE = '/assets/audio';

// Track slugs as laid down by backend/tools/setup_assets.py (Ivan Duch OST).
const PEACEFUL = ['small-town-feeling', 'emonds-field', 'elven-town', 'eldemmors-market', 'trading-harbor'];
const OMINOUS = ['old-nights', 'tuathaan'];

// Low default channel volumes — the OST sits under the simulation, never over it.
// Music is kept gentle by default (it resets to this on every reload, so an
// over-loud default is jarring); raise it from the Sound settings if you want.
const DEFAULT_VOLUMES = { music: 0.12, ambient: 0.5, voice: 1.0, sfx: 0.5 };

const MUSIC_FADE_MS = 2200;
const AMBIENT_FADE_MS = 1500;
const THUNDER_MIN_MS = 9000;
const THUNDER_MAX_MS = 22000;

// Footsteps: one clip, replayed per accepted player step. Rate-limited so a held
// arrow key (OS key-repeat) can't machine-gun it, with per-step pitch jitter so
// repeated steps don't sound mechanical. The clip the user dropped lives in the
// ambient folder; a missing file no-ops like every other layer.
const FOOTSTEP_SRC = `${BASE}/ambient/footsteps.mp3`;
const FOOTSTEP_MIN_MS = 120;
// The clip is a long (~7s) footsteps recording, so each step plays only a short
// slice of it (a Howler sprite) instead of the whole file — otherwise rapid
// steps stacked full-length copies into a clicking drone. Tune to one step.
const FOOTSTEP_SLICE_MS = 320;
// Tile-flavored gain: crisper on hard ground, softer on grass/dirt.
const HARD_TILES = new Set(['stone_path', 'building_floor', 'building_wall']);

function shuffle(list) {
  const out = list.slice();
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

// time_of_day from the backend is one of dawn/morning/afternoon/dusk/night.
// Only true night flips the world to its ominous register.
function isNight(timeOfDay) {
  return timeOfDay === 'night';
}

// The ambient layer keys the current weather + time should be playing. Storm
// stacks heavy rain over the diurnal bed; clear weather adds nothing.
function desiredAmbientLayers(weather, timeOfDay) {
  const layers = new Set();
  if (weather === 'rain') layers.add('rain');
  else if (weather === 'storm') layers.add('storm');
  else if (weather === 'fog') layers.add('wind');
  layers.add(isNight(timeOfDay) ? 'night' : 'birds');
  return layers;
}

export class AudioManager {
  constructor() {
    this.unlocked = false;
    this.masterMuted = false;
    // Master gain across every channel (Howler global volume), independent of
    // the per-channel music/ambient/voice volumes that multiply under it.
    this.masterVolume = 1.0;
    this.volumes = { ...DEFAULT_VOLUMES };

    // Music state.
    this.musicHowl = null;
    this.musicPool = [];
    this.musicIndex = 0;
    this.musicNight = null; // last pool register actually playing

    // Ambient state: key -> Howl (looping). Plus the storm thunder timer.
    this.ambientLayers = new Map();
    this.thunderTimer = null;
    this.thunderHowl = null;

    // Voice channel: the currently-playing clip (replaced on each new line), plus
    // a tiny pub/sub so the UI can show an NPC "speaking" indicator while a voice
    // clip plays.
    this.voiceHowl = null;
    this.voiceActive = false;
    this.voiceListeners = new Set();

    // Footstep SFX: a single preloaded Howl, one short-slice instance at a time.
    this.footstepHowl = null;
    this.footstepReady = false;
    this.lastFootstepAt = 0;
    this.footstepId = null;

    // Last payload signals, so unlock() can start with the correct register and
    // update() can diff against the previous poll.
    this.lastTimeOfDay = 'dawn';
    this.lastWeather = 'clear';
  }

  // --- lifecycle ----------------------------------------------------------
  // Called on the first user gesture (browsers block autoplay before one).
  unlock() {
    if (this.unlocked) return;
    this.unlocked = true;
    // Guarded: if the context is blocked/interrupted, starting audio must not
    // throw into the caller (the title splash) and leave the game un-started.
    try {
      Howler.volume(this.masterVolume); // honor a master volume set before unlock
      Howler.mute(this.masterMuted);
      this._ensureFootsteps(); // preload so the first step isn't silent
      this._startMusicPool(isNight(this.lastTimeOfDay));
      this._syncAmbient(this.lastWeather, this.lastTimeOfDay);
    } catch (error) {
      // The game is fully playable without audio; a later update() retries/resumes.
    }
  }

  // React to a fresh RenderPayload. Cheap and idempotent: it only acts when the
  // register or weather actually changed, so it is safe to call every poll.
  update(payload) {
    if (!payload) return;
    const timeOfDay = payload.time_of_day ?? this.lastTimeOfDay;
    const weather = payload.weather ?? this.lastWeather;
    const flipped = isNight(timeOfDay) !== isNight(this.lastTimeOfDay);
    this.lastTimeOfDay = timeOfDay;
    this.lastWeather = weather;
    if (!this.unlocked) return;

    // Every Web Audio touch below is guarded. Starting a screen-share that
    // captures this tab's audio (or an output-device change) can suspend or
    // interrupt the AudioContext, after which Howler calls throw. Audio is
    // best-effort (Day 9), so a struggling audio layer must NEVER propagate into
    // the game's poll/render loop (an earlier version let this blank the world to
    // EMPTY_STATE every 200ms while sharing audio).
    try {
      this.recover(); // resume a suspended context + restart the OST if it dropped
      // Day<->night flip: crossfade the OST to the other pool.
      if (flipped && this.musicNight !== isNight(timeOfDay)) {
        this._startMusicPool(isNight(timeOfDay));
      }
      this._syncAmbient(weather, timeOfDay);
    } catch (error) {
      // Interrupted context / device change mid-call: ignore and retry next poll.
    }
  }

  // Recover audio after an interruption - notably when a screen-share starts
  // capturing this tab's audio, which suspends the AudioContext and PAUSES the
  // HTML5-streamed OST. Safe to call from the poll loop OR a user gesture: a
  // gesture-context resume succeeds even when the browser blocks a gesture-less
  // one, so calling this on the player's keypresses makes audio self-heal almost
  // instantly instead of needing a manual mute/unmute. Idempotent and guarded.
  recover() {
    if (!this.unlocked) return;
    try {
      const ctx = Howler.ctx;
      if (ctx && ctx.state !== 'running') {
        ctx.resume().catch(() => {});
      }
      // The OST streams via an HTML5 <audio> element; resuming the context does
      // NOT un-pause that element, so nudge it back once the context is running.
      if (ctx && ctx.state === 'running' && this.musicHowl && !this.musicHowl.playing()) {
        this.musicHowl.play();
      }
    } catch (error) {
      // never throws into the caller (poll loop or gesture handler)
    }
  }

  // --- channel controls ---------------------------------------------------
  setMasterMute(muted) {
    this.masterMuted = muted;
    Howler.mute(muted); // global; per-channel volumes are preserved underneath
  }

  toggleMasterMute() {
    this.setMasterMute(!this.masterMuted);
    return this.masterMuted;
  }

  // Master volume: a single global gain over every channel (Howler.volume),
  // separate from mute and from the per-channel sliders. Works before unlock —
  // unlock() re-applies it when audio starts.
  setMasterVolume(value) {
    const vol = Math.max(0, Math.min(1, value));
    this.masterVolume = vol;
    Howler.volume(vol);
  }

  getMasterVolume() {
    return this.masterVolume;
  }

  setVolume(channel, value) {
    const vol = Math.max(0, Math.min(1, value));
    this.volumes[channel] = vol;
    if (channel === 'music' && this.musicHowl) this.musicHowl.volume(vol);
    if (channel === 'ambient') {
      this.ambientLayers.forEach((howl) => howl.volume(vol));
      if (this.thunderHowl) this.thunderHowl.volume(Math.min(1, vol + 0.2));
    }
    if (channel === 'voice' && this.voiceHowl) this.voiceHowl.volume(vol);
    if (channel === 'sfx' && this.footstepHowl) this.footstepHowl.volume(vol);
  }

  getVolume(channel) {
    return this.volumes[channel];
  }

  // --- music --------------------------------------------------------------
  _startMusicPool(night) {
    this.musicNight = night;
    this.musicPool = shuffle(night ? OMINOUS : PEACEFUL);
    this.musicIndex = 0;
    this._playMusicTrack(this.musicPool[0], { crossfade: true });
  }

  _playMusicTrack(slug, { crossfade }) {
    if (!slug) return;
    const previous = this.musicHowl;
    const target = this.volumes.music;
    const next = new Howl({
      src: [`${BASE}/music/${slug}.mp3`],
      html5: true, // stream multi-MB tracks instead of decoding them whole
      volume: 0,
      onend: () => this._advanceMusic(),
      onloaderror: () => {
        // A missing/unplayable track must not stall the pool — skip onward.
        if (this.musicHowl === next) this._advanceMusic();
      }
    });
    this.musicHowl = next;
    next.play();
    next.fade(0, target, crossfade ? MUSIC_FADE_MS : 800);
    if (previous) {
      previous.fade(previous.volume(), 0, MUSIC_FADE_MS);
      previous.once('fade', () => previous.unload());
    }
  }

  _advanceMusic() {
    if (this.musicPool.length === 0) return;
    this.musicIndex += 1;
    if (this.musicIndex >= this.musicPool.length) {
      // Pool exhausted: reshuffle the same register for fresh ordering.
      this.musicPool = shuffle(this.musicNight ? OMINOUS : PEACEFUL);
      this.musicIndex = 0;
    }
    this._playMusicTrack(this.musicPool[this.musicIndex], { crossfade: true });
  }

  // --- ambient ------------------------------------------------------------
  _syncAmbient(weather, timeOfDay) {
    const desired = desiredAmbientLayers(weather, timeOfDay);

    // Fade out layers no longer wanted.
    this.ambientLayers.forEach((howl, key) => {
      if (!desired.has(key)) {
        howl.fade(howl.volume(), 0, AMBIENT_FADE_MS);
        howl.once('fade', () => howl.unload());
        this.ambientLayers.delete(key);
      }
    });

    // Fade in newly-wanted layers (missing files no-op via onloaderror).
    desired.forEach((key) => {
      if (!this.ambientLayers.has(key)) this._startAmbientLayer(key);
    });

    // Storm-only thunder one-shots.
    if (desired.has('storm')) this._startThunder();
    else this._stopThunder();
  }

  _startAmbientLayer(key) {
    const target = this.volumes.ambient;
    const howl = new Howl({
      src: [`${BASE}/ambient/${key}.mp3`],
      loop: true,
      volume: 0,
      html5: false,
      onloaderror: () => {
        // CC0 clip not dropped in yet — silently forget this layer.
        this.ambientLayers.delete(key);
        howl.unload();
      }
    });
    this.ambientLayers.set(key, howl);
    howl.play();
    howl.fade(0, target, AMBIENT_FADE_MS);
  }

  _startThunder() {
    if (this.thunderTimer) return;
    const fire = () => {
      const clap = new Howl({
        src: [`${BASE}/ambient/thunder.mp3`],
        volume: Math.min(1, this.volumes.ambient + 0.2),
        onloaderror: () => clap.unload(),
        onend: () => clap.unload()
      });
      this.thunderHowl = clap;
      clap.play();
      const wait = THUNDER_MIN_MS + Math.random() * (THUNDER_MAX_MS - THUNDER_MIN_MS);
      this.thunderTimer = window.setTimeout(fire, wait);
    };
    // First clap after a short, randomised beat so a storm doesn't open on one.
    this.thunderTimer = window.setTimeout(fire, THUNDER_MIN_MS + Math.random() * 4000);
  }

  _stopThunder() {
    if (this.thunderTimer) {
      window.clearTimeout(this.thunderTimer);
      this.thunderTimer = null;
    }
  }

  // --- footsteps ----------------------------------------------------------
  _ensureFootsteps() {
    if (this.footstepHowl) return;
    this.footstepHowl = new Howl({
      src: [FOOTSTEP_SRC],
      volume: this.volumes.sfx,
      // A short slice sprite so each step is one footstep, not the whole clip.
      sprite: { step: [0, FOOTSTEP_SLICE_MS] },
      onload: () => { this.footstepReady = true; },
      onloaderror: () => { this.footstepReady = false; } // missing clip -> no-op
    });
  }

  // Play one footstep for an accepted player step on the given tile type.
  // Rate-limited, and only ONE instance plays at a time (the previous is stopped
  // first) so rapid steps can't stack the long clip over itself into a clicking
  // drone. Silent until unlocked and until the clip has loaded.
  playFootstep(tileType) {
    if (!this.unlocked) return;
    // CRITICAL: this runs from the movement key handler BEFORE the move intent is
    // posted. It must never throw, or the throw would skip sendInput(move) and
    // the step would never reach the backend (the player teleports back). Web
    // Audio can throw if the context was interrupted by screen-share audio
    // capture, so the whole body is guarded - a missing footstep is fine, a
    // dropped move is not.
    try {
      this._ensureFootsteps();
      if (!this.footstepReady) return;
      const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      if (now - this.lastFootstepAt < FOOTSTEP_MIN_MS) return;
      this.lastFootstepAt = now;
      if (this.footstepId !== null) this.footstepHowl.stop(this.footstepId);
      const id = this.footstepHowl.play('step');
      this.footstepId = id;
      const gain = HARD_TILES.has(tileType) ? 1.0 : 0.72;
      this.footstepHowl.volume(this.volumes.sfx * gain, id);
      this.footstepHowl.rate(0.92 + Math.random() * 0.16, id); // subtle pitch jitter
    } catch (error) {
      // best-effort: a footstep must never interrupt player movement
    }
  }

  // --- voice --------------------------------------------------------------
  // Play one NPC line from a base64 clip (from /api/voice). The format comes
  // from the backend — mp3 (Azure Speech) or wav (Realtime). Replaces any clip
  // still playing so a new reply never overlaps the previous one.
  // Subscribe to voice-playing state changes (true while an NPC clip plays).
  // Returns an unsubscribe function. Lets the dialogue glow the speaking avatar.
  onVoice(callback) {
    this.voiceListeners.add(callback);
    return () => this.voiceListeners.delete(callback);
  }

  _setVoiceActive(active) {
    if (this.voiceActive === active) return;
    this.voiceActive = active;
    this.voiceListeners.forEach((cb) => {
      try { cb(active); } catch (error) { /* a bad listener never breaks audio */ }
    });
  }

  playVoiceBase64(audioB64, format = 'mp3') {
    if (!audioB64) return;
    try {
      if (this.voiceHowl) {
        this.voiceHowl.stop();
        this.voiceHowl.unload();
        this.voiceHowl = null;
      }
      const fmt = format === 'wav' ? 'wav' : 'mp3';
      const mime = fmt === 'wav' ? 'audio/wav' : 'audio/mp3';
      const howl = new Howl({
        src: [`data:${mime};base64,${audioB64}`],
        format: [fmt],
        volume: this.volumes.voice,
        onplay: () => this._setVoiceActive(true),
        onend: () => { this._setVoiceActive(false); howl.unload(); },
        onstop: () => this._setVoiceActive(false),
        onloaderror: () => { this._setVoiceActive(false); howl.unload(); }
      });
      this.voiceHowl = howl;
      howl.play();
    } catch (error) {
      // best-effort voice playback; never affects the dialogue flow
      this._setVoiceActive(false);
    }
  }
}

// One shared manager for the whole app (audio is inherently a singleton).
export const audioManager = new AudioManager();
