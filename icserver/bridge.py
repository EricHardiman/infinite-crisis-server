"""Tutorial 1, part 2: the bridge. From the end of the Catwoman cinematic up to
the moment the Bat Scream (R) can be unlocked.

The order follows the tutorial's own dialogue (conversation keys 0x1xx) and
the original's video:

  pursuers     0x1C9 "Selina has left it to us..." -> 2 drones come for Batman
  unlock_w     0x1E5 / 0x1E4 (level 3) -> 0x1C2 "unlock your next skill" (W)
  w_practice   yellow target drone, only Sonic Shell hurts it (0x1B1, 0x192)
  surround     0x191 "More enemies!" -> 3 drones around Batman (0x199)
  upgrade_q    0x1D9 (level 4) -> 0x1D3 "upgrade a skill" (Q); the gate opens
  to_marker    0x38D "We need to keep moving." -> marker on the bridge
  ambush       the gate behind closes, 3 drones (2 melee + 1 ranged), 0x1CC
  camera       0x22B / 0x22A Stolen Powers -> 0x196 "Place a camera here." (D)
  gate_fight   0x1BD, 0x1D2: the next gate opens; 4 drones hit the gate after
               it; half way there the gate behind closes again
  unlock_e     0x1C6 (level 5) -> 0x1D1 "Unlock your next skill." (E)
  e_practice   0x190 target drone, only Bat Flight hurts it (0x1AA)
  more_drones  0x1AE: 4 drones (2 melee, 2 ranged) come for Batman
  passive      0x1A1 skill point for the passive (Echoes), 0x18F
  vehicle      0x1E2 "Let's go!": the last gate opens; 4 drones hit a vehicle
               at the end of the bridge; attacking one brings all four
  unlock_r     0x1CB (level 6) -> 0x1DC "unlock the Bat Scream" (R)
  scream_intro 0x1A0: the camera spots 3 drones hitting the gate two sections
               back (red alert marker), 0x1C8 "red dots on your mini-map"
  camera_unlock 0x1B6 / 0x1B0 "unlock your camera" (waits for the client's
               User.CameraLocked = False, or camera_unlock_wait seconds)
  scream       0x1CA, 0x1B5, 0x1D8, 0x1D0: fire the Bat Scream (R) at them
               (0/3); 0x3AC after a miss
  camera_lock  0x1A5 "Good shot!", 0x1AD / 0x1A8 / 0x19F "lock the camera
               back on Batman" (User.CameraLocked = True, or camera_lock_wait)
  end          (the last part of the tutorial is not programmed yet)

Positions: the bridge runs from gate 03GateA (54.05, 44.80) to 03GateB
(89.87, 26.21) of the encounter layout (pack 0xA0000256). Everything else is
measured along it ("s", metres from 03GateA) and across it ("l", metres to
the north side), estimated from screenshots of the original. Every spot can
be overridden in config.toml: [tutorial] bridge_positions = { camera = [x, y], ... }
(an Alt+click logs its x, y in server.log).
"""
import math
import time

from . import batman
from . import messages as M
from . import stolenpowers
from .wire import KIND_IID, KIND_INT

ORIGIN = (54.05, 44.80)                 # 03GateA
U = (0.8875, -0.4606)                   # along the bridge, towards 03GateB
N = (0.4606, 0.8875)                    # across it, towards the north side
Z = 200.0
CROSS_YAW = math.atan2(N[1], N[0])      # a gate's long side runs across the bridge
GATE_YAW = -2.042                       # the layout's yaw of both gates


def along(s, lat=0.0):
    return (ORIGIN[0] + s * U[0] + lat * N[0], ORIGIN[1] + s * U[1] + lat * N[1], Z)


def s_of(xy):
    return (xy[0] - ORIGIN[0]) * U[0] + (xy[1] - ORIGIN[1]) * U[1]


GATE_S = {"03GateA": 0.0, "03GateMid": 17.5, "03GateB": 40.36}
GATE_WSTATE = 0x2E0010F3
GATE_HALF_LENGTH, GATE_HALF_WIDTH = 7.0, 0.5

MELEE_WS, RANGED_WS, TARGET_WS = 0x2E001167, 0x2E001168, 0x2E001298
VEHICLE_WS = 0x2E000AAB                 # the same police wagon as the street vehicle

# 2026-10-15 09:08 (clicks snapped by the client to the walkable area): the
# bridge is ~4.8 m wide, from l = -2.5 (south) to l = +2.3 (north), and runs
# straight to s ~ 66, where it opens into a wider area (clicks up to l = 6.4).
BRIDGE_NORTH, BRIDGE_SOUTH, BRIDGE_END = 2.2, -2.4, 64.0

POSITIONS = {
    # 03MeleeA / 03MeleeB of the layout: just before the first gate
    "pursuer1": (49.36, 49.34, Z), "pursuer2": (47.87, 46.76, Z),
    "w_target": (49.6, 48.2, Z),
    "marker1": along(12.0, 0.0),
    "ambush_melee1": along(14.8, -1.2), "ambush_melee2": along(14.8, 1.2), "ambush_ranged": along(16.3, 0.0),
    # 10:57 (screenshot): further on than s = 9; 11:35: s = 14.5 was too close
    # to the middle gate (17.5)
    "camera": along(12.5, 0.0),
    # 11:35: the E target drone stands a little before the last gate (where
    # Batman stood at 11:33:34, (85.6, 28.5)), not relative to Batman
    "e_target": along(35.5, 0.0),
    "gate_melee1": along(38.6, -1.0), "gate_melee2": along(38.6, 1.0),
    "gate_ranged1": along(36.4, -0.8), "gate_ranged2": along(36.4, 1.2),
    # 10:29 (video): a guide marker near the next gate when it opens; the four
    # drones there only turn on Batman when one of them is attacked
    "gate_drones": along(31.5, 0.0),
    # 10:29: the vehicle stands right where the bridge ends (it was ~5 m too far)
    "vehicle": along(60.0, 0.0),
    "vehicle_melee1": along(56.5, -1.0), "vehicle_melee2": along(56.5, 1.0),
    "vehicle_ranged1": along(54.3, -0.8), "vehicle_ranged2": along(54.3, 1.0),
    # the Bat Scream's drones: two sections back, on the camera's side of
    # 03GateMid, hitting it (video: the surveillance camera shows them)
    "scream1": along(15.9, -1.3), "scream2": along(15.3, 0.0), "scream3": along(15.9, 1.3),
}
# What the gates look like: the Door entity 0x40000B0F (world state 0x2E0010F3)
# is placed but shows nothing (2026-10-15 09:06: "something blocks the way but
# it cannot be seen"). Its world state has a second state 0x2E0010F4 (.entity
# 0x2D000E52), sent as a carrier object on the same spot ([tutorial] gate_models).
GATE_MODELS = (0x2E0010F4,)
# 10:03: the 0x2E0010F4 object shows as a WHITE light wall (the original's is
# blue while closed). The gate's scriptlet tables (0x1D00073F, 0x1D00038B) name
# Vfx_OnInit, Object_Closed / Object_Open, Vfx_Active and Vfx_Startup: they are
# played one by one on the gate's visible part ([tutorial] gate_keys).
GATE_KEYS = (0x10000078, 0x1000034F, 0x100000EB, 0x1000018E)
# [tutorial] gate_test = true: candidates in a row on the street before the first
# gate, to see which one is the blue barrier: (label, class or world state)
# (label, class or world state, team property or None)
GATE_TEST = (("A world state 0x2E0010F3, team 1", 0x2E0010F3, 1),
             ("B world state 0x2E0010F4, no team", 0x2E0010F4, None),
             ("C world state 0x2E0010F4, team 0", 0x2E0010F4, 0),
             ("D world state 0x2E0010F4, team 1", 0x2E0010F4, 1),
             ("E world state 0x2E0010F4, team 2", 0x2E0010F4, 2))
