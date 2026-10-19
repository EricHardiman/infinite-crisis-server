# CLAUDE.md — Infinite Crisis preservation server

Read this first, then `docs/HANDOFF.md` (current state and pending work), `docs/FINDINGS.md` (what works, which
maps the install has, what is missing) and `docs/AI_GUIDE.md` (where everything is). Everything in the repository is written in **English**.

## Working with the user

- **Reply to the user in Spanish.** Code, comments, docs, commit messages and the catalog stay in English.
- The user tests in the real game client on this Windows machine and sends back `logs\server.log`,
  `logs\traffic.log`, `logs\unhandled.log` and, when asked, `logs\diag.log` (from `python tools\diag.py ...`,
  run in a second console while the game is open). Screenshots describe what is wrong on screen.
- Never ask the user to do something you can check yourself in the code, the logs or the catalog.

## Hard rules

1. **Never distribute game files**: no `.rp`, no `.exe`, no images, no extracted game texts (descriptions,
   dialogue). IDs, short names and numbers are fine (they make up the catalog).
2. Do not commit: `data/champions.json`, `data/progress.json`, `data/stolen_powers.json`, `data/game_cache.json`, `keys/*.pem`,
   `data/texcache/`, `data/social.json`, `logs/*`, `config.toml`, `__pycache__/`, `*.pyc` (see `.gitignore`).
3. **Every discovery is recorded in three places**: the right catalog table (`catalog/data/*.tsv`, with a short
   English description and a `server_status`), `docs/reverse-engineering.md` (how it works, addresses,
   evidence) and `docs/CHANGELOG.md` (a new `## fase3-xx` entry per build: what the tester reported, what changed,
   config keys). Then `python ic.py catalog` to rebuild `catalog/index.html`.
