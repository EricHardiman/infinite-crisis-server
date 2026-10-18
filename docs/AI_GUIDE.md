# Guide for AI assistants (and new contributors)

This project is a private server for the Infinite Crisis client, built for preservation. Read this page first;
it says where everything is and the rules that keep the project shareable.

## Ground rules

1. **Never commit or ship game files**: no `.rp` packs, no `.exe`, no images, no extracted game texts
   (descriptions, dialogue). IDs, short names and numbers are fine; they are what the catalog holds.
2. **The ID is the key.** The client only understands the game's own IDs (DIDs). Look an ID up before using it,
   and assign things by ID (config values may also accept a catalog name).
3. **Every discovery is recorded in three places**:
   - the catalog table it belongs to (`catalog/data/*.tsv`), with a short English description and a
     `server_status`;
   - `docs/reverse-engineering.md` for how it works (addresses, layouts, evidence);
   - `docs/CHANGELOG.md` for when and why it changed.
   Then run `python ic.py catalog` to rebuild `catalog/index.html`.
4. Everything in the repository is written in English.

## Where to look

| Question | Where |
|---|---|
| What is ID `0x...`? | `python ic.py find 0x...` (searches every catalog table) or `catalog/index.html` |
| Champions, skills, Stolen Powers, artifacts, amplifiers, stages | `catalog/data/` (`champions.tsv`, `skills.tsv`, `stolen_powers.tsv`, `artifacts.tsv`, `amplifiers.tsv`, `stages.tsv`) |
| World objects, characters, animations, effects, cinematics, conversations | `catalog/data/` (`world_objects.tsv`, `characters.tsv`, `animations.tsv`, `vfx.tsv`, `cinematics.tsv`, `conversations.tsv`) |
| Property ids and their value kinds | `catalog/data/properties.tsv` (`kind_code` is what the record / wire readers need) |
| Network events | `catalog/data/network_events.tsv`; byte layouts in `icserver/messages.py`, `icserver/scorecard.py` |
| How a system works (HUD, rewards, replay, props, minimap...) | `docs/reverse-engineering.md` |
| History of every change and test result | `docs/CHANGELOG.md` |
| What works, which maps the install has, what is missing | `docs/FINDINGS.md` |
| Exe patches | `icserver/patcher.py`, `catalog/data/exe_patches.tsv` |
| Reading game data from an install | `icserver/gamedata.py` (`Game(rp_dir).record(did)`, `.text(...)`), `icserver/rp.py` |

## Common tasks

- **Assign a Stolen Power to D/F:** `[tutorial] camera_skill` / `strength_skill` in `config.toml`, a DID or a
  name from `python ic.py stolen-powers`.
- **Program a champion's skills outside the tutorial:** add an entry to `KITS` in `icserver/kits.py` (slot ->
  graph events, scriptlet names, effect and numbers; names are resolved from pack 0xA0000038), then add a test
  like `tests/test_kits.py`. Numbers can be overridden with `[combat] kits` in `config.toml`.
- **A map with the champion select:** `[match] maps "<encounter>" "lobby"` (and `"free"` for free play) in
  `icserver/config.py`; see Coast City v AI `0x40000B6A`.
- **Change an exe patch:** edit `icserver/patcher.py`, run `python tests/test_patcher_layout.py <exe>`, then the
  user runs `python ic.py patch`.
- **Refresh the catalog from a full install:** `python ic.py catalog --scan` (packs, every champion's skills,
  artifacts, amplifiers), then commit `catalog/`.
- **Check a record's contents:** `icserver.gamedata.Game(rp_dir).record(0x48000615)` returns
  `[(key, kind, value)]`; strings are `(token, table)` pairs, `Game.text()` turns them into English.

## Status values

`implemented` (the server makes it work), `shown only` (visible, no behaviour), `sent` / `handled` /
`ignored` (protocol), `off` (supported but disabled), `data only` (ID known, nothing written yet),
`not started`.
