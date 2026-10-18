# Development log

Build by build, in order. Build tags (`fase3-xx`) are the names of the test packages; "fase" is Spanish for
"phase". Times such as "diag 15:27" refer to diagnostic runs on the tester's machine. Builds marked
"requires `python ic.py patch`" add or change exe patches. The consolidated findings are in
[`reverse-engineering.md`](reverse-engineering.md).

## Phase 1: what changed compared to the earlier emulator

| Problem | Cause in the earlier server | Now |
|---|---|---|
| Disconnects and reconnects | Global state: each new connection wiped the previous one's. | One session per connection. You can leave the match or log out and back in without restarting the server. |
| Disconnect when clicking "Launch" twice | The second click sent a second referral and the connection dropped. | The second click is ignored and logged. |
| Loading that sometimes failed | Fixed waits (4 s, 5 s…) regardless of what the client was doing. | Objects are created when the client reports its loading % (10 s at most). `server.log` says which condition was met. |
| Timers from one match firing in the next | Nobody cancelled them. | Each match has its own timers and all are cancelled on exit. |
| Tutorial text changed in the second match | It was kept in a global variable. | It is kept per match. |
| Full object resend every 2 s | Triggered by connection silence. | Configurable (`idle_resend`, 5 s by default) and only while the champion stands still. |
| Login failed without explanation | The key and the patched exe did not match. | `doctor` detects it and `patch` fixes it. |
| The debugger crashed the game | `restart_test.ps1` always attached `tracer.py`. | No debugger is used. |
| Values hard-coded in the code | Champion, spawn position, timings, options. | Everything is in `config.toml`. |

Phase 1 test plan:

1. **Normal tutorial.** Play Tutorial 1 to the second point. Does it get as far as, or further than, the earlier emulator?
2. **Logging in again.** Leave the match (or close the game) and enter again without closing the server. This used to fail.
3. **The sliding Batman.** Set `player_class = 0x4000007C` in `config.toml` and play again.
   - If the second Batman disappears and the camera follows you, that is the fix.
   - If loading gets stuck, go back to `0x40000086` and note the percentage where it stopped.
4. **The skill upgrade button.** When it appears, click it several times. The server does not handle it yet,
   but the event the game sends ends up in `logs\unhandled.log`, which is what the response (`SkillRanked`) is built from.

Logs needed for each test: `logs\server.log`, `logs\unhandled.log`, and screenshots if something looks wrong.

## Phase 2: drones and basic combat

Drones now come from the game's own packs:

- Positions come from the tutorial's placement records (pack `0xa0000256`). That is where group "03" of the
  first zone lives: the cinematic drone, the wave that arrives afterwards, the vehicle and the drone doors.
- Each drone's model comes from its character variant (pack `0xa0000257`). For example, "Soldier Drone"
  is `0x40000C72`. Because it is a variant, it has a health bar and can be attacked.

How the tutorial plays now:

1. When the cinematic ends, the vehicle and the drone doors appear.
2. The arrows guide you through two points. On reaching the second one, **the drone** from the cinematic
   appears further ahead ("A corrupted drone. Take it out!") and the arrows point at it.
3. Right-click the drone (or the ground next to it, because the game does not let you select it yet).
   A + click near the drone also works. Batman walks until he is within striking range and attacks every second.
   The drone's health drops with each hit and, when it reaches 0, the drone dies and disappears.
4. The wave arrives: 2 melee drones and 2 ranged drones ("More drones are coming!").
5. Once they are defeated: "Good job!", Batman reaches level 2 with one skill point, and the tutorial asks you to
   unlock the first skill.

On reaching level 2, the skill bar and its upgrade buttons are shown (they are HUD elements of their own:
Q 30, W 4, E 28, R 5, passive 19), with the Q one highlighted.

The "player" object is now `0x4000007C` ("Unnamed Player", no model) to get rid of the Batman that slid on top
of the walking one. If loading gets stuck with this, use `python ic.py play --classic`.

Limitations of this phase:

- Drones do not move or attack yet.
- Batman does not play the strike animation; he only lowers the drone's health.
- Ranking up a skill still gets no response. When you click the button, the event will end up in `unhandled.log`
  and that is what it will be implemented from.

Combat values (drone health, damage, interval, range) are in `[combat]` in `config.toml`.

Tools for exploring the data:

| Command | What it does |
|---|---|
| `python ic.py layout 0xa0000256` | Lists everything placed in a pack: name, world state, position and orientation. |
| `python ic.py variants 0xa0000257` | Lists which variant with health corresponds to each world state. |
| `python ic.py entities 0x2E000AAB ...` | Searches ALL packs for the entity (0x40...) of each world state. Takes a few minutes; writes `logs\entities.txt`. |

## What this phase does NOT fix yet

Phase 3: drone AI (moving and attacking), attack animations, skills (Q/W/E/R and ranking up), real experience,
and movement on the navigation mesh.

## Phase 3: walk animation

`diag.py --fix` confirmed the cause: Batman's movement component had the animation's maximum speed set to 0
(drones have 3.0), so the walk animation never received any speed. Drones get it from the movement speed property
(`0x100005E4`) in their data. The server now sends that property for Batman (`anim_move_speed` in `[match]`,
4.5 by default). The exe does not need to be patched again.

## Phase 3: ranking up the first skill (temporary)

The client still cannot notify the server when you click the "+" (it lacks the progression logic).
In the meantime, the server unlocks the first skill on its own, 8 seconds after asking for it, and the tutorial
continues: the "+" buttons are hidden, Superman asks for practice drones and 2 appear to be defeated. Adjustable in
`config.toml`: `[tutorial]  auto_rank_seconds = 8` (0 = disabled).

The "+" buttons are no longer hidden when the skill is unlocked, because in the game the whole skill HUD
disappeared along with them. To hide them again: `[tutorial]  hide_upgrade_buttons = true`.

The diagnostics showed that when the "+" is clicked the UI **does send `RankSkill`**, even though the previous
query fails. All that is missing is something in the client to pass it to the server (a pending patch).

## Phase 3: practice drones and cinematics

- The map's "03ThugA/B" are Gotham thugs (humans from the drone cinematic), not targets. The practice targets are
  now **training drones** (`0x40000EB4`, world state `0x2E000808`, the one with the target drone skill), at the
  same positions.
- Before the intro, cinematic `0x35000025` is played (test: it is the one with the power cores falling from the
  sky, possibly the meteor). Configurable: `[match]  pre_cinematics = [0x35000025]`, `[]` to remove it.

Why the HUD does not show the ranked-up skill: the `SkillRanked` notice the UI expects is sent by the game's
progression scripts (`GM_Advancement.RecvNotice_SkillRanked` is a function those scripts call), and those
scripts are not in this client. It is the same gap as with the "+": they have to be replaced with a patch.

## Phase 3: the tutorial opening as in the original (experiment)

Based on the description of the original game:

- **Vehicle blocking the street:** its record (`0x2E000AAB`) is in pack `0xA000024C`, which is now loaded with
  the match (`[match] packs`).
- **Meteors:** impacts with object `0x2E0007D4` (it carries the dust cloud `vfx_env_event_meteor_dust_cloud`).
  The "PowerCore" tried earlier was a relay, not the meteor. 3 fall at the start, a big one behind Batman when he
  reaches the first marker (with a hit reaction on Batman) and another after the first drone ("Not so fast,
  Batman"). `[tutorial]  meteors = false` removes them.
- **The human thug and the drone fighting:** next to the first drone the thug appears (`03ThugB`, not attackable).
  The drone attacks him every 1.4 s until Batman attacks; then the human thug flees and disappears.
- **The wave** is now 2 melee drones, which face the vehicle and hit it until Batman attacks them.
- The human thug and the drone face each other.
- When each meteor and the vehicle appear, the server sends them a test script order so that
  `diag.py --scripts` writes out their script tables (to find out which order makes the meteor fall).
- **Catwoman:** when the practice drones are finished, cinematic `0x35000034` plays and, when it ends, the
  vehicle blocking the street disappears. `catwoman_cinematic = 0` removes it.

## Phase 3: in-game diagnostics

`tools\diag.py` attaches to the game with the previous project's debugger (`tracer.py`) and writes `logs\diag.log`.

Why the "+" does nothing: the button asks the game `InqCanRankSkill`. Inside the exe that query only gets an
answer if a **game script registered a handler** for it. Without a handler, the answer carries an error and the
UI never sends `RankSkill` (which is why nothing shows up in `unhandled.log`). The diagnostics record which
handlers the game registers when loading the match and what the query returns.

1. `python ic.py play` and stay **in the menu**, without entering the match.
2. In another console: `python tools\diag.py --force`
3. Play Tutorial 1 up to the "+", click it 2 or 3 times and walk a little.
4. Ctrl+C in the diagnostics console. Logs needed: `logs\diag.log`, `logs\server.log` and `logs\unhandled.log`.

`--packs` records every data pack (`rp\0x....rp`) the game tries to load, whether it fails, and the table of pack
"slots" per category (the game reserves a fixed number of slots per category; without a free slot the pack is
not loaded and there is no warning).

Result (2026-10-14): `0xA000009A` and `0xA000024C` are **zone** packs (category `0xd`) and the game has a single
slot for that category: if `0xA000009A` is requested, it takes the slot, `0xA000024C` (the tutorial zone) no
longer fits and loading gets stuck. It is not needed: all the vehicle and meteor records are also in
`0xA000024C` and `0xA0000256`, which do get loaded.

## Phase 3: props as entities

The vehicle, the doors and the meteors were created from their bare "world state" (`0x2E...`): the object exists
(its scripts start) but without a model. In the game, a placeable object is an **entity** `0x40...` whose twin
`0x49...` names the world state in property `0x510` (for example the "Door" `0x40000B0F` →
`0x2E0010F3`). On startup, the server looks for those entities in packs `0xA000024C`, `0xA0000256` and
`0xA0000257` and writes it to the log (`props: ...`). `[combat] prop_entities = false` reverts to the previous
behavior; `prop_classes = {"0x2E000AAB" = 0x40000xxx}` forces one by hand.

`ic.py entities` (2026-10-14) found no entity for the vehicle or the meteor in any pack: they are created as a
world state. What was actually wrong: all the encounter's placements use **cell 251** of landblock
`0x13cb` and the server was sending cell 0. Props now go with `[combat] scenery_cell = 251`. (Test 2026-10-14: still
not visible; it was not `DestructiblePriorityLevel` in `UserPreferences.ini` either.) `diag.py --place`
(2026-10-14) showed the cause: the client **places** the doors (Door entity `0x40000B0F`, cell 251) but **never**
the vehicle or the meteors (world state without an entity: their physics component is not created). Those two are
now created as the Door entity with property `0x510` = their world state (`[combat] prop_carrier = 0x40000B0F`;
0 = as before).
Result: the vehicle-door **was placed** at (43.66, 52.61) but is not visible (the door has no model and `0x510`
does not change its world state). Now `prop_carrier = 0` and props go as a world state but **with** a movement
module `[1, 1]` (`scenery_module`), which is what made the client place the door.
Result: the vehicle's world state is still not placed, even with the module. Pending (exe analysis): the creation
type of its `.entity` `0x2D0008BC` (`UniqueDynamicImmobile`, `SharedStaticImmobile`...) and whether the client
only accepts creating it from the map.

- **Wave drones:** the encounter layer puts them past the vehicle (next to the first blue door); in the game they
  hit the vehicle from Batman's side. They now appear ~3 m from the vehicle on that side
  (`[tutorial] wave_positions`).

- **Floating Batman:** the click height creeps up little by little (200.0 → 201.7 on the same street). Heights
  close to the ground are now snapped to `[match] ground_z = 200.0` (0 = disabled).
- **Two Batmen in the Catwoman cinematic:** the cinematic brings its own Batman. Before starting it, the server
  puts your Batman in the same spot and also **hides** him with property `0x90F` (the one the client's cinematic
  player uses to hide entities; the exe's visibility test is `0x2A1 && 0x76A && !0x90F`).
  When the cinematic ends he is shown again. `cinematic_hide_champion = false` / `cinematic_place_champion = false`.

`--force` makes the query answer "no error" to see whether the game gets as far as sending `RankSkill` to the
server. `--fix` sets the maximum walk speed to 7.0 if it is 0. If Batman walks with that, the cause is
confirmed.

## Phase 3: attack animation (experiment)

Attack and skill animations are not decided by the client: they are **scriptlets** (small programs in the
packs, IDs `0x34xxxxxx`) that the server orders to run with event `0x8D`. That event has now been decoded.
Gaslight Batman's scriptlets are:

| Scriptlet | What it is |
|---|---|
| `0x34000037` | Basic attack (effects `Vfx_Bmg_Basic_Ranged_Left/Right`) |
| `0x34000038` | Bat Flight (jump / dash) |
| `0x34000039` | The Bat Scream |
| `0x3400003B` | Sonic Batarang (projectile) |
| `0x3400003A` | Another skill, no target |
| `0x34000048` | Passive with stacks |

On each hit the server orders Batman to run a script, and when a drone dies, it orders the drone to run its
death script. Configured in `config.toml`:

```
[scripts]
basic_attack_keys = [[0x10000195, 0x10000188], [0x10000196, 0x10000189]]  # animation + shot effect
hit_keys = [0x10000223]      # VFX_CBT_Hit_Shared on the drone that was hit
death_keys = [0x100001FA]    # _Defeat_OnDead when the drone dies
```

Test of 2026-10-13: with `Combat_Basic_Attack_Right/Left` the game accepts the order (result 0) and Batman
moves his arms. `CbtState_Death_Induce` is not in the drones' table, so death now uses
`_Defeat_OnDead`, which is.

Second test: the shot fires and deals damage, but travels in a straight line and passes through the drone; the
drone falls on its back when it dies. The server now passes the drone as the target to the shot script (variable
`0x108`, the same one the client itself uses for its skills) and adds the physical hit reaction (`0x10000209`).
To remove it: `send_target = false`.

Result of the first test (2026-10-13): the game **does receive and understand** the order (correct DID and
instance), but rejects it with `0x80070057`: the scriptlet is not in the table of scriptlets Batman is allowed.
The second test showed that table: it does not contain `0x34...` IDs but **script names**
(`0x10000xxx`, for example `Combat_Basic_Attack_Right`, `Batman_Gaslight_Sonic_Batarang`). They come from the
character's script tables (property `0x7D2` of its class → records `0x1d...`). That is why the order now uses
those names.

Test:

1. `python ic.py play` and stay in the menu.
2. In another console: `python tools\diag.py --scripts`
3. Play up to the drone and attack it.
4. Ctrl+C in the diagnostics. Logs needed: `logs\diag.log`, `logs\server.log`, `logs\unhandled.log`, plus whether
   Batman played the shooting animation.

In `diag.log`, each "order result" says what happened: `0` = started, `1` = the game ignored it,
`0x80070057` = invalid ID, `0x8000ffff` = Batman has no scripts component.

## Phase 3: ranking up the skill with the "+" (investigation)

Test 2026-10-14: neither the "+", nor Ctrl+Q (`RankUpSkill1` in the keymap), nor Q send anything to the server
(`traffic.log`: only movement, attack and keepalive). The client decides all of that with the
`GM_Advancement` handlers (InqCanRankSkill, RankSkill, InqSkillRank...), which are registered by a game script:
record `0x39000001` in pack `0xA0000038` (always loaded) uses the registration natives `0xE70012`, `0xE70006`,
`0xE70009`. In matches none of them get registered. Suspicion: the script is activated by the "match started" mode
(event `0x2053`), which the server does not send because, sent with the lobby data, it hangs the load.
Test: `[match] send_match_start = "after_intro"` (or `"in_world"`).
Result: with both, the client **goes back to the loading screen** and connects to the lobby again (`ConnectToLobby
repeated` in `server.log`): `0x2053` is the transition from lobby to match and triggers the real load. New mode
`send_match_start = "reload"`: the server sends it with the lobby data and only creates the objects on that second
load (if it does not arrive within 15 s, it creates them anyway).

## Phase 3: the "+" reaches the server (exe patch)

The UI's "+" does call `GM_Advancement.SendNotice_RankSkill` (native rva `0x524500`), but since no script
registers a handler, the click dies in the client. New patch (applied by `python ic.py patch`): the call to the
dispatcher (rva `0x5245bf`) goes through a code cave in `int3` padding (rva `0x48bc9c`) that first sends a **ping**
(event `0x2136`, the same as Alt+click, sender rva `0x487e60`) with type `0x52414E4B` ("KNAR") and then calls the
original dispatcher. The server recognizes that ping as "rank up skill" and unlocks Q.
`[tutorial] auto_rank_seconds = 60` remains only as a fallback.

- **Drones fight back:** the one Batman attacks (and the wave drones if he comes within 3 m) walks towards him,
  hits him every 1.6 s (`Vfx_Min_Basic_Melee`) and takes 12 health (never below 1). `drones_fight_back = false`.
- **Teleport-in spawn:** wave and practice drones play `Vfx_Spawn` + `Vfx_Fade_In` when they appear
  (`spawn_keys`).

## Phase 3: skill ranks in the HUD, practice drones

- **What native `0x524500` actually is:** it is the UI's *rank query* for a skill (agent, slot). The HUD calls it
  for slots 0-5 at once every time it refreshes (bursts of 6 pings within a few ms); clicking the Q "+" calls it
  alone for slot 1. The server now ignores the bursts and only treats a lone query for slot 1 as a click
  (`RANK_BURST_GAP = 0.08 s`). Previously the bursts unlocked Q without anyone clicking.
- **The HUD shows the rank:** all rank queries (the native's and the one from the HUD's C++ loop, rva
  `0x67c8b1`, which builds `GM_Skill.RecvNotice_UI_SkillUpdate`) go through dispatcher `0x50e580`, which without
  handlers leaves everything at rank 0. Two new code caves (rva `0x5e7924` and `0x7369d4`, `python ic.py patch`)
  call the dispatcher and, if the agent is the local champion (rva `0x45d670`) and the slot is 0-7, read the
  champion's integer property `0x100006C1` (reader rva `0x21c990`): 4 bits per slot, a non-zero value is the rank.
  The server sends it (`Match.skill_ranks`) when Q is ranked up. **The exe has to be patched again.**
- **Correct practice drones:** world `0x2E000808` was a generic soldier drone (same rig `0x2D00068A`
  as `0x2E001167`). The practice drone is world `0x2E001298` (rig `0x2D000F92`,
  `chr_minion_target_drone`: base with a ring) and its entity `0x40000BA9`. Positions estimated from the original
  capture (up the street, to the left of the vehicle); changed with `[tutorial] practice_positions`.
  They do not attack.
- **Drone damage:** 6 per hit (previously 12).
- **Slower spawn:** `[tutorial] spawn_sequence`: `Vfx_Spawn` at 0.1 s, `Vfx_Fade_In` at 0.9 s and at 1.6 s.
- **Attack animation:** `Vfx_Min_Basic_Melee` (`0x100000EC`) did not show the hit. Each hit now uses the
  next script in `[tutorial] drone_attack_keys` and the log says which one it was
  (`hits Batman (attack script 0x...)`): whichever looks right is the only one kept in the list.
- **Recommended skill (orange frame + arrow over Q):** the next query in the HUD loop
  (rva `0x67c8c8`, `InqNextRecommendedSkillToRank`) has no handler either. Code cave C (rva `0x725a64`) calls it and
  then reads the same property `0x100006C1`: the top 4 bits are the recommended slot + 1. The server marks
  Q when granting the skill point and clears it when Q is ranked up. Ranks stay in slots 0-6.
- **Diagnostics:** `python tools\diag.py --ranks` records every rank query that goes through the code caves,
  whether the champion is found and the property is read, and which rank / recommended skill the HUD uses in each
  slot (and when a slot is marked for refresh).
- The log now says which attack script each drone hit uses (`03MeleeC: attack script 0x... (hit N)`).

## Phase 3: "+" fix (diag 2026-10-14)

The `--ranks` diagnostics showed what each thing is (the names used before were swapped):

- Native rva `0x524500` is the **rank query** (InqSkillRank); Ctrl+Q also calls it. The click on the "+"
  first asks **InqCanRankSkill** (rva `0x524b00`), which without a handler answers error `0xe7f` and stops there.
  The real **RankSkill** is native rva `0x524e80` (dispatcher `0x50e9a0`).
- Property `0x100006C1` is read correctly (`leida=1`), but the HUD's C++ loop (rva `0x67c640`) **never
  ran**: it only runs for slots marked "dirty", and nothing marked them.

New patches (`python ic.py patch`):
- The ping code cave now sits on both calls to RankSkill (the "+" and the key for ranking up the recommended
  skill); the server receives the real click.
- Code cave E: InqCanRankSkill answers "no error" for the recommended slot (Q in the tutorial), so the click
  continues on to RankSkill.
- Code cave D: before each HUD update it reads the property; if it changed, it marks slots 0-5 for refresh
  and the HUD receives `RecvNotice_UI_SkillUpdate` with rank and recommended skill (code caves A and C).
- `diag.py --ranks` now also records RankSkill, code cave E and each refresh from code cave D.

## Phase 3: the "+" with the mouse and less aggressive drones

- **The click on the "+" was cut off at the rank query:** without a handler, the query returned garbage (3711 =
  `0xe7f`, the number that appeared over E) and the UI did not continue. Code cave B now always answers the rank
  from the property (0 if there is none). The exe has to be patched again.
- **Drones:** only the drone Batman attacks fights (previously the whole wave activated when he came within 3 m),
  and if Batman moves more than 8 m away it stops chasing him. Until they are attacked, the wave drones keep hitting
  the vehicle (with the vehicle as the script target, so they do not aim at Batman).

## Phase 3: tutorial pacing as in the original

The timings come from the chat log of the original's captures (00:43 "A narrow escape!", 00:46 "We need to
keep moving", 00:55 "What ARE these accursed machines?", 00:58 "A corrupted drone", 01:05 "These metallic monsters",
01:09 "Not so fast / More drones are coming!", 01:12 "Once you start attacking...", 01:22 "Good job!", 01:24, 01:29
"Use a skill point...", 01:36, 01:40 "Construct: target drones?", 01:43 "Practice your new skill"). Previously the
server sent several dialogue lines together and they overlapped.

- Each tutorial moment is now a list of "beats" (seconds after the event, what): dialogue, hint,
  objective, next marker, or an action (the wave appears with "More drones are coming!", the practice drones
  with "Construct: target drones?", level 2 with "Good job!", the highlighted button with "Use a skill point").
- When the practice drones are finished: "It appears the path forward is blocked." and ~6 s later the Catwoman
  cinematic.
- Objectives with the original's text: "Right-click the drones to defeat them with Basic Attacks (0/2)" (counts
  1/2, 2/2), "Click the highlighted button to unlock your Sonic Batarang Skill", "Place your cursor on a target
  and press ('Q') to destroy it with Sonic Batarang".
- `[tutorial] pacing = 1.0` scales all timings (2 = twice as slow, 0 = all at once). The tests use 0
  (`IC_PACING=1` to test with the real timings).
- **The human thug and the first drone:** the tutorial reacts to the first hit Batman lands, not to the attack
  order. The drone keeps fighting the human thug while Batman walks towards it; only on the first hit does the drone
  turn on Batman and the human thug flee (in the original's capture at 00:58 he can be seen running).

## Phase 3: Sonic Batarang (Q) and practice drones

- **Yellow drones immune to basic attacks:** Batman hits them (the attack is visible) but does not lower their
  health (`[tutorial] practice_immune`).
- **Q on the server:** the client sends attack and skill orders through the same event `0x20EE`
  (built at rva `0x670030`): command 2 (or 9), followed by the skill number (0 = basic attack) and the target.
  Previously the server ignored that number and treated everything as a basic attack. Now an order with skill ≠ 0 is
  the Sonic Batarang: Batman faces the target, runs his `Batman_Gaslight_Sonic_Batarang` script (`0x10000164`) with
  the target, and the batarang hits the drone and bounces to the nearest one (up to 2 bounces, 8 m), 200 damage
  each. On first use: "When you use a skill, it goes 'on cooldown'" and then "...consumed 'Will'".
- **Still to be verified in game** that the client sends the order when Q is pressed. `python tools\diag.py --q`
  records every order the client builds, whether it rejects it (and at which check) and whether it sends it. In
  `server.log`, `skill order: command ..., ability ...` appears when it arrives.

## Phase 3: the "real" skill rank (Q)

`diag.py --q` showed that when Q is pressed the client does not even build the order: it stops it earlier, because
as far as it is concerned Q is still at rank 0. The rank the client itself uses (function rva `0x463ce0`) does not
come from GM_Advancement but from a champion property: **`0x100000AF`, a list (type `0xC`) of integers indexed by
slot** (1 = Q). The server never sent it.

- `wire.py` now knows how to pack lists (`KIND_ARRAY`: u32 count and, per element, packed property id
  + value; reader rva `0x101290`).
- When Q is ranked up the champion carries `0x100000AF = [0, 1, 0, 0, 0, 0]` (`[match] rank_array`). With that Q
  should appear active (in color) and be castable; the order arrives as command 2 with skill ≠ 0 and the server
  performs the bouncing batarang.
- `[tutorial] lock_other_skills`: while the tutorial asks you to rank up Q, the "+" for W, E, R and the passive
  are hidden.

## Phase 3: "not enough Will" and the disappearing HUD

- **Q is now attempted** (the rank list `0x100000AF` worked): the client stops it saying there is not enough
  "Will". The vitals message `0x42` has two lists and the HUD shows the sum; the server put health and Will in
  the second one and zeros in the first. They now go in the first one (`[match] vitals_first_list = true`;
  `false` = as before). The HUD should look the same.
- **The HUD disappeared a few seconds after the "+":** the "Use a skill point..." notice arrived 7.5 s after the
  wave and, even if Q had already been ranked up, it still hid the W/E/R "+" buttons, and hiding them wipes the whole
  skill HUD. That notice is now skipped if Q is already ranked up, and `lock_other_skills` is off by default.

## Phase 3: Q works (server) — animation and timings

- Test 2026-10-14 10:29: Q arrives (`skill order: command 2, ability 1, target 0x0, position ...`: it is a shot
  towards the cursor, with no target) and the batarang destroys both drones. The client repeats the order while Q is
  held (4 in half a second): there is now a 2 s wait between casts.
- Animation: Batman runs `Combat_Special_Attack_2` (`0x100000EB`) + `Batman_Gaslight_Sonic_Batarang`
  (`0x10000164`); configurable with `[tutorial] batarang_keys`.
- Timings after destroying the practice drones: 2 s "When you use a skill, it goes 'on cooldown'", 7 s "...consumed
  'Will'", 12 s "It appears the path forward is blocked.", ~17 s Catwoman cinematic.

## Phase 3: repeated dialogue, HUD with only Q, batarang and drones

- **"It appears the path forward is blocked." played twice:** that line belongs to the Catwoman cinematic itself
  (in the game data it carries the "cinematic line" flag, just like "No walls can keep me out!").
  The server no longer sends it; the cinematic starts 12 s after the last drone (2 s cooldown, 7 s Will) and
  speaks the line itself. `[tutorial] catwoman_delay` to adjust.
- **Only Q in the HUD:** on reaching level 2 the W/E/R/passive upgrade buttons are no longer restored (they stay
  hidden rather than being hidden later, which is what wiped the HUD). `[tutorial] restore_other_upgrades = true`
  = as before.
- **Script keys corrected:** previously they came from the wrong name table (`0x100000EB` is not
  Combat_Special_Attack_2, it is Vfx_Active). Now:
  - Batarang: `0x10000164` Batman_Gaslight_Sonic_Batarang + `0x10000171` Vfx_Bmg_Batarang (the projectile) and
    `0x1000017B` Vfx_Bmg_Batarang_Stop at the end.
  - Drone attack (one per hit, rotating): `0x10000124` Robot_Minion_Melee_Attack + `0x100000EC`
    Vfx_Min_Basic_Melee; `0x10000128` Combat_Basic_Attack + `0x100000EC`; `0x10000124` + `0x10000008`. The log says
    `attack scripts 0x...+0x... (hit N)`: test which one shows the hit visibly so only that one is kept.
- **Drone walking:** 1.6 m/s (previously 3.0) in steps every 0.25 s (previously 0.4 s).
  `[tutorial] drone_walk_speed` and `drone_tick`.

## Phase 3: the cinematic cut Superman off

- Test 10:55: the Catwoman cinematic started 12.5 s after the last drone, while Superman was still saying
  the "Will" line. Each line now waits for the previous one to finish (duration estimated from the text length):
  2 s "When you use a skill...", ~10.5 s "Using that skill also consumed 'Will'...", ~19 s cinematic.
  `[tutorial] catwoman_delay = N` forces a fixed time (0 = automatic).
- Q is a shot towards the cursor: if there is no drone near the clicked point, it now hits the first one on the
  line of fire (up to 12 m). Previously, in the test, the first Q "found no target".
- (fase3-av) The client **queues** dialogue lines: if one is sent while another is playing, it waits. With a quick
  batarang, "Practice your new skill..." (2 lines), "When you use a skill..." and "Using that skill..." were still
  queued when the cinematic started. The server now keeps track of when the queue ends (estimated duration of each
  tutorial dialogue line) and the cinematic waits for it to empty + 1.5 s.

## Phase 3: vehicle and meteors (client patch)

Cause found in the exe: the client's object factory (`WorldEntityFactory`, rva `0x14f1f0`) only builds an object
from a world state (`0x2E...`) if that state names a **parent entity**. Otherwise it writes "wstate ... is missing a
parent .entity" and the object is never created. The vehicle (`0x2E000AAB`) and the meteors (`0x2E0007D4`) have no
parent in the data (hence `props: ... (sin entidad)` when the server starts). That is why they were never placed
(what `diag.py --place` saw).

New patch (rva `0x14f3c2`): instead of failing, it uses the Door entity `0x40000B0F` (a prop the client does
place) as the parent and leaves the prop's world state (model and scripts) as is. **The exe has to be patched
again**: `python ic.py patch`.

Possible side effects: the vehicle might get the door's collision (which is useful for blocking the street) and
the meteors too; to be seen.

Tools:
- `python tools\diag.py --entities` records every object built from a world state
  (`objeto desde estado de mundo estado=0x2e000aab entidad_padre=0x40000b0f`) and whether any of them fails.
- `python ic.py dump` dumps (to `logs\dump.txt`) the records of the vehicle, the meteor, the cinematics and
  whatever they name, searching all packs. Takes a few minutes.

### Correction (fase3-ax)

The 11:17 diagnostics showed it had been read backwards: the factory receives the **entity** (`0x40...`) and looks
up its world state (Door `0x40000B0F` → `0x2E0010F3`, drones `0x40000A5C` → `0x2E000808`). A bare world state used
as a class is not even built (no error). The fase3-aw patch did not work and probably broke the
Catwoman cinematic (it ended 0.2 s after starting): **removed**.

New patch: class `0x4F` + the low 6 digits of the world state (vehicle `0x4F000AAB`, meteor
`0x4F0007D4`) tells the patched exe "build the Door entity but with this world state". The server already
sends those classes (`[combat] prop_override = true`). **The exe has to be patched again** (`python ic.py patch`).
`diag.py --entities` now records `PROP 0x4F recibido` and `objeto construido entidad=... estado_de_mundo=...`.

Q also hits if the click lands within 5 m of a drone (previously 4) or in a 2 m wide strip along the line of fire.

## Phase 3: the vehicle is now built, fails at the components (fase3-ay)

Test 11:36 with `diag.py --entities`: the code cave works (`PROP 0x4F recibido clase=0x4f000aab` →
`objeto construido entidad=0x40000b0f estado_de_mundo=0x2e000aab`), but construction fails at **step 3
(components)**: the Door lacks the components the vehicle's world state asks for (the vehicle has a different
"creation type", property `0x50F` = 5). Same with the meteors. The cinematic is visible again.

