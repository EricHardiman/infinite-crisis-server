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

## 14:02 findings: profile icons, the wagon's explosion, Launch delay (2026-10-16)

### Protector (avatar) icons

- Flash `gameplay.singleton.OwnablesManager.RecvNotice_ItemStatuses(items, statuses, types, owned, counts)` is fed
  by **0x20B8** (u8 0 | u32 n | n x (u32 DID | u32 status | u32 content type | u8 owned | u32 count)) and files
  every entry by content type (`emp_gen.ContentTypeList`: 1 Character, 2 StolenPower, **3 AvatarIcon**, 4 Skins,
  5 Amplifier, 6 Boost, 7 Currency, 8 Bundle, 9 Skill, 10 Texture, 11 Artifact, 12 Augments, 13 Mods,
  14 Entitlement, ... 25 LoginReward).
- The profile's icon picker (`ProtectorIconSubmenu`, sprite 21149 `OnItemStatusesChange`) lists
  `GetAllOwnableDatasOfType(3)` with `OWNABLE_UI_STATE_OWNED`, and takes each icon's picture and texts from
  `ProtectorIconManager.GetIconData(did)`, which matches `didIconWC` = the ownable DID. The manager fills itself
  with the Flash -> C++ query **0x1000047D** `RequestProtectorIcons` (arrays of WCs, DIDs, names, descriptions,
  unlock descriptions: static game data).
- The icons themselves: 134 records `0x49xxxxxx` in the UI pack 0xA00000D0 with `0x100008F8` (picture 0x13...),
  `0x10000B77` / `B78` / `B79` (name, description, unlock text; string table 0x2B0003BD, not in the cloud copy of
  the packs) and `0x10000AB9` (bool). Ownable DID = `0x40` + the same low 24 bits (e.g. 0x400005D4 -> 0x490005D4).
- Picking an icon: Flash notice **0x1000047E** `UI_SetProtectorIcon(icon, slot)` to the C++; the header shows it
  after **0x2154** (u8 0 | u32 icon | u32 slot). The network event in between is not identified yet (two-u32
  client events 0x207D / 0x2093 / 0x2098 are sent elsewhere: 0x2098 from a server-event handler at 0x8B88C1,
  0x2093 next to `URL.UpdateNews`, 0x207D next to the strings Start / End).
- Server (fase3-fn): `icserver/cosmetics.py` reads the list from the player's packs at start and every 0x20B8
  carries them as owned (`[account] unlock_avatar_icons`).

### The paddy wagon's explosion

