"""Tutorial 1, "A Champion in Peril": the scripted part, as data.

Phase 1 ported the old server's first two steps. Phase 2 adds the encounter
layout read from the game's own packs (see LAYOUT below and `ic.py layout`)
and the first fight: the drone from the cinematic, then the wave that
follows it, then the level-up that unlocks the first skill.
"""
import math
import struct
import time

from . import batman
from . import messages as M
from .bridge import Bridge
from .wire import KIND_BOOL, KIND_DID, KIND_ENUM, KIND_F32, KIND_IID, KIND_INT

ENCOUNTER = 0x40000991
LAYOUT_PACK = 0xA0000256          # encounter layout records (prefix 0x1d) live here

HUD_MINIMAP, HUD_PORTRAIT, HUD_MISSION_OBJECTIVES, HUD_HINTS = 15, 18, 35, 32
HUD_EVENT_FIRST_RESTORED = 1
START_ELEMENTS = (HUD_PORTRAIT, HUD_MINIMAP, HUD_MISSION_OBJECTIVES, HUD_HINTS)
# HUD element ids (emp_gen UIHUDElementID, read from the UI scripts' getters).
HUD = {
    "PlayerVitalBars": 2, "SkillButtonWUpgradeButton": 4, "SkillButtonRUpgradeButton": 5,
    "SkillButtonBasic": 6, "SkillButtonPassive": 7, "SkillButtonQ": 9, "SkillButtonR": 12,
    "SkillsBar": 14, "Minimap": 15, "SkillButtonW": 17, "Portrait": 18,
    "SkillButtonPassiveUpgradeButton": 19, "LevelAndExperience": 20, "SkillButtonE": 25,
    "SkillPointSpendReminder": 27, "SkillButtonEUpgradeButton": 28, "SkillButtonQUpgradeButton": 30,
    "StatusIconDisplay": 31, "HintManager": 32, "MissionObjectiveTracker": 35,
    "SkillsBarUpgradeReccommendedText": 45,
}
HUD_EVENT_SHOW_HIGHLIGHT = 7
# Revealed at the first level-up: vitals, skills bar, the skill buttons and
# their separate UPGRADE buttons (in a tutorial every element starts hidden;
# the upgrade buttons are elements of their own: Q 30, W 4, E 28, R 5, passive 19).
SKILL_ELEMENTS = tuple(HUD[n] for n in (
    "PlayerVitalBars", "SkillsBar", "LevelAndExperience", "StatusIconDisplay",
    "SkillButtonBasic", "SkillButtonQ", "SkillButtonW", "SkillButtonE", "SkillButtonR", "SkillButtonPassive",
    "SkillButtonQUpgradeButton", "SkillButtonWUpgradeButton", "SkillButtonEUpgradeButton",
    "SkillButtonRUpgradeButton", "SkillButtonPassiveUpgradeButton",
    "SkillPointSpendReminder", "SkillsBarUpgradeReccommendedText"))
FIRST_SKILL_UPGRADE = HUD["SkillButtonQUpgradeButton"]   # highlighted: "unlock the first skill"

OBJECTIVE_CATEGORY_SHOW = 8
CATEGORY_TITLE = "A Champion in Peril"
FIRST_OBJECTIVE = ("<font color='#FFFF00'>Right-click</font> on the marked location to move there"
                   "<br>(Follow the arrows at your Champion's feet)")
INTRO_CONVERSATIONS = (0x1BA,)

HINT_GUIDE_ARROWS, HINT_BASIC_ATTACK, HINT_EXPERIENCE, HINT_SKILL_RANKS, HINT_SKILL_POINTS = 16, 17, 18, 21, 34

# Guide-ping targets per step (landblock 0x13,0xcb local x, y, z). Overridden by
# [tutorial] targets in config.toml. Both walk targets lie west of the first
# drone (35.3, 56.3, from the layout and cinematic 0x35000033), on the way from
# the spawn point; after the second one the drone appears and the guide arrows
# point at it (step DRONE_STEP). The originals' positions are not in the packs.
TARGETS = {1: (25.0, 60.3, 200.0), 2: (30.5, 59.0, 200.0)}
DRONE_STEP = 3
TARGET_RADIUS = 3.5
DRONE_TRIGGER_RADIUS = 7.0     # walking this close to the first drone's spot brings it out

# Pacing (2026-10-14, from the original's chat log timestamps): each beat is
# (seconds after the event, what). "conv" = conversation key, "hint" = tutorial
# hint, "objective" = new objective text, "ping" = next guide ping. All delays
# are multiplied by [tutorial] pacing (0 = everything at once, as before).
#   00:43 A narrow escape! / 00:46-00:50 We need to keep moving... fog of war
#   00:55 What ARE these accursed machines? / 00:58 A corrupted drone. Take it out!
OBJ_MOVE = "<font color='#FFFF00'>Right-click</font> to move to the marked location"
OBJ_DRONE = ("<font color='#FFFF00'>Right-click</font> the drone to "
             "<font color='#00FF00'>Basic Attack</font> and defeat it")
MOVE_STEPS = {
    # he is down from +1 s to +6 s: "A narrow escape!" when he is up again, the
    # next marker (drone_appear_delay) at +7 s
    1: ((6.2, "conv", 0x193), (9.2, "conv", 0x19C), (7.0, "objective", OBJ_MOVE),
        (7.0, "hint", HINT_GUIDE_ARROWS), (7.0, "ping", None)),
    2: ((0.0, "conv", 0x1AC), (3.0, "conv", 0x1B8), (3.0, "objective", OBJ_DRONE)),
}

PING_CLASS = 0x40000A9C                      # "Map Ping": guide arrows point at it
GUIDE_KEYS = (0x10000F80, 0x10000F86)        # Vfx_GuideArrow, Vfx_GuideArrow_Ping (Batman's table)
# type 1 = Alt+click (alert), 2 = Ctrl+click (retreat). 2026-10-14 14:14: with
# 1 -> 0x4000025A they showed swapped, so alert is 0x4000025B.
PLAYER_PING_CLASSES = {1: 0x4000025B, 2: 0x4000025A}

# ---- encounter layout (pack 0xa0000256, records 0x1d000771 / 0x1d0007ee) --------------
# name: (world state DID, (x, y, z) in landblock 0x13,0xcb, yaw radians)
# Extracted with `python ic.py layout 0xa0000256`; tests/test_layout.py checks
# that this table still matches the packs.
LAYOUT = {
    "03MeleeC": (0x2E001167, (35.34, 56.35, 199.95), 0.293),    # = "Drone_01" in cinematic 0x35000033
    "03MeleeD": (0x2E001167, (36.26, 57.69, 199.95), 1.584),
    "03MeleeA": (0x2E001167, (49.36, 49.34, 200.05), -1.835),
    "03MeleeB": (0x2E001167, (47.87, 46.76, 200.08), -1.905),
    "03RangedA": (0x2E001168, (46.58, 50.33, 199.93), -1.906),
    "03RangedB": (0x2E001168, (45.61, 48.59, 199.93), -2.073),
    "03ThugA": (0x2E0012BB, (44.22, 59.02, 199.99), 1.571),
    "03ThugB": (0x2E0012BB, (34.92, 57.60, 199.93), -1.529),
    "DestVehicle": (0x2E000AAB, (43.66, 52.61, 199.86), -2.512),
    "03GateA": (0x2E0010F3, (54.05, 44.80, 200.08), -2.042),
    "03GateB": (0x2E0010F3, (89.87, 26.21, 200.16), -2.042),
}
# World state -> character variant (pack 0xa0000257: the variant's twin record
# 0x49xxxxxx names the world state). A variant gets the game components
# (vitals, combat); a bare world state does not, and must never get event 0x42.
VARIANTS = {
    # The tutorial's own Soldier Drone variant 0x40000C72 can NOT be targeted by
    # the client (it never sent an attack order for it, 2026-10-13), while the
    # Trooper 0x40000A5D could. 0x40000A5C is the matching generic Soldier Drone.
    0x2E001167: 0x40000A5C,   # Soldier Drone (melee)
    0x2E0012BB: 0x40000C71,   # Stabber (thug)
    0x2E001298: 0x40000BA9,   # Target Drone (practice): rig 0x2D000F92 chr_minion_target_drone
    0x2E001168: 0x40000A5D,   # no variant names the tutorial's ranged drone: Trooper Drone stands in
    0x2E000AB5: 0x40000EB2,   # the Destroyer (02Destroyer / Destroyer of the layout), pack 0xA0000257
}
# Not in the layout: the practice targets after the first skill ("Construct:
# can we have some target drones?"). Their world state is 0x2E001298 (rig
# 0x2D000F92 = chr_minion_target_drone: small drone on a stand with a ring) and
# their entity 0x40000BA9 (twin 0x49000BA9, property 0x510). 0x2E000808, used
# before, is a generic soldier drone (rig 0x2D00068A, like 0x2E001167).
# Positions estimated from the original's screenshot (2026-10-14): up the
# street from the fight, left of the vehicle. Overridable: [tutorial] practice_positions.
TARGET_DRONE = 0x2E001298
# 14:30 (picture): the paddy wagon's model lies along its yaw + 90 degrees
# (the street's police wagon lies along its yaw). Spawns add this offset so a
# yaw always names the line the car covers (its walking box uses the same yaw).
MODEL_YAW_OFFSET = {0x2E00034D: -math.pi / 2, 0x2E00034E: -math.pi / 2}
EXTRA_SPAWNS = {
    "03TargetA": (TARGET_DRONE, (42.8, 59.6, 200.0), -0.5),
    "03TargetB": (TARGET_DRONE, (44.2, 57.3, 200.0), -0.5),
    # 2026-10-14 20:54 (dump "crater"): the crater the big meteor leaves is the
    # entity 0x400004FD (world state 0x2E0004BE, .entity 0x2D000375; "Crater1-3"
    # in another tutorial's placement list 0x1D0007E9). Its records are in packs
    # 0xA00000B3 / 0xA000024C, which the tutorial loads.
    "Crater": (0x400004FD, (19.6, 58.9, 200.0), 0.0),
    # 2026-10-15: three blue gates on the bridge (the original's video): the
    # layout has the first and the last (03GateA / 03GateB); the one in the
    # middle is placed on the line between them (bridge.py, [tutorial] bridge_gates)
    "03GateMid": (0x2E0010F3, (69.58, 36.74, 200.1), -2.042),
    # 2026-10-16 17:29: the falling meteors as entities (they fall, block the way
    # and go away; tutorial1.meteor, [tutorial] meteor_mode = "entity")
    "Meteor": (0x2E000BB3, (0.0, 0.0, 200.0), 0.0),
}
CRATER_WSTATE = 0x2E0004BE
# 2026-10-16 23:46 (tester: "like the animation tour, show one every 4 seconds and I
# note which ones are right"): [debug] model_tour = "candidates" shows these world
# states one by one in front of Batman, with "Model n/N 0x2E..." as the objective
# text. Tutorial 1's own pack 0xA000024C: everything a script, effect or spawn
# template of that pack names (not the map's fixed props), the craters and lava
# sets tried before; then the meteor event's pieces (pack 0xA000009A, only when
# it is loaded: MODEL_TOUR_EVENT_ONLY).
MODEL_TOUR_CANDIDATES = (
    0x2E000BB3, 0x2E00131C, 0x2E0002EC, 0x2E0007D4, 0x2E0004BE, 0x2E0004BD, 0x2E0004ED, 0x2E0006DE,
    0x2E001144, 0x2E001145, 0x2E001146, 0x2E0005D6, 0x2E000A9F,
    0x2E000F03, 0x2E000F04, 0x2E000F05, 0x2E000EFE,
    0x2E00061D, 0x2E00061E, 0x2E00061F, 0x2E000620, 0x2E000621, 0x2E000622, 0x2E000623,
    0x2E000800, 0x2E000821, 0x2E000296, 0x2E00070F, 0x2E001200, 0x2E000220, 0x2E000249, 0x2E000059,
    0x2E000755, 0x2E00025E, 0x2E000280, 0x2E00028F, 0x2E00030B, 0x2E000B53, 0x2E00026D,
    0x2E0000CA, 0x2E0000D2, 0x2E0000D3, 0x2E0000E5,
    0x2E0004E5, 0x2E0004E7, 0x2E0005F7, 0x2E0005FB, 0x2E0006DA, 0x2E00069E, 0x2E00069C,
)
# 2026-10-17 00:12 (tester): the game closed during the tour; the connection dropped
# 0.13 s after model 15 (0x2E000F04, templates 0x1D000612 + 0x1D00034B + 0x1D000111)
# was created. Never shown again; later crashes are added to logs/model_tour.json.
MODEL_TOUR_CRASHES = (0x2E000F04,)
# 01:08 (tester, 11 runs): the client closes ~3 s after these appear, bare or with their
# scripts, with nothing else sent in between (the guide was off in the last run). Not
# always (0x2E000620-623 passed once while 0x2E000621 / 622 closed it in other runs), so
# every model that closed the game at least once is skipped in both modes.
MODEL_TOUR_CRASHES_BARE = (0x2E000F03, 0x2E000F04, 0x2E000F05, 0x2E000EFE, 0x2E00061D, 0x2E00061F,
                           0x2E000621, 0x2E000622, 0x2E000296,
                           # 2026-10-17 16:54 (tester, lab fase3-hx): the meteor set piece closed the
                           # game 4.5 s after it appeared (key Vfx_Active_State0 0.3 s in)
                           0x2E000877,
                           # 17:02 (tester): its sibling 0x2E000872 closed it too (3.4 s); the whole family
                           # (same templates 0x1D00025E-0x1D000261, property 0x800) is left out
                           0x2E000872, 0x2E000873, 0x2E000874, 0x2E000875, 0x2E000876)
MODEL_TOUR_EVENT_ONLY = (0x2E0004E5, 0x2E0004E7, 0x2E0005F7, 0x2E0005FB, 0x2E0006DA, 0x2E00069E, 0x2E00069C)


# 2026-10-17 09:31 (tester: "prepare it", the lab of fase3-ha): the meteor family and
# Tutorial 2's own pieces from catalog/data/world_states.tsv, all in the packs Tutorial 2's
# lab loads (0xA00002E5 + 0xA000009A, 0xA00000B3). Each one is shown bare and then with its
# scriptlet templates (labels "n/N a" / "n/N b"); the event object 0x2E00069E (the whole
# meteor event template 0x1D00019C) comes last.
LAB_CANDIDATES = (
    0x2E0004E5,   # vfx_env_event_meteor_warning
    0x2E0004E7,   # the "explosion": own mesh, graph set 0x1C000029 (impact graph 0x1A00021F?)
    0x2E0004ED,   # vfx_env_event_meteor_shockwave
    0x2E0006DE,   # vfx_env_event_meteor_shockwave (pack B3)
    0x2E0007D4,   # vfx_env_event_meteor_dust_cloud + dust ring
    0x2E0005F7,   # env_event_meteor_a (rock)
    0x2E000BB3,   # env_event_meteor_a (rock, Tutorial 1's)
    0x2E0006DA,   # 8 of them in the event template
    0x2E0005FB, 0x2E00069C,
    0x2E0004BE,   # Crater1 / Crater3, 14 particles of its own
    0x2E0004BD,
    0x2E000928,   # stp_meteor (the Stolen Power's meteor, for comparison)
    0x2E001157,   # env_pvp_phase_pod (Tutorial 2's pod)
    0x2E000A9F,   # TurretBasePlate (Tutorial 2's layout)
    0x2E00069E,   # the meteor event object (template 0x1D00019C): the whole event
)


# 2026-10-17 10:37 (tester): the falling sphere that opens and shows the Destroyer is still
# missing, and the meteors may be the Stolen Power "Meteor Drop" (stp_meteor). Second lab
# list ([debug] lab_tour = "sphere", the default now): models without template keys are shown
# once with their templates and graph ("graph").
LAB_SPHERE = (
    0x2E000928,   # stp_meteor: the Stolen Power Meteor Drop's rock (graph 0x1C000053: spawn, spin)
    0x2E000AC5,   # PowerCore, the sphere Tutorial 1 uses now (templates 0x1D000360 + 0x1D000385)
    0x2E000E38,   # env_pvp_drop_pod_a (bodies A-E; graph 0x1C0000AA, explode_a)
    0x2E000FAB,   # env_pvp_drop_pod_a_emitter
    0x2E00103B,   # env_pvp_alien_base_iris (an iris that opens)
    0x2E001157,   # env_pvp_phase_pod (door, plates): the Destroyer's crater ring
)


# 2026-10-17 16:24 (original video: fire columns come down at 3:36.7 and 5:11.8, then a grey dust
# dome): candidates for the fire column, from pack 0xA000009A. The meteor event object 0x2E00069E
# names Vfx_Spawn_Event05 0x1000092F right after its 0x78 property (never run on the object itself;
# it was rejected on the warning anchor). 0x2E000872-0x2E000877 (templates 0x1D00025E-0x1D000261)
# are timed set pieces: 0x2E000877's record spawns five meteor event objects (scale 0.25) with
# particles 0x18000318 / 319 / 321 and the "Destruction" sound bank. [debug] lab_tour = "start".
LAB_START = (
    0x2E00069E,   # the meteor event object (template 0x1D00019C)
    0x2E000877,   # set piece: five meteor events, particles 0x18000318-0x18000321
    0x2E000872, 0x2E000873, 0x2E000874, 0x2E000875, 0x2E000876,
)
# Keys run one by one in the lab for models whose templates list none (lab_modes "keys")
LAB_EXTRA_KEYS = {
    0x2E00069E: (0x1000092F, 0x10000032, 0x1000005D),
    0x2E000877: (0x1000005D, 0x1000006B, 0x10000413, 0x10000032),
    0x2E000872: (0x1000005D, 0x1000006B), 0x2E000873: (0x1000005D, 0x1000006B),
    0x2E000874: (0x1000005D, 0x1000006B), 0x2E000875: (0x1000005D, 0x1000006B),
    0x2E000876: (0x1000005D, 0x1000006B),
}


def lab_config(match):
    """[match] maps entry of the match's encounter when it has "lab" on (Tutorial 2)."""
    mc = getattr(match, "map_cfg", None) or {}
    return mc if mc.get("lab") else None


def _tour_state(cfg, state=None):
    """logs/model_tour.json: the last model shown and the ones that closed the game."""
    import json
    import os
    path = os.path.join(cfg.log_dir, "model_tour.json")
    if state is None:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass
    return state


def model_tour_list(cfg, raw=None):
    """The world states of [debug] model_tour (or raw): "candidates", "lab", "pack:0xA000024C"
    (every world state of that pack, in id order) or a list of ids."""
    import os
    if raw is None:
        raw = cfg["debug"].get("model_tour") or []
    if not raw:
        return []
    if raw == "candidates":
        return list(MODEL_TOUR_CANDIDATES)
    if raw == "lab":
        return list(LAB_CANDIDATES)
    if raw == "sphere":
        return list(LAB_SPHERE)
    if raw == "start":
        return list(LAB_START)
    if isinstance(raw, str) and raw.startswith("pack:"):
        from . import gamedata
        name = f"{int(raw[5:], 16):#010x}.rp"
        path = os.path.join(cfg.game_dir, "rp", name)
        try:
            _n, ids = gamedata.pack_header(path)
        except OSError:
            return []
        return sorted(i for i in ids if i >> 24 == 0x2E)
    return [int(str(v), 0) for v in raw]
# 2026-10-16 22:47: the meteor event's own crater and shockwaves (pack 0xA000009A;
# tutorial1._event_crater): (world state, seconds, scale)
EVENT_CRATER = 0x2E0004E7
EVENT_SHOCKWAVES = ((0x2E0004ED, 5.0, 1.0), (0x2E0006DE, 1.0, 1.0))
SPARKS_WSTATE = 0x2E0006DA
STP_METEOR_WSTATE = 0x2E000928           # the Stolen Power Meteor Drop's rock (tester 10:53)
SPARKS_KEYS = (0x1000018E, 0x10000032, 0x10000078)
LAVA_CRATER_WSTATES = (0x2E001144, 0x2E001145, 0x2E001146)
# [debug] tour_keys = "core" (old spelling "nucleo" also accepted): the actions
# that matter for Batman's kit and the combat engine (00:50: the full tour is
# mostly shared effects of every champion).
TOUR_CORE = (
    (0x10000164, "Q Sonic Batarang (full skill)"), (0x10000163, "W Sonic Shell"),
    (0x10000165, "E Bat Flight"), (0x10000162, "R The Bat Scream"),
    (0x10000195, "basic attack right"), (0x10000196, "basic attack left"),
    (0x10000188, "shot effect right"), (0x10000189, "shot effect left"),
    (0x1000017e, "critical effect"), (0x10000209, "hit reaction"),
    (0x1000003d, "CbtState_KnockUp (knocked into the air)"), (0x100001f9, "_Defeat_StartupIncapacitated"),
    (0x100001fb, "_Defeat_OnIncapacitated"), (0x10000490, "RunScript_Vfx_GetUp (get up)"),
    (0x100001fa, "_Defeat_OnDead (death)"), (0x100001fc, "_Defeat_OnRespawn (respawn)"),
    (0x100001fd, "_Defeat_OnRevive"), (0x10000999, "stunned (effect)"),
    (0x10000201, "level up"), (0x10000181, "Vfx_Bmg_Spawn (appear)"),
    (0x100009fb, "teleport"), (0x100001d3, "emote laugh"), (0x10000641, "emote dance"),
    (0x10000643, "emote joke"), (0x1000115e, "emote oath"),
)
CRATER_EXTRAS = ()   # 00:08: 0x2E0005D6 showed as a grey square: no extras
# the map's copy sits ~(-1.7, +1.4) m from what it shows: same spot on screen as
# the old crater (accepted at 23:07)
LAVA_CRATER_AT = (19.5, 63.0)
# 2026-10-14 21:44 (diag --create): the crater object builds like the rocks, but its
# .entity 0x2D000375 (in pack 0xA000024C) is only a one-bone skeleton without a
# mesh: what shows must come from its scripts (VFX/decals). Probes: Vfx_Startup,
# Vfx_Spawn_Alt01, Vfx_Event1, _Entity_OnEnterWorld_Default (diag --scripts lists
# the crater's own table).
CRATER_KEYS = (0x1000018E, 0x10000347, 0x10000076, 0x100002F5)
# 2026-10-14 22:14: entity 0x400004FD loads but has no scriptlets either (0 groups),
# so the lava is not a script. Tutorial 1's own pack has the crater's spawn
# template 0x1D0008B6 (entity 0x400004FD, world state 0x2E0004BE) with these
# properties. 22:21: sent with the crater it no longer showed (and the player's
# pings stopped reaching the minimap): off by default ([tutorial] crater_props =
# "template" sends them, or a list of [id, kind, value]).
CRATER_PROPS = ((0x10000AA7, "int", 1), (0x8B2, "int", 8), (0x8A5, "f32", 5.0), (0x8A3, "f32", 3.0),
                (0x83C, "int", 1), (0x8C1, "int", 1), (0x1000019D, "int", 0x2000), (0x149, "u32", 0x08000000))
