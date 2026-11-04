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

## ue5-01 — new server for the UE5 client: protocol, accounts, asset service, texture export (2026-10-18)

The user decided that the Python server is the base of a future Unreal Engine 5 client (a thin client that
connects and downloads what it needs). Design draft: [`ue5-architecture.md`](ue5-architecture.md). The legacy
server for the original client is untouched.

- New package `uesrv/`: JSON-lines control protocol (`hello`, `register`, `login`, `profile`, `asset_info`),
  HTTP asset service (`/asset/texture/<did>.png|dds`, needs the session token), accounts with PBKDF2 in
  `data/uesrv_accounts.json`, `uesrv/client.py` (reference client), `uesrv/textures.py` (0x13 -> DDS/PNG, DXT1/3/5).
- `python ic.py uesrv` starts it; `python ic.py export-texture 0x130002CB [folder]` writes PNG and DDS (default
  `exports/`, git-ignored).
- Config: new `[uesrv]` section (host, ports 9100/9101, accounts file, cache dir). Default host 127.0.0.1;
  set `0.0.0.0` to allow another PC of the LAN.
- Test: `python tests/test_uesrv.py` (10 checks, uses ports 19100/19101 and a temp cache).
- Catalog: asset types 0x10, 0x14, 0x16, 0x17, 0x18, 0x19, 0x36 now described.
- Converted assets live only in git-ignored folders (CLAUDE.md hard rule 1).

## ue5-02 — static mesh format (0x17) and OBJ export (2026-10-18)

- `uesrv/meshes.py` decodes 0x17 static meshes of format `0x1205102` (24-byte vertices, u16 indices) and writes OBJ
  with UV and normals; `python ic.py export-mesh 0x170000CB [folder]`; the asset service serves
  `/asset/mesh/<did>.obj`. Test `test_uesrv.py` now has 11 checks (1064 vertices, 532 triangles).
- Gaslight Batman's own mesh is **not** exported yet: see the "Mesh" section of `reverse-engineering.md`.

## ue5-03 — RenderDoc capture tooling for the skinned mesh (2026-10-18)

- `tools/renderdoc_dump.py` (runs inside RenderDoc) dumps every draw's buffers and vertex layout;
  `tools/rdoc_analyze.py` lists draws, writes OBJ and finds the buffers inside a pack (`--match`).
  Tested offline with a synthetic dump built from Batman's pack; the RenderDoc side is untested (not installed here).
- Steps in [`capture-meshes.md`](capture-meshes.md). The in-process debugger `tracer.py` is not used for D3D11 (it
  breaks on fixed exe RVAs and the earlier debugger runs crashed the game).

## ue5-04 — skinned mesh format solved from a RenderDoc capture (2026-10-18)

- The tester captured Tutorial 1 with RenderDoc 1.46 (799 draws, 20 skinned). Gaslight Batman's body (6558
  vertices, 9821 triangles) and legs (1531 vertices, 2314 triangles) are stored in pack `0xA0000076` exactly as the
  client's D3D11 vertex/index buffers, except the bone indices (skeleton-global in the pack). Format in
  `reverse-engineering.md` ("Skinned character mesh"). The cape (cloth) is not in that form.
- `uesrv/meshes.find_skinned` decodes formats `0x24D102` / `0x23D102`; `python tools\mesh_export.py <pack> <folder>
  [--skin]` writes OBJ (+ bone indices / weights JSON) and refuses folders inside the repository.
- Fixes: `tools/renderdoc_dump.py` (RenderDoc 1.46 has no `semanticIndex`), `tools/rdoc_analyze.py` (reads
  R16G16_SNORM UVs, skips draws whose dynamic vertex buffer was saved with other contents).
- No config change (tools only).

## ue5-05 — Gaslight Batman to glTF: mesh + Havok skeleton + skin weights + textures (2026-10-18)

- `uesrv/havok.py` reads Havok 2012.2.1 binary packfiles (fixups, class names) and their `hkaSkeleton`s:
  Batman's `MainSkeleton` has 86 bones; the mesh bone indices index it directly.
- `uesrv/gltf.py` builds a binary glTF: both skinned meshes, the skeleton as joint nodes with inverse bind
  matrices, weights normalised to 1, base colour / normal (unswizzled to the OpenGL convention) / emissive textures
  embedded as PNG. Z-up/+Y-forward -> Y-up/+Z-forward rotation, metres.
- `python tools\gltf_export.py 0xA0000076 C:\ic_export\batman batman_gaslight` writes `batman_gaslight.glb`
  (8089 vertices, 12135 triangles, 2.5 MB) and `batman_gaslight_specular.png`; refuses folders inside the repo.
- Checked with a software render of the .glb (front, side, bent left elbow): textured, facing +Z, skinning follows
  the bones; world x inverse-bind = identity (5.8e-8).
- `uesrv/textures.py`: `png_from_rgba`, `normal_map_rgba`. `tests/test_uesrv.py`: 15 checks (skinned meshes,
  skeleton, material textures, glb).
- Not yet: the cape (Havok cloth), specular in the glTF material, animations.

## ue5-06 — Havok spline animations decoded and exported to glTF (2026-10-18)

- `uesrv/havok_anim.py` decodes `hkaSplineCompressedAnimation` (masks, static / spline tracks, 8/16-bit vectors,
  THREECOMP40 / THREECOMP48 quaternions, B-spline evaluation) and maps tracks to skeleton bones by name.
  All 69 clips of Batman's behavior pack `0xA0000122` parse with the block cursor landing on the next block.
- Clip DIDs from the character's clip table (`clip_table`, `clip_dids`); the clip *names* are still unknown, so
  animations are named `anim_<DID>_<duration>`.
- `python tools\gltf_export.py 0xA0000076 C:\ic_export\batman batman_gaslight --anims 0xA0000122`: the .glb now
  carries 67 animations (5970 frames at 60 fps, 15 MB); rotation channels for every bone, translation / scale only
  where they leave the reference pose; Z-up converted like the mesh.
- Checked by reading the .glb back and rendering frames of several clips (natural poses, no broken limbs).
- `tests/test_uesrv.py`: 18 checks (clips parse, DIDs, track-to-bone map).

## ue5-07 — Batman clip names: 16 verified, the rest still by DID (2026-10-18)

- Searched the name -> DID link statically (asset-bundle names in the character data, project file list, clip
  generators in every traversal order): none matches the clip table; see reverse-engineering.md "Name search".
- Verified names from the clips themselves: the 15 locomotion clips (normal / car / rubble, by Root ground speed
  and arm pose) and the reference pose, added to `catalog/data/animations.tsv` as kind `clip`.
- `tools/gltf_export.py` names the glTF animations from the catalog (`clip_names`); 16 of 67 now carry their real
  name, the others stay `anim_<DID>_<duration>`.
- `tests/test_uesrv.py`: 19 checks (named locomotion clips have their root speed).
- Next for the remaining names: trace in the running client which DID plays for each clip.

## ue5-08 — clip-name trace for the running client (2026-10-18)

- `tools/diag.py --anims`: breakpoint at rva `0x899ea5` (after the asset-loader call in the Havok clip linking
  function `0x899de0`); one `ANIM` line per linked clip with its animationName and the linked animation's
  signature. `--anims` skips the default skills breakpoints.
- `tools/anim_names.py [logs\diag.log] [--write]`: matches those signatures (frames, blocks, data size, first bytes,
  CRC32) against the behavior pack's 69 animations and prints / writes clip DID -> name into
  `catalog/data/animations.tsv`. Dry-run tested with a synthetic trace; the client side is not tested yet.

## fase3-fn — server scripts (0x34) decoded and run: Q (Sonic Batarang) from the game's own data (2026-10-21)

Goal (user, 2026-10-21): run as much of the game as possible without hand-writing each feature. The 0x34 records
are the original server's scripts (hierarchical state machines of visual-programming nodes); the client exe still
contains the VM classes that read them, so they can be decoded exactly and interpreted on our server.

- `tools/script_decoder.py`: runs the client's own Unpack code under Unicorn emulation (needs
  `pip install unicorn capstone`). `python tools\script_decoder.py all` writes `data/script_trees/*.json`
  (790 of 821 scripts decode exactly; not committed, it is derived from the install).
- `tools/script_nodes.py` + catalog table `script_nodes.tsv` (444 node / expression types, 346 registered).
- `icserver/scriptvm.py` (model, `python -m icserver.scriptvm 0x3400003B` prints a script as pseudo-code),
  `icserver/scriptvm_runtime.py` (interpreter: graphs, states, transitions, events, missiles),
  `icserver/scriptvm_world.py` (the tutorial side: scriptlets, facing, cooldown 0x20F8, damage, missile VFX).
- Q in Tutorial 1 can run from script `0x3400003B` + missile script `0x3400003F`: face, cast scriptlet
  `0x10000164`, cooldown from stat 15, damage from stat 5, ricochet to the nearest other target (stat 17), ends
  after MaxCollisions. The missile is simulated on the server (VFX on Batman); Will is not tracked yet.
- `tests/test_scriptvm.py` (8 checks, simulated world).

Config `[scriptvm]` (new): `batarang` (default **false**, the hand-written Q stays until tested in game),
`cast_point` 0.25, `missile_vfx` / `missile_stop_vfx` (scriptlets per missile class), `hit_keys`, `trace`
(log lines `scriptvm ...` in `server.log`).

To test: `python tools\script_decoder.py all`, then `[scriptvm] batarang = true` in `config.toml`, Q on the drones.

## fase3-fo — new data-driven server: python -m ics (2026-10-21)

The user (2026-10-21): write a new server, using as little of the old one as possible, so the game runs with the
most features and the fewest hand-written adjustments, from what the files already hold. The project now lives
in `C:\Infinite Crisis Server\server` (the game copy is its parent folder).

- New package `ics/` (`python -m ics play | server | skills [variant]`). Carried over from `icserver/`: only
  `wire.py`, `crypto.py`, `net.py`, `scheduler.py`, `log.py`, `rp.py` and the message layouts (`messages.py`).
  New: `gamedata.py` (kits, entity / status scripts, layouts from the packs and the catalog), `world.py` (entities,
  movement, combat, the bridge to the scripts), `session.py`, `server.py`, `config.py`, `script_model.py` +
  `script_runtime.py` (the script VM, moved from `icserver/scriptvm*.py` and extended).
- What it does from the data: the champion's whole kit runs from its server scripts (Batman: basic attack, Q, W,
  E, R, passive); missiles are objects of their own class with the scripts their template lists; status effects
  run their own scripts; the encounter layout's units are created from the packs (12 in Tutorial 1).
- Script runtime: enter / update / exit chains, cast signals, status effects and stacks, events between the
  scripts of an entity, timers, and 13 more node / expression types (see `docs/reverse-engineering.md`). Skills
  that run with no unknown node: 42 -> 125 of 259 (`python tools/script_coverage.py`).
- Not there yet: the tutorial's own flow (objectives, dialogue, cinematics: not found in the server scripts, the
  original server's code), unit AI, props (doors, vehicles), champion attributes (health, Will, attack damage are
  `[ics]` settings), leveling.
- Tests: `python tests/test_ics.py` (21 checks, simulated client against the new server), `python
  tests/test_scriptvm.py` (13, now on the new runtime).

Config: everything new is in `[ics]` (`ics/config.py`, each value says why it is there): `champion`,
`encounters` (packs, layout pack, spawn), `health`, `will`, `will_regen`, `unit_health`, `basic_attack_damage`,
`attributes`, `variant_overrides` (0x40000C72 -> 0x40000A5C, the targetable drone), `spawn_layout`,
`run_unit_scripts` (off), `missile_objects`, `trace_scripts`. `[game]` and `[server]` are shared with the old
server.

To test: `python -m ics play`, Tutorial 1, walk to the drones, right-click (basic attack) and Q / W / E / R.

## fase3-fp — ics: map load, normal basic attack, batarang thrown at the ground (2026-10-21)

16:23 (tester, first game test of `python -m ics play`): the map loads wrong; the batarang animation plays when it
is thrown and nothing more; the basic attack always plays the critical-hit animation. Asked whether the exe itself
could run the game: it cannot (the client's script classes only load / save / clone, see
`docs/reverse-engineering.md`), so the server keeps running the game's own scripts.

- **Map:** the player object carries the encounter (0x100001D3) from its second bundle on, during the load, as the
  earlier server did (it came only after the load: the client reported load complete at 60 %). The layout's units
  come `[timing] units_delay` (3 s) after load complete instead of at once.
- **Basic attack:** builtin 0x10 is "the variable is true" (it was always true: always the critical shot); now the
  normal left / right shots play.
- **Batarang at the ground:** a missile aimed at a point flies on in that direction to the end of its range and
  hits the first hostile unit it passes (1 m); before, it stopped at the cursor and vanished.
- **Ricochet:** ApplyEffects' DamageSuccess output and the `>=` class 0x15A88E0 (the missile ended after the first
  hit once its scripts came from the data).
- Tests: `tests/test_ics.py` 21/21, `tests/test_scriptvm.py` 13/13; `tools/script_coverage.py` 126 of 259.

## fase3-fq — ics: the encounter's packs from the data, the layout's props, missile effects (2026-10-21)

17:00 (tester): the map loads only in part, walking forward goes down instead of right, the batarang leaves but
does not bounce, no vehicles; analyse how the exe loads a map so the server knows what each map needs.

- **Static analysis of the load** (`docs/reverse-engineering.md`): the client loads exactly the packs the server
  lists in 0x20AF. The packs now come from the data: encounter template 0x10000406 = the map pack, which lists the
  encounter's packs; plus each champion's model pack from the roster. Tutorial 1 now loads its layout
  (0xA0000256) and variants (0xA0000257) packs, never sent before. `[ics.encounters]` "packs" is only added to it.
- **Layout:** every placement is created as its data class (units 12, props 14: doors, power core, vehicles, the
  ranged drones as bare world states); `variant_overrides` is off (the real tutorial drone 0x40000C72);
  `spawn_world_states`.
- **Batarang:** its own effects (0x100001C1) play on the missile object; the ricochet only picks hostile units
  (FindTargetsInRadius relation 3), not Batman.
- **Camera:** the intro cinematic 0x35000026 as the earlier server played it (`intro_cinematic`,
  `[timing] cinematic_delay`); the client sets the map camera when a cinematic ends.
- The server reads the encounter data at start (about 20 s, in the background).

## fase3-fr — ics: the client closed at the end of the load (2026-10-21)

17:14 (tester): the load screen did not finish and the game closed. The server had sent vitals (0x42) to every
layout placement, the doors and vehicles too; 0x42 to an object with no vitals component crashes the client
(known from the earlier server). `World.vitals` now skips objects without health; `tests/test_ics.py` checks it
(23 checks).

## fase3-fs — ics: HUD shown, scriptlets back to the target-only form (2026-10-21)

17:23 (tester): the match loads and Batman walks the whole map; the drones do nothing, the batarang does no damage
(on screen), no HUD, no vehicles, no animations. Server side the batarang hit and bounced (server.log).

- **HUD:** the tutorial starts with it hidden; every element of `catalog/data/hud_elements.tsv` is shown (0x213D,
  event 1) at the start (`[ics] show_hud`).
- **Animations:** the scriptlets carry only the target (0x108), as in the first test where they played; the
  script's own variables (0x10000030 / 0x100009EB) are behind `[ics] scriptlet_variables` (off).
- Open: unit AI and the tutorial's flow are not in the server scripts; bare world-state props (vehicles) are not
  drawn by the client (as the earlier server found); damage not shown on screen.

## fase3-ft — ics: champion animations after its bundle, HUD after the intro (2026-10-21)

17:33 (tester): still no HUD, no animations, drones idle. The HUD (24 elements) and the scriptlets were sent.
- The champion's scriptlets go 0.06 s after the champion bundle that faces the target (a bundle re-creates the
  object and cuts an animation of the same moment; the earlier server's `champion_defer`):
  `[ics] champion_scriptlet_delay`.
- The HUD is shown again when the intro cinematic ends (the earlier server showed it after the intro).
- Sonic Shell (W): its missile is the entity a SpawnEntity node creates (not implemented yet); a missile with no
  class no longer stops the script.

## fase3-fu — ics: drones fight back, vehicles as server props, the tutorial's own scripts found (2026-10-21)

Pure reverse engineering, as the user chose (2026-10-21 17:40: "Solo ingeniería inversa").
- **Drones:** each unit runs its own attack script from its template (0x10000328; the tutorial drone 0x340004A1)
  and attacks the champion within `[ics] unit_aggro_radius` (8 m; when to attack is the only hand rule). Damage
  `unit_attack_damage` (10) until the units' attributes are read. Cast result 3 is signalled at the cast point.
- **Props:** bare world states of creation type 5 (vehicle, paddy wagons) get 0x50F = 6 (`static_creation_type`);
  the ranged drones (type 7) are units without client vitals.
- **The tutorial's scripts:** the layout records carry the encounter's own server scripts (conversations); decoded,
  not run yet. `tests/test_ics.py` 24 checks.

## fase3-fv — ics: fast start, respawn, quieter log (2026-10-21)

18:12 (tester): "still several things fail". server.log: the drones hit Batman (60 hits) until he died and stayed
dead; the encounter data took 69 s and slowed the whole load (objects at 40 %, units 15 s late); W raised an error.
- Champion placements are found from the match's champions only (reading all 44 champion templates opened dozens of
  packs); big packs (> 40 MB) use a fixed record window instead of scanning every record start; the preparation runs
  once even when the start-up thread and the queue ask together: 69 s -> 18 s, done at server start.
- The champion respawns at the start `[ics] respawn_seconds` (5) after dying; the units stop attacking him.
- Unknown script nodes are logged once per skill; a missile with no class (W: a spawned entity) is skipped.

## fase3-fw — ics: props in the layout's cell, neutral thugs (2026-10-21)

18:35 (tester): the map's elements (vehicles, doors, the Destroyer ...) still do not show; the human NPCs attack
Batman too; a video shows the intro cinematic with the enemies and props along the way (the client draws its own
cinematic actors, so it can draw them).
- Placement properties are read (`ics/rp.py`): side 0x100007A2, scale 0x6B3 / 0x6B4, linked templates 0x954.
- Props are sent with the layout's cell (0xFB) instead of 0; their scale goes with them.
- Units with no side (the thugs) are neutral: only enemies (side 1) attack the champion.
- `tests/test_ics.py` 25 checks.

## fase3-fx — ics: the cinematics' dialogue from their scene scripts (2026-10-21)

18:55 (tester): missing doors, the car, the Destroyer, the sphere that opens to show it, lightning, crates, holes,
the crater after the opening explosion, the meteors with a fire column and smoke. A video showed the intro
cinematic with the Destroyer and props (the client's own cinematic actors).
- Cinematic scenes (0x1D records) parsed from the data (`Data.scene`, `Data.cinematic_scenes`); when the server
  plays a cinematic it runs every scene's server script with its variables and raises its timeline events
  (`[ics] scene_fps` 30): the intro now plays its conversations (441, 559, 558, 557, 556).
- New nodes: StartConversation 0x100000D1, GetPlayer 0x10000187, GetAgent 0x10000188.
- Props, environment events (meteors, lightning, crater) and the Destroyer: under investigation.

## fase3-fy — ics: placed props, the tutorial's flow, all champions, the shop, progression (2026-10-21)

18:55-19:40 (tester): no doors, car, Destroyer, sphere, crates, holes, crater or meteors; "find everything: shop
items, inventory, buying, augments, map loading, every champion's skills, also the disabled ones". Five static
surveys (docs/re-notes/*.md, consolidated in master-plan.md) came first; this build implements their results.
- **Props are placed** (actor-creation-and-environment.md): the client places a network object only through its
  movement component (creation types 7 / 8) fed by the movement module. Every prop now gets the module and
  `0x50F` = 8 unless its world state is 7 / 8. `[ics] prop_movement_module`, `static_creation_type` (8; 6 = fase3-fx).
- **Scriptlet tables from the data** (`ics/rp.py script_tables`, `Data.scriptlets`): a 0x1D table's body has no DID;
  the bodies between two placed records come in list order. Each prop knows its keys (door: Object_Closed /
  Object_Open; wagon: Vfx_OnExplode; crater: Vfx_Spawn_Event01/02, Vfx_Active). After creation the props play
  `[ics] prop_initial_scriptlets` (Vfx_OnInit, Object_Closed: the door's light wall). Scriptlet names from table
  0x33000000 (`Data.scriptlet_names`). `[timing] prop_scriptlet_delay` 1.0.
- **Script VM:** node 0x10000010 is DestroyEntity (not Delay): plays _HFSM_DestroyEntityAction and removes the
  entity / ends the missile.
- **Units' stats from their stat block** (template 0x10000165): drones and thugs 200 health, the Destroyer 1500 /
  45 damage / 0.59 attacks a second. The ranged tutorial drone (no template) borrows the Trooper Drone's attack
  (`[ics] unit_attack_from`). `[ics] unit_stats`. A hostile unit that is hit fights back.
- **The tutorial's flow** (`ics/director.py`, `ics/encounters/tutorial1.py`, `[ics.encounters] director`): 31 steps
  from the intro cinematic to the victory: the objectives by index from table 0x48000D3F (sent as string-table
  references, no game text in the server), the conversations in the catalogue's order with their timed lengths, the
  four cinematics, waves of the layout's own units at the earlier server's positions, meteors played by the crater
  entity's own scriptlets, doors opened / closed with their scriptlets, levels and the "+" per step, the guide
  marker, the Destroyer, victory. `[ics] director_start` starts at a named step (testing).
- **Skill ranks:** the patched client's "+" (ping 0x2136 'RANK') ranks a skill; the champion has level, XP, skill
  points; `[ics] max_skill_ranks` (4/4/4/4/3, from the build records). Outside a flow kills give XP and levels
  (`xp_per_kill`, `xp_levels`, `level_cap` 20: the curve is not in the client).
- **Champion stats from its stats record** (0x100008E2): Gaslight Batman 455 health, 350 Will, 47 attack damage at
  level 1, growth per level, health / Will regeneration; sent as its stat properties. `[ics] champion_stats_from_data`,
  `send_stat_properties`. (The health was 600 from the config.)
- **All 54 champions, 156 variants:** `tools/roster.py` rebuilds data/champions.json from the champions' definition
  records (template 0x48000732): the 11 missing champions (Deadshot, Deathstroke, Nightwing, Raven, Zod ...) are in
  and 5 base variants that were stats records are fixed (Atomic Joker 0x40000962, Robin 0x4000052D ...). Catalog
  champions.tsv 54 rows, skills.tsv +66 rows. `[ics] roster_limit` (0 = all) in case 54 light packs are too many.
  Lobby pick 0x2102 SelectCharacter sets the match's champion (not where the encounter names one).
- **Stolen Powers:** D / F from the data (block 0x1000003F over the base power's, catalog 0x480003CD) in champion
  properties 0x100008F0 / 0x100008F1 and as kit slots 7 / 8 run by the VM. Tutorial: camera 0x48000808 + Super
  Strength 0x48000A3B (`[ics.encounters] stolen_powers`, `stolen_targeting`); elsewhere the champion's default pair.
- **The shop** (`ics/shop.py`): 0x208B buy / 0x20A7 sell validated as the client's own checks do; tier upgrades pay
  the difference and keep the slot; stats (add / percent), passive statuses and active skills (slots 10-15) applied;
  answers 0x20E2 inventory, 0x2086 handle (unlocks the shop), credits 0x1000035E. Recommended buys 0x2078 from the
  default loadout. Credits: `[ics] start_credits` 500, `credits_per_second` 2, `credits_per_kill` (not in the data),
  "+N" floaty 0x100004D6, `shop_anywhere`.
- **Respawn:** LifeState 2 while dead; notices 0x10000090 / 0x100000BC (dead panel countdown) `[ics] respawn_notices`.
- **Play menu from the data:** 0x2024 lists the master list 0x48000001's encounters whose map is installed (14:
  Metropolis Skyway and Apokolips Causeway are gone). `[ics] encounters_from_data`.
- Generic record reader `ics/records.py` (+ ASCII, vector and 8-byte DID kinds), `Data.record`, objectives,
  conversation lengths, artifacts, shop lists, loadouts, champion stats, encounter list.
- Tests: test_ics 27, test_director 17 (the whole tutorial flow), test_shop 16, test_scriptvm 13.

## fase3-fz — ics: paths on the navmesh, targetable enemies, fog, missing statics, no freezes (2026-10-21)

21:44-21:48 (tester, fase3-fy): no collisions (Batman walks through buildings), map elements and the fog of war
missing, some dialogue repeats, enemies cannot be targeted and do not attack, the drones are purple instead of red.
Two surveys: `docs/re-notes/targeting-and-relations.md`, `docs/re-notes/movement-collision-fog-map.md`.
- **Freezes:** the session froze 13 s when the meteor's crater spawned (its scriptlet tables were read from a 42 MB
  pack mid-match) and 3 s at the first drone: every move order arrived at once afterwards. The flow's classes
  (`ics.director.flow_classes`) are now prepared while queueing, and each pack's scriptlet tables are cached in
  `data/cache/` (35 s -> 11 s preparation from the second start).
- **Paths on the navmesh** (`ics/navmesh.py`): the client only snaps a click onto the Kynapse navmesh and sends the
  point; the original server pathed. The map pack's champion-sized NavMesh (0x900113CB in 0xA0C112CA: 17 cells, 175
  triangles) is rasterised into a 0.25 m grid; moves and chases follow A* paths with string pulling. `[ics] pathing`.
- **Targetable enemies:** the client's attack check (0x9d01d0) needs unit flags 0x1000019D, targetable 0x10000AA7 and
  0x100001C3; they are in the units' server-side templates only. Hostile units now carry them (from the template);
  the neutral thugs do not. `[ics] unit_target_properties`.
- **Team colour:** the client computes relation and colour from PVP_Team and then runs `_Entity_OnSetClientRelationship`
  on the entity; units also play it after creation (`[ics] unit_initial_scriptlets`). A quiet unit still fights a
  champion within `[ics] unit_close_aggro` (3 m).
- **Dialogue one at a time:** the director queues conversations (0x1AC came 0.5 s after the 11 s 0x19C).
  `[ics] conversation_gap` 0.4.
- **Fog of war:** the champion is a vision source (0x10000133 = `[ics] champion_vision_radius` 12); enemies out of
  sight (`fog_vision_radius` 14 m or a wall on the navmesh) are hidden with 0x90F, as the earlier server did.
- **Missing statics:** packs 0xA00000B3 and 0xA00000DF added to Tutorial 1's 0x20AF list (17 placements of
  0x2E0005D6 need .entity 0x2D0002E4, only in 0xA00000B3). `[ics.encounters] packs`.

## fase3-ga — ics: obstacles on the navmesh, the meteor's crater stays, the thug runs off, target diagnostic (2026-10-21)

22:50-22:55 (tester, fase3-fz): the drones are red now but still cannot be selected; the meteor falls and its
crater vanishes almost at once; the human does not run away; Batman walks through the first vehicle. The log shows
the drone attacking (unit_close_aggro) and the targeting properties sent; the client still never sends an attack.
- **Obstacles:** props with a footprint block paths on the navmesh (`NavGrid.block` / `unblock`, a copy per match):
  the street vehicle (4.0 x 1.6, the earlier server's box) until it is removed, the gates (7.0 x 0.5) while closed,
  the paddy wagons. `[ics] prop_blockers`.
- **Crater:** the rock / crater 0x2E000BB3 that `Vfx_Spawn_Event01` attaches goes with the next scriptlet; the flow
  now leaves its own 0x2E000BB3 on the impact spot (as the earlier server did).
- **Thug:** new director action `("walk", target, position)`; the human runs to (24, 64) when his drone is down and
  is removed a few seconds later. `[ics] flee_speed` 4.0.
- **Guide arrows** were sent toward a marker already removed: no longer.
- **Target diagnostic:** `python tools\diag.py --target` logs every check of the client's attack validator (VA
  0x9d01d0: relation, visibility, unit flags, targetable, 0x100001C3, alive...) and whether it ACCEPTED or REJECTED the
  entity under the cursor, to find why the drones are still refused.

## fase3-gb — ics: a skipped cinematic stops its dialogue (2026-10-21)

23:19-23:21 (tester): "Superman repeats conversations". server.log: the intro 0x35000026 was skipped after 3 s
(notice 0x10000117 state 4 at 23:20:07) but its scene script 0x3400058A went on (S1 -> S5 at 10, 17, 21, 26 s),
starting the intro's conversations during the game, over the director's lines.
- When the client reports a cinematic's end, its scene scripts stop (`World.stop_scenes`); a stopped script instance
  takes no more events or timers (`script_runtime.Instance.removed`).
- The `--target` diagnostic's log did not arrive (the logs folder was empty when read): to be run again.

## fase3-gc — ics: drones selectable (unit flags as a change) (2026-10-21)

23:28-23:30 (tester, `diag.py --target`): every right click on a drone ran the client's attack validator (VA
0x9d01d0) and stopped at "unit flags = 0" (2 956 times); only Batman (flags 0x8) passed. The unit component caches
0x1000019D at +0xa4 only when the property changes; sent in the creation table it never reached the cache.
- Hostile units get their template's targeting properties at creation and the unit flags 0x1000019D as a change
  `[ics] unit_flags_delay` (0.8 s) later. 0 = the fase3-ga behaviour.
- A full survey of the install was started (docs/re-notes: install inventory, script nodes, protocol, units and AI,
  maps, client scripts and UI, properties, account systems, cinematics / VFX / audio).

## anim-32 — the classes a kit creates are read at load (the first Q explosion)

Branch `ics/kit-fixes`, 2026-11-05.

### What the tester reported (game test 2026-11-04 16:12-16:14, anim-30 / 31)

- Blue Beetle: the Q exploded every time but the first. The first R showed the melee icons at once (closed; to reopen
  if it comes back).
- Superman: the first knockback was normal (closed).

### Found (C log)

- First cast: missile script 0x34000489 entered S1 (timer CollisionDelayTimer, then SpawnEntity 0x40000CD8) at
  16:12:51.015; the creation went at .084: the first SpawnEntity of the class read its data (world state, scriptlet
  tables, creation type) for 69 ms, the timer ran out meanwhile and Vfx_OnCollision went 1 ms after the creation.
  Later casts: creation at once, Vfx_OnCollision ~106 ms after (the script's delay). Earlier sessions' first casts
  showed the same 5 ms.

### What changed

- ics/prewarm.py, `[ics] prewarm_spawn_classes`: at a champion's creation, the entity classes its kit's scripts name
  (SpawnEntity, missiles) get the reads World.spawn makes (as Data.prepare does for an encounter's classes), and their
  own scripts (Data.entity_scripts) are walked too: Energy Cannon's missile 0x40000815 -> 0x34000489 -> 0x40000CD8.
  Blue Beetle's kit: 0.63 s at load; 0x40000CD8's reads then take ~0 s.

### Config keys

`prewarm_spawn_classes` (true).

### How to roll back

- `[ics] prewarm_spawn_classes = false`.

## anim-31 — diag --ranks no longer crashes the game

Branch `ics/kit-fixes`, 2026-11-04.

### What the tester reported (2026-11-04 16:06-16:08)

- The game closed while loading, twice, with `python tools\diag.py --ranks` attached.

### Found (C)

- diag.log: access violation at rva 0x18B360 / 0x18B35E, stack 0x21C9B6 <- ... <- 0x71F987 (cave E2) <- 0x524BCF
  (InqCanRankSkill), right after the "+" query. The --ranks breakpoint 0x71F97A was written for the first cave E;
  cave E2 (rewritten 2026-10-16, rva 0x71F968) has `cmp ecx, [ebp+0xc]` at 0x71F979-0x71F97B, so the breakpoint byte
  landed inside it and turned it into another instruction. The server was not involved.

### What changed

- tools/diag.py --ranks: that breakpoint moved to 0x71F987 (after cave E2's GetSkillRank call: eax = the rank,
  [ebp+0x10] = the slot). Every --ranks breakpoint checked against the patched exe: all at instruction starts; the
  default skill breakpoints lie outside the patched ranges or at their boundaries.

### How to roll back

- Nothing to roll back (a tool fix).

## anim-30 — spawned objects placed at once (the Q explosion); statuses read at load (the first knockback)

Branch `ics/kit-fixes`, 2026-11-04. Details: docs/reverse-engineering.md "The explosion's emitter, the first
knockback, the first R (anim-30)".

### What the tester reported (game test 2026-11-04 15:20-15:26, diag --particles)

- Blue Beetle: only the 14th and 15th of 16 Energy Cannons showed the explosion. The first R took about 5-6 s to show
  the melee icons.
- Superman: the Heat Vision at 15:25 pushed the bot "teleported"; the next one (15:26) was normal.

### Found

- Explosion (diag, C): the emitter 0x18000BDB started on the client in casts 1 and 2 (15:21:56, 15:22:04), which the
  tester did not see explode (the tracer's 100-line budget ended the log there). The client creates the emitter but it
  does not show. client-movement.md 0 (C): the client places a network object by its movement states and replays only
  states >= 0.1 s old; the explosion object got its Vfx_OnCollision 5-118 ms after its creation, before it was placed.
  The two shown casts got it 105 / 118 ms after.
- First knockback (C log): the knockback status script entered 0.13 s after the hit (15:25:48.684 -> .810; later
  casts 3 ms). Its first ApplySkill resolved the status's script in the packs (Data.status_script -> the record list of
  its pack: 2.2 s cold in a fresh process) on the game thread. The pushes themselves follow the script: to 6 m from
  Superman at 10 m/s, so 0.7 m in 0.07 s at 15:25:48 (the bot 5.3 m away) and 3.15 m in 0.35 s at 15:26:03.
- First R (C traffic): the melee tables went at 15:22:48.149-.173 and the redraw at .278, as in the later swaps; the
  melee icons are in pack 0xA0000202 with the ranged ones. The 5-6 s are on the client (to see with diag --ranks).

### What changed

- `[ics] spawn_state_backdate` (0.1): a standing spawned skill object's creation state is stamped 0.1 s earlier (the
  client's replay delay), so the client places it at once (World.bundle, CastWorld.spawn_entity). Project-wide (every
  skill's spawned objects): its own PR.
- `ics/prewarm.py` (new), `[ics] prewarm_statuses`: at a champion's creation (player and bots, the loading screen) the
  statuses its kit scripts apply (and those statuses' scripts, two levels) are resolved and their scripts read.
- tools/tracer.py: PARTICLES lines get a 3000-line budget.
- tests/test_kit_fixes.py 54/54 (2 new: Superman's knockback status resolved at his creation; the explosion object's
  creation state 0.1 s old).

### Config keys

`spawn_state_backdate` (0.1), `prewarm_statuses` (true).

### How to roll back

- `[ics] spawn_state_backdate = 0`, `prewarm_statuses = false`.

## anim-29 — the explosion experiment undone; forced movements logged; diag --particles

Branch `ics/kit-fixes`, 2026-11-04. Details: docs/reverse-engineering.md "The explosion after the linger, the first
knockback, the W indicator (anim-29)".

### What the tester reported (game tests 2026-11-04 02:40-02:47 and 03:12-03:15)

- Superman (02:41): the beam's middle shows every time; at the first E the bot was pushed so fast it looked like a
  teleport.
- Blue Beetle (03:13-03:15, anim-28): the Q exploded in none of 14 casts. The ranged W still shows the skill
  indicator while the (invisible) drone is out.

### Found

- Explosion: with the network removal 1.3 s after the collision (anim-28's linger) 0 of 14 showed; at 0.3 s 5 of 13
  had. The experiment made it worse; the emitter on the object does not show while the object stays.
- First knockback (02:41:21): the knockback status 0x340003F8 entered 0.12 s after the damage (21.706 -> 21.828;
  the second E: 3 ms), the moment the server started Gaslight Batman's graph runtime; the push lasted as long as the
  others (0.35 s vs 0.32 s). The motion states the client got are not in traffic.log: per-tick motion goes unlabelled.
- W indicator: at the launch (03:13:40.797, S1 -> S4) the slot 2 table went with targeting 0x1000003D = 5 (.800), the
  overlay 0x1000015A and the HUD redraw (.916); the client still showed the indicator on the second press.

### What changed

- The personal test sandbox (not in this branch) no longer sets `destroy_network_linger` (the key stays, {} by default).
- `[ics] log_forced_motion`: the per-tick motion of an entity in a forced movement (knockback, dash) is logged with a
  label (World.forced_motion_label; session tick, bot and object sends; World.delta). Same bytes.
- `tools/diag.py --particles`: a line for every scriptlet particle emitter the client starts (action type 0x11,
  execute 0x67F650), with words of the action.
- tests/test_kit_fixes.py 52/52 (1 new: the knockback's motion states get a label).

### Config keys

`log_forced_motion` (true).

### How to roll back

- `[ics] log_forced_motion = false`.

## anim-28 — the Q explosion's removal (sandbox experiment)

Branch `ics/kit-fixes`, 2026-11-04. Details: docs/reverse-engineering.md "Energy Cannon's explosion (anim-28)".

### What the tester reported (game test 2026-11-04 02:40-02:47, diag --graph)

- Superman's beam: not answered; traffic: all 7 beams lived until their stop 0x10000AC1 (0.2-0.5 s), the three with
  the next step close by now in one order with it (02:41:21.841, 56.059, 42:28.922).
- Blue Beetle: the Q exploded in casts 2, 5, 8, 11 and 12 of 13. The form swap problem did not come back.

### Found

- The 13 casts got the same messages in the same order and timings (spawn -> Vfx_OnCollision 110-128 ms ->
  removal 300-306 ms); the diag shows the client starting Vfx_OnCollision on the explosion object and the missile in
  the shown and the missing ones; the explosion objects stood on the navmesh, five at the same spot with both
  results.
- Data (C): the explosion object 0x40000CD8's only table 0x1D0008DE holds one key, Vfx_OnCollision: one action, type
  0x11 (particle emitter attached to the object) 0x18000BDB, floats 40 / 60, probability 1.0. The particle record has
  6 emitters with times of 0.05-0.5 s. The missile's Vfx_OnCollision (table 0x1D0005C8) only stops its own trail
  Vfx_OnInit 0x10000078 (type 0x17) after 0.06 s. So the explosion is the emitter on 0x40000CD8, and ics removes that
  object (0x3) 0.3 s after it starts (the script's DestroyEntity [0.3, 0]).

### What changed

- `[ics] destroy_network_linger` ({class: s}, default {}): a skill object of that class leaves the server's world at
  the script's DestroyEntity time, its network removal (0x3) s later. The personal test sandbox (not in this branch) set {"0x40000CD8": 1.0}
  (experiment, P): if the explosion then always shows, the early removal is the cause.
- tests/test_kit_fixes.py 51/51 (1 new: the explosion object leaves the server at the script's time, the client 1 s
  later).

### Config keys

`destroy_network_linger` ({}).

### How to roll back

- `[ics.destroy_network_linger] "0x40000CD8" = 0` (only if set).

## anim-27 — quiet messages no longer split a champion's moment (Superman's beam)

Branch `ics/kit-fixes`, 2026-11-04. Details: docs/reverse-engineering.md "The beam's middle, the lost form swap, the
explosion's flag (anim-27)".

### What the tester reported (game test 2026-11-04 01:53-01:59, anim-26)

- Basic attack: the shot leaves earlier and the swing looks natural; he does not walk during the swing. The eyes'
  laser and the basic attack's streak go away by themselves again. No skill animation cut without the delay.
- Superman: sometimes the beam between him and the target is missing (eyes and target end shown); once this test.
- Blue Beetle: the Q explosion showed once (01:59:27.409). At 01:58:52.375 R from ranged to melee left the ranged
  skills.

### Found

- Beam: Vfx_Sup_Heat_Vision_Active 0x10000ABE (Heat Vision S3, a RunScriptlet on Superman) and the next step's orders
  (0x100001E3, 0x10000AB7, 0x10000AB9) ran in one moment but went as two 0x8D, 8-11 ms apart (01:53:33.597, 54.208,
  54:58.731, 56:05.662): the target's and Superman's vitals (0x42), a modifier (0x20F0) and status icons sent in
  between flushed the waiting orders; the second 0x8D ended the beam. The other casts kept it until its stop
  0x10000AC1 ~0.4 s later.
- Form swap: R at 01:58:37.765 went to melee on the server (S1 -> S2, slot tables and redraw sent, To_Melee 0x10000BD7
  and the graph event in one order at .771), 1.1 s after a Q with the passive on; at .850 the passive's form restart
  went in an 0x8D of its own. The next R (52.375) went melee -> ranged, so the client probably never took the 37.77
  swap's graph event (Infiltraitor_Activate); to confirm with diag --graph.
- Q explosion: the shown one (01:59:27.964) and the missing ones have the same timings (collision 110 ms after the
  explosion object's spawn, removed 300 ms later); only the run numbers' size differs.
- DestroyEntity's client half (0x9B56D0, C): plays _HFSM_DestroyEntityAction 0x100001E0, posts the removal event 0xFA
  after the node's delay (0x445840), plays _HFSM_DestroyEntityAction_Optional 0x10001128; its flag (+0x28) = 1 also
  raises event 0x100000A1 {destroyed IID} on the creator's script (0x991F60 / 0x96DE90). Not used by ics.

### What changed

- `ics/scriptlet_orders.py`: vitals, modifiers, status icons and cooldowns (0x42, 0x20F0, 0x20E8, 0x20C8, 0x20D0,
  0x2127, 0x20E9, 0x20F8) no longer send a champion's waiting orders; any other message still does (the order on the
  wire between objects kept).
- tests/test_kit_fixes.py 50/50 (1 new: a vitals message between two scriptlets leaves one 0x8D).

### Config keys

`scriptlet_orders_quiet_messages` (true).

### How to roll back

- `[ics] scriptlet_orders_quiet_messages = false`.

## anim-26 — 0x8D again; the sandbox without the champion scriptlet delay

Branch `ics/kit-fixes`, 2026-11-04. Details: docs/reverse-engineering.md "0x2073 tried; the champion scriptlet delay
(anim-26)".

### What the tester reported (game test 2026-11-04 01:28-01:32, anim-25)

- Superman: still no punch sound, and now the heat vision eyes stay on for good.
- Blue Beetle: no Q explosion, no wing glow. Both champions keep the basic attack's streak effect all the time,
  even walking.
- Basic attack: he turns to a target behind him (the tester thought it did before); a move ordered right after the
  attack starts does not wait for the swing. The tester's idea: the delays added for the animations make the shot
  late and the exit from the attack late (a domino).

### Found

- With 0x2073 nothing ended the scripts' runs early, and nothing ended them at all: the basic attacks' RunScriptlet
  runs (streaks) and the eyes' StartScriptlet run lived on. The eyes' stop went right (0x11F, key 0x10000B94, run
  23, 01:29:12.183), but 0x11F reaches 0x52D790 with x = 0: a soft stop (signal 0xFFFFFF01), while the 0x8D's
  stop-all passes x = 1, the immediate end 0x529EF0. The punch sound, the explosion and the glow did not come back
  either, so the early ends were not their cause.
- The move at 01:31:31.534 was held until the swing state's exit (31.565, +31 ms): the attack state of the graph ends
  at the shot; the rest of the clip is the Cosmetic tail, which the graph's own onCosmeticEarlyOut ends on movement.
- The delay: the basic attack was decided at 01:31:31.111 (S1: cooldown, FaceTarget, scriptlets) and its graph event
  left at .251, champion_scriptlet_delay (0.13 s) + a scheduler tick. The cooldown counts from S1; the graph (shot,
  swing end) from the send. The value has no source in the game: it was set 2026-10-21 because "a champion bundle
  re-creates the object and cuts an animation"; object-update-bundles.md (C, 2026-10-28) found a bundle re-creates
  nothing.

### What changed

- `[ics] scriptlet_orders_event` back to "0x8D" (anim-23 / 24 behaviour).
- (Personal test sandbox only, not in this branch: `champion_scriptlet_delay` 0 for its match, P,
  experiment): the champion's scriptlets go when the script runs them. Tutorial 1 and every other match keep 0.13.

### Config keys

`[ics] scriptlet_orders_event` ("0x8D").

### How to roll back

- `[ics] scriptlet_orders_event = "0x2073"` = the anim-25 trial.

## anim-25 — the scripts' scriptlets go additively (0x2073); the basic attack turns and holds the move

Branch `ics/kit-fixes`, 2026-11-04. Details: docs/reverse-engineering.md "0x2073 confirmed; the basic attack's facing
and swing (anim-25)".

### What the tester reported (game test 2026-11-04 00:48-00:56, diag --orders)

- Match 1: the buttons change at once after R; the ranged W starts the passive when launched and when detonated.
- Match 2 (config changed): no punch sound, no Q explosion, no wing glow, nothing stuck; no difference seen.
- He can basic-attack at range with his back to the target, and walk a little before the attack's animation ends.

### Found

- The experiment never ran: `scriptlet_orders_event` was written under a commented `#[ics]`, so TOML put it in
  `[match.maps."0x40000B6A".lobby.bot]`; traffic has no 0x2073. diag --orders (all three logs): every 0x8D list on
  the champion and the bots shows object +0x110 = 0 and 0x1B759EC = 0, so 0x2073's direct path applies (C).
- Facing: the basic attack scripts face the target themselves (Blue Beetle 0x34000457 S1: `FaceTarget($TargetIID)
  [1 0 0.15]`, released at S2's exit). World._attack_step set the heading on the server first, so that FaceTarget saw
  no turn (face_min_turn_degrees) and nothing reached the client.
- Walking: move orders during the swing were taken at once (00:50:19.795 / .936, between the attack's start hook
  19.676 and its fire 19.975); the champion slid while the swing played and the shot still went. The graph data:
  the attack states (Ranged_Basic_Left 104 / _Right 115, Basic_Attack_Melee 116) have no Lua early-out on
  movement; their Cosmetic tails do (onCosmeticEarlyOut).

### What changed

- `[ics] scriptlet_orders_event` = "0x2073" (default): a champion's scriptlets from script nodes (RunScriptlet /
  StartScriptlet / RunFx / RaiseGraphEvent, the runs the original's client copy would start) go as 0x2073: no
  stop-all, nothing ends them early, no ride-along. The server's own orders (falls, get-ups, carries, signal stops)
  keep 0x8D, with the held runs riding along after it.
- `[ics] attack_face_by_script`: a champion's attack step no longer turns him on the server first; the script's
  FaceTarget turns him and sends it.
- `[ics] basic_attack_holds_movement` (P): a move ordered while the graph is in the basic attack's state waits for
  its exit (code 2), then runs; the Cosmetic tail stays free.
- config.toml: the misplaced line removed (no `[ics]` table is needed now).
- tests/test_kit_fixes.py 49/49 (3 new: the turn to a target behind, the move held during the swing, run after it;
  the passive's checks for 0x2073); tests/test_match.py: the S4/S5 label check accepts 0x2073 (604/608, the base's 4).

### Config keys

`scriptlet_orders_event` ("0x2073"), `attack_face_by_script` (true), `basic_attack_holds_movement` (true).

### How to roll back

- `[ics] scriptlet_orders_event = "0x8D"`, `attack_face_by_script = false`, `basic_attack_holds_movement = false`.

## anim-24 — one button redraw per form swap; "skill used" on every taken use; diag --orders; 0x2073 experiment

Branch `ics/kit-fixes`, 2026-11-03. Details: docs/reverse-engineering.md "Button redraws, skill used, the punch sound
and 0x2073 (anim-24)".

### What the tester reported (game test 2026-11-03 23:21-23:27)

- Superman: the punch sound still missing.
- Blue Beetle: the passive's particles and yellow blaster last the whole buff and go at its end; no blink during basic
  attacks; the melee Q starts the passive; the blaster left floating after a form swap is gone. The Q's explosion no
  longer shows at all. His melee form lacks a glowing blue part of the wings (original screenshot vs ours). In the
  original the ranged W also starts the passive, when launched or when detonated. After R the other buttons still
  change only ~2-3 s later in both forms; once (melee -> ranged with the passive started by R) at once.

### Found

- Buttons (C traffic): a swap refreshes six slot tables in a few steps over ~0.12 s (23:26:54.666-.785); each toggled
  the rank property 0x100006C1 (anim-19), six toggles brought it back, and the HUD's check (code cave D, every frame)
  saw no change: the redraw came with R's own "ready" (0x20F8, 3 s). The swap at 23:26:44.429 also sent the passive's
  overlay notice 0x1000015A, which the skill bar (Skill.UpdateSkillUIOverlay) redraws on.
- W: Scarab Scanner 0x34000454 calls SkillEcho only at the launch (S4); the detonation (S4 -> S3 on 0x1000001D) has
  none. At 23:24:29 the passive was in its cooldown (bonus hit 23:24:22.348, ready 23:24:34.413).
- Punch sound (C traffic + graph data): the punch is the graph's HeatVision_Finisher_End clip after
  HeatVision_Loop_to_End (S8's event, 0x100003CA); Vfx_Sup_Heat_Vision_Dash_Stop 0x10000B25 went with it at
  23:22:12.170 and the basic attack's order at 12.420 ended it (every 0x8D ends the server's runs, anim-23).
- Q explosion: the missile's Vfx_OnCollision (23:23:56.430) was followed 7 ms later by its Vfx_OnInit
  (spawned_effect_scriptlets, P, 0.1 s after creation) in an order of its own; the explosion object 0x40000CD8 is
  removed 0.3 s later by the script's DestroyEntity [0.3, 0]. Open.
- Wings: Vfx_Blu_Infiltrator_To_Melee 0x10000BD7 / _To_Ranged 0x10000BD9 entries name 0x19000D86 with
  0x100000E3 / 0x100000E6 / 0x100000E2 (P: appearance parts); ending To_Melee's run early may take the glowing part.
- skill-animations-and-skins.md 3.1 (P): the original most probably ran the champions' skill scripts as client copies,
  whose RunScriptlet / StartScriptlet go through the client's local path, which no 0x8D ends.

### What changed

- `ics/skill_slots.py`: one rank-property toggle when the slot tables stop changing (`slot_table_hud_refresh_delay`
  0.1 s after the last one, P), in an update of its own.
- "Skill used" 0x10000196 at every taken activation again (as before anim-22); SkillEcho raises it only when the
  use's activation did not (no double count; the W's detonation now counts).
- `ics/scriptlet_orders.py`: `[ics] scriptlet_orders_event` ("0x8D"; "0x2073" = experiment: a champion's orders with
  the additive start, no ride-along); signal orders pass as they are.
- `tools/diag.py --orders`: at every 0x8D list (0x627E20) the object's IID, its +0x110 and the global 0x1B759EC; at
  0x2073 (0xA883F0) the same, and which branch it took.
- tests/test_kit_fixes.py: 3 checks (one toggle after the swap, the W's launch and detonation raise "skill used"
  once each); 46/46.

### Config keys

`slot_table_hud_refresh_once` (true), `slot_table_hud_refresh_delay` (0.1), `skill_used_every_use` (true),
`scriptlet_orders_event` ("0x8D").

### How to roll back

- `[ics] slot_table_hud_refresh_once = false`, `skill_used_every_use = false`; `scriptlet_orders_event = "0x8D"`.

## anim-23 — every 0x8D replaces: one order per champion and moment, held runs ride along, stops by 0x11F

Branch `ics/kit-fixes`, 2026-11-03. Details: docs/reverse-engineering.md "Every 0x8D replaces the server's runs".

### What the tester reported (game test 2026-11-03 22:14-22:21)

- Superman: walks right after the punch (fixed in anim-22); the punch sound still missing.
- Blue Beetle: in ranged form the passive's yellow particles are gone completely (the tester: the particles taken for
  E's were the passive's); the melee Q did not apply the passive; the ranged blaster turned yellow with the passive but
  stayed yellow after the buff until he fired at the enemy again, with some blinks. The tester asked whether it is
  the Green Arrow quiver problem of anim-09.

### Found (C, client disassembly)

- **Every 0x8D order first stops every run an earlier network order started on the object**: the list handler
  0x627E20 calls 0x57CB60 at 0x627E4D with a filter (vtable 0x15C9750, method 0x6272D0 = the run's context byte +0x60,
  which 0x6279D0 sets on network runs); each picked run goes 0x57C4B0 -> 0x57B920 -> 0x52D790. Only then are the
  order's entries started. anim-09 found this for Green Arrow's quiver (same answer: yes, the same problem);
  docs/re-notes/client-scriptlets-graphs.md 1.4 said the opposite.
- So the passive's loop Vfx_Blu_Rdirective_Disruption_Active (0x10000BC3, 22:16:44.474) died 0 ms later at the next
  order to him (the Energy Cannon's stop); and its "stop" at the buff's end (22:19:50.770, an 0x8D entry with signal 1
  for a run already dead) started it again: the yellow blaster until the next shot's order. The punch
  Vfx_Sup_Heat_Vision_Dash_Stop (0x10000B25, 22:15:11.802) was cut by the graph event sent 1 ms after it in an order of
  its own.
- Event 0x11F stops one run (0x57C4B0) and nothing else; the client's own StopScriptlet 0x588A80 passes mode 1.
- Event 0x2073 (0xA883F0 -> 0xA22DA0) starts entries without the stop-all and skips live runs, but only directly when
  the object's +0x110 equals the "none" DID global 0x1B759EC; otherwise it goes to a per-IID list of another manager
  (0xA12D50). Not used: to confirm with diag.

### What changed

- `ics/scriptlet_orders.py` (new; one hook in World.__init__, one in StartScriptlet, one in signal_scriptlet):
  - consecutive 0x8D messages to one champion (until another message goes out or the scheduler step ends) go as ONE
    order; the order of the other messages is kept, a lone order goes out byte for byte as before;
  - a StartScriptlet run (a script handle keeps it) is held and rides along, with its run number and variables, after
    the new entries of every later order to that champion until its stop (P: the original server's policy is not
    known; the client restarts it there, a short blink as anim-09's effect set);
  - a script's StopScriptlet goes as event 0x11F (key, run, mode 1) instead of an 0x8D signal (C).
  - Scope: champions (local and bots); Tutorial 1 (0x40000991) is left as before.
- Blue Beetle's melee Q at 22:17:54.886: the passive was in its cooldown, which starts when the buff ends (S3,
  `StartCooldown` after the 6 s buff at 22:17:51.077), so 6 + 12 s from the trigger. As the script says; no change.
- tests/test_match.py: the death checks read every entry of an order (entry_run), count only the death overlay's
  0x11F, and run the moment's due orders before reading "at once" (608/608).
- tests/test_kit_fixes.py: 5 checks (burst + loop in one order, the loop rides along, 0x11F at the buff's end, no loop
  after it, no 0x8D signal stops).

### Config keys

`scriptlet_orders` (true), `scriptlet_orders_skip_encounters` (["0x40000991"]), `scriptlet_orders_scope`
("champions"; "all" = every object, units and props: a project-wide change for its own PR).

### How to roll back

- `[ics] scriptlet_orders = false` (one order per scriptlet and 0x8D signal stops, as anim-22).

## anim-22 — the punch no longer holds Superman; SkillEcho is the "skill used" notice

Branch `ics/kit-fixes`, 2026-11-03.

### What the tester reported (game test 2026-11-03 16:07-16:12, diag --graph)

- Superman: no beacon on the E target nor on the R (Superman and target); no punch sound; after the punch Superman
  stands about 2 s and does not walk.
- Blue Beetle: E effects of the other form stay after the swap to ranged (not to melee); the passive "does not
  trigger"; Q exploded visually on casts 3 and 4, not on 2, 5 and 6 (1 without a target); back to ranged the buttons
  wait for R's cooldown.

### What changed

- **The punch's cast ends with its state**: the cast anim-20's graph_done_waits starts for Heat Vision's S8 kept
  `casting = 1` after the timed fallback (16:09:02.176) and cast_holds_movement held Superman; leaving the state now
  ends that cast. Headless: casting 0 within 0.3 s of the punch.
- **SkillEcho 0x10000195** (P): called by 221 skill scripts right after their cast point; it now raises "skill used"
  0x10000196 {Slot} on the owner's scripts (Blue Beetle's passive 0x34000456 reads Slot, hash 0x5A364). The activation's
  broadcast (ics, kit-audit-2) stays for scripts without the node.

### Answers and findings without a change

- The beacon: sent as the script says (Heat Vision S3's exit `StartScriptlet($TargetIID)[0x10000223, fx 0x1E0003F5]`,
  16:08:59.655, its own run, stopped by S2 at 16:09:02.257). Not drawn by the client: to find on the client (what this
  fx record needs) before a change.
- The passive: it ran on the server (16:10:26, 16:10:52, 16:11:11); the melee E and W at 16:11:08 / 09 fell in its 12 s
  cooldown (stat 15 = 12 at rank 1) after the 10:52 buff.
- Q's explosion: the five area objects 0x40000CD8 all got their 0x10000016 on the client (diag); timing (5 / 110 ms)
  does not separate the shown from the missing ones. Open.

### Config keys

`skill_echo_node` (true).

### How to roll back

- `[ics] skill_echo_node = false`; the punch's cast end has no key of its own (`graph_done_waits = false`, anim-20).

## anim-21 — a scriptlet handle stops its own run (Superman's beacon and punch sound, Blue Beetle's form effects)

Branch `ics/kit-fixes`, 2026-11-03. Details: docs/reverse-engineering.md "Scriptlet handles and runs; the graph takes
Blue Beetle's form events".

### What the tester reported (game test 2026-11-03 15:26-15:35, diag --graph)

- Superman: the knockback direction (ok) and the punch animation (ok). The flight sound comes a little late, the punch
  sound is missing, and the purple circular "beacon" on the target marked for the punch is missing (on the R: on
  Superman and on the target).
- Blue Beetle: E's shots fly and hit (ok), but look round (the original's are flatter, wider sideways); Q's explosion
  still only sometimes; the other form's E effects still stay after R; the icons still change only when R's cooldown
  ends.

### What changed

- **A scriptlet handle stops its own run**: StartScriptlet's handle now keeps its run, and StopScriptlet(handle) stops
  that run. ics stopped the key's newest run on the entity: Heat Vision's `StopScriptlet($TargetIID,
  $ActiveScriptHandle)` stopped the target's newest 0x10000223 run (a hit, 0x16) and left the laser's run 0x14 on;
  the next stop (the beacon's handle) could take the punch impact's run. The beacon is Heat Vision's own
  `StartScriptlet($TargetIID)[0x10000223, fx 0x1E0003F5]` (S3's exit, held until S4 / S6 / S2 stops it); the R's are
  `StartScriptlet(SELF)[0x10000AC7, target]` and `StartScriptlet($TargetIID)[0x10000223, fx 0x1E00038B]`: the
  tester's description matches the scripts. Headless: the laser's stop hits its run, the beacon stays its 2.5 s window.

### Answers and findings without a change

- The diag (`--graph`, 15:33:15 / 15:33:30): Blue Beetle's graph takes Infiltraitor_Activate 0x10000405 (index 0x54)
  and _Deactivate 0x10000407 (0x55); the ToMelee scriptlet 0x10000BD7 raises 0x10000405 itself too. So the blasters
  are not a lost graph event; what hides them is open.
- The flight sound's delay: the champion's scriptlets leave `champion_scriptlet_delay` (0.13 s, an ics value with no
  source in the data, CLAUDE.local Pending 15) after the script runs them.
- Q's explosion: in the traffic the area object 0x40000CD8 gets its 0x10000016 either about 5 ms or about 110 ms after
  its creation; the diag of this run started after the Q. To confirm with the client (diag) before a change.
- The E shots' shape and the late icons: open (no node in the scripts names a scale; what redraws the buttons is not
  known).

### Config keys (ics/config.py `[ics]`)

`scriptlet_handle_runs` (true).

### How to roll back

- `[ics] scriptlet_handle_runs = false`.

## anim-20 — knockback direction, the punch waits for its animation, Blue Beetle's E shots hit, form effects stop

Branch `ics/kit-fixes`, 2026-11-03. Details: docs/reverse-engineering.md "Knockback heading, own-animation waits,
spawned objects' first events, deferred stops".

### What the tester reported (game test 2026-11-03 14:39-14:56, Coast City sandbox)

- Blue Beetle: E hops backwards (ok) and plays the shot animation, but no shot leaves; once it played the shots with
  nobody in reach (14:43:42.926). Per-form cooldowns ok, melee reach ok. The icons still change late (back to melee:
  only when R's cooldown ends); the blasters stay in melee; the E effects of a form sometimes stay after R.
- Superman: W text gone from the bots (ok). E's second press: still no punch animation; the knockback goes a wrong
  way (the original pushes the target on, away from Superman).

### What changed

- **Knockback direction** (P): the "with heading" expression 0x41 given a vector takes its direction. The knockback
  status 0x340003F8 overwrites KnockbackHeading with Offset(source, target) before it; ics read the vector as 0 degrees,
  so every target went +x. Now along the line from Superman (headless: 0 / 45 / 90 / 135 degrees).
- **A state waits for its own animation**: Heat Vision's S8 raises the finisher's graph event and waits for
  OnCastSignal 2; ics gave it the chain's own result (also 2) one ms after entering (14:40:52.643), so the queued basic
  attack's 0x10000128 replaced the finisher. Such a state now waits for the graph's code 2 (the animation's end), as a
  cast does. The queued attack also waits while the champion's graph is in a state a slot skill hooks.
- **Blue Beetle's E shots**: each shot 0x400008C4 (script 0x340004AA) went S0 -> S5 -> S3 on its creation event and
  destroyed itself in S3 (its TargetIID still unset) 77 ms later, before the LaunchMissile of the same chain gave the
  target (14:43:43.048 / .125). The creation event of a script-spawned object now comes after the spawning chain and
  the launch gives the target first (P: the client evaluates once per update). Its damage read the E's stats with slot
  "-1" in an object with no slot (0 damage): a skill's spawned object takes the spawning skill's slot (P). Headless: 4
  hits of 21.6 on a bot behind him.
- **Form effects stop**: a deferred stop of the local champion's scriptlet took the run to stop at the send, so when
  Blue Beetle's passive 0x34000456 stopped and restarted 0x10000BC6 in one instant (14:42:50.380) the stop took the new
  run and the buff's end (56.231) had nothing to stop; the run is now taken at the call.

### Answers and findings without a change

- The shots "with nobody in reach": the shot search is the script's box from Blue Beetle back along his facing,
  travelled distance + TargetRadius 5.75 long and 2 x 5.75 = 11.5 m wide; minions in it count (kinds 0x10108).
- The late icons: the slot tables reach the client at once (14:42:50.197); what redraws the buttons is not known (the
  rank toggle of anim-19 does not). To find with `tools\diag.py` before a change (CLAUDE.local Pending).
- The blasters: the R raises the graph events Infiltraitor_Activate / _Deactivate (0x10000405 / 0x10000407) and they are
  sent; whether the champion's graph takes them (`tools\diag.py --graph`) is to check before a change.

### Config keys (ics/config.py `[ics]`)

`heading_from_vector` (P), `graph_done_waits`, `queued_attack_waits_graph`, `spawn_event_after_chain` (P),
`spawned_entity_skill_slot` (P), `stop_takes_run_at_call` (all true).

### Tests

- `tests/test_kit_fixes.py`: 37 checks (new: the knockback at 45 degrees, S8 waits for the finisher's hook, the E shots
  hit).

### How to roll back

- `[ics] heading_from_vector = false`, `graph_done_waits = false`, `queued_attack_waits_graph = false`,
  `spawn_event_after_chain = false`, `spawned_entity_skill_slot = false`, `stop_takes_run_at_call = false`.

## anim-19 — local frames, per-form cooldowns, the facing in the champion bundle, queued attacks wait (game test of anim-18)

Branch `ics/kit-fixes`, 2026-11-03. Details: docs/reverse-engineering.md "Local frames, per-form cooldowns, the champion
bundle's facing, The Punch Line's needs".

### What the tester reported (game test 2026-11-03 00:29-00:40, Coast City sandbox)

- Superman: W roots (ok), but "Slow" then "Root" show over the bot; in the original the CC texts show only over the
  player's own champion. E pushes (ok); the second E dashes and punches with no punch animation, and once the bot the
  dash touched took the punch.
- Arcane Green Lantern: Q's teleport on the key press and the indicator: ok.
- Blue Beetle: ranged Q's area effect only sometimes; E still faces the dash and fires nothing; W's scarab not shown and
  the indicator shows on the second press (the detonation works); R's icons change late (when the slot's cooldown
  ends), the forms share their Q / W / E cooldowns, the melee basic attack keeps the ranged reach.
- Atomic Joker: R stops (ok). The Punch Line starts, but health stays at 1, the death camera comes at once, he cannot
  move and the head has no splash; the original: health 0, the HUD 1/1 and 8/8 jumps, a yellow counter bar, the head
  gone at 0 jumps, then the champion's 0 health and its Will.

### What changed

- **The facing in the champion bundle**: `Session._objects` built the local champion's bundle without `facing_offset`,
  so anim-18's facing lock never reached the client (`ics/session.py`, one argument). Blue Beetle's E should now hop
  backwards in game.
- **Local frames** (VM): a name used in two local frames (operand source 3, 4, 5 ...) is two variables. Heat Vision
  0x340003D6 keeps its target in graph S1's TargetIID and what the dash collides with in graph S7's own TargetIID; ics
  kept one variable per name, so a bot the dash touched took the punch (00:32:34.158, Swamp Thing). 95 scripts have such
  names.
- **Queued attacks wait for the cast**: QueueOrder 0x100000DB (the punch's "attack the target after") started a basic
  attack 30 ms after the finisher's graph event (00:32:34.295 / .324) and cut it; the attack a skill queues now waits
  while one of the champion's skills is in its cast (its animation's end hook), at most `queued_attack_lock_wait` 2 s
  (ours, a safety), as the client buffers orders during an action (full-combat-skills.md 1.4, C). Not the action lock
  itself: ics can leave one held (Wonder Woman's Q 0x34000185 stays in S6 waiting for a cast end; open).
- **Per-form cooldowns**: the owner block's f64 at 0x20 + 8 x slot is that slot's cooldown end (read by Blue Beetle's
  Q / W / E 0x34000451 / 454 / 455 at 0x28 / 0x30 / 0x38, written by no script); StartCooldown with an explicit slot puts
  a remaining time on that slot, 0 = ready (each form's saved cooldown in 0xD0 / 0xD8 / 0xE0 comes back on the swap).
- **The melee basic reach**: Blue Beetle's basic attack 0x34000457 sets its range with SetSkillStatOverride(IntendedRange)
  [-1, 18] at each re-init (stat 17 = 1 m melee, 18 = 5.25 m ranged); the attack step now reads that override.
- **Buttons redrawn at once** (P): a slot table change also toggles the rank property the HUD re-reads.
- **CC texts only over the player's champion**: the 0x20BD floaty (an ics addition: no script sends it) goes for the
  local champion only, as the tester remembers the original.

### Answers and findings without a change

- "Slow" then "Root": Frost Breath 0x340000F7 applies the slow to every target in the cone and then, inside RootRange,
  the root: the original's order. Over the player's own champion both texts show, in that order.
- The interception of Superman's E: not the original (the script's punch target is graph S1's); fixed above.
- Blue Beetle's Q: both casts exploded on the server (0x34000489 S1 -> S7) and the area object 0x40000CD8 was created
  both times; in the first its explosion scriptlet left 5 ms after the object (00:34:17.169 / .174), in the second 110
  ms. P: a scriptlet that early is lost; not changed until confirmed.
- Blue Beetle's W scarab: the spawned 0x400008BF is a bare class object (as AGL's crater), not drawn; the second press
  was already a key press (no point in its 0x20EE); the indicator on it is open.
- The Punch Line (0x340004DE) needs, before it can work: the HealthLock attribute 0x10000786 and "not attackable"
  0x10000249 its S2 sets (ics honours neither, so the next turret shot killed him); SpendCost(-100 % of health) (health 0
  on purpose); node 0x100000A1 (HeadIID, SELF), a server-only node (no client half) that hands the player's control and
  HUD to the spawned head 0x40000A68 (its 1/1 health and 8 jumps). The last one needs reverse engineering of how the
  server switches the controlled agent: its own task (CLAUDE.local Pending).

### Config keys (ics/config.py `[ics]`)

`local_frames`, `attack_waits_for_action_lock`, `queued_attack_lock_wait` (2.0, ours), `slot_cooldown_vars`,
`attack_range_override`, `slot_table_hud_refresh`, `cc_floaty_local_only` (all true).

### Tests

- `tests/test_kit_fixes.py`: 34 checks (new: the two TargetIID frames of Heat Vision, Blue Beetle's per-form Q cooldown,
  the melee reach override, the ranged Q's remaining cooldown back after the swap).
- `tools/champion_check.py --vs-champion --window 5` against anim-18: 13 slots changed, mostly the damage on the bot
  (Deathstroke W now hits; Atomic Green Lantern W / E / R fewer statuses; Wonder Woman W lost the hit of a basic attack
  her Q had queued, now held by that Q's cast). Battery: test_ics 40/40, test_session_flow 91/91, test_match 604/608 (the
  base's 4 Super Strength watchdog checks), test_meltdown 77/77, test_director 43/43, test_scriptvm 78/78, test_graph 34,
  script_coverage clean.

### How to roll back

- `[ics] local_frames = false`, `attack_waits_for_action_lock = false`, `slot_cooldown_vars = false`,
  `attack_range_override = false`, `slot_table_hud_refresh = false`, `cc_floaty_local_only = false`.
- The champion bundle's facing has no key: `[ics] facing_locks = false` (anim-18) removes the offset it carries.

## anim-18 — skill buttons, facing locks, left sub-graphs, status record flags (Superman, AGL, Blue Beetle, Atomic Joker)

Branch `ics/kit-fixes`, 2026-11-02 (game-tested in a personal Coast City sandbox, not part of this branch). Numbering: the anim-NN series after anim-17;
to be renamed if it goes to a PR. Details: docs/reverse-engineering.md "Skill buttons, facing locks, left sub-graphs,
status record flags".

### What the tester reported (game test 2026-11-02 01:39-02:20, Coast City sandbox)

- Superman: Q sometimes does not empower the hit; W roots nobody in the inner cone and shows no ice; E casts out of
  range, does not push the enemy, and its second part (E again, no click) never runs.
- Arcane Green Lantern: Q cannot teleport and its indicator stays; W does nothing (expected); E's effect only sometimes;
  R ok without the passive's visual.
- Blue Beetle: Q's area effect sometimes missing; W's sentinel scarab not shown and its detonation needs a click; E still
  faces the dash; R leaves the ranged buttons (melee basic range, Q stands still, E only glowing hands) and the blasters.
- Atomic Joker: the passive does not start at death; W's banana glides and keeps spinning, nobody trips; R never stops
  hitting and has no effects. A delay before casts (AGL's Q, Atomic Joker's Q).

### What changed

- **Skill buttons** (`ics/skill_slots.py`, new): SetSkillStatOverride 0x100000FA (name, description, icon, targeting
  type) and SetSlotSkill 0x10000089 now change the local champion's slot table (0x100008E3 / E8 / EA / EC / E6) that the
  HUD reads; ClearSkillStatOverride puts it back. AGL's Q teleport, Superman's E punch and Blue Beetle's W detonation
  are a key press (targeting 5) in their windows; Blue Beetle's Infiltrator Mode shows the melee Q / W / E (icons,
  targeting, range of the swapped records). Field 14 = targeting is P (it only takes valid targeting types).
- **Facing locks**: FaceTarget with an out handle holds the champion's facing until ReleaseFacing 0x10000057 (was a
  no-op); while moving only the model turns. Blue Beetle's E hops with his back to the dash because its script faces the
  point behind his start (0x34000455; anim-16 reached the same by hand) and keeps that yaw after the landing.
- **CanSee 0x1000003C**: an unset observer is SELF. Blue Beetle's E shoots the enemy he hops away from (none before);
  Stargirl's W small stars home on a visible target.
- **VM, left sub-graphs**: a sub-graph its parent leaves stops. Atomic Joker's R ends after 4 bursts / 8 s (it kept
  firing forever, through death and respawn).
- **VM, enter order**: a graph state's enter chain runs before its sub-graph starts. Superman's E pushes the enemy
  (KnockbackDistance was still 0 when the knockback dashed); Nightwing's R waits for the second press to launch the
  bike (it exploded at the first).
- **Status record flags**: the op-6 flags of a status record's list 0x1000046F (Rooted, Stunned, Crippled ...) hold while
  the status lasts. Superman's W roots the inner cone (status 0x48000A06 roots only through its record).
- **Defeat guards**: a turret's / minion's direct hit no longer kills through a type-0 defeat guard; Atomic Joker's The
  Punch Line starts (it raises 0x1000011B as script damage does).

### Answers and findings without a change

- Superman's E out of range: ics casts targeted skills at any distance (all champions); the original walked the
  champion into range first. Left for its own PR (CLAUDE.local Pending 7).
- Superman's Q "sometimes": the basic attack already started when Q was pressed stays normal (01:45:49.07); the next one
  is the Mighty Blow (bonus 17.9). Node 0x10000075 (P: resets the attack) is still a logged no-op.
- AGL's W: Shackles waits for `HasTargets`, which no script of the kit sets (census of fase3-ia); open.
- Atomic Joker's R gives +6 / 9 / 12 % range per rank to every skill and the basic attack (attribute 0x10000A9F, stat
  12): as the original.
- The cast delay: 0.13 s `champion_scriptlet_delay` (fase3-gx, so the stop / facing state lands first) plus the
  animation's own cast point (AGL Q ~0.23 s, Atomic Joker Q ~0.25 s from the order). Normal for ics; `[ics]
  champion_scriptlet_delay = 0.06` shortens it (the anim-matrix risk of fase3-gx comes back).
- Still open (later builds): the banana's lob arc and trip trap, the scarab sentinel object, the blasters / E glow left
  on Blue Beetle's form swap, AGL's E / passive visuals, Blue Beetle's Q area effect, the root's ice that leaves at once
  (a trigger-less `[2, 0]` transition), Superman's Q reset node.

### Config keys (ics/config.py `[ics]`)

`slot_tables`, `facing_locks`, `facing_lock_max_seconds` (6), `can_see_default_self`, `stop_left_subgraphs`,
`graph_enter_before_children`, `status_record_flags`, `defeat_guard_all_damage` (all true).

### Catalog

`script_nodes.tsv`: 0x1000003C CanSee, 0x1000003F, 0x10000057 ReleaseFacing, 0x100000FA (fields), 0x1000008E,
0x10000089. `properties.tsv`: 0x1000046F and its entries 0x10000450 / 0x10000453 / 0x100004C3, 0x1000003D, 0x100002A3,
0x10000302, 0x100008E3 / 0x100008E8.

### Tests

- `tests/test_kit_fixes.py` (new, 29 checks): Atomic Joker's R stops, The Punch Line on a direct hit, Blue Beetle's E
  (travel west, model east, a shot at the bot, the lock gone after), Infiltrator Mode's buttons on and off, AGL's Q
  targeting 5 in its window, Superman's E knockback (1.5-3.5 m), its punch on the key press, and W root.
- `tools/champion_check.py --vs-champion --window 5` against this build's base: 13 slots changed (Atomic Joker R ends;
  Stargirl W / R, Robin R, Solomon Grundy R, Gaslight Joker R, Mecha Wonder Woman R, Harley Quinn R, Nightmare Superman R
  statuses / damage from the enter order and the flags; Nightwing R waits for its second press).

### How to roll back

- Buttons: `[ics] slot_tables = false`. Facing: `facing_locks = false`. CanSee: `can_see_default_self = false`.
- VM: `stop_left_subgraphs = false`, `graph_enter_before_children = false`.
- Status flags: `status_record_flags = false`. Defeat guards: `defeat_guard_all_damage = false`.

## fase3-iz — tester report 2026-10-30 19:46 (strip narrowed, blue core)

Tester (run 19:41 with `diag --strip` started from the menu): the strip vanished in two bit steps, bit 9 the closest
(a fence piece also vanished there); the blue core must face like the red one ("about 190 degrees clockwise").
- Strip (docs/re-notes/ca-strip-two-bit-candidates.md): not a shadow (ShadowMapQuality was already 0); no static with
  index 0x200 | (1 << k) lies over the strip; candidates (#0x208 garden bush 0x2E000800 closest, #0x240, #0x201..204,
  fences #0x243 / #0x246 / #0x24C ...) are hidden one at a time by the new `diag --strip2` (`--franja2`); the strip
  header now counts statics when a cycle starts; render IIDs re-read so breakable fences can be hidden. No pack patch yet.
- Strip, second pass (21:33 recording, ca-strip-two-bit-candidates.md 8): the strip goes only when every bit-9 static is
  hidden; 8 single candidates were breakables the diag can't hide, #0x240 / #0x243 changed nothing; 53 non-breakable
  bit-9 statics remain (30 x 0x2E0005D6 red overlays, suspect #0x262). New `diag --strip3` (`--franja3`): one
  recording names the static (binary code steps + one step per static).
- Blue core yaw back to the data's 90 (`match_structure_yaw_add` core "1": 0): the mirror of the red core's -90.
- Tests: test_match 606/606, test_ics 40/40, test_terrainfix --real 36/36, catalog OK.

## fase3-iy — tester report 2026-10-30 18:12 (Crime Alley)

Tester (run 17:59-18:12 with `diag --hover`, `--heads`, `--strip`): turret heads still lost; the first two turrets show no
destruction (they stay and vanish seconds later); no hover highlight on minions; the middle strip remains (nothing seen
during `--strip`); the bot no longer attacks the tower — it should siege with minions, trade and leave when targeted.
- Hover (docs/re-notes/hover-listener-iid-gate.md, C): the client registers the controlled agent's 0x3CB / LifeState /
  0x100008E3.. listeners (0xA16730) only when the agent's IID top byte is not 2; ours is 2, so no SoftSelection,
  outline or attack cursor ever ran. New exe patch "controlled agent listeners" (0x615C07, jne -> nops; `[game]
  exe_patch_skip`). New `diag --hover` probes. Run `python ic.py patch`.
- Turret death (turret-death-head-rearm.md): lane turrets play `_Defeat_OnDead` + Vfx_Stop and keep their wreck
  (`match_structure_death_scriptlets`, `match_keep_body_roles`). Heads: the trace missed the moment; workaround
  `match_turret_head_rearm` restarts the client-made head 3 s after a fight; suspected client run-id clash (server run
  numbers start at 1).
- Bots (bot-shop-towers-end.md 4): siege behind minions, leave when targeted and return, short trades, react every
  0.2 s near turrets (`bot_tower_tactics`, `bot_siege_*`, `bot_trade_*`, `bot_tower_react`).
- Strip: `--strip` was attached after the map loaded (0 statics recorded); its render-feature steps (shadows, SSAO,
  reflections, decals, lights) changed nothing, so those are ruled out; rerun from the menu.
- Tests: test_match 604/604, test_meltdown 77/77, test_ics 40/40, test_session_flow 91/91, test_scriptvm 78/78,
  test_graph 34, test_tracer_detach 53, catalog OK.

## fase3-ix — tester report 2026-10-30 15:30 (Crime Alley, long list)

Tester (run 16:36-17:00; screenshots 94 / 95 and frames): the Power Core Turret platform 0x2E000A8E is right but turned
180 degrees; turn the blue core 170 degrees right; the core must not attack; enemy minions and the enemy bot cannot hurt
our core; the dampener doesn't come back; an always-lit blue door near the blue base exit; turret heads still vanish;
no recall lights; throw the vehicle at the chosen point (walk into range first); the middle strip remains; the enemy
champion sometimes hidden inside our vision; minimap still shows enemy minions / champion; no hover highlight on units
(ally or enemy) nor left-click select; AGL Q arm missing, E shield ends early, R issues (first "champions only", then
corrected: minions too, and on the target's death the rest goes to the nearest enemy); bots buy one item at a time and
dive towers; no portrait on Champion Level Up; remove the store's title and wallet row.
- Structures (docs/re-notes/core-door-regen.md): blue core yaw -170 (`match_structure_yaw_add`); the core's turret attack
  removed (`match_unarmed_roles` ["core"], no ring flags); minions measure sight to a structure's edge
  (`match_structure_sight_to_edge`) so waves and the bot take the core; structures regenerate out of combat
  (`match_structure_regen` dampener 15/s after 10 s, G); decor doors 0x2E000CD7 by the base exits
  (`match_decor_doors`, position G); PCT platform yaw 180 (`match_structure_platforms`); recall effect sent once, deferred
  (`start_scriptlet_hold_mode` "defer"); `diag --heads` for the vanishing turret heads.
- Vehicle throw (liftable-throw-walk-to-range.md): the throw slot's 0x100006D5 made the client drop far points; now off
  (`liftable_throw_far_order`), the champion walks into range and throws at the point (`liftable_throw_walk`), the press
  fallback aims at the last point (`liftable_press_aim`).
- Fog (ca-fog-minimap-category.md): the minimap note is removed through its category 0x100004DA (the client rewrites
  0x2A1 itself) (`fog_minimap_lever` "category"); the sight line is only required when vision_through_blockers is off
  (`fog_sight_line` "auto"); `fog_log_champions`.
- Unit pick (unit-pick-body-cell-test.md): no server cause found; `diag --hover` (0x3CB writes, outline) and
  `--bodytest`.
- AGL (agl-r-impact-q-e.md): orb Vfx_Active at once (`spawned_effect_delays_by_class` 0x40000484), the orb kept for its
  script's 0.5 s delayed destroy (`missile_destroy_delay_scripts`), `cast_target_kind_mask` {} (minions allowed again),
  a pulse that kills its target jumps with the right pulse count (`death_status_end_after_chain`). E ends when its shield
  breaks (data). Q's hand model: open (no graph on 0x2E000C4C).
- Bots (bot-shop-towers-end.md): shop only in base, in build order, upgrades first, save for the next item, go home to
  shop (`bot_shop_*`); turret awareness (`bot_tower_*`, `bot_dive_*`); combat frozen at match end
  (`match_end_freeze_combat`).
- Level-up portrait (levelup-ribbon-portrait.md): grid icon instead of tex384 (`level_up_icon` "grid_icon").
- Store page: no title / wallet row (`store_page_header` false).
- Tests: test_match 573/573, test_meltdown 77/77, test_ics 40/40, test_session_flow 91/91, test_scriptvm 78/78,
  test_graph 34, test_tracer_detach 53, catalog OK.

## fase3-iw — tester report 2026-10-30 14:51 (video) and the scorecard question

Tester (run 14:51-15:03 with a screen recording; screenshots 92 / 93 and a frame of the original game's end screen):
AGL floats high above the floor; the Raider pad half sank after it was lowered; the Power Core Turret still has no
platform (seen once in a showroom); the rewards panel must be on the Scorecard view (as in the original), not in Stats.
- AGL height (docs/re-notes/agl-floor-raider-pad-pct-prow.md): from 14:53:57 the champion's bundles carried the click
  height, which crept up (200.13 -> 201.52); every path corner, a standing champion and the champion bundle now take the
  navmesh height (`ground_path_from_navmesh`, `ground_snap_standing_champion`, `champion_bundle_snap`); corrections are
  logged to find the source.
- Raider pad z 200.2 (`match_nook_pad_z`; 199.98 sank a third under the paving).
- Power Core Turret platform: probable `0x2E000A8E` (showroom 90; the only base piece never placed), spawned under each
  turret (`match_structure_platforms`, `Units._spawn_platform`; not verified).
- Scorecard (scorecard-rewards-side-panel.md): this client has NO rewards panel on the Scorecard view (sprite 99 holds only
  the two TeamContainers; the original frame is another client build with two tabs); the same parts are the Summary tab
  (0x200000AD). Closest equivalent: four summary lines in the scorecard's chat (`scorecard_chat_summary*`, 0x2183).
- Separation regression (unit-separation-pick-body.md 3.1): the target was shoved by its attackers and a minion could be
  pinned in a line; `match_separation_target_holds`, `match_separation_unpin`. S10 announcer test given queue slack.
- Seen in the video, not fixed yet: after the surrender passed the bot kept fighting ~9 s.
- Vehicle lift old (icserver/finale.py) vs ics (docs/re-notes/vehicle-lift-old-vs-ics.md): the old lift was never complete
  (no toss / catch / destruction; one jump onto the head). ics sent a 0x8B piece rebuild at the catch that rebuilt the
  unattached vehicle mid-air: now only for attached objects (`liftable_attach_rebuild_attached_only`). Open: the
  per-state teleport snaps of toss / carry / flight (A/B with `liftable_carry_snap` = []).
- Tests: test_match 523/523, test_meltdown 50/50, test_ics 40/40, test_session_flow 91/91, test_scriptvm 78/78,
  test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, test_tracer_detach 53, catalog OK.

## fase3-iv — tester reports 2026-10-30 13:00 and 13:18 (Crime Alley)

Tester (12:51-13:00 and 13:05-13:18 runs; screenshots 89-91): the game closed after `diag --layers`; the Power Core
Turret vanished (only a white cylinder) and its base must not be round; the middle black strip disappeared only with
DrawStaticEntities off (`diag --layers` step 2); minions pass through each other (and maybe no hover outline because of
it); the Raider pad seems to float; the timeline tooltips should show a picture; the jungle spawn effect should start at
the 30 s announcement and the creatures appear ~1 s before the end; the scorecard Summary tab is still empty (also when
clicked).
- Diag crash (docs/re-notes/turret-pct-composite.md): the tracer detached while holding a debug event (Ctrl+C on a
  per-frame breakpoint); now Ctrl+C only sets a stop flag and `detach()` restores bytes / watchpoints / memory writes,
  continues held events safely and then detaches. tests/test_tracer_detach.py (53).
- Power Core Turret: lane body 0x40000C8E + the server-made cylinder 0x2E000A9A (`match_structure_parts`) + flag head
  0x2E000AC3 (`match_turret_heads`), Vfx_Active only, no base (`match_structure_classes`, `match_structure_scriptlets`).
- Minion separation (unit-separation-pick-body.md): server-side crowd separation on a grid (`match_unit_separation`,
  `match_separation_*`). The hover / ring problem is the client's type-0x200 character body, built from movement module
  1; new `diag --ring` probes 0x1D1600 / 0x1C6320.
- Timeline (timeline-tooltip-camp-prespawn.md): the tooltip picture is the event's field [6] (didExaminationIcon); drones,
  jungle and a new Raider mark carry billboard portraits and titles (`match_timeline`, `match_timeline_icons`). Camps
  phase in from the 30 s line and turn solid 1 s before (`match_camp_prespawn_from`, `match_camp_prespawn_appear_before`).
- Raider pad z 199.98 (`match_nook_pad_z`; it floated 0.32 m).
- Strip (ca-strip-static-shadow.md): a static-fed pass (probably a directional shadow); new `diag --strip` (`--franja`)
  hides static groups / render features one at a time to name the culprit.
- Scorecard Summary tab (scorecard-summary-tab-conditions.md): every server-side condition is met; three client-side
  causes remain; `diag --scorecard` extended with the full path.
- Tests: test_match 519/519, test_meltdown 50/50, test_ics 40/40, test_session_flow 90/90, test_scriptvm 78/78,
  test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, test_tracer_detach 53, catalog OK.

## fase3-iu — project clean-up (user request 2026-10-30)

The user asked for a clean project: remove unused folders and the Modern UI implementation (it will be redone from
scratch). Moved out of the repository to C:\Infinite Crisis Server\archive-2026-10-30 (nothing deleted):
- `old_files/` (164 tracked files, 42 MB: the first emulator's tools, dumps and extracted tables; only cited as history
  in docs/re-notes and a tools/roster.py docstring).
- The Modern UI code: `ui/` (rebuilt and retired modules), `tools/ui_build.py`, `ui_mod.py`, `ui_preview.py`,
  `rp_repack.py`, `as2c.py`, `gfx_edit.py`, `tests/test_ui_*.py`, `data/ui_build/`; the `ic.py ui` / `ui-test` commands
  are gone. The installed UI pack is the original (reverted). The research stays in docs/re-notes/ui-modern-*.md.
- Loose files: `Assets.cshtml.cs` (empty), `config.toml.bak`, `data/champions.json.bak`, `exports/` (texture / mesh
  exports of game assets; `ic.py export-texture|export-mesh` write there again when used), `__pycache__/` folders.
- Tests after the clean-up: test_match 492/492, test_meltdown 50/50, test_ics 40/40, test_session_flow 90/90,
  test_scriptvm 78/78, test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, catalog OK; doctor OK.

## fase3-it — tester reports 2026-10-30 11:23 and 12:05 (Crime Alley)

Tester (11:05-11:23 and 11:59-12:05 runs, AGL v AI; screenshots 87 / 88): no rewards card on the scorecard; no turret
ring (also with `diag --ring`); turret heads vanish when the turret is attacked / targets you; the Power Core Turret's
base is wrong; lift / throw still robotic; the wreck lingers after the explosion sound; Super Strength soft-lock (stuck
carrying, then the skill dead); the middle black strip stays (also with `diag --nofog`); skills cannot be ranked at level
19; the Raider announcer is now right.
- Super Strength soft-lock (docs/re-notes/liftable-softlock.md): input back once per match, a lift on a thrown rock with
  a stale target, and the throw table saved in place of Super Strength's. New `liftable_input_back_per_lift`,
  `liftable_lift_guard`, `liftable_keep_base_block`, `liftable_watchdog` (+ lift / throw / carry / restore timeouts),
  `liftable_throw_on_press` 1, `liftable_throw_face_motion_bundle`, `liftable_toss_timed`.
- Lift / throw / wreck (liftable-lift-throw-wreck.md): toss states with the lob's velocity and snap
  (`liftable_toss_velocity`), the carried object turned at the throw (`liftable_throw_turn_object`), Vfx_OnExplode 0.75 s
  after the landing (`liftable_land_explode` {"vehicle": 0.75}).
- Scorecard rewards (scorecard-panel-turret-head.md): 0x2188 with no accolade records never reaches Flash; 0x2104 now
  carries the encounter (`scorecard_level_encounter`) and is the late copy (`scorecard_accolades_resend_event` "0x2104").
- Turret heads (turret-head-pct-look.md): no acquire / lose flapping (`match_turret_pick_in_reach`) and no
  Target_Acquired / Target_Lost for a structure whose head is its own Vfx_AI_Active child
  (`match_turret_own_head_no_target_keys`). Power Core Turret: the data's 0x40000C8F (cylinder 0x2E000A9A + flag head
  0x2E000AC3), no gear plate, Object_Reset sent (`match_structure_classes` {}, `match_turret_plates`); the prow is not in
  this client's data.
- Skill ranks (skill-rank-levels.md): the client's rule (array 0x1000099C, else R 6/10/14/18, others 1/3/6/9); the old R
  rank 4 at level 20 was unreachable with the level cap 19. `rank_levels_from_client`, `rank_level_table`,
  `rank_refused_refresh` (a refused rank is logged and the state resent).
- Ring / strip, no fix yet (ca-ring-phantom-strip.md, ca-ring-bodies-strip-layers.md): the ring registers and draws
  (state 6) but its phantom (mask 0xA08) never meets our champion, who has no character-type body (only script-held
  collision bodies exist under ics); the strip is not fog, not a terrain hole, not EnableFog. New `diag --ring` probes,
  `--fogpoly`, `--nofog`, `--layers` (`--capas`). The "fog occluder pass" exe patch does nothing for the strip (kept,
  harmless).
- Log audit: the surrender was the tester's vote; RankSkill rpc 0x81910003 now logged by name.
- Tests: test_match 492/492, test_meltdown 50/50, test_ics 40/40, test_session_flow 90/90, test_terrainfix 33/33,
  catalog OK.

## fase3-is — Modern UI rebuilt from scratch: login and home (user request 2026-10-30)

The tester's screenshots of the restyled Modern UI (login and home, 2026-10-30): "nothing like the approved design,
only colours change and things get misaligned". Agreed: build each screen from scratch with our design, keeping the
instance names and classes the game's code uses (docs/re-notes/ui-modern-rebuild-home.md).
- Method: a module's SYMBOLS are new exported symbols (our art, our CLIK buttons of the game's classes, the game's
  UIWidget_Text with its templates, the Legacy data widgets copied), linked to the same library class as the Legacy
  symbol; one DoInitAction per movie registers them and wraps ui_sys.UIWidget_Base.prototype.AddChildFromLibrary
  (how WrapperMain attaches every screen / header / footer part / the landing nav by linkage name) so that with
  User.InterfaceStyle = 1 the Modern twin is attached. Legacy symbols stay byte-identical; Legacy calls pass through.
- Rebuilt: header 0x20000077 (bar, logo, pointed PLAY, HOME / CHAMPIONS / AMPLIFIERS / STORE, Merits / Crisis Coins
  pills, avatar opening the profile, help / settings / exit), login 0x2000006D (navy column, fields, pointed LOG IN,
  links, info cards), veteran home 0x200000A4 (champion hero with the game's art, PLAY NOW / VIEW CHAMPION,
  achievements, game-mode cards, last map, level rewards), sub-nav 0x200000A8 (ACHIEVEMENTS / RANKED / STATS),
  footer 0x20000090. The settings check box now re-attaches everything live (ICModern.rebuild).
- The 27 restyle modules + the header restyle moved to ui/modern/retired/ (reference, not built; their tests build
  them from there). New: tools/ui_preview.py (PNG preview without the game), common/rebuild.as,
  common/rebuild_kit.py; tools/ui_build.py SYMBOLS support; gfx_edit holes, frame labels, ExportAssets.
- Found: UIWidget_Base resets a placement's scale in its constructor (composite widgets keep their size; texts and
  icons size their box from it); a right / bottom liquid attachment is measured by the widget's own bounds.
- No config key: the Modern UI is client-side and opt-in (python ic.py ui apply + the check box).
- Build: data/ui_build/0xa00000d0.rp (6 movies), verified. Tests: test_ui_rebuild_home 630, test_ui_build 117,
  test_ui_champselect 170, test_ui_collection 838, test_ui_profile 755, test_ui_home 309, test_ui_social 557.

## fase3-ir — Modern UI: every client screen except the HUD (user request 2026-10-30)

The tester's first in-game try of the Modern header (screenshot 84): the switch works live and the scripts run, but
the nav buttons were huge, two of our own bordered panels looked like a Legacy frame, the currencies were covered and
the navy bar never showed. The user then asked for the whole Modern UI at once (the in-match HUD last, its design is not
final).
- Header fixes (ui/modern/movies/0x20000077_header): compact nav after PLAY, no nav panel, profile + currencies right of
  the nav, stronger PLAY tint. The navy bar was corrupt: tools/gfx_edit.define_shape3 overflowed the straight-edge bit
  count on edges > 65535 twips (the bar is 240000); edges are now split (`edge_segments`), >= 255 fill colours use the
  extended count.
- ui/modern/ is one module per movie (tools/ui_build.py discovers them; shared helpers in ui/modern/common/; a broken
  module fails the build naming it). 29 movies (docs/re-notes/ui-modern-build.md 10): champion select + skin carousel
  + PvP loading (0x20000022 / 0x20000067 / 0x20000020; ui-modern-champselect.md), store frame, all dialogs, champions
  + biography, amplifier sets (0x2000007C / 0x20000080 / 0x200000A5 / 0x20000094; ui-modern-collection.md), scorecard,
  rewards (with a 7 s redraw fail-safe), stats, achievements, ranked, calling card (ui-modern-profile.md), home body,
  sub-nav, footer, background, login, login rewards, new-player screens (ui-modern-home.md), custom match lobby,
  group, chat, friends (ui-modern-social.md). Legacy writes nothing to original instances; every Modern change is
  undone by a live switch back.
- Not possible in these movies (see the area notes): chat bubbles / per-friend windows (the engine draws one log), the
  champion-select search and role pills, tall loading cards, base-stat tiles; the store's look lives in
  ics/store_web.py (next step).
- Build: data/ui_build/0xa00000d0.rp 57,571,328 bytes, sha1 1868d70a5170, verified. Tests: test_ui_build 1108,
  test_ui_mod 31, test_ui_champselect 170, test_ui_collection 838, test_ui_profile 755, test_ui_home 309,
  test_ui_social 557, catalog OK.

## fase3-iq — Modern UI, phases 0 and 1 (user request 2026-10-30)

The user approved the MOBA-style client design (canvas https://claude.ai/artifact/AM81tAMYhGA9J4o8huiddu, 13 screens) and
asked to start the "Modern" UI next to the current "Legacy" one, switchable from the options. The in-game feasibility
test (`ui-test`, header movie 0x20000077) had worked on 2026-10-30 00:36 (docs/re-notes/ui-modern-feasibility.md).
- Pipeline (docs/re-notes/ui-modern-build.md): a length-changing repacker for pack 0xA00000D0 (tools/rp_repack.py;
  rebuilds the installed pack byte-identical), an AS2 -> AVM1 compiler (tools/as2c.py), SWF tag writing
  (tools/gfx_edit.py) and `python ic.py ui build|apply|revert|status|list` (tools/ui_build.py). Our own UI source lives
  in ui/modern/ (layout.py + .as scripts); the built pack goes to the git-ignored data/ui_build/; apply / revert refuse
  while the game runs and revert restores the original byte-identical.
- Switch: "Modern interface (beta)" checkbox at the end of the Settings > UI pane (movie 0x2000005F), client preference
  User.InterfaceStyle (0 Legacy, 1 Modern; the server keeps it, 0x216E / 0x216A). Modern header (0x20000077): navy
  translucent bar, pointed PLAY, HOME / CHAMPIONS / AMPLIFIERS / STORE, currencies (Crisis Coins gold, Merits blue),
  avatar top right; Legacy unchanged.
- No server behaviour change (no config key). Tests: test_ui_build 105/105, test_ui_mod 31/31, catalog OK.

## fase3-ip — tester report 2026-10-29 23:03

Tester (run 22:36-23:03, build fase3-io, store test, several Crime Alley v AI matches; screenshots 81-83): the store
test worked (Blue Beetle and 2 skins bought with Crisis Coins at 22:37; `own_all_except` / `account_grants` back to
[]); the rewards panel is missing from the score screen; turrets show two heads (the white one is wrong); the Power
Core Turret has no body or base; at the Raider kill the announcer also said the enemy killed it; the middle zone still
has the black hole; the meteorites' red aura is not the right one; the core's destruction is cut by VICTORY / DEFEAT,
no explosion from the hole and no Victory / Defeat voice; still no turret ring. Then: "bots always use a random skin".
- Black hole (docs/re-notes/ca-street-occluder-ring.md, C): the fog occluder pass blackens between each vision source
  and map static #0xB8 of 13BB, world state 0x2E001207 (the whole-lane piece, 0x7EB = 7); 0x100008CE never took on our
  structures. New exe patch "fog occluder pass" at 0x6AD624 (cmp / jne at 0xAAE224 -> jmp 0xAAE36A, every source skips
  the pass; `[game] exe_patch_skip`). Turret ring: the perception-filter patch is in the exe; new `diag --ring` probes
  (filter gates, relation, draw / effect DID / state).
- Turret heads (docs/re-notes/turret-heads-coredeath.md): the server-made head duplicated the client's own
  Vfx_AI_Active head (`match_turret_head_skip_own_child`). Blue Power Core Turret on the lane body class 0x40000C8E (the
  red one's body by data; `match_structure_classes`); the original's glossy cylinder is still not found. Raider: only
  the killing team's line (`match_boss_kill_voice_by_team`). Core end: the cinematic 0x3500003A plays to its end;
  billboard and the victory voice at 7.5 s (its Cinematic_Announcement frame 225), 0x1000000E at 12 s
  (`match_end_timing`; GH 7.0 / 11.0).
- Score screen (docs/re-notes/scorecard-accolades-meteor-aura.md, C SWF): the rewards panel is the first tab (labelled
  "Summary"); its chain waits for ACCOLADES_RECVD, which never fired because 0x2188 came before the scorecard existed.
  The same 0x2188 is sent again 1.5 s after the scorecard's 0x212E (`scorecard_accolades_resend`, fallback 8 s). New
  `diag --scorecard` (`--puntuacion`). Meteorite: the tint stays (the only red in its data); the original's halo is not
  identified; `liftable_aura_probe` plays logged candidates.
- Bots play a random costume of their champion (`bot_random_skin`; 7 champions without costumes keep the base).
- Store amplifier pictures (user request, docs/re-notes/amplifier-icons.md, C): the client composes them from 256 px
  layers: augment = brand background 0x100009C9 + stat icons 0x100009CD / 0x100009D0 (record 0x48000AAD), mod = the
  last target artifact's icon 0x10000436 + brand badge 0x10000996 (record 0x48000A34). All 334 now show one; the 17
  old ones were wrong (template_properties read past the record). `[ics] store_amp_composed_icons`.
- Run `python ic.py patch` (game closed) for the new exe patch.
- Tests: test_match 442/442, test_meltdown 50/50, test_ics 40/40, test_session_flow 89/89, test_scriptvm 78/78,
  test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, catalog OK.

## fase3-io — tester report 2026-10-29 21:10 (and more frames of the original game)

Tester (Crime Alley v AI, AGL vs Gaslight Batman, run 21:03-21:10, `diag.py --fog --ring --throwpress --destruction`;
screenshots 71-79, 72-79 from a video of the original): the Power Core Turret's base is not visible; the lane's third
turrets have the ring head; a missing truck by the blue base; the red vehicle shows white; the police car does not
appear; supers come when the second turret falls; the first two turret heads look almost transparent; meteorites lack
a red aura; lifting is slow, the throw looks frame by frame, a vehicle vanishes on impact with only the sound; the
fence strip is still black; still no turret ring; normal minions and the enemy champion must only show on the minimap
inside our vision (supers always); camp icons; minions' aggro chevrons; the recall's six converging lights; the score
screen's rewards panel. (The run's logs were found in the recycle bin and analysed from a copy.)
- Structures (docs/re-notes/power-core-turret.md 8): the original has lane turret (x 65 / 95), the ring-head dampener
  0x40000C88 / 0x40000C87 (x 40 / 120) and the Power Core Turret on the prow. `match_role_swaps` = {} (dampener back,
  its socket is flattened by the terrain patch); core turret gets Vfx_Fade_In first (P: its body); supers while the
  enemy's dampener / inner turret is down (`match_supers_on_structure_down`, `match_core_turret_supers` = {}); heads get
  Vfx_Startup only (`match_turret_head_team_keys` false, P). Vehicles: gaslight truck 0x4000081B at (35.5, 81.85), the
  white sports car replaced by the gaslight convertible 0x4000081C (G); the police car was spawned (not visited).
- Fog / ring / minimap (docs/re-notes/ca-fog-minimap-ring.md): allied structures' creation bundles carry 0x100008CE
  (`vision_through_blockers_at_creation`; diag showed them still running the occluder pass by the strip). Turret ring:
  the phantom's perception filter rejects IIDs with top byte 2 (0x852110 -> 0x4DAF10); new exe patch "perception
  filter" at 0x451544 (`[game] exe_patch_skip` to keep the original). Minimap: hidden enemies also get 0x2A1 = false
  (`fog_hide_minimap`, `fog_minimap_always_flags` 0x400000 keeps supers). Camps: the Heavy Tripod carries a minimap note
  (`match_camp_map_notes`); the nook pad (the Raider) keeps its circular capture icon (`match_nook_pad_map_note` true, tester).
- Liftables (docs/re-notes/liftable-aura-lift-throw-break.md): rock red tint by colour override 0x10000CF0 = 5
  (`liftable_aura`); input back at the toss / grab as the scripts do (`liftable_input_back`, toss 0.3 s); flight states
  with full 3D velocity (0xB0 motion bit 0x40 velocity pitch; `liftable_throw_velocity`, step 0.033 s); Vfx_OnExplode
  removed from the landing (it deletes every piece: `liftable_land_scriptlets`, `liftable_land_explode`); a throw order
  during the lift is queued (`liftable_throw_early_queue`).
- Aggro / recall / score (docs/re-notes/aggro-recall-scorepanel.md): minions targeting the local champion run
  CbtState_Aggro(_Active) (`match_aggro_roles`, `match_aggro_flag_mode`); recall streaks traced to FX 0x1E00009C's
  type-3 spawn, no change; 0x2080 word order fixed (`account_level_layout` "client") and cumulative XP numbers
  (`xp_numbers`); the rewards panel is the Accolades tab in this client.
- Store test (tester 2026-10-29 22:30, TEMPORARY: to be set back to [] afterwards, accounts come later): the store page's
  coin colours were swapped (Merits now blue, Crisis Coins gold, as the game's icons); `[ics] own_all_except`
  (Blue Beetle 0x400007FA and skins 0x40000999 / 0x40000CA8 not owned until bought) and `[ics] account_grants`
  (one-time 8000 Merits + 800 Crisis Coins at login). Test passed 22:37 (Blue Beetle + 2 skins bought with Crisis Coins); both keys back to [].
- Run `python ic.py patch` (game closed) for the new exe patch.
- Tests: test_match 430/430, test_meltdown 50/50, test_ics 40/40, test_session_flow 83/83, test_scriptvm 78/78,
  test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, catalog OK.

## fase3-in — tester report 2026-10-29 19:55 and the original-game video

Tester (Crime Alley v AI with AGL, run 19:46-19:55, `diag.py --hover`, screenshot 63; then frames 64-70 of a video of
the original game): the game froze and closed; move both jungle-mouth stealth sections a little down toward the lane;
the vehicle carry / walk / throw is not smooth and it does not explode on impact; a carried meteorite could only be
thrown after a Q; the enemy champion is sometimes invisible inside vision until it attacks; do turrets have vision; the
turret green / yellow / red indicators are missing; minions attack without turning; the upper street strip is still
black. From the video: a third turret before the core (Power Core Turret), the police car, the red vehicle and the
truck by the blue turret are missing, the core's ring, the two falling rings and the base when that turret dies, the
core's ring gone and super minions while it is down.
- Crash (docs/re-notes/vitals-crash-hover-picks.md, C): 0xAB1BD9 `inc [ecx+0x98]` with a null vitals component,
  reached from the 0x42 Vitals executor 0x8C26F0; the server sent 0x42 to Supergirl's Firewall 0x40000BEF, whose
  template has no 0x1000019D, so the client built no vitals component (same as the 2026-10-25 23:22 crash). New `[ics]
  vitals_need_perceived_type` (0x42 only when 0x1000019D & 0x7F59FB) and `spawned_need_vitals_component` (such a spawned
  object is an inert prop). Hover: enemies are picked in this run (131 attack orders from the pick); tools/tracer.py
  parses `-` offsets, `--hover` logs best_score.
- Bundles wiped 0x6-only ids (docs/re-notes/ca-ring-fog-bundles.md, C): the per-tick champion / minion bundle removed
  the Player bit 0x200000 in 0x1000019D (no turret ring) and 0x100008CE (fence strip). New `[ics]
  champion_flags_in_bundle`, `vision_through_blockers_in_bundle`. `diag --fog` / `--ring` probes added.
- Stealth: the vertical jungle-mouth tiles move 1 m toward the lane (y 85.2 -> 84.2); `[ics] match_stealth_lane_shift`.
- Fog sight line ignores structures / vehicles / gates (`NavGrid.line_clear(through_objects)`), `[ics]
  fog_line_through_objects`. Turrets do see: 9 m, core 10, foundry 13.5.
- Liftables (docs/re-notes/liftable-carry-throw-press.md): carried objects snap every 0.05 s (`liftable_carry_snap`,
  `liftable_carry_resend`); the rock's indicator waits for the cooldown 0x20F8 (`liftable_indicator_after_cooldown`);
  a second press with no throw order throws toward the facing (`liftable_throw_on_press`, `liftable_throw_press_window`);
  the landing also sends the vehicle's Destructible_OnBreak_* / OnCompletelyDestroyed keys (`liftable_land_break_keys`,
  `liftable_land_break_after`). New `diag --throwpress` (`--lanzar`), `--destruction` extended.
- Minions face their target (docs/re-notes/minion-attack-facing.md): `[ics] match_attack_face_turn`.
- Power Core Turret (docs/re-notes/power-core-turret.md): classes 0x40000C8F / 0x40000C8D at (27.0, 77.5) / (133.0,
  77.5) (G from frames); core shield Vfx_Indestructible while it lives; `_Defeat_OnDead` (Death 0x100001C0) and the
  body kept until its 300 s respawn (G); Elite Soldier / Trooper replace the enemy's pairs while it is down. Police car
  0x40000459 (124.5, 81.9), pickup 0x4000081A (52.4, 72.8), sports car 0x40000454 (107.4, 72.8) (G). Keys:
  `match_skip_roles` = {}, `match_structure_pos`, `match_keep_body_roles`, `match_structure_death_scriptlets`,
  `match_structure_death_delay`, `match_core_shield`, `match_core_turret_respawn`, `match_core_turret_supers`,
  `liftable_props_added_by_map`.
- Tests: test_match 394/394, test_meltdown 50/50, test_ics 40/40, test_session_flow 81/81, test_scriptvm 78/78,
  test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, catalog OK.

## fase3-im — tester report 2026-10-29 18:31

Tester (Crime Alley v AI with AGL, run 18:31, screenshots 58-62): "move the base a little down"; "that black section
is still missing"; "the stealth zones at both ends are still too far from the edge, the zone's edge should sit next
to the central zone's collision"; "picking up and throwing the vehicle looks odd, as if it skipped animations, and the
vehicle's destruction animation does not play"; "hovering enemy minions and champions draws no click area, so it takes
several clicks to attack"; "if I attack an enemy champion and it runs, my champion runs after it and does not stop to
attack even inside basic-attack range".
- Pedestal: both 0x2E000A36 holograms y 77.5 -> 76.9 (`[ics] match_map_objects`).
- Fence strip (docs/re-notes/ca-fog-stealth-hover.md 1, C): the client applies 0x100008CE modifiers only when the
  entity has a base value (0x974940 -> 0x973730 -> 0x58B1C0) and no champion / turret / minion template has one, so
  fase3-il's modifier did nothing. `World.see_through_blockers` now also sends the property by 0x6 first; new
  `[ics] vision_through_blockers_property = true`. Open: if still black, `diag --fog` + breakpoint 0xAAE1F0.
- Stealth fields (2): tiles now sit on the visible walls (west brick pillar x 52.90, east chain link x 106.95, east
  garden panels), not on the navmesh faces: west vertical (51.7 -> 51.9, 85.2), east vertical (108.3 -> 107.95, 85.2),
  east diagonal (105.8, 87.5 -> 105.66, 87.16). New `[ics] match_stealth_render_faces = true`.
- Hover / clicks (3, C mechanism): the outline (0xA88700 pick -> 0x3CB -> 0xA5D5F0 -> 0xA4EDD0) has no gate besides
  the pick, so both symptoms are the pick missing enemies (18:31: 1 356 of 1 463 move orders had no pick). Cause not
  found; workaround `Session._click_assist`: a move order near a visible enemy becomes an attack. New `[ics]
  click_assist_radius = {"unit": 1.0, "champion": 1.4}` (`{}` = off). New `tools\diag.py --hover` (`--raton`).
- Vehicle lift / throw (docs/re-notes/liftable-throw-destruction.md, C graph data): CarPickup was sent at 0.05 s and
  cut Pickup_Start's clip to its 0.45 s start; `[ics] liftable_car_pickup_at = "graph"` (the Car_Pickup start frame).
  The launch no longer rebuilds an unattached vehicle (`liftable_detach_rebuild_attached_only`); the landing rebuilds
  the pieces before the impulse (`liftable_land_rebuild`, `liftable_land_impulse.after_rebuild`, decompiled 0x632370
  sphere query, not traced live) and plays DestroyEntity's actions 0.15 s after landing as the vehicle's script does
  (`liftable_land_destroy_after`, `liftable_destroy_actions`, incl. `_HFSM_DestroyEntityAction_Optional`).
  `liftable_throw_face_motion_only` (delta mode only).
- Basic-attack chase (docs/re-notes/basic-attack-chase-range.md, C): the reach was stat 18 centre to centre (1.0 m for
  26 of 54 basics, AGL's included); the client uses range + both collision radii (0x9D01D0, 0x5897A0). New `[ics]
  attack_range_radii = true`, `attack_body_radius = {"champion": 0.575, "unit": 0.5}`.
- Tests: test_match 365/365, test_meltdown 50/50, test_ics 40/40, test_session_flow 81/81, test_scriptvm 78/78,
  test_graph 34, test_terrainfix 33/33, director 43, shop 18, navmesh 13, catalog OK.

## fase3-il — tester report 2026-10-29 17:45

Tester (Crime Alley v AI with AGL, run 17:32-17:42, `diag.py --fog --brazo --ring`): the Grab arm line; "the meteorite
must go higher, like in the palm of AGL's hand; usually it has an animation spinning in the palm, and the throw
animation"; "the vehicle falls lying flat, not with the front tilting down to hit and explode".
- Grab arm (docs/re-notes/agl-arm-meteor-vehicle-tilt.md 1, C diag + traffic): all six Grab beams resolve source =
  the missile (IIDs 0x136 / 0x149 / 0x169 / 0x16F / 0x117 / 0x143) and target = AGL, and reach the draw pass. The
  "src = dst = AGL" lines are a beam AGL runs on himself 6-8 s after each load (P: passive Vfx_Atm_Glt_Rads_Active),
  inactive while the intro hides him; not Grab. No change; open: the particle emission probe (0x748231).
- Meteorite (2): AGL's attach point 0x100000B0 is bone 31 RWeapon; in the hold clips 0x1A001131-36 (P) the palm is
  ~2.3 m up, 0.7 m right. `[ics] liftable_carry_offset` rock `[0.7, 0.4, 2.75]` (was `[0.0, 1.4, 1.4]`); new
  `[ics] liftable_hold_spin` rock `[180, 0.1]` (deg/s, step s; the held rock turns by its facing offset, also in the
  throw; P stand-in, `{}` = none). The throw key / clip are unchanged.
- Vehicle (3, C 0xB0 motion bits 0x400 / 0x4000): `movement_block` can send a facing pitch / roll (`World.tilt`:
  an entity's `pitch` / `roll` / `facing_offset` in every movement state; None = the old bytes). New `[ics]
  liftable_throw_pitch` vehicle `{"sign": 1.0, "max": 0.9, "land": -0.6}`: the slope of the arc on each flight state,
  nose-down at the landing (`{}` = flat; `sign -1` if the nose turns the wrong way).
- Catalog: scriptlets (0x10000887), animations (0x1A001131 set), network_events (0xB0 pitch / roll bits).
- Tests: test_match 349/349, test_meltdown 50/50, test_ics 40/40.

Same run, screenshots 56.webp (00:54, the black strip between the lane and the fence by the blue turret) / 57.webp
(01:59, a black wedge from AGL to the parked SUV), "the turret warning ring still does not show" and "the announcer's
voice seems to overlap other notices" (docs/re-notes/ca-fog-ring-announcer.md):
- Fog (1, C mechanism / P cause): 0xAAE0E0 runs, per vision source, an occluder pass over the bodies in an AABB
  phantom (filter 0x10009); 0xADA050 / 0xA4B920 keep map statics (IID top byte 1 / 5) with 0x7EB 7 / 8 (the fence)
  and entities with 0x10000623 (the liftable vehicles 0x4000045D / 0x4000081B). The black is the region BETWEEN the
  source and the blocker (west edge = a ray from the turret (65, 77.5); apex of the wedge = AGL at (97.7, 96.5), SUV
  vehicle 5 at (101.6, 92.1)). New `[ics] vision_through_blockers = true`: every allied vision source (champion,
  allied bots, structures, minions) gets attribute 0x100008CE (the foundries' "vision ignores blockers") by a set
  modifier 0x20F0 op 6, so the pass is skipped. `fog_vision_radius` stays 12.
- Turret ring (2, C): the diag of 17:33 shows the enemy core 0x102 and turrets 0x106 / 0x10C REGISTERED (0x10000C5D
  read 0xDDF83001: low byte 1 = passed; the 0x14A.. "0x10000" IIDs are minions). The ring stayed hidden because
  0xA84FB0 returns state 6 while entry +0x4C is 0, and only the ring phantom's callback 0xA3A5F0 sets it, for the
  local champion when its PerceivedType has **Player 0x200000** (the phantom's filter 0x210000 = Player | Minion).
  New `[ics] champion_player_flag = true`: the champion's unit flags change is 8 | 0x200000.
- Announcer (3, C traffic): the wave and jungle lines went in the same millisecond (17:35:02 0x2A0 + 0x2A1, 17:35:22
  0x29E + 0x29D, 17:35:32 0x29C + 0x29F; GH 17:39:42 0x196 + 0xAE), heard together (P: no client-side wait). New
  `[ics] announcer_queue = true` (+ `announcer_queue_gaps` {"kill": 2.5, "event": 3.0, "line": 2.5},
  `announcer_queue_max_wait` 8, `announcer_queue_kill_events`): one item at a time, kills first, then structure /
  objective events, then timeline lines (`Match.voice_out`).
- Catalog: properties 0x100008CE, 0x10000623, 0x1000062E, 0x7EB, 0x1000019D (Player).
- Tests: test_match 354/354 (new `fog_ring_announcer`, 5 checks), test_ics 40/40, test_session_flow 81/81.

## fase3-ik — tester report 2026-10-29 16:40

Tester (Crime Alley v AI, match 16:34-16:36, screenshot 49.webp; requires `python ic.py patch` with the game closed):
black areas still show on the ground in the middle of the map.
- Black strips in the centre (docs/re-notes/ca-black-strips.md, C georeference with the client's camera and AGL's
  position at 00:29): north x 70-76, y 81.5-83.1 (lane edge to fence), south x 70-75, y 70.4-71.7 (west of the south
  stealth field). Block 13BB is drawn only through its 16 baked 40 x 40 m patches (render-block byte +0x58 = 1, C
  `0x714280` / `0x712310` / `0x713DD0`; the diag lists no near batch for 13BB): layer textures, blend masks and stored
  normals play no part there.
- South strip (C): both triangles of the cell (70-75, 70-75) end at (70, 75), the socket's centre row still at 0 m;
  the lane mesh covers the cell only north of y 71.7. `[game] terrain_sockets` site `crime_alley_lane_turret` now also
  raises (70, 75) (CRC `0xFD6B_E526` -> `0x3979_96D8`; whole_triangles 3, MOPP caveat). Taking the site out of the list
  restores the installed bytes (the rim-only version is gone).
- `python ic.py patch` (`icserver/terrainfix.py` `apply`): a site whose earlier version is installed (its backup bytes
  plus the untouched installed bytes give the site's original CRC) is restored first and patched in the same run,
  instead of "unexpected bytes; not touched"; `tests/test_terrainfix.py` checks it (36/36 with `--real`).
- North strip (P / O): its cell is flat since 15:16 and the patch visibly changed it (46.webp vs 49.webp: a grey-brick
  wedge appeared); what stays black is bounded by a ray from the blue lane turret's spot (65, 77.5): a shadow cast
  from there (fog-of-war occluder or the turret light, P). To check after this build (re-note 6).
- Catalog: packs_notes (`0x800113BB`, baked patch textures `0x1300341E`-`0x1300344D`).

## fase3-ij — tester report 2026-10-29 15:30

Tester (after fase3-ii; runs 14:19-14:34 and 15:17-15:21 Crime Alley v AI): the thrown vehicle still flies straight
and disappears, with no curve, no explosion and no range / target area; the padlock stays when the Raider appears; the
power core's destruction leaves a whole copy of its central part in place.
- Throw indicator (docs/re-notes/throw-padlock-coredeath.md 1.2, C 0xa5dab0 / 0xa6d800): the fase3-ih 0x20F9 reached
  0x340001A3, whose start draws only while the client is targeting that slot, never during a carry. The carry now
  starts the slot's indicator with S->C 0x2180 and ends it with 0x217F at the throw / drop
  (`[ics] liftable_throw_indicator_messages`, `["0x20F9"]` = fase3-ih).
- Lob (1.3, C 0x60B5F0, P effect): states within 2 m are only steered and the arc was drawn flat; each flight state of
  a vehicle now carries a newer teleport sequence so the client places it exactly (`[ics] liftable_throw_snap`, `[]` =
  steered).
- Explosion (1.4, C script 0x3400015F): the landing now sends the original's Vfx_OnExplode + Destructible_IgnoreAOI and
  its DestructionImpulse as 0x8A to the vehicle (radius 4, magnitude 10, level 3), again 0.15 s later
  (`[ics] liftable_land_scriptlets`, `liftable_land_impulse`; `{}` = fase3-ih).
- Relay padlock (2, C 0x588A80 / 0x57C4B0): the 0x11F u8 is the stop mode, which the client's own stop passes as 1
  (fase3-ih sent 0); the unlock stops Vfx_Locked and _Selection_Usage_Locked with mode 1, again 0.5 / 2 s later
  (`[ics] match_nook_pad` `unlock_stop`, `unlock_stop_flag`, `unlock_stop_again`).
- Core duplicate (3, C cinematic data): the end cinematic (Crime Alley 0x3500003B / 3A) creates its own PowerCore at the
  losing core's spot and plays its fall; the networked core stayed under it. It is removed when the cinematic starts
  (`[ics] match_end_cinematic_removes_core`, `match_end_core_remove_delay`).
- Catalog: network events 0x2180 / 0x217F (new), 0x20F9 and 0x11F notes; world object 0x2E000AC5.

Tester (same report, Gotham Heights v AI 15:21-15:26): no move until the match starts; then a hole at the power core's
exit and no ramps to the lanes; the point he stood on looks "a few degrees to the left"; only his champion plays the
intro animation. Crime Alley: the sections still do not load (docs/re-notes/gh-ca-floor-spawn.md).
- Moves / hole (1-2, C timing: the first move came 0.23 s after "base gate t1 gone"; C data: the Door world states
  0x2E00084A / 0x2E000845 carry a Kynapse obstruction box 0x83C 1 / 0x8C1 2 / 0x8AA 60 x 38 m that seals both base
  exits until the start; the click is not a collision pick, 0xA12590): the door still goes at the start, and 0.1 s
  before a floor copy of the same world state with bundle properties 0x83C / 0x8C1 = 0 takes its place and plays
  Object_Open (P that the bundle wins) (`[ics] base_gate_floor_copy`, `{}` = fase3-ii). The countdown seal stays.
- Capture points (3, C data): on their pad statics 0x2E0008D5 (SW was 1.4 m off) (`[ics] match_capture_on_pads`).
- Intro (4, C 0xA9C610): the allied bots are bound to the intro's Player01..04 actors (keys 0x10000001..4)
  (`[ics] cinematic_bind_allies`).
- `tools/tracer.py`: `--moves` lines get a 6000-hit budget (the GH run's were muted by the Crime Alley run).
- Crime Alley (5): the three terrain sites are in the installed pack (C); no other terrain hole near the walkable mesh
  (cores' sockets and the turret socket's centre row are covered). Open: a screenshot of what is still black.
- Catalog: properties 0x83C, 0x8C1, 0x856, 0x857, 0x858, 0x8AA; world objects 0x2E00084A (note), 0x2E0008D5 (new);
  network event 0x20F5 note.

Tester (same report): minions follow the champion across the map (a wave can be pulled behind his tower), the AI
champions follow him behind his tower, recall plays its sound and teleports but shows no effect, the turrets show no
green / yellow / red warning ring, and killed jungle camps leave reward-like icons
(docs/re-notes/leash-recall-turretring-campicons.md).
- Minion leash (1, C: no leash data in 0x3A000026; authored rule): a lane minion keeps a non-structure target only
  within its acquisition range + 1.5 m and within 8 m of the lane point where it left; then it ignores that target 4 s
  and walks back to its lane taking no target until it is within 2 m of it (`[ics] match_leash_rules`,
  `match_minion_chase_margin`, `match_minion_leash_anchor`, `match_minion_leash_ignore`, `match_minion_return_max`,
  `match_minion_lane_rejoin`; false = the old 12 m rule).
- Bot leash (1): no enemy champion under an enemy shooter unless it is busy with one of the bot's minions; a chase is
  dropped 10 m from where it began or past bot_sight + 2 m, the champion ignored 3 s (`[ics] bot_leash_rules`,
  `bot_dive_needs_tank`, `bot_leash`, `bot_chase_margin`, `bot_leash_ignore`).
- Recall (2, C traffic 14:31:53.788): the channel fx (StartScriptlet 0x10000223 + fx 0x1E00009C, 8 s) was followed by
  Fidgets_Disable and Emote_Abort on the champion, which end its run on the client; it is now held as a looping key
  (same run re-sent after the following scriptlets) until its StopScriptlet (`[ics] start_scriptlet_hold`
  `["0x3400000A"]`, `[]` = as before).
- Turret warning ring (3, C 0xA7CA20): registration happens once, at entity add, and needs the Turret bit of
  0x1000019D, which our creation bundle lacked (it came 6-10 s later as a change). Structures' unit flags now ride in
  the creation bundle and go again as a change (0, then the value); an enemy structure's 0x10000133 goes as a change
  too (`[ics] turret_warning_flags_in_bundle`). P: whether the unit component's cache is what 0xA7CA20 reads at that
  moment; `python tools\diag.py --ring` shows each gate.
- Camp icons (4, C script 0x3400007D + template 0x400005E1): the Heavy Tripod's death drop 0x400005E1 (icon
  0x130006D3, minimap category 5, loot tables, no script) was never collected or removed; it is no longer spawned
  (`[ics] spawned_skip_classes` `["0x400005E1"]`, `[]` = spawned as before).
- Catalog: world object 0x400005E1, properties 0x10000C5D / 0x10000C5B / 0x10000C66 notes, scriptlets 0x10000320 /
  0x10000321 (recall), skill slot 6 note.

## fase3-ii — tester report 2026-10-29 14:40 (pedestal, rock in the palm, stealth rules, GH, AGL, picking)

Tester 14:19-14:37 (Crime Alley v AI, Gotham Heights 5v5): the centre floor holes still show (the new
crime_alley_lane_turret site was never applied: `ic.py patch --dry-run` said "would flatten"); move the base hologram
pedestal; AGL's animations still wrong; the lift looks as if animations were skipped; the meteorite belongs in the palm
of AGL's green arm; drones are hard to click; the stealth look stays seconds after leaving a field; inside a field the
enemies must lose sight unless attacked or they enter it; Gotham Heights: zones do not load and the champion stops
taking move orders after the first seconds.
- Base hologram pedestals 0x2E000A36 1.3 m toward the base (x 0.5 / 159.5; the disc stood west of the hologram's feet).
- The carried meteorite sits in front of the chest at the rock script's own offset (0, 1.4, 1.4) (`liftable_carry_offset`).
- Leaving a stealth field stops the shimmer at once with event 0x11F besides the signal (`[ics] stealth_stop_hard`);
  taking damage inside a field no longer reveals (`stealth_reveal_when_hit` false; attacking still reveals).
- AGL E (docs/re-notes/agl-qer-lift.md 2, C traffic 14:22:44-49): Shards_Active was re-sent up to 16 times in 5 s, each
  with a new run number, and the client starts a new run (a new shard burst) for every unknown number; every re-send of
  a looping key now reuses the key's last run number (a mere signal while the run lives), so the sphere bursts, closes
  and stays until Shards_Stop, and is started again only if the client ended it (`looping_resend_same_run`).
- AGL R (agl-qer-lift.md 3, C log 14:28:21 + original video 61-66 s): the first pulse came 0.1 s after the hit (Pulse
  Timer never started = expired) and the stacked target was left 0.13 s after the hit; the status' first pulse now waits
  its PulseDuration (`status_timer_first_wait` ["0x340002BF"]: 5 pulses ~1 s apart, as the original); a move-speed change
  on a walking unit / bot sends its movement state at once (`slow_motion_update`).
- Lift / throw (agl-qer-lift.md 4, C traffic 14:21:34.997 / 39.093): the facing bundle and the pickup / throw 0x8D went
  in the same millisecond, so the turn (applied 0.1 s after its stamp) cut a third of the 0.30 s pickup clip and the
  throw clip; the pickup and throw keys and their timelines now wait `liftable_face_lead` (0.13 s; 0 = as before).
- AGL Q (agl-qer-lift.md 1): the `--brazo` diag never saw a Grab beam: the per-frame checks used their 100-line budget
  on the map's and the intro cinematic's beams in the first 9 s. The Grab beams were built with target AGL (C). The
  "missing 0x5B5" hypothesis is refuted (the missile's world state 0x2E000C4C has none, C). `diag.py --arm` now logs one
  line per beam (entity / model / active / attach of each end, DRAWN / FAILED) with no budget. No server change for Q.
- Gotham Heights move freeze: in every GH run the client sent one move (0x20EE command 4) right after the intro and
  then none (14:35:54 -> 14:36:59; skills, 0x20EA and 0x20D1 still went out), while Crime Alley / Gotham Divided were
  normal. The order API 0xA70030 drops a move unsent when the clicked point does not snap onto the navmesh within
  2.5 m (0x4FB400; the other gates are ruled out: skills pass LifeState / 0x10000B2D / +0xCC, the 0x8686C0 hold is
  transient). GH's base Doors 0x4000026B / 0x40000269 (20 x 37 x 11 m, guessed spot (26, 54)) were kept all match
  ("keep"), unlike every other map's gate, and their collision catches the clicks toward the lanes (P). They now go
  `base_gate_remove_after` s after Object_Open like the others (`[ics] base_gate_keep_after_open` false; true = as
  before). New `tools\diag.py --moves` logs each step of a right click (snap result and click point included)
  (docs/re-notes/gh-freeze-holes-picking.md F).
- Map holes: Gotham Heights' terrain (block 0x1BF3 and neighbours) has no socket on the team-1 side (flat 249.97 m);
  the 0 m diagonal (115, 10)-(125, 25) is a designed lava fissure with bridges (statics at 242-247.7 m, lava overlay
  0x2E0005D6): kept, no site. Crime Alley (screenshot 46.webp): the north strip is the not-yet-applied
  `crime_alley_lane_turret`; the south band under the south stealth field (x 80-90, y 65-70) is the south alcove's rim
  vertex (85, 65) at 0 m -> new terrain site `crime_alley_south_alcove_rim` (one vertex to 199.98 m, 3 normals), on in
  `[game] terrain_sockets`. **Run `python ic.py patch` with the game closed** (it also writes the lane-turret site).
  (notes H; tests/test_terrainfix.py 34 with --real)
- Drone picking: the hover pick 0xA81B30 takes a render-ray hit or a +-0.8 m swept-box hit on collision parts,
  filtered by pick priority in hash order, then the validator score (notes P1). No server difference was proven
  yet; `tools\diag.py --moves --target` on a few drone clicks tells a missed pick from a stolen one (open, P2).

## fase3-ih — tester report 2026-10-29 12:45 (Crime Alley v AI run 12:12-12:24) (2026-10-29)

- Super Strength throw: the range ring and target area now show for the whole carry. Both throw sub-skills name the
  client slot script `0x340001A3`, which ignores the button's own `0x10000023` and starts the slot indicator only on
  ScriptEvent `0x100000B6` (stops on `0x100000B7`), delivered by S->C `0x20F9` (`u8 0 | u64 agent | u32 slot | u8
  available`). Sent `0x20F9(slot, 0)` 0.05 s after the carry is ready and `0x20F9(slot, 1)` at the throw / drop
  (`[ics] liftable_throw_indicator`, `liftable_throw_indicator_delay`; docs/re-notes/throw-truck-padlock.md 1).
- Super Strength throw flight: the vehicle crossed ~6 m in 0.4 s near hand height and exploded at the last state while
  the client still drew it ~0.1 s behind, so the lob was never seen. Now 15 m/s (`0x34000161` MissileVelocity), at
  least 0.8 s, a state every 0.05 s on a ballistic curve, the explosion 0.15 s after the last state
  (`[ics] liftable_throw_speed`, `liftable_throw_min_seconds`, `liftable_throw_step_seconds`, `liftable_land_delay`;
  notes 2).
- Gaslight truck `0x2E000F04` moved to (57.52, 94.01), same yaw 115: its long side is 0.18 / 0.21 / 0.27 m from the
  wall (was 0.62 / 0.65 / 0.71); its blocker is now its `.entity` box [2.5, 1.0] centre 0 (was [2.8, 1.15])
  (`[ics] liftable_props_by_map`, `liftable_blockers`; notes 3).
- Crime Alley relay padlock: the unlock at the Raider's arrival (12:18:57.898) sent both lock bools false and
  `Vfx_Unlocked`, but the padlock hologram is `Vfx_Locked`'s own particle run, which nothing ended. Event `0x11F` now
  stops every `Vfx_Locked` run first (`[ics] match_nook_pad` `"unlock_stop"`; notes 4).
- tests/test_match.py: indicator on / off, the lob still in the air 0.5 s after the press, the Vfx_Locked stop before
  Vfx_Unlocked (the drone under the blast is pinned during the longer flight).
- Crime Alley black sections in the centre: the recording (6:30-13:00) shows two black strips on the sidewalks just
  east of team 1's lane turret, x 70-75 at y 80-85 and y 65-70; the original video (2:36) has ground there. They are
  the rim of the lane-turret terrain socket (vertices (60-70, 70-80) + (75, 80) at 0 m in the 199.98 m street, team-1
  side only), which the street pieces cover only in the middle. New terrain site `crime_alley_lane_turret` raises the
  socket's rim rows y 70 / 80 (7 vertices) with upright normals (new site option `raised_normals_up`); the y 75 row
  stays, so no triangle leaves the MOPP collision tree. On in `[game] terrain_sockets`; **run `python ic.py patch`**
  (game closed) (docs/re-notes/ca-holes-pedestal-turrets.md C1).
- Base hologram pedestal: Tutorial 1's statics place pedestal `0x2E000A36` 6.30 m outside its base platform; Crime
  Alley's statics lack it. Spawned at (-0.8, 77.5) yaw 90 / (160.8, 77.5) yaw -90 with side 3 / 5 and Vfx_Startup +
  Vfx_Active_Blue / _Red (`[ics] match_map_objects` crime_alley; notes P1).
- Lane turret head: the server head `0x2E000AA8` had no side 0x100007A2 and no team change, so its colour keys
  (base table `0x1D00038B`, switched on the side) took the Null colour: the white hologram that floats over the turret
  only while it fires (recording 13:00). It now gets the body's side and the team as a change
  (`[ics] match_turret_head_side`; notes O2).
- tests/test_terrainfix.py (31): the rim site and the upright-normal option; tests/test_match.py: pedestals, head side.
- Drone / camp deaths ("they stand still a moment and disappear"): a dead unit got only its LifeState 2 bundle and the
  0x3 4 s later (traffic 12:15:02.416). Every lane drone and camp creature holds `_Defeat_OnDead 0x100001FA` (its
  world-state table: CbtState_Death_Induce + `Vfx_OnExplode`) and `_Defeat_OnFade 0x100001FE`; the client never runs
  them itself. Now `_Defeat_OnDead` 0.15 s after the death bundle and `_Defeat_OnFade` 2 s after it, then the 0x3 at
  `corpse_seconds` (`[ics] unit_death_scriptlets`, `unit_death_fall_delay`, `unit_fade_scriptlets`, `unit_fade_delay`;
  docs/re-notes/unit-death-slide-levelup.md 1).
- AGL slid while falling (first death 12:16:14.938): two 0x20EE moves arrived 65-75 ms after the death bundle (before
  the client applied LifeState 2), were accepted, and World.tick walked the dead body until and during the fall.
  Orders of a dead champion are now ignored and a dead champion / unit never walks (`[ics] dead_orders_ignored`,
  `dead_hold_still`; notes 2).
- End screen "Champion Level Up!" popup with an empty portrait: 0x2104's second u32 is the character icon (C
  `0xA7E0A0` stores it at +0x150 and passes it first to Ribbon_CharLevelChanged and to the summary's champion portrait);
  ics sent 0. Now the champion's `tex384` (`[ics] level_up_icon`). The same message's numbers were in the wrong order
  (the summary read "720 / 1061997773" = the 0.8f bits): the client order is level, prev, total, earned, bonus, f32 pct,
  f32 prev pct, u32 to next (`[ics] character_level_layout` "client"; "old" = fase3-ig; notes 3).
- tests/test_match.py `unit_death_slide_levelup` (12): drone fall / fade / removal order and the keys off, a dead
  champion's walk_to and leftover destination, the icon, the 0x2104 layout.
- Skill animations cut / out of step (AGL and every champion; frames of the recording vs the original AGL video, traffic
  of the run; docs/re-notes/skill-animations-vs-original.md). Three generic causes:
  - The server's copy of the local champion's graph was fed when the script ran the scriptlet, but the 0x8D left
    `champion_scriptlet_delay` + a tick (0.13-0.17 s) later, so every hook ran that far ahead of the client's clip:
    Meltdown's missile was created before the client got Meltdown_Start (12:22:26.406 / .414), Scorched Earth's crater
    before the slam began, Grab's hand left as the throw started, basic-attack shots before the swing. The graph is now
    fed when the 0x8D is sent; the cast-start grace waits for a pending feed (`[ics] graph_feed_at_send`, true).
  - A script's `skill_to_locomotion` raised at its code 2 (the skill state's hand-over to its `_Cosmetic` tail) ended
    that tail on the client at once: Meltdown's throw ran 0.18 s of its 1.0 s clip. `keep_cosmetic_tail` was armed only
    by the timed cast path, dead since `graph_runtime`. The graph now marks a `_Cosmetic` state entered by
    `skill_to_cosmetic` and the event is dropped while it plays (`[ics] graph_cosmetic_tail` true, `graph_cosmetic_hold`
    0.8 s when the clip length is unknown).
  - Scriptlet stops (StopScriptletKey) of the local champion went at once while its starts were deferred: Scorched
    Earth's smash VFX was stopped 2 ms after it started (12:16:49.095 / .097). Stops now wait the same delay
    (`[ics] champion_stop_deferred`, true).
  - Open (in the note, section 4): Grab's hand stays at AGL and the missile shows only its streak (P: the missile
    object lacks its world state's graph templates 0x5B5); the Shards sphere is re-sent 4 times in 0.6 s and every 1 s
    by the old workarounds and shows only bursts; Meltdown's status pulses at once and, on a target with MaxRads - 1
    stacks, jumps after one pulse, so the passive's slow (4 pulses) never comes (the original's first pulse is ~1 s
    after the hit).
  - champion_check --vs-champion --window 5, fase3-ig keys vs these: sequence OK 182 -> 183, EARLY2 1 -> 0, no slot
    loses its effect; hooks move 0.15 s later for the local champion, so a few window-edge pulses fall outside 5 s
    (equal with --window 6). Its EARLY2 rule allows the feed lag. tests/test_meltdown.py: the walking-away Grab bot starts
    at 4 m (from 5 m the later hand reaches the 7 m range end after the bot).

## fase3-ig — object updates back to full bundles, Crisis Coin prices for everything, Consume timing (2026-10-29)

Tester 10:18-10:28 (first run of fase3-if; Crime Alley v AI vs AI Krypto, then Gotham Heights 5v5 0x40000B6C): enemy
drones and champions inside the champion's sight stayed invisible, yet they could be attacked and could hit; a
consumed vehicle / meteorite played Consume's animation but vanished about a second later with no effect; on Gotham
Heights the champion moved during the countdown, then never again after the start (the client sent no move order
0x20EE at all after 10:28:06), the front of the base did not show, and the game closed at "exit match" (diag: the
usual 0x6BA at process exit); AGL's animations still have problems (not detailed); every store item must also be
buyable with Crisis Coins.
- `[ics] object_update_mode` default back to "bundle" (full bundles as in fase3-ie): the first game run of "delta"
  (0xB0-only states, 0x6 changes, 0x86 removals) coincides with the invisible enemies and the frozen Gotham Heights
  champion; "delta" stays available. Tests that check the delta path set it themselves.
- `store_prices_hc`: every kind also has a Crisis Coin price (augment / mod 30, champion 400, skin 200, slot 50; a
  tenth of the Merit price, G). test_session_flow checks an augment's SC and HC entries.
- Consume on a liftable: its `_HFSM_DestroyEntityAction` plays when DestroyEntity runs and the object goes at the
  script's own delay (`[ics] liftable_consume_destroy_action` true, `liftable_consume_remove_after` 0.0; it waited
  0.6 s more with only Vfx_Fade_Out, which vehicles do not have).
- Open: Gotham Heights after the start needs a run in "bundle" mode to tell whether the delta path caused it.
- Tester 10:44-11:02 (Crime Alley v AI vs AI Krypto): the camps are right ("those are the ones"); move them a little
  back into the wall's niches -> every camp slot 0.9 m north (maps.py; the front slots stay on the navmesh up to 1.0 m).
- A lifted meteorite stayed on its spot (the champion took it but was not seen carrying it): the client attach block
  moves nothing; rocks are now carried by server bundles over the head like the vehicles
  (`[ics] liftable_attach_kinds` [], ["rock"] = as before).
- Turrets attacked but gave no vision: a structure stands in a navmesh hole, so the server's line-of-sight check from
  its centre always failed and everything near it stayed hidden (0x90F); allied structures now reveal by range only
  (`[ics] fog_structure_by_range` true).
- The terrain-socket patch is applied on the install (CA dampeners, GD team-1 lane exits, CC centre; map-audit-all.md
  2.2 lists every map's sockets).
- Tester 11:00 (same run): Grab pulls minions but never the enemy champion; the arm shows only as a projectile
  (docs/re-notes/agl-grab-arm.md). The Grab missile never collided with the bot Robin: his Vault Kick ends with
  DisableCollision, which ics kept as a permanent "unhittable" flag. The client keeps one collision hold per script run
  (0x976990): a run's Disable only undoes its own Enable, and the toggle acts on the script's own entity (each Grab hit
  had put AGL himself out of collision). `[ics] collision_holders`, `collision_toggle_own_entity` (true; false = as
  before).
- IsMoving 0x100000E1 with r1 = 0 counts forced movement only (P); Grab pulls only a target that is not IsMoving[0], so a
  walking champion took the damage-only branch (`[ics] is_moving_flag_walks`, true).
- The arm is the missile Vfx_Active's beam from the flying hand back to AGL's arm (no clip stretches it); Vfx_Active was
  replayed after each turn bundle, three beams per Grab (`[ics] missile_rebundle_scriptlets` [], was ["Vfx_Active"]).
- `tests/test_meltdown.py` +6 Grab checks x 3 scenes (still / walking / after a dash's collision toggles); with the old
  keys 8 fail. If the arm still does not show: `python tools\diag.py --brazo` during one Grab.

## fase3-if — store, death fall, stealth L, camps, vehicle lift, Meltdown, object updates, terrain sockets, log sweep (2026-10-28)

Tester 14:39-15:00 (Crime Alley v AI, AGL vs Atomic Wonder Woman; screenshots 42-47): the score screen loads after the
match now. Reported: the store (SHOP) shows the embedded browser's version page instead of the store; the side stealth
fields are both off (the vertical one back as it was; the fields should line up with that corner's collision edge);
the death animation (falling to the ground when killing / being killed) does not play; the jungle drones are grey /
metallic instead of yellow, show no health bar, sit in the wrong places (original frame: on the upper sidewalk by
the jungle mouth) and there must be no camp in the centre; the SUV should move (not turn) closer to the wall; the
vehicle lift starts and then cuts to the held pose; AGL's R (Meltdown) must slow the target and keep hitting it while
it moves (its waves stop when the target moves); asked: a new full analysis (ultracode + Ghidra) of every map's load
and of the animations that still play wrong, and the reverse engineering to fix it all.

**Requires `python ic.py patch`** (it now also flattens the map packs' terrain sockets). Every behaviour change has an
`[ics]` key (`[game]` for the packs), written (default; value = what it gives), where "= x" alone means x gives
back fase3-ie; the comments in `ics/config.py` say the same. One bullet per change; the evidence is in the notes
named in each bullet and in `reverse-engineering.md`.

- **Store (SHOP) page and amplifier-screen purchases** (`ics/server.py`, `ics/session.py`, `ics/store_web.py`,
  `ics/account.py`; `docs/re-notes/store-fix.md`, C). Cause: the client reads AuthSelect's `nameValuePairs` as a gSOAP
  `NameValuePairArray` whose items are child elements named `nameValuePairs` (`0xADE2D0`); fase3-ie's flat pair parsed
  as an empty array, so the store URL (`InqStoreURL` `0xA97320`) stayed "", `NavigateByInfo` dropped the request
  (`0x8308C0`) and the browser kept its creation page `chrome://version` (`0x83172A`); the run's four client events
  `0x95` (web-ticket listener `0x420B90`) were the four SHOP opens. `BoutiqueDataManager` keeps a price only for the
  currency names `SC` (Merits) / `HC` (Crisis Coins), so fase3-ie's `Merits` left every cost at -1: the set-slot dialog
  sent `0x210E` at `0xFFFFFFFF` and the server's `0x210F` answer has no UI listener (nothing happened, x4). Now
  AuthSelect sends `URL.Store` nested (`http://<host>:<soap_port>/store`); `0x2107` sends an `SC` and an `HC` entry per
  augment / mod / set slot under one boutique id; a set slot costs **500 Merits or 50 Crisis Coins** (the original
  prices are in no record); `0x210E` pays the server's price from the wallet of the currency the client chose and
  answers `0x210C`, `0x20B8`, `0x2081` (+ `0x2090` for a slot); a wrong price answers `0x210D` + a fresh `0x2107`; no
  Crisis Coin price or an unknown currency answers `0x210D`; each purchase and refusal gets a `store purchase ..` line in
  server.log; the store page has a Merits and a Crisis Coins button per item; `0x95` is logged (`web ticket request
  (0x95)`), no longer in unhandled.log (no `0xC2` answer: the page needs no ticket); the ribbon `0x2095` after a
  purchase is off (its second u32 is the ribbon's icon DID and its StringInfo the name: fase3-ie's ribbon was empty).
  Cosmetic, client-side: after a `0x210D` on the slot the client keeps the first clicked currency pending, so the next
  success dialog can show the other currency's cost; the right wallet is charged. Keys: `auth_pairs_nested` (true; =
  false), `store_boutique_currency_keys` (true; = false: the whole fase3-ie purchase), `store_prices_hc` ({amp_slot:
  50}), `store_price_mismatch` ("error"; "changed" = the `0x210F`, "accept" = charge the server's price),
  `store_purchase_ribbon` (false; = true), `store_prices.amp_slot` 500 (was 1000). Tests: test_session_flow +9,
  test_ics +1.
- `tools/diag.py --storepage` (Spanish `--tiendaweb`), only if SHOP still shows the version page while server.log has
  the `0x95` line and no `store page: GET /store`: logs the URL the store screen gets (`0xA97331`), every URL the
  browser checks (`0x832F54`) and whether it is dropped (`0x832F59`, AL 0).
- **Death animation: the champion falls, yours too** (`ics/world.py` `World.damage` / `death_fall` / `death_overlay` /
  `_local_fall`, `ics/messages.py` `stop_scriptlet`, `ics/match/match.py` `Match.end`; `docs/re-notes/death-animation.md`,
  C). The fall is the graph's `Death` state, entered only on `CbtState_Death_Induce 0x100000AD` (a main-machine
  wildcard in all 56 champion graphs); the client never raises it, the server must. The data's message is
  `_Defeat_OnDead 0x100001FA` (held by all 156 champion variants: that graph event + the death cue). Since fase3-gv the
  local champion's death was its LifeState 2 bundle only (the fall sat in the `death_as_property` branch; traffic
  14:45:56.404 / 14:53:25.927). Now the local champion's LifeState 2 bundle goes at once, also while a carry holds its
  bundles, and 0.15 s later (after its stop state and its statuses' exit 0x8Ds) `_Defeat_OnDead`; nothing stands it up
  before the respawn's `_Defeat_OnRespawn` (mid-carry too). A bot's death keeps its order (stop bundle, 0x6 LifeState
  2) with `_Defeat_OnDead` instead of the bare graph event, and its respawn sends one `_Defeat_OnRespawn` per get-up
  delay (was four). The original's grey death screen is the server's `_CDefeatSystem_DeathOverlay 0x10000843` (a
  Colorize at saturation -100 + a smoke texture, no local-player filter), but the skeptic review found our client
  already greys the view itself on the local death (video of fase3-ia / ib), so the server's copy is opt-in: sent after
  the fall to the local champion only and stopped by event `0x11F` (`u8 0 | u32 key | u32 run | u8 flag`; a 0x8D
  signal stops nothing) after the respawn's get-up and at the match end; review fix: a death that ends the match (in
  Clash the last team health is taken inside `World.damage`, before the fall is scheduled) starts no screen after the
  end, where no 0x11F would follow. Open (P): fase3-gu, the only build that sent a fall to the local champion, had "no
  grey screen". Keys: `death_scriptlets` (["_Defeat_OnDead"]; [] = the bare graph event), `death_fall_local` (true; =
  false), `death_fall_delay` (0.15 s; 0 = at once), `death_bundle_force` (true; = false), `death_overlay_scriptlets`
  ([]), `death_overlay_stop` (true), `death_overlay_skip_after_end` (true), `bot_getup_scriptlets` ([]; =
  ["_Defeat_OnRespawn"]). Tests: test_match `death_animation` (20 checks: the 0x11F layout, local death and respawn,
  the fall off, the opt-in screen and its stops, a death that ends a Clash match, mid-carry death, bot death and
  respawn, the bare-event form).
- **Side stealth fields: the original's L at each jungle mouth** (`ics/match/maps.py` Crime Alley "stealth" tiles 4-7,
  `ics/match/match.py`; `docs/re-notes/stealth-alignment.md`, C navmesh, P video). The edge a champion's body stops at
  is the champion navmesh's rim + 0.525 m: west garden side face x 52.725, lane face y 83.125, garden-fence face
  22.93 deg; east x 107.075 (0.2 m off a mirror), fence 157.25 deg. Our camera equals the original's (pitch ~58 deg,
  vertical FOV 46 deg, 14.5 m high), so the original video's frames measure its layout: an L per jungle mouth. Now the
  vertical tiles are back at yaw 90 at **(51.7 / 108.3, 85.2)**, inner edge on the garden's side face, south end on the
  garden corner (the y 84.0 tiles hung 1.1 m into the lane); the diagonal tiles lie along the garden fence on the path
  side at **(54.2, 87.5) yaw 23 / (105.8, 87.5) yaw 157** (the 13:5x yaw 50 / 130 tiles crossed the corner). An enemy
  sees a hidden champion when it stands in any tile that holds it (the two tiles overlap at the bend). Keys:
  `match_stealth_overrides` ({}; per map key and tile index `{"pos": [x, y], "yaw": deg}`; the config comment lists the
  y 84.0 tiles, the whole 13:5x layout and an east L flush with its own corner), `match_stealth_any_shared` (true; =
  false). Tests: test_match +6 (the 13:5x layout fails three of them, the y 84.0 one two); the shimmer checks now wait
  out the level-2 respawn of the preceding mid-toss kill.
- **Jungle camps: yellow, overhead bar, the original's places, no centre camp** (`ics/match/units.py`, `match.py`,
  `maps.py`, `bosses.py`, `ics/world.py`; `docs/re-notes/camps-colour-bar-positions.md`, C unless marked). (1) The
  client tints PVP_Team 0-2 only (`0xA7B0D0`): team 3 gave colour 0 = TeamColor Null (grey). Every role-"camp" unit
  (the Raider and the other maps' camps too) is now sent as PVP_Team **0** with colour index `0x100007A2` = **6**
  (appearance `0x19000A61` value `0x1000011F` -> material `0x16000E7B`: yellow; Flash's neutral bar tint) in every
  bundle, and the team also goes as a change (3, then 0, by 0x6) 0.9 s after the spawn; the server keeps team 3 (fog,
  AI, rewards, scripts) and the 0x42 damage-number key uses team 0. (2) The overhead bar's push gate is the FloatyVitals
  tag `0x1000072C` (`0xA50C3B`), which every jungle creature template declares false: each camp unit gets it = 1 by 0x6
  right after its unit flags, at "Phasing Complete" for a phasing camp (held with its targeting flags), kept in its
  later bundles and never in the creation bundle, so the bar shows when the phase ends, as in the original. (3) Crime
  Alley has two camps and no centre camp (the original's nook pad stands empty at "Phasing Complete"): the Raider comes
  at 300 s with nothing to clear. (4) Each camp is 1 Heavy Tripod + **3** Tripods on the original's slots, measured on
  four video frames with the client's camera (P, +-0.3 m): west (48.82, 91.87) heavy, (51.04, 91.91), (47.20, 90.33),
  (49.60, 90.24), yaw 180; east (110.58, 91.83) heavy, (108.50, 91.82), (112.20, 90.31), (109.95, 90.15), yaw 135 (the
  original's own east; the exact mirror is in the comment of `match_camp_overrides`). Keys: `match_camp_wire_team` (0;
  None = team 3 on the wire), `match_camp_side` (6; = 0), `match_camp_team_as_change` (true; = false),
  `match_camp_vitals_tags` (["0x1000072C"]; [] = no bar), `match_camp_slots` (true; false = the 2 m ring),
  `match_camp_centre` (false; true = the fase3-ie middle camp on the Raider pad). Tests: test_match (no centre camp,
  1 + 3 on the slots, east = mirror within 0.8 m, team 0 / colour 6 on the wire and 3 on the server, the 3 -> 0 change,
  FloatyVitals after the phase-in and the unit flags and never in a creation bundle, the switch-backs, the Raider at
  300 s with team 0 and FloatyVitals and never `0x10000B2D`).
- `tools/diag.py --camps` (Spanish `--campamentos`): the team colour the client computes per object (team, local team,
  relation, colour index), the bar manager's registration, every bar pushed to Flash or held back because its
  FloatyVitals is false (`0xA50C60`), and every bar fade. Walk to a camp before it phases in.
- **Vehicle lift = the original's toss and catch; the SUV against the wall** (`ics/match/liftables.py` `lift`,
  `_graph_times`, `_toss_timeline`, `_toss`, `_catch`, `_hold`, `_block`; `docs/re-notes/vehicle-lift-and-position.md`,
  C). fase3-ie put the vehicle over the head in ONE state 3.4-4.2 m away 0.11 s into the lift (the client places a state
  more than 2 m away at once: `0x60B5F0` -> `0x5C9E90`) and sent PickupObject `0x100007A1` while the graph was in
  `SuperStrength_Car_Pickup`, which drops its `SuperStrength_PickupCar 0x10000175` (only `Car_Hold` takes it, to
  `Car_Catch`): the catch never played. Now the order of the original's sub-skill `0x34000161` (S6-S9): graph event
  CarPickup at 0.05 s (its `Vfx_Event9 0x100000E9`), the vehicle lobbed from where it stands onto the champion from
  Car_Pickup's grab hook in 11 states < 2 m apart (with S7's `VFX_CBT_Hit_Shared` on it), caught 0.65 s later in Hold
  (DisableHit, the vehicle on the hold point, PickupObject on both, the 0x8B rebuild), ready to throw 0.1 s after
  (AGL: CarPickup 0.05, catch 0.7125, ready 0.8125 s; fase3-ie 0.57). The timings come from the champion's own graph,
  its machine found by structure (all 56 graphs have it; six name it `SM_SuperStrength_Car_Throw`). A carrier killed
  before the catch drops the car where it is. The SUV stands at (102.43, 93.90), same yaw 245: its long side
  0.21-0.32 m from the raised wall north of it (was 0.54-0.64 m); its navmesh blocker is its `.entity` box `0x2D00061C`
  (half 1.0 x 2.5 m, centred 0.177 m forward: a new 4th element of `liftable_blockers`). Review fix: with "vehicle" in
  `liftable_attach_kinds` (the documented switch-back to the containment carry) the catch attaches the vehicle; it was
  ignored while the toss is on. Keys: `liftable_vehicle_toss` (true; = false), `liftable_car_pickup_at` (0.05;
  `"graph"` = Car_Pickup's start frame, the whole bend-and-grab, a 0.4 s longer lift), `liftable_toss_seconds` (0.65),
  `liftable_toss_steps` (12), `liftable_toss_arc` (1.5 m), `liftable_attach_seconds` (0.1), `liftable_toss_scriptlet`
  ({} = none); changed: `liftable_props_by_map` (SUV, was [102.3, 93.6]), `liftable_blockers` (SUV, was [2.5, 1.05]).
  Catalog: as a scriptlet key `0x100000E9` is `Vfx_Event9` (`CbtState_StrafeRight` is its graph-event name). Tests:
  test_match +14 (SUV gaps and blocker, graph timings incl. the renamed machines, the `"graph"` switch, CarPickup time,
  toss states, catch order and ready time, Car_Catch in the server's graph copy, a mid-toss throw refused, the fase3-ie
  switch, a mid-toss death, the attach switch-back caught and thrown).
- **Meltdown lands on a moving target, keeps pulsing and slows** (`ics/script_runtime.py`, `ics/script_nodes.py`,
  `ics/world.py`; `docs/re-notes/meltdown-moving-target.md`, C). The movement itself stopped nothing (the status rides
  on its victim, each pulse centred on it); five server causes: (1) the orb `0x40000484` (script `0x340002BE`) re-sets
  its speed every 0.3 s and each re-aim restarted its flight from the launch point: it landed 4.9 s late on a still
  target 4.5 m away and never on a walking one. A mid-flight re-aim now starts where the missile is (1.1 s still,
  2.1 s walking); a ranged homing missile that sets its speed counts the stretch it flew toward its range (Meltdown's
  has none; the other 17 SetMissileVelocity scripts set it once). (2) The status `0x480007AF` (script `0x340002BF`)
  acted for its victim: each pulse's area hit AGL's side (live 14:52:10.712: AGL took 21.5), damage, kill and assists
  were the victim's, and the jump orb was shot by the victim with its slot-4 stats (ChaseDuration 0: gone at once), so
  Meltdown ended after one pulse. A status now acts for its applier (client FindTargets `0x9CCE60` takes the relation
  team from the source descriptor `0x991F60`, P strong): FindTargets' side, ApplyDamage's unset source, DoTs, the
  statuses it applies, its auras' side (never its own carrier) and a missile it launches (the applier's, from the
  status' owner). This also turns Sinestro's Fear Incarnate aura on the victim's allies, Arcane Harley's Delirium aura
  to her side, Solomon Grundy's plague to the victim's allies, Zatanna's Punish blast and Arcane Green Lantern's R. (3)
  Meltdown has no slow of its own: AGL's passive gives a Rad stack per skill hit (the 4th: Radiation Sickness
  `0x480007BC`, a DoT and -40 % move speed `0x48000294`), and status damage raised no skill hit. A status' damage that
  triggers on-hit effects (ApplyDamage value b = 1) from a Q/W/E/R now raises that skill hit `0x1000008A` on the
  applier after the current chain (P, from the game's description). (4) The 20 ms event loop guard cut the 5th unit of
  one pulse: it counts per target. (5) A status that removed itself stopped its chain, so the jump skipped the
  pulses-left decrement (7 pulses after a jump): the removal follows the chain. With an enemy within 4 m Meltdown
  moves there once the victim has 4 stacks (AWW had 3 before that cast: with one of her minions within 4 m it moves at
  the first pulse, as the data's rule says; alone she keeps all 6). Open: one skill hit still gives two Rad stacks while
  the passive's proc is charged (two `TargetIID` locals share one slot in ics; a VM-wide fix needs its own validation),
  the pulse spacing (1.1 s on the 0.1 s update grid, 1.0 s in the data), node `0x1000016F`. Not Meltdown: the
  165-damage hits are the mid t1 turret; graph hook 2 at +0.17 s is the data's `skill_to_cosmetic` (AGL's throw ends by
  design). Keys (all true; false = fase3-ie): `missile_reaim_from_current`, `status_acts_for_source`,
  `status_skill_hit_event`, `event_loop_per_target`, `status_self_remove_after_chain`. Tests: `tests/test_meltdown.py`
  (new, 32 checks, no ports: a still bot, a walking bot, the tester's 3-stack case, the jump to a bot-team unit, 5 units
  in one pulse, AGL dead mid-Meltdown), test_scriptvm +13 (re-aim, the acting entity, relation side, credit, the queued
  skill hit, the jump orb's shooter and origin, the knock-up regression, self-removal, the loop guard per target, each
  key off). `tools/champion_check.py --bot-walk`: the bot walks 10 m away and back in the vs-bot window.
- **Object updates without a 0xBC (delta path)** (`ics/world.py` `World.update` / `delta` / `resync` / `remember_full`,
  `ics/session.py` `_tick` / `_missile_motion` / `_objects` / the stop order, `ics/messages.py` `movement_block` /
  `pvp_movement_state(parent)` / `remove_property` (0x86) / `set_property_entry`, `ics/gamedata.py` `network_mode`;
  `docs/re-notes/object-update-bundles.md`, C). A full 0x4 bundle to a live object re-creates nothing: its 0xF2 is a
  no-op while its u32 equals `entity+0x110` (0), its 0xB0 is one more movement state, a re-sent 0x7D2 / 0x5B5 rebuilds
  nothing; but its 0xBC is a diff (`0x62AFD0`) that **removes** the object's own ids of network mode 1 / 3 it leaves
  out: the ids ics sets by 0x6 only (the unit flags `0x1000019D`, tags `0x10000029` / `0x10000249`, CC flags
  `0x100003F3` / `0x100007FE` / `0x10000B39` / `0x100005A3`, the order lock `0x10000B2D`, the turret target
  `0x10000C66`), which the scriptlets' CC containers watch. The 0xB0-only update works (fase3-hy's "invisible bot" was
  its fog flag `0x90F`, sent only in full bundles). So the bundle-cause given before for the Shards sphere, Grab's arm
  and the camp phase-in was wrong (they stay open, see the next bullet), and Meltdown's stop was the server script (above).
  Now after an object's creation bundle an update is: a 0x4 batch with only the 0xB0 when the motion changed (the
  attach block too), one 0x6 per changed property, one 0x86 per net-1 / 3 id that left the object's list (network
  modes read from the client's MasterProperty record `0x32000000`: 3 822 descriptors, every mode equal to
  properties-complete.tsv); nothing when nothing changed. The cadence stays: the champion every tick it changed (no
  player-object bundle or 0x42 any more), a bot at its throttle with every changed property (a standing bot's fog flip
  now reaches the client), a missile at its turn (no Vfx_Active replay), units at their own states; the idle full bundle
  becomes a resync (movement state + scalar properties by 0x6); the stop order and a script teleport are updates. Full
  bundles stay for the creation and its retries, `_objects` (link, in world, after a cinematic, a `player_rebind`
  "bundle" / "recreate"), a champion's death and respawn, 0.5 s after a creation, the first update in the world after
  loading, and an update with a changed array / table (rank-up, purchase / sale, pad, the Stolen Power swap at a lift /
  throw), each followed for the champion by `vital_notices_on`. Open (O): a 0x6 reads its value with the 0xBC's entry
  reader `0x509740`, which reads no u32 before the packed id, yet ics's u32-first 0x6 works in game. Keys:
  `object_update_mode` ("delta"; "bundle" = fase3-ie byte for byte), `delta_remove_missing` (true), `delta_remove_net0`
  (false), `delta_complex_as_bundle` (true; false = arrays / tables by 0x6 too), `delta_full_on_life_change` (true),
  `delta_full_after_load` (true), `delta_create_window` (0.5 s), `delta_player_object` (false),
  `delta_vitals_with_motion` (false), `delta_resync_seconds` (5.0; 0 = none), `motion_state_backdate` (0.0; P 0.1).
  `resend_looping_after_bundle` / `match_camp_phase_resend` now follow only those full bundles (nearly inert),
  `bot_motion_only` is read in "bundle" mode only, `missile_rebundle_scriptlets` is not played in "delta" mode. Tests:
  test_match `object_updates` (25), test_ics +1 (the walk is 0xB0-only), test_session_flow +1 (no full / player bundle
  per tick); the camps' "full bundle while phasing" check passes `full=True`.
- `tools/diag.py --bundles` (Spanish `--paquetes`): logs each 0xBC table and the ids it removes, each 0xB0 state
  (pushed / dropped) and, with the call stack, every end of a scriptlet's spawned child (`0x666B40`), render effect
  (`0x65CA30`) or beam (`0x659B00`): what still ends the Shards sphere, the camp phase-in and Grab's arm.
- **Black terrain sockets flattened in the map packs** (`icserver/terrainfix.py`, `ic.py patch` / `--dry-run`,
  `icserver/doctor.py`, `ics/match/match.py`; `docs/re-notes/map-audit-all.md` 6, 9-12; the diag's in-memory fill of
  Crime Alley's four dampener vertices removed both black octagons, tester 14:40). A map pack is one zlib stream of
  stored deflate blocks, so `python ic.py patch` rewrites the heights (record `0x80......` +0x450) and the normals
  around them in place and recomputes the stream's Adler-32; each site is checked first (record DID and counts, CRC-32
  of the original / patched bytes), its original bytes go to `rp\<pack>.rp.terrainfix.json`, a second run keeps it, a
  site taken out of the list is restored byte for byte, a pack the game holds open is reported and the others go on.
  On by default: `crime_alley_dampeners` (also 1vAI Tutorial and Clash; the same 4 heights and 24 normals as the diag
  fill), `gotham_divided_lane_exits_team1` (black squares GD-1 / GD-2: the render index buffer holds y * 33 + x, so
  team 1's exits are drawn by batch 2, whose textures are in GD's zone pack) and `coast_city_centre` (CC-2; it lifts 8
  triangles out of the record's Havok MOPP tree, so the report warns: if the cursor or a ground ring drops through
  there, take it out). Off: `gotham_divided_lane_exits_team2` (its asphalt `0x130007AC`-`A9` is in none of GD's packs:
  flattened it would be dark), `gotham_divided_pits` (pods rise there) and `tutorial_2_dampener` (ics runs no Tutorial
  2); the name `gotham_divided_lane_exits` still means both GD team sites. Each Gotham Divided lid of
  `[ics] match_socket_covers` names its site, and a lid whose socket is flattened is not placed (its top would z-fight
  with the street; the check reads only the installed pack's block headers and the record, cached): after the patch GD
  keeps 5 lids (team 2's exits, the pits). `python ic.py doctor` warns while a site of the list is not flattened yet.
  Review fix: a site past (or across) the end of a shorter pack's stream (another version of the pack) is reported as
  not touched and read as "unknown" (it raised an IndexError that stopped `python ic.py patch` and `--dry-run`). Keys:
  `[game] terrain_sockets` (`icserver/config.py`; [] = the packs as installed), `[ics] match_socket_covers_skip_flat`
  (true; false = every lid). Tests: `tests/test_terrainfix.py` (new, 30 checks; `--real` adds 3: apply, re-apply and
  restore md5-identical on copies of the installed packs, about 7 s), test_match +4 GD lid checks. The tester's next
  run is the client's first load of an edited version-0x11 pack (the keymap precedent is a version-10 pack); the
  diag's `--mapa-rellenar` is no longer needed (its help says so).
- **Map audit, every map** (`docs/re-notes/map-audit-all.md`, C data; no code change beyond the bullets above):
  `0x1300008C` is the editor's grid texture (terrain types 0 / 1 / 0xB of the type table `0x07000000`), only in
  Tutorial 1's zone pack; Crime Alley's six outer blocks are unpainted grid outside the play area (nothing needed).
  Every drawn static's world state is installed on every map. Starts, lane mouths, dampeners, turrets and Coast City's
  camps / device match their markers; the jungle-mouth navmesh edges are the champion agent's (x 52.2 / 107.6,
  22.9 deg; moving the SUV +1.0 m would overlap the wall, +0.6 m is flush); Tutorial 2 (`0x40000A81`) has Crime
  Alley's socket on the team-1 side only (record `0x800113C3`). Open: Crime Alley's core yaw is the opposite of its
  markers' (a frame of the original is needed); the side camps have only the west marker `0x2E001118`; Gotham
  Divided's asphalt layer textures (`0x130007AC` / `AB` / `AA` / `A9`) are in none of its packs (runtime check:
  `diag --mapa` on a GD match); what stood at Coast City's centre; the role of Crime Alley's nook markers.
- **Log sweep of the 14:39-15:00 run** (`docs/re-notes/test-2026-10-28-1439-sweep.md` 1-18): every anomaly of
  server.log / traffic.log / unhandled.log / diag.log outside the topics above; the fixes below, each with its `[ics]`
  key (false / 0 = fase3-ie). Tests: test_match `log_sweep` (24 checks, each with its switch-back where it applies),
  test_ics +6 (the start-only lookup, the template bound, map units unchanged).
- **No freeze at a champion's first skill object** (S1, C): at AWW's first Savage Sweep the whole match stopped 2.77 s:
  `creation_type(0x2E0009F0)` built the record-start list of the 22 MB pack `0xA00000DF` on the game thread (2.4-3.3 s)
  for a lookup that reads 4000 bytes from the record's start. The readers that search from a record's start (creation
  type, 0x510, unit attack / stats, template properties, script tables, `record_u32`) no longer build a pack's record
  list (the same answers over 333 classes and their world states); `Data.prepare` builds the skipped ones off the game
  thread. That lookup now takes 0.07 s (the whole spawn ~0.2 s). `record_start_only` (true).
- **Skill helpers no longer fight** (S3, C): `Data.unit_attack` / `unit_stats` searched 32 KB from a template's start,
  past its end, so AWW's sweep helper `0x40000CD6` took her basic attack `0x34000257` from another record and "attacked" GL x7 (a
  long-lived one such as Atomic Joker's Plutonium Peel `0x40000BD4` would walk to the player). They stop at the
  template's end: 7 skill-spawned classes lose a foreign attack (also Zod's R `0x40000E56` and the jungle drop
  `0x400005E1`, the 2026-10-25 crash) and 3 a foreign stat block; map units keep their attacks and stat blocks (Crime
  Alley's team 1 turret also drops 7 attack stats read from the next records, now the same as team 2's).
  `template_window_bounded` (true).
- **Match clock** (S2, C): `Match.tick` clamped a tick to 1 s, so after the freeze the waves, camps, announcer lines,
  the Raider and the end ran 1.8 s behind the HUD clock and the timeline marks. The clock takes the whole step (up to
  10 s); every timer due by then fires in that tick. `match_clock_follows_wall` (true).
- **Bots no longer cut their own skills** (S4, C): a bot's basic attack started inside its Savage Sweep's cast and cut it
  (no damage, no cooldown, cast again at once), and its Vault cut an empowered basic attack. A bot's (and a unit's)
  basic attack and chase wait while one of its skills is in its cast; a bot's skill clears its attack target first, as
  the player's order does; the brain casts no skill while another one is in its cast, nor while its basic attack is
  (at most 1.5 s). `attack_waits_for_cast`, `bot_cast_clears_attack`, `bot_skill_waits_cast` (true),
  `bot_skill_waits_basic` (1.5 s).
- **Bot's ignored skill uses** (S5, C): AWW "cast" W Smite 7 times in 4.5 s while its buff waited for a basic attack; the
  script took none (its transition needs NOT HasStatus `0x480006FD`), the bot never attacked and stopped every 0.7 s.
  A skill use its script does not take is now no cast for a bot: the slot rests 1 s and the bot attacks (the attack
  uses the buff). The "skill used" broadcast `0x10000196` (passives counting uses) goes only for a taken use. The stop
  state stays before the activation. `bot_cast_needs_taker` (true), `bot_untaken_skill_backoff` (1.0 s),
  `skill_used_broadcast_taken` (true).
- **Bots back off from towers** (S6, C code): all four bot deaths were under GL's turret, 5-7 shots each, the only exit
  the 30 % health retreat. A bot an enemy turret targets drops its target and walks back along its lane out of the
  turret's range, and stays out until the turret has not targeted it for 2 s; it chases an enemy champion under an
  enemy turret (allied minions there or not) only with 70 % health or more. `bot_turret_aggro_retreat` (true),
  `bot_dive_health` (0.7), `bot_trace` (false; one server.log line per bot decision).
- **Bot's R at level 6** (S7, C): the bot's rank order did not count the trait (slot 5), so AWW ranked it at levels 5, 6
  and 7 and got her R at 8. Every slot of the loadout's order counts, and an entry the rank gates refuse is retried at
  the next level (R ranks at 6 / 11 / 16 / 20 under `rank_min_levels`; the orders say 6 / 10 / 14 / 18, P: for the
  rank-gating owner). `bot_rank_order_all_slots` (true).
- **No passive credits before the start** (S8, C asymmetry, P rule): the player earned ~120 credits during the intro
  and the countdown, the bots none. `match_income_from_start` (true).
- **Kill feed and announcer name the credited champion** (S9, C): bot deaths 3 and 4 were GL's kills (credits and K/D/A
  right), but the feed said "by turret mid t1" and the announcer line had no portraits. The feed and the announcer now
  name the credited champion (also for a missile's or spawned object's kill); the victim's kill card keeps the real
  killer. `kill_feed_shows_credit` (true).
- **Raider warnings only for a coming Raider** (S10, C): the 4:30 / 4:50 warnings played while the middle camp held the
  Raider's pad, and no Raider came. The first warning waits until the pad is free, then the warnings and the spawn keep
  their lead times (with the default `match_camp_centre = false` there is no middle camp and nothing changes).
  `raider_warn_when_free` (true).
- Logging only: node `0x100000FA` is logged as SetSkillStatOverride (P: server-only, slot / TFX / pair values; no wire
  message known) instead of "floaty_text" (S11); the by-design "skill event 0x10000023 not accepted" line once per
  script and event (S13). Left open (no evidence for a change): S11's wire message, the RankSkill RPC `0x9F
  0x81910003` (its answer's object-reference encoding is not decoded), the surrender refusal before 600 s (the
  original's message is unknown), the selection panel's level, node `0x10000075`, and a local champion's attack order
  during its own cast (`attack_waits_for_cast` covers bots and units only; not reported, and whether the original
  queued or cancelled is unknown).
- **Checks** (2026-10-29, all areas together, after the review fixes above): every `[ics]` key of the pre-build snapshot
  (589) is still defined and none lost its reader; each of the 61 new keys is read; the two overlapping implementation runs left no
  duplicate code (one update path, one definition per function and key). Suites: test_catalog OK, test_ics 41,
  test_director 43, test_shop 18, test_navmesh 13, test_scriptvm 78, test_graph 34, test_match 310, test_meltdown 32,
  test_session_flow 81, test_terrainfix 30, script_coverage 875 / 875 (simulated: 549 / 549 scripts, 325 / 325 skills
  clean). `tools/champion_check.py --vs-champion --window 5` against the fase3-ic run: DMG 157 -> 175, CHMP 12 -> 10,
  FX 91 -> 75, BUFF 6, REF 4 (19 slots up a category, none down), sequence verdicts unchanged, vs-bot damage unchanged
  but AGL's R 88 -> 104 (Meltdown). Gaslight Joker's R vs bot fell 110 -> 3 in that run: the tool's cast order, not the
  server (Rat Swarm `0x34000201` is a toggle; its first cast now deals damage, so the dummy-champion cast that switched
  it back off was skipped and the vs-bot cast switched it off). The tool now presses an instant slot that still waits
  for a second use once more before the vs-bot cast (`--keep-toggles` = before): 109.8 again, with `0x4800068D` and
  `0x480010CA` on the bot.
- **To test**: close the game and the running server (it still runs fase3-ie), run `python ic.py patch` (it also
  flattens the map packs' terrain sockets; `python ic.py doctor` warns until it has), then start `python -m ics play`
  and the client. Crime Alley v AI: SHOP opens this server's store page and the amplifier screen sells a set slot (500
  Merits / 50 Crisis Coins); each jungle mouth's stealth field is an L on the corner's faces; no black octagons at the
  dampener sockets; a champion falls when it dies (yours too: while lying dead, is the screen still grey with the smoke
  edges? if not, set `death_overlay_scriptlets = ["_CDefeatSystem_DeathOverlay"]` under `[ics]`); two camps of 1
  Heavy Tripod + 3 Tripods, yellow, on the upper sidewalk by each jungle mouth, with their overhead bars from "Phasing
  Complete", none in the centre, the Raider at 5:00; the SUV nearer the wall at the same angle; a vehicle lift bends,
  tosses the car onto the champion and catches it; Meltdown follows a walking enemy for its 6 pulses and slows it after
  the 4th stack. Object updates are now deltas: ranking a skill, buying / selling an item, a pad, a vehicle lift /
  throw and a recall should look as before; if something stops moving or updating on screen,
  `object_update_mode = "bundle"` under `[ics]` in `config.toml` is fase3-ie's form. Not fixed by this build (cause
  open): the Shards sphere during basic attacks, Grab's stretched arm and the camps' phase-in; if they still cut, run
  `python tools\diag.py --paquetes` in a second console with the game open during one AGL match (E up while attacking,
  one Grab, a camp phasing in at 0:45). Only if a fix above fails: `--tiendaweb` (SHOP still shows the version page),
  `--campamentos` (camp colour / bar). Send `logs\server.log`, `logs\traffic.log`, `logs\unhandled.log` and
  `logs\diag.log`.
- Store page redesign (user 2026-10-29: "a nice, modern, friendly store with the champions' portraits and their
  backgrounds, for champions and skins"): card grid with tabs (Champions / Skins / Amplifiers / Set slots), search,
  "hide owned", a detail dialog with the full art and the buy buttons; each champion / skin card shows its wallpaper
  (champions.json `wallpaper`, per costume too, 512 px mip) and its portrait (`grid_icon`); amplifiers and the set slot
  show their icon when their record has one (template 0x10000302 / record 0x1000095E), else a glyph. Pictures are
  converted at run time from the installed packs (Pillow's DDS decoder when installed) and cached in
  data/uesrv_cache/store (git-ignored), never stored in the repository; written for the client's Chromium 31 (flexbox,
  ES5). `[ics] store_page_style` "cards" ("table" = the plain table), `store_page_images`, `store_card_mip` 1,
  `store_prewarm_images`. test_session_flow 82 (+1: a portrait served, a DID outside the roster refused).

## fase3-ie — vehicles, camps, timeline, K/D/A, end screen data, emotes, account amplifiers (2026-10-28)

Tester 2026-10-28 (after fase3-id, screenshots): the raised socket floor holds; the vehicles have no collision; a
lifted vehicle sits merged with the champion instead of over its head, vanishes while the champion moves and shows
when it stops; the side stealth fields are still off (turn them twice as far the other way); the jungle creatures
stay in their spawn animation, show the wrong model, and lose the effect at once when attacked; the top timeline's
marks do not match the announcer's times (the match starts, then the first red mark is reached seconds later); the
K/D/A counter is wrong; an emote during a move slides the champion to the point; at the match end the cinematic plays
but the score screen shows no data; asked: enable the shop and the amplifier (stolen power / loadout) sets.
- The side stealth fields turn 16 deg back (blue yaw 98, red 82).
- An emote stops the champion's move / attack first (`[ics] emote_stops_movement`, true).
- Back in the menu after a match the champions, the last played champion and its background did not load (tester): the
  menu refresh also re-sends ownables 0x20B8, champion advancement 0x209D (levels, last used), currencies 0x2081 and
  completed encounters 0x214B (`[ics] menu_refresh_account_data`, true).
- Amplifier sets can be created (`docs/re-notes/store-amplifiers.md`): `0x2090` now sends total = the account's set
  slots (the client fills the rows after the saved sets with empty sets to edit and save; it had total 0 = nothing to
  edit) and max = `[ics] amplifier_set_max` (12); the set slot item `0x49000AA2` is listed in `0x20B8` (type 5) so the
  "buy a set slot" row shows, and a bought slot sends `0x2090` again. A saved set keeps the client's slot id; sets for
  no champion serve every champion. Keys: `amplifier_sets_total_slots` (true), `amplifier_set_max`,
  `amplifier_slot_for_sale` (true); `amplifier_set_slots` (6) is now the total.
- The lobby's set pick (`0x2098`) is remembered per champion; in the match the set's augment stats (`0x10000950`, op 9
  add / 10 percent) go to the champion as their own part of the stats (`World.recompute_stats` `amp_add` / `amp_pct`),
  and into the HUD modifiers with the items'. Mods are not applied yet. Key `amplifier_stats_in_match` (true).
- SHOP: the store screen is a CEF page at the login's `URL.Store`, which the server never sent. AuthSelect now sends
  `URL.Store` = `http://<host>:<soap_port>/store`, a page this server serves (`ics/store_web.py`): wallet, set slots,
  champions, skins, augments, mods with `[ics] store_prices`, a Buy button each; a purchase pays from the account and
  sends `0x210C`, `0x20B8`, `0x2081`, `0x2095` (and `0x2090` for a slot) on the login connection. Keys `store_url`
  ("" = this page, "none" = no pair as before), `store_web_page` (true).
- **Jungle camps' phase-in** (`docs/re-notes/jungle-camps-spawn.md`; tester 13:52): (1) it never ended: the render
  effect in `Vfx_Spawn_Alt01` / `Event02` (table 0x1D000674) is persistent (field 0x375 = 1, C: `0x66D910`,
  `0x673CF0` keeps a holder `0x654BD0` on the run), so it lasts until the run stops, and ics never stopped it;
  (3) an attack provoked the camp, its chase states are full bundles, and a bundle drops the run's attachments (C log,
  P mechanism). Now a camp unit with that table phases for `match_camp_phase_seconds` (3.0, G), invulnerable, not
  provoked and with its targeting flags held (`match_camp_phase_untargetable`); a bundle meanwhile re-sends the key
  (`match_camp_phase_resend`); at the end the run is signalled to stop (`match_camp_phase_stop`), the flags go, one
  bundle follows (`match_camp_phase_end_bundle`). The first camps start that much earlier so the phase completes on
  "Phasing Complete" (`match_camp_phase_lead`). `match_camp_phase_seconds = 0` = fase3-id.
- (2) Model (C data): `0x40000CA0` / `CA1` are the Tripod rig `0x2E000BE2` at template scale 0.35 / 0.7 (the original's
  big + two small golden spider robots); every Tripod class shares that world state, there is no other CA camp model.
  The "wrong model" was the stuck yellow overlay + black fade (P). No change.
- `tests/test_match.py`: phase-in stop before the flags, no damage / provoke / flags while phasing, re-send after a
  bundle, phase over at the line time.
- **Lifted vehicle over the head, visible while walking** (`docs/re-notes/vehicles-carry-collision.md` 1; tester
  13:52): the containment attach (0xB0 flag 0x04) cannot carry the script's AttachmentOffset (0x34000161: (0, 0, 2.5);
  the wire's mode-0x10 block is only point / u8 / bool, C `0x55E290`), so the child sat at the champion's origin; and the
  carried object had been given the champion's destination, so `World.tick` walked it and a full bundle (with the
  attach block) went every tick while he walked (C server code). Vehicles are now carried by their own bundles at the
  champion + 2.5 m with his heading and speed (a destructible's pieces follow its frame, C `0x61F500` -> `0x62C730`),
  a bundle when his course changes or every 0.5 s; carried / thrown objects get no destination. Keys
  `liftable_attach_kinds` (["rock"]; add "vehicle" for fase3-ie's attach), `liftable_carry_offset`, `liftable_no_dest`
  (true), `liftable_carry_resend` (0.5), `liftable_carry_turn` (0.1).
- **Parked vehicles block** (same note, 2): the client moves no character itself, so the server's paths must go round
  them: each parked vehicle's footprint is blocked on the match's navmesh (champion, bots, minions' lane legs) and
  freed when it is lifted, consumed or gone. Keys `liftable_blockers` (world state -> half sizes along the heading, G),
  `liftable_blocker_margin` (0.35 m); {} = off. `tests/test_match.py`: footprint blocked / freed, path goes round,
  vehicle 2.5 m up and not attached, no own destination and no per-tick bundle while walking.
- **Timeline strip** (`docs/re-notes/timeline-kda-endscreen.md` 1, C): Flash places a mark at (event time - (the
  StartTimeline 'now' + its own elapsed)) / 5 s * 12 px. ics sent a 'now' 5.35 s old (the match time stands still
  during the load) and placed the marks before the intro's end moved the start 9.2 s; the jungle lines counted from
  60 s while the camps and their mark are at 45 s. Now: 'now' = the wall clock, event time = now + (match time of the
  event - match time now) (`timeline_wall_now`), the marks are removed and placed again when the intro ends
  (`timeline_rebase`), the jungle lines follow the camps' first time (`match_jungle_lines_follow_camps`).
- **K/D/A** (2, C): the top-right counter shows the `0x1000005B` row of the controlled agent, which was what the
  server counted; kills by a skill's object, and champions finished by a tower / minion / creature after a champion's
  damage, counted for nobody. The kill goes to the missile's champion (`score_kill_owner`), hits through skill objects
  count for assists (`score_hit_owner`), and a non-champion last blow is the kill of the last enemy champion who hit
  within `match_assist_window` s (`score_kill_credit_last_champion`).
- **End screen with no data** (3, C): the Flash scorecard shows only after `UpdateCurrentUpgrades` and
  `UpdatePowerGraphValues` for every row, which the end page `0xA795E0` -> `0xA3AC70` sends per row only when the row's
  artifact list (`0x2045` entry +0x2FC) is not empty, keyed by the row's account IID. ics sent empty rows
  (`end_stats_from_ledger` false since 10-26; that crash was the `0x219E` fixed in fase3-id) with account 0. Now the
  filled rows go (`end_stats_from_ledger` true), each with its own account IID (`end_stats_unique_accounts`), its 6
  artifact slots, champion DID (+0x1C) and level (+0x20) (`end_stats_upgrades`). No `0x2021` after the match (its
  handler ran a second world teardown while the end page was being filled; `exit_lobby_after_match` false), no
  objects / HUD re-send when the end cinematic ends after the match end (`restore_after_end_cinematic` false), and the
  menu's encounter list again 1 s after the end page closes (`menu_refresh_on_end_page_closed`, P for the empty HOME).
- `tools\diag.py --marcador` (`--timelinekda`): the strip's Flash calls, the K/D/A scorecard and the end page's per-row
  upgrades. Tests: `test_match.py` +9 checks (K/D/A credit, `0x2045` rows, timeline times / re-base / jungle lines),
  `test_session_flow.py` (no `0x2021`).

## fase3-id — the end-of-match score screen no longer crashes the client (2026-10-28)

Tester 12:56 ("the match ended (I surrendered), the score screen should appear"): the game crashed instead, as in the
earlier runs. diag.log: access violation at static `0xA37DEE`, right after the end page was filled.
- Cause (C, `docs/re-notes/end-screen-crash.md`): `0xA37DEE` is in the `0x219E` account-standings handler
  `0xA37DC0`, not in the end page. ics sent the 10 u32 in a guessed order with the encounter DID (`0x40000C82`) in the
  rank slot. The client reads `rank_table[rank]` with no bounds check whenever streak >= the `0x219F` minimum streak
  (sent as 0), so it read 1 GB past the table. The wire order is: last played encounter, rank, previous rank,
  sub-rank, previous sub-rank, position, streak, previous streak, played, won.
- `matchend.ranked_values` sends that order, used at the match end and for the menu's `0x2178` request (which would
  have crashed the same way after a first match). `[ics] standings_layout = "reader"` (`"old"` = the fase3-ic order).
- `tests/test_session_flow.py` checks the `0x219E` shape (61 checks).

Tester 12:56 (same run, Atomic Green Lantern): the jungle creatures still appear with no spawn animation; the
meteorite's lift / throw has no proper animation; a lifted vehicle vanishes (invisible over the champion) and its throw
did no damage (`docs/re-notes/liftables-camps-animations.md`).
- **Lifted vehicle vanishes** (C code, P result): a vehicle is a destructible drawn only through its pieces, whose
  render instances 0x8B builds once, in the world; the attach (containment, 0xB0 flag 0x04) re-parents the object's
  render, not those pieces. 0x630FC0 (run by 0x8B) checks the containment parent first and builds the pieces under the
  parent's render node (0x630BF0 -> 0x7602A0). 0x8B now goes again 0.05 s after the attach and right after the detach
  (`[ics] liftable_attach_rebuild`, `liftable_detach_rebuild`).
- **No damage** (C log): the throw point was 1.8 m from AGL, among his own minions; no hostile stood within the 2.5 m
  blast. The blast does damage a hostile in range (test). No change.
- **Lift / throw animation** (C log, P effect): full champion bundles landed inside the clips: the throw skill's slot
  table 0.27 s into the rock pickup (0.55 s for the vehicle), credits / XP bundles during the carry, Super Strength's
  table back 0.29 s into the throw. The throw skill now rides in the lift's facing bundle (`liftable_throw_skill_at_lift`),
  other champion bundles wait until the carry ends (`liftable_hold_champion_bundles`, `World.update(force=)`), and
  Super Strength's table + the cooldown go 0.9 s after the throw's end (`liftable_slot_restore_delay`).
- **Camp spawn-in** (C data, P effect): table 0x1D000674's Vfx_Spawn_Event02 is only the yellow overlay (render
  effect type 8, mesh 0x17001445); Vfx_Spawn_Alt01 has that overlay plus the sparkle particles 0x18000D90. The camps
  play Alt01 0.1 s after their bundle (`match_camp_spawn_scriptlets`, new `match_camp_spawn_delay`; was Event02 at 0.4).
- `tests/test_match.py` 186 checks (+7: bundles during the carry, 0x8B after attach / detach, the slot restore, the
  rock clip, the camp phase-in key).

- Tester 12:23-12:56 (diag `--mapa --mapa-rellenar --brazo`): the raised terrain closes the socket at x 40 / 120
  (confirmed in game); the diag also reports terrain layer texture 0x1300008C missing from the install (outer blocks
  12BA / 12BC / 13BA / 13BC / 14BA / 14BC, open).
- The vertical stealth fields lean 8 deg toward the lane's centre (blue side yaw 82, red side 98; tester).
- The Shards sphere goes again `[ics] resend_looping_after_scriptlet` (0.35 s) after any other scriptlet on the
  champion (traffic: it vanished with each basic attack's 0x10000128).
- Missiles hit when their line passes within their width + the target's body radius (`[ics] missile_target_radius`
  champion 0.6, unit 0.5; minions / structures their own radius): about half of the Grabs aimed at Deathstroke missed.
- Meltdown's no-damage casts: the homing missile chased Deathstroke 5-6 s into his base, where he is invulnerable (no
  change).

## fase3-ic — no match freeze after a stealth reveal, fewer facing bundles, lower side stealth fields (2026-10-28)

Tester 10:15-10:38 (Crime Alley v AI, AGL vs Nightwing): at some point minions and the enemy champion stopped acting,
the enemy champion could not be seen and minions took no damage; the enemy core could still be destroyed and the
victory came twice, then only the tester could move; no regen in the base; the shield still vanishes on hits; the
vehicle does not show over the champion when lifted; R does no damage to the enemy champion; the vertical stealth
fields left and right should sit a little lower; the jungle creatures appear without their animation; under the base
hologram the emitter piece is missing.
- Cause of the freeze (server.log 10:35:45): fase3-ib's stealth reveal called `self.w` inside `World` itself; the
  AttributeError stopped the match timer and the whole mode layer (minions, bots, auras, match end) for the rest of
  the match, and also broke every skill hit inside a strip (graph "hook 3 delivery failed"). Fixed; a test covers a
  reveal inside a strip.
- Mode-layer tick errors are logged with their traceback and stop the layer only after `[ics] mode_error_limit` (50;
  0 = at the first, as before).
- FaceTarget sends no facing bundle when a standing champion already faces its target within `[ics]
  face_min_turn_degrees` (20; 0 = always): each one re-created the champion and dropped the Shards sphere.
- The vertical stealth fields at the jungle mouths move 1.5 m south (y 84.0).
- Map holes (tester: rescan the map load): new diag mode `--mapload` / `--mapa` (+ `--mapa-rellenar`, `--mapa-todo`);
  the x 40 / 120 socket is four terrain vertices 20 m below the street in record 0x800113BB, not a missing asset
  (docs/re-notes/map-load-holes.md).
- Call for help (tester: attacking an enemy champion must turn its towers and minions on the attacker): the hit
  champion's allied minions and structures re-think at once instead of at their next 0.5-0.8 s retarget, and a
  missile's / spawned object's champion counts as the attacker (`[ics] match_call_for_help_now`, true).
- Checked in simulation (no change needed): item health raises the maximum (455 -> 755 with +300), armor cuts attack
  damage (88.5 -> 57.8 at 73 armor) and power damage, attack / power lifesteal heal 25 % of the hit, Will regeneration
  follows the stat. `tools/champion_check.py --vs-champion` casts every slot at a real enemy bot champion too.
- R (Meltdown) did hit Nightwing on the first cast (165 x 2); on later casts its homing missile chased him for ~4.5 s
  and ended without a hit (he was retreating to his base) - open, to watch in the next test.
- R against an enemy champion (tester: "the champions' R do no damage to the enemy champion"; champion_check
  `--vs-champion --window 5`, details in reverse-engineering.md "Ultimates against an enemy champion"). Generic VM
  fixes, each with its `[ics]` key (all true; false = as before):
  - `defer_graph_hooks_in_chain`: a graph hook raised while a script runs a state's chain is delivered after it
    (Green Arrow's Bullseye cancelled itself; Arcane Zatanna's Runic Gate exploded at once instead of after 5 s).
  - `raise_event_float_param`: RaiseEvent's slot-3 number reaches the receiver as 0xD358722 (Bullseye's arrows hit
    for 5e-31; also BonusShield / HealthDelta / DamageMultiplier / NewDamage of 4 more scripts).
  - `kind_unit_excludes_champion`: IsKind bit 0x100 is the non-champion units (the arrows' champion branch).
  - `zero_damage_probe`: ApplyDamage(0) on a live target reports success (4 scripts gate their real hit on it).
  - `poll_guard_event_reset`: a polled transition may fire again in the next tick after an event moved its graph
    (Dex-Starr's R cat skipped the champion after a minion).
  - `hotspot_box_centered`, `hotspot_follows_position`, `update_before_event_exit`: box hotspots are centred on
    their position, node 0x10000025 moves a hotspot, a state left by an event runs its update first (Mecha Wonder
    Woman's Tempest started 5 m past her; her W box keeps reaching the dash's end).
  - `missile_expire_linger` (5.0 s): a missile whose script is still busy after its expiry stays until its own
    DestroyEntity (The Joker's Last Laugh balloon explodes 0.5 s after landing).
  - `hotspot_status_duration`: the status a hotspot holds gets the hotspot's remaining time (Arcane Zatanna's aura
    divided its damage by 0).
  - `int_compare_32bit`: `==` / `!=` compare integers by their 32 bits (Arcane Supergirl's Rao's Wrath never got its
    charges: 4294967295 vs -1).
  - `ai_move_champion`: AIMoveTo runs a champion at its target and raises 0x1000009D in reach (Atomic Wonder Woman's
    Reclaimer).
  - `top_graph_chains`: a top-level graph's own enter / exit chain runs at script start / stop (69 scripts; Star
    Sapphire's Predator brain read its owner there).
  - `spawned_unit_kit`: a spawned unit with an attack starts its attack script ("Attack: its script is not running").
  - `spawned_class_scripts` += `0x40000AE5: [0x34000562]` (Rao's Wrath missile, C) and `0x400005D2: [0x340001A6,
    0x340003D1]` (Star Sapphire's Predator brain, P).
  - `scriptless_spawn_blast` (P stand-in): Green Lantern's Light 0x40000359 and Nightmare Catwoman's Inevitability
    0x40000D2B (no script anywhere) deal their skill's stat 5 within stat 18 m after stat 14 s.
  Vs the bot champion before -> after: Atomic Wonder Woman 0 -> 312, Mecha Wonder Woman 0 -> 268, The Joker 0 -> 202,
  Green Lantern 0 -> 130, Nightmare Catwoman 0 -> 73, Arcane Supergirl 0 -> 72, Arcane Zatanna 0 -> 40, Dex-Starr
  0 -> 36; with the client's press / second press emulated (`--press-event --recast 1`, new options): Deadshot 215,
  Batman 172, Green Arrow 53 (no server change needed beyond the above). Star Sapphire's Manifest now deals 577 to
  minions (Predator), not yet measured on the bot. No damage node by design: Raven, Nightmare Superman, Arcane Harley,
  Starro, Arcane Green Lantern, John Stewart (placeholder), the self buffs. Open: Aquaman's R (waits 0x100000A9).
  Basic / Q / W / E vs the bot: no slot lost damage (The Joker W 0 -> 27, Star Sapphire W 0 -> 38).

## fase3-ib — Consume eats map objects, shield sphere survives attacks, Grab beam diag (2026-10-28)

Tester 09:33-09:37 (Crime Alley v AI, Atomic Green Lantern, `diag.py --brazo`): Grab pulls enemies now but the
stretched arm is missing; the Shards of Will sphere vanishes while attacking and comes back after the attack; two
towers a side now, but the second still has the black "hole" around it; the lift / throw animations of meteorites and
vehicles look bad; the stealth strips still do nothing; Consume on a vehicle or meteorite does not remove it, so it
can still be lifted.
- Diag `--brazo`: Grab's two beam actions (0x673280) resolve their target to AGL's own IID 0x0200000000000002, so the
  binding is right. The arm is the beam's particle line (0x18000752) between the missile and AGL (grab-beam.md); a
  moving missile got a full bundle every tick, which re-created it and dropped its Vfx_Active. Now a missile gets a
  bundle only when its course turns or it stops, and Vfx_Active plays again after it (`[ics] missile_bundle_on_turn`
  true, `missile_turn_radians` 0.12, `missile_rebundle_scriptlets` ["Vfx_Active"]).
- Vehicles (tester's frames of the original, 10:xx): the gaslight truck moves to the mirror image of the SUV, up-right of
  the left jungle mouth's field (57.7, 93.6); both tilt ~25 deg (SUV yaw 245, truck 115).
- `IsKind` reads an object's own kind flags (0x1000019D: meteorite 0x22, vehicle 0x1080) first; Consume 0x340001C4
  destroys its target only when `IsKind [0x82]` holds. A script's `DestroyEntity` on a liftable fades it out, takes it
  off the liftable list and respawns it after `liftable_respawn_seconds` (`[ics] kind_flags_from_entity`, true).
- Each basic attack's "faces the target" bundle re-creates the champion and dropped what its running scriptlets had
  spawned (the Shards sphere); a key in a `scriptlet_restart` loop now goes again right after any bundle of its object
  (`[ics] resend_looping_after_bundle` true, `resend_looping_delay` 0.05 s).
- Stealth (docs/re-notes/stealth-rendering.md): the client ignores the brush status's IsHidden 0x100007BF and node
  0x1000011E; the owner's look is the champion's Vfx_Status_Stealth_Active 0x10000648 (purple particle 0x18000504),
  which the status script started for only 3 of 6 entries and stopped within 0.5-2 s. The server now starts it on
  entry, signals it off on exit and while revealed, and no longer applies the status (`[ics] stealth_shimmer_key`
  "0x10000648", `match_stealth_status` 0; 0x4800028C = as before). Hiding from enemy clients would be 0x6 0x90F = 1
  (not needed against bots: their AI already skips a hidden champion).
- The stealth tiles play Vfx_Active again next to the hex mesh: the mesh alone is grey (the tester's "white zones"),
  the purple is the Vfx_Active particle 0x18000A57 (`[ics] stealth_tile_vfx` true).
- Still open: the socket at x 40 / 120 (no Crime Alley piece fills it), the lift / throw look (needs a video).

## fase3-ia — no end-of-match crash, bonus scaling, cast holds movement, bot cameras, stealth area (2026-10-26)

Tester 19:22-19:53 (fase3-hz, Gaslight Batman v AI: Zod, Crime Alley): the vehicles look right (slightly rotated);
the game froze and closed at the end of the match before the stats; a defeated bot still walks back from the base lying
down; the invisibility should cover the whole stealth field; Bat Scream cast while moving slides the champion and its
damage scaling looks off; many red "lanterns" chase the champion (killable, no gold / XP); the level ring shows no XP.
- **End of match**: the filled 0x2045 rows (fase3-hx) went for the first time and the client closed; empty rows again
  (`end_stats_from_ledger` false) until the layout is checked (docs/re-notes/end-stats-2045.md).
- **Bonus scaling**: skill scalings on bonus stats (GetAttribute mode 1, e.g. Bat Scream 0.9 x bonus attack damage)
  read 0, the item bonuses being folded into the base; the items' part of a stat now counts as bonus
  (`item_bonus_split`; World.item_part). Bat Scream rank 4 with +100 attack damage: 600 -> 690.
- **Casting holds movement**: move orders during a skill's cast (not the basic attack) wait and the last one runs at
  the cast's end (`cast_holds_movement`).
- **Bot cameras**: the "lanterns" were Surveillance Cameras (0x40000265) that AI: Zod put on the champion at every
  cooldown (32 in the match); bots no longer cast 0x3400019D on enemies (`bot_skip_scripts`).
- **Respawned bots**: the get-up graph event at 0 / 0.6 / 1.5 s with _Combat_GoToLocomotion after the first
  (`bot_getup_delays`, `bot_getup_scriptlets`).
- **Stealth area**: a champion is hidden inside each tile's rotated 4 x 2 m box plus `stealth_margin` (0.5 m); the
  diagonal tiles were tested as axis-aligned boxes.
- **Deep scan (deep-scan-animations.md, deep-scan-s2c.md), first fixes:**
  - Respawn get-up: 0x10000034 is in no champion's main state machine (the client dropped it); _Defeat_OnRespawn
    0x100001FC (every champion: Global_Locomotion 0x100000AA, a wildcard to Locomotion) for the local champion and the
    bots (`respawn_graph_events` = [], `respawn_scriptlets`, `bot_getup_scriptlets`, `bot_getup_delays`).
  - Basic-attack hook times follow the attack speed for speed-bound clips (time x clip speed / attacks per second;
    `hooks_attack_speed`); bots get no graph-hook offset (their 0x8D is not deferred), a stop state before a cast
    (`bot_cast_stop_state`) and their actual attack rate as 0x100006FE (`bot_attack_speed_actual`).
  - Floating damage / heal numbers and the shield layer: 0x42's third list carries the hits of the update (dtype,
    vital, overTime 0, key (character << 7 | team << 4), amount x 16, damage negative) and its second list the shield
    (sum of the vital-2 temp vitals); champions carry 0x10000637 = 0 (`vitals_floaty_numbers`, `vitals_shield_layer`).
  - CC floaties: a CC attribute modifier sends 0x20BD (`cc_floaty_status`: stun 2, silence 1, root 10, crippled 16,
    slow 5).
  - Level-up effect _Advancement_LevelUp 0x10000201 at each level (`level_up_scriptlet`).
  - **Maps (deep-scan-maps.md):** the Raider's padlocked plate is the Power Relay 0x4000089D (ws 0x2E000D12, C: the only
    Crime Alley class of minimap category 26), at the nook (80, 97.25) yaw 180 with 0x100004FF = 2 and the lock bools
    0x100006BD / BC true + Vfx_Locked, unlocked (bools false, Vfx_Unlocked) when the Raider comes (`match_nook_pad`;
    P position / polarity, G timing). Scriptlet tables the first pack does not parse are read from the next pack that
    lists them (0x1D0004A0 / A1: the relays, the Orbital Cannon, the GD control point; 0x1D0003BA / BB: the Destroyer
    drone). Crime Alley's team-2 lane turret is 0x40000C8B (mirror of 0x40000C8C, 2500 health, turret-warning table).
    The dampener folds on graph Death 0x100001C0 (`dampener_graph_events`). Lane spawners 0x2E000D03 on both mouths
    (`match_map_objects`; Tutorial 2 positions).
  - Open from the notes: Zod's R (and 13 other staged skills) cancelled by a timed code 2; the shop-anywhere rule;
    timeline banners 0x10000424; accolades 0x2188; the vehicle carry timings.
- **Crime Alley structures** (tester 2026-10-28: three towers a side where the original has two, and "the tower with no
  floor is not the right one"; crime-alley-structures.md): the map's markers are core (17.5 / 142.5), dampener (40 /
  120) and lane turret (65 / 95) only, and the original minimaps show two structures a side plus the core; the core
  turret at 25.5 / 134.5 (taken from Tutorial 2's half lane) is gone (`match_skip_roles`, C). The dampener is the right
  structure at the socket (P strong); no structure model fills the socket (C), so the textured core pedestal 0x2E000A3B
  is tried as its floor (`match_socket_covers.crime_alley`, G look).
- Tester 2026-10-28 (screenshot of x 40: "that tower is not it either; the one there is the same as at the start of the
  lane"; the pedestal did not cover the hole): Crime Alley's x 40 / 120 structure is a second lane turret, inner
  (requires the outer one, protects the core), with plate and head (`match_role_swaps`, `match_turret_heads`,
  `match_turret_plates`); the pedestal cover is off again. AGL's Grab still shows a projectile, not the stretched arm:
  new diag mode `--arm` (`--brazo`) logs the beam action's resolved target (0x67338E).
- **Graph runtime on** (`graph_runtime` true, 2026-10-28): suites identical, champion_check 0 slots worse / 17 better,
  sequence OK 440 -> 518.
- **0x2045 layout fixes** (end-stats-2045.md, C): the stats block starts at entry +0x78, so every read index was one
  too high (f64 reads 11 / 57-60, f32 reads 65 / 66; deaths 6, assists 7, credits 11, XP 26 ...); the head's second u64
  is the account IID (0 now). Our bytes parse to the last byte; the crash is P in the client's team grid 0xA72860
  (only for rows of team 1 / 2, never run before). Filled rows stay off; `end_stats_team` = false sends them with
  team 0 to tell the two apart. New diag mode `--endstats` (`--estadisticas`, with `--matchend`): the grid builder's
  steps, the last label before an exception is the crash site.
- **XP ring** (hud-xp-ring.md, C cause): the HUD's ring asks its thresholds from GM_Advancement InqXPForLevel
  0x10000011, whose handler nobody registered, so it got 0 / 0 and stayed empty. The player's advancement handlers are
  registered at the link (0x9F 0x81A1000B to the local player, P framing: `advancement_handlers`,
  `advancement_rpc_leading_u8`, `advancement_rpc_blob4`), and the server's XP curve is the game's own table
  (0x49000010 array 0x10000067: 300 ... 20700) with the level cap 19 (`xp_levels`, `level_cap`).
- **Skill graph runtime (2026-10-27, docs/re-notes/skill-execution-model.md; off by default)**. Reported: Zod's R cut
  mid-channel by a timed code 2 (fase3-ia open item), Katana's Thousand Cuts and 20 multi-state basic attacks on fixed
  timings, Batflight ending late. The cast signals (event 0x1000000F, code 1 enter / 2 exit / 3 / 4 / 5) are the
  champion graph's turbineEventHookPayload hooks, which the original server got by running the graph itself.
  - `tools/skill_graphs.py` -> `data/skill_graphs.json` (56 graphs, 156 variants): machines, states with enter / exit
    hooks, transitions and wildcards (flags, conditions), clips (start, speed, playbackSpeed bound to the attack
    speed, loop mode, triggers in local time or end-relative), nested machines, Lua early-outs, the graph events each
    scriptlet key raises (type 0x14 actions of the table entries) and the gate census (42 own script, 7 other script, 4
    via scriptlet keys, 3 no raiser). `data/skill_hooks.tsv` stays for diffing.
  - `ics/graph.py`: a graph per champion (local and bots), fed by every 0x8D ics sends (0x100001E3 + 0x780 and the
    keys' events, so RaiseGraphEvent, death / respawn, CC, skill and basic-attack starts); exit hooks before enter
    hooks, one (code, DID) per transition, clip triggers on the clock scaled by attack speed, DID 0 broadcast.
    Wired in World / CastWorld (`graph_for`, `graph_feed`, the tick for Lua early-outs) and `start_cast`: with the
    runtime on and a graph hooking the script, no timed signals; the timed path still runs if no state of the script
    is entered within `graph_start_grace`, or for scripts that accept no 0x1000000F (Batflight, Violet Harvest).
    Safety nets: `graph_state_timeout` (5 s without activity in a hooked state), `graph_missile_release` (Grapple
    Bolt's missile ends without the 0x10000140 its script waits for), `graph_self_debounce` (Mecha Superman's W
    raised its start event twice in one tick), `graph_fast_forward` + `graph_clip_seconds` (clip lengths unknown).
  - Accept filter: an instance gets only the events of its record's accept list (`script_accept_filter`, on); 0x20EA
    goes through it to the slot script (`skill_client_events_filtered`): Green Arrow R, Deadshot R, Dex-Starr W and
    Flash R see 0x10000023.
  - `python -m ics.script_runtime` no longer crashes in `_graph_cast` on the NullWorld's str owner.
  - Validation: all suites pass with the runtime off and on (scriptvm 65, ics 33, director 43, shop 16, match 173,
    session flow 60, navmesh 13, coverage 549 + 325 clean, new tests/test_graph.py 34). tools/champion_check.py --all
    (new `--graph-runtime`, `--accept-filter` and sequence verdicts OK / SIG / HANG / EARLY2), off vs on: effect
    verdicts DMG 420 -> 427, CHMP 33 -> 39, BUFF 35 -> 36, FX 285 -> 271, REF 7 = 7, no slot worse, 17 better (Zod R,
    Superman R, Deathstroke R, Wonder Woman Q, Sinestro R, Zatanna R, Nightwing Q); sequences OK 440 -> 518, SIG 118 ->
    45, HANG 23 -> 12, EARLY2 0 -> 4.
  - Still wrong with the runtime on: Dex-Starr R (another script's skill_to_locomotion in the tick of its code 5),
    Supergirl W (Empowered_Attack pre-empts the dash state), Sinestro E Cull the Weak and Raven R (held state), Atrocitus
    E and Flash R (held in both modes), Batman R / Blue Beetle and Stargirl basics (code sets differ from the graph's),
    and the skills whose start event ics never raises (timed fallback). graph_runtime stays false until the tester
    has tried it.
- Config (`[ics]`): `match_nook_pad`, `dampener_graph_events`, `match_map_objects`, `vitals_floaty_numbers`,
  `vitals_shield_layer`, `cc_floaty_status`, `level_up_scriptlet`, `hooks_attack_speed`, `bot_cast_stop_state`,
  `bot_attack_speed_actual`, `respawn_scriptlets`, `xp_levels`, `level_cap`, `advancement_handlers`, `end_stats_team`, `end_stats_from_ledger`, `item_bonus_split`, `cast_holds_movement`, `bot_skip_scripts`,
  `bot_getup_delays`, `bot_getup_scriptlets`, `stealth_margin`, `graph_runtime`, `graph_start_grace`,
  `graph_clip_seconds`, `graph_state_timeout`, `graph_fast_forward`, `graph_lua_early_out`, `graph_self_debounce`,
  `graph_missile_release`, `script_accept_filter`, `skill_client_events_filtered`.

## fase3-hz — no crash at the middle camp, longer Shards sphere, camp phase-in, stealth vision, vehicles, /tour (2026-10-25)

Tester 23:08-23:22 and 23:39 (fase3-hy, Crime Alley vs AI): the E sphere shows now but ends too early; Q still shows no
arm; meteorites lift and throw but the carry / throw animation looks odd; the camps appear without their transparent
vortex; the pad under the Raider looked wrong (then: the steel pad with the padlock is the right floor); after killing
the middle camp the game froze and closed; at each jungle mouth the diagonal stealth leg is missing; inside a stealth
zone the champion loses its vision; none of the gallery vehicles was seen. Asked for a tour over the map's elements.
- **Crash** (diag: access violation at rva 0x6B1BD9 the moment AGL's W hit the jungle heavy drop 0x400005E1, which the
  server ran as a fighter: it attacked AGL and got vitals / status icons): script-spawned drops / pads are inert
  objects (`spawned_inert_classes`: 0x400005E1, 0x40000C49).
- **Shards of Will**: Shards_Active is sent again every 1 s until Shards_Stop (`scriptlet_restart`).
- **Camps**: no generic _Entity_OnEnterWorld_Default before their phase-in (`match_camp_skip_enter_world`), which goes
  0.4 s after the bundle.
- **Raider pad**: 0x2E00101D back (`match_nook_pad`).
- **Stealth**: a diagonal tile at each jungle mouth (G numbers); the tiles go as the bare world state again
  (`match_stealth_class` = 0: the hotspot entity's template, unit flags 0x2000 + collision polygon, is P a sight
  blocker for the client's fog).
- **Vehicles**: sent with creation type 7 (the meteorites' type; their world states have 8) and re-sent 1 s / 3 s later
  (`liftable_creation_type`, `liftable_resend`).
- **Grab's arm** (grab-arm-carry.md 1, C): the arm is the beam of the missile's Vfx_Active; the return leg of the
  tether failed the range check and the missile ended 0.05 s after turning back (so `tether_retract` never ran): a
  returning tether flies home (`tether_return_unlimited`), and the Grab missile's Vfx_Active goes in its creation tick
  (`spawned_effect_delays_by_class`).
- **Super Strength carry** (grab-arm-carry.md 2): the object rides the champion's hand through the parent block of its
  movement state (0xB0 flag 0x04: parent IID, mode 0x10, attach point 0x100000B0; C format, P values) instead of bundles
  over the head (`liftable_attach`); the sequence follows the clips (rock: grab 0.22 s, hold 0.30, release 0.26, end
  0.28; vehicle: InitCarPickup on both, CarPickup 0.1, grab 0.11, hold 0.57, release 0.20, end 0.22), with
  CbtState_DisableHit / EnableHit (`liftable_hit_events`), no Rubble_Active (in no champion table) and
  _Combat_GoToLocomotion only for the vehicle; reach 4.5 m (`liftable_reach`).
- **Chat commands** (tester 00:16: /tour did nothing; the client keeps "/" lines for itself, only lines without it
  reached the server): "!" works as a prefix too, and "tour ..." needs none.
- **Vehicles, second try** (tester 12:51 with /tour: no vehicle at its stops, gallery neither): sent as their bare world
  state (`liftable_class_mode` = {"vehicle": "world_state"}), the form Tutorial 1's vehicles show with; the creation
  type override is off again (`liftable_creation_type` = {}).
- **Showroom results** (tester 13:40: drew the tutorial crater, meteors, base / gate rings, turret plates and heads,
  the Leviathan shield, drones, Raiders; not the seven vehicles nor the Raider pad 0x2E00101D; item 114 = 0x2E000D25 is
  the base under the liftable meteorites):
  - meteorite base 0x2E000D25 under each liftable meteorite (`liftable_bases`);
  - vehicles and the Raider pad on the exe patch's carrier class 0x4A + low bits (a bare world state is built and never
    placed, icserver/patcher.py "props"; `liftable_class_mode` = {"vehicle": "carrier"}, `match_nook_pad` class
    0x4A00101D + world state);
  - `vitrina N p` shows item N on the carrier class.
  - **Taken back** (tester 14:05: the game closed while loading the map, right after the nine carrier vehicles were
    created): `liftable_class_mode` = {} and the nook pad as the bare world state; the carrier only through `vitrina N p`.
  - Tester 14:20: the seven vehicle items with `p` close the game too (carrier ruled out for them); item 121 (0x2E00101D)
    draws as the bare world state but is the Raider capsule of other modes, not the padlock pad: `match_nook_pad` = {}.
  - `vitrina N pK` uses carrier slot K (0-5) of the patch's table: slot 3 = 0x4000081B, Crime Alley's own gaslight truck
    entity (slot 0, the Door, has no vehicle components: P the cause of the crash).
  - Raider padlock pad: the nook's four type-3 markers (0x2E000944 / 945 / 1117 / 1120) have no record in any installed
    pack; the only world state with a Locked / Unlocked state is Coast City's Doomsday Device 0x2E0008FD (pack
    0xA0000162, not loaded by Crime Alley) (C).
- **Carrier vehicle crash** (diag --create 14:50, C): CDestructionComponent's start 0x62F960 calls 0x4E1100 on its
  destruction record, which 0x57FCD0 loads from property 0x800; the carrier entity's template has none, so the record
  is null and 0x4E1100 reads [ecx+0x38] on 0 (access violation rva 0xE1101). The vehicle world states carry it
  (0x2E000F04 -> 0x500001F0, 0x2E000559 -> 0x5000000A): `vitrina N pK` now sends the world state's 0x800
  (`carrier_destruction_record`, Data.record_u32). Tester 15:54: no crash any more, the components are created (diag: result 0),
  but nothing draws; the carrier object now goes in the layout's cell 0xFB and is re-sent 1 s / 3 s later, as Tutorial
  1's carrier props that showed (`carrier_cell`, `carrier_resend`). Tester 16:20: still nothing drawn.
- **Vehicles draw through 0x8B** (destructible-vehicles.md, C cause, P result): a destructible (0x800) draws only its
  pieces, which the client builds itself only for creation types 6 / 9; the vehicles (type 8) get event 0x8B (rebuild
  intact) 0.3 / 1.1 / 3.1 s after creation while whole, in cell 0xFB (`destruction_reset_event`,
  `destruction_reset_delays`, `liftable_cell`); the showroom sends it too. New diag mode `--destruction`
  (`--destruccion`): the build checks, the 0x8B handler, pieces built and one render instance per piece.
- Tester: all seven gallery vehicles draw now (in a row, not told apart): `vehiculo N` (1-7) in the chat shows the
  gallery's vehicle N alone in front of the champion (showroom item, its id in the chat).
- Tester's gallery screenshots: modern set south to north = sports car 0x2E000559, police car 0x2E0008B8, white SUV
  0x2E000795; gaslight = arrow cart 0x2E000EFE, lamp pickup 0x2E000F03, van 0x2E000F04, convertible 0x2E000F05. The
  right camp's vehicle is now the white SUV (0x4000045D / 0x2E000795), the left one stays the van; the meteorites stand
  0.5 m higher over their base (`liftable_props_by_map` z 200.5, `liftable_bases` z_offset -0.5).
- **Item stats work in combat** (tester: buying +15 % attack speed must attack faster, lifesteal, damage, armor,
  regen...; measured headless with a script, ics only): the item bonuses reached `ent.stats` and the client's
  modifiers, but
  - the skills load their stats only on 0x10000008 at start, so +50 attack damage / +50 % attack speed changed nothing
    (46.5 damage, 1.46 s); a skill whose owner's stats changed (item, level: `stats_version`) reloads them at its next
    use (`stats_reinit_skills`). Now 96 damage, 0.97 s.
  - attributes a champion record lacks read World.attribute's 1.0 fallback (lifesteal 100 %, CDR 1, resilience 1):
    they start at 0 (`attribute_zero_defaults`).
  - cooldown reduction 0x10000B7B: the skills' StartCooldown takes the plain duration (the original server applied
    CDR itself): x (1 - CDR), capped (`cooldown_reduction_cap` 0.4, G). Q 5.15 s -> 4.26 s with 15 %.
  - resilience 0x100004AA (items 0.15 / 0.3, P: CC reduction): an enemy's status on a champion lasts x (1 - res)
    (`resilience_cap` 0.6, G).
  Health / Will and their regen, armor, lifesteal, crit, penetration and move speed already read the item bonuses.
- **Vehicle placement / stealth on the ground** (tester's frames ours vs the original's): the white SUV at (102.3,
  93.6) and the gaslight van at (38.5, 83.5), both east-west (yaw 270; G from frames); the stealth tiles at the navmesh
  height + 0.03 m instead of the map's base height (`stealth_on_ground`, `stealth_ground_lift`).
- **Load "disconnect"** (tester 16:18: "disconnected from the server" for seconds while the match loaded, then back):
  the showroom prefetch thread overlapped the load; it now starts `showroom_prefetch_delay` (30) match seconds after the
  start, pauses `showroom_prefetch_pause` (0.03 s) per record and keeps the list for later matches on the map.
- **Chat freeze**: the first "vitrina" read ~600 world states on the server thread (28 s, the client dropped out for
  seconds); the list is read in a background thread at match start (`showroom_prefetch`).
- **Red "lantern" following the champion** (tester, every opponent while playing Arcane Zatanna): her companion
  0x40000C25 (script 0x34000652: MaxDistFromZatanna, reattach) was sent with no team and drew as an enemy;
  script-spawned objects carry their creator's team, in the bundle and as a change (`spawned_entity_team`).
- **vitrina** in the match chat (tester 13:00: the tour only moves the champion; show the elements one by one as the
  old server's tour played Batman's actions): each world state of the map's own packs with a creation type the server
  places (3, 7, 8, 9: ~160 on Crime Alley) is created 5 m in front of the champion, the previous one removed, with its
  number, id, type and catalog name in the chat and server.log (`vitrina`, `vitrina N`, `vitrina atras`,
  `vitrina auto S`, `vitrina stop`; keys `showroom_creation_types`, `showroom_packs`, `showroom_distance`,
  `showroom_scriptlets`).
- **/tour** (type `tour` or `!tour`) in the match chat (ics/match/tour.py): /tour = next stop, /tour N, /tour atras, /tour auto S, /tour stop,
  /tour reset. Stops: every non-unit object the server placed, the camps and the lane every `tour_lane_step` m, walked
  from the base; each stop is logged in server.log ("tour stop N").
- Config (`[ics]`): `spawned_inert_classes`, `scriptlet_restart`, `match_camp_skip_enter_world`, `match_nook_pad`,
  `match_stealth_class`, `liftable_creation_type`, `liftable_resend`, `tour_command`, `tour_lane_step`,
  `tour_group_radius`, `tour_stand_off`, `tether_return_unlimited`, `spawned_effect_delays_by_class`, `liftable_attach`,
  `liftable_hit_events`, `liftable_reach`, `super_strength_cast_signals`.

## fase3-hy — bots move with full bundles, Super Strength throws, Grab retracts, Shards sent by the server (2026-10-25)

Tester 22:07-22:19 (fase3-hx, Crime Alley vs AI, video 2026-10-25 22-07-33.mp4, test-2026-10-25-2207.md, diag
`--escudo`): a respawned bot walks back lying down; the bot bought the same item twice; the floor under the dampener is
still wrong (a pale slab now); the meteorites have no crater; they can be lifted but not thrown; no E sphere; Grab shows
no arm, "an invisible projectile"; a grabbed champion is not pulled.
- **Bot movement**: the motion-only state (0x4 with only 0xB0) is not applied by the client (the bot stood up only at
  the next full bundle; nothing moved it between its respawn and its first attack). The throttled updates (velocity
  change, heading > 10 deg, 1 s while moving) now go as full bundles, the death stop too (`bot_motion_only` false).
- **Grab**: a tether that reaches the end of its range with no hit retracts to its shooter before it ends
  (`tether_retract`: the arm is a beam from the missile back to its creator and lasted 0.4 s); each drag step of a bot
  champion bumps its teleport sequence so the client places it (`pulled_champion_snaps`).
- **Shards of Will**: diag C: after Shards_Start the client's run of Shards_Active ends at once (stop flags
  0x28000000) and the sphere 0x2E000C89 is never spawned; the server sends Shards_Active itself again
  (`scriptlet_chained` = {}).
- **Super Strength**: the pick-up's 90 s cooldown greyed the button and the throw press never came. While carrying the
  client shows the slot ready (`liftable_button_ready`; the cooldown is shown after the throw) and the slot's client
  skill table is the sub-skill's ground-targeted one (`liftable_throw_skills`: vehicle 0x480003C9, rock 0x480004A2).
- **Meteorite craters**: the Tutorial's lava crater 0x2E0004BE (+ Vfx_Active) under each meteorite (`liftable_bases`;
  Crime Alley loads pack 0xA000024C, `match_extra_packs`). **Taken back (tester 23:03: with 0xA000024C in Crime
  Alley's 0x20AF the load hung at 10 %)**: `match_extra_packs` = {}, `liftable_bases` = {} (the crater spec is kept as
  `liftable_bases_tutorial_crater`).
- **Bots**: an item counts as owned when an owned item upgrades from it (no second Modular Health Vial (1)); alive they
  shop only inside the base aura (`bot_shop_in_base_only`); a cut recall goes back to "retreat"; Super Strength is not
  cast on enemies (`bot_skip_scripts`).
- Crime Alley dampener floor: the 0x2E0000E3 box is a pale slab, removed again (`match_socket_covers.crime_alley` = []).
- Config (`[ics]`): `bot_motion_only`, `tether_retract`, `pulled_champion_snaps`, `scriptlet_chained`,
  `liftable_button_ready`, `liftable_throw_skills`, `liftable_bases`, `match_extra_packs`, `bot_shop_in_base_only`,
  `bot_skip_scripts`, `match_socket_covers`.

## fase3-hx — AGL's Grab pulls champions, Meltdown keeps hitting, recall snaps, items usable, kill voices (2026-10-25)

Tester 19:28-19:45 (fase3-hw, Crime Alley + Gotham Heights, video 2026-10-25 19-28-07.mp4): AGL's Q does not pull enemy
champions, E shows no shield, R should hit several times while slowing; the boxes under Crime Alley's towers are wrong;
Gotham Heights lacks big pieces of the base ramps and its doors; a defeated enemy champion slides across the map until
it respawns; the kill voice says the same whoever kills; after a recall the champion's image stays where it started
until a click; camps misplaced, the middle floor and the Raider's locked base missing; consumables do nothing and should
refill at base.

- **Grab** (simulated): on the hit the arm's script sets its return speed (SetMissileVelocity), which re-aimed the arm at
  its first point; it "arrived" at once and ended with nothing attached. While a tether delivers its hit a speed change
  only sets the speed, then it flies back dragging the target (a bot is pulled from 7 m to 1.5 m in front of AGL).
- **Meltdown** (docs/re-notes/agl-e-r.md, C): the data pulses the target and its neighbours every PulseDuration and jumps
  once the target has Rads Sickness; one hit gave 3 stacks + Sickness because the passive 0x340002B3's exit chain raised
  0x1000001D on its own script and re-fired the same transition while leaving. A graph now fires no transition while its
  exit chain runs (`exit_chain_reentry_guard`); champion_check unchanged.
- **Defeated bots** get a stop state (speed 0) where they fall: the client kept dead-reckoning their last walk.
- **Kill voice**: the killer is often a missile or a skill object, so both IIDs fell back to the local champion and only
  the team differed; the champion behind each source now goes as killer / victim.
- **Recall snap**: a script teleport (recall, Teleport) bumps the teleport sequence and the local champion goes with its
  player links, as at the respawn (`script_teleport_snaps`).
- **Items**: the client enables an item's button only with its skill block in the champion's slot property (0x100008E5,
  E7, E9, EB, ED, EE for slots 10-15); the shop now sends it (`item_skill_blocks`). The potion line 0x40000925 / 929 / 92A
  (script 0x340004BC: heal 100 / 125 / 150 over 10 s, 1 / 2 / 4 charges) refills its charges when attribute 0x10000459
  (in base, set by the base status) changes: simulated, a used charge comes back at base.
- Crime Alley's tower-base boxes 0x2E0000E3 are removed (`match_socket_covers.crime_alley` = []): the video showed
  them as pale untextured slabs.
- **Gotham Heights base doors and ramps** (docs/re-notes/test-2026-10-25-1928.md 1-2): the client builds every static of
  the map (diag: 422 static builds = the type-7 count), so the black holes at the base exit are server objects: the
  layout pack's two "Door" classes 0x4000026B (team 1, ws 0x2E00084A) / 0x40000269 (team 2, ws 0x2E000845), 20 x 37 m
  with the ramps in their mesh, placed by nothing. They are the map's base gates now, at (26, 54) yaw 180 and mirrored
  (G: the mesh's best fit on the navmesh edges), opened at the start and kept (`gates[].keep`). As they do not block the
  navmesh, the countdown leash stays on.
- **Stealth strips** (tester's screenshots of the original: a champion inside shows a purple hex effect, keeps its
  vision, is invisible to enemy champions and drones until it attacks or is hit, then hidden again): the status
  0x4800028C's script 0x340001CF went straight to its "revealed" state because the VM read enum defaults (type 0xE:
  enum DID, value) as 0 (its mask StealthRevealed = 4); now the value is read (22 scripts carry such defaults) and the
  hidden state plays its effect (Start 0x10000648, enter 0x10000649). A champion that attacks or is hit gets the script's
  "revealed" attribute 0x100006F3 for `match_stealth_reveal` s (its effect stops, leave 0x10000647, and starts again):
  `World.reveal`, `stealth_reveal_attribute`.
- **Crime Alley jungle** (docs/re-notes/crime-alley-jungle.md; tester's frames of the original): the Raider's locked
  base is world state 0x2E00101D (a ~10 m steel pad with a padlock, as Tutorial 2 places it at the same nook, C) at
  (80, 97.66) yaw 180, not the superpad 0x40000CB5; camps at the original minimap's spots: middle on the pad, west
  (48.75, 93.0) on marker 0x2E001118, east (111.25, 93.0) (G +-1 m); first camps at 0:45 (`match_camps_first_by_map`);
  camp units play Vfx_Spawn_Event02, the yellow phase-in (`match_camp_spawn_scriptlets`, P); the middle camp stops
  respawning from the Raider's time and the Raider waits until it is cleared (G).
- **HUD** (docs/re-notes/hud-shop-timeline-kills.md, C reads; tester's frames of the original):
  - Shop "Recommended Artifacts": the client reads 0x2078 once while the HUD loads; it went at load complete, too late.
    Now right after the player link (`recommended_at_link`).
  - Timeline strip: 0x100002AF / 0x100002B1 carry the f64 game time (an IID read as ~0 put every event off the strip);
    the match start / first drones / jungle go as 0x100002AB events (`timeline_start_time`, `match_timeline`).
  - Pre-start clock: (now, match start, 1) so it counts down (`match_clock_prestart_countdown`; it showed 1:00:00).
  - Kill banner "<killer> defeated <victim>": raised by the client from the 0x2039 table, which now carries both
    champions' class 0x10000814 / 813, billboard icon 0x10000816 / 815 (template 0x100001FC), name 0x10000819 / 818 and
    announcer-name id 0x10000823 / 822 (template 0x10000593) (`announcer_entity_fields`); bots are named "AI: <champion>"
    (`bot_name_prefix`).
  - Kill card 0x1000021C in the client reader's layout (5 f32 damage lists, 28 u32 slot lists, 4 StringInfo lists,
    2 f32 type lists; everything after the killer name was shifted), filled from the damage of this life by attacker /
    slot / type (`kill_card_layout`, `kill_card_damage_ledger`).
  - End page 0x2045: one row per player with team, name, bot flag, kills by target type (0x8 / 0x10 / 0x100 / 0x10000 /
    0x40000), deaths, assists, credits / XP and by source, damage dealt / taken / reduced by type, healing, Raider /
    Leviathan / dampener counts (`match_stats_ledger`, `end_stats_from_ledger`). Accolades 0x2188 still empty.
- **Repeated casts**: every R and most W presses were cast twice (the second order 0.13-0.2 s later passed because the
  cooldown starts at the script's cast point); a second order of a slot within `cast_repeat_guard` (0.4 s) is ignored.
- **Crime Alley props** (tester's screenshots of the original, crime-alley-props.md):
  - Meteorites and parked vehicles that Super Strength lifts: none is placed by client data, so the server spawns 5
    meteorites (0x400005C9) and 2 vehicles (0x40000454 east, 0x4000081B west; positions from the frames, G) with Super
    Strength's target flags (0x1080 / 0x22, 0x10000AA7, 0x10000029 as changes) and their spawn scriptlets.
  - The lift (Super Strength's 0x10000037 on a liftable) plays the sub-skill's sequence natively
    (ics/match/liftables.py): pick up, carry over the head (slower walk), the next F press throws it; a vehicle lobs up
    to 9 m and explodes (75 + 20/rank in 2.5 m, slow 2 s), a meteorite flies straight 8.5 m and knocks down the first
    hostile (50 + 12.5/rank, 1.5 s). Respawn with the yellow phase-in after `liftable_respawn_seconds` (60, G).
    `liftable_gallery = true` puts all seven vehicle classes behind the blue base to pick the SUV and the truck.
  - Dampener floor: the 0x2E0000E3 box again, flush with the street (z 198, yaw 0, no team); please send a screenshot.
  - Turret warning ring (green / yellow / red): structures carry 0x10000C5D / 0x10000C5B in the create bundle, and a
    turret's target goes as 0x10000C66 (`turret_warning`, `turret_warning_armed_at_start`).
- Diag: `python tools\diag.py --shards` (`--escudo`) for the Shards of Will sphere (agl-e-r.md: packs, data, order and
  variables ruled out; the sphere is lost inside the client).
- Config (`[ics]`): `liftable_props`, `liftable_props_by_map`, `liftable_props_extra`, `liftable_spawn_scriptlets`,
  `liftable_respawn_scriptlets`, `liftable_respawn_seconds`, `liftable_reach`, `liftable_carry_speed`,
  `liftable_carry_height`, `liftable_throw_arc`, `liftable_throw_steps`, `super_strength_cast_signals`,
  `liftable_gallery`, `liftable_gallery_classes`, `turret_warning`, `turret_warning_armed_at_start`,
  `match_socket_covers.crime_alley`, `exit_chain_reentry_guard`, `script_teleport_snaps`, `item_skill_blocks`, `cast_repeat_guard`, `stealth_reveal_attribute`, `match_nook_pad` (new class), `match_camp_spawn_scriptlets`,
  `match_camps_first_by_map`, `recommended_at_link`, `timeline_start_time`, `match_timeline`,
  `match_clock_prestart_countdown`, `announcer_entity_fields`, `bot_name_prefix`, `kill_card_layout`,
  `kill_card_damage_ledger`, `match_stats_ledger`, `end_stats_from_ledger`.

## fase3-hw — load sequence, tracker locks, under-attack pings, socket covers from the census (2026-10-25)

After the tester's fase3-hv report (animations, the black shape still there, the second map stuck at 10 %), three deep
scans: docs/re-notes/match-load-sequence.md (the client's load 10 % -> 100 %), map-runtime-state.md (what the match
expects once loaded), map-object-census.md (every object of the four maps and who must show it).

- **Load** (match-load-sequence.md, C code reads): 20 % waits until every pack of LoadMatchData reported done; its list
  is field f0 of each 0x20ED entry plus 0x20AF, and ics sent f0 = 0xFFFFFFFF, which can keep the "all present" shortcut
  from firing (the request retries forever). 0x20ED now carries each champion's parent pack in f0
  (`champion_data_match_pack`) and each costume its own grid icon in f9, the champion select portrait
  (`champion_data_costume_icon`); 0x20AF drops 0 / unknown pack ids, one of which fails the whole load
  (`enter_match_check_packs`); in a lobby match the objects go out at 0xCC (level loaded) / 35 %, not at 10 % after a
  10 s timer (`objects_on_level_loaded`, `objects_level_max_wait` 30 s).
- **Match state** (map-runtime-state.md):
  - The sector tracker drew a padlock on every Gotham Heights point, relay and Device pip (lock was always 3): lock 0
    while capturable, 3 only while locked; contender "both" (3, no animation) -> the last capturing team
    (`match_tracker_lock`, `match_tracker_contested`).
  - Gotham Divided's beacon pips: the client shows template slots 1 / 2 only (3 / 4 carry 0x10000A9B, spectator); the
    four beacons map onto 1 / 2 and are sent neutral at the start (`match_beacons.player_slots`).
  - Under-attack minimap ping: the client runs every structure's 0x34000838 itself and blinks its note on 0x100000E7,
    which only the server delivers: event 0x2008 {structure, 0x100000E7, 0x34000838} on a hit of an allied structure,
    5 s apart (`match_structure_ping`).
  - No second victory voice on Gotham Divided / Coast City (their end cinematics' scripts voice it,
    `match_victory_voice_skip`); Crime Alley's single tracker pip gets an initial status (`match_tracker_initial`).
- **Socket covers** (map-object-census.md, C data): 0x2E00119F has no geometry (an attach point: no mesh parts, zero
  bounding box). Crime Alley's dampener sockets get the zone pack's 10 x 20 x 2 m box 0x2E0000E3 at z 198 (P); Gotham
  Divided's pit box 0x2E0003F0 goes on both pits and the six base lane-exit sockets (P). Cover properties now keep their
  type (a float scale went as an int). Coast City's hole stays open until a diag run.
- **Diag**: `python tools\diag.py --visibility` (`--visibilidad`) logs the client's draw check 0x61CB30 (entity, world
  state) and the statics it builds (0x544A50): one run settles the covers, the Gotham Divided pits and Coast City.
- Census corrections: the client creates only static types 7, 8, 21 as entities and 2, 10 as render-only; type 3 / 16
  entries (Gotham Heights 0x2E000006 x10, 0x2E00041F-432 x20, Coast City 0x2E000940 / 941) show only if the server
  creates them (next: `match_marker_statics`). No client static is lost to a missing pack.
- Config (`[ics]`): `champion_data_match_pack`, `champion_data_costume_icon`, `enter_match_check_packs`,
  `objects_on_level_loaded`, `objects_level_max_wait`, `match_tracker_lock`, `match_tracker_contested`,
  `match_tracker_initial`, `match_structure_ping`, `match_victory_voice_skip`, `match_beacons.player_slots`,
  `match_socket_covers` (new entries).

## fase3-hv — the second map's load, bots' items shown, socket covers coloured (2026-10-25)

Tester 17:46-17:54 (fase3-hu): animations still wrong; the black shape did not go; the second map's load stuck at
10 %; the bots still buy no items (and should shop after a recall).

- **Load stuck at 10 %**: after a costume pick (Atomic Green Lantern 0x4000080C) fase3-hu's slot 0x2029 named the base
  champion while the pack list and the match carried the costume; the client never got past 10 %.
  `lobby_slot_base_for_costume` is off again (the slot names the costume, as before). The portrait comes from the
  client's variant -> base map (0xabd0a0 -> 0xa25430); the five extra u32 of 0x2029 only reach the own slot's lobby
  fields +0x1C..+0x2C, not the portrait (C, decompiled).
- **Bots' items**: they did buy (Nightmare Catwoman: 5 buys in the log), but the client got 0x20E2 for the player's
  champion only; each bot now gets its inventory 0x20E2 after every buy and at the in-world resend
  (`bot_inventory_messages`). A recalling bot reaches base and shops there.
- **Socket covers**: both were sent (0x2E00119F at z 200) and the octagon stayed; their only scriptlets are the team
  colour ones, as the turret plate's, so each cover now gets its side's team and the team as a change (P).
- Config (`[ics]`): `bot_inventory_messages`, `lobby_slot_base_for_costume` (now false).

## fase3-hu — minimap icons, recall, using pads, bots shop / unstick / get up, gates, costume portrait (2026-10-25)

Tester 16:12-16:34 (fase3-ht, video 2026-10-25 16-12-42.mp4, all four v AI maps; docs/re-notes/test-2026-10-25-1612.md):
many map elements missing or misplaced (doors, jungle drones, ground parts: black shapes), bots buy no items, some go
down one lane or stay stuck, respawned bots lie on the floor and slide, the back-to-base button does nothing, every
minimap icon shows Batman, picking a skin loses the champion select portrait.

- **Black shapes on the ground** (docs/re-notes/black-ground-shapes.md, C cause): each sits on a terrain socket (terrain
  record 0x80 vertices pushed 20-50 m down so a model can stand in the hole) that no model filled. Crime Alley's two
  dampener sockets get the structure socket 0x2E00119F (Tutorial 2 fills the same socket with it, P); Gotham Divided's
  pits get their lid 0x2E0003F0 as a server object with 0x2A1 = true (the client hides the static lid, P), removed when
  a pod rises there; Gotham Divided's dampeners move onto the six base lane-exit sockets (they stood at guessed spots,
  the gates on the sockets) and the gates step back 8 m towards the base (G). The GD socket cover needs pack
  0xA00002E6 (`match_extra_packs`, off: untested). Coast City's middle hole (75-85, 65-75) is still open (diag in the
  note). Team tint and missing textures ruled out.
- **Minimap icons**: the bots carried Gaslight Batman's map icon 0x13000376 (copied from one template); every champion
  now sends its own template 0x10000083 (the local one too, `champion_map_icon`).
- **Recall**: no champion definition has slot 6 (0x100008E4), so the client sent no order. A recall skill in slot 6
  runs the game's recall script 0x3400000A (8 s channel `recall_seconds`, G; moving or damage cancels; teleport to the
  start point), its block sent as 0x100008E4 (`recall_skill`, `recall_icon` 0 = none). Bots recall when retreating
  far from base.
- **Using pads**: 0x20EE command 1 = use the target object (unhandled.log 16:29:45). An object whose template names a
  skill (0x100009BC: the Crime Alley Raider drop 0x40000C49 -> 0x480010AB) gives it to the user's bonus slot 9 (0x100008F2)
  for its stat 14 (30 s) and goes away. That skill's script fires another slot's skill (node 0x10000136) whose slot is
  open, so it deals no damage yet.
- **Bots**: start with the player's credits and shop while dead too (they bought nothing on the 5v5 maps); a failed
  path goes to the nearest walkable point instead of a straight line through walls; a bot that moved < 0.5 m in 3 s
  re-routes; after a respawn they get up (respawn graph event + enter-world scriptlet, as the player). Headless GD 7 min:
  3-4 items each, 87-98 % of the time on their own lane.
- **Gates**: Coast City's two gates were rotated 90 deg (heading 0 is a wall along y): the north neck's gate is at 90
  deg, the south-east one at 0, so they block. Maps without gates (Gotham Heights) keep the player within
  `pre_start_leash` (12 m) of the start point until the match starts.
- **Champion select**: after a costume pick the slot 0x2029 names the base champion (its portrait resolves); the
  costume stays the pick for the match (`lobby_slot_base_for_costume`).
- **Fog**: neutral jungle units need range only (Crime Alley's nook camp, in a pit, looked empty: the navmesh line test
  never cleared from the street) (`fog_neutral_by_range`).
- **Announcer**: a kill between two champions in the world names them in 0x2039 (empty strip at every kill)
  (`announcer_iids` "champions_real").
- Config (`[ics]`): `match_socket_covers`, `match_dampener_sockets`, `gd_gate_setback`, `match_extra_packs`,
  `champion_map_icon`, `recall_skill`, `recall_script`, `recall_seconds`, `recall_icon`,
  `usable_objects`, `usable_reach`, `bot_recall_distance`, `bot_stuck_seconds`, `pre_start_leash`,
  `lobby_slot_base_for_costume`, `fog_neutral_by_range`, `announcer_iids`.
- Not a server fault: the "You have been disconnected" notice after quitting Gotham Heights mid-match from the menu.

## fase3-ht — bot champions on the map, team tint as a change, Shards sphere, stealth tile mesh (2026-10-25)

Tester 13:13 (fase3-hr, video 13-13-18.mp4): no bot champion in any match (the bots were scoreboard rows only); black
octagon on the dampener and black rectangles by the Gotham Divided gates; no Shards of Will sphere; the stealth tiles
show a "+" and streaks. Request: "a total analysis, nothing left pending".

- **Bot champions** (docs/re-notes/bot-champions.md, C path, P result): every bot slot of a lobby match gets a champion
  agent on the map (`World.create_bot_champion`: own world id, stats, kit, Stolen Powers, running skill scripts, the
  lobby slot's IID as 0x10000064). Its bundle is the local champion's list without the HUD-only ids, plus 0x7D2,
  0x1000000C, the targeting / minimap ids (0x10000AA7, 0x100001C3, 0x1000034C, 0x100004DA, 0x2A1, 0x10000083) and
  0x100006FE; unit flags 0 -> 8, status tags and an ally's vision go as changes 0.8 s later. Death keeps the object
  (LifeState 2 by 0x6 + graph event 0x100000AD), respawn = teleport + LifeState 4; levels by 0x6 (`World.bot_level`);
  regen for every bot; the fog hides enemy bots (and Match.visible_to for stealth); a bot's scripts get the bot as
  "my agent". Movement goes as motion-only states (0x4 with only 0xB0) on a change of path, speed or heading.
- **Bot brain** (`ics/match/bots.py`): lane per slot, push behind the lane's leading minion, fight (weaker or aggressor
  champion, last hits, structures only under minion cover), skills by targeting type and range (lead by missile speed),
  retreat under 30 % or under an uncovered enemy turret, base: heal, buy the loadout's artifacts in order, ranks by the
  loadout's skill order. `tools/bot_sim.py` runs a headless match (Crime Alley 1v1 and Gotham Divided 5v5: casts,
  kills, deaths, respawns, levels 3-4 and buys in 300 s; ~2-9 KB/s of messages).
- **Team tint as a change** (docs/re-notes/stubborn-visuals.md 1, C): the dampener rig and the doors are tinted only by
  `_Entity_OnSetClientRelationship` 0x100003A6, which the client runs from the team listener 0xA813F0 when 0x1000009C
  CHANGES; structures and base gates now get team 0, then their team, by 0x6. The dampener also runs Vfx_AI_Active.
- **Shards of Will** (stubborn-visuals.md 2, P): Shards_Start chains Shards_Active itself; our extra copy replaced it
  and dropped the sphere child. Ours is dropped when the chaining key just ran.
- **Stealth tiles** (stubborn-visuals.md 3, P): the hex mesh 0x2E000D37 is spawned as a prop at each tile instead of
  running Vfx_Active (its particle 0x18000A57 drew the streaks).
- **Status stacking** (docs/re-notes/skill-mechanics-recipes.md 1, C shape / P event params): a re-sent 0x10000006
  switches 189 status scripts back to idle, and the decays' AddStacks(count - 1) added instances (Flash's passive grew
  from 5 to 10). A status that counts stacks itself (waits for 0x100000D7 / 0x100000A8) or does not stack now keeps
  one instance with a stack count: a re-apply raises 0x100000D7 {StackCount} and 0x100000A8 {EffectDuration,
  DurationDelta} and resets the expiry; AddStacks sets the absolute count (0 removes it); GetStackCount sums the
  counts. tools/champion_check.py now uses the server's status resolvers: BUFF 14, CHMP 12, DMG 137, FX 103, REF 4.
- **Map bosses and objectives** (docs/re-notes/map-objectives-recipes.md; classes, radii, kill buffs, line keys and the
  cannon timings C, schedules and positions G; `ics/match/bosses.py`):
  - Crime Alley: the Raider 0x40000CA2 at the nook at 5:00 (lines 696 / 699 / 698), its own script 0x34000670 drops
    the pad 0x40000C49 on death (0x2039 event 61, line 701), back 5:00 later.
  - Gotham Divided: two phase pods 0x40000A79 at 10:00 (685 / 683 / 684, 681); the Raider 0x40000938 out of the upper
    pod a minute later (kill buff 0x48000E4B to the killer's team); then seismic mode: each pod captured by presence
    (6 m, 10 s) runs its four lines; both engaged -> 660 / 653 / 662, the Leviathan 0x40000937 (Leviathan_Spawn, 652),
    kill buff 0x48000E4C, event 60, respawn 6:00 (658 / 659 / 663, Leviathan_Respawn).
  - Gotham Divided beacons: won by killing a buff destroyer (Regen / Haste / Surveillance lead three camps, the Heavy
    Mauler = Pulse): tracker slot 1-4, line activated / upgraded, a status on the team for 180 s; the captured
    0x400003AF beacons (on the pods' pits) are gone.
  - Gotham Heights: the Orbital Cannon 0x40000511 (line 406), captured by presence (4.1 m): event 54, tier N strikes
    on the enemy base (4th: one large strike after 31 s), 125 team health per firing, 65 s neutral, 120 s locked, lines
    419 / 418 at the unlock (0x340002CF's timings). Owned points shoot enemies in 9 m with their attack 0x340000D5.
  - Coast City: the Doomsday Device unlocks at 3:00 (238 / 442 / 244, 234), is captured by presence (5 m, event 51),
    fires 10 s later (440) at the enemy core: strike 0x4000035D, champions 100 + 60 x level, structures 750 + 100 x
    level in 7.5 m (0x340001FA defaults), then neutral and locked 60 s. The Guardian's kill plays event 62; every boss's
    template kill buff (0x10000AC2) goes to the killer's team.
  - Dampeners stay where they fell (Object_Deactivate) until they come back.
  - Jungle units run their own entity scripts (0x10000149 at the spawn, 0x10000007 {KillerIID} at death): the heavy
    drop 0x400005E1 now comes from 0x3400007D on all three maps. Camps heal again once home (a path point was left).
- **Stolen Powers** (docs/re-notes/stolen-powers-audit.md 3 / 5):
  - Meteor Drop (6 versions): the meteor 0x4000044F gets the thrown-object sequence its scripts 0x34000167 / 0x34000347
    wait for (0x1000001D {shooter}, 0x10000049, after the skill's stat 19 a collision 0x10000002 {TargetIID,
    CollisionPosition} with what lies within stat 18, then 0x10000035): it now damages (60 base) and knocks down.
  - Super Strength (6): the pickup 0x10000037 is followed by the lift end 0x100000BB 1.2 s later (the clip's end in the
    original), so the script reaches its carry state; a second press while the script waits for it in a nested state is
    its throw stage, not refused by the cooldown the lift started (`recast_while_waiting`). What the thrown target
    does server-side is still open.
  - Teleport (5): its ally check (T4) reads HasFlagAttribute **0x10000B4A** (the audit named 0x1000104A); allied
    minions carry it (`role_flag_attributes`, P): the 4 s channel and the jump now run.
  - Trap (6): still partial: its entity 0x40000482 has no script in any indexed template (O).
  - Picker: every champion is reported at least at level 5 in 0x209D (`champion_min_level`), the versions' unlock
    rule 0x10000922 (P).
  - A NaN modifier value no longer breaks 0x20F0 (an int attribute modifier is sent as 0).
- Coast City gets its base gates (Door 0x40000557 at the two navmesh necks of each base, G positions).
- A profile icon (0x2093) outside record 0x48000803's list is refused (`validate_protector_icons`).
- Still open after this build: the Trap's trigger, what Super Strength's thrown target does, the ~25 stage / end graph events and the
  start events with no receiver (champion-animation-matrix.md 3.4 / 3.5), 0x100006FE as a multiplier (needs a diag
  probe: the stats panel reads the same property), the rubble rocks and Crime Alley's relay (positions unknown), the
  usable pads' use message.
- **Skill mechanics** (docs/re-notes/skill-mechanics-recipes.md 2-7): champion_check BUFF 14 -> 16, DMG 137 -> 141,
  FX 103 -> 98, REF 4 -> 3, no slot lost its verdict.
  - SetSlotSkill 0x10000089 swaps the slot named by the record's 0x100000E6 (not the caller's, wrong for 9 of 16),
    with the base slot's stats under the record's; ClearSkillStatOverride 0x1000008E restores it; 0x100000A9 after
    both; a scriptless record only overlays stats (Aquaman R refused -> 75 damage, Blue Beetle R's dash forms, Grundy
    E, Catwoman R's Acrobat E).
  - Script local frames are +Y forward (41 offsets are (0, d, 0)); a client target point faces from the caster
    (Arcane Supergirl Q 0 -> 70, Swamp Thing Q 0 -> 40, Dex-Starr R 57.5 -> 107.5).
  - Skill stats add their scaling block 0x100004D4 (Mod x the 0x3B formula's attribute): Atomic Joker Q 1.8 -> 109.4,
    Gaslight Catwoman W, Huntress Q, Mecha Wonder Woman Q, Grundy Q; every item-scaled skill scales in game.
  - Chains: DamageSuccess is written before the damage events, a state's own locals start fresh on entry (Shazam Q
    4 hops, Nightmare Superman E 60 -> 180).
  - Events raised now: 0x100000E7 / 0x10000145 (damage taken / by a champion skill), 0x1000007B (team members on
    TrackTeam), 0x10000016 (respawn), 0x10000097 (takedown / assist), 0x10000106 (a returning missile turned back).
  - Orphan scripts for scriptless spawned objects: Swamp Thing E 0x40000BCA -> 0x340005CB (C), Nightmare Robin Q
    0x40000CA4 -> 0x340004E3 (P).
- **Script VM**: a polled transition fires at most once per tick (the Doomsday pad livelocked 2424 times); RaiseEvent on
  the raising instance arrives after its chain (the cannon controller skipped its neutral phase). champion_check: no
  verdict change, 54 s instead of 76 s.
- Config (`[ics]`): `match_raider`, `match_pods`, `match_cannon`, `match_beacons`, `match_kill_buffs`,
  `match_kill_buff_seconds`, `match_boss_kill_events`, `match_dampener_keep_body`, `match_point_attack`,
  `match_point_attack_range`, `match_device` (mode "capture" and its keys), `run_jungle_scripts`,
  `run_jungle_scripts_roles`, `thrown_spawn_classes`, `raise_event_follow`, `role_flag_attributes`,
  `champion_min_level`, `validate_protector_icons`, `recast_while_waiting`, `set_slot_skill`, `local_y_forward`,
  `skill_stat_scaling`, `damage_success_first`, `reset_state_locals`, `spawned_class_scripts`, `damage_family_events`,
  `team_member_events`, `respawn_script_event`, `takedown_script_event`, `script_poll_once_per_tick`, `raise_event_self_deferred`, `status_stack_model`,
  `bot_champions_in_world`, `bot_brains`, `bot_motion_only`, `bot_player_objects`,
  `bot_retreat_health`, `bot_decision_interval`, `bot_reaction`, `bot_skill_chance`, `bot_aggression`, `bot_sight`,
  `bot_behind_minions`, `bot_vision_radius`, `bot_vitals_hz`, `bot_shopping`, `bot_lanes`, `team_as_change`,
  `scriptlet_chained`, `stealth_tile_direct`; `match_structure_scriptlets` dampener + Vfx_AI_Active.
- Tests: test_match 154 (7 bot checks, 16 boss / objective checks); champion_check BUFF 16, CHMP 12, DMG 141, FX 98,
  REF 3.
- To check in game: a nameplate with name, level and a red / blue bar on each bot; right click on an enemy bot attacks;
  its run animation with motion-only states (else `bot_motion_only = false`); its skills play on its model; the dampener
  and the GD gates coloured; the Shards sphere.

## fase3-hs — Grab pull, loop guard, profile icons, structure start effects (2026-10-25)

Tester 13:13-13:22 (fase3-hr, Atomic Green Lantern on Crime Alley, Gotham Heights, Gotham Divided; video 2026-10-25
13-13-18.mp4; docs/re-notes/test-2026-10-25-1313.md): few improvements; animations and map parts still missing;
asked for a deep pass on each champion's animations and each map's objects, all Stolen Powers, and profile icons.

- Video: the Grab arm shows now (v113.0) and Scorched Earth plays slam -> crater -> blast; turrets fire, waves and camps
  spawn, stealth strips work, the menu returns without error. Still: no bot champions in any match, Grab does not pull,
  no Shards sphere, black rectangles by Gotham Divided's gates (like Crime Alley's dampener octagon), Consume (stolen
  0x48000815) does nothing, the passive repeats its chain ~24 times per hit.
- Grab pull: the walking forced move was cancelled by the grab's own stun ("stopped (crowd control)") and the unit AI;
  the pull now places the target along the line every 0.05 s (Missile._return).
- Loop guard: a script instance that gets the same event more than `event_loop_limit` (4) times within 20 ms drops the
  rest (AGL's passive re-entered "any -> S2 on 0x1000001D" 66 times for one basic attack in the simulator).
- Profile icons (docs/re-notes/profile-icons.md, C): the picker (CallingCardDialog, 5 slots) lists only type-3 items of
  0x20B8, and none were sent; the 134 protector icons of record 0x48000803 / 0x10000848 now go, owned
  (`send_protector_icons`, `own_all_icons`); an account without slot 0 gets 0x40000AE3 (`default_protector_icon`).
- Structure start effects (docs/re-notes/map-manifests.md, C tables): the core world states have no Vfx_Startup /
  Vfx_Active_Blue / _Red (dropped) but Vfx_AI_Active; core turret and lane turret bodies Vfx_Active + Vfx_AI_Active;
  foundry Vfx_Startup + Vfx_Active (`match_structure_scriptlets`). Per-map manifests list what else the original
  server created (Raider, phase pods, Orbital Cannon, buff destroyers, Coast City gates ...).
- Stolen Powers (docs/re-notes/stolen-powers-audit.md: 65 records, all accepted headless; 9 working as is): a version's
  stat list (0x100004B4, deltas only) replaced its base power's whole list in Data.stolen_power, so 50 versions had no
  damage / range / cooldown (cooldown 0: spammable, no 0x20F8, wrong tooltip); merged stat by stat (0x100004B6) now
  (`stolen_stat_merge`; headless 42 working / 12 partial / 11 broken). Open: Meteor Drop (spawned 0x4000044F waits
  for the launch sequence), Trap 0x40000482 (no template found), Super Strength (0x100000BB end of lift), Teleport
  (0x1000104A target flag), the client picker may allow only the 12 base powers (champion level 5 rule).
- Animations (docs/re-notes/champion-animation-matrix.md, 54 champions, C client facts: 0x6097E0 alone writes Propel /
  Turn from the replay step; the client never stops by itself; a same-class bundle does not reset the graph but
  replaces every property; the Lua early-outs end a skill on Propel > 0 / Turn != 0):
  - a stop state before every champion cast (`cast_stop_state`; 114 of 216 casts sent none);
  - champion scriptlets 0.13 s after the bundle (`champion_scriptlet_delay` 0.06 -> 0.13) and the graph hook times
    shifted by the same (`graph_hook_offset`), so the stop / facing state lands before the graph event;
  - a script's skill_to_locomotion (0x10000002) is dropped for `keep_cosmetic_tail` 0.8 s after a state that leaves on
    skill_to_cosmetic (29 scripts cut their own tail);
  - AttachEntity is (parent, child) (`attach_parent_first`: Arcane GL's lantern dragged the champion; Grab attaches
    the target to the missile). champion_check: DMG 136 -> 137.
  - Open: ~25 stage / end events (Doomsday Charge, Comet Grab, Lasso, dashes ...), 9 start events with no graph
    transition, 0x100006FE sent as attacks per second (graph default 1.0, to confirm with diag).
- Object descriptor (docs/re-notes/skin-overlay-fix.md, C): the u32 after the class in a 0xF2 bundle is a world-state
  override compared with entity+0x110 (ChangeWorldState 0x54D5C0 when different), not a sequence; ics sent 1, 2, 3 ...
  (a world-state switch request on every bundle); 0 now (`descriptor_world_state_zero`). The costume overlay is not a
  re-create (a create for a live IID builds nothing; a missing class record fails, no fallback): `diag --skins`
  (`--aspectos`) logs constructions / bundles / world-state changes / model setups to find the overlaying entity.
- Scoreboard (docs/re-notes/bot-champions.md, C): lobby rows carry "iid", not "player" / "agent", so the human's row
  had no agent and his kills / deaths / assists / credits never counted; bound to the champion now
  (`match_attach_human`). Bot champions in the world: design in that note (next build).
- Map objectives (docs/re-notes/map-objectives-recipes.md): only 0x340002CF (GH cannon), 0x340001FA (Doomsday pad),
  0x34000670 / 0x3400007D / 0x3400051A / 0x3400051B (death drops) drive objectives; the Raider / pods / Leviathan /
  beacons / relays / Device / dampener timings were C++ match logic (authored config). Next build.

## fase3-hr — Grab pulls the target, crater before the blast (2026-10-25)

Tester 10:34-10:41 (fase3-hq, Atomic Green Lantern, video 2026-10-25 10-34-37.mp4): "Unable to connect to Match" every
time back at the menu; the countdown announcer is still silent; map parts still missing; AGL: Q moves AGL to the enemy
instead of pulling the enemy to AGL, W shows the blast before the crater (should be slam, crater, blast), E still has
no shield sphere, R nearly fine.

- Announcer lines (docs/re-notes/dialog-shield-disconnect.md 1, C): 0x2001 -> dialog vt+8 0xa7ff20 -> 0xa13c90 plays
  only from the encounter's conversation catalogue (template 0x10000B21, loaded by 0xa35dc0), which no PvP template
  has; the keys are lines of the announcer sets. Now 0x2039 with property 0x100003BD = the line key (0xa77da0 ->
  0xa596b0(key, channel)): the shared lines 0x9C / 0xBB / 0x97 / 0xAE / 0xAD on channel 1, or on channel 3 after
  0x202A `u8 0 | u32 0x4000047A` loads the shared set where the template lacks 0x10000803 (Crime Alley v AI); the
  map's own lines (waves, jungle) on channel 2 (`announcer_line_mode`, `announcer_shared_lines`,
  `announcer_load_shared_set`).
- "Unable to connect to Match" (C): the gmConnectionManager tick 0xa9af20 is a 60 s watchdog armed by every accepted
  0x2016 (0xab9080 -> 0xa9aa50); the at-launch 0x2016 armed it after the game connection was up, so it fired when 0x12D
  tore the world down (cm+0xC8 = 0): dialog 0xac5010 + teardown 0xabc480 closed everything (the fase3-ev bug, back
  with lobby_transition_at_launch). Exe patch: 0xa9b102 jne -> jmp (file 0x69A502 75 35 -> EB 35); run
  `python ic.py patch`. The lighting / sky-pack lead was wrong.
- Shards of Will (P): its status sends Shards_Active 0x10000886 and Shards_Start 0x1000088C in one tick; a later
  scriptlet on the object replaces the running one, so Active now goes 0.15 s later (`scriptlet_delays`).
  ShieldPercentage 0 is right (bonus from nearby targets); table 0x1D0003D7 is reachable through AGL's main table.
- Grab: the tethered missile ended at its hit (S9 -> S2 in 0.03 s), nothing pulled the target. A tethered missile that
  hits now flies back to its shooter, dragging the target to 1.5 m in front of him (forced movement), and ends there
  (0x10000005) (`tether_return`, `tether_drag`).
- Scorched Earth: the crater's Vfx_OnInit and Vfx_OnExplode went 0.1 s apart; Vfx_OnExplode now 1 s after the object
  appears (`spawned_effect_delays`).
- Tester 11:27 (video 2026-10-25 11-27-25.mp4): countdown voice / captions, drone and jungle lines, gates until the
  start and the menu without error all work now. Still: no Grab arm and the drone and AGL swap places on a hit; the
  blast still too early; the Shards particles show but not the sphere; map parts missing.
  - Grab swap: AttachEntity(SELF, Target) in the missile script attached the SHOOTER (_real), who then followed the
    target; a missile now attaches itself (`attach_missile_itself`).
  - Arm / tethers (agl-visuals.md 1, C): the missile's Vfx_Active beam (action type 2, exec 0x673280) ends at the
    object's own 0x100004E2 = its creator; missiles and spawned objects now carry it (`missile_creator_property`; 271
    such bindings in the packs).
  - Crater (agl-visuals.md 2, C): Vfx_OnInit (0x2E000C99 scorch) schedules Vfx_OnExplode (0x2E000C90 blast) 1.5 s later
    itself (timed group in table 0x1D0003D8); the server no longer sends OnExplode, and removes the crater after 3 s
    (_Hotspot_Fizzle, then 0x3) (`spawned_effect_scriptlets`, `scriptless_spawn_lifetime`).
  - Shards sphere (agl-visuals.md 3, P): world state 0x2E000C89 spawned by Shards_Active (action 0x0C, exec 0x6852B0)
    behind a gate on 0x1000033E (ShieldPercentage, 0 at base); floor 0.01 (`scriptlet_variable_floors`).
  - Map (crime-alley-still-missing.md): the core's team-colour cylinder (Vfx_Startup / Vfx_Active / Vfx_Active_Blue or
    _Red; it got no scriptlet) (`match_structure_scriptlets`); stealth tile yaws were swapped (centre yaw 0, mouths 90).
    Still open: the dampener's black octagon (P: property group 0x8A5 / 0x8A3 / 0x8B2), red rubble rocks, the core
    platform "prow"; the lava cracks are probably art of another build (the Clash video of the same map lacks them).
- Coverage sweep (docs/re-notes/sweep-*.md):
  - Client events (sweep-c2s.md): telemetry and load steps answered silently (0x20BE / 0x20B4 / 0x214F / 0x211B /
    0x20D3 / 0x207A / 0x00CC); 0x00DA (a networked scriptlet the client asks for on an object it does not own) played
    by 0x8D on that object (`remote_scriptlets`); 0x20AB hold position; 0x212C artifact slots and 0x20D1 selection kept.
  - HUD (sweep-flash-hud.md) / UI (sweep-s2c-ui.md): StopProcessingNewBillboards 0x100002BC before the result
    (`match_stop_billboards`); full-protocol.tsv's status column is stale (100 rows marked "not sent" are sent).
    Next: kill card 0x1000021C, timeline icons / banners, Recommended widget only in base (0x10000A23), 0x20E2 for all.
  - Kill card (sweep-flash-hud.md 2.1): notice 0x1000021C to the victim on death (killer + assisters as live entities,
    icons, teams, killer name; damage columns zero, P) (`match_kill_card`).
  - Backlog: docs/re-notes/sweep-summary.md ranks everything the six sweeps found (P1 / P2 / defer, done / open).
  - Properties (sweep-property-listeners.md, C): property -> graph variable map from the 0x1C records (0x300 Propel,
    0x1F1 Turn, 0x100001BF TargetHeading, 0x100006FE Attribute_AttackSpeed (the only one the server sends), 0x10000936
    AnimationSpeedMultiplier ...); units now carry 0x100006FE (`unit_attack_speed_property`).

## fase3-hq — lighting per map, minion vision (2026-10-25)

Tester 08:55-09:04 (fase3-hp; Gotham Heights 0x40000B6C, Coast City 0x40000B6A, Gotham Divided 0x40000B6B, Crime
Alley): with Crime Alley's outdoor lighting key the fog of war is drawn now, but the minions see too far; the other
maps are almost black. A fifth match in the same client session: the client closed all three connections ~4 s after
0x20AF (no server error; open).

- Lighting key 0x956 per map from each map's victory script (map-loading-deep-scan.md 1): Coast City 0x1000001B ->
  0x0800001B (pack 0xA00000D2), Gotham Divided 0x1000001C -> 0x0800001C (0xA00000FC), Gotham Heights 0x1000000A ->
  0x08000008 (of 0x1000000A / B / D) (`lighting_env`).
- Minion vision: their template carries two 0x10000133 radii (3.0 and 6 / 7 / 8 by type); the smaller one now
  (`match_minion_vision` "min"; "max" = before).
- Map gap analyses (docs/re-notes/map-gaps-gotham-divided.md / -coast-city.md / -gotham-heights.md), first batch:
  - Gotham Divided: base gates (Door 0x40000557 at the static frames 0x2E000EE1, side 3 / 5) and base aura.
  - Coast City: base auras on the spawn platforms 0x2E000CA5. Doomsday Device: 0x10001096 / 0x10001097 were the PAD's
    keys (table 0x1D000924), sent to the device: the device now gets Vfx_Active / Vfx_Locked / Vfx_Unlocked /
    Captured / Vfx_OnFire, the pad Start 0x10001125 / Active 0x10001096. Relays show their beam on the holder's core
    (Vfx_Relay_0N_Start / Active / Stop on world state 0x2E0013EE) (`match_relay_beams`).
  - Gotham Heights: Power Cores 0x400003F2 at (18.39, 50.08) yaw 15 / (142.67, 50.33) yaw -20 (invulnerable: the team
    health is theirs), foundries moved behind the starts (G), base aura 0x4000041F, end cinematics 0x3500000D / E;
    lighting key 0x1000000D at the start (P).
  - Capture points / relays: Vfx_TeamColor_SetContention 0x100008C4 / SetNull 0x10000B0D instead of BeingCaptured /
    Captured / Lost, which they do not accept (`match_capture_scriptlets`).
  - Announcer sets per map (`announcer_events_by_map`): Gotham Divided turret 36 / 37 / 33, dampener 38 / 40 / 48,
    core turret 55, reactivating 64 / reactivated 63, no core % lines; Coast City relay captured 50 / neutralized 59.
- Announcer (docs/re-notes/announcer-and-map-elements.md, C from the packs):
  - Sets per encounter (0x10000802): CA 0x40000D4C, GD 0x40000554, CC 0x40000534, GH 0x4000047E; shared 0x4000047A.
  - announcer.line(): a set's 0x1000082A line goes to the acting team, 0x10000829 to the other; the old order played
    our own victory as "Defeat" in the 2001 / both modes. "Under attack" events have only 0x10000829.
  - Crime Alley ids corrected (the ear test skipped the six silent "under attack" events): turret bot 33, top 36,
    mid 37, dampener 40, relays unlocked 49, relay captured 50, core turret 55, unlock soon 58, raider 61, dampener
    reactivated 63 / reactivating 64, was_shutdown 52; Coast City relays 57 / 50 / 59 / 49 / 58 / 66.
  - New triggers: plain kill (event 30) when no other line; "under attack" for turrets 31 / 35 / 34, core 32, core
    turret 56, dampeners (CA 41, GD 47 / 41 / 39), once per `match_under_attack_gap` 15 s; wave lines per map (CA / GD
    672 / 670 / 668, CC 231 / 247 / 233, GH none: the keys live in each map's layout pack) and jungle online 673 / 669
    / 671 before the first camps (`match_wave_lines`, `match_jungle_lines`); relay capturing.
- Skill animations (docs/re-notes/animation-deep-scan.md, C): each champion's Havok behaviour graph (0x1A packfile in
  its parent pack; the 0x1C record of 0x5B5 only maps global event ids to graph indexes) notifies a
  turbineEventHookPayload {skill script DID, code} on entering a skill state and from its clip triggers: 1 start,
  2 exit, 3 hit (a_SkillHook), 5 missile out (a_MissileFireHook), 6 hold = the scripts' OnCastSignal codes; the
  client never reads them, the server must time them. ics sent 5 / 3 at 0.25 s and a fake 2 at 0.40 s, which raised
  skill_to_locomotion and cut states that leave only on it (Grab's loop, channels) and every cosmetic tail.
  tools/graph_hooks.py dumps the hooks of all 389 skill states into data/skill_hooks.tsv; ics sends 3 / 5 / 6 at the
  graph times and 2 at the state's exit trigger (no self-ending trigger: `graph_exit_fallback` 3 s); chains of
  different timed states (Katana R) keep the fixed timing (`graph_cast_timing`). champion_check: DMG 134 -> 136
  (Arcane Green Lantern Q, Arcane Zatanna Q), no regression. Still open: the graph's Property_* variable ids
  (Propel / Turn end cosmetic tails on any move / turn: diag probes in the note), clip durations, ~40 stage events
  (LassoGrab, Comet Grab, Bullseye ...).
  - Next (not done): bot champions in the world with an AI (every 5v5 map shows them only on the scoreboard), Gotham
    Divided phase pods -> Raider -> Leviathan, Gotham Heights Orbital Cannon (script 0x340002CF), the Device's aimed
    shot (skill 0x4800064A), dampener reactivation in place, jungle families, stealth positions on the big maps.

## fase3-hp — kit audit fixes, countdown lines, default keymap, gate side, stealth class, nook pad (2026-10-25)

Tester 23:48 (fase3-ho, Atomic Wonder Woman): audit every champion's kit; emotes only on the top-row numbers by
default; the stealth zones still look wrong; map textures missing; the middle camp has no floor; no countdown voice
or captions. Notes: docs/re-notes/kit-audit-1.md / -2.md / -3.md, crime-alley-visuals.md, countdown-keymap-gaps.md.

- Kit audit (54 champions, simulator + static scans), general VM fixes:
  - 0x1000008A {TargetIID, slot 0x31D944} on a Q/W/E/R hit (21 scripts / 7 champions) (`skill_hit_event`).
  - 0x100000ED {attacker 0xC89C7B4} on the damaged entity (29 scripts) (`owner_damaged_event`).
  - 0x10000196 {Slot} on all the owner's scripts when Q/W/E/R is used (Huntress, Flash, GL, N. Catwoman passives)
    (`skill_used_broadcast`).
  - Death: 0x10000012 on the dead entity, 0x10000007 on each of its statuses (then ended), 0x10000098 {victim
    0x9A6A765} on the killer (`death_script_events`).
  - A launched entity collides at its target (Huntress Q, Blue Beetle E) (`carried_arrive_collision`).
  - A spawned entity's scripts get ShooterIID (Lex Luthor R drones did 0 damage).
  - SetSkillAttached counts the entity itself as a target (AWW R, Nightmare Robin R, Zatanna R ...).
  - HasFlagAttribute 0x1000006A is a predicate inside AnyOf / NOT / triggers (it ran as the action, always true: 40
    scripts incl. the shared stun / knock statuses 0x34000130-132, Starro R, Zatanna R, Superman E); as an action it
    sets the bool attribute on the ENTITY, read by its other scripts (Gaslight Batman E marks 0x100003AB, the echo
    reads it; test_scriptvm's Batman E now expects the plain first hit, 40) (`predicate_first_in_conditions`).
  - 0x1000008C {VitalExpiredHandle 0x09E49315} when a shield drains; 0x1000011B {KillerIID 0x032C3FD4} when a type-0
    defeat guard stops a lethal hit (Nightmare Superman / Grundy could never die) (`damage_pipeline_events`).
  - A polled "any -> X" no longer re-enters X on a result code either (Starro: ~700 scriptlets / 3 s)
    (`any_reenter_on_code` false).
  - champion_check: DMG 133 -> 134, BUFF 12 -> 13, CHMP 15 -> 16. Still open: status stacking model (6 champions), SetSlotSkill
    swaps (Aquaman R, Blue Beetle R, Catwoman R, Arcane Harley E), frame convention +Y forward (Arcane Supergirl Q),
    cast end for states with a recast (Batman R, Dex-Starr W), ratio damage stats, scriptless spawned objects (GL R/E,
    Gaslight Catwoman E, Mecha Superman E, N. Catwoman R, N. Robin Q), missile turn-back 0x10000106.
- Countdown (countdown-keymap-gaps.md 1, C): the captions are announcer line keys of table 0x2B000093, played only by
  conversation 0x2001 (the 1vAI encounter script 0x34000628 did so): 0x9C 60 s, 0xBB 30 s, 0x97 10 s, 0xAE "Match:
  Initiating", 0xAD "The match has begun!"; first wave 231 / 247 / 233 (`match_countdown_lines`, `match_wave_lines`).
- Default keymap (C): pack 0xA0000038 record 0x22000004 (rows u16 device | u16 DIK | u32 meta | u32 activation | u32
  action; meta Ctrl 0x40000000, Alt 0x20000000), merged over the file at every start; `python ic.py patch` now also
  patches it (icserver/patcher.py PACK_PATCHES: emotes Alt+Numpad1-5 -> Ctrl+1-5 + the stored deflate's Adler-32,
  backup .orig). tools/keymap.py also drops the numpad lines.
- Base gates: side 0x100007A2 (3 blue / 5 red) lights the wall (Object_Closed switches on it) (`match_base_sides`).
- Stealth tiles: the hotspot entity 0x4000039D with world state 0x2E000D36 (`match_stealth_class`).
- Nook: superpad 0x40000CB5 at (80, 97.25) yaw 180 + Vfx_Active_Pad (P) (`match_nook_pad`).
- Dampener: Object_Activate + Vfx_Active (it had no scriptlet) (`match_structure_scriptlets`).
- Recommended / countdown / AWW from fase3-ho kept. Lava cracks still unexplained (no record places them).
- Lighting (docs/re-notes/map-loading-deep-scan.md 3, C mechanism): 0x7E35C0 takes the player's 0x956 and looks it
  up in the region environment table 0x04000000 (pack 0xA0000038): ics always sent 0x10000016 -> 0x08000016, the
  cinematic setup; Crime Alley's outdoor one is 0x10000002 -> 0x08000003 (blue sky ff87b5ef, blue-grey ambient, in
  pack 0xA00002E5). Now per encounter (`lighting_env`, Crime Alley encounters 0x10000002, default unchanged).
  Map loading pipeline documented end to end; lava cracks: not the landblock blend mask (uniform), decals are a local
  render option; Crime Alley's emitter world states 0x2E00110F/1110/1118/111B/1121 exist in no installed pack.

## fase3-ho — charge passives (owner block, signed spends, resource vitals), countdown, stealth rules, jungle camps (2026-10-24)

Tester 22:54 (fase3-hn, Atomic Wonder Woman, recording 2026-10-24 22-54-44.mp4 + the original 2v2 video
videoplayback.mp4): missing map sections; the stealth zones are elsewhere and must hide a champion from the enemy
unless the enemy is in the same zone or the hidden one attacks; AWW: W does not empower the next basic, E always does
the 2-charge circular slash, Q can be recast at once; the gate must stay until the countdown ends, the announcer counts
down; the Recommended panel must follow purchases. Notes: docs/re-notes/aww-kit.md, crime-alley-2v2-video.md,
crime-alley-video-compare.md.

- AWW (variant 0x400003EC; charges = vital 6 "Rev", max 2): four VM bugs, general (aww-kit.md):
  1. Source-2 operands are the entity's owner block, shared by all its scripts (the passive writes the threshold ctx
     0xD4; Q / E / the W status read it as 0, so `VitalThreshold(0)` was always true). Instance vars first, then the
     block (`script_owner_block`; 332 of 875 scripts use source 2).
  2. SpendCost 0x10000031 adds its signed amount to its own vital [values[0]] (Rev +1 drained Will) (`spend_by_vital`).
  3. Each champion's resource vital type from its twin's 0x1000000C (Will 5 for 43; Rev 6 AWW / Huntress; 4 Atrocitus,
     Dex-Starr, Doomsday, Nightmare Robin; 1 Batman, Nightmare Batman, Shazam; 7 Katana); a non-Will resource starts
     empty, no `will_regen` (`champion_resource_from_data`).
  4. A basic attack's hit raises 0x1000008B {TargetIID} on the attacker's scripts (W status 0x3400026A; Zod, Arcane GL)
     (`basic_hit_event`). Simulated: Q one jump + 18 s below 2 Rev, two at 2; W then basic 80 dmg +1 Rev; E cone below
     2. champion_check: BUFF 2 -> 12, DMG 133 unchanged.
- Countdown: the clock is set to 42 s before the start when the intro cinematic ends (`match_pre_start_after_intro`;
  `match_pre_start` 13 -> 60 only bounds the wait); the gate opens at 0; voice names match_starts_30 / _10 /
  match_start wait for their announcer ids. The 2v2 video is Clash (0x40000E68 / E74: outer turret = win, core drained
  by credits / kills); vs AI 0x40000C82 keeps dampener / core turret / core.
- Recommended: 0x2078 re-sent after each purchase without held items (`recommended_follow_inventory`); the original
  moves to the next item (video 7).
- Stealth: 6 tiles of 0x2E000D36 (two north and two south of the centre along the lane, one per jungle-passage mouth;
  G from the original video, no placement in the data); a champion inside is unseen by enemy units unless they stand
  in the same tile, or for `match_stealth_reveal` 2 s after it hits an enemy unit / champion.
- Jungle: camps at (52, 90) and (113, 90) besides the nook (1 big 0x40000CA1 + 2 small 0x40000CA0).
- Plates: the dampener and core turret lose the fase3-hm plate / head (core turret template = 0x2E000AC4).
- Emotes also on Ctrl+1-5 (tools/keymap.py, fase3-hn). Handler error no longer drops the match (fase3-hm).
- Open (video compare): orange lava cracks / ember craters and red rubble piles absent (landblock data 0x810113BB /
  0x800113BB?), the dampener's black octagon base, the base gate unseen during the countdown.

## fase3-hn — emotes on Ctrl+1-5 (tools/keymap.py) (2026-10-24)

Tester 01:09-01:36 (fase3-hm, Supergirl): emotes work (Alt+Numpad); they should be on the top-row numbers, since many
laptops have no numpad. Map parts still missing and skill animations still wrong (details asked).

- tools/keymap.py rewrites Documents\InfiniteCrisis\infinitecrisis.keymap (backup first): Ctrl+1-4, bound to DoNothing
  in the in-match section, become Dance / Joke / Laugh / Taunt and Ctrl+5 Oath; Alt+Numpad kept. Run with the game
  closed (the client rewrites the file). Alt+1-6 stay SmartSelfCastItem.
- Server side the stealth strips (8 x 0x2E000D36), the core turret head / plate and the dampener plate were all sent
  and the champion entered / left the strips; what shows on screen is to be confirmed with screenshots.

## fase3-hm — emote handler fixed, handler errors keep the match, stealth strips, core turret head and plates (2026-10-24)

Tester 00:53-00:56 (fase3-hl, diag --emotes --target, Supergirl): emotes do nothing, the second tower out of the base
still has no floor, the stealth zones (seen in the video) are missing.

- Emotes: the client DID send them. diag --emotes: input 0x68A8E0 -> code 0x60AB70 -> player script 0x564060 -> RPC
  native 0xA1C90 -> 0x9F built 0x1624F0, and the server received `06 00 97 81 | 04 00 00 00 | 3f 02 00 40`
  (0x81970006, n 4, Dance 0x4000023F). ev_script_rpc crashed on `self.cfg.get` and read the message one byte late (no
  leading u8): fixed, both forms read.
- That exception closed the game connection (the match ended). A client event handler's error is now logged and the
  connection kept (`handler_errors_keep_connection`).
- The core turret 0x40000C8D is the same turret body 0x2E000AA0 as the lane turret: it now gets the head 0x2E000AA8 and
  the plate 0x2E000A9F; the dampener the plate (`match_turret_heads`, `match_turret_plates`).
- Stealth strips (crime-alley-missing-elements.md 1.3): 8 tiles of world state 0x2E000D36 (Vfx_Active) at the video's
  positions (G); a champion inside gets the brush status 0x4800028C and the AI does not see it beyond 2 m
  (`match_stealth*`).
- Costume overlay (docs/re-notes/costume-model-overlay.md): a costume is a full replacement (own world state /
  entity setup / mesh), the base pack shares only five byte-identical records, and the server never names the base
  after 0x20AF; the client can keep the base pack from LoadCharactersHeavy 0xA6FCD0. Leading hypothesis (P/O): the
  champion is created at 35 %, before the costume pack is loaded, and re-created in full later. Not changed yet.
- diag --target: the turret (0x210), dampener (0x810) and core (0x4010) pass every step of 0x9d01d0 (ACCEPTED).

## fase3-hl — data move speeds, structures unlocked by bundle, emotes by chat, camp turned (2026-10-24)

Tester 00:12-00:40 (fase3-hk, diag --graph, AGL / Arcane Harley): the jungle camp must turn 90 degrees counter-clockwise
and sit a bit higher in the wall hole; emotes do nothing for any champion; Batman still shows the base model over the
costume; some animations look wrong, maybe because the champions move too fast; some map elements still missing;
after the first turret no structure can be attacked (only minions).

- diag --graph: the stop signal for a live scriptlet run reaches the client (0x57B510 / 0x57C4B0 hit 100+ times).
- Move speed: every champion walked at [ics] move_speed 4.5 m/s; the data's 0x100005E4 is 3.65 (Gaslight Batman), 3.8
  (AGL), 3.9 (Arcane Harley), + 0.005 per level. recompute_stats now sets it (items and slows kept)
  (`champion_move_speed_from_data`).
- Structures: after the turret fell the dampener got 0x100007D9 = true (0x6) and the op 6 modifiers, yet the clicks
  on it never became attack orders (no 0x20EE). The unlock now also re-sends the structure's full bundle carrying
  0x100007D9 = true (`match_unlock_bundle`; P: the template's 0x10000249 -> 0x100007D9 link is read when the object is
  built).
- Emotes: no 0x9F reached the server although the keymap binds Dance..Oath to Alt+Numpad1-5. `diag --emotes`
  (`--gestos`) logs the path (input 0x68A8E0, code 0x60AB70, player script 0x564060, RPC native 0xA1C90, 0x9F build
  0x1624F0). Meanwhile /dance /joke /laugh /taunt /oath (bailar broma reir provocar juramento) in the match chat play
  the emote (`emote_chat_commands`).
- Crime Alley camp: yaw 180 (the earlier 180 -> 90 turn was clockwise on screen) and 1 m deeper, (80, 99.7).

## fase3-hk — turret targeting line released, structures reached at their edge (2026-10-23)

Tester 23:03-23:18 (fase3-hj, diag --graph, Atomic Green Lantern then Gaslight Batman): the second match of the same
client session loads now (0xEB resend confirmed: LOBBY -> LOADING -> PLAYING at 23:11:55). The turret's targeting line
stays on a champion until it dies or the turret falls; Atomic Green Lantern could not attack the turrets (Batman
could); emotes (Ctrl+number) asked for.

- diag --graph: every 0x8D cast scriptlet's graph event reaches the graph (100 "delivered", index 6 / 7 / 9 / 0x10 ...,
  none unknown; 4 queued while the graph loaded). Entity flags +0x118 = 0x49 (bit 0x40 set, bit 8 set, so not dropped).
  The animation path on the client is therefore complete.
- Turret line: a turret whose target walked out of range dropped it in `Units.act` without Target_Lost 0x1000002C (only
  a target change in `think` sent it), and Vfx_Targeting kept looping on the head. Every drop now goes through
  `_drop_target` -> Target_Lost, and the head plays Vfx_Stop then its team's Vfx_Active_Blue / _Red
  (`match_turret_lost_on_drop`, `match_turret_lost_head`).
- AGL vs turrets: the attack orders arrived (`attack turret mid t2 (3000/3000)`) but the basic attack script 0x340002B6
  never started: World._attack_step measured the reach to the structure's centre, which a short-range champion cannot
  reach through the 1.6 m navmesh footprint. The reach now counts to the target's edge (match unit radius), and
  CastWorld.radius returns the same radius for the scripts' hit shapes and IsInRangeAndAngle (`attack_reach_to_edge`).
- Emotes (docs/re-notes/emotes.md): the client's keymap (Documents\InfiniteCrisis\infinitecrisis.keymap) binds them
  to **Alt+Numpad1-5**; Ctrl+1-4 are DoNothing, so nothing reached the server. The key runs the local player's
  CEmoteSystem 0x28F:1, which finds the record in the EmoteDirectory 0x40000012 and sends event 0x9F message 0x81970006
  with the emote record DID; nothing plays locally. ics now handles 0x9F (`ev_script_rpc`) and raises the graph event
  (Joke 0x1000022E, Taunt 0x1000022C, Laugh 0x1000022D, Dance 0x100001F1) on the champion; Oath plays the
  Emote_Oath_Start scriptlet (guess) (`emotes`, `emote_graph_events`).
- Skills play only their start (tester 23:20, AGL: Q's arm never stretches, W's crater never shows and its circle stays
  forever, E's sphere never shows, R's marker never shows; docs/re-notes/skill-second-stages.md):
  - The cast end (2) came 0.15 s after the cast point and moved every AGL skill to S2 (skill_to_locomotion, EndSkill)
    while Grab's tethered missile was still out. 2 now waits for the cast's tethered missile, up to 4 s
    (`cast_waits_tether`), and the tethered missile's own script gets 0x10000005 when back
    (`missile_own_return_event`).
  - SetSkillAttached 0x10000005 now raises 0x10000022 (attached) / 0x10000014 (failed) on its script
    (`attached_skill_events`): Grab's missile reaches S9 (AttachEntity, the target cowers 0x100002BA, AGL's pull
    0x10000331, Vfx_Event1). Also unblocks the same wait in 6 other kits (champion-kits-status.md 6).
  - StopScriptletKey 0x10000012 only logged: the server now keeps (entity, key) -> instance number of each 0x8D run
    and re-sends that entry with signal bit 1 (`stop_scriptlet_signal`; P for the wire form): Scorched Earth's circle
    0x100008AB, and every other kit's stopped loops.
  - Missiles and spawned skill objects were bare classes: they now carry their world state, scriptlet keys and 0x7D2
    tables, and their effect keys no script plays are run (`spawned_object_tables`, `spawned_effect_scriptlets`:
    Vfx_Active, Vfx_OnInit, Vfx_OnExplode): Grab 0x40000485, Meltdown 0x40000484, the crater 0x40000487.
  - Open: Shards of Will's sphere. Its status script sends Shards_Start / Active / Stop (table 0x1D0003D7, referenced
    only by pack 0xA0000150's record list, like Smash's 0x1D0003D9, which does show); ShieldPercentage 0x1000033E is
    (shield - base) / base = 0 at base, as the data computes.

## fase3-hj — 0xEB before every later match (second match stuck at 35 %) (2026-10-23)

Tester 22:32-22:35 (fase3-hh exe patched this time, diag --shop): the first match loads (shop built at "local player
ready", 210 items), the second of the same client session stays at 35 % again; no object was finalised in it, so the
shop hook was not the cause (docs/re-notes/second-match-load-hang.md).

- Cause (C): the world teardown 0xa99b60 -> 0x7d14b0 -> 0x635250(0, 0) clears the client's local player IID
  [0x1b6a710]; only 0xEB (0x64b2e0) sets it again, and ics sent it once, at login. With IID 0 the player object is
  never local (0x64dac0 queues every 0x02 IID until it is), 0x69bd90 never runs and the 55 % step 0xa0a570 is skipped.
  The old server re-sent it (icserver `[match] resend_local_player`, fase3 "Replay"). ics now sends 0xEB again in
  ConnectToLobby (0x20F2) before every match after the first (`resend_local_player`). The pack release / reload of
  packs named in both matches and the exit flow (0x2021) were checked and are not involved.
- Client script instances (docs/re-notes/client-skill-instances.md): any 0x200F / 0x2062 / 0x200C / 0x2043 crashes this
  client build before its body is read (network path ctor 0x44BD00 leaves the record pointer 0, then 0x461510 ->
  0x448BE0 reads [0+0x44]): `skill_script_mirror` and `status_mirror` must stay False. The client creates the slot
  instances itself (0xA9F9F0 -> 0x979860 -> 0x9789C0, from each slot skill's property 0x1000063A = the aiming-decal
  scripts 0x3400020B ...), driven by 0x20C9; the cast animation therefore comes only from the server's 0x8D.
- tools/diag.py `--graph` (`--grafo`): where a started 0x8D's graph event dies (graph component missing 0x27299D,
  entity flag 0x40 0x15BD43, queued 0x15BD82, delivered 0x15BD9F, unknown event 0x15AF83), plus the client slot
  instances (0x5789C0) and 0x20C9 (0x616E60).

## fase3-hi — skill script mirror off (crash at load complete) (2026-10-23)

Tester 22:24 (fase3-hh, diag --scripts): the game closed right after load complete. diag: first-chance 0xC0000005 at rva
0x48BE3 (stack 0x44BD95, the script instance ctor area, 0x838FE7, 0x83D56B, 0x843DAB ...) immediately after the eight
0x200F client copies of the skill scripts. `skill_script_mirror` is now False; how the client gets its skill-slot
instances is being analysed (docs/re-notes/client-skill-instances.md). The re-queue fix of fase3-hh is untested.

## fase3-hh — shop build moved off the 0x20AF handler (second match stuck at 35 %), client copies of skill scripts (2026-10-23)

Requires `python ic.py patch`.

Tester 20:31-22:03 (fase3-hg, diag --scripts): still no skill animations with Atomic Green Lantern; after leaving a
match, the next one (Gaslight Batman vs a Starro bot) stayed at 35 % (the client kept its heartbeats; the server's
messages matched the good load; the game was closed 50 s later).

- diag --scripts: every 0x8D sent to Atomic Green Lantern was accepted (100 orders, result 0 = started, including his
  Grab keys 0x10000899 / 0x1000089A / 0x10000890): the keys resolve; what they show depends on the client's own copy of
  the skill script (skill-animations-and-skins.md 3.1).
- Skill scripts are mirrored to the client at load complete: 0x200F (effect_add, the status-effect form, empty variable
  store) per kit slot script on the champion, so its copies play RunScriptlet / StartScriptlet / RunFx /
  RaiseGraphEvent locally when 0x20C9 "skill used" arrives (`skill_script_mirror`, P).
- Shop catalogue: function F ran inside the 0x20AF handler, where the client also releases the previous match's packs;
  the second match of a client session hung there (P). F now runs from a hook at the entry of 0x69bd90 (local player
  finalised; only caller 0x64dac0, once per match load, after the packs and ~3 s before Flash asks for the items):
  cave R (VA 0x6c0002) reads the encounter from [[0x1b763c0]+0xc4] and calls F, then the moved prologue. The 0x20AF
  hook and cave T are gone.

## fase3-hg — every scriptlet with its variables, hit / persistent FX, champion script tables (2026-10-23)

Sweep (docs/re-notes/skill-animations-and-skins.md) after the tester's "the champions' animations and skins do not
show completely": no pack is missing (a skin needs only its heavy pack + the champion's parent pack, which the client
also loads by itself from 0x20ED metadata, LoadParentRPs 0xA99370); the gaps were in our 0x8D messages.

- `scriptlet_variables` True: the scripts pass variables to 124 scriptlet keys (target IID 0x10000030, speed
  0x100009EB, fx 0x1000050A, 0x1000049D, 0x100003FF ...) and the tables bind them; only 7 keys got them.
- TargetHit 0x1000007A has no client half (0xAB4D80): its hit scriptlet (VFX_CBT_Hit_Shared 0x10000223) now goes with
  variable 0x1000050A = values[5] (normal fx record) or values[6] (critical); 445 nodes in every champion.
- StartScriptlet 0x10000103 (client half 0x9CE300) goes with its nested variables and 0x1000050A = its 0x1E fx record
  (persistent FX: auras, channel loops); record DIDs without a known kind are typed as DIDs.
- The champion carries instance property 0x7D2 = its template's scriptlet tables + its world state's
  (`champion_script_tables`, P): 56 keys resolve only through the world state's tables (AGL's passive...).
  Data.record_tables reads 32 KB into a template (0x7D2 sits past +0x1600 in some).
- Correction (fase3-hc): 0x36000009 / 0x3600002C are Havok ragdoll packfiles, byte-identical in every pack (the sizes
  compared before included the records stored after them); `local_champion_pack_last` stays but the collision is
  harmless. The base variant's heavy pack is never needed for a costume.

## fase3-hf — base gate removed after opening (2026-10-23)

Tester 19:21 (fase3-he): the blue gate shows in the intro cinematic, vanishes at the start, yet still blocks the way
(the champion's moves stopped at x 28.6; the server's navmesh was open, Object_Open sent at 19:22:03). The client keeps
the door's collision after Object_Open: the gate object is removed `base_gate_remove_after` (1.5) s after it opens.
Skill animations / skins still incomplete: a full client + data sweep is under way
(docs/re-notes/skill-animations-and-skins.md).

## fase3-he — walkers on the ground, item bonuses on the HUD, graph-event animations (2026-10-23)

Tester 18:33-18:40 (fase3-hd, Atomic Green Lantern): the champions appear and walk above the floor; their skills have no
animations; items do not change health / attack speed / damage; scenery still missing (the blue base gate, the white
zones that make a champion invulnerable).

- Height: the champion's / units' z came from the spawn point (200.3) or the clicked point (up to 200.7, the picked
  geometry), while the floor is ~200.08 (navmesh). NavGrid keeps each cell's height (`height(x, y)`), and walkers take
  it at every step and in each bundle (`ground_from_navmesh`).
- Animations: Atomic Green Lantern's scripts animate through 0x100001E3 (_HFSM_BehaviorRaiseEventAction) with variable
  0x780 = the graph event; the variable was dropped (36-byte 0x8D, the graph event's own form is 47). 0x100001E3 joins
  `shot_scriptlet_variables` and enum variables are typed (0x780 as enum). `scriptlet_variables` stays off for the rest
  (on 2026-10-21 Batman lost animations with them).
- Items: the HUD's stats are attributes (template base + attribute modifiers); the server's stat properties and its own
  numbers held the bonuses (sim: Nil Cloak takes Atomic GL from 500 to 600 health) but the client never saw a modifier.
  Each item bonus now goes as 0x20F0 (op 9 add / 10 percent), the previous ones removed by 0x20E8
  (`item_client_modifiers`).
- Scenery (docs/re-notes/crime-alley-missing-elements.md): no pack is missing; the base gates and auras are objects the
  server creates. Base gate Door 0x40000557 / 0x2E000CD7 per team at the base exit (29.5 / 130.5, 77.5; P), team set,
  Object_Closed (its light wall 0x2E000CD8) and blocking during the countdown, Object_Open and unblocked at the start.
  Base aura Base 0x40000C7F / 0x2E000A35 on each spawn platform (radius 6), Hotspot_Activate; allies inside get status
  0x48001109 (regen, in-base 0x10000459, may shop, speed), leaving gives 0x48001107; with `base_aura_invulnerable`
  they take no damage inside (`match_base_gates`, `match_base_auras`, `base_aura_status`, `base_aura_leave_status`).
  Not done yet: the purple hexagon strips (probably stealth brush 0x4800028C / 0x2E000D36), three jungle camps in the
  original (x 50 / 80 / 111), and our guessed core turret at x 25.5 that the original minimap does not show.

## fase3-hd — every champion vs AI, turret shot back, bots off my champion (2026-10-23)

Tester 17:10-17:29 (fase3-hc): the shop works (diag: Flash got 210 items; items bought, credits shown); the turret
shots vanished; one model still shows over another; only the first turret can be attacked; a cast's range indicator
stays until another button is clicked; Batarang bounce differs; portraits still vanish when a skin is chosen; no fog,
the drones give no vision; the camera shows the lane diagonally (original video: straight, left to right). The
"Recommended / Build" panel is part of the original HUD (seen in the video). Requests: every champion playable vs AI
(skills, animations, skins), then every Stolen Power and the other maps.

- Turret shot: `match_turret_shot_extra` back to ["0x1000029D"] (now with the 0x10000030 / 0x100009EB variables).
- Bots: `bot_pool_all_champions` (draw from every champion with a kit) and `bots_avoid_my_champion` (a bot playing a
  variant of my champion takes another one when I pick: two variants' model packs collide, fase3-hc).
- Fog / vision (docs/re-notes/fog-vision-runtime.md): the server hid enemies by the champion's sight only; every
  allied unit / structure with a vision radius is a source now (`fog_allied_vision`). The client stores 0x10000133 only
  on a change (unit component +0x8C, default -1) and counts a source only when its flags 0x1000019D match 0x1F4978:
  the radius goes again as 0 then the value by 0x6 for allied units / structures and the champion, plus the champion's
  0x1000019D = 8 (`vision_as_change`). The dark overlay's gates (0xAAE5B0) need no server value; if it stays off,
  `diag --fog` traces them.
- Range indicator (docs/re-notes/targeting-indicator-and-structures.md): the client targeting script shows it on
  0x10000023 (node 0x10000056, 0xa5dab0) and hides it on 0x1000001D / 0x10000009 (node 0x10000022, 0xa4f0c0), and only
  S->C 0x20C9 delivers 0x1000001D. World.cast now sends 0x20C9 (agent, slot, 0x1000001D) after a cast and 0x10000009
  after a refusal (`skill_used_event`).
- Structures: the order check 0x9d01d0 reads 0x10000249 / 0x10000029 as base + modifiers; the dampener / core turret /
  core link 0x10000249 to 0x100007D9, which did not move it. unlock_structures also sets both by a modifier (op 6,
  0x20F0) (`match_unlock_modifiers`). P; `diag --target` on the dampener would confirm.
- Camera (docs/re-notes/pvp-camera-yaw.md): the isometric camera takes its yaw (degrees) from f32 0x1000011E on the
  followed champion at its start (0x96AABF) and watches it (0x968F30); no game data carries it and ics never sent it.
  Crime Alley's intro 0x3500003C ends on heading 0 (straight lane), Tutorial 1's on 45. The champion now carries it in
  its creation and again after load as a change (`camera_yaw` {"0x40000C82": {"1": 0.0, "2": 180.0}}; team 2 a guess).
- tests/test_session_flow.py waits up to 10 s for 0x2016 (nine different bot champions take longer to launch).
- Champions: tools/champion_check.py (new) simulates every champion in Crime Alley casting slots 0-4 on a minion
  (and on a dummy champion), docs/re-notes/champion-kits-status.md has the per-champion table. Before the fixes: every
  basic attack works, 117 / 270 base slots deal damage, no script error or unknown node. Fixed in ics/:
  RaiseEvent [event, script] reaches only that script (`raise_event_script_target`; Cyborg's basic attack fired all
  his skills, 257 such nodes in 164 scripts); missile templates' script list searched past false record starts
  (`missile_scripts_past_starts`, 25 projectiles get their damage); IsInRangeAndAngle without a max range has no
  distance limit (`range_angle_needs_max`, cone skills); the champion's scripts get init event 0x10000088 at creation
  (`champion_init_event`, Arcane Green Lantern's Lantern); a polled "any -> X" transition does not re-enter X
  (`polled_any_no_reenter`, Starro's ~240 scriptlets a second). After: 134 / 270 deal damage, 84 other effects, 11 only on
  an enemy champion, 6 no effect, 4 refused. Still open: champion-only skills need enemy bot
  champions in v AI matches; events 0x10000022 / 0x10000014, 0x1000008B, 0x100000A9; 18 projectiles without scripts.

## fase3-hc — costume packs order, lane pathing round turrets, Bat Scream width, deaths in place, camp (2026-10-23)

Tester 16:13-16:22 (diag --shop, fase3-hb): the minimap is right (LoadMap(0x40000C82) from cave N); the shop's
catalogue is built (0xa908f0 -> 0xa8ebb0 with list 0x48000EA9) but the foundry still lists no items; a costume shows
parts of another model; the camp should turn right and stand deeper in the hole; minions walk through turrets;
buttons do not dim without Will; Bat Scream must hit everything its wave touches; turret / Batman / ranged minion
shots fly straight instead of homing; drones walk away while dying; Bat Flight wrong with some skins.

- Costumes: the model packs of one champion's variants carry the same DIDs with different content (0x36000009:
  68 KB in Samurai 0xA000010C, 46 KB in the base 0xA0000076, another in Android 0xA00002F3) and the last pack loaded
  wins: first the bot's Android pack hid the Samurai's mask, then (fase3-hb) the base pack put the base model over it.
  The base model pack is no longer named; the local champion's model pack goes last in 0x20AF
  (`local_champion_pack_last`); the parent pack stays (`champion_shared_packs`).
- Minions: every lane leg that crosses a blocked footprint (turrets) goes round on the navmesh (`match_lane_pathing`).
- Bat Scream: a missile's hit radius is its skill's stat 22 (3.0 Bat Scream, 1.25 Sonic Batarang, 1.1 Bat Flight;
  P: width), at least 1 m (`missile_radius_from_skill`, `missile_hit_radius`). Simulated: the wave hits every enemy
  minion on its line.
- A dead unit's movement is cleared before its death bundle (`unit_death_in_place`).
- Crime Alley camp 1.5 m deeper (80, 98.7), yaw 90 (G); `match_camp_overrides` {"0": {"pos": [x, y], "yaw": d}}.
- Shots (docs/re-notes/projectiles-homing.md): basic-attack projectiles are client visuals of the shot scriptlet's
  projectile action (type 2, exec 0x673280), which takes its target from variable 0x10000030 (IID) and its speed from
  0x100009EB (f32); `scriptlet_variables` False (2026-10-21) dropped them, so every shot flew along the facing. The shot
  scriptlets now always get them (`shot_scriptlet_variables`: turret 0x100002E0 / 0x1000029D, ranged minion
  0x10000326, Batman 0x10000188 / 0x10000189 / 0x1000017E), plus 0x108; `match_turret_shot_extra` is now [] (0x100002E0
  runs 0x1000029D itself).
- Will (docs/re-notes/skill-button-will.md): the champion's secondary vital type 0x1000000C = 5 (Will) goes in its
  creation (read once by the vitals attach 0x972940; without it the client kept Health only and compared costs with
  Health), and 0x100000CE = true by 0x6 after load and each champion re-send (listener 0xaafcd0 sets [vit+0x64], so
  UI_NotifyVitalChange reaches Flash and the buttons dim; the client sets it itself only for non-0x02 IIDs, 0xa16807)
  (`champion_secondary_vital`, `vital_notices`).
- Shop, requires `python ic.py patch` (docs/re-notes/shop-ui-items.md): Flash reads the item list once, when the HUD
  movie loads (query 0x100002CC -> 0xa44fe0 -> U+4), before cave S built it. The 0x20AF handler now builds the
  catalogue as it stores the encounter: hook VA 0xa99f3f -> cave T (VA 0x6c0004) -> function F (VA 0x13f8fd2:
  0xa908f0 on [[0x1b758d4]+0x80], registers kept). tools/diag.py --shop breaks at 0xa45001 (items count when Flash
  asks). Item stat bonuses are applied by the server (World.recompute_stats), the client only shows 0x10000684.

## fase3-hb — minimap and shop from the exe's HUD cave, costume packs, turret base plates (2026-10-23)

Requires `python ic.py patch`.

Tester 15:40 (diag --shop): the minimap is still wrong, the HUD has no background, the shop has no items, the Samurai
costume shows without its mask, the turrets lack their base.

- Minimap: diag showed LoadMap 0xa4c2c0 called with 0x40000991 from rva 0x611fd3, which is **our own exe patch**
  (cave M in `icserver/patcher.py`, 2026-10-14) pushing a fixed Tutorial 1 DID; the map listener 0xa6a8e0 never ran
  for the 0x100001D3 events (it is a per-entity note listener, attached by the key-0x26 broadcast; the player is not
  one of its entities). Cave M now jumps (always, so a map left by an earlier match is replaced) to cave N (VA
  0x8c4f7e), which reads the match's encounter from `[[0x1b763c0]+0xc4]` (stored by the 0x20AF handler 0xa99f00)
  position-independently (call/pop; the exe is relocated at run time) and loads that map; Tutorial 1 stays the
  fallback when the value is 0.
- Shop: the shop listener 0xa91670 has the same problem. Cave N goes on to cave S (VA 0xb1bf72), which calls the
  catalogue build 0xa908f0(encounter) with ecx = the Upgrade manager `[[0x1b758d4]+0x80]` (game systems from
  0xa91e30; the listener calls it with its sub-object - 0x4c): template 0x1000081E -> 0xa8ebb0 to the UI.
- The mid-match player re-creation (fase3-ha) reached no listener and is off: `player_rebind` "none",
  `player_recreate_delay` 0.
- Costumes: the Samurai pack 0xA000010C points at textures / parts in Batman's parent pack 0xA0000122
  (0x13000372-77, 0x170001BD, 0x1A0000FF, 0x1C000014) and the base model pack 0xA0000076, neither sent when both
  players wear costumes. 0x20AF now names each champion's parent pack and, for a costume, its base model pack
  (`champion_shared_packs`).
- Turrets: the cinematics place TurretBasePlate 0x2E000A9F under each turret; the match spawns it under every
  turret (`match_turret_plates` {"turret": 0x2E000A9F}).
- HUD background: not addressed yet (to check after the minimap patch).

## fase3-ha — ics: structures attackable (flags as a change), skills start at rank 0 (2026-10-23)

Tester 15:00-15:10 (fase3-gz): diag --target ACCEPTS the dampener (flags 0x810) and the core (0x4010) now that the unit
flags go again as a change; the respawn countdown shows. Still: the HUD has no background, the minimap is wrong, the
shop path is never reached (0x100001D3 = 0, then the encounter, by 0x6 to the player), and every skill was active from
the start.

- Map load / shop (static analysis): the shop (Upgrade manager 0xa904d0) and the map manager (0xa6a230) register
  under event-registry key 0x26 ([0x1B6BCE8]+0x28); their property handlers 0xa91670 / 0xa6a8e0 attach to an object
  only on a key-0x26 broadcast of its bundle (0x69bd00, from 0x64bd30 for an existing object with the object
  manager's +0x11C set, or 0x64dac0 when an object is finalised; the latter also raises key 4 "local player ready" for
  the local player). Our player object came while the client was loading, before the managers existed (they come at
  match start, 0xa91e30), so 0x100001D3 events reached no listener: no catalogue, no LoadMap 0xa4c2c0 (minimap
  record 0x48000E36, map info [0x1B758F4], so no fog either). In a lobby match the player (and champion) bundle now
  goes again `player_rebind_delay` 1 s after the match-start notice 0x10000205, then 0x100001D3 = 0 and the encounter
  (`player_rebind` "bundle"; "recreate" removes and recreates the player object). tools/diag.py --shop now also breaks
  on 0x69bd00 / 0x69bd90 / 0x64dac0 / 0xa6a8e0 / 0xa4c2c0.
- Tester 15:22 (diag --shop with the map breakpoints): the rebind works (key-0x26 broadcasts for the player and every
  object, the map property listener 0xa6a8e0 runs), but LoadMap 0xa4c2c0 ran with **0x40000991** (Tutorial 1) in a
  Crime Alley match: the login's 0x214B said Tutorial 1 was last played. 0x214B now goes again with each 0x20AF with
  the match's encounter as "last played" (`last_played_at_match`). The shop handler 0xa91670 still did not run.
- Tester 15:29: LoadMap still got 0x40000991 although the 0x214B "last played" went with 0x40000C82; static analysis:
  the only LoadMap call is in the map listener 0xa6a8e0 (0xa6a9c7) on any 0x100001D3 change (kind DID, owner not
  checked), probably with the change's PREVIOUS value, so a Tutorial 1 value left in the client session loaded. Now
  0x100001D3 goes as the encounter, 0, the encounter; it is cleared (0) when the client leaves a match
  (`encounter_cleared_at_end`); and since a bundle on the existing player did not re-broadcast and the shop's
  Upgrade manager is created at match start, a second pass `player_recreate_delay` 15 s after the match-start notice
  removes and re-creates the player object (`player_rebind` "recreate") before the events. tools/diag.py --shop: the
  listener breakpoint was at a wrong rva (0x6A68E0); now 0x66A8E0 with its arguments, plus the Upgrade manager ctor.
- Crime Alley names the small champion packs 0xA0000116, 0xA0000073, 0xA000022E that hold a few of the missing
  statics' DIDs (a second zone pack hung the load).
- Lobby matches start the champion with Q / W / E / R / passive at rank 0 and one skill point
  (`match_start_ranks` {"0": 1, "6": 1, "7": 1, "8": 1}, `match_start_skill_points` 1); `skill_rank` stays for
  encounters without a flow.

## fase3-gz — ics: rank level gates, the lobby's Stolen Powers, respawn teleport, camp spot, announcer IIDs (2026-10-23)

Tester 13:59-14:36 (fase3-gy), a long Crime Alley vs AI match with screenshots: the batarang's bounce still lost; no
respawn countdown; after the respawn Batman shows only once he is given an order; a costume's portrait empties in
champion select; the Stolen Powers picked there were not the match's; the HUD has no background; any skill could be
ranked from the start (R from level 1: diag 14:02:01); the turret shows a targeting line, no projectile; only the
first turret takes basic attacks (0x100007D9 went to the dampener 14:10:40, core turret, core: orders still refused);
the camp stands outside its hole; wrong minimap, no pings; the second structure (dampener, event 34) gave an empty
strip without voice; no critical-hit animation. The shop diag was not run with --shop.

- Rank gates: the next rank of a slot needs a level: `rank_min_levels` {"4": [6, 11, 16, 20]} (the 4th R rank: P),
  other slots rank r from level 2r - 1 (`rank_level_rule`).
- The Stolen Powers picked in champion select are the match's (World.stolen_choice, `lobby_stolen_powers`).
- The respawn is a teleport: the champion's seq A byte (client-movement.md) is incremented and the champion goes the
  session's way with the player object's links (World.send_champion, `respawn_teleport`).
- Crime Alley's camp at the jungle markers (80.0, 97.2), yaw 180 (facing the street).
- Turret shots also send the body's Vfx_Basic_Ranged 0x1000029D (`match_turret_shot_extra`).
- Respawn countdown: notice 0x10000090 is `u32 state | f64 time of the next state` (reader 0x8c48c0, movsd in
  0x8beac0; Flash DefeatStatus.StartCountdownTimerNow on the game clock); it carried the u64 player id (a double ~0,
  the countdown ended at once).
- Pings: 0x2136 is echoed as 0x2137 to the player (u8 0 | u64 pinger | f32 x | f32 y | u64 target | u32 type,
  `ping_echo`). 0x2006 is a handle-tracked map note (u8 0 | u32 category | Handle | f32 x | f32 y | u32 | u32 team).
- Minimap: 0x100001D3 goes by 0x6 as 0, then the encounter, so LoadMap (0xA4C2C0, minimap record 0x10000287 =
  0x48000E36 for Crime Alley) always sees a change.
- HUD: lobby matches also show elements 8, 10, 11 CharacterPanel, 13, 16 StatsPanel, 24, 29, 33, 36, 37, 38, 41, 44
  (`lobby_hud_extra`; a tutorial-type encounter starts them hidden, BaseHudElement.SetInitialVisibilityBasedOnEncounter).
- Champion select: my 0x2029 again 0.5 s after a pick (`lobby_slot_resend`): the client loads a costume's portrait
  packs only when no load runs (0xabc620 "Already Loading").
- Critical hits: Batman's basic attack plays its crit through scriptlet 0x100000B8 when RollCritical (attribute
  0x10000B46, linked to 0x1000060F in his template) succeeds; his base crit chance is 0 (the HUD shows 0.0), crits come
  from items.
- Tester 14:49 (diag --target --shop, a server started before the countdown / minimap / HUD / ping changes): the
  dampener, core turret and core were refused at "flags accepted" with cached unit flags 0, although 0x1000019D went
  to each by 0x6 a second after its creation. The flags now go again as a change (0, then the value) when the HUD is
  ready and when a structure is unlocked (`match_refresh_flags`). The shop path (0xa91670 / 0xa908f0 / 0xa8ebb0) was
  never reached with the single 0x100001D3 event of that build.
- 0x2039 goes with the local champion as source and target (`announcer_iids` = "champion"): with the dampener and its
  killer the client showed an empty strip; with no IIDs (dampener reactivating / reactivated) and with the champion
  (the test) it spoke.

## fase3-gy — ics: the announcer works; its events wired to the match; the shop's encounter property (2026-10-23)

Tester 13:14 (fase3-gx): the announcer spoke through 0x2039 (each event once, with its text strip; the 0x2001 line
fallback was silent). Named by ear in order: 8 enemy team annihilated, 10 / 15 / 17 enemy Power Core at 25 / 75 / 50 %,
18 first blood, 19 relentless, 20 furious, 21 dominated, 22 unstoppable, 23 double kill, 24 shutdown, 25 invincible,
26 triple, 27 quadra, 28 penta kill, 29 "you are victorious" (the big VICTORY image), 30 "you have defeated the enemy",
31 / 32 / 33 the enemy's bottom / top / middle turret destroyed, 34 enemy middle dampener deactivated, 35 ally power
relays unlocked, 36 we captured a power relay, 37 shutdown, 40 enemy power core turret destroyed, 41 ally power relays
unlock in 10 s, 49 we defeated the Raider, 50 ally dampener reactivated, 52 ally dampener reactivating in 30 s; 55, 56,
58, 61, 63, 64 said nothing. The diag (--shop) never reached the catalogue path 0xa91670.

- `announcer_events` holds that map; the match plays: turret / dampener / core turret destroyed (the destroyer's team
  picks the own / enemy form), core at 75 / 50 / 25 %, first blood, shutdown (victim on a streak of 3+), double to
  penta kill (`match_multikill_window` 10 s), relentless to invincible (streak 3-7+), annihilated, dampener
  reactivating in 30 s / reactivated, victory. The start test is off again (`announcer_test_on_start` = 0).
- 0x100001D3 (the encounter) goes to the player by event 0x6 after load complete as well: the client builds the shop
  catalogue and loads the map info only when it CHANGES, which a creation bundle is not (`encounter_property_event`).
- Tests: test_match 131.

## fase3-gx — ics: the announcer's enable notice and channels, line fallback (2026-10-23)

Tester 12:30 (fase3-gw): none of the 16 test announcer events played (0x2039 sent 6 s apart). Bat Scream now hits in
game (12:22:16: 600, 540, 480, 420, 360 on one wave).

- Notice 0x10000205 (empty, handler 0xa8ea40) after load complete enables the client's dialog system (bit 0x4 at
  [dialog+0x14c], else 0x2039 is dropped) and starts the turret warnings (`dialog_enable_notice`).
- 0x2039 on the event's channel: 1 = the shared set 0x4000047A (events 8, 18-30, 52), 2 = the encounter's set
  (Crime Alley 0x40000D4C); channel 0 has none (0xa35dc0 / 0xa282b0).
- ics/match/announcer.py: each event's own-team / enemy line ids (the sets' 0x10000829 / 0x1000082A columns); the
  lines are conversation keys, so 0x2001 plays them directly (`announcer_mode` "2039" / "2001" / "both"). The start
  test plays each event by 0x2039, then its line by 0x2001 3 s later (`announcer_test_fallback`), one event every 7 s.

## fase3-gw — ics: one hit per redirect, client skill events off, announcer test without chat (2026-10-23)

Tester 12:13-12:22 (fase3-gv): worse; Batman lost animations (the batarang's bounce), no announcer, no shop items.
The log shows no chat message (0x20F6) reached the server in the match, so `/anunciador` never ran.

- World._missile_hits (fase3-gv) went on colliding with more entities in the same tick after a bounce redirected the
  missile; it now orders the entities along the stretch flown and stops once the missile is redirected or ended
  (only a missile flying on through its line, Bat Scream, takes several).
- `skill_client_events` = false: 0x20EA's event 0x10000023 was raised 47 times on the slots' skill scripts without its
  meaning being known.
- `announcer_test_on_start` = 20 s: every announcer event plays once by itself (one every `announcer_test_gap` = 6 s),
  each logged as "announcer test: event N", so the ids can be matched by ear.
- tools/diag.py `--shop` (`--tienda`): breakpoints at the catalogue path 0xa91670 / 0xa908f0 / 0xa8ebb0.

## fase3-gv — ics: Bat Scream's wave hits, death and respawn animation states (2026-10-23)

Tester 11:25-11:31 (fase3-gu): minions without their teleport-in; at death no grey screen (the 0x6 LifeState form)
and the champion slid while falling; after the respawn he stayed lying down and slid to each click until a skill was
cast; the shop shows no items but a Batman icon in some slots; R (Bat Scream) did no damage and showed no wave. Later
the same day: no "turret destroyed" / minions-countdown messages or announcer voice, turrets silent and their shots
unseen, some ground elements missing.

- Bat Scream (0x34000039 -> missile 0x40000092, script 0x34000043, range 230 at 15 m/s): the missile check in
  World._missile_hits counted a hit only within 1 m of where the missile stood at the tick, so a fast missile crossed
  the minions untouched. It now tests the whole stretch flown since the last tick, and a missile aimed at a point
  flies on after a hit while its script has not destroyed it (the wave hits every enemy on its line with less damage
  each time; the batarang still destroys itself). `[ics] skillshot_pierce`. Simulated: 350 -> 125, 455 -> 252.
- Death: back to the full creation bundle (`death_as_property` = false: the grey screen came with it); the champion
  stops moving when he dies; at the respawn graph event CbtState_Death_Recover 0x10000034 and the enter-world
  scriptlet (`respawn_graph_events`, `respawn_scriptlets`).
- Announcer: server-driven 0x2039 (u8 0 | u32 flag | u32 channel | PropTable 0x10000806 event, 0x10000812 /
  0x10000811 source / target IID, 0x1000081D / 0x1000081C teams; handler 0xa7fe60 -> 0xa77da0, line chosen from the
  encounter's set 0x10000802 = 0x40000D4C and the shared 0x4000047A). The event ids' meaning is not in the client: chat
  command `/anunciador N` or `/anunciador todos` plays them; `[ics] announcer_events` maps structure_lost,
  structure_destroyed, wave_soon (`match_waves.warn_before`), wave, first_blood, kill, victory, defeat once known.
- Turrets are two objects: the head (world state 0x2E000AA8) is created with each outer turret, started
  (Vfx_Startup) and coloured by team (Vfx_Active_Blue / Red); the body gets Target_Acquired 0x1000014A (target
  variable) / Target_Lost 0x1000002C and the head Vfx_Targeting when the target changes (`match_turret_heads`,
  `match_turret_target_scriptlets`).
- Crime Alley's 0x20AF added the Gotham Heights zone pack 0xA000009A (108 statics' DIDs only there). Tester 12:07:
  the load stopped at 15 % and the client left after 60 s; a second zone pack hangs the level load, so it is not
  named again ([ics.encounters] 0x40000C82 packs = []). The Android costume 0x40000BD3 picked in the countdown is a
  real costume (the bot's "Bot" name only came from the slot). The game hello no longer turns a LOBBY phase back into
  GAME_CONNECTED (0x20F2 can arrive first now that 0x20AF waits for the launch).
- Open: the minions' teleport-in (spawner placement 0x2E000D03 is server-made: Vfx_Spawner_Tier01 0x10000B1A,
  Vfx_Active_State0/1), timeline banners 0x10000424 (title tokens unknown), the shop catalogue (diag on 0xa908f0)
  and the Batman icons (0x20E2 empty slots as DID 0?), pings 0x2006.

## fase3-gu — ics: Crime Alley full match review: waves in single file, death animation (2026-10-23)

Tester 10:10-11:05 (fase3-gt), a full Crime Alley vs AI match with `tools\diag.py --entities`: the minions are now
visible (diag: 34 + 34 objects built from 0x2E000808 / 0x2E000840, no creation error). Reported: the shop shows no
items; only the first turret can be attacked (the logs agree: basic-attack orders reached the server only for
turret mid t2, none for the dampener, core turret or core, which fell to skills and minions); no victory (the enemy
core was at 85 / 4000 when the client left: it never reached 0); the minions must come out one behind the other
with their teleport-in; no turret projectiles (the server sent the shot scriptlet 0x100002E0 187 times, a key of the
turret's table); no dark fog of war, minions have no vision; at death no fall, a grey screen with the timer, and
after the respawn the camera only finds Batman after a click; the minimap is wrong; pings are not shown (0x2136 is
only logged, no 0x2006 map note is sent back).

- Waves: each minion teleports in at the lane mouth `match_waves.stagger` = 1 s after the previous one (0 = the
  earlier rows).
- Death: graph event CbtState_Death_Induce 0x100000AD on the champion after LifeState 2 (`death_graph_event`).
- Structures: when one stops being protected it gets bool 0x100007D9 = true: the dampener, core turret and core
  templates link the targetable status 0x10000249 (check C of the order validator 0x9d01d0) to it, default false,
  so the client refused every attack order on them (`match_unlock_property`).
- Client 0x20EA (u32 slot | list<u32> events, from the order dispatcher 0xa85da0 for skills with 0x10000A46) is
  raised on that slot's skill script (`skill_client_events`).
- Allied minions are fog-of-war vision sources (0x10000133 = their template's vision, `match_unit_vision`).
- The fallback turret / minion shot goes through CastWorld.run_scriptlet (the scripts' own 0x8D form).
- Tests: test_match 128 (the core gets 0x100007D9 only once unprotected).
- Open (static analysis next): attack orders refused by the client on protected-then-unprotected structures; the
  empty shop (its list 0x48000EA9 and all 210 artifacts are in the resident pack 0xA00000B3); the invisible turret
  shot; fog and minion vision; the minimap; ping echo 0x2006; the respawn camera; client event 0x20EA (441 times,
  u32 1-4 | list [0x10000023]).

## fase3-gt — ics: first Crime Alley vs AI match: skins, turret shots, death, intro camera (2026-10-23)

Tester 09:43-09:47 (fase3-gs): champion select, the countdown and the load worked, and the match ran (waves, camps,
turrets, respawn). Reported: no skin list and no portraits on the loading screen; turrets took health with no shot
or turret warning seen; at death the game froze, then the champion was at the base; the map's camera turned 90
degrees; the minion waves were not visible; a purple sphere (Tutorial 1's) outside the map.

- 0x204C lists every owned champion (type 1) and costume (type 4): the skin picker's source.
  `[ics] lobby_owned_costumes`.
- Lobby matches send 0x20AF at the countdown's end with 0x2016 / 0x206D: at the game connection's hello it set
  lobby+0x4CB and cut the lobby's costume / portrait packs short. `[ics] lobby_enter_match_at_launch`.
- Match units get their attack script's init event 0x10000088 at spawn and level-up (`match_unit_init_event`), and
  the direct-damage fallback now sends the shot's scriptlet (turrets 0x100002E0, ranged minions 0x10000326) and deals
  the damage when it arrives (`match_attack_scriptlets`, `match_shot_speed`). The turret script itself still does
  not reach its shot in the simulation (open).
- Death: LifeState 0x100000FA = 2 by event 0x6 instead of a full creation bundle of the controlled champion, = 4
  before the respawn (`death_as_property`).
- The mode layer's intro cinematic plays `cinematic_delay` s after load complete (it was sent during the load and
  ended at once; the client sets the map camera when a cinematic ends). `[ics] cinematic_after_load`.
- Open: the invisible lane minions, the purple sphere (layout static 0x2E00101D from the neighbouring landblock), the
  turret warning's target source.
- Tests: test_session_flow 60 (0x204C owned costumes; no 0x20AF before the countdown's end).

## fase3-gs — ics: champion select before the loading screen; the menu's maps after a match (2026-10-23)

Tester 00:05 (fase3-gr): Crime Alley vs AI (0x40000C82) queued and was accepted, but the client went straight to the
loading screen (10-35 %) with no champion select, then closed. The server sent 0x2016 after 0x20AF and 0x2016 + 0x206D
with the lobby state. The decompiled handlers show that 0x2016 is SetLobbyTransition (UI event 0x23, lobby -> loading
screen) and 0x206D marks everyone loaded (UI event 0x33), see reverse-engineering.md.

- With a champion select (vs AI / PvP lobby) 0x2016 and 0x206D are sent at the launch, after 0x2053 (and after the
  0x20AF re-send for a changed pick). The tutorials are unchanged.
- The object timing of a lobby match (`objects_min_delay` / `objects_max_wait`) now counts from the launch, not from
  the lobby opening (60 s of select would have created the champion before the client loaded).
- Config: `[ics] lobby_transition_at_launch = true` (false = the old order).
- Tester 09:21: champion select now appears and the lock works, but then no skin list / countdown, no champion
  cards on the loading screen, and the load hung at 35 % until the client gave up (0x12D 60 s later). The 0x2053
  sent at the launch switches the client to view-match (spectator) mode (reverse-engineering.md). Now:
  - 0x2053 is not sent to the player (`[ics] send_match_started = false`);
  - 0x204B carries f64 game-clock times (was u64 integers, read by the client as ~0) and the countdown is
    `launch_delay` = 15 s (was 3) for the costume choice; at its end 0x2016 + 0x206D move to the loading screen;
  - a costume of the locked champion can be picked during the countdown (0x20E4 with the costume variant);
  - 0x2031 lists every slot, bots at `bot_loading_percent` = 100;
  - a costume's champion XP, level and last use go to its champion (the default variant).
- After a match the menu had no maps and queueing sent encounter 0 (tester, 2026-10-23; also 2026-10-22 14:11):
  the tutorial's 0x20AF named 0xA00000B3 and 0xA00000DF, packs the exe loads at start-up. Named packs are unloaded
  when the match ends, and B3 holds every encounter's records, so the menu lost them all. 0x20AF now leaves out the
  start-up packs (they are resident anyway). Config: `[ics] resident_packs` ([] = the old behaviour).
- Tests: test_session_flow 58 (no 0x2016 / 0x206D during champion select; f64 countdown; costume pick after the
  lock; 0x2016 + 0x206D at the countdown's end and no 0x2053; no start-up pack in 0x20AF).

## fase3-gr — ics: small meteor strikes without the crater entity (2026-10-23)

Tester 23:42-23:57 (fase3-gq): Tutorial 1 ran to the Destroyer (step 31 of 32); the big meteor's crater animation
appeared at several places. The small strikes created the crater entity 0x40000CAB for its fire column, and its
Vfx_Active also attaches the big crater with its lava (world state table 0x1D000155). The small strikes are now the
rock (its own fall and trail) and the dust cloud only. Still reported and open: the second bridge gate shows only after
the flashlight (D) step, the drones' death and spawn-in effects look wrong, the intro's burning cars.

## fase3-gq — ics: guide rings, units' spawn-in, small meteor strikes, the bridge ambush from the gate (2026-10-22)

Tester (after fase3-gp, comparing with the original videos): no burning cars at the start of the intro; the drones
pop up (the original: a pink / purple flash where they appear, Part 1 1:18); no ground marker where to go (only the
arrows at Batman's feet); every meteor leaves the big lava crater (the original: only the first one).
- **Guide ring**: the marker plays Vfx_GuideArrow with script variable 0x1000050A = FX 0x1E00055E (0x34000600's Group
  ping) and the champion Vfx_GuideArrow with 0x1E000510 (its Group arrow). `[ics] marker_scriptlets` entries are now
  `[on, scriptlet, FX]` (the old list is in the comment). Practice targets get a ring each and the arrow aims at the
  first living one (`("guide", group)`, `[ics] guide_targets`, true).
- **Spawn-in**: every unit the director or a match wave creates plays `_Entity_OnEnterWorld_Default` (-> Vfx_Spawn:
  purple ring 0x1700142A, particles 0x18000B56 / B58) 0.1 s after its bundle: `[ics] unit_spawn_scriptlets`
  (`["_Entity_OnEnterWorld_Default", "Vfx_Spawn"]`, the first the unit holds; [] = off), `unit_spawn_delay` (0.1).
- **Meteors**: only the first big one (step `meteor`) leaves the crater and lava. The walk's, the wave's (now at
  (37.0, 55.4), beside where Batman finished the first drone) and a new one in the bridge ambush (2.5 s after the
  drones, among them) are small strikes: rock at 0.3, the strike entity's fire column (Vfx_Active, removed after
  2 s), dust cloud 0x2E0007D4 (Vfx_Startup). `[ics] tutorial_small_strikes` (true; false = fase3-gp).
- **Bridge ambush** from the closed gate 03GateA behind Batman (original 3:55): `[ics] tutorial_ambush_from_gate`
  (true; false = 14.8-16.3 m ahead as before).
- Director: `("if", key, [actions], [actions])` picks a list by an `[ics]` switch at start.
- **Burning intro vehicles: not fixed.** They are map statics whose key 0x5 -> Vfx_OnInit attaches fire and a light
  (reverse-engineering.md, "Tutorial 1 visuals"); the client builds them and what starts that key is not traced yet.
- Tests: test_director 43 checks (guide ring FX, practice-target rings, spawn-in, small strikes without crater, the
  big one with it, the ambush).

## fase3-gp — ics: the tutorial HUD revealed step by step, one Batman in the cinematics, the vehicle's wreck (2026-10-22)

Tester 14:43-14:51 (Tutorial 1, compared with the original's videos): the vehicle Catwoman attacks in her cinematic
does not explode; two Batmans appear; the whole HUD and every skill button are there from the start (D and F were
cast during the first wave).
- The HUD follows the original (Part 1 video 0:00-6:05, wAngel 2:40-10:45; the client starts a Tutorial_Basic
  encounter with only the objective tracker and the hints, `BaseHudElement.SetInitialVisibilityBasedOnEncounter`):
  portrait + minimap with the first objective; at level 2 the skill bar with Q, W, E, R (rank 0), passive and basic
  attack and an arrow over Q's "+"; health / Will bars (Will framed) and the Will hint at the first Sonic Batarang;
  the experience bar (framed) and the Experience hint at the W unlock; D (framed) at the camera step; F (framed) and
  the Earn Stolen Powers hint at Super Strength; level 7 and arrows over passive / Q / W / E right after the
  Destroyer's cinematic. Hints moved or added: Experience to the W unlock, Will, Skill Charges, Skill Ranks,
  Spacebar, Camera zoom, Earn Stolen Powers; Super Strength and moving after the Destroyer's cinematic.
- New director actions: `("hud", [elements])`, `("hud_hide", ...)`, `("highlight", element, id[, arrows])`,
  `("highlight_off", element)`, `("skill_button", slot[, on])`, `("after", s, action)`; `("ranks", ...)` puts the
  tutorial arrow on each rankable "+". A slot whose button is not shown is refused (`World.cast_filter`).
  `[ics] tutorial_progressive_hud` (true; false = every element at the first "hud", every slot usable),
  `[ics] tutorial_rank_arrows` (true).
- 0x20F5 now binds the champion to the scene's player actor (flags 2, bindings {0, champion}) and asks the client to
  hide the Characters (PerceivedType 8: the champion) while it plays; they come back when it ends.
  `[ics] cinematic_bind_champion` (true), `[ics] cinematic_hide_types` (8; 0 = the old DID-only message).
- Catwoman's cinematic: the intact vehicle goes at her strike (frame 146, 4.9 s) and its wreck 0x2E00135E / 5F / 60
  stays at (43.66, 52.61) after the cinematic (the cinematic's own pieces and fire go with it).
- Tests: test_director 35 checks (HUD per step, refused hidden slot, arrows, Will bars, wreck, the 0x20F5 layout).

## fase3-go — ics: the play menu's map list after a match, queue eligibility, JoinQueue for encounter 0 (2026-10-22)

Tester 14:11 (screenshots of Play -> VS Player -> Normal -> Choose Map, Featured Maps, VS A.I.): every map tile was
'undefined' (type Unknown, average match time undefined), some said "Queues are currently unavailable", the featured
maps were 'undefined' too; choosing one sent JoinQueue 0x20EB with encounter 0 (`00000000 00000000 01 ffffffff`), the
server queued encounter 0x0 and the game connection dropped. Tutorial 1 had been queued correctly before (0x40000991,
flags 0x300000). Static analysis (reverse-engineering.md "The play menu's map list"): the 0x2024 layout ics sends is
right; the client's query 0xA68030 could not load the encounters' templates in the menu built after the match, so
names / type / tutorial flag were missing and JoinQueue's QueueKey (0x86E060) came out (0, 0). The cause of the
failed loads is not known yet (diagnostic below).
- **Menu refresh after a match**: `[ics] menu_refresh_after_match` (3.0 s) after the client leaves a match world
  (0x12D) the server sends **0x20FF** (the encounter list again; the client raises ResetMapSelectionList and the menu
  queries its maps again) and 0x2101. 0 = off.
- **Queue eligibility 0x2101** at login (after 0x215D, before 0x2080) and with every refresh: level, capacity (the
  roster size), the menu's encounters, ranked minimum level `[ics] ranked_min_level` (1), draft requirement 0.
  `[ics] queue_eligibility` (true).
- **JoinQueue for encounter 0** (or one without a map pack) is refused: 0x20E0 removed from queue + the refresh,
  instead of a referral to a match that cannot load. `[ics] reject_unknown_encounters` (true).
- The 0x2024 queue flag word is documented (0x200000 blind pick, 0x20000 draft, 0x10000 ranked) and configurable per
  category: `[ics] queue_flags` ({} = the same bytes as before: 0x220000, tutorials 0).
- New builders `ics/messages.py` `encounter_update` (0x20FF) and `queue_eligibility` (0x2101).
- `python tools\diag.py --encounters` (new): logs the menu query's encounter count, whether each encounter's template
  and name record load on the client (0 = not loaded) and JoinQueue's key.
- Tests: test_session_flow 54 checks (new: the 0x2024 bytes, 0x2101, JoinQueue for encounter 0 -> 0x20E0 + 0x20FF,
  0x20FF + 0x2101 after leaving the match).

Test: (1) log in and go straight to Play -> VS Player / VS A.I. (names expected); (2) play Tutorial 1, leave, wait
3 s in the menu and open the maps again. If (2) still shows 'undefined', send `logs\diag.log` from
`python tools\diag.py --encounters` started in a second console before opening the maps.

### fase3-go (continued) — ics: the practice targets die to their skill, Sonic Shell explodes (2026-10-22)

Tester 14:10 (server.log): in practice_q the two practice targets never died: Sonic Batarang cast next to them
logged `EnableCollision 0x10000070: no server effect` and `missile 0x40000090 gone` with no hit, basic attacks
(`attack targets1 (1/1)`) did no damage; the drones took damage normally. Cause: the targets are neutral (team 0,
the data gives them no side) and the server refused neutrals twice: its missile collision test passed only hostile
units, and CheckRelation refused relation "neutral" (`neutral_hittable = false`). See reverse-engineering.md
"Practice targets, missile collision, launched entities".
- Missile collision (`CastWorld.collides`): anything not on the shooter's team and not DisableCollision'd; a neutral
  only when hittable (`[ics] neutral_hittable`, or marked by the flow). The missile script still decides the hit.
  `[ics] missile_hits_neutral_targets` (true; false = the old hostile-only test).
- DisableCollision 0x1000006F / EnableCollision 0x10000070 implemented (the entity's collision flag; a missile
  passes through an entity with collision off).
- New flow action `("only_skill", group, slot)`: the practice targets (Q, W and E steps) are hittable neutrals and
  only that skill hurts them; any other hit does nothing and plays Superman's 0x1CD (basic attack) or 0x1DB then
  0x1B2 (another skill), each once (`IMMUNE_LINES` in ics/encounters/tutorial1.py).
  `[ics] practice_target_only_skill` (true; false = any damage kills them, they have 1 health).
- The damage pipeline knows the slot behind each hit (the script's, the launching skill's for a missile, the applying
  skill's for a status, the spawning skill's for a spawned entity).
- Sonic Shell (W) never exploded: an entity SpawnEntity creates now gets event 0x10000049, and a launched entity gets
  0x10000049 / 0x100000EE / ShooterIID at launch and 0x10000035 when its flight ends; it stays where it lands until its
  script destroys it. `[ics] spawned_entity_events` (true), `[ics] launched_entity_linger` (5.0 s fallback removal).
- Tests: test_director 23 checks (new: targets neutral + hittable + only Q, a basic attack does nothing and queues
  0x1CD, the collision rule, Sonic Batarang cast at a target kills both, Sonic Shell and Bat Flight kill the W / E
  targets), with a timed clock for missiles and script timers.
- Open: Super Strength on the bridge vehicle waits for the vehicle's answer (0x100000BB) that nothing raises yet.

Test: in practice_q press Q on a target (both should die, the batarang bounces); a basic attack on one should make
Superman say targets only take skills. Later W on the W target and E on the E target.

## fase3-gn — ics: the console no longer freezes the server (2026-10-22)

Tester 13:58: the first login worked (with the daily reward); after leaving, the second login hung at "retrieving
champions" and the server logged nothing more (not even the SOAP request). Two logins in a row work in a simulated
client against the same build, so the server was blocked from outside: a click in the Windows console starts a
QuickEdit selection and the process stops at its next print. `python -m ics` now switches QuickEdit off for its
console (`[ics] console_no_quick_edit`).
- 14:02 (screenshot: stuck at "Retrieving encounters", all three connection lights green): the second login sent
  back the 5 preferences the first session had stored (0x216A); the first login, with none, worked, and the earlier
  server always sent 0x216A empty. They are sent back only with `[ics] send_stored_preferences` (false).

## fase3-gm — ics: the full script VM, PvP maps and mechanics, the PvP / menu flow (2026-10-22)

Built from the full decompilation (docs/re-notes/full-*.md). Not yet tested in the game client.
- **Combat / script VM** (`ics/script_runtime.py` rewritten, new `ics/script_nodes.py`, `ics/combat.py`, CastWorld
  in `ics/world.py`): the decoder reads 875/875 scripts (fixes A-D); every node class runs (simulated: 325/325
  skills, 549/549 other scripts, 0 unknown, 0 crashes); bugs fixed (0xC = x - 1, PostEventDelayed, unstarted timers
  expire, CheckRelation masks, ApplySkill outputs, RemoveStatus this-instance, LaunchMissile fields); attribute
  stacking (0x96D460) with 0x20F0 / 0x20E8, CC attributes by event 0x6, statuses with icons, cooldowns 0x20F8, cast
  bars, missiles with target event 0x100000EE, hotspots, shields, VOT; CC stops the unit and refuses orders.
  Config block `# ---- combat (script VM) ----`.
- **PvP maps and mechanics** (new package `ics/match/`): per-map spawns (cores, turrets, dampeners, Foundry,
  beacons, relays and the Doomsday Device, capture points, camps), unit stats with level formulas 0x3B, minion
  waves along the lane mouths with minion AI, match clock 0x10000109, roster / scoreboard 0x1000005B, kill feed
  0x217A, team health, trackers 0x2069, timeline notices, surrender 0x10000454-456, respawns, protection order, win
  / loss sequence, map events. `ics/navmesh.py`: cell count from +0x98, big-endian blobs (Gotham Divided). Authored
  values in the block `# ---- PvP maps and mechanics ----` (waves, leashes, respawn, capture, Device, events,
  surrender).
- **PvP / menu flow** (`ics/session.py` reworked, new `ics/account.py`, `ics/lobby.py`, `ics/chat.py`,
  `ics/matchend.py`): per-account persistence (data/accounts/<name>.json, gitignored), login data in order, queue /
  accept / champion select with bots (picks accepted as 0x20E4 and 0x2102, logged), lobby changes, loadouts and
  boutique, store, profile, achievements and rewards, leaderboards, login calendar, chat echo, custom match; the
  match is handed to `ics/match` and ends with rewards, XP and currency. Config block `# ---- PvP flow and account ----`.
- `Data.template_properties` reads templates past the pack's record list end: every encounter has its map pack
  again (0x40000C82, 0x4000013E, 0x40000B6B, 0x40000B6A were 0).
- Tests: test_scriptvm 65, test_ics 33 (temporary account dir), test_match 122 (new), test_session_flow 48 (new);
  all others unchanged and passing. The catalog lists every event the server now sends / handles.

## Full decompilation of the client (2026-10-22, no build)

The tester asked to decompile everything. Ghidra 12.1.4 headless decompiled InfiniteCrisis.exe completely (60 529
functions, call graph and string index) and the launcher / game DLLs; JPEXS FFDec 26.4 (installed in C:	oolsfdec)
exported the UI's ActionScript. The output stays outside the repository (re-work/). Eight notes in docs/re-notes/
(index: full-index.md): maps and world, match mechanics, combat and skills, protocol (+ full-protocol.tsv), entities
and engine, account and social, the complete UI. No server change in this entry.

## fase3-gl — ics: knockdown through the client's crowd-control attributes, the tutorial's end (2026-10-22)

The tester authorized full decompilation; four client subsystems were decompiled with REA / Ghidra (notes in
docs/re-notes/: client-movement, client-status-effects, client-scriptlets-graphs, client-cinematics-matchend).
- Knockdown: the champion is stopped with a speed-0 bundle and gets bools 0x10000B2D (no order is sent at all) and
  0x100003F3 (Stunned) by event 0x6 while down; cleared `[ics] knockdown_free_after` after the get-up
  (`knockdown_flags`).
- The tutorial's end (`ics/matchend.py`, `[ics] tutorial_end_sequence`): VICTORY billboard (0x2038, notice
  0x100002EB type 9, announcer line), `victory_hold` s later the match-ended notice with 0x216A (replay the post-match
  movie), 0x214B, 0x2045, 0x2120 (Tutorial n complete) and the scorecard bundle (re-sent `scorecard_resend`);
  the reward is answered to 0x212E / 0x2124 / 0x2128; 0x20A6 re-sends 0x2190. Progress persists in
  data/progress.json and is sent at login (0x214B, 0x2120).

## fase3-gk — ics: events during a step's actions are kept (2026-10-22)

Tester 10:20 (video): the crater shows its lava star; the first drone, the wave and the small meteor work; the flow
stuck at "unlock Sonic Batarang" (Q was ranked at 10:21:51 while the step's own dialogue still played, before its
`ranked` trigger was armed). Batman did not fall: the graph events (0x100002F5 ...) were sent but the client kept
him walking.
- The director keeps `ranked` / `cast` / `preference` / `hit` events that come while a step runs its actions and
  checks them when the trigger is armed.

## fase3-gj — ics: knockdown, the first drone's fight and gate, the small meteor fixed (2026-10-22)

Tester 10:06 (video): Batman should fall when the big meteor lands; the drone cannot be targeted; the human should
run off when Batman attacks the drone; the drone may only be attacked once the dialogue says so. Logs: the small
meteor failed to spawn (`spawn_at` extra properties with int keys).
- Knockdown at the big meteor's impact (director action `knockdown`): graph events CbtState_Knockdown 0x100002F5,
  CbtState_Dead 0x1000010B at +1.8 s, then RunScript_Vfx_GetUp 0x10000490 + CbtState_GetUp 0x1000009D at +5 s
  (scriptlet 0x100001E3 with variable 0x780, `World.graph_event`); orders are ignored meanwhile.
- The first drone fights the human (`fight`), is held untargetable (`untargetable`: its unit flags / tags wait)
  until conversation 0x1B8 has played, then `targetable` sends them (event 0x6) with a full bundle. The earlier
  drones became targetable only once they started fighting Batman, i.e. after a full bundle following the 0x6 sets.
- A champion's hit fires trigger `("hit", group)`: the step `drone_fight` sends the human off and turns the drone on
  Batman. A unit busy with someone else turns on the champion when he hits it.
- `spawn_at` extra properties fixed.

## fase3-gi — ics: small meteor as the scaled rock, the crater's lava (2026-10-22)

Tester 10:00 (video): the objective banner and the hints now show. The crater has no lava; the small meteor looked
like the big strike.
- The small meteor is the rock world state 0x2E000BB3 alone at scale 0.3 (property 0x6B4, as the earlier server
  did): it falls and lands with its own graph. It is removed when the first drone step starts. `spawn_at` takes
  extra placement properties.
- Each impact plays the crater state's own `Vfx_Active` (table 0x1D000155: the lava meshes 0x2E001060 / 0x2E001061).

## fase3-gh — ics: Tutorial 1 closer to the original's videos (2026-10-22)

Tester 09:30: two meteors fall; the drones should only attack when attacked. The tester sent two recordings of the
original tutorial; their analysis is in reverse-engineering.md.
- The meteor's rock is no longer copied (the copy fell again); the crater world state 0x2E0004BE is left at each
  impact (with the crater pieces 0x2E0002F6-F8) instead of the bare lava meshes.
- A smaller strike beside Batman two seconds into the first walk; the first marker comes with the objective.
- `[ics] unit_close_aggro` 0: a quiet unit only fights once hit. The wave's two drones go at Batman (as in the
  videos).
- The objective is also sent as the banner (`[ics] objective_banner`): the top-centre text.
- Tutorial hints 16 (guide arrows), 17 (basic attack), 18 (experience), 34 (skill points), 23 (passive), 26 (Super
  Strength) at the original's moments.

## fase3-gg — ics: crater pieces, conversations paced by the client (2026-10-22)

Tester 09:13 (video): the drones can be attacked now; after the meteor "what stayed is not the crater but another
visual element" (0x2E000375 is a roof).
- The meteor leaves the crater pieces 0x2E0002F6 / F7 / F8 (the world states of the meshes `Vfx_Spawn_Event02`
  attaches) instead of 0x2E000375. `Data._record` reads header-2 world states.
- The client's 0x2140 (`u32 instance`, a conversation has played) is handled: the director queues conversations and
  starts the next one then (`[ics] conversation_done_event`, true; the catalog length + 1.5 s stays as a fallback).

## fase3-gf — ics: drones attackable (status tags), no doubled intro lines, crater static (2026-10-22)

Tester 08:56 (video + diag `--target --dialog`): same problems. diag: the drone passed the unit flags and failed the
validator's "status tag check B"; the video: every intro conversation went by twice (the director's once), and
after the strike only a red disk stayed.
- Hostile units get bools 0x10000029 and 0x10000249 = 1 (`[ics] unit_targetable_tags`), sent like the unit flags
  (event 0x6 after `unit_flags_delay`).
- Scene-script conversations are no longer sent (`[ics] scene_conversations`, false): the cinematic plays them.
  The director still waits for them.
- Each meteor also leaves the crater static 0x2E000375.
- The video shows the human running off at the drone (fase3-ge works).

## fase3-ge — ics: crater kept, the human flees with the drone, conversation instances, order diagnostics (2026-10-22)

Tester 08:39 (diag `--target`): the drone has the right colour now; the crater still goes and the fire stays; the drone
still cannot be attacked; Superman still repeats lines; the human does not run off.
- diag: the client's validator accepted the drone from the moment its unit flags arrived (event 0x6, 08:40:11), but
  every right click still went out as a move order. `diag.py --target` now logs the order decision (hover pick,
  interact check, validator, order sent) and one line per validator result; `--dialog` logs the client's conversation
  starts.
- The meteor no longer gets a separate `Vfx_Active`: `Vfx_Spawn_Event02` runs it itself, and ours replaced the
  scriptlet that holds the crater meshes.
- The human (03ThugB) runs to `thug_flee` 1.5 s after the drone appears and is gone 6 s later (before: only after the
  drone died).
- Each conversation gets its own instance id (`[ics] conversation_instances`, true; false = 0xFFFFFFFF as before).

## fase3-gd — ics: unit flags by event 0x6, purple drones, no doubled wagons, crater meshes (2026-10-22)

Tester 08:13 (diag `--target`): the drone still cannot be targeted (flags still 0 after the second bundle); Superman
still repeats lines; the two vehicles the Destroyer throws at the start stay on the street (doubled) and he walks
through them; the meteor crater still vanishes while its lava stays; the drones are red, the original's are purple.
- Unit flags 0x1000019D go as event 0x6 (set one property: `u8 0 | u32 id | packed id | value`, handler 0x635360 ->
  the object's property collection, its change path) `[ics] unit_flags_event` (true; false = the fase3-gc bundle).
- Hostile units get colour override 0x10000CF0 = `[ics] unit_colour_override` (1, as the generic drone template
  0x49000A5C has it); 0 = the client's relative colour (enemy 5, red).
- A scene script's conversation (the intro's 441 = 0x1B9) holds the director's next line until it ends
  (`[ics] queue_scene_conversations`, `scene_conversation_seconds` 6.0 for lines without a timing): 0x1BA came 2 s
  after 0x1B9, over it.
- 02PaddyWagonA / B are no longer created at the start (the intro cinematic brings its own).
- Each meteor also leaves the crater meshes 0x2E001060 / 0x2E001061 (attached by Vfx_Active from table 0x1D000155)
  as objects of their own.

## Survey of the whole install (2026-10-22, no build)

Tester (2026-10-21 23:30): "analyse every file of the game, leave nothing out". Nine static surveys, each a note in
docs/re-notes/: install-inventory, script-nodes-complete, protocol-complete, units-and-ai, maps-complete,
client-scripts-and-ui, properties-complete (+ .tsv with all 3 822 property descriptors), account-systems-data,
cinematics-vfx-audio. Consolidated in docs/re-notes/master-plan.md (v2), with the build order.
