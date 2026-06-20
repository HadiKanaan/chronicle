# Chronicle of the Velvet Lies

A **backend-authoritative living-world RPG simulation** — a medieval town that runs
itself with ~13 machine-learning models and a **local LLM**, where you inherit a
villager's life, talk to people who *remember* you, and watch an emergent narrative
unfold. Everything runs **on-device, no cloud required**.

> **The project lives in [`chronicle/`](chronicle/).** Start there:
> - 📖 **[chronicle/README.md](chronicle/README.md)** — full overview, architecture, ML layer, and setup/run instructions
> - 🧭 **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** — a presentation-oriented briefing (and slide outline)
> - 🚀 **[chronicle/specs/001-living-world-rpg/quickstart.md](chronicle/specs/001-living-world-rpg/quickstart.md)** — step-by-step quickstart

## Quick start

```bash
# Backend
cd chronicle/backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m uvicorn main:app --port 8000

# Frontend (second terminal)
cd chronicle/frontend
npm install && npm run dev      # http://localhost:5173
```

A local [Ollama](https://ollama.com) with a Qwen model enables in-character
conversation; without it, NPCs use rule-based fallbacks and everything else still
runs. See [chronicle/README.md](chronicle/README.md) for assets, voices, controls,
and tests.

## Stack

Python · FastAPI · SQLite · scikit-learn · local Qwen LLM (Ollama) · React + Vite ·
Howler.js. Backend is the single source of truth; the frontend is a dumb renderer.

## Tech tree

- **World** — procedurally generated town (Aldenmoor), ~80 NPCs in 3 tiers, 4 factions, fog of war, an ML-generated continent map.
- **AI/ML** — 13 of 14 scikit-learn models (biome/behavior/mood/weather/sentiment/rumor/relationship/faction/…) + TF-IDF RAG memory.
- **LLM** — local conversations grounded in persistent memory, mood, and rumors; a schema-constrained Demon-Lord antagonist.
- **Emergence** — rumor propagation + distortion, faction dynamics, and dynamic NPC personhood (talk to someone enough and they become "real").
- **Presentation** — full-screen pixel-art camera, diegetic HUD, minimap, day/night OST, ambient weather, and NPC voices.

_Music by Ivan Duch. Built with Spec-Kit, day by day._
