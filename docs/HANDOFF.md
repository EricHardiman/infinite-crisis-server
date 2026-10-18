# Handoff — state at build fase3-jd (2026-10-18)

Read `CLAUDE.md` first; `docs/FINDINGS.md` has the summary for new contributors. The history of every build is in `docs/CHANGELOG.md`; this page is the short version.
The sections after "Current state" are the earlier handoff (fase3-gz) and are kept for history.

## Current state (fase3-jd)

Confirmed in the game:
- Tutorial 1 from start to victory (street, bridge, Super Strength, the Destroyer, ending).
- Coast City v AI (0x40000B6A) opens the champion select first (fase3-iy): every champion can be picked and
  locked (client event 0x20E4, fase3-iz), the player plays the locked champion and Gaslight Batman stands on the
  other team as the AI (fase3-ja).

Shipped, not yet seen in the game:
- fase3-jb/jd: the map's own fog-of-war map (exe cave N; fase3-jb's version overlapped cave X and the patch was
  refused, fixed in fase3-jd). Needs `python ic.py patch`.
- fase3-jb: free play on Coast City v AI (`icserver/freeplay.py`): level 6 with 6 skill points, one level every
  60 s up to 20, skill ranks with the "+", an indestructible training drone, a tour of the champion's animations.
- fase3-jc: John Stewart's Q W E R (`icserver/kits.py`). His game data only has placeholder numbers, so the
  behaviour is an interpretation of the skill names; the mine, base and turret have no world object yet.

Decided by the tester:
- Tutorial 1: no electricity between Batman's antennas for now (the only effect that lights it, Cinematic_Intro,
  also plays a voice line and a rope); the sphere lands with the crater and the dust wave. The right sphere is
  a purple one, not yet found.

Open work (in order):
1. The tester's results for fase3-jb/jc/jd (fog, free play, John Stewart).
2. The store items on Coast City v AI.
3. Bot AI: Gaslight Batman moves and fights.
4. Other champions' kits (`icserver/kits.py` `KITS`), John's passive and basic attack, world objects for his
   mine / base / turret (candidates: world states 0x2E0013A8 and 0x2E0013B2 in pack 0xA000039F).
5. Tutorial 1: the purple Destroyer sphere, the throw's aim ring, the antenna electricity.

## Earlier handoff (fase3-gz, 2026-10-17)

Moving from the cloud chat to Claude Code on the user's machine.

### Goal (then)
Finish **Tutorial 1** with all of Gaslight Batman's animations, actions and interactions.

### Confirmed working in game (then)
- Full tutorial flow: street, bridge, finale, victory, Champion Unlocked banner, showcase movie.
- Replay of the tutorial (`0xEB` local player resent before each later match).
- HUD: basic attack and passive in colour, D places a Surveillance Camera at the cursor.

### Shipped in fase3-fm, NOT yet verified by the user (then)
- Car carried centred on Batman (`CARRY_ORIGIN`, `carry_height` 2.1), throw arc + spin, F swapped to the throw
  skill `0x480003C9` while carrying (aim ring).
- Scriptlet `0x5` on the car for the explosion fire.
- Sphere / props scriptlet tables resolved automatically from world states (`tutorial1.resolve_script_tables`).
- Camera max range 10 m: Batman walks into range before placing (`bridge.camera_tick`).
- Knockdown always face-down (graph events Knockdown → Dead → GetUp).
- Victory voice line: conversation `0x250`.
- Second car: `car_extra_back_shift` -1.6 (fase3-fn; +1.6 had moved it forward).
- fase3-fn: no meteor dust at the car's landing point; logging on a writer thread (Launch delay); 134 profile
  icons owned (`icserver/cosmetics.py`).
- fase3-fo: game data read before the ports open and cached (`data/game_cache.json`); the background reading
  during the match caused freezes and disconnects.
- fase3-fp: console on its own thread (the logs were lost), second car back to its original spot, unused HUD
  elements hidden (yellow "+"?), profile header sent at login.
- Still open from the tester's 14:41 list: gates white, D camera placed out of range (needs a log), car explosion.

