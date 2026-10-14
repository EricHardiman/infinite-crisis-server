# FIRST DRONE + BASIC ATTACK 2026-10-10 late (verified)
- Drone = Soldier/"target drone" variant 0x40000B24 (pack 0xa0000257; twin 0x49000b24, world state
  0x2e000808, entity 0x2d00068a, model chr_minion_target_drone with a Havok ragdoll), IID
  0x0300000000000001 (type 3: type-2 IIDs count as players), team 2, spawned at (46.0, 58.8, 200)
  when the Basic Attack step starts (build_drone, DRONE_*). Health bar via 0x42.
- Client teams: GetTeam 0x454050 (team component [ent+0x84]+0x4c, else prop 0x1000009c);
  Relation 0x454a90 returns 4 same team / 1 either team 0 / 2 enemy. Target checks 0x60a430:
  target needs 0x1000034c != 0 and bool 0x10000aa7 (drone has both from its record); optional
  mask 0x10000506 (Batman: 4).
- Right-click on a target = 0x20EE command 2: u32 cmd | u32 | u64 target IID | u16. The client
  only sends it in range; from further away the click is a plain move onto the target, which the
  server now treats as an attack (DRONE_CLICK_RADIUS). Server-side: attack_order/combat_tick walk
  into ATTACK_RANGE, face, 50 damage per second, 0x42 updates, then drone_death().
- Death: LifeState 0x100000fa -> 2 (Dead) hides the health bar but plays NO death; 1 then remove.
  The ragdoll/death is presumably triggered by a Havok behavior event, probably carried by 0x42's
  change-record list (reader 0x443660 -> element 0x4414f0, format not decoded yet).
- ANIMATION/ACTION LEAD (2026-10-10): animations are Havok behavior graphs (records 0x1a..., e.g.
  drone graphs 0x1a000a3e/0x1a0013c9/0x1a000547/0x1a000555 in pack 0xa0000257) driven by NAMED
  EVENTS: CbtState_Death_Induce, CbtState_GetHit, CbtState_KnockDown/KnockUp/Cower/GetUp, and
  Combat_Basic_Attack (record 0x1f00000f, pack 0xa000006f). Graph variables:
  Property_Slider_Propel/Turn, Property_BehaviorParams_TargetHeading,
  Property_Attribute_AttackSpeed. Event-name tables: records 0x33000000 / 0x30000000 (pack
  0xa0000038). Death clips + RunScript_Vfx_Death_A/B in 0x1f000040. Skill script records
  (e.g. 0x30000211: ShooterIID, TargetIID, SkillDamage, KnockDownDuration). NEXT: find the
  server message that raises a behavior event on an entity (attack swing, hit, death).
  0x42's change-record list (0x443660 -> element 0x575e70: u8 | u8 | bool | list via
  0x574700) looks like vital modifiers, not hits. No damage-number notices exist in the HUD.
- ACTION HUNT, round 2 (2026-10-10): scriptlets (prefix 0x34 = data type 7) raise the behavior
  events; Batman's basic attack lives in scriptlets 0x34000038/0x34000039 (pack 0xa0000122:
  Basic_Attack_Left/Right, onSetBasicAttackSpeed, onBasicAttackEarlyOut; entity 0x2d0001e0).
  Start-scriptlet = 0x5789c0(did) (loads type 7). Callers: 0x579860/0x5798e0 (entity creation:
  started 0x3400019e and the ping's 0x3400053c/0x34000600, seen live), 0x5c48b0 <- 0x5d0870 <-
  0x5d0ee0 <- 0x651760 (<- 0x6aabf0 = event 0x20e2 handler, payload looks like items/cosmetics;
  <- listener 0x65e6c0) and 0x651820 (<- 0x661260 = slot +0x60 of the charsys sub-object
  vtable 0x1204908, which takes a LARGE struct by value; its caller is not found yet), 0x6180c0.
  Revealing the skill bar (HUD 14, 6, 9, 17, 25, 12, 7) showed Q/W/E greyed out and no client
  skill request at all (SKILL_BAR_TEST_ELEMENTS, now off).
- Open: Batman's attack animation (no event known; 0x20f8 = skill used/StartSkillCooldown,
  0x20dc = ExecuteSkillError), death/ragdoll, damage numbers, XP/coin.

