# Game ID catalog

`catalog/index.html` is a single page (open it from disk or publish it with GitHub Pages) with every game ID
the server works with: champions, skills, Stolen Powers, artifacts, amplifiers, stages, and an engine
reference (skill slots, properties, network events, scriptlets, HUD elements, data packs, exe patches).

**The ID is the key.** The client only understands the game's own IDs (DIDs, e.g. `0x48000808`), so things
are assigned by ID; names are only for finding them. Config values that name a Stolen Power accept either
(`strength_skill = "0x48000A3B"` or `"Super Strength / Superman"`).

## Files

| Path | What |
|---|---|
| `data/*.tsv` | The tables (tab-separated, first row = column names). This is the source of truth; tools and AIs should read these. |
| `template.html` | The page design. `/*__CATALOG__*/null` is replaced by the data. |
| `index.html` | Generated: `python tools/build_catalog.py` (or `python ic.py catalog`). Do not edit by hand. |

Some tables are refreshed from the project's own sources on every build:

| Table | Source |
|---|---|
| `champions.tsv` | `data/champions.json` (local only; the TSV is what is committed) |
| `stolen_powers.tsv` | `data/stolen_powers.tsv`, plus targeting / script from `data/stolen_powers.json` (`python ic.py stolen-powers`) |
| `scriptlets.tsv` | `data/batman_actions.tsv` |
| `hud_elements.tsv` | `icserver/tutorial1.py` (`HUD`) |
| `exe_patches.tsv` | `icserver/patcher.py` (`PATCHES`) |

The rest (`stages`, `skills`, `skill_slots`, `properties`, `network_events`, `packs`, `artifacts`,
`amplifiers`) are edited by hand.

## Conventions

- IDs in hex, `0x` + 8 upper-case digits. A skill inside a champion's skill set is `set:slot`
  (`0x48000615:1` = Gaslight Batman's Q).
- ID prefixes: `0x40` entity / variant, `0x48` / `0x49` data records, `0x2E` world state, `0x13` image,
  `0x10` property or scriptlet key, `0x1D` template, `0x2B` string table, `0x34` script, `0x35` cinematic,
  `0xA0` data pack.
- `server_status`: `implemented` (the server makes it work), `shown only`, `sent` / `handled` (protocol),
  `data only` (the ID is known, behaviour not written yet), `not started`.
- **Only IDs, names and relationships go here.** No game files, images, or texts extracted from the game.

## Recording a discovery

Every new finding goes into the table it belongs to (with a short English description and a `server_status`),
into `docs/reverse-engineering.md` (how it works) and into `docs/CHANGELOG.md` (when it changed). Then
rebuild the page. `docs/AI_GUIDE.md` explains this for AI assistants.

## Scanning a full install

`python ic.py catalog --scan` reads the player's `rp\` folder (`tools/catalog_scan.py`) and refreshes
`packs.tsv`, `skills.tsv` (every champion's skill set), `artifacts.tsv`, `amplifiers.tsv` and
`item_stats.tsv`. Hand-written notes for packs and skills live in `packs_notes.tsv` and `skills_notes.tsv`
and are merged in.

## Known inconsistencies (to resolve)

- Carrier slot 1: `config.py` uses `0x400004FD`, `patcher.PROP_CARRIERS_DEFAULT` still has `0x40000289`.
- Bat Scream width: 3 m in `batman.py` and the docs, `r_width = 4.0` in `config.py`.
- Bridge car: `bridge.VEHICLE_WS` is `0x2E000AAB`, the config default is `0x2E00034E`.
- Melee drone: the tutorial pack maps `0x2E001167` to `0x40000C72`; the server sends `0x40000A5C`.
- Throw objective token: `0x029BF934` (docs) vs `0x03DBF934` (`finale.py` comment).
- Sphere record `0x1D000789`: `finale.py` uses it for the sphere; cinematic `0x35000025` uses it for the Gate actor.
- Some numbers mean different things in different name tables (e.g. `0x1000003D` is the skill targeting
  property and also `CbtState_KnockUp`); always say which table an ID comes from.

## Roadmap

| Phase | State |
|---|---|
| 0. Conventions, page, documentation rule | done |
| 1. Pack map (`packs.tsv`) | done: 616 packs, 68,900 records, 309 with English text tables |
| 2. Property dictionary (`properties.tsv`, 3,822 ids with kinds) | done; meanings filled as found |
| 3. Game texts (`icserver/gamedata.py`, English string tables) | reader done (used for names; texts stay local) |
| 4. Champions | IDs, variants, skill sets, costumes done; base stats still unknown (champion record) |
| 5. Skills | done: 258 skills of the 43 champions + the 2 implemented Stolen Powers |
| 6. Artifacts and amplifiers | done (228 artifacts, 162 augments, 172 mods) |
| 7. World (objects, characters, animations, effects, cinematics, conversations) | first pass done |
| 8. Network events | done (95) |
| 9. Search (`ic.py find`) and `docs/AI_GUIDE.md` | done |
| 10. Validation (`tests/test_catalog.py`) | done |