4. Every behaviour change gets a `config.py` default with a comment (date/time of the tester's report and why), so
   it can be switched back from `config.toml`.
5. Exe patches live in `icserver/patcher.py` (original and new bytes are checked); after changing them the user
   must run `python ic.py patch`.

## Layout

| Path | What |
|---|---|
| `ic.py` | CLI: `doctor`, `patch`, `server`, `play` (opens the chosen interface), `app`, `legacy`, `sounds`, `worlds`, `catalog [--scan]`, `find <text or ID>`, `stolen-powers [text]`, `layout`, `variants`, `entities`, `dump`, `carriers` |
| `icserver/session.py` | One login session: phases, lobby/loading, object creation, every client event handler (`HANDLERS` at the end), the Match class (champion bundle, ranks, Stolen Power slots) |
| `icserver/tutorial1.py` | Tutorial 1 part 1 (street), HUD ids, knockdown, props built on carriers, prop scriptlet tables |
| `icserver/bridge.py` | Part 2 (the bridge): camera (D), gates, Bat Scream, `start_at` shortcuts |
| `icserver/finale.py` | Part 3: Super Strength (lift / carry / throw / explosion), Destroyer, victory, match end |
| `icserver/batman.py`, `abilities.py` | Gaslight Batman's Q/W/E/R and cooldowns |
| `icserver/freeplay.py` | Free play on a champion-select map: levels / ranks, training drone, animation tour |
| `icserver/kits.py` | Skills of champions other than Gaslight Batman outside the tutorial (`KITS`; John Stewart first), `[combat] kits` overrides |
| `icserver/champion_fx.py` | Gaslight Batman's graph events and scriptlets for the lab's animation tour (`[debug] lab_tour`) |
| `icserver/net.py`, `log.py`, `scheduler.py` | Connection wrapper (send never raises), logging on a writer thread, per-match timers |
| `icserver/progress.py` | Progress kept between logins (`data/progress.json`: encounters completed, which unlocks Tutorial 2) |
| `icserver/messages.py`, `scorecard.py`, `wire.py` | Message builders and wire format |
| `icserver/skilldata.py`, `stolenpowers.py`, `cosmetics.py`, `roster.py`, `gamecache.py`, `gamedata.py`, `rp.py` | Reading the game data from the player's install (records, kinds, English strings, packs) |
| `icserver/webapp.py`, `textures.py`, `social.py`, `interface.py`, `winctl.py`, `emotes.py`, `webui/` | The companion app (`python ic.py app`, served on the SOAP port at `/app`, `/api/*`, `/tex/<did>.png`); pictures decoded from the install and cached in `data/texcache/` |
| `icserver/config.py` | Every setting with its default and the reason for it |
| `tools/diag.py` + `tools/tracer.py` | Breakpoint logger for the running client (`--scripts`, `--skills`, `--reward`, `--replay`, `--props`, ...) |
| `tools/tutorial_models.py` | Every model of Tutorial 1 and 2 -> `catalog/data/tutorial_models.tsv` (`ic.py tutorial-models`) |
| `tools/split_file.py` | Splits a big file (a video) into 300 MB parts so it can be sent to the cloud session |
| `tools/build_catalog.py`, `tools/catalog_scan.py`, `tools/world_scan.py` | The ID catalog page, the full-install scanner and the world-state inventory (`ic.py worlds`) |
| `catalog/` | `data/*.tsv` (source of truth) and the generated `index.html` |
| `docs/` | `reverse-engineering.md`, `CHANGELOG.md`, `FINDINGS.md`, `AI_GUIDE.md`, `HANDOFF.md`, `re-notes/` (raw static-analysis notes with exe addresses) |

## Testing

- `python tests\test_catalog.py` — catalog tables are well formed.
- `python tests\test_patcher_layout.py [InfiniteCrisis.exe]` — no two exe patches overlap; with the exe, the
  whole patch applies (run it after every change to `patcher.py`).
- `python tests\test_e2e.py tests\e2e.example.toml` (178 checks) and `python tests\test_jump.py tests\e2e.example.toml`
  (24), `tests\test_lab.py` (10, real packs; 9 with `lab_tour = "batman"` and a small `champion_tour_interval`), `tests\test_collections.py` (12), `tests\test_lobby.py` (19, champion select + free play), `tests\test_kits.py` (16, John Stewart's Q W E R), `tests\test_movie_queue.py` (17) and `tests\test_app.py` (30) — a simulated client against the server; adjust the paths in the example config first. They use other
  ports than the real server.
- Then the user tests in the game. Build tags continue from `fase3-jr` (next: `fase3-js`).

## Facts that are easy to get wrong

- Never do heavy work (pack reading, decompression) on a thread while a match runs: the GIL starves the network
  threads (freezes, "server disconnected"). Do it before the ports open and cache it (`icserver/gamecache.py`).
- The folder layout: `icserver\ic.py` (run from here) and the package in `icserver\icserver\`. Package files next
  to `ic.py` are stray copies.

- Never hide a skills-bar element with 0x213D (event 2) other than the upgrade buttons / RecommendedText: it hides
  the whole skills bar.
- Never queue the player before the client sends its own JoinQueue at the end of the overview movie
  (`queue_on_movie_end`): it cuts the movie and the match has no dialogue audio (2026-10-16 16:23).
- roster.py: a cluster without a 0x52 sound bank is usually a costume (its variant is in champions.json's costume_info);
  only John Stewart is a real unreleased champion.
- roster.extend() appends the added champions after champions.json's: sorting them alphabetically among the
  others gives champions another champion's portrait (tester, 2026-10). Never sort the roster.
- A costume must never repeat its champion's own variant (the client loses the champion): `messages.costumes()`.
- Sounds: Wwise event ids are typed values of kind 0x2C in records; banks are 0x52 records (id = FNV-1 hash of the
  name). `python ic.py sounds` / catalog Sounds.
- Pack slots per category come from the exe table at VA 0x1600a40; zone packs (category 0xd) have 2 slots only
  with the fase3-gh patch, and the server sends `[match] event_packs` only if the exe has them.
- Server obstacle boxes are grown by Batman's 0.6 m radius; polygons are not (use a polygon for small props).
- Moving a prop entity with speed > 0 keeps it moving on the client until a bundle with speed 0 arrives; a carrier prop
  ignores speed-0 updates but follows updates with a speed > 0: move it with moving updates and end with a crawl
  (0.01 m/s); remove + create flickers. Between updates it moves along its heading: give it the direction of travel. Its height only comes from its
  creation: vertical motion (a fall, an arc) needs a new object per step (2026-10-17 15:44), but a new object fades
  in over a few hundred ms, so 30-100 ms steps are invisible (15:57).
- Two name tables: scriptlet keys (`0x33000000`, run with event `0x8D`) and animation-graph events (`0x300000A4`,
  raised with scriptlet `0x100001E3` + script variable `0x780` = event id). The same number means different things.
- A prop built on a carrier class (`0x4A......`) only accepts scriptlets if it gets its world state's templates
  (property `0x7D2` + graph `0x5B5`); they are read from the packs at server start.
- Skill stats: 3 = cost (Will, negative), 5 = damage, 15 = cooldown, 18 = range (probable).
- World state records: `did | 7 | .entity | 0 | count | entries`; other records: `did | 0 | count | entries`.
- `gamedata` reads only u32-sized values; vector properties (0x24E, 0x667, 0x4B9) stop it. Use
  `world_state(did, partial=True)` when only the first entries (such as 0x7D2) are needed.
- Some world states close the client ~3 s after being created on a carrier, bare or not (0x2E000F03-F05, EFE,
  61D-623, 296, and the meteor set pieces 872-877: tutorial1.MODEL_TOUR_CRASHES_BARE); never spawn them. They come
  in families sharing their first template; the lab's models tours skip the whole family (fase3-jq).
- Each map needs its own zone pack (category 0xd, two slots with the patch): `[match] maps` per encounter. Never send
  Tutorial 1's zone pack with another map.
- `catalog/data/tutorial_models.tsv` (python ic.py tutorial-models) lists every model of the two tutorials;
  `catalog/data/world_states.tsv` (python ic.py worlds) lists every world state with its model names and the packs it
  needs: look there first for a model. `stp_` names belong to Stolen Powers (pack 0xA00000B3, always loaded); the
  tutorial's falling meteors are nevertheless stp_meteor 0x2E000928 (tester 2026-10-17).
- The lab's default tour is `[debug] lab_tour = "models1"`: Tutorial 1's models from tutorial_models.tsv, bare,
  named in the objective text, with Tutorial 1's zone pack 0xA000024C in the second zone slot (fase3-jp).
  "models" = Tutorial 2's (fase3-jo); "batman" = the champion animation tour.
- Tutorial 2 (0x40000A81) is the model lab while its `[match] maps` entry has `"lab": true` (`Match.lab`, not
  `Match.tutorial`). A world state's 0x5B5 graph can sit after a vector property: read the raw triplet.
- A cinematic (0x35) creates its own actors from its record; an entity the server spawns with the same world state
  shows twice (the Destroyer, 2026-10-17 11:36). Spawn the server's copy when the cinematic ends.
- A scriptlet the champion's own table does not list (data/batman_actions.tsv) is dropped by the client: check it
  before sending (Vfx_Bmg_Active 0x10000180 and FX_Spawn_End 0x1000005A are not in Batman's, 2026-10-17 18:25).
  data/batman_actions.tsv names some keys from the graph-event table; name them from 0x33000000.
- Graph event ids: name table 0x300000A4 (pack 0xA0000038) stores `u32 id | u32 length | name`.
- Property 0x5B5 takes a graph SET (0x1C......), never a graph (0x1A......): a 0x1A there closed the client
  (2026-10-17 13:41).
- The phase pod 0x2E001157 has no graph set of its own; a borrowed one (0x1C0000B5) made it invisible
  (2026-10-17 14:05). Send it bare.
- Cinematic actors carry their templates in property 0x954 (array of 0x462 DIDs); the PowerCore actor of 0x35000025
  has 0x1D00078A (allows 0x1000005A, E5B, E5C, E5F; the ending's piece, not the sphere). The phase pod is spawned as an effect by templates (State02 / State03), not by a graph of its own.
- The Destroyer's sphere: closed 0x2E000FC7 (graph set 0x1C0000B5, templates 0x1D0006AC), open 0x2E00101D
  (tester 2026-10-17 15:02); the phase pod 0x2E001157 is the crater ring. Object_Activate 0x10000CCE, then Vfx_Event1
  0x10000076, opens the closed sphere (16:07 / 16:19).
- A skill key pressed by the server (winctl.press_key) cast at the cursor at once (the car was thrown, 2026-10-17
  22:38). Never press a skill key for the player.
- Cinematic_Intro 0x100009EC is the only thing that lights Batman's antennas (Tutorial 2 tour, 23:29); it runs at the
  intro cinematic (`champion_intro_at = "cinematic"`): at the tutorial start its spawn line (the "rope") shows (23:37),
  and a skipped cinematic shows it too (23:46): off (`champion_intro_keys = []`) until the effect that lights the
  antennas alone is found. On the loading screen a voice line was heard (22:40). Its
  Spawn goes through action type 0x737, which the HFSM raise-event scriptlet does not reproduce (22:51). Nothing may
  sound before the tutorial, not even on the loading screen (23:02). The end-of-spawn graph events lit
  nothing (fase3-ir); Cinematic_Hidden (SpawnIdle) makes Batman invisible (fase3-is, 23:19): never on the player.
- skilldata reads skill records with the kinds of props.txt, its BUILTIN_KINDS and catalog/data/properties.tsv; a key
  of unknown kind makes the whole record read as empty (the throw skill until fase3-iq).
- The yellow sphere 0x2E000FC7 is the Gotham Divided drop pod (env_pvp_drop_pod_a); no other sphere/pod model exists in the
  install; the phase pod 0x2E001157 is the crater, not the purple sphere (tester 11:49, fase3-jl); none of the pod's scriptlets
  makes it purple (fase3-jm): the purple sphere is not in this install.
- The Destroyer's closed sphere 0x2E000FC7 never opens if it got Vfx_Spawn 0x10000032; the open model 0x2E00101D
  does not show when swapped in (23:34). Keep the closed sphere and open it with Object_Activate + Vfx_Event1.
- Champion select (2026-10-18): an encounter's twin 0x49xxxxxx says if it has one (no SkipsLobby 0x10000B0E: all
  PvP / v AI maps and Tutorial 3). The client shows it only when 0x204C's number of teams is not 0, and loads the map
  on 0x2016: send 0x2016 only after the lock (`[match] maps` "lobby"). Crime Alley, Apokolips Causeway and
  Metropolis Skyway have no map data in the install (only Metropolis's menu icon; deep scan fase3-jr); they are
  left out of 0x2024 (`[match] hide_missing_maps`).
- With a champion select, 0x20AF (the match's champions + packs) goes after the lock with the locked champion and the
  bot's; the controlled object's class is `Match.agent_class` (fase3-ja).
- The Amplifiers tab opens only after 0x2090 (sets), 0x2107 (store data) and the item statuses. Its Flash managers
  are created when the tab opens and ask with 0x2116: answer 0x2116 every time, never rate-limit it; its own reply is 0x2115
  (account encounter stats = the Stats tab; sample counters, fase3-jj).
- The minimap / fog map comes from the encounter in the lobby manager (exe cave N, fase3-jb); patch caves must be
  position-independent (the client runs with ASLR).