# MINIMAP SOLVED 2026-10-10 evening (verified: real map image shows)
- The current-encounter property 0x100001d3 is storage GROUP 3 (never written by the wire).
  EXE PATCHES 5-8 (tools/patch_client.py) switch the map listeners to 0x100001fc (kind 0x15,
  group 4, def flag 0x10000 = listeners notified, inside both handlers' id-range chains); the
  server sends (0x100001FC, 0x15, 0x40000991) on the player object on resends
  (PLAYER_LATE_PROPERTIES).
  - Map-IMAGE listener: registered at 0x65b148 (fn 0x65aaa0, listener obj+0x20), handler
    0x66a8e0 (cmp 0x66a906) -> 0x64c2c0 -> twin prop 0x10000287 -> DeliverMapData.
  - Map-manager listener: 0x60cbe1 (fn 0x60cbc0, obj+8, vtable 0x12058bc), handler 0x680cd0
    (cmp 0x680eb4) only marks the map dirty ([obj+0x90]).
  - Property stores call listener slot +8 (0x173460 shows it); 0x12058bc's +8 is an adapter
    (0x6bf010) that forwards to +0xc.
  - Dead ends: 0x10000287 (no notify flag), 0x100002eb (a third listener 0x6567f0 treats it as
    the encounter TWIN and re-sets the CAMERA: rotated 90 deg), 0x100008ab (above 0x680cd0's
    id range).
  - Tool: tools/live/propscan.py lists property defs by kind/group/flags (run propdef.py once
    first in the session).
- 0x2053 "match started" mode (SEND_MATCH_START) now LOADS but switches the HUD to the PvP layout
  (BLUE/RED scoreboard, no chat log); hiding HUD elements 8/13/33 did not help. Left OFF.
- tracer.py polls tracer.inject while idle too (slim runs). Delete stale logs/tracer.inject
  before attaching: a leftover propdef line ran `callthis fee60 0 ...` once.

# UPDATE 2026-10-10
- WALK ANIMATION FIXED (verified): the movement module's max speed (module+0x2d0) was 0, and 0x2097e0
  clamps the animation forward speed to it -> speed 0 -> glide. It is set by f32 PROPERTY 0x7EC
  (listener 0x150160 on the module's +8 subobject, `this`+0x2c8 = module+0x2d0). Now sent on both
  objects as MOVE_SPEED. Velocity vfunc 0x156640 = |frame delta| / dt / scale (fine).
- Walk updates are position-only (`build_match_objects(position_only=True)`: F2 + B0, no BC
  property table). Re-sending all properties at 60 Hz x 2 objects stalled the client.
- TCP_NODELAY on the user and game server sockets.
- RAPID-CLICK FREEZE FIXED (verified): the client pauses ALL entity replay (flag 0x17697d0, checked
  at 0x20b62e) once 5 s pass without a "server update" (0x69aae0; 10/30/60 s print warnings). The
  game-connection keepalive (time packet 0x01000000 + object resend) only went out on a 2 s recv
  TIMEOUT, so a stream of 0x20EE move orders starved it. It now runs on a 2 s timer.
  Replay facts: sample ring of 9 (rva 0x1525a0; drops samples whose orientation + velocity match
  the last one), playback time = client server-clock estimate - 0.1 s ([0x1462938]); the clocks
  agree with our time.time() stamps. The client ticks movement at 30 fps (dt 1/30).
- SECOND BATMAN GONE (verified): PLAYER_AVATAR = 0x4000007C "Unnamed Player" (no model). Loads fine,
  lighting, guide arrows and walking unchanged. Fog of war still has 1 active component.
- Known cosmetic, not caused by us: the lava-crack glow in the ground slides with the camera
  (present with either player record).
- GROUND MARKER: parked. Its logic is in compiled script record 0x1e00055b (AlertPingScriptlet /
  GroupPingScriptlet, vars UseAlert/UseVFX/NearbyRange/TargetPosition; reads props 0x10000034,
  0x100000b8, 0x10000f86, 0x1000050a, 0x10000012, 0x10000f80, 0x10000559, 0x10000173 ...).
  Ping scriptlet records are stubs (0x34000600 -> arrow model 0x170014a0).
- MINIMAP (2026-10-10): 0x100001d3 is only READ/listened by the client (no setter anywhere in the
  exe). It lives in the group-3 store [entity+0x40] (class vtable 0x11c9d28, created for every
  entity, 0x22a340); none of sub-events 0xBC/0xB7/0xB8/0xBA/0xF5 writes it. Map loader 0x64c2c0 has
  exactly one caller (listener 0x66a8e0). Desc u64 (desc+0x38) != 0 makes 0x229d70 load a type-0x23
  (DID prefix 0x82, map-placement) resource -- not it.
- 0x2053 "match started" retried (SEND_MATCH_START): no crash any more, but load STALLS at 30%:
  champion 0x40000086 fails ConstructStep3 (assert 0x14f32b; twin lookup 0x78880 ->
  0x1dfba0(0x49000086, type 0x29, 1) returns 0). Its pack 0xa0000076 is loaded by LoadMatchData,
  then VerifyAndLoadAllNeededRPS (0x6bc620) runs Clear{Light,Heavy}ResourcePackReferences and the
  twin is gone. Needed-pack lists come from the local lobby slot (0x6b83a0 matches the local id
  against slot ids at +0xd8, champion at +0x118 -> 0x45e010 -> 0x46da70) and lobby+0x30 (0x204C
  DID list). Delaying the objects to 12 s did not help. 0x2053 body = u8 | u32 | list<StringInfo>
  x2 (strings, not packs). Without the twin the agent link (0x60a570) never fires -> stall.
  DON'T inject `callthis 6b83a0 ...` -- it crashed the game.
- 0x2053 LATER THE SAME DAY (SEND_MATCH_START=True path in login_server.py, now off again):
  1. 0x204B DeliverMatchLaunchWarning (u8 | f64 | f64 | u32 room; handler 0x6bd420) needs to go
     with the lobby data: it locks the slot, sets the skin override lobby+0x230 = 0 and runs
     VerifyAndLoadAllNeededRPS while the lobby still holds its refs. FIXES the champion build.
  2. The objects must be created BEFORE 0x2053: the charsys subscribes to the local player's
     controlled-agent notice (0x60a510 -> 0x4836f0; handler 0x60a570) only while NOT started
     (0x6bee50). FIXES charsys+0x100 / pending bit 8's first half.
  3. 0x2016 after 0x2053 puts the UI into the world-load screen (state 0x23). Without it the
     native load ran but the UI never transitioned.
  4. SOLVED (verified 15:32): started mode LOADS INTO THE WORLD. Flow on 0x20F2: 0x2029, 0x204C,
     0x204B; objects after MATCH_OBJECTS_DELAY; 1 s later 0x2053, then the ROSTER (generic
     notice 0x2 to the player, notice 0x1000005b, build_match_roster(); accepted only once
     started, 0x6c49a0 checks lobby+0xac), then 0x2016 + 0x206D. Result: SERVER LOAD COMPLETE,
     new BLUE/RED scoreboard with a 00:00 match timer at the top; banner, arrows, nameplate OK.
     Roster u32 fields must stay 0 for now: (team, champion variant, ...) crashed the UI script
     (rva 0xdaacf2). Minimap still green (0x64c2c0 never hit).
  (was) BLOCKER: in started mode the UI condition "player ready in world" (0x6b5200) calls
     0x6c39f0 = every entity in the lobby manager's participant map ([0x1777138]+0x58, count
     +0x5c) must exist and be placed. The map is EMPTY. It is filled by 0x6c49a0 (entries 0x60
     bytes, entity IID at +0x30) from listener 0x6901f0 = slot +0x98 of interface vtable
     0x1205930 (object built at 0x68fb1c, subobject +0x44). The server event that delivers that
     roster list is NOT found yet. Without it: no script notice 0x1000015c -> flow+0x78 never set
     -> pending bit 8 stays -> load stalls at 55%.
  - 0x2053's two lists are NOT players: elements are 0x24 bytes (u8 | wstring | u32 | u32 | ...),
    reader 0x441b20 -> 0x1a9580; probably name/value options.
  - Tools: tracer `--only` now accepts any rva (generic label); tools/live/noticemap.py /
    tools/live/subs.py dump an entity's notice-subscriber hash maps (layout in the scripts' docstrings).
