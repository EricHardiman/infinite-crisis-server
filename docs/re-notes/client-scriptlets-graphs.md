# Client scriptlets (event 0x8D) and animation-graph events

Static analysis of `InfiniteCrisis.exe` (Ghidra via REA, image base 0x400000, all addresses VA), 2026-10-22, plus
reads of the scriptlet tables of packs `0xA00000DF` / `0xA0000256` / `0xA0000162` with `ics.rp` / `ics.gamedata`.
Confidence: **C** = read in code or data, **P** = probable, **O** = open.

Summary of the answer to "why did Batman ignore CbtState_Knockdown / Dead / GetUp":

* The 0x8D path, the table check, the scriptlet `0x100001E3`, its action and its variable `0x780` are all correct in
  what the server sends (C, section 1-3). Nothing in the client rejects that message for the champion.
* The action raises the event with the **same call the cinematic player uses** (`entity+4 ->vtable+0x58(event)`),
  so a raised event reaches the graph (C).
* What differs from the cases that worked (old server: `_Defeat_OnIncapacitated`, scriptlet `CbtState_KnockUp`, the
  CarPickup on a standing Batman) is the **state of the champion** when the event arrives: in fase3-gj he was
  walking under a server-driven move and nothing blocked his locomotion; the data-authored defeat / knock
  scriptlets go together with the LifeState / "cannot act" properties and a stop. Most probable cause (P): the
  movement / locomotion side re-drives the graph back to locomotion. Section 4 gives the recipe the data implies.

---------------------------------------------------------------------------------------------------------------------

## 1. Event 0x8D: handler and pipeline (C)

### 1.1 Handler chain

| Step | Address | What |
|---|---|---|
| exec / serializer | `0x698C40` / `0x83C030` | standard message wrapper |
| handler | **`0x634F20`** | `obj+0x10` (script component) must exist -> `0x627E20(list)` |
| list loop | **`0x627E20`** | for each 0x60-byte entry: copy the parameters (`0x657630`), call `0x6279D0(key, instance, params, signals)`; keeps the last negative HRESULT |
| one entry | **`0x6279D0`** | see 1.2 |
| 0x2073 (via local player) | `0xA22DA0` | same entry list; an entry whose instance is already running is skipped (`0x57B510`), else `0x6279D0` |
| 0x2050 / 0x2056 | `0x588A00` -> `0x57D8B0` -> `0x57CFD0` -> `0x57C260` | the *local* start path (the one the client's own script nodes use); no instance number from the wire, no originator test |

Entry layout in memory (stride 0x60, filled by the reader the project already documents in
`ics/messages.scriptlet_entry`): `+0 key`, `+4 instance`, `+8 signal bit set`, `+0x18 parameters` (flags at
params+0x38, originator u64 at params+0x20, start time f64 at params+0x18, variable table inside).

### 1.2 `0x6279D0` (one 0x8D entry), in order

1. Component owner (`comp+4`) must exist, else `0x8000FFFF`.
2. **Originator test**: if params+0x20 (originator u64) == `DAT_01B6A710` (the local player / controlled IID returned by
   `0x635230`), the entry is dropped (result 1). Our server sends originator 0: fine.
3. **Table test** `0x5235C0(tableset = comp+0x3C, key, mask 3)`: the key must be in one of the object's scriptlet
   tables (hash per table, recursive through base tables) and the entry's property **`0x211`** (enum `0x300000B6`,
   default **2**) ANDed with 3 must be non-zero. Fails -> `0x80070057`, nothing happens (this is how carrier props lost
   their scriptlets before they got their 0x7D2 tables).
4. **Instance test** `0x57B510(instance)`: if a run with that instance number is alive on the object, the entry is a
   **signal** to it (`0x534BF0`: again skipped when the originator is local; if its start time is in the future it is
   rescheduled, else `0x534290` runs the scriptlet's *signal* action list for the bits set in the signal bit set).
   Otherwise a new run is created: `0x57BDC0(key, instance)` (instance `DAT_0185F2B0` = "allocate", else the wire
   number) registers it in two lists (by instance at comp+0x14/+0x18, by key at comp+0x24/+0x28).
5. Context `0x517240(owner, params)`: ctx IID = `owner+0x100` (the object itself), the parameters incl. the variable
   table (ctx+0x18) are copied; **ctx+0x60 = 1** ("started from the network").
6. Start `0x5364D0(run, key, tableset, &ctx, signals)` -> definition lookup `0x52AA40` -> `0x5362F0` (start time,
   scheduling) -> `0x535CC0` (execute).

The local path (`0x57C260`) additionally counts live runs with the same key and refuses a new one when the count
reaches the key's **property `0x479`** (int, default 1 = only one instance; `0x100001E3` has 999) (C for the count, P
that `0x51F080` reads 0x479).

