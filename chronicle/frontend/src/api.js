export async function getState() {
  const response = await fetch('/api/state');
  if (!response.ok) {
    throw new Error(`Failed to load state: ${response.status}`);
  }
  return response.json();
}

export async function sendInput(input) {
  const response = await fetch('/api/input', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(input)
  });
  if (!response.ok) {
    throw new Error(`Failed to send input: ${response.status}`);
  }
  return response.json();
}

export async function generateWorld() {
  const response = await fetch('/api/generate-world', {
    method: 'POST'
  });
  if (!response.ok) {
    throw new Error(`Failed to generate world: ${response.status}`);
  }
  return response.json();
}

export async function getNPCs() {
  const response = await fetch('/api/npcs');
  if (!response.ok) {
    throw new Error(`Failed to load NPCs: ${response.status}`);
  }
  return response.json();
}

export async function getConversationContext(npcId) {
  const response = await fetch(`/api/conversation/${encodeURIComponent(npcId)}`);
  if (!response.ok) {
    throw new Error(`Failed to load conversation context: ${response.status}`);
  }
  return response.json();
}

export async function sendConversation(npcId, playerText) {
  const response = await fetch('/api/conversation', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ npc_id: npcId, player_text: playerText })
  });
  if (!response.ok) {
    throw new Error(`Failed to send conversation: ${response.status}`);
  }
  return response.json();
}

// Day 9: fetch an NPC line's TTS audio AFTER the reply text has rendered. The
// backend mediates Azure Speech so the key never reaches here; it returns
// { voiced: true, audio_b64, format } or { voiced: false } when unavailable or
// disabled. Never throws on a non-2xx — a voice outage is a silent non-event.
export async function sendVoice(npcId, text) {
  try {
    const response = await fetch('/api/voice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ npc_id: npcId, text })
    });
    if (!response.ok) {
      return { voiced: false };
    }
    return response.json();
  } catch (error) {
    return { voiced: false };
  }
}

// Fetched exactly ONCE when the player opens the map overlay - never in the
// 500ms state poll. The continent is generated once and cached by the backend.
export async function getContinent() {
  const response = await fetch('/api/continent');
  if (!response.ok) {
    throw new Error(`Failed to load continent: ${response.status}`);
  }
  return response.json();
}

// Demo/debug controls (set time, trigger a dawn tick, set faction scores).
export async function sendDebug(action, payload = {}) {
  const response = await fetch('/api/debug', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, payload })
  });
  if (!response.ok) {
    throw new Error(`Debug command failed: ${response.status}`);
  }
  return response.json();
}

export async function getLog() {
  const response = await fetch('/api/log');
  if (!response.ok) {
    throw new Error(`Failed to load log: ${response.status}`);
  }
  return response.json();
}