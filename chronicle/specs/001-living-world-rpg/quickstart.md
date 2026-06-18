# Quickstart: Living World RPG Simulation

## Prerequisites

- **Python 3.12** (the backend venv is managed with `uv`).
- **Node 18+** for the Vite frontend.
- **Ollama** running locally with a chat model pulled, for NPC conversation:
  ```powershell
  ollama pull qwen2.5:1.5b-instruct   # demo default (fast)
  # optional: qwen2.5:3b-instruct (better), qwen3:4b (best local)
  ```
  Without Ollama everything still runs; Tier-1 NPCs just fall back to stub replies.

## Backend (port 8000)

```powershell
cd chronicle/backend
# first time: create the venv + install deps
uv venv
uv pip install -r requirements.txt
# run (serves the API, and the built frontend at / if frontend/dist exists)
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

The world generates once on first start and is reopened (never regenerated) on
later starts. The conversation model is a one-line swap in
`backend/systems/conversation.py` (`MODEL = ...`).

## Frontend (port 5173)

```powershell
cd chronicle/frontend
npm install
npm run dev
```

Open **http://localhost:5173** (the dev server proxies `/api` to port 8000).

## Optional: Azure OpenAI provider

Put credentials in `chronicle/.env` (gitignored; never commit a key):

```
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

Restart the backend; the HUD's **LLM: … [switch]** button then toggles
local ⇄ Azure live, showing each provider's last-reply latency.

## Tests

```powershell
cd chronicle/backend
.venv\Scripts\python.exe -m pytest        # 124 passing
```

## Demo Checks (validation)

- **World is alive:** `/api/state` returns a populated payload; NPCs move, the
  clock and weather advance with no player input.
- **Fog of war:** only a radius around the host NPC is visible; walking reveals
  new tiles (they persist across restarts); `R` toggles reveal-all.
- **Continent map:** press **M** — colored biomes/countries, rivers, capitals,
  and the "Aldenmoor — you are here" pin; hover a country for stats.
- **Conversation + memory:** click a Tier-1 NPC, talk twice — it stays in
  character and references earlier context. The HUD shows the active LLM provider
  and last-reply latency.
- **Save/load:** stop the backend, restart, reload — day/hour, fog, factions,
  rumors, and Demon-Lord history are identical (the world is never regenerated).
- **ML reacts on cue:** open **Debug controls** → adjust a faction or talk to its
  NPCs → **Trigger dawn** → that faction's reputation drifts, relationships shift,
  and rumors spread/distort (notifications + HUD numbers move).
- **Antagonist:** the Demon Lord posts a daily decision and erodes faction morale
  (distinct from your standing).