- tracer.py `--only <rva>,<rva>`: slim mode (just those breakpoints, no watches, high hit limit).
  The full breakpoint set traps thousands of times a second while walking -> stutter. Extra slim
  bps: 0x20987e (smooth: local delta), 0x20991f (smooth: anim vars, logs cap = module+0x2d0).
- Analysis tools: regenerate tools/analysis/full.asm with
  `python fulldis.py` (run from tools/analysis, ~10 s).
- The memory notes referenced below (C:\Users\Eric\...) are not in this repo.

# RESULTS 2026-10-05 ~23:30 (verified by Eric) — details in memory note `ic-minimap-nameplate.md`
- NAMEPLATE (name, health bar, level, selection ring) WORKS: champion property 0x100000FA = 4 (LifeState Alive, kind 8).
- Minimap NOTE icons work (ping icon 0x10000083 sent explicitly); category 0x100004da kind 8 now sent too.
- PLAYER PINGS (Alt+click, event 0x2136) are answered: red triangle ground marker + minimap dot, 6 s.
- Guide-ping ground marker: bool 0x10000909 did NOT produce one. Still open.
- MINIMAP IMAGE: the HUD loads it when RecvNotice_DeliverMapData(0x48000d3e) is called (flashcall), so the
  only missing piece is the native trigger: property 0x100001d3 is storage GROUP 3 (store [entity+0x40]),
  which the wire property events never write, and setting it by inject fires no listener. PLAYER_LATE_PROPERTIES
  (0x100001d3 on resends) is therefore ineffective but harmless. Next idea: find what posts the engine notice that
  0x66a8e0 (listener vtable 0x1203a48, this-0x20) handles, or how 0x2053 "match started" fills the player.

# UPDATE 2026-10-05 NIGHT (static analysis, mostly superseded by the RESULTS block above) — memory note `ic-minimap-nameplate.md`