# 10:29: still white. The light walls of the game are team coloured (blue =
# the player's side); the gate objects had no team property at all, which may
# be why they show neutral white. [tutorial] gate_team: the team given to the
# gate's visible part ("player" = Batman's team, -1 = none).
TEAM_PROPERTY = 0x1000009C
VEHICLE_YAW = CROSS_YAW - math.pi        # across the road (like the street vehicle)

# Where Batman is put by [tutorial] start_at (to test a part without playing
# the whole tutorial), with his level and skill ranks at that point.
JUMPS = {
    "bridge": dict(at=(42.4, 56.8, Z), level=2, ranks={1: 1}),
    "camera": dict(at=along(12.0, 0.0), level=4, ranks={1: 2, 2: 1}),
    "gate_fight": dict(at=along(13.0, 0.0), level=4, ranks={1: 2, 2: 1}, camera=True),
    "unlock_e": dict(at=along(30.0, 0.0), level=4, ranks={1: 2, 2: 1}, camera=True),
    "e_practice": dict(at=along(30.0, 0.0), level=5, ranks={1: 2, 2: 1}, camera=True, rank_next=3),
    "vehicle": dict(at=along(36.0, 0.0), level=5, ranks={1: 2, 2: 1, 3: 1, 5: 1}, camera=True),
    "scream": dict(at=along(52.0, 0.0), level=6, ranks={1: 2, 2: 1, 3: 1, 4: 1, 5: 1}, camera=True),
    "strength": dict(at=along(55.0, 0.0), level=6, ranks={1: 2, 2: 1, 3: 1, 4: 1, 5: 1}, camera=True),
    "destroyer": dict(at=(124.0, 16.5, Z), level=6, ranks={1: 2, 2: 1, 3: 1, 4: 1, 5: 1}, camera=True),
}

HUD_UPGRADE_BUTTON = {1: 30, 2: 4, 3: 28, 4: 5, 5: 19}
HUD_EVENT_RESTORE, HUD_EVENT_HIDE, HUD_EVENT_HIGHLIGHT = 1, 2, 7
HINT_SKILL_POINTS, HINT_SKILL_CHARGES, HINT_PASSIVE, HINT_STOLEN_POWERS = 34, 22, 23, 27

OBJ_DRONES = ("Use <font color='#00FF00'>Basic Attacks (Right-click)</font> and "
              "<font color='#66FFFF'>Skills</font> to defeat the drones ({}/{})")
OBJ_MOVE = "<font color='#FFFF00'>Right-click</font> to move to the marked location"
OBJ_UNLOCK = {
    2: "Click the highlighted button to unlock <font color='#66FFFF'>Sonic Shell</font>",
    1: "Click the highlighted button to upgrade <font color='#66FFFF'>Sonic Batarang</font>",
    3: "Click the highlighted button to unlock <font color='#66FFFF'>Bat Flight</font>",
    5: "Click the highlighted button to upgrade your <font color='#66FFFF'>'Passive Skill' - Echoes</font>",
    4: "Click the highlighted button to unlock your <font color='#66FFFF'>'Ultimate Skill' - Bat Scream</font>",
}
OBJ_UPGRADE_Q_OR_W = ("Click a highlighted button to upgrade either <font color='#66FFFF'>Sonic Batarang</font> "
                      "or <font color='#66FFFF'>Sonic Shell</font>")
OBJ_W_PRACTICE = ("Place your cursor on the target and press <font color='#FFFF00'>('W')</font> "
                  "to destroy it with <font color='#66FFFF'>Sonic Shell</font>")
OBJ_E_PRACTICE = ("Place your cursor on the target and press <font color='#FFFF00'>('E')</font> "
                  "to hit it with <font color='#66FFFF'>Bat Flight</font>")
OBJ_CAMERA = ("Place your cursor on the marked location and press <font color='#FFFF00'>('D')</font> "
              "to place a surveillance camera")
# not among the tutorial's objective strings (the screenshot of the original):
OBJ_SCREAM = ("Aim your cursor at the drones and press <font color='#FFFF00'>('R')</font> "
              "to fire the <font color='#66FFFF'>Bat Scream</font> ({}/{})")
OBJ_PAN = ("<font color='#FFFF00'>Left-click</font> on the mini map, or place your cursor on the edge of the "
           "screen, to pan to the highlighted location")                       # 038bf934
OBJ_LOCK = "Lock the camera back on Batman"                                     # = line 0x19F
OBJ_END = "Tutorial: end of the part the server knows so far"

# Superman's lines for the target drones (said once each)
CONV_ONLY_SKILLS = 0x1CD                 # "...only affected by skills, not basic attacks."
CONV_INEFFECTIVE = 0x1DB                 # "That attack is ineffective against this target."
CONV_TRY_SKILL = 0x1B2                   # "Try using the skill you just learned on that target drone."
CONV_LOW_HEALTH = 0x1CE                  # "Batman's health is low. The Construct is healing him..."

# step numbers of the bridge's guide markers (the walk of part 1 uses 1-3)
MARKER_STEP = {"marker1": 11, "camera": 12, "gate_drones": 13}