### 1.3 Definition = merge of every table (C)

`0x52AA40` caches per key; `0x525690` builds the definition by walking **every table of the object (and their
bases)** and appending that key's action lists from each one: list **1** (start) -> def+0xC, list **2** (signal
handlers) -> def+0x1C, list **4** (end) -> def+0x2C. So a key present in several tables runs all of their actions.

### 1.4 Execution, attachments, lifetime (C unless marked)

* `0x535CC0`: state 2 (running), then `0x534900` for list 1, 2 and 4 in that order (`0x534900(ctx, phase, list)`).
  Phase 1 clears ctx+0x60, so every action runs whether the run came from the network or not; an action whose vtable
  +0x48 says "not from network" would be skipped only in phase 2 (all checked action types return 1).
* Each action: probability `in_ECX[10]` (f32, 1.0 = always), intensity jitter, then vtable **+0x28 execute**
  (`0x52DC90`). An action may return a *persistent instance* (0x5C bytes, `0x52A660`); one without flag 2 (+0x54) is
  kept in the run's list (`run+0x54/+0x5C`): **these are the attachments** (particles, meshes, child scriptlets,
  waits). One-shot actions (raise event, set variable) return nothing.
* If the run has no live child (`run[0x17]==0`) it is flagged finished (0x40) and removed at once (`0x57BAF0`:
  out of both lists, `0x516F80` stops whatever is left). Otherwise it lives until its children end or a signal /
  stop ends it; the end list (4) runs then.
* **Replacing** (corrected 2026-11-03, anim-23: the list handler `0x627E20` first stops every network-started run on
  the object, `0x627E4D` -> `0x57CB60`; docs/reverse-engineering.md "Every 0x8D replaces the server's runs"). Within
  the entry loop itself there is no "new scriptlet replaces the old one" rule. A new key starts a second run
  next to the first; the same instance number signals the existing run. What removes attachments is (a) the run
  ending, (b) an explicit stop action in the data (P: type 0x17 / the `Vfx_Stop` keys), (c) the object being
  destroyed. Data authors chain states (`Vfx_Startup` -> `Vfx_Active_State1` via a type 5 action with a delay).
* Variables: ctx+0x18 (the 0x8D variable table). An action field bound to a variable gets it at run time
  (`0x528CD0` copies the action, `0x51CD90` applies bindings): the binding's variable descriptor byte +0x12 == 6 ->
  read from the ctx variable table (`0x44AEC0`), otherwise **read from the target entity's own property**
  (`0x58B320`). So a binding can also pull e.g. the target's team or position.

### 1.5 Scriptlet entry format in the table bodies (C for the words read, P for the names)

```
key | 0 | n_props | props (a | a | value, or a | a|0x40000000 | value...) | n_actions | actions
action = u32 type | u32 n_bindings | n x (u32, u32, u32 field, u32 variable) | u32 0 | u32 0
       | u32 1 | f32 probability (1.0) | f32 jitter (0) | f32 intensity (1.0) | u32 time (0xFFFFFFFF = none)
       | type-specific words | [u32 n_children | children]   (containers)
```

Examples read from the packs (exact words):