Three server changes are in place and waiting for one test launch (game + tracer are running
with new breakpoints; `python check.py` passes):
1. MINIMAP IMAGE: `PLAYER_PROPERTIES` now carries `(0x100001D3, 0x15, 0x40000991)` = current
   encounter DID. The map manager listens for that property on the LOCAL PLAYER object
   (0x60cbc0), resolves the encounter twin 0x49000991 -> prop 0x10000287 = image 0x48000d3e and
   invokes GM_MapManager.RecvNotice_DeliverMapData. Expect: real map image instead of green.
   Trace labels: "map manager: ...", "map: DeliverMapData to HUD".
2. MINIMAP NOTE ICON: `PING_PROPERTIES` now also sends icon `(0x10000083, 0x15, 0x13000A15)`;
   the note reader 0x64b150 takes icon/category from the ENTITY'S properties. Category
   0x100004da (twin value 0x12) not sent yet: kind unknown -> run
   `python propdef.py 100004da 1000019d 10000831 10000456 10000909 10000060` IN-WORLD
   (propdef needs breakpoint traffic on the main thread; at the login screen every id came back
   "NOT REGISTERED" because the injected calls never ran).
3. PLAYER PINGS ANSWERED: client event 0x2136 (f32 x | f32 y | u64 target | u32 type) ->
   `answer_ping()` creates a plain Map Ping 0x4000025a/b at (x, y) with PING_PROPERTIES and
   removes it after 6 s. Test: Alt+click / G on the ground -> minimap dot? ground marker VFX?
   Trace labels "map note: create for entity", "map note: ADDED", "entity prop listener 680cd0".

NAMEPLATE (overhead name + health + level) — not changed yet, instrumented: the HUD's
FloatyVitalsManager is fed by native 0x650a70 -> GM_UI.RecvNotice_UpdateFloatyVitalArray; an
entity gets in only through filter 0x60efc0: entity kind 7/8 (record field 0x50f; Batman's
wstate has 7 = ok), PerceivedType flags (property **0x1000019d**, bitmask: Character = 8,
Player = 0x200000, CapturePoint = 0x80000 must be clear; cached in the character component
+0xa4) must contain Character OR property 0x10000831 != 0, and a vitals component. The server
never sends 0x1000019d, so the filter probably rejects the champion. Next step after the trace
confirms it: send `(0x1000019D, <kind from propdef>, 0x200008)` on the champion agent (0x200008 =
Character|Player is a mask the client itself tests). Display type comes from property 0x10000456
(enum VitalDisplayType; Champion_VitalDisplayType value: see script) — may also be needed.
Trace labels: "floaty: notice 0x26 (entity iid)", "floaty: filter" (+ "passed ..." lines),
"floaty: entity ADDED", "floaty: flush arrays", "floaty: send ...".

GROUND MARKER at the guide ping: still open. The guide ping twin 0x49000a9c has two scriptlets
(field 0x8e): 0x3400053c (refs props 0x10000155, 0x10000909, 0x10000060) and 0x34000600 (the
arrows). Scriptlet class table = record 0x1e00055b (AlertPingScriptlet, GroupPingScriptlet,
AlertArrowScriptlet, GroupArrowScriptlet, ...; vars UseAlert, UseVFX, NearbyRange, TargetPosition,
PlayerIID, RetryDuration). 0x10000909 is referenced by NO native code -> scriptlet-only
property; try it as a bool on the ping once its kind is known. Record dump tool: the session
scratchpad `recdump.py <pack> <offset> <len> [strings]` (copy it to tools/ if useful).

# UPDATE 2026-10-05 (read this first; it supersedes parts of the 2026-10-01 text below)

Reference for the real Tutorial 1: https://www.youtube.com/watch?v=PL78fWMWceo (starts 0:03).
Frame-by-frame notes and all Superman captions: memory note `ic-tutorial1-reference-video.md`.
Other new notes: `ic-facing-fix.md`.

Done today
- Facing SOLVED: model forward = +y at yaw 0; motion header is now `0xAC 0x18` with an explicit
  i16 yaw (1e-4 rad) = heading - pi/2 (`facing_yaw()`). Verified by Eric.
- Intro cinematic is **0x35000026** (now `CINEMATIC_DID`). 0x35000025 (used before) is Batman
  walking up to a tower at the base = not the intro. Trigger any on the live game:
  `logs\send.txt`: `player 20f5 0001000000<did LE>`.
- Spawn moved to where the intro's last pan ends: (18.7, 60.4, 200.3) in lb 13cb; matches the
  video's first playable frame. OPEN: the scene there is very dark (fog of war / vision?).
- Tutorial start now reveals only HUD elements 18 (portrait), 15 (minimap), 35 (objectives), as
  in the video; `TUTORIAL_START_ELEMENTS`. Step logic: first completed walk -> 0x2009 objective 1
  completed (client fires UpdateObjective_State/_Text). 0x2009 cannot ADD an objective.
- Live tools: `logs\heading.txt` (radians, forces heading while standing), `physdump.py`.