- Graph 0x1A0001B8 (`env_gas_vehicle_paddy_wagon_behavior.hkb`, pack 0xA000024C): state machine `Paddy Wagon` with
  Idle01 / Idle02, each with an Idle and a Crash clip (`env_gas_deco_vehicle_a_cin_car_a/b_crash`, the intro
  cinematic's crash); events `State_to_State`, `IdleState01`, `IdleState02`; no variables. There is no explosion
  state: `env_gas_vehicle_paddy_wagon_exploding.hkx` is a character asset (the breakable model of entity
  0x2D000238), so the break-up is done by the destruction / physics side, not by an animation.
- Destructible explosion script **0x3400015F** (pack 0xA000024C) runs on the object: Vfx_OnThrown 0x1000087A,
  **Vfx_OnFire 0x1000013E**, Vfx_OnInit 0x10000078, Destructible_IgnoreAOI 0x10000A9D, Vfx_OnExplode 0x10000079,
  skill 0x48000294 + VFX_CBT_Hit_Shared on the target, with `DestructionMagnitude`, `DestructionRange`,
  `ExplosionRange`, `DestructionDelayDuration`. 0x3400072D carries `DestructionMagnitude` / `DestructionRadius`
  (the impulse). Neither is referenced by the wagons' world states 0x2E00034D / 0x2E00034E.
- The meteor dust cloud (0x2E0007D4) the server used as the car blast was the wrong animation (tester); it is off
  (`blast_wstate` = 0). The car keeps its own Vfx_OnExplode (sound) and the drones' hit effects.

### Launch -> loading delay

- After the encounter overview movie the client sends the preference `User.SawEncounterOverviewMovie@<encounter>`
  and, about 2 s later, JoinQueue 0x20EB (client side; 0x20C4, empty, goes out on the Launch click).
- The server then took about 3 s more to refer the client: each log line opened, appended to and closed
  `traffic.log` (about 150 ms per line on the tester's machine, even between the two lines of one message). The
  logs now go through one writer thread with the files kept open (`icserver/log.py`).

### Server start-up reading (2026-10-16 14:23)

Reading the prop world states' scriptlet tables (`tutorial1.resolve_script_tables`) decompresses packs
0xA000024C (114 MB), 0xA0000256 and 0xA0000257 in Python: about 80 s on the tester's machine. Run in a thread it
overlapped the match and starved the network threads (log lines 250-300 ms apart, late movement, client
disconnects). It now runs before the ports open and is cached in `data/game_cache.json` (`icserver/gamecache.py`,
keyed by every pack's name, size and date).

### HUD elements and the profile header (2026-10-16 14:41)

- `emp_gen.gmUIHUDElementIDList` (complete list in `catalog/data/hud_elements.tsv` for the ones used): 21
  SkillButtonStolenPowerTSkill, 24 ArtifactFoundryButton, 29 CurrentArtifactSlots, 43 SkillButtonRecall (the skills
  bar's `ShowElement` case for 43 sets `m_btnRecall._visible`). The skills bar also carries `m_mcBonusSkillContainer`
  (bonus skill) and `m_skillPointSpend_bg` / `m_wtSkillPoints` (the "available points" text).
- The home header class (sprite 21149) has `RecvNotice_SendHeaderNameAndProtectorIcons(name, iconDIDs, names, descs,
  unlockDescs)` -> `m_ccDisplay.SetData([CallingCardData])`, five sub-menu buttons `m_btSubMenuButton0..4` ->
  `ShowProtectorIconSubmenu` (lists the owned AvatarIcon ownables) -> `SetProtectorIcon(did, slot)` -> notice
  0x1000047E. The C++ side of 0x2190 (exec 0xA57200 -> 0xA56560 -> 0xA3F340) builds the name / description arrays
  itself from the DIDs.
- 2026-10-16 15:10: the icon picker's choice reaches the server as **0x2093** (8 bytes: u32 icon ownable DID |
  u32 slot), the "two u32" client event sent next to `URL.UpdateNews` in the exe. 0x2154 is the confirmation.
- Hiding a skills-bar element with 0x213D (event 2) hides the whole bar unless it is RecommendedText (45):
  `SkillsBar.HideElement` forwards to the base class. Hide upgrade buttons only (they are separate elements).

### Champions outside the roster (2026-10-16 15:31)

The install has nine more playable champions than `data/champions.json`: Zod (graph 0x1A001662, pack 0xA0000378),
Arcane Harley Quinn (0x1A0016AF, 0xA0000384), Arcane Zatanna (0x1A0012EB, 0xA0000303), Nightmare Catwoman
(0x1A0015E8, 0xA000036D), Deathstroke (0x1F00004D, 0xA000030E), Deadshot (0x1F000051, 0xA0000337), Dex-Starr
(0x1F000052, 0xA000033F), Raven (0x1A001408, 0xA0000332), Huntress (0x1A001596, 0xA0000362). Each champion has a
cluster of consecutive packs; e.g. Krypto: wallpaper 0xA00002F4 (13:1 48:1), light 0xA00002F5 (13:2 52:1 48:1),
skills 0xA00002F6 (13:8 48:4 2B:1, text table), parent 0xA00002F7 (behavior graph, 0x48 records), heavy
0xA00002F8. Zod's cluster is 0xA0000375-0xA0000379. Pack 0xA00002FF holds 453 0x40 / 0x49 pairs (a variant list
to check). The champion list itself is server data (0x20ED meta entries), not in the local packs.

### Champion pack clusters (2026-10-16 15:44)

Rules (icserver/roster.py), checked on Krypto (all fields equal to champions.json) and used for nine more:
- light pack = exactly {0x52 bank, 0x48 C, 0x13, 0x13}; C = the champion record (0x10000384 tex384, 0x10000799
  tex799, 0x10000433 / 0x434 name strings in table 0x2B000105).
- wallpaper pack = {0x48 C+1, 0x13}; C+1 = "pregame heavy" with 0x100005B0 = wallpaper.
- skills pack = a nearby pack with a 0x2B text table, no behavior graph and four 0x48: the skill set is the one
  closest to C (C+2; Dex-Starr C-2).
- parent pack = the nearby pack with the 0x52 bank and a text table (usually holding the behavior graph; Huntress
  keeps her graph in the heavy pack).
- heavy pack = a 0x40 V / 0x49 V pair whose 0x49 record names C (offset ~300: C+1, then C); when two pairs are
  there (X, X+1), the second one is the champion (X's record is short and names neither). Grid icon = 0x1000072E
  of the 0x49 record (heavy_dbpc).

## Texture records and champion pictures (companion app, 2026-10-16 16:00)

Texture records (`0x13......`) found in the packs are laid out as:

    u32 did | u32 2 | u32 type (1 = 2D; 5-8 also seen) | u32 flags | u32 3 | u32 width | u32 height
    | 4-byte format | u32 size | pixel data (largest mip first)

The format field holds `DXT1`, `DXT3`, `DXT5`, or the number `0x15` (A8R8G8B8, bytes B G R A). Every picture the
app uses decodes with this layout: wallpapers, portraits, skill icons, avatar icons and artifact icons.
`icserver/textures.py` decodes the first image to PNG.

Champion pictures:
- `0x10000799` on the champion record C (light pack) is a full-body splash for every champion checked.
- `0x100005B0` on the 0x48 C+1 record (wallpaper pack) is usually the same kind of picture. For Zod and
  Deathstroke it is their emblem, so the app shows 0x10000799 first.
- `0x1000072E` on the variant's 0x49 heavy record is the square grid portrait.

## Missing champions: duplicate costumes and unreleased clusters (2026-10-16 16:36)

**Robin, Arcane Supergirl, Star Sapphire.** All three were in `data/champions.json`, but each lists a costume
whose variant equals the champion's own variant:
- Robin: 0x400005B4;
- Arcane Supergirl: 0x40000AB2;
- Star Sapphire: 0x400005CF, listed twice.

The server sent that variant twice:
- in the item statuses 0x20B8, once as a champion (content type 1) and again as a costume (content type 4);
- in the champion meta list, a second entry with the costume's packs and no icon.

The client lost the champion. No other champion has such a costume. These costumes are now skipped
(`messages.costumes()`, `[account] skip_base_costumes`).

**Unreleased champions.** A light pack with two pictures, one 0x48 record and **no 0x52 sound bank** is usually a
costume. The pregame record (wallpaper 0x100005B0) sits at C-1 instead of C+1, which matches how costume records
in champions.json are laid out (pregame = light - 1). John Stewart has the same layout, but he also has his own
behavior graph (`chr_john_stewart_behavior`, 0x1A001778 in 0xA000039F), his own skill set (0x480013E4 in
0xA000039B and in the parent) and his own pictures. `roster.py` now accepts such a cluster when:
- the parent is the graph pack that holds the skill set;
- that pack is not a known champion's pack;
- the graph's name is a new champion name.

A costume fails these tests because its nearest graph belongs to its champion. The cache key became
`extra_champions_v2`, so the search runs again once.

All `chr_*_behavior` graphs of the install (catalog `animation_graphs.tsv`) were checked against the roster. The
graphs that are not champions are costumes, pets, minions, props and parts of other champions' kits (owl,
rabbit, pod, lantern, Billy Batson...). After John Stewart and Nightwing, none of them is a champion missing from
the roster.

## Client event 0x20C4 after a match (2026-10-16 16:58)

The client sends 0x20C4 (empty body) on Launch and again when the end page closes after a match. The server marks a
session when a match ends (`end_match`). The next 0x20C4 is then the end page closing, which is when the new
interface brings the launcher back (`Session.ev_launch_or_end_page`, `icserver/interface.py`).

**Correction (17:07):** six of the sound-bank-less clusters are costumes of other champions. Their variants
appear in champions.json's costume_info:

| Pack | Variant | Costume of |
|---|---|---|
| 0xA00002FD | 0x40000BEE | Sinestro |
| 0xA0000309 | 0x40000C09 | Arcane Green Lantern |
| 0xA000032D | 0x40000C4B | Solomon Grundy |
| 0xA0000367 | 0x40000CDB | Mecha Wonder Woman |
| 0xA0000373 | 0x40000D1C | Nightmare Batman |
| 0xA000037E | 0x40000D2E | Harley Quinn |

Each sits just before the next champion's cluster, so its nearest graph names that new champion. The variant test
is what separates them from John Stewart.

## The overview movie and JoinQueue (2026-10-16 17:16)

`User.SawEncounterOverviewMovie@<encounter>` (0x216E) arrives when the overview movie **starts**. Queuing the player
at that moment cuts the movie and leaves its audio playing over the loading screen (fase3-fs, rolled back in
fase3-fu).

The client then does one of two things:
1. It sends its own JoinQueue 0x20EB (17:10 run, 3 s later, after 0x20C4 on Launch).
2. It goes back to the Launch screen, which asks for its banners (0x212E; 17:15 run, 10 s later) and waits for
   another Launch.

In case 2, the server treats that 0x212E as the end of the movie and queues the player
(`Session.ev_ask_achievement_banners`).

## The meteor event's assets (2026-10-16 17:29)

**Pack 0xA000009A** (141 MB, a PvP map; the tutorial does not load it) holds the whole meteor event. Script table
0x1D00019C references:
- **Rock:** world states 0x2E0005F7 and 0x2E000BB3, .entity 0x2D00048D (`env_event_meteor_a_rig`: Root / Meteor /
  Meteor_cap). Graph 0x1A0002BF `env_event_meteor_a_behavior`, clips `env_event_meteor_a` and `_impact`.
- **Ground warning:** 0x2E0004E5 (.entity 0x2D000390, `vfx_env_event_meteor_warning`). Graph 0x1A000217, clip
  `drop`, rig Light / Warning.
- **Others:** 0x2E0004E7, 0x2E0004ED, 0x2E0006DA, 0x2E0006DE, and the dust cloud 0x2E0007D4.
- **Impact:** `vfx_env_event_meteor_impact`, graph 0x1A00021F, clip `explode`. Its rig has Fragment_A..M and
  Plume_Bottom / Mid / Top.
- **Dust ring:** graph 0x1A000365, clip `expand`.

**Other meteor assets:**

| Asset | Graph | Where |
|---|---|---|
| `env_event_meteor_fragment` (.entity 0x2D00044D) | 0x1A0002BA, idle clip | 0x2E00131C in 0xA000024C (loaded by the tutorial); 0x2E000CF5 in 0xA0000179 (placement 0x1D0003BB); 0x2E0005B3 in 0xA0000164 |
| `stp_meteor_rock` (Meteor Drop stolen power: spawn / spin) | 0x1A00050E | 0xA00000B3 |
| `vfx_env_event_meteor_shockwave` | 0x1A00024A | 0xA00000B3 |

The graphs are not referenced by DID from the world states: a bare world state shows only the rig, without its
animation. Since fase3-ga the start meteors are entities that the server moves down from 18 m.

## Pack slots and the second zone slot (2026-10-16 19:20)

The client loads `.rp` packs into fixed **slots**, one set per pack category (the `u32` after `RP01` in the pack
header: 0xd = zone packs such as 0xA000024C and 0xA000009A, 7 = heavy champion packs such as 0xA0000076).

- **Slot table** at VA `0x1600a40` (file offset `0x11FEE40`): 26 entries of 0x14 bytes,
  `{u32 count, u32 category, u32 size A (KB), u32 size B (KB), u32 flags}`; flag 0x40000 = skipped.
  Category 0xd: **1 slot of 158 720 KB** (155 MB). Others: category 7 and 8 have 10 slots, 6 has 16.
- **Builder** VA `0x9d3ff0(table, n)` (only caller VA `0xa08780`: `push 0x1a; push 0x1600a40; add ecx,0x2039c`):
  sums the counts into `[mgr+0xc]`, allocates count × 0x28 slot records (category at +0x14, loaded pack id at
  +0x1c, -1 = free) and VirtualAllocs (MEM_COMMIT | MEM_RESERVE) each slot's size rounded to 64 KB.
- **Loader** VA `0x9dd120(pack id)`: returns the slot if the pack is already loaded, else reads the pack header
  (VA `0x9da330`), finds a free slot of its category (VA `0x9d3400`, which scans every slot) and loads it there
  (VA `0x9db3b0`). With one zone slot taken by 0xA000024C, 0xA000009A never loaded (the load hung).
- **Patch** (fase3-gh): category 0xd's count 1 → 2 (file offset `0x11FEF44`). The free-slot finder already handles
  several slots per category. Cost: 155 MB more committed memory (the exe is large-address aware).
- The server adds `[match] event_packs` (0xA000009A) to the match's pack list (0x20AF) only if the patched exe has
  2 zone slots (`patcher.zone_slots`).

**The meteor event template 0x1D00019C** (pack 0xA000009A), as far as read:
- Properties: `0x7EB` = 1, `0x19B` = 0x15, `0x24E` = 1, `0x4B9` = (−3, −3, −3) and `0x666` = (3, 3, 5) (a bounding
  box), `0x50F` = 3, and `0x78` = the scriptlet map with one key, **`0x1000092F`**.
- The key's tracks: actions of type `0xc` create a world state at an offset (8 × `0x2E0006DA` at 8–20 m around the
  spot, the warning `0x2E0004E5`, `0x2E0004E7`, `0x2E0004ED`, `0x2E0006DE`, the dust `0x2E0007D4`, the rock
  `0x2E0005F7` and later `0x2E000BB3`); actions of type `0x2C` play sounds (`0xB3A8D439`, `0xEB685A04`, `0xB18A7F0B`,
  `0xD48DB5C6`, `0x0934A9BA`, `0xA4B1A226`). Keys `0x1000087B` / `0x1000087C` / `0x1000087F` / `0x10000926` /
  `0x10000927` inside are probably signals and timings.
- No world state in the staged packs names 0x1D00019C (the two matches found were inside texture data). The server
  therefore puts it on an anchor prop (generic effect world state `0x2E000013`) as property `0x7D2` and runs
  `0x1000092F` with event 0x8D (`tutorial1._meteor_event`). Untested in the game yet.
- **20:08 test (diag --packs --scripts):** the slot list shows `category 0xd: 2 slots` and both 0xA000009A and
  0xA000024C load (no hang). On the anchor, `0x1000092F` is rejected (0x80070057): its scriptlet table has 1 group
  (the template) that allows only `0x5`. So `0x1000092F` is not an allowed key; `0x5` is tried next (fase3-gi).
  World state `0x2E000013` (.entity 0x2D000063) shows as a **water jet**, not an invisible effect.
- **20:33 test:** `0x5` is accepted (result 0) but nothing changes on screen; the jets were still there with the
  warning `0x2E0004E5` as the anchor.
- **The template is an HFSM.** Read further, 0x1D00019C has states and transitions: signals `0x1000087B` / `7C` /
  `7F` / `0x10000926` / `927`, waits (`6 | f32 seconds`), damage areas (property `0x10000437` … with skills
  `0x480007FD` / `0x480007FC`, radius 13 / 23 m), particle actions (type 17: `0x1800024B`, `0x18000E6A`,
  `0x180002D1`), a camera shake (type 11), sounds (type `0x2C`) and creates (type `0xc`: world state, a few
  floats, offset x y z, heading, then the key started on the new object):
  - 8 × `0x2E0006DA` at (0, 15), (8, 8), (15, 15), (−8, 15), (−8, 8), (5, 8), (0, 20), (15, 15), key `0x10000078`.
    `0x2E0006DA`'s own record: `0x7D2` = `0x1D0001BC`, `0x50F` = 3, `0x7EB` = 1 (not 0x1D00019C).
  - warning `0x2E0004E5`: own `0x7D2` = `0x1D000114`, graph `0x5B5` = `0x1C000028`.
  - `0x2E0004E7` (with `0x10000039`), `0x2E0004ED` / `0x2E0006DE` / dust `0x2E0007D4`: key `0x1000018E`.
  - rock `0x2E0005F7` and later `0x2E000BB3`: key `0x10000032`.
- **20:58 test (diag + picture):** the ring piece `0x2E0006DA` accepts `0x10000078` and `0x5`; the warning `0x2E0004E5`
  accepts `0x1000018E` and `0x5`; the rocks `0x2E0005F7` / `0x2E000BB3` have **no** scriptlet table (0 groups), so
  `0x10000032` is rejected and they never animate. The rock model (.entity 0x2D00048D) is the **glowing lava rock**:
  at scale 1 it is about twice Batman's height.
- fase3-gj: the server places those pieces itself, with their own templates, one variant per small meteor
  (`tutorial1.METEOR_EVENT_PROBES`).

## Sounds (Wwise) (2026-10-16 17:47)

- **`audio\Audio_SB.pck`** is an AKPK package with 41 sound banks (BKHD v112 / DIDX / DATA / HIRC / STID) and
  1687 events (HIRC object type 4). The language folders (`English(US)` ...) hold the voice banks. `*_Str.pck`
  holds the streamed files.
- **Pack records `0x52`** declare a bank: `u32 did | u32 bank id | u32 n | name`. The bank id is Wwise's FNV-1 32
  hash of the lower-case name (`Destruction` = 0x91D0BEA7).
  - Tutorial 1's pack 0xA0000256 declares Destruction, Turrets, Announcer_General, Music_Divided,
    AMB_GothamHeights, AMB_Tutorial and VO_Tutorial_Hero.
  - Pack 0xA000024C declares **mse_Meteor** (0xCFD61E2D, 10 events) and mse_MeteorStorm.
- **A record plays a sound** through a typed value of kind **0x2C**: `u32 0x2C | u32 event id`. The event names
  are not in the data (only their hashes). `python ic.py sounds` writes `catalog/data/sounds.tsv` (event, bank,
  the records that play it) and `sound_banks.tsv`.
- **Meteor sounds** (bank mse_Meteor):
  - Script table 0x1D00019C (the meteor event of pack 0xA000009A) plays 0x0934A9BA, 0xA4B1A226, 0xB3A8D439,
    0xD48DB5C6 and 0xEB685A04, plus 0xB18A7F0B from Destruction.
  - Record **0x170001C4** (pack 0xA000024C) plays 0x0934A9BA, 0xA4B1A226 and 0xD48DB5C6, and also names the rock
    0x2E000BB3 and the dust cloud 0x2E0007D4. It is the meteor's effect.
  - 0x170001C4 is attached to 0x2E0002EC, a type-2 record over 0x2E000013 with property 0x1EB = 0x170001C4. That
    makes 0x2E0002EC the likely complete falling meteor: rock, dust and sound.

## Server obstacles: boxes are grown, polygons are not (2026-10-16 21:34)

`world.Mover` obstacles are either a box `(cx, cy, half_length, half_width, yaw)`, grown by Batman's radius
(`Mover.radius` = 0.6 m), or a polygon `[[x, y], ...]` taken as the line his centre can not cross. A small prop
(the meteors) must be a polygon, or he stops 0.6 m further out than intended.

## Carrier props ignore position updates (2026-10-16 22:11)

A prop built on a carrier class (0x4A…) is placed where it is created; later object bundles with a new position
and speed 0 do not move it on the client (the meteor falls and pushes were all sent, and the rocks stayed put). A
speed > 0 makes the client extrapolate (the fase3-gd rocks that slid on). To move such a prop, remove it (0x3) and
create it again at the new spot.

## Meteor event pieces and the rocks' lost scriptlet table (2026-10-16 22:47)

- **The rocks have a scriptlet table after all.** 0x2E000BB3 carries 0x7D2 = 0x1D0003B5 (packs 0xA000024C and
  0xA000009A) and 0x2E0005F7 carries 0x1D000167. `gamedata.world_state` read the entries with a u32-only value
  reader and gave up at the first vector property (0x24E / 0x667 / 0x4B9 are three floats), returning None, so the
  carrier-built rocks never got a table ("0 groups" in diag). `world_state(..., partial=True)` now returns what it
  read before that point; 0x7D2 comes first in these records.
- **What template 0x1D00019C creates** (create action 0xc: world state, then lifetime and scale floats, then the
  start key a few words later):
  - big-impact branch: 0x2E0004E7 for 20 s with key 0x10000039, 0x2E0004ED for 5 s and 0x2E0006DE for 1 s with
    0x1000018E, the dust 0x2E0007D4 for 5 s with 0x1000018E;
  - small-impact branch: dust (scale 0.25), 0x2E0004ED, 0x2E0006DE (scale 0.25);
  - rocks 0x2E0005F7 / 0x2E000BB3 for 5 s with 0x10000032 (Vfx_Spawn); warning 0x2E0004E5; 8 x 0x2E0006DA with
    0x10000078; particles (action 0x11) 0x1800024B / 0x18000E6A / 0x180002D1.
- **Entities:** 0x2E0004E7 -> .entity 0x2D000392 (one-bone "autobone" mesh with an hkpMoppCode collision shape,
  like the old crater 0x2D000375) and template 0x1D000115 (graph 0x1C000029, effects 0x170006DE / 0x170006F0): taken
  as the event's crater. 0x2E0004ED / 0x2E0006DE -> .entity 0x2D000397 = `vfx_env_event_meteor_shockwave_rig`
  (pack 0xA00000B3), templates 0x1D000124 / 0x1D0001BD.
- The impact rig `vfx_env_event_meteor_impact` (bones Plume_Bottom / Mid / Top, Fragment_A…M; graph 0x1A00021F,
  animation "explode") is record 0x100004CE of pack 0xA000009A. Nothing in any pack names 0x100004CE or 0x1A00021F
  by id, so the object that plays it (the fire column and smoke plume of the tester's frames) is still unknown.
- World state 0x2E00069E (.entity 0x2D00050C) is the object whose own 0x7D2 is 0x1D00019C: the meteor event
  object itself. Not spawned yet; a candidate if the pieces above do not give the fire column.
- Record 0x1500EEB6 (pack 0xA000009A) is a compiled copy of the same create actions (with a shader blob).

### Correction (2026-10-16 23:30, fase3-gs test)

- 0x2E0004E7 is the meteor event's **explosion** (fire and smoke), not its crater: placed as the crater it showed
  an explosion that never ended (the event gives it a 20 s lifetime; the server must remove it) and no crater. Its
  table rejected 0x10000039 (0x80070057). The crater stays 0x2E0004BE.
- The rocks now get table 0x1D0003B5 ("1 groups" in diag) and accept Vfx_Spawn 0x10000032, which shows nothing
  visible.
- Pushed rocks re-created with a speed (fase3-gs "glide") still read as vanishing and reappearing; every
  remove + create flickers. A carrier prop takes position updates while they carry a speed > 0 (only speed-0
  updates are ignored), so a push is now sent as moving updates and a final crawl of 0.01 m/s.
- Graph event RunScript_FX_Spawn 0x1000006B on Batman: the tester saw "a rope going up" from Batman now and then:
  probably Gaslight Batman's grapple spawn (unconfirmed).

## Model tour candidates (2026-10-16 23:46)

The tester judged the rocks (0x2E000BB3), the explosion (0x2E0004E7) and the crater (0x2E0004BE) to be the wrong
models: the original's crater already has its lava, and each meteor is a column of fire then a column of smoke.
Tutorial 1's map layout (pack 0xA0000256 placements) has no meteor, crater or fire object, so the original server
spawned them. `[debug] model_tour` shows candidates one at a time (`tutorial1.MODEL_TOUR_CANDIDATES`): every world
state of pack 0xA000024C named by a script, effect or spawn template of that pack (38, from a reference scan), the
craters and lava sets tried before, and the meteor event's pieces of 0xA000009A. Templates read for them (0x7D2):
0x2E00131C -> 0x1D0008EA (233 KB), 0x2E000F03 / F04 / F05 / EFE -> 0x1D000611 / 612 / 615 / 60D + 0x1D00034B +
0x1D000111, 0x2E00061D…623 -> 0x1D000168, 0x2E0004BE -> 0x1D000155, 0x2E001144 -> 0x1D000768, 0x2E0005D6 ->
0x1D000162, 0x2E000800 -> 0x1D000219, 0x2E000821 -> 0x1D00022E, 0x2E000296 -> 0x1D0000DE, 0x2E00070F -> 0x1D0001CA.

Graph event RunScript_FX_Spawn 0x1000006B on Batman plays a rope (grapple) going up: not part of the tutorial.
- 2026-10-17 00:12: the client closed 0.13 s after the tour created 0x2E000F04 on a carrier (model 15; the tester
  read "13" on screen, the objective text lags). Its siblings 0x2E000F03 / F05 / EFE share templates 0x1D00034B +
  0x1D000111 and spawn templates naming entities 0x400002A4 / 0x4000083E and skill 0x48000E19: probably
  character-like objects that need more than a carrier.
- 2026-10-17 00:44: models 14-27 of the tour closed the client about 3 s after being created (not
  deterministic: 0x2E000620-623 passed once, 0x2E00061D / 61F / 621 / 622 with the same template 0x1D000168 closed
  it in other runs). All their records are in loaded packs; the scripts of their templates running on a carrier are
  the likely cause. The tour now sends bare models.
- 2026-10-17 00:58: the tour crashes line up with the guide's variant C (Vfx_GuideArrow_Ping on ping 1 + GuideArrow on
  Batman aimed at it), ~0.5 s before the client closed, with a tour model standing at the marker. The bare run
  closed the same way, so the models' scripts were not the cause. Probable: the arrows' path query hitting the
  model's collision shape on a carrier object.
- Batman's SpawnIdle / FX_Spawn / Vfx_Bmg_Spawn at the tutorial start show his grapple rope.
- 2026-10-17 01:08: correction: with the guide off the client still closed 3.2 s after the bare 0x2E000F03 appeared,
  with nothing sent in between. Those models close the client on their own (not always: delayed resource loading
  is the likely trigger). They are skipped by the tour.

## Map packs per encounter (2026-10-17 08:02)

Every map the tester tried (Coast City v AI, Gotham Divided, Gotham Heights, Coast City, Crisis Labs, Metropolis
Skyway, Tutorial 2) hung at 15-25 %: the server sent Tutorial 1's packs (0xA0000076, 0xA000024C, 0xA00000CC and the
event pack 0xA000009A) for every encounter, so both zone slots were taken and the map's zone pack could not load.