_PROP_KINDS = {"int": KIND_INT, "f32": KIND_F32, "u32": 0x13, "bool": KIND_BOOL, "did": KIND_DID, "enum": KIND_ENUM}
STATIC_SCENERY = ("Crater",)      # entities that are part of the ground: never hidden by the fog
FIRST_DRONE = "03MeleeC"
THUG = "03ThugB"          # the human fighting the first drone; runs away when Batman attacks
THUG_FLEE_TO = (24.0, 64.0, 200.0)
CATWOMAN_CINEMATIC = 0x35000034   # Catwoman breaks the vehicle blocking the street
# How long the client takes to speak a conversation (text length; the voice
# files are not read): ~2.6 words/s + 0.8 s per line. 0x19A: "When you use a
# skill, it goes 'on cooldown'." + "After the timer ends, you can use it again."
# 0x1E3: "Using that skill also consumed 'Will', a resource Gaslight Batman
# recovers over time."
CONV_SECONDS = {0x1BA: 5.1, 0x193: 3.1, 0x19C: 11.5, 0x1AC: 3.0, 0x1B8: 3.1, 0x1E1: 4.6, 0x1E0: 4.7,
                0x38C: 6.6, 0x1DF: 1.6, 0x1D4: 5.3, 0x1BE: 4.9, 0x19B: 6.4, 0x1AB: 3.7, 0x1B7: 9.7,
                0x19A: 8.8, 0x1E3: 5.8,
                # the Bat Scream part (estimates from the line lengths)
                0x1A0: 5.0, 0x1C8: 3.2, 0x1B6: 3.0, 0x1B0: 3.0, 0x1CA: 5.5, 0x1B5: 5.0, 0x1D8: 9.5,
                0x1D0: 3.0, 0x3AC: 5.5, 0x1A5: 7.5, 0x1AD: 3.2, 0x1A8: 5.0, 0x19F: 3.0}
# The client queues conversations: one sent while another is being spoken waits
# for it (2026-10-14: after a quick Batarang, 0x1B7, 0x19A and 0x1E3 were still
# queued when the cinematic started). speech_end tracks when the queue empties.
# The cinematic has its own "Gaslight_Batman" actor here (pack 0xa0000256);
# the player's Batman is not hidden, so he is moved onto it beforehand.
CATWOMAN_CINEMATIC_BATMAN = ((40.687, 58.229, 199.985), 2 * math.atan2(-0.9724, 0.2333))
# Meteor impacts: world state 0x2E0007D4 (pack 0xa0000256) carries the
# vfx_env_event_meteor_dust_cloud rig (0x2D000656) and script table 0x1D00020B.
# ("PowerCore" 0x2E000AC5 was wrong: its scripts are Vfx_Relay_*, a relay/turret.)
# 2026-10-14 20:30 (dump): 0x2E0007D4 (.entity 0x2D000656) is only the impact's
# DUST CLOUD (vfx_env_event_meteor_dust_cloud_rig: the "grey columns"). The rock
# is 0x2E000BB3 (.entity 0x2D00048D, env_event_meteor_a_rig: Root / Meteor /
# Meteor_cap), present in pack 0xA000024C, the one the tutorial already loads.
METEOR_CLASS = 0x2E000BB3
METEOR_DUST_CLASS = 0x2E0007D4
# 2026-10-16 17:59: the game's meteor effect (rock + dust + mse_Meteor sounds)
METEOR_EFFECT_WSTATE = 0x2E0002EC
# 2026-10-16 19:20 (tester: "si intentalo"): the meteor event itself, script
# template 0x1D00019C of pack 0xA000009A (loaded only with the exe's two-zone-
# slot patch, [match] event_packs). Its scriptlet map (property 0x78) has one
# key, 0x1000092F, whose tracks create (action 0xc) the ground warning
# 0x2E0004E5, the rock 0x2E0005F7 / 0x2E000BB3, 8 pieces 0x2E0006DA around the
# spot, 0x2E0004E7 / 0x2E0004ED / 0x2E0006DE, the dust 0x2E0007D4, and play
# (action 0x2C) the mse_Meteor sounds. Run on an anchor prop (generic effect
# world state 0x2E000013) that carries the template as its 0x7D2.
METEOR_EVENT_PACK = 0xA000009A
METEOR_EVENT_TABLE = 0x1D00019C
METEOR_EVENT_KEY = 0x1000092F
METEOR_EVENT_ANCHOR = 0x2E000013
# 20:08 (tester + diag): both zone packs loaded, but 0x1000092F was rejected
# (0x80070057): the anchor's table allowed only 0x5 (1 group = the template).
# 0x5 is now tried as the template's entry. 0x2E000013's .entity 0x2D000063
# showed as a WATER JET ("chorros de agua"): the anchor is now the event's own
# ground warning 0x2E0004E5.
METEOR_EVENT_KEYS = (0x5,)
METEOR_EVENT_WARNING = 0x2E0004E5
# 20:33 (tester: "the same"; diag: 0x5 accepted, nothing seen). The template
# is an HFSM (states, signals 0x1000087B/7C/7F/926/927, waits, damage areas
# with skills 0x480007FC/FD, particles 0x1800024B / 0x18000E6A / 0x180002D1)
# that creates its pieces one by one: 8 x 0x2E0006DA in a ring (own template
# 0x1D0001BC, started with 0x10000078), the warning 0x2E0004E5 (own 0x1D000114
# + graph 0x1C000028), the rock 0x2E0005F7 (started with 0x10000032), dust
# 0x2E0007D4 (0x1000018E). The server now places those pieces itself, with
# their own templates. One probe per meteor, in fall order, so one
# run tells which one shows the real thing ([tutorial] meteor_event_probes):
# each probe = steps [delay s, world state, [keys], dx, dy, dz, lifetime s].
METEOR_EVENT_PROBES = (
    # 1st small one: a ring piece 0x2E0006DA with its start key
    ((0.0, 0x2E0006DA, (0x1000092F, 0x10000078, 0x5), 0, 0, 0, 12.0),),
    # 2nd: the ground warning with its own scripts, the rock 1.5 s later (rock key)
    ((0.0, 0x2E0004E5, (0x1000018E, 0x10000078, 0x5), 0, 0, 0, 3.0),
     (1.5, 0x2E0005F7, (0x10000032, 0x1000018E), 0, 0, 0, 10.0)),
    # 3rd: the tutorial pack's rock with the rock key, and the dust
    ((0.0, 0x2E000BB3, (0x10000032, 0x1000018E), 0, 0, 0, 10.0),
     (0.3, 0x2E0007D4, (0x1000018E,), 0, 0, 0, 4.0)),
)
METEOR_EFFECT_SCRIPT = 0x170001C4
# 18:54 (tester's video frames): the small meteors at the start are small burning
# pieces: env_event_meteor_fragment (world state 0x2E00131C, .entity 0x2D00044D,
# graph 0x1A0002BA; its .entity plays sound 0x4875B851 of bank Destruction,
# which Tutorial 1's pack declares). Pack 0xA000024C.
METEOR_FRAGMENT = 0x2E00131C
PROP_OBJECT_BASE_ID = 0x0200000000001000     # meteors, craters, blasts: + n
# 2026-10-14 16:15 (screenshot): the 3 small meteors land right around Batman's
# start (18.7, 60.4) and stay until he gets up after the big one; the big one
# opens a crack behind him at the first marker and stays.
# 2026-10-16 22:22 (tester's three pings, in falling order)
SMALL_METEORS = ((21.4, 56.6, 200.0), (20.2, 63.4, 200.0), (21.5, 60.5, 200.0))
SMALL_METEORS_OLD = ((20.6, 60.0, 200.0), (20.8, 57.6, 200.0), (17.6, 57.2, 200.0))
WAVE_METEOR = (24.0, 66.0, 200.0)
# 2026-10-14 22:00 (screenshot vs video): at (19.6, 58.9) the crater showed ~6 m
# to the right of where the video has it (x = screen right, y = screen down)
# 22:14: at (13.5, 60.0) it was too far left; the video has it ~3.5 m further on
# 22:28: a bit closer to the street lamp (video)
# 22:35: the extra 0x2E000A9F was a turret base plate, centred on the object's
# origin: the camera turns the map (+x = screen up-right, +y = screen up-left,
# ~53 px/m) and the crater's mesh sits ~(3.2, 0.3) m off its origin. Against
# the lamp (~(18.2, 66.0)) the video's crater needs its origin at ~(15.7, 60.3).
# 22:57: still ~(+2.3, +1.0) m off against the lamp in the video
BIG_METEOR = (18.0, 61.3, 200.0)
METEOR_LIFETIME = 8.0
# 2026-10-14 16:30: 0x10000209 (_HFSM_TargetHitAction_PhysicalReaction) is only a
# flinch. CbtState_KnockUp (0x1000003D, in Batman's scriptlet table) throws him
# up and down; then he gets up ([tutorial] knockdown_keys).
VEHICLE_SPOT = (43.66, 52.61, 200.0)        # the street vehicle (DestVehicle) on the ground
KNOCKDOWN_KEYS = (0x100001FB,)            # _Defeat_OnIncapacitated (seen 01:15)
GETUP_KEYS = (0x100001FD, 0x10000490)     # _Defeat_OnRevive + RunScript_Vfx_GetUp
# graph events (name table 0x300000A4) for the face-down knockdown (knockdown())
KNOCKDOWN_EVENTS = (0x100002F5,)          # CbtState_Knockdown
KNOCKDOWN_SNAP_EVENTS = (0x1000010B,)     # CbtState_Dead: the frozen face-down pose
GETUP_EVENTS = (0x1000009D,)              # CbtState_GetUp (Knockup_Selection 0 = face down)
GETUP_FX_KEYS = (0x10000490,)             # RunScript_Vfx_GetUp
RAISE_EVENT_KEY, RAISE_EVENT_VAR = 0x100001E3, 0x780   # _HFSM_BehaviorRaiseEventAction, event variable
# Probes sent to a new meteor / the vehicle so `diag.py --scripts` lists their
# script tables: _Entity_OnEnterWorld_Default, Destructible_AdvanceState.
# The meteor's own table (diag 2026-10-13): Vfx_Startup, Vfx_Spawn_Alt01, Vfx_Event1.
METEOR_PROBE_KEYS = (0x1000018E, 0x10000347, 0x10000076)
VEHICLE_PROBE_KEYS = (0x10000063,)
VEHICLE_BREAK_KEYS = (0x10000063,)     # Destructible_AdvanceState: intact -> damaged -> wreck
VEHICLE_HIT_RADIUS = 4.5               # m from the vehicle's centre: a Q thrown there hits it
# While the player does not attack, the first drone fights the human: its melee
# attack (0x100000EC, "Vfx_Min_Basic_Melee"/"Combat_Special_Attack_1", in the
# drones' script table) every FIGHT_INTERVAL s, and the human reacts.
DRONE_FIGHT_KEYS = (0x100000EC,)
THUG_HIT_KEYS = (0x10000209,)
# The human swings back half a beat later (0x10000124 is in his table too) and
# the drone flinches ([tutorial] thug_attack_keys, [] = he only takes hits).
THUG_ATTACK_KEYS = (0x10000124,)
DRONE_HIT_KEYS = (0x10000209,)
# 22:57: the human stood side-on to the drone. His model faces +x at yaw 0
# (the layout's -1.529 points at the drone), the drones' +y: [tutorial] thug_yaw_offset.
# 23:07: with +pi/2 he had his back to the drone: -pi/2. 23:15: almost facing
# it, still ~30 degrees short (he looks straight down the screen, the drone is
# down-right): -pi/2 + 0.52
# 00:00: the video has him side-on to the drone while they fight (a batter's
# stance): his original spot and facing were right. No turn, no shift.
THUG_SHIFT = (0.0, 0.0)
THUG_YAW_OFFSET = 0.0
FIGHT_INTERVAL = 1.4    # _HFSM_TargetHitAction_PhysicalReaction on Batman
WAVE = ("03MeleeA", "03MeleeB")   # "2 new drones hit the vehicle blocking the street"
# The layout puts them past the vehicle (x 48-49, by the first blue door); in the
# game they hit it from Batman's side (2026-10-14). Overridable: [tutorial] wave_positions.
# Drones fight back (2026-10-14: "the drones should attack me and hurt me").
# A drone turns aggressive when Batman attacks it (the wave also when he comes
# close); it walks up to him and hits with its melee script.
DRONE_AGGRO_RADIUS = 0.0     # 0 = only the drone Batman attacks turns on him (2026-10-14 11:50: "as
                             # before: they appear hitting the vehicle and the one I attack attacks me";
                             # 6 m made the wave charge at once). Earlier: they
                             # attacked by themselves from far away)
DRONE_LEASH = 8.0            # an aggressive drone farther than this from Batman calms down
DRONE_ATTACK_RANGE = 2.2
RANGED_ATTACK_RANGE = 6.0    # the ranged drones (Trooper) shoot from here
DRONE_ATTACK_INTERVAL = 1.6
DRONE_DAMAGE = 6          # halved 2026-10-14 ("a bit high")
DRONE_WALK_SPEED = 1.6      # m/s ([tutorial] drone_walk_speed); 3.0 looked like sliding
DRONE_TICK = 0.25           # s between AI updates (smaller steps = smoother walk)
DRONE_SPAWN_KEYS = (0x10000032, 0x10000033)    # Vfx_Spawn + Vfx_Fade_In: they "teleport in"
# (delay s, script key): the teleport-in, spread out (2026-10-14: "too fast").
# Overridable: [tutorial] spawn_sequence = [[0.1, 0x10000032], ...]
SPAWN_SEQUENCE = ((0.1, 0x10000032), (0.9, 0x10000033), (1.6, 0x10000033))
# Attack scripts tried in turn, one per hit, logged with the key so the one that
# shows the swing can be kept ([tutorial] drone_attack_keys). 0x100000EC alone
# showed nothing (2026-10-14).
# 2026-10-14: the old keys came from the wrong name table (animnames); the
# scriptlet keys are the anim-event ids (animevents): Robot_Minion_Melee_Attack
# 0x10000124, Combat_Basic_Attack 0x10000128, Vfx_Min_Basic_Melee 0x100000EC,
# Vfx_Min_Basic_Melee_Active 0x10000008. Each entry = the scripts of one swing
# (animation + effect, like Batman's basic attack: Combat_Basic_Attack_Right +
# Vfx_Bmg_Basic_Ranged_Right).
# 2026-10-14 21:52 (diag --scripts): the drone's table rejects 0x10000128 and
# 0x10000008 (0x80070057): only the first swing played, the others did nothing.
DRONE_ATTACK_KEYS = ((0x10000124, 0x100000EC),)
# Skill ranks for the HUD: the patched client reads them from this champion
# property (int, 4 bits per skill slot; slot 1 = Q). See patcher.py.
SKILL_RANKS_PROPERTY = 0x100006C1
# Sonic Batarang (Q). Batman: Batman_Gaslight_Sonic_Batarang (0x10000164, in his
# script table) with the target as script variable 0x108; each drone it reaches:
# VFX_CBT_Hit_Shared + physical reaction. It ricochets to the nearest other
# enemy within BATARANG_RICOCHET_RANGE, BATARANG_BOUNCES times at most.
# 0x100000EB is Vfx_Active (not Combat_Special_Attack_2: that came from the wrong
# name table). Batman_Gaslight_Sonic_Batarang + Vfx_Bmg_Batarang (the projectile),
# Vfx_Bmg_Batarang_Stop when it is over.
BATARANG_CAST_KEYS = (0x10000164, 0x10000171)
BATARANG_STOP_KEYS = (0x1000017B,)
BATARANG_COOLDOWN = 2.0        # s: the client repeats Q while it is held (4 orders in 0.5 s)
BATARANG_HIT_KEYS = (0x10000223, 0x10000209)
BATARANG_DAMAGE = 200
BATARANG_RICOCHET_RANGE = 8.0
BATARANG_BOUNCES = 2
BATARANG_FLIGHT = 0.45         # s until it reaches the first target
BATARANG_HOP = 0.3             # s per ricochet
# The client's real skill ranks (GetSkillRank rva 0x463ce0): champion property
# 0x100000AF (kind 0xC, array) indexed by slot 1-5 (a slot's own index
# property 0x10000A16 is absent for Gaslight Batman), int elements. Any int
# property id types the elements; Level's is used.
RANK_ARRAY_PROPERTY = 0x100000AF
RANK_ELEMENT_PROPERTY = 0x10000167
Q_SLOT = 1          # the client's skill slot index of Q (its "+" queries slot 1)


def set_recommended(ranks, slot):
    """SKILL_RANKS_PROPERTY: bits 0-27 = rank per slot (4 bits each, slots 0-6),
    bits 28-31 = recommended slot + 1 (0 = none)."""
    return (ranks & 0x0FFFFFFF) | ((slot + 1) << 28 if slot is not None else 0)
BATMAN_HIT_KEYS = (0x10000223,)                # VFX_CBT_Hit_Shared on Batman
# along the vehicle's square-side flank, 2.2 m from its long axis (2026-10-14
# 16:22: MeleeB at (40.6, 52.6) stood apart from the vehicle)
WAVE_POSITIONS = {"03MeleeA": (43.6, 55.3, 200.0), "03MeleeB": (41.2, 53.5, 200.0)}
SCENERY = ("DestVehicle", "03GateA", "03GateMid", "03GateB")
# Props are entities 0x40xxxxxx whose twin 0x49xxxxxx names the world state
# (property 0x510). Creating the bare world state gives an object with scripts
# but no model (2026-10-14: vehicle, gates and meteors invisible although all
# their records are in loaded packs). Filled at server start by
# resolve_prop_classes() from the packs below; the Door is known already.
PROP_CLASSES = {0x2E0010F3: 0x40000B0F}
# Class 0x4A-0x4F + the low 24 bits of a world state = "carrier entity N
# (N = prefix - 0x4A, table in the patched exe: [combat] prop_carriers) built
# with world state 0x2Exxxxxx" (patcher.py, props). For world states that no
# entity names (vehicle, meteors).
PROP_OVERRIDE_BASE = 0x4A


def prop_class(wstate, cfg, slot=None):
    """Class id to send for a prop world state."""
    if wstate in PROP_CLASSES:
        return PROP_CLASSES[wstate]
    if cfg["combat"].get("prop_override", True):
        slot = int(cfg["combat"].get("prop_carrier_slot", 0) if slot is None else slot) % 6
        return ((PROP_OVERRIDE_BASE + slot) << 24) | (wstate & 0x00FFFFFF)
    return wstate


def is_override_class(class_id):
    return PROP_OVERRIDE_BASE <= class_id >> 24 <= PROP_OVERRIDE_BASE + 5
WSTATE_PROPERTY = 0x510         # an entity's world state (twin 0x49 records)
# 17:36 (static analysis): a client object's allowed-scriptlet list is built,
# once, from its property 0x7D2 (a list of 0x1D script templates, element key
# 0x462) when its script component starts (0x57B860 -> 0x58EDD0). A prop built
# on a carrier never gets its world state's 0x7D2 ("0 groups" in diag
# --scripts), so every scriptlet on it was rejected. Sent with the object:
# world state -> (script template, behavior graph)  ([combat] prop_script_tables)
SCRIPT_TABLE_PROPERTY, SCRIPT_TABLE_ELEMENT = 0x7D2, 0x462
WSTATE_SCRIPT_TABLES = {
    0x2E00034D: (0x1D0000BB, 0x1C000021),     # 02PaddyWagonA
    0x2E00034E: (0x1D0000BA, 0x1C000021),     # 02PaddyWagonB
}


# fase3-hd (2026-10-17 09:59, tester: model 2b, the explosion with its graph set, looked right;
# "let's look at the particles"): for the lab, each world state's graph read raw from its
# record (0x5B5 often sits after a vector property) and the scriptlet keys of its templates,
# in the order the template lists them, with the particle effects (0x18) each one names.
# Filled by resolve_script_tables at server start.
LAB_GRAPHS = {}          # world state -> graph (0x1A / 0x1C)
TEMPLATE_KEYS = {}       # template 0x1D -> [(key, (particles...)), ...]