| Scriptlet (table) | Actions |
|---|---|
| `_HFSM_BehaviorRaiseEventAction 0x100001E3` (`0x1D0000E2`, Batman) | props `{0x479 = 999}`; 1 action **type 0x14**, 1 binding `(1, 1, field 0x97, variable 0x780)`, literal event 0 |
| `Engagement_SideStep_Left 0x100001F2` (same table) | type 0x14, event `0x100000EA` |
| `_Defeat_OnIncapacitated 0x100001FB` (`0x1D0000E8`) | type 0x14 event **`0x100000AD` CbtState_Death_Induce**; type 0x17 with key `0x10000130` |
| `_Defeat_OnDead 0x100001FA` | type 0x14 event `0x100000AD`, then `0x100001FB`-related actions |
| `_Defeat_StartupIncapacitated 0x100001F9` | props `{0x7E6}`; type 0x14 event **`0x1000010B` CbtState_Dead** (the prone pose) |
| `_Defeat_OnRevive 0x100001FD` | type 0x14 event **`0x1000009D` CbtState_GetUp**; type 0x14 event `0x100000AA` |
| `CbtState_KnockUp 0x1000003D` (scriptlet key, not the graph event) | type 0x22 container: watches property `0x100000FA` LifeState (values 5 / 4), children: type 0x14 `0x1000009D`, type 0x18 ... |
| `CbtState_GetUp 0x10000355` (scriptlet key) | type 0x22 containers on `0x100000FA`, `0x10000B2D`, `0x100003F3` |
| `_Combat_GoToLocomotion 0x100002FD` | type 0x22 containers on `0x100000FA` and `0x10000B2D` |
| `Vfx_Startup 0x1000018E` (`0x1D0008EF`) | type 5, time 0x6A, key `0x1000006B` (Vfx_Active_State1), child type 0x11 particle `0x180012F4` |
| `Vfx_Active_State1` | type 0x11 particle `0x180012F4` (floats 40.0, 60.0) |

### 1.6 Action types (C: registry and addresses; P: meanings)

Registry: 0x31 factories built by `0x669CE0` in `DAT_01B6AB70` (count `DAT_01B6AB78`), looked up by the type byte
in `0x5335A0` / `0x52E460`. Object vtable slots: +0x24 type, **+0x28 execute**, +0x48 allowed when started from the
network, +0x50 "skip now".

| Type | Create | Object vtable | Execute | Meaning |
|---|---|---|---|---|
| 0x01 | `0x663AC0` | `0x15CE630` | `0x677590` | O |
| 0x04 | `0x663D10` | `0x15CE6E0` | `0x65B0A0` | O |
| 0x05 | `0x662710` | | | run another scriptlet key after a delay (P, data) |
| 0x0E | `0x6629A0` | `0x15CF3B8` | `0x5157B0` | O |
| 0x11 | | | | attach particle emitter `0x18......` (P, data) |
| **0x14** | `0x6637A0` | **`0x15CF250`** | **`0x672930`** | **raise animation-graph event** (C, 2) |
| 0x17 | `0x662CC0` | `0x15CF0B0` | `0x684D10` | builds a target list (`0x51EF90(6)`) and runs a key on it (P) |
| 0x1B-0x1E | `0x663970`, `0x6638D0`, `0x663830`, `0x663A10` | `0x15CF7B0`, `0x15CF750`, `0x15CF6F0`, `0x15CF810` | `0x6774D0`, `0x677470`, `0x677410`, `0x677530` | O (one family) |
| 0x20 | `0x664550` | `0x15CEFD0` | `0x660E40` | O |
| **0x22** | `0x6632C0` | `0x15CF1E0` | `0x530310` | persistent container with a property condition and children (C container; P condition) |
| 0x26 / 0x27 / 0x28 / 0x2A / 0x2B / 0x2C / 0x2E / 0x2F | `0x664660` / `0x663110` / `0x663080` / `0x663230` / `0x6631A0` / `0x664720` / `0x664920` / `0x675A00` | | `0x65B6A0` / `0x9DB900` / `0x65C7D0` / `0x9DB900` / `0x668E50` / `0x674B80` / `0x682110` / `0x6694F0` | O |
| others (2, 3, 6-0xD, 0xF, 0x10, 0x12, 0x15, 0x16, 0x18-0x1A, 0x1F, 0x21, 0x23-0x25, 0x29, 0x2D, 0x30) | see `0x669CE0` | | | O (sounds, meshes, spawn world state, set variable are among them) |

---------------------------------------------------------------------------------------------------------------------

## 2. How a graph event is raised (C)

