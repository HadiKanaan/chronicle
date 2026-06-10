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

export async function getLog() {
  const response = await fetch('/api/log');
  if (!response.ok) {
    throw new Error(`Failed to load log: ${response.status}`);
  }
  return response.json();
}