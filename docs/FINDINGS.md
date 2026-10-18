# What we know so far (state at fase3-jf, 2026-10-18)

A summary for the people joining the project: what works, what the install allows, what is still missing and
the findings worth knowing before touching the code. The details and the evidence are in
[`reverse-engineering.md`](reverse-engineering.md); when and why each thing changed is in
[`CHANGELOG.md`](CHANGELOG.md).

## Tutorial 1

- It plays from the start to the victory: the street, the bridge, Super Strength, the Destroyer and the ending
  cinematic. Then come the reward ribbon ("Champion Unlocked"), Gaslight Batman's showcase movie and the
  scorecard.
- **The game does not disconnect at the end.** The player goes back to the menus. Tutorial 1 can be selected
  and played again in the same login, as many times as wanted (fase3-fa / fase3-fe, confirmed 2026-10-16
  23:40). For each new match, the server sends the local player (`0xEB`) again. The reward chain is
  `0x212E` → `0x211F` → `0x2124` → `0x2125`. Gaslight Batman is sent as not owned when the tutorial starts, so
  the unlock shows every time (`replay_champion_unlock`).
- Finishing Tutorial 1 unlocks Tutorial 2 on the home screen. The list of completed encounters is kept in
  `data/progress.json` (event `0x214B`).
- Known gaps, decided with the tester:
  - **No electricity between Batman's gun antennas.** The only effect that lights them is the cinematic
    scriptlet Cinematic_Intro (`0x100009EC`), and it also plays a voice line and shows a rope.
  - **The Destroyer's sphere is the wrong one.** We use `0x2E000FC7`, which is yellow. The original one is
    purple and probably carries the falling animation; it is not found yet. The yellow one lands together with
    the crater and the dust wave.
  - **The throw's aim ring on the ground does not show** (the yellow area around Batman when he lifts a car).
- Positions in the bridge and the finale were estimated from videos.

## Maps: which ones the install has

Every map exists as an encounter definition (`catalog/data/stages.tsv`), but only some have the files the
client needs to load them. Those files are the terrain pack (`0xA0C1xxxx`), the zone and mission packs, and
the sound banks. We checked the tester's full `rp` folder (about 590 packs).

| Map | Encounter(s) | Map files in the install | Champion select first |
|---|---|---|---|
| Tutorial 1 (Basic) | 0x40000991 | yes (0xA000024C / 0xA0000256) | no (SkipsLobby) |
| Tutorial 2 (Intermediate) | 0x40000A81 | yes (0xA00002E5 / 0xA00002E6) | no (SkipsLobby) |
| Coast City | 0x40000270, v AI 0x40000B6A, Crisis Labs 0x4000039C | yes (zone 0xA00000D2, mission 0xA0000162) | yes |
| Gotham Divided | 0x40000399, v AI 0x40000B6B | yes (mission 0xA0000168) | yes |
| Gotham Heights | 0x4000013E, v AI 0x40000B6C | yes (mission 0xA000016B) | yes |
| Crime Alley | 1vAI Tutorial 0x40000CA6, v AI 0x40000C82, Clash 1v1 0x40000E68, Clash 2v2 0x40000E74 | **no** | yes |
| Apokolips Causeway | Clash 1v1 0x40000EC0 | **no** | yes |
| Metropolis Skyway | 0x40000C28 | **no** | unknown (no lobby record) |

So:
- **Can be built:** Tutorials 1 and 2, and every Coast City, Gotham Divided and Gotham Heights mode (PvP and
  versus AI).
- **Cannot be built with this install:** Tutorial 3 (Crime Alley 1vAI), Crime Alley v AI and the three Clash
  maps. Their terrain, zones, missions and sounds are missing. The encounter definition alone is not enough,
  and nothing can be done on the server side without those files.
- **Coast City v AI is the test map for champions** (fase3-iy … jd):
  - It opens the champion select, and any champion can be picked and locked.
  - The player plays the locked champion, and Gaslight Batman stands on the other team.
  - In free play the player starts at level 6 and gains a level every minute. A training drone can be hit but
    not destroyed, and the champion plays each of its animations once.
  - Still missing: the store items, the bot's AI (it does not move or fight yet) and every champion's skills
    except Gaslight Batman's and John Stewart's.
  - The fog-of-war fix for this map needs `python ic.py patch`. It is not yet confirmed in the game.

## Champions