* **Action 0x14 execute `0x672930`**: `event = this+0x34` (field **0x97**, enum `0x300000A4`, setter `0x656430`
  accepts only kind 8 / 0x0A); then **reads scriptlet variable `0x780` from the context itself** (`0x44AEC0(ctx+0x18,
  0x780)`) and, if its kind is 8 or 0x0A, uses it instead. event 0 -> `0x80070057`. Target = the context's IID (the
  object the 0x8D was addressed to) via the entity manager (`0x514D20` -> `[0x1B67258]+0x58`), then
  **`(entity+4)->vtable[0x58](event)`**; no other check (vtable +0x48 = 1, +0x50 = 0).
* The **cinematic player** raises its actor A-list the same way: `0x6A6880` -> `0x6A6830` -> `0x6A6720` ->
  **`0x69DCA0`**: `(actor_entity+4)->vtable[0x58](event)` for each (frame, event) in the window. Cinematic actors
  animate, so this call works when the graph knows the event (C for the call; the graph-side mapping of the global
  id to the graph's own event table is in the per-graph enum, not traced here: O).
* The client's own script node `0x1000004E` RaiseGraphEvent: execute **`0x9CE1C0`** resolves the entity
  (`0x992280`), builds a variable table with `0x780 = event` (kind 8 or 0x0A only), sets run flags 0x12 (| 4 when the
  local player entity exists) and runs scriptlet `0x100001E3` on it through **`0x588A00`** (local path). So the client
  plays its own skills' graph events with exactly the message the server builds; there is no separate network
  "graph event" message.
* Not graph events (corrections): `0x4607A0` / `0x461430` (used at `0x9B5E00`, `0x970A80`, `0x96DFB0`,
  `0x976B30`, `0x9C4A80`, `0xA15680`, `0xA38540`, `0x69DF90`, `0x6A10F0`) build and queue **script (HFSM) events**
  into an event sink whose accepted ids are a sorted list at sink+0xD8 (queue at +0xB0); unknown ids are dropped.
  The immediates `0x100000AD` at `0x9B5E56` and `0x1000009D` at `0x970B32` noted in `knock_re.txt` are script-node
  / script-event ids that collide with the graph names (`0x9B5E00` chooses node `0x100000AD` or `0x1000009C`, both
  are node ids in `catalog/data/script_nodes.tsv`). Many `mov eax, 0x1000xxxx; ret` stubs at `0x97Cxxx` are node
  type getters (collisions again, e.g. `0x97C291` = `0x100000BB`).

---------------------------------------------------------------------------------------------------------------------

## 3. Why the champion can ignore it, and what the original server did

What is ruled out (C):
* table: `0x100001E3` is in **`0x1D0000E2`** (pack `0xA00000DF`), one of Gaslight Batman's tables (variant
  `0x40000086` 0x7D2 -> `0x1D0000E2`, `0x1D0000E8`, `0x1D0000EF`, `0x1D0001F6`, `0x1D0003AB` (+ bases `0x1D0004AC`,
  `0x1D0004F4`)); `0x211` default 2 passes the mask 3. (Requires the champion object's class to be that variant or a
  costume with the same 0x7D2: check `w.champion.class_id`.)
* originator 0, new instance numbers, kind 8 for `0x780`: all accepted.
* no "server vs client controlled" gate in the action: it does not look at who controls the entity.

Remaining causes, most probable first:
1. **Locomotion wins** (P). In the failing test Batman was walking along a server path and the server kept sending
   his movement; the old server's working falls (`_Defeat_OnIncapacitated`, `CbtState_KnockUp` scriptlet, the
   graph-event knockdown in fase3-fl) happened while he was stopped (`knockdown_delay` with the marker stop). The
   champion's data couples these states with properties the client watches: `CbtState_KnockUp` / `CbtState_GetUp` /
   `_Combat_GoToLocomotion` are type 0x22 containers on **LifeState `0x100000FA`**, **`0x10000B2D` (cannot act)** and
   **`0x100003F3` (stunned)**; `0x85EA30` / `0xA0E7F0` / ... register listeners on the same three properties
   (client-status-effects.md, client-movement.md 3: LifeState != 4 or 0x10000B2D blocks every order, 0x100003F3
   holds skills).
2. The event reached a graph state with no transition for it (O): the wildcard list in `knock_re.txt` comes from
   SM_Main_Machine; if the locomotion sub-machine consumes the event first, nothing happens. Death_Induce worked
   through `_Defeat_OnIncapacitated`, Knockdown `0x100002F5` was never seen working.