Next step, find a carrier of the same type:
- `python ic.py carriers` (takes a few minutes) writes `logs\carriers.txt`: entities whose world state resembles
  the vehicle's (those with score 2-3 at the top). Log needed: `logs\carriers.txt`.
- The carrier is chosen in `config.toml`: `[combat] prop_carrier_entity = 0x40000xxx` followed by
  `python ic.py patch`.

Other changes:
- The wave leaves the vehicle and goes for Batman when he comes within 6 m or attacks one of the two (both
  together). `[tutorial] wave_aggro_radius`. The log says `... leaves the vehicle and goes for Batman`.
- The wait between the last dialogue line and the Catwoman cinematic is halved
  (`[tutorial] catwoman_wait_scale = 0.5`).

## Phase 3: testing 6 carriers at once (fase3-az)

`carriers.txt` (11:50): only one entity has the same creation type as the vehicle (`0x50F` = 5):
`0x40000289`, but it is in a pack (`0xA000016B`) that the tutorial does not load. To avoid one test per candidate,
the patched exe now has a **table of 6 carriers**: class `0x4A`..`0x4F` + the world state selects carrier 0..5
(`[combat] prop_carriers`, by default Door `0x40000B0F`, `0x40000289`, `0x400001BD`,
`0x4000081B`, `0x40000B0A`, `0x40000092`; the last ones are entities from packs that do get loaded).
With `[combat] prop_try_all_carriers = true` the server places the vehicle 6 times in the same spot, one per
carrier, and the meteors rotate through them. `diag.py --entities` shows which one is built without
`step 3 (components)` (or whether the carrier is not loaded: `ERROR: the carrier entity is not in the loaded packs`).
The exe has to be patched again: `python ic.py patch`.

The wave is back to the previous behavior: they hit the vehicle and only the drone you attack comes for you.

## Phase 3: why the drones kept "hitting the vehicle" and which component fails (fase3-ba)

- **Drones:** the server did set them to fight you, but when hitting it left them facing east (an angle
  calculation with zero displacement gave 0), which is exactly towards the vehicle. They now keep facing
  Batman. The log says `... attacked, turns on Batman`, `... walks to Batman (x m)` and `... hits Batman (x m)`.
- **Vehicle/meteors:** the 11:55 test gave the same error with the 5 loaded carriers (`0x40000289` is not in the
  tutorial's packs), so the problem is not the carrier but some component the vehicle's world state asks for.
  `diag.py --entities` now watches each of the ~30 component creators in step 3 and records only the one that
  fails: `*** COMPONENT FAILED: creator rva 0x... error 0x...`. No need to patch again if already done with
  fase3-az.

## Phase 3: the failing component and the start with markers (fase3-bb)

- **Vehicle/meteors:** the 12:05 diagnostic always flagged the same component (creator rva `0x204760`). That
  component re-reads the object's class from the creation data, where the fake class `0x4A...` was still present
  (the code cave only changed it in a local variable). The code cave now writes the carrier there too. **Re-patch
  required** (`python ic.py patch`).
- **Start like the original:** at the start there is a marker nearby (`[tutorial] walk_targets`, default
  (26.5, 59.8)); on arrival the big meteor falls and knocks Batman down; when he gets up (`drone_appear_delay` = 6.5 s)
  the drone and the human thug appear fighting, with a second marker over them. On approach (≈6 m): "What ARE these
  accursed machines?" / "A corrupted drone. Take it out!". The old keys `targets` and `drone_step` are no longer used.

## Phase 3: the start as in the video (fase3-bc)

- Batman cannot move until the 3 small meteors have fallen (`[tutorial] start_lock` = 3.5 s), nor while he is on the
  ground after the big meteor (`knockdown_lock` = 3 s). The log says `move order ignored: ...`.
- The second marker (and the drone fighting the human thug) appears 8.5 s after the hit, with "You see what Batman
  sees" (`drone_appear_delay`); approaching earlier no longer triggers it sooner.
- Markers: they were sent with cell 0; the props the client does place (the doors) use the encounter's cell 251.
  Markers now use 251 (`[combat] ping_cell`, 0 = as before).
- Vehicle: the fase3-bb fix was not enough (the same component still fails). `diag.py --entities` now logs which
  `.entity` that component resolves from the class, with what type and what it returns.

## Phase 3: markers and guide arrows; vehicle with its own .entity (fase3-bd)

- **Markers:** the "Map Ping" entity (`0x40000A9C`) turned out to be an **InvisibleTarget** (world state `0x2E000002`,
  the same one in the encounter layer over the vehicle): it is not visible. The ground marker and the arrows at
  Batman's feet are Batman's own scripts in his table: `Vfx_GuideArrow` (`0x10000F80`) and
  `Vfx_GuideArrow_Ping` (`0x10000F86`). The server now launches them on Batman, pointing at the ping, every time it
  creates one (`[tutorial] guide_keys`).
- **Vehicle:** the failing component gets the `.entity` (model/skeleton `0x2D...`) from the class; with the
  carrier it received the Door's along with the vehicle's world state. Map objects are built with the world state
  there, so the code cave now sets the world state (`0x2E000AAB`). **Re-patch required.**
  `diag.py --entities` logs only for our props: `*** componente 0x204760: clase ... -> .entity ...`, type and
  result.

## Phase 3: the client now creates the vehicle on its own (fase3-be)

Diag 13:04: at 13:04:36 (during the intro cutscene) the **client itself** built the vehicle's world state
`0x2E000AAB` with its `.entity` `0x2D0008BC`, without error (type 1). In other words, the vehicle exists on the
client even though it is not visible; what is missing is whatever displays/activates it. All 6 carriers still fail
(the component reads the class from another copy of the data), so that test is disabled
(`prop_try_all_carriers = false`).

`diag.py --entities --place --scripts` logs who creates the vehicle (stack), where it is placed and whether the
client accepts the guide-arrow scripts (`resultado de la orden`).

## Phase 3: the vehicle blocks the way on the server (fase3-bf)

Why there are no collisions: the server moves Batman in a **straight line** toward the click (the client only shows
what the server sends), so he passes through anything on the map: boxes, vehicles, walls. Collisions have to exist
on the server as obstacles.

- First obstacle: the street vehicle (`DestVehicle`, center (43.7, 52.6), rotated as on the map). Batman stops when
  he touches it instead of passing through. It disappears when the Catwoman cutscene ends (the path opens).
- `[combat] vehicle_blocks = true` enables it; `vehicle_box = [4.0, 1.6]` is the half-length and half-width in meters.
- The log says `tutorial: the street vehicle blocks the way`.
- Boxes and other objects can be added the same way once their positions are known.

## Phase 3: first obstacle (boxes) and Batman walks around obstacles (fase3-bg)

- **Boxes:** from the path walked around them in testing (13:29:06–13:29:09), a rotated rectangle was computed
  (center (32.35, 58.83), half-size 2.53 × 1.89 m, rotation 0.30 rad). It goes in `[combat] obstacles` as
  `[name, x, y, half_length, half_width, rotation]`; more can be added the same way.
- **Walking around:** previously Batman stopped dead when touching an obstacle. Now, if the click lies behind a box or
  the vehicle, the server finds the shortest path via the corners and Batman walks around it (like the original
  game). If the click falls inside an obstacle, he walks to the nearest free point.
- The log says `tutorial: obstacle Boxes1 at (32.4, 58.8)`.

## Phase 3: wagon + boxes and wall with their real shape (fase3-bh)

- The client "snaps" each click to the edge of the walkable area (which is why exact points such as (28.7, 57.2)
  repeat). Combining the ~7500 clicks from all logs yields the walkable map, and the gaps are the obstacles.
- Obstacles can now be **polygons** that follow that edge: `["Wagon", [[x, y], ...]]` (the wagon and the stack of
  boxes in front of it, L-shaped) and `["SouthWall", ...]` (the wall/building to the south). A polygon is the line
  Batman's center does not cross; standalone boxes are still `[name, x, y, half_length, half_width, rotation]`.
- The single `Boxes1` rectangle was removed (it let Batman pass through the front of the wagon and did not let him get
  close to the boxes).
- Batman walks around obstacles via the corners (shortest path) and the path is only recomputed when the click
  changes. No recorded click falls inside an obstacle.

## Phase 3: boxes at the end of the street, marker test and Alt/Ctrl pings (fase3-bi)

- **Obstacle `Boxes2`:** the boxes and rubble at the end of the street, taken from the edge where the client snaps
  clicks ((39.1, 53.0) and (41.1, 49.0)).
- **Markers:** the game has a guide script (`0x1E00055B`: AlertPingScriptlet / AlertArrowScriptlet) that launches
  `Vfx_GuideArrow_Ping` and `Vfx_GuideArrow` pointing at the ping. We do not know with what data, so each marker
  tries three forms, one every 4 s (`[tutorial] guide_variants`, `guide_variant_gap`):
  - **A** (on appearing): both on Batman with the ping as a variable (as before).
  - **B** (+4 s): same as A, plus the ping as the order's second object.
  - **C** (+8 s): the circle on the ping itself and the arrows on Batman.
  The log says `tutorial: marker N, guide variant X`.
- **Player pings:** the log now says which one it was: `ping Alt+click (alert) [type 1]` or
  `ping Ctrl+click (retreat) [type 2]` (previously it always said "Alt+click").

## Phase 3: visible marker, Alt/Ctrl pings fixed, the marker triggers when walked over (fase3-bj)

- **Player pings:** they were swapped. Alt+click (alert) now uses class `0x4000025B` and Ctrl+click
  (retreat) uses `0x4000025A`.
- **Visible marker:** since player pings are visible, each tutorial marker also gets an alert ping at the same point,
  until the original circle works (`[tutorial] marker_ping_class`, 0 = off). The log says
  `tutorial: visible marker N at (x, y)`. The A/B/C circle tests keep running.
- The first marker moves to (25.1, 59.9), where the tester placed a ping (`[tutorial] walk_targets`).
- **Reaching the marker:** previously Batman had to **stop** within the radius (3.5 m); now passing through is enough.
  When the big meteor falls, Batman stops wherever he is.

## Phase 3: green marker, Batman must stand on it, second marker on the ground, the human thug walks around (fase3-bk)

- **Marker:** it is now the green ping (class `0x4000025A`, `[tutorial] marker_ping_class`).
- **Radius:** Batman has to step on the marker: 1.5 m (`[tutorial] marker_radius`; previously 3.5 m when stopping, and
  later when passing).
- **Second marker:** placed on the ground next to the fight, at (37.6, 58.0) (`[tutorial] drone_marker`), not under
  the drone. "A corrupted drone" plays when it is stepped on, and the marker is not removed until Batman stands on it
  (even if the drone is already down).
- **The fleeing human thug** now walks around the wagon and the boxes instead of through them (`world.route`). It
  takes about 4 s.

## Phase 3: markers in place, really stepping on them, batarang that stops (fase3-bl)

- Markers at the positions marked in testing: the first at (23.6, 60.6) and the second at (36.9, 57.6).
- **Stepping on the marker:** walking over it only counts within 0.6 m of the center (`marker_pass_radius`); where
  Batman stops it counts within 1.5 m (`marker_radius`). This way it no longer triggers before arriving.
- Since the second marker is 2 m from the drone, a ground click counts as attacking the drone only within 1.6 m
  (`[combat] click_attack_radius`, previously 2.5).
- **Marker color:** it now uses the map-note category the ping itself carries in the game data (1) instead of 0x12
  (`[tutorial] marker_category`). This is the test to make it show green.
- **Basic attack shots:** each pistol shot kept going, passed through the drone and vanished far away. Now, when it
  reaches the drone (distance / `[scripts] shot_speed` = 20 m/s), the server stops the shot (`Vfx_Bmg_Basic_Stop`)
  and launches the impact right there (`Vfx_Bmg_Basic_Hit`) along with the drone's reaction. The batarang was left as
  it was (fase3-bk), since it already looked right.
- **Level up:** the "spend your point" reminder (element 27) is no longer shown; it is the suspect for all skills
  getting highlighted (`[tutorial] skill_point_reminder = true` = as before).

## Phase 3: east building and green ring test (fase3-bn)

- **Obstacle `EastBuilding`:** the building east of the square (edge at x ≈ 45.2 from y 53.6 northward), derived from
  the clicks; it is no longer possible to go from (45.5, 52.3) to (45.1, 60.3) through it.
- **Green ring (test):** the property set of the guide ping in the data (`0x1D0007A9`) contains property `0x8E` with
  two effects (`0x3400053C`, used only by that ping, and `0x34000600`). They are now sent with the markers
  (`[tutorial] marker_vfx`, `[]` = off).

## Phase 3: the green ring crashed the game (fase3-bo)

- Diag 15:11 / 15:13: the client crashed (access violation at rva `0x561d1`) right when building marker
  `0x4000025A` with property `0x8E` (effect list). `marker_vfx` is off (`[]`) by default.
- With `prop_override = false` the vehicle is sent with its world state `0x2E000AAB` as is; the crash happened before
  we could tell whether the client builds it. Test: repeat the run with this package.

## Phase 3: second marker, map edges, vehicle and meteors DO get built (fase3-bp)

- **Diag 15:17 (with `prop_override = false`):** the client built **our** vehicle `0x2E000AAB` (`.entity`
  `0x2D0008BC`, type 4, result 0) and the meteors `0x2E0007D4` (`.entity 0x2D000656`) without errors, via a different
  path than the cutscene's. With the carriers it failed. `prop_override` stays `false` by default (the carrier patch
  is not needed). Still to confirm whether they are VISIBLE.
- **The second marker did not appear:** walking anywhere after the meteor, the drone step counted as done because
  its marker had no position yet ("no target = arrived"), and its dialogue was skipped too. Now that step waits for
  the drone to appear and for Batman to step on the marker.
- **Map edges:** obstacles were finite polygons and Batman walked around them "outside the map" (going behind the
  building to get past the vehicle). Now the east building, the north wall (`NorthWall`, y = 64.3) and the south
  side of the street (`SouthStreet`) extend to the edge, and a detour longer than 2.5 times the direct distance is
  discarded: Batman walks straight and stops at the obstacle.

## Phase 3: why the vehicle is not visible (diag 15:27) and `diag.py --create` (fase3-bq)

- The second marker now appears (log 15:28:13 `visible marker 2`).
- **Vehicle:** with its world state `0x2E000AAB` the client builds ALL its components without error (model
  `0x2D0008BC`), but never places it on the map: in `--place` the doors show up at (54.05, 44.80) and
  (89.87, 26.21) with cell 251 and the marker at (23.6, 60.6), and nothing at (43.66, 52.61). The doors are sent
  as an entity (`0x40000B0F`) and do get placed; the vehicle has no entity of its own. Same for the meteors.
- In the exe, object creation (rva `0x14f540`) only places the object if it carries an "initial position" (its third
  argument). `python tools\\diag.py --entities --create --place` logs, for each object, its class, whether it carries
  that position, the component results and whether it was applied. That shows what the vehicle is missing.

## Phase 3: code cave Z, the vehicle with its model on the carrier (fase3-br) — RE-PATCH REQUIRED

- Diag 15:35 (`--create`): all objects are created without an initial position and placed afterwards by the server
  message. The doors (entity) get placed; the vehicle and the meteors with their bare world state build the model but
  are never placed (the meteors are placed "nowhere", cell `ffffffff`).
- With a carrier (class `0x4A...`, code cave X) the object does get placed, but the model component (init rva
  `0x1693a0`) looked up the model for class `0x4A000AAB` and did not find it. **Code cave Z** (rva `0x2cf73c`, called
  from rva `0x1693aa`): for classes `0x4A`-`0x4F` it looks up the model using `0x2E` + the low 24 bits, i.e. the
  vehicle's/meteor's own model. No relocations in the touched bytes.
- `[combat] prop_override` goes back to `true`. **Re-patch required:** `python ic.py patch`.

## Phase 3: the vehicle breaks in stages (fase3-bs)

- The vehicle is now visible (code cave Z)! It is a destructible: the game has `Destructible_AdvanceState`
  (`0x10000063`), which moves it to the next state (intact → damaged → wrecked).
- Previously that script was sent 1 s after creating it (old test); not anymore.
- **Batarang at the vehicle:** a Q thrown within 4.5 m of the vehicle (with no drone in the way) hits it and advances
  one state. The log says `Sonic Batarang: at the vehicle` and `tutorial: vehicle state N`.
- **Catwoman:** `vehicle_break_at` = 6 s into her cutscene, the vehicle is taken to wrecked, and when the cutscene
  ends it is **no longer deleted**: the wreck remains (`vehicle_keep_wreck`) and the path is clear.
- `[tutorial] vehicle_states`, `vehicle_break_keys`, `vehicle_break_at`, `vehicle_keep_wreck` for tuning.

## Phase 3: the vehicle has no scripts (fase3-bt)

- Diag 15:52 (`--scripts`): when sent `Destructible_AdvanceState`, the client reports "scriptlet table: 0 groups,
  allowed: none" for the vehicle. The vehicle does not accept scriptlets: breaking does not go through them. In the
  exe, destruction is handled by Havok (`CDestructionComponent`, `hkdDestruction...`), so the event that triggers it
  still has to be found.
- Meanwhile the vehicle is again removed when the Catwoman cutscene ends (`vehicle_keep_wreck = false`), so that an
  intact vehicle that can be walked through does not remain.

## Phase 3: aimed batarang, and the vehicle goes away with Catwoman's hit (fase3-bu)

- **Batarang:** previously it was enough for a drone to be within 5 m of the cursor, even if Batman threw in another
  direction. Now it only hits if aimed on top of the drone (1.5 m, `[tutorial] batarang_aim_radius`) or if the drone
  is on the throw line (12 m long, 1.5 m wide).
- **Vehicle in the cutscene:** `vehicle_break_at` = 6 s into the Catwoman cutscene (when she hits it) the vehicle
  disappears and the path opens. No explosion yet: the vehicle does not accept scriptlets and its destruction is
  handled by Havok; what triggers it still has to be found.

## Phase 3: meteors around Batman and the crater that stays (fase3-bv)

- **3 small meteors:** they now fall next to Batman at the start ((20.6, 60.0), (20.8, 57.6), (17.6, 57.2);
  `[tutorial] small_meteors`) and **stay** until the next marker appears (previously they were deleted after 8 s and
  fell far away, at (15, 56.5), (24, 66), (30, 55)).
- **Big meteor:** falls behind Batman at the first marker ((19.6, 58.9), `big_meteor`) and stays (the crater).
- **Marker color (test):** pings carried the champion's team (1) and showed red. They now carry team 0
  (`[tutorial] ping_team`; `-1` = as before). This also applies to the player's Alt/Ctrl+click pings.

## Phase 3: drones walk without jumps, wave next to the vehicle, meteors disabled (fase3-bw)

- **Drones that "jumped":** each update sent the point where the drone would be 0.25 s LATER; the client kept running
  from there and then corrected. Now the current position is sent, with heading and speed, and then it advances.
  They also walk around the wagon and the boxes (same planner as Batman).
- **Wave:** the two drones spawn right beside the side of the vehicle facing the square ((43.6, 55.3) and
  (41.2, 53.5)).
- **Meteors:** the model that loads appears as gray columns; they are disabled (`[tutorial] meteor_objects =
  false`). Batman's knockdown with the big meteor is unchanged.

## Phase 3: Batman's knockdown with CbtState_KnockUp and fog of war diagnostic (fase3-bx)