Not working / dead ends
- The right-side objective tracker never appears (and per the video the tutorial does not use it:
  the objective is a TOP-CENTRE BANNER). Sending the banner StringInfo (objective flag bit11)
  did not show anything yet. Tried without success: inactive 2nd objective, enable off/on,
  element reveal/open, 8 s delay. Do not spend more time on the tracker; work on the banner
  (script ObjectiveBannerDisplay, MainHUD.m_obdObjectiveBannerDisplay).
- Player object = generic world state 0x2E000003 (entity 0x2D000002): entity is created but has
  no motion component / no 0xB0 listeners, cannot be placed, load stalls at ~35%. Reverted to the
  Batman world state (so the second, gliding Batman is still there).
- Detaching the tracer (`logs\tracer.stop`) and starting it again on the running game: the game
  was gone afterwards (crash not analysed). Avoid, or expect a relaunch.
- A breakpoint at rva 0x49994a (logs the HUD movie pointer + Invoke fn in the tracker-enable
  glue) was added to tracer.py for a planned "call into Flash" tool (Movie::Invoke = vtable
  +0x5c(name, result, args, nargs); GFx::Value = 16 bytes: ptr, type (2 = bool), 8-byte value).

DARK GAP AFTER THE INTRO FIXED (2026-10-05 ~22:30, verified): server re-sends the match objects as
soon as the client reports cinematic state 4 (tutorial_start) + EXE PATCH 4 (lighting re-eval
interval 2.5 -> 0.2 s, rva 0x11dcd6c / file 0x11db16c, backup
InfiniteCrisis_patched.before_env_timer_patch.exe). Both are needed. Details: memory note
ic-dark-world-lighting.md. Game is launched with restart_test.ps1 again (Steam route optional).

STATE AT ~21:50 2026-10-05 (verified by Eric from a Steam launch): intro -> guide arrows (green
chevrons) point at a ping entity 0x40000a9c at TUTORIAL_TARGETS[1]; walking within TARGET_RADIUS
completes the step (Batman/Superman lines, "Guide Arrows" hint, banner update); the old ping is
REMOVED with event 0x3 and a NEW ping object is created for the next target (moving a ping with
an update bundle makes the arrows vanish); second arrival -> drone lines, "Basic Attack" hint,
drone banner. Still missing vs the video at this point: the green ground marker + minimap icon at
the ping (ping icon 0x13000a15; bools 0x10000b96/b97 only turn the arrows yellow), the overhead
NAMEPLATE (name + health bar + level) and yellow selection ring under the champion, encounter
effects (fire column), the first drone (+ combat), minimap image. Client ping request = client
event 0x2136 (f32 x | f32 y | u64 target IID | u32 type), unanswered. Player record 0x4000007c
"Unnamed Player" (twin 0x4900007c, modelless) is the next thing to try for the player object.

GUIDE ARROWS / HINTS / BANNER (2026-10-05 ~19:20, verified by Eric):
- Banner = objective flag bit24 StringInfo (last on the wire). Hint panel = event 0x2 to the player
  (notice 0x1000027f, build_tutorial_hint; HUD element 32 revealed). Right-side tracker now off.
- Guide arrows = an entity from record 0x40000a9c "Map Ping" (pack 0xa00000b3); the client draws
  the chevrons toward it. Server: build_ping(step), TUTORIAL_TARGETS, TARGET_RADIUS (real arrival
  check), ping teleported to the next target (no delete event known). OPEN: ground marker + minimap
  dot at the ping, object deletion event, player record 0x4000007c "Unnamed Player" (no model?).
  A background analysis of those was cut off by the usage limit; restart it (see memory note).
- Steam launch: `restart_steam.ps1` (run in background; it waits 5 min for Play). MOVE_HZ = 60.

STATE AT END OF 2026-10-05 (verified by Eric in one clean launch, no manual steps):
load -> intro cinematic 0x35000026 starts in-world with Superman's 5 intro conversations (panel,
voice, captions) -> server sends 0x1ba at cinematic end, tracker shows "A Champion in Peril" ->
walk 1: Batman 0x193 + Superman 0x19c, objective text changes -> walk 2: 0x1ac + 0x1b8, drone
objective text. Facing + walk animation fine. Script table: `TUTORIAL_MOVE_STEPS`; all keys:
`tools\conversations_tutorial1.txt`. Memory note `ic-conversations.md` has the details.
OPEN, in suggested order: (1) scene is far too DARK compared with the video (fog of war / vision
for the champion? unverified); (2) world marker + guide arrows + real target positions instead
of "any walk counts"; (3) drones / combat; (4) top-centre objective banner text (widget open,
gets no data); (5) minimap image; (6) second, gliding Batman (player object); (7) "match
started" mode (0x2053) crashes — currently bypassed by exe patch 3; (8) the table-load race fix
(MATCH_OBJECTS_DELAY) has held for 1 launch only.