3. The graph never got it (O, testable): break on `0x672930` and log ESI after `0x67298B` (the event) and EAX after
   `0x514D20` (the entity); break on `0x6279D0` return (1 = originator skip, `0x80070057` = key not in tables).
   Suggested `tools/diag.py` probes: `0x6279D0` ret value, `0x672930` + `0x6729AA` (the +0x58 call happens).

What the original server most likely did (P, from the data authored for it; none of these keys is referenced by
client code, so the server sent them):
* Death: LifeState `0x100000FA` != 4 (+ `0x10000B2D`), then `_Defeat_OnIncapacitated` / `_Defeat_OnDead`
  (Death_Induce), `_Defeat_OnFade`; respawn `_Defeat_OnRespawn`; revive `_Defeat_OnRevive` (GetUp).
* A champion that must start lying down: `_Defeat_StartupIncapacitated` (raises CbtState_Dead = the face-down
  pose).
* Knock-ups / stuns: the status scripts set `0x100003F3` / `0x10000B2D` and the scriptlet keys `CbtState_KnockUp`,
  `CbtState_GetUp`, `_Combat_GoToLocomotion` (type 0x22 containers that react to those properties).
* Cinematics: the cinematic's A list (`0x69DCA0`), not scriptlets.

## 4. Recommendation for the tutorial knockdown

In this order, each as a `config.py` switch (behaviour change rule):
1. Stop the champion first: send his movement stop state (client-movement.md 1.4) and ignore 0x20EE while down
   (already done for orders); set **`0x100003F3 = 1`** (and optionally `0x10000B2D = 1`) on him.
2. Then raise the fall with data-authored scriptlets that raise literal events: `_Defeat_OnIncapacitated`
   (`0x100001FB`, random face) or **`_Defeat_StartupIncapacitated` (`0x100001F9`) for the deterministic prone pose**,
   or keep `0x100001E3`+`0x780` with `0x100002F5` now that he is stopped.
3. At get-up: `_Defeat_OnRevive` (`0x100001FD`) or `0x100001E3`+`0x1000009D`, then clear `0x100003F3` /
   `0x10000B2D` (the `CbtState_GetUp` / `_Combat_GoToLocomotion` containers watch exactly these).
If (2) still shows nothing, run the probes in 3.3 before changing anything else.

---------------------------------------------------------------------------------------------------------------------

## 5. Other client script entry points the server can use (C for the call chains)

| Message | Chain | Effect |
|---|---|---|
| `0x8D` | `0x634F20` -> `0x627E20` -> `0x6279D0` | start / signal scriptlets with instance numbers, variables, originator (1) |
| `0x2073` | `0xA22DA0` | same list through the local player; entries whose instance is alive are skipped |
| `0x2050` (u64 object, u32 key) | `0xA14580` -> `0x57D8B0` | run a key on the object, no variables (local path, `0x479` instance cap applies) |
| `0x2056` (u32 key, variable table) | `0xA0D040` -> `0x57D8B0` | same with variables, on the destination object |
| **`0x204E`** (u64 agent, u32 event) | exec `0x8B6820` -> `0xAA1B90` -> `0x96DE90` | **script (HFSM) event** to every running script of the agent's component at `entity+0x8C` (each script's sink at +0x70, `0x461430`); unknown event ids are ignored by each script. This is the way to wake a client-side 0x34 script waiting on an event such as `0x10000060` (P for the use) |
| **`0x2008`** (u64 agent, u32 event, u32 key) | exec `0x8B68C0` -> `0xAA1BF0` -> `0x96DED0` | same, only to the scripts whose id (vtable+8) == key (P: the 0x34 script DID) |

(The protocol tables called 0x204E / 0x2008 "effects: raise script event"; the target is the agent's script /
effect component at `entity+0x8C`, `0xAA1A60`.)

## 6. Open points

* The class at `entity+4` and its vtable +0x58 (global event id -> graph event index, guards inside it).
* Action types other than 0x14 / 0x22 / 0x17: execute addresses are listed in 1.6.
* The exact meaning of the type 0x22 condition words (`prop | 0 | n | values... | prop | value | 0 | 3 | 5`).
* Property `0x211` values (enum `0x300000B6`): which value forbids network start.
