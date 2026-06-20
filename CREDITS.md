# Credits

*Chronicle of the Velvet Lies* is built on freely-licensed third-party assets.
This file records their authors. Audio and art files are not committed to the
repository (they are regenerated locally by `chronicle/backend/tools/setup_assets.py`),
so this is the canonical record of where they came from.

## Music — Ivan Duch

The day/night original soundtrack is composed by **Ivan Duch**
(<https://ivanduch.com/>), used under his free-music license. Seven tracks back
the world, split into a day pool and a night pool:

**Peaceful (day):**
- Dragon Tales 1 — Small Town Feeling → `small-town-feeling.mp3`
- Two Rivers Tales — Emond's Field → `emonds-field.mp3`
- Venture Forth, Chapter 3 — Elven Town → `elven-town.mp3`
- Venture Forth, Chapter 2 — Eldemmor's Market → `eldemmors-market.mp3`
- Pirates — Givmaru Trading Harbor → `trading-harbor.mp3`

**Ominous (night):**
- Vampires — Old Nights → `old-nights.mp3`
- Two Rivers Tales — Tuatha'an → `tuathaan.mp3`

The slugged copies live under `chronicle/frontend/public/assets/audio/music/`
and are produced from the CHRONICLE-root source tracks by `setup_assets.py`.

## Ambient SFX — CC0

Weather and diurnal ambience (`chronicle/frontend/public/assets/audio/ambient/`)
uses CC0 clips sourced from Pixabay / OpenGameArt. Expected filenames:
`rain.mp3`, `storm.mp3`, `wind.mp3`, `birds.mp3`, `night.mp3`, `thunder.mp3`.
Missing files no-op gracefully — drop replacements in to enable each layer.

## NPC Voices — Azure Speech

NPC dialogue is voiced at runtime by Microsoft Azure Cognitive Services Speech
(en-GB neural voices). No audio is bundled; the backend mediates synthesis so
the subscription key never reaches the client.

## Art

- **Pixel Crawler — Free Pack** (character/entity sprites)
- **Kenney — Medieval RTS** (structures, environment, RTS spritesheet)
- **The Fan-tasy Tileset (Free)** by Jamie Brownhill (buildings, props, tiles)