def template_keys(data, did):
    """Scriptlet keys of a template record (0x1D): "key | 0 | n actions | prop | prop" runs,
    each with the particle effects (0x18) that follow it. Unique keys, first-seen order."""
    k = data.find(struct.pack("<II", did, 0x7EB))
    if k < 0:
        return []
    nxt = data.find(b"\xeb\x07\x00\x00\xeb\x07\x00\x00", k + 8)
    end = min(k + 40000, nxt - 4 if nxt > 0 else k + 40000)
    v = struct.unpack_from("<%dI" % ((end - k) // 4), data, k)
    out = {}
    cur = None
    for i in range(len(v) - 4):
        if v[i] >> 24 == 0x10 and v[i + 1] == 0 and 1 <= v[i + 2] <= 30 and v[i + 3] < 0x2000 \
                and v[i + 3] == v[i + 4]:
            cur = v[i]
            out.setdefault(cur, [])
        elif cur is not None and v[i] >> 24 == 0x18 and v[i] & 0xFFFF0000 == 0x18000000 and v[i] not in out[cur]:
            out[cur].append(v[i])
    return [(key, tuple(ps)) for key, ps in out.items()]


def script_table_props(wstate, cfg, raw_graph=False):
    """Extra properties giving a carrier-built prop its world state's scriptlets.
    raw_graph: also its graph read raw from the record (the lab, LAB_GRAPHS)."""
    from .wire import KIND_ARRAY
    tables = dict(WSTATE_SCRIPT_TABLES)
    for key, value in (cfg["combat"].get("prop_script_table_map") or {}).items():
        tables[int(str(key), 16)] = tuple(int(v) for v in value)
    if not cfg["combat"].get("prop_script_tables", True):
        return []
    if wstate not in tables:
        # 10:37: a model without templates (stp_meteor) still gets its graph in the lab
        graph = LAB_GRAPHS.get(wstate, 0) if raw_graph else 0
        return [(0x5B5, KIND_DID, graph)] if graph else []
    table, behavior = tables[wstate]
    if raw_graph and not behavior:
        behavior = LAB_GRAPHS.get(wstate, 0)
    templates = table if isinstance(table, (tuple, list)) else (table,)
    props = [(SCRIPT_TABLE_PROPERTY, KIND_ARRAY, [(SCRIPT_TABLE_ELEMENT, KIND_DID, t) for t in templates])]
    if behavior:
        props.append((0x5B5, KIND_DID, behavior))
    return props
PROP_PACKS = (0xA000024C, 0xA0000256, 0xA0000257)
# 14:54 (diag --scripts): the paddy wagon on its carrier (entity 0x40000B0F)
# has an empty scriptlet table; its own entity, if a pack has one, is used
PROP_WSTATES = (0x2E000AAB, METEOR_CLASS, 0x2E0010F3, 0x2E00034D, 0x2E00034E)


def resolve_prop_classes(cfg, log=None):
    """Look up the entity class of each prop world state in the game's packs
    (a few seconds; run in a background thread at server start)."""
    import os
    from . import rp
    if not cfg["combat"].get("prop_entities", True):
        PROP_CLASSES.clear()
        return {}
    for key, value in (cfg["combat"].get("prop_classes") or {}).items():
        PROP_CLASSES[int(str(key), 16)] = int(value)
    packs = rp.PackSet(os.path.join(cfg.game_dir, "rp"))
    missing = [w for w in PROP_WSTATES if w not in (cfg["combat"].get("prop_classes") or {})]
    for pack_id in PROP_PACKS:
        if not missing:
            break
        try:
            found = rp.entity_classes_for(packs.pack(pack_id), missing)
        except (OSError, ValueError) as e:
            if log:
                log(f"props: could not read pack {pack_id:#x}: {e}")
            continue
        PROP_CLASSES.update(found)
        missing = [w for w in missing if w not in found]
    if log:
        log("props: " + ", ".join(f"{w:#x} -> {PROP_CLASSES[w]:#x}" if w in PROP_CLASSES else f"{w:#x} -> (no entity)"
                                  for w in PROP_WSTATES))
    resolve_script_tables(cfg, log)
    return dict(PROP_CLASSES)


# world states the server builds on a carrier: their scriptlet templates are read
# from their own records at server start (resolve_script_tables)
TABLE_WSTATES = (0x2E00034D, 0x2E00034E, 0x2E000AAB, 0x2E000AC5, METEOR_CLASS, METEOR_DUST_CLASS, 0x2E0010F4,
                 # 20:33 (fase3-gj): the meteor event's objects (pack 0xA000009A)
                 0x2E0006DA, 0x2E0004E5, 0x2E0005F7,
                 # 2026-10-16 22:47 (fase3-gs): the event's crater 0x2E0004E7 and its two
                 # shockwaves 0x2E0004ED / 0x2E0006DE (templates 0x1D000115 / 124 / 1BD)
                 0x2E0004E7, 0x2E0004ED, 0x2E0006DE)


def _resolve_lab(cfg, rp_dir, log=None):
    """LAB_GRAPHS and TEMPLATE_KEYS for the lab's models (cached in data/game_cache.json)."""
    import os
    from . import gamedata, gamecache
    lab_ids = tuple(LAB_CANDIDATES) + tuple(w for w in LAB_SPHERE if w not in LAB_CANDIDATES)
    lab_ids += tuple(w for w in LAB_START if w not in lab_ids)       # 2026-10-17 16:24
    key = "lab_keys_v2_%x" % (sum(lab_ids) & 0xFFFFFF)
    cached = gamecache.get(rp_dir, key)
    if cached is None:
        cached = {"graphs": {}, "keys": {}}
        try:
            game = gamedata.Game(rp_dir, os.path.join(cfg.log_dir, "props.txt"))
            idx = game.index()
            for ws in lab_ids:
                raw = game.world_state_raw(ws)
                for i in range(20, len(raw) - 11, 4):
                    k1, k2, v = struct.unpack_from("<III", raw, i)
                    if k1 == k2 == 0x5B5 and v >> 24 in (0x1A, 0x1C):
                        cached["graphs"][str(ws)] = v
                        break
                rec = game.world_state(ws, partial=True)
                tables = [v for _k, _kind, v in (gamedata.get(rec[1], SCRIPT_TABLE_PROPERTY) or [])
                          if isinstance(v, int)] if rec else []
                for t in tables:
                    if str(t) in cached["keys"] or t not in idx:
                        continue
                    data = game.packs.pack(idx[t]).data
                    cached["keys"][str(t)] = [[k, list(ps)] for k, ps in template_keys(data, t)]
            gamecache.put(rp_dir, key, cached)
        except Exception as e:             # never stop the server for this
            if log:
                log(f"lab keys: {e!r}")
            return
    LAB_GRAPHS.update({int(k): int(v) for k, v in cached["graphs"].items()})
    TEMPLATE_KEYS.update({int(t): [(int(k), tuple(ps)) for k, ps in v] for t, v in cached["keys"].items()})
    if log:
        log("lab: graphs " + ", ".join(f"{w:#x}->{g:#x}" for w, g in LAB_GRAPHS.items())
            + "; template keys " + ", ".join(f"{t:#x}:{len(v)}" for t, v in TEMPLATE_KEYS.items()))


def resolve_script_tables(cfg, log=None):
    """2026-10-16 (diag --scripts): a prop built on a carrier had no scriptlets
    unless its world state's templates were sent (property 0x7D2, behavior graph
    0x5B5): the falling sphere (0x2E000AC5) rejected its start / open scripts.
    They are now read from each world state's own record ("did | 7 | .entity |
    0 | count | entries") in the player's packs."""
    import os
    from . import gamedata
    if not cfg["combat"].get("prop_script_tables_auto", True):
        return
    from . import gamecache
    rp_dir = os.path.join(cfg.game_dir, "rp")
    extra = [ws for ws in model_tour_list(cfg) if ws not in TABLE_WSTATES]
    # the lab's models (Tutorial 2) need their tables too
    if any((v or {}).get("lab") for v in (cfg["match"].get("maps") or {}).values()):
        extra += [ws for ws in tuple(LAB_CANDIDATES) + tuple(LAB_SPHERE) + tuple(LAB_START)
                  if ws not in TABLE_WSTATES and ws not in extra]
    cache_key = "script_tables_v5" + (f"_tour{len(extra)}_{sum(extra) & 0xFFFFFF:x}" if extra else "")
    # 10:53: always (Tutorial 1's falling meteor stp_meteor needs its graph from LAB_GRAPHS)
    _resolve_lab(cfg, rp_dir, log)
    cached = gamecache.get(rp_dir, cache_key)
    if cached is not None:
        found = []
        for ws, (tables, behavior) in cached.items():
            WSTATE_SCRIPT_TABLES[int(ws)] = (tuple(tables), behavior)
            found.append(f"{int(ws):#x} -> {' '.join(hex(t) for t in tables)}" + (f" (graph {behavior:#x})" if behavior else ""))
        if log:
            log("prop scriptlet tables (cached): " + ("; ".join(found) or "none"))
        return
    try:
        game = gamedata.Game(rp_dir, os.path.join(cfg.log_dir, "props.txt"))
        found, store = [], {}
        for ws in tuple(TABLE_WSTATES) + tuple(extra):
            # 22:47: partial - the rocks' records hold vectors the reader cannot
            # size after their 0x7D2, so they came back empty ("0 groups")
            rec = game.world_state(ws, partial=True)
            if not rec:
                continue
            _entity, entries = rec
            tables = tuple(v for _k, _kind, v in (gamedata.get(entries, SCRIPT_TABLE_PROPERTY) or [])
                           if isinstance(v, int))
            behavior = gamedata.get(entries, 0x5B5) or 0
            if not behavior and (ws in extra or ws == 0x2E0004E7):
                # fase3-hb: 0x5B5 often comes after a vector the reader cannot size (the
                # explosion 0x2E0004E7: graph set 0x1C000029); read it as the raw triplet
                # "0x5B5 | 0x5B5 | value". Tour / lab models and the explosion only (Tutorial 1's
                # explosion gets its graph set too; the other props are unchanged).
                raw = game.world_state_raw(ws)
                for i in range(20, len(raw) - 11, 4):
                    k1, k2, v = struct.unpack_from("<III", raw, i)
                    if k1 == k2 == 0x5B5 and v >> 24 in (0x1A, 0x1C):
                        behavior = v
                        break
            if tables:
                WSTATE_SCRIPT_TABLES[ws] = (tables, behavior)
                store[str(ws)] = [list(tables), behavior]
                found.append(f"{ws:#x} -> {' '.join(hex(t) for t in tables)}" + (f" (graph {behavior:#x})" if behavior else ""))
        gamecache.put(rp_dir, cache_key, store)
        if log:
            log("prop scriptlet tables: " + ("; ".join(found) or "none found in the packs"))
    except Exception as e:                # never stop the server for this
        if log:
            log(f"prop scriptlet tables: {e!r}")

WAVE_OBJECTIVE = ("<font color='#FFFF00'>Right-click</font> the drones to defeat them with "
                  "<font color='#00FF00'>Basic Attacks</font> ({}/2)")
SKILL_OBJECTIVE = "Click the highlighted button to unlock your <font color='#00FFFF'>Sonic Batarang</font> Skill"
PRACTICE = ("03TargetA", "03TargetB")
PRACTICE_OBJECTIVE = ("Place your cursor on a target and press <font color='#FFFF00'>('Q')</font> "
                      "to destroy it with <font color='#00FFFF'>Sonic Batarang</font>")
UPGRADE_ELEMENTS = tuple(HUD[n] for n in (
    "SkillButtonQUpgradeButton", "SkillButtonWUpgradeButton", "SkillButtonEUpgradeButton",
    "SkillButtonRUpgradeButton", "SkillButtonPassiveUpgradeButton",
    "SkillPointSpendReminder", "SkillsBarUpgradeReccommendedText"))
HUD_EVENT_HIDE = 2
# never used in the tutorial: Stolen Power T skill, Artifact Foundry button,
# current artifact slots, Recall (emp_gen UIHUDElementID): (21, 24, 29, 43).
# 2026-10-16 15:14 (tester): hiding them hid the WHOLE skills bar (the bar's
# HideElement passes every id but RecommendedText to its base class, which
# hides the bar itself). Off: () ([tutorial] hide_hud_elements).
HIDDEN_HUD_ELEMENTS = ()
OTHER_UPGRADE_BUTTONS = tuple(HUD[n] for n in (
    "SkillButtonWUpgradeButton", "SkillButtonEUpgradeButton",
    "SkillButtonRUpgradeButton", "SkillButtonPassiveUpgradeButton"))


# The guide ping's own property set in the packs (0x1D0007A9, "Map Ping", the
# one with map note category 0x12) carries property 0x8E = a list of two 0x30E
# entries: 0x3400053C (only used by that set) and 0x34000600. Candidates for the
# green ground ring; sent with the markers ([tutorial] marker_vfx, [] = off).
MARKER_VFX = (0x3400053C, 0x34000600)
VFX_LIST_PROPERTY, VFX_ELEMENT_PROPERTY = 0x8E, 0x30E


def marker_vfx_property(cfg):
    dids = cfg["tutorial"].get("marker_vfx", [])        # crashes the client (2026-10-14 15:11)
    if not dids:
        return []
    from .wire import KIND_ARRAY
    return [(VFX_LIST_PROPERTY, KIND_ARRAY, [(VFX_ELEMENT_PROPERTY, KIND_DID, int(d)) for d in dids])]


def ping_team(match):
    """PVP_Team on the pings. 2026-10-14: with the champion's team (1) the marker
    shows RED (enemy colour?); the player object carries no team, so 0 may read
    as "ours" (green). [tutorial] ping_team, -1 = the champion's team."""
    v = int(match.cfg["tutorial"].get("ping_team", 0))
    return match.team if v < 0 else v


def ping_properties(team, style="minimal", show=True):
    """Properties sent on pings / markers ([tutorial] ping_style):
      minimal - only "show on the map": each ping class keeps its own icon
                (2026-10-14 17:12: the two pings show different icons this way)
      team    - minimal plus PVP_Team (the colour, see ping_team_for)
      full    - the old set (icon 0x13000A15, category 0x12, scriptlet bool)"""
    # "show on the map": off when an invisible companion carries the minimap
    # note (else, with the exe's team-read patch, every ping would show twice)
    props = [(0x100007D8, KIND_BOOL, 1 if show else 0)]
    if style in ("team", "full"):
        props.append((0x1000009C, KIND_INT, team))       # PVP_Team
    if style == "full":
        props += [
            (0x10000083, KIND_DID, 0x13000A15),  # map note icon
            (0x100004DA, KIND_ENUM, 0x12),       # map note category
            (0x10000909, KIND_BOOL, 1),          # scriptlet bool (ground marker candidate)
        ]
    return props


def ping_style(match):
    return str(match.cfg["tutorial"].get("ping_style", "team")).lower()


# The client colours a ping by the relation of its PVP_Team to the local
# player's team (rva 0x853380): same team = friend (4, blue), one of them 0 =
# neutral (1), different / -1 = enemy (2, red). 2026-10-14: team 1 (Batman's)
# gave blue, -1 / no player team gave red. So Alt (alert) goes as an enemy
# team (red) and Ctrl (retreat) and the tutorial marker as neutral (0; green?).
# [tutorial] ping_class_teams = { "0x4000025B" = 2, "0x4000025A" = 0 }
PING_CLASS_TEAMS = {0x4000025B: 2, 0x4000025A: 0}


# Minimap notes (map manager rva 0x64b150): an entity with "show on the map"
# gets a note with its icon 0x10000083, category 0x100004DA and icon variant
# 0x100007FB, but NOT when its team is an enemy's (relation 2, rva 0x853380).
# The red (enemy-team) Alt ping would never show there, so every ping gets an
# invisible companion (the guide's "Map Ping" class, InvisibleTarget) on the
# same spot that only carries the note, with a neutral team.
# The ping classes' own record (0x4900025A): icon 0x13000A15, category 1.
MAP_NOTE_ICON = 0x13000A15
MAP_NOTE_BASE_ID = 0x0200000000000070       # + n % 0x10
MAP_NOTE_VARIANTS = {0x4000025B: 0, 0x4000025A: 1}   # alert / retreat (guess)


def map_note_properties(match, class_id, category=None):
    tc = match.cfg["tutorial"]
    if category is None:
        category = int(tc.get("map_note_category", 0x1D))
    variants = dict(MAP_NOTE_VARIANTS)
    raw = tc.get("map_note_variants")
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                variants[int(str(k), 0)] = int(v)
            except ValueError:
                pass
    return [
        (0x100007D8, KIND_BOOL, 1),                                       # show on the map
        (0x1000009C, KIND_INT, int(tc.get("map_note_team", 0))),          # not an enemy's
    ] + ([(0x10000083, KIND_DID, int(tc.get("map_note_icon", 0)))] if int(tc.get("map_note_icon", 0)) else []) + [
        # 2026-10-14 18:41: with icon 0x13000A15 the minimap showed a yellow cone
        # next to the ping's own icon: the HUD draws the ping icon by itself
        (0x100004DA, KIND_ENUM, int(category)),
        (0x100007FB, KIND_INT, variants.get(class_id, 0)),
    ]


def note_mode(match):
    """[tutorial] map_notes: "self" = the visible ping / marker carries its own
    minimap note (2026-10-14 18:24: the invisible companions reached the HUD but
    never got a position), "companion" = an invisible object next to it does,
    "off" = none."""
    v = match.cfg["tutorial"].get("map_notes", "self")
    if v is True:
        return "companion"
    if v is False:
        return "off"
    return str(v).lower()


def note_extras(match, class_id, category=None):
    """Icon, category and variant of the minimap note (no show flag, no team)."""
    return [p for p in map_note_properties(match, class_id, category) if p[0] not in (0x100007D8, 0x1000009C)]


# 22:57: with category 1 and variants 0/1 both ping types showed the same icon
# on the minimap. Guess: the HUD's variant is the client's ping type (1 = alert,
# 2 = retreat). [tutorial] player_note_variants = { "0x4000025B" = 1, ... }
PLAYER_NOTE_VARIANTS = {0x4000025B: 0, 0x4000025A: 0}   # 23:22: the category picks the icon
# 23:07: still one icon for both with category 1. Category 0x1D is the client's
# ping category (the note reader shifts it to the enemy's icons for team 2, and
# the guide marker's retreat icon draws with it): back to 0x1D + variant 0/1,
# with the patched exe keeping the alert pings (team 2) on their own icon.


def player_note_variant(match, class_id):
    table = dict(PLAYER_NOTE_VARIANTS)
    raw = match.cfg["tutorial"].get("player_note_variants")
    if isinstance(raw, dict):
        for k, v in raw.items():
            table[int(str(k), 0)] = int(v)
    return table.get(class_id, 1)


def player_note_props(match, class_id, extras_only=False):
    props = map_note_properties(match, class_id, player_note_category(match, class_id))
    props = [(k, kind, player_note_variant(match, class_id) if k == 0x100007FB else v) for k, kind, v in props]
    if extras_only:
        props = [p for p in props if p[0] not in (0x100007D8, 0x1000009C)]
    return props


# 23:22: the HUD's Flash (MapNoteCategoryList, classes_all.txt) picks the ping
# icon/animation by CATEGORY: 1 = PING, 18 = ALERT_PING_INGAME,
# 21 = RETREAT_PING_INGAME (17 / 22 = ALERT_PING / RETREAT_PING; 0x1D = 29 is
# BEACON). [tutorial] player_note_categories = { "0x4000025B" = 18, ... }
# 23:42: on screen the two came out swapped (like the ping classes themselves)
PLAYER_NOTE_CATEGORIES = {0x4000025B: 21, 0x4000025A: 18}


def player_note_category(match, class_id=None):
    tc = match.cfg["tutorial"]
    if "player_note_category" in tc:            # one category for both (old setting)
        return int(tc["player_note_category"])
    table = dict(PLAYER_NOTE_CATEGORIES)
    raw = tc.get("player_note_categories")
    if isinstance(raw, dict):
        for k, v in raw.items():
            table[int(str(k), 0)] = int(v)
    return table.get(class_id, 1)


def ping_team_for(match, class_id):
    raw = match.cfg["tutorial"].get("ping_class_teams")
    table = dict(PING_CLASS_TEAMS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                table[int(str(k), 0)] = int(v)
            except ValueError:
                pass
    if class_id in table:
        return table[class_id]
    return ping_team(match)


def objective_one(text):
    return M.objective(1, text=text, active=True, category=1, sort_order=0, optional=False, banner=text)


class Tutorial:
    def __init__(self, match, targets=None, drone_step=DRONE_STEP):
        self.started_at = time.time()    # match length on the end page
        self.aggressive = set()          # eids of drones fighting Batman
        self.next_hit = {}
        self.walk_logged = {}
        self.attack_count = {}           # eid -> hits so far (attack script rotation)
        self.match = match
        self.targets = {i + 1: tuple(t) for i, t in enumerate(targets)} if targets else dict(TARGETS)
        self.drone_step = drone_step     # the drone appears when the guide points at this step
        self.step = 0
        self.objective_text = FIRST_OBJECTIVE
        self.first_attack_done = False
        self.phase = "walk"          # walk -> first_drone -> wave -> skills
        self.thug_eid = None
        # set by the session: schedule(delay, fn) sends fn()'s messages later
        self.schedule = lambda delay, fn: None
        self.run_scripts = lambda entity_id, keys, what, variables=None, second=0: None
        self.log = lambda text: None      # server.log (set by the session)
        self.on_skill_prompt = None       # set by the session (auto-rank fallback timer)
        self.damage = lambda ent, amount: None   # set by the session
        self.batarang_casts = 0
        self.locked_until = 0.0           # Batman cannot move before this (time.time())
        self.lock_reason = ""
        self.meteor_count = 0
        self.visible_markers = set()      # steps with a visible marker on the ground
        self.marker_ids = {}              # step -> object id of its visible marker now
        self.flying_until = 0.0           # Bat Flight: move orders wait until he lands
        self.low_health_said = False
        self.bridge = Bridge(self)        # part 2: after the Catwoman cinematic
        from .finale import Finale
        self.finale = Finale(self)        # part 3: Super Strength, the Destroyer, the victory

    def ping(self, step, now):
        xyz = self.targets.get(step)
        if not xyz:
            return None
        spawn = self.match.mover.spawn
        # the ping is a placed prop like the doors: cell 251 of the layout ([combat] ping_cell;
        # 2026-10-14 12:20: the markers were never seen with cell 0)
        cc = self.match.cfg.get("combat", {}) if hasattr(self.match.cfg, "get") else {}
        cell = int(cc.get("ping_cell", cc.get("scenery_cell", 251)))
        pos = (spawn[0], 0x13, 0xCB, cell) + tuple(xyz)
        # The ping entity is an "InvisibleTarget" (world state 0x2E000002): the
        # marker on the ground and the arrows at Batman's feet are Batman's own
        # scripts Vfx_GuideArrow (0x10000F80) and Vfx_GuideArrow_Ping (0x10000F86),
        # both in his script table, aimed at the ping (2026-10-14 12:27).
        ping_id = M.PING_OBJECT_ID + step
        keys = tuple(int(k) for k in (self.match.cfg["tutorial"].get("guide_keys") or GUIDE_KEYS))
        if keys:
            # 2026-10-14: the scripts were accepted but nothing showed. The game's
            # guide script (0x1E00055B: AlertPingScriptlet / AlertArrowScriptlet)
            # plays them aimed at the ping, so try three ways one after the other
            # and ask which moment shows the marker ([tutorial] guide_variants):
            #   A: both on Batman, target as script variable 0x108 (as before)
            #   B: as A plus the ping as the order's second object (field 0x20)
            #   C: the ground marker (GuideArrow_Ping) on the ping itself, the
            #      arrows (GuideArrow) on Batman aimed at the ping
            tc = self.match.cfg["tutorial"]
            variants = [str(v).upper() for v in tc.get("guide_variants", ["A", "B", "C"])]
            gap = float(tc.get("guide_variant_gap", 4.0))
            target = [(M.PROP_SCRIPT_TARGET, KIND_IID, ping_id)]
            arrow = [k for k in keys if k != GUIDE_KEYS[1]] or list(keys)
            marker = [k for k in keys if k == GUIDE_KEYS[1]] or list(keys)

            def run(v, step=step):
                if self.step != step:
                    return []                                 # that marker is already behind
                if getattr(self, "tour_active", False):
                    # 2026-10-17 00:58: every tour crash came ~0.5 s after variant C (the
                    # arrows' path to the ping, next to the tour model): no guide on tours
                    return []
                self.log(f"tutorial: marker {step}, guide variant {v}")
                if v == "A":
                    self.run_scripts(M.CHAMPION_AGENT_ID, keys, f"guide {v} -> ping {step}", target)
                elif v == "B":
                    self.run_scripts(M.CHAMPION_AGENT_ID, keys, f"guide {v} -> ping {step}", target, ping_id)
                elif v == "C":
                    self.run_scripts(ping_id, marker, f"guide {v}: marker on ping {step}", target)
                    self.run_scripts(M.CHAMPION_AGENT_ID, arrow, f"guide {v}: arrows -> ping {step}", target, ping_id)
                return []
            for i, v in enumerate(variants):
                self.schedule(0.3 + gap * i, lambda v=v: run(v))
        # The guide ping itself is invisible. The players' own pings (Alt / Ctrl +
        # click) DO show (2026-10-14 14:14), so a player ping goes on the same spot
        # as the visible marker until the guide's ground circle works
        # ([tutorial] marker_ping_class, 0 = off).
        vis = int(self.match.cfg["tutorial"].get("marker_ping_class", PLAYER_PING_CLASSES[2]) or 0)
        if vis:
            self.visible_markers.add(step)
            mpos = (spawn[0], spawn[1], spawn[2], 0) + tuple(xyz)
            cat = int(self.match.cfg["tutorial"].get("marker_category", 0x1D))
            mode = note_mode(self.match)
            # 2026-10-14 19:56: swapping the marker after 5 s lost the ground marker
            # and the minimap kept its icon. Now the ground marker never carries
            # the note; an invisible object on the same spot carries it and is
            # removed after [tutorial] marker_note_seconds (the note manager now
            # runs, so it should get its position).
            # 20:04: without "show on the map" the ground marker is not drawn at
            # all (the ping's ground ring is part of the map-note system), so the
            # marker carries its note again; the minimap icon is meant to fade by
            # itself with the ping category 0x1D (see [tutorial] map_note_category)
            props = ping_properties(ping_team_for(self.match, vis), ping_style(self.match), show=True)
            props += [(k, kind, cat if k == 0x100004DA else v) for k, kind, v in note_extras(self.match, vis)]
            props += marker_vfx_property(self.match.cfg)
            msg = M.create_object(M.MARKER_OBJECT_ID + step, vis, now, position=mpos,
                                  module=self.match.module, second_seq=self.match.second_seq,
                                  properties=props)
            self.marker_ids[step] = M.MARKER_OBJECT_ID + step
            note_id = M.MARKER_OBJECT_ID + 0x8 + step
            note = None
            if mode == "companion":
                note = M.create_object(note_id, PING_CLASS, now, position=mpos, module=self.match.module,
                                       second_seq=self.match.second_seq,
                                       properties=map_note_properties(self.match, vis))
            note_s = float(self.match.cfg["tutorial"].get("marker_note_seconds", 5.0) or 0)

            def show(step=step, msg=msg, note=note):
                if self.step != step:
                    return []
                self.log(f"tutorial: visible marker {step} at ({xyz[0]:.1f}, {xyz[1]:.1f})")
                out = [(f"visible marker {step} (player ping class {vis:#x})", msg)]
                if note:
                    out.append((f"minimap note of marker {step}", note))
                return out
            self.schedule(0.1, show)

            def unnote(step=step):
                self.log(f"tutorial: marker {step} leaves the minimap")
                return [(f"minimap note of marker {step} removed (0x3)", M.remove_object(note_id))]
            if note and note_s > 0:
                self.schedule(0.1 + note_s, unnote)
        if note_mode(self.match) == "companion":
            props = map_note_properties(self.match, vis or PLAYER_PING_CLASSES[2])
        else:
            props = ping_properties(ping_team(self.match), ping_style(self.match), show=not vis)
        return M.create_object(ping_id, PING_CLASS, now, position=pos,
                               module=self.match.module, second_seq=self.match.second_seq,
                               properties=props + marker_vfx_property(self.match.cfg))

    def remove_ping(self, step, keep_visible=False):
        """Remove a guide ping and the visible marker that goes with it (the
        visible one stays until Batman steps on it when keep_visible)."""
        out = [(f"guide ping {step} removed (0x3)", M.remove_object(M.PING_OBJECT_ID + step))]
        if step in self.visible_markers and not keep_visible:
            self.visible_markers.discard(step)
            mid = self.marker_ids.pop(step, M.MARKER_OBJECT_ID + step)
            out.append((f"visible marker {step} removed (0x3)", M.remove_object(mid)))
            out.append((f"minimap note of marker {step} removed (0x3)",
                        M.remove_object(M.MARKER_OBJECT_ID + 0x8 + step)))
        return out

    def _objective(self, text):
        self.objective_text = text
        return [("objective 1 new text (0x2009)", M.objective_update(objective_one(text)))]

    def _beat_msgs(self, kind, value, now):
        if kind == "conv":
            return self.say(value, now)
        if kind == "hint":
            return [(f"tutorial hint {value}", M.tutorial_hint(value))]
        if kind == "objective":
            return self._objective(value)
        if kind == "ping":
            ping = self.ping(self.step, now)
            return [(f"guide ping {self.step}", ping)] if ping else []
        if kind == "call":
            return value() or []
        raise ValueError(kind)

    def say(self, key, now=None):
        """Start a conversation and move the end of the client's speech queue."""
        now = now or time.time()
        pacing = float(self.match.cfg["tutorial"].get("pacing", 1.0))
        self.speech_end = max(getattr(self, "speech_end", 0.0), now) + CONV_SECONDS.get(key, 4.0) * pacing
        return [(f"conversation {key:#x} (0x2001)", M.start_conversation(key))]

    def after_speech(self, margin, fn):
        """Call fn once every queued line has been spoken (+ margin s)."""
        def check():
            wait = getattr(self, "speech_end", 0.0) + margin - time.time()
            if wait > 0.05:
                self.schedule(wait, check)
                return []
            return fn()
        return check()

    def beats(self, beats, now=None):
        """Play (delay, kind, value) beats: delay 0 ones are returned now, the
        rest are scheduled ([tutorial] pacing scales the delays)."""
        scale = float(self.match.cfg["tutorial"].get("pacing", 1.0))
        now_msgs = []
        for delay, kind, value in beats:
            delay *= scale
            if delay <= 0:
                now_msgs += self._beat_msgs(kind, value, now or time.time())
            else:
                self.schedule(delay, lambda kind=kind, value=value: self._beat_msgs(kind, value, time.time()))
        return now_msgs

    def start(self, now):
        """Cinematic finished: HUD, vitals, objective, first conversation, ping.
        Returns the messages, or [] if the tutorial already started."""
        if self.step:
            return []
        # 2026-10-17 20:46 (tester): in the original Batman already stands with the antennas lit when we
        # get control; the shimmer before that is his Spawn animation (the electricity comes on when it
        # ends, 20:41). The graph event Spawn is raised as soon as the intro cinematic ends and the
        # tutorial itself (HUD, prompt, meteors, movement) starts champion_spawn_hold s later.
        tc0 = self.match.cfg["tutorial"]
        hold = float(tc0.get("champion_spawn_hold", 5.0))
        spawn_events = [int(e) for e in tc0.get("champion_spawn_events", []) or []]
        if hold > 0 and spawn_events and not getattr(self, "spawn_raised", False):
            self.spawn_raised = True
            self.raise_events(spawn_events, "Batman spawn (before the start)")
            self.lock(now, hold, "spawn animation")
            self.log(f"tutorial: Batman's spawn animation; the tutorial starts in {hold:g} s")
            self.schedule(hold, lambda: self.start(time.time()))
            return []
        # 2026-10-17 23:29 (tester, Tutorial 2 tour: only Cinematic_Intro lights the antennas; Spawn raised by
        # the server does not, even after Vfx_Bmg_Spawn): Cinematic_Intro runs on Batman as the tutorial starts,
        # in the game (the lab tours never reported its voice line; on the loading screen it was heard, 22:40),
        # as in the original (his spawn shimmer as the camera arrives, then the antennas). He stands still
        # champion_intro_lock s while it plays (the start's meteors keep him there anyway: start_lock).
        if str(tc0.get("champion_intro_at", "start")) == "start" and not getattr(self, "spawn_raised", False):
            ikeys = [int(k) for k in tc0.get("champion_intro_keys", []) or []]
            if ikeys:
                self.spawn_raised = True
                self.run_scripts(M.CHAMPION_AGENT_ID, ikeys, "Batman intro (Cinematic_Intro, tutorial start)")
                self.lock(now, float(tc0.get("champion_intro_lock", 2.8)), "spawn animation")
        self.step = 1
        m = self.match
        self._champion_ambient()
        msgs = [(f"HUD element {e} restored (0x213d)", M.hud_element(e, HUD_EVENT_FIRST_RESTORED))
                for e in START_ELEMENTS]
        msgs.append(("champion vitals (0x42)", M.vitals(M.CHAMPION_AGENT_ID, m.vitals)))
        msgs.append(("objective list (0x2034)", M.objective_list(
            [objective_one(self.objective_text)],
            [M.objective_category(1, CATEGORY_TITLE, state=OBJECTIVE_CATEGORY_SHOW)])))
        start_at = str(m.cfg["tutorial"].get("start_at", "") or "")
        if start_at:
            # [tutorial] start_at: skip part 1 and start at a later point (testing)
            if m.cfg["tutorial"].get("drones_fight_back", True):
                self.schedule(0.5, self._drone_ai)
            self.schedule(0.5, self._bridge_tick)
            self.schedule(1.0, lambda: self.bridge.jump(start_at, time.time()))
            self._action_tour()
            return msgs
        for k in INTRO_CONVERSATIONS:
            msgs += self.say(k, now)
        ping = self.ping(1, now)
        if ping:
            msgs.append(("guide ping 1", ping))
        if m.cfg["tutorial"].get("drones_fight_back", True):
            self.schedule(0.5, self._drone_ai)
        self.schedule(0.5, self._bridge_tick)
        if self.match.cfg["tutorial"].get("meteors", True):
            # "before you can move, 3 small meteors fall near him"
            tc = m.cfg["tutorial"]
            spots = [tuple(xyz) for xyz in (tc.get("small_meteors") or SMALL_METEORS)]
            # 2026-10-17 16:24 (original video): small_meteor_times (was 1.0 + 0.7 i)
            times = [float(t) for t in (tc.get("small_meteor_times") or [])]
            times += [1.0 + 0.7 * i for i in range(len(times), len(spots))]
            for xyz, at in zip(spots, times):
                self.schedule(at, lambda xyz=xyz: self.meteor(xyz, time.time(), lifetime=0, group="small"))
            if spots:
                # the big meteor never comes before the small ones have hit (big_meteor_after_small)
                self.small_meteors_done = now + max(times[:len(spots)]) + float(tc.get("stp_meteor_impact", 1.0))
            if spots and tc.get("small_meteor_cloud", True):
                centre = tuple(sum(p[k] for p in spots) / len(spots) for k in range(3))
                # 18:46 (tester): the dust came after the meteors had landed; it must come with them:
                # from the first impact (small_meteor_cloud_delay from there; was the last + 0.3)
                hit = max(0.0, min(times[:len(spots)]) + float(tc.get("stp_meteor_impact", 1.0))
                          + float(tc.get("small_meteor_cloud_delay", -0.2)))
                self.schedule(hit, lambda: self._small_meteor_cloud(centre))
            self.lock(now, float(m.cfg["tutorial"].get("start_lock", 3.5)), "the first meteors are falling")
        self._action_tour()
        self._model_tour()
        return msgs

    def _model_tour(self):
        """[debug] model_tour: show world states one at a time in front of Batman, every
        model_tour_interval s, numbered in the objective text and in server.log."""
        m = self.match
        dc = m.cfg["debug"]
        ids = model_tour_list(m.cfg)
        if not self.meteor_event_ready():
            ids = [w for w in ids if w not in MODEL_TOUR_EVENT_ONLY]
        if not ids:
            return
        self.tour_active = True
        state = _tour_state(m.cfg)
        key = f"{len(ids)}:{sum(ids) & 0xFFFFFFF:x}"
        # 2026-10-17 00:44 (tester): from model 14 on the game closed ~3 s after nearly every
        # model (14, 16, 17, 18, 20, 22, 23; 21-26 once passed, 27 at 0.2 s). Models 1-13 were
        # fine. The later ones carry scriptlet templates (characters, turrets...) whose
        # scripts run on the gate carrier. The tour now shows the bare model (no templates,
        # no keys) unless model_tour_scripts is on; each mode has its own crash list.
        with_scripts = bool(dc.get("model_tour_scripts", False))
        crash_key = "crashed" if with_scripts else "crashed_bare"
        self.tour_crash_key = crash_key
        if state.get("key") != key:
            state = {"key": key, "last": 0, "crashed": state.get("crashed", []),
                     "crashed_bare": state.get("crashed_bare", [])}
        skip = set(state.get(crash_key, [])) | set(MODEL_TOUR_CRASHES) | set(MODEL_TOUR_CRASHES_BARE)
        # 00:12: model_tour_from 0 (default) = go on after the last one shown before
        first = int(dc.get("model_tour_from", 0)) or int(state.get("last", 0)) + 1
        if first > len(ids):
            first = 1
        gap = float(dc.get("model_tour_interval", 4.0))
        start = float(dc.get("model_tour_start", 6.0))
        at = tuple(float(v) for v in dc.get("model_tour_at", [23.0, 56.0, 200.0]))
        scale = float(dc.get("model_tour_scale", 1.0))
        keys = [int(k) for k in dc.get("model_tour_keys", [0x1000018E, 0x10000032, 0x10000078]) or []] \
            if with_scripts else []
        total = len(ids)
        self.tour_state = state
        self.log(f"model tour: {total} models from {first}, every {gap:g} s, "
                 f"{'with their scripts' if with_scripts else 'bare models (no scripts)'}"
                 + (f"; skipped (closed the game): {', '.join(hex(w) for w in sorted(skip))}" if skip else ""))
        slot = 0
        for n in range(first, total + 1):
            ws = ids[n - 1]
            if ws in skip:
                continue

            def show(n=n, ws=ws):
                label = f"Model {n}/{total} {ws:#010X}"
                self.log(f"model tour {n}/{total}: world state {ws:#x}")
                self.tour_last = (n, ws, time.time())
                state.update(last=n)
                _tour_state(m.cfg, state)
                eid, msg = self._prop_object(ws, at, time.time(), 0, scale, f"model tour {n}", scripts=with_scripts)
                if keys:
                    self.schedule(0.3, lambda: (self.run_scripts(eid, keys, f"model tour {n} {ws:#x}"), [])[1])
                self.schedule(max(0.5, gap - 0.2), lambda: [(f"model tour {n} removed (0x3)", M.remove_object(eid))])
                return self._objective(label) + [msg]
            self.schedule(start + gap * slot, show)
            slot += 1

    def _champion_tour(self):
        """2026-10-17 19:18 (tester: "a tour of every Gaslight Batman animation, I tell you which ones";
        Tutorial 2): [debug] lab_tour = "batman". Every graph event of his behavior graph, then every
        scriptlet the client accepts on him (icserver/champion_fx.py), one every champion_tour_interval
        s, labelled "G n/N name" / "S n/N name" in the objective text and server.log. A scriptlet named
        *_Active / *_Start is followed by its *_Stop (when he has one) after champion_tour_stop_after s
        so effects do not pile up; graph events that knock him down are followed by CbtState_GetUp.
        It resumes after the last entry shown (logs/model_tour.json "batman"); champion_tour_from = n
        starts at entry n (1 = from the beginning)."""
        from . import champion_fx
        m = self.match
        dc = m.cfg["debug"]
        entries = [("G", k, n) for k, n in champion_fx.GRAPH] + [("S", k, n) for k, n in champion_fx.SCRIPTLETS]
        # 19:52: champion_tour_only = ["G Spawn", "S Vfx_Bmg_Spawn", ...] shows only those entries (in that order)
        only = [str(x) for x in dc.get("champion_tour_only") or []]
        if only:
            entries = [e for o in only for e in entries if f"{e[0]} {e[2]}" == o]
        by_name = {n: k for k, n in champion_fx.SCRIPTLETS}
        gap = float(dc.get("champion_tour_interval", 3.0))
        stop_after = float(dc.get("champion_tour_stop_after", 2.4))
        start = float(dc.get("lab_start", 6.0))
        state = _tour_state(m.cfg)
        tour = state.get("batman") or {}
        if tour.get("key") != len(entries):
            tour = {"key": len(entries), "last": 0, "crashed": []}
        state["batman"] = tour
        first = int(dc.get("champion_tour_from", 0)) or int(tour.get("last", 0)) + 1
        if first > len(entries):
            first = 1
        self.tour_state = state
        self.tour_crash_key = "batman"
        ng = sum(1 for e in entries if e[0] == "G")
        self.log(f"champion tour: {len(entries)} entries ({ng} graph events, {len(entries) - ng} scriptlets) "
                 f"from {first}, every {gap:g} s")
        getup_ev = next((k for k, n in champion_fx.GRAPH if n == "CbtState_GetUp"), None)
        slot = 0
        crashed = set(tour.get("crashed", []))
        for e in range(first, len(entries) + 1):
            kind, key, name = entries[e - 1]
            if e in crashed:
                continue
            num = sum(1 for x in entries[:e] if x[0] == kind)
            total = ng if kind == "G" else len(entries) - ng
            label = f"{kind} {num}/{total} {name}"

            def show(e=e, kind=kind, key=key, name=name, label=label):
                self.log(f"champion tour {e}/{len(entries)}: {label} ({key:#x})")
                tour.update(last=e)
                _tour_state(m.cfg, state)
                self.tour_last = (e, key, time.time(), kind)
                if kind == "G":
                    self.raise_events([key], f"tour {label}")
                    if getup_ev and any(w in name for w in ("Dead", "Death", "Knock", "Incapac", "Cower")):
                        self.schedule(stop_after, lambda: self.raise_events([getup_ev], "tour get up"))
                else:
                    self.run_scripts(M.CHAMPION_AGENT_ID, [key], f"tour {label}")
                    for end in ("_Active", "_Start"):
                        if name.endswith(end) and by_name.get(name[:-len(end)] + "_Stop"):
                            stop = by_name[name[:-len(end)] + "_Stop"]
                            self.schedule(stop_after, lambda stop=stop: (
                                self.run_scripts(M.CHAMPION_AGENT_ID, [stop], "tour stop"), [])[1])
                return self._objective(label)
            self.schedule(start + gap * slot, show)
            slot += 1
        self.schedule(start + gap * slot + 0.5, lambda: self._objective("Tour finished"))
        return []

    def lab_start(self, now):
        """2026-10-17 (fase3-hb): Tutorial 2 as a lab. No guide, drones or meteors: the objective
        list, then [debug] lab_tour shown one by one next to the start point, numbered in the
        objective text and in server.log. lab_modes, per model:
          "bare"    - the model alone ("Model n/N a")
          "scripts" - with its scriptlet templates and graph, model_tour_keys run ("b")
          "keys"    - fase3-hd: one entry per scriptlet key of its templates (TEMPLATE_KEYS):
                      the model with its templates and raw graph, then only that key, which
                      plays the particle effects it names ("Model n/N key j/J 0x1000....")
        Models that closed the game are skipped next time (logs/model_tour.json, key "lab")."""
        m = self.match
        dc = m.cfg["debug"]
        self.step = -1                    # not a Tutorial 1 step: the guide code stays out
        self.tour_active = True
        msgs = [("objective list (0x2034)", M.objective_list(
            [objective_one("Lab")], [M.objective_category(1, CATEGORY_TITLE, state=OBJECTIVE_CATEGORY_SHOW)]))]
        if str(dc.get("lab_tour", "")) == "batman":
            return msgs + self._champion_tour()
        ids = model_tour_list(m.cfg, dc.get("lab_tour", "sphere") or "sphere")
        if not self.meteor_event_ready():
            self.log("lab: pack 0xA000009A is not loaded (exe without the two zone slots?): "
                     "the meteor event pieces are left out")
            ids = [w for w in ids if w not in MODEL_TOUR_EVENT_ONLY and w != 0x2E0004ED and w != 0x2E0007D4]
        modes = [str(v) for v in (dc.get("lab_modes") or ["keys"])]
        entries = []                      # (world state, mode, key or 0, label suffix)
        for ws in ids:
            for mode in modes:
                if mode == "keys":
                    keys_here = []
                    for t in (WSTATE_SCRIPT_TABLES.get(ws, ((), 0))[0] or ()):
                        keys_here += [(k, ps) for k, ps in TEMPLATE_KEYS.get(t, []) if k not in [x for x, _ in keys_here]]
                    keys_here += [(k, ()) for k in LAB_EXTRA_KEYS.get(ws, ()) if k not in [x for x, _ in keys_here]]
                    for j, (k, ps) in enumerate(keys_here, 1):
                        entries.append((ws, f"key:{k:#x}", k, f" key {j}/{len(keys_here)} {k:#X}",
                                        " ".join(hex(p) for p in ps)))
                    if not keys_here:
                        # 10:37: no keys found: once with its templates and graph (its graph plays)
                        entries.append((ws, "graph", 0, " graph", ""))
                        entries.append((ws, "graph+keys", 0, " graph+keys", ""))
                else:
                    tag = "ab"[modes.index(mode)] if mode in ("bare", "scripts") and len(modes) <= 2 else mode
                    entries.append((ws, mode, 0, tag, ""))
        off = [float(v) for v in dc.get("lab_offset", [-4.3, 4.4, 0.0])]
        state = _tour_state(m.cfg)
        lab = state.get("lab") or {}
        # 09:49: the spot is part of the key: a new lab_offset starts from model 1 again
        key = f"{len(entries)}:{sum(ids) & 0xFFFFFFF:x}:{off[0]:g},{off[1]:g}:{'+'.join(modes)}"
        if lab.get("key") != key:
            lab = {"key": key, "last": 0, "crashed": lab.get("crashed", [])}
        state["lab"] = lab
        skip = {tuple(x) for x in lab.get("crashed", [])}
        first = int(dc.get("lab_from", 0)) or int(lab.get("last", 0)) + 1
        if first > len(entries):
            first = 1
        gap = float(dc.get("lab_interval", 5.0))
        start = float(dc.get("lab_start", 6.0))
        spawn = m.mover.spawn
        at = (spawn[4] + off[0], spawn[5] + off[1], spawn[6] + off[2])
        tour_keys = [int(k) for k in dc.get("model_tour_keys", [0x1000018E, 0x10000032, 0x10000078]) or []]
        # 10:37: "graph+keys" = the start keys plus the Destroyer's open key 0x10000E5C
        open_keys = [int(k) for k in dc.get("lab_open_keys", [0x1000018E, 0x10000032, 0x10000078, 0x10000E5C]) or []]
        self.tour_state = state
        self.tour_crash_key = "lab"
        total = len(ids)
        self.log(f"lab: {total} models, {len(entries)} entries ({', '.join(modes)}) from entry {first}, every "
                 f"{gap:g} s at ({at[0]:.1f}, {at[1]:.1f}, {at[2]:.1f})"
                 + (f"; skipped (closed the game): {sorted(skip)}" if skip else ""))
        if not entries:
            self.log("lab: nothing to show (no template keys found for these models?)")
        slot = 0
        for e in range(first, len(entries) + 1):
            ws, mode, run_key, suffix, parts = entries[e - 1]
            # 16:54 (tester): a model that closed the game is skipped with all its keys, not only
            # the entry that was showing (the model itself, not the key, closes it ~3-5 s after it appears)
            if (f"{ws:#x}", mode) in skip or ws in MODEL_TOUR_CRASHES_BARE \
                    or any(x[0] == f"{ws:#x}" for x in skip):
                continue
            n = ids.index(ws) + 1

            def show(e=e, n=n, ws=ws, mode=mode, run_key=run_key, suffix=suffix, parts=parts):
                label = f"Model {n}/{total}{suffix} {ws:#010X}" if not run_key else f"Model {n}/{total}{suffix}"
                with_scripts = mode != "bare"
                self.log(f"lab {e}/{len(entries)}: model {n}/{total}{suffix} world state {ws:#x} ({mode})"
                         + (f", particles {parts}" if parts else ""))
                self.tour_last = (n, ws, time.time(), mode)
                lab.update(last=e)
                _tour_state(m.cfg, state)
                eid, msg = self._prop_object(ws, at, time.time(), 0, 1.0, f"lab {n}{suffix}", scripts=with_scripts,
                                             raw_graph=with_scripts)
                run = [run_key] if run_key else (tour_keys if mode == "scripts" else
                                                 open_keys if mode == "graph+keys" else [])
                if run:
                    self.schedule(0.3, lambda: (self.run_scripts(eid, run, f"lab {n}{suffix} {ws:#x}"), [])[1])
                self.schedule(max(0.5, gap - 0.2), lambda: [(f"lab {n}{suffix} removed (0x3)", M.remove_object(eid))])
                return self._objective(label) + [msg]
            self.schedule(start + gap * slot, show)
            slot += 1
        self.schedule(start + gap * slot + 0.5, lambda: self._objective("Lab finished"))
        return msgs

    def on_match_end(self, why):
        """00:12: the client closing right after a tour model was created marks that
        model as crashing (logs/model_tour.json); the next tour skips it."""
        last = getattr(self, "tour_last", None)
        if last and "connection" in why and time.time() - last[2] < float(
                self.match.cfg["debug"].get("model_tour_crash_window", 6.0)):   # 01:08: closes 0.1-3.3 s after
            n, ws, _t = last[:3]
            state = getattr(self, "tour_state", {})
            ck = getattr(self, "tour_crash_key", "crashed")
            if ck == "batman":
                # 19:18: champion tour: the entry that closed the game is skipped next time
                tour = state.setdefault("batman", {})
                tour["crashed"] = sorted(set(tour.get("crashed", [])) | {n})
            elif ck == "lab":
                lab = state.setdefault("lab", {})
                lab["crashed"] = sorted({tuple(x) for x in lab.get("crashed", [])} | {(f"{ws:#x}", last[3])})
            else:
                state[ck] = sorted(set(state.get(ck, [])) | {ws})
            _tour_state(self.match.cfg, state)
            self.log(f"model tour: the game closed {time.time() - last[2]:.1f} s after model {n} ({ws:#x}); "
                     "it is skipped from now on")

    def _action_tour(self):
        """[debug] tour_keys: play Batman's scriptlets one by one to see what each does."""
        import os
        dc = self.match.cfg["debug"]
        raw = dc.get("tour_keys") or []
        if not raw:
            return
        names = {}
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "batman_actions.tsv")
        try:
            for line in open(path, encoding="utf-8"):
                k, _, n = line.rstrip("\n").partition("\t")
                names[int(k, 16)] = n
        except OSError:
            pass
        if raw == "all":
            keys = list(names)
        elif raw in ("core", "nucleo"):
            keys = [k for k, _ in TOUR_CORE]
            names.update(dict(TOUR_CORE))
        else:
            keys = [int(str(k), 0) for k in raw]
        gap = float(dc.get("tour_interval", 3.0))
        start = float(dc.get("tour_start", 6.0))
        for i, key in enumerate(keys):
            def play(key=key, i=i):
                self.log(f"tour {i + 1}/{len(keys)}: {key:#x} {names.get(key, '')}")
                self.run_scripts(M.CHAMPION_AGENT_ID, [key], f"tour {key:#x}")
                return []
            self.schedule(start + gap * i, play)

    def meteor(self, xyz, now, knockdown=False, lifetime=None, group=None):
        """A falling PowerCore at xyz, removed after METEOR_LIFETIME (lifetime
        0 = stays; group = removed together by remove_meteors(group))."""
        m = self.match
        tc = m.cfg["tutorial"]
        msgs = []
        if self.meteor_event_ready() and tc.get("big_meteor_event" if knockdown else "meteor_event", True):
            return msgs + self._meteor_event(xyz, now, big=knockdown, lifetime=lifetime, group=group)
        if knockdown and tc.get("big_meteor_falls", True):
            # 18:36 (tester): at the first marker the big meteor made no dust: it
            # now falls like the small ones (bigger, big_meteor_scale) with the
            # dust cloud 0x2E0007D4 (big_meteor_dust), removed when it has hit
            fall = float(tc.get("big_meteor_fall_seconds", 1.4))
            msgs += self._falling_meteor(xyz, now, lifetime=fall + float(tc.get("big_meteor_rock_seconds", 0.6)),
                                         big=True)
            if tc.get("big_meteor_crater", True):
                # the crater and the knockdown when it hits
                def hit():
                    out = self.crater(xyz, time.time())
                    self.knockdown()
                    return out
                self.schedule(fall, hit)
            else:
                self.schedule(fall, lambda: (self.knockdown(), [])[1])
            return msgs
        if knockdown and tc.get("big_meteor_crater", True):
            # the big one: a blast and the crater appears
            msgs += self.crater(xyz, now)
            if not tc.get("big_meteor_rock", False):
                self.knockdown()
                return msgs
        mode = tc.get("meteor_mode", "effect")
        if not knockdown and mode == "effect":
            return msgs + self._meteor_effect(xyz, now, lifetime, group)
        if not knockdown and mode == "entity":
            return msgs + self._falling_meteor(xyz, now, lifetime, group)
        if not tc.get("meteor_objects", False):
            # 2026-10-14 16:22: the meteor model shows as big grey "fur" columns
            # (wrong asset / not animated): no objects until the real one is found
            if knockdown:
                self.knockdown()
            return msgs
        # 2026-10-14 21:03: property 0x10000426 did not change the size. The
        # render component (VA 0x622F10) multiplies its scale by property
        # 0x6B4 (float; world state 0x2E001037 carries 0x6B4 = 2.1, and the
        # exe's SetScale at 0x58D650 writes 0x6B4) and by 0x450.
        scale = float(tc.get("big_meteor_scale", 1.0) if knockdown else tc.get("meteor_scale", 0.3))
        wstate = int(tc.get("meteor_wstate", METEOR_CLASS))
        slot = (self.meteor_count + 1) % 6 if m.cfg["combat"].get("prop_try_all_carriers", True) else None
        eid, msg = self._prop_object(wstate, xyz, now, slot, scale, "meteor")
        if group:
            self.meteor_groups = getattr(self, "meteor_groups", {})
            self.meteor_groups.setdefault(group, []).append(eid)
        msgs.append(msg)
        self.schedule(0.3, lambda: (self.run_scripts(eid, METEOR_PROBE_KEYS, "meteor start"), [])[1])
        life = METEOR_LIFETIME if lifetime is None else lifetime
        if life:
            self.schedule(life, lambda: [(f"meteor {eid:#x} removed", M.remove_object(eid))])
        if knockdown:
            self.knockdown()
        return msgs

    def _small_meteor_cloud(self, xyz):
        """2026-10-17 16:24 (original video 3:37.4-3:38.4): one big grey dust dome after the small
        meteors hit: the dust cloud 0x2E0007D4 at their centre ([tutorial] small_meteor_cloud_*)."""
        tc = self.match.cfg["tutorial"]
        eid, msg = self._prop_object(METEOR_DUST_CLASS, tuple(xyz), time.time(), 0,
                                     float(tc.get("small_meteor_cloud_scale", 1.5)), "small meteors' dust")
        self.schedule(0.2, lambda: (self.run_scripts(eid, METEOR_PROBE_KEYS, "small meteors' dust"), [])[1])
        self.schedule(float(tc.get("small_meteor_cloud_seconds", 3.0)),
                      lambda: [("small meteors' dust removed (0x3)", M.remove_object(eid))])
        self.log(f"tutorial: the small meteors' dust cloud at ({xyz[0]:.1f}, {xyz[1]:.1f})")
        return [msg]

    def _stp_meteor(self, xyz, now, lifetime, group, big):
        """2026-10-17 10:53 (tester, lab fase3-he "Model 1/6"): the falling meteors look like the
        Stolen Power Meteor Drop's rock stp_meteor 0x2E000928 (pack 0xA00000B3, graph 0x1C000053,
        read raw at server start). It is created at the spot and plays its own fall; after
        stp_meteor_impact s the rest of the impact (smoke, fire, sparks, the rock / crater)
        follows, and it is removed after stp_meteor_seconds."""
        tc = self.match.cfg["tutorial"]
        ws = int(tc.get("stp_meteor_wstate", STP_METEOR_WSTATE) or 0)
        scale = float(tc.get("big_stp_meteor_scale" if big else "stp_meteor_scale", 1.5 if big else 1.0))
        eid, msg = self._prop_object(ws, tuple(xyz), now, 0, scale, "falling meteor", raw_graph=True)
        secs = float(tc.get("stp_meteor_seconds", 3.0))
        if secs > 0:
            self.schedule(secs, lambda: [(f"falling meteor {eid:#x} removed (0x3)", M.remove_object(eid))])
        impact = float(tc.get("big_stp_meteor_impact" if big else "stp_meteor_impact", 1.0))
        self.schedule(impact, lambda: self._falling_meteor(xyz, time.time(), lifetime, group, big=big,
                                                           after_stp=True))
        self.log(f"tutorial: {'big ' if big else ''}meteor falls (stp_meteor {ws:#x}) at ({xyz[0]:.1f}, {xyz[1]:.1f}), "
                 f"impact in {impact:g} s")
        return [msg]

    def _falling_meteor(self, xyz, now, lifetime=None, group=None, height=None, big=False, after_stp=False):
        """2026-10-16 17:29 (tester): the meteors must be bigger, block the way
        and go away after a while. The rock (world state 0x2E000BB3) is created
        as an entity [tutorial] meteor_fall_height m above its spot and falls in
        meteor_fall_steps moves over meteor_fall_seconds; once down it is an
        obstacle (a box of meteor_block_half m) until meteor_lifetime_small s
        later (or until the next marker removes its group)."""
        m = self.match
        tc = m.cfg["tutorial"]
        if height is None and not after_stp and tc.get("stp_meteor", True) and int(
                tc.get("stp_meteor_wstate", STP_METEOR_WSTATE) or 0):
            return self._stp_meteor(xyz, now, lifetime, group, big)
        if height is None and tc.get("meteor_appear", True):
            # 22:11 (tester's video): a small meteor is a puff of smoke, then the
            # rock lies on the ground (no fall, no dust ring); and a carrier prop
            # ignores the server's moves anyway (it stayed where it was created).
            # Smoke now at the spot, the rock created there meteor_appear_delay s
            # later (the big one: at its impact, big_meteor_fall_seconds).
            out = []
            keys = [int(k) for k in tc.get("big_meteor_smoke_keys" if big else "meteor_smoke_keys",
                                           [0x10000347]) or []]
            if keys and tc.get("big_meteor_smoke" if big else "meteor_smoke", True):
                x, y, z = xyz
                seid, smsg = self._prop_object(METEOR_DUST_CLASS, (x, y, z), now, 0,
                                               float(tc.get("big_meteor_smoke_scale" if big else "meteor_smoke_scale",
                                                            1.0 if big else 0.6)), "meteor smoke")
                out.append(smsg)
                self.schedule(0.15, lambda: (self.run_scripts(seid, keys, "meteor smoke"), [])[1])
                self.schedule(float(tc.get("meteor_smoke_seconds", 3.0)),
                              lambda: [("meteor smoke removed (0x3)", M.remove_object(seid))])
            if not big and tc.get("meteor_fire", True) and self.meteor_event_ready():
                out += self._event_explosion(xyz, now, big=False)
            delay = float(tc.get("big_meteor_fall_seconds", 2.0) if big else tc.get("meteor_appear_delay", 0.5))
            # 2026-10-16 22:47 (tester's frames: a column of fire, then the smoke, then
            # the rock on the ground): the rocks now get their own scriptlet table
            # (0x1D0003B5; the record reader lost it before) and the event's own key
            # for them, Vfx_Spawn 0x10000032 (meteor_land_keys). The rock is created
            # meteor_key_lead s before it should lie there, so its animation plays.
            if [k for k in tc.get("meteor_land_keys", []) or []]:
                delay = max(0.0, delay - float(tc.get("big_meteor_key_lead" if big else "meteor_key_lead",
                                                      1.0 if big else 0.5)))
            if delay <= 0:
                return out + self._falling_meteor(xyz, now, lifetime, group, height=0.0, big=big)
            self.schedule(delay, lambda: self._falling_meteor(xyz, time.time(), lifetime, group, height=0.0, big=big))
            return out
        scale = float(tc.get("big_meteor_scale", 1.2) if big else tc.get("meteor_scale", 0.6))
        props = [(int(p), KIND_F32, scale) for p in ([tc.get("meteor_scale_property", 0x6B4)]
                                                      if not isinstance(tc.get("meteor_scale_property", 0x6B4), list)
                                                      else tc.get("meteor_scale_property")) if int(p)]
        height = float(tc.get("big_meteor_fall_height" if big else "meteor_fall_height", 22.0 if big else 18.0)) \
            if height is None else float(height)
        x, y, z = xyz
        self.meteor_count += 1
        label = f"Meteor{self.meteor_count}"
        ws = int(tc.get("big_meteor_wstate" if big else "small_meteor_wstate", METEOR_CLASS if big else METEOR_FRAGMENT))
        # 19:11 (tester): a straight drop is hardly seen from the top-down camera
        # ("no meteor falls, the crater just appears"): it comes in at a slant
        # from [tutorial] meteor_fall_from (dx, dy m; scaled for the big one)
        off = tc.get("big_meteor_fall_from" if big else "meteor_fall_from", [-14.0, 10.0] if big else [-6.0, 4.0]) \
            if height > 0 else [0.0, 0.0]
        sx, sy = x + float(off[0]), y + float(off[1])
        msgs = m.spawn("Meteor", now, attackable=False, xyz=(sx, sy, z + height), props=props, label=label, wstate=ws)
        ent = m.entities[max(m.entities)]
        if group:
            self.meteor_groups = getattr(self, "meteor_groups", {})
            self.meteor_groups.setdefault(group, []).append(ent.eid)
        steps = max(1, int(tc.get("big_meteor_fall_steps" if big else "meteor_fall_steps", 16 if big else 10))) \
            if height > 0 else 0
        secs = float(tc.get("big_meteor_fall_seconds" if big else "meteor_fall_seconds", 1.4 if big else 0.9)) \
            if height > 0 else 0.0
        for i in range(1, steps + 1):
            f = i / steps
            zz = z + height * (1 - f * f)            # falls faster and faster
            px, py = sx + (x - sx) * f, sy + (y - sy) * f
            last = i == steps

            def fall(zz=zz, px=px, py=py, last=last):
                if getattr(ent, "removed", False):
                    return []
                return m.move_entity(ent, (px, py, zz), time.time(), speed=0.0 if last else height / secs,
                                     heading=ent.heading)
            self.schedule(secs * f, fall)
        half = float(tc.get("meteor_block_half", 0.0))

        def landed():
            if getattr(ent, "removed", False):
                return []
            out = []
            ent.pos = [x, y, z]
            if half > 0:
                m.mover.obstacles[label] = self.meteor_obstacle(x, y)
            # 23:30 (diag): Vfx_Spawn 0x10000032 is accepted by the rock and shows nothing
            land_keys = [int(k) for k in tc.get("meteor_land_keys", []) or []]
            if land_keys:
                self.run_scripts(ent.eid, land_keys, "meteor lands")
            # 18:11 (tester): no sound, no dust. The effect 0x170001C4 (rock + dust +
            # mse_Meteor sounds) is tried as the rock's own property 0x1EB once it
            # lands ([tutorial] meteor_land_effect, 0 = off), and the dust cloud
            # 0x2E0007D4 (seen working as the car's blast) is placed there
            fx = int(tc.get("meteor_land_effect", METEOR_EFFECT_SCRIPT) or 0)
            if fx:
                ent.extra_props = [p for p in ent.extra_props if p[0] != 0x1EB] + [(0x1EB, KIND_DID, fx)]
                out.append((f"{label}: effect {fx:#x} (0x1EB)", m.entity_bundle(ent, time.time())))
            if tc.get("big_meteor_dust" if big else "meteor_dust", big):
                deid, dmsg = self._prop_object(METEOR_DUST_CLASS, (x, y, z), time.time(), 0,
                                               float(tc.get("big_meteor_dust_scale" if big else "meteor_dust_scale",
                                                            1.0 if big else 0.5)), "meteor dust")
                out.append(dmsg)
                self.schedule(0.2, lambda: (self.run_scripts(deid, METEOR_PROBE_KEYS, "meteor dust"), [])[1])
                self.schedule(float(tc.get("meteor_dust_seconds", 3.0)),
                              lambda: [("meteor dust removed (0x3)", M.remove_object(deid))])
            if tc.get("meteor_push", True) and not big:
                self.schedule(0.15, lambda: self._push_meteor(ent))
            return out
        self.schedule(secs + 0.05, landed)
        life = float(tc.get("meteor_lifetime_small", 20.0)) if lifetime in (None, 0) else float(lifetime)
        if life > 0:
            self.schedule(secs + life, lambda: self._remove_meteor(ent))
        return msgs

    def meteor_event_ready(self):
        """The meteor event's pack is part of this match (see [match] event_packs)."""
        return METEOR_EVENT_PACK in (getattr(self.match, "event_packs", None) or [])

    def _meteor_event(self, xyz, now, big=False, lifetime=None, group=None):
        """The game's own meteor event (template 0x1D00019C, see above) at xyz:
        an anchor prop with the template as 0x7D2 runs its scriptlet. The
        client draws the warning, the falling rock, the impact and plays the
        sounds. After meteor_event_impact s the spot blocks the way (small
        ones, until meteor_lifetime_small s) or the crater + knockdown come
        (the big one)."""
        from .wire import KIND_ARRAY
        m = self.match
        tc = m.cfg["tutorial"]
        probes = tc.get("meteor_event_probes")
        probes = METEOR_EVENT_PROBES if probes is None else probes
        if big and tc.get("big_meteor_event_probe", True):
            # the big one: warning, rock (its fall key), dust; crater + knockdown at impact
            steps = ((0.0, 0x2E0004E5, (0x1000018E, 0x10000078, 0x5), 0, 0, 0, 3.0),
                     (0.5, 0x2E0005F7, (0x10000032, 0x1000018E), 0, 0, 0, 0.0),
                     (float(tc.get("meteor_event_impact", 2.0)), 0x2E0007D4, (0x1000018E,), 0, 0, 0, 4.0))
            msgs = self._meteor_probe(xyz, now, steps, "big", lifetime=0.001)

            def hit():
                out = self.crater(xyz, time.time()) if tc.get("big_meteor_crater", True) else []
                self.knockdown()
                return out
            self.schedule(float(tc.get("meteor_event_impact", 2.0)), hit)
            return msgs
        if probes and not big:
            self.meteor_probe_n = getattr(self, "meteor_probe_n", -1) + 1
            return self._meteor_probe(xyz, now, probes[self.meteor_probe_n % len(probes)], self.meteor_probe_n + 1,
                                      lifetime, group)
        table = int(tc.get("meteor_event_table", METEOR_EVENT_TABLE))
        extra = [(SCRIPT_TABLE_PROPERTY, KIND_ARRAY, [(SCRIPT_TABLE_ELEMENT, KIND_DID, table)])]
        anchor = int(tc.get("meteor_event_anchor", METEOR_EVENT_WARNING))
        scale = float(tc.get("big_meteor_event_scale" if big else "meteor_event_scale", 1.0))
        eid, msg = self._prop_object(anchor, xyz, now, int(tc.get("meteor_event_carrier_slot", 0)), scale,
                                     "meteor event", extra=extra)
        self.meteor_event_ids = getattr(self, "meteor_event_ids", set()) | {eid}
        if group:
            self.meteor_groups = getattr(self, "meteor_groups", {})
            self.meteor_groups.setdefault(group, []).append(eid)
        keys = [int(k) for k in tc.get("meteor_event_keys") or METEOR_EVENT_KEYS]
        self.schedule(float(tc.get("meteor_event_delay", 0.1)),
                      lambda: (self.run_scripts(eid, keys, "meteor event"), [])[1])
        impact = float(tc.get("meteor_event_impact", 2.0))
        x, y, _z = xyz
        label = f"MeteorEvent{eid & 0xFFFF:x}"
        if big:
            def hit():
                out = self.crater(xyz, time.time()) if tc.get("big_meteor_crater", True) else []
                self.knockdown()
                return out
            self.schedule(impact, hit)
        else:
            half = float(tc.get("meteor_event_block_half", 0.6))
            if half > 0:
                self.schedule(impact, lambda: (m.mover.obstacles.__setitem__(label, self.meteor_obstacle(x, y)), [])[1])
            life = float(tc.get("meteor_lifetime_small", 20.0)) if lifetime in (None, 0) else float(lifetime)
            if life > 0:
                self.schedule(impact + life, lambda: (m.mover.obstacles.pop(label, None), [])[1])
        secs = float(tc.get("meteor_event_seconds", 0.0))
        if secs <= 0 and not big:
            secs = impact + (float(tc.get("meteor_lifetime_small", 20.0)) if lifetime in (None, 0) else float(lifetime))
        if secs > 0:
            self.schedule(secs, lambda: [(f"meteor event {eid:#x} removed", M.remove_object(eid))])
        self.log(f"tutorial: meteor event {table:#x} key(s) {' '.join(hex(k) for k in keys)} at "
                 f"({x:.1f}, {y:.1f}){' (big)' if big else ''}")
        return [msg]

    def _meteor_probe(self, xyz, now, steps, n, lifetime=None, group=None):
        """One meteor as a list of objects placed and started one after another
        (METEOR_EVENT_PROBES); logged as "meteor probe n" for the tester."""
        m = self.match
        tc = m.cfg["tutorial"]
        x, y, z = xyz
        msgs = []
        for step in steps:
            delay, ws, keys, dx, dy, dz, life = (list(step) + [0, 0, 0, 0])[:7]
            ws, keys = int(ws), [int(k) for k in keys or ()]
            pos = (x + float(dx), y + float(dy), z + float(dz))

            def place(ws=ws, keys=keys, pos=pos, life=float(life or 0)):
                eid, msg = self._prop_object(ws, pos, time.time(), int(tc.get("meteor_event_carrier_slot", 0)), 1.0,
                                             f"meteor probe {n}")
                self.meteor_event_ids = getattr(self, "meteor_event_ids", set()) | {eid}
                if group:
                    self.meteor_groups = getattr(self, "meteor_groups", {})
                    self.meteor_groups.setdefault(group, []).append(eid)
                if keys:
                    for i, k in enumerate(keys):     # one order each: a rejected one does not stop the next
                        self.schedule(0.1 + 0.05 * i, lambda k=k: (self.run_scripts(eid, [k], f"meteor probe {n}"), [])[1])
                if life > 0:
                    self.schedule(life, lambda: [(f"meteor probe {n} {eid:#x} removed", M.remove_object(eid))])
                return [msg]
            if float(delay) > 0:
                self.schedule(float(delay), place)
            else:
                msgs += place()
        self.log(f"tutorial: meteor probe {n} at ({x:.1f}, {y:.1f}): " +
                 " then ".join(f"{int(st[1]):#x}" for st in steps))
        half = float(tc.get("meteor_event_block_half", 0.6))
        label = f"MeteorProbe{n}"
        if half > 0:
            m.mover.obstacles[label] = self.meteor_obstacle(x, y)
            life = float(tc.get("meteor_lifetime_small", 20.0)) if lifetime in (None, 0) else float(lifetime)
            self.schedule(life, lambda: (m.mover.obstacles.pop(label, None), [])[1])
        return msgs

    def _meteor_effect(self, xyz, now, lifetime=None, group=None):
        """2026-10-16 17:59 (tester: "do it now"): the game's own falling meteor.
        World state 0x2E0002EC is the generic effect object 0x2E000013 (.entity
        0x2D000063) with property 0x1EB = effect 0x170001C4, which names the
        rock 0x2E000BB3, the dust cloud 0x2E0007D4 and three sounds of bank
        mse_Meteor (pack 0xA000024C, loaded by the tutorial). It is placed on
        the landing spot ([tutorial] meteor_effect_wstate, 0 = none) and removed
        after meteor_effect_seconds. meteor_effect_rock: once it has landed
        (meteor_effect_land s) the rock that stays is the entity of
        _falling_meteor, already on the ground (blocks the way, goes later)."""
        m = self.match
        tc = m.cfg["tutorial"]
        msgs = []
        ws = int(tc.get("meteor_effect_wstate", METEOR_EFFECT_WSTATE) or 0)
        if ws:
            extra = int(tc.get("meteor_effect_property", 0x1EB) or 0)
            eid, msg = self._prop_object(ws, xyz, now, int(tc.get("meteor_effect_carrier_slot", 0)),
                                         float(tc.get("meteor_effect_scale", 1.0)), "meteor effect",
                                         extra=[(extra, KIND_DID, int(tc.get("meteor_effect_script", METEOR_EFFECT_SCRIPT)))]
                                         if extra else None)
            msgs.append(msg)
            keys = [int(k) for k in tc.get("meteor_effect_keys", list(METEOR_PROBE_KEYS)) or []]
            if keys:
                self.schedule(0.1, lambda: (self.run_scripts(eid, keys, "meteor effect start"), [])[1])
            secs = float(tc.get("meteor_effect_seconds", 6.0))
            if secs > 0:
                self.schedule(secs, lambda: [(f"meteor effect {eid:#x} removed", M.remove_object(eid))])
        if tc.get("meteor_effect_rock", True):
            land = float(tc.get("meteor_effect_land", 1.0))

            def rock():
                return self._falling_meteor(xyz, time.time(), lifetime, group, height=0.0 if ws else None)
            if ws and land > 0:
                self.schedule(land, rock)
            else:
                msgs += rock()
        return msgs

    def meteor_obstacle(self, x, y):
        """2026-10-16 21:34 (tester): Batman still walked round the meteors well
        away from them. A box obstacle is grown by Batman's radius (0.6 m), so a
        0.3 m half box kept his centre 0.9 m away and the 0.6 m push never
        happened. A meteor is now an octagon given as the line his centre can
        not cross: [tutorial] meteor_block_radius m (0 = none) around it, less
        than meteor_push_radius so touching it pushes it."""
        r = float(self.match.cfg["tutorial"].get("meteor_block_radius", 0.45))
        if r <= 0:
            return [[x, y], [x, y], [x, y]]          # a point: blocks nothing
        return [[x + r * math.cos(math.pi / 8 + i * math.pi / 4), y + r * math.sin(math.pi / 8 + i * math.pi / 4)]
                for i in range(8)]

    def _push_meteor(self, ent):
        """18:11 (tester): touching a meteor with Batman should push it away from
        him. Every meteor_push_tick s while it lies there: if Batman is closer
        than meteor_push_radius m, the rock slides away along the line from him
        to it until it is meteor_push_radius + meteor_push_extra m away."""
        m = self.match
        tc = m.cfg["tutorial"]
        if getattr(ent, "removed", False) or ent.eid not in m.entities:
            return []
        out = []
        r = float(tc.get("meteor_push_radius", 0.9))
        bx, by = m.mover.pos[0], m.mover.pos[1]
        ex, ey, ez = ent.pos
        dx, dy = ex - bx, ey - by
        d = math.hypot(dx, dy)
        if d < r and not getattr(ent, "sliding", False):
            if d < 1e-3:
                dx, dy, d = math.cos(m.mover.heading), math.sin(m.mover.heading), 1.0
            ux, uy = dx / d, dy / d
            # 18:36 (tester): pushed rocks slid on forever and through buildings: the
            # slide is short, ends with a stop (speed 0) and is cut where a wall starts
            dist = r + float(tc.get("meteor_push_extra", 0.6)) - d
            step = 0.1
            free = 0.0
            # 21:47 (tester: Batman walks over them, they never move): the rock's
            # own obstacle blocked its slide test, so it never slid. Tested without it.
            own = m.mover.obstacles.pop(ent.name, None)
            try:
                while free + step <= dist and not m.mover.blocked(ex + ux * (free + step), ey + uy * (free + step)):
                    free += step
            finally:
                if own is not None:
                    m.mover.obstacles[ent.name] = own
            if free >= 0.1:
                nx, ny = ex + ux * free, ey + uy * free
                if ent.name in m.mover.obstacles:
                    m.mover.obstacles[ent.name] = self.meteor_obstacle(nx, ny)
                mode = tc.get("meteor_push_mode", "drift")
                if mode == "drift":
                    # 2026-10-16 23:30 (tester: they still vanish and reappear): every
                    # re-creation flickers. A carrier prop does take updates while it
                    # moves (speed > 0; only speed-0 ones are ignored), so the rock is
                    # sent moving in a few updates along the push (the client moves a
                    # prop along its heading, so the heading cannot spin it), and the
                    # last one keeps a crawl of meteor_stop_speed m/s instead of 0.
                    speed = max(0.5, float(tc.get("meteor_glide_speed", 2.5)))
                    secs = free / speed
                    steps = max(1, int(tc.get("meteor_roll_steps", 4)))
                    crawl = float(tc.get("meteor_stop_speed", 0.01))
                    ent.sliding = True
                    for i in range(steps + 1):
                        f = i / steps
                        px, py = ex + ux * free * f, ey + uy * free * f

                        def drift(px=px, py=py, last=(i == steps)):
                            if last:
                                ent.sliding = False
                            if getattr(ent, "removed", False):
                                return []
                            return m.move_entity(ent, (px, py, ez), time.time(),
                                                 speed=crawl if last else speed,
                                                 heading=math.atan2(uy, ux))
                        if i == 0:
                            out = drift()
                        else:
                            self.schedule(secs * f, drift)
                elif mode == "glide":
                    # 2026-10-16 22:47 (tester: "they vanish and show up a bit further on"):
                    # the stepped re-creation looked like jumps. A carrier prop does follow
                    # a speed > 0 (the client moves it along its heading) but ignores the
                    # later stop, so: re-created once moving away from Batman, then once
                    # more, standing, where it has got to (meteor_glide_speed m/s).
                    speed = max(0.5, float(tc.get("meteor_glide_speed", 2.5)))
                    secs = free / speed
                    ent.sliding = True
                    ent.pos = [ex, ey, ez]
                    ent.heading = math.atan2(uy, ux)
                    ent.speed = speed
                    out = [(f"{ent.name} rolls: removed (0x3)", M.remove_object(ent.eid)),
                           (f"{ent.name} rolls towards ({nx:.1f}, {ny:.1f}) at {speed:g} m/s",
                            m.entity_bundle(ent, time.time()))]

                    def stop(nx=nx, ny=ny):
                        ent.sliding = False
                        if getattr(ent, "removed", False):
                            return []
                        ent.pos = [nx, ny, ez]
                        ent.speed = 0.0
                        return [(f"{ent.name} stops: removed (0x3)", M.remove_object(ent.eid)),
                                (f"{ent.name} stops at ({nx:.1f}, {ny:.1f})", m.entity_bundle(ent, time.time()))]
                    self.schedule(secs, stop)
                elif mode == "recreate":
                    # 22:11 (tester): the rocks never moved on screen although
                    # their moves were sent: a carrier-built prop ignores later
                    # position updates (and Batman walked through the rock left
                    # behind). The rock is removed and created again where it
                    # slid to (same object id).
                    # 22:36 (tester): it should roll away, not jump: a few short
                    # re-creations along the way, turning a little each time
                    steps = max(1, int(tc.get("meteor_roll_steps", 4)))
                    secs = float(tc.get("meteor_roll_seconds", 0.4))
                    turn = math.radians(float(tc.get("meteor_roll_turn", 35.0)))
                    ent.sliding = True
                    for i in range(1, steps + 1):
                        f = i / steps
                        px, py = ex + ux * free * f, ey + uy * free * f

                        def roll(px=px, py=py, last=(i == steps)):
                            if last:
                                ent.sliding = False
                            if getattr(ent, "removed", False):
                                return []
                            ent.pos = [px, py, ez]
                            ent.speed = 0.0
                            ent.heading += turn
                            return [(f"{ent.name} rolls: removed (0x3)", M.remove_object(ent.eid)),
                                    (f"{ent.name} rolls to ({px:.1f}, {py:.1f})", m.entity_bundle(ent, time.time()))]
                        if i == 1:
                            out = roll()
                        else:
                            self.schedule(secs * (i - 1) / steps, roll)
                else:
                    steps = max(1, int(tc.get("meteor_push_steps", 5)))
                    secs = float(tc.get("meteor_push_seconds", 0.3))
                    ent.sliding = True
                    for i in range(1, steps + 1):
                        f = i / steps
                        f = 1 - (1 - f) * (1 - f)          # eases out
                        px, py = ex + ux * free * f, ey + uy * free * f

                        def slide(px=px, py=py, last=(i == steps)):
                            if last:
                                ent.sliding = False
                            if getattr(ent, "removed", False):
                                return []
                            return m.move_entity(ent, (px, py, ez), time.time(), speed=0.0, heading=ent.heading)
                        self.schedule(secs * i / steps, slide)
        self.schedule(float(tc.get("meteor_push_tick", 0.15)), lambda: self._push_meteor(ent))
        return out

    def _remove_meteor(self, ent):
        m = self.match
        if getattr(ent, "removed", False):
            return []
        ent.removed = True
        m.entities.pop(ent.eid, None)
        m.mover.obstacles.pop(ent.name, None)
        return [(f"{ent.name} removed (0x3)", M.remove_object(ent.eid))]

    def raise_events(self, events, what):
        """Graph events on Batman through _HFSM_BehaviorRaiseEventAction
        (0x100001E3, event id in script variable 0x780)."""
        for ev in events:
            self.run_scripts(M.CHAMPION_AGENT_ID, (RAISE_EVENT_KEY,), f"{what}: graph event {ev:#x}",
                             [(RAISE_EVENT_VAR, M.KIND_ENUM, ev)])
        return []

    def _champion_ambient(self, delay=None):
        """2026-10-16 21:59 (tester): Gaslight Batman's suit has no electricity
        running over its two antennas. Candidates from his own scriptlet table
        (data/batman_actions.tsv): SpawnIdle 0x10000183 and FX_Spawn 0x10000119,
        started one by one on him at the start and after he gets up
        ([tutorial] champion_ambient_keys, [] = off; diag --scripts tells which
        are accepted)."""
        tc = self.match.cfg["tutorial"]
        keys = [int(k) for k in tc.get("champion_ambient_keys", []) or []]
        d = float(tc.get("champion_ambient_delay", 1.0) if delay is None else delay)
        for i, k in enumerate(keys):
            self.schedule(d + 0.3 * i, lambda k=k: (self.run_scripts(M.CHAMPION_AGENT_ID, [k],
                                                                     f"Batman ambient {k:#x}"), [])[1])
        # 2026-10-16 22:47 (tester's frames of the original): when the tutorial starts
        # Batman beams in (vertical light streaks) and a blue electric glow runs over
        # him before his health bar shows. The scriptlets above are accepted and show
        # nothing; his graph has the state Spawn 0x10000154 with the event
        # RunScript_FX_Spawn 0x1000006B, raised now at the start (champion_spawn_events)
        if delay is None:
            # 2026-10-17 23:09 (tester: the end-of-spawn graph events lit nothing): champion_start_keys run on
            # him once, at the start only (Cinematic_Hidden 0x100009EB: its own action type raises SpawnIdle,
            # the state that follows Spawn, without Spawn's respawn clip and its voice line)
            skeys = [int(k) for k in tc.get("champion_start_keys", []) or []]
            if skeys:
                self.schedule(float(tc.get("champion_spawn_delay", 0.0)), lambda: (
                    self.run_scripts(M.CHAMPION_AGENT_ID, skeys, "Batman start (antennas)"), [])[1])
            events = [int(e) for e in tc.get("champion_spawn_events", [0x1000006B]) or []]
            if events and not getattr(self, "spawn_raised", False):
                self.schedule(float(tc.get("champion_spawn_delay", 0.0)),
                              lambda: self.raise_events(events, "Batman spawn"))
            # 2026-10-17 18:05 (tester + full video at 0.1 s): he starts covered in a silver hex shimmer
            # with thin white lines coming down on him (~5 s), then a cyan ring wave at his feet and
            # he is normal. Scriptlet table 0x33000000: FX_Spawn 0x10000119 / FX_Spawn_End
            # 0x1000005A. FX_Spawn alone left the "rope" (the lines) on him: it is now ended
            # champion_spawn_seconds later (champion_spawn_keys / champion_spawn_end_keys).
            self._champion_fx_tour()
            start = [int(k) for k in tc.get("champion_spawn_keys", []) or []]
            end = [int(k) for k in tc.get("champion_spawn_end_keys", []) or []]
            sd = float(tc.get("champion_spawn_delay", 0.0))
            if start:
                self.schedule(sd, lambda: (
                    self.run_scripts(M.CHAMPION_AGENT_ID, start, "Batman spawn (FX_Spawn)"), [])[1])
            if end:
                self.schedule(sd + float(tc.get("champion_spawn_seconds", 2.5)), lambda: (
                    self.run_scripts(M.CHAMPION_AGENT_ID, end, "Batman spawn end (FX_Spawn_End)"), [])[1])

    def _champion_fx_tour(self):
        """2026-10-17 18:25 (tester): neither the white shimmer before the match nor the electricity
        between the antennas showed. Vfx_Bmg_Active 0x10000180 and FX_Spawn_End 0x1000005A are not
        in Batman's own scriptlet table (data/batman_actions.tsv), so the client drops them.
        Candidates that are in it, named from table 0x33000000: _Defeat_OnRespawn 0x100001FC (the
        respawn phase-in), Vfx_Bmg_Echoes_Active 0x10000198 (his passive), Vfx_Active_State0
        0x1000005D. [tutorial] champion_fx_tour = [[s after the start, key, label], ...]: each runs
        on Batman and its label shows as the objective text for champion_fx_label_seconds, so
        the tester can say which one makes which effect. [] = off."""
        tc = self.match.cfg["tutorial"]
        tour = tc.get("champion_fx_tour") or []
        keep = float(tc.get("champion_fx_label_seconds", 4.0))
        for at, key, label in tour:
            # 19:09: a key or a list of keys; an empty label = no objective text
            keys = [int(k) for k in (key if isinstance(key, (list, tuple)) else [key])]

            def go(keys=keys, label=str(label)):
                before = self.objective_text
                self.run_scripts(M.CHAMPION_AGENT_ID, keys, f"Batman fx test {label} "
                                 + " ".join(f"{k:#x}" for k in keys))
                self.log(f"tutorial: Batman fx test '{label}' " + " ".join(f"{k:#x}" for k in keys))
                if keep > 0 and label:
                    self.schedule(keep, lambda: self._objective(before) if self.objective_text == label else [])
                    return self._objective(label)
                return []
            self.schedule(float(at), go)

    def knockdown(self):
        """The big meteor knocks Batman down.

        2026-10-16 (his behavior graph 0x1A0002E7 and its Lua): _Defeat_OnIncapacitated
        enters SM_Death, whose state is Death_Selection, set 50/50 by
        onStandardDeath() on every return to walking: face up (Death_A) or face
        down (Death_B), while the get-up (SM_Get_Up) is always the face-down one.
        So by default ([tutorial] knockdown_mode = "face_down") the graph events
        are raised directly: CbtState_Knockdown (the knockdown clip, end pose
        held), CbtState_Dead a little later (frozen face-down pose, the get-up's
        first frame), then CbtState_GetUp (face-down get-up; it returns to
        walking by itself). "incapacitated" = the old scriptlets."""
        tc = self.match.cfg["tutorial"]
        hold = float(tc.get("knockdown_hold", 5.0)) * float(tc.get("pacing", 1.0))
        # 2026-10-16 20:08 (tester): pressing a direction while he was still on
        # the ground slid him along lying down. The marker's lock ran from the
        # marker, and the meteor event hits later than the old rock did, so it
        # ended before the get-up. He now stays locked from the fall until
        # knockdown_hold + knockdown_getup_seconds later.
        extra = float(tc.get("knockdown_getup_seconds", 1.5))
        if extra >= 0:
            self.lock(time.time(), float(tc.get("knockdown_hold", 5.0)) + extra, "on the ground")
        if str(tc.get("knockdown_mode", "face_down")) == "face_down":
            self.raise_events([int(e) for e in tc.get("knockdown_events") or KNOCKDOWN_EVENTS],
                              "Batman knocked down (face down)")
            snap = float(tc.get("knockdown_snap_delay", 1.8))
            snap_events = [int(e) for e in tc.get("knockdown_snap_events", list(KNOCKDOWN_SNAP_EVENTS)) or []]
            if snap > 0 and snap_events:
                self.schedule(snap, lambda: self.raise_events(snap_events, "Batman lies face down"))
            if hold > 0:
                getup = [int(e) for e in tc.get("getup_events") or GETUP_EVENTS]
                keys = [int(k) for k in tc.get("getup_fx_keys", list(GETUP_FX_KEYS)) or []]

                def up():
                    if keys:
                        self.run_scripts(M.CHAMPION_AGENT_ID, keys, "get-up effect")
                    self._champion_ambient(1.5)
                    return self.raise_events(getup, "Batman gets up (face down)")
                self.schedule(hold, up)
            return
        self.run_scripts(M.CHAMPION_AGENT_ID, [int(k) for k in tc.get("knockdown_keys") or KNOCKDOWN_KEYS],
                         "Batman knocked down")
        keys = [int(k) for k in tc.get("getup_keys") or GETUP_KEYS]
        if hold > 0 and keys:
            self.schedule(hold, lambda: (self.run_scripts(M.CHAMPION_AGENT_ID, keys, "Batman gets up"), [])[1])

    def _prop_object(self, wstate, xyz, now, slot, scale, what, eid=None, extra=None, scripts=True,
                     raw_graph=False, heading=None):
        """A placed prop (world state through a carrier class, cell 251 of the
        layout) with optional scale. Returns (object id, message)."""
        m = self.match
        tc = m.cfg["tutorial"]
        if eid is None:                   # (an eid = the same object again, moved)
            self.meteor_count += 1
            # 2026-10-15: PING_OBJECT_ID + 0x100 + n ran into the server's entity
            # ids (0x...100 up): its own range now
            eid = PROP_OBJECT_BASE_ID + self.meteor_count
        spawn = m.mover.spawn
        # 2026-10-17: the map's own landblock (Tutorial 2's lab; Tutorial 1 = 0x13CB as before)
        pos = (spawn[0], spawn[1], spawn[2], m.cfg["combat"].get("scenery_cell", 251)) + tuple(xyz)
        cls = prop_class(wstate, m.cfg, slot)
        props = []
        prop_ids = tc.get("meteor_scale_property", 0x6B4)
        if not isinstance(prop_ids, (list, tuple)):
            prop_ids = [prop_ids]
        if abs(scale - 1.0) > 1e-6:
            props = [(int(p), KIND_F32, float(scale)) for p in prop_ids if int(p)]
        props += list(extra or [])
        if what == "crater":
            raw = tc.get("crater_props")
            for pid, kind, value in (() if raw is None else CRATER_PROPS if raw == "template" else raw):
                kind = _PROP_KINDS[str(kind)]
                props.append((int(pid), kind, float(value) if kind == KIND_F32 else int(value)))
        carrier = m.cfg["combat"].get("prop_carrier") or 0
        if cls >> 24 == 0x2E and carrier:
            cls, props = carrier, props + [(WSTATE_PROPERTY, KIND_DID, wstate)]
        if cls != wstate and wstate >> 24 == 0x2E and scripts:
            # its world state's scriptlet templates (meteors, dust, the sphere)
            props = props + script_table_props(wstate, m.cfg, raw_graph)
        module = M.scenery_module(m.cfg) if cls >> 24 == 0x2E else m.module
        if heading is None:
            heading = float(tc.get("crater_yaw", 0.0)) if what == "crater" else 0.0
        label = f"{what} {self.meteor_count} ({cls:#x}) at ({xyz[0]:.0f}, {xyz[1]:.0f}, {xyz[2]:.0f}) scale {scale:g}"
        return eid, (label, M.create_object(eid, cls, now, position=pos, module=module, heading=heading,
                                            second_seq=m.second_seq, properties=props))

    def crater(self, xyz, now, _later=False, keep_id=False):
        """The big meteor's crater (+ its start scripts as the blast).
        [tutorial] crater_mode: "wstate" = world state 0x2E0004BE placed like
        the meteor rocks (which render); "entity" = entity 0x400004FD."""
        m = self.match
        tc = m.cfg["tutorial"]
        if tc.get("crater_mode", "wstate") == "entity":
            return m.spawn("Crater", now, attackable=False, xyz=tuple(xyz))
        explosion = []
        if not _later and tc.get("big_meteor_explosion", True) and self.meteor_event_ready():
            explosion = self._event_explosion(xyz, now, big=True)
            # 2026-10-17 18:46 (tester): the crater popped up at once; the blast must start in the
            # middle of the crater and cover it appearing: the crater comes crater_delay s later
            cd = float(tc.get("crater_delay", 0.3))
            if cd > 0:
                saved_id = getattr(self, "crater_id", None)

                def later():
                    out = self.crater(tuple(xyz), time.time(), _later=True)
                    if keep_id:
                        self.crater_id = saved_id
                    return out
                self.schedule(cd, later)
                return explosion
        if tc.get("crater_set", "old") == "event" and self.meteor_event_ready():
            return explosion + self._event_crater(xyz, now)
        if tc.get("crater_set", "old") == "lava":
            # 23:53: the lava crater the map already has by the bank is three world
            # states placed on one spot (landblock 0x13cb, (38.31, 66.99)):
            # 0x2E001144 / 45 / 46 (.entity 0x2D000E6B / 6C / 6D, pack 0xA000024C;
            # 46 carries a warm light). [tutorial] crater_set = "old" = 0x2E0004BE.
            lx, ly = tc.get("lava_crater_at") or LAVA_CRATER_AT
            pos = (float(lx), float(ly), xyz[2])
            msgs = []
            for ws in tc.get("lava_crater_wstates") or LAVA_CRATER_WSTATES:
                eid, msg = self._prop_object(int(ws), pos, now, int(tc.get("lava_carrier_slot", 0)),
                                             1.0, "crater")
                msgs.append(msg)
            self.crater_id = eid
            self.log(f"tutorial: lava crater at ({pos[0]:.1f}, {pos[1]:.1f})")
            return explosion + msgs
        wstate = int(tc.get("crater_wstate", CRATER_WSTATE))
        slot = int(tc.get("crater_carrier_slot", 1))
        eid, msg = self._prop_object(wstate, xyz, now, slot, float(tc.get("crater_scale", 1.0)), "crater")
        self.crater_id = eid
        self.log(f"tutorial: crater {eid:#x} (world state {wstate:#x}) at ({xyz[0]:.1f}, {xyz[1]:.1f})")
        # 22:28: still no lava. The other tutorial's placement list 0x1D0008CC puts
        # world state 0x2E000A9F next to its craters; its .entity 0x2D0008B6 is a
        # flat 6 x 6 m piece (0.18 m high): probably the lava pool.
        # [tutorial] crater_extras = [[world state, dx, dy], ...]
        extra_msgs = []
        # 00:04: the bank's set (0x2E001144-46) was not it either (pale glowing
        # pit). 0x2E0005D6 uses the crater's own entity 0x400004FD, three meshes
        # and colour 0x2A0 = 0xFF0000FF (red): the lava, laid over the crater.
        for extra in tc.get("crater_extras", []) or []:
            ws, dx, dy = int(extra[0]), float(extra[1]), float(extra[2])
            pos = (xyz[0] + dx, xyz[1] + dy, xyz[2])
            extra_msgs.append(self._prop_object(ws, pos, now, slot, 1.0, "crater extra")[1])
            self.log(f"tutorial: crater extra {ws:#x} at ({pos[0]:.1f}, {pos[1]:.1f})")
        if tc.get("crater_blast", True):
            keys = [int(k) for k in tc.get("crater_keys") or CRATER_KEYS]
            self.schedule(0.2, lambda: (self.run_scripts(eid, keys, "crater blast"), [])[1])
        return explosion + [msg] + extra_msgs

    def _event_explosion(self, xyz, now, big=False, scale=None, secs=None, offset=None, shockwaves=True):
        """2026-10-16 23:30 (tester, fase3-gs): 0x2E0004E7 is not the crater but the
        explosion (fire and smoke), and it never ended: the meteor event gives it a
        lifetime (20 s at its big impact) and the server never removed it. Now it is
        removed after big_meteor_explosion_seconds / meteor_fire_seconds. Its key
        0x10000039 was rejected (its table allows another one), so none is run.
        The small meteors use it smaller as their fire column (meteor_fire)."""
        m = self.match
        tc = m.cfg["tutorial"]
        if big:
            dx, dy = (float(v) for v in (offset if offset is not None else tc.get("event_crater_offset", [3.2, 0.3])))
            pos = (xyz[0] + dx, xyz[1] + dy, xyz[2])
        else:
            pos = tuple(xyz)
        ws = int(tc.get("event_crater_wstate", EVENT_CRATER))
        if scale is None:
            scale = float(tc.get("big_meteor_explosion_scale" if big else "meteor_fire_scale", 1.0 if big else 0.35))
        if secs is None:
            secs = float(tc.get("big_meteor_explosion_seconds" if big else "meteor_fire_seconds", 4.0 if big else 2.0))
        eid, msg = self._prop_object(ws, pos, now, int(tc.get("event_crater_carrier_slot", 0)), scale,
                                     "explosion" if big else "meteor fire")
        out = [msg]
        # 2026-10-17 10:37 (tester, lab fase3-hd): the big explosion is 0x2E0004E7 with its graph set
        # and key 0x10000526 (event_crater_keys); the small meteors' fire keeps its own
        # (meteor_fire_keys, none by default)
        keys = [int(k) for k in tc.get("event_crater_keys" if big else "meteor_fire_keys", []) or []]
        if keys:
            self.schedule(0.1, lambda: (self.run_scripts(eid, keys, "explosion" if big else "meteor fire"), [])[1])
        if tc.get("big_meteor_sparks" if big else "meteor_sparks", big):
            out += self._sparks(pos, now, big)
        if secs > 0:
            self.schedule(secs, lambda: [(f"explosion {eid:#x} removed (0x3)", M.remove_object(eid))])
        if big and shockwaves:
            for wsw, wsecs, wscale in tc.get("event_crater_shockwaves", EVENT_SHOCKWAVES) or []:
                weid, wmsg = self._prop_object(int(wsw), pos, now, 0, float(wscale), "shockwave")
                out.append(wmsg)
                self.schedule(0.1, lambda weid=weid: (self.run_scripts(weid, [0x1000018E], "shockwave"), [])[1])
                self.schedule(float(wsecs), lambda weid=weid: [(f"shockwave {weid:#x} removed (0x3)",
                                                                M.remove_object(weid))])
        return out

    def _sparks(self, pos, now, big):
        """10:37 (tester, lab "Model 8/16b"): the sparks are 0x2E0006DA with its scriptlet
        templates and keys 0x1000018E / 0x10000032 / 0x10000078 (the meteor event creates 8 of
        them at the big impact). [tutorial] sparks_wstate / sparks_keys / sparks_seconds /
        sparks_scale; big_meteor_sparks (on) and meteor_sparks (small meteors, off)."""
        tc = self.match.cfg["tutorial"]
        ws = int(tc.get("sparks_wstate", SPARKS_WSTATE) or 0)
        if not ws:
            return []
        scale = float(tc.get("sparks_scale", 1.0) if big else tc.get("meteor_sparks_scale", 0.5))
        eid, msg = self._prop_object(ws, pos, now, 0, scale, "sparks")
        keys = [int(k) for k in tc.get("sparks_keys", SPARKS_KEYS) or []]
        if keys:
            self.schedule(0.3, lambda: (self.run_scripts(eid, keys, "sparks"), [])[1])
        secs = float(tc.get("sparks_seconds", 4.0))
        if secs > 0:
            self.schedule(secs, lambda: [(f"sparks {eid:#x} removed (0x3)", M.remove_object(eid))])
        return [msg]

    def _event_crater(self, xyz, now):
        """2026-10-16 22:47 (tester: "that crater should have its own model"): the
        meteor event's template 0x1D00019C, at the big impact, creates (action 0xc)
        0x2E0004E7 for 20 s with key 0x10000039 (.entity 0x2D000392: a mesh with a
        collision shape, like the old crater's 0x2D000375), the shockwaves
        0x2E0004ED (5 s) and 0x2E0006DE (1 s) with 0x1000018E, and the dust cloud.
        Pack 0xA000009A ([match] event_packs). [tutorial] crater_set = "old" goes
        back to 0x2E0004BE."""
        m = self.match
        tc = m.cfg["tutorial"]
        dx, dy = (float(v) for v in tc.get("event_crater_offset", [3.2, 0.3]))
        pos = (xyz[0] + dx, xyz[1] + dy, xyz[2])
        ws = int(tc.get("event_crater_wstate", EVENT_CRATER))
        eid, msg = self._prop_object(ws, pos, now, int(tc.get("event_crater_carrier_slot", 0)),
                                     float(tc.get("event_crater_scale", 1.0)), "crater")
        self.crater_id = eid
        self.log(f"tutorial: event crater {eid:#x} (world state {ws:#x}) at ({pos[0]:.1f}, {pos[1]:.1f})")
        keys = [int(k) for k in tc.get("event_crater_keys", [0x10000039]) or []]
        if keys:
            self.schedule(0.1, lambda: (self.run_scripts(eid, keys, "event crater"), [])[1])
        return [msg]

    def remove_meteors(self, group):
        eids = getattr(self, "meteor_groups", {}).pop(group, [])
        out = []
        for eid in eids:
            ent = self.match.entities.get(eid)
            if ent is not None:
                out += self._remove_meteor(ent)
            elif self.match.cfg["tutorial"].get("meteor_mode", "entity") != "entity" or \
                    eid in getattr(self, "meteor_event_ids", ()):
                out.append((f"meteor {eid:#x} removed ({group})", M.remove_object(eid)))
        return out

    def scenery(self, now):
        """Static map pieces of the first area (vehicle, drone gates)."""
        out = []
        cc = self.match.cfg["combat"]
        if cc.get("vehicle_blocks", True):
            # the street vehicle blocks the way until Catwoman breaks it (even while
            # the client does not show it): [combat] vehicle_box = [half length, half width]
            (vx, vy, _), yaw = LAYOUT["DestVehicle"][1], LAYOUT["DestVehicle"][2]
            hl, hw = cc.get("vehicle_box", [4.0, 1.6])
            self.match.mover.obstacles["DestVehicle"] = (vx, vy, float(hl), float(hw), yaw)
            self.log("tutorial: the street vehicle blocks the way")
        for ob in cc.get("obstacles", []):
            name, rest = str(ob[0]), ob[1:]
            if len(rest) == 1:                                # polygon
                pts = [(float(x), float(y)) for x, y in rest[0]]
                self.match.mover.obstacles[name] = pts
                self.log(f"tutorial: obstacle {name} ({len(pts)} corners)")
            else:                                             # box
                self.match.mover.obstacles[name] = tuple(float(v) for v in rest)
                self.log(f"tutorial: obstacle {name} at ({float(rest[0]):.1f}, {float(rest[1]):.1f})")
        for name in SCENERY:
            out += self.match.spawn(name, now, attackable=False)
        out += self.bridge.gate_obstacles(now)   # the blue gates on the bridge block the way
        if self.match.cfg["combat"].get("prop_try_all_carriers", True):
            # test: the same vehicle with each of the 6 carriers (diag --entities
            # shows which one builds without "step 3 (components)")
            base = int(self.match.cfg["combat"].get("prop_carrier_slot", 0)) % 6
            for slot in range(6):
                if slot == base:
                    continue
                out += self.match.spawn("DestVehicle", now, attackable=False, carrier_slot=slot)
                ent = self.match.entities[max(self.match.entities)]
                ent.name = f"DestVehicle~{slot}"
        self.vehicle_state = 0
        return out

    # ---- the street vehicle breaks in steps (Destructible_AdvanceState) ------------
    def _vehicle(self):
        return next((e for e in self.match.entities.values() if e.name == "DestVehicle"), None)

    def advance_vehicle(self, reason):
        """One step more broken (state 1 = damaged, 2 = wreck)."""
        v = self._vehicle()
        last = int(self.match.cfg["tutorial"].get("vehicle_states", 2))
        if not v or getattr(self, "vehicle_state", 0) >= last:
            return []
        self.vehicle_state = getattr(self, "vehicle_state", 0) + 1
        keys = [int(k) for k in self.match.cfg["tutorial"].get("vehicle_break_keys", VEHICLE_BREAK_KEYS)]
        self.log(f"tutorial: vehicle state {self.vehicle_state} ({reason})")
        self.run_scripts(v.eid, keys, f"vehicle breaks a step ({reason})")
        return []

    def break_vehicle(self, now, reason):
        """All the way to the wreck."""
        last = int(self.match.cfg["tutorial"].get("vehicle_states", 2))
        for i in range(max(0, last - getattr(self, "vehicle_state", 0))):
            self.schedule(0.4 * i, lambda: self.advance_vehicle(reason))
        return []

    def _cinematic_blast(self, xyz):
        """17:43 (tester): in the Catwoman cinematic nothing falls: the ground blows up and a crater
        opens. The big meteor's crater and explosion (crater()) without the falling rock; the
        tutorial's own crater (crater_id) is kept."""
        tc = self.match.cfg["tutorial"]
        if not tc.get("catwoman_blast_crater", False):
            # 21:40 (tester): two craters were left that should not be there (by the gate and where
            # the vehicle stood): the blast only, no crater
            self.log(f"tutorial: blast in the Catwoman cinematic at ({xyz[0]:.1f}, {xyz[1]:.1f})")
            return self._event_explosion(tuple(xyz), time.time(), big=True, offset=(0.0, 0.0),
                                         scale=float(tc.get("catwoman_blast_scale", 0.7)))
        saved = getattr(self, "crater_id", None)
        saved_scale = tc.get("big_meteor_explosion_scale")
        tc["big_meteor_explosion_scale"] = float(tc.get("catwoman_blast_scale", 0.7))
        try:
            out = self.crater(tuple(xyz), time.time(), keep_id=True)
        finally:
            if saved_scale is None:
                tc.pop("big_meteor_explosion_scale", None)
            else:
                tc["big_meteor_explosion_scale"] = saved_scale
            self.crater_id = saved
        self.log(f"tutorial: blast and crater in the Catwoman cinematic at ({xyz[0]:.1f}, {xyz[1]:.1f})")
        return out

    def _vehicle_destroyed(self, blast=True):
        """Catwoman's blow: the vehicle goes (its explosion is not reproduced yet:
        it accepts no scriptlets, diag 2026-10-14 15:52) and the way opens."""
        m = self.match
        tc = m.cfg["tutorial"]
        m.mover.obstacles.pop("DestVehicle", None)
        out = []
        pos = None
        for ent in list(m.entities.values()):
            if ent.name.startswith("DestVehicle"):
                if ent.name == "DestVehicle":
                    pos = tuple(ent.pos)
                out.append(("vehicle destroyed by Catwoman (0x3)", M.remove_object(ent.eid)))
                del m.entities[ent.eid]
        if out:
            self.log("tutorial: Catwoman destroys the vehicle")
        # 2026-10-17 17:08 (tester's video vs the original 5:03): the vehicle only vanished; in the
        # original it blows up in a big yellow blast. The big meteor's explosion (0x2E0004E7 with
        # its key, shockwaves, sparks) where it stood (vehicle_blast, scale vehicle_blast_scale).
        if blast and pos and tc.get("vehicle_blast", True) and self.meteor_event_ready():
            # 17:43 (tester's video): at the meteor's size it filled the screen with the shockwave, flying
            # rocks and a yellow cloud; the original is a fireball about the vehicle's size with burning
            # pieces, gone in ~1 s. Smaller, shorter, no shockwaves (vehicle_blast_shockwaves).
            out += self._event_explosion(pos, time.time(), big=True, offset=(0.0, 0.0),
                                         scale=float(tc.get("vehicle_blast_scale", 0.45)),
                                         secs=float(tc.get("vehicle_blast_seconds", 1.5)),
                                         shockwaves=bool(tc.get("vehicle_blast_shockwaves", False)))
            self.log(f"tutorial: the vehicle blows up at ({pos[0]:.1f}, {pos[1]:.1f})")
        return out

    def batarang_at_vehicle(self, xyz, now):
        """Q thrown at the vehicle (no drone on the way): Batman throws it and
        the vehicle breaks one step when it arrives."""
        v = self._vehicle()
        if not v or math.hypot(xyz[0] - v.pos[0], xyz[1] - v.pos[1]) > VEHICLE_HIT_RADIUS:
            return []
        if now < getattr(self, "batarang_ready", 0):
            return []
        self.batarang_ready = now + BATARANG_COOLDOWN
        m = self.match
        bx, by, _ = m.mover.pos
        m.mover.heading = math.atan2(v.pos[1] - by, v.pos[0] - bx)
        m.sequence += 1
        keys = tuple(m.cfg["tutorial"].get("batarang_keys") or BATARANG_CAST_KEYS)
        self.run_scripts(M.CHAMPION_AGENT_ID, keys, "Sonic Batarang at the vehicle",
                         [(M.PROP_SCRIPT_TARGET, KIND_IID, v.eid)])
        self.schedule(BATARANG_FLIGHT, lambda: self.advance_vehicle("Sonic Batarang"))
        self.schedule(BATARANG_FLIGHT + BATARANG_HOP, lambda: (
            self.run_scripts(M.CHAMPION_AGENT_ID, BATARANG_STOP_KEYS, "Sonic Batarang over"), [])[1])
        self.log("Sonic Batarang: at the vehicle")
        return [("Batman faces the vehicle", m.champion_bundle(now))]

    def lock(self, now, seconds, reason):
        """Batman cannot move for `seconds` (x pacing)."""
        seconds *= float(self.match.cfg["tutorial"].get("pacing", 1.0))
        if seconds > 0:
            self.locked_until = max(self.locked_until, now + seconds)
            self.lock_reason = reason
            self.lock_logged = False
            mv = self.match.mover
            if mv.target is not None:                         # stop where he is
                mv.target, mv.speed = None, 0.0
            self.log(f"tutorial: Batman cannot move for {seconds:.1f} s ({reason})")

    def at_target(self, passing=False):
        """Batman stands on the current marker (2026-10-14 14:26: 3.5 m was far
        too wide; he has to step onto it: [tutorial] marker_radius where he
        stops, marker_pass_radius while walking through)."""
        xyz = self.targets.get(self.step)
        tc = self.match.cfg["tutorial"]
        radius = float(tc.get("marker_pass_radius", 0.6) if passing else tc.get("marker_radius", TARGET_RADIUS))
        if not xyz:
            # 2026-10-14 15:17: the drone's marker has no spot until the drone
            # appears; "no target = arrived" skipped it (and its lines) at once
            return self.step != self.drone_step
        return self.match.mover.distance_to(xyz) <= radius

    def arrived(self, now, passing=False):
        beats = MOVE_STEPS.get(self.step)
        if not beats or not self.at_target(passing):
            return []
        if self.step == self.drone_step and self.phase != "first_drone":
            # the drone was beaten before he stepped on its marker: just clear it
            self.step += 1
            return self.remove_ping(self.step - 1)
        self.step += 1
        msgs = self.remove_ping(self.step - 1)
        drone_now = self.step == self.drone_step and self.phase == "walk"
        if drone_now:
            beats = tuple(b for b in beats if b[1] != "ping")
        if self.step == 2 and self.match.cfg["tutorial"].get("meteors", True):
            # "after 4 steps a big meteor falls behind him and he falls down"
            # 2026-10-14 16:42: on the marker the falling meteor is heard; 1 s later
            # it hits behind him and he falls; up after 5 s; 1.5 s more before he
            # can move, the next marker showing 1 s into it (drone_appear_delay)
            tc = self.match.cfg["tutorial"]
            big = tuple(tc.get("big_meteor") or BIG_METEOR)
            delay = float(tc.get("knockdown_delay", 1.0)) * float(tc.get("pacing", 1.0))
            # 2026-10-17 16:24: Batman can walk sooner now (start_lock 2.8): never before the small
            # meteors have hit + big_meteor_after_small s (original: 3:37.1 -> 3:38.9)
            done = getattr(self, "small_meteors_done", 0.0)
            if done:
                delay = max(delay, done + float(tc.get("big_meteor_after_small", 0.8)) - now)
            self.schedule(delay, lambda: self.meteor(big, time.time(), knockdown=True, lifetime=0))   # the crack stays
            self.lock(now, float(tc.get("knockdown_lock", 7.5)), "knocked down by the meteor")
        msgs += self.beats(beats, now)
        if drone_now:
            # he gets up first; then the drone and the human are seen fighting
            delay = float(self.match.cfg["tutorial"].get("drone_appear_delay", 6.5))
            delay *= float(self.match.cfg["tutorial"].get("pacing", 1.0))
            if delay > 0:
                self.schedule(delay, lambda: self._drone_appears(time.time()))
            else:
                msgs += self._drone_appears(now)
        return msgs

    def _drone_appears(self, now):
        """The drone from cinematic 0x35000033 appears ahead and the guide
        arrows point at it."""
        if self.phase != "walk":          # already out (scheduled + walked up to it)
            return []
        self.log("tutorial: the drone and the human appear fighting")
        self.phase = "first_drone"
        gone = self.remove_meteors("small")       # "the 3 first meteors disappear" with the next marker
        # the second marker goes on the ground next to the fight, not under the
        # drone (2026-10-14 14:26); [tutorial] drone_marker, [] = at the drone
        dm = self.match.cfg["tutorial"].get("drone_marker") or LAYOUT[FIRST_DRONE][1]
        self.targets[self.drone_step] = tuple(float(v) for v in dm)
        msgs = list(gone)
        ping = self.ping(self.drone_step, now)
        if ping:
            msgs.append(("guide ping at the drone", ping))
        msgs += self.match.spawn(FIRST_DRONE, now)
        thug = self.match.spawn(THUG, now, attackable=False)
        if thug:
            self.thug_eid = max(self.match.entities)
            drone = next(e for e in self.match.entities.values() if e.name == FIRST_DRONE)
            t = self.match.entities[self.thug_eid]
            t.heading = math.atan2(drone.pos[1] - t.pos[1], drone.pos[0] - t.pos[0])
            t.yaw_offset = float(self.match.cfg["tutorial"].get("thug_yaw_offset", THUG_YAW_OFFSET))
            # 23:42: "a little to one side so he is in front of the drone": keep
            # the facing, shift him [tutorial] thug_shift m (screen right = world
            # (+0.78, -0.63))
            dx, dy = self.match.cfg["tutorial"].get("thug_shift", THUG_SHIFT)
            t.pos = [t.pos[0] + float(dx), t.pos[1] + float(dy), t.pos[2]]
            drone.heading = math.atan2(t.pos[1] - drone.pos[1], t.pos[0] - drone.pos[0])
            msgs += thug + [("thug faces the drone", self.match.entity_bundle(t, now)),
                            ("drone faces the thug", self.match.entity_bundle(drone, now))]
            self.schedule(1.0, self._fight)
        return msgs

    def _spawn_effect(self, names):
        """The drones 'teleport in': Vfx_Spawn, then Vfx_Fade_In, spread over
        ~1.5 s ([tutorial] spawn_sequence; the old spawn_keys still works)."""
        tc = self.match.cfg["tutorial"]
        seq = tc.get("spawn_sequence")
        if seq is None and tc.get("spawn_keys") is not None:
            seq = [(0.1 + 0.8 * i, k) for i, k in enumerate(tc["spawn_keys"])]
        seq = SPAWN_SEQUENCE if seq is None else seq
        for e in list(self.match.entities.values()):
            if e.name in names and e.alive:
                for delay, key in seq:
                    self.schedule(float(delay), lambda eid=e.eid, name=e.name, key=int(key): (
                        self.run_scripts(eid, (key,), f"{name} teleports in ({key:#x})"), [])[1])

    def _attack_key(self, eid, ent=None):
        """Next attack script for this drone (they are tried in turn)."""
        keys = self.match.cfg["tutorial"].get("drone_attack_keys") or DRONE_ATTACK_KEYS
        if getattr(ent, "role", None) == "ranged":
            keys = self.match.cfg["tutorial"].get("ranged_attack_keys") or keys
        n = self.attack_count.get(eid, 0)
        self.attack_count[eid] = n + 1
        entry = keys[n % len(keys)]
        combo = tuple(int(k) for k in entry) if isinstance(entry, (list, tuple)) else (int(entry),)
        e = self.match.entities.get(eid)
        self.log(f"{e.name if e else hex(eid)}: attack scripts {'+'.join(f'{k:#x}' for k in combo)} (hit {n + 1})")
        return combo

    def immune_to_basic(self, ent):
        """The yellow target drones only take the skill they are there for."""
        if getattr(ent, "only_slot", None):
            return True
        return ent.name in PRACTICE and self.match.cfg["tutorial"].get("practice_immune", True)

    def wrong_attack(self, ent, slot):
        """Superman's line when a target drone is hit by the wrong attack."""
        return self.bridge.wrong_attack(ent, slot) if getattr(ent, "only_slot", None) else []

    def skill_hit(self, ent, damage, slot):
        """Damage from a skill (slot), unless the target only takes another one."""
        only = getattr(ent, "only_slot", None)
        if only and only != slot:
            self.log(f"{ent.name}: only skill slot {only} hurts it (hit by slot {slot})")
            return self.wrong_attack(ent, slot)
        msgs = self.attacked(ent, time.time())
        self.damage(ent, damage)
        return msgs

    # ---- W, E and D (batman.py) ----------------------------------------------------
    def sonic_shell(self, point, target, now):
        from . import batman
        return batman.sonic_shell(self, point, target, now)

    def bat_flight(self, point, target, now):
        from . import batman
        return batman.bat_flight(self, point, target, now)

    def bat_scream(self, point, target, now):
        from . import batman
        return batman.bat_scream(self, point, target, now)

    def scream_result(self, hit):
        return self.bridge.scream_result(hit)

    def resend(self, ent, delays=(1.0, 3.0)):
        """Send a placed object again a little later. 2026-10-15 13:11 (diag
        --create): the vehicle at the end of the bridge was never built by the
        client from its first message, only when it was moved (lifted)."""
        for d in self.match.cfg["tutorial"].get("prop_resend", delays) or ():
            self.schedule(float(d), lambda: [] if getattr(ent, "removed", False) or ent.eid not in self.match.entities
                          else [(f"{ent.name} sent again", self.match.entity_bundle(ent, time.time()))])

    def cinematic_done(self, did, now):
        """A cinematic ended on the client; None = not one the tutorial waits for."""
        return self.finale.cinematic_done(did, now)

    def carrying(self):
        return self.finale.carrying

    def throw(self, xyz, how):
        return self.finale.throw(xyz, how)

    def super_strength(self, xyz, target, now):
        """F (slot 8): lift the car, or throw it when carrying it."""
        if self.finale.carrying:
            return self.finale.throw(tuple(target.pos) if target is not None else xyz, "F")
        return self.finale.lift("F", xyz)

    def preference(self, name, value, now):
        """A client preference change (event 0x216E), e.g. User.CameraLocked."""
        if name == "User.CameraLocked" and self.phase == "bridge":
            return self.bridge.camera_lock_changed(value.lower() == "true", now)
        return []

    def stolen_power(self, point, now, how="D"):
        """D: Gaslight Batman's surveillance camera."""
        return self.bridge.place_camera(point or tuple(self.match.mover.pos), now, how)

    def rank_slots(self):
        """The skill slots whose '+' the tutorial is waiting for (() = none)."""
        if self.phase == "skills":
            return (Q_SLOT,)
        return tuple(self.bridge.pending_ranks)

    def rank_slot(self):
        """The recommended one of rank_slots() (None = none)."""
        slots = self.rank_slots()
        return slots[0] if slots else None

    def after_catwoman(self, now):
        return self.bridge.start(now)

    def batarang(self, target, now):
        """Q: Batman throws the Sonic Batarang at target; it ricochets."""
        m = self.match
        if now < getattr(self, "batarang_ready", 0):
            return []
        self.batarang_ready = now + BATARANG_COOLDOWN
        tc = m.cfg["tutorial"]
        bx, by, _ = m.mover.pos
        m.mover.heading = math.atan2(target.pos[1] - by, target.pos[0] - bx)
        batman.root(self, now, reason="Sonic Batarang")
        m.sequence += 1
        msgs = [("Batman faces the Batarang target", m.champion_bundle(now))]
        keys = tuple(tc.get("batarang_keys") or BATARANG_CAST_KEYS)
        self.run_scripts(M.CHAMPION_AGENT_ID, keys, f"Sonic Batarang at {target.name}",
                         [(M.PROP_SCRIPT_TARGET, KIND_IID, target.eid)])
        chain, last = [target], target
        others = [e for e in m.entities.values() if e.alive and e.attackable and e is not target]
        for _ in range(BATARANG_BOUNCES):
            near = [e for e in others if e not in chain and e.distance_to(last.pos[:2]) <= BATARANG_RICOCHET_RANGE]
            if not near:
                break
            last = min(near, key=lambda e: e.distance_to(last.pos[:2]))
            chain.append(last)
        self.log("Sonic Batarang: " + " -> ".join(e.name for e in chain))
        damage = int(tc.get("batarang_damage", BATARANG_DAMAGE))
        for i, e in enumerate(chain):
            def hit(e=e):
                if not e.alive:
                    return []
                self.run_scripts(e.eid, BATARANG_HIT_KEYS, f"Batarang hits {e.name}",
                                 [(M.PROP_SCRIPT_TARGET, KIND_IID, M.CHAMPION_AGENT_ID)])
                if getattr(e, "only_slot", None) or getattr(e, "group", None):
                    return self.skill_hit(e, damage, Q_SLOT)
                self.damage(e, damage)
                return []
            self.schedule(BATARANG_FLIGHT + BATARANG_HOP * i, hit)
        self.schedule(BATARANG_FLIGHT + BATARANG_HOP * len(chain), lambda: (
            self.run_scripts(M.CHAMPION_AGENT_ID, BATARANG_STOP_KEYS, "Sonic Batarang over"), [])[1])
        self.batarang_casts += 1
        return msgs

    def batarang_at_point(self, xyz, now):
        """Q with nothing to hit: Batman still throws it towards the cursor
        (17:36: nothing was shown at all)."""
        m = self.match
        if xyz is None or now < getattr(self, "batarang_ready", 0):
            return []
        self.batarang_ready = now + BATARANG_COOLDOWN
        bx, by, _ = m.mover.pos
        if abs(xyz[0] - bx) + abs(xyz[1] - by) > 1e-3:
            m.mover.heading = math.atan2(xyz[1] - by, xyz[0] - bx)
        batman.root(self, now, reason="Sonic Batarang")
        m.sequence += 1
        keys = tuple(m.cfg["tutorial"].get("batarang_keys") or BATARANG_CAST_KEYS)
        self.run_scripts(M.CHAMPION_AGENT_ID, keys, "Sonic Batarang (no target)")
        self.schedule(BATARANG_FLIGHT + BATARANG_HOP, lambda: (
            self.run_scripts(M.CHAMPION_AGENT_ID, BATARANG_STOP_KEYS, "Sonic Batarang over"), [])[1])
        self.log("Sonic Batarang: no target, thrown towards the cursor")
        return [("Batman faces the Batarang throw", m.champion_bundle(now))]

    def _drone_ai(self):
        """Aggressive drones walk up to Batman and hit him (every 0.4 s)."""
        m = self.match
        tc = m.cfg["tutorial"]
        tick = float(tc.get("drone_tick", DRONE_TICK))
        walk = float(tc.get("drone_walk_speed", DRONE_WALK_SPEED))
        self.schedule(tick, self._drone_ai)
        if self.phase in ("done",):
            return []
        bx, by, bz = m.mover.pos
        now = time.time()
        out = []
        for e in list(m.entities.values()):
            if not (e.alive and e.attackable) or e.name in PRACTICE or getattr(e, "role", None) == "target":
                continue
            d = math.hypot(e.pos[0] - bx, e.pos[1] - by)
            leash = getattr(e, "leash", None) or DRONE_LEASH * (1.75 if e.name in WAVE else 1.0)
            if e.eid in self.aggressive and d > leash:
                self.aggressive.discard(e.eid)
                self.log(f"{e.name}: Batman is {d:.1f} m away, stops chasing")
            if e.eid not in self.aggressive:
                if e.name in WAVE and d < float(m.cfg["tutorial"].get("wave_aggro_radius", DRONE_AGGRO_RADIUS)):
                    self.aggressive.add(e.eid)
                    self.wave_quiet = False
                    self.log(f"{e.name}: leaves the vehicle and goes for Batman ({d:.1f} m)")
                else:
                    continue
            reach = (float(tc.get("ranged_attack_range", RANGED_ATTACK_RANGE))
                     if getattr(e, "role", None) == "ranged" else DRONE_ATTACK_RANGE)
            if d > reach:
                if now >= self.walk_logged.get(e.eid, 0):
                    self.walk_logged[e.eid] = now + 2.0
                    self.log(f"{e.name}: walks to Batman ({d:.1f} m)")
                # 2026-10-14 16:22: drones "jumped": each update sent the point
                # one tick AHEAD (the client then ran on from there and snapped).
                # Now: send where it IS, heading and speed, then advance; and walk
                # round the wagon / boxes instead of through them.
                from .world import route
                pts = route(m.mover.obstacles, e.pos, (bx, by), radius=0.4)
                wx, wy = pts[1] if len(pts) > 1 else (bx, by)
                last_leg = len(pts) <= 2
                dw = math.hypot(wx - e.pos[0], wy - e.pos[1]) or 1e-6
                step = min(walk * tick, (d - reach * 0.8) if last_leg else dw)
                e.heading = math.atan2(wy - e.pos[1], wx - e.pos[0])
                e.speed = walk
                out.append((f"{e.name} walks", m.entity_bundle(e, now)))
                e.pos = [e.pos[0] + (wx - e.pos[0]) / dw * step, e.pos[1] + (wy - e.pos[1]) / dw * step, e.pos[2]]
                continue
            if now < self.next_hit.get(e.eid, 0):
                continue
            self.next_hit[e.eid] = now + DRONE_ATTACK_INTERVAL
            e.heading = math.atan2(by - e.pos[1], bx - e.pos[0])
            out += m.move_entity(e, tuple(e.pos), now, speed=0.0)
            keys = self._attack_key(e.eid, e)
            self.log(f"{e.name}: hits Batman ({d:.1f} m)")
            self.run_scripts(e.eid, keys, f"{e.name} hits Batman",
                             [(M.PROP_SCRIPT_TARGET, KIND_IID, M.CHAMPION_AGENT_ID)])
            self.run_scripts(M.CHAMPION_AGENT_ID, BATMAN_HIT_KEYS, "Batman hit")
            hp, hp_max = m.vitals[0]
            m.vitals[0] = (max(1, hp - DRONE_DAMAGE), hp_max)
            out.append((f"Batman takes {DRONE_DAMAGE} ({m.vitals[0][0]}/{hp_max}) (0x42)",
                        M.vitals(M.CHAMPION_AGENT_ID, m.vitals)))
            self.last_hit_at = now
        return out

    def _bridge_tick(self):
        """Every 0.25 s: the bridge's markers and gates, and Batman's healing."""
        self.schedule(0.25, self._bridge_tick)
        now = time.time()
        return self.bridge.camera_tick(now) + self.bridge.update(now) + self.finale.update(now) + self._regen(now)

    def _regen(self, now):
        """'The Construct is healing him': Batman never dies in the tutorial. Out
        of combat he heals ([tutorial] regen_per_second); low on health he gets
        a quick heal and Superman's warning (once)."""
        m = self.match
        hp, hp_max = m.vitals[0]
        out = []
        if hp < hp_max * 0.25:
            m.vitals[0] = (int(hp_max * 0.6), hp_max)
            if not self.low_health_said:
                self.low_health_said = True
                out += self.say(0x1CE)
            return out + [("Batman healed by the Construct (0x42)", M.vitals(M.CHAMPION_AGENT_ID, m.vitals))]
        rate = float(m.cfg["tutorial"].get("regen_per_second", 8.0))
        if hp < hp_max and rate > 0 and now - getattr(self, "last_hit_at", 0.0) > 4.0:
            if now - getattr(self, "last_regen", 0.0) >= 1.0:
                self.last_regen = now
                m.vitals[0] = (min(hp_max, hp + int(rate)), hp_max)
                out.append(("Batman regenerates (0x42)", M.vitals(M.CHAMPION_AGENT_ID, m.vitals)))
        return out

    def _hit_vehicle(self):
        """The wave drones hit the vehicle until Batman attacks one of them."""
        m = self.match
        if not getattr(self, "wave_quiet", False):
            return []
        vehicle = next((v for v in m.entities.values() if v.name == "DestVehicle"), None)
        target = [(M.PROP_SCRIPT_TARGET, KIND_IID, vehicle.eid)] if vehicle else None
        for e in m.entities.values():
            if e.name in WAVE and e.alive and e.eid not in self.aggressive:
                keys = self._attack_key(e.eid)
                self.run_scripts(e.eid, keys, f"{e.name} hits the vehicle ({keys[0]:#x})", target)
        self.schedule(FIGHT_INTERVAL, self._hit_vehicle)
        return []

    def _fight(self):
        """One exchange of the drone-vs-human fight; repeats until Batman attacks."""
        m = self.match
        drone = next((e for e in m.entities.values() if e.name == FIRST_DRONE and e.alive), None)
        thug = m.entities.get(self.thug_eid)
        if self.first_attack_done or not drone or not thug:
            return []
        keys = self._attack_key(drone.eid)
        self.run_scripts(drone.eid, keys, f"drone hits the human ({keys[0]:#x})")
        self.run_scripts(thug.eid, THUG_HIT_KEYS, "human hit")
        tc = m.cfg["tutorial"]
        back = tc.get("thug_attack_keys")
        back = THUG_ATTACK_KEYS if back is None else tuple(int(k) for k in back)
        if back:
            def swing_back():
                if self.first_attack_done or not drone.alive:
                    return []
                self.run_scripts(thug.eid, back, "human hits the drone")
                self.run_scripts(drone.eid, DRONE_HIT_KEYS, "drone hit")
                return []
            self.schedule(FIGHT_INTERVAL / 2, swing_back)
        self.schedule(FIGHT_INTERVAL, self._fight)
        return []

    def near_drone(self, now):
        """Called while walking: getting close to the drone's spot skips the
        remaining walk steps (the player found it on their own)."""
        if self.phase != "walk" or not self.step or self.step >= self.drone_step:
            return []                     # after the first marker it appears on its own timer
        if not self.match.cfg["tutorial"].get("skip_markers", False):
            # 2026-10-14 19:39: walking past the first marker must not start the
            # next one: every marker has to be stepped on, in order
            return []
        if self.match.mover.distance_to(LAYOUT[FIRST_DRONE][1]) > DRONE_TRIGGER_RADIUS:
            return []
        msgs = self.remove_ping(self.step)
        # what the skipped steps would have said (the last one: the drone's lines)
        skipped = []
        while self.step < self.drone_step:
            skipped = [b for b in MOVE_STEPS.get(self.step, ()) if b[1] != "ping"]
            self.step += 1
        return msgs + self.beats(skipped) + self._drone_appears(now)

    def attacked(self, entity, now):
        bridge_msgs = self.bridge.attacked(entity) or []
        if (entity.name in WAVE or entity.name == FIRST_DRONE) and entity.eid not in self.aggressive:
            self.aggressive.add(entity.eid)
            self.log(f"{entity.name}: attacked, turns on Batman")
            if entity.name in WAVE:
                # 2026-10-14 20:12: attacking one of the two drones at the vehicle
                # turns BOTH on Batman
                for other in self.match.entities.values():
                    if (other.name in WAVE and other.eid not in self.aggressive
                            and other.alive and not getattr(other, "removed", False)):
                        self.aggressive.add(other.eid)
                        self.wave_quiet = False
                        self.log(f"{other.name}: its partner was attacked, turns on Batman")
        if self.first_attack_done:
            return bridge_msgs
        self.first_attack_done = True
        msgs = bridge_msgs
        thug = self.match.entities.get(self.thug_eid)
        if thug:
            # the human runs away from the fight, then leaves
            # run in small steps (the client animates each one), then leave
            # around the wagon and the boxes, not through them
            from .world import route
            sz = thug.pos[2]
            thug.yaw_offset = 0.0           # 23:42: the fight's turn made his run look wrong
            # 00:00: he vanished mid-run: the fog of war hid him behind the boxes /
            # wagon. He leaves the fight for good, so the fog no longer applies.
            thug.no_fog = True
            pts = route(self.match.mover.obstacles, thug.pos, THUG_FLEE_TO)
            speed, dt = 5.0, 0.15
            xyzs = []
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / (speed * dt))))
                xyzs += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n, sz) for k in range(1, n + 1)]
            steps = len(xyzs)
            for i, xyz in enumerate(xyzs, 1):
                self.schedule(dt * i, lambda xyz=xyz, last=(i == steps): self.match.move_entity(
                    thug, xyz, time.time(), speed=0.0 if last else speed))
            eid = thug.eid
            self.log(f"tutorial: the human runs away ({len(pts) - 2} corners, {steps * dt:.1f} s)")
            def gone(thug=thug, eid=eid):
                thug.removed = True
                return [("thug gone (0x3)", M.remove_object(eid))]
            self.schedule(dt * steps + 1.5, gone)
        return msgs

    def killed(self, entity, now):
        m = self.match
        if str(getattr(entity, "group", None) or "").startswith("finale"):
            return self.finale.killed(entity, now)
        if getattr(entity, "group", None):
            return self.bridge.killed(entity, now)
        if self.phase == "first_drone" and entity.name == FIRST_DRONE:
            # 01:05 These metallic monsters... / 01:09 Not so fast, Batman. More drones
            # are coming! (+ the wave) / 01:12 Once you start attacking... + hint
            self.phase = "wave"
            msgs = self.remove_ping(self.drone_step, keep_visible=True)
            return msgs + self.beats((
                (0.5, "conv", 0x1E1), (4.0, "conv", 0x1E0), (5.0, "call", self._wave),
                (7.0, "conv", 0x38C), (7.0, "hint", HINT_BASIC_ATTACK)))
        if self.phase == "wave" and entity.name in WAVE:
            left = sum(1 for e in m.entities.values() if e.alive and e.name in WAVE)
            if left:
                return self._objective(WAVE_OBJECTIVE.format(len(WAVE) - left))
            # 01:22 Good job! (+ level 2) / 01:24 Beyond his basic attack... /
            # 01:29 Use a skill point... + highlighted Q
            self.phase = "skills"
            return self._objective(WAVE_OBJECTIVE.format(len(WAVE))) + self.beats((
                (0.5, "conv", 0x1DF), (0.5, "call", self._level_up),
                (2.5, "conv", 0x1D4), (7.5, "call", self._skill_prompt)))
        if self.phase == "practice" and not any(e.alive and e.name in PRACTICE for e in m.entities.values()):
            # After the Batarang: "When you use a skill, it goes 'on cooldown'..." /
            # "...consumed 'Will'..." / "It appears the path forward is blocked."
            # then Catwoman breaks the vehicle.
            self.phase = "catwoman"
            # "It appears the path forward is blocked." (0x1AF) is the first line of
            # the Catwoman cinematic itself (conversation flag 0x4000, like 0x358 and
            # 0x357), so the server does not start it: it played twice (2026-10-14).
            # Each line waits for the previous one to be spoken (2026-10-14: the
            # cinematic cut Superman's 'Will' line).
            will_at = 2.0 + CONV_SECONDS[0x19A] + 0.5
            msgs = self.beats(((2.0, "conv", 0x19A), (will_at, "conv", 0x1E3)))
            cin = m.cfg["tutorial"].get("catwoman_cinematic", CATWOMAN_CINEMATIC)
            if cin:
                delay = m.cfg["tutorial"].get("catwoman_delay")
                pacing = float(m.cfg["tutorial"].get("pacing", 1.0))
                if delay:
                    self.schedule(float(delay) * pacing + 0.5, lambda: self._catwoman(cin))
                else:
                    # once 0x1E3 is sent, wait for the whole queue to be spoken
                    # 2026-10-14 11:39: "the time between the last line and the
                    # cinematic is too long, halve it": the estimate was generous
                    scale = float(m.cfg["tutorial"].get("catwoman_wait_scale", 0.5))

                    def go():
                        wait = max(0.0, (getattr(self, "speech_end", 0.0) - time.time()) * scale) + 0.5 * pacing
                        self.schedule(wait, lambda: self._catwoman(cin))
                        return []
                    self.schedule(will_at * pacing + 0.1, go)
            else:
                # no cinematic: part 2 (the bridge) starts once the lines are spoken
                self.schedule(will_at * pacing + 0.1, lambda: self.after_speech(1.0 * pacing, lambda: (
                    self._vehicle_destroyed() + self.bridge.start(time.time()))))
            return msgs
        return []

    def _wave(self):
        """'More drones are coming!': the wave teleports in by the vehicle."""
        m = self.match
        now = time.time()
        msgs = []
        if m.cfg["tutorial"].get("meteors", True):
            msgs += self.meteor(WAVE_METEOR, now)          # "not so fast, Batman": another one falls
        override = m.cfg["tutorial"].get("wave_positions") or WAVE_POSITIONS
        for name in WAVE:
            msgs += m.spawn(name, now, xyz=tuple(override[name]) if name in override else None)
        self._spawn_effect(WAVE)
        vehicle = next((e for e in m.entities.values() if e.name == "DestVehicle"), None)
        if vehicle:
            for e in m.entities.values():
                if e.name in WAVE:
                    e.heading = math.atan2(vehicle.pos[1] - e.pos[1], vehicle.pos[0] - e.pos[0])
                    msgs.append((f"{e.name} faces the vehicle", m.entity_bundle(e, now)))
            self.wave_quiet = True
            self.schedule(1.0, self._hit_vehicle)
        self.log("tutorial: the wave arrives")
        return msgs + self._objective(WAVE_OBJECTIVE.format(0))

    def _level_up(self):
        m = self.match
        m.level, m.xp, m.skill_points = 2, 0, 1
        m.skill_ranks = set_recommended(m.skill_ranks, Q_SLOT)    # orange frame + arrow on Q
        m.sequence += 1      # a higher sequence so the client applies the new property values
        msgs = [("champion level 2 + skill point", m.champion_bundle(time.time()))]
        # Only Q's upgrade button: the W/E/R/passive ones stay hidden (never
        # restored), so only Q shows the rank-up animation (2026-10-14).
        others = () if m.cfg["tutorial"].get("restore_other_upgrades", False) else OTHER_UPGRADE_BUTTONS
        if not m.cfg["tutorial"].get("skill_point_reminder", False):
            # 2026-10-14 14:44: every skill still showed the rank-up animation; the
            # "spend your skill point" reminder is the candidate (only Q should)
            others = tuple(others) + (HUD["SkillPointSpendReminder"],)
        msgs += [(f"HUD element {e} restored (0x213d)", M.hud_element(e, HUD_EVENT_FIRST_RESTORED))
                 for e in SKILL_ELEMENTS if e not in others]
        # 2026-10-16 14:41 (tester): a yellow "+" just above the passive, left of the
        # skills bar (not the red rank-up "+"). Elements the tutorial never uses
        # are hidden explicitly: the Stolen Power T-skill slot 21, the Artifact
        # Foundry button 24, the artifact slots 29 and Recall 43 ([tutorial]
        # hide_hud_elements, UIHUDElementID numbers)
        for e in m.cfg["tutorial"].get("hide_hud_elements", HIDDEN_HUD_ELEMENTS) or ():
            msgs.append((f"HUD element {int(e)} hidden (0x213d)", M.hud_element(int(e), HUD_EVENT_HIDE)))
        msgs.append(("champion vitals (0x42)", M.vitals(M.CHAMPION_AGENT_ID, m.vitals)))
        msgs.append((f"tutorial hint {HINT_EXPERIENCE}", M.tutorial_hint(HINT_EXPERIENCE)))
        return msgs

    def _skill_prompt(self):
        if self.phase != "skills":        # Q was already ranked: no prompt, no highlight
            return []
        msgs = self.say(0x1BE) + [
                ("highlight Q upgrade button (0x213d)",
                 M.hud_element(FIRST_SKILL_UPGRADE, HUD_EVENT_SHOW_HIGHLIGHT))]
        if self.match.cfg["tutorial"].get("lock_other_skills", False):
            msgs += [(f"HUD element {e} hidden: only Q can be ranked (0x213d)", M.hud_element(e, HUD_EVENT_HIDE))
                     for e in OTHER_UPGRADE_BUTTONS]
        msgs.append((f"tutorial hint {HINT_SKILL_POINTS}", M.tutorial_hint(HINT_SKILL_POINTS)))
        msgs.append((f"tutorial hint {HINT_SKILL_RANKS}", M.tutorial_hint(HINT_SKILL_RANKS)))
        if self.on_skill_prompt:
            self.on_skill_prompt()
        return msgs + self._objective(SKILL_OBJECTIVE)

    def _catwoman(self, cin):
        m = self.match
        out = []
        tc = m.cfg["tutorial"]
        # she breaks the vehicle during the cinematic ([tutorial] vehicle_break_at
        # seconds after it starts; the wreck stays, see vehicle_keep_wreck)
        at = float(tc.get("vehicle_break_at", 6.0))
        if at >= 0:
            self.schedule(at, self._vehicle_destroyed)
        # 2026-10-17 17:08 (original 5:08.7 / 5:11.8): meteors keep falling during the cinematic, a
        # fire column and a smoke wave. [seconds into the cinematic, dx, dy] from the vehicle
        # (catwoman_meteors; [] = off); small meteors, gone after catwoman_meteor_lifetime s.
        if tc.get("meteors", True) and not getattr(self, "catwoman_over", False):
            base = VEHICLE_SPOT
            for at_m, dx, dy in tc.get("catwoman_meteors") or []:
                xyz = (base[0] + float(dx), base[1] + float(dy), base[2])
                self.schedule(float(at_m), lambda xyz=xyz: [] if getattr(self, "catwoman_over", False)
                              else self._cinematic_blast(xyz))
        if tc.get("cinematic_place_champion", True):
            xyz, heading = CATWOMAN_CINEMATIC_BATMAN
            m.mover.place(xyz, heading)
        if tc.get("cinematic_hide_champion", True):
            m.champion_hidden = True        # shown again when the cinematic ends (state 4)
        if tc.get("cinematic_place_champion", True) or tc.get("cinematic_hide_champion", True):
            m.sequence += 1
            out.append(("Batman placed / hidden for the cinematic", m.champion_bundle(time.time())))
        return out + [(f"Catwoman cinematic {cin:#x} (0x20f5)", M.cinematic(cin))]

    def skill_ranked(self, now, auto=False, slot=Q_SLOT):
        """A skill's '+' was clicked (the patched client sends RankSkill as a
        ping). The first one is Q; the later ones belong to the bridge."""
        if self.phase != "skills":
            return self.bridge.ranked(slot, now, auto)
        if slot != Q_SLOT:
            return []
        m = self.match
        self.phase = "practice"
        m.skill_points = 0
        m.skill_ranks = set_recommended(m.skill_ranks, None) | 1 << (4 * Q_SLOT)   # Q at rank 1
        m.sequence += 1
        msgs = [("champion skill point spent" + (" (automatic)" if auto else ""), m.champion_bundle(now))]
        if m.cfg["tutorial"].get("hide_upgrade_buttons"):
            msgs += [(f"HUD element {e} hidden (0x213d)", M.hud_element(e, HUD_EVENT_HIDE))
                     for e in UPGRADE_ELEMENTS]
        # 01:36 You can learn more... / 01:40 Construct: Can we have some target
        # drones? (they appear) / 01:43 Practice your new skill... + objective
        return msgs + self.beats((
            (0.5, "conv", 0x19B), (4.5, "conv", 0x1AB), (5.5, "call", self._practice_drones),
            (7.5, "conv", 0x1B7), (7.5, "objective", PRACTICE_OBJECTIVE)))

    def _practice_drones(self):
        m = self.match
        now = time.time()
        msgs = []
        override = m.cfg["tutorial"].get("practice_positions") or {}
        for name in PRACTICE:
            xyz = override.get(name)
            msgs += m.spawn(name, now, xyz=tuple(xyz) if xyz else None)
        self._spawn_effect(PRACTICE)
        self.ambient_meteors("practice")
        return msgs

    def ambient_meteors(self, hook):
        """2026-10-17 17:51 (tester's full video "infinite-crisis-tutorial", 0.5 s frames): flaming
        rocks keep falling near Batman as set dressing (02:41, 02:43 by the practice targets;
        03:37, 03:38, 03:44 on the bridge after the pursuers; 05:38 at the Bat Flight target): a
        fire trail, a smoke puff, a small chunk. [tutorial] ambient_meteors = {hook: [[delay s,
        dx, dy], ...]} relative to Batman when the hook fires (x = screen right, y = screen down);
        small meteors gone after ambient_meteor_lifetime s. Hooks: "practice" and bridge stages."""
        m = self.match
        tc = m.cfg["tutorial"]
        if not tc.get("meteors", True):
            return
        for delay, dx, dy in (tc.get("ambient_meteors") or {}).get(hook, []) or []:
            def drop(dx=float(dx), dy=float(dy), hook_name=hook):
                bx, by, bz = m.mover.pos[0], m.mover.pos[1], m.mover.pos[2]
                xyz = (bx + dx, by + dy, bz)
                self.log(f"tutorial: ambient meteor ({hook_name}) at ({xyz[0]:.1f}, {xyz[1]:.1f})")
                return self.meteor(xyz, time.time(), lifetime=float(tc.get("ambient_meteor_lifetime", 4.0)),
                                   group="ambient")
            self.schedule(float(delay), drop)