- fase3-ft: the companion app (`python ic.py app`, `icserver/webapp.py` + `icserver/webui/`): play, champions,
  profile icons, arsenal. Not yet seen by the tester. Next: back to the Tutorial 1 details (victory voice, gates,
  yellow "+", explosion, D camera range, the "Unable to connect to Match" dialog = event 0x95, Champions tab
  0x21A4, costumes and skills of the 9 added champions; `catalog_scan` should use the extended roster).

- fase3-fu: app restyled after the League of Legends client (tester's request); `queue_on_movie_end` rolled back
  to false (it cut the overview movie and broke the dialogue audio in the match). Possible follow-up: the app's
  `queue_after_login` also queues before the client does; watch for the same audio problem.

- fase3-fv: Robin / Arcane Supergirl / Star Sapphire fixed (costumes repeating the base variant are skipped);
  John Stewart (unreleased) added by roster.py; app restyled with glass panels over full-screen champion art.

- fase3-fw: app top bar has a red/yellow/green server light; status panel replaced by a friends panel and a chat
  dock (`icserver/social.py`, data/social.json).

- fase3-fx: interface switch (legacy on first start; app Settings -> legacy; Ctrl+Shift+U in game -> new; app comes
  back after a match). Windows parts (winctl.py) are untested on the tester's machine yet. Possible later: a real
  button in the game's Options (Flash UI edit).

- fase3-fy: no more duplicate champions (costume clusters were taken as unreleased champions).

- fase3-fz: after the overview movie, the Launch screen's banner request (0x212E) queues the player when the client did
  not (second Launch no longer needed).

- fase3-ga: start meteors fall (entities), block the way, vanish after 20 s; emotes Ctrl+1..4. Crater: waiting for
  the tester's reference picture (the right crater with lava).

- fase3-gb: sound catalog (`python ic.py sounds`, icserver/audio.py).
- fase3-gc: start meteors use the game effect 0x2E0002EC (0x170001C4: rock + dust + mse_Meteor sounds) + the staying
  rock entity: showed nothing.
- fase3-gd: falling rock again + dust 0x2E0007D4 + 0x1EB = 0x170001C4 on landing (sound test) + push by Batman.
  Meteor sound: none (0x1EB test failed).
- fase3-ge: push stops (speed 0, walls), dust only on the big meteor, big meteor falls before crater/knockdown.
  Open: meteor sound (graph 0x1A0002BF?), the lava crater.
- fase3-gf: Exit Match ends any match (relaunch works); small meteors = fragments 0x2E00131C; smoother push. Lava crater:
  reference frames received (red lava splash by the lamp, fiery impact); asset not found in the loadable packs.
- fase3-gg: slanted visible meteor flights, small collision, dead drones sent with speed 0. Next: exe patch for a
  second zone-pack slot (category 0xd) to load 0xA000009A (meteor event + impact) with the tutorial.
- fase3-gh: exe patch for two zone slots (0x11FEF44); `[match] event_packs` = 0xA000009A when the exe has it; meteors
  = the game's event template 0x1D00019C on anchor 0x2E000013 (key 0x1000092F). Untested in game: check
  `diag --packs` (both zone packs load?) and `--scripts` (0x1000092F accepted?). If the load hangs, set
  `[match] event_packs = []`.
- fase3-gi: both zone packs load (20:08 diag). 0x1000092F rejected (only 0x5 allowed) -> key 0x5; anchor 0x2E000013
  is a water jet -> warning 0x2E0004E5. Batman locked while down (no sliding). If 0x5 does nothing either, the
  template's real entry point must be found (client 0x58EDD0 builds the allowed list from 0x7D2 templates).
- fase3-gj: 0x5 accepted but nothing shown. 0x1D00019C is an HFSM; its pieces are placed by the server, 3 probes
  (one per small meteor, see METEOR_EVENT_PROBES). Waiting for the tester to say which probe looks right.
- fase3-gk: rocks render as the glowing lava rock but cannot animate (no scriptlet table). Meteors = falling lava-rock
  entities 0x2E000BB3 again, scale 0.35 / 0.7. Open: fire trail and impact (needs the HFSM template or the
  particles 0x1800024B / 0x18000E6A / 0x180002D1), sound.
- fase3-gl: meteor collision 0.6 m square, push at 0.6 m; slower fall (1.6 s / 2.0 s). Open: fall visible?, sound.
- fase3-gm: meteor obstacle = octagon 0.45 m (boxes are grown by Batman's 0.6 m radius); push at 0.6 m.
- fase3-gn: push fixed (own obstacle blocked the slide), octagon 0.7 m, push 0.9 m. Open: lava crater, fall smoke, sound.
- fase3-go: octagon 0.95 m, push 1.15 m, small-meteor dust, Batman ambient keys 0x10000183 / 0x10000119 (suit electricity?).
- fase3-gp: carrier props ignore moves -> meteors appear at the spot after smoke (0x2E0007D4 key 0x10000347), push = remove + create.
- fase3-gq: small meteors at the tester's pings; smoke key 0x10000076; ambient + 0x10000181. Open: smoke trail asset, suit electricity, fog of war, lava crater, sound.
- fase3-gr: no dust waves before the crater; pushed rocks roll (stepped re-creation). Fog diag: draws, darken yes, map=0x0. Open: smoke column asset, suit electricity, fog, lava crater, sound.
- fase3-gs: rocks get their scriptlet table 0x1D0003B5 (world_state partial read) and run Vfx_Spawn 0x10000032; event crater 0x2E0004E7 + shockwaves; gliding push; RunScript_FX_Spawn at the start. Open: fire column (impact rig 0x100004CE unused), fog, sounds.
- fase3-gt: 0x2E0004E7 is the explosion (timed; small version as each meteor's fire), old crater back, drift push (moving updates + 0.01 m/s crawl). Open: lava crater model, fog, sounds, spawn glow.
- fase3-gu: [debug] model_tour (50 candidates, numbered in the objective text); rope event off. Waiting for the tester's numbers for meteor, fire column, smoke column, explosion, lava crater.
- fase3-gv: tour skips 0x2E000F04 (closed the game), resumes from logs/model_tour.json, auto-marks crashes.
- fase3-gw: tour sends bare models (model_tour_scripts false); later models with scripts closed the client after ~3 s.
- fase3-gx: no guide during the tour (variant C arrows + model at the marker closed the client), tour at (23, 56); champion_ambient_keys [] (rope).
- fase3-gy: tour skips the 9 models that closed the client (they do it alone, ~3 s after appearing); crash window 4.5 s.
- fase3-gz: [match] maps (packs + start per encounter): Tutorial 2, Coast City, Gotham Divided, Gotham Heights, Metropolis Skyway load their own zone pack (to verify). The local copy of the install was partial (97 packs); the user's rp folder has ~590.

### Open work (then, in order)
1. Get the user's logs for fase3-fm and fix whatever above did not work.
2. **Explosion fire** (see reverse-engineering.md "14:02 findings": script 0x3400015F / Vfx_OnFire 0x1000013E): spawn the destructible world state `0x2E00134F` (analog
   `0x1D0008EF`) at the impact point and run keys `0x10000078` / `0x10000016` / `0x10000079`.
3. **Profile icons:** picking one sends an unknown event (unhandled.log) -> answer with 0x2154 (scorecard.protector_icon_slot).
4. **Emotes** (Ctrl+1..4): done in fase3-ga through a keyboard watcher + graph events (icserver/emotes.py); the
   client's own wire event is still unknown. Needs the tester's confirmation.
5. Correct `icserver/abilities.py` cooldowns to the stat-15 values: Q 5 s, W 8 s, E 20 s (−2 per rank),
   R 110 s (−10 per rank). It still has the old guesses 9/12/14/80.
6. Skill animations for Q/W/E/R (phase 2 of the user's plan).
7. Aesthetics: meteor fall, craters, dust, the sphere that falls and opens (phase 3). fase3-ha: candidates in
   `world_states.tsv` (reverse-engineering.md "World-state inventory"); fase3-hb: the tour runs in Tutorial 2
   (the lab). fase3-he: explosion, crater, sparks and the Destroyer's ring
   chosen by the tester are in Tutorial 1; the lab now tries the sphere / drop pod and the Stolen Power meteor.
8. Champion base stats.

## Notes
- The heavy reverse-engineering artifacts from the cloud session (full disassembly, extracted packs) were not
  transferred. Regenerate what you need locally from `C:\Infinite Crisis Steam` (read-only; never copy game files
  into the repo). Addresses and findings are in `docs/re-notes/*.txt` and `docs/reverse-engineering.md`.
- `catalog/index.html` is the quickest way to look up an ID; `python ic.py find <text|id>` does the same in the
  console.