- `data/champions.json` (generated on each player's machine, not in the repository) holds the released roster.
  `icserver/roster.py` finds 11 more champions in the install and adds them:
  - fase3-fs (9): Arcane Zatanna, Deathstroke, Raven, Deadshot, Dex-Starr, Huntress, Nightmare Catwoman, Zod and
    Arcane Harley Quinn.
  - Later: Nightwing and John Stewart.
- **John Stewart is the only champion that was never released.** His data has names and effects but only
  placeholder numbers. Every skill does 40 damage (+40 per rank), costs 30 Will and has a 14 s cooldown (−2 per
  rank). His Q W E R are an interpretation of the skill names (fase3-jc, `icserver/kits.py`).
- **Keep the added champions at the end of the list.** The tester found that sorting them in alphabetical
  order among the others breaks the portraits: champions show another champion's picture. `roster.extend()`
  appends them after the champions of `champions.json` for that reason. The cause is not traced yet. A likely
  cause is that the client pairs each entry with the art by its position in the list, not by its ID.
- Six costume clusters were once taken for new champions. They showed twice, with another champion's portrait
  and skin (fase3-fy). The rule that finds champions now skips them.

## Profile and collection

- **The profile pictures can be changed.**
  - All 134 avatar (Protector) icons are sent as owned.
  - Choosing one, in the game or in the companion app, sends client event `0x2093` (icon, slot). The server
    saves it in `data/progress.json` and answers `0x2154`.
  - The saved icons are used on the profile card in every `0x2190`, and they are kept between logins
    (fase3-fq / fase3-ft).
- Amplifiers: 162 augments and 172 mods are sent as unlocked. The game's Amplifiers tab also needs the amplifier
  set list (0x2090) and the store's amplifier data (0x2107); both are sent at login and on the client's request
  (fase3-jg / jh). The tab loads (tester, 10:36), after a short wait.
- The profile's Stats tab gets the account's encounter stats (0x2115). The server sends made-up counters
  (fase3-jj). Which counter is which label is still to be matched. Artifacts and Stolen Powers are read from the
  install and listed in the catalog and the companion app.
- The companion app (`python ic.py app`) shows the champions with art, abilities and skins, the profile icons,
  the arsenal, friends and a chat. The game's own menus can still be used (`[app]` / Ctrl+Shift+U).

## Still not found or not understood

- **Effects and animations:** the antenna electricity without the cinematic, the purple sphere, the throw's
  aim ring, the crater's lava, and the explosion fire of the thrown car (candidate world state `0x2E00134F`).
- **Batman's scriptlet keys:** 25 of the 354 are known by sight. The other 329 have not been checked one by one.
- **Network messages not traced yet:**
  - The emotes: Ctrl+1..4 work through a keyboard watcher on the server's side.
  - The lobby notices from Flash (SelectCharacter, LobbyUIReady…).
  - The D button of the real client.
- **Gameplay numbers:** the skills' Will costs and status effects, the champions' base stats, and the stat
  IDs other than the cooldown.
- **John Stewart:** the world objects of his mine, base and turret. Candidates are world states `0x2E0013A8`
  and `0x2E0013B2` in pack `0xA000039F`.
- **Ranged drones:** their own attack effects. They use the melee drone's effects for now.

The full list is in [`reverse-engineering.md`, "Open questions"](reverse-engineering.md#15-open-questions).

## Findings worth knowing before changing code

- **Never do heavy work while a match runs.** Reading packs or decompressing during a match starves the network
  threads (Python's GIL): the game freezes and shows "server disconnected". Game data is read before the ports
  open and cached in `data/game_cache.json`.
- **The exe patches are checked byte by byte** against the 2015 Steam build. Code caves must not overlap: run
  `python tests/test_patcher_layout.py <exe>` after any change. The client runs with ASLR, so caves must be
  position-independent.
- **The minimap and the fog of war come from the encounter** that the lobby manager holds (`0x204C`, exe cave
  N). Before fase3-jb, every map used Tutorial 1's map, so other maps looked dark.
- **Two name tables in pack `0xA0000038`.** Graph-event names and scriptlet names live in the same pack, in
  the same format, and both use `0x10xxxxxx` IDs. Graph events come before file offset 900000 and scriptlets
  after it. Mixing them up raises the wrong thing.
- **The champion select** shows only when `0x204C` sends a team count other than 0. The world loads only when
  the server sends `0x2016`, which must come after the lock (client event `0x20E4`). `0x20AF` names the
  match's champions and must carry the locked one.
- **Never put game files in the repository:** no `.rp` packs, no `.exe`, no images, no extracted texts.
  IDs, short names and numbers are fine. The server reads everything else from each player's own install.