- **Knockdown on reaching the first marker:** `0x10000209` was being sent (just a flinch). Now
  `CbtState_KnockUp` (`0x1000003D`, in Batman's script table) + the hit effect (`0x10000223`):
  it lifts him, he falls and gets up on his own. `[tutorial] knockdown_keys` to try others.
- **Ping color:** team 0 also showed red; `ping_team` goes back to `-1` (the champion's).
- **Fog of war / green minimap:** the exe has `CFogOfWarComponent` (update at rva `0x6b3520`), which only runs if its
  owner has a valid position and the game state is not 7. `diag.py --fog` logs whether it updates and what blocks it.
  The green minimap is probably the same fog, never computed.

## Phase 3: knockdown timings and server-side fog of war (fase3-by)

- **Knockdown at the first marker** (`[tutorial]`): when he steps on it Batman stays still; at `knockdown_delay` = 1 s
  the meteor falls and he goes down; at `knockdown_lock` = 7.5 s after stepping on the marker he can move (1 + 5 on the
  ground + 1.5), and the second marker appears at `drone_appear_delay` = 7 s. "A narrow escape!" at 6.2 s, the
  objective and the hint at 7 s.
- **Fog of war:** diag 16:38 (`--fog`): the client's fog component DOES update (state 5, valid position). What was
  missing is that the server must not send what Batman cannot see. Now characters (drones, the human thug, the
  targets) farther than `vision_radius` = 14 m, or behind a wall / the wagon / the vehicle, are hidden with property
  `0x90F` and reappear when seen (`fog_of_war`). Map objects remain visible.

## Phase 3: player team (dark fog and green pings) and drones that came back to life (fase3-bz)

- **Team on the player object:** the client has per-team fog modes (keyboard commands `SetAllFogOfWarVision`,
  `SetTeam1FogOfWarVision`, `SetTeam2FogOfWarVision`) and colors pings by their team relative to the player's. The
  player had no team: the fog looked "all visible" (clear) and all pings red (enemy). The player now carries
  `PVP_Team` = the champion's (`[match] player_team = false` = as before).
- **Defeated drones that reappeared:** the server fog re-sent them when they came into range, which recreated them.
  It now leaves the dead and already-removed ones alone (the fleeing human thug does not come back either).

## fase3-ca — ping color

- Pings and the tutorial marker no longer carry a forced icon, category or team: only "show on map". Each class uses
  its own icon and color (Ctrl+click = retreat 0x4000025A, Alt+click = alert 0x4000025B; the tutorial marker uses the
  retreat one).
- `[tutorial] ping_style = "minimal"` (default). `"team"` adds PVP_Team and `"full"` restores the previous set.

## fase3-cb — ping color by type, fog and minimap diagnostics

- A ping's color is set by the client from the relation between the ping's team and Batman's: same team = blue,
  team 0 = neutral, other team = red. Alt+click (alert, 0x4000025B) now uses team 2 (red), and Ctrl+click (retreat,
  0x4000025A) and the tutorial marker use team 0 (neutral, should show green). Changed in
  `[tutorial] ping_class_teams` (`ping_style = "team"`).
- The green minimap is the placeholder image: the real map only reaches the HUD when the player's property
  0x100001D3 changes, and that does not happen. `python tools/diag.py --minimap` asks the game for the image during
  the match (at 8 s and at 25 s) to confirm the fix before patching the exe.
- `--fog` now also logs the fog rendering: vision sources, texture, whether it darkens and which filter blocks it.

## fase3-cc — minimap fixed, pings and Batman on the minimap

- **Re-patch the exe** (`python ic.py patch`). When the HUD loads, the patch requests the Tutorial 1 map image from
  the map manager: the same thing the `--minimap` diagnostic did in the 17:25 test, but without the diagnostic.
- Each ping and each tutorial marker carries an invisible "note" at the same point with the minimap icon
  (0x13000A15, category 1). The game does not draw enemy-team objects on the minimap, so the note is separate and
  has a neutral team. Settings: `[tutorial] map_notes`, `map_note_icon`, `map_note_category`, `map_note_variants`
  (the icon variant for each type is a guess).
- Batman carries "show on map" and the tutorial avatar's minimap icon (0x13000376):
  `[match] champion_map_icon` (0 = no).
- `--fog` also logs the engine's fog switches (EnableFog / EnableMaskFog) and whether the map is loaded when it
  renders.

## fase3-cd — dark fog test and minimap note diagnostic

- `[match] lighting_env` (previously hardcoded to 0x10000016): the scene's lighting environment. On 2026-10-05 the
  scene came out almost black without it, but at that time the fog of war had no vision source: that black may have
  been the fog itself. With `lighting_env = 0` the server does not send it and the client uses the region's.
- `python tools\diag.py --notes` logs why a ping, a marker or Batman does or does not show on the minimap ("show on
  map" flag, team relation, note created).

## fase3-ce — local team (diagnostic)

- The 17:47 `--notes` diag showed why nothing appears on the minimap: the game compares each object's team with the
  LOCAL team stored in the match object ([[0x1777068]+0xbc]) and everything came out "enemy" (relation 2), even
  Batman (team 1). That local team is never filled in.
- `python tools\diag.py --team --notes --fog` writes it (1) at 3 s, to confirm that this makes Batman/pings show on
  the minimap (and perhaps lights up the vision area with `lighting_env = 0`) before making it permanent.

## fase3-cf — team lookup in the minimap notes

- Diag 17:53: with the local team set to 1 everything still came out "enemy"; before, it was 0 (not -1). That only
  happens if the game FAILS to read the object's own team (lookup rva 0x188820, store [entity+0x38]). `--notes` now
  logs that lookup (whether it found it, the type and the value).
- `lighting_env = 0` left everything dark, including around Batman: it is the scene lighting, not the fog. Back to
  the default value (delete the line).

## fase3-cg — Batman and pings on the minimap (exe patch)

- **Re-patch the exe** (`python ic.py patch`).
- Diag 17:57: the minimap note reader reads each object's team with a function (rva 0x188820) that does not find the
  properties the server sends (al = 0 for all, Batman included): team -1 = enemy = not drawn. The patch uses the
  generic reader (rva 0x21c990) instead, the same one that already colors the ground pings correctly.
- The visible pings and marker no longer carry "show on map": the note is set by their invisible companion
  (otherwise each ping would show twice).
- fase3-ch: the first version of the patch called a wrong address (VA 0xa1c990 instead of 0x61c990) and the game
  crashed on load (18:03). Fixed.

## fase3-ci — minimap notes: the hand-off to the HUD

- Diag 18:17: with the patch the notes ARE now created (Batman icon 0x13000376 category 2; pings and marker icon
  0x13000A15 category 1), and the local team set to 1 changed nothing on screen. The game keeps a single note per
  (category, variant): each new ping moves the previous one.
- `--notes` now follows the note all the way to the UI (Flash): whether it is sent, whether the HUD movie exists,
  whether it finds its list and whether the positions arrive (UpdateMapNotes).

## fase3-cj — the minimap note is carried by the ping itself

- Diag 18:24: the invisible companions' notes DO reach the HUD (it finds its list and adds them), but never receive
  a position (UpdateMapNotes was not called even once): that invisible object is never placed in the world. Now the
  visible ping and the visible marker carry their own note (icon 0x13000A15, category 1, variant per type).
  `[tutorial] map_notes = "self"` (or "companion" / "off").
- Batman's note is sent when he is created, during loading, when the HUD does not yet have its note list
  (list = 0): it gets lost. Pending.

## fase3-cl — minimap: "map delivered"

- **Re-patch the exe** (`python ic.py patch`).
- Diag 18:34: the minimap note manager runs every frame (rva 0x66a7c0) but never gets to set the positions: besides
  the loaded map it requires the "map delivered to HUD" flag ([M+0xc8]), which is only set by the HUD re-delivery
  when the map was already loaded. The minimap code cave now sets it too.

## fase3-cm — pings on the minimap without the yellow cone

- 18:41: pings and Batman now show on the minimap! (with fase3-cl). But each ping also came with a yellow cone: it
  was the icon 0x13000A15 we were sending; the HUD already draws the ping icon on its own.
  `[tutorial] map_note_icon = 0` (default) does not send it.

## fase3-cn — minimap timings

- Player pings: 4.5 s (`[timing] ping_lifetime`, previously 6).
- Tutorial marker: shows on the minimap only for `[tutorial] marker_note_seconds` (4 s) after it appears; the ground
  one stays until Batman steps on it. Since the client only reads "show on map" when an object is created, at 4 s the
  same marker is created without a note (id +8) and the one that had it is deleted.

## fase3-co — markers in order and a single Batman icon

- Markers activate in order: passing near the drone no longer skips the first marker
  (`[tutorial] skip_markers = false`; previously any pass near the drone made the second one appear).
- The minimap already draws the local player on its own (yellow ring) now that the note manager works; the extra
  icon 0x13000376 was redundant: `[match] champion_map_icon = 0` (default).

## fase3-cq — the ground marker is no longer touched; the note is separate

- 19:56: swapping the marker for a copy at 5 s made the ground one disappear while the icon stayed on the minimap.
  Now the ground marker carries no note and stays until Batman steps on it; an invisible object at the same point
  carries the minimap icon (marker id + 8) and is deleted after `marker_note_seconds` (5 s).

## fase3-cr — ping category (0x1D) and ground marker back

- 20:04: without "show on map" the ground marker is not drawn (its ring is part of the map note system), and
  removing an object does not erase its minimap icon (the game frees it 30 s later). The marker carries its note
  again.
- Pings and marker now use category 0x1D (the one the client treats as a player ping, with team colors) instead of
  1, which drew two icons. The idea is that with it the minimap plays the ping animation and turns it off by itself.

## fase3-cs — the two vehicle drones attack together

- When one of the two drones hitting the vehicle is attacked, the other also goes after Batman (previously only the
  attacked one). The leash for those two is 14 m (8 for the others).
- Minimap: stays as in fase3-cr (a single ping; the ground marker turns off with the ping, the guide arrow remains).

## fase3-ct — finding the real meteor

- The object we were using (`0x2E0007D4`, .entity `0x2D000656`) is only the impact's **dust
  cloud** (`vfx_env_event_meteor_dust_cloud_rig`): that is why "grey columns" appeared
  (the cloud mesh without its animation). The meteor itself is a different object: the
  `dump.txt` from 14/10 11:26 shows `env_event_meteor_a_rig` (the rock with its "cap"),
  `vfx_env_event_meteor_warning` (the ground warning) and `vfx_env_event_meteor_impact`
  in pack `0xa000009a`.
- `python ic.py dump <text> [<text> ...]` now also accepts text: it searches every pack,
  dumps the record that contains each text and the records that name it (to reach the
  0x2E "world state" that has to be created).

## fase3-cu — the real meteor

- From the 20:30 dump: the rock is world state `0x2E000BB3` (.entity `0x2D00048D`,
  `env_event_meteor_a_rig`: Root / Meteor / Meteor_cap) and it lives in pack
  `0xA000024C`, which the tutorial already loads (the vehicle's pack). The earlier
  `0x2E0007D4` was only the impact's dust cloud (the "grey columns").
- Meteors are once again created as objects (`meteor_objects = true`) using the rock
  (`[tutorial] meteor_wstate = 0x2E000BB3`), through the same path as the vehicle
  (class `0x4A000BB3`, code cave Z for the model).
- The same pack has two other candidates for later: `0x2E0004E5` (.entity `0x2D000390`,
  impact/warning) in `0xA000009A`, and the event list `0x1D00019C`, which names the
  warning, rock and impact.

## fase3-cv — meteor size

- 20:42: the rock is now visible, but large. Small meteors now carry property
  `0x10000426` = 0.5 (`[tutorial] meteor_scale`; the big one uses `big_meteor_scale` =
  1.0). That this property is the scale is an assumption: in the tutorial avatar's
  world state it is 1.0. `meteor_scale_property = 0` turns it off.

## fase3-cw — the big meteor's crater

- 20:54 dump (`crater`): the crater is entity `0x400004FD` (world state `0x2E0004BE`,
  .entity `0x2D000375`), with its records in packs the tutorial already loads
  (`0xA00000B3`, `0xA000024C`). In another tutorial's placement list (`0x1D0007E9`) it
  appears as "Crater1/2/3".
- On reaching the first marker, a big rock no longer falls: the crater appears at
  (19.6, 58.9) and Batman falls. `[tutorial] big_meteor_crater` (true) and
  `big_meteor_rock` (false). The crater is not hidden by the fog of war.

## fase3-cx — real meteor size and the crater as a placed prop

- Property `0x10000426` was not the scale. The render component (VA `0x622F10`)
  multiplies its scale by property `0x6B4` (float). The exe's SetScale (`0x58D650`)
  writes `0x6B4`, and world state `0x2E001037` carries it with 2.1. Small meteors are
  now sent with `0x6B4 = 0.3`. Configured with `[tutorial] meteor_scale`,
  `big_meteor_scale` and `meteor_scale_property` (can be a list).
- The crater is no longer created as entity `0x400004FD`, which was not drawn. It is
  now created the same way as the rocks that do show up: world state `0x2E0004BE` via
  the carrier class, in cell 251. Controlled by these `[tutorial]` keys:
  - `crater_mode` (`wstate` or `entity`);
  - `crater_wstate`, `crater_carrier_slot` and `crater_scale`;
  - `crater_yaw`;
  - `crater_blast`: fires the startup scripts as a blast.
- Entity `0x400004FD` (`entity` mode) now also uses cell 251.

## fase3-cy — crater diagnostics

- `diag --create` (21:44): the crater (`0x4B0004BE`) builds without errors, just like
  the rocks. Its `.entity 0x2D000375` is in `0xA000024C`, but it is only a one-bone
  skeleton with no mesh, and it does not end in an appearance reference like the meteor
  does (`0x19000501`). The crater's visible part must come from its scripts (VFX and
  decals).
- On creation, the crater receives the `[tutorial] crater_keys` probes (Vfx_Startup,
  Vfx_Spawn_Alt01, Vfx_Event1 and _Entity_OnEnterWorld_Default). `diag --scripts`
  lists its scriptlet table.

## fase3-cz — the crater uses carrier 0

- `diag --scripts` (21:52): the crater was requested with class `0x4B0004BE` (carrier 1,
  entity `0x40000289`), which is not in the loaded packs. Result:
  "BuildCreationInfoFromEntityDesc" fails and the object does not exist, so it does not
  receive its scripts either. The rocks use carrier 0 (`0x4A...`, the door
  `0x40000B0F`), which does load. Now `crater_carrier_slot = 0`.

## fase3-da — the crater in place and with its own entity (requires `python ic.py patch`)

- 22:00: the crater is now visible, but it ended up about 6 m to the right of where it
  is in the video, and without the lava. Now `BIG_METEOR = (13.5, 60.0)`; it can be
  adjusted with `[tutorial] big_meteor = [x, y, z]`. On screen, x grows to the right
  and y downwards.
- With carrier 0 (the door) the crater has no scripts: its table is empty
  ("0 groups"). The lava and smoke must come from the scripts of its real entity,
  `0x400004FD`. Carrier 1 is now `0x400004FD`, and the crater uses it
  (`crater_carrier_slot = 1`). Since the carrier table changed, the exe must be patched
  again. If diag reports "the carrier entity is not in the loaded packs", revert with
  `crater_carrier_slot = 0`.

## fase3-db — crater position and its template properties

- 22:14: with carrier `0x400004FD` the crater builds fine, but that entity has no
  scriptlets either ("0 groups"). The lava does not come from a script.
- The tutorial pack (`0xA000024C`) contains the crater's spawn template, `0x1D0008B6`:
  entity `0x400004FD`, state `0x2E0004BE` and several properties (`0x8A5 = 5.0`,
  `0x8A3 = 3.0`, `0x8B2 = 8`, `0x10000AA7 = 1`, `0x149 = 0x08000000`…). They are now
  sent with the crater (`[tutorial] crater_props`; `[]` = none).
- Position: at (13.5, 60.0) it was too far left. It is now at (17.0, 59.5).

## fase3-dc — without the template properties

- 22:21: with the `0x1D0008B6` properties the crater did not appear and the player's
  pings stopped showing on the minimap; no ping appears in the log. So they are turned
  off again. `[tutorial] crater_props = "template"` turns them on, or a list of
  `[id, type, value]` can be given.

## fase3-dd — crater next to the street lamp and a lava test

- 22:28: the crater moves a little closer to the street lamp (per the video): it is now
  at (15.5, 58.5).
- Possible lava: in placement list `0x1D0008CC`, next to the craters, is state
  `0x2E000A9F`. Its .entity `0x2D0008B6` is a flat 6 × 6 m piece (0.18 m high). It is
  created at the same point as the crater (`[tutorial] crater_extras = [[state, dx, dy], ...]`;
  `[]` = none).
- Minimap pings: they reach the server (22:26) but are not shown. The note reader
  (VA `0xA4B150`) keeps a single note per (category, variant): if one already exists,
  it overwrites it with the new object (`0xA144D0`). The guide markers use the same key
  (`0x1D`, variant 0/1) as the player's pings. Pending: `diag --notes`.

## fase3-de — player pings on the minimap and crater next to the street lamp

- `diag --notes` (22:34): the minimap notes for the player's pings are created and reach
  the HUD (category `0x1D`), but they are not drawn. They also share the
  (category, variant) key with the guide marker: a retreat ping only overwrote the
  marker's note. Pings were visible with category 1 (fase3-cl/cm) and stopped showing
  when everything moved to `0x1D` (fase3-cr). Player pings now use category 1
  (`[tutorial] player_note_category`) and the marker keeps `0x1D`.
- The extra `0x2E000A9F` was a turret base (not the lava): removed
  (`crater_extras = []`). It was useful for measuring the camera: +x goes up and to the
  right on screen, +y up and to the left, at ~53 px per metre. The crater mesh is offset
  ~(3.2, 0.3) m from its origin. Using the street lamp (~(18.2, 66.0)) as a reference,
  the crater in the video has its origin at ~(15.7, 60.3).

## fase3-df — drone/human thug fight, ping icons and crater

- Fight: the 21:52 diag shows the drone's table rejects `0x10000128` and `0x10000008`.
  Two out of three hits did nothing, hence the incomplete attack. The drone now only
  uses `0x10000124 + 0x100000EC`. The human thug strikes back half an interval later
  (`0x10000124`, `[tutorial] thug_attack_keys`) and the drone reacts.
- The human thug was standing sideways: his model faces +x at yaw 0 (in the layout,
  -1.529 points at the drone), while the drones' model faces +y. Corrected with
  `[tutorial] thug_yaw_offset` (π/2), which only changes where he faces, not the
  direction he moves in.
- Pings: with category 1 and variants 0/1, both types showed the same icon. The variant
  is now the client's ping type: 1 = alert, 2 = retreat
  (`[tutorial] player_note_variants`; this is an assumption).
- Crater at (18.0, 61.3).

## fase3-dg — ping icons with the client's category (requires `python ic.py patch`)

- 23:07: with category 1, alert and retreat showed the same icon. The client's ping
  category is `0x1D`: with it the guide marker shows the green retreat icon. The note
  reader adds 2 to the variant when the ping belongs to team 2 (the enemy icons), and
  the minimap does not draw those. Our alerts are sent with team 2 so they show red,
  which is why they did not appear. New patch: the addition becomes + 0
  (VA `0xA4B2FC`). Player pings go back to `0x1D` with variant 0 = alert and
  1 = retreat.
- Human thug: with +π/2 he had his back to the drone; now `thug_yaw_offset = -π/2`.
- First marker 1.5 m further ahead: (25.1, 60.3).

## fase3-dh — human thug facing forward and pings visible again

- Human thug: almost facing forward; he was ~30° off: `thug_yaw_offset = -π/2 + 0.52`.
- Pings: with `0x1D` (and the + 2 patch) they are not visible. The guide marker's green
  icon on the minimap does not come from a `0x1D` note, but from objective tracking
  (the guide ping `0x32`, type `0x12`, in the 22:34 diag). They go back to category 1,
  which is drawn, though with a single icon for both types. The retreat icon still
  needs to be found.

## fase3-di — the correct icon for each ping

- The UI (Flash, `MapNoteCategoryList` in `tools/gfx/classes_all.txt`) picks the ping's
  icon and animation by the note's CATEGORY, not by the variant:
  1 = PING, 17 = ALERT_PING, 18 = ALERT_PING_INGAME, 21 = RETREAT_PING_INGAME,
  22 = RETREAT_PING, 29 (`0x1D`) = BEACON. Alert now uses 18 and retreat 21
  (`[tutorial] player_note_categories`). `player_note_category` still works and sets a
  single category for both.
- Human thug: `thug_yaw_offset = -π/2 + 0.35`.
- Batman action inventory: `docs/batman_actions.md` lists the 354 keys in his scriptlet
  table, grouped, with the most likely name for each (some names share a number).
  `data/batman_actions.tsv` has the same list.
- Action tour: with `[debug] tour_keys = "all"` (or a list of keys), when the tutorial
  starts Batman runs them one at a time every `tour_interval` seconds (3 s).
  `server.log` records which one each is (`tour N/354: key name`).

## fase3-dj — ping icons the right way round, human thug's escape and the skills tool

- Pings: the icons were swapped. Now alert = 21 and retreat = 18 (the same thing
  happened with the ping classes).
- Human thug: when fleeing, the fight rotation is removed, which is what made his run
  look odd (he ran sideways). For the fight he shifts slightly to one side
  (`[tutorial] thug_shift = [0.3, -0.25]` m) without changing where he faces.
- Step 2 of the Batman plan: `python tools\skills.py ["Gaslight Batman" | 0x48...]`
  writes `logs\skills.txt` with the champion's skill sheets: resolved text (name and
  description of each skill, with `{}` where the game inserts the number) and each
  property with its value as an integer and as a float. In pack `0xA0000122`, record
  `0x48000615` contains the passive (Echoes), R (Bat Scream), Q (Sonic Batarang),
  W (Sonic Shell) and E (Bat Flight). The property names are not yet known.

## fase3-dk — the lava crater from the map

- The 23:53 dump finds nothing named "lava" or "crater". The meteor impact
  (`vfx_env_event_meteor_impact_*`) is only in pack `0xA000009A`, which the tutorial
  cannot load.
- But the map already has a lava crater next to the bank. In terrain pack `0xA0C112CA`
  (landblock `0x13cb`), at (38.31, 66.99), there are three world states at the same
  point: `0x2E001144`, `0x2E001145` and `0x2E001146` (.entity `0x2D000E6B/6C/6D`, in
  `0xA000024C`, which does load). The 46 carries a warm light. The big meteor now places
  those three, at (19.5, 63.0) (`[tutorial] lava_crater_at`). `crater_set = "old"`
  reverts to crater `0x2E0004BE`.
- `tools\skills.py` did not find the champion record by name. For Gaslight Batman it now
  also reads the already known records (`0x48000615`, the skills, and `0x48000617`, the
  champion).

## fase3-dl — the human thug returns to his original stance and no longer vanishes when fleeing

- 00:00 (video frame): the human thug fights sideways facing the drone, so the original
  position and orientation were correct. `thug_yaw_offset = 0` and
  `thug_shift = [0, 0]`. He still strikes back.
- When fleeing he vanished abruptly: the fog of war hid him as soon as he was behind the
  crates or the cart. When he starts running he is no longer subject to the fog (it is
  removed the same way on arrival).

## fase3-dm — skills: text per table

- `skills.txt` (00:03) mixed in descriptions from other champions (Catwoman, Ivy…): the
  same text token repeats across different tables. Text is now looked up by
  (table 0x2B, token).
- What is visible so far: each skill (Echoes, Bat Scream, Sonic Batarang, Sonic Shell,
  Bat Flight) carries its icon (`0x10000302`, a 0x13 image), its formula sheet
  (`0x100002a3`, a 0x48 record) and a list of stat/value pairs (`0x100004b6` = stat id,
  `0x100004b7` = value; `0x100004d2` looks like the per-rank value). For example, Sonic
  Batarang: 25 + 60, ratios 0.7 / 0.6 and stats 18 → 9, 30 → 14, 17 → 4, 22 → 1.25,
  15 → 5, 3 and 12. It is still unknown what each id is (cooldown, cost, range…): this
  will be cross-referenced with the `{}` in the descriptions and with what the game
  shows.
- Champion Gaslight Batman: `0x48000617` (pack `0xA00000B8`) → template `0x48000732`.

## fase3-dn — the earlier crater + red lava on top

- 00:04: the set by the bank (`0x2E001144-46`) was not it either: it shows a pale glowing
  hole. Back to the crater that did look similar (`0x2E0004BE`, `crater_set = "old"`),
  and on top of it, at the same point, `0x2E0005D6` is placed: it uses the same entity as
  the crater (`0x400004FD`), has three meshes and colour `0x2A0 = 0xFF0000FF` (red). It
  should be the lava. Changed with `[tutorial] crater_extras = [[state, dx, dy], ...]`
  (`[]` = no lava), and `crater_set = "lava"` tries the bank one again.

## fase3-do — Q cooldown on the button (start of the skill engine)

- The lava `0x2E0005D6` was a grey square: removed (`crater_extras = []`). The crater's
  visuals are left for later.
- Client event 0x20F8 (handler rva `0x4bc7c0`, reader rva `0x439bd0`): u8 0 |
  u64 agent | u32 slot | f64 end time. The client shows the remaining time on the button
  (`GM_UI.RecvNotice_StartSkillCooldown`).
- New `icserver/abilities.py`: Gaslight Batman's kit by slot (1 = Q, 2 = W, 3 = E,
  4 = R) with cooldowns (Q = 9 s from Sonic Batarang's stat 18; the others are
  provisional) and cooldown tracking. Casting Q sends 0x20F8, and it cannot be cast
  again until the cooldown ends (`[combat] cooldowns = { "1" = 9.0 }`,
  `enforce_cooldowns`).

## fase3-dp — Q shows as ready again after the cooldown

- 00:19: the cooldown sweep does appear, but when it ends the button stays grey. When the
  cooldown ends, another 0x20F8 is sent with 0 s remaining so the UI closes the clock
  (`[combat] cooldown_end_notice`).

## fase3-dq — short action tour

- 00:50: the full tour (354 actions) is almost entirely effects shared by every champion
  (states, items, emotes, cinematics): Batman's table is the union of several groups.
  `[debug] tour_keys = "core"` runs only 25: full Q/W/E/R, basic attack, critical, hit
  received, knock-up, incapacitated, get up, death, respawn, stunned, level up, spawn,
  teleport and 4 emotes.

## fase3-dr — coloured skill buttons (requires `python ic.py patch`)

- 00:59: the Q button always stays dimmed. The UI enables a button
  (`GM_Skill.RecvNotice_EnableSkillButton`, VA `0xa230c0`) only if none of its blocking
  conditions hold. Condition `0x1000003B` (VA `0xa1d3ad`) looks up the slot in an
  "available" list that the original server's scripts filled in and ours does not.
  Patch: that condition no longer blocks (rank 0 is still shown as locked separately).

## fase3-ds — knockdown with "incapacitated" and what remains of the tutorial

- Short tour (01:15): seen: full W, E and R; the basic attack (right/left) and its shots;
  the critical; the hit reaction; `_Defeat_StartupIncapacitated` /
  `_Defeat_OnIncapacitated`; and `Vfx_Bmg_Spawn`. Not seen: KnockUp, GetUp, death,
  respawn, revive, stunned, level up, teleport, or the emotes.
- Meteor knockdown: `_Defeat_OnIncapacitated` (`0x100001FB`), and after
  `[tutorial] knockdown_hold` s (5) `_Defeat_OnRevive` + `RunScript_Vfx_GetUp`
  (`getup_keys`) so that he gets up.
- What remains of Tutorial 1, according to its dialogue (after Catwoman):
  1. Catwoman's pursuers (0x1C9), and with them the level up and unlocking W
     (0x1E5, 0x1E4, 0x1C2).
  2. Practise Sonic Shell (0x1B1, 0x192). Then "More enemies!" (0x191, 0x199), another
     level up and ranking up a skill (0x1D9, 0x1D3), and clearing drones (0x1CC).
  3. Move forward (0x38D). Stolen power: surveillance camera (0x22B, 0x22A, 0x196,
     0x1BD, 0x1D2).
  4. Unlock E and practise Bat Flight (0x1C6, 0x1D1, 0x190, 0x1AA). More drones (0x1AE),
     rank up (0x1A1) and the Echoes passive (0x18F).
  5. Level 6 and unlock R (0x1E2, 0x1CB, 0x1DC). The camera sees drones far away
     (0x1A0…0x1B5); unlock the camera and use Bat Scream (0x1D8, 0x1D0, 0x3AC, 0x1A5);
     lock the camera again (0x1AD, 0x1A8, 0x19F).
  6. Another car on the road: stolen power Super Strength, throw the car (0x1C5, 0x1C1,
     0x1C0, 0x1B4).
  7. The Destroyer boss (0x1CF, 0x1D7, 0x1C7) and the ending (0x1BC).

## fase3-dt — English documentation for the repository

- All documentation is now in English: `README.md` (replaces `LEEME.md`), `docs/CHANGELOG.md` (this log),
  `docs/reverse-engineering.md` (consolidated findings: packs, string tables, skill data, events,
  properties, scriptlets, skill HUD, carriers, minimap, camera, patches, remaining tutorial content) and
  `docs/batman_actions.md` (replaces `docs/batman_acciones.md`, now with the action tour results).
- Code comments, help texts and log messages translated. Renamed: `tools/habilidades.py` → `tools/skills.py`
  (`logs\skills.txt`), `tools/buscar_scripts.py` → `tools/find_scripts.py`, `tools/extraer_registros.py` →
  `tools/extract_records.py` (`logs\records\`), `tools/diag_caminar.py` → `tools/diag_walk.py`,
  `logs\entidades.txt` → `logs\entities.txt`, `logs\portadoras.txt` → `logs\carriers.txt`.
- English flags (the Spanish spellings still work): `diag.py --walk --fix --force --started --walk-only
  --entities --ranks --fog --team --notes --minimap --create --place`; `ic.py --classic`;
  `[debug] tour_keys = "core"`. `doctor` prints `WARN` / `FAIL`.
- `.gitignore` added (local config, keys, logs, champions.json, patched exe).

## fase3-du — the bridge: from Catwoman's pursuers to the Bat Scream (requires `python ic.py patch`)

The rest of the first part of Tutorial 1, as described from the original's video, in a new module
`icserver/bridge.py` (the stage list is at its top):

- After the Catwoman cinematic Batman says "Or, Selina has left it to us to deal with her pursuers!" (0x1C9)
  and two drones come for him.
- Level 3: "Use your new skill point to unlock your next skill." (0x1C2): only W's "+" is highlighted and
  accepted. A yellow target drone appears ("Why don't you try out your new skill?"); only Sonic Shell hurts
  it (a basic attack makes Superman say "That target drone is only affected by skills…").
- "More enemies!": three drones appear around Batman. Level 4: upgrade Q (0x1D3); the gate at the start of
  the bridge opens, "We need to keep moving." and a marker on the bridge.
- On the marker the gate behind him closes and three drones attack (two melee, one ranged in the middle).
- Stolen Powers (0x22B, 0x22A): the D button (HUD element 22) gets Gaslight Batman's Surveillance Camera
  (skill 0x48000808, champion property 0x100008F0); "Place a camera here." with a marker; D on the spot
  places the camera (entity 0x40000265). Fallbacks while D is unconfirmed: an Alt/Ctrl+click on the spot, or
  automatically after `camera_auto_seconds` (25 s).
- "Well placed surveillance cameras…" then "Keep fighting your way to the base.": the middle gate opens. Four
  drones (2 melee, 2 ranged) are hitting the last gate; half way there the gate behind closes again; they
  turn on Batman when he comes close or attacks one of them.
- Level 5: unlock E (0x1D1); "Practice the skill on the target drone." (only Bat Flight hurts it). Then
  "Our enemy is sending more drones!" (4 drones), a skill point for the passive (0x1A1, Echoes), 0x18F.
- "Let's go!" (0x1E2): the last gate opens (and closes behind him). At the end of the bridge four drones are
  hitting a vehicle; attacking one brings all four. Level 6: "You can now unlock … The Bat Scream" (0x1DC);
  R's "+" ends the programmed part.

Skills (`icserver/batman.py`): W Sonic Shell (projectile to the point, hits everything within 3 m), E Bat
Flight (flies up to 9 m and hits where he lands; orders are ignored while he flies). Each has its cooldown on
the button (0x20F8, slots 2 and 3). The skill order's "ability" is the skill slot. Target drones only take
their skill. Batman heals out of combat and the Construct heals him when he is low ("Batman's health is
low…", once): he cannot die in the tutorial.

Client patch: cave D2 now marks HUD skill slots 0–7 dirty (was 0–5), so the D button (slot 7) is refreshed.

New `[tutorial]` options: `start_at` (jump straight to "bridge", "camera", "gate_fight", "unlock_e",
"e_practice" or "vehicle"), `bridge_positions` (move any spot), gate and drone settings, camera fallbacks,
`passive_auto_seconds`, `ranged_attack_range` / `ranged_attack_keys`, `regen_per_second`; `[combat]` W/E
damage, range, speed and radius. Tests: the e2e run plays the whole bridge (144 checks); `tests/test_jump.py`
checks every `start_at`.

Found on the way (see reverse-engineering.md): the skill slot enum (7 = Secondary1 = D), the slot → skill
property table (VA 0x15EDA28), the camera's skill and entity, the hint ids (22 Skill Charges, 23 Passive
Skills, 27 Earn Stolen Powers…), the tutorial's objective texts, and the three placement groups of the map.

Positions to confirm in game (Alt+click logs x, y): the middle gate, the marker on the bridge, the camera
spot, and the vehicle at the end of the bridge.

## fase3-dv — bridge edges, visible gates (test) and walking into a closed gate

From the first test of the bridge (2026-10-15 09:06, `start_at = "bridge"`):

- W (Sonic Shell) works from the real client: the skill order arrives with ability 2. The W "+" arrived as
  RankSkill slot 2. The Q "+" (upgrade to rank 2) never arrived; the server ranked it automatically after
  `auto_rank_seconds`. D sent nothing (the camera was placed by the fallback).
- **Batman walked round the gates over the water.** The server's map had no edge on the north side of the bridge,
  so the path went round the end of a closed gate. The clicks the client snaps to the walkable area give the
  bridge's width: from l = −2.5 to l = +2.3 m, straight up to s ≈ 66 m, where it opens out. New obstacles
  `BridgeNorth` / `BridgeSouth` (`[tutorial] bridge_edges`, `bridge_north`, `bridge_south`, `bridge_end`).
  When there is no way round, Batman now walks straight and stops at the obstacle (before: he did not move).
- Spots on the bridge moved to its centre line (they were up to 2.4 m to the north, on the edge).
- **The gates were invisible:** the Door entity `0x40000B0F` is placed but has no visible model. Each gate now
  also gets a carrier object with the door's second world state `0x2E0010F4` (`[tutorial] gate_models`).
  `[tutorial] gate_test = true` puts four candidates in a row on the street before the first gate (A world
  state `0x2E0010F3`, B `0x2E0010F4`, C `0x2E0012B7` = the other Door of the tutorial pack, D entity
  `0x40000C6E`) to see which one is the blue barrier.

## fase3-dw — the "+" for rank 2, Batman walking off, the Stolen Powers catalog

From the test of 2026-10-15 09:21:

- **Q could not be upgraded to rank 2 from the HUD** (the server ranked it after 40 s). The HUD's "+" is
  driven by SkillUpdate's `eCanRankSkill`, an ErrorType that the patched client takes from the nibbles of
  property `0x100006C1` — the server was putting the skill RANKS there, so a rank-0 skill always showed a "+"
  and a rank-1 skill never did. The nibbles are now "may be ranked now" flags (0 = the slot the tutorial waits
  for). Also explains the old "every skill shows the rank-up animation".
- **Batman walked off in a straight line through everything** right when the D button was given (both tests).
  That champion update carried the rank array (`0x100000AF`) with 8 elements (for slot 7) and the recommended
  slot 7. The client only reads that array for slots 1–5 (`GetSkillRank` returns the level for other slots), so
  the extra elements were useless and are the prime suspect: back to 6 elements, and no "recommended" D. A
  replay of the player's orders against the server showed nothing wrong on the server side (Batman stops
  where he should), so the runaway was on the client.
- **Stolen Powers:** the catalog record `0x480003CD` lists the 12 powers and 53 champion versions (65);
  `data/stolen_powers.tsv` has them with names and icons. A champion's own power is property `0x10000CE5` of
  its twin record.
- D still sends nothing to the server. `python tools\diag.py --stolen` logs whether the HUD reads the D skill,
  what the D button gets, and how far pressing D gets.

## fase3-dx — Batman running off (cause found), the gates' look

From the test of 2026-10-15 10:00 (with `tools\diag.py --stolen`):

- The Q "+" for rank 2 now works from the HUD (fase3-dw).
- **Batman running off for good:** after the D button was given (10:01:31) the client never refreshed the
  HUD again and Batman kept his last speed: the client stopped applying the champion's updates. The update
  carried property `0x100008F0` (the slot-7 skill) as a DID, but in the champion's data the slot properties
  (`0x100008E8` …) hold a whole skill structure, not a DID. It is no longer sent
  (`[tutorial] stolen_power_property`, default off). The D button still has no skill: place the camera with
  an Alt+click on the marked spot (or wait `camera_auto_seconds`).
- The diag also showed the HUD's SkillUpdate for slots 6 and 7 with no icon and that, at the start, slot 7
  already reports "can rank" (its nibble is outside what the caves read).
- **Gates:** `gate_test` showed that world state `0x2E0010F4` is the light wall (white); A (`0x2E0010F3` as the
  Door entity), C (`0x2E0012B7`) and D (`0x40000C6E`) show nothing. To make it blue (closed), the gate's own
  scripts are played on it one by one, 1.5 s apart: Vfx_OnInit `0x10000078`, Object_Closed `0x1000034F`,
  Vfx_Active `0x100000EB`, Vfx_Startup `0x1000018E` (`[tutorial] gate_keys`; server.log says when each one
  goes).

## fase3-dy — the bridge reviewed point by point, and the Bat Scream (requires `python ic.py patch`)

From the review of 2026-10-15 10:29 (with four screenshots of the original):

- **Q or W at level 4:** the skill point after the three drones may go to either skill, as in the original
  ("Click a highlighted button to upgrade either Sonic Batarang or Sonic Shell"); both "+" are highlighted.
  The tutorial can now wait for several slots at once, and exe cave E2 lets the "+" through for every slot
  the server flags (it used to allow only the recommended one): **re-run `python ic.py patch`**.
- **After the camera** the gate opens and a guide marker appears near the next gate, where the four drones are
  hitting it. They no longer notice Batman when he comes close: attacking one brings all four (the marker goes
  away then). `[tutorial] gate_drones_notice` / `vehicle_drones_notice` > 0 bring back the old behaviour.
- **E practice:** the yellow target drone appears ~5 m behind Batman, towards the gate he came through
  (replaced in fase3-ea by a fixed spot).
- **The vehicle** stands right where the bridge ends (s = 60 m, was 65), its four drones 4–6 m before it; they
  too only turn on Batman when attacked.
- **The Bat Scream (new):** after unlocking R the camera spots three drones hitting the middle gate on the
  camera's side (red alert marker on them; the cameras now give vision in the fog of war). Superman explains
  how to unlock the camera; the server listens for the client's `User.CameraLocked` preference (event
  `0x216E`, now logged as "client preference …") and goes on after `camera_unlock_wait` seconds without it.
  R fires a 60 m × 3 m line through the cursor that goes through the gates (`[combat] r_*`), 10 s cooldown in
  the tutorial. A miss: "Take a moment, aim…" (`0x3AC`). All three down: "Good shot!", then "Lock the camera
  back on Batman" (waits for `User.CameraLocked = True` or `camera_lock_wait`). Then the end of the
  programmed part. `start_at = "scream"` jumps straight there.
- **Gates still white:** they now get the player's team (property `0x1000009C`), on the idea that the game's
  light walls are team coloured (`[tutorial] gate_team`, `-1` = none). `gate_test = true` now shows five
  candidates: A `0x2E0010F3` team 1; B `0x2E0010F4` no team; C, D, E `0x2E0010F4` with team 0, 1, 2.

## fase3-dz — camera spot, the D button's data format (diagnostic)

From the test of 2026-10-15 10:57:

- **Camera spot** moved ~5.5 m further along the bridge (s = 14.5, just before the middle gate), where the
  original has it.
- **The D button:** the slot properties (`0x100008E8` for Q … `0x100008F0` for D) are not DIDs but whole
  property collections: in the champion record Q's is `0x100008E8 = { 0x100001C0 name, 0x100000E6, 0x100004AF
  { texts }, 0x10000302 icon, 0x100002A3 (0x48000154/0x48000156, a category), 0x100004B4, 0x100004B3 [stats],
  … }`, i.e. the skill's whole definition inline. The client's value reader (VA `0x507590`) reads value kind
  `0x0B` as a nested property table (reader VA `0x503330`, the same format as an object's property table), so
  the server can send one, but every property inside must have the size the client expects for it: the wire
  carries no kinds, which is why the DID sent in fase3-dw broke every later update. New
  `python tools\diag.py --props`: when loading ends it writes the client's whole property descriptor table to
  `logs\props.txt` (the property manager is the global at rva `0x1766cb4`, lookup VA `0x4fee60`), from which the
  D skill's collection can be built.
- **Gates:** still white with every `gate_test` candidate, team or not. The team property does not change it.

## fase3-ea — camera and E target spots

From the test of 2026-10-15 11:33:

- Camera spot: s = 12.5 (14.5 was too close to the middle gate).
- The E target drone no longer depends on where Batman stands: it appears at a fixed spot a little before the
  last gate (s = 35.5, where Batman stood in the screenshot; `bridge_positions.e_target`). Only Bat Flight hurts
  it (basic attacks, Q, W and R do nothing); one E landing on it destroys it.
- `tools\diag.py --props` now writes `logs\props.txt` at the first breakpoint of any kind, so it also works
  when the diagnostic is started after the match has loaded (11:31 it was, and nothing was written).

## fase3-eb — the finale: Super Strength, the Destroyer, the victory; D and F with real skill data

From the test of 2026-10-15 11:41 (with `logs\props.txt`) and five screenshots of the original:

- **E against the other drones:** Bat Flight aimed at a drone landed where the cursor was and "hit nothing": the
  server only took a drone within 1.5 m of the cursor as the target. Now 3 m (`[tutorial] skill_aim_radius`), and
  the drone it was aimed at is always hit when Batman lands next to it. A miss logs the nearest drone's distance.
- **After locking the camera** the tutorial goes on (it ended there).
- **Part 3, new (`icserver/finale.py`):** 0x1C5 "We've got another car in our way…", 0x1C1 "use Super
  Strength": the F button (HUD element 23) and a marker on the vehicle at the end of the bridge. Batman lifts it
  (F; while F sends nothing, an Alt+click on it or walking into it), carries it over his head (hint 26), 0x1C0
  "Look out, more drones!" (3 drones), 0x1B4 "Throw the car!": a right-click on a drone throws it; it explodes
  where it lands and destroys what is around. Then the Destroyer's cinematic (`0x35000028`, with its own lines
  0x1CF), 0x1D7 "You know what to do." and "Use what you've learned to reach the Destroyer": the Destroyer
  (variant `0x40000EB2`, 3000 health, does not fight back, Batman hits it from 7 m), a second car (world state
  `0x2E00074E`, 02PaddyWagonB) with a melee and a ranged drone hitting it (they turn on Batman only when attacked,
  marker on the car once in sight), two drones further on. The car's drones down: level 7 and a skill point for
  any skill (0x195). Lift the car, throw it at the two drones, 0x1C7 "We will not allow this machine…", "Defeat
  the Destroyer". Then the ending cinematic (`0x35000025`) and VICTORY (an objective text for now: the real
  victory screen is called by the client's own encounter scripts, `GM_Encounter.NotifyMatchEnded`, not yet
  reached from the server). `start_at = "strength"` / `"destroyer"`.
- **D and F with the real skill data:** with `logs\props.txt` the server builds each Stolen Power slot's skill
  collection from the game data (base skill of the catalog group + the champion version on top) and sends it as
  `0x100008F0` / `0x100008F1` (`icserver/skilldata.py`; `[tutorial] stolen_power_property = "auto"`, `false`
  turns it off). If Batman runs off again when D is given, turn it off and send `server.log`.
- **Object id clash:** meteors, the crater and the blast used ids 0x…130 + n, the same range as the server's
  entities (0x…100 up): now 0x…1000 + n.

## fase3-ec — the sphere, the second car

From the test of 2026-10-15 12:32:

- **The second car was invisible** (it blocked the way): the 02PaddyWagon world states (`0x2E00074D/4E`) are not
  in the tutorial's packs. It is the street's police wagon again (`[tutorial] car_b_wstate`).
- **The sphere:** cinematic `0x35000028` only shows the Destroyer and the four drones walking out. The falling
  sphere is the layout's PowerCore (world state `0x2E000AC5`, record `0x1D000789`: at (152.5, 28.0), dropping from
  z 215): the server now drops it there over 2 s, plays its start scripts as it lands, then starts the cinematic;
  it stays (`sphere_wstate`, `sphere_fall_seconds`, `sphere_from_height`; `finale_positions.sphere`).
- **The end:** in the original VICTORY shows over the ending's last shot (the base's structure), then an animated
  movie plays and the match ends. The server still only shows VICTORY as the objective. The movie
  (`GM_Encounter.RecvNotice_PlayEndOfMatchEncounterMovie`) is called from VA `0xa795e0`, a method of the client's
  end-of-match screen object (flags `+0x1a9`, `+0x1aa`, `+0xe4`; vtables at file offset `0x1203d80`…), not yet
  traced back to the network event that starts it.

## fase3-ed — Super Strength animations, the car's explosion

From the test of 2026-10-15 12:42 (the whole finale ran: lift, throw, sphere, second car, Destroyer, ending):

- **Lifting:** Batman's own Super Strength scriptlets, `SuperStrength_InitObjectPickup` (`0x100007A2`) then
  `SuperStrength_PickupObject` (`0x100007A1`) 0.4 s later, with the car as target (variable `0x108` and second
  object); the car rises over his head in 0.8 s instead of jumping there (`lift_keys`, `lift_seconds`).
- **Throwing:** `SuperStrength_ThrowObject` (`0x100007A0`), and the car leaves 0.35 s later, after the wind-up
  (`throw_keys`, `throw_windup`).
- **The explosion:** the vehicle has no scriptlets (its destruction is Havok's), so the blast is played on every
  drone it catches: `Vfx_Stp_Detonate_Matter_Explosion_Hit` (`0x100005B4`, the Detonate Stolen Power's blast) +
  the hit reaction (`blast_keys`), plus the dust cloud as before.
- `stolen powers: no property kinds`: the D / F skill data needs `props.txt` in the server's `logs` folder.

## fase3-ee — walking again after Super Strength

From the test of 2026-10-15 13:02:

- After the pickup animation Batman slid instead of walking, and kept sliding after the throw: once the pickup (and
  the throw) animation is over the server now plays `_Combat_GoToLocomotion` (`0x100002FD`) on him
  (`locomotion_keys`, `pickup_seconds`, `throw_seconds`).
- Objective while Superman explains Super Strength: "Another car blocks the way" (the part 1 objective stayed up).
- Open: the vehicle at the end of the bridge is invisible until it is lifted (the second car, the same world
  state, shows); the explosion on the drones (`0x100005B4`) shows nothing; the second car's real model
  (02PaddyWagon `0x2E00074D/4E`) is not in the packs the server knows of; the "Use Super Strength" label on the
  car. Next diagnostics: `tools\diag.py --scripts --create --place` and `ic.py entities 0x2E00074D 0x2E00074E`.

## fase3-ef — the invisible vehicle, a try at the car's explosion

From the test of 2026-10-15 13:11 (diag `--scripts --create --place`):

- **The vehicle at the end of the bridge:** the server created it at 13:11:24, but the client only built it (cave X,
  "object built … 0x2e000aab") at 13:11:40, when it was lifted and sent again. Placed vehicles are now sent again 1 s
  and 3 s after they appear (`[tutorial] prop_resend`).
- **The explosion:** the names table (pack `0xA0000038`, `u32 id | u32 length | name`) lists the Destructible
  events: `Destructible_AdvanceState` `0x10000063`, `Destructible_Damage` `0x10000010`, `Destructible_OnBreak`
  `0x100003A9`, `Destructible_OnCompletelyDestroyed` `0x10000290`, `Destructible_State0…9`, … In the client's
  property descriptors `0x10000063` is an INT property (kind `0x10`), `0x10000010` kind 1. So the car that lands is
  now sent with property `0x10000063` = 1, then 2 (0.3 s later), stays 4 s as a wreck and goes
  (`car_break_property`, `wreck_seconds`).
- The drones hitting the second car now stand between Batman and the car, where the tester marked them
  ((131.6, 17.2) and (131.3, 15.1)).
- The diag's 100-line budget per breakpoint was used up by the gate scripts before the finale: no script results for
  the blast. Run it with only `--scripts` next time, starting at `start_at = "strength"`.

## fase3-eg — lifting with one animation, the second car closer to its drones

From the test of 2026-10-15 13:21 (the vehicle at the end of the bridge now shows):

- Lifting played SuperStrength_InitObjectPickup and then SuperStrength_PickupObject; the tester saw Batman go down
  "like at the start" before lifting. Only `SuperStrength_PickupObject` (`0x100007A1`) now (`lift_keys`).
- The second car moved to (134.0, 16.2), 2.5 m behind the two drones hitting it (it was 4.5 m).
- The car's wreck property (`0x10000063` = 1, 2) showed nothing; the car just vanishes 4 s after landing.


## fase3-eh — car B closes the street, the paddy wagon model, explosion probes

From the test of 2026-10-15 13:35 (Batman walked past car B on its south side, at y 11.5):

- Car B moved to (134.3, 14.8), 1.4 m further south across the street. Its walking block is now
  7.5 m × 1.8 m half-sizes (`[tutorial] car_b_box`). That reaches the south wall and the crates behind the car.
- `[tutorial] finale_obstacles` adds more collision shapes around car B. They use the same format as
  `[combat] obstacles`.
- Car B's model: the encounter layout `0x1D000771` (pack `0xA0000256`) places `02PaddyWagonA` / `B` with world
  states `0x2E00034D` / `0x2E00034E`. The earlier `0x2E00074D` / `4E` were a misreading. `car_b_wstate` is now
  `0x2E00034D`; `0x2E000AAB` brings back the police wagon if the paddy wagon does not show.
- Explosion probes:
  - When a thrown car lands, `Vfx_OnExplode`, `Destructible_OnBreak` and `Destructible_OnCompletelyDestroyed` run
    on it (`car_explode_keys`).
  - The drones caught by the blast also get `Vfx_OnExplode` and `Vfx_Inf_Explode`.
- `tools/extract_records.py vehicles` (or `--follow`) copies both cars' world states and every record they point
  to: script tables, rigs and models. Their destruction data is needed to find the real explosion.
- The encounter layout `0x1D000774` has the four drones around the Destroyer at (151.7, 25.8), (153.9, 22.5),
  (152.8, 26.6) and (155.2, 23.6). These are noted for the drone positions still to fix.

## fase3-ei — walls at car B, what the cars' records show

From the test of 2026-10-15 13:56. The paddy wagon shows, but Batman still got past car B and "jumped" near the
crates. The long box made the server's way round go past the box's south end, through the wall, because the server
did not know about the wall there.

- New `[tutorial] finale_obstacles` (default) from the clicks the client snapped to the street's edges:
  - `CarBSouthWall` (y < 11.25 for x 117–139).
  - `CarBNorthCrates` (the crates and fence line, y 18.65 → 22 for x 117–141).
- Car B's box (7.5 × 1.6 half-sizes) now reaches into both walls, so there is no way round. Batman stops at the car
  (simulated: clicks past it end at x 131–133). Once the car is thrown the street is open again.
- `logs\records` (13:56) shows:
  - `0x2E000AAB` (the street / bridge police wagon) is a static prop: one-bone rig `0x2D0008BC`, script table
    `0x1D000199`, no destruction property.
  - `0x2E00034D` (02PaddyWagonA, car B) is the destructible one:
    - skeleton `0x2D000238` with breakable parts (`env_gas_deco_vehicle_a_*`: chassis, body, doors, hood, wheels…);
    - property `0x5B5` → `0x1C000021`;
    - script table `0x1D0000BB`;
    - Havok collision (`hkpMoppCode`).
  - The break steps (`0x10000063` = 1, 2) and the explode scriptlets now land on a car that can actually break.
- `tools/extract_records.py destruction` copies `0x1C000021`, `0x1D0000BB` and `0x1700163E`. `--all` writes every
  place an ID appears, because the first match for `0x1D0000BB` was mesh data, not the record.

## fase3-ej — extract_records finds records that do not start with their ID

From the `logs\records` of 2026-10-15 14:08 (`extract_records.py destruction`):

- `0x1C000021`, `0x1D0000BB` and `0x1700163E` are in pack `0xA000024C`'s ID list, but none of the places their
  IDs appear is the record:
  - all the hits for `0x1C000021` are references from world states, for example `0x2E00034D` and another one with
    model `0x17000BC4`, or mesh index noise;
  - the records do not begin with their own ID.
- `--all` now also prints where the pack's ID list puts the record (the records around it) and writes
  `<DID>_region@<offset>.bin`: the bytes between the neighbours found before and after it.
  - Checked on `0x1D000890`: its first match is out of order at `0x14D044`; the list puts it between `0x3400058F`
    (`0x37202C`) and `0x13002F91` (`0x373654`).
- `destruction` now also includes `0x2E00034D`.

## fase3-ek — car B turned across the gap, the paddy wagon's crash

From the test of 2026-10-15 14:15 (the collisions at car B now hold):

- Car B is turned to −50° and sits at (134.3, 15.0). It now runs from the crates (131.5, 18.4) to the building
  corner at (137, 11.6). Straight across the road it left a visible gap at its front.
- Its two drones moved off its west side: (130.1, 15.6) and (130.9, 13.4).
- `CarBSouthWall` follows the building corner and the street turning north-east, up to x 143.5. This is from the
  clicks the client snapped there: (138.5, 12.1), (141.2, 13.3), (143.1, 14.1).
- `logs\records` (14:11, the new `_region` files): the paddy wagon's `0x1C000021` is a Havok behavior graph,
  `env_gas_vehicle_paddy_wagon_behavior.hkb`.
  - States `Idle01` / `Idle02`. Each has an idle clip and a crash clip: `env_gas_deco_vehicle_a_cin_car_a_crash.hkx`
    and `…car_b_crash.hkx`.
  - Behavior strings `State_to_State`, `IdleState01` and `IdleState02`. The character also names
    `env_gas_vehicle_paddy_wagon_exploding.hkx`.
  - The world state sets enum property `0x100003F2` to `IdleState01` (`0x10000117`).
- When a thrown car lands, `0x100003F2` is set to `State_to_State` (`0x10000050`), then to `IdleState02`
  (`0x10000116`) 1 s later (`car_crash_states`, `car_crash_step`). The wreck stays 6 s (`wreck_seconds`).
- `[tutorial] bridge_vehicle_wstate` sets the car at the end of the bridge. The default is still `0x2E000AAB`,
  which cannot break; `0x2E00034D` is the paddy wagon, which can.

## fase3-el — the paddy wagon's model axis, both cars breakable, Destroyer start probes

From the test of 2026-10-15 14:30 (picture: car B stood along the road, leaving a gap by the building):

- The paddy wagon's model lies along its yaw + 90°, while the street's police wagon lies along its yaw. Since
  fase3-eh car B's walking box was across the road while the car itself stood along it.
  - `tutorial1.MODEL_YAW_OFFSET` (−90° for `0x2E00034D` / `4E`) is added when spawning, so the box and the car now
    share one yaw.
  - Car B now covers the crates → building corner line (−50°).
- The car at the end of the bridge is now the paddy wagon too (`bridge_vehicle_wstate` = `0x2E00034D`), so both
  thrown cars can break. `0x2E000AAB` brings back the police wagon.
- Car B starts as the behavior graph's `IdleState02` (`car_b_behavior_state`), the graph's second car.
- On landing, `car_explode_keys` also tries `_EventHook_OnCollision_RaiseBehaviorEvent` (`0x100001DD`) and
  `_HFSM_BehaviorRaiseEventAction` (`0x100001E3`).
- The sphere that falls and opens: the Destroyer's world state `0x2E000AB5` is the "chr_Min_DDD_Guardian" (rig
  `0x2D0008C6`, script table `0x1D0003BA`, property `0x6F3` = `0x1000011F`). Its start scripts
  (`destroyer_spawn_keys`, default the sphere's) run on it 0.3 s after it spawns.

## fase3-em — what `diag --scripts` showed: the Destroyer's cinematic scriptlets, the car's empty table

From the test of 2026-10-15 14:54 (`diag.py --scripts`):

- The thrown car (paddy wagon on carrier entity `0x40000B0F`) has an EMPTY scriptlet table. Every script tried
  on it at landing was rejected (`0x80070057`): `Vfx_OnExplode`, `Destructible_OnBreak`,
  `Destructible_OnCompletelyDestroyed`, `_EventHook_OnCollision_RaiseBehaviorEvent`, `_HFSM_BehaviorRaiseEventAction`.
  - `0x2E00034D` is now in `PROP_WSTATES`, so the server looks for the paddy wagon's own entity in the packs at
    start. The `props:` line shows whether one exists; if so the car is created as that entity and gets its
    scriptlets.
- The drones accept `Vfx_OnExplode` and `Vfx_Stp_Detonate_Matter_Explosion_Hit`, but reject `Vfx_Inf_Explode`.
- The sphere prop (`0x2E000AC5`, rig `0x2D0008D5`) has an empty scriptlet table too: its start scripts were rejected.
- The Destroyer (`0x40000EB2`) has a 6-group scriptlet table with `Cinematic_Startup` (`0x100007EB`),
  `Cinematic_Hidden`, and `CinematicCharacter_State00` / `01` (`0x10000E5B` / `0x10000E5C`). The old start probes
  were rejected.
  - It is now spawned before its cinematic (`destroyer_in_cinematic`), running `Cinematic_Startup` +
    `CinematicCharacter_State00` (`destroyer_start_keys`).
  - When the cinematic ends it runs `CinematicCharacter_State01` + `Vfx_Spawn` (`destroyer_open_keys`).

## fase3-en — car B where the tester pinged it, the bridge car is the other paddy wagon

From the test of 2026-10-15 15:09 (screenshots from the original's video, in order: the street vehicle, the bridge
vehicle, car B):

- The street vehicle and car B have the right models.
- The car at the end of the bridge did not: in the original it is another wagon.
  - It is now `02PaddyWagonB` (`0x2E00034E`), the layout's other wagon.
  - Its world state uses model `0x17000BC4` and the same breakable behavior graph `0x1C000021` (pack
    `0xA000024C` at `0x153ED74`).
  - `bridge_vehicle_wstate` switches it back.
- Car B runs between the tester's two Alt+clicks, (133.3, 16.0) and (134.5, 9.8): centre (133.9, 12.9), −79°. Its
  walking box still reaches into both walls; the drones stay clear of it.
- `0x2E00034E` is also looked up for an entity of its own (`props:` line).

## fase3-eo — ending the match: VICTORY page, post-match movie, Tutorial 2 unlocked

From the test of 2026-10-15 15:21:

- Car B sits between the last two Alt+clicks, (132.9, 16.2) and (134.1, 10.5): centre (133.5, 13.35), −78°.
- After the ending cinematic, the server sends the client's real end-of-match messages (see
  docs/reverse-engineering.md "Ending a match"):
  - notice `0x1000000E` (NotifyMatchEnded) with Batman's team as the winner, so the page shows VICTORY;
  - the end-of-match stats `0x2045`, which the end page also needs before it fills in;
  - `0x214B`, the completed encounters, with Tutorial 1.
  - The end page itself plays the encounter's post-match movie, Batman's story, the first time.
  - `[tutorial] send_match_end`, `send_match_stats` and `winning_team` turn these off or override them.
- `icserver/progress.py` keeps the completed encounters in `data/progress.json` and sends them at every login
  (before `0x2080`), so Tutorial 2 stays unlocked. Delete the file to lock it again.

## fase3-ep — Launch works after the victory, the VICTORY banner gets its time

From the test of 2026-10-15 15:55. The post-match movie (Batman's story) played (`User.HasSeenPostEncounterVideo`
arrived) and the client went back to the home screen. But:

- **Launch ignored after the movie.** Every Launch was ignored ("a match is already being set up") and the client
  dropped the connection ("check the ports"). The session was still PLAYING with the old game connection open, and
  the client sends nothing when it leaves for the home screen.
  - Now the victory marks the match finished.
  - The next JoinQueue closes the old game connection, ends the match and queues normally.
- **No VICTORY banner.** The banner over the scene did not show: the movie started 0.7 s after the end notice.
  - The end-of-match stats `0x2045`, which complete the end page and start the movie, now go 6 s after the notice
    (`match_stats_delay`), so the VICTORY state can show first.
  - The objective line "VICTORY" is gone (`victory_objective`).

## fase3-eq — objective off at the end, car B centred, holding the car, a second match in the same login

From the test of 2026-10-15 16:14:

- **Objective at the end.** "Defeat the Destroyer…" stayed on screen after the end. At the victory the objective
  is now cleared and the objective tracker turned off (`0x2075`), before the VICTORY state.
- **Car B centred.** Its middle showed at (132.9, 13.9), the tester's Alt+click, while it was spawned at
  (133.5, 13.35). The paddy wagon's origin is (0.66 along, 0.47 across) its line (`MODEL_ORIGIN`); the car is now
  spawned so that it looks centred, and its walking box stays on the line.
- **Holding the car.** After the pickup, Batman went back to plain locomotion (no hands-up pose).
  - He now gets his carrying state `RunScript_SuperStrength_Object_Active` (`0x100005D4`, in his scriptlet table
    per diag 14:54; `carry_keys`). Locomotion only comes back after the throw.
  - The carried car no longer gets Batman's speed: the client was running it ahead between updates.
- **Bat Scream.** It missed some drones. The wave now starts 1 m behind Batman and is 4 m wide plus 1 m for the
  drone's size (`r_width` 4).
- **Second match in the same login.** After the victory, Launch got a match that stuck at 15% loading. The client
  still holds the old world's objects.
  - The new match removes the previous match's server objects before creating its own.
  - It continues the object sequence numbers (`Match.seq_base`).
  - `[match] remove_stale_objects` turns the removal off.

## fase3-er — the end of the match the way the client expects it

From the test of 2026-10-15 16:32. The client left the world 0.1 s after the match-ended notice, never showed the
VICTORY overlay, reported port problems on the home screen, and the next match stuck before loading. Static
analysis (docs/reverse-engineering.md "Leaving the match world"):

- **Leaving the world.** The server now ends a match like the original: notice `0x1000000E` + `0x214B` at the
  victory, the stats `0x2045` 6 s later, and `0x2021` "exit lobby" (room id) 8 s after the victory
  (`exit_lobby_delay`).
  - The client leaves the world and answers `0x12D`.
  - Only then (1 s later) does the server close the game connection and go back to MENU. Closing it earlier is
    what the client reports as a connection problem.
  - The next match removes the old objects and continues the sequence numbers, as in fase3-eq.
- **Objective banner.** The centre text "Defeat the Destroyer…" is the objective's banner. Clearing the objective
  now also empties its banner.
- **Bat Scream.** Cast while walking, Batman slid on. He now stops (speed 0) and stays rooted for the cast
  (`[combat] r_root`, 1 s).
- **`tools/diag.py --matchend`** (`--finpartida`): breakpoints on the world teardown (with its caller), the
  connection status codes, the load-gate flags, `0x2021`, the end page, the stats and the movie lookup.

## fase3-es — VICTORY in the world first, the movie every time, the game connection stays open

From the test of 2026-10-15 17:06 (`diag --matchend`).

What the test showed:
- The match-ended notice itself makes the client leave the world at once and show the results at home. Its UI
  state machine runs a "leave world" action on that event.
- Closing the game connection 1 s after `0x12D` caused the "connection problem" teardown 3 s later.

Changes:
- **VICTORY first.** When the ending cinematic ends, the objective banner says VICTORY ("Defeat the Destroyer…"
  goes) and Batman gets `Cinematic_Victory` (`victory_keys`).
- **Then the match end.** `victory_hold` (6 s) later, all at once:
  - the movie preference reset (`0x216A`);
  - the match-ended notice;
  - the completed list;
  - the stats.
- **The movie every time.** `User.HasSeenPostEncounterVideo@0x40000991` is set back to False through `0x216A`
  before every match end (`replay_post_match_movie`). Batman's story plays after every Tutorial 1.
- **No exit lobby by default.** `0x2021` is no longer sent (`exit_lobby_delay` = −1): the client leaves by itself.
- **The game connection stays open.** After `0x12D` the match ends but the game connection is no longer closed;
  the next referral's connection replaces it.
- **Tutorial 2.** `0x40000A81` stalling at 15% is not a client-state problem. The server has no data for that
  map yet: it sends Tutorial 1's objects and packs.

## fase3-et — Super Strength from Batman's animation graph, the car's own explosion, casts that show, the victory and reward screens

From the test of 2026-10-15 17:36 and a static analysis of Batman's animation graph, the Super Strength scripts and
the intro cinematic. See docs/reverse-engineering.md.

**Lift and carry**
- **Lift:** Batman stops and faces the car, then gets `SuperStrength_InitObjectPickup` (bends down and grabs it)
  and, `lift_step` (0.5 s) later, `SuperStrength_PickupObject` (lifts it).
- **The car on the lift:** it stays where it is until the lift, then goes straight up to `carry_height` (2.7 m),
  its middle over his head.
  - Before, it slid into Batman at ground height, which is likely why he sank "under the map".
- **Carrying:** the graph's Hold state walks with the hands up on its own. Nothing is sent to Batman while he
  carries.
  - `0x100005D4` was a Stargirl effect, not a carry state.
  - Skills are ignored until the throw.
- **Throw:** `SuperStrength_ThrowObject`; the car leaves his hands at 0.20 s (`throw_windup`). Normal walking
  comes back at 0.9 s.

**Explosion:** the cars now get their world state's script table (property `0x7D2`, plus `0x5B5`)
(`[combat] prop_script_tables`). On landing they run their own `Vfx_OnExplode`, as in the original's cinematic.
The property tries (`0x100003F2`, `0x10000063`) are off.

**Casts and attacks**
- **Animation order:** every scriptlet on Batman goes `[scripts] champion_defer` (0.06 s) after the messages of
  the same moment. A champion bundle (facing, stop, visible again) sent right after the cast was cutting the
  animation; this applies to Q/W/R, the basic attack and `Cinematic_Victory`.
- **Stop to cast:** Q and W stop Batman where he casts and hold him there `[combat] cast_root` (0.35 s); R keeps
  `r_root`.
- **Q with no target:** it is now still thrown towards the cursor; before, nothing happened.

**Car B position:** centred between the 17:25 pings (134.0, 14.0), along them. The model offset is now (0.68
along, 0 across), taken from the paddy wagon's skeleton; the 0.47 m across was the "to one side".
`[tutorial] car_model_origin` overrides it.

**Destroyer down**
- "Defeat the Destroyer…" is cleared at once.
- Batman is hidden only when the ending cinematic starts (`ending_delay` 1.0 s); before, he vanished as soon as
  the Destroyer fell.

**Victory**
- At the end of the cinematic (Superman's last line), three things fire together:
  - the client's ShowAnnouncement "VICTORY" (`victory_announcement`);
  - the objective banner (`victory_banner`);
  - `Cinematic_Victory`.
- `victory_timeline_banner = true` tries the timeline banner too.

**Reward screens**
- When the tutorial starts, Gaslight Batman is sent as not owned (`replay_champion_unlock`).
- At the end of the match he turns owned (`0x20B8`) and a ribbon "item fulfilled" (`0x2095`) is sent. This is the
  trigger for the home screen's "Champion Unlocked" → abilities → "Mission Complete" sequence.
- `reward_champion = 0` turns this off.

## fase3-eu — the lift's CarPickup event, the keepalive after the match, the ending's strip

From the test of 2026-10-15 19:21.

**Lift**
- The test: Batman bent down and stayed crouched. Both orders were accepted (diag), but the graph's
  `Pickup_Start` waits for the event CarPickup, which `PickupObject` does not raise on its own.
- The fix: with the last lift key the server now raises CarPickup (`0x10000246`) through
  `_HFSM_BehaviorRaiseEventAction` (`0x100001E3`, variable `0x780` = the event, an enum), the same way the
  client's own raise-event script node does it (`[tutorial] lift_events`, `raise_event_kind`).
- He cannot walk off while lifting (`lift_lock`). Before, the car stayed behind and then caught up with him.

**After the match**
- The `time` keepalive now belongs to the game connection, not to the match.
- Before, it stopped at the match end, and 60 s later the client dropped the connection with an error: "You have
  been disconnected", "verify ports 9000-9036".

**Destroyer down:** the objective goes inactive, so its strip goes too, not just its text.

**Victory**
- The yellow objective-banner VICTORY is off (`victory_banner = ""`); the announcement stays as a placeholder.
- The real boxed VICTORY is the client's end-of-match state (HUD hidden, EndOfMatch camera, splash). Its
  definition is in the UI state machine data in pack `0xA00000D0`, which is needed to see why event `0x21` leaves
  the world at once.

**Rewards:** the ribbon's text is "Gaslight Batman" (`reward_text`).

**Pings:** a Ctrl+click is always a ping, even on the car; only an Alt+click lifts it. An Alt+click on the car is
now logged with its position.

## fase3-ev — playing again after a match, the carried car keeps up, the cars' positions

From the test of 2026-10-15 20:22.

**Playing again after a match**
- Back home, the old game connection is still open (keepalive). The client closes it itself after the new
  referral, and that close ended the NEW match.
- The client's next game connection then got a bare stand-in match: objects from sequence 1, stuck at 15 %,
  "Unable to connect to Match".
- The old connection is now let go when the player queues again. The e2e test now plays the real sequence: 0x12D,
  queue again, the old link closes after the referral.

**The carried car keeps up with Batman**
- It moves with his speed and heading, sent with each of his movement updates, and gets speed 0 the moment he
  stops (`carry_follow_speed`).
- Before, it was only put where he was, 4 times a second.

**Car positions**
- The bridge's car (0x2E00034E) has no origin offset again; it had been right.
- Car B is centred between the tester's two pings, (133.1, 17.2) and (134.6, 10.6).

**UI data for the VICTORY and the reward screens:** `tools\extract_records.py uistate` dumps the UI state
machine records of pack 0xA00000D0 (`--swf` adds its SWF records) to `logs\records\0xa00000d0`.

## fase3-ew — the boxed VICTORY billboard and the scorecard's data (UI pack 0xA00000D0)

The tester sent the UI pack, `0xA00000D0`. Its ActionScript library gave the field names and enums used here.
Notes: `docs/ui-pack-0xa00000d0-notes.txt`.

**The VICTORY billboard**
- ShowAnnouncement's field `a` is the billboard type:
  - 2 is the plain strip we had been getting;
  - 9 MatchWin and 11 Team1Victory create the big blue boxed WinLoss billboard.
- Now sent as type 9, with source and target team = the player's team.
- `0x2038` (UI event MatchEnded) goes with it (`send_match_ended_event`).

**NotifyMatchEnded:** the field order is `uWinningTeam, uPlayerTeam, fMatchDuration, nTier, fTargetTime`. The
second field is now the player's team; it was 0.

**The empty page after the movie** is the scorecard, which is MISSION COMPLETE for a tutorial. It shows only when
it has all its data. New `icserver/scorecard.py` builds what it waits for:
- `0x2190` header and protector icons
- `0x2081` currency balance
- `0x2080` account level and XP
- `0x20B9` soft-currency reward
- `0x2104` character level and XP
- `0x2188` accolades
- `0x2090` amplifier sets
- `0x219F` and `0x219E` standings

These are sent with the match end, then again 5, 25 and 60 s later (`send_scorecard`, `scorecard_resend`).

**`0x2095`** is a small "upgrade unlocked" ribbon whose DID is an icon, not the Champion Unlocked panel. It is off
(`reward_ribbon_icon`).

**Champion Unlocked and the showcase** come from the client's trainee achievements, built from achievement
definitions that are not in the packs we have. `tools\extract_records.py achievements` finds them in every pack.

## fase3-ex — training achievements: Champion Unlocked and the showcase

The tester sent the achievement records (218, from `tools\extract_records.py achievements`). The tutorials'
training achievements are:

| Tutorial | Achievement | Encounter | Reward set |
|---|---|---|---|
| 1 | `0x40000B08` | `0x40000991` | `0x40000B07` |
| 2 | `0x40000BD5` | `0x40000A81` | `0x40000C57` |
| 3 | `0x40000C59` | `0x40000CA6` | `0x40000C55` |

The trainee list is `[0x40000B08, 0x40000BD5, 0x40000C59, 0x40000EB9, 0x40000EBA]`.

**At login:** `0x2120` (achievement progress) now carries the 5 trainee achievements. The tutorials already done
are completed. Before, `0x2120` was an empty table.

**At the end of a tutorial:**
- `0x2120` marks its achievement newly complete (current 1, previous 0).
- `0x2125` (pending reward sets) carries its reward set with the champion as the item.
- The client shows the "Champion Unlocked" super-reward ribbon for a Character item. When it is dismissed, the
  client plays the champion's showcase movie (`0x10000C58` on `0x49000086`).
- The scorecard's `0x2190` sends the pending reward again.
- `[tutorial] send_achievements`.

**Note:** the client's trainee or first-time-player status (which loads the trainee screens) also depends on the
account level. Our account is level 30, so it counts as "Player". The reward panel and Mission Complete do not
depend on that status.

## fase3-ey — VICTORY inside the ending cinematic, the match ends with it; cars towards their rear

From the test of 2026-10-15 21:40.

**VICTORY**
- The test: when the cinematic ended, the camera went back to Batman, then VICTORY showed, then the match closed.
- Now the big VICTORY billboard (and the `0x2038`) goes out during the ending cinematic, after Superman's last
  line: `victory_in_cinematic` = 18.5 s after it starts (it lasts about 23 s).
- The match ends the moment the cinematic ends (`victory_end_delay` 0).

**Cars 2 and 3** are moved 0.8 m towards their rear (`car_back_shift`).

## fase3-ez — the scorecard resends stay out of a new match

21:35: the 25 s scorecard resend landed in the next match's load. Resends now go out only while no other match
has started. Replaying the tutorial in the same login still stalls at 15 %; that needs `diag --matchend` during
the second load (the load gate at 0xa99e20).

## fase3-fa — replaying in the same login, the match ends inside the ending cinematic, the reward panel after the scorecard

From the test of 2026-10-15 22:09 (`diag --matchend`) and a static analysis of the second load.

**Replaying the tutorial (stuck at 10-14 %)**
- Cause: the client's world teardown keeps the world objects. Our creates for the new match reused the same ids,
  so the client took them as updates; the "object created" listeners never fired and the load never moved on.
- When the client leaves a finished match (`0x12D`), every object of that match is now removed (`0x3`): the
  champion, the player and all server objects (`remove_objects_on_leave`).
- The client frees a removed object only 30 s later, so the next match's objects wait until then
  (`[timing] object_free_seconds` = 31).
- The 10 % shown by the second load is normal: its packs are already loaded.

**The client's 60 s lobby watchdog**
- Every accepted `0x2016` arms it, and only the game connection's "connected" status clears it.
- With the `0x2016`s sent after that status, it fired after the player left the world: a second teardown, an exit
  lobby (`0x2021` handler) and an error.
- `0x20AF` and `0x2016(0)` now go before the game welcome (`enter_match_first`), and the room-id `0x2016` is no
  longer sent with the lobby data (`lobby_room_check`).

**Match end:** the match now ends just before the ending cinematic does (`match_end_in_cinematic` = 22.6 s after
it starts; the cinematic lasts about 23.0 s). Before, the camera went back to Batman first.

**Reward panel**
- The client holds reward ribbons while the scorecard is up.
- When it closes the end page (`0x20A6`), the server sends `0x2190` again, which makes the client pass its pending
  Champion Unlocked reward to the UI again, no longer held (`reward_after_scorecard`).

**Account level and the Training Missions screen:** that screen (the trainee status) needs account level < 5.
Ours is 30, so the account counts as a veteran. `[account] level = 1` is the test for it.

## fase3-fb — cars 2 and 3 placed

22:35: the tester asked for twice the earlier shift in the other direction. `car_back_shift` = −0.8 m (it was
+0.8), so both cars move 1.6 m from where fase3-fa put them.

## fase3-fc — one folder: the diagnostic's debugger is in tools\

- `tools\tracer.py`, the earlier project's debugger, is now part of this project.
- `tools\diag.py` uses it by default; `[debug] old_server_dir` is optional and only overrides it.
- README: "One folder, ready for GitHub".

## fase3-fd — back to the old lobby order (the first load stalled at 55 %)

22:43: with `0x20AF` + `0x2016(0)` before the game welcome and no room-id `0x2016`, the first Tutorial 1 load
stopped at 55 %. Both are back as before (`enter_match_first = false`, `lobby_room_check = true`). The other
fase3-fa changes stay.

## fase3-fe — Champion Unlocked on request; replaying Tutorial 1 in the same login

Static analysis of the 22:49 run (the ribbon never showed; the replay stopped at 10 % and the client gave up 60 s
later).

**Champion Unlocked**
- The client passes a `0x2125` (pending reward set) to the UI only once, when it arrives. At match end the client
  is still in the world, nothing listens and the reward is lost; resends with the same instance id are ignored.
  `0x2190` does not resend it (the earlier note was wrong).
- The real chain starts at the end page: the client sends `0x212E` (pending achievement notifications), the server
  answers `0x211F` (an empty table: `00 00 00`), the UI then asks `0x2124` (pending rewards), and the server answers
  with the `0x2125`. Continue on the ribbon sends `0x2128` (claim); the client then plays the showcase movie by
  itself (achievement record property `0x10000BCD`).
- The `0x2125` is no longer sent at match end (`reward_at_match_end = false`); it is kept for the session and sent
  on `0x212E` (with the `0x211F`, `reward_with_banners`) and on `0x2124`, until it is claimed.
  `reward_after_scorecard` (the `0x2190` on `0x20A6`) is off.

**Replay**
- The client's world teardown destroys every object and resets its local player id to 0. Only `0xEB` (set local
  player, sent at login) sets it again, so on the second match the player was never "local", no `0x211B` came back
  and loading stopped at 10 %.
- `0xEB` is now sent again before the lobby data of every match after the first (`[match] resend_local_player`).
- The `0x3` removals after `0x12D` and the 31 s wait did nothing (the objects were already gone): off by default
  (`remove_objects_on_leave = false`, `[timing] object_free_seconds = 0`).

**Diagnostics:** `tools\diag.py --reward` and `--replay` log the two chains above.

## fase3-ff — skill HUD: colours, D and F, no "+" on D/F (requires `python ic.py patch`)

23:40 (tester): the reward ribbon, its showcase movie and the replay all work (fase3-fe confirmed: the `0xEB`
resend and the `0x212E` → `0x211F` → `0x2124` → `0x2125` chain).

- **Learned skills grey:** cave E answered Flash's *rank* query (the IDs were swapped in our notes) with the
  "may rank now" flags. It now returns the client's real rank (exe patch).
- **Basic attack grey:** its rank (element 0 of `0x100000AF`) was 0, and the array was only sent once Q was
  learned. It is now sent from the first champion bundle with the basic attack at rank 1.
- **"+" on D and F at level-up:** slots 7/8 kept "can rank = no error". They now answer
  `SkillRank_NotHighEnoughLevel` (exe patch); slot 8 is refreshed too.
- **D and F:** they need the slot's skill collection, which the server builds from `logs\props.txt`
  (`tools\diag.py --props`). That file was missing, so neither button had a skill. The server now looks for
  the file again on every use (it appears while the server runs). With the skills there, the camera timer and
  "lift on touch" are off (`[tutorial] skill_buttons_only`): D, then a click places the camera; F lifts the
  car (also with the cursor off the car when Batman is next to it). Alt+click on the car still works.
- `0x2128` (claim) has no leading `u8`.

## fase3-fg — Q/W/E colours, D/F icons, F works; the Stolen Powers dictionary

00:17 (tester): basic attack and passive in colour, D places the camera at the cursor. Still: Q/W/E dull,
no icon on D/F (only "6", the level), F does nothing. Static analysis:

- **Q/W/E dull:** the "not enough Will" look. Flash's skill bar reads the champion's Will when it is set up (at
  the link) and our first vitals (`0x42`) came only after the intro, so it saw Will 0; Q/W/E have a cost, R
  does not. The champion's vitals now go with every champion bundle, from the first create on
  (`[match] vitals_with_bundle`).
- **No icon on D/F:** Flash fully sets up only the slots that have a skill at the link; D/F got theirs later.
  Both slot collections now go in the first bundle (`[tutorial] stolen_powers_from_start`); their buttons stay
  hidden until the tutorial grants them, and orders before that are ignored.
- **F sent nothing:** Super Strength targets an entity (targeting type 14) and the client's picker refuses our
  car, so no order. On slot 8 it is now a ground-target skill like the camera (`[tutorial] strength_targeting
  = 1`): F, then a click on (or near) the car.
- **Stolen Powers dictionary:** `python ic.py stolen-powers` lists all 65 and writes their full skill data to
  `data\stolen_powers.json` (from your install; not in the repo). `python ic.py stolen-powers <text>` searches
  by power, champion or DID. `camera_skill` / `strength_skill` accept names, e.g.
  `"Super Strength / Superman"`.

## fase3-fh — D and F without props.txt; slower walk while carrying

01:12 (tester): no D/F icons, D and F did nothing, the car was lifted on touch again. The log says why:
`logs\props.txt missing` (it had been deleted with the logs), so the server had no skill data for D/F and fell
back to the old automatic behaviour.

- The value kinds of the 48 properties that the Stolen Powers catalog and its 65 skills use are now built into
  `skilldata.py` (taken from the client's descriptors). D/F no longer depend on `props.txt`; when the file is
  there it is read on top.
- While carrying the car Batman walks at `[tutorial] carry_move_speed` (3.0 m/s, was the normal 4.5): the
  hands-up walk is slower and he slid.

## fase3-fi — the game ID catalog

`catalog/index.html`: one page with a menu (Champions, Skills, Stolen Powers, Artifacts, Amplifiers, Stages,
Skill slots, Properties, Network events, Scriptlets, HUD elements, Data packs, Exe patches), search across
every section, sortable columns and a copy button on every ID. The data is `catalog/data/*.tsv`;
`python ic.py catalog` rebuilds the page. Artifacts and amplifiers are empty until their catalogs are found in
the packs. See `catalog/README.md`.

## fase3-fj — the documentation phases (catalog with 21 sections)

All ten documentation phases have a first version; `catalog/README.md` has the state of each.

- **New sections:** Artifacts (228), Amplifiers (162 augments + 172 mods), Item stats (21), World objects,
  Characters, Animations, Effects, Cinematics, Conversations, Key records. Properties now lists the client's
  3,822 property descriptors with their value kinds (`kind_code`), with meanings where known.
- **Scanner:** `python ic.py catalog --scan` reads a full install (`tools/catalog_scan.py`) and refreshes the
  pack map, every champion's skill set, artifacts, amplifiers and item stats. Hand-written notes for packs
  and skills live in `packs_notes.tsv` / `skills_notes.tsv`.
- **Game data reader:** `icserver/gamedata.py` (records by DID across packs, property kinds, English string
  tables). The string-table reader is fixed: tail streams are chunked like the payload and one stream holds
  many tables (8,547 English strings from 11 local packs instead of 28).
- **Search:** `python ic.py find <text or ID>` looks in every catalog table.
- **AI guide:** `docs/AI_GUIDE.md` (rules, where to look, the "record every discovery in the catalog, the RE
  notes and the changelog" rule).
- **Validation:** `tests/test_catalog.py` checks the tables and lists game IDs used in the code that the
  catalog does not mention yet.
- **Findings:** skill stat 15 is most likely the cooldown (it drops per rank) and stat 3 the cost; the
  earlier reading took stat 18 as the cooldown. Artifacts/augments/mods catalogs and record layouts are in
  `catalog/data/records.tsv` and the scanner.
- **Fixed in the docs:** paddy wagon IDs (`0x2E00034D/4E`), meteor rock `0x2E000BB3` vs dust `0x2E0007D4`,
  last gate `0x2E000CD7`, the swapped rank dispatcher IDs in `patcher.py` comments, the reward resend note in
  `scorecard.py`. Remaining inconsistencies are listed in `catalog/README.md`.

## fase3-fk — the full-install scan (07:47)

The tester ran `python ic.py catalog --scan` on the full install:

- `packs.tsv`: 616 packs, 68,900 records, 309 packs with English text tables.
- `skills.tsv`: the six skills (basic, Q, W, E, R, passive) of all 43 champions with names, icons, targeting
  type, script and stats, plus the two implemented Stolen Powers (260 rows).
- Stat 15 drops per rank in every kit, so it is the cooldown (seconds). Gaslight Batman's real cooldowns are
  Q 5 s, W 8 s, E 20 s (−2 per rank), R 110 s (−10 per rank); `icserver/abilities.py` still uses the earlier
  guesses (9 / 12 / 14 / 80 s) and will be corrected with the skill work.

## fase3-fl — throw, car effects, face-down knockdown, victory voice, asset tables

08:02 (tester): an extra "+" left on the HUD; Batman keeps walking after a throw; no fire when a car explodes;
second car 0.8 m back; no Victory voice; the meteor knockdown sometimes falls backwards.

- **Extra "+":** the passive's upgrade button (19) was restored by `start_at` because the passive has a rank there.
  It stays hidden now.
- **Throw:** Batman stops, faces the target and is locked for the throw (`[tutorial] throw_lock`, default
  `throw_seconds`); attack orders during the lock are ignored too.
- **Car effects** (thrown-object script `0x34000167`): Vfx_OnInit when the car appears, Vfx_OnThrown during the
  flight, Vfx_OnCollision at impact and Vfx_OnExplode 0.2 s later (`car_init_keys`, `car_thrown_keys`,
  `car_collision_keys`, `car_explode_delay`). To confirm with `tools\diag.py --scripts` whether the car accepts them.
- **Second car** (the bridge's): 0.8 m further to its rear (`[tutorial] car_extra_back_shift`).
- **Victory voice:** announcer line `0x250` as a conversation with the billboard (`victory_voice_lines`; a
  candidate, the original's way is not found).
- **Knockdown always face down:** graph events Knockdown → Dead → GetUp instead of `_Defeat_OnIncapacitated`, whose
  fall direction the graph's Lua picks at random (`knockdown_mode`).
- **Catalog:** new sections Asset types (record types by DID prefix) and Animation graphs (every `.hkb` and its
  `.hkx` clips), both from `python ic.py catalog --scan`; big tables show 400 rows with a "Show all" button.

## fase3-fm — carry, throw aim, sphere scripts, camera range

12:18 (tester): the car hangs to one side and above Batman's hands; no fire yet; second car 0.8 m more; throw
range markers and the camera's range missing; emotes (Ctrl+1...); the "+" on the HUD; the sphere should fall and
open with the drones and the Destroyer already there.

- **Carry:** the car's middle is put over Batman along the car's own yaw (the offset went sideways) for both cars,
  and lower (`carry_height` 2.1, was 2.7).
- **Throw:** a 4 m arc and half a turn of tumble (`throw_arc`, `throw_spin`); while carrying, F is Super
  Strength's own throw skill `0x480003C9` (range ring, F + click throws), back to Super Strength after the throw.
- **Explosion:** the wagon accepts only `0x5` and Vfx_OnExplode; `0x5` is sent when it appears and before the
  explosion (`car_init_keys`, `car_collision_keys`).
- **Second car:** 1.6 m to its rear in all (`car_extra_back_shift`).
- **Camera (D):** out of range (10 m, `camera_range`) Batman walks until the spot is in range, then places it.
- **Sphere / props:** every prop built on a carrier gets its world state's own scriptlet templates, read from the
  packs at server start (the sphere's start / open scripts were all rejected).
- **The mouse icon with a green "+"** is original HUD art (basic attack = right click); nothing to hide.
- **Emotes:** the animations are known (graph events); the client's emote message is still to be captured.

## fase3-fn — Launch delay, second car, explosion, profile icons

14:02 (tester): after the overview movie the Launch screen shows again for a few seconds before loading; the
second car went forward instead of back (move it twice that the other way); unlock cosmetics such as profile
icons. 14:05: the explosion animation is not the right one.

- **Launch delay:** logging no longer blocks the server. Every log line used to open, append to and close the
  file (about 150 ms per line on the tester's machine, about 3 s between JoinQueue and the referral); one writer
  thread now keeps the logs open. A `traffic.log` over 32 MB is renamed to `traffic.old.log` at start. About 2 s
  between the movie's end and JoinQueue are the client's own.
- **Second car** (the bridge's): `car_extra_back_shift` is now -1.6 (3.2 m back from fase3-fm, 1.6 m behind the
  original spot): +1.6 had moved it forward.
- **Explosion:** the meteor dust cloud at the landing point is gone (`[tutorial] blast_wstate` = 0; it was a
  meteor effect). The car's real explosion data (script 0x3400015F with Vfx_OnFire, the breakable model) is
  documented; it is not reproduced yet.
- **Profile icons:** the 134 Protector (avatar) icons are sent as owned with the item statuses
  (`icserver/cosmetics.py`, `[account] unlock_avatar_icons`). Picking one sends an event the server does not know
  yet: it lands in `logs\unhandled.log`. New catalog section "Avatar icons" (names: `python ic.py catalog --scan`).
- **Handoff files:** `CLAUDE.md`, `docs/HANDOFF.md`, `docs/re-notes/`, `tests/e2e.example.toml`.

## fase3-fo — freezes and "server disconnected": start-up game data off the match

14:23 (tester): "server disconnected" messages again, freezes, Batman running through buildings without stopping.

- **Cause:** at start the server read the props' scriptlet tables from the packs (three big packs decompressed in
  Python) in a background thread. On the tester's machine it took about 80 s and, in the 14:10 run, it was still
  running in the middle of the match (finished 14:11:42): the network threads were starved, every log line took
  250-300 ms (14:11:08-14:11:32) and the movement updates came late (Batman ran on past the walls).
- **Now:** that reading (and the profile icons list) runs once **before the ports open** ("reading the game
  data" on the console) and is cached in `data/game_cache.json` (DIDs only; rebuilt when a pack file changes).
  Later starts take a moment.
- **Console output** also goes through the log writer thread: a print to a slow (or text-selected) Windows
  console can no longer block the server.
- The profile icons' names are read only by `python ic.py catalog --scan` (reading every pack's text is slow).
- Folder check: the tester's `icserver\` had stray copies of the package files (`session.py`, `finale.py`,
  `__init__.py`...) next to `ic.py`. They are not used (the code is in `icserver\icserver\`) and can be deleted.

## fase3-fp — logs that stop, second car, yellow "+", profile header

14:41 (tester): the Launch screen still comes back for a few seconds after the overview movie; the second car keeps
moving towards the side of the bridge; a yellow "+" above the passive, left of the skills bar (not the red rank-up
"+"); gates still white; cameras (D) still appear wherever clicked; the explosion is still not the right one; the
profile icons still do not show. The 14:31 logs stop right after the server start.

- **Logs:** with the console printed by the file writer thread, the very slow console of the tester's machine
  (about 250 ms a line) held the writer back and everything queued was lost when the window closed. The console
  now has its own thread and shows only the latest 40 pending lines (the files get every line; they are flushed
  at least every 0.5 s).
- **Second car:** the offset ran along the car's long axis, which on the bridge lies across the road (hence "towards
  the side"). Back to the original spot (`car_extra_back_shift` empty; tester's choice).
- **Yellow "+":** elements the tutorial never uses are hidden at the first level-up / `start_at`: Stolen Power
  T-skill 21, Artifact Foundry button 24, artifact slots 29, Recall 43 (`[tutorial] hide_hud_elements`). Which one
  the yellow "+" is remains to be confirmed.
- **Profile:** the home header (0x2190: name + 5 Protector icon slots, each opening the icon picker) is now sent at
  login with the first 5 avatar icons (`[account] send_profile_header`).
- Not changed yet: gate colour, the car's real explosion (see reverse-engineering.md "14:02 findings"), the camera
  range (the code walks Batman into range; the 14:31 run left no log to see what happened).
- 14:57 (tester stopped the first start with Ctrl+C while it read the packs): `gamedata.Game.world_state` searched
  every record start of the pack for each world state (10-20 s per call on the 114 MB pack 0xA000024C); it now
  finds the record header (`did | 7`) directly: all seven world states in under a second after the pack is
  decompressed.

## fase3-fq — HUD back, profile icons kept, smoother throw

15:14 (tester): about a second of the Launch screen after the overview movie; the HUD gone; the thrown car's
flight looks odd; the profile icons now show but a chosen one does not stay on the card; the second car is right.

- **HUD:** hiding elements 21 / 24 / 29 / 43 hid the whole skills bar (its `HideElement` hands every id but
  RecommendedText to the base class, which hides the bar). Nothing is hidden now (`hide_hud_elements` = []).
- **Profile icons:** picking one sends **0x2093** (u32 icon | u32 slot). The server saves it in
  `data/progress.json`, answers **0x2154** (icon, slot) and uses the saved icons in every 0x2190.
- **Throw:** 20 flight steps (was 10) and no spin around the vertical axis (`throw_steps`, `throw_spin`).
- **Launch:** the server now answers JoinQueue in under 5 ms (15:10:37.338 -> referral 37.342); the remaining
  ~1.5 s between the movie's end (preference at 15:10:35.77) and JoinQueue is the client's own.

## fase3-fr — amplifiers, car wreck, new champions found

15:31 (tester): are Zod, Arcane Harley Quinn, Arcane Zatanna, Nightmare Catwoman, Deathstroke, Deadshot, Dex-Starr,
Raven and Huntress in the files (with attacks and animations)? The victory voice still does not play; the
Amplifiers tab is empty; a "check the ports" error after the match; the Champions tab does not load the champions;
the thrown car flies off in another direction instead of bursting.

- **Champions:** all nine are in the install, each with its own behavior graph and attack / Q / W / E / R clips
  (catalog Characters, "champion (not in the roster)"). They are not in `data/champions.json`: adding them needs a
  roster entry built from each one's pack cluster (next step).
- **Amplifiers:** the 162 augments and 172 mods of `catalog/data/amplifiers.tsv` are sent as owned (0x20B8 content
  types 12 / 13, `[account] unlock_amplifiers`).
- **Car impact:** the wagon's Vfx_OnExplode breaks it apart in the client's physics and launches the body; the
  wreck now goes 0.25 s after the explosion (`wreck_seconds`, was 6.0).
- Profile header icons only take avatar icons (content type 3) from the owned list.
- Not changed: victory voice (conversation 0x250 via 0x2001 plays nothing); the port error and the Champions tab
  (the logs show no error from the server; client event 0x95 on the game connection and 0x21A4 x3 are unanswered).

## fase3-fs — nine more champions, queue at the movie's end

15:44 (tester): enable the champions found in the files; the Launch screen still flashes after the overview
movie. (Also: "Unable to connect to Match. Please verify ports 9000-9036 and 5000-5036" after a match.)

- **Champions:** `icserver/roster.py` finds every champion cluster of the install that `data/champions.json` lacks
  and adds it to the roster at server start (cached in `data/game_cache.json`; `[account] extra_champions`): Arcane
  Zatanna, Deathstroke, Raven, Deadshot, Dex-Starr, Huntress, Nightmare Catwoman, Zod, Arcane Harley Quinn. The
  rules were checked against Krypto's entry in champions.json (all 13 fields equal). No costumes for them yet.
- **Launch:** when the overview movie's preference arrives (`User.SawEncounterOverviewMovie@<encounter>`), the
  server queues the player at once (`[match] queue_on_movie_end`); the client's JoinQueue ~1 s later only gets the
  queue answers again.

## fase3-ft — the companion app (new interface)

15:59 (tester): "redesign the whole interface, one that looks modern and nice and works for everything", then go
back to the Tutorial 1 details. Chosen: an app of our own next to the game (the in-game menus stay as they are),
covering home / play, profile and cosmetics, champions and skins, amplifiers and Stolen Powers; dark, modern DC
look.

- **`python ic.py app`** starts the server and opens the app (`http://127.0.0.1:8888/app`, an Edge or Chrome app
  window, else the default browser). It is served by the server's own HTTP port; nothing new to install.
- **Play:** the Play button starts the game when it is not running; after the login the server queues Tutorial 1
  by itself (`[app] queue_after_login`, `queue_after_login_delay` 1.5 s), so the match loads without going through
  the in-game menus. With the game already in the menus, Play queues at once.
- **Champions:** the 52 champions (43 + the 9 added in fase3-fs) with search, New / Playable filters and a detail
  panel (art, abilities with icons and stats, skins).
- **Profile:** the 5 profile-card icon slots and the 134 avatar icons. Choosing one saves it
  (`data/progress.json`) and updates a running game at once (0x2154).
- **Arsenal:** amplifiers by brand (augments and mods, readable names and stats), artifacts with icons and stats,
  Stolen Powers.
- **Pictures** are decoded from the player's own install (texture records 0x13, DXT1/3/5 and BGRA) in a separate
  process and cached in `data/texcache/` (not committed). The champion art uses property 0x10000799 first: the
  pregame wallpaper 0x100005B0 is an emblem for Zod and Deathstroke.
- New files: `icserver/webapp.py`, `icserver/textures.py`, `icserver/webui/` (index.html, app.css, app.js),
  `tests/test_app.py` (16 checks: routes, Play before and after the login).
- Config: new `[app]` section (`launch_game`, `queue_after_login`, `queue_after_login_delay`, `open_window`).

Tests: e2e 178/178, jump 24/24, movie queue 8/8, app 16/16.

## fase3-fu — League-style app, movie queue rolled back

16:23 (tester): wants the app to look like the League of Legends client. Also: since fase3-fs the overview movie
was cut after half a second, the loading screen showed while the movie's audio kept playing, and in the match no
dialogue line had sound.

- **Rollback:** `[match] queue_on_movie_end` is now `false`. The client queues by itself again after the movie,
  as before fase3-fs. The short flash of the Launch screen is back, but the movie and the dialogue audio are
  intact. `tests/test_movie_queue.py` turns the option on to keep testing it.
- **App, new layout:** the top bar has a PLAY button, the Home / Collection / Arsenal / Profile tabs, a queue
  timer and the player's icon and level. A status column on the right shows the server, the game client and the
  Training progress. Gold on deep navy, Cinzel headings.
  - PLAY opens a mode select: Training / PvP / Versus AI, then a list of stages, a picture, and Confirm. Confirm
    does what Play did in fase3-ft (starts the game, then queues after the login).
  - Home: the Tutorial 1 banner plus tiles for the new champions and the profile icons.
  - Collection: champions in gold frames (search, filter) with a full-page champion view (art, ability icons,
    skins), and an Icons tab to fill the five profile-card slots.
  - Arsenal: amplifiers (brand filter), artifacts, Stolen Powers.
  - Profile: the crest with level, the five card icons, Training progress.

Tests: e2e 178/178, jump 24/24, movie queue 8/8, app 16/16.

## fase3-fv — Robin, Arcane Supergirl, Star Sapphire, John Stewart; glass interface

16:36 (tester): enable Robin, Arcane Supergirl and Star Sapphire, and any other champion in the files. Make the
interface as clean, aesthetic and intuitive as possible, with transparencies, after LoL and Heroes of the Storm.

- **Robin, Arcane Supergirl, Star Sapphire:** their entries in champions.json each have a costume that repeats the
  champion's own variant, so the client got that variant again as a costume and lost the champion. Those costumes
  are no longer sent (`[account] skip_base_costumes`, default true).
- **More champions:** all behavior graphs of the install were compared with the roster. New: **John Stewart**, a
  champion that was never released. He has his own graph, skill set and pictures, but no sound bank, so he may be
  silent (`[account] unreleased_champions`, default true). **Nightwing** was already being added on the tester's
  install. `roster.py` searches again once (cache key `extra_champions_v2`).
- **App:** the champion's art fills the window behind frosted-glass panels:
  - the top bar, the status panel, the lists and the mode select;
  - rounded cards and pill buttons;
  - gold only for PLAY and Confirm.
  
  The champion page shows that champion's art full screen. Unreleased champions carry their own badge.

Tests: e2e 178/178, jump 24/24, app 16/16, movie queue 8/8.

## fase3-fw — server light, friends list and chat

16:51 (tester): drop the server status panel; put a server icon in the top bar with three colours (red, yellow,
green). Add the friends list, chat and the other social parts.

- **Server light** (top bar): green = server ready; yellow = it answers but is busy (the game is starting, queued
  or loading, or an answer took over 1.5 s); red = no answer. Hover it for the details (game closed / in the
  menus / in a match).
- **Friends panel** (right side; the friends button in the top bar shows or hides it, remembered per browser):
  - your status (Online / Away / Busy; "In game" while the game is connected);
  - add a friend by name, and requests from people who added you (Accept);
  - Online and Offline groups with unread counts; hover a friend to remove them.
- **Chat:** a dock at the bottom right with one tab per conversation, minimize and close. Messages to friends who
  are offline wait for them.
- Anyone who opens the app on this server is a user, known by the account's player name. A friend on the same
  network sees you when their app points at your server. Friends, messages and read marks are kept in
  `data/social.json` (not committed; `[app] social_file`); presence is in memory (offline 20 s after the app stops
  polling).
- New: `icserver/social.py`; routes `GET /api/social`, `POST /api/social/friend`, `GET/POST /api/chat`.
  `tests/test_app.py` now has 23 checks.

## fase3-fx — legacy / new interface switch

16:58 (tester): the first start should open the legacy interface (the game's own menus). There should be a button to
switch to the new interface (the client says it will restart, then opens in the new one), and one in the new
interface to switch back. Launch / Play must start the tutorials in both, and when a match ends the chosen
interface should come back.

- **`python ic.py play`** opens the interface chosen last (`data/progress.json` "interface"). On the first start
  that is the legacy one (`[app] default_interface`). `python ic.py app` chooses the new one, and the new
  `python ic.py legacy` chooses the legacy one.
- **New → legacy:** Settings (gear, top bar) → Switch to legacy → "Restart in the legacy interface?" → the
  launcher shows "Restarting…" and closes. The game opens, or comes to the front if it is already running.
- **Legacy → new:** **Ctrl+Shift+U** while the game runs (`[app] switch_hotkey`). The game is minimized and a
  Windows box asks "Switch to the new interface? The game will close and Infinite Crisis will restart in the new
  launcher". Yes closes the game and opens the launcher; No brings the game back. A button inside the game's own
  Options menu would mean editing the game's Flash UI (in the packs); not done.
- **After a match** in the new interface: when the end page closes (client event 0x20C4 after a match ended), the
  game window is minimized and the launcher comes to the front, 3 s later (`[app] return_to_app_after_match`,
  `return_to_app_delay`). Play in the launcher brings the game window back as the match loads. The legacy
  interface keeps the game's own flow.
- New files: `icserver/interface.py` (mode, Switcher) and `icserver/winctl.py` (Windows windows, process,
  message box and hotkey helpers through ctypes; they do nothing on other systems). New route:
  `GET/POST /api/interface`. The app's title is "Infinite Crisis Launcher", so it is not confused with the game
  window. `tests/test_app.py` now has 30 checks.

## fase3-fy — duplicate champions in the game's list

17:07 (tester): six champions showed twice in the game's champion list: Zod, Arcane Zatanna, Raven, Deathstroke,
Nightmare Catwoman and Arcane Harley Quinn. The second copy had another champion's portrait (Nightmare Batman,
Sinestro, Solomon Grundy, Arcane Green Lantern, Mecha Wonder Woman, Harley Quinn) and loaded one of that champion's
skins.

- Cause (fase3-fv): the new rule for unreleased champions (clusters without a sound bank) also took six costume
  clusters. Each sat just before the cluster of the champion it was named after, so it was judged before that
  champion was known. Their variants are costumes of other champions in champions.json.
- `roster.py` now judges those clusters only after every released champion is found. A cluster is dropped when its
  variant is a known costume variant, or its name or graph pack belongs to a released champion. `extend()` also
  never adds the same name or variant twice. Cache key `extra_champions_v3` (searched again once).
- On the tester's install this leaves 52 + 11: the nine of fase3-fs, Nightwing and John Stewart.

## fase3-fz — Launch screen back after the overview movie

17:16 (tester): Tutorial 1 → Launch → the overview movie, then the Launch screen came back instead of the loading
screen. A second Launch loaded the tutorial.

- Log: the preference `User.SawEncounterOverviewMovie@0x40000991` arrived at 17:15:35 (the movie). No JoinQueue
  followed. At 17:15:45 the client asked for the screen's banners (0x212E): it was back on the Launch screen, with
  the movie over. JoinQueue came only with the second Launch at 17:15:50. In the working run at 17:10 the client
  sent 0x20C4 on Launch and its own JoinQueue 3 s after the preference; this time it sent no 0x20C4.
- The server now remembers the movie. If the client's next message in the menus is the banner request (0x212E),
  within 90 s and without its own JoinQueue, the server queues the player itself 0.3 s later. The movie is over by
  then, so nothing is cut (unlike fase3-fs, which queued at the preference itself). A JoinQueue from the client
  cancels the wait. Config `[match] queue_after_movie` (true) and `queue_after_movie_window` (90).
- `tests/test_movie_queue.py`: 15 checks.

## fase3-ga — falling meteors with collisions, emotes on Ctrl+1..4

17:29 (tester): the 3 meteors at the start are not the right ones: they should be a bit bigger, block the way and go
away after a while. At the first marker the crater with lava should appear (another crater than the current one).
Program Ctrl+1..4.

- **Meteors** (`[tutorial] meteor_mode = "entity"`, the default): each one is created as an entity 18 m up and falls
  onto its spot in 8 moves over 0.7 s (`meteor_fall_height`, `meteor_fall_steps`, `meteor_fall_seconds`).
  - On the ground it blocks Batman's way with a 1.6 × 1.6 m square (`meteor_block_half` 0.8).
  - It goes away after 20 s (`meteor_lifetime_small`), or earlier when the next marker removes the group, as before.
  - Twice the old size (`meteor_scale` 0.6, was 0.3).
  - `meteor_mode = "prop"` gives back the old static rocks.
- **Emotes:** the game hands Ctrl+1..4 (Joke, Taunt, Laugh, Dance) to a script method whose network message is
  unknown; no unhandled event shows up for them. The server now watches those keys itself while the game window is
  in front (a keyboard hook that never swallows keys). It raises the emote on Batman's behavior graph:

  | Key | Emote | Graph event |
  |---|---|---|
  | Ctrl+1 | Joke | `0x1000022E` |
  | Ctrl+2 | Taunt | `0x1000022C` |
  | Ctrl+3 | Laugh | `0x1000022D` |
  | Ctrl+4 | Dance | `0x100001F1` |

  Walking cancels an emote (the graph's own rule). `[app] emote_keys` turns this off. New `icserver/emotes.py`,
  plus `winctl.watch_keys`.
- **Crater:** not changed yet. The tester's earlier reference picture is needed again.

Findings for the meteor event (pack 0xA000009A, a PvP map, not loaded by the tutorial), recorded in
reverse-engineering.md:
- the rock `env_event_meteor_a` (graph 0x1A0002BF, world states 0x2E0005F7 / 0x2E000BB3);
- the ground warning `vfx_env_event_meteor_warning` (0x2E0004E5, graph 0x1A000217);
- the impact `vfx_env_event_meteor_impact` (13 fragments and a plume, graph 0x1A00021F);
- the dust ring (graph 0x1A000365).

Script table 0x1D00019C ties them together. Also present: `env_event_meteor_fragment` (graph 0x1A0002BA,
.entity 0x2D00044D; world state 0x2E00131C in 0xA000024C, which the tutorial loads).

## fase3-gb — sound catalog

17:47 (tester): the meteors make a sound while they fall; is there a dictionary of the sounds?

- There was none. New `python ic.py sounds` (`icserver/audio.py`) reads `audio\Audio_SB.pck`. It lists the 1687
  Wwise events with their bank and the game records that play them (typed value kind 0x2C), and the 41 banks named
  from the packs' 0x52 records. New catalog sections Sounds and Sound banks. The committed tables came from the
  packs staged in the cloud session. On the full install `python ic.py sounds` completes the "played_by" column.
- The meteor sounds are in bank **mse_Meteor**, declared in pack 0xA000024C, which the tutorial loads. Effect
  record 0x170001C4 plays three of them together with the rock 0x2E000BB3 and the dust 0x2E0007D4. It hangs on
  0x2E0002EC, the probable complete falling meteor; it will be tried next. Details in reverse-engineering.md.

## fase3-gc — the game's meteor effect (dust and sound)

17:59 (tester): use the complete meteor effect now.

- `[tutorial] meteor_mode = "effect"` (new default). Each of the start meteors places world state **0x2E0002EC** on
  its landing spot. That is the generic effect object 0x2E000013 (.entity 0x2D000063) with property 0x1EB = effect
  **0x170001C4**, which names the rock, the dust cloud and three sounds of bank mse_Meteor; all are in pack
  0xA000024C. Property 0x1EB = 0x170001C4 is also sent explicitly.
- After 1 s (`meteor_effect_land`) the rock that stays appears on the ground. It is the fase3-ga entity: it blocks
  the way and goes after 20 s. The effect object is removed after 6 s (`meteor_effect_seconds`).
- `meteor_effect_rock = false` leaves only the game's effect. `meteor_mode = "entity"` gives back the fase3-ga fall
  (rock only, silent).
- Not yet seen in the game: the effect may need a start key, or may show its own rock. The e2e check now accepts
  either object.

## fase3-gd — meteors fall again, dust, smaller contact, pushed by Batman

18:11 (tester, fase3-gc logs): no sound while falling, no dust, the collision area was bigger than the rock, the
rocks popped up instead of falling. Touching a rock with Batman should push it away from him.

- The effect object 0x2E0002EC showed nothing (sent at 18:09:17, no visible result). `meteor_mode` is back to
  `"entity"`: the rock falls from 18 m.
- On landing:
  - the dust cloud 0x2E0007D4 is placed there (`meteor_dust`, `meteor_dust_scale` 0.5, `meteor_dust_seconds` 3);
    it is the object that showed as dust under the thrown car;
  - the effect 0x170001C4 (rock + dust + mse_Meteor sounds) is tried as the rock's own property 0x1EB
    (`meteor_land_effect`, 0 = off).
- No fixed blocking square any more (`meteor_block_half` 0). Every 0.15 s, if Batman is within 0.9 m of a rock's
  centre, the rock slides away from him along the line from him to it, to 1.5 m (`meteor_push`,
  `meteor_push_radius`, `meteor_push_extra`, `meteor_push_speed`).
- Emotes (17:46 log): Ctrl+1..4 reached the server (Joke, Taunt, Laugh, Dance were raised).

## fase3-ge — pushed rocks stop, dust on the big meteor, big meteor falls

18:36 (tester): the meteors still fall without sound. The dust is the bigger meteor's effect, not the small ones'.
Touched rocks slid in a straight line forever, through buildings. At the first marker the big meteor made no sound
and no dust, and the crater shown is not the lava one.

- **Push:** one short slide away from Batman, ending with a stop message (speed 0). Without it the client kept the
  rock moving. The slide is cut where a wall or building starts (`mover.blocked`), and no new push starts while
  one is running. `meteor_push_extra` 0.5.
- **Dust:** off for the small meteors (`meteor_dust` false). The big meteor at the first marker now falls as a
  rock (`big_meteor_falls`, scale 1.2), with the dust cloud at scale 1.0 (`big_meteor_dust`). The crater and
  Batman's knockdown come when it hits; the big rock goes 0.6 s later.
- **Sound:** the 0x1EB test made no sound; off (`meteor_land_effect` 0). The likely source is the rock's own
  behavior graph 0x1A0002BF (clips env_event_meteor_a / _impact, event Impact00), which the bare world state does
  not get.
- **Crater:** unchanged (0x2E0004BE). The tester's reference picture is needed to find the lava one.

## fase3-gf — Exit Match then Launch, burning meteor fragments, gentler push

18:54 (tester, with frames of the original tutorial video): the three start meteors are small burning pieces next
to Batman. The big impact is a fiery explosion with a dust plume and leaves a lava splash (red cracks) by the street
lamp. Still no sound; touched rocks still move oddly. After Exit Match the tutorial could not be launched again.

- **Exit Match:** the client sent 0x12D (left the match world) while the match was unfinished. The session stayed
  in PLAYING, so every following Launch got "JoinQueue ignored: a match is already being set up". Leaving the world
  now ends any match (`[match] leave_unfinished`). `tests/test_movie_queue.py` has the check (17 checks).
- **Small meteors** are now `env_event_meteor_fragment`: world state 0x2E00131C, .entity 0x2D00044D, graph
  0x1A0002BA. The .entity plays sound 0x4875B851 of bank Destruction, which Tutorial 1's pack declares.
  `[tutorial] small_meteor_wstate`; `meteor_scale` 1.0. The big one keeps the rock 0x2E000BB3
  (`big_meteor_wstate`).
- **Push:** five small position updates over 0.3 s, easing out (`meteor_push_steps`, `meteor_push_seconds`),
  instead of one move with a speed.
- **Lava crater:** not found yet. No texture in the loadable packs (0xA000024C, 0xA0000256, 0xA00000B3) looks like
  the splash, and nothing is named lava or crater. The meteor impact effect (`vfx_env_event_meteor_impact`) is only
  in zone pack 0xA000009A. The client has a single zone slot, already taken by 0xA000024C (diag 2026-10-14).

## fase3-gg — visible meteor flights, small collision, drone pieces stop

19:11 (tester): the fragments are not the right meteors either, and they had no collision. No meteor is seen
falling: the crater just appears, half hidden by the dust. A destroyed drone's pieces sometimes slide far along the
ground. (Exit Match then Launch now works: 19:09 log.)

- **Flights:** a straight drop is hardly visible from the top-down camera. The meteors now come in at a slant, from
  an offset towards the top-left of the screen, over a longer time:
  - small: from (−6, +4) m, 18 m up, 0.9 s, 10 steps (`meteor_fall_from`, `meteor_fall_seconds`,
    `meteor_fall_steps`);
  - big: from (−14, +10) m, 22 m up, 1.4 s, 16 steps (`big_meteor_*`).

  The crater and the knockdown still come at the big one's impact.
- **Collision:** a 0.7 m square stops Batman at each small meteor (`meteor_block_half` 0.35), and contact pushes it
  (`meteor_push_radius` 1.1).
- **Drone death:** the "dead" bundle carried the speed of a drone killed while walking, so the client kept moving the
  wreck. It is now sent with speed 0 (`[combat] stop_on_death`).
- **The real meteor event and the lava crater:** the assets are in zone pack 0xA000009A, and the client has a single
  zone slot (0xA000024C takes it). Next idea: an exe patch giving the zone category a second slot, so 0xA000009A can
  load next to the tutorial's pack.

## fase3-gh — second zone pack slot; the game's own meteor event (requires `python ic.py patch`)

19:20 (tester, "si intentalo"): try the exe patch that lets the meteor event's pack load with the tutorial.

- **Exe patch:** the client's pack slot table (VA 0x1600a40) gives zone packs (category 0xd) a single 155 MB slot, so
  0xA000009A could not load next to Tutorial 1's 0xA000024C. It now has two (file offset 0x11FEF44, 1 → 2). About
  155 MB more memory is reserved at start.
- **Match packs:** `[match] event_packs = [0xA000009A]` is added to the match's pack list only when the patched exe
  has the two slots (otherwise the server leaves it out and says so in `server.log`).
  `event_packs_unchecked = true` skips the check.
- **Meteors:** with that pack loaded, every meteor (the 3 small ones and the big one) is the game's own event:
  template 0x1D00019C on an anchor prop (0x2E000013, property 0x7D2), started with key 0x1000092F. The client should
  draw the warning, the falling rock, the impact and play the mse_Meteor sounds. The server keeps a 1.2 m obstacle
  where a small one fell, and the big one brings the crater and the knockdown 2 s after it starts.
  Config: `[tutorial] meteor_event`, `big_meteor_event` (False = the old rocks), `meteor_event_impact` (2.0 s, a
  guess), `meteor_event_block_half`, `meteor_event_keys`, `meteor_event_anchor`, `meteor_event_seconds`.
- Tests: e2e accepts the anchor; the basic-attack check now looks for its own 0x8D (the knockdown scripts can come
  first). 178/178 with and without the event pack.

To check: `python tools\diag.py --packs` should show both 0xA000024C and 0xA000009A loaded, and
`--scripts` whether `0x1000092F` is accepted on the anchor.

## fase3-gi — meteor event: key 0x5 on the warning; no sliding while down

20:08 (tester): "it got worse": water jets instead of meteors. While Batman was on the ground, pressing a direction slid
him along lying down. (diag: both zone packs loaded with the fase3-gh patch; the event's key was rejected.)

- **Anchor:** `0x2E000013` is a water jet. The anchor is now the event's own ground warning `0x2E0004E5`
  (`[tutorial] meteor_event_anchor`).
- **Key:** `0x1000092F` was rejected (the template's group allows only `0x5`). `meteor_event_keys = [0x5]`.
- **Knockdown:** the marker's 7.5 s move lock started at the marker, but the meteor event hits later than the old
  rock, so the lock ended before the get-up. He is now also locked from the fall itself for `knockdown_hold` (5 s) +
  `knockdown_getup_seconds` (1.5 s).

## fase3-gj — meteor event pieces placed one by one (three probes)

20:33 (tester): "the same" (water jets). Diag: key `0x5` accepted on the warning, nothing else.

- Template 0x1D00019C turned out to be a whole state machine (HFSM) that creates the event's pieces one by one.
  The server now places those pieces itself, each with its own scriptlet template read from the packs
  (`script_tables_v2` cache: the first start reads the game data again).
- **The three small meteors are three different probes**, in the order they fall:
  1. a ring piece `0x2E0006DA` (key `0x10000078`);
  2. the warning `0x2E0004E5`, then the rock `0x2E0005F7` 1.5 s later (key `0x10000032`);
  3. the tutorial pack's rock `0x2E000BB3` (key `0x10000032`) and the dust.
  The tester says which one looks right. `[tutorial] meteor_event_probes` (`[]` = the single anchor).
- **The big one:** warning, rock `0x2E0005F7` (`0x10000032`) at +0.5 s, dust at the impact, then crater and knockdown
  (`big_meteor_event_probe`).

## fase3-gk — the lava rock, smaller, falling again

20:58 (tester, with a picture): the three meteors are as big as the last one (the glowing lava rock by the crater).

- The diag shows the event's pieces can not be animated from the server (the rock accepts no scriptlet), so the
  meteors fall again as server-moved entities (fase3-gg's slanted fall, push and collision), now with the lava rock
  model `0x2E000BB3` for all of them: small ones at scale 0.35 (`meteor_scale`), the big one at 0.7
  (`big_meteor_scale`), blocking square 0.45 m (`meteor_block_half`).
- `meteor_event` / `big_meteor_event` are off by default (True = the fase3-gj probes again). The two-zone-slot patch
  stays; the event pack still loads (`[match] event_packs`).

## fase3-gl — tighter meteor collision, slower fall

21:24 (tester): the meteors' collision area is much bigger than the rocks; no sound, no fall and no dust seen. The
tester pinged a map piece near (40–44, 57–64) whose collision is what the meteors should feel like.

- **Collision:** the push started when Batman was 1.1 m from a rock's centre, before he touched it. Now a 0.6 m
  square blocks him (`meteor_block_half` 0.3) and the push starts at 0.6 m (`meteor_push_radius`), sliding 0.4 m
  (`meteor_push_extra`).
- **Fall:** the moves were sent (traffic: 10 updates in 0.9 s) but not seen. Slower and smoother: small ones 1.6 s in
  18 updates, the big one 2.0 s in 22 (`meteor_fall_*`, `big_meteor_fall_*`).
- **Dust:** the big one's dust `0x2E0007D4` ran its three scriptlets (diag 21:22:49, all accepted).
- **Sound:** still none. The meteor sounds are played by the event's state machine (0x1D00019C, action 0x2C), which
  the server can not run yet.

## fase3-gm — meteors block only at the rock (octagon), push works

21:34 (tester): the meteors still block a much bigger area than the rock; Batman walks round them and can not get
close. No sound, no fall with smoke.

- **Cause:** a box obstacle is grown by Batman's radius (`world.Mover.radius` 0.6 m), so the 0.3 m half box kept his
  centre 0.9 m from the rock, and the 0.6 m push could never happen.
- **Fix:** a meteor is now an octagon given as the line his centre can not cross (polygons are not grown),
  `[tutorial] meteor_block_radius` = 0.45 m from the rock's centre (`tutorial1.meteor_obstacle`). The push starts at
  0.6 m, so walking into a rock pushes it.
- Fall smoke and sound: not yet (the event's state machine is what plays them).

## fase3-gn — meteors push again; collision 0.7 m

21:47 (tester): Batman walks over the meteors (no collision, they do not move on contact); the crater has no lava; no
sound, fall or dust.

- **Push bug (since fase3-gd):** the slide test (`mover.blocked` along the push line) hit the rock's own obstacle, so a
  rock never slid. The rock's obstacle is now left out of that test (`tutorial1._push_meteor`).
- **Size:** at 0.45 m his path passed 0.55 m from a rock's centre (simulated), over the model. Now
  `meteor_block_radius` 0.7, push from 0.9 m (`meteor_push_radius`), slide 0.6 m.
- Open: lava crater, fall smoke, sound.

## fase3-go — meteor collision 0.95 m, small meteor dust, suit electricity try

21:59 (tester): the meteors still have no collision; Batman's suit lacks the electricity over its two antennas; no lava
crater, sound, or dust on the small meteors.

- **Collision:** the push now works (traffic 21:58:08: Meteor1 slid), but Batman still passed over the rocks at
  0.7 m. `meteor_block_radius` 0.95, `meteor_push_radius` 1.15.
- **Dust:** `meteor_dust` on for the small meteors too (0x2E0007D4 where each lands).
- **Suit electricity:** SpawnIdle `0x10000183` and FX_Spawn `0x10000119` (his own scriptlet table) are started on
  Batman at the tutorial start and after he gets up (`[tutorial] champion_ambient_keys`). Diag `--scripts` shows
  whether they are accepted.
- Open: lava crater, fall smoke, sound.

## fase3-gp — meteors appear after a puff of smoke; pushes re-create the rock

22:11 (tester): Batman walks over the meteors and they stay where they are. From a video of the original: the small
meteors make no dust ring, only smoke as they fall; then the rock lies on the ground.

- **Cause:** a carrier-built prop ignores the server's later position updates. The traffic shows every push
  (22:08:00–03) and the whole fall were sent, but the client kept each rock where it was created (the fall's start,
  in the air, offset from the landing spot), while the server's obstacle was at the landing spot and moved with the
  pushes. So Batman met no obstacle at the rock he saw.
- **Fix:** no fall. A smoke puff (dust cloud 0x2E0007D4 with its scriptlet 0x10000347) at the spot, and the rock is
  created there 0.5 s later (the big one at its impact). A push removes the rock and creates it again where it slid
  to (same object id). Config `[tutorial] meteor_appear`, `meteor_appear_delay`, `meteor_smoke*`,
  `meteor_push_mode` ("recreate" / "slide"). `meteor_dust` is off for the small ones again.

## fase3-gq — small meteors where the tester pinged; smoke and suit electricity, next tries

22:22 (tester): three pings, in order, where the small meteors must fall (same timing). No smoke seen, no electricity on
the suit, the fog of war is still not drawn.

- **Positions:** `SMALL_METEORS` = (21.4, 56.6), (20.2, 63.4), (21.5, 60.5), in that order (old ones kept as
  `SMALL_METEORS_OLD`; `[tutorial] small_meteors` overrides).
- **Smoke:** 0x10000347 on the dust cloud was accepted (diag 22:18:26) but shows nothing; 0x1000018E is the dust ring.
  Now the third key, 0x10000076 (`meteor_smoke_keys`).
- **Suit electricity:** SpawnIdle 0x10000183 and FX_Spawn 0x10000119 were accepted (diag) but showed nothing. Added
  Vfx_Bmg_Spawn 0x10000181 (`champion_ambient_keys`).
- Fog of war: an older open item (fase3-bx … cd; `diag.py --fog`), not changed here.

## fase3-gr — no dust waves before the crater; pushed meteors roll

22:36 (tester): no electricity on Batman, no fog of war; the small meteors make a wave when they hit the ground (they
should show a column of smoke); touched meteors should roll away, not jump; only the big crater makes the dust wave.

- **Dust waves:** every scriptlet of the dust cloud 0x2E0007D4 (0x1000018E, 0x10000347, 0x10000076) is a wave. The
  smoke before the small and the big meteors is off (`meteor_smoke`, `big_meteor_smoke`); the big one keeps its wave
  at the crater (`big_meteor_dust`). No smoke-column asset has been found in the loaded packs yet (only the map event's
  impact rig names a Plume).
- **Rolling:** a push now re-creates the rock in 4 steps over 0.4 s, turning 35° each step
  (`meteor_roll_steps`, `meteor_roll_seconds`, `meteor_roll_turn`).
- **Suit electricity:** 0x10000183, 0x10000119 and 0x10000181 are all accepted and show nothing. Open.
- **Fog of war (diag 22:31 --fog):** the fog component updates and draws, "darken" = yes, but `map=0x0` and the camera
  cell info is empty. Open (see fase3-bx … cd).

## fase3-gs — rocks get their own animation key, the meteor event's crater, gliding rocks

22:47 (tester, with frames of the original): Batman beams in with a blue electric glow before his health bar shows;
each meteor falls as a column of fire, then a column of smoke, then the rock lies there; the explosion that opens the
crater is fire and a dust wave; the crater has its own model with lava (ours is another one). Touched rocks vanish and
show up a bit further on.

- **Rocks:** their scriptlet table was never sent: `gamedata.world_state` returned None at the first vector
  property, so the rocks had "0 groups". It now returns the entries read before that point (`partial=True`), and
  0x2E000BB3 gets 0x1D0003B5. The rock is created at its spot `meteor_key_lead` s (0.5; big 1.0) earlier than before
  and runs Vfx_Spawn 0x10000032, the key the meteor event runs on its rocks (`meteor_land_keys`, [] = old probe
  keys). Cache key `script_tables_v3` (the first start re-reads the tables).
- **Crater:** `crater_set` "event" (when pack 0xA000009A is loaded): the event's crater 0x2E0004E7 with key
  0x10000039, placed at the big meteor + (3.2, 0.3) m (`event_crater_offset`), plus the shockwaves 0x2E0004ED (5 s)
  and 0x2E0006DE (1 s) with 0x1000018E (`event_crater_shockwaves`). The dust wave stays. "old" = 0x2E0004BE.
- **Push:** `meteor_push_mode` "glide": the rock is re-created once moving away from Batman at `meteor_glide_speed`
  (2.5 m/s; the client moves it along its heading) and once more, standing, where it got to.
- **Batman's spawn:** graph event RunScript_FX_Spawn 0x1000006B raised at the start (`champion_spawn_events`).
- Not changed: fog of war, meteor sounds, the impact rig's fire column (record 0x100004CE; no object found that uses it).

## fase3-gt — the explosion ends, the old crater is back, small meteors burn, rocks drift instead of flicker

23:30 (tester, fase3-gs logs + diag): rocks appear but without fire or smoke; no crater, and the "explosion" stayed
forever; no Batman animations seen except, now and then, a rope going up from Batman; touched rocks still vanish and
reappear further on.

- **Explosion:** 0x2E0004E7 is the event's explosion. It is placed at the big impact (with the shockwaves) and removed
  after `big_meteor_explosion_seconds` (4). Its key 0x10000039 was rejected: `event_crater_keys` [].
- **Crater:** `crater_set` back to "old" (0x2E0004BE).
- **Small meteors:** the same explosion at `meteor_fire_scale` 0.35 for `meteor_fire_seconds` 2 where each one falls
  (`meteor_fire`), then the rock 0.5 s later. Vfx_Spawn on the rocks (accepted, nothing seen) is off
  (`meteor_land_keys` []).
- **Push:** `meteor_push_mode` "drift": moving updates along the push at 2.5 m/s and a last one at
  `meteor_stop_speed` 0.01 m/s (no re-creation, no flicker); `meteor_push_extra` 1.2 m (longer, fewer pushes).
  The rock does not spin (the client moves it along its heading).
- Batman: RunScript_FX_Spawn is kept (probably the rope = grapple spawn); waiting for the tester to say when it shows.

## fase3-gu — model tour; no rope on Batman

23:45 (tester, fase3-gt): the rope animation on Batman must go. The original crater already has its lava (not a crater
and then lava). The rocks, the explosion and the fall are other models: each meteor is a column of fire, then a column
of smoke. Touched rocks slide, they do not roll. Proposal: a tour like the animation tour, one model every 4 s, and the
tester notes the right ones.

- **Model tour:** `[debug] model_tour` = "candidates" (50 world states: tutorial1.MODEL_TOUR_CANDIDATES), "pack:0x..."
  (every world state of one pack) or a list. One every `model_tour_interval` (4 s) at `model_tour_at`
  (24, 60, 200), numbered in the objective text ("Model n/N 0x2E...") and in server.log ("model tour n/N");
  `model_tour_from` resumes, `model_tour_keys` are tried on each (0x1000018E, 0x10000032, 0x10000078). Their
  scriptlet tables are read at server start (cache key with the tour's size).
- **Batman:** `champion_spawn_events` [] (RunScript_FX_Spawn played the rope).
- Rolling is unchanged: the rocks slide (no spin is possible on a moving prop; see fase3-gt).

## fase3-gv — the model tour skips what closes the game and resumes

00:12 (tester): the game closed at model "13". The connection dropped 0.13 s after model 15 (0x2E000F04) was created.

- 0x2E000F04 is never shown (`tutorial1.MODEL_TOUR_CRASHES`).
- The tour remembers its progress in `logs/model_tour.json`: `model_tour_from` 0 (new default) goes on after the last
  model shown. If the game connection drops less than 1 s after a model is created, that model is added to the file's
  crash list and skipped from then on (`Tutorial.on_match_end`, called from `Session.end_match`).
- server.log names the start point and the skipped models.

## fase3-gw — model tour shows bare models

00:44 (tester, nine runs): from model 14 on the game closed about 3 s after nearly every model (14, 16, 17, 18, 20,
22, 23); 21-26 passed once and 27 closed it 0.2 s after appearing. Models 1-13 had all worked. All of them are in packs
the client loads. The later ones carry scriptlet templates (0x1D000611 + 0x1D00034B + 0x1D000111, 0x1D000168,
0x1D0000DE...): their scripts run on the gate carrier, and the same model passed in one run and closed the game in
another, which points at those scripts, not at the models.

- `model_tour_scripts` false (new default): the tour sends each model without its templates and without keys.
  true = as before. Separate crash lists per mode in `logs/model_tour.json` (`crashed`, `crashed_bare`); the
  built-in 0x2E000F04 is only skipped with scripts.
- `_prop_object(..., scripts=False)`.

## fase3-gx — no rope on Batman; the tour no longer crashes with the guide arrows

00:58 (tester): the game still closed from model 15 on (bare models too), and the rope still showed.

- **Crash:** in every crashing run the client closed about 0.5 s after the guide's variant C (the ground marker on
  ping 1 and Batman's arrows aimed at it) while a tour model stood at (24, 60), next to the first marker (25.1, 60.3)
  and on the arrows' line; the earlier runs that passed variant C had a model without a collision shape there. The
  guide is not run while a tour is on, and `model_tour_at` is now (23, 56).
- **Rope:** it came from `champion_ambient_keys` (SpawnIdle 0x10000183, FX_Spawn 0x10000119, Vfx_Bmg_Spawn 0x10000181,
  sent since fase3-gq): Gaslight Batman's grapple spawn. Default [] now.

## fase3-gy — the tour skips every model that closed the game

01:08 (tester): the game still closed with model 14 (bare, no guide). Nothing at all was sent between the model
(01:06:56.4) and the drop (01:06:59.6): the model itself closes the client about 3 s after it appears. Not every
time (0x2E000620-623 passed once), so the guide was not the cause either.

- `MODEL_TOUR_CRASHES_BARE`: every model that closed the game at least once (0x2E000F03, F04, F05, EFE, 61D, 61F,
  621, 622, 296) is skipped in both modes.
- `model_tour_crash_window` 4.5 s (was 1 s): a drop up to 4.5 s after a model appears marks it (it closed after
  0.1-3.3 s).

## fase3-gz — every map gets its own packs

07:50 (tester): six maps hung on the loading screen. The server sent Tutorial 1's packs for every encounter.

- `[match] maps`: per encounter, the packs (its zone pack found among the install's five), the start position (from
  its mission layout) and its intro cinematics (none by default). Tutorial 2 0xA00002E5, Coast City and its
  variants 0xA00000D2, Gotham Divided 0xA000009A (guess), Gotham Heights / Metropolis Skyway 0xA00000FC (guess).
  Encounters not listed keep `packs` + `event_packs` + `spawn` (Tutorial 1 unchanged).
- server.log names the packs and the start of each match.
- The champion bundle's landblock comes from the start (was fixed at 0x13CB).
- Catalog: zone and mission packs in packs_notes.tsv.

## fase3-ha — inventory of every world state

07:58 (tester): asked for a new search of every game file for craters, meteors, fire and smoke columns,
explosions, and for anything missing in the catalog.

- New `python ic.py worlds` (tools/world_scan.py) and catalog table **World states (all)**
  (`world_states.tsv`, 2064 rows): packs, .entity, model names, kind, templates, graphs, particles, layout names,
  who uses it and the packs it needs. See reverse-engineering.md "World-state inventory".
- `python ic.py catalog --scan` over the full install (616 packs): no changes to the other tables.
- `python ic.py sounds` over the full install: 161 named banks (was 46), 1002 events with a known user (was 498).
- Findings: the meteor's fire column and falling rock are the impact rig (graph 0x1A00021F, pack 9A only);
  `stp_meteor` 0x2E000928 is the Stolen Power, not the event; no lava / smoke / crater-named model exists.
- No server behaviour change.


## fase3-hb — the model lab in Tutorial 2

09:31 (tester): prepare the lab and send the zip.

- Tutorial 2 is a model lab (`[match] maps` "0x40000A81": `"lab": true`, `"event_packs": [0xA000009A]`): no guide or
  enemies; 6 s after it starts, 16 candidates from `world_states.tsv` (`tutorial1.LAB_CANDIDATES`) appear one at
  a time next to the start point, every 5 s, first bare ("Model n/16a") and then with their scriptlet templates
  ("Model n/16b"); "Lab finished" at the end. server.log has the same numbers. A model that closes the game is
  skipped next time (logs/model_tour.json "lab"); `lab_from` restarts at an entry.
- Config `[debug]`: `lab_tour`, `lab_modes`, `lab_interval`, `lab_start`, `lab_offset`, `lab_from`.
- The explosion 0x2E0004E7 now gets its graph set 0x1C000029 (also in Tutorial 1's big meteor).
- Props are placed in the map's own landblock.
- New `tests/test_lab.py` (8 checks, needs the real packs).
- Requires `python ic.py patch` only if it was never run (two zone slots, fase3-gh).

## fase3-hc — lab models on the other side of Batman

09:49 (tester): the models appeared among the map's own props and overlapped them.

- `[debug] lab_offset` default (-4.3, 4.4, 0): same distance from the start point, opposite side (was (4.3, -4.4)).
- The lab's resume key includes the offset: a new spot starts again from model 1.

## fase3-hd — lab: the particles of each scriptlet key

09:59 (tester, screenshot): "Model 2/16b 0x2E0004E7" (the explosion with its graph set 0x1C000029) showed the
right yellow dust/smoke cloud. Next: the particles.

- Templates (0x1D) list scriptlet keys, each with the actions it runs; particle effects (0x18) are among them.
  `tutorial1.template_keys` reads them (pattern "key | 0 | n actions | prop | prop"); `_resolve_lab` caches each
  lab model's template keys and its graph read raw from the record (`LAB_GRAPHS`) at server start.
- `[debug] lab_modes` default `["keys"]`: one entry per key; the model with its templates and graph is created,
  then only that key runs. Objective text "Model n/16 key j/J 0x1000....", server.log names the particles.
  31 entries: explosion 0x2E0004E7 (15 keys, particles 0x1800045D / 0x1800044C), shockwave 0x2E0004ED (7 keys,
  0x18000465 / 0x18000297 / 0x1800045D), crater 0x2E0004BE (9 keys, its 14 particles 0x18000423-0x18000435).
  The other lab models have no keys in their templates as read.
- Graphs found raw but never sent before: rocks 0x2E0005F7 / 0x2E000BB3 -> 0x1C000036, shockwaves -> 0x1C00002A,
  warning -> 0x1C000028, dust -> 0x1C000046 (lab only for now).
- `tests/test_lab.py` 10 checks.

## fase3-he — explosion, crater, sparks and the Destroyer's ring from the lab; sphere lab

10:37 (tester, lab fase3-hd): explosion = "Model 2/16 key 0x10000526"; crater = "Model 11/16 key 1/9 0x100003A9",
turned 5 degrees clockwise; the shockwave is right; sparks = "Model 8/16b" 0x2E0006DA; the Destroyer's crater ring =
"Model 14/16" 0x2E001157. No lava, fire column or smoke column found. Missing: the sphere that falls, opens and shows
the Destroyer and four drones. Question: are the meteors the Stolen Power "Meteor Drop"?

- Tutorial 1 big meteor: 0x2E0004E7 runs `event_crater_keys` [0x10000526] (was []); the small meteors' fire uses
  `meteor_fire_keys` (none). Sparks 0x2E0006DA at the big impact (`big_meteor_sparks`, `sparks_*`; small ones
  with `meteor_sparks`, off).
- Crater 0x2E0004BE on a carrier with its template (`crater_carrier_slot` 0, was 1), `crater_keys`
  [0x100003A9] (was tutorial1.CRATER_KEYS), `crater_yaw` -0.0873 rad (5 degrees clockwise; was 0).
- Finale: env_pvp_phase_pod 0x2E001157 where the sphere lands (`destroyer_ring_wstate`, `_scale`, `_scripts`).
- Lab (Tutorial 2): `lab_tour` "sphere" (new default, tutorial1.LAB_SPHERE): stp_meteor 0x2E000928 (the Stolen
  Power Meteor Drop's rock, graph 0x1C000053), PowerCore 0x2E000AC5, drop pod 0x2E000E38, drop pod emitter
  0x2E000FAB (5 template keys), alien base iris 0x2E00103B, phase pod 0x2E001157. Models without template keys get
  two entries: "graph" (templates + graph) and "graph+keys" (plus `lab_open_keys`, with the Destroyer's open key
  0x10000E5C). A model without templates still gets its graph in the lab.
- Tester's config.toml: `meteors = false` and the Tutorial 1 model tour removed (backup config.toml.bak).

## fase3-hf — the meteors fall as the Stolen Power Meteor Drop's rock

10:53 (tester, lab fase3-he): "Model 1/6" (stp_meteor 0x2E000928) looks like the meteors that fall in the tutorial.

- Tutorial 1: every meteor (the three small ones, the later ones and the big one) starts as stp_meteor on a carrier with
  its graph 0x1C000053 (`stp_meteor`, `stp_meteor_wstate`, `stp_meteor_scale` 1.0, `big_stp_meteor_scale` 1.5); after
  `stp_meteor_impact` / `big_stp_meteor_impact` (1 s) the rest follows as before (smoke, fire, sparks, the rock on the
  ground); it is removed after `stp_meteor_seconds` (3 s). The big meteor's crater and knockdown keep their time
  (`big_meteor_fall_seconds`, 2 s).
- `_resolve_lab` (graphs read raw) now always runs at server start (cached).
- tests/test_e2e.py accepts 0x2E000928 as a meteor.

## fase3-hg — the Destroyer's cinematic keys

11:12 (tester): check the Destroyer's cinematic (the sphere that falls, opens and shows the Destroyer and four
drones is missing).

- Cinematic 0x35000028 (pack 0xA0000256) read: camera keyframes at frames 0 / 460 / 475; actors Destroyer
  (0x2E000AB5; 0x100007A2 = 1, scale 0.85, 0x954 = 2, templates 0x1D000774 + 0x1D000385; keys 0x100003A6 at frame
  115, Cinematic_Startup 0x100007EB at frame 125), Melee1 / Melee2 (0x2E001167) and Ranged1 / Ranged2 (0x2E001168),
  each with Cinematic_Hidden 0x100009EB at frame 1 and Cinematic_Intro 0x100009EC at frame 125, walking from their
  start to a second point; camera shakes 0x10000060 at frames 15, 60, 195, 345.
- The server now runs the actor's keys on the spawned Destroyer at their frames (`destroyer_cinematic_keys`,
  30 fps); `destroyer_start_keys` keeps only State00 (Startup moved to its frame). The Destroyer carries the
  actor's properties (`destroyer_actor_props`, `destroyer_actor_scale`, `destroyer_actor_tables`), sent as
  `Entity.actor_props` (they do not turn it into a prop).

## fase3-hh — one Destroyer in the cinematic; the ring centred on it

11:36 (tester, screenshot + logs, start_at = "strength"): two Destroyers on top of each other in the cinematic; the
crater ring must be centred on the Destroyer (it was at the sphere's spot (152.5, 28.0), 4 m off).

- The cinematic 0x35000028 brings its own Destroyer actor and plays its keys itself: the server's Destroyer is
  spawned when the cinematic ends (`destroyer_in_cinematic` false, was true); `destroyer_cinematic_keys` [] and
  `destroyer_actor_props` false (fase3-hg's additions off).
- The ring 0x2E001157 at the Destroyer's spot (152.75, 24.0) (`destroyer_ring_at` "destroyer" / "sphere",
  `destroyer_ring_offset`).

## fase3-hi — the sphere falls inside the Destroyer cinematic; ring turned 90 degrees

12:32 (tester, diag --scripts --create, start_at = "strength"): turn the ring 90 degrees counter-clockwise; in the
cinematic the sphere does not crash (the Destroyer appears and the four drones walk out).

- diag: the cinematic builds its own actors (2 x 0x2E001168, 2 x 0x2E001167, 0x2E000AB5) without errors and no
  sphere object; the PowerCore 0x2E000AC5 rejected 0x1000018E / 0x10000347 / 0x10000076 (0x80070057) and its
  allowed table holds 0x100003A6 / 0x100003A7 (0x100003A6 = the cinematic's frame-115 key on its Destroyer).
- `sphere_in_cinematic` (on): the cinematic goes 0.5 s after the drones die (`sphere_cinematic_delay`), the
  PowerCore falls from 0.5 s into it (`sphere_cinematic_start`, `sphere_fall_seconds` 2) on the Destroyer's spot
  (`sphere_at`), and 0x100003A6 runs on it at frame 115 (`sphere_cinematic_keys`). `sphere_keys` empty (were the
  rejected keys).
- `destroyer_ring_yaw` 1.5708 (90 degrees counter-clockwise; was 0). `_prop_object(heading=...)`.

## fase3-hj — the sphere on the ground

13:21 (tester, diag, with `sphere_cinematic_keys` 0x100003A6 at 3.83 s + 0x100003A7 at 4.5 s): "something tries to
appear but stays stuck in the sky".

- diag: the PowerCore was built once (PROP received at 13:20:27, at 15 m) and the server's falling re-creations
  never moved it (a carrier prop ignores them); 0x100003A6 and 0x100003A7 were both accepted (result 0).
- `sphere_from_height` 0 (was 15): created on the ground, no server fall; its keys animate it.
- `sphere_cinematic_keys` default [[3.8333, 0x100003A6], [4.5, 0x100003A7]].

## fase3-hk — the sphere is the phase pod

13:28 (tester): the PowerCore 0x2E000AC5 now loads on the spot but "is another part, not the sphere".

- The sphere is the phase pod 0x2E001157 (rig 0x2D000E7F: body, door, plates A-D with sub-plates, thumper, top;
  the model the tester took for the crater ring). Its graph 0x1A000E0B (env_pvp_phase_pod_behavior.hkb, packs
  0xA0000168 / 0xA0000256) has the clips entrance_a, raider_open_a, raider_open_a_idle, active_idle, leviathan,
  die and the events Spawn 0x10000154, Activate 0x100001C1, Deactivate 0x10000419, Death 0x100001C0, OpenIdle
  0x100004A5, ClosedIdle 0x100004A6 (ids from name table 0x300000A4).
- `sphere_wstate` 0x2E001157 (was 0x2E000AC5), `sphere_graph` 0x1A000E0B sent as its 0x5B5, `sphere_yaw` 1.5708,
  `sphere_cinematic_events` [[0.6, Spawn], [3.8333, OpenIdle]] raised with 0x100001E3 / variable 0x780,
  `sphere_cinematic_keys` [] (the PowerCore's), `destroyer_ring_wstate` 0 (the pod is the ring once open).

## fase3-hl — back to the bare pod after a crash

13:41 (tester): the game closed when the cinematic started. traffic: the pod (with 0x5B5 = 0x1A000E0B and its
templates) was created at 0.5 s, Spawn raised at 0.6 s, OpenIdle at 3.83 s, the client closed at 4.65 s.

- A 0x5B5 holds a graph SET (0x1C...); a raw graph id 0x1A... there is the likely cause (the same ~3 s close as the
  model tour's crashes). `sphere_graph` 0 and `sphere_cinematic_events` [] by default; `sphere_scripts` false (the
  pod is sent bare, as it showed fine as the ring). To test a graph set: `sphere_graph = 0x1C0000B5` (the only one
  in both packs that hold the pod graph, 0xA0000168 and 0xA0000256, that is not already known) with the events.

## fase3-hm — the pod with graph set 0x1C0000B5 and Vfx_Spawn

13:56 (tester, diag): with `sphere_graph = 0x1C0000B5`, its templates and the Spawn / OpenIdle events the game did
not close, but the sphere still does not show. diag: the pod's scriptlet table allows only 0x10000032 (Vfx_Spawn);
0x100001E3 (graph events) is rejected (0x80070057).

- Defaults: `sphere_graph` 0x1C0000B5, `sphere_scripts` true, `sphere_cinematic_events` [], `sphere_cinematic_keys`
  [[0.6, 0x10000032]].

## fase3-hn — the bare phase pod back (the crater ring)

14:05 (tester): with fase3-hm (graph set 0x1C0000B5, templates 0x1D00078F, Vfx_Spawn 0x10000032 at 0.6 s) neither
the sphere nor the crater shows. traffic/diag: the pod is created (entity 0x2D000E7F, result 0) and Vfx_Spawn is
accepted (result 0), but nothing is drawn.

- Found in the packs: 0x1C0000B5 is the graph set (0x5B5) of world state 0x2E000FC7, not of the pod. Every graph set
  in packs 0xA0000168 / 0xA0000256 is taken by another world state (0x1C000022 -> 0x2E00033A, 0x1C000046 -> 0x2E0007D4,
  0x1C00006C -> 0x2E000AC5, 0x1C0000B5 -> 0x2E000FC7, 0x1C0000BA -> 0x2E00103B, 0x1C0000CA -> 0x2E001037). The pod's
  record has four properties only: 0x50F = 5, 0x7D2 = [0x1D00078F], 0x7EB = 7, 0x2A4 = 0x8B; no graph.
- Defaults back to the bare pod: `sphere_graph` 0, `sphere_scripts` false, `sphere_cinematic_keys` [].

## fase3-ho — the sphere's core: the PowerCore with its cinematic template

14:28 (tester): with the bare phase pod (fase3-hn, config.toml cleaned) the crater shows; the sphere does not.

- Found in pack 0xA0000256: cinematic actors carry their templates in property 0x954 (`0x954 | 0x954 | 1 | 0x462 |
  template`); the PowerCore actor (0x2E000AC5) of cinematic 0x35000025 has 0x1D00078A, the Gate 0x1D000789. Template
  data in the same pack spawns world state 0x2E001157 (the phase pod, the crater ring, scale 1.1) with explosion
  pieces 0x2E0007D4 / 0x2E0004ED on CinematicCharacter_State02 0x10000E5D / State03 0x10000E5E (Vfx_Spawn
  0x10000032 on the pod); another template spawns it on 0x100000EB with 0x10000347 / OpenIdle 0x100004A5.
- New: `_sphere_core` creates the PowerCore at the Destroyer during cinematic 0x35000028 with `sphere_core_templates`
  [0x1D00078A] (as 0x7D2) and `sphere_core_graph` 0x1C00006C, and runs `sphere_core_keys` [[0.6, 0x10000E5B],
  [3.8333, 0x10000E5C], [4.5, 0x10000E5D], [5.2, 0x10000E5E]]. `sphere_core_wstate` 0 turns it off. The crater
  ring (bare pod) stays as in fase3-hn.

## fase3-hp — the sphere core off; tour of Tutorial 1's placement pack

14:44 (tester, diag): the PowerCore with template 0x1D00078A shows in the crater, but it is the element of the last
cinematic of Tutorial 1 (0x35000025), not the sphere; the crater ring still shows. diag: its table allows
0x1000005A, 0x10000E5B, 0x10000E5C, 0x10000E5F; 0x10000E5D / 0x10000E5E are rejected (0x80070057), so the
template that spawns the phase pod on State02 / State03 belongs to another actor (the Gate 0x2E000CD7, 0x1D000789?).

- `sphere_core_wstate` 0 (off; was 0x2E000AC5).
- To look for the sphere: `[debug] model_tour = "pack:0xA0000256"` tours the 51 world states of Tutorial 1's
  placement pack in Tutorial 1.

## fase3-hq — the Destroyer's sphere found: closed 0x2E000FC7, open 0x2E00101D

15:02 (tester, `[debug] model_tour = "pack:0xA0000256"` in Tutorial 1): model 37 is the closed sphere, model 38 the
open sphere.

- Model 37 = 0x2E000FC7 (packs 0xA0000168 / 0xA0000256; entity 0x2D000D3F, templates 0x1D0006AC, graph set
  0x1C0000B5 - the graph set tried on the phase pod in fase3-hm). Model 38 = 0x2E00101D (packs 0xA0000162 /
  0xA0000256 / 0xA00002E6; entity 0x2D000D92, template 0x1D000385).
- `sphere_wstate` 0x2E000FC7 (was 0x2E001157) with `sphere_graph` 0x1C0000B5 and the new `sphere_templates`
  [0x1D0006AC], created at the Destroyer 0.5 s into cinematic 0x35000028. New `sphere_open_wstate` 0x2E00101D /
  `sphere_open_at` 4.0: the closed sphere is removed and the open one placed then. The phase pod is the crater
  ring again (`destroyer_ring_wstate` 0x2E001157, was 0), placed 2 s after the sphere.

## fase3-hr — the sphere turned to the street; graph events Spawn / Explode

15:13 (tester + screenshot): the closed sphere appears (as if teleported: no fall, no opening) and the open one
replaces it; the open sphere's doorway faces the top-left corner of the screen instead of the street Batman comes
along.

- `sphere_yaw` 3.927 (was 1.5708): 135 degrees anticlockwise, for both spheres.
- Found: the closed sphere 0x2E000FC7 carries the drop pod rig (env_pvp_drop_pod_a bones next to its record); graph
  0x1A000CDC (env_pvp_drop_pod_a_behavior) has the events Spawn 0x10000154, Entrance 0x1000042A, Idle 0x1000013D,
  Explode 0x1000041F, Spawn_Idle 0x100002A1 (name table 0x300000A4) and the clips entrance_a, idle_a, explode_a.
- `sphere_cinematic_events` [[0.6, Spawn 0x10000154], [3.5, Explode 0x1000041F]] (was []), `sphere_open_at` 5.0
  (was 4.0). The events need 0x100001E3 in the sphere's table (template 0x1D0006AC): diag --scripts tells.

## fase3-hs — the sphere falls; the thrown car arcs to its target; cameras on walkable ground

15:26 (tester, video + diag --scripts): (1) surveillance cameras could be placed off the map, in the water and
inside vehicles; (2) the thrown car shot off in a straight line until it hit something; (3) the closed sphere
appears as if teleported and is swapped for the open one with no opening (the opening sound is heard); its doorway
now faces the street (fase3-hr turn kept).

- diag: the closed sphere 0x2E000FC7 (template 0x1D0006AC) allows Vfx_Spawn 0x10000032, Vfx_Active_State0
  0x1000005D, Vfx_Fade_Out 0x1000006A, Vfx_Event1 0x10000076, Vfx_Event10 0x100000DC, _HFSM_DestroyEntityAction
  0x100001E0, Vfx_SpawnIdle 0x1000087D, Vfx_Spawn_Hit 0x1000087E, Object_Deactivate 0x10000CCD, Object_Activate
  0x10000CCE; the graph-event scriptlet 0x100001E3 is rejected.
- Sphere: falls `sphere_from_height` 12 m in `sphere_fall_seconds` 1.0 with moving updates at a crawl
  (`sphere_fall_mode` "move", `sphere_fall_step` 0.1, `sphere_fall_speed` 0.01; was created on the ground), the
  crater ring when it lands; `sphere_cinematic_keys` Vfx_Spawn 0.55 s, Vfx_Spawn_Hit 1.55 s, Object_Activate +
  Vfx_Event1 4.6 s; `sphere_cinematic_events` [] again; `sphere_open_at` 4.5.
- Throw: the car faces the target (`throw_face_target`) and its last flight update is a crawl (`throw_end_speed`
  0.01): a carrier moves along its heading at the sent speed and ignores speed 0, so it flew on along its own yaw.
- Cameras: `camera_on_walkable` (bridge.py `_camera_spot`): the D click goes to the nearest spot outside every
  obstacle, pulled back along Batman's line of sight to before the first obstacle.

## fase3-ht — the sphere and the thrown car drawn with a new object per step; dust at the landing

15:44 (tester, video): the cameras are right now. The sphere stayed up a moment, vanished and reappeared open (no fall,
no opening, no dust); the car still flew in a straight line.

- Video: the closed sphere stayed 12 m up through the ten moving updates; the car flew level at its carry height. A
  carrier prop keeps the height it was created at; updates (speed > 0) move it on the ground plane only.
- Sphere: `sphere_fall_mode` "respawn" (was "move"): every `sphere_fall_step` s a new object one step lower, the one
  above removed in the same tick; the open swap and the keys follow the current object. New `sphere_dust_wstate`
  0x2E0007D4 (the meteor dust cloud, as the car blast) at the landing, `sphere_dust_scale` 1.5, `sphere_dust_lifetime`
  3.0.
- Car: `throw_mode` "respawn" (new; "move" = the flat moving updates): the car is removed as it leaves Batman's hands,
  a copy is created at each point of the arc (`throw_steps`, `throw_arc` 4 m) and the car itself is created again
  where it lands, before it explodes.

## fase3-hu — the car flies visibly again; the sphere's opening gets time

15:57 (tester, video): the car vanished in flight and reappeared where it hit; the sphere lands with the crater and the
dust ring, an animation starts on it and is cut by the swap to the open sphere.

- Video: the flight copies of the car (30 ms each) and the sphere's fall steps (100 ms each) never showed: a new object
  fades in for longer than that; only the last sphere step (on the ground) is seen, with the dust.
- `throw_mode` "move" again (was "respawn"): the car is visible in flight, level.
- `sphere_open_at` 7.5 (was 4.5); `sphere_cinematic_keys` Object_Activate 0x10000CCE at 2.5 s and Vfx_Event1
  0x10000076 at 4.0 s (both were at 4.6 s, 0.4 s before the swap), to tell which starts the opening.

## fase3-hv — the sphere opens by itself (Vfx_Event1); created on the ground with Vfx_Spawn

16:07 (tester, video: "almost there"; check the fall once more, then on to the start of the tutorial).

- Video: the closed sphere's halves part ~3.5 s after it appears, right after Vfx_Event1 0x10000076 (Object_Activate
  at 2.5 s showed nothing); the opening takes ~1.5 s and leaves the open shell around the Destroyer and the drones. The
  swap to the open model at 7.5 s then only flickered. The fall steps never show (a new object fades in ~0.3 s);
  Vfx_Spawn had gone to the first (highest) step, never to the sphere on the ground.
- `sphere_open_at` 0 (swap off; was 7.5). `sphere_from_height` 0 (was 12): the sphere is created on the ground and gets
  Vfx_Spawn 0.05 s later (its drop-pod graph's entrance_a may be the fall), Vfx_Spawn_Hit at 1 s with the dust and the
  crater ring, Vfx_Event1 (the opening) at 3.5 s (`sphere_cinematic_keys` [[0.55, 0x10000032], [1.55, 0x1000087E],
  [4.0, 0x10000076]], s after the drones die).

## fase3-hw — back to the fase3-hu sphere

16:19 (tester: "it was better before this change"; video): with fase3-hv (created on the ground, Vfx_Spawn on it, no
Object_Activate) the closed sphere never opened. The fase3-hu settings again: `sphere_from_height` 12 (respawn steps),
`sphere_open_at` 7.5, `sphere_cinematic_keys` [[0.55, Vfx_Spawn], [1.55, Vfx_Spawn_Hit], [2.5, Object_Activate],
[4.0, Vfx_Event1]]. Object_Activate 0x10000CCE seems needed before Vfx_Event1 0x10000076 opens it.

## fase3-hx — Tutorial 1's start timed like the original; fire-column lab

16:24 (tester): remove `start_at` and look again at the original video of the tutorial's start, up to the end of the
Catwoman cinematic. The tester's config.toml: `start_at` commented out (backup config.toml.bak-1624).

- Video, frame by frame: see reverse-engineering.md "Tutorial 1's start in the original video". Batman walks ~3 s in;
  two fire columns hit 3.4-3.9 s in; a grey dust dome covers the street for ~1 s; the big blast comes ~0.5 s after he
  reaches the marker; he is down ~4.3 s.
- `start_lock` 2.8 (was 3.5). `small_meteor_times` [2.4, 2.6, 2.9] (new; was 1.0 / 1.7 / 2.4): with the 1 s
  stp_meteor fall they hit 3.4-3.9 s in.
- `small_meteor_cloud` (new, on): one dust cloud 0x2E0007D4 (scale `small_meteor_cloud_scale` 1.5) at the small
  meteors' centre, `small_meteor_cloud_delay` 0.3 s after the last impact, removed after `small_meteor_cloud_seconds` 3.
- Big meteor: `knockdown_delay` 0.3 (was 1.0) and `big_meteor_fall_seconds` 1.0 (was 2.0): the crater, blast and
  knockdown when the falling rock lands, ~1.3 s after the marker (was 3 s). `big_meteor_after_small` 0.8: never sooner
  than that after the last small meteor has hit.
- Tutorial 2 lab: `[debug] lab_tour` "start" (new default; was "sphere"): the meteor event object 0x2E00069E with
  Vfx_Spawn_Event05 0x1000092F (its own key, never run on it), Vfx_Spawn and Vfx_Active_State0, and the set pieces
  0x2E000872-0x2E000877 (0x2E000877 spawns five meteor events) with Vfx_Active_State0 / RunScript_FX_Spawn /
  _CEntitySystem_EnvironmentStateChange. Candidates for the fire columns.
- tests/test_lab.py follows `lab_tour` "start".

## fase3-hy — the lab skips the set piece that closed the game

16:55 (tester, lab fase3-hx): the game closed at the third model shown. server.log: entry 4/17, set piece 0x2E000877
(key Vfx_Active_State0), closed 4.5 s after it appeared; the meteor event object 0x2E00069E (entries 1-3) passed.
model_tour.json did not mark it (the crash window was 4.5 s).

- 0x2E000877 added to `tutorial1.MODEL_TOUR_CRASHES_BARE` (never spawned).
- `[debug] model_tour_crash_window` 6.0 (was 4.5).
- The lab skips every entry of a model that closed the game (all its keys), not only the entry that was showing. The
  next run goes on with 0x2E000872.
- tests/test_lab.py: crashing models are left out of the expected list.

## fase3-hz — the whole set-piece family left out of the lab

17:03 (tester, lab fase3-hy): the game closed again. server.log: 0x2E000872 (entry 8/17, Vfx_Active_State0) closed it
3.4 s after it appeared (marked in model_tour.json).

- 0x2E000872-0x2E000876 added to `tutorial1.MODEL_TOUR_CRASHES_BARE` with 0x2E000877 (same templates, same kind of
  record). The "start" lab now only shows the meteor event object 0x2E00069E (3 entries).

## fase3-ia — the vehicle blows up; meteors during the Catwoman cinematic; shorter big cloud

17:08 (tester): video of Tutorial 1 from the start to after the Catwoman cinematic (fase3-hx) + logs. Compared frame by
frame with the original (reverse-engineering.md "Tester's video of fase3-hx vs the original").

- `vehicle_blast` (new, on): when Catwoman hits the vehicle (`vehicle_break_at`), the big meteor's explosion
  0x2E0004E7 (its key, shockwaves, sparks) where it stood, scale `vehicle_blast_scale` 1.2. Not on the `start_at`
  shortcut.
- `catwoman_meteors` (new) [[11.5, 8, -6], [14.6, -6, 1]]: small meteors (fall, fire, rock) during the cinematic, s into
  it and offset from the vehicle (first guess from the original's camera); none once the cinematic has ended;
  `catwoman_meteor_lifetime` 8 s.
- `big_meteor_explosion_seconds` 2.5 (was 4.0): the big meteor's yellow cloud covered the street ~4.5 s.
- Not changed yet: the small meteors' cloud is yellow-brown (original grey); no wreck model; ~2 s dark view at the end of
  the cinematic.

## fase3-ib — Catwoman cinematic: blasts and craters, a smaller vehicle blast

17:43 (tester, video): in the background of the cinematic no meteor falls, the ground blows up and a crater opens; the
vehicle's explosion is still not right (it filled the screen with the meteor's shockwave, rocks and yellow cloud).

- `catwoman_meteors` now places the big meteor's crater and explosion (crater(), scale `catwoman_blast_scale` 0.7)
  instead of a falling meteor; the tutorial's own crater is kept. `catwoman_meteor_lifetime` removed.
- Vehicle blast: `vehicle_blast_scale` 0.45 (was 1.2), `vehicle_blast_seconds` 1.5 (new), `vehicle_blast_shockwaves`
  false (new): only the explosion and the sparks, about the vehicle's size.
- `_event_explosion` takes scale / seconds / offset / shockwaves arguments.

## fase3-ic — Tutorial 1 checked again against a full video at 0.5 s

17:51 (tester): a full video of the original Tutorial 1; frames every 0.5 s (and every 0.03-0.2 s at each event) so no
animation is skipped. Findings in reverse-engineering.md "The tester's full Tutorial 1 video at 0.5 s".

- `knockdown_hold` 3.8 (new in config.py; the code default was 5.0): Batman lies ~3.5 s in the original.
  `knockdown_lock` 6.6 (was 7.5), `drone_appear_delay` 6.0 (was 7.0).
- `ambient_meteors` (new): flaming rocks falling near Batman as set dressing, by hook ("practice" when the practice
  targets appear, and bridge stages "unlock_w", "e_practice"), `ambient_meteor_lifetime` 4 s.
  `Tutorial.ambient_meteors(hook)`; bridge `_stage` calls it.
- `vehicle_blast_seconds` 1.0 (was 1.5): the vehicle's fire lasts ~0.85 s.

## fase3-id — Batman's spawn effect and the suit's electricity

18:05 (tester): Batman's start animation and the constant electricity on his suit's antennas are missing.

- Video (0.1 s): hex shimmer and white lines on him for ~5 s, a cyan ring at his feet, then normal; arcs on the gun
  antennas afterwards. See reverse-engineering.md "Gaslight Batman's spawn and suit electricity".
- `champion_spawn_keys` [FX_Spawn 0x10000119] at the start and `champion_spawn_end_keys` [FX_Spawn_End 0x1000005A]
  `champion_spawn_seconds` 2.5 s later (new): the lines (the old "rope") now end.
- `champion_ambient_keys` [Vfx_Bmg_Active 0x10000180] (was []): at the start (+1 s) and after the get-up.
- Catalog: 0x10000183 is Vfx_Bmg_Sonic_Shell_Stop as a scriptlet (SpawnIdle only as a graph event); 0x10000180 and
  0x1000005A added.

## fase3-ie — Batman's effects: a labelled test of three candidates

18:25 (tester): neither the white shimmer before the match nor the electricity between the antennas showed.

- Vfx_Bmg_Active 0x10000180 and FX_Spawn_End 0x1000005A are not in Batman's own scriptlet table: dropped by the client.
  `champion_ambient_keys`, `champion_spawn_keys`, `champion_spawn_end_keys` back to [].
- `champion_fx_tour` (new): candidates from his table, one by one after the start, each labelled in the objective text
  for `champion_fx_label_seconds` (4 s): 0.5 s "Test 1/3: Respawn" (_Defeat_OnRespawn 0x100001FC), 7 s "Test 2/3:
  Echoes" (Vfx_Bmg_Echoes_Active 0x10000198), 13.5 s "Test 3/3: Active State" (Vfx_Active_State0 0x1000005D).

## fase3-if — blast in the crater, dust with the meteors, next effect test

18:46 (tester): still no shimmer or antenna electricity; the meteors fall and the dust comes after (it should be at
the same time); the big blast is ahead of the crater, it should start in the middle of it and cover the crater
appearing.

- `event_crater_offset` [0, 0] (was [3.2, 0.3]); `crater_delay` 0.3 (new): the crater is created 0.3 s after the blast.
  The Catwoman cinematic blasts keep the tutorial's crater (keep_id).
- Small meteors' dust: from the first impact, `small_meteor_cloud_delay` -0.2 (was the last impact + 0.3).
- `champion_fx_tour`: five new candidates from the client's own accepted list (diag 17:06): Cinematic_Intro
  0x100009EC, Vfx_Fade_In 0x10000033, Vfx_Active 0x100000EB, _Encounter_OnAgentControlledByPlayer 0x10000200,
  _Player_OnAgentControlledByPlayer 0x100001E8 (labels "Test n/5").

## fase3-ig — the big meteor is only the blast and the crater; next effect test

19:09 (tester): a rope on Batman at the start (wrong animation); remove the meteor falling behind, keep only the crater
and the blast; another animation showed in the middle of the crater after the big meteor went; still no antenna
electricity or shimmer.

- `big_meteor_falls` false (was true): no stp_meteor fall and no rock in the crater; the blast and the crater
  (crater(), crater 0.3 s after the blast) and the knockdown come `knockdown_delay` 0.4 s (was 0.3) after the marker.
- `champion_fx_tour`: entries take a key or a list; an empty label shows nothing. Test 1/3 Invulnerability
  (0x100008B7 + 0x100008B5 at 0.5 s, _Stop 0x100008B6 at 3.5 s), 2/3 Supercharge 0x100001D3 (7 s, left on), 3/3
  Protection Shield 0x10000AA2 (13 s). Cinematic_Intro (the rope) is out.

## fase3-ih — Tutorial 2: a tour of every Gaslight Batman animation

19:18 (tester): prepare a tour of all of Gaslight Batman's animations in Tutorial 2; the tester says which ones the
tutorial needs.

- `[debug] lab_tour` "batman" (new default; was "start"): `Tutorial._champion_tour` runs on the player's champion the
  111 graph events of his behavior graph and then the 354 scriptlets the client accepts on him
  (`icserver/champion_fx.py`, most likely candidates first), one every `champion_tour_interval` (3 s), labelled
  "G n/111 name" / "S n/354 name" in the objective text and server.log. *_Active / *_Start scriptlets get their
  *_Stop after `champion_tour_stop_after` (2.4 s); knock-down / death events get CbtState_GetUp. Resumes after the
  last entry (logs/model_tour.json "batman"); `champion_tour_from` = n starts at n; an entry that closed the game is
  skipped next time.
- Tutorial 1's `champion_fx_tour` off ([]).
- tests/test_lab.py checks the tour when `lab_tour` is "batman".

## fase3-ii — what Cinematic_Intro does; a five-entry tour

19:52 (tester, champion tour): S 37/354 Cinematic_Intro turned on the antennas' electricity; does it do anything else?

- Its template entry: action 0x737 = 2, graph event Spawn 0x10000154, scriptlet Vfx_Bmg_Spawn 0x10000181 (see
  reverse-engineering.md "Cinematic_Intro lights the antennas"). The Spawn graph state is the likely rope.
- `[debug] champion_tour_only` (new): only the listed entries ("G name" / "S name"), in that order: Vfx_Bmg_Spawn,
  SpawnIdle, Spawn, Cinematic_Hidden, Cinematic_Intro. `champion_tour_interval` 6 s (was 3). The tour's numbering is
  per list ("S 1/3", "G 1/2").

## fase3-ij — Batman's spawn at the start of Tutorial 1 (antenna electricity)

20:41 (tester, champion tour): the antennas' electricity came on when "G 2/2 Spawn" ended.

- `champion_spawn_events` [Spawn 0x10000154] (was []): the graph event is raised on Batman when Tutorial 1 starts
  (`champion_spawn_delay` 0), so he plays his spawn and the electricity stays on.

## fase3-ik — the Spawn animation before the tutorial starts

20:46 (tester): in the original Batman does not play that animation during play: he stands with the electricity on
when we get control, unless the start of Tutorial 1 is that animation, standing, while we take control.

- `champion_spawn_hold` 5.0 (new): when the intro cinematic ends the graph event Spawn is raised and Batman is locked;
  the tutorial (HUD, first prompt, marker, meteors) starts 5 s later, so the player gets control of a Batman that
  has finished his spawn with the antennas lit (the original: shimmer 01:20-01:25.3, HUD 01:25). 0 = the old way.
- tests/e2e.example.toml sets `champion_spawn_hold = 0.0` (the test client expects the HUD at once).

## fase3-il — critical basic attacks

20:55 (tester): S 163 Combat_Critical_Attack and S 171 (Vfx_Bmg_Crit) are Batman's critical hit (arms and shot); the
critical-hit chance is not programmed. Also: how many laugh / joke / dance / taunt animations does he have?

- `[combat] crit_chance` 0.2 and `crit_multiplier` 1.5 (new): a basic attack can be critical; it plays
  `[scripts] crit_keys` [Combat_Critical_Attack 0x100000B8, Vfx_Bmg_Crit 0x1000017E] and ends the shot with
  `crit_stop_keys` [Vfx_Bmg_Crit_Stop 0x1000017C]; server.log "critical hit on ...".
- Emotes: one clip each (dance, joke, laugh, taunt); see reverse-engineering.md "Critical hits and emotes".
- tests/e2e.example.toml sets `crit_chance = 0.0` (the test checks the normal basic-attack keys).

## fase3-im — the throw's aim rings show by themselves

21:28 (tester, two pictures of the original): with the car lifted the yellow range ring around Batman and the ring
at the cursor are shown; a left click throws the car to that point.

- `[tutorial] throw_auto_aim` 0.4 s (new; 0 = off) and `throw_aim_key` 0x46 (F): once the throw skill is on F the
  server presses F in the game window (only when the game is in front; `winctl.press_key`), so the client shows the
  aim rings and the next left click throws. server.log: "the throw's aim shown (F pressed for the player)".

## fase3-in — no craters from the Catwoman blasts; Champions / Amplifiers after a match

21:40 (tester, screenshots): two craters that should not be there (where the vehicle stood, by the bridge gate); the
second car moved forward again; after the match the Champions tab shows no champion and Amplifiers nothing.

- `catwoman_blast_crater` false (new): the Catwoman cinematic's two blasts leave no crater (they used crater()).
- `[account] resend_collections` (new, on): the client's 0x21A4 (Champions) and 0x2116 (Amplifiers) are answered with
  the login's 0x20ED / 0x209D / 0x20B8 (at most every 2 s). New tests/test_collections.py (5 checks).
- Second car: no position code changed since fase3-fq; server.log 21:34 spawns BridgeVehicle at (107.3, 17.2) and
  FinaleCarB at (133.8, 14.0), as before. Waiting for the tester to say which car and where it should be.

## fase3-io — Batman spawns while the scene loads; the throw's F press; the sphere's fall; the second car

21:53 (tester, video 21:49): the antennas' electricity still did not show; Batman stood still too long before he could
move ("play that movement with the scene load"); no yellow ring when the car is lifted; the sphere seems to appear out
of nowhere. 21:40 (the second car moved forward) is explained by the same log.

- `champion_intro_keys` [0x100009EC] / `champion_intro_delay` 0.5 (new): Batman's Cinematic_Intro scriptlet (0x737 = 2,
  graph event Spawn, Vfx_Bmg_Spawn 0x10000181) runs 0.5 s after the client's load-complete notice, during the intro
  cinematic. The five-entry tour (20:41) ran Vfx_Bmg_Spawn before Spawn, and Tutorial 1 so far raised only Spawn: the
  scriptlet half is now sent too. `champion_spawn_hold` 0 (was 5.0): the tutorial starts as soon as the intro ends.
- `winctl.press_key`: the F press for the throw's aim carries the key's scan code and is held 80 ms (it was a
  scan-code-0 press released at once; the client sent no skill order after it, server.log 21:50:03.03).
- `sphere_fall_step` 0.2 (was 0.1) and `sphere_step_overlap` 0.3 (new): each step of the sphere's fall stays until the
  next one has faded in (the frames showed it appear on the ground between two 0.5 s frames).
- BridgeVehicle: under `start_at` it was spawned by finale.start with the model-origin offsets, at (107.7, 17.9)
  instead of (107.3, 17.2). `finale._spawn_car(raw=True)` places it exactly where Tutorial 1's bridge part puts it.

## fase3-ip — no voice line at the start; no server F press; the sphere appears inside its dust

22:40 (tester): a Batman voice line plays as the match is about to start (it must not); no yellow ring when the car is
lifted; the sphere's fall looks frame by frame ("horrible"); the crater and the opening animation are fine.

- `champion_intro_keys` [0x10000181] (was [0x100009EC]) + `champion_intro_events` [0x10000154] (new): the parts of
  Cinematic_Intro without its action 0x737 = 2 (Vfx_Bmg_Spawn and the graph event Spawn), still 0.5 s after load
  complete.
- `throw_auto_aim` 0 (was 0.4): server.log 22:38:46.43: with the scan code the F press reached the game, and the
  client answered with a skill order at the cursor (ability 8) in the same millisecond: it smart-casts F and threw the
  car instead of showing the rings.
- `sphere_from_height` 0 (was 12), `sphere_fall_seconds` 0 (was 1.0), `sphere_step_overlap` 0 (was 0.3): the sphere,
  its dust and the crater ring are created together on the ground; the dust hides the sphere's fade-in.

## fase3-iq — the throw skill really goes on F; Cinematic_Intro during the loading screen; crater at the impact

22:51 (tester): the crater shows before the sphere's impact animation; with fase3-io (Cinematic_Intro, with the voice
line) the antennas were lit, with fase3-ip they are not; the throw looks odd and there is still no yellow aim.

- The throw skill 0x480003C9 was never on F: `skilldata` read it as 0 properties (server.log 22:38:46 "0 properties":
  0x10000ABC, 0x1000063A, 0x100006D5, 0x10000646, 0x100006D7 / D8 had no known kind), so `_f_skill(True)` kept
  Super Strength. Unknown kinds now come from `catalog/data/properties.tsv` (`skilldata.catalog_kinds`); the record
  reads as 12 properties with targeting 0x1000003D = 1 (ground) and its ground markers. If a throw table has no
  targeting, the lift's is added.
- `throw_min_distance` 5.0 (new): a target closer than 5 m is pushed out to 5 m along its direction (22:48:33: an
  attack order on a drone 0.3 m away threw the car at Batman's feet).
- `champion_intro_keys` [0x100009EC] again, `champion_intro_events` [], `champion_intro_at` "link" (new): Cinematic_Intro
  runs 0.5 s after the player -> champion link (the client is still on its loading screen) instead of after load
  complete. Its record raises Spawn through its own action type 0x737 (with parameters), not through the HFSM
  raise-event scriptlet, which is likely why fase3-ip's split did not light the antennas.
- `sphere_impact_delay` 1.05 (new): the sphere's dust and crater ring come with its impact (Vfx_Spawn_Hit 0x1000087E,
  1.05 s after it appears) instead of with it.

## fase3-ir — the antennas without the spawn's voice line

23:02 (tester): nothing may sound, not even on the loading screen; Batman must start the tutorial with the electricity
between his antennas, as in the videos and pictures of the original.

- `champion_intro_keys` [] (was [0x100009EC]): Cinematic_Intro is no longer sent; its graph event Spawn plays his
  respawn clip (Clip_Spawn, chr_batman_gaslight_attk_respawn_a) with the voice line.
- `champion_spawn_events` [0x10000031, 0x100001AE] (was [0x10000154]), `champion_spawn_delay` 0.3 (was 0): at the
  tutorial start the graph events of the END of his spawn are raised instead: RunScript_FX_Spawn_End and
  RunScript_Vfx_Active (the electricity came on when Spawn ended, 20:41). Untested guess; if the antennas stay dark the
  next step is a Tutorial 2 tour of these end-of-spawn events.

## fase3-is — Cinematic_Hidden for the antennas; the opened sphere stays

23:09 (tester): still no yellow ring around Batman; the sphere falls but does not play its opening, and a few seconds
later the part that opens disappears; no electricity between the antennas.

- `champion_spawn_events` [] (the end-of-spawn graph events of fase3-ir lit nothing); `champion_start_keys`
  [0x100009EB] (new): Cinematic_Hidden at the tutorial start: its own action type 0x737 raises SpawnIdle, the state
  that follows Spawn, without Spawn's respawn clip and voice line.
- `sphere_open_at` 0 (was 7.5): no swap to the open model 0x2E00101D (the 21:49 frames: the opened halves vanish at
  the swap). The dust comes with the sphere again; only the crater ring waits `sphere_impact_delay`.
- The throw: server.log 23:08:11 reads the throw skill with 12 properties and puts it on F, but the client cast it on
  the F press at the cursor (23:08:13.202, 13 m away) without aiming: F is cast at once on this client.

## fase3-it — Batman visible again; the sphere as in fase3-ip; a short tour for the antennas

23:19 (tester): Batman vanished and only came back when he lifted the car; the sphere must be as it was when it worked
(fase3-ip): now something shows on the ground before it falls and it does not open.

- `champion_start_keys` [] (was [0x100009EB]): Cinematic_Hidden hides Batman (SpawnIdle is the hidden state before a
  spawn).
- `sphere_open_at` 7.5 and `sphere_impact_delay` 0 again: the sphere, its dust and the crater ring together, the swap
  to the open model at 7.5 s, exactly fase3-ip.
- `[debug] champion_tour_only` = G Spawn, S Vfx_Bmg_Spawn, G Spawn, S Cinematic_Intro, every 8 s (was 6) in Tutorial
  2: which one lights the antennas and which one plays the voice line.

## fase3-iu — Cinematic_Intro at the tutorial start

23:29 (tester, Tutorial 2 tour of fase3-it): only "S 2/2" (Cinematic_Intro) lit the antennas; G Spawn alone and G Spawn
after Vfx_Bmg_Spawn did not.

- `champion_intro_keys` [0x100009EC] again, `champion_intro_at` "start" (was "link"), `champion_intro_lock` 2.8 (new):
  Cinematic_Intro runs on Batman in the game as the tutorial starts (right after the refresh that follows the intro
  cinematic), not on the loading screen where its voice line was heard (22:40); none of the three lab tours that ran
  it (19:52, 20:41, 23:28) reported a voice. Batman stands still 2.8 s meanwhile (the start's meteors hold him that
  long anyway).

## fase3-iv — the sphere opens again

23:34 (tester, video 23:32 with fase3-it): the sphere still fails: something shows on the ground before it falls, it
does not open, and later it is gone.

- Frames (0.5 s): the crater ring appears ~1 s before the sphere has faded in; Vfx_Event1 at 4.0 s opens nothing; at
  the swap (7.5 s) the sphere vanishes and the open model 0x2E00101D does not show, only the ring and the Destroyer.
  In the 21:49 video (fase3-io, falling steps) it opened: there Vfx_Spawn 0x10000032 went to a fall step, never to the
  sphere on the ground (as at 16:19, when Vfx_Spawn on the sphere on the ground kept it closed).
- `sphere_cinematic_keys` without [0.55, Vfx_Spawn]; `sphere_open_at` 0 (was 7.5: no swap, the opened sphere stays);
  `sphere_impact_delay` 1.05 (was 0: the crater ring with Vfx_Spawn_Hit, the impact). The dust stays with the sphere.

## fase3-iw — Batman's spawn during the intro cinematic

23:38 (tester, video 23:37 with fase3-iv): a strange rope animation on Batman. Frames (0.25 s, cropped): as the camera
reaches him a yellow line runs from the sky down to him with a blue ring at his feet (his respawn, ~1 s); afterwards
the blue arcs on his antennas are on (Cinematic_Intro works for the electricity).

- `champion_intro_at` "cinematic" (new value, was "start"), `champion_intro_delay` 1.5 (was 0.5): Cinematic_Intro runs
  1.5 s after the intro cinematic 0x35000026 is sent (it lasts ~4.7 s), while its camera shows the street, so the
  spawn is over when the player sees Batman. "start" still works; its lock is not applied with "cinematic".

## fase3-ix — the sphere with its crater and dust; no spawn effect on Batman

23:46 (tester): the sphere is to appear on the ground together with the crater and the dust wave; skipping the intro
cinematic right away still shows Batman's spawn rope, so Batman goes without the antennas' electricity while the tester
looks for the effect that turns it on.

- `sphere_impact_delay` 0 (was 1.05): the sphere, its crater ring and its dust come together.
- `champion_intro_keys` [] (was [0x100009EC]): no Cinematic_Intro. No spawn scriptlet or graph event is sent to Batman
  (`champion_spawn_events` and `champion_start_keys` are empty too).

## fase3-iy — which maps have a champion select; the champion select in Coast City v AI

23:53 (tester): some maps should load the champion selection first and then the map.

- Validated from the game data (reverse-engineering.md, "Champion select before the map"). Only Tutorial 1 and
  Tutorial 2 skip the lobby (SkipsLobby 0x10000B0E). The 4 PvP maps and Crisis Labs, the 3 Clash maps, the 4
  versus-AI maps and Tutorial 3 have a champion select.
- The server never shows it: its 0x204C sends 0 teams, and the client only sends the lobby details to the UI when the
  number of teams is not 0. catalog stages.tsv notes updated. No behaviour change yet.
- 00:06 (tester: start with a "1 vs AI" map, the AI being the Gaslight Batman we already have, to begin the other
  champions). Crime Alley (Tutorial 3, Crime Alley v AI) is not in the install. The candidate is Coast City v AI
  0x40000B6A (packs in [match] maps since fase3-gz; whether it loads is still unconfirmed), set up as 1 v 1 by the server.
- 00:06 (tester): the right Destroyer sphere is a purple one (ours, 0x2E000FC7, is yellow); to be found later.
- 00:13 (tester: "do it with Coast City vs AI"). Coast City v AI 0x40000B6A gets `[match] maps` "lobby"
  {teams 2, per_team 1, lock_events [], wait 60}:
  - 0x204C now carries the number of teams, players per team and my team (`messages.lobby_state`); before, it
    sent 0, 0, 0.
  - 0x2016 + 0x206D and the object creation wait until a client event listed in `lock_events` arrives, or `wait`
    seconds pass (`Session._lobby_finish`). 0x2016's apply is the client's "lobby over, load the world"
    (0x8b8a90 -> 0xab9080 -> CheckTransitionToWorldLoad 0xab8ec0).
  - Every client event during the champion select goes to server.log ("champion select: client event ..."), to find
    the select and lock events.
  - The map still loads with Gaslight Batman; the chosen champion and the AI come next.
- New tests/test_lobby.py (10 checks).

## fase3-iz — champion select: every champion allowed, the lock answered

00:25 (tester): the champion select shows, but no champion can be locked; "enable them all and make the button work".
server.log 00:23:32 / 00:24:11: the client sent 0x20E4 (9 bytes: u32 variant, Green Arrow 0x400006F9 and
0x40000E57 | u8 1 | u32 1) twice and got no answer.

- 0x204C's last list (u32 count + DIDs) is taken as the champions the match allows. It carried only Gaslight Batman;
  for a champion select it now lists the whole roster (`[match] maps` "lobby" "available" = "all").
- New handler for 0x20E4 (`Session.ev_lobby_character`), taken as the lock request
  (`SendNotice_PlayerChangedCharacterLockStatus(did, true)`). The server sends the slot 0x2029 back with that
  character and the locked byte, then ends the lobby `lock_delay` (2 s) later. `lock_ends` = false keeps the lobby
  open.
- `wait` 120 s (was 60).
- The map still loads with Gaslight Batman.
- tests/test_lobby.py: 12 checks.

## fase3-ja — play the locked champion; Gaslight Batman as the bot; Coast City's own lighting

00:35 (tester, fase3-iz): the lock worked (server.log 00:32:05: 0x20E4 for John Stewart 0x40000E57, map loaded 2 s
later), but "I must play the champion I choose, with Gaslight Batman on the other side". The map is very dark (fog
of war / vision?), and the store items do not load.

- `[match] maps` "lobby" `enter_after_lock` (new, true): with a champion select, 0x20AF (the champions whose data the
  match loads) is no longer sent at the game connection. It goes after the lock, naming the locked champion and the
  bot's.
- `play_pick` (new, true): the locked champion is the match's champion and the class of the controlled object
  (`Match.agent_class`, was always `[match] agent_class`).
- `bot` (new): the AI's champion, Gaslight Batman 0x40000086, team 2, 600 health, created 1 s after the match starts at
  Coast City's enemy start (mission 0xA0000162, cinematic 0x35000012 Player01 (137.47, 60.22, 250.19)). It stands
  still: no AI yet.
- `[match] maps` "lighting_env" (new, per map): Coast City v AI sends no 0x956 (0), so the client uses the region's
  lighting. 0x10000016 is Tutorial 1's.
- The locked champion's own skills are not implemented by the server (only Gaslight Batman's are). The in-match
  store is not served yet.
- tests/test_lobby.py: 16 checks.

## fase3-jb — the map's own fog map (exe patch); free play: level 6, ranks, training drone, animation tour

**Requires `python ic.py patch`.**

00:44 (tester, fase3-ja): the chosen champion loads. The map is still dark. Asks: level up in the HUD starting at
level 6; every possible animation of the champion; a drone that can be attacked but is indestructible; check the fog.

- Dark map: the minimap cave M (fase3-cg) loaded Tutorial 1's map image (MINIMAP_ENCOUNTER) for every map. The
  fog-of-war blocker map reads that map data, so on Coast City the fog was Tutorial 1's. New cave N (rva 0x997f5c):
  where cave M pushed the constant, it pushes the lobby manager's encounter ([[VA 0x1b77068]+0xb4], set by 0x204C).
  It finds the global position-independently (call/pop), because the client runs with ASLR. Tutorial 1 is the
  fallback.
- New icserver/freeplay.py, `[match] maps` "free" on Coast City v AI:
  - Start at level 6 with 6 skill points (`start_level`, `skill_points`).
  - The '+' ranks Q W E R (`max_ranks` [0, 5, 5, 5, 3]): Q/W/E up to (level + 1) // 2, R at levels 6, 11 and 16.
  - One more level every 60 s up to 20 (`level_up_seconds`, `max_level`).
  - A Training Drone 6 m from the start (`drone_class` 0x40000A5C, `drone_offset`). It takes hits, but its health stays
    full (`Entity.invulnerable`).
  - A tour of the champion's animations: every graph event named in his behavior-graph pack (roster "parent_pack"),
    read when the lobby ends. Green Arrow has 130, Superman 148, Gaslight Batman 125. One every 4 s
    (`tour_interval`), named in the objective; deaths and knockdowns are followed by CbtState_GetUp.
- `_enemy_near` uses the map's landblock (was Tutorial 1's 0x13CB).
- tests/test_lobby.py: 19 checks.

## fase3-jc — John Stewart's abilities (Q W E R) in free play

00:57 (tester): "program John's abilities".

- New `icserver/kits.py`: on a map outside the tutorial (Coast City v AI after the champion select), a skill order
  for John Stewart (0x40000E57) goes to his kit instead of being ignored. Each cast checks the rank (the '+'),
  the cooldown (0x20F8 on the button) and the Will (0x42), raises his graph event (Wildcard_QSkill ...) and plays
  his scriptlets (Vfx_Jst_*).
  - Q Full Auto: 8 shots in 2 s at the first enemy along the aim (11 m x 2 m).
  - W Claymore Mine: a mine at the aim (up to 9 m); it arms in 1 s, lasts 30 s and goes off on an enemy within 3.5 m.
  - E Forward Base: a base at the aim for 12 s; inside it (5 m) John regains health and Will.
  - R Omni Turret: a turret at the aim for 20 s; every second it shoots the nearest enemy within 12 m.
  - Will regenerates 2 per second.
- The game data only has placeholder numbers for him (40 damage +40 per rank, 30 Will, 14 s cooldown -2 per rank)
  and no description of the effects: the behaviour is an interpretation of the skill names. Every number can be
  changed with `[combat] kits` (new setting).
- Not done: the passive (Architect's Will), his own basic attack, world objects for the mine, base and turret.
- `freeplay.graph_event_names` only reads the graph-event table (offset < 900000), not the scriptlet names.
- New test `tests/test_kits.py` (16 checks).

## fase3-jd — fix: `ic.py patch` refused the exe (cave N overlapped cave X)

**Requires `python ic.py patch`.**

01:10 (tester): `python ic.py patch` -> "unexpected bytes at 0x99735c ... not the 2015 Steam build".

- fase3-jb's cave N (the lobby's encounter for the map image, the dark-map fix) was placed at file 0x99735C, two
  bytes into cave X (props, file 0x99735A, 54 bytes). The patcher applies cave X first, then found cave X's bytes
  where cave N expected 0xCC padding. So no fase3-jb exe patch was ever applied, and the map was still dark.
- Cave N now uses free 0xCC padding at file 0x4C4380 (rva 0x4c4f80); cave M calls it there. Checked by building
  the patched exe from the 2015 Steam exe and disassembling both caves.
- New `tests/test_patcher_layout.py`: no two patches overlap; with the exe path, the full build applies.

## fase3-je — documentation brought up to date

01:30 (tester): "make sure everything is documented" (before the branch goes to EricHardiman/infinite-crisis-server).

- `README.md`: every module and test listed, Coast City v AI / free play / John Stewart in the status, the full
  list of files kept out of the repository.
- `CLAUDE.md`: `kits.py`, `champion_fx.py`, `net.py` / `log.py` / `scheduler.py`, `progress.py`,
  `tools/split_file.py`, `tests/test_kits.py` and `tests/test_patcher_layout.py`.
- `docs/HANDOFF.md`: a "Current state (fase3-jd)" section (confirmed, shipped but not seen, decisions, open
  work); the fase3-gz handoff kept below it.
- `docs/AI_GUIDE.md`: how to add a champion's kit, a champion-select map, and change an exe patch.
- `config.example.toml`: where the per-map settings are, and an example of `[combat] kits`.
- Catalog: John Stewart's passive and basic attack had an invalid status (now `data only`); two IDs used in the
  code were missing (0x35000013 Coast City mission layout, 0x480007FC meteor damage-area skill).
  `tests/test_catalog.py` passes again.
- No code changes.

## fase3-jf — docs/FINDINGS.md: summary for new contributors

10:02 (tester): the documentation still missed some things for the team: Tutorial 1 does not disconnect at the end
and can be played again; which maps are in the files and which are not, and what can or cannot be built because
of it; sorting the new champions alphabetically breaks the portraits; the profile pictures can be changed; some
animations and game elements are still not found; anything else relevant.

- New `docs/FINDINGS.md` with all of that (Tutorial 1, maps table, champions, profile and collection, not found
  yet, findings to know before changing code). Linked from `README.md`, `CLAUDE.md`, `docs/AI_GUIDE.md` and
  `docs/HANDOFF.md`.
- `catalog/data/stages.tsv`: every encounter says whether its map files are in the install; Coast City v AI is
  `implemented` (champion select, free play).
- `icserver/roster.py` and `CLAUDE.md`: the added champions stay after champions.json's; sorting them
  alphabetically gives champions the wrong portrait (tester). Docstring only, no behaviour change.

## fase3-jg — the Amplifiers tab: the data it waits for

10:09 (tester): the Amplifiers tab keeps loading and never shows the amplifiers.

- The tab waits for three pieces of data (`docs/reverse-engineering.md`, "The Amplifiers tab"). Two of them never
  came in the menus:
  - the amplifier set list (0x2090), which was sent only with the scorecard;
  - the store's amplifier data (0x2107, newly decoded), which was never sent.
- `[account] send_amplifier_data` (new, on): 0x2090 (0 sets, `amplifier_set_slots` = 6, a guess) and an empty
  0x2107 (`scorecard.amplifier_boutique_data`) are sent at login, before 0x2080, and again when the client sends
  0x2116 (on opening the tab).
- The third piece (the amplifiers' own data) comes from the item statuses the server already sends (162 augments,
  172 mods as owned).
- Catalog: network events 0x2107, 0x2116 and 0x2106 added, 0x2090 updated.
- `tests/test_collections.py`: 9 checks (was 5). `tests/test_e2e.py`'s login check counts the two new messages.
- Not seen in the game yet. If the tab still loads forever, the next suspect is 0x2106 (the store request).

## fase3-jh — the Amplifiers tab: answer its own requests

10:23 (tester's logs with fase3-jg): the login carried 0x2090 and 0x2107, but the tab still loaded forever.

- Flash creates BoutiqueDataManager and AmplifierSetManager only when the tab opens. Their constructors clear their
  "have data" flags, register for the notices and send the requests that reach the server as 0x2116. So the
  login's 0x2090 / 0x2107 arrived before anything listened.
- The reply to 0x2116 was then skipped: 0x21A4 (Champions data, sent 1.2 s before) had used the 2 s limit of
  `resend_collections` (server.log 10:22:45.706 / 10:22:46.898, no message sent after it).
- 0x2116 is now always answered at once with 0x2090, 0x2107 and the item statuses 0x20B8. AmplifierSetManager
  builds its amplifier list on `EVENT_ITEM_STATUSES_UPDATE`. The 2 s limit stays for 0x21A4 only.
- `tests/test_collections.py`: 10 checks (0x2116 right after 0x21A4).

## fase3-ji — 0x2116's own answer: 0x2115 (store offers)

10:28 (tester's logs with fase3-jh): no 0x2116 or 0x21A4 in this session, only 0x20BA and 0x2106 at 10:28:16. So
the server could not answer the tab.

- 0x2116 is sent by VA 0xa57170 only while the store UI's "offers loaded" byte (+0x1b1) is 0. Otherwise the client
  rebuilds the lists from its cache (VA 0xa416b0).
- That byte is set by the exec of **0x2115** (VA 0x8aad20 -> 0xa57000), the store's offers. Each offer is 0x230
  bytes (reader VA 0x866650, not decoded). The exec looks for offer 0x4000094C, sets the byte and rebuilds the
  lists.
- 0x2116 is now answered first with an empty 0x2115 (`scorecard.store_offers`), then 0x2090, 0x2107 and 0x20B8 as
  in fase3-jh.
- `tests/test_collections.py`: 11 checks.
- Open: what the tester did in the 10:28 session, and whether the tab still loads after a full restart of the
  game.

## fase3-jj — the Stats tab: account encounter stats (0x2115)

10:36 (tester, fase3-ji): the amplifiers take a moment but now show. Asks: can the Stats tab show data?

- fase3-ji took 0x2115 for the store's offers. It is the account's **encounter stats**. Its exec (VA 0xa57000) caches
  the entries and calls VA 0xa416b0, which calls VA 0x8ce3d0, the caller of Flash
  `GM_Character.RecvNotice_SendAccountEncounterStats(encounters, ranked, stat labels, stat data)` (string at VA
  0x15f4210). 0x2116 is `RequestAccountEncounterStats`.
- Entry layout (reader VA 0x866650, 0x230 bytes in memory): u64, ranked bool, u32 encounter DID, then 60 counters
  (u64 integers and a few u32) and two StringInfos (`scorecard.ENCOUNTER_STATS_FIELDS`). The labels come from each
  encounter record (property 0x10000A73). Entry 0x4000094C is put first, probably the totals.
- `[account] encounter_stats` (new, "sample"): 0x2115 carries made-up counters for the totals entry and the 15
  encounters. They are different per encounter and never 0, so a screenshot can show which counter feeds which
  label. "empty" = no entries.
- `tests/test_collections.py`: the 0x2115 check now looks at the 16 entries.
- Not seen in the game yet. A wrong layout would show as a broken Stats tab or a client error in the log.