DARKNESS SOLVED (2026-10-05 ~18:30, verified by Eric): it was the client's DEFAULT lighting
environment (type 2 at [[0x1773518]+0xdc]+0x11c, chosen by rva 0x3e35c0). Fix: player object
property 0x956 (kind 8) = 0x10000016 (`PLAYER_PROPERTIES`). Details: memory note
`ic-dark-world-lighting.md`; tool `scenesnap.py`. Still open: it is dark for ~1 s after the
intro before the light comes on; fog of war is active internally but shows no dimming.
The notes below are the investigation trail (kept for the ruled-out causes):

DARKNESS INVESTIGATION (2026-10-05 evening):
- The world goes almost black when the intro cinematic 0x35000026 ENDS; playing cinematic
  0x35000025 afterwards makes it lit again (`logs\send.txt`: `player 20f5 000100000025000035`).
  Global, not positional. Not time of day (object [0x1758abc], +0x10; set via 0xc3b50).
- Probably NOT the fog-of-war mask: forcing controller byte [[0x1773518]+0xdc]+0x39 = 0 and
  zeroing [0x1772170]+0x48 changed nothing, with and without an active fog component.
- Fog of war itself now WORKS internally: the component (entity handle +0x88, vtable 0x12098e8,
  update 0x6b3520, manager list count at 0x1776c34) only activates on the LOCAL PLAYER's entity
  (gate 0x6add80) and reveals around that entity's 0x100000cf target. `PLAYER_AVATAR` is now the
  variant 0x40000086 (player object gets game components) -> count 1, one viewer (the agent,
  radius 12.0 from property 0x10000133). Tool: `fowdump.py <entity handle>`. Team on the player
  object is still -1 (not set).
- A background analysis of what the cinematic leaves behind was started; result not in yet.

LATER ON 2026-10-05 (supersedes the "Next" list below where they differ)
- Objective tracker FIXED: the objective CATEGORY must be sent in state 8 (Show); state 0 opens
  the tracker but draws nothing. `OBJECTIVE_CATEGORY_SHOW`. Found with `flashcall.py` (calls /
  reads the Flash HUD live, see memory `ic-tracing-toolkit.md`).
- CONVERSATIONS SOLVED IN PRINCIPLE (verified live: Superman panel + captions in chat log):
  event **0x2001 StartConversation** to the player object: u8 base | u64 IID (0) | u32 mode (1 =
  encounter table) | u32 key | u32 n + u64[n] participant IIDs (n = 1) | u8 1 | u32 instance id
  (0xFFFFFFFF = no finish report; else the client sends 0x2140 u32 id when done).
  Table = DID 0x40000cb7 (property 0x10000b21 of encounter twin 0x49000991). Intro keys:
  0x1b9, 0x22f, 0x22e, 0x22d, 0x22c, 0x1ba, then 0x193 (Gaslight Batman). The intro cinematic
  0x35000026 queues these itself when it is started IN-WORLD (not when started during loading).
- BLOCKER: the dialog manager only plays its queue when gate bits 4|8 of [[0x17758d4]+0x1c]+0x14c
  are set. Bit 4 is set only in the "match started" branch at ServerLoadComplete, i.e. when the
  lobby "started" byte ([0x1777138]+0xac) is 1 = event **0x2053**. With 0x2053 the client crashes
  during load (two different crashes, see the comment at `SEND_MATCH_START` in login_server.py).
  Workaround for testing: `logs\tracer.inject`: `poke32 [[base+17758d4]+1c]+14c 8c`.
- EXE PATCH 3 (2026-10-05, backup `InfiniteCrisis_patched.before_dialog_gate_patch.exe`): file
  offset 0x67ef34 / rva 0x67fb34 `83 e2 0c 80 fa 0c` -> `83 e2 08 80 fa 08` (conversation queue
  tick 0x67fad0 now needs only gate bit 8, not 4|8), so conversations play without 0x2053.
- The cinematic is now sent 5 s after the load-complete notice (`CINEMATIC_DELAY`), see below.
- (old note) The intro cinematic is still sent during the loading screen; it should start when the curtain
  goes up (client notice: event 0x2 to the player, body 5e010010..., arrives at
  ServerLoadComplete, curtain up ~5 s later).
- tracer.py: first-chance exceptions now log stack rvas + registers reliably.

Next: Superman conversation panel + captions
- Caption strings live in string table **0x2B0001EE** (pack 0xa0000256), e.g. token 0x06dd4811
  "Gaslight Gotham is under attack.", 0x06dd4812, 0x06dd4813 ...; DID prefix 0x2B = string table.
  Nothing in the packs references those tokens, so the server sent them as StringInfo
  (table DID + token).
- Candidate event **0x217a** (serializer 0x445170: u8 | u64 | u32 | u32 | u64 | u32 | u32 n +
  u32[]; handler 0x667110 builds a 0x48-byte item, vtable 0x1202648, queued on global
  0x17758e8). Timed sequence class: vtable 0x120298c (process = 0x6673c0: entries of 0x68 bytes
  at +0x20, f64 time at entry+0x50, shows a line via 0x659300 -> GM_Dialog.
  RecvNotice_ShowConversationSlot 0x497090). The link between the two is not worked out yet.