The install has five zone packs (category 0xd; pack header u32 at +4), told apart by the names inside:

| Zone pack | Map | Mission pack (category 0xf) | Landblock | Start used |
|---|---|---|---|---|
| 0xA000024C | Tutorial 1 (Gaslight) | 0xA0000256 | 0x13CB | (18.7, 60.4, 200.3) |
| 0xA00002E5 | Tutorial 2 (tut_adv_* pieces) | 0xA00002E6 | 0x13C3 / 0x13BB | (25.32, 75.39, 200.23), cinematic 0x3500002C |
| 0xA00000D2 | Coast City (env_coastcity) | 0xA0000162 | 0x23E3 | (20.19, 57.44, 250.2), Player01 of 0x35000013 |
| 0xA000009A | a Gotham map (env_gotham), meteor event | 0xA0000168? (Gotham Divided) | 0x1BD3 | (19.61, 137.09, 250.22) |
| 0xA00000FC | no names | 0xA000016B? | 0x1BF3 | (18.39, 50.08, 252.5) |

- Encounter descriptions (0x49xxxxxx, pack 0xA00000B3) name records of their mission pack: Tutorial 1 0x40000B69 /
  0x40000CB7 (0xA0000256), Tutorial 2 0x40000CBC (0xA00002E6), Coast City 0x40000534 (0xA0000162), Gotham Divided
  0x40000554 (0xA0000168). The zone pack itself is not named; it was matched by content. The Gotham Divided /
  0xA000009A and 0xA00000FC pairings are guesses until the client loads them.
- Tutorial 2's layout places Crater1 / Crater3 (0x2E0004BE) and TurretBasePlate 0x2E000A9F, and its packs carry the
  meteor rock graph 0x1A0002BF: it probably has meteors of its own.
- `[match] maps` gives each encounter its packs, start and intro cinematics (none by default); the champion
  bundle's landblock comes from that start.


## World-state inventory of the whole install (2026-10-17 09:30)

`python ic.py worlds` (tools/world_scan.py) reads the 616 packs once (about 8 minutes) and writes
`catalog/data/world_states.tsv`: 2064 world states (0x2E). Record starts come from the record headers
("did | 7 | .entity | 0" for world states, "did | 0" for the rest); references are aligned u32 values that are record
IDs of some pack, followed two levels deep (world state -> entity / templates -> their records). Model names are
the rig bone and .hkx / .hkb names (`vfx_..._rig_Root` -> `vfx_...`); shader parameter names are ignored (they
matched "fog"). `needs_packs` is every pack holding one of those records: a wide list, because shared textures count.

Meteor family, as the data names it:

| World state | Model | Packs | Notes |
|---|---|---|---|
| 0x2E0004E5 | vfx_env_event_meteor_warning (graph 0x1A000217) | 9A | ground warning |
| 0x2E0004E7 | own autobone mesh (0x17000530, 0x17001FF0, 0x190003C3), graph set 0x1C000029, template 0x1D000115 | 9A | the "explosion"; 0x1C000029 is also in the event object 0x2E00069E's graph set, next to the impact graph |
| (no world state) | vfx_env_event_meteor_impact, graph 0x1A00021F (explode.hkx, bones Plume / Fragment) | 9A only | the fire column and falling rock; reached only through a graph set, not by a direct reference |
| 0x2E0004ED, 0x2E0006DE | vfx_env_event_meteor_shockwave (graph 0x1A00024A in B3) | 9A / B3 | |
| 0x2E0007D4 | vfx_env_event_meteor_dust_cloud (+ dust_ring, graph 0x1A000365) | 9A 162 168 24C 256 2E5 | |
| 0x2E0005F7, 0x2E000BB3 | env_event_meteor_a (graph 0x1A0002BF, states impact / ...) | 9A 24C 2E5 2E6 | the rocks |
| 0x2E0005B3, 0x2E000CF5, 0x2E00131C | env_event_meteor_fragment (graph 0x1A0002BA) | 164 / 179 / 24C | fragments |
| 0x2E0010E4 | vfx_env_pvp_lev_meteor (bones Meteor, Meteor_cap; graph 0x1A0010F1) | 168 | the PvP map's meteor |
| 0x2E000928 | stp_meteor (rock_behavior, spawn, spin, rock_project; graph 0x1A000790) | B3 | the Stolen Power "meteor" (`stp_` = Stolen Power; pack B3 holds the Stolen Powers) |
| 0x2E0004BE | no rig names; template 0x1D000155, graph 0x1A0000AA, 14 particles 0x18000423-0x18000435, 0x18001000 | 9A 24C 2E5 | placed as Crater1 / Crater3 |

Other effects found by name: vfx_chr_ntw_bike_exploding 0x2E001386 (pack 39A), vfx_chr_mec_ww_afterburn_aoe
0x2E000C60 (157, fire), env_pvp_drop_pod_a 0x2E000E38 / emitter 0x2E000FAB, env_pvp_phase_pod 0x2E001157 (256, 2E5),
env_gas_tut_adv_wall_explode graph 0x1A001376 (2E5), env_gas_vehicle_paddy_wagon_exploding graph 0x1A0001B8 (24C).
No record anywhere is named lava, magma, smoke or crater: the lava crater and the smoke column must be particles
(0x18) or parts of the impact rig, not separate world states.

## Graph sets after vector properties; the Tutorial 2 lab (2026-10-17 09:45)

- A world state's graph (0x5B5) can come after a vector property (0x24E / 0x667 / 0x4B9) that gamedata cannot size,
  so `world_state(partial=True)` misses it. The explosion 0x2E0004E7 has `0x5B5 | 0x5B5 | 0x1C000029` at word 44
  of its record; it was always sent without it, which may be why it never played its animation and never ended.
  `resolve_script_tables` now reads the raw triplet for tour / lab models and 0x2E0004E7 (cache key v5).
- Tutorial 2 (0x40000A81) loads zone 0xA00002E5 plus the meteor event's 0xA000009A in the second zone slot
  (`[match] maps` "event_packs"); 0xA000024C cannot be added (two zone slots only), so the fragment 0x2E00131C is
  not in the lab. `"lab": true` makes `Match.lab` a Tutorial object that only runs `lab_start()` (objective list,
  then `tutorial1.LAB_CANDIDATES` one by one next to the start point, bare and with scripts). It is not
  `Match.tutorial`, so no Tutorial 1 guide, movement or combat code runs in that map.
- Prop positions now use the map's landblock (spawn[1], spawn[2]) instead of the fixed 0x13CB.

## Template keys and their particles (2026-10-17 10:05)

