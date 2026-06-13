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

// Fetched exactly ONCE when the player opens the map overlay - never in the
// 500ms state poll. The continent is generated once and cached by the backend.
export async function getContinent() {
  const response = await fetch('/api/continent');
  if (!response.ok) {
    throw new Error(`Failed to load continent: ${response.status}`);
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