- Then: encounter objects (fires, drones, energy wall), world marker + guide arrows, minimap image.

---

# Infinite Crisis private server — handoff (2026-10-01, ~22:50)

Goal: make Tutorials 1–3 playable on the private server. Tutorial 1 ("A Champion in
Peril", Gaslight Batman) now loads into the world natively and is partly interactive.

Detailed, dated findings live in the memory notes:
`C:\Users\Eric\.claude\projects\D--SteamLibrary-steamapps-common-Infinite-Crisis-Steam\memory\`
— read `ic-match-flow.md` (the UPDATE sections at the bottom are the most recent and
most important), then `ic-tracing-toolkit.md`.

## Setup

- Game dir: `D:\SteamLibrary\steamapps\common\Infinite Crisis Steam`
- Server: `_server\login_server.py` (SOAP :8888, login/user TCP :9000, game server :9001)
- Client: `InfiniteCrisis_patched.exe`. All addresses are RVAs. Two patches so far:
  1. RSA public key replaced (login).
  2. **Oodle patch** at file offset 0xbe3862 / rva 0xbe4462: `56 8b cb e8 66 25 b2 ff`
     -> `33 c0 90 90 90 90 90 90`. Stops the client compressing what it sends on the
     game connection (OodleNetwork1 TCP), so the server can read it.
     Backup: `InfiniteCrisis_patched.before_oodle_patch.exe`.
- Disassembly: `_server\tools\analysis\full.asm` (operands are VA = rva + 0x400000).
  Tools there: `icdis.py <rva> <len>`, `fs2.py` (function start), `xref.py`, `vt.py`,
  `serdump.py <serializer rva>`, `events.tsv` (event id, vtable, execute, serializer, calls).

## Test loop

1. Edit `login_server.py`, run `python _server\check.py`.
2. PowerShell: `& "...\_server\restart_test.ps1"` (do not pipe it).
3. Eric logs in (test@test.com / test): Play Now -> VS A.I. -> Tutorial -> Tutorial 1 ->
   Select -> Launch -> Esc. He waits for the go-ahead and reports with screenshots.
4. Read `_server\logs\trace.log` from the last "tracer start" line and `logs\requests.log`.

Rules: never ask Eric to use a debugger; don't ask whether to continue, only ask for
test clicks. Never hot-swap `tracer.py` while the game runs (crashes it); edit it by
writing `.new` then `os.replace`, and relaunch with the restart script. Bash heredocs
mangle backslashes: write patch scripts with the Write tool, or avoid `\n`/`\x` in heredocs.

## Live tools (no restart needed)

- `python _server\peek.py "<expr>"` — read client memory (`base`, hex, `+`, `[x]`).
- `logs\tracer.inject` (consumed once): `poke8/poke32 <expr> <hex>`, `call <rva> [args]`,
  `callthis <rva> <ecx expr> [args]`, `watch [RW ]label|expr`. Return value is logged
  as "INJECT call returned eax=". Scratch memory: rva 0x190e400..0x190efff.
- `logs\send.txt`: lines `<dest: player|svc|hex id> <event hex> <body hex>` sent on the
  login connection (within ~2 s).
- `logs\spawn.txt`: `region lbx lby cell x y z` (lbx/lby/cell hex) — teleports the champion.
- `logs\module.txt`: `seq type` — swaps the movement module (bump seq each time).
- `_server\pos.py <phys hex>...` — viewer + physics positions.
- `_server\navprobe.py <lbx> <lby> <x> <y> <z> [radius]` — nearest navigable point
  (needs `logs\agent.txt` = agent entity pointer from an "issue command" trace line).
- `_server\propdef.py <prop id hex>...` — property kind / storage group from the client.
- `call 45d670` via inject returns the controlled agent's entity handle:
  `[h]` physics, `+0x38` properties, `+0x54` motion component, `+0x80` vitals component.

## What works (all automatic, no tracer hacks)

- Queue -> lobby -> referral -> game connection -> match load -> PVE loading screen.
- Two objects are created: player `0x0200000000000001` (still Batman's world state
  0x2E0001B2 — STOPGAP, shows as a second Batman) and champion agent
  `0x0200000000000002` created from the **variant record 0x40000086** (needed: game
  components such as vitals/skills are only attached to type-0x40 descriptors, rva 0x69d7a0).
- Position message (event 0xB0 inside the create bundle): flags 0x62 | module seq | module
  type 1 | sub 0x0F | f64 time | Position (lb, cell, f32 x,y,z) | u16 | motion header.
  The movement-module part (flag 0x20) is what makes the client place the entity.
- Player property 0x100000cf (controlled agent) and 0x100005e8 -> agent id, sent on the
  resends so the client sees a change; that sets the readiness flag the UI graph waits for.
- Play area: landblock (0x13,0xcb) only (navmesh info exists just for that block):
  street x ~16..155, y ~18..64, z ~200. Spawn (60, 44.5, 200.2). The plaza in (0x14,0xcb)
  is the cinematic set; clicks there are rejected by the client's pathfinder.
- Intro cinematic 0x35000025 (event 0x20F5 to the player) plays ~23 s, then the client
  reports event 0x2 to the player object (`17010010 | u32 4 | DID`) -> `tutorial_start()`.
- `tutorial_start()` sends, all addressed to the PLAYER OBJECT (not a service):
  - 0x213d HUD reveals (u8 | u32 element | u32 event | u32 highlight | u32 did), event 1
    FirstRestored, elements 2,18,14,15,35,6,9,17,25,12,7,20,31;
  - 0x42 vitals to the agent (list 1 zeros, list 2 values; HUD shows list1+list2);
  - 0x2034 objective list with one category + one objective;
  - 0x2075 tracker enable, 2 s later (an immediate enable is ignored).
- Champion properties on the agent (name, team, level, XP, skill points, icons) fill the
  portrait. HUD shows portrait, 600/600 + 100/100, skill icons, objective text.
- Right-click movement: client sends 0x20EE on the game connection (u32 cmd 4 | u64 | u32 |
  Position | u8); server walks the champion in a straight line at 6 u/s, 10 Hz.

## Walk animation — partly working (tested 22:55)

The replay movement module hard-teleported every frame because the second sequence byte
(motion header bit 0x1000) was never sent and 0 counts as "changed" (rva 0x209af0). The
smooth branch (0x20b5f0 -> 0x1c9fe0 + 0x2097e0) is the one that sets the animation
variables (floats 0x1f1 / 0x300 / 0x501 on the entity's animation component). Header is
now `0xA4 0x1A` + f32 heading + f32 speed + u8 teleport seq + u8 1.

Result (Eric): of the two Batmans, ONE now plays the walk animation and the other still
glides; NEITHER turns to face the direction of travel. Likely the animated one is the
champion agent (variant 0x40000086, has the game components) and the gliding one is the
player object (bare world state) — not confirmed.

Verified live after the test: the smooth branch is now taken (0x20a270 returns to 0x20b804,
95+ hits; only 4 initial hard teleports), and BOTH objects' physics quats are
(0.942, 0, 0, -0.336) = z-rotation of -0.685 rad, matching the last move's heading
(atan2(-2.8, 3.3)). So position, heading and the smooth path are all correct in physics.

What 0x2097e0 sets: it rotates the frame's movement delta into the entity's local frame
(0xc7a50), then float 0x501 = local velocity part, 0x300 = forward speed clamped to
[motion comp+0x2d0], 0x1f1 = angle between the current and target orientation * const
(a turn-rate input). The walking Batman therefore gets a forward speed, i.e. the engine
agrees that his heading is "forward".

Facing is the open part: the heading does reach the physics object (quat = z-rotation by
the heading, read live), but the visible model does not rotate. Next ideas: look at what
0x2097e0 computes (it rotates the movement delta with 0xc7a50 before setting the three
animation floats — may be a local-space direction, i.e. he "strafes"), try the explicit
yaw field (header bit 0x08, u16 in 1e-4 rad) instead of bit 0x200, and check the
heading convention (atan2(dy, dx) assumed; cos/sin order at 0x17dce8 unverified).

## Open items, roughly in order

1. Facing/turning (see above), and remove the second, gliding Batman (item 5).
2. Voice-over / captions: UI side is GM_Dialog.RecvNotice_ShowConversationSlot /
   HideConversationSlot (native 0x497090 / 0x496c00, called from 0x658ee0 <- queue
   processor 0x6673c0) and HUD element 3 (ConversationUI). The server event and the
   tutorial's dialogue record ids are not found yet. 0x2087 is only a modal OK dialog.
   0x217a feeds a different queue.
3. Objective heading shows "undefined" (not the category title; cosmetic).
4. Minimap image (green placeholder), XP bar "0/0" (InqXPForLevel unanswered).
5. Real player entity instead of the second Batman (try descriptor 0x2D000002 or find
   the proper player record).
6. Skills (Q/W/E/R presses -> client events not yet examined), enemies/drones, combat.
7. Tutorial step logic: detect arrival at the marked location, advance objectives with
   0x2009 (single-objective update; do not re-send 0x2034, it closes the tracker).
   Objective/prompt texts are in pack 0xa00000b3 (`tools\strings_all.tsv`).

## Things that crash or break — avoid

- Sending 0x42 to an entity without a vitals component (bare world state) crashes the
  client (rva 0x6b1bd9).
- Restarting the tracer while the game runs.
- Re-sending 0x2034 closes the objective tracker; enable again after a pause.
- Removing then restoring the controlled-agent link re-fires ServerLoadComplete.
- Movement module types 9 and 3 stop the champion responding; type 2 behaves like 1.
