# Infinite Crisis client: reverse-engineering notes

What this project has learned about the 2015 Steam client (`InfiniteCrisis.exe`, 26,500,568 bytes,
SHA-256 `463adfff…a33e31`) and its data packs. Most protocol formats were first worked out by
[EricHardiman/infinite-crisis-server](https://github.com/EricHardiman/infinite-crisis-server); this file
covers what was added here. The development log with every experiment (including failed ones) is
[`CHANGELOG.md`](CHANGELOG.md).

Status labels: **confirmed** = verified in game; **probable** = consistent with the code and data but not
verified in isolation; **guess** = placeholder value the server uses until something better is found.

Contents:

1. [Conventions](#1-conventions)
2. [Data packs and records](#2-data-packs-and-records)
3. [String tables](#3-string-tables)
4. [Skill data (Gaslight Batman)](#4-skill-data-gaslight-batman)
5. [Protocol events](#5-protocol-events)
6. [Object properties](#6-object-properties)
7. [Scriptlets (animations and effects)](#7-scriptlets-animations-and-effects)
8. [Skills in the HUD: ranks, cooldowns, enabled buttons](#8-skills-in-the-hud-ranks-cooldowns-enabled-buttons)
9. [Props without an entity: carriers](#9-props-without-an-entity-carriers)
10. [Minimap: map image, notes, pings](#10-minimap-map-image-notes-pings)
11. [Camera and screen mapping](#11-camera-and-screen-mapping)
12. [Tutorial 1 data](#12-tutorial-1-data)
13. [Exe patches](#13-exe-patches)
14. [Remaining Tutorial 1 content](#remaining-tutorial-1-content)
15. [Open questions](#15-open-questions)

---

## 1. Conventions

- **Addresses.** `VA = rva + 0x400000`. For `.text`, file offset = `VA − 0x400C00`.
  For `.rdata`, `VA = file offset − 0x1177400 + 0x1579000`. The patch table in `icserver/patcher.py` uses
  file offsets and gives the rva of each one.
- **DIDs** (data IDs) are 32-bit; the top byte is the type. Types seen so far:

  | Prefix | Meaning |
  |---|---|
  | `0x10` | Property / key name (scriptlet keys, property IDs, enum keys) |
  | `0x13` | Image / texture (e.g. skill icons, minimap icons) |
  | `0x1D` | Template / placement record |
  | `0x2B` | String table |
  | `0x2D` | `.entity` (model/skeleton definition) |
  | `0x2E` | World state (what is placed in the world) |
  | `0x34` | Scriptlet |
  | `0x35` | Cinematic |
  | `0x3B` | Scaling reference (used by skill tooltips) |
  | `0x40` | Entity class (what the server sends as an object's class) |
  | `0x48` | Data record (skill sets, champions, formula sheets…) |
  | `0x49` | Twin record of a `0x40` class (same low bits; e.g. `0x4900025A` ↔ `0x4000025A`) |
  | `0x4A`–`0x4F` | Not a game type: the patched client reads these as "prop carrier N + world state" (section 9) |
  | `0xA0` | Pack ID (`rp\*.rp`) |

- **Object IDs** used by this server: `0x0200000000000001` local player, `…02` champion,
  `…30 + step` guide pings, `…40 + n%0x20` player pings, `…60 + step` tutorial markers,
  `…70 + n%0x10` minimap note companions, `0x02000000000001xx` scenery.

## 2. Data packs and records

`rp\*.rp` files are Turbine "10PR" packs (`icserver/rp.py`):

- Header at 0: `u32` payload size at `0xC`, `u32` record count at `0x10`.
- Payload from `0x400` in `0x20000`-byte blocks whose last 4 bytes are a trailer.
- Payload = `count × u32` DIDs, then **one zlib stream** with all records concatenated.
- In the map packs and `0xA0000038` that stream is `78 01` + **stored** deflate blocks (0xFFFB bytes each): the records
  lie verbatim in the file, so a same-length edit is a byte edit plus the stream's Adler-32 (big-endian, after the last
  block); the block trailers are lengths (`icserver/terrainfix.py`, `docs/re-notes/map-audit-all.md` 1.3).
- Records have **no size table**. A record starts with its DID; a real `0x48` record header is the DID
  followed by four zero bytes (a DID followed by anything else is usually a reference). `tools/skills.py`
  bounds a `0x48` record by the next real `0x48` header (cap 40 KB).
- After the payload (rounded up to `0x400`) come extra zlib streams (`78 01`), each aligned to `0x400`:
  these hold the **string tables** (section 3).

**Property trees.** Records store properties as triples `key, key | type << 28, value`: the second word
repeats the key's low 28 bits with a type nibble on top. A string reference is two words:
`token, 0x2Bxxxxxx` (token + string-table DID).

Useful packs: `0xA0000256` (Tutorial 1 placement: records `0x1D000771` / `0x1D0007EE`), `0xA0000257`
(character variants with health, e.g. "Soldier Drone" `0x40000C72`), `0xA0000122` (Gaslight Batman's skill
set), `0xA00000B8` (Gaslight Batman's champion record).

## 3. String tables

Each string table is a zlib stream in a pack's tail (section 2):

```
u32 table DID (0x2B…) | u32 language | u32 count
entries: u32 token | u32 nparts | nparts × (u32 len + len UTF-16LE chars) | u32 m | m × u32
```

The bytes between entries are not fully understood, so `tools/skills.py` finds entries by scanning and
validating them. Multi-part strings are joined with `{}` where the game inserts values.

Notes:

- **Tokens repeat across tables**, so a string is identified by `(table DID, token)`, never by the token
  alone (keying by token alone mixed up texts between champions).
- Several languages share the same tokens; the English text is the plain-ASCII one.

## 4. Skill data (Gaslight Batman)

`python tools\skills.py "Gaslight Batman"` writes a readable dump to `logs\skills.txt`.

| Record | Pack | Contents |
|---|---|---|
| `0x48000615` | `0xA0000122` | Skill set: **Echoes** (passive), **The Bat Scream** (R), **Sonic Batarang** (Q), **Sonic Shell** (W), **Bat Flight** (E) |
| `0x48000617` | `0xA00000B8` | Champion record → template `0x48000732` |

Per-skill properties found so far:

| Key | Meaning |
|---|---|
| `0x10000302` | Skill icon (`0x13…` image) |
| `0x100002A3` | Formula sheet (`0x48…` record) |
| `0x100004B6` | Tooltip argument: stat ID |
| `0x100004B7` | Tooltip argument: base value |
| `0x100004D2` | Tooltip argument: per-rank value |
| `0x100004D7` | Tooltip argument: scaling reference (`0x3B…`) |

**2026-10-16 (full skill-set read, `catalog/data/skills.tsv`):** stat **15 is the cooldown** in seconds (it drops per rank in every champion's kit; Gaslight Batman: Q 5, W 8, E 20 −2/rank, R 110 −10/rank), stat **3 the cost** (Will, stored negative: Q −40 −10/rank, W −50, E −75), stat **5 the damage**, and stat 18 probably the range (R 230). The older reading below took stat 18 as the cooldown.

Example, Sonic Batarang (Q): damage 25 + 60 per rank, ratios 0.7 / 0.6; stat list `18 → 9`, `30 → 14`,
`17 → 4`, `22 → 1.25`, `15 → 5`. **Stat 18 = 9** is taken as the cooldown in seconds (probable). The other stat
IDs are not identified yet. Comparing them with the in-game tooltips of Q/W/E/R will name them.

Kit used by the server (`icserver/abilities.py`, slots as the client numbers them: 0 basic, 1 Q, 2 W, 3 E,
4 R, 5 passive):

| Slot | Skill | Cooldown |
|---|---|---|
| 1 Q | Sonic Batarang | 9 s (from stat 18) |
| 2 W | Sonic Shell | 12 s (guess) |
| 3 E | Bat Flight | 14 s (guess) |
| 4 R | The Bat Scream | 80 s (guess) |

`[combat] cooldowns = {1 = 9.0, …}` overrides them; `enforce_cooldowns` rejects casts during a cooldown.

## 5. Protocol events

Events this server sends or handles (most were documented by the earlier project; `messages.py` has the
byte layouts).

**Server → client**

| Event | Meaning |
|---|---|
| `0x2`, `0x2001`, `0x2009`, `0x2034`, `0x2075` | Tutorial hint, start conversation, objective update, objective list, objective tracker enabled |
| `0x3` / `0x4` | Remove object / create object (with properties) |
| `0x42` | Vitals (health, secondary resource) |
| `0x8D` | Start scriptlets on an entity (section 7) |
| `0xCE`, `0xEB`, `0x2024`, `0x209D`, `0x20ED`, … | Login-time data: character set, local player, encounter info, master character list, champion data |
| `0x2016`, `0x2028`, `0x2029`, `0x204C`, `0x206D`, `0x20AD`, `0x20C0`, `0x20FA`, `0x2031`, `0x20AF` | Queue, lobby, loading and match entry |
| `0x2053` | "Match started". Sending it makes the client go back to the loading screen (it is off by default: `[match] send_match_start`). The dialog gate it normally opens is patched instead (section 13). |
| `0x20F5` | Play cinematic (`0x35…`) |
| `0x20F8` | **Skill cooldown** (section 8) |
| `0x213D` | HUD element event (show / hide / highlight, e.g. the skill "+" buttons) |

**Packs after a match (fase3-gs).** The menu does not keep encounter templates: each InqPVPEncounters query
(`0xa68030`) looks every encounter DID up again (`0xa68372 call 0x8535d0` -> DB loader `0x43ce00`), and the lookup is
null when the record's pack is not loaded; the encounter is then skipped and QueueKey (`0x86e060`) is (0, 0). The
0x49 / 0x48 encounter records live in **0xA00000B3**, loaded once at start-up (loader `0x9DD580`) without a pin
(entry flag 0x1000). A pack named in 0x20AF (gmConnectionManager+0xB4, `0xa99f00`) joins the ResourcePackLoader's
match-data list (`[0x1b75808]+0x18`, LoadMatchData `0xa99460` -> `0xa08e90`), which is released by `0xa08860`
(next LoadParentRPs) and by the wrapper-loaded callback `0xa08ed0` (script node 0x1000018F UI_ExitWorldLoadWrapper,
`0xab52a0`). A release unloads at once (`0x9e3e20` -> `0x9dd930` -> `0x9dd5e0`). So naming a start-up pack in 0x20AF
unloads it at the end of the match, and 0x2024 / 0x20FF never load packs: the menu has no encounters until a
0x20AF names B3 again. ics leaves the start-up packs out of 0x20AF (`[ics] resident_packs`). The encounter manager
itself survives the teardown (its reset `0xa786a0` does not touch +0x228, so 0x20FF stays accepted). Exit hazard:
`0xabc480` skips the teardown while lobby+0x4CA / +0x4C8 (RPs loading) are set, leaving +0x4CD "exiting" set, and
then the room-created handler `0xabde80` returns early; 0x2021 should not come while lobby RPs are loading.

**Announcer enable and channels (fase3-gx).** 0x2039's exec 0x8b2040 resolves the destination like 0x2001 (player
1 works) and calls 0xa7fe60 -> 0xa77da0 on the dialog system [0xa12d50()+0x1c]. Bit 0x4 of [dialog+0x14c] is set
only by the handler of the empty notice **0x10000205** (0xa8ea40 -> 0xa8eaaa: needs lobby+0x4BC != 0; also raises UI
event 0x33, starts the turret warnings, 0xabf090) or the view-match branch of 0xa964b0; bit 0x8 by UI script node
0x10000179 (0xab46c0 -> 0xa13b20). Channels: 0xa8f0f0 clears all but 0; 0xa35dc0 fills channel 1 with the shared set
(template 0x10000803) and 2 with the encounter's (0x10000802); 0xa282b0 looks the event up in the channel's set
(0x1000080A list). Announcer line ids share the conversation-key space (Crime Alley event 49 = Tutorial 1 keys
0x1B4-0x1B7), so 0x2001 plays them.

**Announcer, turrets, spawners (fase3-gv).** The announcer is server-driven: 0x2039 (exec 0x8b2040, handler 0xa7fe60
-> 0xa77da0, returns unless the dialog system's [this+0x14c] & 0xC == 0xC; flag bit 2 needs arg 1) reads 0x100003BD /
0x10000865 / 0x10000806 (match event) / 0x10000864, 0x10000812 / 0x10000811 (source / target IID), 0x1000081D /
0x1000081C (teams); 0xa309d0 picks the line from the encounter's set (template 0x10000802: Crime Alley 0x40000D4C,
events 10, 15, 17, 31-37, 40, 41, 49, 50, 55, 56, 58, 61, 63, 64; shared 0x4000047A: 8, 18-30, 52) and 0xa596b0 plays
it. 0x100002EB billboard types: 2 generic, 6 location, 7 tie, 8 loss, 9 win, 10 / 11 team victory. Timeline banner
0x10000424: u32 event | u64 iid | 3 x u32 | u8 | u32 | f64 time | u8 | u32 n | n x (StringInfo, StringInfo, u32 7) |
f64 end. Crime Alley's layout pack 0xA00002E6 places the turret body 0x2E000AA0 and head 0x2E000AA8 (the cinematics 0x3500002A / 2B add TurretBasePlate
0x2E000A9F under it; the match spawns it too, fase3-hb) at (65 / 95,
77.5) and the spawner 0x2E000D03 at the lane mouth; the body's tables hold Target_Acquired 0x1000014A, Target_Lost
0x1000002C, Object_Ranged_Attack 0x100002E0, Vfx_Targeting 0x1000005C; the head's Vfx_Startup 0x1000018E and the
team colours Vfx_Active_Red 0x100007F2 / Blue 0x100007F6 / Purple 0x10000D86; the spawner's Vfx_Spawner_Tier01 /
02 0x10000B1A / B1B and Vfx_Active_State0 / 1 0x1000005D / 0x1000006B. Bat Scream (0x34000039) launches missile
0x40000092 (script 0x34000043: each hit S5 -> S1, damage diminishing per collision, back to S4 for the next).
Vfx_Targeting loops on the head until something replaces it: no 0x8D form stops one run, so a turret that loses
its target sends Target_Lost on the body and Vfx_Stop + Vfx_Active_<team> on the head (fase3-hk). Structures block a
navmesh footprint (`match_structure_radius`, 1.6 m for turrets), so melee reach must be counted to that edge, not the
centre (Atomic Green Lantern, fase3-hk). diag --graph (fase3-hk) showed every cast 0x8D's graph event delivered to the
champion's graph (entity flags +0x118 = 0x49), so the client side of skill animations is complete.
**Emotes (fase3-hk, docs/re-notes/emotes.md).** Alt+Numpad1-5 (keymap; not Ctrl+number) -> input 0xa8a8e0 ->
0xa0ab70 code (Joke 0x16, Taunt 0x15, Laugh 0x17, Dance 0x18, Oath 0x1C) -> 0x964060(local player) -> WLib 0x28F:1
(0xa60c) looks the code up in EmoteDirectory 0x40000012 (pack 0xA00000B3, list 0x1000002D, enum 0x10000A8F) and calls
stub 0xbf5c -> event 0x9F, message 0x81970006, blob u32 emote record DID. Nothing plays locally; the server raises the
champion graph's Emote_* event (scriptlet 0x100001E3 + 0x780), whose graph runs RunScript_Vfx_Chr_Emote_* itself.
**Skill second stages (fase3-hk, docs/re-notes/skill-second-stages.md).** A skill's states end on the cast end signal
(OnCastSignal 0x1000000F 2): S2 raises skill_to_locomotion 0x10000002 and EndSkill, so a cast end sent too early cuts
the animation (Grab's arm, Meltdown's throw); the client never reports cast timing. Grab's missile 0x340002C1 waits
after SetSkillAttached (node 0x10000005) for 0x10000022 (attached: S9 AttachEntity + RaiseGraphEvent(Shooter)
0x10000331) or 0x10000014; its T6 ends on 0x10000005 (back). StopScriptletKey (node 0x10000012) signals the live run
(client 0x993DB0 -> 0x588A80 -> 0x57C4B0(key, signal 1)); on the wire a 0x8D entry with a live instance number is a
signal (0x6279D0 -> 0x57B510), its bit set = compact bit count + bytes. Missile / spawned classes (0x40000484/5/7)
have world states 0x2E000C08 / C4C / C01 whose tables (0x1D0003D2-D8 in pack 0xA0000150) hold Vfx_Active /
Vfx_OnInit / Vfx_OnExplode. AGL's champion tables 0x1D0003CE/CF/D0 do not parse with Data.script_table, and the
effect tables 0x1D0003D3/D6/D7/D9 are named by no record (only the pack's record list), yet Smash 0x100008AB resolves
on the client: it must find them another way (open).
Champion move speed is the stats record's 0x100005E4 (base 3.65-3.9 m/s, growth 0.005 per level), fase3-hl. A
structure unlocked late (dampener / core turret / core) must be rebuilt with 0x100007D9 = true in its bundle: a 0x6
change alone does not move the linked status 0x10000249 (P, fase3-hl). The diag --graph run of fase3-hk saw the stop
signal path (0x57B510 -> 0x57C4B0) taken.
**Emote wire form (fase3-hm, captured).** Event 0x9F body = u32 0x81970006 | u32 4 | u32 emote record DID (no leading
u8); path confirmed by diag --emotes (0x68A8E0 -> 0x60AB70 -> 0x564060 -> 0xA1C90 -> 0x1624F0). Stealth strips:
world state 0x2E000D36 + brush status 0x4800028C (positions G). Costumes are full replacements: Samurai 0x490003C7 ->
0x2E000A86 -> 0x2D00089E (pack 0xA000010C) vs base 0x49000086 -> 0x2E0001B2 -> 0x2D000115 (0xA0000076);
docs/re-notes/costume-model-overlay.md.
Keymap (fase3-hn): Documents\InfiniteCrisis\infinitecrisis.keymap, MetaKeys 1 Shift / 2 Ctrl / 4 Alt; an action may hold
several bindings, a key + modifier only one; the in-match section binds Ctrl+1-4 to DoNothing by default.
**Script owner block and resources (fase3-ho, docs/re-notes/aww-kit.md).** Operand source 2 = the entity's owner block,
shared by every script on it (a passive's LoadSkillStats writes values other skills read). SpendCost 0x10000031 adds a
signed amount to vital values[0]. A champion's resource vital is its twin's 0x1000000C (5 Will, 6 Rev, 4, 1, 7), max
= stat 0x10000432. A basic attack hit raises 0x1000008B {TargetIID} on the attacker. Crime Alley stealth tiles: world
state 0x2E000D36, 4 x 2 m, long side along y at yaw 0; placed by the server (no record places them).
**Countdown and keymap (fase3-hp, docs/re-notes/countdown-keymap-gaps.md).** Pre-match captions = announcer line keys
(table 0x2B000093, record 0x4000047A) sent as conversation 0x2001; no announcer event set reaches them, so 0x2039
cannot. Keymap: loader 0x404B20 reads the file (0x603570) then merges the packed defaults (0x603450, pack 0xA0000038
record 0x22000004); one binding per section + key + meta, the later merge wins; a parse error drops the file; saver
0x4066D0. Kit events (kit-audit-*.md): 0x1000008A skill hit, 0x100000ED damaged, 0x10000196 skill used, 0x10000012 /
0x10000007 death, 0x10000098 kill. Base gate wall lit by side 0x100007A2; stealth hotspot class 0x4000039D (box
0x4BB / 0x31, status 0x100002C4 = 0x4800028C).
**Map loading and lighting (fase3-hp, docs/re-notes/map-loading-deep-scan.md).** 0x20AF -> 0xA99F00 -> 0xA99E20
(ruleset 0x1000028A, map pack 0x10000406) -> 0xA99370 packs -> event 0xCC; landblock 0x548F30 -> 0x5EC890 -> 0x549510
(terrain 0x80, statics 0x82, property bags 0x5921E0 / 0x592130, nav, terrain mesh, entities); lighting 0x7F3390 ->
0x7E35C0 key = player 0x956 (else 0x5CC, 0x216, 2) -> 0x5A3570 region table 0x04000000 -> environment record (sky
0x7ED100, key light 0x64F050, fog 0x64E4E0, ambient 0x6509A0; a missing record leaves the scene unlit). Crime Alley
0x10000002 -> 0x08000003. Music template 0x10000ADC; switchable ambience 0x1000065C/D (not sent yet).
Per-map lighting keys (fase3-hq): Coast City 0x1000001B, Gotham Divided 0x1000001C, Gotham Heights 0x1000000A (B /
D also exist). Minion templates carry two vision radii 0x10000133 (3.0 and 6-8); the smaller one is used.
Big maps (fase3-hq, docs/re-notes/map-gaps-*.md): Gotham Divided announcer set 0x40000554, phase pod 0x40000A79
(graph raider_open / leviathan_begin) -> Raider 0x40000938 -> Leviathan 0x40000937; Coast City set 0x49000534, device
table 0x1D0002FE vs pad table 0x1D000924, device shot = pad skill 0x4800064A, core relay beams on 0x2E0013EE; Gotham
Heights set 0x4900047E, Power Core 0x400003F2 (ws 0x2E000B47), Orbital Cannon 0x40000511 (ws 0x2E000D12, id 165, core
script 0x340002CF), points take Vfx_TeamColor_SetContention / SetNull, not the CapturePoint states.
Announcer (fase3-hq, docs/re-notes/announcer-and-map-elements.md): event sets per encounter 0x10000802 (CA 0x40000D4C,
GD 0x40000554, CC 0x40000534, GH 0x4000047E) + shared 0x10000803 = 0x4000047A; per event 0x1000082A = acting team's
line, 0x10000829 = the other team's; a 0x2001 line key plays only if the map's layout pack holds it; the original
server played lines with script node 0x10000121 [line, event, .., team, other].
**Skill animation hooks (fase3-hq, docs/re-notes/animation-deep-scan.md).** Champion graph = 0x1A Havok packfile
(AGL 0x1A000821 in 0xA0000150, Gaslight Batman 0x1A0002E7 in 0xA0000122); skill states notify
turbineEventHookPayload {script DID, code} (1 start, 2 exit, 3 hit, 5 missile out, 6 hold) on enter / exit and from
clip triggers; codes = OnCastSignal 0x1000000F; no client reader (the server times them). Graph variables come from
entity properties via 0x55A830 -> 0x559F50 -> map 0x5594C0; the Lua onCosmeticEarlyOut fires Global_Locomotion when
Property_Slider_Propel >= 1 or Property_Slider_Turn != 0. data/skill_hooks.tsv from tools/graph_hooks.py.
**Dialog and watchdog (fase3-hr, docs/re-notes/dialog-shield-disconnect.md).** 0x2001 plays only from the
conversation catalogue (template 0x10000B21: Tutorial 1 0x40000CB7, Tutorial Advanced 0x40000CE3; no PvP template); an
announcer line plays by 0x2039 with 0x100003BD = key (0xa596b0(key, channel); channel 1 shared set 0x10000803, 2 the
encounter's 0x10000802, 3 a set loaded by 0x202A u32 DID via 0x8b2230 -> 0xa1b400). Connection watchdog 0xa9af20: 60 s,
armed by an accepted 0x2016, shows "Unable to connect to Match" (table 0x2B000010) and tears down (0xabc480); patched.
**Beams, timed groups, graph variables (fase3-hr).** A scriptlet beam (action type 2) ends at the owner's 0x100004E2
(creator IID). Scriptlet records hold timed groups `6 | f32 s | 6 | n` (the per-action word is a node id, not a frame).
Graph variables are bound to properties by the 0x1C record's hash {property id, variable index} (loader 0x55D8E0 ->
0x55C980 -> 0x55C130; watcher 0x559150, write 0x55A830 -> 0x559F50); 0x100006FE Attribute_AttackSpeed is the only
server-fed one. Property watchers register through 0x58BA40 (notify fires the creation value).
**Profile icons (fase3-hs, docs/re-notes/profile-icons.md).** CallingCardDialog (movie 0xA00000D0) has 5 protector icon
slots; the list = 0x20B8 items of ContentType 3, mapped by ProtectorIconManager from record 0x48000803 property
0x10000848 (134 x 0x10000847 WC DIDs 0x400005D4..0x40000F17); selection 0x2093 u32 WC | u32 slot, confirm 0x2154, all
5 by 0x2190.
**Stolen Powers (fase3-hs, docs/re-notes/stolen-powers-audit.md).** 65 records (12 base + 53 champion versions, one script
per group; targeting 14 unit / 1 point / 5, 7 instant; no Will cost). A version's block 0x1000003F lies over its base
power's; its stat list 0x100004B4 holds deltas, merged per stat id 0x100004B6. Versions unlock at champion level 5
(0x10000922).
**Animation and descriptor facts (fase3-hs).** 0x6097E0 (from the replay step 0x60B5F0, smooth branch only) writes
Propel 0x300 / Turn 0x1F1 / 0x501; a same-class 0xF2 for a live IID builds nothing (0x64D8A0) but its property block
replaces all properties (0x62AFD0); the descriptor u32 at +0x28 is a world-state override vs entity+0x110
(ChangeWorldState 0x54D5C0); entity construction 0x54B9A0 fails for a live IID; 0x54F1F0 fails on a missing class
record. AttachEntity takes (parent, child).

**Bot champions (fase3-ht, docs/re-notes/bot-champions.md).** A non-local champion is the same object as the local one
(event 0x4 bundle, class = variant, movement module 1, mode 1 with no controller IID) without the player link;
0x10000064 = its lobby IID (0x0200000000F00000 + n). The targeting ids of its 0x49 template (0x1000019D = 8 as a change,
0x10000AA7, 0x100001C3 0x28, 0x1000034C 0x1E, status tags 0x10000029 / 0x10000249) and the minimap ids (0x100004DA = 2,
0x2A1, 0x10000083 0x13000376) are sent by the server. The client dead-reckons a remote state (9-state history, error
<= 2 m smoothed), so one 0xB0 state per velocity change is enough. No bot decision logic exists in the data: the
levelling script 0x340007E2 (nodes 0x10000189 ranks / 0x10000186 shop), the loadout 0x10000CEB and the retarget
interval 0x3A000026 (0.5 - 0.8 s) are the only inputs.
**Match load and runtime (fase3-hw, docs/re-notes/match-load-sequence.md, map-runtime-state.md,
map-object-census.md).** 10 % = LoadParentRPs done (0xA99370) and LoadMatchData started (0xA99460); 20 % after every
LoadMatchData pack reported (0xA09F10 OnCharacterSwapComplete -> 0xA09DE0 -> 0xA97340); its list = 0x20ED entry f0 +
0x20AF. One unknown pack id fails a load request; a 0xFFFFFFFF in a list whose others are loaded retries forever. The
lobby slot icon is f9 of the variant's 0x20ED part 2 entry (0xA25510); the variant -> base map is part 1's groups
(0x85E010). The sector tracker (Flash SectorObjective) shows a padlock for lock 3 or the player's team; reader
0x859970 skips template entries with 0x10000A9B unless spectating. The client instantiates every entity's 0x8E scripts
(0x9798E0 -> 0x44C620); event 0x2008 (u8 0 | u64 entity | u32 event | u32 script, handler 0xAA1BF0) raises an event
on one of them. Static entries: index / IID pair optional; types 7 / 8 / 21 become entities (0x548550), 2 / 10
render-only, 3 / 16 never. 0x2E00119F has no geometry.
**Terrain sockets (fase3-hu, docs/re-notes/black-ground-shapes.md).** The terrain record 0x80 is a 33 x 33 height grid
(5 m; client 0x53BB00 / 0x53BA00, `did | 0x441 | flags | 0x441 | u16 heights`). Maps push vertices far down where a
model stands in the hole (sockets); an empty socket renders as an opaque black shape. Sockets: Crime Alley (40, 75) /
(40, 80) and x 120 at z 180; Gotham Divided's six base lane exits at z 200 and the pits (55, 55) / (105, 105) at z 0;
Coast City (75-85, 65-75) at z 0. The client draws an object only if 0x2A1 && 0x76A && !0x90F (0x61CB30); the GD pit lid
0x2E0003F0 is the only static with 0x2A1 present and no value.
**HUD feeds (fase3-hx, docs/re-notes/hud-shop-timeline-kills.md).** Shop Recommended row = the controlled agent's
upgrade component +0x50, filled only by 0x2078 and read once by query 0x100002ED (0xA34CA0) while the HUD loads.
0x100002AF / 0x100002B1 payload = f64 game time (reader 0x941620 -> Flash StartTimeline); 0x100002AB events delivered
once both arrived (audience 7 / 6 / 5 / 4). SetMatchTime 0x10000109 pre-start shows (end - start) - elapsed. Kill
billboards are raised by the client (0xA59300) from the 0x2039 table keys 0x10000816 / 815 icons, 819 / 818 names;
the original builder 0x9CE360 filled 0x10000814 class, 0x10000816 = template 0x100001FC, 0x10000819 = Name 0x3CE,
0x10000823 = template 0x10000593. Kill card reader 0x9326C0 layout in the note. 0x2045 entry: reader 0x8776A0 + stats
block 0x866650 (at entry +0x78: read indexes as in end-stats-2045.md, one lower than hud-shop-timeline-kills.md 6; f64 reads 11 / 57-60, f32 65 / 66; second head u64 = account IID), stat ids from catalog 0x48001172, grid from the encounter twin's 0x10000B2C (built by 0xA72860 only for teams 1 / 2).
**Liftable props, turret warning ring (fase3-hx, docs/re-notes/crime-alley-props.md).** No client data places Crime
Alley's meteorites (rock 0x400005C9 / 0x2E000D22, pack 0xA00002E6) or parked vehicles (seven classes in pack 0xA00002E5,
scripts 0x3400015F / 0x34000160, spawn table 0x1D00067A with Vfx_Spawn_Event01-04): the server spawns them. Super
Strength 0x480003CB takes a target only if its unit flags share a bit with 0x1000068D = 0x82 and it has 0x10000AA7 and
0x10000029 (0x9D01D0); vehicles 0x1080, rocks 0x22, sent as changes. 0x34000164 only raises 0x10000037 on the object and
waits for 0x100000BB: the sub-skill of 0x10000855 (type 3 0x480003C9 / 0x34000161 lob for vehicles: 9 m, blast 2.5 m,
75 + 20/rank, slow 0x48000294 2 s; type 2 0x480004A2 / 0x34000177 rubble: straight 8.5 m at 15.5, 50 + 12.5/rank,
knock-down 0x48000295 1.5 s) was started by the original server's code; ics plays its scriptlets (InitObjectPickup
0x100007A2, PickupObject 0x100007A1, CarPickup graph event, ThrowObject 0x100007A0, PickupRubble 0x100004CD, Rubble_Active
0x10000775, ThrowRubble 0x100004CC, Vfx_OnThrown / OnFire / OnExplode / OnCollision / Fade_Out) natively
(ics/match/liftables.py). The turret warning ring is client-computed (0xA84FB0): registration 0xA7CA20 at entity add
needs unit flag 0x10, bool 0x10000C5D, not allied, range 0x10000133 > 0; 0x10000C5B = armed; 0x10000C66 = the turret's
target IID (red when it is the local champion); green with >= 2 minions in range, yellow with 1.
**Crime Alley structures (fase3-ia, crime-alley-structures.md).** Each side has three type-3 structure markers only:
core 0x2E0011A7 / A6 (17.5 / 142.5), dampener 0x2E0011A9 / A8 (40 / 120), lane turret 0x2E0011AD / AC (65 / 95; the
cinematic actors BlueTurretBody / RedTurretBody 0x2E000AA0 sit on them); 0x2E0011AA / AB are unused: no core turret.
The vs-AI "prow" turret is the core's own Vfx_AI_Active child 0x2E000AC3. No structure model fills the x 40 / 120
terrain socket (collision boxes about 2 m).
**Crime Alley's relay and tables in several packs (fase3-ia, deep-scan-maps.md).** The padlocked nook plate is the
Power Relay 0x4000089D (ws 0x2E000D12): the client draws the padlock from the per-team bools 0x100006BD (team 1) /
0x100006BC (team 2) (0x96CA10, 0xAA23C0) and the minimap lock from 0x100004FF (0xA0CAB0). A scriptlet table can be
listed by several packs and only some parse it (0x1D0004A0 / A1 fail in 0xA0000162, parse in 0xA000016B). The dampener
graph 0x1A000B15 starts in Activate and folds on Death 0x100001C0 (Respawn 0x100003FD).
**Floating numbers, CC floaties, respawn graph (fase3-ia, deep-scan-s2c.md / deep-scan-animations.md).** 0x42 =
u8 0 | vitals list | ablative list (shield value / capacity, drawn on the bar) | hit list {u8 dmgType, u8 vitalType,
u8 overTime, cint k, k x (u8 viewer key, Vit amount x 16)} | u8 hit; the client shows the element whose key matches the
viewer ((character << 7) | team << 4 | 0x10000637), damage negative by type (1 Attack, 2 Power, 3 True), heals
positive. CC floaties come only from 0x20BD / 0x208D / 0x44 / node 0x100001AD. A respawned champion leaves the death
pose only on Global_Locomotion 0x100000AA, raised by _Defeat_OnRespawn 0x100001FC (0x10000034 is in no main machine).
Speed-bound attack clips play at playbackSpeed = 0x100006FE.
**XP ring (fase3-ia, hud-xp-ring.md).** ExperienceConsole / ExperienceBar fill = (XP - F(L)) / (F(L+1) - F(L)) with
XP 0x10000142 (cumulative) and level 0x10000167; F comes from InqXPForLevel 0x10000011 (handler 0x9B70 -> 0x91B8 ->
0xE154, native 0x340001(0xB, 0x10000027) -> class 0x40000010, table 0x49000010 array 0x10000067), asked at HUD load
and on LEVEL_CHANGED; unregistered handlers answer 0 / 0. The handlers are registered by player slot 198 (0x9654),
reached by script RPC 0x81A1000B. Level cap InqLevelCap 0x10000009 = min(0x10000975, default 19, 100).
**Bonus vs base stats (fase3-ia).** Skill scaling blocks (0x100004D4) on formulas with mode 1 (0x3B0002EA attack
damage, 0x3B0002E6 power damage, ...) multiply the BONUS stat (GetAttribute mode 1 = current - base); items count as
bonus. Bat Scream 0x48000615 slot 4: damage 225 + 125/rank + 0.9 x bonus attack damage.
**Item stats on the server (fase3-hz).** Items' 0x10000684 stats use the attribute ids combat reads (0x10000426
health, 0x10000B76 / B75 damage, 0x10000B84 / B7A armor, 0x100006FE attack speed op 10, 0x10000B7C / B7F lifesteal,
0x10000B46 crit, 0x10000B83 / B7E pen, 0x10000B7B CDR, 0x100004AA resilience, 0x10000486 -> Will, 0x10000483 -> Will
regen, 0x10000140 health regen, 0x100005E4 move speed). Skill scripts read their stats (LoadSkillStats) on 0x10000008,
so a stat change needs that event again; StartCooldown takes the plain duration (CDR was native, P).
**Destructible objects draw only through their pieces (fase3-hz, destructible-vehicles.md).** A record chain with
property 0x800 gets the destruction RenderComponent (creator 0x604920 -> 0x626FC0, vtable 0x15C94D0), which draws only
the destruction component's active piece list (comp+0x10, count +0x18). The client builds the intact pieces itself only
for creation types 6 and 9 (0x630FC0 at 0x631004, 0x630BF0 at 0x630C17); Crime Alley's vehicles are type 8 (placed, but
no pieces). S2C 0x8B (u8 0 | u64 IID, handler 0x631050) rebuilds them with no type check (0x6303F0), then 0x630FC0(0)
makes each piece's body (0x62DBA0) and render instance (0x62C490). 0x10D / 0x138 carry piece states.
**Destruction component needs 0x800 (fase3-hz, diag --create).** CDestructionComponent (vtable 0x15CA670) loads its
destruction record from property 0x800 in 0x57FCD0 (lookup 0x556470, failure leaves [comp+8] = 0 and returns
0x80004005); its start 0x62F960 does not check and calls 0x4E1100(record) -> access violation at 0x4E1101. A carrier
(0x4A..) object takes the carrier entity's template, which lacks 0x800; Crime Alley's vehicle world states have it.
**Attaching an object to a parent (fase3-hz, grab-arm-carry.md).** No separate message: the object's 0xB0 block
carries flag 0x04 = u64 parent IID (0 detaches, 0x64B330), then u32 mode and, for mode 0x10, {u32 attach point, u8,
u8} (reader 0x57EE90, listener 0x6113E0 -> 0x634C70 -> 0x58A220 -> 0x55F930); a bundle without the block detaches (P).
Grab's arm = the type-2 beam (exe 0x673280) in the missile's Vfx_Active, from its attach point 0x10000039 to 0x100004E2.
**Script-spawned drops must not be fighters (fase3-hz).** The jungle heavy drop 0x400005E1 (spawned by 0x3400007D on
the unit's death) has unit stats, so World.spawn made it a unit with AI and vitals; a hit on it (vitals 0x42 / status
icon 0x20C8 to an object the client built without that component) crashed the client (access violation rva 0x6B1BD9).
The Shards sphere lives only while its Active run lives: re-sending 0x10000886 keeps it up until Shards_Stop.
**Remote movement, tether retract, Shards chain (fase3-hy, test-2026-10-25-2207.md).** A 0x4 batch with only the 0xB0
movement block is not applied to a remote champion in game (C: a respawned bot stayed in its death pose and position
until the next full bundle); bots get full bundles. A remote champion moved by the server (Grab's drag) needs a newer
teleport sequence per step, as the local champion's recall. Shards_Start's own run of Shards_Active ends at once in
the client (diag: 0x17 instance end, stop flags 0x28000000, no 0x0C execute of 0x2E000C89). Super Strength's pick-up
starts its 90 s cooldown (0x34000164 S4 -> S3 StartCooldown), which greys the client's button before the throw.
**Recall, use, minimap icon (fase3-hu).** The champion's slot 6 (recall, 0x100008E4) is in no definition: the server
gives it (script 0x3400000A: S0 -> S1 on 0x10000088 records HomePosition, S1 -> S2 on use, channel stat 14, cancelled by
0.25 m of movement or 0x100000ED / 0x10000009 / 0x10000068 / 0x10000007, S4 teleport home). 0x20EE command 1 is "use
object" (u64 target = the object); a usable object's template 0x100009BC names the skill the user gets in the bonus
slot 9 (0x100008F2). A champion's minimap icon is its template's 0x10000083 (Gaslight Batman 0x13000376, Blue Beetle
0x13001DC3, ...). Lobby slot 0x2029 carries icon / pre-game / base champion DIDs in its five extra u32 (order O); with
them 0 a costume DID shows no portrait.
**Skill mechanics (fase3-ht, docs/re-notes/skill-mechanics-recipes.md).** SetSlotSkill 0x10000089's slot is property
0x100000E6 of the record's 0x1000003F block; 0x1000008E on that slot is the revert; 0x100000A9 {SkillSlot,
0x17AF14 script} follows both. Script local frames: +Y forward, +X lateral. A skill stat = base block 0x100004D3
(value 0x100004B7, per rank 0x100004D2) + scaling block 0x100004D4 (Mod, per rank, formula 0x100004D7 among
0x3B0002EA / E6 / E8 / 360 / EE / E9 / 10B / 203 / 149 / 2D0: attack / power / health / Will, current or bonus).
ApplyDamage's out DamageSuccess must exist before the damage pipeline's 0x10000020. Of 106 events scripts wait for, 51
were never raised (table in the note). Swamp Thing E's object 0x40000BCA runs the orphan script 0x340005CB.
**Stolen Power mechanics (fase3-ht).** Meteor Drop's meteor 0x4000044F runs the thrown-object scripts 0x34000167 /
0x34000347: S5 -> S9 on 0x1000001D (ShooterIID from 0x9A6A765), -> S2 on 0x10000049, S7 -> S6 on the collision
0x10000002 {TargetIID 0x632FE62, CollisionPosition 0x33016EE} (damage + knockdown 0x48000295 on a valid enemy,
DestructionImpulse on buildings IsKind 0x1000), -> S3 fizzle on 0x10000035. Super Strength 0x34000164: S2 -> S4 on a
targetable target (IsTargetable 0x1000001C), RaiseEvent 0x10000037 on it, S4 -> S3 (carry) on 0x100000BB (the lift
clip's end). Teleport 0x34000304 T4: ally (relation 4), IsKind 0x90150, alive, not IsKind 0x4000, HasFlagAttribute
0x10000B4A; 4 s channel (stat 14), cooldown 420 / 60.
**Map objectives (fase3-ht, docs/re-notes/map-objectives-recipes.md).** Only four objective flows are scripted in data:
the GH cannon controller 0x340002CF (hosted by the Power Core, talks to the cannon by entity id 165 with mission events
0x10000060 unlock / 0x10000078 neutral / 0x100000C9 lock; 65 s neutral, 120 s lock, 4 impacts, tier N = N strikes),
the Doomsday pad strike 0x340001FA (spawns 0x4000035D; damage base + delta x Device level 0x3B0001E7), and the death
drops 0x34000670 (CA Raider -> pad 0x40000C49) / 0x3400007D (heavy drop 0x400005E1), which wait for 0x10000149 after
the spawn and 0x10000007 {KillerIID} at death on the entity script itself. Every boss / pod / beacon / relay / Device
schedule was C++ match rule. Kill buffs live in the boss template's 0x10000AC2 (GD Raider 0x48000E4B, Leviathan
0x48000E4C, Guardian 0x48000A73, CC Raiders 0x48000CCF). Capture radii 0x10000504: pod 6.0, Device 5.0, cannon 4.1,
GH point 4.25, relay 3.0.
**Status stacks (fase3-ht, docs/re-notes/skill-mechanics-recipes.md 1).** Counted statuses (Flash 0x3400022C, Robin
0x34000330, Gaslight Batman 0x3400045A, Nightmare Catwoman 0x34000742, haste 0x34000320 ...) set StackCount on
0x100000D7 and EffectDuration / DurationDelta on 0x100000A8; 189 status scripts have `S1 -> S0 on 0x10000006`, so the
engine never re-sends the apply event to a running instance. Max stacks = 0x10000063; AddStacks 0x100000D9 carries the
absolute count (the decays pass --GetStackCount).
**Team tint and stubborn visuals (fase3-ht, docs/re-notes/stubborn-visuals.md).** 0x83C / 0x8B1 / 0x8B2 / 0x8A3 /
0x8A5 / 0x8C1 are Kynapse AIObstructionComponent fields (pathing only). Team-coloured rigs without their own team
scriptlets (dampener env_pvp_dampener_a, door 0x2E000CD7) are tinted by table 0x1D000385 `_Entity_OnSetClientRelationship`
0x100003A6, run only from 0xA7B0D0 (team listener 0xA813F0 / 0xA84370) on a CHANGE of 0x1000009C, with variables
0x100004A8 (relation) and 0x100007A9 (side). Scriptlet action type 0x0C: 0x37E world state, 0x325 child scriptlet,
0x37C scale, 0x67C keep as persistent instance; node type 0x24 is a switch (branch type 6 default, 0x17 a case with op
4 <, 1 <=, 6 >, 2 >=, 5 ==, 3 !=), so every ShieldPercentage picks a Shards shell. 0x7E6 belongs to the scriptlet entry
(reader 0x51EFE0): a start with flag +0x38 & 4 and 0x7E6 false is refused.

**Full Crime Alley match (fase3-gu).** Attack orders on structures: 0x9d01d0 reads the target's status attributes
(component entity+0x84, 0x974940 -> 0x973730, tag ids at 0x15fe670): 0x10000029 = 1 (check B), 0x10000249 = 1
(check C), 0x10000B4A = 0 (some slots). The outer turret 0x40000C86 has 0x10000249 = 1 in its template; the
dampener 0x40000C87, core turret 0x40000C8D and core 0x40000C89 have 0x10000249 = **0x100007D9** (a bool property,
default false): the server sets it when the protection clears. 0x20EA = u32 slot | list<u32> events
(0xa23510 from 0xa85da0 for skills with 0x10000A46, slot recorded at 0x186dd8c by 0xa16e60). 0x2006 add map note
(handler 0xa56c90): u8 0 | u32 category | Handle{u32, u64} | u32 | u32 | {u32} | u32; MapNoteCategory 1 PING,
3 TURRET, 18 ALERT_PING_INGAME, 21 RETREAT_PING_INGAME, 29 BEACON. Shop catalogue: a change of 0x100001D3 on the
player -> 0xa91670 -> 0xa908f0 (encounter -> 0x49 template -> 0x1000081E). That listener never runs for our player; the exe's HUD cave S calls 0xa908f0 itself (section 10, fase3-hb). The turret's shot needs no missile entity:
0x48000FDD's script 0x340005F7 tracks the shot on the target and raises impact 0x10000126.

**First Crime Alley match (fase3-gt).** Skin picker: 0x204C's owned list is copied (type 1 champion / 4 costume)
by `0xa95e70` into lobby+0x40; `0xab93a0` keeps the costumes of my base champion (`0x86da70`), `0xa3e240` turns them
into light packs and `0xab9e60` raises CharacterVariantsLoaded. 0x2029 fields (exec `0x8b9150` -> `0xabd0a0`):
draft, team, index, u64 player, name, u8 bot, champion, level, u8 locked, room, sequence, 5 x u32, Stolen Power 1,
2, amplifier set; icon / pre-game image come from the champion DID (`0x85e010`). 0x20AF (`0xa99f00`) sets lobby+0x4CB
(m_bForceOverrideNoLoading): `0xabd9c0` then stops waiting for the lobby packs and goes to LoadMatchDataAndLevel,
so in a lobby match it comes at the countdown's end. Turret attack 0x34000014: graph S1's S0 loads $SkillRange,
$SourcePosition and the damage stats on event **0x10000088** (level / init); S3 is the visible shot RunScriptlet
0x100002E0 (0x10000030 target, 0x100009EB speed), damage on impact 0x10000126 (ApplyDamage, hit FX 0x1E00007D).
Ranged minion 0x340004A0: wind-up 0x100000D4, shot 0x10000326 after OnCastSignal 5. The turret warning is computed by
the client (`0xa84fb0`, option User.TurretWarningEnabled): state 5 when a turret entry's target IID is the local
player. Open: what feeds that target; why the lane minions' objects do not show (their bundle matches the
turrets'); the client filter that hides layout static 0x2E00101D (the purple sphere, landblock 0x12BB).

**Champion select -> costume countdown -> loading (fase3-gs).** 0x2053 (handler `0xaba390`) calls `0xabee90(1)`:
byte `[0x1b77138]+0xAC` = view-match ("IsViewMatchEnabled", also set by 0x206E `0xab8e00`). With it set `0xa964b0`
stops sending 0x20D5 and passes the percent to the UI ("UpdateLobbyLoadingPercentForViewmatch"), the load-complete
notice 0x10000204 (`0x886950`) is never sent, the 0x204B handler `0xabd420` skips the local lock and pack load, and
the loading screen shows only the view-match percent (no player cards). So a player never gets 0x2053. The load
percent is cumulative (`0xab7bf0` adds to lobby+0x14): +10 LoadMatchData, +10 match packs, +5 game connection, +10
= 35 during champion select; +20 (`0xa0a570`) and +15 (`0xa96cf0`) need the player object. 0x204B's two times are
**f64** (serializer `0x838930`, `movsd` in the handler): game-clock seconds (the time packets' clock);
LaunchWarning.as fires at end-10, -5, -2, -1 and end (callbacks in the past are dropped), so >= 10 s. A locked
0x2029 for my slot (before 0x2016) starts the costume pack load (`0xabc620` -> `0xaba750`); when it ends
(`0xabd9c0` -> `0xabb870`) Lobby.CharacterVariantsLoaded shows the skin list. The SkinPicker sends 0x20E4
SelectCharacter with the costume variant; the server answers with my 0x2029 carrying it. Loading-screen cards come
from the 0x2029 slots (the client derives icon and pre-game image from the variant DID); 0x2031 is display only.

**Lobby -> loading screen (fase3-gs).** 0x2016 (handler `0xab9080`) passes the room check (`lobby+0x4BC` equal to
the u32 or still 0), sets `lobby+0x4CC` and `lobby+0xA8` (SetLobbyTransitionCalled) and calls `0xab8ec0`, which logs
"Sending CheckTransitionToWorldLoad" and raises UI state event **0x23**: the champion-select screen is left for the
loading screen. 0x206D (`0xab84f0`) sets `lobby+0x1C0` (everyone loaded) and calls `0xa964b0`, which raises UI event
**0x33** (into the world) once the local load is complete. So with a champion select neither may come before the
launch: ics sends 0x2053, then 0x2016 and 0x206D (`[ics] lobby_transition_at_launch`). The tutorials (no select)
keep 0x2016 0 after 0x20AF.

**Client → server**

| Event | Meaning |
|---|---|
| `0x20EB`, `0x20CA`, `0x20F2`, `0x20D5` | Join queue, accept match, connect to lobby, loading percent |
| `0x20EE` | Move order |
| `0x2` | Notice (generic) |
| `0x2136` | **Player ping**: `f32 x | f32 y | u64 target | u32 type`. Type 1 / 2 are the two ping kinds the player can place. The patched client also reuses it for skill ranking (type `0x52414E4B`, "KNAR", target = slot; section 8). |
| `0x216E` | **User preference saved**: `u8 n` + n ASCII bytes (name, e.g. `User.CameraLocked`, `User.ShowAllChat`) \| `u8 n` + n UTF-16 chars (value, `True` / `False`) \| `u32` (`0x10000C33`). Sent at load for every preference; whether the camera-lock key sends `User.CameraLocked` during play is not confirmed yet (the Bat Scream step listens for it, with a timeout). |

## 6. Object properties

Property value kinds on the wire (`icserver/wire.py`): `7` IID, `8` enum, `9` f32, `0x0C` array, `0x0E`
string, `0x10` int, `0x13` u32, `0x15` DID, `0x16` bool.

| Property | Meaning |
|---|---|
| `0x100000CF` | Controlled agent (player → champion link) |
| `0x100001D3` | Encounter DID on the local player. A change of it makes the client load the minimap image; that never happens on its own, hence a patch (section 10). |
| `0x100005E4` | Movement speed (f32). Drives the walk animation speed. Drones carry 3.0 in their data; the server sends `[match] anim_move_speed` (4.5) for Batman, otherwise he slides without walking. |
| `0x100006C1` | Skill ranks (int): 4 bits per slot 0–6; top 4 bits = recommended slot + 1. Kept by the server and read by patched client code. |
| `0x6B4` | **Object scale** (f32). Read by the render component (VA `0x622F10`), which also multiplies by `0x450`; the exe's SetScale (`0x58D650`) writes `0x6B4`. World state `0x2E001037` carries `0x6B4 = 2.1`. Used to size the meteors (`[tutorial] meteor_scale`, 0.3). |
| `0x108` | Scriptlet variable: target instance ID (u64), used for aimed shots (section 7) |
| `0x50F` | "Creation type" in world states; used by `ic.py carriers` to find carrier candidates |

## 7. Scriptlets (animations and effects)

Animations, visual effects and sounds are scriptlets started by the server with event `0x8D`
(`messages.start_scriptlets(entity, [key, …])`). Each champion/creature has a table of **allowed scriptlet
keys** (`0x10…`); a key that is not in the entity's table is rejected (diag result `0x80070057`), and
`0x8000ffff` means the entity has no script component.

- **Gaslight Batman** accepts **354 keys**: his own (abilities, VFX) plus shared groups (combat states,
  status effects, items, emotes, cinematics). Full list with probable names: [`batman_actions.md`](batman_actions.md)
  and `data/batman_actions.tsv`. Names come from the game's animation/event name tables; several names share
  a hash, so the most probable one for Batman is shown.
- Confirmed on Batman: Q `0x10000164`, W `0x10000163`, E `0x10000165`, R `0x10000162`; basic attack
  right/left `0x10000195` / `0x10000196` with shot VFX `0x10000188` / `0x10000189`; crit VFX `0x1000017E`;
  hit reaction `0x10000209`; `_Defeat_StartupIncapacitated` `0x100001F9`; `_Defeat_OnIncapacitated`
  `0x100001FB`; spawn VFX `0x10000181`.
- Played alone on an idle Batman, these showed nothing: KnockUp `0x1000003D`, GetUp `0x10000490`, death
  `0x100001FA`, respawn `0x100001FC`, revive `0x100001FD`, stun `0x10000999`, level up `0x10000201`,
  teleport `0x100009FB`, emotes. They probably need variables, a target or a state change as well.
- Basic attack pattern used by the server: `[0x10000195, 0x10000188]` then `[0x10000196, 0x10000189]`,
  with the target in variable `0x108`. On the hit drone: `0x10000223` (effect) + `0x10000209`
  (reaction). On a drone's death: `0x100001FA`.
- **Drones** accept `0x10000124` + `0x100000EC` together (their attack); they reject `0x10000128` and
  `0x10000008`. The human thug uses `0x10000124`.

## 8. Skills in the HUD: ranks, cooldowns, enabled buttons

### Ranking up ("+" button)

`GM_Advancement` has no handlers in this client (its scripts never register any), so every query returns
its default and every notice is dropped. The dispatchers (from how the client uses them):

| Dispatcher | ID | Role |
|---|---|---|
| rva `0x50e580` | `0x1000006A` | `InqCanRankSkill(agent, slot, &eError)` (2026-10-16: the IDs were swapped in earlier notes). Callers: Flash native rva `0x524500`, HUD skill loop rva `0x67c8b1`. |
| rva `0x50e840` | `0x10000063` | `InqSkillRank(agent, slot, &rank)`, only from Flash native rva `0x524b00` (`SkillsPanel.QuerySkillRanks`). |
| rva `0x50e6d0` | `0x1000023C` | Next recommended skill (HUD loop rva `0x67c8c8`, "rank recommended" key rva `0x60b6b9`). |
| rva `0x50e9a0` | `0x1000009B` | `RankSkill(agent, slot)` (native rva `0x524e80`, and rva `0x60b6dc`). |

**Correction (2026-10-15):** the HUD skill loop passes the value it gets from the `0x1000006A` dispatcher
(VA `0xa7c8b1`, answered by caves A/B) as SkillUpdate's `eCanRankSkill`, an `ErrorType` (0 =
`None_ErrorType` = the "+" shows; `SkillRank_NotHighEnoughLevel` = `0x10000022`, …). The skill's displayed rank
comes from elsewhere (the `0x100000AF` array). So the nibbles of `0x100006C1` are **not ranks** but "may this
slot be ranked now" flags: the server sends 0 for the slot it waits for and 1 for the others. With ranks
there, every rank-0 skill showed a "+" and a rank-1 skill never did (Q could not reach rank 2).
`GetSkillRank` (VA `0x863ce0`) reads the `0x100000AF` array only for slots 1–5; for any other slot it
returns the champion's level.

The patches (section 13) answer these from property `0x100006C1` and make `RankSkill` send a ping
(`0x2136`, type "KNAR", target = slot) that the server turns into a rank-up. The HUD skill loop
(VA `0xa7c640`) walks slots 0–15 but only refreshes those marked dirty (one byte per slot at VA
`0x1b759a8`), and nothing marks them in this client; a code cave marks slots 0–7 dirty whenever
`0x100006C1` changes, which produces `GM_Skill.RecvNotice_UI_SkillUpdate`. Setting the recommended slot
(top 4 bits) is enough to change the value and force a refresh.

### Rank level requirements (2026-10-30, `docs/re-notes/skill-rank-levels.md`)

The client's own InqCanRankSkill (WLib `0x926C`, live once `0x9F 0x81A1000B` registers the handlers) checks the
level in `0x94E4`: the skill block's int array **`0x1000099C`** (rank r needs `array[r-1]`; native `0x1050008` = exe
`0x8509A0` -> `0x86EF10`) when it has an entry for the rank, else a built-in table: **R 6 / 10 / 14 / 18, every other
slot 1 / 3 / 6 / 9**. Only Green Arrow's R (`[1, 6, 11, 16]`) and Starro's E (`[2]`) carry the array. All 156 build
orders (`0x1000034B`) follow this rule point by point. The old server rule put the 4th R rank at 20 (> level cap 19),
so at level 19 the client offered the R ("+", Recommended) and the server dropped the request silently. ics now uses
the client's rule (`[ics] rank_levels_from_client`, `rank_level_table`) for the player and the bots, logs a refused
rank with its reason and sends the rank state again (`rank_refused_refresh`).

### Grey buttons, D/F and the "+" on D/F (2026-10-16, static analysis)

- Flash draws a skill button grey when it is disabled or its rank is not above 0
  (`SkillControl.IsSkillButtonDisabled`). The disable conditions come only from server event `0x20A0`
  (u32 slot, u32 ErrorType, 16 bytes, u8 add/remove), never sent, so they are not the cause.
- Two writers set the rank Flash shows: the HUD loop (correct) and `QuerySkillRanks` through cave E, which
  returned 0 / 3711 from the "may rank" flags. Cave E2 now returns `GetSkillRank` (VA `0x863ce0`).
- The basic attack's rank is element 0 of `0x100000AF`: the server now always sends the array with element
  0 ≥ 1 (`[match] basic_attack_rank`).
- The HUD loop starts each slot's "can rank" value at 0 (VA `0xa7c886`); cave A answered only slots 0–6, so
  D/F (7/8) showed a "+". Slots > 6 now get `0x10000022` (`SkillRank_NotHighEnoughLevel`). Cave D2 also marks
  slot 8 dirty.
- D/F use Q's input path (slot map VA `0xa16f20`, handler `0xa8a8e0`, skill use `0xa85da0`). Nothing happens
  unless the slot property (`0x100008F0` / `0x100008F1`) exists and its targeting type `0x1000003D` is non-zero.
  The camera is a ground-target skill (type 1: D, then a left click → `0x20EE` command 2, ability 7, position);
  Super Strength is type 14 (an entity under the cursor; ability 8 with the target's id).

### Skill slots and where their skill comes from

Flash `SkillSlotList`: 0 BasicAttack, 1–4 Q/W/E/R (`FirstPowerSetSkill`…`LastPowerSetSkill`), 5 Passive
(`LastRankable`), 6 Recall, 7 Secondary1 (the Stolen Power on **D**), 8 Secondary2, 9 Bonus, 10–15 items;
−1 Invalid, −2 All, −3 AllCharacterSkills.

The client reads the skill DID of a slot from a champion property; VA `0x85d1c0(agent, slot, &did)` looks it
up in the table at VA `0x15EDA28` (16 entries, `.rdata`):

| Slot | Property | Slot | Property |
|---|---|---|---|
| 0 | `0x100008E3` | 8 | `0x100008F1` |
| 1 | `0x100008E8` | 9 | `0x100008F2` |
| 2 | `0x100008EA` | 10 | `0x100008E5` |
| 3 | `0x100008EC` | 11 | `0x100008E7` |
| 4 | `0x100008E6` | 12 | `0x100008E9` |
| 5 | `0x100008EF` | 13 | `0x100008EB` |
| 6 | `0x100008E4` | 14 | `0x100008ED` |
| 7 | `0x100008F0` | 15 | `0x100008EE` |

Slots 1–5 come from the champion's own data; the Stolen Power (slot 7) is chosen in the lobby, so the server
has to send it. The property reader is the generic one (VA `0x58b320`), so server properties are seen.

**The slot properties are property collections, not DIDs** (2026-10-15). In the champion record
(`0x48000615`) Q's `0x100008E8` holds the skill's whole definition: name `0x100001C0`, `0x100000E6`, texts
`0x100004AF`, icon `0x10000302`, `0x100002A3` (`0x48000154` / `0x48000156` in every slot: a category, not the
skill), `0x100004B4`, stats array `0x100004B3`, … The client's complex-value reader (VA `0x507590`, by kind
`1`–`0x16`) reads kind `0x0B` as a nested property table (VA `0x503330`, the same format as an object's table:
`u8 size class | compact count | entries`). Sending `0x100008F0` as a 4-byte DID desynchronised the client's
reading of the whole update and every later one. The kinds of the properties inside come from the client's
property descriptors (manager: global at rva `0x1766cb4`; lookup VA `0x4fee60`: buckets at `+0x2c`, node `+4`
next, `+8` id, `+0x12` owner category): `tools\diag.py --props` dumps them to `logs\props.txt`.

**Property descriptors** (`props.txt`, 3,800 of them): `+0x08` id, `+0x0C` value kind, `+0x12` owner category.
Examples: `0x100008F0` 0x0B, `0x100005E4` 9 (f32), `0x100006C1` 0x10 (int), `0x100000CF` 7 (IID),
`0x100000AF` 0x0C (array), `0x100001C0` 0x0E (string), `0x10000302` 0x15 (DID), `0x100004B4` 0x0C,
`0x100004B3` 0x0B. Value readers: simple kinds VA `0x507d60` (5, 8/0x0A enum, 9 f32, 0x10 compact int, 0x11,
0x13 u32, 0x15 DID, 0x16 bool), complex kinds VA `0x507590` (0x0B property table, 0x0C array, 0x0D bit field,
0x0E string, …).

**Pack record format** (read by `icserver/skilldata.py`): `u32 did | u32 0 | u32 count | entries`; entry =
`u32 key | u32 type word | value`, where the type word is the key itself, or `key | 0x40000000` for an entry
without a value; array = `u32 count | (u32 element key | value)…`; collection = `u32 0 | u32 count | entries`;
string = `u32 0 | u32 token | u32 string table | u32 0 | u32 0`; IID 8 bytes; other kinds 4 bytes. On the wire a
string can go in token form: `u8 0 | u32 token | u32 table | variables table` (StringInfo reader VA `0x5a9580`;
mode 1 = literal text).

**A Stolen Power's slot collection:** each power has a base skill (first of its catalog group, e.g. Surveillance
Camera `0x48000523`, Super Strength `0x480003CB`) and champion versions (`0x48000808` Gaslight Batman's camera,
`0x48000A3B` Superman's Super Strength). The skill block is property `0x1000003F` of those records (name,
icon, texts, stats `0x100004B4`, the skill's script `0x10000328` = `0x3400019D` / `0x34000164`, …); the version's
entries go on top of the base's. Q's slot collection in the champion record has the same keys.

A skill order (event `0x20EE`, command 2 or 9) carries **the slot** as its "ability" field: Q arrives as 1,
W as 2, E as 3, D as 7 (expected; not yet seen from the real client).

### Stolen Powers

The catalog is record `0x480003CD` (pack `0xA00000B3`): property `0x10000842` = 12 groups, each a count
(`0x10000841`) followed by skill DIDs (`0x10000840`). 12 base powers and 53 champion versions, 65 in all, listed
with names and icons in `data/stolen_powers.tsv`: Consume, Detonate, Healing Wave, Invulnerability, Meteor
Drop, Psychic Assault, Super Strength, Super Speed, Surveillance Camera, Teleport, Trap, X-Ray Vision. A
champion's own power is property `0x10000CE5` of its twin record (Gaslight Batman `0x49000086` →
`0x48000808`). Each champion has two pre-selected Stolen Powers (one is its own), on D (slot 7, property
`0x100008F0`) and F (slot 8, property `0x100008F1`); the lobby can swap one
(`GM_Lobby.SendNotice_RequestChangeStolenPower`, `RecvNotice_PlayerPickedStolenPowers`).

### The surveillance camera (Stolen Power)

| What | DID |
|---|---|
| Skill record | `0x48000808` (icon `0x13001791`) |
| Camera entity | `0x40000265` (world state `0x2E000E6C`, `.entity` `0x2D000BFD`) |
| Template | `0x1D000244` "Surveillance Camera" (creation type `0x50F` = 7) |
| HUD button | element 22 `SkillButtonStolenPower1` (21 `SkillButtonStolenPowerTSkill`, 23 `SkillButtonStolenPower2`) |

The server gives every placed camera vision for its fog of war (`[tutorial] camera_vision_radius`, 10 m): in
the tutorial it is the camera that shows the three Bat Scream drones two sections back.

### The Bat Scream (R)

Scriptlets `0x10000162` (Batman_Gaslight_Bat_Scream), `0x10000173` (Vfx_Bmg_Scream), `0x10000176`
(Scream_Stop). "It can travel for miles, damaging all enemies in its path" (line `0x1D8`): the server makes it
a straight line from Batman through the cursor, 60 m long and 3 m wide, through walls and gates, at 40 m/s
(`[combat] r_range`, `r_width`, `r_speed`, `r_damage`). The original's tutorial showed a 10 s cooldown on the
button (`[tutorial] r_cooldown`; the kit's 80 s is a guess for real matches).

Flash side: `GM_Skill.RecvNotice_UI_SkillUpdate(slot, siCost, fCost, siCooldown, desc, name, didIcon, rank,
bSkillCanBeActivated, damageType, canRank, recommended, inBase, grid columns…)`.

### Cooldown: event `0x20F8`

Handler rva `0x4bc7c0`, reader rva `0x439bd0`:

```
u8 0 | u64 agent IID | u32 skill slot | f64 end time (game clock)
```

The client computes `end − now` (VA `0xa0e320`) and calls `GM_UI.RecvNotice_StartSkillCooldown(slot,
seconds)`, which draws the sweep on the button (**confirmed**). The server also sends a zero-length cooldown
when it ends.

### Enabled (coloured) skill buttons

`GM_Skill.RecvNotice_EnableSkillButton` (native wrapper VA `0x8a0ca0`) is called from VA `0xa230c0`, which
enables a button only if none of the disable conditions in the table at `[0x1b75928 + slot*4]` holds
(checked through VA `0xa1d380`):

| Condition key | Check |
|---|---|
| `0x1000003B` | Looks the slot up in a per-slot "available" list at `[VA 0xa12d50() + 0x90] + 0x48` (data at `+0x60`, count at `+0x68`, 8-byte entries `slot, flag`) via VA `0x861480`. The original server's scripts filled this list; this server does not, so every button read as disabled. Patched to never disable (rank 0 still shows as locked). |
| `0x10000050`, `0x1000006B` | Checked through VA `0x8619f0` with property `0x100007FD` (meaning not identified yet). |

Other Flash notices seen: the `LifeState` enum (includes `Incapacitated`), which is probably how the
original server drove knockdowns and deaths.

## 9. Props without an entity: carriers

`WorldEntityFactory` (rva `0x14f1f0`) builds an object from an **entity class** (`0x40…`) and looks up that
entity's world state (rva `0x14be10`). A bare world state (`0x2E…`) sent as the class silently builds
nothing, and the street vehicle (`0x2E000AAB`), the meteors (rock `0x2E000BB3`, dust cloud `0x2E0007D4`) and the crater (`0x2E0004BE`)
have no entity of their own.

Patched behaviour: class `0x4A…0x4F` + the world state's low 24 bits means "build carrier entity N (N =
prefix − `0x4A`, from a 6-entry table in the exe at file offset `0xC18340`) with world state `0x2Exxxxxx`".
Cave X swaps the class for the carrier and remembers the world state; cave Y uses that world state after
the lookup; cave Z makes the model component load the `.entity` of the world state, not of the carrier.

Carrier table (`[combat] prop_carriers`, written by `ic.py patch`):

| Slot | Class prefix | Carrier |
|---|---|---|
| 0 | `0x4A` | `0x40000B0F` (Door) |
| 1 | `0x4B` | `0x400004FD` (default in the exe patch: `0x40000289`, which is not loaded in Tutorial 1) |
| 2 | `0x4C` | `0x400001BD` |
| 3 | `0x4D` | `0x4000081B` |
| 4 | `0x4E` | `0x40000B0A` |
| 5 | `0x4F` | `0x40000092` |

A carrier must be loaded in the current map (diag: "the carrier entity is not in the loaded packs").

## 10. Minimap: map image, notes, pings

### Map image

The map manager `M = [[0x17758d4] + 0x50]` turns the encounter DID into the map image (rva `0x64c2c0`)
and hands it to the HUD. Normally a change of the local player's property `0x100001D3` triggers it; that
never arrives, so the minimap stayed a green placeholder (and the fog-of-war map was never drawn). A cave
in the HUD's "re-deliver the map" (rva `0x60d810`) loads it when none is loaded, and also sets
`[M + 0xc8]` ("map delivered"), without which the note manager's tick (rva `0x66a7c0`) never positions a
note.

2026-10-23 (fase3-hb): that cave used to push a fixed Tutorial 1 DID (0x40000991), so every other map showed the
tutorial's minimap. It now always (also when a map is already loaded, e.g. from an earlier match) jumps to cave N
(VA `0x8c4f7e`), which reads the match's encounter from `[[0x1b763c0] + 0xc4]` (gmConnectionManager; the 0x20AF
handler `0xa99f00` stores the encounter DID there) with a call/pop base (the exe is relocated at run time, so caves
cannot hold absolute addresses), Tutorial 1 as fallback, calls LoadMap and goes on to the shop cave S (VA
`0xb1bf72`): `0xa908f0(encounter)` with ecx = Upgrade manager `[[0x1b758d4] + 0x80]`.

Why 0x100001D3 events do nothing: the listener `0xa6a8e0` (`param_1 + 0x100` = the watched object) handles the
note properties 0x10000548, 0x2A1, 0x100000FA, 0x100004DA, 0x10000587, 0x10000B2D, 0x10000D0A and 0x100001D3 (kind
0x15, new value -> LoadMap) of the objects it is attached to; diag showed it attached to map-note entities (it ran
when minions changed state) but never for the player. The shop listener `0xa91670` (sub-object +0x4c of the
Upgrade manager, created at client start-up by `0xa91e30`, game systems `[0x1b758d4]`: +0x50 map manager, +0x80
Upgrade manager) behaves the same.

Flash reads the foundry's items once per HUD movie (ArtifactDataManager.ResetAllData -> query 0x100002CC ->
implementer 0xa44fe0 -> list U+4, count U+0xC; filter 0x9d2520: record, category, tier), so the catalogue must exist
before the HUD loads: since fase3-hc the 0x20AF handler builds it (hook 0xa99f3f -> cave T 0x6c0004 -> F 0x13f8fd2).
No event makes Flash ask again (docs/re-notes/shop-ui-items.md).

### Shots, Will (fase3-hc)

- Basic-attack projectiles (turret, minions, champions) are the shot scriptlet's projectile action (type 2, exec
  0x673280): target from scriptlet variable 0x10000030 (IID), speed 0x100009EB (f32, default 10 m/s); the client
  destroys it on contact (0x2E000B74 table 0x1D000387). docs/re-notes/projectiles-homing.md.
- Champion property 0x1000000C (enum) = secondary vital type (5 = Will), read once at creation by 0x972940; local
  bool 0x100000CE = vitals notify flag [vit+0x64] (listener 0xaafcd0), set by the client only for non-0x02 IIDs
  (0xa16807). Flash greys a button when |stat 3| > Will (SkillControl.OnSecondaryVitalChange).
  docs/re-notes/skill-button-will.md.

### Notes

- Note reader: VA `0xA4B150`. Notes are keyed by `(category, variant)`; VA `0xa144d0` updates an existing
  note. The reader takes the object's team through a property read that finds nothing for server
  properties (team −1 = "enemy", never drawn); patched to use the generic reader (VA `0x61c990`).
- HUD call: `GM_Encounter.RecvNotice_UI_UpdateTrackerStatus(iid, x, y, state, icon, variant, category, …)`.
- Team-2 ping notes got `variant + 2` (enemy icon set, not drawn); patched to `+ 0`.
- The guide marker's minimap icon comes from the **objective tracker** (tracked object `0x32`, type
  `0x12`), not from a map note.

Flash `MapNoteCategoryList` (the `category` argument):

| # | Category | # | Category |
|---|---|---|---|
| 0 | Undefined | 16 | CAMERA |
| 1 | PING | 17 | ALERT_PING |
| 2 | CHARACTER | 18 | ALERT_PING_INGAME |
| 3 | TURRET | 19 | PING_INGAME |
| 4 | METEOR_PICKUP | 21 | RETREAT_PING_INGAME |
| 5 | HEALTH_PICKUP | 22 | RETREAT_PING |
| 6 | BASE | 23 | STATIC |
| 7 | AGENT | 26 | SMALL_CAPTURABLE |
| 8 | CAPTURE_POINT | 27 | LARGE_CAPTURABLE |
| 9 | MINION | 28 | LARGE_MAPOBJECTIVE |
| 11 | BLANK | 29 (`0x1D`) | BEACON |
| 12 | STORMSHIELD | 30 | POWERCORE |
| 13 | SPEED | 31 | DEVICE |
| 14 | SKILL_BAT_SCREAM | | |
| 15 | GENERIC_PICKUP | | |

The Flash chooses the ping animation by category: `ALERT_PING_INGAME` → alert effect; `PING` or
`RETREAT_PING_INGAME` → retreat effect. Category `0x1D` drew nothing, and category 1 drew the same icon for
both ping types.

### Player pings

| Ping type (event `0x2136`) | Object class | Note category that shows the right icon (**confirmed**) |
|---|---|---|
| 1 | `0x4000025B` | 21 (`RETREAT_PING_INGAME`) |
| 2 | `0x4000025A` | 18 (`ALERT_PING_INGAME`) |

Variant 0 for both. Twin record `0x4900025A` carries icon `0x13000A15` (32×32 texture) and category 1
("Map Ping", template `0x1D00020A`).

## 11. Camera and screen mapping

From screenshots of the tutorial camera: `screen = R(321°) · (x, −y) · k`, with `k ≈ 53 px/m` at a
1676-pixel-wide window (≈ 43 px/m at 1360). So world `+x` points up-right on screen and `+y` up-left.
Useful for turning "move it a bit towards the lamp" into world offsets.

## 12. Tutorial 1 data

World positions are in landblock `0x13, 0xCB` (spawn `(18.7, 60.4, 200.3)`).

| Item | Data |
|---|---|
| Big meteor | Lands at `(18.0, 61.3, 200.0)`; meteor rock world state `0x2E000BB3` (its dust cloud is `0x2E0007D4`), scale 0.3 via `0x6B4`. |
| Crater | World state `0x2E0004BE` (its `.entity` `0x2D000375` is a skeleton only, no scripts). The mesh sits ≈ (3.2, 0.3) m from its origin. The lava of the original is still missing: map candidates `0x2E001144/45/46` (pale pit) and `0x2E0005D6` (grey square) are not it; `0x2E000A9F` is a turret plate. |
| Batman knocked down | `_Defeat_OnIncapacitated` (`0x100001FB`), then after 5 s `_Defeat_OnRevive` + `RunScript_Vfx_GetUp` (`0x100001FD`, `0x10000490`; untested). |
| Drone vs human thug | Drone attack `0x10000124 + 0x100000EC`, thug attack `0x10000124`, drone hit reaction `0x10000209`. The thug fights with no extra yaw offset; when fleeing he ignores fog of war so he does not vanish. |
| First guide marker | `(25.1, 60.3, 200.0)` |
| Vehicle | Street vehicle world state `0x2E000AAB` (via a carrier); drone doors `0x40000B0F`. |
| Cinematics | Intro `0x35000026`; Catwoman breaks the vehicle `0x35000034`. |
| Target drone | `0x40000BA9` (world state `0x2E001298`, rig `chr_minion_target_drone`): the yellow practice drones. |
| Ranged drone | No variant names the tutorial's ranged world state `0x2E001168`; Trooper Drone `0x40000A5D` stands in. |

The tutorial's script is driven by its conversations (dialogue keys such as `0x1BA`, `0x1C9`).

### Encounter layout groups (pack `0xA0000256`)

`python ic.py layout 0xa0000256` lists 41 placements. Names with their first position:

| Group | Placements |
|---|---|
| 03 (street and bridge) | `03MeleeA/B/C/D`, `03RangedA/B`, `03ThugA/B`, `03GasJoker` (40.7, 70.9), `03GateA` (54.05, 44.80), `03GateB` (89.87, 26.21), `DestVehicle` (43.66, 52.61). `03MeleeA/B` and `03RangedA/B` have a second position on the bridge (62.8–66.6, 38.9–41.6). |
| 02 (north, x 77–114, y 105–133) | `02Destroyer` (moves from (113.75, 123) to (95.25, 125.75)), `02PaddyWagonA/B` (world states `0x2E00034D/4E`, the car to throw), `02MeleeA–D`, `02RangedA/B`, `02GaslightBatman`. |
| 01 (east, x 141–160, y 12–32) | `Destroyer` (152.75, 24.0), `Melee1/2`, `Ranged1/2`, `01GateA`/`Gate` (world state `0x2E000CD7`), `GaslightBatman` (158.5, 30.8). |
| Cinematics | `Drone_01`, `Thug_01/02`, `Gaslight_Batman(_01)`, `Gaslight_Catwoman`, `InvisibleTarget`, `PowerCore` (meteors). |

### The bridge (part 2, `icserver/bridge.py`)

The bridge runs from `03GateA` to `03GateB` (40.4 m). Positions are measured along it (`s`, unit vector
`(0.8875, −0.4606)`) and across it (`l`, `(0.4606, 0.8875)`); the south edge is at `l ≈ −1.3…−3.0` (from the
`SouthStreet` obstacle, clicked in game). The middle gate (`s = 17.5`) and every other spot were estimated from
the original's video with the camera mapping of section 11, so they are configurable
(`[tutorial] bridge_positions`).

### Tutorial hints

Hint table `0x4800070C` maps hint ids to hint records (`0x40000D30…0x40000D48`); each hint's texts are in its
own string table `0x2B000202…0x2B00021A` (title token `0x03EB3762`, body `0x0DA3DC6C`).

| Id | Hint | Id | Hint |
|---|---|---|---|
| 16 | Guide Arrows | 28 | Attack-move |
| 17 | Basic Attack | 29 | Attributes |
| 18 | Experience | 30 | Level Reset |
| 19 | Quick Upgrade | 31 | Damage Types |
| 20 | Will | 32 | Recommended Panel |
| 21 | Skill Ranks | 33 | Damaging Turrets |
| 22 | Skill Charges | 34 | Skill Points |
| 23 | Passive Skills | 35 | Jungle Leashing |
| 24 | Spacebar | 36 | Jungle Camps |
| 25 | Camera zoom | 37 | Activating Artifacts |
| 26 | Super Strength and moving | 38 | Tactical Skills |
| 27 | Earn Stolen Powers | 40 | Status Icons |

(Id 39 = Deployed Items; ids 2–15 and 41–44 belong to other maps.)

### Objective texts

The tutorial's objective banners are strings with tokens ending in `bf934` in pack `0xA00000B3` (for example
`026bf934` "Use Basic Attacks (Right-click) and Skills to defeat the drones", `05ebf934` "Click the
highlighted button to unlock Sonic Shell", `02bbf934` "…unlock Bat Flight", `02ebf934` "…upgrade your
'Passive Skill' - Echoes", `036bf934` "…unlock your 'Ultimate Skill' - Bat Scream", `029bf934` "Left-click to
throw the vehicle", `03fbf934` "Defeat the Destroyer…", `027bf934` "Click a highlighted button to upgrade either
Sonic Batarang or Sonic Shell", `038bf934` "Left-click on the mini map, or place your cursor on the edge of the
screen, to pan to the highlighted location"). The server sends the English text itself. The Bat Scream's
objective ("Aim your cursor at the drones and press ('R') to fire the Bat Scream (0/3)", from a screenshot) is
not among these strings.

## Remaining Tutorial 1 content

Programmed (build fase3-du, `icserver/bridge.py`), after the Catwoman cinematic:

1. Catwoman's pursuers (`0x1C9`), level up and unlock W (`0x1E5`, `0x1E4`, `0x1C2`).
2. Practise Sonic Shell (`0x1B1`, `0x192`). "More enemies!" (`0x191`, `0x199`), another level and a rank-up
   (`0x1D9`, `0x1D3`), clear the drones (`0x1CC`).
3. Move on (`0x38D`). Stolen power: surveillance camera (`0x22B`, `0x22A`, `0x196`, `0x1BD`, `0x1D2`).
4. Unlock E and practise Bat Flight (`0x1C6`, `0x1D1`, `0x190`, `0x1AA`); more drones (`0x1AE`), rank up
   (`0x1A1`), the Echoes passive (`0x18F`).
5. "Let's go!" (`0x1E2`), the drones at the vehicle, level 6 and unlock R (`0x1CB`, `0x1DC`).
6. (fase3-dy) The camera sees distant drones (`0x1A0`, `0x1C8`); unlock the camera (`0x1B6`, `0x1B0`, `0x1CA`,
   `0x1B5`) and use the Bat Scream (`0x1D8`, `0x1D0`, `0x3AC` after a miss, `0x1A5`); lock it again (`0x1AD`,
   `0x1A8`, `0x19F`).

7. (fase3-eb, `icserver/finale.py`) Another car on the road: Super Strength, throw the car (`0x1C5`, `0x1C1`,
   `0x1C0`, `0x1B4`); the Destroyer's cinematic `0x35000028` (lines `0x1CF`), `0x1D7`, the second car, `0x1C7`,
   the Destroyer (variant `0x40000EB2`, world state `0x2E000AB5`); the ending cinematic `0x35000025` (lines
   `0x1BC`).

Still to do: the real victory screen. `GM_Encounter.RecvNotice_NotifyMatchEnded` and
`RecvNotice_PlayEndOfMatchEncounterMovie` are called from the client's GM_Encounter natives (table of 89 at file
offset `0x1466118`; NotifyMatchEnded's reader VA `0x941750`, PlayEndOfMatchEncounterMovie from VA `0xa727ee`),
i.e. by the client's own encounter scripts, not directly by a network event.

## 13. Exe patches

`python ic.py patch` applies these to a copy of the untouched client (it refuses any other build). Every
entry is documented in `icserver/patcher.py` next to its bytes. Offsets are file offsets.

| File offset | rva | Patch |
|---|---|---|
| `0xBE3862` | `0xbe4462` | Oodle: outgoing game packets uncompressed (earlier project) |
| `0x67EF34` | `0x67fb34` | Dialog gate: conversations play without "match started" |
| `0x11DB16C` | `0x11dcd6c` | Lighting re-evaluation 2.5 s → 0.2 s |
| `0x48B09C` | `0x48bc9c` | Skills: ping cave, `RankSkill` goes to the server as ping "KNAR" |
| `0x52431A` | `0x524f1a` | Skills: the "+" `RankSkill` native calls the ping cave |
| `0x60AADC` | `0x60b6dc` | Skills: "rank recommended skill" calls the ping cave |
| `0x5239BF` | `0x5245bf` | Skills: UI rank query asks cave A |
| `0x5E6D24` | `0x5e7924` | Skills: cave A, rank query + local champion check |
| `0x735DD4` | `0x7369d4` | Skills: cave B, rank from property `0x100006C1` |
| `0x67BCB1` | `0x67c8b1` | Skills: HUD skill loop asks cave A for the rank |
| `0x724E64` | `0x725a64` | Skills: cave C, recommended skill from `0x100006C1` |
| `0x67BCC8` | `0x67c8c8` | Skills: HUD skill loop asks cave C |
| `0x523FCA` | `0x524bca` | Skills: `InqCanRankSkill` asks cave E |
| `0x72EBE4` | `0x72f7e4` | Skills: cave E1, `InqCanRankSkill` |
| `0x71ED68` | `0x71f968` | Skills: cave E2, every slot flagged "may rank now" in `0x100006C1` can rank (was: only the recommended one) |
| `0x67C602` | `0x67d202` | Skills: HUD update calls cave D first |
| `0xFB43B8` | `0xfb4fb8` | Skills: cave D1, read the property every frame |
| `0xFAA3B8` | `0xfaafb8` | Skills: cave D2, mark skill slots 0–7 dirty when it changed |
| `0x14E60E` | `0x14f20e` | Props: class read → cave X |
| `0x99735A` | `0x997f5a` | Props: cave X, class `0x4A`–`0x4F` → carrier + remembered world state |
| `0xC18340` | `0xc18f40` | Props: carrier table (6 × u32, from `[combat] prop_carriers`) |
| `0x14E7B4` | `0x14f3b4` | Props: world-state lookup → cave Y |
| `0xFBE3BC` | `0xfbefbc` | Props: cave Y, use the remembered world state |
| `0x1687AA` | `0x1693aa` | Props: model lookup → cave Z |
| `0x2CEB3C` | `0x2cf73c` | Props: cave Z, class `0x4A`–`0x4F` → world state `0x2E` for the model |
| `0x60CC13` | `0x60d813` | Minimap: HUD re-deliver → cave M |
| `0x6113BC` | `0x611fbc` | Minimap: cave M, load the encounter's map image and mark it delivered |
| `0x64A702` | `0x64b302` | Minimap: note team read with the generic property reader |
| `0x61C7E4` | `0x61d3e4` | Skills: the "slot available" condition no longer greys the buttons |
| `0x64A6FC` | `0x64b2fc` | Minimap: team-2 ping notes keep their own icon variant |
| `0x11A1F5F` | — | RSA login key: modulus replaced with the server key's (earlier project) |

Code caves use `0xCC` padding inside `.text`; two unused `.data` tail slots hold state (rva `0x190ef00`
last ranks value, rva `0x190ef40` remembered world state).

## 15. Open questions

- The crater's lava: which world state or effect the original used.
- Skill stat IDs other than 18 (cooldown): need tooltip screenshots of Q/W/E/R at several ranks.
- Will (secondary resource) cost per skill, and status effects (Sonic Shell, Bat Flight, Bat Scream).
- Condition keys `0x10000050` / `0x1000006B` (property `0x100007FD`) of the skill button.
- How the original server drove `LifeState` (knockdown, death, respawn) and whether GetUp/KnockUp need it.
- Fog of war darkness, vehicle destruction, drone highlight (older open items in the changelog).
- The remaining 329 of Batman's 354 scriptlet keys have not been checked one by one.
- What the real client sends for D (slot 7), and whether the D button shows the camera skill with property
  `0x100008F0` alone; the camera's charges.
- The ranged drones' own attack scriptlets (they use the melee drone's keys for now).
- Exact positions of the bridge's middle gate, marker, camera spot and end-of-bridge vehicle.
- Why the gates' light wall (`0x2E0010F4`) shows white: team property (blue = the player's side?) or a script.
- Whether the camera-lock key sends `User.CameraLocked` (`0x216E`) while playing.

## Ending a match (static analysis, 2026-10-15)

All of this comes from static analysis of the unpatched exe and has not been tested against a running client.

- **Match-ended notice.** `GM_Encounter.RecvNotice_NotifyMatchEnded` is a network notice: event `0x2` to the local
  player.
  - Notice id `0x1000000E` (registered at `0x9612c6`, reader `0x941750`).
  - Payload: `u32 winning team | u32 | f32 match seconds | u32 | f32`.
  - The end-of-match page (`0xa809e0`):
    - stores the player's team (`PVP_Team 0x1000009C`, from the object or its controlled agent);
    - switches the UI with `GM_UI.RecvNotice_UIStateMachineEvent(0x21)`;
    - fills the page in `0xa795e0`.
  - Flash shows VICTORY when the winning team equals the player's team.
- **End-of-match stats.** The page also needs event `0x2045` (to the player system; exec `0x8b2bd0` → `0xa91bf0`):
  `u8 0 | u32 n | n entries (reader 0x8776a0) | f32`. `messages.end_of_match_stats` builds one all-zero entry; the
  layout is in `_end_stats_entry`.
  - Tutorials (`0x10000D0B` ≠ 0) skip the scoreboard.
- **Post-match movie.** The client looks it up from the encounter description itself: property `0x10000C1B` of
  `0x49000991` (`0x8596b0` via `0xa724a0`).
  - It plays it through `GM_Encounter.RecvNotice_PlayEndOfMatchEncounterMovie` while the preference
    `User.HasSeenPostEncounterVideo@0x40000991` is unset, then saves that preference (it arrives as `0x216E`).
- **Completed encounters.** Event `0x214B` (to the player system; exec `0x8b2860` → `0xa30cd0`,
  `GM_Encounter.RecvNotice_UI_CompletedEncounters`): `u8 0 | u32 n | n × u32 encounter | u32 last played | u32 flags`.
  - The encounter records chain the tutorials: `0x49000991` names `0x40000A81` as next (`0x10000B66`), and
    `0x49000A81` names `0x40000991` as its prerequisite (`0x10000B68`).
  - Tutorial 2 is locked until Tutorial 1 is in this list. The server keeps the list in `data/progress.json` and
    sends it at each login, before `0x2080`.
- **Back to the home screen.** Not determined statically. The end screen's button probably sends a client notice
  (incoming `0x2`); its id is still to capture.

### Leaving the match world (static analysis, 2026-10-15 16:32)

- **`0x12D`** (client → game connection, empty body) means "I have left the world". It is sent by `0x692950`, at
  the end of the world teardown `0xa99b60`, which resets the HUD, minimap and objectives and clears session flags
  `+0x70`. No reply is expected.
- **Who calls the teardown** (`0xa99b60`):
  - `0xa9a040`: disconnect with an error;
  - `0xa9a260`: connection interface;
  - `0xab52a0`: address/port check;
  - `0xabbb06`: "Exiting Lobby" after the packs load;
  - `0xabc56b`: the handler of server event **`0x2021`** (`RecvEvt_DeliverNotifyPlayerToExitLobby`).
- **`0x2021`** goes to the player system: `u8 0 | u32 room id`. The client leaves the world, then fires UI event
  `0x5F` (home).
- **Loading the next match** (`0xa99e20`) needs session flags `+0x70 & 7 == 7`:
  - game connection up;
  - `0x20AF` arrived;
  - packs not loading.
- **`0x20A6`** (client) is sent when the end page closes.
- The VICTORY overlay belongs to UI state `0x21`. Data names `Cinematic_Victory` (`0x10000A9E`) and
  `EndOfMatch_CinematicCamera` exist but the exe does not reference them.
- `tools/diag.py --matchend` logs the teardown's caller, the connection status codes, the load-gate flags, and
  the end page / stats / movie lookups.

### The end of a match at runtime (diag --matchend, 2026-10-15 17:04)

- **The client leaves the world itself.** Notice `0x1000000E` → end page → UI event `0x21`, whose UI-state action
  `0xab52a0` (action type `0x1000018F`, "if in a valid cell, leave the world") runs the teardown `0xa99b60` at once.
  - `ds:0x18712c0` is `0xFFFF` ("no cell"), not a port.
  - The original therefore had its in-world VICTORY phase before the notice; the results show at home.
- A third teardown 3 s later (`0xa9a040`, disconnected with an error) came from the server closing the game
  connection. The connection must stay open; the next referral replaces it.
- **Post-match movie.** It plays only while `User.HasSeenPostEncounterVideo@<encounter>` is unset. The client keeps
  that preference in `UserPreferences.ini` (`0xa6cc20`).
  - Event `0x216A` (player system, handler `0xa742d0`) overwrites preferences:
    `u8 0 | u8 0 | compact n | n × (compact len + ASCII name | u16 BE type 0x16 | u8 bool)`.
- `Cinematic_Victory` (`0x10000A9E`) and the `EndOfMatch_CinematicCamera` input context (`0x1000000F`, UI action
  type `0x10000019`) exist. What drives them is in UI-state data outside the exe.
- **Match started.** The server does not send match started (`0x2053`, handler `0xaba390`: UI event `0x14`). This
  may change which route UI event `0x21` takes (`[match] send_match_start`).

### Super Strength, the car's explosion and the end-of-tutorial panels (static analysis, 2026-10-15 17:36)

**Two name tables.** The 0x8D scriptlet keys are named by table `0x33000000`; Havok animation-graph events by
table `0x300000A4`. The same number means different things in each. For example, `0x100005D4` as a scriptlet is
`Vfx_Stp_Bend_Spacetime_Target_Active`, not a carry state; `0x10000176` as a scriptlet is `Vfx_Bmg_Scream_Stop`.

**Batman's animation graph** (`0x1A0002E7`, pack `0xA0000122`, `chr_batman_gaslight_behavior.hkb`):
- InitCarPickup → sub-machine `SuperStrength_Car`, state `Pickup_Start`: he bends down, grabs, and holds that pose.
- CarPickup → `Pickup` → `Hold`. `Hold` blends the car idle / walk / run clips by the normal walking speed
  (property `0x300`), so the hands-up carry walk needs nothing more.
- ThrowCar throws: the car leaves his hands at 0.20 s. `state_to_locomotion` / `_Combat_GoToLocomotion`
  `0x100002FD` brings back normal walking.
- Any other skill, basic attack or hit event leaves the car state.

**Super Strength's server scripts** (`0x34000164` / `0x34000161`) run these scriptlets on the caster, in order:
- InitObjectPickup `0x100007A2`;
- PickupObject `0x100007A1`, also on the object;
- ThrowObject `0x100007A0`, also on the object;
- `_Combat_GoToLocomotion`.

**A prop's allowed scriptlets** are built once, when its script component starts (`0x57B860` → `0x58EDD0`), from
its property `0x7D2`: an array of `0x1D` script templates, element key `0x462`. Carrier-built props never got their
world state's `0x7D2`, so every scriptlet on them was rejected.
- Paddy wagon A `0x2E00034D` → `0x1D0000BB`; B `0x2E00034E` → `0x1D0000BA`; behavior graph `0x5B5` = `0x1C000021`.
- The original's intro cinematic `0x35000026` blows both wagons up with their own `Vfx_OnExplode` (`0x10000079`)
  alone.
- No client code reads `0x100003F2` or `0x10000063`: changing them does nothing.

**Paddy wagon skeleton** `0x2D000238`: front at +Y and symmetric left/right. About 5.4 m long, 2.6 m wide and
2.6 m high. Its middle is about 0.68 m ahead of the model origin and 0 across.

**Notices for the end of the tutorial:**
- `0x100002EB` ShowAnnouncement: `StringInfo text | u32 a (≠ 0) | u32 b | u32 c | i32 d | i32 e | u8 flag`.
  `0x100002EC` clears it.
- `0x10000424` AddTimelineBanner (after `0x100002AF` and `0x100002B1`).
- Home reward panels: `0x20B8` item statuses sent again (from the second delivery on, the client passes only the
  changed items to Flash) and `0x2095` ribbon "item fulfilled": `u8 0 | u32 key | u32 item | StringInfo`.

## Knockdown, thrown-car effects and the victory voice (static analysis, 2026-10-16)

**Batman's falls** (graph `0x1A0002E7`, its Lua `0x1F000002`):
- `SM_Death`'s start state is bound to variable 6 `Death_Selection`: 0 = Death_A (face up), 1 = Death_B
  (face down), 3 = Ragdoll_Death. `onStandardDeath()` sets it to `math.random(0,1)` on every return to walking,
  so `_Defeat_OnIncapacitated` (→ `CbtState_Death_Induce` `0x100000AD`) falls face up or face down at random.
- `SM_KnockUp` and `SM_Get_Up` share variable 10 `Knockup_Selection`. Knock-up: 0 FaceDown, 1 FlipBack,
  2 FlipForward (random in `onRandomizeKnockUp()`). Get-up: 0 = Get_Up_FaceDown, 1 = FaceUp. Nothing else sets it,
  so the get-up is always the face-down one.
- Graph events (table `0x300000A4`): `CbtState_Knockdown` `0x100002F5` (knockdown clip, end pose held),
  `CbtState_Dead` `0x1000010B` (the face-down recover clip at speed 0 = the get-up's first pose),
  `CbtState_GetUp` `0x1000009D` (returns to walking by itself at 0.4 s), `CbtState_KnockUp` `0x10000020`.
- The server raises Knockdown, then Dead at +1.8 s, then GetUp at +5 s (`[tutorial] knockdown_mode =
  "face_down"`); `"incapacitated"` keeps the old scriptlets.

**Thrown objects** (Super Strength scripts `0x34000164` / `0x34000161`; the thrown object's own script
`0x34000167`, listed in throwable templates' effect list, property `0x8E` element `0x30E`):
- On the object: Vfx_OnThrown `0x1000087A` 0.3 s into the throw; on collision Vfx_OnCollision `0x10000016`, then
  Vfx_OnExplode `0x10000079`, a destruction push, `0x1000001C`.
- On the target: skill `0x48000295` (Destructible_AdvanceState `0x10000063` = 1, knockdown script `0x34000131`),
  VFX_CBT_Hit_Shared `0x10000223`, effects `0x1E000017` / `0x1E00001A` for the knockdown duration.
- Destructible table `0x1D0008EF` (an analog of the wagons' `0x1D0000BA/BB`): its particles (`0x180006C3/C4`) and
  debris model (`0x170001C6`) hang off Vfx_OnInit / Vfx_OnCollision, not Vfx_OnExplode alone.

**Victory voice:** Flash's WinLoss billboard plays no sound and no client code plays a victory line. Candidate:
announcer dialog line `0x250` (CODE_UI_ANC_Congratulations_Victory) as conversation event `0x2001`, sent with the
billboard (`[tutorial] victory_voice_lines`).

**Record types** by DID prefix are listed in `catalog/data/asset_types.tsv`; behavior graphs and the clips they play
in `catalog/data/animation_graphs.tsv` (both refreshed by `python ic.py catalog --scan`).

## 12:18 findings (diag --scripts and static analysis, 2026-10-16)

- **World state records** are `u32 did | u32 7 | u32 .entity (0x2D) | u32 0 | u32 count | entries`
  (`gamedata.Game.world_state`). Their property `0x7D2` (array of `0x462` = `0x1D` script templates) and `0x5B5`
  (behavior graph) are what a carrier-built prop needs for its scriptlets; the server now reads them at start for
  every prop it builds (`tutorial1.resolve_script_tables`): sphere `0x2E000AC5` → `0x1D000360` + `0x1D000385`,
  graph `0x1C00006C`; dust `0x2E0007D4` → `0x1D00020B`, graph `0x1C000046`; gate light `0x2E0010F4` → `0x1D00038B`.
- **Paddy wagon scriptlets** (diag): only `0x5` and Vfx_OnExplode `0x10000079` are allowed; Vfx_OnCollision and
  Vfx_OnInit are rejected. OnExplode runs (sound) but no fire is seen yet.
- **Super Strength's throw** is a separate skill, `0x480003C9` (linked skill 3 of base `0x480003CB`, property
  `0x10000855`): ground target, 9 m range (stat `0x17`), radius 2.5 m (stat `0x12`), ground markers
  `0x100006D7` / `0x100006D8` drawn by the aim code (VA `0xa39360`). The client never swaps it in by itself.
- **Emotes:** input actions Joke `0x100000CC`, Taunt `0x100000CD`, Laugh `0x100000CE`, Dance `0x100000CF`, Oath
  `0x100000DB` → emote codes `0x16` / `0x15` / `0x17` / `0x18` / `0x1C` → client script method `0x28F0001`. Batman's
  graph plays them on events Emote_Taunt `0x1000022C`, Emote_Laugh `0x1000022D`, Emote_Joke `0x1000022E`,
  Emote_Dance `0x100001F1` (end `0x100001F0`, abort `0x100001F2`). The event the client sends is still unknown.
- **The small mouse icon** left of the basic attack is the skill panel's own `m_mcMouseButton` (image `0x13000E68`,
  "basic attack = right click"), not a server element.

## Asset formats for the UE5 export (2026-10-18, Gaslight Batman pack `0xA0000076`)

- **Texture `0x13`:** `u32 did | u32 version (2) | u32 mips | u32 0 | u32 flags (3 or 0x103) | u32 width | u32 height |
  4s FourCC (DXT1/DXT5) | u32 data size | mip chain, largest first`. `0x130002CB` is 1024x1024 DXT5, 9 mips, 1398096
  bytes (exactly the chain sum). Exported to DDS by prepending a 128-byte header. The DXT5 textures can be
  normal maps (xy in alpha/green): `0x130002CB` is Batman's. Version 4 (`0x13001A01`: `04 | 1 | 0 | 3 | 0x10 |
  DXT1 | 0x300`) has another header and is not decoded.
- **`0x10`** records are only their DID (key names). **`0x14`** = shader/material template with DXBC bytecode and
  parameters (ColorAndOpacity, NormalMap, SpecularMap, EnvMap, EmissiveMap...), ~75 KB each, shared pack
  `0xA0000037`. **`0x16`** = material instance (texture refs `0x13` + floats). **`0x17`** = 20-byte model part
  binding: `did | 0x14 | key 0x10 | count | 0x16`. **`0x19`** = key/value parameter set (probably material).
- **`0x18` / `0x36`** hold Havok packfiles (magic `57 E0 E0 57 10 C0 C0 10`, `hk_2012.2.1-r1`): skeleton, ragdoll,
  cloth. Full-install scan: 21177 packfiles, all 2012.2.1; `hkaSkeleton` in 224 packs, ragdoll 161, cloth 111,
  `hkbBehaviorGraph` + `hkaSplineCompressedAnimation` 96. No `hkxMesh`/`hkxVertexBuffer`: the render mesh is not Havok.
- **Static mesh `0x17` (solved for format `0x1205102`):** `did | shader 0x14 | key | 1 | material 0x16 | 1 | 1 | ref |
  1 | format | vertex count | vertices | bbox (6 f32) | 0 | 1 | index count | u16 indices`. Vertex 24 bytes: `f32 x,y,z |
  u32 normal (3 signed bytes) | u32 uv (2 x UNORM16) | u32 tangent`. Verified on `0x170000CB` (1064 vertices, max
  index 1063, 532 triangles, a debris model). Other format words seen (`0x205102`, `0x2205102`, `0x3205102`,
  `0x4205102`, `0x21D102`, `0x122D102`...) are not decoded; the 20-byte `0x17` stubs (e.g. Batman `0x170000DB`) only
  bind shader + material.
- **Skinned character mesh (solved 2026-10-18, RenderDoc capture of Tutorial 1, Gaslight Batman, pack `0xA0000076`):**
  one block per mesh: `... | u32 0x10000011 | u32 1 | u32 ref 0x170000DB | u32 1 | u32 format | u32 vertex count N |
  N x 32-byte vertices | f32 bbox min/max | u32 0 | u32 1 | u32 index count M | M x u16 indices` (triangle list,
  indices start at 0). Vertex = the client's D3D11 input layout: `POSITION f32x3 @0 | NORMAL R8G8B8A8_UNORM @12 |
  TEXCOORD0 R16G16_SNORM @16 | TANGENT R8G8B8A8_UNORM @20 | BLENDINDICES R8G8B8A8_UINT @24 | BLENDWEIGHT
  R8G8B8A8_UNORM @28`. Evidence: the captured vertex and index buffers of draws 1259 and 948 are byte-identical to the
  pack at stream offsets 3802620 (6558 vertices, 29463 indices at 4012512, format `0x24D102`, z 1.08-2.42 = upper
  body) and 4592424 (1531 vertices, 6942 indices at 4641452, format `0x23D102`, z 0-1.14 = legs), **except the bone
  indices**: the pack holds skeleton-global bones (0x25, 0x27...), the GPU gets a per-draw palette (0x13, 0x14...).
  A third skinned draw (1752 indices, 48-byte vertices with f32 normals) has its index buffer at 1425976 but no
  matching vertices in the pack: probably the cape, rebuilt at run time by the Havok cloth (`hclClothData`).
  Decoder `uesrv/meshes.find_skinned`, export `python tools\mesh_export.py <pack> <folder> [--skin]`.
- **Havok skeleton (read 2026-10-18, `uesrv/havok.py`):** binary packfiles are file version 9, layout bytes
  `04 01 00 01` (4-byte pointers, little endian, empty-base optimisation). Header 64 bytes, then 48-byte section
  headers (`__classnames__`, `__types__`, `__data__`: tag[20] + start + local / global / virtual fixups + exports +
  imports + end). Pointers are resolved from the local (src, dst) and global (src, section, dst) fixups; the virtual
  fixups name each object's class. `hkaSkeleton`: name @8, parentIndices @12, bones @24 (8-byte hkaBone: name ptr +
  hkBool), referencePose @36 (48-byte hkQsTransform). Gaslight Batman: `MainSkeleton`, 86 bones
  `chr_batman_gaslight_main_*` (Parent, Root at z 1.19, HipGirdle, legs, spine, arms with fingers, two gun bones
  with antennas, Backpack_Accessory), packfile at stream offset 4862300 of `0xA0000076`; a 12-bone `Ragdoll` and
  `hkaSkeletonMapper`s sit in the other packfiles. **The mesh bone indices are this skeleton's indices** (each
  vertex is ~0.2 m from its dominant bone, ~0.9 m from a random one; the legs mesh uses only leg bones).
- **Material `0x160000E5` (Batman):** the model part `0x170000DB` binds shader `0x140003C9` and this material. Its
  texture entries are `(key, 0xBB8, 0x13 DID, 0, 0)`: `0xBB8` base colour `0x130002CD` (1024 DXT1), `0xBC3` normal
  `0x130002CB` (1024 DXT5 swizzled: x in alpha, y in green, DirectX green), `0xBCA` emissive `0x130002CC` (512 DXT1,
  almost black), `0xBE6` specular / gloss `0x130002CA` (1024 DXT5), `0xBC7` `0x13001A01` (version-4 texture, not
  decoded). Meanings come from the decoded images (no key names known). UV origin is top-left (head vertices map
  to the cowl at the top-left of the base colour).
- **Orientation:** the game is Z-up with characters facing +Y; the glTF export maps (x, y, z) -> (-x, z, y), a pure
  rotation (checked with a software render of the .glb: face and bat emblem toward +Z).
- **Animations (decoded 2026-10-18, `uesrv/havok_anim.py`):** Batman's behavior pack `0xA0000122` holds 69
  `hkaSplineCompressedAnimation` packfiles (67 full-body with 86 tracks, 2 VFX with 5). Fields:
  hkaAnimation type @8 (3) | duration @12 | transform tracks @16 | float tracks @20 | annotationTracks @28 (16 bytes
  each; the track name is the bone name, either `chr_batman_gaslight_main_<bone>` or `chr_batman_gaslight_<bone>`) |
  numFrames @40 | numBlocks @44 | maxFramesPerBlock @48 (256) | maskAndQuantizationSize @52 | blockDuration @56
  (4.25 s = 255 frames) | blockInverseDuration @60 | frameDuration @64 (1/60) | blockOffsets @68 | floatBlockOffsets
  @80 | transformOffsets @92 | floatOffsets @104 | data @116. Block layout and spline evaluation in the module
  docstring (Havok's standard 2012 spline format; rotations THREECOMP40 / THREECOMP48). Evidence: for all 69 clips
  the reader ends 0-12 bytes before the next block / end of data (16-byte block padding), and rendered frames show
  natural poses (combat idle, walk cycle, dance, knockback, T reference pose).
- **Clip DIDs:** each clip is a `0x1A` record; the packfiles appear in the stream in the pack's id-list order.
  The character's clip table sits before the behavior-graph packfile (stream offset 810724): `u32 81 | 81 x 0x1A DID |
  1 | 0x1F000002 (the graph's Lua script, record type 0x1F) | 0 | 81 | 81 x f32 duration` (68 distinct DIDs). Matching
  durations in id order assigns a DID to all 69 packfiles. **Clip names are not resolved**: the 81 graph
  `hkbClipGenerator`s (name @32, animationName @96 like `chr_batman_gaslight_idle_combat_a.hkx`,
  animationBindingIndex -1) match the table in count but not verifiably in order (the same animationName would need
  the same DID), and the character's animationNames were stripped (replaced by the table). Next: trace which DID
  the client loads when a clip plays (`tools/diag.py`), or find the name -> DID lookup in the exe.
- **Name search, 2026-10-18 (what was ruled out):** `hkbCharacterStringData` @32 is a 2012.2 asset bundle
  (`hkbAssetBundleStringData`: bundle name "" + 68 animation names, character packfile at stream offset 0xE2FC8,
  first name `loc_walk_fwd_25_a`); 68 = the table's distinct DIDs, @44 (filename bundle) is empty. Neither that list,
  nor the project's `animationFilenames` (80, alphabetical), nor the clip generators in storage / DFS / BFS / stack
  order (states sorted by `stateId` @60, blender children by weight @40, both ways) line up with the table or with the
  pack's DID order: tested against the anchors below, the best ordering matched 2 of 16. Clips carry no annotations.
- **Names verified from the decoded clips** (catalog `animations.tsv`, kind `clip`): the Root bone's ground speed is
  exactly 1.25 / 2.5 / 3.7 / 5 / 9 m/s for three sets of five clips, matching the `loc_walk_fwd_125 / 25`,
  `loc_run_fwd_37 / 50 / 90` names; renders tell the sets apart (guns forward = normal `798 173 6C8 6C6 6C4`,
  arms overhead = `_car_a` `799 6C2 6C7 6C5 6C3`, arms at the chest = `skill_rubble_` `F42 F41 F45 F44 F43`).
  `0x1A0000FD` is the static T reference pose. The other 51 clips keep `anim_<DID>`; e.g. `0x1A0002B6` (4 s, 2.5 m/s,
  a flip and a crouched landing) looks like the enter-world or Batflight clip, unverified.
- **Clip linking in the exe (static analysis 2026-10-18):** rva `0x899de0` is Havok's clip-to-animation linking
  (it logs "Animation loaded directly from clip's animationName" / "Could not load fallback animation"). It walks an
  array of 8-byte entries whose first word is a clip generator (`ebp`), reads `animationName` at `[clip+0x60] & ~1`
  (`esi`) and calls the asset loader through `[[ebx]+0xc](..., name, 0x1ce8444)`; at rva `0x899ea5` (right after the
  call) `eax` is the `hkaAnimationBinding` (or 0) and `[eax+0xc]` its animation. `tools/diag.py --anims` logs there
  the clip name, the animationName and the animation's signature (duration, frames, blocks, data size, first 32
  bytes, CRC32 of the data); `tools/anim_names.py` matches the signature to the pack's packfiles (all 69 signatures
  are distinct) to get DID -> name. Untested in the running client so far.
- **RenderDoc 1.46 Python API:** `VertexInputAttribute` has no `semanticIndex`; the index is appended to `name`
  (`TEXCOORD1`). `tools/renderdoc_dump.py` splits it.
- `oodle_141_win32.dll` is used only for network (`OodleNetwork1TCP`), not for assets.

## Server scripts (0x34) as the original server's logic (survey, 2026-10-20)

**Question:** can the game run with most features without hand-coding each one? The client is a thin,
server-authoritative client, so the original server code is not in it. Evidence from `InfiniteCrisis.exe` (Ghidra 12.1.4
through REA, sha256 `463adfff…`): the client refuses to set NetSharedVisually/NetSharedPrivately properties because
"these are server-authorative" (string `0x15c9f80`, checked at `0x62b4be`). A skill field description says the
missile offset is used "on the server" (`0x1805380`). The Kynapse (AI pathing) console help is "Server only". There are
no server-side game classes: the RTTI has no `gmS…` names next to the client's `gmC…`. Kynapse code is linked (the
console handler `0x58de10` edits the manager at `DAT_01b62e60`), but only as shared-engine debug commands.

**What the client packs do carry:** the server's *data*. 875 records of type `0x34` (server scripts, 70 packs,
about 8.7 MB) are node graphs. (Correction, same day: the exe does contain the script VM that reads and runs them; see "The script VM in the client exe" below.) Each node starts with `u32 2 | u32 node type
(0x100000xx)`. The node types decoded so far are Delay `0x10000010` (followed by f32 seconds) and RunScriptlet
`0x10000034` (key, target `0x4DD4` = SELF); see `re-notes/fx_re.txt`. The scripts reference skills `0x48` (3478
references), status effects `0x1E` (2823), scaling formulas `0x3B` (4121), other scripts `0x34` (3131), templates
`0x1D`, world states `0x2E` and classes `0x40`. `python tools\server_scripts.py survey` finds 148 candidate node
types. They are heavily skewed: the top 40 cover 82% of all uses (top: `0x10000058` in 297 scripts, `0x1000000E`
153, `0x10000007` 88, `0x10000003` 91, `0x10000024` 79, `0x10000019` 73, `0x10000034` 62). The numbers collide with
the property and graph-event tables, so the catalog names for them are wrong. The packs' 0x30/0x33 name tables only
hold variable names (DelayTimer, WaitTimer, ...), not node type names.

**Consequence:** a generic interpreter for 0x34 graphs (plus skill records 0x48, status effects 0x1E and scaling
formulas 0x3B) would run every champion's skills from the game's own data, instead of coding them one by one like
`batman.py` / `finale.py`. Bot AI, match rules (score, respawn, objectives) and encounter triggers do not appear as
0x34 data so far and still have to be written. Some referenced records are missing from the local packs (e.g.
`0x1D0000BA/BB`).

### 0x34 record format (decoding in progress, 2026-10-20)

`python tools\server_scripts.py dump 0x34xxxxxx` prints a record readably; `words` prints raw u32s.
- **Extent:** a record starts with `did | n | 1 | 0 | 0 | 0` (n is small, usually 1). The 0x34 DIDs also appear as
  references inside other records, so the start must match that header. The record ends where the next DID of the
  pack's ID list begins (the pack payload is the records concatenated in list order). 821 of 875 listed 0x34
  records are found in the player's packs; the median size is about 2.9 KB.
- **Variable names** are stored as the **ELF/PJW hash** of the name (`elf_hash` in the tool; e.g. `TargetIID` →
  `0x08DCD754`). Each scope ends with a table `n | (hash, slot)×n | n | (u32 length, chars padded to 4)×n`, and the
  names are *not* in the same order as the pairs, so match them by hash.
- **Operands** are 3 words. `value | -1 | -1` is a literal (u32, f32 or a hash). `hash | source | slot` is a
  variable: source 1 = script instance variable, 3 = block local, 4 and 5 = others not yet identified.
  `0x4DD4 | 2 | 0` is SELF, the entity running the script.
- **Layout:** header, then one or more blocks, each with variable declarations (`… | n | types… | defaults… | 1 |
  0`; types seen: 7 timer, 8, 0xD enum with a 0x30 table, 3), the name table, then statements. After the blocks come
  a state machine (states and transitions: `6 | event type | …` entries), the instance variable table and, last, the
  handled events (`k | T… | flags | 0 | 2`; e.g. `T3 T6 T5`, `T7 T149 T2`).
- **Statements** begin `u32 2 | node type`. Identified so far from the thrown-object script `0x34000167`, whose
  in-game behaviour is known:
  | Node | Operands seen |
  |---|---|
  | `0x10000010` Delay | `0 | target | f32 seconds | 1 | 0 0 0` |
  | `0x10000034` RunScriptlet | `0 | key (0x33 table) | target | argument | 0 0 0` |
  | `0x10000027` ApplySkill | `0x48 skill | target | parameter | …` (the thrown car: knockdown skill `0x48000295` on TargetIID with KnockDownDuration) |
  | `0x1000001D` ApplyEffects | `source | count | 0x1E effects… | magnitude | target | …` (`0x1E000017` + `0x1E00001A`, magnitude SkillDamage) |
  `0x1000006F` guards the fizzle branch (FizzleTimer from FizzleDuration). `0x10000134` and `0x10000085` head the
  collision branch (the latter carries DestructionRadius / DestructionMagnitude at CollisionPosition, the destruction
  impulse). `0x10000058` (the most common) heads blocks and is probably a sequence.

### The script VM in the client exe (static analysis, 2026-10-20)

The client contains the script VM that reads and runs 0x34 records, apparently shared engine code (`gmHFSMComponent`,
string `0x15f958c`, updates its HFSM instances in `0x977b30` and drops finished ones in `0x977aa0`).
- **Node registration:** each node type has a static initializer `mov [ebp-0xC], type; mov [ebp-8], factory;
  mov [ebp-4], object size; call 0x44e410; call 0x45fa20` (e.g. rva `0x13c2f70`: `0x10000155`, factory `0x9ca7c0`,
  0x34 bytes). 346 types in `0x10000000–0x10000FFF` are registered. All 60 most-used types in the player's scripts are
  among them (99% of uses). `python tools\script_nodes.py` rebuilds `catalog/data/script_nodes.tsv` from the exe.
- **Factory → class:** the factory allocates `size` bytes (TLS allocator, tag `0x56`) and tail-jumps to the C++
  constructor; its last `.rdata` vtable store is the class vtable (resolved for 183 types so far; other factories use
  other code shapes).
- **Vtable:** slot 5 = Unpack (stream), slot 6 = Pack (exact inverse), slot 11 = create the runtime instance (Delay:
  allocates 0x3C bytes and builds instance class `0x9a37b0`, vtable `0x15fb6f4`) or a clone (ApplySkill, ApplyEffects).
  Slot 11 has 139 distinct implementations in about 180 classes, so most nodes have their own runtime code in the client.
- **Readers:** `0xafae80(n)` reads n raw bytes from the stream. `0x453160` reads an operand as 3 u32 (object fields +4,
  +0x10, +0x14). `0x45fe70` is the node base: it reads a u32 node type and, when non-zero, creates that node through
  the factory lookup `0x45e450` and unpacks it in place. So the next node of a chain is serialized *before* the
  current node's own fields. `0x9c6830` reads a u32 length followed by that many bytes (RunScriptlet's argument
  block). The tagged-archive variant of these readers is `0x45fff0` / `0x460230`.
- **Unpack signatures** (B base, O operand, rN raw): Delay `B O O` (target, seconds); RunScriptlet `B O {len+bytes}`
  (O = scriptlet key | target | source, then the argument block); ApplyEffects `B O O O r1 r1 r1 r1 r4 r4 O O O O O
  r1`; `0x10000058` `B O O r4`; `0x10000007` and `0x100000A7` `B O O O r4 O O O O O r4 r1 O`; `0x10000085` (destruction
  impulse) `B r1 r4 r4 r4 O×9 r4 r4 r1 r1 r1`.
- **Operand values:** `value | -1 | -1` is unset or a literal; `value | 1 | 0` holds a literal (e.g. Delay 0.6 s is
  `0x3F19999A | 1 | 0`); `hash | 1 or 3 | slot` is a variable; `0x4DD4 | 2 | 0` is SELF. The meaning of the source
  code is not fully pinned down: 1 is used both for literals and for instance variables.
- **Open:** the record-level container (blocks, variable declarations, state machine) and the network message that
  starts a script on an entity. If the client already runs these HFSMs, the server may only need to start them and to
  resolve the authoritative parts (damage, deaths), instead of reimplementing every node.
- **Who runs what (2026-10-20):** a skill's 0x34 script is the *server* side. Bat Scream's `0x34000039` contains
  `RunScriptlet(0x10000162 Batman_Gaslight_The_Bat_Scream, SELF)`, which is the order our server sends by hand today
  (event 0x8D). The client looks the key up in the champion's 0x1D template (`0x1D000073`, pack `0xA0000122`, which
  holds the keys of all his skills) and plays the animation and effects. Missile entities carry their own scripts too
  (class `0x40000093`, Sonic Shell's missile, contains nodes running `0x10000163`). So the server needs its own 0x34
  VM. The client's node classes (Unpack = exact format, runtime instance = semantics) are its specification, and
  nothing has to be guessed from data alone. Batman's pack also holds his HFSM `0x3A000052` (record type 0x3A), which
  `tools\diag.py --hfsm` already watches.

### Exact decoding of 0x34 records with the client's own code (2026-10-20)

`python tools\script_decoder.py all` decodes 778 of the 821 0x34 records in the player's packs into node trees
(`data\script_trees\*.json`, kept out of git); `tree 0x34xxxxxx` prints one. It maps the exe into a Unicorn emulator and
runs the client's Unpack. The pieces found on the way:
- **Database type 7 = records 0x34.** The DID range 0x34000000–0x34FFFFFF is registered with type index 7 (rva
  `0x5e06b5`), and type 7 is bound at `0x9e0619` to create `0x44b960` (0x60-byte object, tag ScriptNode), unpack
  `0x9d80a0` → `0x44ece0` and `0x9d4bd0`.
- **`0x44ece0`** reads the DID (`0x43d210`), the node array at +0x20 (`0x44e840`: count, then per element u32 type →
  factory `0x45e450` → vtable slot 5), an optional object at +0x30 (`0x44a370`: u8 present flag), then +0x34, +0x44
  and the trailer. Node chains, child slots (`0x44ee70`: 3 × "type + node") and operands (`0x453160`) all go through
  the byte stream `0xafae80`.
- **Packed records pad every read to 4 bytes.** A u8 flag or count takes a whole word, and a string's characters are
  padded to the next word. With that rule the client's reader consumes whole records.
- **Server-only field:** a variable block (`0x45aa30`: types `0x45a610`, name table `0x45a940`, check `0x45a300`) is
  followed in the packs by the variables' default values, which the client build does not read. Sizes per type
  (words): 7 → 2, 8 → 2, 9 → 3, 0xD (enum: table DID + value) → 2, 0xE → 2, others 1; type 0xA varies. The decoder
  skips up to the name table (`1 | 0 | n | n × (hash, slot) | n strings`) and keeps the skipped words in
  `defaults`.
- **Not decoded yet:** 43 records stop in value readers (`0x46053e` / `0x469e95` chains, probably more server-only
  fields). 48 records end before data with flags bit 0x100 (`0x101`, `0x111`) in the trailer, apparently a server-only
  tail.
- **Emulation notes:** the static initializers in `0x13a0000–0x13d0000` must run first (447 of them, they fill the
  type registry). The TLS allocator is a struct of function pointers (`[TlsGetValue()] + 0` = alloc(self, size, n,
  tag, flags)). The allocator imports are tbbmalloc's `scalable_*`. SEH needs fs → a fake TEB. The string pool is not
  initialised, so `0x45a0b0` / `0x45a300` reject names (bypassed).
- **Script structure (decoded trees, 2026-10-20):** a script is a state machine. The decoder labels classes with low
  type ids as `builtin:N` (built-in VM classes); action nodes are `0x100000xx`.
  `builtin:1` = graph (holds states), `builtin:2` = state, `builtin:7` = action list run on entering a state,
  `builtin:9` = transition (condition `builtin:0xA` → `builtin:3` → a node, and an event `builtin:6`),
  `builtin:5` = the events the script listens to (Sonic Batarang: `0x10000008`, `0x100000A4`, `0x1000000C`,
  `0x100001B3`).
  Sonic Batarang `0x3400003B`, as an example:
  - `0x10000050` → `0x1000009F` loads skill stats into variables as pairs (stat → variable): 3 cost, 0xF
    `SkillCooldownDuration`, 0x12 `SkillRange`, 0x1E `MissileSpeed` (Sonic Shell: 0x17 `CastRadius`). This
    confirms stat 15 = cooldown, 18 = range, 30 = missile speed, 23 = cast radius.
  - Cast state: `0x1000003F` ×2 face `TargetPosition` / `TargetIID` (`FacingIDVariable`), `RunScriptlet
    0x10000164` on SELF (the cast animation), `0x10000014` takes `TargetPosition`.
  - Fire state: `0x1000005E` ×2 = launch a missile of class `0x40000090` at `TargetPosition` / `TargetIID` with
    `SkillRange`, `MissileSpeed` and `FireOffset`; `0x10000007` starts the cooldown with `SkillCooldownDuration`.
    Bat Scream fires class `0x40000092`; Sonic Shell spawns entity `0x40000093` (`0x100000A0` with
    `CreatePosition`), then `0x1000005E` with `MissileVelocity`, and `0x100000FA` detonates with `CastRadius` after
    `MissileLifetime` / `MissileDetonationTimer`.
  - Damage is not in the skill script: the missile classes (`0x40000090/92/93`) carry their own scripts.
  Batman's six skill scripts use 54 distinct node types.

### Script VM object model (static analysis + decoded trees, 2026-10-20)

Classes come in three families. The decoder now records each node's runtime vtable (`vt`) so they can be told apart:
- **Structural (`0x15A8xxx`, ScriptNode tag):**
  - **graph = composite state** (vt `0x15A8218`, id 1, Unpack `0x44f140`): 3 child chains (`0x44ee70`, at +8),
    optional local variable block (`0x44a370` → `0x45aa30`, at +0x14), array of child states/nodes (`0x44e840`, at
    +0x18), array of polymorphic objects (`0x44be80`, at +0x28; created by type with tag 0x56, probably transitions),
    a 4-level nested list of u32 (`0x44e690` → `0x44e090` → `0x44c790` → `0x44a790` → `0x4494b0`, at +0x38; the
    link table: node → port → link → values) and a u32 (at +0x44).
  - **state** (vt `0x15A7F98`, id 2, Unpack `0x44f060`): the same 3 chains and optional locals.
  - Others: list (`0x15A8B68`), transition-like (`0x15A8ADC`), condition (`0x15A890C`), loop (`0x15A8B98`), event
    (`0x15A8794`), event list (`0x15A8B0C`), ... Their execute is vtable slot 11. Ghidra has no function bodies
    there (they are only reached through the vtables), so they need local disassembly.
- **Expressions (`0x15A9xxx`, value registry `0x45fa20`, ids 1–0x47):** evaluate (vtable slot 10) into a 16-byte
  variant whose type codes are 1 int32, 2 uint32, 3 float, 5 int64, 6 uint64, 7 double, 9 vector3 (pointer).
  Binary operators read two child expressions (`0x469ee0`), unary operators one (`0x469e40`). Identified:
  - arithmetic: `0x23` add (`0x4532a0`), `0x1C` sub (`0x4538d0`), `0x29` mul (`0x453f50`), `0x17` increment;
  - comparison: `0x22` equal, `0x1B` not equal (`0x450890`), `0x2A` less than (`0x44f9d0`), `0x31` max;
  - vectors: `0x28` make vector3, `0x05` cross product, `0x08` length, `0x0D` normalise, `0x16` dot product,
    `0x37` vector add;
  - other: `0x1D` logical not, `0x06` / `0x2C` integer divide, `0x03` variable, `0x02` constant.
- **Game actions (`0x15Fxxxx`, ids `0x100000xx`):** 146 distinct types are used by the 259 champion skills. About
  40 of them cover most uses: `0x1000009F` load skill stats (98% of skills), `0x10000007` cooldown (85%),
  `0x10000034` RunScriptlet (82%), ...
- **Transitions** (the objects at graph +0x28, Unpack `0x44eb50`): `sources` = list of state indices (`0x44af20`,
  elements read at `0x44afbf`; empty = from any state), `target` state index (u32, `0x44eb74`), a trigger node
  ("type + node", `0x44eb86`; 0 = none, i.e. immediate), then two u32 (`0x44ebd3`, `0x44ebe5`; the second is 1 on
  the "back to idle" transition).
  The link table at +0x38 is the same information precomputed per state: for each state, 3 ports, each with two
  lists of transition indices (port 2, list 0 = transitions leaving that state).
  The decoder now closes each node exactly when its Unpack returns, with a one-shot hook on the return address,
  so graph-level reads are no longer attributed to the last child state.
  Sonic Batarang's main graph (`0x3400003B`, second graph):
  - States: S0 idle; S1 cast (face the target, RunScriptlet `0x10000164`); S2 fire (two missiles `0x40000090`,
    cooldown); S3 cleanup (`0x1000000A`).
  - Transitions: T3 S0→S1 on `0x1000013B(0x1000001D)` (activation); T0 S1→S2 on `0x10000019(0x1000000F, 5)`;
    T1 S1/S2→S3 on `0x10000019(0x1000000F, 2)`; T2 any→S3 on event `0x10000009` when `NeedCleanup`; T4 S3→S0
    immediately.
  - The first graph loads the skill stats (`0x10000050` → `0x1000009F`) and lists the events the script listens to
    (`0x10000008`, `0x100000A4`, `0x1000000C`, `0x100001B3`).
- **Reading model:** `icserver/scriptvm.py` builds graphs, states, transitions, chains and nodes from the decoded
  trees. `python -m icserver.scriptvm 0x3400003B` prints a script as pseudo-code. Each child's role comes from the
  reader that precedes it in its parent (`via` in the tree):
  - `0x45FE89` next node of a chain, `0x44E8E2` array item (graph states), `0x44EE99` state chain slot,
    `0x44EB86` transition trigger, `0x460502` assigned value;
  - `0x469EF9` / `0x469F46` binary operands, `0x469E59` unary operand, `0x469FF9` / `0x46A046` / `0x46A093`
    vector x/y/z, `0x45FC62` / `0x46001A` embedded node.
  - Operands come from readers `0x453173` / `0x453185` / `0x453197` (value, source, slot).
- **First runtime (simulation only, 2026-10-20):** `icserver/scriptvm_runtime.py` runs a script's graphs, states,
  chains, transitions and events against a `World` interface. `python -m icserver.scriptvm_runtime 0x3400003B`
  simulates one Sonic Batarang activation from the original data: face the target, RunScriptlet `0x10000164`, at
  the cast point one missile `0x40000090` (speed = stat 30 = 14, range = stat 18 = 9), cooldown = stat 15 = 5 s,
  then cleanup and back to idle.
  Assumptions to check in game: chain result codes 5 = cast point, 3 = cast finished, 2 = done or interrupted
  (inferred from 600+ transitions); event `0x1000001D` = skill used; `0x10000026` = cast (fills TargetIID /
  TargetPosition from the request, waits for the cast point); `0x10000031` = spend Will (stat 3).
  The missile script `0x3400003F` (11 states) still needs about 12 node types: `0x1000006F`, `0x10000024`,
  `0x10000062`, `0x10000114`, `0x1000007A`, `0x1000003E`, `0x1000001E`, `0x10000029`, `0x10000028`, `0x10000052`,
  `0x1000006A`, `0x10000070`, plus the structural ones (assignment, loop, conditions). Its damage formula is
  `stat 5 × max(0.2, 1 − hits × reduction)`, which lowers the damage on each ricochet.

### Running scripts: semantics fixed while running Sonic Batarang (2026-10-21, fase3-fn)

Found by running Q (`0x3400003B`) and its missile (`0x3400003F`) end to end in `icserver/scriptvm_runtime.py`
and checking each step against the data; node names are in `catalog/data/script_nodes.tsv` (status `partial`).

- **LIST `0x15A8B68` is if / else / then.** Its values are `[3, then-type, else-type, always-type, cond-type]`;
  the condition is the child read at `0x46001A`, the three slots are the children read at `0x45FC62` in that order.
  Only one of then / else runs, then the always slot.
- **NOT classes:** expression `0x24` (vt `0x15A9280`) is "is zero"; NODECOND `0x15A890C` is the negation of its
  node predicate and is false with no node. An unknown predicate is treated as false.
- **SetVariable `0x10000058` with a `#name` operand** copies the parameter of that name from the event that
  entered the state (e.g. Collider, SubEntity, EntityPosition of collision `0x10000002`).
- **Events:** every region sees an event, but each region fires at most one transition per event.
- **Cast `0x10000026` is not latent:** its chain finishes at once and the chain result (5 = cast point) is
  delivered after the cast time; the 0x10000019 trigger then moves the skill graph on.
- **IsValidPosition `0x10000014`** guards the missile spawn; without it the state re-entered and launched a
  second missile.
- **Assumption (not confirmed):** a target hit counts as a collision for MaxCollisions (NumCollisions grows when
  a state that applied damage is left). The server-only expression `0xC` is still unknown (probably integer
  divide, `idiv` in `icserver/scriptvm.py`); builtin predicate vt `0x15A89F0` (type 0x10) returns true.
- **Default values** of script variables (server-only blocks) take 2, 3 or 2 words by variant type
  (`7, 8 → 2`, `9, 0xA → 3`, `0xD, 0xE → 2`); type `0xA` is a guess.

## The new data-driven server and what running the scripts taught (2026-10-21, fase3-fo)

`python -m ics` is a new server written so that champions, skills and maps come from the game data instead of
hand-written code. Only the protocol plumbing was carried over from `icserver/` (wire format, RSA, connection,
scheduler, log, pack reader, message layouts). Running Batman's basic attack and Q end to end, and every champion
skill in simulation (`tools/script_coverage.py`: 42 -> 125 of 259 skills run with no unknown node), fixed the
following.

### Where the server finds things in the packs
- **Champion kit:** `catalog/data/champions.tsv` (variant and costumes -> skill set) and `skills.tsv` (skill set:slot
  -> script 0x34, stats). In the skill record: block 0x1000003F, script property 0x10000328, stats 0x100004B4.
- **Entity class -> its server scripts:** the class's template record `0x49xxxxxx` (same low bits), property
  `0x8E` = list of DIDs (entry kind 0x30E). E.g. Sonic Batarang's missile 0x40000090 -> template 0x49000090 ->
  [0x3400003F, 0x340001A6]. This replaces the hand-written missile -> script map.
- **Status effect records `0x48...`** (not skill kits): property `0x10000242` = their script (0x48000AB0 ->
  0x34000470), `0x10000063` = max stacks (99 shot trackers, 1 a stun, 10 a passive stack), `0x10000334` flags
  (0x8, 0x10, 0x4000, 0x4100; meaning unknown).
- **Record headers:** `did | 0 | count` (most), `did | 7 | entity | 0 | count` (world states), `did | 2|3|4 | count`
  (entities and templates). The pack's record list order is not reliable for finding a record's start (a
  reference to the DID can come first): `ics/gamedata.py _record` checks the header.

### Script semantics
- **Three chain slots per state: enter, update, exit.** The state's three chain reads (reader 0x44EE99) give the
  type of each slot's first node, 0 = empty; the decoder's child list leaves empty slots out, so the slot comes
  from the fields. Update runs every tick while in the state (the server uses 0.1 s), exit when the state is left
  (innermost sub-graph first). Evidence: the basic attack 0x34000037 runs InitSkill / LoadSkillStats in S0's
  *exit*; status 0x34000470 recomputes its shot's travelled range in S1's *update*; exits clear stored targets.
- **Cast results are signals of the cast in progress**, not the end of a chain: Cast (0x10000026) starts a cast
  that signals 5 at the cast point and 2 when it ends (the server: 0.25 s + 0.15 s, not found in the data). The
  end of a chain only fires plain transitions. Basic attack: S1 Cast -> S4 on IsAlive; S4 -> S2 (the shot) on 5;
  S2,S4 -> S3 on 2.
- **Transition field a:** transitions with a = 2 are checked before those with a = 1 (S1 -> S0 "when done" [1,1]
  must not win over S1 -> S4 IsAlive [2,1]). A bare predicate node can be a trigger.
- **Builtin numbers collide between registries:** "builtin 0x6" is the event node (vt 0x15A8794) in the node
  registry and the division (vt 0x15A94E8) in the expression registry; always go by the class (vt). Expression
  classes found: 0x15A8F44 the game time, 0x15A9910 / 0x15A9948 x / y of a vector, 0x15A98D8 squared length,
  0x15A9BE8 position + offset, 0x15A9A28 / 0x15A99F0 / 0x15A9398 number conversions (values = the result type).
- **Persistent scripts:** a champion's skill scripts start with the champion and wait for the "skill used" event
  0x1000001D (the passive runs by itself); statuses and RaiseEvent need the scripts of one entity to see each
  other's events.
- **Status effects:** ApplySkill (0x10000027) starts the status's script on the target (a new instance per use when
  max stacks > 1) and sends it 0x10000006 "applied" with parameters; 0x10000003 "removed" when its duration ends.
  HasStatus = 0x100000A4.
- **Event parameters by operand slot** (derived with `tools/script_params.py`: the slots callers fill vs. what the
  receivers read). ApplySkill: 0 target, 1 EffectDuration, 2 EffectRank/StackCount, 3 EventBool (0xC58DA9C),
  5 SourceEntityDID, 6 EventIID (0xCC58914), 9 EffectSource (the caster when empty). RaiseEvent (0x1000006B):
  0 the receiving entity, 1 the event IID (0x9A6A765), 2 Position, 3 a value (0x5A05762 / Bool 0x4965C).
  Names from the ELF hash where a known name matches (Bool, Slot, Delta, DataID, EffectSource, EffectDuration,
  EventBool, EventIID, EventPosition, SkillSlot, EntityPosition, SubEntity, TargetIID, StackCount, SourceIID); the
  hash is weak, so longer guesses collide and were not used.
- **The basic attack's shot** is not a missile object: RunScriptlet passes the target (variable 0x10000030) and the
  shot speed (0x100009EB) to the client, and ApplySkill(SELF, ..., target)[0x48000AB0] starts status 0x34000470,
  which tracks the shot ((now - FireTime) x speed + slush) and raises 0x10000126 on its owner when it arrives;
  the basic attack's graph S2 applies the damage then. Assumption: the tracker ends when it raises the impact (only
  0x340005F7 removes itself with node 0x10000018; the others would raise it every tick).
- **Other nodes:** 0x1000004E RaiseGraphEvent(entity)[graph event] (scriptlet 0x100001E3 + variable 0x780),
  0x10000011 GetPosition, 0x1000007A HitEffect(target)[scriptlet key], 0x10000103 StartScriptlet(entity, -, -, out
  handle)[key], 0x1000010B RollCritical, builtin 0x2 StartTimer(timer, seconds) / builtin 0x8 TimerExpired(timer),
  builtin 0x11 Copy(destination, source), expression 0x10000002 GetAttribute(entity)[attribute property] (the
  basic attack reads 0x100005FE, its attacks per second).

### The client cannot run the game's logic itself (static analysis, 2026-10-21)
The user asked whether the exe could run the game with no server work. It cannot: there is no offline, local or
listen-server mode (no such strings), and the server-script node classes in the client are data-only. Their
vtables (e.g. ApplyEffects 0x15FC8FC, Cast 0x15FB844, ApplySkill 0x15FDFDC, RunScriptlet 0x15FE13C, StartCooldown
0x15FD638) hold: [0] scalar deleting destructor, [5] Unpack, [6] Pack, [11] Clone (allocates the class size and
copy-constructs: ApplyEffects 0xDC), [12] destructor, [10] for a few classes (Cast 0x9934F0) a resource preload;
the rest are shared base methods (0x45AD80 ...) or the empty 0xAB4D80. No Execute: the code that applies damage,
launches missiles or runs the state machines was only in the original server. The client's part is loading,
drawing and the scriptlets (0x33) the server orders.

### More script semantics (fase3-fp)
- **builtin 0x10 (vt 0x15A89F0) = "the variable is true"**: the basic attack picks its critical shot with
  `builtin 0x10($CriticalChanceRoll)`; the missile ends on `NOT builtin 0x10($DamageSuccess)`.
- **ApplyEffects slot 5 is an output: DamageSuccess.**
- **vt 0x15A88E0 with two operands = ">="** (another class numbered 0x12): missile `NumCollisions >= MaxCollisions`.
- **The basic attack's normal shots** alternate left / right: wind-up 0x10000195 / 0x10000196, shot 0x10000188 /
  0x10000189 (the critical ones: 0x100000B8 / 0x1000017E).
- **Load:** the player object needs 0x100001D3 (the encounter) from its second bundle on, during the load (the map
  manager loads the map when it changes); without it the client reported load complete at 60 % and the map was
  wrong. The map's units must wait until after the load.

### What the client loads for a map, and where the server finds it (static analysis, 2026-10-21, fase3-fq)
- **0x20AF (handler 0xA99F00)** stores the encounter DID, a DID list and a pack list; the loader 0xA99E20 reads
  the encounter's 0x1000028A and 0x10000406, then `gmConnectionManager::LoadParentRPs` (0xA99370) loads, for every
  DID of the list, the pack that holds it (0x866480), plus the listed packs. **The client loads exactly what the
  server names**; it does not work out a map's packs by itself.
- **Encounter template 0x49xxxxxx** (Tutorial 1: 0x49000991, pack 0xA00000B3, header `did | 2 | 0x2E`):
  0x10000406 = the **map pack** (0xA0C112CA), 0x10000AE6 = a required champion (0x40000086), 0x10000897 = the lobby
  music pack, 0x10000B66 next encounter, 0x10000C1B the post-match movie, a dozen 0x48... settings records.
- **The map pack** (category 1: terrain cells 0x80/0x81/0x82/0x90 named by landblock, e.g. 0x800113CB) holds
  `u32 count | count x pack DID` = the encounter's packs. Tutorial 1: 0xA000024C zone (category 0xD), 0xA0000256
  layout (0xF), 0xA0000257 variants (0xE), 0xA00002D6 / 0xA00002D7 (0x7, textures). Tutorial 2 0xA0C112C2 and
  Gotham Heights v AI 0xA0C11AF2 (zone 0xA000009A) follow the same pattern.
- The earlier server sent only the zone pack: the **layout and variants packs were never loaded**. That is the
  likely cause of the invisible props (the carrier workaround) and of the untargetable tutorial drone 0x40000C72.
- **Layout placements -> classes:** a variant from the variants pack (units), else the entity whose template has
  0x510 = the world state (doors 0x40000B0F / 0x40000557, the power core 0x40000C90), else the bare world state.
  Champions' placements: the world state in each champion variant's template 0x510 (132 of them). Templates run
  past the pack's record list end (Gaslight Batman: 0x510 at +0x1C74).
- **FindTargetsInRadius** values `[.., kinds, relation, max count ..]`: relation 3 = hostile.
- A missile's own scriptlets (RunScriptlet(SELF) in 0x3400003F: 0x100001C1, 0x1000064C) play on its object.

### Layout props, unit attacks and the encounter's scripts (2026-10-21, fase3-fu)
- **Client-placed objects** (static analysis, BlockEntities 0x547B50 / 0x53DA40): only the landblock statics of the
  map pack's 0x82 records (`flags | 7 | index | cell | world state | xyz | quaternion | [properties]`, IID top
  byte 1). None of the layout's gameplay objects is among them: the server creates those.
- **DB types** (prefix -> type, table 0x1B68B30 built by 0x5E0360): 0x1D -> 0x22 property collection, 0x2D -> 0x0B,
  0x2E -> 0x2D, 0x34 -> 0x07, 0x35 -> 0x3E (Director), 0x40-0x47 -> 0x40, 0x48-0x4F -> 0x29, 0x1F -> 0x50 (Havok
  behaviour Lua: animation only), 0x80 -> 0x0E, 0x81 -> 0x24, 0x82 -> 0x23, 0x90-0x9F -> 0x3B.
- **WorldEntityFactory 0x54F1F0** accepts a bare world state (DB type 0x2D) as the class; an entity class reads
  0x510 and coerces a non-"unique" creation type (0x50F not in {1,4,6,7,8,9}, check 0x580120) to 6 or 8. The
  vehicle and paddy wagons have 0x50F = 5 (landblock static): the server now sends them 0x50F = 6. The ranged
  drone 0x2E001168 has 7 (a mobile character).
- **Unit attacks:** a variant's template holds its attack skill like a champion skill block: script 0x10000328
  (tutorial drone 0x40000C72 / thug 0x40000C71 -> 0x340004A1, Destroyer 0x40000EB2 -> 0x3400058F, generic drone
  0x40000A5C -> 0x34000088) and stats 0x100004B6 / 0x100004B7 (stat 18 range 1.0). These scripts advance on cast
  result 3 (S1 -> S2 applies the damage): the cast signals 5 and 3 at the cast point.
- **Encounter scripts in the layout pack:** the layout records 0x1D end with `hash | type | value` variable
  overrides followed by a server script: 0x1D0007EE -> 0x3400058A (conversations 441, 559, 558, 557, 556, one per
  event 0x10000060), 0x1D00078A (the PowerCore point) -> 0x34000591 (conversation 444 then node 0x10000121 [393]),
  0x1D000774 -> 0x34000595 (conversation 463), 0x34000700 (conversations). Node 0x100000D1 [0, key, 1, 1, 0, 1,
  60.0] looks like StartConversation(key) with a 60 s limit. Who starts them and what raises 0x10000060 is open.
  The decoder's record finder skipped them (header `did | 1 | 1 | ...`); all 18 0x34 records of the tutorial's
  packs now decode.

### Layout placement properties (2026-10-21, fase3-fw)
After a placement's world state: `u32 x3 | u32 count | entries` (`key | key | value`; the array 0x954 is
`key | key | n | n x (0x462 | DID)`), read by `ics/rp.py _placement_props`:
- **0x100007A2 = side**: 1 on every drone (the encounter's enemies), 3 on the doors and the power core, absent on
  the thugs (neutral: they fight the drones, not Batman).
- **0x6B3 / 0x6B4 = scale** (01GateA 0.9, Destroyer 0.85).
- **0x954 = linked 0x1D templates**: the power core -> 0x1D00078A (script 0x34000591), 03ThugA -> 0x1D000890,
  03MeleeD -> 0x1D0007EE (script 0x3400058A, conversations), the Destroyer -> 0x1D000774 + 0x1D000385,
  InvisibleTarget -> 0x1D0000E1. The templates end with variable overrides and a timeline of `0x10000060 | frame`
  pairs (200, 390, 530, 655, 846 in 0x1D0007EE): the event that advances their conversation scripts, raised by
  time. Not run yet: when each template starts is still open.
- Every placement's position has cell 0xFB (251); the earlier server sent props with it and they showed.

### Cinematic scenes and their server scripts (2026-10-21, fase3-fx)
The 0x1D records the layout placements link (property 0x954) are **cinematic scenes**: header
`did | 0x1000xxxx | 1 | 0 | cell | landblock | position`, then the actors' placements with per-frame tracks
(scriptlet keys such as Batman's 0x10000196 / 0x10000189 at given frames), and at the end
`n events | n x (frame, event 0x10000060) | n vars | u32 | n x (hash, type 3, value) | scene script 0x34...`
(the script DID is the record's last word; the pack's record list takes it for the next record).
- Cinematics link scenes through their placements, recursively: 0x35000026 (intro) -> 0x1D0007A4 -> 0x1D000771 ->
  0x1D0007EE (script 0x3400058A, events at frames 10, 200, 390, 530, 655, 846, 4 vars) and 0x1D000890;
  0x35000025 -> 0x1D000789 -> 0x1D00078A (the falling power core with 15 path points: script 0x34000591, events 15,
  545); 0x35000028 / 0x35000033 -> 0x1D000774 (script 0x34000595, events 14, 145, 300, 450, 580).
- The client plays the scene (actors, animations); the server runs the scene script and raises 0x10000060 at the
  frames (30 fps assumed). The scripts start conversations (node 0x100000D1 [0, key, ...]: 441, 559, 558, 557, 556
  in 0x3400058A; 444; 463), read the player and his agent (0x10000187 / 0x10000188) and set an environment value on
  enter / exit (0x1000009C [1, 0x10000016 | 2 | 0]).
- The cinematic's actors (the Destroyer, the sphere, cinematic drones) are the client's own; the gameplay objects
  are the server's.

### Placing props, scriptlet tables, flows, champions, the shop (2026-10-21, fase3-fy)

Surveys: `docs/re-notes/actor-creation-and-environment.md`, `tutorial-data-inventory.md`, `maps-encounters.md`,
`champions-all.md`, `shop-items-inventory.md`, `progression-meta.md`; plan in `master-plan.md`.

- **Network objects are placed only by their movement component.** 0xB0 is read by 0x57EE90; the only listener that
  places is component C (creator 0x604D80, ctor 0x60A9B0), whose module (vtable 0x15C62A8 +0x68) calls
  SetEntityFrame 0x588290. C exists only for creation types whose mobility (table 0x580160) is 2: types 7 and 8.
  WorldEntityFactory 0x54F1F0 rewrites an entity class's non-unique type to 6 or 8 (by mobility); a bare world
  state keeps its own (3, 5, 9: never placed). So props go out with the module (`0x62 | 01 | 01 | 0x0F`) and
  `0x50F` = 8 (UniqueDynamicMobile); 0x64CA10 merges the 0xBC table into the creation desc before step 3.
- **Scriptlet tables (0x1D) in a pack:** their bodies do not start with their DID. A body is `u32 n bases | n x base
  table | u32 1 | u32 count | scriptlets`; a scriptlet is `key | 0 | n props | props | n actions | ...`. In a pack the
  records whose body starts with their DID give the anchors (the longest chain of occurrences in list order); the
  unanchored records between two anchors have their bodies in the same order (`ics/rp.py script_tables`, 49 of 50
  tables of 0xA0000256 exact). An object accepts the keys of its world state's and its entity template's 0x7D2
  tables, the placement's 0x954 tables and their bases. Scriptlet key names: the largest name run of pack
  0xA0000038 (`u32 key | u32 length | name padded to 4`) is table 0x33000000.
- **Unit stats:** template property 0x10000165 names a stat block `did | 0 | n | key | key | f32` (entries
  `key | 0x5...` are formula slots without a value). **Champion stats:** the definition's 0x100008E2 names a 0x40 /
  0x49 pair whose twin has array 0x100008E0 of 0x100008DD {0x10000100 stat, 0x100008DF value at level 1,
  0x100008DE growth per level}; the champion's Will is 0x10000432 and its Will regeneration 0x10000484 (items use
  0x10000486 / 0x10000483 for them; treated as the same stats, probable).
- **Champion definitions** (twin 0x49 of each variant, header `did | 4 | n`, template 0x1000048B = 0x48000732) name
  every pack and record the client needs; variants with one skill set (0x100005E9) are one champion; the base is
  the one whose light record has 0x10000575. 54 champions, 156 variants. Names in the string tables end in grammar
  tags (`[mn]`, `[fn]`).
- **Default loadout** (definition 0x10000CEB -> 0x48...): 0x1000064E the Stolen Power pair, 0x10000478 recommended
  artifacts (`0x10000477 {0x10000475, 0x10000694 artifact}`), 0x10000A12 augments, 0x1000098F mods, 0x1000034B the
  rank order (19 slots: 1-4 Q/W/E/R, 5 passive).
- **Encounter templates** (`did | 2 | n`) read with three more kinds: 0x01 ASCII (`u32 length | bytes`, padded),
  0x06 three f32, 0x14 a DID padded to 8 bytes (the map pack 0x10000406). Category 0x10000D0B (1 vs AI, 2
  challenge, 3 PvP, 4 tutorial), objective table 0x100001D2, shop list 0x1000081E (foundry record 0x1000042C).
- **Objective table** 0x48000D3F: array 0x1000019F of tables {0x1000030B id, 0x10000C15 text (token, table
  0x2B0000ED), 0x10000283 count, 0x10000B20 key binding}; title 0x10000391. A StringInfo can be sent as `u8 0 | u32
  token | u32 table | variables`, so the server sends the reference, not the text.
- **Shop protocol** (client bodies have no leading 0): 0x208B `u32 artifact | u32 seq | u64 iid`, 0x20A7 `u32 artifact
  | u32 slot | u32 seq | u64 iid`; answers 0x20E2 to the champion (`u32 n | n x (did, count) | amplifier-set tail`),
  0x2086 `u32 seq | u64 iid` (unlocks the shop), credits 0x1000035E; 0x2078 recommended list; may shop: 0x10000A23.
- **Not in the data** (authored in `ics/encounters/tutorial1.py` and `[ics]`): when each tutorial step happens and
  where server-made objects stand; credits and XP amounts; the XP curve; respawn times.

### Targeting, relations, navmesh paths, fog, statics (2026-10-21, fase3-fz)

Surveys: `docs/re-notes/targeting-and-relations.md`, `docs/re-notes/movement-collision-fog-map.md` (VAs).
- **Right click:** 0xa8a270 -> 0xa86a00 picks the entity under the cursor (0xa81b30, scored by 0xa16a60) and makes
  an attack order only if the validator 0x9d01d0(champion, target, slot 0) accepts it: relation mask (skill
  0x10000448, default 3 = neutral or enemy), visibility, **unit flags** ([[ent+0x84]+0xa4] or property 0x1000019D,
  accepted when flags & 0x1000068D's default 0x555959; 0 always fails), **0x10000AA7** (targetable), **0x100001C3**
  non-zero, alive. The units' templates (0x49...) hold 0x1000019D 0x10000, 0x10000AA7 1, 0x100001C3 / 0x1000034C 0x1E;
  the client's own records do not: the server sends them as instance properties.
- **Relation:** team = the unit component's cached PVP_Team, else property 0x1000009C; same team 4 (ally), team 0 1
  (neutral), else 2 (enemy). The local team is the local player object's PVP_Team. On a PVP_Team change the client
  (0xa7b0d0) stores the relation (0x10000425) and colour (0x100007A2: ally 3, enemy 5, neutral 6) and runs
  `_Entity_OnSetClientRelationship` (0x100003A6).
- **Movement:** no path message exists either way; the client snaps a click onto its Kynapse navmesh
  (0xA70030 -> 0x4FA870) and sends 0x20EE; Kynapse's commands are "server only". The 0xB0 module part is `u8 seq | u8
  mode | [flag 0x01: u64 controller IID]`; the mode is a row of record 0x48000002 (property 0x38B).
- **NavMesh blob** (map pack records 0x900113CB / 0x901113CB / 0x902113CB, one per agent class: radius 0.525 / 1.1 /
  2.1): `u32 1 | f32 radius | f32 height | u32 agent class | 0 | 0 | u32 size | "BlobAggFile"`; from "BlobAggFile":
  +0x2C cell count, +0x54 cell box, +0xB0 cells as (u32 size | u32 offset from its field). Cell: `u32 x | u32 y | 4 x
  (count | offset)`, the fourth = floors (size | offset). Floor: `u32 | u8 box[4] | (n, off) vertices u8 x, y (0.2 m,
  100 per cell) | (n, off) f32 altitudes | (n, off) half-edges (u16 pair | u16 start vertex + type)`, three per
  triangle. A cell is 1/8 landblock; cell index = landblock x 8 + n. Decoded in `ics/navmesh.py`.
- **Fog of war:** the viewer is the player object's 0x100000CF entity; vision sources are same-team, 0x2A1 not
  false, alive, radius 0x10000133 (+ attribute 0x10000642); darkening is off when the champion has attribute
  0x100007C0. The client fog does not hide network objects: the server hides unseen enemies with 0x90F.
- **Statics:** BlockEntities 0x53DA40 drops a static whose class cannot be built; 0x2E0005D6's .entity 0x2D0002E4 is
  only in 0xA00000B3.

### Obstacles, the meteor crater, the attack validator's checks (2026-10-21, fase3-ga)

- Dynamic obstacles are not in the NavMesh: the server blocks a box per prop (`[ics] prop_blockers`, half sizes
  along the placement's yaw = ics heading - pi/2) and frees it when the prop goes or a gate plays Object_Open.
- A child a scriptlet attaches (the meteor rock 0x2E000BB3 of `Vfx_Spawn_Event01` on crater entity 0x40000CAB) lives
  only while that scriptlet runs; to keep it, the server creates the world state as its own object.
- Attack validator VA 0x9d01d0 (champion, target, slot, ...): relation & skill mask (0x854a90 / 0x85f560),
  0x85d420, 0x85fb90, status tags 0x974940 (tables 0x15fe680 / 670 / 674), visibility (0xa9f220 component +0x5c),
  0x9cfaf0 (champion may act), unit flags (0xaa0dc0 component +0xa4, else 0x1000019D via 0x58d2d0) vs 0x8618c0,
  0x861910 / 0x9cfac0 (targetable), 0x9d0180(target, 0x82), 0x100001C3 via 0x513a90, 0x9cfaf0(target), range.
  `tools/diag.py --target` breaks after each one.

### The tutorial HUD, cinematic bindings and hiding, the vehicle's wreck (2026-10-22, fase3-gp)

- **HUD elements (UI ActionScript, `gameplay/common/BaseHudElement.as`, `mainhud/MainHUD.as`,
  `skills2/SkillsPanel.as`).** Each HUD element sets its visibility from the encounter type when it loads: a
  `Tutorial_Basic` encounter shows only `MissionObjectiveTracker` 35 and `HintManager` 32; `Tutorial_Intermediate`
  a longer list (objectives, vitals, conversation, character panel, minimap, W, portrait, XP, status icons, sector
  objectives, billboards, selection, player info, artifact slots, hints); every other encounter all. `0x213D`
  (`u8 0 | u32 element | u32 event | u32 highlight id | u32 highlight DID`) -> `RecvNotice_NotifyHUDElement`: event 1
  ShowElement (the first one plays the reveal animation), 2 HideElement, 7 ShowHighlight, 8 HideHighlight (all of
  the element's tips), 9 ShowArrowHighlight, 10 HideArrowHighlight, 3/4 tutorial mode, 11/12 open/close, 13 trigger.
  The skill panel takes the bar 14 and the buttons Q 9, W 17, E 25, R 12, passive 7, D 22, F 23, recall 43
  (`SkillControl.RevealElement`); the basic attack 6 and the upgrade buttons 30 / 4 / 28 / 5 / 19 are not handled by
  ShowElement, and a HideElement for any of them hides the whole panel (`BaseHudElement.HideElement`). Highlights are
  drawn only by elements whose class overrides ShowHighlight (skill panel by highlight id: Q 2, W 10, E 4, R 13,
  passive 17, D 3, F 16, "+" Q 15 W 7 E 11 R 12 passive 9; vitals 25 / Will 53; XP 24; minimap; objectives ...).
- **What the original showed when** (Part 1 video and the wAngel video, frames read at 5 s steps and zoomed):
  intro: nothing but the speaker portrait and chat; walk (0:42): champion portrait, minimap, objective, chat (no bar,
  no vitals, no XP); level 2 after the wave (1:33): bar with Q W E R at rank 0, passive (rank 1) and basic attack,
  yellow arrow over Q's "+" with "Click the highlighted button" (1:41); first Sonic Batarang (2:15-2:21): Will hint,
  health / Will bars under the bar with the Will bar framed; Catwoman's cinematic (2:25-2:40): HUD hidden, one
  Batman, the vehicle breaks and a red wreck stays (2:40, 2:50); after the pursuers (2:56): Experience hint and the
  XP bar under the portrait, framed; camera step (4:14): D button framed (3 charges), Skill Charges hint (4:25);
  E unlock (4:46): Skill Ranks hint; passive (5:10-5:15): arrow over the passive "+", Passive Skills hint; R (5:45);
  Super Strength (wAngel 9:28): F framed, Earn Stolen Powers hint; after the Destroyer's cinematic (9:55-9:57):
  Super Strength and moving hint, arrows over passive, Q, W, E. D and F are never shown before their steps.
- **0x20F5 fields (reader 0x878020; 0xa9cff0, 0xa9ceb0, 0xa9c490 read with the manager as `this`).** The manager
  keeps the message at +0x38, so manager+0x40 = bit5 bool, +0x44 = bit3 u32, +0x48 = bit4 u32, +0x4C = flags.
  `0xa9c490(1)` at the start runs only when bit3 != 0: for each world entity that is not a cinematic actor (motion
  flag 0x40 clear), it is hidden (property 0x90F = 1) when `0x10000B5B & bit4` (bit4 != 0) or `PerceivedType &
  bit3` (`0x9d0180`: unit component +0xA4 or property 0x1000019D); bit5 picks the entity list (factory +0x6C instead
  of +0x68). Cleanup runs it with 0 and the entities come back. Gaslight Batman's template has PerceivedType 8
  (Character), drones 0x10000 (Minion). Without bit3 nothing is hidden: the scene's own Batman ("player" actor,
  variable 1, needs_binding 0 in 0x35000034 / 0x35000033) stood beside the champion. Bindings: `u32 n` + n x
  `(u32 key, u64 IID)` (0x877E90 / 0x962AD0); with flags bit 1 the entry equal to the local champion gets key 1
  (0xa9c610); a bound actor takes the source's class and copies its visual component, and gets 0x8EE = the source.
- **The vehicle's break.** Catwoman's CinematicCharacter_State02 (table 0x1D0008C2, frame 146) spawns the wreck
  pieces 0x2E00135E / 5F / 60 (pack 0xA00000B3, tables 0x1D000916-918 whose only key is 0x5) on InvisibleTarget at
  offset 0; they are the cinematic's local copies and go with it. The DestVehicle world state 0x2E000AAB has no
  break of its own (table 0x1D000199: _ExecuteScriptlet / _StopScriptlet only), so the server removes it at the
  strike and creates the pieces itself.
- Open: the scene-script lookup (`Data.cinematic_scenes`) follows actor tables recursively, so 0x35000034 also
  starts the intro's scene 0x1D0007EE (script 0x3400058A) through Batman's table 0x1D000771 (its conversations are
  not sent; the director's queue waits for them).

### The play menu's map list: 0x2024, the query, 0x2101, JoinQueue (static analysis, 2026-10-22, fase3-go)

Tester 14:11: after Tutorial 1, Play -> VS Player / VS A.I. showed every map tile as 'undefined' (type Unknown,
match time undefined), the tutorials among the PvP maps, "Queues are currently unavailable" on some, Featured Maps
'undefined', and JoinQueue 0x20EB carried encounter 0 (`00000000 00000000 01 ffffffff`). The tutorial tiles had
worked before the match (the overview movie of 0x40000991 was played, which needs the template). (C = code read.)

- **0x2024** (exec 0x8B2970, serializer 0x846D40, handler 0xA733B0) stores into the encounter manager
  `[0xA12D50()+0x68]`: list<u32> DIDs -> +0x04, list<u32> queue flags -> +0x14, `u32 n x string` (cint length +
  chars) per-encounter access filter -> +0x34, list<u32> -> +0x24, u32 -> +0x70, `u32 n x string` account access
  strings -> `[0xA12D50()+0x54]+0x18C`, u8 -> `[0x1B77138]+0xAF`, wstr +0x1FC, wstr +0x200, u64 +0x208; sets
  +0x228 = 1 and raises the menu notices (0x916280, 0x897E90). The layout ics sends was already right (C).
- **0x20FF** UpdateEncounterInfo (handler 0xA734D0): the same four lists, applied only when +0x228 is set (after a
  0x2024); raises the same notices, so the Flash `EncounterManager` (`RecvNotice_ResetMapSelectionList`) queries
  again (C).
- **The query** `GM_Encounter.InqPVPEncounters` = 0xA68030 (`this` - 0x40 = the DID list). Per encounter: the filter
  0x86FD90 (empty access string = shown); `aPVPBlindPickEnabled` = flag bit 21, `aPVPDraftEnabled` = bit 17,
  `aPVPRankedEnabled` = bit 16; `aEncounterTypes` = 0x1000054E of the template (0x85E400: 1/2 Crime Alley, 3 GH,
  4 GD, 5 CC); then the template object 0x8535D0 (-> 0x4FDDD0 -> 0x478880: DB type 0x29 record `0x49 | did`); only
  when it loads: `aTutorialEncounter` (0x10000D0B == 4), `aIsBotMatch` (== 1), prev / next 0x10000B68 / 0x10000B66,
  players 0x10000BCC, teams 0x10000BCB, movie, lobby rules 0x10000C86. Names, images and texts come from
  0xA493E0 -> 0xA35FB0: template 0x100001D2 -> record 0x48...... (0x10000391 name, 0x10000392, 0x10000BDA /
  0x10000B8F / 0x100008D0 images, 0x10000383 / 0x1000039B, 0x10000C6D..C73 counts); an encounter whose record does
  not load is skipped there, so those arrays end short and the Flash reads `undefined`. FeaturedMap_PVP /
  FeaturedMap_BOTS: strings of the account game settings (0x218B, read through 0x86B5B0 on `[0xA12D50()+0x54]+0x60`),
  parsed with strtoul (C).
- **The tester's screen = templates that did not load**: type 0 (Unknown), no names, tutorials not flagged as
  tutorials (so in the blind-pick list), the 3 tutorials with flags 0 = "Queues unavailable" (they are the alert
  tiles on the last pages), and **JoinQueue's QueueKey 0x86E060 returns (0, 0) when the template does not load**
  (otherwise `did | 0x100000 for category 4 | 0x200000 solo, 0x20000 draft, 0x30000 ranked`: the tutorial's
  0x300000). The data is in the install (0xA00000B3 holds every 0x40 / 0x49 / 0x48 record involved), so the client
  could not read it at that moment: the menu built after the match. Why is not known yet (G: the query ran while the
  match's world / packs were being torn down; `tools\diag.py --encounters` logs each template load).
- **0x2101** queue eligibility (exec 0x8BABA0, serializer 0x845AC0, handler 0xA740D0 -> 0xA6AFA0 on the singleton
  0xA37BF0): `u8 0 | u32 level | u32 ranked capacity | list<u32> encounters (+0x1F8) | list<u32> (+0x208, same
  length; overwritten with 0xA292F0(encounter), 0 except Coast City) | u32 ranked minimum level | u32 draft
  requirement`. Ranked eligible = 0x10000BCC + [0x1866B8C] <= capacity; draft eligible = requirement <= value;
  meets level = minimum <= level; then UI.QueueEligibility (0xA5CD00) (C). Never sent before fase3-go.

### Practice targets, missile collision, launched entities (2026-10-22, fase3-go)

Tester 14:10: in Tutorial 1's practice_q the two practice targets (0x40000BA9, HP 1 from block 0x48000F6F) never
died; the Sonic Batarang's missile script logged EnableCollision and "missile gone" with no hit, basic attacks ran
their script and did nothing. Evidence from the decoded trees and the simulated tests:
- The targets have no side in the data (no 0x100007A2: the flow spawns them by class), so ics gave them **team 0
  (neutral)**. Two server-side filters refused neutrals: the missile collision test (`World._missile_hits`,
  `Missile._first_on_line`) passed only `hostile()` units, and CheckRelation / FindTargets refused relation 1 with
  `[ics] neutral_hittable = false`. The scripts themselves accept neutrals: missile 0x3400003F's collision
  transition T1 checks `IsKind 0x10108 + CheckRelation(Shooter, Target)[3]` (3 = enemy or neutral), the basic
  attack 0x34000037 graph S2 (on 0x10000126 from tracker 0x34000470) applies damage under
  `IsAlive + CheckRelation[3] + IsValid`. full-combat-skills.md 4.1: collision is the server's and the missile script
  filters by kind / relation itself.
- Now the server's collision test (`CastWorld.collides`) is: not the shooter's team, not DisableCollision'd, neutral
  only when hittable. **DisableCollision 0x1000006F / EnableCollision 0x10000070** (no fields) set / clear the
  entity's collision flag (DisableCollision stored 0 before: `_val` of a node with no field).
- The original objective ("press Q to destroy it with Sonic Batarang") and catalog 0x40000BA9: a practice target
  only takes the skill its step teaches; other hits play Superman's 0x1CD (basic attack) or 0x1DB / 0x1B2 (another
  skill). Nothing in the target's data (no 0x8E script but 0x34000600, the guide arrow) does it: the original's
  tutorial logic did (P), as the earlier server did (`only_slot`). The damage's slot is now known in the pipeline:
  the script's own slot, the launching skill's for a missile (LaunchMissile records it), the applying skill's for a
  status, the spawning skill's for an entity SpawnEntity made.
- **Sonic Shell** (W, 0x3400003A) spawns the shell 0x40000093 (script 0x34000042) and launches that entity: the
  shell's script goes S0 -> S5 on 0x10000049 and S5 -> S4 on 0x10000049 again, then explodes (S4 -> S2,
  FindTargets 0x610109 mask 7, damage under CheckRelation(ShooterIID, target)[3]) on 0x10000035. So a created
  entity's scripts get 0x10000049 when it is created and again when launched (with 0x100000EE and ShooterIID), and
  0x10000035 when its flight ends; it stays where it lands until its own DestroyEntity(SELF). Before, nothing raised
  those events on a launched entity and it was removed on landing: W never exploded.
- Open: **Super Strength** (F, 0x34000164) on the tutorial's vehicle (world state 0x2E000AAB) raises 0x10000037 on
  the vehicle and waits for 0x100000BB; the vehicle has no 0x8E scripts, so the handler is elsewhere (its world
  state's throwable component / scriptlet tables, not found yet). The step ends when its drones die any way.

### Findings while building fase3-gm (2026-10-22)

- The champion pick is **0x20E4** (builder 0x87a770, sender 0x889150); 0x2102's only builder caller is the custom
  match SetDraftMode (constant 0x20000). 0x2004 = u32 room | SP1 | SP2 | u64 player; in 0x2029 the u32 after
  "locked" is the room and the last two u32 the Stolen Powers; 0x204C keeps teams only with queue flag bit 17.
- Encounter templates: 0x10000BCB players per team, 0x100004A1 select time; 0x10000463 = array of {0x1000045F f32
  team health, 0x10000460 team}; 0x1000021C is f32 (600.0). Unit stats per level come from table 0x1000031A
  (minions 500 + 10 / level, structures 2 550-6 000); formula records 0x3B: `did|1|1|n|types|defaults|1|0|n|
  (hash, slot)|names`.
- Skills: event 0x10000008 makes a skill load its stats (without it some basic attacks did 0 damage); the last value
  of LoadSkillStats / InitSkill is the slot whose stats are read (-1 = own); 0x100000EE carries a missile's target;
  StartVitalOverTime's last value is the damage type (0 = heal); instant skills without a Cast node wait for codes 3
  and 5. The client's vitals reader 0x96D3F0 keeps only the second word of the long form.

### The whole client decompiled (2026-10-22, no build)

Ghidra headless decompiled all 60 529 functions of InfiniteCrisis.exe (and the launcher / game DLLs); JPEXS
exported the UI's ActionScript. Seven subsystem notes and their index: docs/re-notes/full-index.md. Key results:
entities are 0x120-byte structs with 64 component slots whose creation is gated by PerceivedType 0x1000019D (mask
0x7F59FB for vitals / floaty / status icons), mobility (creation types 7, 8) and 0x7D2 / 0x954; graph events are
dropped while entity flag +0x118 has 0x40 without 8; the client has no gameplay logic for structures, capture points,
the Device or pickups (all server-side); the scoreboard is notice 0x1000005B, the kill feed 0x217A, surrender
0x10000454-456, the match clock 0x10000109; 441 events with 306 field layouts confirmed (full-protocol.tsv);
frames are plaintext; every missing script node has a spec (full-combat-skills.md), with bugs found in ics (0xC is
x - 1, CheckRelation masks, vitals above 16383, unstarted timers count as expired). Conflicts between the notes are
listed in the index.

### Client subsystems decompiled (REA / Ghidra, 2026-10-22, fase3-gl)

Four notes in docs/re-notes/ (addresses, formats, C/P marks): **client-movement.md** (the server drives every
position, champion included: replay module 0x15C6360, 9-state history, dead reckoning, 2 m snap; stop = an explicit
speed-0 state; teleport = seq A + 1; order gates), **client-status-effects.md** (crowd control is bool unit
attributes read through 0x974940 / 0x973730: Stunned 0x100003F3, 0x10000B2D blocks every order, Rooted 0x100007FE,
Crippled 0x10000B39, Silenced 0x100005A3; effect events 0x200F / 0x2043 carry script instances; stun / knockdown
records 0x48000293 / 0x48000295 / 0x48000296), **client-scriptlets-graphs.md** (0x8D pipeline 0x634F20 ->
0x6279D0, table merge 0x525690, action registry 0x669CE0; 0x100001E3 raises graph events with no gate; 0x204E /
0x2008 raise script events; `_Defeat_*` scriptlets are server-sent), **client-cinematics-matchend.md** (0x20F5
format and flags, the only notice back 0x10000117, VICTORY before 0x1000000E, post-match movie property 0x10000C1B
gated by 0x2045 and User.HasSeenPostEncounterVideo, scorecard bundle, trainee achievement 0x40000B08 in 0x2120,
0x214B unlocks Tutorial 2).

### Small meteors and the crater's lava (2026-10-22, fase3-gi)

The crater world state 0x2E0004BE alone shows broken cobbles; its only scriptlet, `Vfx_Active` (table 0x1D000155),
adds the lava meshes 0x2E001060 / 0x2E001061 (alone they showed as a flat red disk). The rock 0x2E000BB3
(`Vfx_Event1-3`, `Vfx_Spawn`, `Vfx_Spawn_Alt01`) falls and lands with its own graph when created: the small
meteors are that rock at scale 0x6B4 = 0.3. The objective banner (field 0x1000000) and hints 16 / 17 / 18 / 34
show in the client (tester's video 10:00).

### Tutorial 1 as the original played it (two gameplay videos, 2026-10-22, fase3-gh)

Two recorded playthroughs of the original (the whole tutorial, intro to the reward screen). Order of the objective
banners, groups and counts: identical to `ics/encounters/tutorial1.py` (2 pursuers, 3 around Batman, 3, three
groups of 4, Bat Flight, Bat Scream 3, camera centre / lock, Super Strength, reach and defeat the Destroyer, the
power core cinematic, VICTORY, then a client motion comic and the reward screen). Details the server lacked:
- A smaller meteor lands beside Batman two seconds into the first walk; the big one behind him at the first marker;
  one more just before the wave's two drones, which appear with a spawn effect by the vehicle and walk at Batman.
- The crater stays as red lava cracks in a star on the cobbles.
- The first drone fights the human (who runs off) and only fights Batman when attacked.
- The objective text is drawn at the top centre with its counter: the objective's banner field (0x1000000), which
  the earlier server set and `ics` did not.
- Tutorial hints (bottom left) appear through the tutorial (guide arrows while walking to the second marker, basic
  attack with the wave, experience and skill points at the first level, Super Strength ...).

### Conversation finished 0x2140; the crater pieces (2026-10-22, fase3-gg)

- Tester 09:13: the drones can be attacked (fase3-gf: bools 0x10000029 / 0x10000249 on the target), the flow reached
  the Q unlock.
- **Client event 0x2140** = `u32 instance`: sent when a conversation started with 0x2001 has played, one per
  instance, in order (09:14:08 0x1BA instance 1 -> 0x2140 1 at 09:14:11.9; 0x19C 7.8 s against the catalog's 11.5 s).
- **The meteor's crater** (meshes 0x170001D0-D2 of `Vfx_Spawn_Event02`) is three world states in pack 0xA000024C:
  0x2E0002F8 / 0x2E0002F7 / 0x2E0002F6 (`did | 2 | 0x2D000063 | 0 | 4`: 0x1EB = the mesh, 0x50F = 3, 0x7EB = 1,
  0x4A8 = 1). This header-2 form (like header 7) was not read before. **0x2E000375 is a roof**, not a crater (the
  survey notes that called it a crater mesh were wrong; tester's video 09:13).

### Status tag checks of the attack validator; conversations a cinematic plays itself (2026-10-22, fase3-gf)

- diag 08:57 (`--target`, grouped lines): with unit flags 0x10000 the drone failed "status tag check B". In the
  validator esi = caster, edi = target. The tag checks call **0x974940(entity, &otherIID, &tag, default)** ->
  the entity's unit component (0xaa0dc0) -> **0x973730**: the component's value of the tag (a property id; vt+0x60),
  overridden per other IID (hash at +0x10) or per the other's team (table +0x30, count +0x38; team from
  **0x854050** = unit component +0x4c or PVP_Team 0x1000009C), evaluated by 0x96d460; with no value the default.
  Tags (dwords at 0x15fe670..0x15fe680): check B **0x10000029** (target, default 1), check C **0x10000249**
  (target, default 1), 0x10000642, alive check 0x10000B2D (default 0), check A 0x10000B4A (caster, default 0).
  The tutorial drone template 0x49000C72 has 0x10000029 / 0x10000249 / 0x10000B2D as `key | 0x5... | ref`
  entries (references the original server resolved), the generic 0x49000A5C and the client class 0x48000168 = 1.
- The right click: hover pick 0 on the drone (the pick scores only what the validator accepts), interact check
  0x9d0490 = 0x1000001A, validator 0 -> move order.
- Conversations: 0x2001 handler -> CDialogSystem (vtable 0x1604DFC: +4 0xa67670 = 0x2047, +8 0xa7ff20 = start).
  Start: 0xa13c90(entity, source, key) (source 1 = the encounter's table [+0xF8], else the entity's), then
  0xa77ae0 -> instance 0xa62dd0 (+0x34 the u8: queue it, 0 = dropped; +0x35 always 0 from 0x2001; +0x38 instance),
  queued at [+0xA0]. The tester's video showed each intro conversation twice and the later ones once: the cinematic
  plays its own conversations, so the scene script's copies (sent by the server) queued behind them.
- The crater the intro shows is the map's crater static 0x2E000375 (broken cobbles over lava); after the strike only
  a flat red disk and the rock stayed.

### The right click's order, the meteor's crater, conversation instances (2026-10-22, fase3-ge)

- diag 08:39 (`--target`): with the unit flags sent as event 0x6 (fase3-gd) the attack validator ACCEPTED targets from
  the moment they arrived (08:40:11); before, every drone was refused at "unit flags = 0". The client still sent only
  move orders (0x20EE command 4) and four command 6 (stop). The order decision **0xa86a00**: hover pick 0xa81b30 at
  0xa86a42 (result -> IID at entity +0x100, looked up again through [0x1b67258] vt+0x58); then **0x9d0490**
  (interact check) at 0xa86b0c: with the "may interact" argument, a result of 0 gives command 1 (0x96fdf0) or 6 when
  byte [this+0x110] is set, a result of 0x10000031 gives command 6; then, with the "may attack" argument and byte
  [this+0x110] clear, **0x9d01d0(champion, target, 0, 0, 0)** at 0xa86bb3 gives command 2 (9 with [this+0x113]);
  otherwise command 3 / 4 (move to the ground point). `diag.py --target` now breaks at the pick result 0xa86a47, the
  interact result 0xa86b11, the validator result 0xa86bb8 and the order sent (0x88b030), and folds each validator
  call into one line (the hover loop over the props used up the 3 000-line budget before the drones existed).
- The meteor (table 0x1D0008B6): `Vfx_Spawn_Event02` attaches the crater meshes 0x170001D0-D2 and runs `Vfx_Active`
  itself. A scriptlet sent afterwards replaces the running one, and its attachments go with it, so the server's own
  `Vfx_Active` left only the fire.
- 0x2001 handler 0xa13b90 calls the dialog system ([0x1b758d4]+0x1C) vt+8 (entity, u32, key, speaker list, u8, 0,
  instance, time limit -1.0); 0x2047 calls vt+4. The dialog system's update 0xa89c40 (profile name "CDialogSystem")
  walks its active conversations and calls 0xa83b10 / 0xa7fad0 on each.

### Setting one property: event 0x6; team colour override (2026-10-22, fase3-gd)

Event 0x6 (also 0x7 / 0x13B) carries `u8 0 | one property entry` (the same entry as in a property table: u32 id,
packed id, value). Serializer 0x445530 (0x509740 reads the value, 0x5015f0 when packed); handler 0x635360 takes the
object's property collection [obj+0x38] and runs vt+0x10 (begin), vt+0x50 (set the value), vt+0x14 (commit), the
change path the watchers listen on. A second full bundle (fase3-gc) did not change the unit component's cached flags
(diag 08:13, still 0). The colour: when PVP_Team changes, 0xa7b0d0 takes 0x10000CF0 if non-zero, else the relative
colour (enemy 5 = red); the generic drone template 0x49000A5C has 0x10000CF0 = 1, the tutorial's 0x49000C72 has
none. The intro cinematic's scene script 0x3400058A starts conversations 441 (0x1B9), 559, 558, 557 and 556, one per
timeline event (a skipped intro only gets the first).

### Unit flags must arrive as a change (2026-10-21, fase3-gc)

`diag.py --target` (breakpoints after each check of the attack validator VA 0x9d01d0) showed every network unit
refused at the unit-flags check: 0xaa0dc0 returns the unit component and its cached flags +0xa4 were 0, although the
creation table carried 0x1000019D = 0x10000. The component's watcher (registered at attach, notify on change) only
updates the cache on a change, so the server sends the flags in a later bundle.

## Tutorial 1 visuals against the original video (2026-10-22, fase3-gq)

Compared frame by frame with the Part 1 walkthrough (0:00-6:05) and the wAngel video; static data read with
`ics.gamedata` (tables dumped key by key: action `0x17 1 0 <key>` = run another key of the table, `0x11 <0x18...>` =
particle, `0x18 0 0 0 1 1 1 0x617 <hash>` = the FX template held in a script variable).

- **Guide ring.** Script `0x34000600` keeps its six FX templates as state locals (pack `0xA00000B3` at `0x178BE3C`, after
  the S0 locals' type words `8 4 4 4 4 4 4 0 0`): AlertPing `0x1E00055D`, GroupPing `0x1E00055E`, AlertArrow `0x1E000511`,
  GroupArrow `0x1E000510`, AlertDestructiblePing `0x1E00055C`, GroupDestructiblePing `0x1E00055B`. S0's exit picks
  Group or Alert by `0x10000B97` (UseAlert) and the destructible variant by unit flag `0x1000`; S1 runs
  `RunScriptlet(SELF, 0x10000F86, 0x1000050A = ping FX)` and `RunScriptlet(agent, 0x10000F80, 0x10000559 = target
  position, 0x1000050A = arrow FX)`. Vfx_GuideArrow and Vfx_GuideArrow_Ping have the same body (`0x18`: play the FX
  template in variable `0x1000050A`, property `0x617` kind did). The marker `0x40000A9C` (tables `0x1D0006E2`,
  `0x1D0007A9`, ws `0x2E000002`) has Vfx_GuideArrow but not _Ping, so the server plays Vfx_GuideArrow on it with
  `0x1000050A = 0x1E00055E` (the green ring, video 0:43) and on the champion with `0x1E000510` (the chevrons).
  Without the variable nothing showed (the fase3-gp traffic: no ping sent, the marker's table filtered it).
  `0x1D0006E2`'s Vfx_Spawn_Alt01/02/03 (particles `0x18001019` / `0x18001012` / `0x18001030`, then Vfx_Active_State1-3)
  are the player map pings' ground effects. The practice target's template `0x49000BA9` carries `0x8E = [0x34000600]`
  with IsActive `0x10000B94` = 1 and UseVFX `0x10000B96` = 1: its ring and the arrow show at once (video 1:53-2:05).
- **Spawn-in.** The drones' table `0x1D0002F8` (`0x1D0002F9` ranged) `_Entity_OnEnterWorld_Default 0x100002F5` runs
  Vfx_Spawn (`0x1D0002F7` / `0x1D0002F6`): particles `0x18000B56`, a colour fade (`0xFF8FBEEF`), the ring mesh
  `0x1700142A`, particles `0x18000B58` = the purple ring at 1:18.4 and 3:55.5. The practice target's ws table
  `0x1D000862` has the same key (yellow glow at 1:52.5). The server played only `_Entity_OnSetClientRelationship` 1 s
  after creation; the units now get `_Entity_OnEnterWorld_Default` 0.1 s after their bundle.
- **Meteors.** Only the first big strike (0:52) leaves the lava crater. The walk's (0:44), the wave's (1:15, ~1.5 m
  from Batman toward the vehicle) and the bridge ambush's (3:57, among the drones) are: rock, a ~1 s fire column,
  a dust cloud, small red rocks left. Table `0x1D0008B6` Vfx_Active (particles `0x1800024B`, `0x18000E6A`,
  `0x180002D1`) is the column and loops; Vfx_Spawn_Event02 attaches the crater meshes `0x170001D0-D2`.
- **Burning vehicles of the intro (not solved).** The intro's first camera (track `0x10000012`, (107, 35.5) -> (93,
  32.5)) looks at map statics whose tables run key `0x5` -> Vfx_OnInit = fire particles `0x180000DE` / `0x180000DF` /
  `0x1800014C` / `0x1800009A` + an orange point light: wagons `0x2E00034B` (79.3, 26.9) and `0x2E00034F` (105.4, 22.8)
  (`0x1D0000BC` / `0x1D0000BF`), carts `0x2E001219` x6, `0x2E000124 / 127 / 128` (`0x1D0000A6`), `0x2E00026B`,
  `0x2E00026D`, `0x2E000248`, `0x2E00036A-36C` (`0x1D000093`: particle `0x18000113`). They are client-built statics
  (BlockEntities `0x53DA40`); what starts their key `0x5` on the client is not traced. The type-3 emitters along the
  same road (`0x2E001115-0x2E001140`, `0x2E0010D2`, `0x2E000625`) are absent from the install and cannot be built.
- **Bridge ambush.** The three drones spawn in at the closed gate `03GateA` behind Batman (3:55), not ahead of him.

## In-match camera, range indicator, vision (fase3-hd)

- Camera yaw: f32 0x1000011E (degrees) on the followed champion (local player's 0x100005E8 link), read by the
  isometric camera's start 0x96A930 (0x96AABF) and watched (0x968F30 -> 0x9677F0); heading = -yaw, 0 looks along +y.
  Crime Alley's intro ends on heading 0, Tutorial 1's on 45 (docs/re-notes/pvp-camera-yaw.md).
- Range indicator: client nodes 0x10000056 (show, 0xa5dab0) / 0x10000022 (hide, 0xa4f0c0) in the client targeting
  scripts, hidden on 0x1000001D / 0x10000009, which only S->C 0x20C9 delivers
  (docs/re-notes/targeting-indicator-and-structures.md).
- Order check 0x9d01d0 on structures: 0x10000249 and 0x10000029 = 1 as base + attribute modifiers.
- Vision sources (0xAB12C0, 0.4 s): allies whose flags 0x1000019D match 0x1F4978 and whose 0x10000133 (stored only on
  a change, default -1) is positive; the client hides enemies itself only under attribute 0x100007C0 and rewrites
  0x2A1 every 0.4 s (docs/re-notes/fog-vision-runtime.md).
- Script VM (champion-kits-status.md): RaiseEvent (0x1000006B) values [event, script DID]: a non-zero script DID
  targets only that script's instances on the entity; IsInRangeAndAngle (0x10000052) limits the distance only when
  its max operand is set; a template's 0x8E script list may sit past interior "record starts" of the pack.
- Crime Alley scenery the server creates (crime-alley-missing-elements.md): base gate Door 0x40000557 / 0x2E000CD7
  (table 0x1D000461; Object_Closed -> light wall 0x2E000CD8, team colour), base aura Base 0x40000C7F / 0x2E000A35
  (Hotspot_Activate, radius 0x100002AA = 6; in-base status 0x48001109 / script 0x340006C1, leave 0x48001107 /
  0x340006C0). The statics of the three landblocks resolve in the packs we send; 0xA000009A is not needed.
- Skill visuals (skill-animations-and-skins.md): the client never plays a cast from the skill record; client copies of
  0x34 scripts (created by 0x200F / 0x200C, driven by 0x20C9) have client halves for RunScriptlet 0x9CE2E0,
  StartScriptlet 0x9CE300 and RunFx 0xAB7620 (both set variable 0x1000050A = fx record), RaiseGraphEvent 0x9CE1C0;
  TargetHit has none (0xAB4D80). A 0x8D key is looked up in the instance's 0x7D2 tables and their bases recursively
  (0x58EDD0, 0x5235C0), with no costume -> base fallback; a missing key drops the run silently. 0x20AF loads each
  listed champion's parent pack itself (0xA99370 via 0x20ED metadata 0x866480) and value[0] of that metadata
  (0xA99460 / 0x866420; ics sends 0xFFFFFFFF). Action field 0x617 (fx record) binds variable 0x1000050A.
- Shop build timing (fase3-hh): the catalogue (0xa908f0) is built from a hook on 0x69bd90 (key-4 "local player ready"
  broadcast, only caller 0x64dac0) instead of inside the 0x20AF handler, which hung the second match of a session.
- Client copies of skill scripts: ics sends 0x200F per kit slot script on the champion at load complete
  (`skill_script_mirror`); diag --scripts showed every server 0x8D accepted (result 0) yet no visible skill animation.
- Second match of a session (second-match-load-hang.md): the world teardown 0xa99b60 -> 0x7d14b0 -> 0x635250(0, 0)
  clears the local player IID [0x1b6a710]/[0x1b6a714]; 0xEB (0x64b2e0) must come again before the next match, or
  0x64dac0 never finalises the player as local and the 55 % step 0xa0a570 (0xa964b0(0x14)) never runs.
- Script instances by network (client-skill-instances.md): 0x200F / 0x2062 / 0x200C / 0x2043 all go through 0x838F80
  -> default ctor 0x44BD00 -> 0x461510 -> 0x448BE0 with a null record: an access violation in this build, never send
  them. The client builds each slot's instance from skill property 0x1000063A (aiming-decal scripts) at HFSM start-up
  (0xA9F9F0 -> 0x979860 -> 0x9789C0); 0x20C9 reaches those. Graph events from 0x8D: action 0x672930 needs the
  behaviour-graph component [entity+4]; 0x55BD30 drops the event when entity flags +0x118 have 0x40 without 8,
  queues it while the graph is not ready, delivers through 0x55AF70 (0x5590E0 = -1: event unknown to the graph).

## Skill graph runtime: cast signals from the champion's own behaviour graph (2026-10-27, fase3-ia)

Full analysis: docs/re-notes/skill-execution-model.md (C = read in code / data, P = probable).

- **Where the cast signals come from (C pipeline, P server)**: every skill state of a champion graph carries
  `turbineEventHookPayload {didTargetHFSM @0x14, eEventHookType @0x18, vMissileOffset @0x20}` (class 0x1D09950, ctor
  0x1173210, payload kind 0x10000001) on its enter / exit notify events and clip triggers. The animation-event handler
  0x878680 -> 0x85D5B0 -> hook bus 0x85B750 / 0x877B00 -> effects component 0x973C20.. -> 0x9723D0 builds event
  **0x1000000F** with parameter **0xC58BA9B = hook type** (1 SkillStart = enter, 2 SkillEnd = exit, 3 Skill, 4
  MissileInit, 5 MissileFire; 6 SkillHold is never registered) and **0xA2103E4 MissileFireOffset**, posted to the
  instances with the payload's DID (all instances when 0). The client hosts no cast-script instances, so on the client
  it reaches nothing; the original server ran each champion's graph and its scripts got OnCastSignal from it.
- **Code 2 = the graph left the skill's state** by any route: its own trigger (skill_to_cosmetic /
  skill_to_locomotion), a stage chain's end, a CC / death / other-skill wildcard of the main machine. Stage hooks fire
  only once their sub-state is entered; gates are graph events the scripts raise (RaiseGraphEvent: 42 own script, 7
  another script, 4 through scriptlet keys run by a script, 3 with no raiser found; tools/skill_graphs.py census).
- **Data** (tools/skill_graphs.py -> data/skill_graphs.json, 56 graphs for the 156 variants): per graph its top
  machines and every machine (start state hkbStateMachine +108 P, states +144, wildcards +156), state info (+40 enter
  / +44 exit notify arrays of (event, payload), +48 transitions, +52 generator, +56 name, +60 id), transitions (60 bytes:
  +36 hkbExpressionCondition, +40 event, +44 target, +58 flags: 0x20 disabled, 0x200 allow self, 0x400 / 0x800
  global / local wildcard), clips (hkbClipGenerator +96 animation, +116 start time, +120 playback speed, +124
  enforced duration, +134 mode, 1 = looping; triggers 16 bytes: local time, event, payload, end-relative byte;
  playbackSpeed bindings to Property_Attribute_AttackSpeed), blends (layers with state machines all run; among clip
  children the first with triggers), Lua early-outs. Event names resolve through the 0x300000A4 table, which
  `rp.name_tables` returns in several runs (Batman_Gaslight_Bat_Scream 0x100000E7 and Basic_Attack_Left 0x100000F4 sit
  in a run of their own). Scriptlet keys' graph events are the type-0x14 actions of their table entries: `0x14 | n
  bindings | n x 4 words | 0 | 0 | 1 | f32 1.0 | jitter | intensity | time | event` (Gaslight Batman:
  Combat_Basic_Attack_Left 0x10000196 -> Basic_Attack_Left, Batman_Gaslight_Bat_Scream key 0x10000162 -> 0x100000E7).
- **Accept lists (C)**: each script record's top-level field 0x44AF56 (count) + 0x44AFBF (event ids) is the sorted list
  the client VM checks (0x461430); it equals the events its triggers name for all 875 scripts. Batflight 0x34000038
  accepts no 0x1000000F (it runs on dash events).
- **0x20EA (C)**: `slot | count | class 1 | event | has-params 0`; 0x10000023 "targeting begun" from 0xA26420 for
  every non-instant slot, 0x10000009 "targeting cancelled" only for skills with bool 0x10000A46 (Green Arrow R).
- **ics (`[ics] graph_runtime`, ics/graph.py)**: a GraphInstance per champion (local and bots), fed by every 0x8D the
  server sends (0x100001E3 + 0x780, and the keys' type-0x14 events), delivering hooks through
  script_runtime.deliver_hook (DID routing, accept list). Clip durations are not in the data (the animation-name ->
  0x1A clip link is made by the client loader at run time): end-relative triggers use an assumed length
  (`graph_clip_seconds`) and a gate the state cannot take yet completes such an estimated self-transition first.
- Measured with tools/champion_check.py --all (new sequence verdicts OK / SIG / HANG / EARLY2): see CHANGELOG fase3-ia.


## Object kind flags in scripts; bundles drop running scriptlet spawns (2026-10-28, fase3-ib)

- `IsKind` (0x10000029) tests the entity's kind flags, the unit flags 0x1000019D (client 0x9cfbf0: attribute component
  `+0xA4` or property 0x1000019D). Map objects carry their own: Crime Alley's meteorites 0x22, vehicles 0x1080. Consume
  (Stolen Power 0x48000815, script 0x340001C4) ends its S1 with `if IsKind(Target)[0x82]: DestroyEntity(Target)[0.3 s]`,
  so it eats a meteorite (bit 0x02) or a vehicle (bit 0x80); before, ics only knew the unit / champion / prop /
  missile bits and the object stayed (C script tree, P effect in game).
- Grab's beam (diag `--brazo`, 2026-10-28 09:33): the beam action 0x673280 resolves its target (q[ebp-0x28] at
  0x67338E) to AGL's own IID for both beam actions of each cast, so the beam binds to the caster; why it does not draw
  is open (docs/re-notes/grab-beam.md).
- A full object bundle (the champion's "faces the target" before each basic attack) re-creates the object on the
  client and drops what its running scriptlets had spawned (the Shards of Will sphere), which the next
  `scriptlet_restart` resend brought back (tester: "the shield disappears while attacking and returns after"); the
  looping keys now go again right after the bundle (P).
- Grab's arm (docs/re-notes/grab-beam.md, C data): the missile's Vfx_Active type-2 action has width 0 and no caps; it
  emits particle 0x18000752 along the line from the missile's attach point 0x10000039 to AGL's 0x1000007C, re-resolved
  every frame. A full object bundle re-creates the missile and drops the run, so a missile now gets bundles only when
  its course turns (P).
- Stealth (docs/re-notes/stealth-rendering.md, C code): 0x100007BF appears nowhere in the exe and node 0x1000011E's
  client execute is a bare `ret`: both are server-only. The owner sees the champion's Vfx_Status_Stealth_Active
  0x10000648 (table 0x1D0000E1, particle 0x18000504); enemies stop drawing an entity when its property 0x90F is true
  (listener 0x624490 draws only with 0x2A1 && 0x76A && !0x90F). The tiles' purple is their Vfx_Active particle
  0x18000A57; the hex mesh 0x2E000D37 alone is tinted grey (0x7D1 = 0.737).
- FaceTarget's full bundle re-creates the champion object on the client (and drops what its running scriptlets
  spawned); a standing champion already facing its target gets none (fase3-ic, P).
- Call for help (fase3-ic, P from the AI data's retarget interval 0x3A000026): a champion hitting an enemy champion
  makes the victim's allied minions and structures re-acquire immediately; structures take the aggressor only within
  their reach.
- Crime Alley's black socket at x 40 / 120 (docs/re-notes/map-load-holes.md, C data / P conclusion): no asset is
  missing (every record goes through resolver 0x43CE00, which returns 0 silently on a missing DID; all Crime Alley
  terrain, statics, materials and textures are installed). The landblock's terrain record 0x800113BB puts the
  vertices (40, 75), (40, 80), (120, 75), (120, 80) at 179.96 m (the off-lane level under the buildings) inside a
  199.98 m street, with normals tilted into the pit: the hole is in the terrain heights. The server cannot send heights;
  diag `--mapload` / `--mapa` logs what the client loads and fails to find, and `--mapa-rellenar` lifts the four
  vertices in the running client's memory as an experiment before a permanent exe or pack patch.
- Permanent terrain-socket fix and the audit of every map (fase3-if, docs/re-notes/map-audit-all.md, C): record 0x80 =
  (unpack 0x5490D0) DID | +0x30 flags | +0x3C u16 heights (record +0x450) | +0x48 render block (palette 0x53F4A0, read
  exactly `count` entries: a batch layer index past it takes heap memory, as on CA 12BA / 12BC; batch = n | indices |
  first index | triangles | first vertex | vertices | bbox | mask | material | 15 words) | +0xC4 normals (record
  +0x81F8 on 13BB, +0x800C GD 1BD3, +0x8C9C CC 23E3) | z max / min | embedded Havok hkpMoppCode | LOD-1 byte (0 on these
  maps) | ... | +0x1B0 statics DID. 0x712860 builds the render mesh with no special case for height 0. `python ic.py
  patch` raises the black sockets (CA (40 / 120, 75-80), GD team 1's three lane exits (team 2's and the pits optional:
  see "Terrain sockets in the map packs" below), CC's 3 x 3 centre) to
  the street around them in the packs and levels their normals (`icserver/terrainfix.py`, `[game] terrain_sockets`).
  Terrain layer types are the 42-entry table record 0x07000000 (`0xA0000038` dec. 0xDBBE8: type id | name | texture A |
  B | uv | projection | texture C ...); 0x1300008C is the grid of types 0 / 1 / 0xB (Tutorial 1's zone pack only; CA's
  six outer blocks use it, outside the play area). Gotham Divided's asphalt types 0xE / 0xF (0x130007AC / AB / AA / A9)
  are in none of GD's packs.

## Ultimates against an enemy champion: VM fixes (2026-10-28, fase3-ic)

Measured with `python tools\champion_check.py --vs-champion --window 5` (every slot also cast at a real bot champion
2 m away, `World.create_bot_champion`); `--press-event` sends the client's 0x20EA 0x10000023 "targeting begun" before a
non-instant cast and `--recast 1` presses the key again 1 s later at the bot when a graph out of its idle S0 waits for
0x1000001D (a release / second stage). Causes found (C = seen in the script tree / data, P = assumption):

- **Graph hooks inside a state's chain** (C): Bullseye 0x3400040C S1 raises graph event 0x100003BF before
  `StartTimer(ShootTimer)`; ics' graph runtime answered with hook 1 synchronously and re-checked S1's transitions with
  the timer still unset (= expired), so the draw cancelled itself (S1 -> S4) in the tick it began. The same pattern
  made Arcane Zatanna's Runic Gate W explode at once instead of after its 5 s rune. A hook raised while the instance
  runs a chain is now delivered when that chain has run (`script_runtime.deliver_hook` / `Chain.run`,
  `[ics] defer_graph_hooks_in_chain`).
- **RaiseEvent parameters** (C): receivers read slot 2 as `Position` 0x6A0AB2E (TargetPosition, DashTargetPosition) and
  slot 3 by type: Bool 0x4965C (crit rolls), 0x5A05762 (handles, counts), **0xD358722 numbers** (Damage of Green
  Arrow's four arrows 0x3400043D..440, BonusShield 0x3400053A, HealthDelta 0x34000583, DamageMultiplier 0x340007C9,
  NewDamage 0x340007D0). 0xD358722 had been filed under slot 2, so the arrows read their record default (5e-31).
  `RAISE_PARAMS` slot 3 = (0x5A05762, 0x4965C, 0xD358722) (`[ics] raise_event_float_param`).
- **IsKind bit 0x100** (C): the data writes champions explicitly (`0x108`, `0x10108`, 137 uses); the arrows test
  `IsKind [0x10100]` (the minion hit, S8) before `IsKind [8]` (the champion hit: thermite + full damage, S1). Bit
  0x100 no longer matches champions (`World.kind_matches`, `[ics] kind_unit_excludes_champion`).
- **ApplyDamage(0) as a probe** (C): 0x3400043D / 0x34000453 / 0x340004CF / 0x3400077A apply `$ZeroDamage` and deal
  the real hit only when DamageSuccess holds; a zero hit on a live, damageable target now reports success without
  damage (`[ics] zero_damage_probe`).
- **Once-per-tick guard of polled transitions** (C): Dex-Starr's Shred The World cat 0x3400072C hit a minion, and the
  champion it met 0.05 s later was skipped because the hit transition S3 -> S6 had fired within half an update. An
  event-triggered transition of the same graph since then lifts the guard (`Region.check`, `_event_epoch`,
  `[ics] poll_guard_event_reset`).
- **Box hotspots are centred** (C): every shape-2 hotspot is placed at its length / 2 (Tempest 0x340002C8 at SkillRange
  * 0.5, Mecha WW's W 0x340002CA at start + offset / 2, the beams of 0x340005AB at start + BeamLength * 0.5); ics read
  the box as 0..length from the position, so Tempest's started 5 m past her. `Hotspot.contains` (`[ics]
  hotspot_box_centered`). Node 0x10000025 with a hotspot in operand 3 (`[1 0 ..]`) moves that hotspot (`[ics]
  hotspot_follows_position`), and a state with an update chain left by an event runs that update first when it has
  not run in this tick (the W box stopped 1 m short; `[ics] update_before_event_exit`, P: client update order).
- **Missiles after their expiry** (C): The Joker's Last Laugh balloon 0x34000118 goes S2 -> S3 on 0x10000035, explodes
  in S1 after DelayTimer and only then DestroyEntity(SELF); ics removed the missile and its script at the expiry. A
  missile whose script is out of its idle state after the expiry stays (no more collisions, `expired`) until its own
  DestroyEntity, at most `[ics] missile_expire_linger` s.
- **Hotspot status A duration** (C): Arcane Zatanna's aura status 0x3400064C computes `TotalDamage / EffectDuration`
  per second; status A (held while inside) got EffectDuration 0 -> no damage. It now gets the hotspot's remaining time
  (`[ics] hotspot_status_duration`).
- **32-bit integer equality** (C): Rao's Wrath 0x3400054D fills its charges when `CurrentCharges == 4294967295` (its
  record default); the constant is a signed int (-1), so the R could never be cast (T7 needs charges > 0). `==` / `!=`
  on two integers compare their 32 bits (`_same`, `[ics] int_compare_32bit`). Its missile 0x40000AE5 has no template
  script; orphan 0x34000562 loads slot 4's stats 5 / 18 from the shooter and raises 0x10000141 back on script
  0x3400054D (C), so `[ics] spawned_class_scripts` binds it.
- **AIMoveTo on a champion** (C node use, P arrival event): Reclaimer 0x34000253 S1 runs at its target with
  `AIMoveTo(-, MaxDistance, TargetIID, SELF)` and strikes in S2, entered on 0x1000009D; `CastWorld.ai_move` ignored
  champions. It now chases the unit and raises 0x1000009D on the champion's scripts in reach (`[ics] ai_move_champion`).
- **Top-level graph chains** (C): 69 scripts have an enter / exit chain on a top-level graph node (Star Sapphire's
  Predator brain 0x340003D1: `GetCreator($StarSapphireIID)`, LoadSkillStats); the runtime only ran nested graph
  states' chains. They run at instance start (before its first state) and stop (`[ics] top_graph_chains`). With the
  Predator 0x400005D2 bound to 0x340003D1 (P, kit-audit-3.md) and its template attack started (`[ics]
  spawned_unit_kit`), Manifest dealt 577 to minions in its window.
- **Scriptless skill objects** (P stand-in): Green Lantern's Light 0x40000359 and Nightmare Catwoman's Inevitability
  0x40000D2B have no script in any template or decoded tree; `[ics] scriptless_spawn_blast` deals the spawning skill's
  stat 5 as power damage within stat 18 m after stat 14 s until their class records are decoded.
- Needing only client input (no server change): Deadshot's One Shot, One Kill starts on 0x10000023 (0x20EA, delivered
  by `World.raise_skill_event`) and fires on the order; Green Arrow's Bullseye draws on the press and fires on the next
  order; Batman's The Dark Knight dives on a second press that names a unit.
- No damage node by design (audit of the R script, its statuses, missiles and spawns): Raven (ally shields), Nightmare
  Superman (prison), Arcane Harley Quinn (status 0x4800130E), Starro (mind control), Arcane Green Lantern (ally shield,
  healing marks), John Stewart (placeholder kit), and the self buffs whose damage comes through basic attacks or being
  hit (Catwoman, Doomsday, Huntress, Swamp Thing, Wonder Woman, Blue Beetle, Atomic Poison Ivy). Aquaman's 0x34000397
  only switches its disable condition on 0x100000A9 (the new ultimate's HFSM); what raises it is open (O).

## Account standings 0x219E: wire order and the end-screen crash (2026-10-28, fase3-id)

Details and evidence in `docs/re-notes/end-screen-crash.md`. C = assembly / decompiler, P = probable.

- **Crash** (C): the tester's end-of-match crash at static `0xA37DEE` (`cmp byte [ebx + edx], 0`) is in
  `0xA37DC0`, the handler of `0x219E` (event class vtable `0x15EFF68`, built at `0x87FDC7` with id `0x219E`, size
  0x48; exec `0x8BAD90`; serializer `0x83FEB0` reads 10 u32 into event +0x20..+0x44 in order). `edx` = the standings
  singleton's (`0xA37BF0`, global `0x1B758F8`) per-rank byte table at +0x188, `ebx` = the rank. There is no bounds
  check (the `0x219F` handler `0xA5C840` does check `rank < [singleton + 0x190]`). ics sent the encounter DID
  `0x40000C82` as the rank.
- **Wire order** (C, from how `0xA37DC0` fills the vectors passed to `UI_DeliverAccountStandingsData` through
  `0x900FC0`): `u8 0 | u32 last played encounter (singleton +0x3C) | u32 rank (aRanks) | u32 previous rank
  (aPreviousRanks) | u32 sub-rank | u32 previous sub-rank | u32 rank position (aRankPositions; the old value moves to
  aPreviousRankPositions) | u32 streak | u32 previous streak | u32 matches played | u32 matches won`.
  aStreakActives = streak >= singleton +0x20 AND table[rank] != 0 (the same for the previous pair);
  aWonLastMatch = previous streak < streak. The entry for an encounter already in the list is updated in place.
- The minimum streak at singleton +0x20 is the 4th of `0x219F`'s 5 trailing u32 (`0x848B80` -> event +0xCC ->
  `0xA5C840` param 6); the first three go to `0xA4CA10`, which rebuilds the rank tiers from client data
  (`0x100000FA`, `0x10000DBB` / `0x10000DD5`). ics sends 0, so the table lookup always runs (P: rank 0 is a valid index).
- Server: `ics/matchend.py ranked_values`, `[ics] standings_layout`.

## Super Strength carry of a destructible, champion bundles in clips, camp phase-in (2026-10-28, fase3-id)

Details and evidence in `docs/re-notes/liftables-camps-animations.md`. C = decompiler / data / log, P = probable.

- **Containment** (C): the 0xB0 flag 0x04 block reaches `0x6113E0` -> `0x634C70` -> `0x58A220` -> `0x55F930`: the
  child gets location state 5 (`0x588330` -> `0x570BF0`, which re-registers the object and its render), a containment
  record (`0x55E360`: +0x10 mode, +0x14 child, +0x18 the mode-0x10 extra block copied by `0x55E6B0`: u32, u8, a
  0x1C-byte local transform left at its defaults, bool) added to the parent with `vt+0x60`. entity+0x1C = the
  containment component, its +0x58 = the parent (`0x587A50`, chain walk `0x55DCE0`).
- **Destructible render under a parent** (C path): the destruction render variant's attach method (vt+0x68 `0x6239A0`)
  only builds piece render instances that do not exist yet (`0x630BF0`: `piece+0x15C == 0`); the ones 0x8B built in the
  world stay as they were. `0x630FC0` (0x8B's last step, `0x631050`) takes the contained branch when `0x587A50` gives a
  parent: `0x630BF0(parent+0x14 -> +0xA0, ...)` -> `0x7602A0(piece, parent render, 0x200, ...)`. So 0x8B after the
  attach is the way to draw a carried vehicle, and after the detach to draw it in the world again (P result).
- **Render effect** scriptlet action type 8 (C): factory vtable `0x15CF5E8` (create `0x663F00`, ctor `0x654C00`,
  object vtable `0x15CEAB0`), execute **`0x673CF0`**: needs entity+0x14 (render component), skips (success) when its
  own byte +0x38 is 0 and the run flags (ctx+0x50 = the 0x8D entry's u32 run flags, copied by `0x657630`) have 0x40;
  passes the effect to render vt+0x50 (`0x623920`, normal variant), which queues it (`0x623480`) and applies it when
  the render instance (+0xA0) exists.
- **Camp spawn keys** (C data, pack 0xA0000161 table 0x1D000674): Vfx_Spawn_Event02 / Event03 / Event04 = type 5
  groups with a type 8 overlay (mesh 0x17001445, colour 0xFFF5EC04, fades 0.25 / 0.5 / 0.75 s); Vfx_Spawn_Alt01 =
  the same overlay plus particle 0x18000D90 (type 0x11, 40 / 60) and a black fade; Alt02 particle 0x18000B6E.
- **Thrown vehicle damage** (C log): the server's lob does damage a hostile within 2.5 m of the landing point; the
  12:28:41 throw landed 1.8 m from the champion among his own minions.
- Server: `ics/match/liftables.py` (`_rebuild`, `_throw_button(send=)`, `_release` restore), `World.update(force=)`,
  `ics/match/match.py _spawn_camp`; keys `liftable_attach_rebuild`, `liftable_detach_rebuild`,
  `liftable_throw_skill_at_lift`, `liftable_hold_champion_bundles`, `liftable_slot_restore_delay`,
  `match_camp_spawn_scriptlets`, `match_camp_spawn_delay`.

## Main-menu store and amplifier sets (2026-10-28, fase3-ie)

Raw notes: `docs/re-notes/store-amplifiers.md`.

- **Why no set could be created** (C, AS2 `gameplay.singleton.AmplifierSetManager.RecvNotice_NotifyListAmplifierSets`):
  the handler loops `i < uiTotalAmplifierSets`; rows `i < slotIDs.length` take the server's set, the others become
  `clientOnlySet` sets with the lowest free id and the first set icon (`m_aAmplifierSetIcons[0]`). So `total` is the
  number of set *slots*, not of saved sets; the server sent total 0 (no saved set), the screen had nothing to edit.
  `GetPlayerHasMaxNumberOfAmplifierSets` = `!(total < max)`; while false the Assembler adds an
  `AmplifierSetForSaleListItem` built from the first ContentType-5 ownable (`OwnablesManager.GetAllOwnableDatasOfType`)
  and its boutique entry (`BoutiqueDataManager.GetBoutiqueDataByDID`, from `0x2107`).
- **Save** (C): the Assembler sends `UI_SaveAmplifierSet(ampSetID, didCharacter, name, didSetIcon, e1..e7)` of its
  working set (`0x20FC`); `RecvNotice_NotifyAmplifierSet` (`0x20C7`) updates the set only if its id is already in
  `m_aAmplifierSetDatasByID` (else nothing happens): the answer must keep the client's slot id.
- **Store screen** (C): `gameplay.wrapper.store.Store.NavigateToStore` raises `EM_WebTicket.UI_RequestWebTicket`; the
  C++ listener is the app object built at `0x420950` (`0x4084A0`, app+0x1A8), interface vtable `0x15A63BC` with one
  method **`0x420B90`**, which raises `RecvNotice_UI_OnWebTicketUpdated(GUID string, shard)` (`0x6971D0`) at once from
  the GUID + u32 stored by event `0xC2` (`0x420920`; never sent, so a zero GUID). The Store then reads
  `GM_UI.InqStoreURL` and loads it with `webticket` / `shard` headers (`HTTPRequest`); `OnLoadEnd` with an HTTP status
  >= 400 closes the screen with an error dialog, else hides the spinner. The URL comes from AuthSelect's
  `nameValuePairs` `URL.Store` (`0xA9B890`; a config value at app+0x144 first, `0xA9B3B0` default last). The vtable at
  `0x15A63B4` (`0x420C00`) is the Steam MicroTxn callback -> `UI_OnMicroTxnAuthorizationResponse` -> the page's
  `FinalizeSteamPurchase(order, authorized)`.
- Server: `ics/account.py` (`amplifier_sets_msg`, `chosen_amplifier_set`, `amplifier_bonuses`,
  `AccountData.amplifier_stats`), `ics/store_web.py`, `ics/server.py` (`store_url`, `/store`), `ics/session.py`
  (`_complete_purchase`, `_maybe_create`), `ics/world.py` (`amp_add` / `amp_pct`); keys `amplifier_sets_total_slots`,
  `amplifier_set_max`, `amplifier_slot_for_sale`, `amplifier_stats_in_match`, `store_url`, `store_web_page`.

## Jungle camps: persistent phase-in, attack cancel, Tripod model (2026-10-28, fase3-ie)

Notes: `docs/re-notes/jungle-camps-spawn.md`. Tester 13:52: the Crime Alley camps stay in the yellow phase-in, lose it
when attacked, and look wrong.
- Scriptlet action type 8 (render effect; factory vtable `0x15CF5E8`, object vtable `0x15CEAB0`, execute `0x673CF0`):
  word reader `0x66D910`, property map `0x67CB70`, defaults `0x654C00`. Fields: `+0x34` sub-type (`0x5BF`; switch 1 / 3
  / 5 / 6 / 8), **`+0x38` persistent (`0x375`, default 1)**, `+0x3C` / `+0x40` / `+0x44` floats (`0x319` / `0x2C5` /
  `0x3D4`, defaults 0.25 / 1.0 / 0.25), `+0x48` (`0x417`), `+0x61` (`0x933`), curves, `+0x5C` priority (`0x6C7`, the
  render component sorts its effect list on it, `0x623480`), colour `+0x68` (`0x2C4`), ..., `+0x158` mesh (`0x834`).
  In the packed table body the type word comes first, the action base (probability, jitter, intensity, sequence) last.
- With `+0x38` set, `0x673CF0` returns a holder (`0x654BD0`, vtable `0x15CEA68`) as the run's attachment: the effect
  lives as long as the scriptlet run. `Vfx_Spawn_Alt01` / `Event02` of table `0x1D000674` have `+0x38 = 1`, so the
  phase-in ends only when the server stops the run (signal) or re-creates the object (a full bundle). No CA table has
  a "phasing complete" key.
- A provoked camp chases; its movement states are full bundles (`Units.send_state`), which dropped the phase-in (log
  13:46:26: the first `state` bundle right after the hit).
- Model: `0x49000CA0` / `0x49000CA1` (pack `0xA00002E7`) -> world state `0x2E000BE2` (.entity `0x2D0009D0`, graph
  `0x1C000086`), scale `0x6B4` 0.35 / 0.7; every Tripod class of the four maps uses `0x2E000BE2`. The client merges the
  class template at creation (`0x54F1F0`), so the scale needs no server property.
- Server: `Match._camp_phase` / `_camp_phase_in` / `_camp_phase_end`, `Units._late_flag` (held flags); keys
  `match_camp_phase_seconds`, `match_camp_phase_untargetable`, `match_camp_phase_resend`, `match_camp_phase_stop`,
  `match_camp_phase_end_bundle`, `match_camp_phase_lead`.

## Carried vehicles over the head; parked vehicles block paths (2026-10-28, fase3-ie)

Detail: [`re-notes/vehicles-carry-collision.md`](re-notes/vehicles-carry-collision.md).

- **AttachEntity's offset never reaches the client** (C): the vehicle carry script 0x34000161 attaches with
  AttachmentOffset (0, 0, 2.5) at point 0x100000B0 (the rock script 0x34000177: (0, 1.4, 1.4)); the 0xB0 flag 0x04
  block's mode-0x10 extra (`0x55E290`) is only u32 point, u8, bool, and the 0x1C-byte local transform in the copy made
  by `0x55E6B0` is never filled from the wire. A contained child therefore sits at the parent's origin (P: the tester's
  "merged with the champion at ground level"). Children are walked again on every parent frame change (`0x577EE0` /
  `0x577F30` -> `0x575B90` -> child component +0x38 vt+0x50); listeners hear attach / change through `0x55E4E0` ->
  `0x55DBF0`.
- **Destructible pieces follow their entity's frame** (C path): the destruction render variant's vt+0x64
  (`0x61F500`, vtable `0x15C94D0`) -> `0x61EC50` -> `0x62C730` moves every non-dynamic piece body to the new frame x
  the piece's local transform; the piece render instances read their body (`0x62DD00` / `0x62DD30`). So a vehicle
  moved by plain movement bundles carries its pieces along.
- **Server bug** (C): a carried object got the champion's destination, so `World.tick` walked it on its own and the
  session sent it a full bundle every tick (with the attach block); now carried / thrown objects get none
  (`liftable_no_dest`) and a vehicle is carried by its own bundles at champion + 2.5 m (`liftable_attach_kinds`,
  `liftable_carry_offset`, `liftable_carry_resend`, `liftable_carry_turn`).
- **Collision** (C): the client moves no character itself (client-movement.md 0), so parked vehicles block only through
  the server's paths: their footprints are blocked on the match's navmesh while parked (`liftable_blockers`,
  `liftable_blocker_margin`; G sizes).

## Timeline strip timing, K/D/A credit and the end page's per-row data (2026-10-28)

Full notes: `docs/re-notes/timeline-kda-endscreen.md` (C/P/O).

- **Strip under the clock** (Flash `EventTimelineDisplay`, C): `StartTimeline(t)` stores `m_ttStartTime = t` and
  starts an `IntervalTimer` from the client's `GetGameTime()`; a mark sits at
  `floor((eventTime - (m_ttStartTime + elapsed)) / 5 * 12)` px, lights the now-marker at x in [-4, 4] (severity
  1 High red, 2 Medium, 3 Low) and is removed at x <= -50. So the 'now' payload of `0x100002AF` / `0x100002B1` /
  `0x100002AB` must be the real time at send, and an event's time the real time it will happen. C++: `0xA5A0F0`
  (start, replays the stored list via `0xA480E0`), `0xA786F0` (add; stores via `0xA6ED90`), `0xA48A50` (remove:
  banner if the handle matches, else the event, Flash `0x8B4160`). ics: 'now' = `time.time()`, event time =
  now + (at - match time), marks re-placed when the intro re-bases the clock.
- **K/D/A** (C): top-right `PersonalScore` = MatchData row of the controlled agent from `0x1000005B` (row reader
  `0x867BF0`, builder `0xA4A4F0`: kills +0x50, deaths +0x54, assists +0x58, your IID = controlled agent). The
  numbers are the server's: kills by a missile go to its champion, a non-champion last blow to the last enemy
  champion who hit within the assist window.
- **End page per-row data** (C): `0xA795E0`, after Flash `UI_SendEndOfMatchStats` (`0x8E3AC0`) and
  `SetEndOfMatchStatsHeader` (`0x8E76D0`), runs per `0x2045` row `0x9D1700` (entry +0x2FC list: u32 n | n x (DID,
  stack), reader `0x844770`), `0x4FD4E0` (+0x1C champion DID) -> `0xA25430` -> `0xA51820` (power graph), then
  `0xA3AC70(account IID +0x08)` -> Flash `UpdateCurrentUpgrades` (`0x906DD0`) + `UpdatePowerGraphValues`
  (`0x907A00`) **only when the list is not empty**. Flash `ScorecardManager` shows nothing until it has one of each
  per distinct account IID (`AccountIIDs.length`), plus header, stats, accolades, levels, currencies, amplifier sets
  and the ranked data. So every row needs its own account IID and a non-empty artifact list.
- **0x2021** (C, diag): its handler `0xABC480` runs a world teardown; sent after `0x12D` it tore the world down a
  second time while the end page was being filled. Not needed after a match.
- After a match the landing screen keeps the champion list and "last played" it got at login; the server re-sends
  0x20B8 / 0x209D / 0x2081 / 0x214B with the menu refresh (fase3-ie, P: the landing screen's champion and background
  come from 0x209D's last-used times).

## Store page URL and contextual purchase prices (2026-10-28, fase3-if)

Full notes and the fix plan: `docs/re-notes/store-fix.md` (C/P/O). Corrects the fase3-ie store bullet above.

- **Every Flash browser starts on `chrome://version`** (C): `Turbine.Browser.CreateDesc` (`0xA03ED0` -> `0xA00790` ->
  `0x9FF850` -> `0x831FD0` -> `0x831520`) calls `cef_browser_host_create_browser` (`0x1099D20`) with that URL. A
  navigation goes `NavigateByInfo` `0x9FF070` -> `0x8330D0` -> `0x832F30`, which drops it unless `0x8308C0` (nav
  info valid: URL not empty and `cef_parse_url` true) passes; before the CEF browser exists it is kept at +0x80.
- **Store URL** (C): `GM_UI.InqStoreURL` = `0xA97320` returns app+0x144, filled once per login by the AuthSelect
  completion handler `0xA9B890` (vtable slot `0x1606F84`): app+0x144, else the `URL.Store` pair (`0xA971D0`, exact
  compare `0x437DD0`), else `PROJECT_STORE_URL` of the map `0x1B6901C`, which is always empty; stored by `0xA9A280`
  (`0xA9A309`), which also reads `URL.Tutorial1..3`, `URL.YouTubeChannel`, `URL.ReleaseNotes`, the four map URLs,
  `URL.Survey`, `URL.Credits`, `URL.UpdateNews`, `URL.Augment`, `URL.Mod`.
- **AuthSelect response types** (C, gSOAP in/out pairs): `return` = `authResponseMessage` (`0xADE4F0` / `0xADC7C0`:
  errorString, loginTicket, **nameValuePairs : NameValuePairArray** +0x18, new/oldSocialMediaEncryptionKey, randomID,
  sessionKey, userServerAddr, userServerPort); `NameValuePairArray` (`0xADE2D0` / `0xADC520`) = repeated child
  elements named `nameValuePairs` of type `NameValuePair` (`0xADE0F0`: name, value). The pairs are therefore nested
  (`<nameValuePairs><nameValuePairs><name>..`); a flat pair parses as an empty array.
- **Web ticket** (C): `EM_WebTicket.UI_RequestWebTicket` -> `0x420B90` (vtable `0x15A63BC`) raises
  `UI_OnWebTicketUpdated` at once (`0x6971D0`) with the GUID / u32 that only event `0xC2` sets (`0x420920`).
- **Boutique prices** (C): the only price source is `0x2107` (`0xA57510`, ids as `%I64d` text) ->
  `BoutiqueDataManager`, which keeps a value only for currency names "sc" (Merits) and "hc" (Crisis Coins), case
  ignored; costs default to -1, and the purchase dialogs then send `0x210E` with price -1 (`0xFFFFFFFF`). The set
  slot dialog (`DualCurrencyPurchaseDialog`) needs both prices; augments / mods use "SC" only. `0x210E` = u64 id | u32
  DID | str8 "SC"/"HC" | u32 price | str8 language. The UI listens to `0x210C` / `0x210D` only (Assembler);
  `0x210F` (`0xA35A30`) has no listener, so `0x2110` / `0x2111` never come from it.
- **Client event `0x95` = one store open** (C, second pass): `0x95` is built only by `0x692DF0`, called only by
  `0x420B90` right after it raised `UI_OnWebTicketUpdated`; the Store screen is the only live sender of
  `UI_RequestWebTicket` (the Assembler's `OpenStoreToAugmentOrModPage` is unreachable: `m_adAmplifierClickedForPurchase`
  is only ever set to null). The run's four `0x95` (14:39:21, 14:39:30, 14:54:51, 14:59:10) are four SHOP opens that
  each asked `InqStoreURL` and got "".
- **The store URL sticks per client process** (C): `0xA9B890` reads the `URL.Store` pair only while app+0x144 is empty
  (`0xA9BA8B`-`0xA9BAC0`); once set, later logins keep it. Nothing else sets it: `PROJECT_STORE_URL` is always "", no
  command-line option, nothing in `TurbineLauncher.exe.config` or the user preferences; `turbinebrowser.exe` is only
  CEF's renderer subprocess. No placeholder or host check on the way (`0x832F30` / `0x832A80`).
- **Boutique request** (C): `0x2106`'s str8 is the client language (app vtable +0xDC, `0xA2FCD0` -> `0x883560` /
  `0x883340`), the same getter as `0x210E`'s trailing "en"; `0x210E` goes `0xA46FC0` -> `0x8854D0` / `0x8852A0`.
  No record holds a price (the slot `0x49000AA2`: icon, flag, name; an augment twin: stat lines, strings, flags).

## Champion death animation: the fall is the server's (2026-10-28, fase3-if)

Full notes: `docs/re-notes/death-animation.md` (C/P/O, traffic excerpts, plan).

- **Graph** (C, all 56 champion graphs of `data/skill_graphs.json`): main-machine wildcard `CbtState_Death_Induce
  0x100000AD` (flags 0xC00, no self-transition) -> `Death`, a sub-machine whose start state is bound to
  `Death_Selection`: 0 face up / 1 face down (clips `attk_death_fup_a` / `fdown_a`, trigger `RunScript_Vfx_Death_A` /
  `_B`), 3 `Ragdoll_Death` (idle clip + turbine ragdoll modifiers). The graph's Lua sets it: `Locomotion.onActivate`
  -> random 0 / 1, `KnockUp` / `KnockDown` `.onActivate` -> 3. `Death` has no transition of its own; `Global_Locomotion
  0x100000AA` (`_Defeat_OnRespawn`) and the other main wildcards leave it. No graph variable is bound to LifeState.
- **Client** (C): nothing raises `0x100000AD` by itself (its two immediates are a script-event id at `0x9B5E00` and an
  input switch at `0xAC3CC0`); the `_Defeat_*` keys `0x100001F9` - `0x100001FE` have no code site (the six
  `0x100001FC` immediates in `0x9CE360`, `0xA4A030`, `0xA5D250`, `0xAB2D30`, `0xAB3250` are reads of property
  `0x100001FC`, kind DID). LifeState `0x100000FA` listeners: `0x968F30` (dead list `0xA3FE60` / `0xA336B0`, camera
  `0xA30E70`), `0xA80CD0` (HUD, `0xA0A600` on 2), `0xAB00A0`, `0xABF320`, `0x96C780`, `0x85EC10`, unit-component cache
  `0x979A60` -> order gate `0x9CFAF0`. A 0x4 bundle to an existing IID (`0x64D8A0`) does not reset the graph.
- **Data** (C): `_Defeat_OnDead 0x100001FA` (table `0x1D0000E8`: one type 0x14 raise of `0x100000AD`; `0x1D0001F6`:
  one type 9 sound) is in all 156 champion variants' tables, with `_Defeat_OnRespawn 0x100001FC` and
  `_HFSM_BehaviorRaiseEventAction 0x100001E3`. Cinematic deaths use it; status `0x340000EE` re-runs it at its exit on a
  dead SELF. P: the original server sent it after LifeState 2.
- **ics** (C): the local champion's death sent only the LifeState 2 bundle (the fall was in the `death_as_property`
  branch, off since fase3-gv), so it never fell; bots got stop bundle + 0x6 + `0x100000AD` and fell.
- **Death screen** (C data and code, P look): `_CDefeatSystem_DeathOverlay 0x10000843` (shared champion table
  `0x1D0000EF`, beside `_Advancement_LevelUp` and the other server-system scriptlets; no client string or usable
  immediate: the two byte hits `0x41B2E8` / `0xA8EEBB` are an instruction operand and a shop property) = one type 0x23
  timeline container (definition `0x52B290`, vtable `0x15B13B8`, execute `0x52F760`) with two persistent children:
  type 0x10 (execute `0x657F60` -> `0x775E20` -> `0x76EAA0`, an AfterEffect that loads texture `0x13001485`; error
  path `.../render/scene/manager/effects/AfterEffect.cpp`) and type 0x2D (definition `0x653C60`, fields `0x67A380`:
  persistent, fade-in / hold / fade-out, local-player-only +0x45, curves `0x8D5` / `0x8D4` / `0x8D3` / `0x8D2`;
  execute `0x659460` -> `0x776060` -> effect `0x76ED70`, vtable `0x15DAB80`). The effect's update `0x765980` writes the
  VideoPost object `[0x1B72160]`: `Colorize.Saturation` +0x1DC, `Hue` +0x1E0, `Contrast` +0x1E4, `Brightness` +0x1E8
  and `UseColorize` +0x1DA = 1 (names from `0x76D640`); its destructor `0x767930` clears +0x1DA; no other writer. The
  data: fade-in 0.75 s, hold, fade-out 0.25 s, +0x45 = 0 (no local-player filter), saturation -100 = grey screen. The
  sweep's "sound" meanings of action types 0x10 / 0x2D are wrong. **Corrected (skeptic review, death-animation.md
  10.2)**: ics never sent it, yet our builds show this very screen on the local death (C, video of fase3-ia/ib: the
  whole view, models included, desaturates in one frame with the same smoke edges as the original; the fog only darkens
  the ground). So the client runs it by itself; how it gets the key is O (no `.text` immediate, `.data` word, string or
  hash of it, no other pack reference). The "fog of war" explanation is withdrawn.
- **Event 0x11F stops a scriptlet run** (C): `u8 0 | u32 key | u32 instance | u8 flag (0 / 1)` (serializer
  `0x6751A0`); exec `0x675280`: entity by IID -> script component `[[ent+4]+0x10]` -> `0x57C4B0(key, flag, instance)`:
  instance `[0x185F2B0]` = 0xFFFFFFFF (never written) = every run of the key, else that run -> `0x57B920` ->
  `0x52D790` -> `0x529EF0` (state 4, end list `0x529E40`, state 5) -> unlinked and released. A 0x8D entry with a live
  instance and a signal bit goes `0x534BF0` -> `0x534290`, which only runs the definition's signal list (def+0x1C).

### Implemented (fase3-if, 2026-10-29)

- **Local champion** (`ics/world.py` `World.damage`, `_local_fall`, `death_fall`): the LifeState 2 bundle (it carries
  the stop, speed 0) at once, also while a carry holds the champion's bundles (`[ics] death_bundle_force`), then
  `[ics] death_fall_delay` (0.15 s) later 0x8D `_Defeat_OnDead 0x100001FA` (`death_scriptlets`, `death_fall_local`).
  The delay keeps the order "status exits -> stop -> fall": a movement state is applied 0.1 s after its stamp and an
  0x8D at once (`0x60B5F0`), and script 0x8Ds on the local champion go `champion_scriptlet_delay` (0.13 s) late (in a
  simulated GD death a status's exit scriptlet `0x100003EA` landed before the fall). Respawn: teleport bundle
  (LifeState 4) -> `_Defeat_OnRespawn` (Global_Locomotion).
- **Bots** (unchanged order, at once): stop bundle -> 0x6 LifeState 2 -> `_Defeat_OnDead` (was the bare
  `0x100001E3` + `0x780 = 0x100000AD`: the same `Death` state, no cue). Respawn: 0x6 LifeState 4 -> bundle -> one
  `_Defeat_OnRespawn` per `bot_getup_delays` entry (`bot_getup_scriptlets` [], was two per entry).
- **Nothing leaves Death before the respawn** (C graph data, all 56 graphs): `Death` has no transition and `SM_Death`
  no wildcard (its states none either, but Vampire Batman's / Zatanna's `Non_Ragdoll_Death` -> `Ragdoll_Death` on
  `CbtState_KnockUp`), so only the main machine's wildcards stand the body up. Super Strength's carry script
  `0x34000164` can raise `skill_to_locomotion 0x10000002` in its end state (EVENT_END comes with the death's drop; in
  the simulated mid-carry death it raised nothing); that event is a main-machine wildcard in none of the 56 graphs, so
  a death mid-carry keeps the fall (tests/test_match.py "carry: ...").
- **Death screen**: client-run (above); the server's copy is opt-in (`[ics] death_overlay_scriptlets`, default []:
  `["_CDefeatSystem_DeathOverlay"]` sends it after the fall, local champion only) and its run is stopped by event 0x11F
  (`M.stop_scriptlet`, `death_overlay_stop`) after the respawn's get-up and at the match end (the original's grey ended
  when the end cinematic started). Open (P risk, death-animation.md 10.3): fase3-gu, the only earlier build that sent a
  fall to the local champion, had "no grey screen"; if the grey goes with the fall, the opt-in is the fallback.
- **A death that ends the match** (fase3-if review, C ics): `Match` listens to World's events synchronously, so in Clash
  the local death that takes the last team health runs `_champion_died` -> `hurt_team` -> `Match.end` inside
  `World.damage`'s "killed" emit, before `_local_fall` schedules the fall. `Match.end`'s 0x11F stop then finds no run,
  and the fall 0.15 s later would start the opt-in screen with no stop ever after (the respawn is cancelled when the
  client leaves the world 4 s later). `Match.end` now marks the world (`match_ended`) and `World.death_overlay` starts
  no screen after it (`[ics] death_overlay_skip_after_end`); the fall itself still plays during the end hold.

## Object update bundles: a 0x4 to a live object re-creates nothing (2026-10-28, fase3-if)

Full notes, log evidence and the update-path plan: `docs/re-notes/object-update-bundles.md` (C/P/O). Corrects the
fase3-ib / fase3-ic / fase3-id bullets (and champion-animation-matrix.md 1, deep-scan-animations.md 1.2) that say a
full bundle re-creates the object or replaces all of its properties.

- **Path** (C): batch exec `0x5D9FF0` -> object manager `0x64E070` -> `0x64AB70` -> `0x64BD30` (deferred while the IID
  waits for its landblock; re-shown when it is in the set `this+0xE0`; sub-events dispatched in wire order). 0xF2 ->
  `0x64D8A0`: for a live IID only `f2+0x28` vs `entity+0x110` is compared (both 0: `[0x1B67260]` / `[0x1B6AB20]` are
  zero-filled `.data`, read-only in code); a difference calls ChangeWorldState `0x54D5C0` (rebuild), the only bundle
  field that re-initialises a live object. 0xB0 -> exec `0x698CD0` -> `0x6298D0` -> the movement listener `0x60AFA0`
  (merge `0x57DA90`, push `0x609C70`, same module seq = no-op in `0x553E70`) and the containment listener `0x6113E0`
  (parent IID 0 only clears a queued attach). 0xBC -> exec `0x699330` -> `0x635440` -> property component vt+0xA4
  `0x62AFD0`.
- **`0x62AFD0` is a diff** (C): it collects the object's own ids whose descriptor network mode (+0x16) is 1 or 3
  (`0x4FB520`), drops those the table holds (`0x503C60`), removes the rest (vt+0x54 `0x577E10`) and sets every sent
  entry (vt+0x50 `0x578DE0`, the 0x6 path). The setter notifies only a new id (`0x577EE0`) or a different value
  (`0x577F30`; `0x4FDC30` / `0x4FC020`: words, floats, arrays `0x4FF770` and tables `0x5004B0` element by element);
  a removal notifies "removed" or "changed" back to the class template's value (`0x577F90`). 0x6 = exec `0x699450`
  -> vt+0x50; 0x86 (`u8 0 | u32 id`, reader `0x839500`) = exec `0x699210` -> vt+0x54.
- So an identical bundle notifies nothing; `0x7D2` is read only when the script component is built (`0x58CB60`,
  `0x58EDD0`) and `0x5B5` only when the animation component (re)initialises (`0x556D70` / `0x556DC0`). What a bundle
  does change: ids sent by 0x6 with net mode 1 / 3 and left out of it are removed (log: unit flags `0x1000019D`, tags
  `0x10000029` / `0x10000249` of the bot and the champion, `0x100003F3`, `0x10000C66`; the order lock `0x10000B2D` by
  code), and its 0xB0 facing / speed drive Turn / Propel like any movement state.
- The 0xB0-only update works (C path): the fase3-hy bot "invisible until it attacks" was the fog flag `0x90F`, which
  ics sent only in full bundles. Meltdown's stop is the server script: its status removed itself after its
  first-pulse jump (graph hook 2 at +0.17 s is the data's `skill_to_cosmetic`, the end of AGL's throw; see "Meltdown
  against a moving target" below). What ends the
  Shards sphere, a camp's phase-in and Grab's arm is open: `python tools\diag.py --bundles` (Spanish `--paquetes`)
  logs every 0xBC, its removals, every 0xB0 state and, with the call stack, every end of a spawned child
  (`0x666B40`), render effect (`0x65CA30`) or beam (`0x659B00`).
- **Skeptic check** (note section 12; C unless marked).
  - *Same storage.* The 0x6 / 0xBC setter `0x578DE0` stores into the own hash at component+0x1C (`0x4BFB00` from
    +0x18), the table the diff walks (`0x62AFEA`) and the remover erases (`0x577E3E`). "has" (`0x62A460`) checks the
    client override hash at +0x90 first.
  - *Dispatch.* `0x64E070` is slot +0x3C of vtable `0x15CDC70` (object manager +0x10). `0x64BD30` dispatches each
    sub-event through slot +0x18 `0xB0C730`, which routes by routing+0x28.
  - *Deferral.* An event for a non-live IID is deferred only when the routing u64 at +8 is set
    (`0x64E206`-`0x64E22D`); otherwise it is dropped (0x80004002). What fills that word for server messages is O.
  - *entity+0x110.* Only `0x54AA50` (init "none") and ChangeWorldState `0x54D5C0` write it. Carrier props are no
    exception. ChangeWorldState returns at a failed load {DB type 0x2D, DID} before detaching.
  - *Who loses what (ics).* Units keep their late flags (also in `extra_props`). The 0x6-only ids that bundles remove
    are: the champion's and the bots' 0x1000019D, the bots' tags, the CC bools 0x100003F3 / 0x100007FE / 0x10000B39 /
    0x100005A3 and 0x10000B2D, and 0x10000C66.
    `on_cc` sends a stop bundle right after the CC 0x6, which removes the flag in the same burst.

## Object updates without a 0xBC: the delta path in ics (2026-10-29, fase3-if)

Implementation of the section above (`docs/re-notes/object-update-bundles.md` 13; tester report 2026-10-28 15:00).
`[ics] object_update_mode` = "delta" (default; "bundle" = fase3-ie, byte for byte).

- **Network modes from the install** (C): `Data.network_mode` parses the client's MasterProperty record `0x32000000`
  (pack `0xA0000039`; unpack `0x502750`: u32 tag, `w0` id | kind << 16, `w1`, `w2` = network mode in byte +2, `w3`
  flags, tag 2 / 3 extras, tag 0x8x defaults by kind and member sets, whole words). 3 822 descriptors to the record's
  exact end, every mode equal to properties-complete.tsv. Net 1 / 3 = what a 0xBC removes when it omits an id.
- **An object the client has is updated by `World.delta`**: a 0x4 batch with only the 0xB0 when its motion changed
  (`pvp_movement_state`, with the 0x04 attach block; `messages.movement_block` builds the bundle's and the state's 0xB0
  alike), one 0x6 per property whose packed entry changed, one 0x86 (`u8 0 | u32 id`) per net-1 / 3 id that left its
  list (`delta_remove_missing`; net-0 ids only with `delta_remove_net0`). No 0xF2, no 0xBC, so nothing ics set by 0x6
  only (unit flags, tags, CC flags, order lock, turret target) is removed any more.
- **Full bundles that stay**: creation, its retries, `_objects` (create / link / in world / after a cinematic), a
  champion's death and respawn (`delta_full_on_life_change`), 0.5 s after a creation (`delta_create_window`: an event
  that reaches an object whose creation runs may be dropped), the first update in the world of an object sent while
  loading (`delta_full_after_load`), an update with a changed array / table (`delta_complex_as_bundle`: the rank array,
  item / pad / Stolen Power tables). After a full champion bundle `vital_notices_on` puts the unit flags back.
- **Cadence unchanged** (`Session._tick`): the champion every tick it changed (no player-object bundle / 0x42), bots at
  `World.motion_due` with every changed property (a standing bot's fog flip `0x90F` now goes), missiles at their turn
  (no `missile_rebundle_scriptlets` replay), units at their own states. The idle full bundle becomes a resync
  (`delta_resync_seconds`: movement state + scalar properties by 0x6). The stop order and a script teleport
  (`send_champion`) are deltas (a new seq A snaps).
- **0x6 with arrays / tables** reads its value with the 0xBC table's own entry reader (C): table `0x503330` ->
  `0x5025D0` = per entry u32 key + `0x509740`; 0x6 serializer `0x445530` (vtable `0x15D18D0`, factory `0x691500`) =
  base u8 `0xB0D380` + `0x509740`. Open: no u32 is read before the packed id there, yet ics's u32-first 0x6 works in
  game (2026-10-23 15:00 diag --target accepted the structures after a 0 -> flags toggle by 0x6); 0x86 follows its own
  serializer `0x839500` (P until the first test).
- Tests: test_match `object_updates` (25), test_ics (+1), test_session_flow (+1).

## Crime Alley stealth fields: corner collision faces and the original's layout (2026-10-28, fase3-if)

Details, numbers and the implementation plan: `docs/re-notes/stealth-alignment.md`.
- **Where a champion's body stops** (C): the rim of the map pack's navmesh blob for the champion agent `0x10000003`
  (radius 0.525, height 2.1; Crime Alley `0xA0C112BA` +0x2A4E6FC, 176 triangles) moved out by the radius. The three
  agent blobs (0.525 / 1.1 / 2.1) give the same face at each corner on the 0.2 m vertex grid, so rim + radius is the
  obstacle face. Crime Alley's jungle mouths: west garden side face x 52.725, lane face y 83.125, garden-fence face
  22.93 deg through (54.005, 86.316); east x 107.075, fence 157.25 deg through (106.797, 85.916). The west garden is
  brick (pillars `0x2E0012F5`, `.entity 0x2D000FDA` 0.8 x 0.8 x 2.3 m), the east chain link (`0x2E0008F4` / `F5` / `F6`,
  whose `.entity` records carry 4 / 3 / 2 m collision boxes 0.2 m thick): the mouths are not mirror-built.
- **`.entity` header** (C data): `did | 0 | 0 | n | n x (f32 half x y z | f32 centre x y z | f32 quaternion w x y z) |
  1 | 0 | 1 | 0 | f32 bbox min xyz, max xyz | ...`; n = 0 for render-only pieces (the brick fence).
- **The in-match camera** (C on our frames, P on the original's): pitch 57.5-58.7 deg, vertical FOV 46 deg, 14.4-14.7 m
  above the ground, yaw 0 on Crime Alley; the same in the original video and in a recording of ours. Fitted with a
  pinhole model (principal point at the viewport centre) on the "+" of our tiles at known spawn points (rms 0.6 px) and
  on pillar-cap / fence-post tops in the original (rms 1.0-1.5 px). It turns frames of the original into map metres
  within about 0.15 m (the "+" or a tile's near and lateral edges; far edges read long because of the glow).
- **The original's stealth layout at the jungle mouths** (P, measured that way): an L of two 4 x 2 m tiles per mouth, a
  vertical one centred at (51.7 / 108.3, 85.2) from the garden corner north along the side face and one along the
  garden fence on the path side; left and right mirrored about x 80. No placement data exists for them (C,
  crime-alley-video-compare.md: the original server spawned the hotspots from its own data).

## Crime Alley stealth fields: the L in ics, flush with the corner faces (2026-10-29, fase3-if)

Tester 2026-10-28 15:00 ("both side fields are off; the vertical one back as it was, lined up with the collision edge
of that corner"). What shipped from `docs/re-notes/stealth-alignment.md` 8 (its section 10).
- **Layout** (`ics/match/maps.py`, Crime Alley "stealth" tiles 4-7, flagged `"flush"`): vertical (51.7, 85.2) /
  (108.3, 85.2) yaw 90; along the garden fence (54.2, 87.5) yaw 23 / (105.8, 87.5) yaw 157. Long edge vs the collision
  face (champion navmesh rim + 0.525 m), all on the walkable side: 0.025 / 0.225 / 0.016 / 0.084 m, angles 0 / 0 /
  0.07 / 0.25 deg; the vertical tiles' corners lie 0.08 / 0.24 m from the garden corners (52.725 / 107.075, 83.125).
  The east tile keeps the original's mirror (the east side face is 0.2 m west of a mirror of the west one).
- **Face test** (test_match; reusable for any tile or prop placed against a wall): rim edges = triangle edges used once
  in the champion-agent blob (`navmesh.find_blobs` / `parse_blob`, landblock coordinates rounded to the mm); each rim
  edge moved 0.525 m away from its own triangle is a face with an outward normal. A tile's long edge that faces the
  same way and runs within 3 deg of a face is sampled at 9 points; the points that project onto the face segment give
  signed offsets (+ = past the face, inside the obstacle).
- **Hide test at the bend** (the original's rule is O): the two tiles of an L overlap at the bend. `Match.visible_to`
  lets an enemy see a hidden champion when any strip holds both (`[ics] match_stealth_any_shared`). Before, only the
  first strip holding each was compared, so a champion in the bend stayed hidden from an enemy a metre away in the
  diagonal tile.
- **Switch-back**: `[ics] match_stealth_overrides` = {map key: {tile index: {"pos": [x, y], "yaw": deg}}}, merged over
  the map's spec in `Match._spawn_stealth` (in config.toml: `[ics.match_stealth_overrides.crime_alley]` then
  `"4" = {pos = [51.7, 84.0]}`).

## Jungle camps: neutral colour, the overhead bar's gates, the original's camp slots (2026-10-28, fase3-if)

Tester 2026-10-28 15:00: grey Tripods with no overhead bar, a camp in the centre, side camps misplaced. Full note:
`docs/re-notes/camps-colour-bar-positions.md`.

- **Team colour** (C, `0xA7B0D0`, run by the team listener `0xA813F0`): team = `0x854050` (unit component `+0x4C`,
  change-only); colour index = `0x10000CF0` if set, else relative (`0x8533C0`: neutral 6, enemy 5, ally 3) or absolute
  (`0x853450`: 0 -> 6, 1 -> 3, 2 -> 5), **only for teams 0..2** (`cmp edi, 2; ja` at `0xA7B143`): team 3 gives colour
  0. It writes `0x100007A2`, sets variables `0x100004A8` / `0x100007A9` and runs `_Entity_OnSetClientRelationship`.
- **The tint itself** (C data): in table `0x1D000385` that key is a type-0x22 container on `0x100007A2` whose children
  set appearance set **`0x19000A61`** group `0x10000004`: 5 -> `0x1000011E` red, 3 -> `0x1000011D` blue, **6 ->
  `0x1000011F` yellow** (material `0x16000E7B` RGBA 0.937 0.710 0.051), 1 -> `0x10000128` purple (`0x160018B4`, the
  override of the tutorial drones and of the CA minions' template), 0 / other -> `0x10000127` Null. Material instance
  layout: `did | 1 | 0x7D0 | 0x7D0 | f32 R G B A | 0 | 0`. Flash tints the bar separately (`TeamUtils`): team 0 ->
  0xCCCC33 yellow. The original's yellow creatures and yellow bars = **PVP_Team 0**; ics sends 3.
- **Overhead bar** (C): registered once at entity add (manager vtable `0x1602D20` -> `0xA3A900` -> filter `0xA0EFC0`:
  creation type 7 / 8, a non-character needs **VitalDisplayType `0x10000831`** != 0, not `0x80000`, a life component),
  then pushed to Flash (`0xA50A70` -> `0x904440`) when alive, rendered and its **FloatyVitals attribute `0x1000072C`**
  is true (one tag at `0x16016AC`, default 1, checked at `0xA50C3B`; `0x10000B2D` only drives fades through the
  listener `0xA1DC10`), with the PerceivedType from the unit component's change-only cache (`0x9CFBF0`); an added bar
  that turns hidden or loses FloatyVitals is removed and pushed again later (`0xA50CAC`); Flash's
  `OverheadVitalsBase` never attaches a bar whose PerceivedType is 0. Every jungle creature template (CA `0x49000CA0` /
  `CA1` / `CA2`, GD, CC) declares `0x1000072C`, `0x10000029`, `0x10000249` and `0x1000009C` with no value (`0x5...`
  entries, false, as `0x10000029` was for the tutorial drone in fase3-gf); minions and structures carry
  `0x1000072C = 1`; ics never sends it, so no camp gets a bar (skeptic review, camps note 8). `0x10000831` is the VitalDisplayType (1 Expanded,
  2 SimpleElite, 3 Simple, 4 Champion, 5 ExpandedElite, 6-9 the large ones): Tripod 1, Heavy Tripod 5 (star +
  dividers, as in the original), from the template the client merges (`0x478880` builds the `0x49` DID).
- **Camera** (C data, P meaning): encounters name camera record `0x4800114E` -> `0x2100001E`, words 10, 17, 45, -57, 0,
  17 (distance range, FOV, pitch, yaw, distance); Tutorial 1's `0x2100000A` has yaw 45.
- **The original's camps** (P, +-0.3 m, four video frames): 1 Heavy Tripod + 3 Tripods on the upper sidewalk by each
  jungle mouth: west (48.82, 91.87) heavy, (51.04, 91.91), (47.20, 90.33), (49.60, 90.24); east (110.58, 91.83),
  (108.50, 91.82), (112.20, 90.31), (109.95, 90.15) (the west's mirror 0.5 m further west). No creature at the nook's
  locked pad at "Phasing Complete" (Clash). The phase-in lasts ~3.2 s and the bars appear when it ends.
- `tools/diag.py --camps` (Spanish `--campamentos`): team colour, bar registration, bar push (PerceivedType) and fades.

### Implemented (fase3-if)

- **Wire team** (`ics/match/units.py` `Units.spawn`, `ics/world.py` `World.properties`): every role-"camp" unit (bosses
  included) carries `ent.wire_team` = `[ics] match_camp_wire_team` (0); bundles send `0x1000009C` = 0 and
  `0x100007A2` = `match_camp_side` (6), the server keeps `team` 3 for fog, AI, rewards and script relations.
  `Units.late_wire_team` sends the team again as a change (3, then 0, by 0x6) `unit_flags_delay + 0.1` s after the
  spawn (`match_camp_team_as_change`). `World.floaty_key` (the 0x42 damage-number key `(team & 7) << 4`) uses the wire
  team too.
- **FloatyVitals** (`Units.late_vitals`, `Match._camp_phase_end`): `0x1000072C` = 1 by 0x6 `unit_flags_delay + 0.25`
  s after the spawn (after the unit flags' +0.2), kept in `extra_props`. A phasing camp holds it with its targeting
  flags (`hold_flags` -> `pending_vitals`) and gets it at Phasing Complete right after `0x1000019D` / `0x10000029` /
  `0x10000249`, so the push carries PerceivedType `0x100`; the phase-end bundle then carries it. It is never in a
  creation bundle. All 54 champion templates, the CA minions, structures, relay `0x4000089D` and the vehicles carry
  `0x1000072C = 1`; only the Tripods (while phasing) and the Raider (its first second) lack it in a CA match.
- **Diag** (`--camps`): `0x650C60` (`0xA50C60`, `mov [ebp-1], al`) runs only when the FloatyVitals check returned false;
  the breakpoint after the call (`0xA50C59`) would be hit by every bar entry every frame.
- **Camps** (`ics/match/maps.py`, `Match._spawn_camp`): Crime Alley's "camps" are the two side camps with "slots" (the
  original's, first = the heavy = "pos"; `match_camp_slots`, false = the 2 m ring); the middle camp moved to
  "camps_centre" (`match_camp_centre`, false). Without it `Bosses._spawn_raider` brings the Raider at 300 s. Crime
  Alley has no meteor storm, so the storm's camp-based impact sites are unaffected.

## Terrain sockets in the map packs: per-team Gotham Divided sites, the MOPP tree, the lids (2026-10-29, fase3-if)

`docs/re-notes/map-audit-all.md` 10-11 (C unless noted). Builds on the terrain record of the fase3-ib section above.
- **Render index order.** The landblock render block's index buffer (`u32 0x1800 | 6144 u16`) holds vertex-buffer
  indices k with x = (k % 33) * 5, y = (k / 33) * 5. 0x712860 writes vertex `local_28 * 33 + uVar10` with
  x = uVar10 * 5, which is the transpose of the heights' order (index (x / 5) * 33 + y / 5). Read that way, every
  batch's triangles span exactly its stored bbox: CA 13BB 12 of 12 batches, GD 1BD3 8 of 8, CC 23E3 33 of 33. In the
  heights' order 0, 0 and 1 batches match. Batch -> palette -> layer type -> textures (table `0x07000000`) then gives
  the ground a flattened socket shows:
  - Gotham Divided team 1's lane exits (40, 150), (35, 125), (10, 120) are drawn only by batch 2 (types 0x7 / 0xD,
    textures in `0xA00000FC`).
  - Team 2's (150, 40), (125, 35), (120, 10) only by batch 1 (asphalt 0xE / 0xF, in no GD pack). 0x7137B0 binds a
    null texture for a missing layer DID, and the client runs D3D11, so P: flat, that ground would be dark.
- **MOPP.** The `hkpMoppCode` at record +0xD8 is attached unchanged to the collision mesh rebuilt from the heights
  (0x53BCB2 -> 0x539D90).
  - Code info: offset -0.05; scale 83195.48 on CA, 66565.06 on GD and CC.
  - Key = 2 * (yc * 32 + xc) + t, as 0x53BA00 builds the triangles.
  - A raised triangle that keeps a ring vertex stays inside its path's z interval (CA's 32, GD's 48 + 16).
  - A triangle with all three corners raised leaves it: only Coast City's centre, keys 862-865 / 926-929
    (`terrainfix.whole_triangles` = 8). A collision query the tree prunes can miss those triangles; which client
    queries walk the tree is O.
- **Sites** (`icserver/terrainfix.py` `SITES`, `[game] terrain_sockets`):
  - on: `crime_alley_dampeners`, `gotham_divided_lane_exits_team1`, `coast_city_centre`;
  - off: `gotham_divided_lane_exits_team2`, `gotham_divided_pits`, `tutorial_2_dampener`. The last is record
    `0x800113C3` at decompressed 0x472D570 of `0xA0C112C2`, normals at +0x80FC, (40, 75) / (40, 80) at 179.96 m.
  - The alias `gotham_divided_lane_exits` means both teams' sites. The backup is read by decompressed offset, so the
    entry of a combined site restores either half.
  - Crime Alley's 28 written values equal the 14:40 diag fill's (`tests/test_terrainfix.py`).
- **Lids** (`ics/match/match.py` `_spawn_socket_covers` / `_socket_flattened`): a `[ics] match_socket_covers` entry
  with `"terrain_site"` is left out while `terrainfix.installed_state` reads that site as patched
  (`[ics] match_socket_covers_skip_flat`). The probe is a lazy `Stream`: block headers plus the record's arrays, cached
  per path, size and mtime.
- **Shadowing.** Each patched terrain DID is in exactly one of the 616 packs. The client keeps no copy of pack data,
  and ics never reads terrain heights.
- **Another version of a pack** (fase3-if review): `Stream._dspans` refuses decompressed bytes outside the stream with
  a ValueError, so a site whose record lies past the end of a shorter stream (or across it) is reported as "not
  touched" by `apply` (dry run too) and read as "unknown" (cached) by `installed_state`; it used to walk off the block
  list with an IndexError that stopped `python ic.py patch`. The installed packs have 0x4C48A4 (Tutorial 2) to
  0x5681C0C (GD) bytes past their sites.

## Crime Alley's centre is drawn by baked patches; the black strips by the blue lane turret (2026-10-29, fase3-ik)

`docs/re-notes/ca-black-strips.md` (tester report 2026-10-29 16:40, screenshot 49.webp).
- **Near batches or baked patches.** `0x714280` (both callers pass param_5 = 1) builds a landblock's ground with
  `0x712860` + the near batches (`0x713DD0` -> `0x713C10`) unless byte +0x58 of the render block (first of the two
  bytes `0x547740` reads after the three u16 arrays) is set; then `0x712310` + the far branch (`0x7132D0` per patch).
  Crime Alley sets it in 13BB only (record +0x81DC = 1): 16 patches of 40 x 40 m, 9 x 9 vertices from the +0x3C heights
  (index i * 33 + j, as the patch writes them), constant vertex normals (`0x711B10`), 128 triangles each split along
  (x0 + 5, y0) - (x0, y0 + 5) (second 6144-index array), material `0x140002C5`, textures `0x1300341E + 3k` .. `+2`
  (2048 DXT1 colour, 1024 DXT5 normal map, 1024 DXT1), all in the map pack. So 13BB never uses its near batches, layer
  textures, blend masks or stored normals (C; the diag's `--mapload` lists no 13BB batch). The boxes of patches
  (40-80, 40-80) / (40-80, 80-120) say z >= 179.96: the bake predates the 0 m lane-turret socket.
- **Strips** (camera of `camps-colour-bar-positions.md` 3.1 on AGL at (71.5, 75.4)): south x 70-75, y 70.4-71.7 = the
  part of cell (70-75, 70-75) south of the lane mesh; both its triangles end at (70, 75) = 0 m (C). Site
  `crime_alley_lane_turret` raises (70, 75) too. North x 70-76, y 81.5-83.1: flat cell, changed by the 15:16 patch, the
  rest bounded by a ray from the turret's spot (65, 77.5) (P shadow of the fog-of-war circle / turret light, O).
- **Redefined sites.** `terrainfix.apply` restores a site whose earlier version is installed (backup bytes + untouched
  installed bytes = the site's original CRC) and patches it in the same run.

## Super Strength vehicle lift: the original's toss and catch; the SUV against the wall (2026-10-28, fase3-if)

Tester 2026-10-28 15:00: the vehicle lift "starts lifting, then cuts to already holding it"; the SUV should move a
little closer to the raised wall north of it without turning. Full note: `docs/re-notes/vehicle-lift-and-position.md`.

- **The champions' car machine** (C, `data/skill_graphs.json` + the raw hkbClipGenerator fields of pack `0xA0000150`,
  AGL; hk 2012.2: name +96, cropStart +108, cropEnd +112, startTime +116, speed +120, mode +134; a transition's effect
  pointer at +32 of its 60 bytes). SM_Main_Machine's wildcard `SuperStrength_InitCarPickup 0x10000176`
  (".1s_Ignore_ContinueBlend") enters `SuperStrength_Car_Pickup_Start` (the pickup clip, cropEnd 0.783, single: the
  bend-and-grab up to the 0.45 s frame, where it holds). `SuperStrength_CarPickup 0x10000246`
  ("Instant_Ignore_ContinueBlend") -> `SuperStrength_Car_Pickup` (the same clip from 0.45 at speed 0.8; a_SkillHook
  code 3 at 0.46 = the grab; state_to_state at 0.75 -> Hold, ".2s"). `SuperStrength_Car_Hold` (car idle / walk / run)
  is the only state with a transition on `SuperStrength_PickupCar 0x10000175` (-> `Car_Catch`, ".075s", the catch clip
  from 0.122, back to Hold at its end); an event a state has no transition for is dropped.
- **Per champion** (C, found by structure: the start state's CarPickup out-transition -> its target's first clip):
  all 56 graphs of the 156 variants have the machine; doomsday, gaslight_catwoman, poison_ivy, vampire_batman,
  wonder_woman and zatanna name it `SM_SuperStrength_Car_Throw`, and Joker's and Doomsday's states are renamed.
  Car_Pickup start / grab hook / Hold (the last two in s after CarPickup): 49 graphs 0.45 / 0.0125 / 0.375 (AGL,
  Gaslight Batman); chr_batman, Catwoman 0.4103 / 0.1597 / 0.3897; Nightmare Superman, Supergirl 0.4103 / 0.0497 /
  0.3397; Joker and its Arkham skin 0.45 / 0.01 / 0.3; AWW 0.45 / 0.15 / 0.4375 (its Car_Pickup loops).
- **Scriptlet action type 0x23, timed sequence** (C code): factory vtable `0x15CF4F8` (create `0x6633D0`, runtime
  `0x663450`, object vtable `0x15B0D08`), execute `0x52F760`, update `0x52F940(now)`: a group fires once
  `now > group time / rate + start` (group time = f32 at entry +0x14; rate = runtime vt+0x4C `0x515960` = def[+0x50] *
  def[+0x4C]).
- **The original's CarPickup** (C data, shared champion table `0x1D0000EF`, pack `0xA00000DF`): `Vfx_Event9
  0x100000E9` @0x14863A0 = [0x23: group (6, 0.05, 6, 1) -> 0x14 `0x10000246`], [0x14 `0x10000246`], [0x14
  `0x10000176`]: CarPickup at once (dropped: still in Locomotion), InitCarPickup, then CarPickup again 0.05 s later (P
  order). `0x100007A2` InitObjectPickup @0x1485F64 = [0x14 `0x10000176`], [0x23: group 0.55 s -> type 4, P camera
  shake]; `0x100007A1` PickupObject @0x1485C68 = [0x14 `0x10000175`], [type 4: 0.2 / 0.1 / 3 / 0.03]. As a scriptlet
  key `0x100000E9` is `Vfx_Event9`; `CbtState_StrafeRight` is the graph-event table's name for the same number.
- **Sub-skill `0x34000161`** (C script; defaults from its server-only blocks): S6 = Vfx_Event9 + InitObjectPickup on
  SELF, face the object, object untargetable (`0x10000029`), input held; S6 -> S7 on OnCastSignal 3. S7 =
  `LaunchLobbedMissile` (script `0x34000160`, 70 deg, at the champion + 1.1 m toward the object), RunScriptlet(object,
  `0x10000223` VFX_CBT_Hit_Shared, `0x100002F8` = ObjectPickupScriptlet `0x1E0000BE`), RaiseEvent `0x100000BB` ->
  `0x34000164`, TossDuration 0.3; S8 CatchDuration 0.35 (S7 / S8 -> S9 also on the lob's landing `0x10000002`); S9 =
  DisableHit `0x100003AF`, AttachEntity((0, 0, 2.5), point `0x100000B0`), PickupObject `0x100007A1` on SELF and the
  object, AttachmentDuration 0.1 -> S4 (input back). MaxRange 1.0 (+ both radii) for S10 -> S6. The vehicle's script
  `0x34000162` S8 runs InitObjectPickup on the vehicle and raises `0x10000085` (starts `0x34000161`).
- **Remote replay** (C, `0x60B5F0`, client-movement.md 1.3): a sampled state within 2 m is steered to (`0x5C9FE0`),
  a farther one is placed at once with the velocity zeroed (`0x5C9E90`); only with a body (component +0x1C), P for a
  vehicle. fase3-ie's single 3.4 / 4.2 m "over the head" state was therefore a jump.
- **The SUV's box** (C data, P meaning): world state `0x2E000795` -> `.entity` `0x2D00061C` (pack `0xA000009A`
  @0x1A28AD4, header @0x3BAB75C): `did | 0 | 0 | 1 | half (1.0, 2.5, 1.116) | centre (0, 0.177, 1.111) | 1.0 | ... |
  bbox`; all seven vehicle boxes are 1.0 x 2.5 m in x / y (a uniform proxy), the model's +y is the heading (placement
  yaw + 90 deg). The wall north of it: Crime Alley navmesh `0xA0C112BA`, agent `0x10000003` rim (102.2, 94.8) ->
  (107.2, 92.6) at -23.75 deg; agents `0x10000002` / `0x10000001` are the same vertices shifted 0.6 / 1.6 m in y, so
  the wall face lies 0.48-0.60 m beyond the agent-3 rim.

### Implemented (fase3-if)

- `ics/match/liftables.py`: a vehicle (KINDS "toss") replays 0x34000161 (`[ics] liftable_vehicle_toss`; false = the
  fase3-ie order). CarPickup at `liftable_car_pickup_at` (0.05; `"graph"` = the champion graph's Car_Pickup start);
  from the grab hook `liftable_toss_steps` - 1 movement states over `liftable_toss_seconds` (0.65) on the line to the
  hold point plus `liftable_toss_arc` (1.5 m) * sin(pi f), with S7's `liftable_toss_scriptlet` on the vehicle; the
  catch (never before Hold + 0.05 s): DisableHit, the hold-point state, PickupObject on both, the 0x8B rebuild; ready
  `liftable_attach_seconds` (0.1) later. `_graph_times` reads `ics.graph.data()` (the graph runtime may be off). A dead
  carrier drops the car at every stage. With "vehicle" in `[ics] liftable_attach_kinds` (the switch-back to the
  containment carry) the catch attaches the vehicle on the hold point instead of the hold-point state (fase3-if
  review: `_catch` ignored the key, only the old grab frame read it).
- The SUV at (102.43, 93.90), yaw 245 (`liftable_props_by_map`); its blocker is its box, `[2.5, 1.0, 0.0, 0.177]`
  (`liftable_blockers`; the 4th element = the box centre's forward offset, `Liftables._block`).

## Store page and contextual purchases in ics; the item-fulfilled ribbon (2026-10-29, fase3-if)

Notes: `docs/re-notes/store-fix.md` section 7 (implementation of the section "Store page URL and contextual purchase
prices" above).
- **AuthSelect** (`ics/server.py`): `URL.Store` is sent as the client's `NameValuePairArray` reads it (outer
  `nameValuePairs`, items = child elements `nameValuePairs` with `name` / `value`), after `loginTicket`. A model of the
  client's read (`tests/test_ics.py` `auth_pairs`) gives the URL for this form and nothing for the flat one.
- **Prices and purchases** (`ics/session.py`): `0x2107` = per augment / mod / set slot an `SC` entry (Merits) and an
  `HC` entry (Crisis Coins) with the same boutique id; `0x210E` is paid at the server's price in the wallet of the
  client's currency; a wrong price (the client's -1 = 0xFFFFFFFF) gets `0x210D` GeneralError + a fresh `0x2107`
  (`0x210F` has no UI listener). The slot's success path is `0x210C` -> `DualCurrencyPurchaseCompleteDialog`, then
  `0x2090` total + 1.
- **`0x2095` item-fulfilled ribbon** (C, code): exec `0x8AAF60` passes &msg+0x20 / +0x24 / +0x28 to `0xA7EA00`, which
  stores (first u32, second u32, StringInfo) in a map keyed by the first u32 (`0xA746B0`, object `[0xA12D50()+0x54]`
  +0x19C; nothing happens when that object is missing), sets +0x1B0 and runs `0xA26B50`: for each node
  `0x88F040(second u32, &name)` -> `RecvNotice_Ribbon_ItemFulfilled(i_didIcon, i_siName)` -> `UpgradeUnlockRibbon`.
  Layout: `u8 0 | u32 key | u32 icon DID | StringInfo name`. ics no longer sends it after a store purchase (`[ics]
  store_purchase_ribbon`).
- **Client event `0x95`** (one per SHOP open) is logged and left unanswered; `0xC2` (the web ticket) stays unsent.
- **The store URL is a narrow string**: `0x402C60` / `0x402D60` copy a ref-counted buffer of `size` 1-byte characters
  (header -0x10 refcount, -4 size with the terminator); `0x8308C0`'s `cmp [ecx-4],1` is the empty test.
  `tools/diag.py --storepage` reads it at `0xA97331` (`s[[[esp]]]`) and at `0x832F54` (`s[[ecx]]`).

## Amplifier icons on the store page (2026-10-29)

Notes: `docs/re-notes/amplifier-icons.md`.
- **No amplifier record holds an icon** (C): the 5-entry augment / mod records have none; the 17 `0x10000302` icons the
  store used came from `Data.template_properties` reading past the record (wrong pictures: a tower, skill icons).
- **The client composes the icon** (C, AS2 `AmplifierSetManager.OnItemStatusesChange` + `AmplifierDisplay`, exe):
  augment = `UI_InqAugmentData` -> `0xA26F70`: brand `0x10000956` -> background `0x100009C9` (bottom layer), stat line 1's
  `0x10000958` -> `0x100009D0` (top-left, top layer), stat line 2 -> `0x100009CD` (bottom-right, middle layer), all from
  record `0x48000AAD` (game-data key `0x100000AF`, cached by `0xA710F0`, looked up by `0xA21C90` with the property
  constants at `0x16017F8` / `0x16017EC`, and `0xA21CF0`). Mod = `UI_InqModData`: the last target artifact's
  `0x10000436` (`0xA271D0` -> `0x8578E0`, bottom) under the brand `0x1000097B`'s corner badge `0x10000996` of record
  `0x48000A34` (game-data key `0x100000A7`, `0x8655F0`; the same badge is the in-match `didModBrandOverlayIcon`).
- Every layer is a 256 px DXT3 picture with alpha meant to be stacked at full size.
- Server: `ics/store_web.py` `_amp_layers` / `_compose` (Pillow), `[ics] store_amp_composed_icons`; cached in
  `data/uesrv_cache/store/amp_<did>_c.png`, composed by the prewarm thread too. 334 / 334 store amplifiers get a picture.

## Log sweep of the 2026-10-28 run: record lookups, match clock, bot casts and turrets, kill display, Raider (2026-10-29, fase3-if)

Notes: `docs/re-notes/test-2026-10-28-1439-sweep.md` (findings S1-S13, finalizer section 16, skeptic section 17,
implementation section 18). Run: Crime Alley v AI, Atomic Green Lantern against AI Atomic Wonder Woman.
- **Record lookups and the 2.77 s freeze (S1, C)**: `Data._record` built a pack's record-start list (`Pack.record_starts`,
  packs < 40 MB) on first use only to bound the record. `creation_type`, `champion_world_state`, `unit_attack`,
  `unit_stats`, `record_u32`, `template_properties` and `record_tables` read a window from the record's start and never
  use that end; `entity_scripts`, `status_script`, `status_max_stacks` (and `combat.status_flags`, `unitdata`) do. The
  freeze at AWW's first Savage Sweep was `creation_type(0x2E0009F0)` building the list of pack `0xA00000DF` (2736
  records, 21.7 MB): 2.4-3.3 s for a lookup that reads 4000 bytes (the decompress is 0.07-0.1 s; the 32 MB
  `0xA00000B3` was already built by the warm-up). A start-only lookup now gets `end = start + 16 KB` and builds no
  list; `Data.prepare` (server start, queue thread) builds the skipped ones. Over 333 classes (156 champion variants,
  the 78 skill-spawned classes, every `maps.py` class) and their world states, record tables, creation types, 0x510,
  template properties, attacks and stat blocks are the same both ways.
- **Template bound (S3, C)**: `unit_attack` / `unit_stats` read 32 KB from a template's start, past its end. A template
  ends at the first word after its header that is a DID of the same pack followed by a header word (0, 1, 2, 3, 4, 7) and
  a count 0 < c < 4096 (`Data._template_end`; a world state's `did | 7 | entity | 0 | count` never passes the count test).
  `0x40000CD6` (AWW's sweep helper, template `0x49000CD6` in `0xA0000124`) ends at +0x46C; the scan took AWW's basic
  attack `0x34000257` at +0x4BB4, inside record `0x480006D4`, so the helper was a unit that attacked the player. Cut:
  the attacks of `0x40000208`, `0x40000265`, `0x400005E1`, `0x40000A6C`, `0x40000BD4` (Atomic Joker's Plutonium Peel),
  `0x40000CD6`, `0x40000E56` and the stat blocks of `0x400005E1`, `0x40000A6C`, `0x40000CEB` (plus the never-spawned
  encounter DIDs `0x40000270`, `0x40000CA6`, `0x40000E62` / `68` / `74`). Map units keep their attack scripts and stat
  blocks; their attack stat lists lose entries read from the next records: melee minions stats 30 / 44, and Crime
  Alley's team 1 turret `0x40000C92` the stats 2 / 8 / 11 / 19 / 23 / 24 / 32 that team 2's `0x40000C93` never had
  (its template ends at +0x9B4, the record list's next start `0x34000605`). Their attack scripts read none of those
  (`0x34000088` / `0x340004A1`: 5, 18; turret `0x34000014`: 1, 14, 15, 18, 20, 30; Raider `0x34000512`: 5, 18, 30).
- **Match clock (S2, C)**: `Match.tick` clamped dt to 1 s; the HUD clock (`send_clock`, sent once) and the timeline strip
  follow the wall clock, so after the freeze waves, camps, lines, the Raider and the end ran 1.8 s late. The clock now
  takes the whole step (up to 10 s) and every timer due by then fires in that tick; the subsystems keep the 1 s step.
- **Skill uses a script ignores (S5, C)**: `Graph.event` returns whether a transition fired on the event and
  `Instance.event` dropped it. AWW's W Smite `0x34000255` has one `0x1000001D` transition (graph S1 T0, gated by NOT
  `HasStatus 0x480006FD`, its buff, which the next basic attack uses up), so 10 of the run's 16 "casts Smite" did
  nothing and `World.cast` still returned True: the brain stopped every 0.7 s and never attacked. `Instance.event` and
  `activate()` now return the flag (a stopped instance, the accept filter and the loop cut = not taken) and the
  `0x10000196 {Slot}` broadcast goes only for a taken use. Census (NullWorld, no targets): 5 of 216 Q/W/E/R scripts do
  not take a first use: Shackles `0x34000294` (HasTargets), Kryptonian Rage `0x340000E1` (VitalThreshold), One Shot One
  Kill `0x34000694` (waits for `0x10000023` first), Kendo `0x340005BA` and Might of Atlantis `0x34000397` (no
  `0x1000001D` transition: a bot's use of them never did anything).
- **Bot casts (S4, C)**: `World._attack_step` started slot 0 with no cast check, and its chase sets `dest` directly
  (past `cast_holds_movement`); `BotBrain.try_skill` kept the attack target (the player's order clears it,
  `session.ev_order`): AWW's basic attack cut her Savage Sweep (S1 -> S2 -> S0, no S3: no damage, no cooldown, recast at
  once), and her Vault cut an empowered basic attack. A simulated check also showed the brain casting Vault 0.5 s into
  the sweep's 1 s cast.
- **Bots under towers (S6, C code; the run's branch P)**: the `bots.py` docstring promised a retreat under an enemy
  turret, but `BotBrain.decide` never looked at the bot's own position: `turret_danger` only filtered targets and
  ignored a turret whose range held an allied minion; the only exit was `bot_retreat_health` 0.3 when one shot is ~15 %
  of the bot's health (4 of 4 bot deaths under GL's turret, 5-7 shots each).
- **Bot rank order (S7, C)**: `rank_up` counted the spent ranks of slots 1-4, but the 54 loadouts' 19-entry
  `skill_order` lists hold slot 5 (AWW `0x400003EC`: `[3, 1, 2, 3, 5, 4, 2, 3, 2, 4, ...]`), so after the trait the same
  entry repeated (trait at levels 5 / 6 / 7, R at 8). 53 of 54 orders put the R ranks at levels 6 / 10 / 14 / 18 (Green
  Arrow `0x400006F9`: 1 / 6 / 11 / 16) against `[ics] rank_min_levels` `{"4": [6, 11, 16, 20]}` (P); a gated entry is now
  retried at the next level, so a bot's R ranks come at 6 / 11 / 16 / 20 under those gates.
- **Kill display (S9, C mechanism; the original's display P)**: `_champion_died` credited a turret-finished kill to the
  last enemy champion who hit the victim (fase3-ie) but passed the raw killer to `Scoreboard.kill_feed` and to the
  announcer, whose `Match.voice` falls back to the local champion as both IIDs when the source is not a champion (a 77
  byte 0x2039 with no entity fields; a champion kill is 239 bytes with both portraits).
- **Passive income (S8, C asymmetry; the original's rule P from the M5 video's 1000 credits at the end of the
  pre-game)**: `World.income` paid the local champion from `in_world` on, the bots only from the start.
- **Raider warnings (S10, C)**: `Bosses._schedule_raider` scheduled the 4:30 / 4:50 warnings unconditionally while
  `_spawn_raider` waited (5 s retries) for the middle camp on the Raider's pad.
- **Node `0x100000FA` (S11, P)**: not a floaty text. Factory `0x99C5E0`, vtable `0x15FD158` whose slots 7 and 10 are
  `purecall` `0x134D420`: a server-only node. Values: 0 = skill slot (`0xFFFFFFFF` = this skill), 11 = a TFX DID (AWW's
  passive `0x34000265`: slots 1 / 2 / 3 with `0x1300148F` / `90` / `91`, the empowered-skill effects; its counterpart is
  ClearSkillStatOverride), 13 / 14 = a pair (Super Strength `0x34000164`: (1, 1) then (1, 13); Reclaimer `0x34000253`:
  (0, 5)). Probably SetSkillStatOverride; its wire message is unknown (O).
- **Left as they were**: client event `0x95` (the web-ticket request of `UI_RequestWebTicket`, listener `0x420B90`, sender
  `0x692DF0` via `0x444A90`; the store area logs it), the RankSkill RPC `0x9F 0x81910003` (answer `0x81910001` = the "+"
  animation, O), the surrender refusal before 600 s (the original's message O), the selection panel's level
  (`SelectionPanel.StartWatchingEntity` reads `Level_Property` once), the doubled `0x20A8` status icon updates and node
  `0x10000075` (no server effect, O).

### Implemented (fase3-if)

- `ics/gamedata.py`: `Data._record(did, need_end)`, `_build_starts`, `build_skipped_lists` (called by `Data.prepare`),
  `_template_end`; `unit_attack` / `unit_stats` bounded (`[ics] record_start_only`, `template_window_bounded`; set by
  `ics/server.py`).
- `ics/match/match.py`: `Match.tick` (`match_clock_follows_wall`), the income hold lifted in `_begin`
  (`match_income_from_start`, `World.income`), `_champion_died` shows the credited champion (`kill_feed_shows_credit`).
- `ics/script_runtime.py`: `Instance.event` / `activate()` return the taken flag; `0x10000196` only for a taken use
  (`skill_used_broadcast_taken`, module flag `SKILL_USED_BROADCAST_TAKEN`).
- `ics/world.py`: `_attack_step` waits for a non-local entity's skill cast (`attack_waits_for_cast`); `cast` fails a bot's
  untaken use and rests the slot (`bot_cast_needs_taker`, `bot_untaken_skill_backoff`; the stop state stays before the
  activation); `basic_cast_at`; the `0x10000023` "not accepted" line once per script.
- `ics/match/bots.py`: `try_skill` clears the attack target (`bot_cast_clears_attack`) and skips a resting slot;
  `fight` casts nothing while a skill or (up to 1.5 s) the basic attack is in its cast (`bot_skill_waits_cast`,
  `bot_skill_waits_basic`); the `evade` state and the dive rule (`bot_turret_aggro_retreat`, `bot_dive_health`);
  `rank_up` (`bot_rank_order_all_slots`); a per-decision trace (`bot_trace`).
- `ics/match/bosses.py`: the Raider's warnings and spawn wait for a free pad (`raider_warn_when_free`).
- `ics/script_nodes.py`: `0x100000FA` logged as SetSkillStatOverride (P), nothing sent.
- Tests: `tests/test_match.py` `log_sweep` (24 checks), `tests/test_ics.py` (6 checks on the warm server data).

## Meltdown against a moving target: homing re-aim, a status acts for its applier (2026-10-29, fase3-if)

Tester report 2026-10-28 15:00 (Crime Alley v AI, Atomic Green Lantern vs bot Atomic Wonder Woman): a Meltdown hit
must slow the enemy, and its "waves" stop hitting it and the effect is cut when it moves. Full analysis:
`docs/re-notes/meltdown-moving-target.md` (investigation, finalizer 8, skeptic 9, implementation 10). Movement itself
stops nothing: the status rides on its victim and each pulse is a FindTargets centred on the status' owner (C).

- **Chain (C, script trees):** R `0x340002B4` (slot 4) launches the orb `0x40000484` (script `0x340002BE`) at the target;
  the orb's hit raises `0x100000EE` to the shooter's `0x340002B4`, which applies status `0x480007AF` (script
  `0x340002BF`) for PulseDuration x PulsesRemaining. The status pulses every PulseDuration (ApplyDamage on SELF, then
  FindTargets(PulseRange) relation 3, SELF excluded, ApplyDamage on each), raises `0x10000006` to its EffectSource's
  `0x340002B4` (PulsesRemaining - 1) and, when the victim has Sickness or MaxRadStacks - 1 Rad stacks, launches the orb
  again at the best enemy within JumpRange (non-sick, +101 for a champion, nearest) and removes itself. No hotspot or
  aura anywhere in the chain; no slow node: the slow is AGL's passive `0x340002B3` (a Rad stack `0x480007B6` per skill
  hit `0x1000008A` / proc `0x1000001D`; at MaxStacks it removes them and applies Radiation Sickness `0x480007BC`, whose
  script `0x340002C6` runs a DoT and ApplySkill(SELF) `0x48000294` -> `0x34000134`: AddAttributeModifier `0x100005E4`
  op 10 = SlowAmount -0.4).
- **Homing re-aim (C, ics):** `0x340002BE` S7 sets its speed every SpeedBoostDuration (0.3 s, 4 -> 15 m/s over 5 s);
  `Missile.fly_to` measured each new trip from `Missile.pos`, written only at creation / arrival / collision, and the
  per-tick hit test `World._missile_hits` skips missiles that follow a target, so the arrival timer kept moving away:
  a still target 4.5 m away was hit after 4.9 s, a walking one never (chase timer 6 s). Live: `test-2026-10-25-1928.md`
  (the orb looped S3 -> S7 for 4.4 s on a minion).
- **Who a status acts for (C client code, P strong for the server rule):** the client half of FindTargets `0x9CCE60`
  builds its query from SELF (owner block `0x44C5C0`, excluded when the node's byte +0xF is 0, `0x4A9060`) and the team
  of the context's source descriptor `0x991F60` (-> `0x854050`, property 0x1000009C); `0x991F60` takes ctx type
  `0x10000005` to `0x55B9C0` (a 3-byte `return 0` in the client: the server's lookup of the running effect), 2 to the
  skill component `0x96E160`, `0x10000006` to property 0x100004FE, else the creator 0x100004E2 or SELF. GetCreator's
  execute `0x993480` calls the same `0x991F60`, and status scripts name its output after the applier (`0x340005C9`
  `$EffectSource`, `0x34000654` `$Caster`, `0x34000543` `$StarroIID`). Data: of the 21 status scripts with ApplyDamage that
  read EffectSource, 19 leave its source operand unset (`0x340000F0` deals its end blast to relation 3 + SELF). ics took
  every one from the victim: Meltdown's pulse area hit AGL's side (live 14:52:10.712: AGL took 21.5), the damage, kills
  and assists were the victim's, and the jump orb was shot by the victim, whose slot 4 has ChaseDuration 0.
- **Status skill hits (P, from the game's own description and the missing stack node):** a status' damage counts as
  the applying skill's hit; the client VM queues events per instance (`0x96DED0`), so the stack of pulse N lands after
  pulse N's jump test: the 4th pulse makes the victim sick and moves Meltdown on. Gate: ApplyDamage value b = 1
  ("triggers on-hit effects"): 34 of 47 status ApplyDamage nodes, in 23 status scripts; proc damage has b = 0.
- **Loop guard, self removal (C ics):** the 20 ms event guard (`Instance.event`) counted per event id, so one pulse's
  5th unit got no stack; a status' self RemoveStatus stopped its chain, so the jump skipped `0x10000006`
  (PulsesRemaining stayed one too high: 7 pulses after a jump).
- **Status auras (C data, P rule):** CreateHotspot / CreateAura's flag [0] ("include the owner", full-combat-skills.md)
  is 0 in all 52 hotspot and aura nodes. With the applier's side, the mask-3 auras of the statuses put on an enemy
  (Sinestro's Fear Incarnate `0x3400048B`, Solomon Grundy's Buried on Sunday plague `0x340006AB`, `0x340007D9`) matched
  their own carrier: the plague re-infected it and recursed through the infected's auras
  (champion_check: a RecursionError in Buried on Sunday). A status' aura never targets its carrier, and a status it
  holds on a unit that already had it is not the aura's to remove.
- **Not Meltdown:** the 165-damage hits of that run are the mid t1 turret's shots (10.939 / 11.971 -> 11.078 /
  12.085). Graph hook 2 at +0.17 s after the cast is the data's `skill_to_cosmetic` of `Clip_Meltdown` (end of AGL's
  throw by design, `data/skill_hooks.tsv`); the waves stopped because the status removed itself after its first-pulse
  jump (AWW already had 3 stacks, two of them from one Scorched Earth hit: the passive's graph S1 `TargetIID` (source 3)
  and its nested S1 `TargetIID` (source 5) share one slot in ics, so a skill hit also fires the charged proc; open).

### Implemented (fase3-if)

- `ics/script_runtime.py`: `Missile._advance` / `fly_to` (`missile_reaim_from_current`, module flag
  `REAIM_FROM_CURRENT`); `Missile(..., origin=)`; `acting_entity(inst)` and `effect_source` set by `apply_status` /
  `_restack` before any chain of the status runs, from its `source` argument, never the EffectSource parameter (25
  basic attacks put a shot tracker on SELF with EffectSource = the target) (`status_acts_for_source`,
  `STATUS_ACTS_FOR_SOURCE`); the loop guard keyed by (event, target) (`event_loop_per_target`, `EVENT_LOOP_PER_TARGET`).
- `ics/script_nodes.py`: `_find_targets` (relation from `acting_entity`), `_apply_damage` (default source, the queued
  status skill hit: `status_skill_hit_event`), `_start_vot`, `_apply_skill`, `_add_stacks`, `_hotspot` /
  `_hotspot_tick` (owner = applier, `hs.exclude` = the carrier), `_launch` (a new missile of a status: shooter = the
  applier, origin = the owner), `_remove_status` (self form after the chain: `status_self_remove_after_chain`).
- `ics/world.py`: `ObjectMissile.start` starts the client object at the origin (team and 0x100004E2 the shooter's).
- `ics/server.py` / `tools/champion_check.py` set the module flags; `tools/champion_check.py --bot-walk`.
- Tests: `tests/test_meltdown.py` (32 checks, no ports), `tests/test_scriptvm.py` (+13). Headless (test_meltdown): the
  orb lands 1.1 s after the cast on a still bot 4.5 m away and 2.1 s on a walking one; 6 pulses, all AGL's; Sickness and
  the slow (bot 3.9 -> 2.34 m/s); with 3 stacks and a bot-team unit 2 m away the jump orb is AGL's, starts at the bot,
  and the unit gets the 5 pulses left. `champion_check --vs-champion` (54 champions), fixes off -> on: BUFF 15 -> 16,
  CHMP 11, DMG 159 -> 178, FX 82 -> 62, REF 3; sequence verdicts unchanged.

### Store page pictures (2026-10-29, fase3-if)

- The client's store is a CEF browser (Chromium 31) showing the page at URL.Store; anything it can render is allowed,
  so the page shows the game's own art: per champion and per costume the roster (data/champions.json, from the
  champion definitions) gives `wallpaper` (1024 x 1024 DXT3, 11 mips) and `grid_icon` (128 x 128 portrait); the card
  uses mip 1 (512 px). Amplifier icons: the augment's template property 0x10000302 (17 of 334 have one), the set slot's
  record property 0x1000095E (0x13002966). Converted per request from the player's packs and cached locally.

## Grab never hit the bot champion: collision holders, IsMoving, the arm (2026-10-29, fase3-ig)

Tester 2026-10-29 11:00 (AGL vs bot Robin): Grab pulls minions, never the champion; the arm shows as a projectile.
Details and evidence: `docs/re-notes/agl-grab-arm.md`.
- The Grab missile never collided with Robin in the whole run (no `0x340002C1 S3 -> S4` with him; he stood on the line
  2.3 m away at 10:52:15). ics kept one "collision off" flag per entity: Robin's Vault Kick 0x3400030D ends with
  DisableCollision 0x1000006F, so after his first one every missile passed through him.
- Client (C): `0x97D860` / `0x97D720` take the run's context entity (`0x44C5C0`, SELF = the missile for a missile
  script) and call `0x976990(run key, 0|1)` on its physics component (`0xAA10B0`): enable adds the 16-byte run key to a
  holder array, disable removes it (`0x96EB00`) and takes the body out (`0x972110`) only when the component's three
  holder lists are all empty. ics now keeps per-run holds; champions / units / structures / props stay in collision by
  template (P), and the toggle acts on the script's own entity (each Grab hit used to put AGL out of collision).
- IsMoving 0x100000E1 (server-only): r1 = 0 is a forced movement only (P from its three users: recall next to a 0.25 m
  distance test, get-up, Grab's `NOT IsMoving(target)[0]` pull test), r1 = 1 any movement. Before, r1 = 0 meant walking,
  which sent a walking target to Grab's damage-only branch S11.
- 0x3F000003 (pack 0xA0000150 @0x34FC4): a 0x3F reaction handler = variable block (EntityPosition, SourceIID,
  Collider, SubEntity, Position, BlipSequence, 90Degrees = 90.0, IsEthereal) + one chain repeating the S4 -> S1 test; the
  script's `<0xABEB783 src 5>` operand is its 90Degrees.
- The arm: none of AGL's 67 skeletal clips has a scale track or stretches the arm chain (the enter-world clip flies the
  construct rings in from ~26 m); AGL's Grab state is start -> loop (until Grab_Hit 0x10000331) -> end -> end loop, no
  bound variable. The stretch is the missile Vfx_Active's type 2 beam back to AGL's attach 0x1000007C while
  ArmFade_RemoveHand hides the construct hand; the beam lives as long as the missile. The server replayed Vfx_Active
  after each turn bundle (3 runs in 0.43 s, each its own beam); no longer.

## Super Strength throw indicator and flight, relay padlock stop (2026-10-29, fase3-ih)

Details: `docs/re-notes/throw-truck-padlock.md`.

- **Throw indicator (C).** The throw sub-skills `0x480003C9` (vehicle, targeting type 1) and `0x480004A2` (rubble,
  type 13) both carry `0x1000063A = 0x340001A3`, the client slot script. Its graph: S0 -> S1 on ScriptEvent
  `0x100000B6` (enter: `LastSkillSlotUsed = SkillSlot` param, node `0x10000056` -> `0xab62d0` -> `0xa5dab0` = start the
  slot's indicator), S1 -> S0 on `0x100000B7` (exit: node `0x10000022` -> `0xa4f0c0` = end). It does not listen to the
  button's `0x10000023`. S->C `0x20F9` (serializer `0x839550`: `u8 0 | u64 agent | u32 slot | u8 available`; handler
  `0xa2a1b0`) raises `0x100000B6 + available` with param `SkillSlot` (hash `0x31D944`) through `0xa16e60`. ics sends
  `0x20F9(slot, 0)` when a carry is ready and `(slot, 1)` at the throw / drop.
- **What the indicator draws (C, `0xa39360`).** Range decal (+0x80): texture `0x100002A3`, radius stat 18
  (`0x874930`), plus the capsule radius for types 7 / 0xE / 9; second decal (+0x84): texture `0x100006D8`, radius
  stat 23 (`0x874990`); cursor area (+0x88): texture `0x100006D7`, radius stat 18 when `0x85d230(type)`, else 6.0 (half
  stat 22 for type 16); stat 22 = line width (`0x873ab0(.., 0x16)`); `0x10000ABC` names a stat used for the camera
  (`0x874ad0` -> `0x89fa80`). Vehicle throw: ring 9 m (stat 23, `0x48000156`), area 2.5 m (stat 18, `0x48000155`).
  Rubble: ring 8.5 m (stat 18, `0x48000154`), line width 1.25.
- **Flight (C script, P look).** `0x34000161` S2 throws with `LaunchLobbedMissile(ObjectIID, TargetPosition, -,
  MissileVelocity 15.0, ...)` (angle value 0; the toss onto the champion uses 70 deg). The client has no gravity in
  its replay and draws states ~0.1 s late, so the server sends the arc as states (every 0.05 s, >= 0.8 s) and the
  explosion 0.15 s after the last.
- **Relay padlock (C keys, P effect).** `Vfx_Locked` on ws `0x2E000D12` starts particles `0x18000703` / `0x180006FB` /
  `0x180007DF` that stay until the run ends; `Vfx_Unlocked` and the lock bools `0x100006BD` / `0x100006BC` do not end
  it. Event `0x11F` with instance `0xFFFFFFFF` stops every run of the key.

## Carry indicator by 0x2180, snapped lob, landing impulse, relay stop mode, end-cinematic core (2026-10-29, fase3-ij)

Details: `docs/re-notes/throw-padlock-coredeath.md`.

- **0x20F9 cannot show the carry indicator (C).** `0x340001A3`'s node `0x10000056` reaches `0xa5dab0(slot, flag 0)`,
  which draws only when `slot == [[0xa12d50()]+0x90]+0xEC`, the HUD controller's current targeting slot (set only in
  targeting mode). S->C **0x2180** (`u8 0 | u32 slot`, ser `0x839500`, handler `0xa6d800`) starts the same indicator
  with no gate (end the shown slot, +0x60 = slot, `0xa39360`, `0xa39820`); the per-frame `0xa29680` keeps the cursor
  area on the cursor for the slot at +0x60. **0x217F** (`u8 0 | u32 slot | u8`, ser `0x83f690`, `0xa5d070` ->
  `0xa4f0c0(slot, u8, 1, 0)`) ends it. The original Super Strength script `0x34000164` S3 overrides the slot's own
  targeting stat (1 = 1 / 13) and stat 23 (`node_100000FA`, `node_10000148`, `node_10000153`) instead of swapping the
  table (C tree).
- **Steered states lose the height (C code, P effect).** `0x60B5F0` steers a state within 2 m by a displacement
  (`0x5C9FE0`) and snaps (`0x5C9E90`) only on > 2 m or a newer seq A / B; the arc states (< 2 m apart) were drawn
  straight at hand height in two runs. A newer teleport sequence per flight state places each exactly.
- **Thrown vehicle's landing (C script `0x3400015F`).** S2: Vfx_OnInit, Vfx_OnExplode, Destructible_IgnoreAOI,
  DestructionImpulse (sphere, DestructionRange 4.0, DestructionMagnitude 10, level 3), DestructionDelayDuration 0.15 s;
  S4: impulse again, DestroyEntity 10.5 s; ExplosionRange 3.0. Vehicle tables `0x1D000612` / `0x1D00034B` /
  `0x1D000111` have no Vfx_OnInit.
- **0x11F's u8 is a stop mode (C).** Exec -> `0x57C4B0(key, mode, instance)` -> `0x57B920` -> component vt+0x7C(mode);
  the client's own StopScriptletKey `0x588A80` passes mode 1 (e.g. `0xAA23C0` stopping `_Selection_Usage_Locked`
  `0x10000653` when the local team's lock bool turns false). The minimap note's lock mask (`0xA0CAB0`) is recomputed by
  the listener `0xA80CD0` on any change of 0x100006BC / BD / 0x100004FF.
- **End cinematics draw their own core (C data).** Crime Alley `0x3500003B` / `3A`: actor PowerCore `0x2E000AC5` at
  the losing core's spot, `Vfx_Destruct_State0` at frame 0; the networked core under it made the "duplicate" the
  tester saw.

## Crime Alley holes, base hologram pedestal, turret heads (2026-10-29, fase3-ih)

Details: `docs/re-notes/ca-holes-pedestal-turrets.md`.

- **Black strips by the lane turret (C frames + data).** Recording 12-09-37.mp4 6:30-13:00: black on the sidewalks at
  x 70-75, y 80-85 and 65-70 (original video 2:36: ground). CA terrain `0x800113BB` has the lane-turret socket
  (60-70, 70-80) + (75, 80) at 0 m (team-1 side only); street statics cover its middle. Site
  `crime_alley_lane_turret` (icserver/terrainfix.py) raises only the rim rows y 70 / 80 to 199.98 m with upright
  normals (`raised_normals_up`), so no triangle has three raised corners (the MOPP tree still bounds it). CRC
  0xF375_46A7 -> 0x7534_9554. Not touched: the south alcove (85, 50-65) / (90, 55-60) at 0 m behind the buildings
  (not seen black).
- **Base hologram pedestal `0x2E000A36` (C data).** Ctype 8, `.entity 0x2D00085F`, mesh `0x1700142A`, tables
  `0x1D000385` + `0x1D00038B`, side map on `0x100007A2`. Only static user: Tutorial 1 block `0x13CB` (159.2, 37.5)
  yaw 90 = 6.30 m west of the base platform `0x2E000A35` at (5.5, 37.5). Crime Alley's statics (blocks 12BB / 13BB /
  14BB, all world states installed and loaded) have the same neighbours `0x2E00121A` / `0x2E00081F` but no pedestal.
  Spawned by the server (match_map_objects) at (-0.8 / 160.8, 77.5).
- **Turret tables (C data).** Lane turret base table `0x1D000372`: Vfx_Active = child `0x2E000A9E` (attach
  `0x10000052`, scale 0.6, Vfx_Startup; its table `0x1D00060A` = damage phases) + a switch on `0x100007A2` choosing
  particles `0x180006CD` / `CE` / `CB` / `0x18001432`; Vfx_AI_Active = child `0x2E000AA8` (0x67C = 1: the client
  spawns it even for a networked owner; scale 0.9, Vfx_Startup on it); Vfx_Targeting = beam particles
  `0x180006D5`-`D8`, `0x1800143D`. Head table `0x1D00035C` (Vfx_Startup, Vfx_Targeting) has base `0x1D00038B`, whose
  Vfx_Startup / Vfx_Active_* switch on the side (appearance `0x19000A61` / `0x19001299`). The server head never had
  a side, so it took the Null colour (white) (P).

## Unit deaths, the dead slide, the level-up ribbon icon (2026-10-29, fase3-ih)

Tester report 2026-10-29 12:45 (run 12:12-12:24); details in `docs/re-notes/unit-death-slide-levelup.md`.

- **Unit death (C data, C traffic)**: lane drones (`0x40000BF8` / `BFA` / `BF9`, world states `0x2E000808` / `840` /
  `E21`, tables `0x1D0002F8` / `2F9` / `5D3`) and camp creatures (`0x40000CA0` / `CA1`, world state `0x2E000BE2`, table
  `0x1D00042D`; `0x40000CA2` table `0x1D000677`) all hold `_Defeat_OnDead 0x100001FA` and `_Defeat_OnFade 0x100001FE`.
  The minion `_Defeat_OnDead` entry (pack `0xA000006F`) runs `Vfx_OnExplode 0x10000079` (type 0x17) and clears
  `0x100003AF` / `0x100003B0` (type 0x16); the shared class table `0x1D0000E8` has the type 0x14 raise of
  `CbtState_Death_Induce 0x100000AD`. No client code runs `_Defeat_*` (death-animation.md 2.3). ics sent a dead unit only
  its LifeState 2 bundle then 0x3 after `corpse_seconds` (traffic 12:15:02.416 / 12:15:06.4); now `_Defeat_OnDead` +0.15 s,
  `_Defeat_OnFade` +2 s. The fade timing is P.
- **Dead slide (C code + log)**: the client gates orders on LifeState 4 only once it applies the death state (a
  movement state applies 0.1 s after its stamp), so moves sent 65-75 ms after the death bundle reached
  `Session.ev_order`, which had no alive check; `World.walk_to` set a path and `World.tick` moved any entity with a
  destination, dead or not. Now both refuse a dead champion / unit.
- **0x2104 (C, decomp 0xA7E0A0)**: field 2 (after the champion DID) is stored at +0x150 and passed as the first argument
  of `0x88E780` (Flash `Ribbon_CharLevelChanged(didCharacterIcon, name, prev, level, totalXP, pct, nextLevelXP,
  didCharacter)`) when level != prev, and to the summary's `DidCharIcon`. Number order (C from the stored offsets
  +0x120 total / +0x124 to-next / +0x130 pct and the screenshot "720 / 1061997773" = 0.8f): level, prev, total, earned,
  bonus, f32 pct, f32 prev pct, u32 to next (earned / bonus / prev pct positions P).

## Skill animations vs the original: server graph lead, cosmetic tails, stop order (2026-10-29, fase3-ih)

Full evidence: docs/re-notes/skill-animations-vs-original.md (frames of the tester's recording, synced at 12:09:37.4, vs
the original AGL video; traffic of the 12:12-12:24 run).

- **Feed lag (C)**: `CastWorld.run_scriptlet` fed the BGE (`World.graph_feed`) immediately but sent the local champion's
  0x8D `champion_scriptlet_delay` (0.13 s) + a scheduler tick later; the BGE's hooks (code 3 / 5 / 2) therefore fired
  0.13-0.17 s before the client's clip reached them (Meltdown missile 26.406 vs Meltdown_Start 26.414; Scorched Earth
  crater 49.088 vs its graph event 49.094; Grab code 5 at .717 vs start event .715). Bots' 0x8D is not deferred, so they
  were in step. `[ics] graph_feed_at_send` feeds at the send; `_runtime_cast`'s grace waits on `graph_feed_pending`.
- **Cosmetic tails (C)**: skill states hand the rest of their clip to `<skill>_Cosmetic` via `skill_to_cosmetic` (AGL
  Meltdown 0.17 s of 1.0 s, Scorched Earth 0.15 s); the hand-over is the skill state's exit = code 2, and scripts raise
  `skill_to_locomotion` 0x10000002 in their code-2 state (Meltdown 0x340002B4 S2 under NeedCleanup = SetCleanupFlag
  0x100000E2). Every graph out-transition has flags 0 / 16 / 32 (no trigger or initiate intervals), so the client leaves
  the tail at once. `keep_cosmetic_tail` (`cosmetic_until`) is set only by `_graph_cast` (timed path). `[ics]
  graph_cosmetic_tail` / `graph_cosmetic_hold`: GraphInstance.in_cosmetic() drops the script's event during the tail.
- **Stop order (C)**: StopScriptletKey -> `World.signal_scriptlet` sent at once, the start deferred: Vfx_Atm_Glt_Smash_Active
  0x100008AB start 49.095, stop 49.097. `[ics] champion_stop_deferred`.
- **Clip lengths (C / O)**: the character clip table (havok_anim.clip_table) has one entry per clip generator; Gaslight
  Batman's first 6 entries match his generators in object order, then the orders diverge (offset / DFS / BFS give the
  same 26 name-DID conflicts), so lengths still need `diag --anims`.
- **Meltdown target status 0x340002BF (C)**: enter = icon 0x480007B1, hit FX, StartScriptlet 0x10000889; update = pulse
  when PulseTimer (unset = expired) runs out: damage in PulseRange, rad stack, and when RadStackCount == MaxRads - 1 a
  jump LaunchMissile 0x40000484 to the best enemy in JumpRange + RemoveStatus. The run's cast: hit 26.688, pulse .797,
  jump .805, removed .830; the original video's first pulse is ~1 s after the hit (P: the timer started at enter there).

### AGL Q / E / R and the Super Strength lift, fase3-ii (2026-10-29, `re-notes/agl-qer-lift.md`)

- **0x8D run numbers (C, 0x6279D0 step 4)**: an entry whose run number is alive on the object only signals that run; an
  unknown number starts a new run. The Shards sphere's re-sends (`scriptlet_restart`, `resend_looping_after_*`) each
  used a new number, so each restarted the shell's burst; they now reuse the key's last number
  (`[ics] looping_resend_same_run`): nothing happens while the run lives, the run starts again only if it ended.
- **Grab missile world state 0x2E000C4C** (C data): 0x6B4 1.25, 0x7D2 [0x1D0003D2], 0x50F 7, model 0x357 =
  0x17000F70, **no 0x5B5**; the "missing graph template" hypothesis is refuted. Grab_Start 0x10000899 runs
  ArmFade_RemoveHand 0x10000911 (type 8 fade) and particle 0x18000754 at 0.24 s; Grab_Stop runs ArmFade_AddHand
  0x1000093D at 0.06 s. Vfx_Stop 0x10000130 (AGL table @0x1D334) stops Vfx_Active, Grab_Active, Rads_Active,
  Shards_Active, State0/1 and others (type 0x17 with 0x163 = 1).
- **diag --arm budget (C)**: the per-frame beam checks hit tracer's 100-line cap on the map's beams (14:20:01) and the
  intro cinematic's (14:20:06) before any Grab; `--arm` now groups them per beam (entry 0x749960, ecx = beam; ends
  0x74CC05 DRAWN / 0x74CC0C FAILED), one line per beam when its chain changes.
- **Meltdown status 0x340002BF (C log 14:28:21)**: its update chain tests PulseTimer before any StartTimer, so the
  first pulse came 0.1 s after the hit; the original video pulses ~1 s apart starting ~1 s after the impact. ics now
  starts such a timer at its first test with the script's own StartTimer duration (`[ics] status_timer_first_wait`).
- **Lift / throw facing (C traffic 14:21:34.997 / 39.093)**: the facing bundle and the pickup / throw 0x8D went in the
  same millisecond; a movement state is applied 0.1 s after its stamp, an 0x8D at once, so the turn cut the 0.30 s
  rubble pickup and the throw clips (`[ics] liftable_face_lead` 0.13 s).

## Gotham Heights move freeze, map holes, the hover pick (2026-10-29, fase3-ii)

Notes: `docs/re-notes/gh-freeze-holes-picking.md`.
- **Order API 0xA70030 drops a move unsent (C)**: after the may-act gate (0x9CFAF0) and the controller lock
  (`[ecx+0xCC]`), a move / attack-move snaps the clicked Position onto the navmesh with `0x4FB400(champ, pos, out, 0,
  2.5)` (agent shape 0x4F2E40, on-mesh test 0x4FA6E0 in the click's landblock section, 2.5 m search 0x4FA870); a
  failure returns at 0xA700FA. The buffer 0x8686C0 holds a move while `[+0x70]|[+0x74]` != 0 or `[+0x8C]` != -1;
  `[+0x8C]` is set only by the skill-start listener 0x8614D0 (vtables 0x15EDD30 / 0x16035E0, expiry now + 0.24 s) and
  cleared by 0x861520 / the expiry, so it is transient; skill orders are held by 0x863860 when `[+0x70]` != 0.
- **GH (P)**: only one move per run reached the server while skills did; GH's base Doors 0x4000026B / 0x40000269
  (ws 0x2E00084A / 0x2E000845, 20 x 37 x 11 m) stayed all match at a guessed spot and their collision takes the ground
  pick toward the lanes -> the 2.5 m snap fails. `[ics] base_gate_keep_after_open` false removes them after the start.
  `tools/diag.py --moves` breaks at 0xA8A140, 0xA86A47, 0xA70030, 0xA70072, 0xA700F8 (snap + Position at
  `[ebp+0x18]`), 0xA70224 (hold) and 0x88B030.
- **GH terrain (C)**: block 0x80011BF3 is 249.97 m west of x 115 and the 200 m covered level east of x 115-145 (team-2
  floors are statics); the 0 m diagonal (115, 10)-(125, 25) is a designed lava fissure (statics 0x2E000861 at 242.3 m,
  lava overlay 0x2E0005D6 at 245.2 m, lights 0x2E000011 at 246-247.7 m, bridges 0x2E0007AD / 7AE at 250.1 m). No site.
- **Crime Alley south alcove (C)**: (85, 50-65), (90, 55-60) at 0 m, (80, 65) at 195 m; the rim vertex (85, 65) opens
  the south sidewalk x 80-90, y 65-70 (black band under the south stealth field in 46.webp; props there at 199.98-201 m).
  Terrain site `crime_alley_south_alcove_rim` raises it to 199.98 m (CRC 0xBD45_DDC9 -> 0xF230_ADFD).
- **Hover pick 0xA81B30 (C)**: candidates from the render pick 0x75D150 (filter 0xA0E120; flags 1, priority 3) and
  from a swept +-0.8 m box (0x5B27B0, detail 3, query 0x5BCD30 -> 0x598080) against collision parts (flags 2, priority
  1 / 2 / 3 from the hit part type +0x88); `0x100004A4` must be a subset of the flags; candidates below the current
  best's priority are skipped; score 0xA16A60, ties by distance. Why the drones are hard to click is open (notes P2).

## Leash, recall effect, turret warning ring, camp drop icons (2026-10-29, fase3-ij)

Notes: `docs/re-notes/leash-recall-turretring-campicons.md`.
- **Leash (C: no data)**: the only AI parameters are `0x3A000026` GetBestPerceivedTargetInterval_Min / _Max 0.5 / 0.8
  and AIActive, the vision `0x10000133` and the attack's stat 18; no aggro / chase / leash distance exists in the
  data, the exe has no AI strings (units-and-ai.md 5.1). `ics` authors the rule: a lane minion keeps a non-structure
  target only within its acquisition range + `match_minion_chase_margin` and within `match_minion_leash_anchor` m of
  the lane point where it left; the bots do not chase under a free enemy shooter and leash 10 m from the chase start.
- **Recall 0x3400000A (C, script + traffic)**: S2 enter raises Recall_Start `0x100005BA` (a main-machine wildcard only in
  Zod's graph, dropped by the other 53), StartScriptlet `0x10000223` with `0x1000033E` = RecallDuration and fx
  `0x1E00009C` (the channel effect), Fidgets_Disable `0x10000320`, BeginTeleport `0x1000007D`, SetUntargetable
  `0x100000C8`[1], Emote_Abort `0x100001F2` and SetCameraMode `0x1000014B`[1, 5]; S2 exit Fidgets_Enable `0x10000321`,
  EndTeleport `0x1000007F`, StopScriptlet(handle), camera mode 0; S4 Recall_End `0x100005BB`, the teleport
  `0x10000025`(HomePosition), RecordPlayerAction `0x10000108`[8]; S3 (cancel) Recall_Abort `0x100005CF`. The fx run
  went 0.03 s before Fidgets_Disable / Emote_Abort on the same object (traffic 14:31:53.788 / .817); a later scriptlet
  ends a looping run on the client (the Shards sphere case), so the fx is held as a looping key (`start_scriptlet_hold`).
- **Turret warning ring registration 0xA7CA20 (C)**: vtable `0x1605074` slot 1 (event subscription `0x68EDA0` on list
  `[0x186CF14]`, made by the manager ctor `0xA891A0`, built at client start by `0xA91E30`); no direct caller; gates in
  order `0xA7CA29` disabled byte, `0xA7CA33` view-match, entity lookup, `0xA7CA63` `0x9D0180(ent, 0x10)` (unit component
  `[ent+0x84]`: cache `+0xA4`, else property 0x1000019D), `0xA7CA81` 0x10000C5D, `0xA7CA9A` `0x85C130` allied,
  `0xA7CAC6` already registered, then 0x10000C5B / 0x10000C66 / `0x9CFAF0` alive and `0xA7CB23` range `0x9CFC40`
  (cache `+0x8C` initial -1.0, else 0x10000133); `(r + 1)^2 <= 0` refuses (`0xA7CBA5`). The listener `0xA8DFB0` updates
  only registered entries. Our creation bundle lacked 0x1000019D (traffic 15:17:47.403), so no structure registered.
  `tools/diag.py --ring` logs each gate.
- **Jungle heavy drop 0x400005E1 (C)**: spawned by `0x3400007D` S1 (`SpawnEntity [.. 0x400005E1 1 0x1000009C]` with the
  dead creature's own team from GetTeam(SELF)); template `0x10000083` icon `0x130006D3`, `0x100004DA` = 5,
  `0x100006F1` = 6, `0x1000019D` = 4, `0x10000D8B` = 0x80000, world state `0x2E000FBB` (common tables + `_Upgrade_Loot`,
  `_SUpgradeSystem_OnCurrencyGained`, `Vfx_Item_*`), no entity script. Nothing collected or removed it.

### Gotham Heights base Door: obstruction box, floor copy, pads, intro bindings (2026-10-29, fase3-ij)

Details: `docs/re-notes/gh-ca-floor-spawn.md`.
- **Right-click ground point (C)**: 0xA86A00 -> 0xA12510 / 0xA12280 (camera ray) -> 0xA12590 intersects the ray with
  the horizontal plane at the champion's height; no collision pick. A move is lost only at the navmesh snap of the
  order API 0xA70030 (0x4FB400 -> 0x4FA870, 2.5 m) or the earlier gates.
- **AIObstructionComponent (C)**: built by 0x606400 when 0x83C == 1 (0x6063C0); 0x5561D0 -> 0x555E20 reads the shape
  0x8C1 (1 prism 0x8B1 via 0x555240, **2 box via 0x554EB0**: table 0x8AA {0x858 min, 0x857 max}, + offset 0x85C,
  rotated by 0x856 degrees, scaled by the entity scale; 5 0x555820; 6 physics mesh 0x588360).
- **GH Door 0x2E00084A / 0x2E000845 (C data)**: box (-30, -30, 0)..(30, 7.93 / 1.8, 4), yaw 248.41 / 110.39. At ics's
  (26, 54) yaw 180 it seals both base exits and the core platform and ends at the base pocket (P: the original
  pre-start seal). The client drops moves inside it; Object_Open does not lift it; removing the door does (first
  move 0.23 s after the removal, C). fase3-ij replaces the door at the start with a copy carrying 0x83C / 0x8C1 = 0
  in its bundle (`[ics] base_gate_floor_copy`, P that the bundle wins).
- **Capture pads (C)**: static 0x2E0008D5 (type 7, yaw 180) under each GH point: SW (49.45, 26.5), SE (111.72, 26.99),
  W (26.91, 90.47), N (80.0, 127.93), E (133.1, 90.1) (`[ics] match_capture_on_pads`).
- **Cinematic bindings (C, 0xA9C610)**: with flags bit 1 and A = 0 only the entry equal to the local champion is
  rewritten (key 1); other entries keep the key the server sends, so allies go out as 0x10000001..4 for the PvP
  intros' Player01..04 actors (`[ics] cinematic_bind_allies`).

## Grab beam ends, AGL's palm, a thrown object's pitch (2026-10-29, fase3-il, `re-notes/agl-arm-meteor-vehicle-tilt.md`)

- Grab's type 2 beam (C, diag 17:32-17:42 + traffic IIDs): source = the Grab missile, target = AGL (0x100004E2), every
  end check ok and the draw pass 0x74CC05 reached for all six casts. A beam with both ends = AGL is AGL's own (P: the
  passive Vfx_Atm_Glt_Rads_Active 0x10000887), 6-8 s after load, model not active during the intro. The beam's
  particles spawn in 0x7480A0 only with a loaded particle record (checks 0x7481A9 / 0x7481B6) and a count > 0
  (0x748226; loop 0x748231 -> 0x7423F0 at 0x748313) (C code; O whether they spawn for Grab).
- Attach point 0x100000B0 of AGL (`.entity` 0x2D0009A9, pack 0xA0000151 @0x11B6BC): bone 31 RWeapon, position 0,
  quaternion (0.717, 0.142, -0.662, -0.163) (C). Forward kinematics over pack 0xA0000150's clips: in 0x1A001131-36
  (P: the rubble Hold blend) the bone is at right 0.5-0.85, forward 0.1-1.0, up 2.2-2.6 m. ics carries the rock there.
- 0xB0 motion bits 0x400 (s16 facing pitch) and 0x4000 (s16 roll), rad * 10000, follow the facing yaw (C reader
  0x57E530; orientation 0xAF2D00). ics sends a pitch on a thrown vehicle's flight states (`[ics] liftable_throw_pitch`);
  the sign on screen is P.
- The rock's table 0x1D0004FB (pack 0xA0000162): Vfx_PickUp 0x1000023A = type 0x17 on Vfx_Active (flag 1, P stop);
  no entry turns the rock (P). SuperStrength_Rubble_Active 0x10000775 is not in AGL's tables (C), so the client drops it.

### Fog occluders, the turret ring's Player gate, announcer overlap (2026-10-29, fase3-il, `re-notes/ca-fog-ring-announcer.md`)

- Fog occluders (C code): 0xAB0C60 builds, per vision source, an AABB phantom (`0xEB7FF0`, filter info 0x10009) of the
  source's circle at its height + 0.25 m; 0xAAE0E0 draws the circle, then (unless `0x974940(source, 0x100008CE)` =
  attribute "vision ignores blockers", the foundries 0x4000016F / 0x40000170 carry it) walks the phantom's overlapping
  collidables (+0xC0 / +0xC4), reads each body's properties (`0x573050`: keys 1, 0, 5, 6 = IID) and draws it
  (`0xE600D0`, Havok query into the fog collector +0x100) unless 0xADA050 says skip. 0xADA050 ends in 0xA4B920(source,
  body entity): skip if 0x1000062E; occlude if **0x10000623** (entities: liftable vehicles 0x4000045D / 0x4000081B) or,
  for a map static (IID top byte 1 / 5, `0x4DAFF0`), if **0x7EB** is 7 or 8. Server objects (top byte 2) occlude only
  with 0x10000623.
- On this client the pass blackens the ground between the source and the blocker (C screenshots 56 / 57 against the
  sources logged by `diag --fog`; why it is inverted is O). `[ics] vision_through_blockers` sets 0x100008CE on the allied
  sources by 0x20F0 op 6 (P: an attribute read through the unit component's modifier list, 0x973730).
- Turret warning ring (C code + diag): registration 0xA7CA20 succeeded for the enemy core / turrets (17:33:40); each
  frame 0xA8C960 -> 0xA84FB0 gives state 6 (hidden) while entry +0x4C is 0. The ring phantom built in 0xA2A710 (filter
  0x210000) calls 0xA3A5F0 on enter / leave: a Minion 0x10000 (not Pet 0x100000) goes into the list +0x3C; an entity
  with **Player 0x200000** whose IID is the local champion (0x85D6D0) sets +0x4C. PerceivedTypeList: Player 0x200000,
  Pet 0x100000, AutomatedPlayer 0x8000. Other client tests use 0x200008 (Character | Player), so 8 | 0x200000 keeps them.
- Announcer (C traffic, P client): the server sent wave + jungle lines in the same millisecond and the tester hears
  them together (0x2039 handler 0xA77DA0 -> 0xA596B0 -> 0xA0A960; channels 1 / 3 and 2 are separate players; no
  client-side wait between items was found, O). ics queues them (`Match.voice_out`, `[ics] announcer_queue`).

## Vehicle lift / throw skips, the missing vehicle destruction, the basic-attack chase (2026-10-29, fase3-im)

Tester report 2026-10-29 18:31. Details and evidence: `re-notes/liftable-throw-destruction.md`,
`re-notes/basic-attack-chase-range.md`.

- Lift (C graph data): AGL's `SM_SuperStrength_Car` Pickup_Start plays car_pickup.hkx 0 -> 0.45 s (cropEnd 0.783 of
  the 1.233 s clip 0x1A00082D) and holds; CarPickup's **Instant** transition to Car_Pickup restarts the same clip at
  0.45. CarPickup at 0.05 s jumped the clip 0.05 -> 0.45 (the skipped bend). `[ics] liftable_car_pickup_at = "graph"`.
- Throw (C traffic): the throw's turn went as a full champion bundle inside Hold (delta mode falls back to a bundle
  when a table changed); now the movement state alone (`liftable_throw_face_motion_only`).
- Destruction (C code): 0x8A `0x632370` -> sphere query `0x631C50` (`0x5CEA30`; pieces `0x631B00`, destructible
  entities `0x631940`) -> `0x631FA0` (only with hits) -> `0x62F290` / `0x62BEF0` / `0x62BC00`: piece health (+0x44) minus
  the magnitude, break at <= 0. Piece bodies are made at the entity's frame by 0x8B (`0x630FC0` / `0x62DBA0`) and the
  component's update (`0x6305A0` / `0x62E660`) does not move them: the last build was at the launch. 0x8B now goes on
  the landing frame before the impulse (`liftable_land_rebuild`), the launch's 0x8B only for an attached object.
- DestroyEntity (0x10000010) plays `_HFSM_DestroyEntityAction` + `_HFSM_DestroyEntityAction_Optional` (0x10001128); the
  vehicles hold only the Optional one (table 0x1D00034B, one type-0x1F action on 0x10000623, P the fog-occluder flag).
  Played at 0x3400015F S4 (landing + 0.15 s) and on Consume (`liftable_land_destroy_after`, `liftable_destroy_actions`).
- Basic-attack chase (C): the client validator `0x9D01D0` step 11 = skill range + both radii (`0x5897A0`); melee basics
  have stat 18 = 1.0 m (26 of 54), less than two champion bodies, so a fleeing target was never "in range". A champion's
  reach now adds both radii (`attack_range_radii`, `attack_body_radius`).

## Fog attribute base values, jungle-mouth fields on the drawn walls, the hover pick's outline (2026-10-29, fase3-im, `re-notes/ca-fog-stealth-hover.md`)

- Attribute reads (C): `0x974940` -> `0x973730` asks the unit component's vt+0x60 (`0x970B80` = `0x58B1C0(entity,
  id)`, the entity's own property) for a **base value** and applies the 0x20F0 modifiers (own hash, per-team table,
  `0x96D460`) only when one exists; otherwise it returns the caller's default. fase3-il's `0x100008CE` set modifier
  therefore did nothing on champions / turrets / minions (no template has the property; the foundries do).
  `[ics] vision_through_blockers_property`: the property itself = true by 0x6 before the modifier.
- Crime Alley jungle-mouth fields (C statics): the drawn walls stand 0.18-0.37 m behind the navmesh faces the
  fase3-if tiles were laid on (west pillar face x 52.90, east chain-link side panel x 106.95, east garden panels
  157 deg + 0.10 m). `[ics] match_stealth_render_faces`: tiles (51.9, 85.2) / (107.95, 85.2) yaw 90 and (105.66, 87.16)
  yaw 157 (maps.py "render"); the west diagonal already lay on the brick pillars.
- Hover outline (C): selection tick `0xA88700` -> pick `0xA81B30` -> champion property 0x3CB -> listener `0xA5D5F0`
  -> `0xA4EDD0` (colour `0xA1D020`: hover (0, 1, 0, 1) at `0x186D9D8`, alive only) -> client properties 0x974 / 0x973 /
  0x975 -> render listener `0x625250` -> `0x61EC00`. The outline needs nothing but the pick. Scores `0xA16A60`: other
  unit 15 (5 when found by the render ray only) + relation bonus + 0x100001C3 / 10, own champion 5 + 0x1C3 / 10.
  18:31 traffic: 107 of 1 463 move orders carried a pick of our own champion or an ally, 1 356 none: enemies are
  found by the render ray alone (P; why the +-0.8 m box sweep misses them is O). `[ics] click_assist_radius`
  (`Session._click_assist`) turns a move order next to a visible enemy into the attack; `tools\diag.py --hover`
  logs the tick's pick and every candidate's flags / priority / score.

## Crash on a 0x42 to Supergirl's Firewall, hover picks in the fase3-im run (2026-10-29, fase3-in, `re-notes/vitals-crash-hover-picks.md`)

- Crash 19:55:11 (C): access violation at rva 0x6B1BD9 = VA **0xAB1BD9** (`inc [ecx+0x98]`, `ecx = 0`), 4th instruction
  of 0xAB1BD0, called by **0xAB2880** with `this = [entity+0x80]` (the vitals component, no null check), called by
  0x8C26F0, the executor of server event **0x42 Vitals**. traffic.log 19:55:11.454: the server's only 0x42 to a spawned
  object, `0x40000bef of AI: Arcane Supergirl vitals 0/1`: Arcane Supergirl's Firewall 0x40000BEF (stat block health
  1.0, template without PerceivedType 0x1000019D) hit by AGL's Scorched Earth. The client builds the vitals component
  only for `0x1000019D & 0x7F59FB` at construction (full-entities-engine.md 4). Same rva as the 2026-10-25 23:22 crash
  (jungle drop 0x400005E1, PerceivedType 4). Not caused by the debugger nor by 0x100008CE.
- Fix: `World.vitals_component` (template PerceivedType | sent 0x1000019D, & 0x7F59FB) gates 0x42 and turns
  `client_vitals` off (`[ics] vitals_need_perceived_type`); `CastWorld.spawn_entity` makes such a spawned object with
  no attack inert (`[ics] spawned_need_vitals_component`). Every map's units / structures / bots still pass (headless).
- Hover (C log): enemy minions and Supergirl got flags 0x2 / 0x3 and were picked by the tick 0xA88784; 131 attack
  orders on enemies came from the client's own pick, 7 from `click_assist`. `tools\tracer.py`'s `ev` now parses `-`
  offsets (`[ebp-24]` printed "?"); `--hover` also logs `best_score` `[ebp-2c]` (win = score > best, 0xA822A7).

## Turret ring and fog attribute wiped by full bundles, sight line through objects, mouth fields toward the lane (2026-10-29, fase3-in, `re-notes/ca-ring-fog-bundles.md`)

- Common cause (C): with `object_update_mode` "bundle" a moving champion / minion gets a full bundle every tick, and its
  0xBC diff (`0x62AFD0`) removes own net-1/3 ids it omits or resets them to the template value. The champion's
  `0x1000019D` = 0x200008 (Player bit for the ring) and `0x100008CE` (fog: no occluder pass) were set by 0x6 only at
  19:48:32.161 and gone with the next bundle (19:48:39.968, 1532 bytes, neither id). Fix: both ride in the object's
  bundles (`[ics] champion_flags_in_bundle`, `vision_through_blockers_in_bundle`).
- Ring (C code): entry +0x4C is written only by the ring phantom's callback **0xA3A5F0** (Minion 0x10000 -> unit list;
  else Player 0x200000 test at 0xA3A695 + local champion IID 0x85D6D0 -> `[entry+0x4C]` at 0xA3A6C5). The phantom
  (0xA2A710) filters team / relation 2 / PerceivedType mask 0x210000. Option byte 0x186CE4F is 1 in .data.
  `diag --ring` logs the callback (rva 0x63A5F0 / 0x63A69D / 0x63A6C5).
- Fog attribute read (C, correction): vtable 0x1609B78 slot +0x60 = **0xA9DC90** (`0x58B320` variant read of the
  entity's own property, container [ent+0x38]); 0x970B80 is slot +0x5C. Base value missing -> default false.
  `diag --fog` logs the occluder decision per source (rva 0x6AE209, al = attribute) and each kept occluder body
  (rva 0x6AE32E, body type / IID at [ebp-0x44] / [ebp-0x40]).
- Black strip (C): not terrain: installed heights flat at 199-200 m over x 40-105, y 55-100 except (60, 75) / (65, 75)
  (under the lane mesh); baked texture `0x13003439` has the curb and bricks; pure-black pixels with sharp edges as the
  occluder wedge of 57.webp. The stealth world states 0x2E000D36 / 0x2E000D37 carry 0x7EB = 7, but server objects
  occlude only with 0x10000623 (0xA4B920).
- Server fog (C): the sight line ran on the match navmesh copy where structures (3.2 m squares), vehicles and gates
  are blocked cells (value 2), so an enemy behind our own lane turret stayed hidden on lit ground.
  `NavGrid.line_clear(through_objects=True)` (`[ics] fog_line_through_objects`).
- Stealth (P camera): screen down = -y; the vertical jungle-mouth tiles move 1.0 m toward the lane
  (`maps.py` "lane_dir", `[ics] match_stealth_lane_shift`): centres (51.9, 84.2) / (107.95, 84.2).

## Carry snap, the throw press, the landed vehicle's break keys, minion facing (2026-10-29, fase3-in, `re-notes/liftable-carry-throw-press.md`, `re-notes/minion-attack-facing.md`)

- Press path (C): 0x20EA comes from `0xa26420` (targeting start; needs controller `+0x110` == 0 and `+0xF0` == -1, sets
  `+0xEC`) or from the dispatcher `0xa85da0`'s cancel branches (`0xa23510`); CanActivate `0x8709e0` runs before it.
  The order follows on the release: `0xa76320` / the dispatcher switch on targeting type `0x1000003D` (type 13 =
  line: the cursor pick `0xa19e50(.., 1, 0, ..)` fails when the champion's position block has no valid cell) ->
  `0xa70030` -> `0xa70600` -> `0xa25d80` (`0x100006AB` no navmesh snap, `0x100006D5` range clamp, minimum distance)
  -> `0x8686c0` -> `0x863860` (hold rules; buffer `+0x78` = current action slot, written only by S->C **0x2083**
  `0xa1a5a0`) -> 0x20EE. The dispatcher ignores a press of the slot in champion property `0x100006B4` unless the skill
  has `0x100006B3`. Per-skill cast mode `0x10000937` (`0x85fe60`), else the global setting.
- Run 19:52 (C traffic): 13 slot-7 presses of a carried rock reached the server as 0x20EA with no 0x20EE; the rock's
  indicator (0x2180 / 0x20F9 0) had gone 0.7 s before the slot's kept-ready 0x20F8, the reverse of the vehicle carry
  that threw. Which gate refused is O (`diag --throwpress`). `[ics] liftable_indicator_after_cooldown`,
  `liftable_throw_on_press` / `liftable_throw_press_window` (second unanswered press throws toward the facing).
- Graph (C): AGL's `SuperStrength_Rubble_Pickup` has a code-2 trigger with did 0x34000177 (the rubble throw script)
  at 0.37 s; `SuperStrength_Car_Pickup` has none.
- Carry (C server code + `client-movement.md` 1.3): carried objects went only on a course change / every 0.5 s, each
  within 2 m, i.e. steered by the body velocity that drops the height over the head. `[ics] liftable_carry_snap`
  (newer teleport sequence per carry state) and `liftable_carry_resend` 0.05 s.
- 0x8A (C): the reader `0x445c90` copies the magnitude's 4 bytes raw and `0x62BC00` subtracts them as an int (10.0f =
  0x41200000: any piece reached breaks); `0x631B00` / `0x631940` skip an owner whose position has no valid cell;
  `0x631FA0` runs only with hits; `0x62BEF0` skips a piece with flags +0x194 bit 0. Break keys: truck 0x1D000612, SUV
  0x1D0001FD (Destructible_OnBreak_*_T1 0x10000332-0x10000335 / 0x1000051D, Destructible_OnCompletelyDestroyed
  0x10000290). `[ics] liftable_land_break_keys` / `liftable_land_break_after` (P fallback); `diag --destruction` logs
  the impulse, scans, hits and piece damage.
- Minions (C): `Units.act` sent the stop state before turning toward the target and never sent a standing unit's
  turns; with the attack script falling back to `_direct_attack` no FaceTarget runs. `[ics] match_attack_face_turn`.

## Power Core Turret, the core's shield ring, elites while it is down, more parked vehicles (2026-10-29, fase3-in, `re-notes/power-core-turret.md`)

- Source: the tester's frames of the original Crime Alley v AI video (66 / 67: a turret on the core platform's prow and
  a rotating ring round the core; 70: "The enemy's Power Core Turret has been destroyed!" = event 55, its remains = base
  with the team's dot and two fallen rings, no ring round the red core any more; 64 / 65 / 68: parked vehicles).
- Structure (C classes, G position): v AI `0x40000C8F` (ws `0x2E000AC4`, 3500 HP, `0x10000B84` 35) / team 2
  `0x40000C8D` (ws `0x2E000AA0`, 3000 HP, 15); range `0x10000133` 9, warning ring `0x10000C5D` 1, credits formula
  `0x10000689` (the dampener has none). No pack places `0x2E000AC4` or the classes (all-pack scan: only their own
  records). Position (27.0, 77.5) / (133.0, 77.5) from the frames (57 px/m), `[ics] match_structure_pos`; spawned again
  (`match_skip_roles` {}). Protection order unchanged (P): inner turret -> Power Core Turret -> core.
- Shield (C keys, P look): core table `0x1D00098A` Vfx_Indestructible `0x1000008E` = one type-35 action spawning child
  `0x2E000A3A` (entity `0x2D000863`, next to the core pedestal's `0x2D000864`); Vfx_Indestructible_Stop `0x1000013D` =
  type 23 stop of `0x1000008E` + side-switched particles. `[ics] match_core_shield` plays them on the core while its
  Power Core Turret lives / when it falls / when it respawns.
- Death (C table): `0x1D00035F` _Defeat_OnDead `0x100001FA` = stop Vfx_OnExplode, type 20 graph event Death
  `0x100001C0` (graph `0x1C000069`), then Vfx_Destruct_State0 (particles `0x18000B50`, side switch). The client never
  runs it itself; `[ics] match_structure_death_scriptlets` / `match_keep_body_roles` (body kept until the respawn,
  `match_core_turret_respawn` G 300 s: no respawn time in the template or the scripts).
- Supers (C classes, P rule): Crime Alley's packs hold no Destroyer Drone; the v AI minion family `0x40000C9A`-`C9E`
  (numbered between the v AI structures and jungle) has Elite Trooper `0x40000C9B` / Elite Soldier `0x40000C9C` with the
  `0x400000` flag (as GD's Destroyer / elites). `[ics] match_core_turret_supers`.
- Vehicles (C: no Crime Alley pack places a vehicle; G positions): `[ics] liftable_props_added_by_map` police car
  `0x40000459` (124.5, 81.9) yaw 90, gaslight pickup `0x4000081A` (52.4, 72.8) yaw 270, sports car `0x40000454` (107.4,
  72.8) yaw 90; the blue-base mirror of the police car is off (no frame).

## Minion aggro indicator, the recall FX template, the 0x2080 word order (2026-10-29, fase3-io, `re-notes/aggro-recall-scorepanel.md`)

- **Aggro indicator (C data, P meaning).** The common unit table `0x1D0000E8` holds `CbtState_Aggro 0x10000D61` (a 0.5 s
  type-8 overlay, material `0x170011FB`) and `CbtState_Aggro_Active 0x10000D62` (type `0x2E` x2 and a persistent type-8
  overlay, material `0x17001A92`, gold `0xFF783A04` for enemies / blue `0xFF1B53FF` for allies), each behind a `0x22`
  container on `0x100000CE == 1` and one on the team colour `0x100007A2`. `0x100000CE` is written by the client at
  `0xA16730` (false on the old, true on the new object: the controlled agent, P) and turns HUD vital notices on
  (`0xAAFCD0`). ics runs both keys on a minion that targets the local champion with `0x100000CE = 1` as a run variable
  and stops them by `0x11F` when it drops him (`[ics] match_aggro_roles`, `match_aggro_flag`, `match_aggro_flag_mode`,
  `match_aggro_scriptlets`). The switch rule itself (`champion_aggressor`) was already there.
- **Recall FX template `0x1E00009C` (C words).** Unplaced record of pack `0xA00000B3` (@`0x3D85A8`): particle
  `0x180001F2`, lights, sounds behind `0x100000CE == 1`, a container timed by `0x1000033E`, a type-3 spawn naming FX
  `0x1E00037F` / `0x1E000380` / `0x1E00037E` (particles `0x18000A3A` / `39`, `0x18000A4D`; duration `0x100008D7` <-
  `0x1000033E`), and a type-8 overlay `0x170011FB`. P: the six converging streaks are that spawn; why it does not show is
  open (no server change).
- **0x2080 (C).** Handler `0xA7DFB0` calls Flash `SendAccountEndOfMatchLevelAndXP` (`0x8908D0`) with wire words
  `(w0, w1, w5, w2, w3, w4, w6, w7)` and the header's `SendAccountLevelAndXP` (`0x891200`) with `(w0, w2, w6, w5)`: the
  wire order is level | prev | total | earned | bonus | to next | f32 pct | f32 prev pct (`[ics] account_level_layout`).
  The original's panel shows cumulative XP / cumulative XP of the next level (`[ics] xp_numbers`). The rewards panel of
  this client is the scorecard's Accolades tab (`ScorecardAccolades`: Merits, champion, protector, map + duration).

## Meteorite tint, Super Strength's input back, the throw's velocity, Vfx_OnExplode deletes a vehicle (2026-10-29, fase3-io, `re-notes/liftable-aura-lift-throw-break.md`)

- **Vfx_OnExplode on a destructible vehicle (C).** Table `0x1D00034B`: action type **0x29** (execute `0x530FA0`: per
  destruction piece, from `0x4F5C20(0x801)` or the destruction component's vfunc +0x5C) with a child **0x28** (execute
  `0x65C7D0`: `(entity+0x58)->vfunc+0x4C(sub-entity)`). CDestructionComponent (ctor `0x62F800`, vtable `0x15CA670`)
  +0x4C = `0x62ED00` -> `0x62EBF0`: the piece's render instance (+0x15C) and physics body (+0x188) are destroyed and it
  leaves the active list; with none left, record+0x70's scriptlet runs. The vehicle (drawn only through its active
  pieces) vanishes, and a 0x8A sent after it finds no piece body (diag 21:08:27 / 21:10:18: piece bodies 0, entities 0).
  ics no longer sends it at the landing (`[ics] liftable_land_scriptlets`, `liftable_land_explode`).
- **Destructible_IgnoreAOI** sets property `0x8FA`; `0x62FB20` (0x10D / 0x138 piece state) clears all pieces when set (C).
- **Super Strength's input back (C scripts).** `0x34000161` S7 (toss) and `0x34000177` S3 (grab) raise `0x100000BB` on
  `0x34000164`; S7 -> S9 also on `0x10000002`, raised by the lob's script `0x34000160` when it lands (TossDuration 0.3,
  CatchDuration 0.35 are only the timers). `[ics] liftable_input_back`, `liftable_toss_seconds` 0.3.
- **0xB0 motion bit 0x40 (C reader `0x57E530`):** an f32 after the speed (+0x4C), the velocity's pitch:
  v = (cos h cos p, sin h cos p, sin p) * speed (`0x57DA90`). `movement_block(vel_pitch=)`; thrown objects send the
  curve's 3D velocity at each state's own time (`[ics] liftable_throw_velocity`).
- **Meteorite tint (C data, P that it is the original's red).** ws `0x2E000D22` table `0x1D000385`
  (`_Entity_OnSetClientRelationship` on `0x100007A2`), children `0x2E000D13` / `D14` table `0x1D00038B` (Vfx_Startup,
  Vfx_Active_Red / Purple / Blue on appearance `0x19001299`); base `0x2E000D25` table `0x1D0004AA` = Vfx_Active_State1-3 /
  Vfx_Stop only. ics: override `0x10000CF0 = 5` + PVP_Team 3 -> 0 on the ground, team 3 lifted (`[ics] liftable_aura`);
  base State1 at spawn.
- **Throw press (C diag):** the meteorite threw at the first press (21:06:23, quick cast type 0xD, hold check passed)
  with the fase3-in indicator order.

## Crime Alley structures and vehicles, second pass (2026-10-29 21:10, `re-notes/power-core-turret.md` 8)

- **Three structures a side (C frames).** Original frames 72 / 77 / 64 / 70: x 65 / 95 lane turret on the gear plate, x
  40 / 120 a turret on a round ring pedestal with a dark legged body and the stacked ring hologram (it fires), the Power
  Core Turret on the core platform's prow (its remains stay there, frame 70). The x 40 / 120 one is the **dampener
  class** `0x40000C88` / `0x40000C87` (world state `0x2E000E04`, rig ring + body + six legs, attack `0x34000014`, 3000 HP;
  table `0x1D00063A`: Vfx_Active child `0x2E000A9E`, Vfx_AI_Active head `0x2E000AA8` scale 0.75). `[ics]
  match_role_swaps` {} puts it back (the 2026-10-28 lane-turret swap was made over the then-black socket).
- **Supers on the second structure.** `[ics] match_supers_on_structure_down` (map -> roles, melee, ranged): while the
  enemy's dampener (or inner turret) on the lane is down, the waves bring Elite Soldier `0x40000C9C` / Elite Trooper
  `0x40000C9B` until it respawns (`match_dampener_respawn`); `match_core_turret_supers` {} (fase3-in rule off).
- **Power Core Turret body (C table, P cause).** Base table `0x1D000374` is the only turret table with Vfx_Fade_In
  `0x10000033` (type-5 group: type-35 render action, then type-23 stop of Vfx_Fade_Out `0x1000006A`); in game only the
  `0x2E000AC3` hologram showed (frame 71). Vfx_Fade_In is sent before Vfx_Active / Vfx_AI_Active.
- **Turret heads (C tables, P effect).** The original's head is the body's Vfx_AI_Active child (type-12 action, field
  0x325 = Vfx_Startup `0x1000018E` only). The head's base table `0x1D00038B` Vfx_Active_Red / _Blue / _Purple set
  appearance `0x19001299` group 0x10000002 to 0x10000002 / 1 / 3 (materials `0x16002113` / `0x16002112` / `0x16002289`);
  Vfx_Startup picks the team colour (appearance `0x19000A61` group 0x10000004, and a type-34 overlay mesh `0x1700132C`
  coloured by side 0x100007A2). ics sent Vfx_Active_* to its own heads at spawn and at each target loss; `[ics]
  match_turret_head_team_keys` false stops that (P: the faint look).
- **Vehicles (G).** Frame 72: dark gaslight truck `0x4000081B` / `0x2E000F04` at (35.5, 81.85) yaw 270; frames 65 / 76: the
  red car with a white top is not the sports car `0x2E000559` (white in game): gaslight convertible `0x4000081C` /
  `0x2E000F05` at (107.4, 72.8) yaw 90 (G; the arrow cart `0x40000C40` is the last untried class). The police car
  `0x40000459` was created and built its 7 intact pieces (diag `--destruction`, iid `0x...138`); P not seen because the
  camera never reached the red base's north curb. Crime Alley's packs hold only seven vehicle world states.

## Fog occluder pass from our structures, the ring phantom's IID filter, minimap visibility, camp icons (2026-10-29 21:10, fase3-io, `re-notes/ca-fog-minimap-ring.md`)

- **Fence strip (C diag `--fog`).** With fase3-in AGL's circle skips the occluder pass (al 1 from 21:05:00) and every AGL
  bundle carries `0x100008CE` and `0x1000019D = 0x200008`. Our core / core turret / inner / lane turrets (`0x...101 /
  103 / 105 / 10B`) ran it all match (al 0) against the map static `0x01113BB0000000B8` although each got `0x100008CE =
  true` by 0x6 at 21:04:58 and was never re-bundled; the foundry (template value) skipped it. Their templates declare the
  id without a value (`ce080010 ce080050`). `[ics] vision_through_blockers_at_creation`: the value rides in an allied
  structure's creation bundle (merged into the creation desc like a template value). O: why the 0x6 base was not read.
- **Ring phantom filter (C disassembly, diag `--ring`: 4 enemy structures registered, 0 phantom callbacks).** 0xA2A710's
  phantom uses filter class `0x15ECA98` (ctor 0x8528F0; slot +0x28 = 0x852210: 0x852110, PerceivedType mask 0x210000,
  team relation 2). **0x852110 refuses any body whose IID top byte is 2** (`0x4DAF10`, jne at va 0x852146), and top byte
  2 is a player object (0x8631A0 owner walk, 0xA16730). ics objects are all top byte 2, so no unit ever entered.
  Exe patch at file offset `0x451544` (jne -> nops; `[game] exe_patch_skip`). The phantom's listener vtable is
  `0x1602318` (slot 9 0xA5E270 enter, slot 10 0xA5E2A0 leave -> 0xA3A5F0). Same filter class: 0x9C24C0, 0x9CCE60,
  0xA93470.
- **Minimap notes (C).** 0xA4BD80 adds a note only while `0x2A1` is true; 0xA5B190 (map manager entity hook) watches
  0x2A1 / 0x100004DA / LifeState / 0x10000B2D / 0x10000548. 0x90F hides only the model. `[ics] fog_hide_minimap`:
  enemies out of sight get 0x2A1 false, except unit flags 0x400000 (super minions `0x40000C9C` / `0x40000C9B` = 0x410000).
- **Camp / centre icons (C Flash + data, G icon).** Flash `MapNote.UpdateForPerceivedType`: categories 8 / 26 / 27
  without an icon draw the capture-point border (neutral tint 0xCCCC33); 9 / 31 / 3 / 30 tint the icon (neutral
  0xCCCC33, unknown 0xCCCCCC). The nook pad `0x4000089D` (template 26, `0x100007D8` 1) was the yellow circle at our
  centre: sent 0 (`[ics] match_nook_pad_map_note`). No camp marker exists in the data; the Heavy Tripod `0x40000CA1`
  carries 9 + minion icon `0x13000141` (`[ics] match_camp_map_notes`). In 78.png the yellow ring on the lane is the
  local player's YouAreHereEffect.

## The centre strip is the street piece's fog occluder; the turret ring's remaining gates (2026-10-29 23:03, fase3-ip, `re-notes/ca-street-occluder-ring.md`)

- **Black strip by the fence (C data, C mechanism, P source).** `83.webp` (Batman, another spot than AGL's `49.webp`)
  shows the same strip x 70.05-76.3, y 81.8-83.4 with the same west edge (slope 0.74): fixed in the world. Terrain is
  patched there and no static covers it. The fase3-io `--fog` diag named one occluder body for every source,
  `0x01113BB0000000B8` = map static #0xB8 of 13BB = **world state `0x2E001207`** at (17, 77.5, 199.78), the whole-lane
  collision piece (no render geometry) with **`0x7EB = 7`** (vision blocker for `0xA4B920`). The pass `0xAAE0E0` (query
  box (r, r, 0.001) at source + 0.25 m) fills the region between the source and that body; our structures' circles never
  skipped it (attribute 0x100008CE by 0x6 or in the creation bundle: al 0 / strip unchanged). Exe patch file offset
  `0x6AD624`: the cmp/jne at va 0xaae224 -> jmp 0xaae36a (the skip branch) for every source; `[game] exe_patch_skip
  ["fog occluder pass"]`.
- **Turret ring (C code, O runtime).** The perception-filter patch is in `InfiniteCrisis_patched.exe` (0x451544
  `84 c0 90 90`). Rest of filter `0x852210`: `0x852110` (entity, top byte 2, `0x403`, base filter `0x5BC020` with empty
  lists), PerceivedType & `0x210000`, relation `0x853380(+0x68, body team) & 2`; ctor `0x8528F0` leaves +0x58 = 0, +0x74 = 0.
  Team = unit component cache +0x4C (ctor `0x979170` -1; watcher vtable `0x15F97F0` stores kind-0x10 notifies only);
  -1 on either side = relation 2 (passes). Registration entry fields from `0xA7CA20` (+8 0x10000C5B, +0x10 0x10000C66,
  +0x20 r ... +0x34). Draw `0xA84FB0`: ring effect DID from `0x439E00(&out, 0x100000E4, 0xF)`, object `0xA12E50` ->
  `0xA33F40` (+0x1C), state change plays 0x1000103D. Server side is complete; whether the Havok phantom pairs with the
  local champion's body is O. `diag --ring` adds probes 0x452220 / 0x45227A / 0x45228E (filter gates) and 0x685294 /
  0x6852F5 / 0x68535A (effect DID, ring object, state change).

## The ring's phantom never reports a body; the fence strip is not the occluder pass (2026-10-30, tester report 11:23, `re-notes/ca-ring-phantom-strip.md`)

- **Ring (C diag, P cause).** The 11:05 `diag --ring` was attached at 11:07:25, after the structures' bundles (11:06:21),
  so their registrations are missing; its 346 "entity added" lines are camps and minions (al 0 = not a turret, right;
  0x100 / 0x10000 are eax's upper bytes). Not one call of the filter `0x852210` (probe 0x452220 follows its first call)
  in 16 minutes: the ring's phantom never paired with anything (not created, or the units have no collidable it sees).
  New probes: 0x62AAF6 (the physics service's create call in 0xA2A710: eax = its implementation), 0x62AAF8 (handle vs
  the null id 0x1B67EE0), 0x57978F (a unit's own perception phantom 0x9793F0, key 0x4934AE2, created or not). The diag
  must run from the menu, before Launch.
- **Strip (C).** With the occluder loop jumped over (patched exe read back), `0xAAE0E0` only resets the collector
  (`0xAA5170`: octagon of the radius) for every source, and the strip stays: the occluder pass is not its cause (the
  patch is harmless; `[game] exe_patch_skip = ["fog occluder pass"]` restores it). The fog base bake reads terrain map
  layer 0x10000002 (`0x586140` over hash `0x1B67B90`, filled by `0x586B00` from property **0x84A** of the statics
  record: `0x847` origin, `0x848` extents, `0x846` layer id, `0x849` image); on 13BB it is **`0x3E00000D`** (64 x 64
  A8R8G8B8 over 160 m) with red 0 in every texel: nothing is baked dark. Compose `0xAAB3B0` clears to white and draws
  each source as a fan, rim vertices (0, 1, 0, 1), clipped (1, 0, 0, 1). Open: fog vs light / geometry; `diag --nofog`
  (EnableFog off, clear colour (0, 1, 0, 1), running memory only) and `--fogpoly` (polygons in metres) decide it.

## Turret heads, the Power Core Turret's body, boss kill voices, the match end (2026-10-29, tester report 23:03)

Details: `docs/re-notes/turret-heads-coredeath.md`.

- **One head per turret (C table).** The lane turret base table `0x1D000372` Vfx_AI_Active `0x10000D63` is a single
  type-12 spawn of `0x2E000AA8` (scale 0.9, event `0x100000FE` -> Vfx_Startup `0x1000018E`, Vfx_Targeting wired); the
  dampener's `0x1D00063A` spawns the same head at scale 0.75, z -1.4. The client makes it, coloured by the body; the
  server-made head (`[ics] match_turret_heads`) was a second, white (Null colour) copy. `[ics]
  match_turret_head_skip_own_child`.
- **The blue Power Core Turret's world state has no body mesh (C names, P effect).** Rig names in pack `0xA0000162`:
  `env_pvp_turret_powercore_a` (lane body `0x2E000AA0`) holds the bones `Root, Base, Ring_*, Shield, Vfx_Ground,
  Head_Aim` plus the mesh nodes `Lane_Turret_A` / `Lane_Turret_A_Head`; `env_pvp_powercore_turret_a_body`
  (`0x2E000AC4`) has the same bones and no mesh node. The world states differ only in 0x50F (8 / 7). Template
  `0x49000C8E` = `0x49000C8F` except 0x510 = `0x2E000AA0` (the red `0x40000C8D` uses `0x2E000AA0` too). `[ics]
  match_structure_classes` spawns `0x40000C8E` for team 1.
- **Boss kill voice (C sets).** Event 61 has only the acting team's line (697); 701 is the other team's: one or the
  other per listener (`[ics] match_boss_kill_voice_by_team`).
- **End cinematic timing (C data).** Crime Alley `0x3500003A` / `3B`: 11.5 s, PowerCore `0x2E000AC5` frame 0
  Vfx_Destruct_State0, frame 225 Cinematic_Announcement `0x10000A50`; cinematics run at 30 fps (0x35000038: frame 2130
  in 72 s), so 7.5 s. GD / CC raise their event-29 timeline events at the same frame, GH's Cinematic_Announcement is at
  210 (7.0 s, cinematic 10.5 s). Notice 0x1000000E makes the client leave the world at once (`0xa809e0` ->
  `0xab52a0`), so it must come after the cinematic. `[ics] match_end_timing`.

## The score screen's Accolades tab, the UI state machine 0x34000000, the meteorite's "orb children" (2026-10-29 23:03, fase3-ip, `re-notes/scorecard-accolades-meteor-aura.md`)

- **The rewards panel is the first tab (C, SWF + Flash).** Scorecard sprite 112: `m_btnTabAccolades` (x 11.75,
  label "Summary"), `m_btnTabSummary` (x 158.75, "Scorecard"), `m_btnTabStats` ("Stats"); `SummaryTab` holds only the
  two team tables. The original's side panel (screenshot 79) is another client build.
- **UI state machine = script `0x34000000`** (pack `0xA0000037`, decoded like the server scripts). Scorecard graph:
  enter = LoadScorecardScreen (100) + NextScorecardTab = Accolades; on ScorecardLoadComplete (37, end of
  `Scorecard.OnAllDataRecvd`) -> LoadScorecard_Accolades (106) / _Summary (72) / _Stats (91) by the tab variable.
- **Empty Accolades tab (C Flash).** `AccoladesDisplay` gets its data only at load (all data in) or on ACCOLADES_RECVD,
  which `ScorecardManager` raises only when the accolades notice arrives after every other piece; `Init()` asks for the
  accolades before the header, so a 0x2188 cached at the match end leaves the alpha-0 chain stopped at its first step.
  `[ics] scorecard_accolades_resend` sends 0x2188 again 1.5 s after the scorecard's 0x212E (its AskForRibbons at
  screen load); `scorecard_accolades_resend_fallback`. `diag --scorecard` logs the Flash natives' order.
- **0x219E show-banner** is always set by `0xA37DC0` (+0x12 = 1); the 0x2045 ranked flag is the encounter manager's
  +0x8E bit 0 (`0xA795E0` -> `0x8E3AC0`).
- **Action type 0xC** in scriptlet bodies spawns a world state as a client object and runs a key on it (relay table
  `0x1D0004A1`: `0x2E000D13` / `0x2E000D14` with Vfx_Startup; superpad table `0x1D0008FA`: `0x2E00137F`). D13 / D14
  (table `0x1D00038B`, the team hologram table) are the relay's 7 m capture plate (`.entity 0x2D000ADE` bbox), not the
  meteorite's children (they only follow the Rock template in the packs). The rock's tint is appearance set
  `0x19000A61` group `0x10000004` -> parameter sets `0x16000E7D` (0x7D0) / `0x16000E80` (0x7F3), red. `[ics]
  liftable_aura_probe` (default []) tries logged candidates for the original's floating halo (O).

## The scorecard's "Summary" tab, every condition (2026-10-30, tester report 13:18, `re-notes/scorecard-summary-tab-conditions.md`)

- **Flash (C).** "Summary" = tab 0 `ScorecardAccolades`, attached at run time from movie `0x200000AD` (the scorecard
  `0x2000008C` imports `Import_ScorecardAccolades`); the state machine opens it first (event 106) unless the
  view-last-match mode is on. Its parts start `_visible = false`; the first `show(true)` either queues the rank ribbon
  (0x2045 ranked flag + 0x219E show-banner) and waits for it, or animates: `AccoladesDisplay` needs data, which it gets
  only at load (all data in) or from ACCOLADES_RECVD, raised only by an accolades notice arriving after ALL_DATA.
  Leaving the tab and coming back (`KillAnimations` then `draw()`) or Esc while animating shows every part at alpha 100.
- **C++ (C).** Flash's Init request 0x100004E6 -> dispatcher `0x911D30` -> `0xA1A190` replays the accolades cache
  (manager `0xA12D50` +8) through `0x8CEE70` every time: it is why ALL_DATA fires, and it is never last (the header is
  asked after it). Live notices: 0x2104 `0xA7E0A0` / 0x2188 `0xA61DA0` -> `0xA56DB0` (list lengths equal; flag != 0
  with no entries -> first-map accolade `0xA40B10`; else the encounter record must exist) -> `0x8CEE70` (Flash target
  `[ebp-0xA0]`). Request 0x100003F1 -> `0xA1A100` (0x2104 cache +0x54), 0x100003FA -> `0xA1A1D0`. 0x2104's reader
  `0x849680` matches ics' layout (the encounter is the u32 at +0xE0).
- **This run:** every message the path needs was sent, the late 0x2104 after ALL_DATA; the remaining causes (no
  live notice reached Flash, ranked-ribbon wait, the tab content never loaded) are told apart by `diag --scorecard`
  (new gates `0x4CEEE6`, `0x661DAE`, `0x67E0A0`, `0x67E321`, `0x656E2C`, `0x61A19C`, ...) and by Esc / tab switching.

## Editing the Flash UI: the Modern UI feasibility test (2026-10-30, `re-notes/ui-modern-feasibility.md`)

- **Movies.** The out-of-match UI is Scaleform GFx: DB type `0x20` records, only in pack `0xA00000D0` (checked over
  all 616 DID lists), record `did | flags | [imports] | 0 | 0 | images | u32 length | GFX`. 80 uncompressed `GFX` v8,
  one v9, the AS2 class library `0x20000025` is `CWS`; no DoABC anywhere (AS2 only). Movies hold art, sprites,
  placements with instance names and `Object.registerClass` init actions; all behaviour is library code that calls C++
  with `ExternalInterface.call("Turbine.SendNotice", id, ...)`. The home-screen bar is the wrapper header
  `0x20000077` (record at stream `0x26D52DC`, 61 931 bytes, CRC `0xD3D3_FF27`); `WrapperMain` attaches its exported
  symbols `HeaderLetterbox` / `HeaderLeft` / `HeaderCenter` (PLAY = `m_pvpPlay`) / `HeaderRight` (`m_btStoreButton`,
  settings, help, exit) by linkage name, so its root timeline is never shown.
- **Integrity.** The client reads the pack header (`0x9DACA0` / `0x9D31C0`: payload size, count, tail streams at
  0x400-aligned offsets after the payload; no checksum) and inflates the payload as a stream block by block
  (`0x9D9280`, zlib 1.2.3, trailers = bytes per block). zlib's Adler-32 is the only check; nothing hashes or signs
  packs or records. A same-length record edit = bytes + Adler-32 (like `icserver/terrainfix.py`).
- **Tool.** `python ic.py ui-test apply / revert / status / info / extract` (`tools/ui_mod.py`, `tests/test_ui_mod.py`):
  with the game closed, puts a test header into the pack (navy colour transform on the four header backgrounds, blue on
  PLAY, a vector-drawn "MODERN UI TEST" badge under the bar; 72 empty DoInitAction stubs dropped to keep the length;
  every instance name, init action, import and export untouched), backup `0xa00000d0.rp.uitest.json`, revert
  byte-identical. Tried on a copy only; the in-game check is the tester's.
- **Preferences from Flash.** `GM_Options.SendQuery_Get{Bool,Int,UInt,Float}Option(name)` / `SendNotice_Set...`
  (`0x1000013E` / `0x1000013F` for bool) reach `0xA4DBC0` / `0xA4DA00` (int `0xA4DEF0` / `0xA4DD30`, uint
  `0xA4E220` / `0xA4E060`, float `0xA4E570` / `0xA4E390`), which register an unknown name on first use (`0x4D8930`)
  and save to `UserPreferences.ini` (`0x4D9040`); synced values go to the server with `0x216E` and come back in
  `0x216A`. So a movie can choose Legacy / Modern from e.g. `User.InterfaceStyle` with no exe or server change; the
  login screen can read the local INI value before the account exists [P].

## The Modern UI build pipeline (2026-10-30, `re-notes/ui-modern-build.md`)

- **Pack layout, exact.** `+0xC` of a 10PR header is the payload *span*: file bytes from 0x400 to the end of the
  Adler-32, trailers included. File blocks of 0x20000 = 0x1FFFC data + a u32 trailer holding the zlib bytes in the
  block (block 0: `0x1FFFC - 4 x count`, the DID list is not zlib); the **last block is partial and has no trailer**.
  Tail streams sit at `align_0x400(0x400 + span)`, each padded to 0x400, with the same block / trailer layout counted
  from their own start. `0xA00000D0`'s stored-block split is zlib 1.2.3 level 0 fed 32 KB at a time (65 531, 32 773,
  32 768 ..., rest, empty, empty final). `tools/rp_repack.py` rebuilds the installed pack byte-identical and can
  replace a record by one of another length (records are 4-aligned, in DID-list order, movies carry their length) or
  append a record [P: a DID only in the list is untested in the client].
- **AS2 from Python.** `tools/as2c.py` compiles a JavaScript-like AS2 subset to AVM1 (one constant pool,
  DefineFunction v1, DefineLocal, GetVariable / GetMember for dotted library names) and has a test VM; scripts reach
  the library classes (`GM_Options`, `GM_UI`, `gameplay.wrapper.WrapperMain.Instance`, `flash.geom.Transform`) through
  `_global`, exactly as the library's own code does.
- **Movie edits.** `tools/ui_build.py` + one module per movie in `ui/modern/movies/<did>_<name>/` (shared palette / art / helpers in `ui/modern/common/`): per exported symbol, new vector art (DefineShape3 in a
  DefineSprite, placed with alpha 0), new instances of the movie's own game buttons (clip actions compiled from our
  source), copies of placements, and one DoAction appended to frame 1 (after the symbol's own `stop()`); every
  original tag, placement, instance name and init action is kept byte-identical (tested).
- **The switch.** `User.InterfaceStyle` (int, 0 Legacy default / 1 Modern) through `GM_Options.SendQuery_GetIntOption`
  (`0x1000013A`) / `SendNotice_SetIntOption` (`0x1000013D`); a check box added to the settings dialog's UI pane
  (`0x2000005F` `UIPaneContents`, `m_btnICModernUI`, a copy of the profanity-filter box) saves it at once and switches
  the header live through `_global.ICModern`. The account keeps it (`0x216E` -> `ics/account.py` -> `0x216A` int).
- **Modern header** (`0x20000077`): navy bar over transparent Legacy backgrounds, PLAY moved left and tinted on a
  pointed plate, HOME / CHAMPIONS / AMPLIFIERS / STORE (new `MediumTextButtonLarge` instances calling
  `NavButtons.OnHomePress` / `OnStorePress` and `UIStateMachineEvent(TransitionToCharacters / TransitionToAmplifiers)`),
  profile and currencies at the top right (coins gold, merits blue). The class code is untouched; Legacy writes
  nothing to any original instance. Commands: `python ic.py ui build | apply | revert | status | list`.

## Rebuilding Flash screens instead of restyling them (2026-10-30, `re-notes/ui-modern-rebuild-home.md`)

- **One attach point.** `WrapperMain` (movie `0x20000075`) attaches every screen (`AttachNextScreen`,
  `m_ssData.m_sScreenIDString` = `"LoginScreen"`, `"VeteranLandingScreen"`, ...), the four header parts, the footer
  parts, the legal footer and the landing nav by linkage name through `ui_sys.UIWidget_Base.prototype.
  AddChildFromLibrary` -> `attachMovie`; only the store and the background go through `ResolutionSizer`. It imports a
  single dummy symbol per screen movie (`Import_Login`, `Import_VeteranLanding`, ...) yet attaches their other
  exports: GFx resolves the names through the imported movies.
- **The switch.** A `DoInitAction` (on an exported empty sprite, like the `__Packages` stubs) in each rebuilt movie
  wraps that method at run time (the library is not edited): with `User.InterfaceStyle` = 1 a linkage with a Modern
  twin (`ICM_*`, registered to the same class) is attached instead; else the original call.
- **Constraints of the library.** `UIWidget_Base.CreatePosIfNeeded` (constructor) takes `getBounds(this).xMax/yMax x
  placement scale` as the widget's size and resets `_xscale` / `_yscale` to 100 (texts and `utils.Icon` then draw
  into that size; composite widgets keep their authored size). `LiquidNode.ComputeNewPosition`: a `"center"`
  attachment puts the origin at the container's centre; `"same"` on the right / bottom edge subtracts the widget's
  measured width / height. CLIK `Button.setState` plays `stateMap` labels last to first and ignores missing ones
  (`up` / `over` / `down` / `disabled` + `selected_*` suffice). Text is `UIWidget_Text` with a template from the
  client's template XML (`iprp_Template`: H3 ~20 px, H4 ~15, TitleRegularSmall ~14, ToolTipSmall ~11,
  TitleRegularLarge 36; author box 120 x 24 from `0x20000000`).

## The Super Strength soft-lock and the dead slot (2026-10-30, tester report 11:23, `re-notes/liftable-softlock.md`)

- **Input back once per match (C).** `Liftables._input_back` kept its "sent" mark on the slot's script instance
  (`ent.skill_insts[7]`, created once per match), so only the first lift ever posted 0x100000BB to 0x34000164: from the
  second on, S4's input hold (node 0x100000AD) lasted the whole carry ("move refused (crowd control)" 22 / 16 / 24 / 57
  times in the carries of 11:10:20, 11:10:48, 11:13:19, 11:16:33) and S3's StartCooldown never ran (no 90 s cooldown,
  no "kept ready" 0x20F8). Now per lift (`[ics] liftable_input_back_per_lift`).
- **A thrown rock re-lifted in flight (C).** 11:16:33.659: a slot-7 order with target 0x0, 0.68 s after a throw, became
  a new Super Strength use; `script_runtime.activate` keeps the last TargetIID when an order has none, so 0x34000164
  raised 0x10000037 on the rock in flight, `Liftables.lift` took it (it checked only "in props, not carried"), the old
  flight landed it and `_gone` removed it in the champion's hands (34.551): a 24 s ghost carry. `[ics]
  liftable_lift_guard`: no lift of a gone / flying / tossing / landed / carried object or through a stale TargetIID (the
  order record lacks one); a refused request posts 0x10000009 so S4 never keeps its hold. P: the original cleared
  TargetIID on a target-0x0 order (the VM still keeps it for every skill).
- **The slot table lost (C).** The lift at 33.662 came during the previous carry's pending slot restore
  (`liftable_slot_restore_delay` 0.9 s); `_throw_button` took the slot's current table (the rubble throw's) as Super
  Strength's, and the end of that carry restored the throw table for good (11:16:59.425, 1432 bytes instead of 1539):
  every later order had target 0x0 and 0x34000164 went S2 -> S0. `[ics] liftable_keep_base_block`.
- **Watchdog** (`Liftables._watch`, `[ics] liftable_watchdog`): object gone -> the carry ends at once; dead carrier ->
  drop; lift not ready after `liftable_lift_timeout` -> ready; throw not ended after `liftable_throw_timeout` -> ended;
  ready carry over `liftable_carry_timeout` -> thrown / put down (`liftable_carry_timeout_action`); slot still on the throw
  table `liftable_restore_timeout` after the restore was due -> Super Strength's table back.
- **Throw press (C pattern, O client step):** the unanswered presses came in pairs 1.9-3.2 s apart, the fallback threw
  on the second; `liftable_throw_on_press` 2 -> 1.
- **Robotic throw / toss (C causes):** the throw's turn was a full 1450-byte champion bundle mid-Hold since
  `object_update_mode` went back to "bundle" (the motion-only turn existed for "delta" only):
  `liftable_throw_face_motion_bundle` sends the 0xB0 state alone in bundle mode too; the toss's 9 fixed states went two
  to a ~68 ms tick: `liftable_toss_timed` (one state per `liftable_throw_step_seconds` at its own time).
- **O:** the landed vehicle vanishing ~2 s after the landing is nothing the server sends (0x8B, 0x8A x2, the Optional
  destroy action = fog-occluder flag, break sounds / particles, removal at 10.5 s); next run `diag.py --destruction`.

## The vehicle's toss, the throw's carried state, the wreck that stays (2026-10-30, tester report 12:05, `re-notes/liftable-lift-throw-wreck.md`)

- **Run check (C):** one vehicle lift (12:01:34.479), throw on the first press (order 130 ms after the 0x20EA), landing
  37.475, removal 47.996; input back at the toss, 0x20F8 before the indicator, Super Strength's table back at its normal
  size, 87 s cooldown; no watchdog line and no refused move.
- **Toss (C bytes):** the timed toss states had speed 0 and no newer seq A (`01 01`), so the client steered toward a
  standing target 0.1 s behind, dropping the height (0x60B5F0 / 0x5C9FE0): the lob crept, then popped up at the catch's
  snap. `[ics] liftable_toss_velocity` ["vehicle"]: snapped states with the lob's 3D velocity (heading, speed, motion
  pitch 0x40) and the facing turned by `facing_offset`, from f = 0.
- **Throw (C code):** the carried vehicle kept its last carry state (old heading, the walking speed) until the first
  flight state 0.33 s after the champion's turn. `[ics] liftable_throw_turn_object`: one carry state, turned and stopped,
  at the throw.
- **Attach (C, unchanged):** the 0xB0 parent block carries no local transform (`0x55E6B0`), so the vehicle stays carried
  by its own states.
- **Wreck (C code, P key):** `0x62EBF0` (piece removal, from Vfx_OnExplode's 0x28) first runs `0x62E6E0` on
  piece+0x50 (the piece's effect lists), then frees its render instance / body; with no piece left it runs the
  destruction record's +0x70 scriptlet on the entity (`0x57D8B0`). Truck record 0x500001F0's only non-piece key is
  0x10000290 Destructible_OnCompletelyDestroyed (P = +0x70). `[ics] liftable_land_explode` {"vehicle": 0.75}: the break
  keys at +0.2 s on the intact wreck, Vfx_OnExplode at +0.75 s removes it (was: standing until the 0x3 at +10.5 s).
  P: a doubled explosion sound; the break-key fire ends with the pieces.

## The score screen's live accolades notice, turret target flapping, the Power Core Turret's plate (2026-10-30, tester report 11:23, `re-notes/scorecard-panel-turret-head.md`)

- **0x2188 empty = dropped (C):** handler `0xA61DA0` returns before `0xA56DB0` / Flash `0x8CEE70` when its second list
  (the accolade records) is empty, so the fase3-ip late 0x2188 (traffic 11:23:17.193) never raised ACCOLADES_RECVD.
  `0x8CEE70`'s other caller is 0x2104's `0xA7E0A0`, which passes its trailing u32 (param_21) to `0xA56DB0` as the
  encounter: with a record found it calls Flash with the (empty) lists. `[ics] scorecard_level_encounter` (0x2104
  carries the encounter) and `[ics] scorecard_accolades_resend_event` "0x2104" (the late copy after the scorecard's
  0x212E). 0x2188 lists: 1 unused, 2 accolade records, 3 medal 1-3, bytelist, 4-5 values for `0xA344C0` (P).
- **Turret target flap (C code / traffic):** `Units.think` picked structure targets out to range + 1 m, `Units.act`
  dropped them beyond range + target radius in the same tick: Target_Acquired + Target_Lost 1 ms apart (135 / 127 in
  the run), each starting and stopping Vfx_Targeting on the body (type-0x17 actions, flag 1 = stop) and on the
  client-made head (graph events `0x1000009C` / `0x1000013D`). P: the cause of the vanishing heads.
  `[ics] match_turret_pick_in_reach`.
- **Power Core Turret plate (C traffic):** the lane body `0x2E000AA0` (`0x40000C8E` / `C8D`) had no gear plate
  `0x2E000A9F`; `[ics] match_turret_plates` core_turret.
- **Surrender at 930 s (C traffic):** the tester's vote, notice `0x10000454` = 1 (11:23:02.993). Client RankSkill RPC
  `0x9F 0x81910003` = u32 rank | u32 slot | u64 agent (12 in the run, logged by name now).

## The turret head lost on target, the Power Core Turret's own parts (2026-10-30, tester report 12:05, `re-notes/turret-head-pct-look.md`)

- **Head lost on target (C data / code, P cause):** traffic 12:02:09-19: per acquisition only 0x10000C66 + Target_Acquired
  `0x1000014A`, per loss 0x10000C66 = 0 + Target_Lost `0x1000002C` (no flap since `match_turret_pick_in_reach`). Body
  table `0x1D00035D`: Target_Acquired / _Lost = two type-0x17 runs / stops of Vfx_Targeting. The client's run start
  `0x57B9D0` forwards a key run without an instance number (`DAT_0185F2B0`, the type-0x17 case) through the component's
  key -> child list (`+0x1C/+0x24/+0x28`) to spawned children: the head `0x2E000AA8` made by the body's Vfx_AI_Active
  gets them (its Vfx_Targeting: graph events Combat_Idle / Idle, which its graph `0x1C00006E` =
  `env_pvp_lane_turret_head_a_behavior` does not have). The turret's attack script `0x34000014` never runs either key
  (it runs Object_Ranged_Attack only); the head first vanished when it became the client child (fase3-ip). `[ics]
  match_turret_own_head_no_target_keys`: no Target_Acquired / _Lost for such a structure (0x10000C66 and shots stay).
- **Power Core Turret parts (C):** `0x40000C8F` -> `0x2E000AC4` (rig `env_pvp_powercore_turret_a_body`, graph
  `0x1C000069`), base `0x1D000374`: Vfx_Active spawns the cylinder `0x2E000A9A` (z -0.25, Vfx_Startup = hologram
  overlay; its other keys Vfx_Object_Phase1-14 / Vfx_Object_Reset = type-0x2E actions on group `0x10000002`, reached
  only through the body's Object_Reset / Object_PhaseN in `0x1D000600`); Vfx_AI_Active spawns the flag head `0x2E000AC3`
  (graph `0x1C00006A` = `env_pvp_powercore_a_turret_head_behavior`). `_Entity_OnSetClientRelationship` re-runs
  Vfx_Active locally. A name scan of every pack finds no prow / socket model (only these rigs and the core's).
  `[ics] match_structure_classes` {} (blue = C8F / AC4 again), `match_turret_plates` without core_turret, and
  Object_Reset last in `match_structure_scriptlets["core_turret"]` (P: the cylinder's opaque fill).

## The turret ring's phantom meets no body of the champion; the fence strip is no terrain hole (2026-10-30, tester report 12:05, `re-notes/ca-ring-bodies-strip-layers.md`)

- **Ring (C diag / code, P cause):** the 12:00 diag saw the four enemy structures registered and their phantoms built
  (`create_fn` 0x518CA0 at base 0x2E0000 = static **`0x638CA0`**, vtable `0x15CBBF0` +0x18, non-null handle), and AGL
  walked to (88.6, 79.0), inside the enemy lane turret's 14.5 m box, with not one filter call. The service's
  overlap-add **`0x6385D0`** drops a candidate before the filter when its world-object type (Havok property 0,
  `0x573050`) & the filter's mask (+0xC, vt+0x24) is 0 (`test` at **0x638636**). The ring's filter preset `0x5BB8A0`:
  kind 0x10000, mask **0xA08** = Shadow solid entity 8 | Rigid body character 0x200 | Rigid body sub entity 0x800
  (type names `0x5B1E60`). A unit's collision component (entity +0xB8, `0x15F9500` / `0x1609520`) builds its body
  (`0x9793F0`, key 0x4934AE2) only while a script holds collision (`0x976990` EnableCollision / `0x9754A0`); the only
  one in the run was the Grab missile 0x138 (the client hosts missile scripts; champion classes list none). Which
  character body the champion needs, and what makes the client build it, is open. New `diag --ring` probes 0x638636
  (every overlap candidate: kind, mask, IID) and 0x976990 (every hold).
- **Strip (C):** `87.webp` with `--nofog` active: still black, a parallelogram x ~70-85.5 between the lane mesh (y
  81.8) and the fence base (y 83.4), both side edges parallel (36 deg). Not an index hole (both u16 index arrays of
  `0x800113BB`, near grid and 16 far patches, draw every cell), not the heights, not the baked colour (`0x13003439`
  bricks; `0x1300343B` flat), not the fog's EnableFog. WorldRender draw toggles (`0x7F1310`, bytes): +0x2E
  AllowOutdoorMultiPassShadows, +0x2F DrawLandscapeWater, +0x30 DrawLandscape, +0x31 DrawCeiling, +0x32 DrawFloor,
  +0x33 DrawSky, +0x34 DrawParticles, +0x35 DrawFrills, +0x36 EnableFog, +0x37 EnableDistanceFog, +0x38
  EnableGroundFog, +0x39 EnableMaskFog, +0x3A..+0x3D Dynamic / Static / Opaque / Translucent entities, +0x3E
  DrawCellMeshes, +0x3F DrawLightCoronas. `tools\diag.py --layers` switches them off one at a time to name the strip's
  layer. The "fog occluder pass" exe patch does nothing for the strip (kept for now, see the note 2.4).

## The timeline tooltip's picture and the jungle's 30-second phase-in (2026-10-30, tester report 13:18, `re-notes/timeline-tooltip-camp-prespawn.md`)

- Hovering a strip mark opens Flash `EventTimelineTooltip`: title = the entry's first StringInfo (tinted by severity),
  description = the second, **picture = `didExaminationIcon` (descriptor `[6]` of notice `0x100002AB`)**, plus its own
  countdown. ics sent both icons 0 and no strings, hence the black box with only the countdown (C, AS2).
- The original's only script-built descriptors (GH cannon `0x340002CF`, node `0x1000011A`: severity, strip icon,
  examination icon, tint u8) put a unit's Character_Billboard_Icon `0x100001FC` in `[6]` (`0x130016CD` = the super
  drone's) and a small icon (`0x130029AD` / `0x130029C4`) or 0 in `[5]` (C).
- ics: `[ics] match_timeline` entries carry `icon` (read from the data: the map's melee drone -> `0x13000F9D`, the
  jungle Tripods and the Raider -> `0x13001A37`), optional `strip_icon` and `title`; a Raider mark at
  `match_raider.at`; `match_timeline_icons` switches the pictures off. `Data.record_u32` finds the Raider's
  `0x100001FC` that the template reader misses.
- Jungle: the first camps spawn in their persistent `Vfx_Spawn_Alt01` phase-in at the "Online in 30 seconds" line
  (`match_camp_prespawn_from` -30) and complete it 1 s before the jungle time (`match_camp_prespawn_appear_before`);
  respawns (no countdown line) keep the 3 s phase. No separate spawner / portal effect exists for CA camps (P, tables).

## Units passing through each other; the movement module's character body (2026-10-30, tester report 13:18, `re-notes/unit-separation-pick-body.md`)

- **Overlap (C):** remote units are replayed from the server's states (module 1 sampler `0x609240` / `0x552130`); the
  client resolves no contact between two units, so separation is the server's. ics had none (headless Crime Alley:
  1 894 / 32 832 minion pairs under 0.7 m).
- ics `Units.separate` (`[ics] match_unit_separation`, `match_separation_roles` / `_push` / `_resync` /
  `_shuffle_min` / `_slack`): every tick a grid pass pushes each minion / camp unit out of other units (half each),
  champions, bots and structures (all on the unit), radii = the attack radii (`World._attack_radius`); never out of
  its target's reach; a walking unit is nudged (sidestep when pushed back), a state only when the client's dead
  reckoning is 0.4 m off; a standing one slides to its free spot (start + stop state facing its target); never onto
  an unwalkable cell. After: 59 / 33 225 pairs under 0.7 m.
- **Client radius (C):** `0x5897A0` = CModelComponent (`entity+0x18`) `+0x10` -> f32 `+0xB0` x physics scale `+0x74`
  (`0x571950`: property 0x6B4 x 0x450) + 0.05. The `.entity` field behind `+0xB0` is O.
- **Character body (C code):** the movement module builds it, not a script. Replay module 1 (`0x15C6360`) attach
  `0x60BAC0` -> `0x60A340` -> `0x5D1600(entity, shape)` (character object `0x5C6030`; module `0x10000005` attach
  `0xAAD210` likewise; property 0x991 false -> a second body); once the character has a world and passes the cell
  test `0x5C9B20`, `0x5C6320` builds world-object type **0x200 Rigid body character** (`0x5C3330` / `0x5C3550`, mass
  100) and type 0x400 when 0x991 is false. Module 9 (`0x15C62A8`, modes 0x41 / 0x4C) builds its type 0x200 body in
  `0x60A620`. ics already sends module 1 for every unit and champion; no server message / property / script was found
  that adds a body (no config key). The ring's mask 0xA08 includes 0x200, so the ring meeting nothing (12:00 run)
  means P that `0x5C6320` never ran for them; the same would leave the hover pick only the render mesh. `diag --ring`
  probes `0x1D1600` (character created, world) and `0x1C6320` (body built) decide it.

## The game closing after a diag; the Power Core Turret as a composite (2026-10-30, tester report 13:00, `re-notes/turret-pct-composite.md`)

- Crash (C): the game closed 4 s after Ctrl+C ended `diag --layers` (breakpoint `0x6AE5B0`, hit every frame). Ctrl+C
  raised KeyboardInterrupt right after `WaitForDebugEvent` returned, so `tools/tracer.py` detached
  (`DebugActiveProcessStop`) with an int3 / single-step event received and never continued; Windows hands that
  exception to the game, which has no handler. `DebugSetProcessKillOnExit(FALSE)` was already set (not the cause).
  The server sent nothing unusual (client keep-alive 13:00:38.98, connection reset 13:00:46.342).
- Fix: console Ctrl+C / Break / close only request a stop (`SetConsoleCtrlHandler`); the loop stops between events;
  `detach()` restores every int3 byte, clears the debug registers, undoes `restore_on_detach` writes (`--layers`,
  `--nofog`), continues the held event and drains the queued ones (Eip back onto the breakpoint, TF cleared, no
  re-arm), clears TF on a still-pending thread, then detaches. `tests/test_tracer_detach.py` (fake kernel32, 53 checks).
  The 13:05 run stopped two `--layers` diags this way and the game stayed up.
- Power Core Turret (C data, G frames): `0x2E000AC4` has no mesh of its own; on it only the hologram children drew
  (cylinder `0x2E000A9A`, flag `0x2E000AC3`; frames 71 / 82 / 89). Its Object_Reset (`0x1D000600` -> `0x1D000374`
  Vfx_Object_Reset = timeline of Vfx_Object_Phase0..4 runs) reaches A9A's type-46 actions (`0, 0x7D0, N, group
  0x10000002, 1, 1.0`) and left it white without the flag. Now: class `0x40000C8E` (lane body `0x2E000AA0`, as the red
  `0x40000C8D` by data), body key Vfx_Active only, flag head AC3 made by the server (`match_turret_heads`), the A9A
  cylinder made by the server (new `match_structure_parts`, z -0.25), no base (the original's prow is not in the data;
  the tester: the base is not round). O: the original's opaque fill.

## The fence strip is drawn through the statics; hiding one render node; the nook pad's height (2026-10-30, tester report 13:18, `re-notes/ca-strip-static-shadow.md`)

- **Strip (C log, P cause):** `diag --layers` (13:09:59): only DrawStaticEntities off removed it; Opaque / Translucent
  entities off did not, so it is not a static's own surface but something statics feed into another pass (P a
  directional shadow: parallel side edges; both environments `0x08000003` / `0x08000016` hold 200 / 140 at +0x20 /
  +0x24, P sun heading / pitch). **Cast-shadows flag (C):** RenderComponent property switch `0x624500`, case **0x4A8**
  -> component flag 0x20 (`0x6249F8`) -> node flag **0x400** (`0x624A2F`); the shadow casters pass `0x761320` draws
  nodes with 0x400 and without 2. In 13BB only the 11 lights `0x2E000011` carry 0x4A8; the fences on the strip's edge
  (`0x2E001324` / `12F6` / `04D7` / `097C`) and the lamp `0x2E001219` do not; the server's stealth tiles
  `0x2E000D36` / `D37` (0x4A8 = 1), the nook pad `0x2E000D12` and the gate `0x2E000CD7` do. `0x2E001207` has no
  render geometry (gfx `0x1100077A` = param set `0x19001160` only; its shape `0x10001649` = 228-vertex / 444-triangle
  collision mesh + MOPP, the 4 m block north of y 83.4); `0x2E001185` (gfx `0x1100076C`) neither. Other RenderComponent
  property flags: 0x1F0 -> 0x10000, 0x5F9 -> 0x1000000 (node flag 8, `0x77E2A0`), 0x1EE -> 0x2000000, 0x4FD -> 0x20000000
  (node 0x4000), 0x44F -> 0x40000, 0x451 -> 0x2000, 0x4FE -> 0x80000, 0x3B5 -> 0x80.
- **Hiding one object at run time (C):** a model node attaches in `0x781640`, which calls RenderComponent `0x6226E0`
  at **`0x78165C`** (ecx = component = node +0x264, esi = node); the component keeps the node at **+0xA0** and its
  entity at +4. Node **+0x220 bit 0x800** = hidden (`0x77DF70`, set by the 0x2A1 / 0x76A / 0x90F path at `0x624D67`);
  bit 0x8000 / 0x10 / 8 are other cull states. **Graphics settings** are globals registered by `0x7C55E0`:
  `Render.ShadowMapQuality` **0x1865744** (the shadow pass `0x794280` skips at `0x7942B5` when 0; needs
  `DeferredRenderer` 0x18656BC), `MinSizeToHaveShadows` 0x1865748, `EnableSSAO` 0x1865778, `EnableHDAO` 0x1865779,
  `SurfaceReflections` 0x18656D8, `EnableDecals` 0x186575A, `EnableNonGlobalLights` 0x1865758, `EnableUniqueLights`
  0x1865759; the change watcher is `0x7C83D0`. New `tools\diag.py --strip` (`--franja`): records every 13BB static's
  component while the map loads, then steps the settings off and hides statics (all, each fence piece, the street /
  rain / lamp pieces, the stealth tiles, ten index-bit groups), 5 s each.
- **Nook pad (C):** the relay `0x4000089D` (`.entity 0x2D000ADC`, box z 0 .. 0.092) was sent at the map's z 200.3; the
  terrain at (80, 97.25) is 199.98 (navmesh 200.08, markers `0x2E000944` / `945` 200.085): 0.32 m afloat. Now
  `[ics] match_nook_pad_z = 199.98`.

## The strip's `--strip` answer, the two-bit candidates, the blue core's yaw (2026-10-30, tester report 19:46, `re-notes/ca-strip-two-bit-candidates.md`)

- **Not a shadow map (C log):** `Render.ShadowMapQuality` was already 0 in the 19:41 run and the strip stayed black.
- **Static IIDs (C):** the loader `0x548550` keeps the entry's own IID (in-memory entry +0x20 type, +0x28 / +0x2C IID,
  looked up by `0x53BFD0`), so the index groups of `--strip` are the record's index field. `0x820113BB`: header count
  0x16A, entries `flags | type | [index | 0x01113BB0 if & 4] | [world state if & 8] | xyz | quaternion | [0 | n | props
  if & 0x80]` (a 0x80 prop seen: `0x6B4` scale); indices are sparse.
- **Answer (tester):** the strip went in the bit-9 step and one other bit step -> index `0x200 | (1 << k)`. Instantiated
  entries with such an index: 0x201 / 0x202 / 0x204 (breakable crates at x 19-27), **0x208** (garden bush `0x2E000800`
  at (85.56, 86.54), scale 1.15, mesh box y >= 84.7: the only one within 4 m of the strip), 0x240 (west fence
  `0x2E0004D6`); 0x280 is a type-16 start point. None has a box over the strip (C boxes, P render = box).
- **Breakables were not recorded (C log, P cause):** #0x246 / #0x24C (`0x2E0012F6` / `0x2E001324`, fracture data) had no
  render node at the 0x78165C probe; P their IID is set after the attach. `--strip` now re-reads every recorded
  component's IID when a cycle starts and logs the count there (the "0 statics recorded" header at the first fog frame
  was premature). New `--strip2` (`--franja2`): the candidates one at a time, 6 s each, then bit-9 / all controls.
- **Blue core yaw (P geometry, tester):** at yaw -80 the prow (local -y) points west-south-west (`96.webp`); red at -90
  points it west, at the lane; the left / right mirror gives blue 90 = -80 - 190 (the tester's "about 190 clockwise").
  `[ics] match_structure_yaw_add` crime_alley core "1" = 0.0 (was -170).

## The `--strip2` recording: only the bit-9 control clears the strip; `--strip3` (2026-10-30, tester recording 21:33, `re-notes/ca-strip-two-bit-candidates.md` 8)

- **Video -> log (C):** taskbar clock minute flips at t = 6.0-6.5 / 66 / 186 / 246 s -> log = 21:33:53.5-54.0 + t. The
  strip (mean grey 2.9 -> 82) is gone exactly in steps 11 (every bit-9 static, 51 nodes) and 12 (every static) of each of
  the 4 cycles, never in steps 1-10. In step 11 a red translucent band shows in the north garden (not in step 12).
- **The single candidates hid nothing (C log):** #0x208 / #0x201 / #0x202 / #0x204 / #0x246 / #0x24C / #0x247 / #0x207
  had 0 recorded nodes: all breakables (world states with fracture data `0x800`), which never pass the 0x78165C attach
  probe even after the IID re-read. #0x240 / #0x243 (1 node each) did not clear it. So the culprit is a non-breakable
  bit-9 static.
- **The bit-9 set (C data):** 80 instantiated bit-9 entries, 53 non-breakable (diag: 204 statics recorded in all, 51 bit-9
  nodes hidden): 30 x `0x2E0005D6` (0x257-0x275; class `0x400004FD`, colour 0x2A0 red, 5 cm stored box, inline mesh),
  7 x `0x2E0012E8`, 5 garden / lane fence pieces `0x2E0004D6/4D7`, 11 singles (list: `tools\diag.py` `STRIP3_INFO`).
  Nearest: #0x262 `0x2E0005D6` at (78.01, 85.82, 201.50), 2.4 m behind the strip (P suspect, not identified).
- **`--strip3` (`--franja3`):** numbers the recorded live bit-9 nodes #1..#N per cycle (nearest first, logged), then a
  control, 12 fixed code steps (bit k of n = 1 / = 0, k = 0..5: one culprit clears exactly one of each pair and the
  "= 1" hits spell n; both / neither = more than one static) and one step per static; 6 s each, first cycle 75 s after
  the first frame.

## The original's rewards side panel on the Scorecard view is not in this client (2026-10-30, tester report 14:51, `re-notes/scorecard-rewards-side-panel.md`)

- **Flash (C).** Movie `0x2000008C` (stream `0x2767B98`): `ScorecardScreen` (113) -> `Scorecard` (112: background,
  tutorial-only level image / next challenge / mission text, `m_stSummaryTab`, prev / next arrows, three tab buttons)
  -> `SummaryTab` (99) = only `m_tcTeamContainerTop` / `m_tcTeamContainerBottom` (`TeamContainer` 98); its
  `show(true)` opens the chat window (the box at the right of the view). No hidden or alpha-0 clip, no frame label, no
  run-time attach besides the two tabs. The old layout's bar images (`XPInfoBG_png`, Orange / Yellow / Blue
  `BarFill*_png`) are still exported but placed by nothing.
- **Where the parts went (C).** The original's screenshot (79) has two tabs ("Summary" = tables + panel, "Stats"); this
  client has three, and the panel's parts are the first tab "Summary" = `ScorecardAccolades` of `0x200000AD` (merit,
  champion bar, protector bar, `AccoladesMapDisaply` with the only match-duration text of the library).
- **Run 14:48-15:11 (C, diag --scorecard).** "Summary" opened first (event 106), not ranked, the late 0x2104 reached
  Flash after ALL_DATA: every logged condition of the Summary tab held.
- **ics.** `[ics] scorecard_chat_summary` (true): the result, duration and the three rewards as four chat lines
  (0x2183) in the Scorecard view's chat window, 2.5 s after the scorecard's 0x212E (fallback 9 s). A real panel there
  needs a Flash edit of `0x2000008C` (game pack; not done).

## The champion's height in its bundles, the Raider pad's floor, the Power Core Turret's platform (2026-10-30, tester report 14:51, `re-notes/agl-floor-raider-pad-pct-prow.md`)

- **Champion z (C traffic).** The champion + player bundles carried the navmesh's z until 14:53:51, then the client's
  last click height: 200.13 -> 200.65 (lane, navmesh 200.08) -> 201.52 (blue base, navmesh 200.15) by 15:01:54. The
  client picks clicks on a plane at its champion's drawn height, so the error grows (fase3-hd's floating Batman). A
  simulated match never reproduced it (P path: a script teleport / forced-movement end keeping a point's z, or
  `Session._objects`, which never snapped). Now path corners take the navmesh's height (`ground_path_from_navmesh`),
  a standing champion is snapped every tick (`ground_snap_standing_champion`) and so is the champion bundle
  (`champion_bundle_snap`); each correction is logged ("off the navmesh ... put back").
- **Raider pad (G frames, C data).** At 199.98 the pad's north third goes under the paved floor north of the nook
  (straight edge at y ~98.4); at 200.3 it floated over the gravel. Terrain 199.98, navmesh 200.08, nook markers
  `0x2E001117` / `0x2E001120` at 200.20 / 200.22: `match_nook_pad_z` 200.2.
- **PCT platform (P).** `0x2E000A8E` (`.entity 0x2D0008A6`, ctype 8, pack `0xA00002E6`): table `0x1D000385` like the
  core pedestal and the gear plate, the plate's `0x303` / `0x57A`, never placed by any static, cinematic or table.
  `match_structure_platforms` places it under each Power Core Turret (team 2 mirrored; yaw / forward / dz in config).

## The vehicle lift: old Tutorial 1 server against ics (2026-10-30, user question, `re-notes/vehicle-lift-old-vs-ics.md`)

- **Old lift (C code + changelog).** `icserver/finale.py`: InitObjectPickup on Batman (var 0x108 and the 0x8D's
  2nd-IID field = the car), PickupObject 0.5 s later (dropped by the graph in Pickup_Start), the car put over the head
  in one > 2 m jump (snapped), CarPickup 0.05 s later, then Hold; no toss, no Car_Catch. While walking the car got a
  steered bundle (no teleport sequence) in the same tick as each champion bundle, with his speed / heading. Throw:
  ThrowObject, 10 fixed unsnapped states from 0.2 s, Vfx_OnCollision 0x5 / Vfx_OnExplode, GoToLocomotion at 0.96 s.
  Accepted by the tester after fase3-fm, not complete.
- **ics (C headless stream).** 0x34000161's order: InitObjectPickup on the champion and the vehicle (on the vehicle the
  three Super Strength keys are one sound each, table `0x1D00034B`), CarPickup at Car_Pickup's start frame, the toss
  (per-tick snapped states with 3D velocity), the catch (DisableHit, PickupObject on both), carry states snapped every
  0.05 s, the throw at the clip's MissileFire with per-tick snapped flight states, the destruction sequence.
- **Catch rebuild (C code, P visible).** The catch sent 0x8B (pieces cleared and rebuilt, `0x631050`) also for a
  vehicle carried by its own states, which moves its pieces with its frame: it only re-made the vehicle during
  Car_Catch. `[ics] liftable_attach_rebuild_attached_only` (true) limits it to attached objects.
- **Most likely "robotic" (P).** Every toss / carry / flight state is a teleport snap (velocity reset for one physics
  step) at 20-30 Hz against a steered champion; the old server's carry was steered. Not changed: A/B with
  `liftable_carry_snap = []`, `liftable_carry_resend = 0.033`. Catch 0.05 s into Hold (`liftable_toss_seconds` 0.3;
  0.65 = 0x34000161's timers' bound) is the other candidate.

## The vehicle throw beyond its range: walk into range, then throw (2026-10-30, tester report 15:30, `re-notes/liftable-throw-walk-to-range.md`)

- **No order beyond 9.5 m (C traffic + decomp).** In the 16:36-17:00 run every throw came from the unanswered-press
  fallback (`liftable_throw_on_press`, toward the facing): each carry ended with one 0x20EA of slot 7 and no 0x20EE.
  `0xa25d80` reads skill bool `0x100006D5` (`0x861830` -> `0x860550` -> `0x85ee30`: the champion's slot table, the one
  ics sends while carrying); with it the client refuses a point farther than `0x875f30` + 0.5 m (types 1 / 11 / 16:
  stat 23; others: stat 18) with `Skill_InvalidTarget` 0x1000003C and sends nothing. The vehicle throw `0x480003C9` has
  it (stat 23 = 9 m); the rubble throw `0x480004A2` does not (a line, always sent).
- **Fix.** `[ics] liftable_throw_far_order` (the throw table goes with `0x100006D5` = 0), `liftable_throw_walk`
  (["vehicle"]: a point beyond the range walks the carrier along a navmesh path at carry speed and throws at the point
  once within range; any other order cancels the walk and keeps the carry), `liftable_throw_walk_timeout` (8 s, then
  thrown clamped), `liftable_press_aim` (the press fallback throws at the last aimed point instead of the facing).

## Hover highlight and the units' character body: the Position is the client's own (2026-10-30, tester report 15:30, `re-notes/unit-pick-body-cell-test.md`)

- **The cursor pick works at a right click (C traffic).** The 16:36-17:02 run has 193 attack orders the client aimed
  itself at enemy minions / the enemy champion and move orders on allies; only 15 came from `click_assist`. A right
  click picks with `0xA81B30(champion, 0, 1)`; the selection tick with slot `[[0xA12D50()]+0x90]+0xEC` = **-1** while
  no ability is armed. Both write 0x3CB (`0xA168F0`); the outline (`0xA4EDD0`) follows 0x3CB. With slot -1 an ally the
  validator `0x9D01D0` refuses scores 0 (slot 0: 1 + 0x1C3 / 100) in `0xA16A60` (C code, O runtime).
- **Character body (C code).** `0x5C9DD0` (body build gate) runs for every character on every physics step
  (`0x5D3650` -> `0x5CA0C0`), with the character's last Position (+0x44, set by the snap `0x5C9E90`; the replay
  module's seq bytes start at the sentinel `[0x1B697F8]`, so its first state snaps). So a missing type 0x200 body means
  the landblock test `0x5C9B20` refuses the position on every step: `0x5BE910` (blocks covered) -> `0x5C86D0` per block
  (`0x5C2690`: in the physics manager `0x1B683A0`'s list +0x94 of blocks within +-120 m of the world centre, which
  follows `[0x1B6A710]` via `0x7D2640` -> `0x5D2C20`; then services `0x15BD8C4` vt+0x50 / `0x15BDA0C` vt+0x24, O).
- **Cell 0 is the outdoor cell (C).** `0x13AA138` / `0x13A7118` set `[0x1B682DC]` / `[0x1B58998]` = 0xFFFF + 1 = 0; the
  Position reader `0x47C610` stores `[0x1B58998]` for flag 0x80; the client's own order positions (flags 0xFB / 0xDB)
  mean cell 0. ics sends cell 0 explicitly (flags 0x5B), region 1, the map's landblock, instance 0 (flag 4 absent, as
  the client): the same Position. Not the cause (P strong). No server change; `diag --hover` gains the 0x3CB write and
  the outline colour, new `diag --bodytest` (`--cuerpos`, heavy, 20-30 s) logs the body's position, gate, the block
  test per block and removals.

## The "Champion Level Up!" popup's empty portrait: a picture from an unloaded pack (2026-10-30, tester report 15:30, `re-notes/levelup-ribbon-portrait.md`)

- 0x2104's u32 after the champion is the icon Flash `CharLevelUpRibbon.SetData` passes to `utils.Icon.SetIcon` ->
  `SetBgImage(did)` (no lookup of its own). ics sent AGL's `tex384` `0x13001650` (traffic 16:58:55.719), which is only
  in the champion's light pack `0xA000014F`; the popup shows in the menus after the world is left, and the box stayed
  black (P: pack not resident). The champion's `grid_icon` (AGL `0x13001652`) is in the UI pack `0xA00000D0` (52 of 54
  champions) and `0xA0000103` (54 of 54), the champion grid's picture.
- `[ics] level_up_icon` default `"grid_icon"` ("tex384" = fase3-ih..fase3-ir). **P**: which DID the original sent.

## Bot champions: shopping at base in build order, tower awareness, frozen at match end (2026-10-30, tester report 15:30, `re-notes/bot-shop-towers-end.md`)

- **Shopping (C log, C data / P meaning).** In the 16:37-16:58 run 8-9 of Poison Ivy's 14 buys came while she lay dead
  in the lane (the player's dead-may-shop rule), one per second as the income paid each tier. The bot script
  `0x340007E2` shops (node `0x10000186`) only while `HasFlagAttribute 0x10000A23`, the may-shop attribute the base aura
  status `0x48001109` adds: bots shop only inside their base aura (`bot_shop_when_dead` false). A visit spends as much
  as it can along the loadout's `0x10000478` list (grouped by line, tier by tier; a lower tier is the next's
  component, cost `0x1000036C` cumulative), the held line's next tier first (`bot_shop_upgrades_first`), passing over
  what the shop cannot sell now and saving for the first step it cannot pay; one 0x20E2 per visit. It goes home to shop
  when the plan would spend `bot_shop_recall_value` credits (no enemy champion within 12 m, 45 s gap).
- **Towers (C code).** The shooters' priority (`Units.think`): an enemy champion hitting an allied champion, else the
  current target, else the closest minion. `bot_tower_awareness`: a minion / structure only when the bot's attack point
  (reach x 0.8, as `World._attack_step`) and the minion are out of every enemy shooter's range + 1.5 m, or the shooter
  is busy with the bot's minions and 2 of them are in range; a champion there only under a busy shooter at
  `bot_dive_health` or for a near-certain kill (share <= 0.2, health <= 2 x attack damage `0x10000B76`); a bot standing
  in an unheld range steps out before being targeted; the push point waits out of it.
- **Match end (C code).** `Match.tick` stops at `over`, but `World.tick` runs on and `_attack_step` kept casting the
  bot's basic attack on its old target; `World.damage` had no end check. `match_end_freeze_combat`: `Match.end` ->
  `BotManager.freeze`; `World.combat_frozen()` refuses damage, non-local casts and attack steps after the end.

## Bot champions: tower tactics - siege behind minions, out when targeted, timed trades (2026-10-30, tester report 18:12, `re-notes/bot-shop-towers-end.md` 4)

- **Why the 15:30 rule stopped the sieges (C log + traffic, 18:00-18:11 run, AI Atomic Joker mid).** 13 "steps out of
  turret mid t1's range (its minions do not hold it)" and only one burst of bot hits on that turret (18:10:36-41, then
  stepped out at 18:10:41.087, 56 ms after the turret's `0x10000C66` went to 0). The traffic shows the turret's target
  at 0 for 0.1-0.6 s after every minion death (`Units.think` re-picks at its next 0.5-0.8 s think); `tower_busy` wanted
  a live minion target at that instant and `bot_tower_min_tanks` 2 tanks, so every death and every 1-minion wave made
  the turret "unsafe"; minions also came before structures in `pick_target`, and from the push point's waiting spot
  (range + 1.5 + 1 m) the turret (11.5 m+) was out of `bot_sight` 9. A headless lane (player kept home, 300 s):
  2 bot hits on the turret with the 15:30 rules.
- **Turret rules the bot plays against (C code, `Units.think` / `Match` damage hook).** A shooter keeps its target
  while it is within range + target radius + 0.5 m (`_valid`); with none it takes the closest minion within reach, a
  champion only with no minion; an enemy champion that hit an allied champion in the last `match_call_for_help` 2 s
  within its reach comes first, and `match_call_for_help_now` re-thinks at the hit, so a champion hit from inside the
  reach turns the turret at once - the hitter's position counts, not the victim's. Shots every 1 / attack speed s.
- **ics (`[ics] bot_tower_tactics`).** `BotBrain.holds(shooter)`: not on the bot, the bot no champion aggressor
  (`Match.aggressors`, 2 s), `bot_siege_min_tanks` (1) of its minions in range with more health together than
  (`bot_siege_tank_shots` 1 + the shots it fires while the bot walks out of range + 1 m) of its attack damage. Held:
  the bot attacks the structure (`siege_target`, within `bot_siege_sight` 14 m, before minions with `bot_siege_first`;
  `Match.protected` still decides what is attackable). Not held while in range: steps out (`step_out`); targeted: walks
  out (`evade`) and comes back as soon as `holds` is true again (no 2 s wait). A champion near a shooter: when the point
  it hits from is out of range + `bot_tower_margin`, in a short trade (held, health >= `bot_trade_health` 0.5, at most
  `bot_trade_depth` 2 m inside range + 1, the shooter's `next_attack` later than `bot_trade_windup` 0.4 s + the walk
  out when the hit lands now; after the hit it is the aggressor -> not held -> steps out), or a near-certain kill. Near
  a shooter it re-decides every `bot_tower_react` 0.2 s. Headless lane with tactics: 11-18 bot hits, the turret's
  health 2500 -> 1209-1446 in 200-300 s, no bot death (`tests/test_match.py bot_tower_tactics_1812`).

## AGL R target filter, Meltdown's orb effect and impact, the Shards end, the Grab hand (2026-10-30, tester report 15:30, `re-notes/agl-r-impact-q-e.md`)

- **Unit-target filter (C, exe 0x85F960):** the unit-flag mask `0x1000068D` a skill block leaves out defaults to
  **0x450109** for every slot but 0 (`0x85F97C`), 0x555959 for slot 0 / -1 (`0x85F986`); the relation mask
  `0x10000448` defaults to 3. Meltdown's block (0x100008E6 of 0x480007A2) sets neither, so the client accepts
  champions, minions and neutral bosses; 18 other blocks set 0x1000068D = 8 (champions only). ics refuses non-champion
  targets for Meltdown on the tester's word (`[ics] cast_target_kind_mask`, error 0x20DC 0x1000003C).
- **Meltdown when its target dies (2026-10-30, tester; C data):** status 0x340002BF's exit chain re-targets: if NOT
  IsAlive(SELF), pulses left and the last pulse's DamageSuccess, FindTargets(JumpRange = stat 23 = 4 m, kinds 0x10108,
  relation 3) scored non-sick +202, champion +101, 1 / distance, and LaunchMissile 0x40000484 at the best; its hit
  applies PulseDuration x PulsesRemaining (AGL's 0x340002B4 S2). ics runs it through `World._death_events`; a death
  caused inside the status' own chain (its pulse kills) now ends that status after the chain, as the client VM queues
  events, so its PulsesRemaining - 1 counts first (`[ics] death_status_end_after_chain`; it gave one pulse too many).
  Minion targets are allowed again (`cast_target_kind_mask` default `{}`).
- **Delayed DestroyEntity of a homing missile (C):** Meltdown's orb script 0x340002BE ends its hit with
  DestroyEntity(SELF)[0.5 s] one update tick after its Vfx_OnCollision; `Missile.arrive` removed the object at once
  (0x3 ~20 ms after the impact key), cutting the impact. Listed scripts now keep the object for their own delay
  (`[ics] missile_destroy_delay_scripts`). 55 scripts use a delayed DestroyEntity(SELF).
- **Effect keys of short flights (C):** Vfx_Active went 0.1 s after the orb's creation; an orb that hits within 0.1 s
  never showed one. Meltdown's orb now gets it at once (`spawned_effect_delays_by_class`).
- **Shards of Will (C data):** status 0x340002C3 removes itself on 0x1000008C for its own temp vital, i.e. when the
  shield is drained; the sphere then ends with Shards_Stop. The latest early ends (1.7 s, 3.0 s) were drained shields.
- **Grab (O):** the missile object flies to the target (its beam's far end reaches it in the video) but its model
  0x17000F70 (world state 0x2E000C4C, no graph 0x5B5; the Shards shell uses the same model with graph 0x1C000083) is
  not seen; no missing server message found.

## Enemies off the minimap by note category; sight inside the lit circle (2026-10-30, tester report 15:30, `re-notes/ca-fog-minimap-category.md`)

- **Why fase3-io's 0x2A1 = false did nothing (C code + traffic).** The server sent it (3 272 hidden minion bundles with
  0x2A1 = 0 / 0x90F = 1), but 0x2A1 is client-local: the fog component's evaluator `0xAAA670` (via 0xA9F240, every
  candidate each update) writes it **true** for every entity unless our champion has `0x100007C0`. The map manager's
  watcher `0xA6A8E0` (manager+0x20) removed the note on the server's false (`0xA4C030`) and re-added it on the client's
  true (`0xA4BD80`). Note lists: +0x38 pending add, +0x48 live, +0x28 pending removal, flushed to Flash
  `RecvNotice_RemoveMapNote` by `0xA22A10`; the -65536 note position (`0xA4C430`) means "other landblock", not fog.
- **Lever that holds (C path, P in game).** `0x100004DA` (net 1, no client writer but the ping builder 0xA843E0): the
  same watcher removes the note on 0 and adds it on a non-zero kind 8 / 10 value. `[ics] fog_minimap_lever` "category":
  enemy lane units / champions out of sight get `0x100004DA = 0`, back in sight the template's category (9 / 2,
  `fog_minimap_categories`); super minions untouched; 0x2A1 no longer sent. "on_map" = fase3-io.
- **Hidden inside the circle (P strong).** With `vision_through_blockers` and the occluder-pass exe patch every allied
  circle is drawn whole, but `World.fog` also needed a clear navmesh line, so an enemy around a building corner at a
  jungle mouth stayed hidden until 3 m. `[ics] fog_sight_line` "auto": the line only without vision_through_blockers.
  In the lane the old rule already matched (headless replay: 6 of 1 045 samples hidden inside 12 m, all within one
  0.4 s fog step). `[ics] fog_log_champions`: a `fog:` server.log line per enemy-champion change (position, nearest
  source, distance, radius, line, reason).

## Crime Alley core: yaw, unarmed, reachable; the decor door; dampener regen; recall fx once; `diag --heads` (2026-10-30, tester report 15:30, `re-notes/core-door-regen.md`)

- **Core yaw (G from the tester, C convention).** Yaw is counter-clockwise from above and the game camera has +y up, so
  "170 degrees to the right" is -170: blue core 90 -> -80 (`[ics] match_structure_yaw_add`); the data's core markers
  `0x2E0011A7` / `A6` say -90 / 90.
- **The core shot (C data / traffic).** Core templates `0x40000C8A` / `C89` carry the turret attack `0x10000328 =
  0x34000014` (185 damage, range 10) and `0x10000C5D = 1`; ics used them as a turret's, so the core killed the red
  minions and the bot that reached it (traffic 16:53-16:58). `[ics] match_unarmed_roles` ["core"]: no attack, no target,
  `0x10000C5D` / `0x10000C5B` false in the bundle.
- **Nobody hit the exposed core (C).** After the Power Core Turret fell (16:55:15, 0x100007D9 sent, shield stopped) the
  server never called `World.damage` on the core: the red units fought the blue wave spawning at the lane mouth next to
  the core and died to its shots. A melee minion's 3 m sight (the template's smaller 0x10000133) was measured to the
  core's centre, 3 m inside its blocked footprint, so one standing at the rim had no target: `[ics]
  match_structure_sight_to_edge` (Units.enemies_near counts a structure from its edge). Sim: the red waves take the
  core 4000 -> 0 in ~70 s.
- **Decor door (C absence, G spot).** No Crime Alley static / layout / marker places a door. `[ics] match_decor_doors`:
  the base-gate world state `0x2E000CD7` as a bare object (no class: no collision polygon), side 3 / 5 (Object_Closed's
  switch lights the wall `0x2E000CD8`), scale `0x6B4` 0.4, Vfx_OnInit + Object_Closed, never opened; G at (33.0, 83.2)
  / (127.0, 83.2), the tester's screenshot did not arrive.
- **Dampener (C logs).** Its respawn worked (16:52:43 -> 16:57:43, lines 64 / 63, new IID) and it fell again 20 s later;
  but a damaged structure never healed (504 / 3000 for 2 min). `[ics] match_structure_regen` {"dampener": 15 HP/s after
  10 s without a hit} (G; no regen property in its template; `0x10000140` = 10 on the core, 50 on the PCT, meaning O).
- **Recall streaks (C rule, P cause).** The fase3-ij hold re-sent the fx 4 times with its own run number, which signals
  a live run (`client-scriptlets-graphs.md` 1.4). The streaks are the fx's type-3 spawn = the client's timed indicator
  object `0xA847E0` (DIDs `0x10000940`-`943` from a record's +0x2C..+0x38, progress `0x10000945`, `0x10000944`; callers
  `0xA884A0` / `0xA88590` set `0x100008D5` / `0x100008D7` duration / `0x100008D8` elapsed / `0x1000093F` and run keys
  `0x10000381` / `0x10000380`). `[ics] start_scriptlet_hold_mode` "defer": sent once 0.12 s after its tick, never re-sent.
- **Turret heads (O).** Nothing we send reuses the head's Vfx_AI_Active run number; the body's Object_Ranged_Attack
  already runs Vfx_Basic_Ranged (type 23), ours is a duplicate network run. `python tools\diag.py --heads` logs every
  spawned-child end (`0x666b40`, owner IID) / render-effect end (`0x65ca30`) / run removal (`0x57baf0`) with the stack and
  every server 0x8D (`0x6279d0`).

## Hover highlight: the champion's 0x3CB listener is gated on its IID top byte (2026-10-30, tester report 18:12, `re-notes/hover-listener-iid-gate.md`)

- diag --hover 18:00:46-18:03:29 (R): the selection tick's pick works: 0x3CB took every wave-1 enemy minion
  (0x148 / 0x14A / 0x14C / 0x14E, score 20 with flags 2), the allies 0x147 / 0x149 / 0x14D (1.3), structures, the bot.
  But `outline colour` (0xA4EDEC) fired only 12 times, never for an ally / structure / the bot, and for enemies only
  right after an attack or ability order on them (lock / ability paths); the four outline colours all have green =
  alpha = 1, so the alpha-1 lines are the attack lock's yellow (1,1,0,1) `0x186D9C8`.
- Every hover effect lives in the property listener `0xA5D5F0` (vtable `0x1604224` slot 3) case 0x3CB (C):
  `0xA4ECC0` -> `0xA1CD40` starts **`_Selection_SoftSelection_Valid` 0x100001E4** (validator `0x9D01D0` accepts with the
  current slot) or **`_Invalid` 0x100001E6** on the hovered unit (`0x588A00`; stopped by `0x58CBB0`); attackable unit:
  `0x8BB950` (RecvNotice_UsableTargetInRange) + `_Selection_Usage_Valid` 0x100001DF; `0xA4EDD0` (green 0x974 outline
  only for a non-attackable unit, our champion or an armed ability's target: `0xA1D020`); cursor `0xA1CDD0`. Lane
  minions, turrets and camps have 0x100001E4 / 0x100001E6 in their tables (not 0x100001DF / E1).
- The listener (and those on LifeState 0x100000FA, 0x10000B2D, 0x100008E3-0x100008F2, plus 0x100000CE = true and the
  attack range +0x58) is registered by the controlled-agent handler `0xA16730` only when `0x4DAF10(agent IID)` (top
  byte == 2) is false: `jne 0xA168DA` at va 0xA16809. ics's champion is `0x0200000000000002`, so no hover effect ever ran.
- Fix (exe patch "controlled agent listeners", `icserver/patcher.py`): file 0x615C07 `84c00f85cb000000` ->
  `84c0909090909090`. `[game] exe_patch_skip ["controlled agent listeners"]` restores it. Needs `python ic.py patch`.
  `diag --hover` adds `agent listener gate` (0xA16807), `0x3CB listener` (0xA5D709), `soft selection start` (0xA4EDAB).

## Turret heads: the `--heads` trace; lane turret death and wreck (2026-10-30, tester report 18:12, `re-notes/turret-death-head-rearm.md`)

- **Trace (C).** diag.log: `--hover` 18:00:46-18:03:29, `--heads` 18:03:38-18:04:29, `--strip` after. IIDs (creation
  order from `0x0200000000000100`, bot first): dampeners 0x10B / 0x10C, lane turrets 0x10D / 0x10F, PCT 0x103 / 0x107.
  In the `--heads` window no spawned-child end (`0x666b40`), render-effect end (`0x65ca30`) or 0x8D touched a structure
  while lane turret 0x10D fought four times; its first fight (18:03:08-25) predates the probe. The head had already
  gone (P: first fight, as in every report since fase3-ip); the trigger is still O.
- **Client run ids (C, decompiled).** `0x57BDC0`: a run started with the "no instance" value 0xFFFFFFFF
  (`DAT_0185F2B0`, local type-23 runs) takes a per-component counter id (+0x50); server runs keep the server's
  instance; both share one first-match id list (`0x57B390` / `0x57B400`). `0x57C260` refuses a run past the
  definition's instance limit (`0x51F080`, property 0x479, default 1, result 0x80044321); `0x536C40` removes a run that
  is not live right after it runs (`0x514B70`). O: whether a local id equal to the head run's instance (ics numbers runs
  from 1) ends the head.
- **Mitigation (P).** `[ics] match_turret_head_rearm` {"after": 3, "gap": 0.2, "min_gap": 20}: after a fight the body's
  Vfx_AI_Active runs are stopped (0x11F, instance 0xFFFFFFFF) and a new run makes the head again.
- **Lane turret death (C data).** `0x1D00035D` _Defeat_OnDead = type-23 run of Vfx_OnExplode, a type-9 branch, graph
  Death `0x100001C0`; graph `env_pvp_lane_turret_a_body_behavior` Death = die_a (0.1 s) + rigid-body / powered ragdoll
  modifiers, no exit (Idle = idle_a 5.98 s). ics removed the body after corpse_seconds with no key (traffic 18:11:11.741
  -> 15.751). Now `match_keep_body_roles` += turret / inner_turret (wreck kept: no respawn) and
  `match_structure_death_scriptlets` turret / inner_turret = ["_Defeat_OnDead", "Vfx_Stop"] (Vfx_Stop `0x10000130`,
  base `0x1D000372`: stops Vfx_Active, Vfx_Targeting, Vfx_Event1, Vfx_AI_Active = head + hum). The dampener already
  plays Object_Deactivate + graph Death (graph `0x1A000B15`, Deactivate clip 1.0 s); unchanged.

## Skill buttons, facing locks, left sub-graphs, status record flags (2026-11-02, anim-18)

Tester's game test 2026-11-02 01:39-02:20 (Arcane Green Lantern, Atomic Joker, Superman, Blue Beetle on the Coast City
sandbox). Evidence: `logs/server.log` / `traffic.log` of that run, the decoded trees (`python -m ics.script_model`),
the records read by kind, and `tests/test_kit_fixes.py` (29 checks). C = read in the data / the run, P = probable.

- **SetSkillStatOverride 0x100000FA is the button's presentation (C for the fields, P for the wire).** Read across the
  61 nodes of the 875 trees against the slot blocks (`0x100008E8` ...): field 2 / 3 = a string pair (id, table
  `0x2B......`) like the block's name `0x100001C0`; 7 / 8 the description `0x1000003E`; 11 an icon `0x1300....`
  (`0x10000302`; Blue Beetle R's 0x13001DE6 / DFE / DFF); 12 `0x100002A3` (0x48000154 / 0x48000156, the values of
  Blue Beetle's base Q and melee Q blocks); 14 the targeting type `0x1000003D` (only 1, 5, 7, 13, 14 occur; 5 in AGL's Q
  teleport window 0x34000293 S4, Superman's E punch window 0x340003D6 S4 and Blue Beetle's W detonation 0x34000454; 13
  in Super Strength's throw 0x34000164). Fields 13 / 16 / 17 / 18 / 19 (1 or 2) are open. The node has no client half
  (vtable slots 7 / 10 purecall), so the original server sent it. ics sends the local champion's slot table (kind 0x0B,
  the whole block, as the Stolen Powers' `0x100008F0` / `F1`): the skill set's block, a SetSlotSkill record's block
  over it (entries by id, stats by stat id) and these fields (`ics/skill_slots.py`). The run showed why it matters: AGL
  pressed Q again at 01:40:49.182 (`0x20EA`) and the client opened the aim indicator (targeting 13) instead of
  casting; the click came at 50.623, after the construct was gone (49.70), and the indicator stayed.
- **SetSlotSkill's client half (P).** The client re-reads a slot's skill when its slot property changes (listener
  `0xA5E150` -> `0xA4F6B0`, client-skill-instances.md 2); Blue Beetle's R records 0x48000A97 / A95 / A96 carry their own
  icon, targeting (melee Q: 14, a leap at an entity) and script. The run kept the ranged buttons.
- **FaceTarget's facing lock (C from the script).** Blue Beetle's E 0x34000455 S1: `DashToPosition(SELF, Target)`,
  `GetPosition(SELF, Start)`, `Offset(Start, Target) -> PositionOffset`, `FacingPosition = Start + vec3(-x, -y, 0)`
  (0x3E / 0x3D are x / y), `FaceTarget(FacingPosition, -, $FacingIDVariable)`; S3 (the landing) `ReleaseFacing`. So
  the original hops with its back to the dash because the script faces the point behind the start, not by a rule of
  ours. Its shots look along that facing: `FindTargets` box of length (travelled + TargetRadius 5.75) and width 11.5
  from the champion along his facing = the path he left, where the enemies are; `CanSee(-, $LoopingIID)` with an unset
  observer (= SELF), one shot per target (`AddToList` / `IsInList`). `Stick_And_Move_Right` 0x100003FE / `_Left`
  0x10000404 are raised per shot, alternating hands (not side hops as anim-16 read them). ics: a lock on the entity
  while moving keeps the heading of travel (the client moves along it) and turns the model with `facing_offset`;
  `CastWorld.heading` returns the model's yaw under a lock; ReleaseFacing drops it.
- **Left sub-graphs kept running (C, simulated).** Atomic Joker's R 0x340004DA: graph S1 `T0: S1 -> S0` on NOT
  IsAlive / BurstCount >= TotalNumBursts (4) / MaxTimer (8 s) fired at 8 s, but the left burst graph kept its state,
  so its own timer poll fired a burst every 1.1 s for ever (in the run: 01:43:10 -> 01:44:14, after his death and
  respawn). `Region.leave` now halts the left child.
- **A graph state's enter chain runs before its sub-graph (P from the knockback, C for the run).** Status 0x340003F8
  (Superman's E knockback): graph S1's enter sets EffectSource and KnockbackDistance (stat 17 of the source's slot 3 = 6
  m, minus the distance); its sub-state S2, entered at once, runs `DashToPosition(SELF, TargetPosition, speed,
  KnockbackDistance)`. ics started the sub-graph first: the dash went 0 m. Top-level graph chains already ran before
  the first state (`[ics] top_graph_chains`). The champion_check run with the new order changed 11 slots; Nightwing's
  R 0x34000794 no longer explodes the bike at the first press (S5's enter now runs before its sub-graph; the second
  press launches it).
- **Status records carry their own flags (C).** 232 status records hold list `0x1000046F` of `{0x10000450 attribute,
  0x10000453 op, 0x100004C3 bool | 0x100008A7 number}`; ics read none. Superman's W root 0x48000A06 roots only through
  it (Rooted 0x100007FE, op 6); its script 0x340002A9 shows the ice (`0x100003EA`, fx 0x1E000257) and the icon
  0x48000792, and leaves S1 at once by a trigger-less `[2, 0]` transition (the run: icon at 01:45:46.144, removed at
  .146). The op-6 flags now hold for the status' lifetime; numeric entries (op 7 / 9 / 10) wait for their value's
  source. Open: the meaning of a trigger-less transition's b = 0 (38 of them; the basic attack's impact pulse
  0x34000037 graph S2 needs it to fire, the root's icon would need it not to).
- **Defeat guards and direct hits (C).** Atomic Joker's passive 0x340004DE holds a type-0 guard and waits for
  0x1000011B; a turret killed him at 01:43:45 through `Units._direct_attack` -> `World.damage`, past the guard check of
  `script_nodes.deal_damage`. `World.damage` now applies it too.
- **Atomic Joker's R rank bonus (C).** 0x340004DA S0's exit adds `RangeIncrease` (stat 12 = 0.06, +0.03 per rank) to
  attribute 0x10000A9F on himself: the original's +6 / 9 / 12 % range for every skill and the basic attack.
- Stargirl's W 0x3400056D also asks `CanSee(-, $TargetIID)`: its small stars now home on a visible target (131.8
  damage on the dummy, was 6.8).

## Local frames, per-form cooldowns, the champion bundle's facing, The Punch Line's needs (2026-11-03, anim-19)

Tester's game test 2026-11-03 00:29-00:40 of anim-18 (`logs/server.log`, `traffic.log`). C = read in the data / the run,
P = probable.

- **Operand sources are variable frames (C from the data).** An operand is `value (name hash) | source | slot`; source 1
  = the script's variables, 2 = the owner block, 3, 4, 5 ... = the local blocks of nested graphs / states by depth (the
  slot is the offset inside that block). Heat Vision 0x340003D6 uses TargetIID at source 3 (graph S1: the cast's target,
  the punch's ApplyDamage) and at source 5 (graph S7's sub-graph: `SetVariable($TargetIID<src 5>, #Collider)` on each
  dash collision). ics stored variables by name only, so a collision replaced the punch target (run: the punch hit Swamp
  Thing, 00:32:34.158). 95 scripts use a name in two or more local frames; ics now keeps those names per (source, name).
- **The owner block's cooldown array (C from the data, P for the writer).** Blue Beetle's Q / W / E graph S2 (the form
  swap) reads `<0xABD05A2 src 2 slot 0x28>` / `<0xABD0592 slot 0x30>` / `<0xABD0582 slot 0x38>` as "end - now" and saves
  them in 0xD0 / 0xD8 / 0xE0; only 0x3400040D / 40E / 410 also read 0x28-0x38, and no script writes them: the engine's
  f64 at 0x20 + 8 x slot = the slot's cooldown end (the client's per-agent cooldown store, full-combat-skills.md 1.3).
  `StartCooldown(TimeRemaining)[slot]` then puts the other form's remaining cooldown back, 0 = ready (ics ignored 0).
- **Blue Beetle's basic reach (C).** 0x34000457 graph S0's exit: `LoadSkillStats(RangedRange 18, MeleeRange 17)`,
  IntendedRange by the owner flag 0xE8 (the form), `SetSkillStatOverride(IntendedRange)[-1, 18]` when it differs; it
  re-inits on 0x100000A9 (raised after every slot swap).
- **The champion bundle's facing (C, ics).** `Session._objects` (the local champion's bundle in "bundle" mode) did not
  pass `World.tilt`, so a facing lock's `facing_offset` never left the server.
- **QueueOrder and the action lock (C for the client's buffer, P for the server).** Heat Vision's S8 runs the finisher's
  graph event and `QueueOrder(SELF, $TargetIID)[2 0 ...]`; the basic attack's 0x10000128 went 30 ms after the graph event
  and replaced the animation. The client holds orders while an action lock is held (0x863860); the server's attack step
  now waits while a skill of the champion is in its cast (the action lock itself can stay held in ics: Wonder
  Woman's Q 0x34000185 S6).
- **Blue Beetle's Energy Cannon area (P).** The missile 0x34000489 explodes in S7 (both casts in the run) and spawns its
  area object 0x40000CD8 at the collision in S1; its 0x10000016 scriptlet left 5 ms after the object's creation in the
  first cast (110 ms in the second). Open whether the client drops a scriptlet on so new an object.
- **The Punch Line 0x340004DE (C for the nodes, O for the control switch).** S0: `SetDefeatType(Handle)[1, 0]` (type 0).
  On 0x1000011B -> S2: `SpendCost(-100 %)[vital 2, percent]` (health to 0), `AddAttributeModifier` x3: 0x10000249
  (attackable) = $False, 0x10000140 (health regen) = $HealthRegenRate, 0x10000786 = $HealthLock; S2 -> S1 on
  NOT HasStatus(flags 0x2000). S1: SpawnEntity head 0x40000A68 (team, level), `node_100000A1($HeadIID, SELF)`; exit:
  `node_100000A1(-, SELF)`, the head's 0x10000130 and DestroyEntity unless smitten. 0x100000A1 has no client half
  (full-combat-skills.md: "SetOwner / link"); the tester's original (HUD 1/1 health, 8/8 jumps on the second bar, a
  counter bar under the name, control of the head) says it makes the head the player's controlled agent. ics: the node
  is a logged no-op, 0x10000786 / 0x10000249 are not honoured (the next turret shot killed him, 00:37:47.929).

## Knockback heading, own-animation waits, spawned objects' first events, deferred stops (2026-11-03, anim-20)

Tester's game test 2026-11-03 14:39-14:56 of anim-19. C = read in the data / the run, P = probable.

- **0x41 "with heading" takes a vector (C for the data, P for the rule).** Status 0x340003F8 (Superman's E knockback):
  `KnockbackHeading = heading(EffectSourcePosition)`, then inside the If `Offset(EffectSourcePosition, EntityPosition) ->
  KnockbackHeading` (a vector), then `TargetPosition = transform(with_heading(EntityPosition, KnockbackHeading),
  vec3(0, KnockbackDistance, 0))`. ics turned the vector into the number 0: every target went toward +x. A vector now
  gives its own direction, which sends the target on along Superman -> target (what the tester sees in the original).
- **A state that raises its own animation waits for its end (C for the run).** Heat Vision 0x340003D6 S8: RaiseGraphEvent
  0x100003CA (finisher), ApplyDamage, QueueOrder; `T15: S8 -> S2 on OnCastSignal 2`. With no Cast node running,
  `Region.finished` gave the chain's result RESULT_DONE (= 2) and T15 fired at once (14:40:52.643); the finisher's hook
  2 came at .812, the queued attack's 0x10000128 at .811. A state whose enter chain raises a graph event and that waits
  for code 2 now starts the cast path (the graph's code 2 when its state is left).
- **Spawned objects' first events (C for the run, P for the order).** Blue Beetle's E (0x34000455 S1 of graph S2):
  SpawnEntity 0x400008C4 then LaunchMissile($MissileIID, $TargetIID). The shot's script 0x340004AA: S0 -> S5 on
  0x10000049, S5 -> S3, `S3 -> S2 on NOT IsAlive($TargetIID)` (S2 = DestroyEntity(SELF) after 0.06 s), `S3 -> S6 on
  0x100000EE` (sets TargetIID). ics raised 0x10000049 inside SpawnEntity, so the shot died before the launch's
  0x100000EE. Its damage: `LoadSkillStats($ShooterIID, Damage, ReducedDamageMult)[5 1, slot -1]` in an object with no
  slot read 0.
- **Deferred stops (C, ics).** `CastWorld.stop_scriptlet` for the local champion is sent champion_scriptlet_delay late;
  it looked up the live run at the send. Blue Beetle's passive S6 update stops ActiveVFXHandle and starts 0x10000BC6 in
  one step on a form change (14:42:50.380); the stop then took the new run, and S3's stop at the buff's end (56.231) was
  only logged.
- Open: what redraws the skill buttons after a slot table change (the tester: only at R's cooldown end); whether Blue
  Beetle's graph takes Infiltraitor_Activate / _Deactivate 0x10000405 / 0x10000407 (the blasters).

## Scriptlet handles and runs; the graph takes Blue Beetle's form events (2026-11-03, anim-21)

- **A StartScriptlet handle names one run (C for the run, C for ics).** ics keeps one live run per (entity, key) and
  `StopScriptlet(handle)` stopped that newest run. Heat Vision 0x340003D6 runs three 0x10000223 on its target (the laser
  `StartScriptlet[$ActiveScriptHandle] fx 0x1E000389`, HitEffect fx 0x1E00038A, the knockback's HitEffect without fx),
  then `StopScriptlet($TargetIID, $ActiveScriptHandle)`: the run stopped was 0x16 (traffic 15:27:48.977), not the
  laser's 0x14. The beacon is `StartScriptlet($TargetIID, $HeatVisionActiveHandle)[0x10000223, fx 0x1E0003F5]` (S3
  exit; stopped in S2 / S6); the R 0x340003D5 holds `0x10000AC7` on Superman (variable 0x10000030 = target) and
  `0x10000223 fx 0x1E00038B` on the target. The handle now keeps its run and the stop names it.
- **Blue Beetle's form graph events (C, diag --graph 15:33:15 / 15:33:30).** Infiltraitor_Activate 0x10000405 reaches
  his graph at index 0x54 and _Deactivate 0x10000407 at 0x55 (flags 0x49, delivered); the ToMelee scriptlet 0x10000BD7
  raises 0x10000405 itself as well. The blasters' visibility is not this event alone (open).

## SkillEcho 0x10000195 and the punch's cast (2026-11-03, anim-22)

- **SkillEcho (P).** 221 skill scripts run node 0x10000195 (no client half) right after their cast point; Blue Beetle's
  passive 0x34000456 graph S1 waits for 0x10000196 (T7) and sets `$SkillSlot = #0x5A364` (ELF hash of "Slot") to count
  Q / W / E / R uses. The node now raises 0x10000196 {Slot} on the owner's scripts; ics's own broadcast at the activation
  (kit-audit-2.md 4) stays for scripts without the node. In the run the melee E / W fell in the passive's 12 s cooldown.
- **The punch's cast (C, ics).** anim-20's own-animation wait starts a cast for Heat Vision's S8; after the graph's
  "no state entered" fallback (16:09:02.176) its timed cast kept `casting = 1` once the state was left, so
  cast_holds_movement held Superman about 2 s. Leaving the state ends that cast.
- **Heat Vision's beacon (C for the server, O for the client).** `0x10000223` with variable 0x1000050A = 0x1E0003F5 on
  the target, its own run (16:08:59.655), stopped at 16:09:02.257: sent as the script says; not drawn.

## Every 0x8D replaces the server's runs; 0x11F stops one; 0x2073 adds (2026-11-03, anim-23)

Game test 2026-11-03 22:14-22:21 (Superman, Blue Beetle on Coast City PvP): the punch sound missing; Blue Beetle's
passive particles (Vfx_Blu_Rdirective_Disruption_Active 0x10000BC3) gone in ranged form; his yellow blaster stayed
after the buff until he fired again.

- **0x8D stops before it starts (C).** The list handler 0x627E20 (from 0x634F20) calls 0x57CB60 at 0x627E4D with a
  filter object on the stack (vtable 0x15C9750: +4 = 0x6272D0 `return run->ctx->byte_60`, +8 = 0x55B9C0 `return 0`).
  0x57CB60 walks the script component's runs (array comp+0x18, count comp+0x0C), collects those the filter picks and
  calls 0x57C4B0(&r, 0, 1, run number, 1) for each: 0x57B920 -> 0x52D790 (ends the run; state 5 runs are unlinked from
  both lists). 0x6279D0 sets ctx+0x60 = 1 on every run a network order starts (client-scriptlets-graphs.md 1.2 step 5),
  so every 0x8D first ends every run earlier server orders started on that object, then starts / signals its own
  entries. A later entry whose run number is no longer alive is a new run (step 4). This is anim-09's finding for Green
  Arrow's quiver (tag minha-versao-icserver, "The anim-09 game test of 2026-10-27 01:13"); the 1.4 note "no new
  scriptlet replaces the old one" covered the entry loop only.
- **Consequences seen.** 22:16:44.474: Disruption_Start 0x10000BC4 and _Active 0x10000BC3 went in two orders and the
  Energy Cannon's stop (an 0x8D with signal 1) followed in a third: the loop lived 0 ms. 22:19:50.770: the buff's stop
  (an 0x8D, signal 1, run 26) found the run dead and started the loop again: the yellow blaster until the next shot's
  order. 22:15:11.802: Superman's Vfx_Sup_Heat_Vision_Dash_Stop 0x10000B25 (the punch, with its sound) was followed 1 ms
  later by a graph event 0x100001E3 in an order of its own.
- **0x11F (C).** Exec 0x675280 -> 0x57C4B0(key, mode = the u8, run): stops one run (0xFFFFFFFF = every run of the key)
  without touching the others. The client's own StopScriptlet 0x588A80 passes mode 1.
- **0x2073 (C, unused).** Handler 0xA883F0: when the object's +0x110 equals the global 0x1B759EC (bss, compared all
  over 0xA1....-0xA8.... like a "none" DID), 0xA22DA0 starts the entries with 0x6279D0 and skips live run numbers
  (0x57B510), with no stop-all; otherwise the list goes to a per-IID map of the manager 0xA12D50 (0xA82DF0 /
  0x588D40). Runs it starts still carry ctx+0x60, so a later 0x8D ends them too. To read +0x110 and 0x1B759EC with diag
  before using it.
- **What ics does (P for the policy).** ics/scriptlet_orders.py wraps World.send: consecutive 0x8D messages to one
  champion go as one order (until another message or the end of the scheduler step), a StartScriptlet run rides along
  after the new entries of every later order to that champion until its StopScriptlet, and a script's StopScriptlet is
  0x11F mode 1. The original server's policy is not known; it kept such loops (the tester remembers the particles for
  the whole buff). A held run is restarted by each order (stop-all, then a new run with the same number): a short
  blink. The blink-free way would be the script component's replicated state (OnSync 0x627C70, anim-09 item 9) or
  0x2073 if its direct path applies to champions.
- **Blue Beetle's passive cooldown (C, script 0x34000456).** S3 `StartCooldown($CooldownDuration)` runs when the buff
  ends (S6 -> S3 on its timer, or S1 -> S3 after the bonus hit), so the next trigger is 6 + 12 s after the last one at
  rank 1; the melee Q at 22:17:54.886 was 3.8 s after the buff's end (22:17:51.077).

## Button redraws, skill used, the punch sound and 0x2073 (2026-11-03, anim-24)

Game test 2026-11-03 23:21-23:27 (Superman, Blue Beetle on Coast City PvP).

- **Button redraws (C traffic, P fix).** The HUD skill loop redraws only slots marked dirty; the patched client's
  code cave D marks slots 0-8 when champion property 0x100006C1 differs from its last read (every frame). A form swap
  refreshes six slot tables in a few steps over ~0.12 s (23:26:54.666-.785); anim-19 toggled the property's top nibble
  1 <-> 2 at each, so six toggles left it unchanged and the buttons waited for R's 0x20F8 "ready" (3 s). The skill
  bar also redraws on the overlay notice 0x1000015A (Skill.UpdateSkillUIOverlay): the swap at 23:26:44.429 sent the
  passive's and was instant. ics now toggles once, slot_table_hud_refresh_delay (0.1 s, ours) after the last table
  change. The original's own trigger is not known; candidates on the wire: 0x207C (slot override, its last u32 = slot
  to refresh) and 0x208C (Skill.UI_NotifySkillButtonUpdateIsSuppressed), never sent by ics.
- **"Skill used" (P).** Scarab Scanner 0x34000454 calls SkillEcho 0x10000195 at its launch (S4) and nothing at the
  detonation (S4 -> S3 on 0x1000001D); the tester remembers the passive starting at either. So the notice comes from
  every taken activation (as ics did before anim-22, kit-audit-2.md 4); SkillEcho raises it only for a use whose
  activation did not (a SkillEcho inside the activation event counts as the use's notice).
- **The punch (C graph data).** Superman's graph: HeatVision_Finisher (121) runs the sub-machine 20:
  HeatVision_Finisher_Loop (flight loop clip) -> on HeatVision_Loop_to_End -> HeatVision_Finisher_End (the punch
  clip, skill_to_cosmetic at 0.1 s). Heat Vision S7 raises Finisher, S8 (dash arrived 0x100000C1) raises Loop_to_End
  0x100003CA. S7's exit runs Vfx_Sup_Heat_Vision_Dash_Stop 0x10000B25 (sent at 23:22:12.170); the basic attack's 0x8D
  at 12.420 ended its run (anim-23's rule). The target's TargetHit 0x10000223 with fx 0x1E000403 lived 12.033-12.749.
- **The original's way (P, skill-animations-and-skins.md 3.1).** RunScriptlet / StartScriptlet / RaiseGraphEvent have
  client halves that start runs through the local path (0x57C260; ctx+0x60 clear, so no 0x8D ends them) with
  originator = the local player; a server 0x8D with that originator is dropped (0x6279D0 step 2). The original server
  most probably replicated each champion's skill scripts to the client (0x200F / 0x200C, as ics does for status
  scripts) and the copies played the visuals.
- **0x2073 (experiment).** Exec 0x8B5B20: the object by the message's destination IID, then 0xA883F0(object, list).
  Direct start (0xA22DA0: 0x6279D0 per entry, live run numbers skipped, no stop-all) only when object+0x110 equals
  [0x1B759EC] (filled at run time); else the list goes to 0xA12D50's per-IID map. `diag --orders` logs both values.
  `[ics] scriptlet_orders_event = "0x2073"` sends a champion's orders that way (no ride-along).
- **Q explosion (open).** 0x34000489 S7: RunScriptlet Vfx_OnCollision on the explosion object 0x40000CD8 and on the
  missile, DestroyEntity(SELF)[0.1, 1], DestroyEntity(explosion)[0.3, 0] (the flag's meaning not known). ics's
  spawned_effect_scriptlets sends the missile's Vfx_OnInit 0.1 s after creation, after the collision on a short shot.
- **Melee wings (open, P).** The To_Melee / To_Ranged entries (table 0x1D0005AD, pack 0xA0000201) name 0x19000D86
  with 0x100000E3 / 0x100000E6 / 0x100000E2; their runs end at the next 0x8D in ics.

## 0x2073 confirmed; the basic attack's facing and swing (2026-11-04, anim-25)

- **0x2073's direct path (C, diag).** `diag --orders` (2026-11-04 00:51-00:56, logs diag1 / diag2.1 / diag2.2): at
  every 0x8D list (0x627E20) on the champion (IID ..02) and the bots (..100 / ..101) the object's +0x110 = 0 and the
  global 0x1B759EC = 0, so 0xA883F0 calls 0xA22DA0 directly for those objects: each entry through 0x6279D0, live run
  numbers skipped, no stop-all. ics sends a champion's script-node scriptlets (labels of CastWorld.run_scriptlet)
  as 0x2073 and keeps 0x8D for the server's own orders (P for the split; it follows skill-animations-and-skins.md 3.1:
  the original's client copies of the skill scripts started those runs locally, where no 0x8D ends them).
- **Basic attack facing (C, script).** The champions' basic attack scripts call FaceTarget($TargetIID)[1 0 0.15]
  in their swing state (Blue Beetle 0x34000457 S1) and ReleaseFacing at its exit. World._attack_step turned the
  champion on the server before casting, so CastWorld.face saw a turn under face_min_turn_degrees and sent no
  facing: the client kept the old heading (shots with his back to the target).
- **Walking during the swing (C data, P rule).** Blue Beetle's graph: Ranged_Basic_Left 104 / Right 115 (clip
  triggers a_SkillHold 0.05, basicattack_to_basicattack 0.24 -> the Cosmetic state) and Basic_Attack_Melee 116 have
  no Lua early-out; their Cosmetic states run onCosmeticEarlyOut / Combat_Locomotion_* (movement ends them). ics took
  move orders at once during the swing (00:50:19.795 / .936 between start 19.676 and fire 19.975): the champion slid
  while the clip played and the shot still left. Now a move ordered while the graph is in a state the basic attack's
  script hooks waits for the state's exit (code 2), then runs. Who held it in the original (the server's order
  system, P; the client buffers only on its action code / lock counter, full-combat-skills.md S3.7) is not known.

## 0x2073 tried; the champion scriptlet delay (2026-11-04, anim-26)

- **0x2073 in the game (C traffic, tester).** With the champions' script scriptlets sent as 0x2073 (anim-25) runs
  were never ended early, and also never ended: Superman's Vfx_Sup_Heat_Vision_Eyes_Active (StartScriptlet, run 23)
  stayed after its 0x11F (01:29:12.183, key and run right), and the basic attacks' streak runs stayed. 0x11F's exec
  calls 0x57C4B0(.., key, mode, run, 0): with the last argument 0, 0x52D790 posts the stop signal 0xFFFFFF01 (a
  definition's signal handlers; P that these loops have none) instead of 0x529EF0 (end list, attachments released),
  which the 0x8D's stop-all uses (argument 1). The punch sound, the Q explosion and the melee wing glow stayed missing,
  so runs ended early were not their cause. Default back to 0x8D.
- **The champion scriptlet delay (C traffic).** A basic attack decided at 01:31:31.111 (the script's S1: StartCooldown,
  FaceTarget, the swing's scriptlets) reached the client at .251: champion_scriptlet_delay 0.13 s plus a scheduler
  tick. graph_feed_at_send feeds the server's graph at the send, so the hooks (shot, swing end) are as late as the
  client's clip, while the cooldown counts from S1. The delay's reason (2026-10-21: a champion bundle re-creates the
  object and cuts an animation) was found wrong (object-update-bundles.md, C). The sandbox now runs with 0 (P).
- **The swing and movement (C data).** The basic attack's graph state ends at the shot (Blue Beetle: the clip's
  basicattack_to_basicattack at 0.24 s, then the Cosmetic tail); onCosmeticEarlyOut lets movement end the tail. The
  held move (anim-25) waited 31 ms at 01:31:31.534.

## The beam's middle, the lost form swap, the explosion's flag (2026-11-04, anim-27)

- **Superman's beam (C traffic).** Heat Vision 0x340003D6 S3 runs RunScriptlet(SELF)[0x10000ABE
  Vfx_Sup_Heat_Vision_Active, 0x10000030 = target] (the beam) next to the held eyes 0x10000B94 and the target's
  StartScriptlet 0x10000223 (fx 0x1E000389, the beam's end). In 4 of 13 casts the next step's orders (0x100001E3,
  0x10000AB7, 0x10000AB9) went 8-11 ms later in a second 0x8D, which ended the beam (the held eyes and target end ride
  or live on the target). Between them only vitals / modifier / status icon messages went out; they flushed the
  waiting orders (anim-23's "any other message" rule). They now do not.
- **The lost form swap (C traffic, P cause).** R 01:58:37.765: server melee, tables and the redraw sent, To_Melee +
  graph event 0x10000405 in one order (.771, + the passive's held loop); .850 the passive's form restart
  (0x11F + 0x10000BC6 in its own 0x8D). The tester then saw ranged and pressed R (52.375), which the server took as
  melee -> ranged. Whether the client graph dropped Infiltraitor_Activate (or the .850 order's stop-all ended the run
  before its action) is for diag --graph (0x2279D0 started, 0x2729A9 reaching the graph, 0x15BD43 / 0x15BD82 dropped /
  queued).
- **DestroyEntity's client half (C, 0x9B56D0).** 0x588A00(_HFSM_DestroyEntityAction 0x100001E0) on the object; if it
  ran, 0x445840(object IID, delay = node f32 +0x24) posts the removal event 0xFA; then
  _HFSM_DestroyEntityAction_Optional 0x10001128; flag byte +0x28 = 1: event 0x100000A1 (template 0x460BB0) with the
  object's IID (parameter hash 0x2572644) to the creator's HFSM (0x991F60 source, 0xAA1A60, 0x96DE90). Energy Cannon's
  explosion object uses [0.3, 0] (no notice), its missile [0.1, 1].
- **The Q explosion (open).** Shown at 01:59:27.964, missing at 01:58:19 / 26 / 36: same spawn -> collision (110 ms)
  -> removal (300 ms) timings and the same messages; only the run number grew past 127 (a 2-byte compact).

## Energy Cannon's explosion (2026-11-04, anim-28)

- **Where the explosion is (C, data).** Energy Cannon's missile 0x40000815 (script 0x34000489) spawns the explosion
  object 0x40000CD8 at the collision (S1 SpawnEntity) and, 0.1 s later (S7), runs Vfx_OnCollision 0x10000016 on it and
  on itself, then DestroyEntity(SELF)[0.1, 1] and DestroyEntity(explosion)[0.3, 0]. The explosion object's world
  state 0x2E0009F0 / tables 0x1D000456, 0x1D0008DE: 0x1D0008DE (pack 0xA0000202) holds only Vfx_OnCollision = one
  action type 0x11 (particle emitter on the object, client-scriptlets-graphs.md 1.6) 0x18000BDB, floats 40.0 / 60.0,
  probability 1.0. The particle record 0x18000BDB (5 160 bytes, same pack) has 6 emitters with times 0.05-0.5 s. The
  missile's own Vfx_OnCollision (table 0x1D0005C8) only stops its trail Vfx_OnInit 0x10000078 after 0.06 s.
- **Game test 02:44-02:47 (C traffic).** 13 casts, shown in 5: the same messages, the same order, collision 110-128 ms
  after the spawn, removal (0x3) 300-306 ms after the collision; the diag (budget: casts 1-4) shows the client
  starting Vfx_OnCollision on both objects in shown and missing casts; the objects stood on the navmesh, casts 3 / 6 /
  7 / 12 at the same spot (13.55, 59.2, 250.2) with both results.
- **P:** the emitters need more than the 0.3 s the object lives on the client; how the original removed a destroyed
  object (DestroyEntity's client half posts the 0xFA state change after the delay, 0x9B56D0) is not known. The
  sandbox delays the network removal 1 s ([ics] destroy_network_linger) to test it.

## The explosion after the linger, the first knockback, the W indicator (2026-11-04, anim-29)

- **Explosion (C traffic, tester).** anim-28 kept the explosion object 0x40000CD8 on the client 1.3 s after its
  Vfx_OnCollision (removal 0x3 "1 s after", 03:13:53.121 ...): 0 of 14 showed. With the removal at 0.3 s (the
  script's) 5 of 13 had. So the type 0x11 emitter 0x18000BDB on the object is not seen while the object stays; what
  the client does at the removal (or what else differs in the shown casts) is for `diag --particles` (the emitter's
  start, 0x67F650) next to the removal times in traffic.log. The linger is off again.
- **First knockback of a match (C log).** 02:41:21.704 Heat Vision S3, damage .706, the server started Gaslight
  Batman's graph runtime (.705), the knockback status script 0x340003F8 entered .828 (0.12 s later; 3 ms in the
  later casts), its end .182 (0.35 s; later casts 0.32 s). The tester saw a teleport-like push only that time. The
  motion states were unlabelled (net.py logs label None as nothing); `[ics] log_forced_motion` labels them now.
- **The W indicator (C traffic).** Scarab Scanner S4 (launch) runs SetSkillStatOverride 0x100000FA [this, field 14 =
  5, field 16 = 1]; ics sent slot 2's table with targeting 0x1000003D = 5 (03:13:40.800), overlay 0x1000015A slot 2
  on, and the HUD redraw (.916); at the drone's end (46.933) the table cleared. The client still drew the indicator
  for the second press, so its targeting mode is not (only) the slot table's 0x1000003D. Open (pendência 16).

## The explosion's emitter, the first knockback, the first R (2026-11-04, anim-30)

- **The explosion's emitter starts but is not seen (C diag + C client rule).** `diag --particles` (action type 0x11,
  execute 0x67F650; the particle record is the action's word +0x34): 0x18000BDB started on the client at 15:21:56
  and 15:22:04 (Energy Cannon casts 1 and 2), neither seen by the tester; the tracer's 100-line budget ended the log
  at 15:22:04 (PARTICLES now has 3000). client-movement.md 0 (C): a network object is placed only by its movement
  states, and each physics tick replays the newest state whose time <= now - 0.1 s; a new object's only state (its
  creation bundle, stamped now) is not used for 0.1 s. The explosion object 0x40000CD8 got Vfx_OnCollision 5 ms
  (cast 1) or ~110 ms (the others) after its creation; the two shown (14, 15) got it 105 / 118 ms after. The emitter
  attached to an object not placed yet does not show where the tester looks. ics now stamps a standing spawned
  object's creation state 0.1 s earlier ([ics] spawn_state_backdate; 0.1 = the client's replay delay; with speed 0
  the dead-reckoning adds nothing). Krizalid's spawned_effect_scriptlets sends a missile's Vfx_OnInit 0.1 s after its
  creation, probably the same delay met another way.
- **The first status of a kind costs a pack read (C log).** apply_status resolves a status record's script with
  Data.status_script, whose _record builds the record list of the record's pack on first use (2.2 s cold for
  0x48000A0F in a fresh process), on the game thread. Heat Vision's knockback status 0x340003F8 started 0.13 s after
  the hit at the match's first E (15:25:48.684 -> .810), 3 ms in the later ones. ics/prewarm.py resolves, at each
  champion's creation, the statuses its kit's ApplySkill nodes name (and their scripts', two levels).
- **The knockback's length (C script).** 0x340003D6 S3: KnockbackDuration = max(KnockbackDistance - distance, 0.1)
  / KnockbackSpeed; status 0x340003F8: to KnockbackDistance (stat 17 = 6 m) from Superman. 15:25:48: 0.7 m in 0.07 s
  (the bot 5.3 m away, walking); 15:26:03: 3.15 m in 0.35 s. A short push is a quick hop by the data.
- **The first R (C traffic, open).** 15:22:48.036: the melee slot tables at .149-.173, the rank toggle .278, the same
  as the later swaps that showed at once; the melee icons 0x13001DE1 / DE6 / DFE / DFF live in pack 0xA0000202 with
  the ranged ones. The tester saw them 5-6 s later the first time only: client side, to see with diag --ranks (the
  HUD's refresh marks).
- **Skill script copies (context).** World.mirror_skill_scripts sends the champion's skill scripts to the client as
  0x200F (the original's probable way, skill-animations-and-skins.md 3.1); [ics] skill_script_mirror is off since
  2026-10-23 22:24 (the client closed at load complete: access violation at rva 0x48BE3).

## The first Q explosion (2026-11-05, anim-32)

- **C log.** Energy Cannon's missile script 0x34000489 S1 starts CollisionDelayTimer, then SpawnEntity(0x40000CD8);
  S1 -> S7 (Vfx_OnCollision) on the timer. At the match's first cast (16:12:51.015) the SpawnEntity read the class's
  data for the first time (69 ms on the game thread), so the creation went at .084 and the collision 1 ms later; later
  casts: creation at once, collision ~106 ms after. With anim-30's placement fix every cast but the first showed the
  explosion. ics/prewarm.py now reads, at each champion's creation, the classes its kit's scripts name and walks their
  scripts (0x40000815 -> 0x34000489 -> 0x40000CD8).