- The explosion 0x2E0004E7 with its graph set 0x1C000029 shows the yellow dust / smoke cloud of the big impact
  (tester's screenshot 09:59): the graph set is what makes these pieces play.
- A template record (0x1D) starts "did | 0x7EB | 0x7EB | n" and holds runs "scriptlet key | 0 | n actions |
  prop | prop ..."; action properties 0x211 / 0x7E6 carry a sound (kind 0x2C) and the particle effect (0x18) with
  an attach key. Crater template 0x1D000155: keys 0x100003A9 (particles 0x1800042D, 0x18000435, 0x1800042C,
  0x1800042B), 0x10000440 (0x18000429, 0x1800042F), 0x10000442 (0x18000428, 0x18000430), 0x10000443 (0x18000423),
  0x1000043D (0x1800042A, 0x18000433), 0x10000332 (0x18000431), 0x10000335 (0x18000432), 0x100003A8, 0x10000333.
  Explosion 0x1D000115: 0x10000526-0x10000532, 0x1000051E (0x1800045D), 0x10000332 / 0x1000051D / 0x10000333 /
  0x100003A9 (0x1800044C). Shockwave 0x1D000124: 0x10000332 / 0x10000333 / 0x1000051D (0x18000465), 0x10000209
  (0x18000297), 0x1000053B (0x1800045D).
- World states whose 0x5B5 sits after a vector property: rocks 0x2E0005F7 / 0x2E000BB3 (0x1C000036), shockwaves
  0x2E0004ED / 0x2E0006DE (0x1C00002A), warning 0x2E0004E5 (0x1C000028), dust 0x2E0007D4 (0x1C000046), stp_meteor
  0x2E000928 (0x1C000053), TurretBasePlate 0x2E000A9F (0x1C000069). The crater 0x2E0004BE and the event object
  0x2E00069E have none.

## Tester's picks from the lab (2026-10-17 10:37)

| Piece | World state | How |
|---|---|---|
| Big meteor explosion | 0x2E0004E7 | carrier + template 0x1D000115 + graph set 0x1C000029, key 0x10000526 (particle 0x1800045D) |
| Crater | 0x2E0004BE | carrier + template 0x1D000155, key 0x100003A9 (particles 0x1800042D / 35 / 2C / 2B), yaw -5 degrees |
| Shockwave | 0x2E0004ED / 0x2E0006DE | as before (key 0x1000018E) |
| Sparks | 0x2E0006DA | carrier + template 0x1D0001BC, keys 0x1000018E 0x10000032 0x10000078 |
| Destroyer's crater ring | 0x2E001157 (env_pvp_phase_pod) | carrier, bare |

Not found among the meteor pieces: lava, fire column, smoke column. The drop pod (0x2E000E38, entity 0x2D000BCF,
templates 0x1D000620 + 0x1D000385, graph set 0x1C0000AA; rig 0x2D000D3F has bodies A-E and graph 0x1A000B60 has
"explode_a") and the PowerCore 0x2E000AC5 (templates 0x1D000360 + 0x1D000385, graph 0x1C00006C) share template
0x1D000385; neither template has keys in the "key | 0 | n | prop | prop" form, so their opening is probably a graph
event. The Stolen Power Meteor Drop (0x480005A2, script 0x340001D3) drops stp_meteor 0x2E000928 (pack B3).

- 2026-10-17 10:53: the tester recognised the tutorial's falling meteors in stp_meteor 0x2E000928 (the Stolen Power
  Meteor Drop's rock, pack 0xA00000B3, always loaded) created with only its graph 0x1C000053 (no templates): the
  graph plays the fall by itself.

## The Destroyer's cinematic 0x35000028 (2026-10-17 11:20)

Record layout (pack 0xA0000256): `did | 1 | camera key 0x10000012 | n camera keyframes | (frame | cell 0xFB | lb x |
lb y | x y z | quaternion | flag | 3 floats)...`, then `1 | 0 | fov 45.0 | n actors`, each actor `name length | name |
world state | 0 0 0 | n props | (key key value)... | n positions | (flag | cell | lb | xyz | quaternion)... | n keys |
(frame | scriptlet key | 5 x 0)...`; after the actors `n | 0x10000012 | n camera events | (frame | 0x10000060)...`
and an object script 0x34000595 with the attach points 0x10000039 / 40 / 47 / 4B.

| Actor | World state | Keys |
|---|---|---|
| Destroyer | 0x2E000AB5 (templates 0x1D000774 + 0x1D000385, scale 0.85) | 115: 0x100003A6, 125: Cinematic_Startup 0x100007EB |
| Melee1 / Melee2 | 0x2E001167 | 1: Cinematic_Hidden 0x100009EB, 125: Cinematic_Intro 0x100009EC |
| Ranged1 / Ranged2 | 0x2E001168 | 1: 0x100009EB, 125: 0x100009EC |

The PowerCore 0x2E000AC5 and the drop pod 0x2E000E38 share template 0x1D000385 with this actor: the closed sphere
is probably the Destroyer's own State00 look, opened by the keys above.

- 11:36 (tester): with the server's Destroyer spawned before 0x35000028 the cinematic showed two Destroyers: a
  cinematic creates its own actors from its record (they are not matched to server entities by world state).

## The original Tutorial 1 on video (2026-10-17 11:55)

A walkthrough video of the original game (tester's file, not in the repo). Times are video times; Batman can
move at 3:34.

| Time | What happens |
|---|---|
| 3:34.0 | Batman controllable, first marker and the "Right-click on the marked location" objective |
| 3:36.5 | He starts walking |
| 3:36.8 | Two meteors come in as long diagonal columns of fire from the sky, right next to him |
| 3:37.1-3:37.4 | Impact: white smoke burst and a transparent dome (shockwave) |
| 3:37.5-3:38.5 | Thick grey smoke cloud over the street (~1 s) |
| 3:39.0 | The big meteor: a large yellow explosion a few metres away (as 0x2E0004E7 with key 0x10000526) |
| 3:39.5-3:41.0 | A dust ring expands from the impact; Batman is knocked down |
| 3:41-3:43 | The crater: rubble and a bright red lava pool; the small meteors lie as rocks glowing red; Batman stands up at 3:43.5 |
| 9:33.5 | Destroyer cinematic starts (after the Super Strength drones) |
| 9:34.5 | A dark sphere with purple lights falls onto the plaza (inside the cinematic) |
| 9:35.0-9:36.5 | It lands with a dust ring |
| 9:38.5-9:39.5 | The sphere opens in two halves: the Destroyer and four drones inside |
| 9:39.5-9:50.5 | The drones walk out; the open lower shell stays as a ring around the Destroyer |
| 9:51 | Gameplay again ("Use what you've learned to reach the Destroyer") |

So the falling sphere is part of cinematic 0x35000028 (the server's own PowerCore drop is not in the original),
and the ring around the Destroyer is the sphere's open shell.

- 2026-10-17 12:30 (diag --scripts --create): cinematic 0x35000028 builds its actors on the client (0x2E001168 x2,
  0x2E001167 x2, 0x2E000AB5) and nothing else: no sphere object. The PowerCore 0x2E000AC5 (templates 0x1D000360 +
  0x1D000385) allows 0x1000002C 0x1000005C 0x10000079 0x1000008E 0x100000EA 0x100000EB 0x100000F5 0x1000013D
  0x1000014A 0x1000029D 0x100002E0 0x100003A6 0x100003A7 0x100008C4 0x10000A50 0x10000AED-AEF.

- 13:21 (diag): the PowerCore accepts 0x100003A6 and 0x100003A7 (result 0). Re-sending its create with a new z does
  not move a carrier prop (only one "PROP received"): it stayed 15 m up.

## The Destroyer's sphere is the phase pod (2026-10-17 13:30)

The PowerCore 0x2E000AC5 is another model (tester 13:28). The phase pod 0x2E001157 has the right parts and graph
0x1A000E0B: clips env_pvp_phase_pod_entrance_a, raider_open_a, raider_open_a_idle, active_idle_a,
attackable_idle_a(_gethit), leviathan_begin_a / thump_a / inactive_idle_a, die_a, phasepod_destruction_a; events
state_to_state, Deactivate 0x10000419, Activate 0x100001C1, Death 0x100001C0, Spawn 0x10000154, OpenIdle 0x100004A5,
ClosedIdle 0x100004A6, RunScript_Vfx_Event1. Name table 0x300000A4 (pack 0xA0000038) stores `id | length | name`.

- 13:56 (diag): the phase pod 0x2E001157 with template 0x1D00078F allows only Vfx_Spawn 0x10000032; graph set
  0x1C0000B5 as its 0x5B5 does not close the client.

- 14:05 (tester + packs): the phase pod 0x2E001157 record (pack 0xA0000256 offset ~6775128): `0x50F = 5`,
  `0x7D2 = [0x1D00078F]`, `0x7EB = 7`, `0x2A4 = 0x8B`; no 0x5B5. World-state properties are written
  `key | key | kind | value`; searching `B5 05 00 00 B5 05 00 00 <1C id>` gives each graph set's owner:
  0x1C000022 -> 0x2E00033A, 0x1C000046 -> 0x2E0007D4, 0x1C00006C -> 0x2E000AC5, 0x1C0000B5 -> 0x2E000FC7,
  0x1C0000BA -> 0x2E00103B, 0x1C0000CA -> 0x2E001037. With 0x1C0000B5 + templates the pod was not drawn.
  The pod's graph 0x1A000E0B sits in an id list `count | 1A ids` (0x1A000DE0, DE5, DE4, DE1, DE2, 0x1A001231,
  0x1A000E0C, 0x1A000E0B) whose owner is not identified yet.

- 14:28 (packs): cinematic actor records hold their templates in property 0x954 (array of 0x462 DIDs, like 0x7D2):
  PowerCore actor of 0x35000025 -> 0x1D00078A, Gate -> 0x1D000789 (pack 0xA0000256, ~offset 9265976). Template
  bodies in that pack contain "spawn world state" entries `0xC | 0x2E001157 | 1 | ... | scale 1.1 x3` keyed by
  scriptlets: one on 0x10000E5D / 0x10000E5E (CinematicCharacter_State02 / 03) next to spawns of 0x2E0007D4 and
  0x2E0004ED (~offset 7130252), one on 0x100000EB with 0x10000347 and OpenIdle 0x100004A5 (~offset 5977376). So the
  phase pod is spawned as an effect by another object's template; which template body is 0x1D00078A is not
  confirmed (template bodies do not start with their id). Tested in fase3-ho.

- 14:44 (diag): PowerCore 0x2E000AC5 with 0x7D2 = [0x1D00078A] allows 0x1000005A, CinematicCharacter_State00
  0x10000E5B, State01 0x10000E5C, State04 0x10000E5F; State02 / State03 rejected. Tester: it is the ending
  cinematic's piece, not the Destroyer's sphere.

- 15:02 (tester, Tutorial 1 tour of pack 0xA0000256): the Destroyer's sphere is world state 0x2E000FC7 (closed;
  `0x7D2 = [0x1D0006AC]`, `0x4FD = 0x400004FD`, `0x7EB = 0x14`, `0x962 = 4`, `0x2A4 = 0x4000054F`, `0x75 = 1`,
  `0x50F = 3`, `0x5B5 = 0x1C0000B5`) and 0x2E00101D (open; template 0x1D000385). The tour numbers models in the
  sorted order of the pack's 0x2E ids (37 and 38 of 51).

- 15:13: the drop pod graph 0x1A000CDC (env_pvp_drop_pod_a_behavior.hkb) names the events Spawn 0x10000154,
  Entrance 0x1000042A, Idle 0x1000013D, Explode 0x1000041F, Spawn_Idle 0x100002A1, Active_Idle, CbtState_Death_Induce
  and the clips entrance_a / idle_a / explode_a; the closed sphere 0x2E000FC7's record sits next to drop pod
  animation data (pack 0xA0000168 offset ~4120). On-screen turns: a positive yaw turns a prop anticlockwise.

- 15:26 (tester's video): a carrier prop given a speed keeps moving along its heading (yaw) at that speed between
  updates; with the thrown car's yaw kept and a final speed-0 update (ignored by carriers) the car flew straight on
  along its own facing. Moves of a carrier: heading = direction of travel, end with a crawl (0.01 m/s).
- Scriptlet names (name table 0x33000000, pack 0xA0000038): 0x1000005D Vfx_Active_State0, 0x1000006A Vfx_Fade_Out,
  0x100000DC Vfx_Event10, 0x100001E0 _HFSM_DestroyEntityAction, 0x1000087D Vfx_SpawnIdle, 0x1000087E Vfx_Spawn_Hit,
  0x10000CCD Object_Deactivate, 0x10000CCE Object_Activate.

- 15:44 (tester's video): a carrier prop's height comes only from its creation; moving updates (speed > 0) slide it on
  the ground plane at that height (the sphere stayed 12 m up, the thrown car flew level). Vertical motion = a new
  object per step (remove the previous one in the same tick).

- 15:57 (tester's video): a newly created prop fades in over a few hundred ms; objects that live 30-100 ms (step copies)
  are not seen. A fall or arc drawn with step copies needs steps longer than the fade.

- 16:07 (tester's video): Vfx_Event1 0x10000076 plays the closed sphere 0x2E000FC7's opening (the two halves part,
  ~1.5 s) and it stays open; Object_Activate 0x10000CCE shows nothing.

- 16:19 (tester's video): without Object_Activate 0x10000CCE first, Vfx_Event1 0x10000076 did not open the closed sphere
  (with Vfx_Spawn sent to the sphere itself); with Object_Activate 1.5 s before it opened (16:07).

## Tutorial 1's start in the original video, frame by frame (2026-10-17 16:24)

Times are video times of the tester's walkthrough (Batman fades in at 3:33.5).

| Time | What happens |
|---|---|
| 3:34 | First prompt (move to the marker, arrows at his feet) |
| 3:36.4 | Batman already walking toward the marker |
| 3:36.7-3:37.2 | Two fire columns come down next to him (meteor trails from the sky) |
| 3:37.4-3:38.4 | A grey dust dome grows out of the impacts and covers the street for about a second |
| 3:38.4 | Batman on the marker |
| 3:38.9 | Big yellow blast at the lower left (the big meteor), then a dust ring (3:39.5-3:40.5) |
| 3:41-3:43 | Batman on the ground; red star-shaped lava splat and a small glowing rock where it hit |
| 3:43.25 | He is up; prompt "Right-click to move to the marked location" |
| 5:03-5:13 | Catwoman cinematic: the vehicle blows up (5:03), Catwoman in a purple puff (5:07), fire in the background (5:08.7), another fire column at the lower left (5:11.8) followed by a smoke wave (5:12.2-5:13) and a glowing rock |

The server had Batman locked 3.5 s, the small meteors hitting at 2.0 / 2.7 / 3.4 s and the big one 3 s after the
marker (fase3-hx changes this: `start_lock`, `small_meteor_times`, `small_meteor_cloud`, `knockdown_delay`,
`big_meteor_fall_seconds`, `big_meteor_after_small`).

### Fire-column candidates (pack 0xA000009A)

- The impact rig graph 0x1A00021F appears in no other record of the 616 packs except the pack index and its own record:
  graph sets do not list graphs by id, so its owner cannot be found by searching for the id.
- The meteor event object 0x2E00069E (entity 0x2D00050C, a 0.1 m box with attach point 0x10000039; template
  0x1D00019C) has, after a valueless property 0x78, the words `0 | 1 | 7 | 0x1000092F`: Vfx_Spawn_Event05 (name table
  0x33000000). That key was rejected on the warning anchor with the template; it was never run on the object itself.
- World states 0x2E000872-0x2E000877 (entities 0x2D0006E3-0x2D0006E8, templates 0x1D000260 / 61 / 5E / 5F, property
  0x800 = 0x500000C0...0x500000C5) are timed set pieces. 0x2E000877's entity record (an autobone skeleton followed by
  a timeline with frame numbers 18-211) holds particles 0x18000318 / 0x18000319 / 0x18000321, keys 0x1000005D
  (Vfx_Active_State0), 0x1000006B (RunScript_FX_Spawn), 0x10000413 (_CEntitySystem_EnvironmentStateChange),
  0x1000069C, and five create actions (`0xC | 0x2E00069E | 1 | 0 | 0 | 0.25 x4`) at offsets (7.5, 0), (3, 8.5),
  (-3, 8.5), (2, 7.75), (-2, 7.75): a meteor barrage. The sound bank "Destruction" lists 0x2D0006E8. None of them is
  placed by id in Tutorial 1's packs (0xA000024C / 0xA0000256).
- Tutorial 2 lab `[debug] lab_tour = "start"` (tutorial1.LAB_START / LAB_EXTRA_KEYS) shows them with these keys.
- 2026-10-17 16:54 (tester, lab fase3-hx): the set piece 0x2E000877 (with its template 0x1D000260 and Vfx_Active_State0
  run 0.3 s after it appeared) closed the game 4.5 s after it appeared, like the models in MODEL_TOUR_CRASHES_BARE.
  The meteor event object 0x2E00069E (entries 1-3: Vfx_Spawn_Event05, Vfx_Spawn, Vfx_Active_State0) did not close it.
- 17:02 (tester, lab fase3-hy): the sibling 0x2E000872 (template 0x1D000260, Vfx_Active_State0) closed the game 3.4 s
  after it appeared. The set pieces 0x2E000872-0x2E000877 cannot be spawned on a carrier; all six are in
  MODEL_TOUR_CRASHES_BARE. They are probably level-placed timelines that need their own placement, not a prop.

## Tester's video of fase3-hx vs the original (2026-10-17 17:08)

Video "2026-10-17 17-06-06" (t = video time; the tutorial starts at t 2.2):

| Moment | Original | Server (fase3-hx) |
|---|---|---|
| Small meteors | two fire columns, then a grey dust dome ~1 s | the stp_meteor rocks, then the small meteors' dust cloud 0x2E0007D4 (yellow-brown, ~2 s): close, the colour differs |
| Big meteor | yellow blast, dust ring, clear ~2 s later | blast + debris (t 12.5), then a yellow cloud covering the street ~4.5 s (t 13-17): too long |
| Lava / rocks | red star splat + glowing rock | red rocks and the crater: present |
| Catwoman hits the vehicle | big yellow explosion, a wreck stays (5:03-5:04) | the vehicle just vanishes (t 93.5) |
| Later in the cinematic | fire behind (5:08.7), a fire column lower left + smoke wave (5:11.8) | nothing |
| End of the cinematic | straight to the street | ~2 s of a dark view around Batman (t 104) before the street |

No model of the wrecked vehicle is known yet (the vehicle 0x2E000AAB has no destruction states; 0x2E00034D / 34E are the
other paddy wagons, whole).
- 17:43 (tester, video "2026-10-17 17-39-53", fase3-ia): during the Catwoman cinematic nothing falls: the ground blows up
  and a crater opens (5:08.7 / 5:11.8). The vehicle blast made with the big meteor's explosion (scale 1.2, with
  shockwaves) filled the screen: grey shockwave, flying rocks, then the yellow cloud for ~3 s. The original (5:03,
  frames at 0.2 s) is a white-orange fireball about the vehicle's size with burning pieces flying out and a low
  smoke ring, gone in ~1 s; a wreck stays. The real effect is probably the wagon's destructible script 0x3400015F
  (Vfx_OnFire 0x1000013E, Vfx_OnExplode 0x10000079), which the street vehicle's empty table cannot run.

## The tester's full Tutorial 1 video at 0.5 s (2026-10-17 17:51)

"infinite-crisis-tutorial" (654 s, 1280x720): sampled at 0.5 s and every event again at 0.03-0.2 s. Main facts
(video times):

- Start: HUD and first prompt at 01:25.0, marker at 01:26.0; two fireballs with long flame trails hit at 01:28.0 /
  01:28.1 (white-grey dust dome, grey smoke over half the screen until ~01:29.6). Big blast at 01:30.0 just after
  Batman reaches the marker: white-orange flash, tan dust with a curved shockwave ring sweeping past (01:30-01:32.4).
  Batman down 01:30.5-01:34.0, get-up 01:34.0-01:34.8, next prompt and marker 01:34.4-01:35.0.
- Thug vs drone from 01:38; a white spark starburst + smoke puff by the steps (01:38.9) and a dust burst off a wall
  (01:44.2). Drone death: lilac-white flash, then a dark wreck with fading purple lines.
- Drone teleport-in: red health bars first, purple/white shimmer columns, then solid (~0.6-1.0 s), lavender rings.
- Practice targets (02:43.6) come with falling flaming rocks (02:41.3, 02:43.2) and an orange ground glow.
- Catwoman cinematic 03:04.4-03:20.2. The vehicle vanishes in one frame (03:09.65); a nearly white fireball about
  2 x Batman's height with radial flame streaks and shards thrown toward the camera, yellow-orange and rising,
  gone by 03:10.5 (~0.85 s). No shockwave, no smoke ring. A pile of twisted red/orange-edged metal (about 3 x
  Batman's length) stays one vehicle length down-left, where the crates were (the crates are gone). Catwoman: a
  lavender smoke column and a purple ground swirl (03:13.4), then a translucent lavender form running off.
- Bridge: flaming rocks fall at 03:37.2, 03:38.2, 03:44.2 and 05:38.2 near Batman (smoke, a small chunk, no damage).
  Gates fade out in ~0.5 s when opening; closing draws the edge lines first, then fills (~0.25 s). Level-up: a gold
  light column ~1 s.
- Super Strength: the truck rises over Batman in ~0.5 s, turns ~90 degrees to face the target before the throw, flies
  ~0.4 s nearly level (no tumbling), white fireball ~5 x Batman, orange sparks, orange smoke, no wreck.
- Destroyer cinematic: the sphere drops in ~0.1 s (no trail, no shadow), sinks a third into broken cobbles, white
  sparks at the base, a flat grey-brown dust ring 08:23.4-08:26; seams dim (08:26.0) and flare (08:26.9), the shell
  opens into petals 08:27.2-08:28.3, Destroyer + four drones inside.
- Fight: second truck on the Destroyer (09:13.8), a falling fire jet near Batman (09:40.4), Destroyer death: white-pink
  burst, magenta haze, a pink light column, nothing left (09:46.2-09:47.5); ending cinematic 09:48.9, VICTORY 10:07.3.

## Gaslight Batman's spawn and suit electricity (2026-10-17 18:05)

- Full video at 0.1 s (01:20-01:26): when the camera reaches him Batman is covered in a silver hexagonal shimmer with
  thin white lines coming down on him; at ~01:25.3 a cyan-white ring wave spreads at his feet (~0.5 s) and he is
  normal. Afterwards white-cyan arcs flicker on the antennas of his gauntlet guns (rig bones
  `chr_batman_gaslight_{main,LGun,RGun}_{L,R}Gun_AntennaA/B`, pack 0xA0000122).
- The scriptlet name table 0x33000000 (pack 0xA0000038) gives: FX_Spawn 0x10000119, **FX_Spawn_End 0x1000005A**,
  **Vfx_Bmg_Active 0x10000180**, Vfx_Bmg_Spawn 0x10000181, Vfx_Bmg_Sonic_Shell_Stop 0x10000183. In the graph-event
  table 0x300000A4 the same numbers mean other things: 0x10000183 SpawnIdle, 0x10000031 RunScript_FX_Spawn_End,
  0x1000006B RunScript_FX_Spawn, 0x10000154 Spawn. The catalog had 0x10000183 as SpawnIdle (wrong table).
- The "rope" the tester saw (fase3-gt / gx) matches the spawn's white lines started by FX_Spawn and never ended.
- 18:25 (tester, fase3-id): neither effect showed. The traffic shows FX_Spawn, Vfx_Bmg_Active and FX_Spawn_End sent;
  Vfx_Bmg_Active 0x10000180 and FX_Spawn_End 0x1000005A are not in Batman's own scriptlet table
  (data/batman_actions.tsv, 354 keys), so the client drops them. Named from table 0x33000000, his table has
  `_Defeat_StartupIncapacitated` 0x100001F9, `_Defeat_OnRespawn` 0x100001FC, `_Defeat_OnRevive` 0x100001FD,
  `Vfx_Bmg_Echoes_Active` 0x10000198 (passive), `Vfx_Active_State0` 0x1000005D, Vfx_Bmg_Spawn 0x10000181, FX_Spawn
  0x10000119. (data/batman_actions.tsv names some of them from the graph-event table: 0x10000183 "SpawnIdle",
  0x10000198 "Footstep_Left_Sprint".)
- 18:46 (tester, fase3-ie): Respawn / Echoes / Active State showed nothing. diag.log (17:06) lists every scriptlet the
  client accepts on Batman (table did 0x10000F80, 9 groups); named from 0x33000000 it includes Vfx_Fade_In 0x10000033,
  Vfx_Active 0x100000EB, Cinematic_Hidden 0x100009EB, **Cinematic_Intro 0x100009EC**, _Player_OnAgentControlledByPlayer
  0x100001E8, _Encounter_OnAgentControlledByPlayer 0x10000200, Vfx_GuideArrow 0x10000F80 / _Ping 0x10000F86 (the
  client runs these two itself at the tutorial start). Next test: those five.
- Big meteor: the blast is now centred on the crater (event_crater_offset 0, 0) and the crater comes 0.3 s after it.
- 19:09 (tester, fase3-if): test 1 Cinematic_Intro 0x100009EC put the "rope" on Batman (wrong); Fade_In, Vfx_Active,
  _Encounter_/_Player_OnAgentControlledByPlayer showed nothing. Next: Vfx_Stp_Invulnerability_Start / Active / Stop
  (0x100008B7 / B5 / B6; the hex shimmer may be a shield, the ring its end), Vfx_Status_Supercharge_Active 0x100001D3
  (his graph has CbtState_SuperCharged), Vfx_Item_Protection_Shield_Active 0x10000AA2.

## Gaslight Batman champion tour (2026-10-17 19:18)

The tester asked for a tour of every Gaslight Batman animation in Tutorial 2. `icserver/champion_fx.py` lists:
- GRAPH (111): names found in pack 0xA0000122 (his behavior graph 0x1A0002E7) that are in the graph-event table
  0x300000A4, raised with _HFSM_BehaviorRaiseEventAction. Among them RunScript_Vfx_Active 0x100001AE /
  StopScript_Vfx_Active 0x100001AD, RunScript_FX_Spawn 0x1000006B / _End 0x10000031, Spawn 0x10000154, SpawnIdle
  0x10000183, CbtState_SuperCharged.
- SCRIPTLETS (354): the client's accepted list on him (diag 17:06), named from 0x33000000.

### Cinematic_Intro lights the antennas (2026-10-17 19:52)

- Tester (champion tour "S 37/354 Cinematic_Intro"): it turned on the electricity of Batman's antennas (and it is the
  scriptlet that put the "rope" on him at 19:09).
- Its entry in the template next to the tutorial avatar 0x2E0001B2 (pack 0xA0000076, ~offset 4856400; templates
  0x1D0003AB / 0x1D000526, the block starts at 0x1D0004AC): `0x100009EC | 0 | 2 actions`: action 0x737 = 2, then
  0x211 (graph event) **Spawn 0x10000154**, then (kind 23) the scriptlet **Vfx_Bmg_Spawn 0x10000181**.
  Cinematic_Hidden 0x100009EB: 0x737 = 2 and the graph event **SpawnIdle 0x10000183**. The same template has
  FX_Spawn 0x10000119 -> Vfx_Bmg_Spawn, then Spawn and Vfx_Active 0x100000EB, and Vfx_Active_State0 entries.
- Next tour (`champion_tour_only`): Vfx_Bmg_Spawn, SpawnIdle, Spawn, Cinematic_Hidden, Cinematic_Intro, one by one,
  to tell which part is the electricity and which the rope.
- 20:41 (tester, five-entry tour): the electricity comes on when the graph event **Spawn 0x10000154** ends. So the
  antennas' arcs belong to his spawn sequence in the behavior graph (Spawn -> SpawnIdle -> idle), not to a scriptlet;
  Cinematic_Intro worked because it raises Spawn.
- 20:46 (tester): in the original Batman already stands with the antennas lit when the player gets control; the
  standing shimmer seen as the camera arrives (01:20-01:25.3, then the ring) is taken to be the Spawn animation itself,
  played before control.
- 21:53 (tester, fase3-in: Spawn raised alone at the start, 5 s hold): no electricity in Tutorial 1. In the tour
  Vfx_Bmg_Spawn 0x10000181 had run 12 s before Spawn, so both halves of Cinematic_Intro had played. fase3-io runs the
  whole Cinematic_Intro 0.5 s after the load-complete notice (during the intro cinematic 0x35000026, ~6.4 s before its
  state 4), so the Spawn sequence is over when the player gets control.
- The throw's aim (21:50:03): the server's F press (keybd_event, scan code 0, released at once) produced no skill
  order from the client. fase3-io sends the scan code (MapVirtualKeyW) and holds the key 80 ms.
- 22:38 (fase3-io): with the scan code the press reaches the game and the client sends a skill order (command 2,
  ability 8, at the cursor) at once: F is smart-cast (the exe has the preference User.SkillSmartcastOption and the
  strings "Smartcasting Value" / "Selfcasting Value"; the client did not report it to the server). Pressing F for the
  player throws the car, so it is off. How the original showed the rings on its own while carrying is still unknown.
- 22:51 (fase3-ip, tester): the split (Vfx_Bmg_Spawn + Spawn raised with 0x100001E3) did not light the antennas; the
  whole Cinematic_Intro did. Its record (pack 0xA0000076 at 0x4A222A): `0x100009EC | 0 | 2 actions`; action 1 has the
  type 0x737 (word 0x40000737, then 0x211, 0x211, 1, 3, 0x14, 0, 0, 0, 1, 1.0f, 0, 1.0f, -1) and the graph event
  0x10000154; action 2 has the type 0x17 (a scriptlet: Vfx_Bmg_Spawn). So "0x737 = 2" was the action count's
  neighbour, not a property: the graph event goes through action type 0x737, which the server cannot send by
  itself. fase3-iq runs Cinematic_Intro during the loading screen (champion_intro_at = "link").
- The throw skill 0x480003C9 (pack 0xA00000B3 at 0xC3E4DC) was read as 0 properties because six of its keys had no
  kind in skilldata's table; they are in properties.tsv (0x10000ABC enum = 23, 0x1000063A did = 0x340001A3,
  0x100006D5 bool = 1, 0x10000646 enum = 3, 0x100006D7 / 0x100006D8 did = 0x48000155 / 0x48000156, 0x100006F8 and
  0x100000E6 present without a value). Until fase3-iq F kept Super Strength while carrying, so the client never had a
  ground-target throw skill to aim.
- 22:40 (tester): Cinematic_Intro run during loading played a Batman voice line.
- 23:02: Batman's pack 0xA0000122 has Clip_Spawn / Clip_SpawnIdle, the clip chr_batman_gaslight_attk_respawn_a, the
  graph events RunScript_FX_Spawn / RunScript_FX_Spawn_End and a_SoundEventHook, and the voice bank
  chr_Batman_Gas_VO: Spawn is his respawn, whose clip carries the voice line. fase3-ir raises only the end-of-spawn
  graph events RunScript_FX_Spawn_End 0x10000031 and RunScript_Vfx_Active 0x100001AE at the tutorial start.
- 23:09 (tester, fase3-ir): those two lit nothing. fase3-is runs Cinematic_Hidden 0x100009EB (action type 0x737 with
  SpawnIdle) at the start.
- 23:19 (tester, fase3-is): Cinematic_Hidden made Batman invisible until the car lift (a full champion re-create):
  SpawnIdle is the hidden waiting state before Spawn, not the state after it.
- 23:29 (tester, tour G Spawn / S Vfx_Bmg_Spawn / G Spawn / S Cinematic_Intro, 8 s apart, Tutorial 2): only
  Cinematic_Intro lit the antennas. The graph event Spawn raised through _HFSM_BehaviorRaiseEventAction does not, with
  or without Vfx_Bmg_Spawn before it (the 20:41 reading "when Spawn ends" was wrong: Cinematic_Intro had run in that
  tour too). The electricity needs Cinematic_Intro's own action type 0x737.
- 23:37 video (fase3-iv, Cinematic_Intro at the tutorial start): the spawn shows a yellow vertical line from the sky
  to Batman with a blue ring at his feet for about 1 s (the "rope" of 19:09), then the antennas' blue arcs stay on.
  fase3-iw runs it during the intro cinematic instead.
- 23:46 (tester): the intro cinematic can be skipped at once, and then the rope shows anyway; Cinematic_Intro is off
  (fase3-ix) until the effect that lights the antennas alone is found.
- Throw aim (23:08, fase3-iq): with the throw skill on F (12 properties: targeting 1, ground markers 0x48000155 /
  0x48000156; 0x48000156 in pack 0xA00000B3 at 0x404D38 is a decal record: 0x1000057D / 0x1000057E = decal
  0x17000608, texture 0x13000135, 3.0) the F press still sent the cast at once (23:08:13.202). The rings are the
  client's own aim decals; the client did not aim. The exe's preference table (VA 0x15A28B4 ...) has
  User.SkillSmartcastOption / User.UseSelfCast next to Display.FullScreen_OutOfGame; the tester's UserPreferences.ini
  has no SkillSmartcastOption line (default). fase3-ip sends its parts without the
  action 0x737 = 2 (Vfx_Bmg_Spawn 0x10000181 + graph event Spawn).

## Critical hits and emotes (2026-10-17 20:55)

- Tester (champion tour): S 163 Combat_Critical_Attack 0x100000B8 (the arms) and S 171 Vfx_Bmg_Crit 0x1000017E (the
  shot) are Batman's critical basic attack. His graph has the variables CriticalChanceRoll / CriticalRoll, the state
  Basic_Attack_Critical and the clip chr_batman_gaslight_attk_basic_crit_a. His real crit chance is not known yet.
- Emotes in his pack 0xA0000122: one clip each: chr_batman_gaslight_emote_dance / _joke / _laugh / _taunt (graph
  events Emote_Dance / Joke / Laugh / Taunt, Emote_End / Emote_Abort), each with Run/StopScript_Vfx_Chr_Emote_*; the
  dance has its sound BATM_GAS_3P_DANCE_SFX (+ _STOP). Scriptlets on him: Emote_Dance_Start 0x10000490,
  Emote_Laugh_Start 0x10000492, Emote_Taunt_Start 0x10000493, Emote_Joke_Start 0x10000497, Emote_Oath_Start
  0x1000115E (no oath clip in his pack), Vfx_Chr_Emote_Dance 0x10000641, Vfx_Chr_Emote_Joke 0x10000643.
  chr_batman_gaslight_idle_laughter_a is CbtState_Laugh (the Joker's laugh status), not an emote.

## The throw's aim rings (2026-10-17 21:28)

Tester's pictures of the original: with the car overhead a big yellow ring around Batman (the throw's range) and a
small yellow ring at the cursor are on screen, and a left click throws; the car then flies turned sideways to the
point. Those rings are the client's aim for a ground-target skill: the throw skill 0x480003C9 the server puts on F
while carrying (its range stat and ground markers 0x100006D7 / 0x100006D8) shows them when F is pressed. No server
message is known that puts the client into aiming by itself, so the server presses F in the game window
(winctl.press_key) once the throw skill is on F.

## Champions / Amplifiers tabs after a match (2026-10-17 21:40)

After a match (Tutorial 1 end, 21:37) the Champions and Amplifiers tabs were empty. unhandled.log: the client sent
0x21A4 (u32 0) twice when Champions opened, 0x2106 (`02 "en"`) and 0x2116 (empty) when Amplifiers opened; the server
answered none of them (0x21A4 was already noted unanswered in fase3-fr). Their real replies are not known; the server
now answers 0x21A4 / 0x2116 with the login's champion data 0x20ED, character list 0x209D and item statuses 0x20B8.

## The Destroyer's sphere on the ground (2026-10-17 23:34)

- The closed sphere 0x2E000FC7 created on the ground does not open (Object_Activate + Vfx_Event1) once it has been
  given Vfx_Spawn 0x10000032 (16:19, 23:32 video). It opens when Vfx_Spawn is not sent to it (21:49 video, where it
  went to a fall-step object). Its swap to the open model 0x2E00101D shows nothing (both videos): the opened closed
  sphere is kept instead (fase3-iv).

## Champion select before the map (2026-10-18)

Tester: some maps should show the champion selection first and then load the map.

- Each encounter's twin record (`0x49xxxxxx`, pack 0xA00000B3, header `did | 2 | count | entries`) has:
  - `0x10000D0B` encounter type: 4 tutorial, 3 PvP, 1 versus AI. The exe's `IsTutorial` (VA 0x8582a0) is
    `0x10000D0B == 4`.
  - `0x10000B0E` bool SkipsLobby (VA 0x8582d0 reads it). Only Tutorial 1 (0x40000991) and Tutorial 2 (0x40000A81)
    have it. Every PvP and versus-AI map, and Tutorial 3 (Crime Alley: 1vAI Tutorial 0x40000CA6), go through the
    champion select first.
  - `0x10000AE7` (array of `0x10000AE6` champion DIDs): the three tutorials list only Gaslight Batman 0x40000086.
  - Metropolis Skyway 0x40000C28 has no twin in 0xA00000B3.
- Client side. CLobbyManager is at [0x1b77068].
  - The 0x204C handler (message vtable 0x15f2288, apply 0x8b8970 -> 0xabde80) stores its first two u32
    (our `0, 0`) as the number of teams (lobby+0xac) and players per team (+0xb0). It also stores the encounter and
    qflags (+0xb4 / +0xb8), my team (+0xbc) and the room (+0x4bc).
  - `CLobbyManager::SendLobbyEncounterDetails` (0xab8130) builds Flash's
    `GM_Lobby.RecvNotice_LobbyEncounterDetails(numTeams, playersPerTeam, encounter, draft (qflags bit 17), ranked
    (bit 16), custom (bit 18), myPlayer, myTeam, admin, mapName, requiredPlayers, isTutorial, skipsLobby, rejoin,
    encounterType, diamondMinimap)`.
  - Both the ConnectToLobby sender (0xabea40) and the 0x204C handler only call it when the number of teams is not 0.
    The server sends 0 teams, so the lobby UI (Flash `gameplay.lobby.PvPLobby`) never gets the details, and every map
    goes straight to loading with Gaslight Batman.
- Flash's lobby notices to the server include `SendNotice_SelectCharacter`, `SendNotice_PlayerChangedCharacterLockStatus`,
  `SendNotice_LobbyUIReady`, `SendNotice_TeamDisplayReady` and `SendNotice_PlayerSelectedEarlyLaunch`. Their
  event ids are still to be traced.
- Maps in the install (2026-10-18). Only these have map packs:
  - Coast City: mission 0xA0000162, zone 0xA00000D2.
  - Gotham Divided: mission 0xA0000168.
  - Gotham Heights: mission 0xA000016B, whose sound banks are AMB / Announcer / Music_GothamHeights.
  - Tutorial 1: 0xA000024C / 0xA0000256.
  - Tutorial 2: 0xA00002E5 / 0xA00002E6.
  - The zone packs 0xA000009A and 0xA00000FC belong to the two Gotham maps.

  No pack or sound bank exists for Crime Alley, Apokolips Causeway or Metropolis Skyway. So Tutorial 3, Crime Alley
  v AI and the three Clash maps cannot load with this install. The playable "versus AI" maps are Coast City,
  Gotham Divided and Gotham Heights v AI.
- 2026-10-18 00:06 (tester): the Destroyer's sphere used so far (0x2E000FC7) is the yellow one; the original's is
  purple and probably carries the falling animation. To be found.
- 00:10 check of the user's whole rp folder (≈590 packs). The six terrain packs have ids 0xA0C1xxxx, and each one's
  low half is a map landblock minus 0x0101: 12BA / 12C2 (Tutorial 2, 0x13BB / 0x13C3), 12CA (Tutorial 1, 0x13CB),
  1AD2 (Gotham Divided, 0x1BD3), 1AF2 (Gotham Heights, 0x1BF3) and 22E2 (Coast City, 0x23E3). The 5 zone packs and 4
  mission packs match the same maps; 0xA0000161 / 0xA000016E are not map packs. So Crime Alley: 1vAI Tutorial
  (0x40000CA6) exists only as an encounter definition: its map data (terrain, zone, mission, sounds) is not in this
  install.
- 0x2016 (our "end room check") is the client's lobby-to-world transition. Its message class (vtable 0x15efc38, ctor
  0x87f0a0) applies through 0x8b8a90 -> 0xab9080: room check, lobby+0x4cc = 1, SetLobbyTransitionCalled
  (lobby+0xa8) = 1, then CheckTransitionToWorldLoad 0xab8ec0. That function wants a selected character
  ([0xa1a040()+0xf4] valid) and fires UI state-machine event 0x23 TransitionToWorldLoad. The tutorials get it in
  ConnectToLobby. A champion-select map must get it only after the lock (fase3-iy).
- Flash -> C++ lobby notice ids: LobbyUIReady 0x100000CA, SelectCharacter 0x100000CE,
  PlayerChangedCharacterLockStatus 0x100000CF, CharacterLockFail 0x100000D0, UpdateLobbyState 0x100000C5,
  LobbyEncounterDetails 0x100000C6. The network events they send are not traced yet.
- 0x2029 lobby slot (serializer 0x8479b0): u32 team (+0x68) | u32 index (+0x6c) | u64 player (+0x70) | StringInfo
  name (+0x78) | u8 (+0x9c, is bot?) | u32 character (+0xa0) | u32 (+0xa4) | u8 (+0xa8, locked?) | u32 (+0xac) |
  u32 (+0xb0) | 7 x u32 (+0xb4..+0xcc) | list (+0xd0). Flash PvPLobby.RecvNotice_UpdateLobbyState gets per player:
  team numbers, team indexes, player ids, names, is bot, character DIDs, levels, pre-game DIDs, locked status, reveal,
  Stolen Powers, wallpapers, icons, base characters, amplifier sets. It calls SetMyCharacterFromLobby(variant,
  base). The lock button (m_rbLobbyLock) is turned off while m_didCharacterFromLobby is not a valid DID or the
  button's OwnableUIState is UNAVAILABLE / DISABLED.
- Client event 0x20E4 (00:23, Coast City v AI lobby): u32 character variant | u8 1 | u32 1, sent when the tester tried to
  lock. Taken to be the lock request (fase3-iz).
- 0x204C list at +0x40: u32 count + (u32 DID | u32 status | u32 content type | u8 owned | u32 count), the
  item-status format of 0x20B8 (applied through 0xa14660 -> 0xa843a0). List at +0x50: u32 count + DIDs, kept by the
  lobby (0xa95e70 -> 0xadb230). It is taken to be the allowed characters.
- Coast City starts (mission pack 0xA0000162, landblock 0x23E3): cinematic 0x35000013 Player01-05 at x ~13-24 (our
  team's start, (20.19, 57.44, 250.20)); cinematic 0x35000012 Player01-05 at x ~136-147 (the other team; Player01
  (137.47, 60.22, 250.19) yaw -1.222).
- Lighting: property 0x956 0x10000016 is the tutorial's Gaslight lighting. No 0x956 value was found in the Coast City
  mission pack. fase3-ja sends none there, so the client uses the region's own lighting.
- Dark Coast City (2026-10-18): the fase3-cg minimap cave M asked the map manager (0xa4c2c0) for Tutorial 1's map
  image whatever the map. The fog-of-war blocker map comes from that map data. Cave N (fase3-jb) asks for the encounter
  in the lobby manager, [[0x1b77068]+0xb4] (OnLobbyState stores 0x204C's encounter there).
- 0x956 (property "lighting environment" in the catalog): the client reads it on the LOCAL PLAYER (0x7e35df, together
  with 0x5cc and 0x216, each compared with 2) and in 0xab4b08 (writes it to the player). Its meaning is still
  unclear; leaving it out (fase3-ja) did not change Coast City's darkness.
- A champion's animations: the names in his behavior-graph pack (roster "parent_pack") that are in the graph-event
  table 0x300000A4 (pack 0xA0000038; 4687 names). They are raised with _HFSM_BehaviorRaiseEventAction 0x100001E3 +
  variable 0x780.


Note (2026-10-18 01:10): cave N first sat at file 0x99735C, inside cave X; it now lives at file 0x4C4380
(rva 0x4c4f80, free 0xCC padding).

## John Stewart's kit (2026-10-18 00:57)

Tester: "program John's abilities". John Stewart (variant 0x40000E57) was never released.

- Skill set 0x480013E4 (pack 0xA000039B): Q `full_auto` (script 0x340007A7, targeting 13), W `claymore_mine`
  (0x340007A8), E `forward_base` (0x340007A9), R `omni_turret` (0x340007AA), passive `architects_will`
  (0x340007AB), basic attack 0x340007A6 (targeting 9). Every skill has the same placeholder numbers: damage 40
  +40 per rank with 0.4 scaling, cost stat 3 = -30 (-10 per rank), cooldown stat 15 = 14 (-2 per rank).
- Pack 0xA0000038 has two name tables in the same `u32 id | u32 len | name` format: graph events (table
  0x300000A4) before file offset 900000, scriptlets (table 0x33000000) after it. Both have 0x10xxxxxx ids, so a
  name search must split them by offset (icserver/kits.py `names`).
  - John's graph events (behavior graph in pack 0xA000039F): Wildcard_QSkill 0x100003BD, Wildcard_WSkill
    0x100003C0, Wildcard_ESkill 0x100003C2, Wildcard_RSkill 0x100003BF.
  - His scriptlets: Vfx_Jst_FullAuto_Active 0x100010F1; Vfx_Jst_Claymore 0x100010FC, Claymore_Phase_Start /
    Active / Stop 0x100010ED / F0 / E6; Forward_Base_1..4 0x100010E5 / EA / EC / EF, Forward_Base_Upgrading_1..4
    E4 / E9 / EB / EE, Forward_Base_Dismantle E8; Turret 0x100010F3, Turret_Active_1..4 F4 / F6 / F9 / FB,
    Turret_<n>_Fire F7 / DF / E2 / E7, Turret_Upgrading_1..4 FE / FF / E0 / E1, Turret_Dismantle F8;
    Architect_Start / Active / Stop E3 / FA / FD.
- What each skill did in the game was never shipped. The server's behaviour (fase3-jc) follows the names; see
  `catalog/data/skills_notes.tsv`. The client plays the scriptlets on the champion (agent 0x0200000000000002);
  the mine, base and turret have no world object of their own yet (the two world states in pack 0xA000039F,
  0x2E0013A8 and 0x2E0013B2, are candidates).

## The Amplifiers tab (2026-10-18 10:09)

Tester: the Amplifiers tab keeps loading and never shows the amplifiers.

- Flash (UI pack 0xA00000D0) opens the tab only when `CheckForAllDataAvailable` finds three flags set:
  - `AmplifierSetManager.hasAllAmplifierSetData`. It is set by `RecvNotice_NotifyListAmplifierSets`, which the
    client calls for message 0x2090 (exec VA 0x8aa0c0 -> 0xa64520 -> 0x8cb1a0). It is called even for an empty
    list. Until fase3-jg the server sent 0x2090 only with the scorecard, so in the menus it never came.
  - `AmplifierSetManager.hasAllAmplifierData`. It is set by `OnItemStatusesChange`: on the item statuses (0x20B8),
    it takes the owned Mods / Augments and reads their names, tooltips and icons from the client's own data
    (`SendQuery_UI_InqModData` / `SendQuery_UI_InqAugmentData`).
  - `BoutiqueDataManager.hasDataForAmplifiers`. It is set by `GM_Amplifier.RecvNotice_NotifyContextualAmplifierData
    (boutique ids, amplifier DIDs, currency names, currency values)`, the store prices. The server never sent it.
- That notice comes from message **0x2107**:
  - ctor VA 0x8ca6f0 sets the id 0x2107, vtable 0x15f3e94, serializer VA 0x847870 and exec VA 0x8aa140 ->
    0xa57510 -> 0x8ca800 (Flash call).
  - Body: `u8 0 | u32 count | count x (u64 boutique id | u32 amplifier DID | compact length + 8-bit currency name |
    u32 price)`. The element reader is VA 0x86d980, 0x18 bytes in memory, and the string is read by VA 0x424b80.
  - A count of 0 still calls Flash (0xa5758a jumps to the notice), and Flash sets the flag after its loop.
- 0x2090's two u32 after the u8 are passed to Flash as `i_uiTotalAmplifierSets` / `i_uiMaxAmplifierSets`
  ([msg+0x20] / [msg+0x24]).
- 0x2116 (empty, client) is sent when the tab opens, from VA 0x88a730, called from VA 0xa57170 in the same
  amplifier code. 0x2106 (`02 "en"`, client) also comes then (VA 0x883340, called from VA 0xa2fd1e); it is
  probably the store catalog and is not answered yet.
- fase3-jg sends 0x2090 (0 sets, 6 slots) and an empty 0x2107 at login and again on 0x2116.
- fase3-jh (10:23 logs): both managers are created only when the tab opens. BoutiqueDataManager's constructor
  (UI pack, sprite code near "m_bHasAmplifierBoutiqueData") sets the flag false, registers
  NotifyContextualAmplifierData and calls `SendNotice_UI_RequestAllAmplifierBoutiqueData`. AmplifierSetManager's
  sets both flags false, registers NotifyAmplifierSet / NotifyListAmplifierSets, calls
  `SendNotice_UI_RequestAllAmplifierSets` and listens to `OwnablesManager.EVENT_ITEM_STATUSES_UPDATE`. Data
  sent before that is lost, so the answers must follow the client's 0x2116.
- fase3-ji: 0x2116 (VA 0x88a730) is sent by VA 0xa57170 only while byte +0x1b1 of the store UI object
  ([VA 0xa12d50()+0x54]) is 0. Otherwise VA 0xa416b0 rebuilds the store lists from the cache. The byte is set by
  0x2115's exec (ctor VA 0x8aa4f0, vtable 0x15f2d3c, serializer VA 0x846460, list reader VA 0x841d90 with 0x230-byte
  elements read by VA 0x866650, exec VA 0x8aad20 -> 0xa57000). The exec searches the list for an entry whose
  +8 is 0x4000094C and is cleared at VA 0xa1aa7d. So 0x2116 asks for the store offers and 0x2115 answers it. The
  server sends it empty.

## The Stats tab: account encounter stats (2026-10-18 10:36)

- Correction to fase3-ji: 0x2116 (client, empty) is `RequestAccountEncounterStats`, and **0x2115** is the answer.
- The exec (VA 0x8aad20 -> 0xa57000) needs the profile object ([VA 0xa12d50()+0x54]). It copies the entries to its
  list at +0x1b4, the 0x4000094C entry first, sets +0x1b1 = 1 (cached) and calls VA 0xa416b0.
- VA 0xa416b0 looks up each entry's encounter record (VA 0x8535d0) and its property 0x10000A73 (kind 0x15). It
  builds the label and data arrays (counters loaded with `fild qword`, ratios formatted "%.2f") and calls VA
  0x8ce3d0. That function calls Flash `GM_Character.RecvNotice_SendAccountEncounterStats(i_adidEncounters,
  i_aRanked, i_statLabels, i_statData)` (UI pack: a screen with AccoladeManager and scroll views).
- Entry wire format (VA 0x866650): u64 (+0) | u8 bool 0/1 (+0xc, ranked) | u32 encounter (+0x8) | 14 x u64
  (+0x10..+0x78) | 2 x u32 | 6 x u64 | u32 | 8 x u64 | u32 | 6 x u64 | u32 (+0x130) | StringInfo (+0x1e8) |
  StringInfo (+0x20c) | 21 x u64 (+0x138..+0x1d8) | 2 x u32. That is 481 bytes plus the two StringInfos.
- VA 0xa57170 sends 0x2116 only while +0x1b1 is 0 (cleared at VA 0xa1aa7d). Otherwise it rebuilds from the cache.