class Bridge:
    def __init__(self, tut):
        self.t = tut
        self.m = tut.match
        self.stage = None
        self.groups = {}                 # group -> [eid, ...]
        self.group_size = {}
        self.pending_ranks = ()          # slots whose '+' the tutorial waits for
        self.prompt_id = 0
        self.said = set()
        self.gate_state = {}             # gate name -> "open" / "closed"
        self.cameras = []
        self.camera_ready = False
        self.flags = set()
        self.hit_targets = {}            # group -> name of the object its drones hit
        self.hitting = False             # the hit_objects loop is running
        self.no_aggro = set()            # groups that never turn on Batman
        self.wake_on_attack = set()      # idle groups that turn on Batman when one is attacked
        self.alert_ids = []              # the red alert marker (object ids)
        self.camera_locked = None        # last User.CameraLocked from the client

    @property
    def pending_rank(self):
        return self.pending_ranks[0] if self.pending_ranks else None

    # ---- helpers -------------------------------------------------------------------
    @property
    def tc(self):
        return self.m.cfg["tutorial"]

    def pos(self, name):
        raw = (self.tc.get("bridge_positions") or {}).get(name)
        if raw:
            return (float(raw[0]), float(raw[1]), float(raw[2]) if len(raw) > 2 else Z)
        return POSITIONS[name]

    def gate_s(self, name):
        raw = (self.tc.get("bridge_gates") or {}).get(name)
        return float(raw) if raw is not None else GATE_S[name]

    def batman_s(self):
        return s_of(self.m.mover.pos)

    def say_once(self, key, now=None):
        if key in self.said:
            return []
        self.said.add(key)
        return self.t.say(key, now)

    def beats(self, beats):
        return self.t.beats(beats)

    def after_speech(self, fn, margin=0.3):
        return lambda: self.t.after_speech(margin * float(self.tc.get("pacing", 1.0)), fn)

    def objective(self, text):
        return self.t._objective(text)

    def _stage(self, name):
        self.stage = name
        self.t.log(f"tutorial (bridge): {name}")
        self.t.ambient_meteors(name)      # 2026-10-17 17:51: falling rocks as in the original

    # ---- gates ---------------------------------------------------------------------
    def gate_obstacles(self, now):
        """At the tutorial start every gate is closed (blocks the way) and the
        bridge's edges are walls. Returns the gates' visible parts."""
        self._edges()
        msgs = []
        for name in GATE_S:
            self.gate_state.setdefault(name, "closed")
            self._block(name, True)
            msgs += self._gate_visuals(name, now)
        if self.tc.get("gate_test", False):
            msgs += self._gate_test(now)
        return msgs

    def _edges(self):
        """The bridge has no railing in the server's map: without these Batman
        walked round the gates over the water (2026-10-15 09:08)."""
        if not self.tc.get("bridge_edges", True):
            return
        north = float(self.tc.get("bridge_north", BRIDGE_NORTH))
        south = float(self.tc.get("bridge_south", BRIDGE_SOUTH))
        end = float(self.tc.get("bridge_end", BRIDGE_END))
        obs = self.m.mover.obstacles
        obs["BridgeNorth"] = [list(along(0.6, north)[:2]), list(along(end, north)[:2]),
                              list(along(end, 40.0)[:2]), list(along(0.6, 40.0)[:2])]
        obs["BridgeSouth"] = [list(along(36.0, south)[:2]), list(along(end, south)[:2]),
                              list(along(end, -40.0)[:2]), list(along(36.0, -40.0)[:2])]
        self.t.log(f"tutorial: bridge edges at l = {north:+.1f} / {south:+.1f} m, up to s = {end:.0f} m")

    def _gate_visuals(self, name, now):
        from . import tutorial1
        msgs = []
        xyz = self._gate_xyz(name)
        keys = [int(k) for k in self.tc.get("gate_keys", GATE_KEYS) or ()]
        for ws in self.tc.get("gate_models", GATE_MODELS) or ():
            vis = f"{name}~{int(ws):x}"
            tutorial1.EXTRA_SPAWNS[vis] = (int(ws), xyz, GATE_YAW)
            before = set(self.m.entities)
            msgs += self.m.spawn(vis, now, attackable=False, xyz=xyz)
            for eid in set(self.m.entities) - before:
                msgs += self._team_up(self.m.entities[eid], self.gate_team(), now)
                for i, key in enumerate(keys):
                    self.t.schedule(1.0 + 1.5 * i, lambda eid=eid, key=key, vis=vis: (
                        self.t.log(f"gate look: {vis} script {key:#x}") if vis.startswith("03GateA") else None,
                        self.t.run_scripts(eid, (key,), f"{vis} blue? ({key:#x})"), [])[2])
        return msgs

    def gate_team(self):
        raw = self.tc.get("gate_team", "player")
        if raw == "player":
            return self.m.team
        return None if raw is None or int(raw) < 0 else int(raw)

    def _team_up(self, ent, team, now):
        """Give a placed object a team (property 0x1000009C) and re-send it."""
        if team is None:
            return []
        ent.extra_props = list(getattr(ent, "extra_props", [])) + [(TEAM_PROPERTY, KIND_INT, int(team))]
        return [(f"{ent.name} team {team}", self.m.entity_bundle(ent, time.time()))]

    def _gate_test(self, now):
        from . import tutorial1
        msgs = []
        for i, (label, cls, team) in enumerate(GATE_TEST):
            xyz = along(-3.0 - 3.0 * i, 0.0)
            name = f"GateTest{'ABCDEFGH'[i]}"
            tutorial1.EXTRA_SPAWNS[name] = (cls, xyz, GATE_YAW)
            before = set(self.m.entities)
            msgs += self.m.spawn(name, now, attackable=False, xyz=xyz)
            for eid in set(self.m.entities) - before:
                msgs += self._team_up(self.m.entities[eid], team, now)
            self.t.log(f"gate test {label} at ({xyz[0]:.1f}, {xyz[1]:.1f})")
        return msgs

    def _gate_entities(self, name):
        return [e for e in self.m.entities.values()
                if (e.name == name or e.name.startswith(name + "~")) and not getattr(e, "removed", False)]

    def _block(self, name, on):
        key = f"Gate {name}"
        if on and self.tc.get("gates_block", True):
            x, y, _ = self._gate_xyz(name)
            self.m.mover.obstacles[key] = (x, y, GATE_HALF_LENGTH, GATE_HALF_WIDTH, CROSS_YAW)
        else:
            self.m.mover.obstacles.pop(key, None)

    def _gate_xyz(self, name):
        from . import tutorial1
        raw = (self.tc.get("bridge_positions") or {}).get(name)
        if raw:
            return (float(raw[0]), float(raw[1]), Z)
        if name in (self.tc.get("bridge_gates") or {}):
            return along(self.gate_s(name))
        entry = tutorial1.LAYOUT.get(name) or tutorial1.EXTRA_SPAWNS.get(name)
        return entry[1] if entry else along(self.gate_s(name))

    def open_gate(self, name, why):
        if self.gate_state.get(name) == "open":
            return []
        self.gate_state[name] = "open"
        self._block(name, False)
        self.t.log(f"tutorial: gate {name} opens ({why})")
        out = []
        for ent in self._gate_entities(name):
            ent.removed = True
            del self.m.entities[ent.eid]
            out.append((f"gate {ent.name} opens (0x3)", M.remove_object(ent.eid)))
        return out

    def close_gate(self, name, why):
        if self.gate_state.get(name) == "closed":
            return []
        if abs(self.batman_s() - self.gate_s(name)) < 1.5:
            return []                                   # he is standing in it
        self.gate_state[name] = "closed"
        self._block(name, True)
        self.t.log(f"tutorial: gate {name} closes ({why})")
        # a new object id: the removed one is freed by the client a while later
        now = time.time()
        return self.m.spawn(name, now, attackable=False, xyz=self._gate_xyz(name)) + self._gate_visuals(name, now)

    # ---- drones --------------------------------------------------------------------
    def spawn_drone(self, name, kind, xyz, group, face=None, only_slot=None, aggressive=True, health=None):
        from . import tutorial1
        m = self.m
        now = time.time()
        if m.mover.blocked(xyz[0], xyz[1]):                  # not inside a wall / gate / vehicle
            free = m.mover.free_goal(m.mover.pos[0], m.mover.pos[1], xyz[0], xyz[1])
            if free:
                xyz = (free[0], free[1], xyz[2])
        fx, fy = face if face is not None else m.mover.pos[:2]
        heading = math.atan2(fy - xyz[1], fx - xyz[0])
        from .finale import DESTROYER_WS
        wstate = {"melee": MELEE_WS, "ranged": RANGED_WS, "target": TARGET_WS, "destroyer": DESTROYER_WS}[kind]
        tutorial1.EXTRA_SPAWNS[name] = (wstate, tuple(xyz), heading - math.pi / 2)
        before = set(m.entities)
        msgs = m.spawn(name, now, xyz=tuple(xyz))
        new = [eid for eid in m.entities if eid not in before]
        if not new:
            return msgs
        ent = m.entities[new[0]]
        ent.group, ent.role, ent.only_slot = group, kind, only_slot
        ent.leash = 80.0
        if health:
            ent.health = ent.max_health = int(health)
            msgs.append((f"{name} vitals (0x42)", M.vitals(ent.eid, [(ent.health, ent.max_health)])))
        if aggressive and kind not in ("target", "destroyer"):
            self.t.aggressive.add(ent.eid)
        self.groups.setdefault(group, []).append(ent.eid)
        self.group_size[group] = len(self.groups[group])
        return msgs

    def group_left(self, group):
        return sum(1 for eid in self.groups.get(group, ()) if eid in self.m.entities and self.m.entities[eid].alive)

    def _drones_objective(self, group):
        n = self.group_size.get(group, 0)
        return self.objective(OBJ_DRONES.format(n - self.group_left(group), n))

    def _teleport_in(self, names):
        self.t._spawn_effect(names)

    def spawn_group(self, group, specs, aggressive=True, face=None):
        """specs: [(name, kind, position name or xyz)]; returns messages."""
        msgs, names = [], []
        for name, kind, where in specs:
            xyz = self.pos(where) if isinstance(where, str) else where
            msgs += self.spawn_drone(name, kind, xyz, group, face=face, aggressive=aggressive)
            names.append(name)
        self._teleport_in(names)
        self.t.log(f"tutorial: {len(names)} drones ({group})")
        return msgs + self._drones_objective(group)

    def attacked(self, ent):
        group = getattr(ent, "group", None)
        if group in self.hit_targets and group not in self.no_aggro:
            return self._aggro_group(group, f"{ent.name} was attacked")
        if group in self.wake_on_attack:
            self.wake_on_attack.discard(group)
            for eid in self.groups.get(group, ()):
                e = self.m.entities.get(eid)
                if e and e.alive:
                    self.t.aggressive.add(eid)
            self.t.log(f"tutorial: the {group} drones turn on Batman ({ent.name} was attacked)")
        return []

    def _aggro_group(self, group, why):
        if group not in self.hit_targets:
            return []
        self.hit_targets.pop(group, None)
        for eid in self.groups.get(group, ()):
            e = self.m.entities.get(eid)
            if e and e.alive:
                self.t.aggressive.add(eid)
        self.t.log(f"tutorial: the {group} drones turn on Batman ({why})")
        if group == "gate" and "gate_marker" in self.flags:
            self.flags.discard("gate_marker")
            return self._unmark("gate_drones")
        return []

    def _start_hitting(self):
        if not self.hitting:
            self.hitting = True
            self.t.schedule(1.0, self.hit_objects)

    def hit_objects(self):
        """Drones that are not fighting Batman hit their gate / vehicle."""
        for group, target_name in list(self.hit_targets.items()):
            target = next((e for e in self.m.entities.values() if e.name == target_name
                           and not getattr(e, "removed", False)), None)
            variables = [(M.PROP_SCRIPT_TARGET, KIND_IID, target.eid)] if target else None
            for eid in self.groups.get(group, ()):
                e = self.m.entities.get(eid)
                if e and e.alive and eid not in self.t.aggressive:
                    keys = self.t._attack_key(eid, e)
                    self.t.run_scripts(eid, keys, f"{e.name} hits {target_name}", variables)
        if self.hit_targets:
            from . import tutorial1
            self.t.schedule(tutorial1.FIGHT_INTERVAL, self.hit_objects)
        else:
            self.hitting = False
        return []

    def target_drone(self, name, where, slot):
        hp = int(self.tc.get("bridge_target_health", 100))
        msgs = self.spawn_drone(name, "target", where, "target", only_slot=slot, aggressive=False, health=hp)
        self._teleport_in([name])
        return msgs

    # ---- skill points --------------------------------------------------------------
    def level_up(self, level, points=1):
        m = self.m
        if level:
            m.level = level
        m.skill_points += points
        m.sequence += 1
        self.t.log(f"tutorial: level {m.level}, {m.skill_points} skill point(s)")
        return [(f"champion level {m.level} + skill point", m.champion_bundle(time.time()))]

    def prompt_rank(self, slots, conv, hint=None, objective=None):
        """Wait for the '+' of one of slots (an int or a tuple: the first one is
        the recommended one, the others may be ranked as well)."""
        from . import tutorial1
        m = self.m
        slots = (slots,) if isinstance(slots, int) else tuple(slots)
        self.pending_ranks = slots
        self.prompt_id += 1
        pid = self.prompt_id
        m.skill_ranks = tutorial1.set_recommended(m.skill_ranks, slots[0])
        m.sequence += 1
        msgs = [("skill recommended", m.champion_bundle(time.time()))] + self.t.say(conv)
        for slot in slots:
            button = HUD_UPGRADE_BUTTON[slot]
            msgs += [(f"HUD element {button} restored (0x213d)", M.hud_element(button, HUD_EVENT_RESTORE)),
                     (f"highlight upgrade button {button} (0x213d)", M.hud_element(button, HUD_EVENT_HIGHLIGHT))]
        if hint:
            msgs.append((f"tutorial hint {hint}", M.tutorial_hint(hint)))
        auto = float(self.tc.get("auto_rank_seconds", 0) or 0)
        if slots[0] == batman.SLOT_PASSIVE:
            auto = auto or float(self.tc.get("passive_auto_seconds", 30.0) or 0)
        if auto > 0:
            self.t.schedule(auto, lambda: self.ranked(slots[0], time.time(), auto=True)
                            if self.prompt_id == pid else [])
        self.t.log(f"tutorial: waiting for the '+' of slot {' or '.join(map(str, slots))}")
        return msgs + self.objective(objective or OBJ_UNLOCK[slots[0]])

    def ranked(self, slot, now, auto=False):
        from . import tutorial1
        if slot not in self.pending_ranks:
            return []
        m = self.m
        self.pending_ranks = ()
        m.skill_points = max(0, m.skill_points - 1)
        rank = (m.skill_ranks >> (4 * slot)) & 0xF
        m.skill_ranks = tutorial1.set_recommended(m.skill_ranks, None) + (1 << (4 * slot)) * (rank < 15)
        m.sequence += 1
        self.t.log(f"tutorial: slot {slot} now rank {rank + 1}" + (" (automatic)" if auto else ""))
        msgs = [(f"slot {slot} ranked up" + (" (automatic)" if auto else ""), m.champion_bundle(now))]
        nxt = {"unlock_w": self._w_practice, "upgrade_q": self._open_first_gate, "unlock_e": self._e_practice,
               "passive": self._after_passive, "unlock_r": self._scream_intro}.get(self.stage)
        return msgs + (nxt() if nxt else [])

    # ---- the stages ----------------------------------------------------------------
    def start(self, now):
        """The Catwoman cinematic is over: her pursuers come."""
        if self.stage:
            return []
        self._stage("pursuers")
        self.t.phase = "bridge"
        return self.beats(((0.5, "conv", 0x1C9), (2.0, "call", self._pursuers)))

    def _pursuers(self):
        return self.spawn_group("pursuers", [("BridgePursuer1", "melee", "pursuer1"),
                                             ("BridgePursuer2", "melee", "pursuer2")])

    def killed(self, ent, now):
        group = getattr(ent, "group", None)
        if group is None:
            return []
        if group == "target":
            if self.stage == "w_practice":
                return self._surround_intro()
            if self.stage == "e_practice":
                self._stage("e_practice_done")      # "...and Batman finishes his line"
                return self.t.after_speech(0.5 * float(self.tc.get("pacing", 1.0)), self._more_drones)
            return []
        left = self.group_left(group)
        if group == "scream":
            return self._scream_killed(left)
        msgs = self._drones_objective(group)
        if left:
            return msgs
        if group == "gate" and "gate_marker" in self.flags:
            self.flags.discard("gate_marker")
            msgs += self._unmark("gate_drones")
        nxt = {"pursuers": self._after_pursuers, "surround": self._after_surround, "ambush": self._camera_intro,
               "gate": self._after_gate, "more": self._passive, "vehicle": self._after_vehicle}.get(group)
        self.t.log(f"tutorial: the {group} drones are defeated")
        return msgs + (nxt() if nxt else [])

    def _after_pursuers(self):
        self._stage("unlock_w")
        return self.beats(((0.5, "conv", 0x1E5), (0.5, "call", lambda: self.level_up(3)),
                           (3.0, "conv", 0x1E4),
                           (3.5, "call", self.after_speech(lambda: self.prompt_rank(batman.SLOT_W, 0x1C2,
                                                                                    HINT_SKILL_POINTS)))))

    def _w_practice(self):
        self._stage("w_practice")
        return self.beats(((0.5, "call", lambda: self.target_drone("BridgeTargetW", self.pos("w_target"),
                                                                   batman.SLOT_W)),
                           (1.0, "conv", 0x1B1), (1.0, "objective", OBJ_W_PRACTICE), (4.5, "conv", 0x192)))

    def _surround_intro(self):
        self._stage("surround")
        return self.beats(((0.5, "conv", 0x191), (0.5, "call", self._surround), (6.0, "conv", 0x199)))

    def _surround(self):
        """Three drones around Batman, each on a spot he can walk to straight
        (not inside a wall, not behind a closed gate)."""
        mv = self.m.mover
        bx, by, _ = mv.pos
        r0 = float(self.tc.get("surround_radius", 4.5))
        specs = []
        for i in range(3):
            base = math.pi / 2 + i * 2 * math.pi / 3
            spot = None
            for r in (r0, r0 * 0.75, r0 * 0.5):
                for da in (0.0, 0.35, -0.35, 0.7, -0.7):
                    x, y = bx + r * math.cos(base + da), by + r * math.sin(base + da)
                    if not mv.blocked(x, y) and mv.segment_clear(bx, by, x, y):
                        spot = (x, y, Z)
                        break
                if spot:
                    break
            specs.append((f"BridgeSurround{i + 1}", "melee", spot or (bx + 1.5 * math.cos(base), by + 1.5 * math.sin(base), Z)))
        return self.spawn_group("surround", specs)

    def _after_surround(self):
        self._stage("upgrade_q")
        return self.beats(((0.5, "conv", 0x1D9), (0.5, "call", lambda: self.level_up(4)),
                           (3.0, "call", self.after_speech(lambda: self.prompt_rank(
                               (batman.SLOT_Q, batman.SLOT_W), 0x1D3, objective=OBJ_UPGRADE_Q_OR_W)))))

    def _open_first_gate(self):
        """Q upgraded: the gate at the start of the bridge opens and a marker
        shows where to go."""
        self._stage("to_marker")
        msgs = self.open_gate("03GateA", "Q upgraded")
        return msgs + self.t.say(0x38D) + self._marker("marker1") + self.objective(OBJ_MOVE)

    def _marker(self, name):
        step = MARKER_STEP[name]
        self.t.step = step                 # the marker and its arrows only show for the current step
        self.t.targets[step] = self.pos(name)
        ping = self.t.ping(step, time.time())
        self.t.log(f"tutorial: marker '{name}' at ({self.pos(name)[0]:.1f}, {self.pos(name)[1]:.1f})")
        return [(f"guide ping '{name}'", ping)] if ping else []

    def _unmark(self, name):
        return self.t.remove_ping(MARKER_STEP[name])

    def _ambush(self):
        self._stage("ambush")
        msgs = self._unmark("marker1") + self.close_gate("03GateA", "Batman reached the marker")
        msgs += self.t.say(0x1CC)
        return msgs + self.spawn_group("ambush", [("BridgeAmbushMelee1", "melee", "ambush_melee1"),
                                                  ("BridgeAmbushRanged", "ranged", "ambush_ranged"),
                                                  ("BridgeAmbushMelee2", "melee", "ambush_melee2")])

    def _camera_intro(self):
        self._stage("camera_intro")
        return self.beats(((0.5, "conv", 0x22B), (1.0, "call", self.after_speech(self._camera_power))))

    def _camera_power(self):
        """'Gaslight Batman's power is a Surveillance Camera': the D button."""
        msgs = self.t.say(0x22A) + self.enable_camera()
        msgs.append((f"tutorial hint {HINT_STOLEN_POWERS}", M.tutorial_hint(HINT_STOLEN_POWERS)))
        self.t.schedule(0.5 * float(self.tc.get("pacing", 1.0)), self.after_speech(self._camera_prompt))
        return msgs

    def enable_camera(self):
        """Give Batman his Stolen Power: the camera skill on slot 7 (D), shown on
        the HUD (element 22). The changed rank property makes the HUD refresh
        the skill slots (the patched client marks slots 0-7 dirty)."""
        from . import tutorial1
        m = self.m
        self.camera_ready = True
        # 2026-10-15 10:01: sending the skill as property 0x100008F0 (a DID) broke
        # every later champion update on the client (no HUD refresh any more, and
        # Batman ran off with his last speed): in the champion's data that slot
        # property is a whole skill structure, not a DID. Off until its format is
        # known ([tutorial] stolen_power_property = true to send it anyway).
        # 12:01: the slot holds the skill's whole definition (a property
        # collection), built from the game data with the client's own property
        # kinds (logs\props.txt from tools\diag.py --props); "dids" = the old
        # test that sent the skill as a DID (breaks the client's updates)
        mode = self.tc.get("stolen_power_property", "auto")
        if mode == "dids":
            m.stolen_power = stolenpowers.resolve(self.tc.get("camera_skill"), batman.CAMERA_SKILL)
        elif mode:
            from . import skilldata
            table = skilldata.stolen_power(m.cfg, stolenpowers.resolve(self.tc.get("camera_skill"), skilldata.CAMERA_VERSION))
            if table:
                m.stolen_powers[batman.SLOT_D] = table
        m.hud_refresh += 1                    # refresh the skill buttons (slot 7 too)
        m.sequence += 1
        self.t.log("tutorial: Stolen Power (surveillance camera) on D"
                   + (f" (property 0x100008F0 = {m.stolen_power:#x})" if m.stolen_power else "")
                   + (" (skill collection 0x100008F0 sent)" if batman.SLOT_D in m.stolen_powers else ""))
        return [("Stolen Power: camera skill on slot 7 (property 0x100008F0)", m.champion_bundle(time.time())),
                ("HUD element 22 (D button) restored (0x213d)",
                 M.hud_element(batman.HUD_SKILL_BUTTON_D, HUD_EVENT_RESTORE)),
                ("highlight the D button (0x213d)", M.hud_element(batman.HUD_SKILL_BUTTON_D, HUD_EVENT_HIGHLIGHT))]

    def _camera_prompt(self):
        self._stage("camera")
        msgs = self.t.say(0x196) + self._marker("camera") + self.objective(OBJ_CAMERA)
        auto = float(self.tc.get("camera_auto_seconds", 25.0) or 0)
        if auto > 0 and batman.SLOT_D in self.m.stolen_powers and self.tc.get("skill_buttons_only", True):
            # 2026-10-16: with the camera skill on D the player places it himself
            # (D, then a click); the timer is only for a client without it
            auto = 0
        if auto > 0:
            def fallback():
                if self.stage != "camera":
                    return []
                self.t.log("tutorial: no D order from the client: the camera is placed automatically")
                return self.place_camera(self.pos("camera"), time.time(), "automatic")
            self.t.schedule(auto, fallback)
        return msgs

    def camera_tick(self, now):
        """A D order beyond the camera's range: Batman walks until the spot is
        in range, then places it (as the original's ground-target skills do)."""
        pending = getattr(self, "pending_camera", None)
        if not pending:
            return []
        xyz, how, issued, walk_to = pending
        m = self.m
        if m.mover.target is not None and math.hypot(m.mover.target[0] - walk_to[0],
                                                     m.mover.target[1] - walk_to[1]) > 1.0:
            self.pending_camera = None             # the player sent him elsewhere
            return []
        if m.mover.target is None and now - issued > 0.5 and \
                m.mover.distance_to(xyz) > self.camera_range() + 0.2:
            self.pending_camera = None             # he was stopped
            return []
        if m.mover.distance_to(xyz) <= self.camera_range():
            self.pending_camera = None
            m.mover.target, m.mover.speed = None, 0.0
            m.sequence += 1
            return [("Batman stops to place the camera", m.champion_bundle(now))] + \
                self.place_camera(xyz, now, how, walked=True)
        return []

    def camera_range(self):
        # the camera skill's stat 18 (range) is 10 m ([tutorial] camera_range)
        return float(self.tc.get("camera_range", 10.0))

    def _camera_spot(self, xyz):
        """The clicked point if Batman could stand there and see it, else the nearest such spot."""
        mv = self.m.mover
        bx, by = mv.pos[0], mv.pos[1]
        goal = mv.free_goal(bx, by, xyz[0], xyz[1])
        if goal is None:
            return None
        gx, gy = goal
        if mv.segment_clear(bx, by, gx, gy):
            return gx, gy
        d = math.hypot(gx - bx, gy - by)
        n = max(1, int(d / 0.25))
        last = (bx, by)
        for i in range(1, n + 1):
            px, py = bx + (gx - bx) * i / n, by + (gy - by) * i / n
            if mv.blocked(px, py) or not mv.segment_clear(bx, by, px, py):
                break
            last = (px, py)
        return last

    def place_camera(self, xyz, now, how, walked=False):
        """D (or the fallbacks): a surveillance camera at xyz."""
        from .world import Entity
        m = self.m
        if not self.camera_ready:
            self.t.log("D: Batman has no Stolen Power yet")
            return []
        if how == "D" and self.tc.get("camera_on_walkable", True):
            # 2026-10-17 15:26 (tester's video): cameras could be put off the map, in the water or
            # inside the vehicles. The click is moved to the nearest free spot (outside every
            # obstacle: walls, vehicles, the bridge edges) and pulled back along the line from Batman
            # to the last spot before an obstacle ([tutorial] camera_on_walkable)
            legal = self._camera_spot(xyz)
            if legal is None:
                self.t.log(f"D at ({xyz[0]:.1f}, {xyz[1]:.1f}): no free spot there")
                return []
            if math.hypot(legal[0] - xyz[0], legal[1] - xyz[1]) > 0.05:
                self.t.log(f"D at ({xyz[0]:.1f}, {xyz[1]:.1f}): moved to ({legal[0]:.1f}, {legal[1]:.1f}) "
                           "(outside the walkable area)")
            xyz = (legal[0], legal[1], xyz[2] if len(xyz) > 2 else Z)
        if how == "D" and not walked and m.mover.distance_to(xyz) > self.camera_range():
            # 12:18 (tester): out of range -> walk until it is in range
            bx, by, _ = m.mover.pos
            d = m.mover.distance_to(xyz)
            k = (d - self.camera_range() + 0.5) / d
            m.mover.target = [bx + (xyz[0] - bx) * k, by + (xyz[1] - by) * k, m.mover.pos[2]]
            self.pending_camera = (tuple(xyz), how, now, list(m.mover.target))
            self.t.log(f"D at ({xyz[0]:.1f}, {xyz[1]:.1f}): {d:.1f} m away, Batman walks into range")
            return []
        if self.stage == "camera_intro":
            self.t.log("D: wait for Superman to say where the camera goes")
            return []
        last = getattr(self, "last_camera_at", 0.0)
        if now - last < 1.0 or len(self.cameras) >= int(self.tc.get("camera_charges", 3)):
            self.t.log("D: no camera charge left" if now - last >= 1.0 else "D: repeated order ignored")
            return []
        spot = self.pos("camera")
        on_spot = math.hypot(xyz[0] - spot[0], xyz[1] - spot[1]) <= float(self.tc.get("camera_spot_radius", 3.5))
        if self.stage == "camera" and not on_spot:
            self.t.log(f"D at ({xyz[0]:.1f}, {xyz[1]:.1f}): not on the marked spot "
                       f"({math.hypot(xyz[0] - spot[0], xyz[1] - spot[1]):.1f} m away)")
            return []
        eid = m._next_eid
        m._next_eid += 1
        cam = Entity(eid, f"Camera{len(self.cameras) + 1}", int(self.tc.get("camera_entity", batman.CAMERA_ENTITY)),
                     (xyz[0], xyz[1], Z), m.mover.heading - math.pi / 2, m.team)
        cam.extra_props = [(0x1000009C, KIND_INT, m.team)]          # Batman's team
        cam.no_fog = True
        m.entities[eid] = cam
        self.cameras.append(eid)
        self.last_camera_at = now
        self.t.log(f"tutorial: surveillance camera ({how}) at ({xyz[0]:.1f}, {xyz[1]:.1f})")
        msgs = [(f"surveillance camera {cam.class_id:#x} ({how})", m.entity_bundle(cam, now))]
        if self.stage != "camera":
            return msgs
        self._stage("camera_done")
        msgs += self._unmark("camera") + self.t.say(0x1BD)
        self.t.schedule(0.5 * float(self.tc.get("pacing", 1.0)), self.after_speech(self._open_second_gate))
        return msgs

    def _open_second_gate(self):
        """'Keep fighting your way to the base.': the next gate opens; four drones
        are hitting the last gate of the bridge."""
        self._stage("gate_fight")
        msgs = self.t.say(0x1D2) + self.open_gate("03GateMid", "the camera is placed")
        msgs.append((f"tutorial hint {HINT_SKILL_CHARGES}", M.tutorial_hint(HINT_SKILL_CHARGES)))
        gate = self._gate_xyz("03GateB")
        msgs += self.spawn_group("gate", [("BridgeGateMelee1", "melee", "gate_melee1"),
                                          ("BridgeGateMelee2", "melee", "gate_melee2"),
                                          ("BridgeGateRanged1", "ranged", "gate_ranged1"),
                                          ("BridgeGateRanged2", "ranged", "gate_ranged2")],
                                 aggressive=False, face=gate[:2])
        self.hit_targets["gate"] = "03GateB"
        self._start_hitting()
        self.flags.add("gate_marker")
        return msgs + self._marker("gate_drones")

    def _after_gate(self):
        self._stage("unlock_e")
        return self.beats(((0.5, "conv", 0x1C6), (0.5, "call", lambda: self.level_up(5)),
                           (2.5, "call", self.after_speech(lambda: self.prompt_rank(batman.SLOT_E, 0x1D1)))))

    def _e_practice(self):
        self._stage("e_practice")
        xyz = self.pos("e_target")
        return self.beats(((0.5, "conv", 0x190),
                           (0.5, "call", lambda: self.target_drone("BridgeTargetE", xyz, batman.SLOT_E)),
                           (0.5, "objective", OBJ_E_PRACTICE), (4.0, "conv", 0x1AA)))

    def _more_drones(self):
        self._stage("more_drones")
        # they come from the far end of the bridge ([tutorial] bridge_positions
        # more_melee1 ... more_ranged2 fix them instead)
        sb = self.batman_s()
        ahead = float(self.tc.get("more_drones_distance", 8.0))
        s = sb + ahead if sb + ahead <= self.gate_s("03GateB") - 1.0 else sb - ahead   # behind him if no room ahead
        spots = {"more_melee1": along(s - 1.0, -0.4), "more_melee2": along(s - 1.0, 2.0),
                 "more_ranged1": along(s, 0.0), "more_ranged2": along(s, 2.4)}
        raw = self.tc.get("bridge_positions") or {}
        specs = [(f"BridgeMore{k[5:].capitalize()}", k[5:-1], self.pos(k) if k in raw else xyz)
                 for k, xyz in spots.items()]
        return self.t.say(0x1AE) + self.spawn_group("more", specs)

    def _passive(self):
        self._stage("passive")
        return self.beats(((0.5, "call", lambda: self.level_up(None)),
                           (0.5, "call", lambda: self.prompt_rank(batman.SLOT_PASSIVE, 0x1A1, HINT_PASSIVE))))

    def _after_passive(self):
        self._stage("passive_done")
        return self.beats(((0.5, "conv", 0x18F), (1.0, "call", self.after_speech(self._lets_go))))

    def _lets_go(self):
        """'Let's go!': the last gate opens; at the end of the bridge four drones
        are hitting a vehicle."""
        from . import tutorial1
        self._stage("vehicle")
        m = self.m
        now = time.time()
        msgs = self.t.say(0x1E2) + self.open_gate("03GateB", "Let's go!")
        vxyz = self.pos("vehicle")
        tutorial1.EXTRA_SPAWNS["BridgeVehicle"] = (int(self.tc.get("bridge_vehicle_wstate", VEHICLE_WS) or VEHICLE_WS), vxyz, float(self.tc.get("bridge_vehicle_yaw", VEHICLE_YAW)))
        before = set(m.entities)
        msgs += m.spawn("BridgeVehicle", now, attackable=False, xyz=vxyz)
        for eid in set(m.entities) - before:
            self.t.resend(m.entities[eid])
        hl, hw = m.cfg["combat"].get("vehicle_box", [4.0, 1.6])
        m.mover.obstacles["BridgeVehicle"] = (vxyz[0], vxyz[1], float(hl), float(hw),
                                              float(self.tc.get("bridge_vehicle_yaw", VEHICLE_YAW)))
        msgs += self.spawn_group("vehicle", [("BridgeVehicleMelee1", "melee", "vehicle_melee1"),
                                             ("BridgeVehicleMelee2", "melee", "vehicle_melee2"),
                                             ("BridgeVehicleRanged1", "ranged", "vehicle_ranged1"),
                                             ("BridgeVehicleRanged2", "ranged", "vehicle_ranged2")],
                                 aggressive=False, face=vxyz[:2])
        self.hit_targets["vehicle"] = "BridgeVehicle"
        self._start_hitting()
        return msgs

    def _after_vehicle(self):
        self._stage("unlock_r")
        return self.beats(((0.5, "conv", 0x1CB), (0.5, "call", lambda: self.level_up(6)),
                           (2.5, "call", self.after_speech(lambda: self.prompt_rank(batman.SLOT_R, 0x1DC)))))

    # ---- the Bat Scream ------------------------------------------------------------
    def _scream_intro(self):
        """R unlocked: the surveillance camera has spotted three drones hitting
        the gate two sections back."""
        self._stage("scream_intro")
        return self.beats(((0.5, "conv", 0x1A0), (0.5, "call", self._scream_drones),
                           (1.0, "call", self.after_speech(self._camera_unlock_lines))))

    def _scream_drones(self):
        gate = self._gate_xyz("03GateMid")
        msgs = self.spawn_group("scream", [("BridgeScream1", "melee", "scream1"),
                                           ("BridgeScream2", "melee", "scream2"),
                                           ("BridgeScream3", "melee", "scream3")],
                                aggressive=False, face=gate[:2])
        for eid in self.groups.get("scream", ()):
            e = self.m.entities.get(eid)
            if e:
                e.only_slot = batman.SLOT_R            # out of reach of anything else anyway
        self.no_aggro.add("scream")
        self.hit_targets["scream"] = "03GateMid"
        self._start_hitting()
        return msgs + self._alert_marker()

    def _alert_marker(self):
        """A red alert ping (the player's Alt+click marker) on the drones."""
        from . import tutorial1
        import struct
        m = self.m
        pts = [m.entities[e].pos for e in self.groups.get("scream", ()) if e in m.entities]
        if not pts:
            return []
        x = sum(p[0] for p in pts) / len(pts)
        y = sum(p[1] for p in pts) / len(pts)
        # its own object id: the last of the player pings' 32 (the player's own
        # pings count up from the first one)
        result = tutorial1.player_ping(m, struct.pack("<ffQI", x, y, 0, 1), 0x1F, time.time())
        if not result:
            return []
        object_id, data, notes = result
        self.alert_ids = [object_id] + [n for n, _ in notes]
        self.t.log(f"tutorial: red alert marker on the Bat Scream drones at ({x:.1f}, {y:.1f})")
        return [(f"alert marker {object_id:#x}", data)] + [(f"minimap note {n:#x}", d) for n, d in notes]

    def _remove_alert(self):
        ids, self.alert_ids = self.alert_ids, []
        return [("alert marker removed (0x3)", M.remove_object(i)) for i in ids]

    def _camera_unlock_lines(self):
        """'Your camera is currently locked to Batman. To view other areas,
        unlock your camera.'"""
        self._stage("camera_unlock")
        msgs = self.t.say(0x1C8) + self.t.say(0x1B6) + self.t.say(0x1B0)
        wait = float(self.tc.get("camera_unlock_wait", 10.0) or 0)

        def fallback():
            if self.stage != "camera_unlock":
                return []
            self.t.log("tutorial: no 'camera unlocked' from the client: going on")
            return self._scream_lines()
        self.t.schedule(0.5, self.after_speech(lambda: (self.t.schedule(wait, fallback), [])[1]))
        if self.camera_locked is False:            # already unlocked
            self.t.schedule(0.5, self.after_speech(lambda: self._scream_lines() if self.stage == "camera_unlock"
                                                    else []))
        return msgs

    def camera_lock_changed(self, locked, now):
        """The client's User.CameraLocked preference (Y / the camera lock key)."""
        self.camera_locked = locked
        self.t.log(f"tutorial: camera {'locked on Batman' if locked else 'unlocked'}")
        if not locked and self.stage == "camera_unlock":
            return self.after_speech(self._scream_lines, 0.3)() or []
        if locked and self.stage == "camera_lock":
            return self._end()
        return []

    def _scream_lines(self):
        if self.stage != "camera_unlock":
            return []
        self._stage("scream_lines")
        msgs = self.t.say(0x1CA) + self.objective(OBJ_PAN) + self.t.say(0x1B5) + self.t.say(0x1D8)
        self.t.schedule(0.3, self.after_speech(self._scream_prompt, 0.2))
        return msgs

    def _scream_prompt(self):
        if self.stage != "scream_lines":
            return []
        self._stage("scream")
        return self.t.say(0x1D0) + self._scream_objective()

    def _scream_objective(self):
        n = self.group_size.get("scream", 0)
        return self.objective(OBJ_SCREAM.format(n - self.group_left("scream"), n))

    def _scream_killed(self, left):
        msgs = self._scream_objective() if self.stage in ("scream", "scream_lines") else []
        if left:
            return msgs
        self.hit_targets.pop("scream", None)
        self.t.log("tutorial: the Bat Scream drones are defeated")
        return msgs + self._remove_alert() + self._scream_done()

    def scream_result(self, hit):
        """A Bat Scream has finished: hit = the entities it hit."""
        if self.stage not in ("scream", "scream_lines", "camera_unlock", "scream_intro"):
            return []
        mine = [e for e in hit if getattr(e, "group", None) == "scream"]
        if self.group_left("scream") and not mine:
            self.t.log("tutorial: the Bat Scream missed the drones")
            return self.t.say(0x3AC)
        return []

    def _scream_done(self):
        """'Good shot!' -- then lock the camera on Batman again."""
        self._stage("camera_lock_lines")

        def lines():
            self._stage("camera_lock")
            msgs = self.t.say(0x1AD) + self.t.say(0x1A8) + self.t.say(0x19F) + self.objective(OBJ_LOCK)
            if self.camera_locked:                 # never unlocked (or locked again already)
                self.t.schedule(0.5, self.after_speech(lambda: self._end() if self.stage == "camera_lock" else []))
                return msgs
            wait = float(self.tc.get("camera_lock_wait", 10.0) or 0)
            self.t.schedule(0.5, self.after_speech(lambda: (self.t.schedule(
                wait, lambda: self._end() if self.stage == "camera_lock" else []), [])[1]))
            return msgs
        return self.t.say(0x1A5) + (self.after_speech(lines, 0.3)() or [])

    def _end(self):
        if self.stage == "end":
            return []
        self._stage("end")
        self.t.log("tutorial: the Bat Scream part is over: on to the finale")
        return self.t.finale.start(time.time())

    # ---- every AI tick -------------------------------------------------------------
    def update(self, now):
        """Markers, gates closing behind Batman, drones noticing him."""
        if not self.stage:
            return []
        m = self.m
        s = self.batman_s()
        out = []
        if self.stage == "to_marker":
            xyz = self.pos("marker1")
            if m.mover.distance_to(xyz) <= float(self.tc.get("bridge_marker_radius", 2.0)):
                out += self._ambush()
        if (self.stage in ("gate_fight", "unlock_e", "e_practice", "e_practice_done", "more_drones")
                and "gate2_closed" not in self.flags and s >= float(self.tc.get("gate2_close_at", 27.0))):
            out += self.close_gate("03GateMid", "half way to the last gate")
            if self.gate_state.get("03GateMid") == "closed":
                self.flags.add("gate2_closed")
        # 10:29: the drones at the gate and at the vehicle only turn on Batman
        # when one of them is attacked ([tutorial] gate_drones_notice /
        # vehicle_drones_notice > 0: also when he comes that close)
        notice = float(self.tc.get("gate_drones_notice", 0) or 0)
        if "gate" in self.hit_targets and notice > 0:
            near = [eid for eid in self.groups.get("gate", ()) if eid in m.entities
                    and m.entities[eid].alive and m.entities[eid].distance_to(m.mover.pos[:2]) <= notice]
            if near:
                out += self._aggro_group("gate", "Batman came close")
        if self.stage == "vehicle":
            if ("gate3_closed" not in self.flags and self.tc.get("gate3_reclose", True)
                    and s >= self.gate_s("03GateB") + float(self.tc.get("gate3_close_after", 6.0))):
                out += self.close_gate("03GateB", "Batman went past it")
                if self.gate_state.get("03GateB") == "closed":
                    self.flags.add("gate3_closed")
            notice = float(self.tc.get("vehicle_drones_notice", 0) or 0)
            if "vehicle" in self.hit_targets and notice > 0:
                near = [eid for eid in self.groups.get("vehicle", ()) if eid in m.entities
                        and m.entities[eid].alive and m.entities[eid].distance_to(m.mover.pos[:2]) <= notice]
                if near:
                    out += self._aggro_group("vehicle", "Batman came close")
        return out

    # ---- immunities ----------------------------------------------------------------
    def wrong_attack(self, ent, slot):
        """A target drone hit by the wrong attack (basic attack = slot 0)."""
        if slot == 0:
            return self.say_once(CONV_ONLY_SKILLS)
        msgs = self.say_once(CONV_INEFFECTIVE)
        return msgs or self.say_once(CONV_TRY_SKILL)

    # ---- jumping straight to a part ([tutorial] start_at) -------------------------
    def jump(self, where, now):
        from . import tutorial1
        spec = JUMPS.get(where)
        if not spec:
            self.t.log(f"start_at '{where}': unknown (use one of {', '.join(JUMPS)})")
            return []
        m = self.m
        t = self.t
        t.log(f"tutorial: start_at = {where} (part 1 skipped)")
        t.phase = "bridge"
        t.step = 4
        t.first_attack_done = True
        msgs = t._level_up() + t._vehicle_destroyed(blast=False)
        m.level = spec["level"]
        m.skill_points = 0
        m.skill_ranks = sum(r << (4 * slot) for slot, r in spec["ranks"].items())
        if spec.get("camera"):
            self.camera_ready = True
            if self.tc.get("stolen_power_property", "auto"):
                from . import skilldata
                table = skilldata.stolen_power(m.cfg, stolenpowers.resolve(self.tc.get("camera_skill"), skilldata.CAMERA_VERSION))
                if table:
                    m.stolen_powers[batman.SLOT_D] = table
            msgs.append(("HUD element 22 (D button) restored (0x213d)",
                         M.hud_element(batman.HUD_SKILL_BUTTON_D, HUD_EVENT_RESTORE)))
            # the camera placed earlier in the tutorial (it gives vision there)
            msgs += self.place_camera(self.pos("camera"), now, "start_at")
        # 08:02 (tester): an extra "+" on the left of the HUD: the passive's upgrade
        # button (19), restored because the passive has a rank here; it is never
        # ranked by the player, so its button stays hidden
        for button in {HUD_UPGRADE_BUTTON[s] for s in spec["ranks"] if s != batman.SLOT_PASSIVE}:
            msgs.append((f"HUD element {button} restored (0x213d)", M.hud_element(button, HUD_EVENT_RESTORE)))
        m.mover.place(spec["at"], math.atan2(U[1], U[0]))
        m.sequence += 1
        msgs.append((f"Batman placed for '{where}'", m.champion_bundle(now)))
        self.stage = "jump"
        go = {"bridge": lambda: self.start(time.time()), "camera": self._camera_intro,
              "gate_fight": self._open_second_gate, "unlock_e": self._after_gate,
              "e_practice": lambda: self._jump_rank(batman.SLOT_E, self._e_practice),
              "vehicle": self._lets_go, "scream": self._jump_scream,
              "strength": self._jump_finale, "destroyer": self._jump_destroyer}[where]
        if where == "bridge":
            self.stage = None
        if where in ("unlock_e", "e_practice", "vehicle", "scream"):
            self.flags.add("gate2_closed")
        if where in ("scream", "strength", "destroyer"):
            self.flags.add("gate3_closed")
        t.schedule(1.0, go)
        return msgs + [(f"tutorial hint {tutorial1.HINT_EXPERIENCE}", M.tutorial_hint(tutorial1.HINT_EXPERIENCE))]

    def _jump_scream(self):
        """start_at = "scream": the vehicle's drones are gone, R is unlocked."""
        self._stage("unlock_r")
        return self._scream_intro()

    def _jump_finale(self):
        """start_at = "strength": the Bat Scream part is over."""
        self._stage("end")
        return self.t.finale.start(time.time())

    def _jump_destroyer(self):
        """start_at = "destroyer": the Destroyer's cinematic is over."""
        self._stage("end")
        f = self.t.finale
        f.stage = "destroyer_cinematic"
        return f.give_super_strength() + f._after_destroyer_cinematic()

    def _jump_rank(self, slot, then):
        m = self.m
        m.skill_ranks += 1 << (4 * slot)
        m.sequence += 1
        return [("skill ranked for the jump", m.champion_bundle(time.time()))] + then()