def player_ping(match, body, count, now):
    """Answer client event 0x2136 (Alt+click): f32 x | f32 y | u64 target | u32 type.
    Returns (object id, message, [(note id, note message)]) or None."""
    if len(body) < 20:
        return None
    x, y, target, ptype = struct.unpack_from("<ffQI", body, 0)
    object_id = M.PLAYER_PING_BASE_ID + (count % 0x20)
    class_id = PLAYER_PING_CLASSES.get(ptype, 0x4000025A)
    spawn = match.mover.spawn
    pos = (spawn[0], spawn[1], spawn[2], 0, x, y, spawn[6])
    mode = note_mode(match)
    props = ping_properties(ping_team_for(match, class_id), ping_style(match), show=mode == "self")
    if mode == "self":
        props += player_note_props(match, class_id, extras_only=True)
    msg = M.create_object(object_id, class_id, now, position=pos, module=match.module,
                          second_seq=match.second_seq, properties=props)
    notes = []
    if mode == "companion":
        note_id = MAP_NOTE_BASE_ID + (count % 0x10)
        notes.append((note_id, M.create_object(note_id, PING_CLASS, now, position=pos, module=match.module,
                                               second_seq=match.second_seq,
                                               properties=player_note_props(match, class_id))))
    return object_id, msg, notes
