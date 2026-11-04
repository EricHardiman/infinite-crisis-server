"""Runs the original server's scripts (records 0x34) from their decoded model (ics/script_model.py).

Execution model (client VM, docs/re-notes/full-combat-skills.md 5.1; C = read in the client code):
  - a script's top-level graphs run in parallel; a graph is a state machine whose states have three chains:
    enter, update (every tick while in the state) and exit;
  - an action chain runs its nodes in order; an action chain used as a condition returns the result of its last
    node (true when it ends with an action); AnyOf / AllOf in an action chain are selector / sequence (C);
  - IfThenElse runs then / else and always its "after" chain; While stops after 1025 iterations (C); Switch compares
    a selector with case values, falling through empty children, default = child count-2, after = child count-1 (C);
  - transitions fire on a chain result code (trigger 0x10000019: 5 cast point, 3 cast finished, 2 done), on an
    event, on a condition (checked at every update while the state is active) or immediately when the state's
    enter chain ends. Transitions with no source states apply from any state;
  - timers (builtin 0x2 / 0x8): a timer never started counts as expired (C); PostEventDelayed (builtin 0x12) posts an
    event after a delay (C).
What each action node does is in ics/script_nodes.py (the combat / world nodes) and below (the VM's own nodes).

The game side is a World object (NullWorld documents the interface). The match provides the real one
(ics/world.py CastWorld); NullWorld logs everything for the command-line simulation:

    python -m ics.script_runtime 0x3400003B      simulate one Sonic Batarang (skill + its missile)
"""
import collections
import heapq
import itertools
import math
import time
import random
import struct

from . import script_model as V
from .combat import Combat, Handle

# result codes reported by a finished chain (trigger 0x10000019 with enum 0x1000000F)
RESULT_DONE, RESULT_CAST_DONE, RESULT_CAST_POINT = 2, 3, 5
COMPLETE = "complete"                # a state's chain ran to its end (plain transitions, field a = 1)
REENTER_ON_CODE = False              # [ics] any_reenter_on_code (kit-audit-3.md 7: Starro's 700 scriptlets / 3 s)
PREDICATE_FIRST = True               # [ics] predicate_first_in_conditions
GRAPH_HOOK_OFFSET = 0.13             # [ics] graph_hook_offset
KEEP_COSMETIC_TAIL = 0.8             # [ics] keep_cosmetic_tail (s, 0 = off)
EVENT_LOOP_LIMIT = 4                 # [ics] event_loop_limit (0 = no guard)
STATUS_STACK_MODEL = True            # [ics] status_stack_model (skill-mechanics-recipes.md 1)
EVENT_STACKS_CHANGED, EVENT_DURATION_CHANGED = 0x100000D7, 0x100000A8
TETHER_RETURN = True                 # [ics] tether_return
TETHER_RETRACT = True                # [ics] tether_retract
TETHER_RETURN_UNLIMITED = True       # [ics] tether_return_unlimited
STATS_REINIT = True                  # [ics] stats_reinit_skills
HOOKS_ATTACK_SPEED = True            # [ics] hooks_attack_speed
TETHER_DRAG = True                   # [ics] tether_drag
SKILL_USED_BROADCAST = True          # [ics] skill_used_broadcast
SKILL_USED_BROADCAST_TAKEN = True    # [ics] skill_used_broadcast_taken (test-2026-10-28-1439-sweep.md S5)
CARRIED_ARRIVE_COLLISION = True      # [ics] carried_arrive_collision
SPEND_BY_VITAL = True                # [ics] spend_by_vital (set by ics/server.py)
OWNER_BLOCK = True                   # [ics] script_owner_block (set by ics/server.py)
MISSILE_OWN_RETURN_EVENT = True      # [ics] missile_own_return_event (set by ics/server.py)
CAST_WAITS_TETHER = 4.0             # [ics] cast_waits_tether: s the cast's end (2) waits for its tethered missile
CAST_RECOVERY = 0.15                 # s from the cast point to the cast's end (not found in the data yet)
UPDATE_INTERVAL = 0.1                # s between runs of a state's update chain (the server's tick)
ANY_NO_REENTER = True                # [ics] polled_any_no_reenter (set by the server)
EXIT_REENTRY_GUARD = True            # [ics] exit_chain_reentry_guard (agl-e-r.md)
STOP_LEFT_SUBGRAPHS = True           # [ics] stop_left_subgraphs (Atomic Joker's R, 2026-11-02)
GRAPH_ENTER_FIRST = True             # [ics] graph_enter_before_children (Superman's E knockback, 2026-11-02)
STATUS_RECORD_FLAGS = True           # [ics] status_record_flags (Superman's W root, 2026-11-02)
LOCAL_FRAMES = True                  # [ics] local_frames (Superman's E punch target, 2026-11-03)
SLOT_COOLDOWN_VARS = True            # [ics] slot_cooldown_vars (Blue Beetle's per-form cooldowns, 2026-11-03)
HEADING_FROM_VECTOR = True           # [ics] heading_from_vector (Superman's E knockback direction, 2026-11-03)
GRAPH_DONE_WAITS = True              # [ics] graph_done_waits (Superman's E punch animation, 2026-11-03)
LAUNCH_SETS_TARGET = True            # [ics] spawn_event_after_chain (Blue Beetle's E shots, 2026-11-03)
HANDLE_RUNS = True                   # [ics] scriptlet_handle_runs (a StopScriptlet stops its own run, 2026-11-03)
SKILL_ECHO_NODE = True               # [ics] skill_echo_node (Blue Beetle's passive, 2026-11-03)
SKILL_USED_EVERY_USE = True          # [ics] skill_used_every_use (Blue Beetle's W detonation, 2026-11-03 23:24)
STATUS_TIMER_FIRST_WAIT = {0x340002BF}  # [ics] status_timer_first_wait: status script DIDs (agl-qer-lift.md 3)
# [ics] missile_destroy_delay_scripts: missile scripts whose own DestroyEntity(SELF, delay) decides when a homing missile
# that reached its target goes (agl-r-impact-q-e.md 3.2)
MISSILE_DESTROY_DELAY_SCRIPTS = {0x340002BE}
MISSILE_DESTROY_FALLBACK = 2.0       # s: the end of such a missile if its script never destroys it
DEFER_HOOKS_IN_CHAIN = True          # [ics] defer_graph_hooks_in_chain (2026-10-28, R vs champions)
RESET_LOCALS = True                  # [ics] reset_state_locals (skill-mechanics-recipes.md 5)
LOCAL_Y_FORWARD = True               # [ics] local_y_forward (skill-mechanics-recipes.md 3)
POLL_ONCE_PER_TICK = True            # [ics] script_poll_once_per_tick (map-objectives-recipes.md 6 gap 2)
POLL_GUARD_EVENT_RESET = True        # [ics] poll_guard_event_reset (2026-10-28, R vs champions)
EXIT_UPDATE = True                   # [ics] update_before_event_exit (2026-10-28, R vs champions)
EXPIRE_LINGER = 5.0                  # [ics] missile_expire_linger: s a busy missile script runs on after its expiry
INT_COMPARE_32 = True                # [ics] int_compare_32bit (2026-10-28, R vs champions)
TOP_GRAPH_CHAINS = True              # [ics] top_graph_chains (2026-10-28, R vs champions)
# 2026-10-28 15:00 (tester report 2026-10-28 15:00: AGL's R must slow and keep hitting a moving target;
# docs/re-notes/meltdown-moving-target.md 6; set by ics/server.py)
REAIM_FROM_CURRENT = True            # [ics] missile_reaim_from_current: a mid-flight re-aim starts where the missile is
STATUS_ACTS_FOR_SOURCE = True        # [ics] status_acts_for_source: a status acts for its applier (acting_entity)
EVENT_LOOP_PER_TARGET = True         # [ics] event_loop_per_target: the event loop guard counts per event target
BURST_LIMIT = 24                     # nested transitions of one instance before the rest waits a tick
WHILE_LIMIT = 1025                   # the client's While stops after 1025 iterations (0x45B8D0, C)
EVENT_ACTIVATE = 0x1000001D          # skill used (trigger 0x1000013B in the skill's main graph)
EVENT_SPAWN = 0x10000049             # a missile was created (missile script: start)
EVENT_COLLISION = 0x10000002         # a missile reached an entity (trigger 0x10000055)
EVENT_EXPIRED = 0x10000035           # a missile ran out of range / time
EVENT_MISSILE_TARGET = 0x100000EE    # a missile's target (TargetIID / TargetPosition), P from the data
EVENT_INTERRUPT = 0x10000009         # skill interrupted / script ending
EVENT_REINIT = 0x10000008            # rank / level / stats changed (the skills' re-init family, P)
EVENT_ATTRIBUTE = 0x100000A2         # an attribute value changed (OnAttributeChanged 0x100000B1)
EVENT_COMBAT = 0x10000020            # a hit: attacker, defender, value (OnCombatEventByKind 0x1000002C)
MARKER_HIT = 0x100003AB              # "already hit by this missile" marker (0x1000006A)
PARAM_ATTRIBUTE = "__attribute__"    # event parameter: the attribute id (the client's hash is set at run time)
PARAM_CODE = "__code__"              # event parameter: the cast result code (OnCastSignal)
PARAM_A, PARAM_B, PARAM_VALUE = "__a__", "__b__", "__value__"   # two-entity event (0x1000002C)

# words taken by a variable's default value, by variable type (server-only block in the packs; fix C of
# script-nodes-complete.md: 0xA is 1 word when empty, else 3; 0xC is 5)
DEFAULT_WORDS = {7: 2, 8: 2, 9: 3, 0xA: 3, 0xC: 5, 0xD: 2, 0xE: 2}

# structural and builtin classes (decoder vtables; the type ids of the node and expression registries overlap)
VT_ASSIGN, VT_LIST, VT_LOOP, VT_ALL, VT_ANY = "0x15A89C0", "0x15A8B68", "0x15A8B98", "0x15A8ADC", "0x15A8B0C"
VT_COND, VT_NODECOND, VT_EVENT = "0x15A8764", "0x15A890C", "0x15A8794"
VT_START_TIMER, VT_TIMER_EXPIRED, VT_IS_TRUE, VT_COPY = "0x15A8880", "0x15A8820", "0x15A89F0", "0x15A8A50"
VT_POST_EVENT, VT_HAS_PARAM, VT_SWITCH, VT_SET_BOOL = "0x15A88E0", "0x15A8850", "0x15A8BC8", "0x15A8A80"
VT_CLEAR, VT_EQUAL, VT_PENDING, VT_DEBUG = "0x15A8990", "0x15A8A20", "0x15A87C4", "0x15A8938"
VT_GET_ATTRIBUTE, VT_END_SCRIPT = "0x15FDD28", "0x15FA3C8"     # both type 0x10000002 (expression / node)
PREDICATE_VTS = {VT_ALL, VT_ANY, VT_COND, VT_NODECOND, VT_EVENT, VT_TIMER_EXPIRED, VT_IS_TRUE, VT_HAS_PARAM,
                 VT_EQUAL, VT_PENDING}
EXPR_OPS = dict(V.EXPR)
EXPR_OPS.update({
    "0x15A9050": ">=", "0x15A9328": "!", "0x15A9088": "<=", "0x15A8FE0": ">", "0x15A9C20": "transform",
    "0x15A9408": "--", "0x15A92B8": "or", "0x15A92F0": "and", "0x15A9558": "abs", "0x15A90C0": "min",
    "0x15A95C8": "sqrt", "0x15A9168": "&", "0x15A96A8": "cos", "0x15A9670": "sin", "0x15A96E0": "tan",
    "0x15A9360": "pow", "0x15A9B78": "random", "0x15A9B40": "round", "0x15A99B8": "int32", "0x15A9638": "ceil",
    "0x15A9600": "floor", "0x15A9BB0": "select", "0x15A9398": "neg", "0x15A8F44": "time", "0x15A9980": "z",
    "0x15A9948": "y", "0x15A9910": "x", "0x15A9C90": "heading", "0x15A9BE8": "with_heading", "0x15A98D8": "len2",
    "0x15A9750": "deg2rad", "0x15A9788": "rad2deg", "0x15A9D00": "forward", "0x15A9CC8": "location",
    "0x15A9A28": "uint32", "0x15A99F0": "float", "0x15A9AD0": "uint64", "0x15A9A98": "double", "0x15A9A60": "int64",
    "0x15A9130": "clamp", "0x15A9B08": "mod", "0x15A9520": "imod", "0x15A9590": "log", "0x15A9718": "atan",
    "0x15A91D8": "^", "0x15A91A0": "|", "0x15A9210": "<<", "0x15A9248": ">>", "0x15FABA4": "lerp",
    "0x15FABDC": "scale_by_level", VT_GET_ATTRIBUTE: "get_attribute", "0x15FDCFC": "get_attribute",
    "0x15FAA28": "null", "0x15A9280": "~", "0x15A94E8": "/",
})
# trees decoded before fix B of the decoder label the two late-registered expressions this way
SERVER_EXPR = {"server-expr:0x10": "or", "server-expr:0xc": "--"}


def f32(v):
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]
    return 0.0


def num(v):
    """A variable value as a number (raw u32 floats from literals are converted)."""
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int) and v > 0xFFFFF:
        return f32(v)
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


class Frame(tuple):
    """A position with a yaw (the VM's frames: location + orientation; on the ground pitch / roll stay 0). The yaw
    is in degrees, in the server's heading convention (atan2(dy, dx))."""

    def __new__(cls, pos, yaw=0.0):
        self = super().__new__(cls, tuple(float(x) for x in tuple(pos)[:3]))
        self.yaw = float(yaw)
        return self

    def __repr__(self):
        return f"Frame({tuple(self)}, yaw={self.yaw:g})"


def _vec(v):
    if isinstance(v, tuple):
        t = tuple(float(x) if isinstance(x, (int, float)) else 0.0 for x in v[:3])
        return t + (0.0,) * (3 - len(t))
    return (num(v), 0.0, 0.0)


def _same(a, b):
    if a in (None, 0) and b in (None, 0):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if isinstance(a, float) or isinstance(b, float):
            return abs(num(a) - num(b)) < 1e-6
        if INT_COMPARE_32 and a != b and -(1 << 31) <= min(a, b) and max(a, b) < (1 << 32):
            # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Arcane Supergirl's
            # Rao's Wrath 0x3400054D fills its charges when CurrentCharges == 4294967295, its record default; the
            # constant is a signed int (-1), so the charges stayed "unset" and the R could never be cast): 32-bit
            # integers compare by their bits ([ics] int_compare_32bit)
            return (a - b) % (1 << 32) == 0
        return a == b
    return a == b


class NullWorld:
    """World interface, logging only (simulation): a caster 'Batman' (team 1) and two drones (team 2)."""

    def __init__(self, log=print):
        self.log = log
        self.time = 0.0
        self.timers = []
        self.seq = 0
        self.entities = {"Batman": (0.0, 0.0, 0.0), "Drone": (8.0, 0.0, 0.0), "Drone2": (10.0, 3.0, 0.0)}
        self.teams = {"Batman": 1, "Drone": 2, "Drone2": 2}
        self.headings = {}
        self.health = {"Drone": 300.0, "Drone2": 300.0, "Batman": 600.0}
        self.max_health = {"Drone": 300.0, "Drone2": 300.0, "Batman": 600.0}
        self.will = {"Batman": 100.0}
        self.missiles = []
        self.scripts, self.statuses = {}, {}
        self.combat = Combat(self)
        self.sent = []                     # (kind, details) of every message a real world would send
        self.poll_conditions = True
        self._spawned = itertools.count(1)
        self.classes = {}
        self.kit, self.slot = {}, None     # optional: the caster's catalog kit (slot -> ics.gamedata.Skill)

    # time
    def now(self):
        return self.time

    def after(self, seconds, fn):
        self.seq += 1
        heapq.heappush(self.timers, (self.time + max(0.0, seconds), self.seq, fn))

    def run_until(self, until, max_steps=50000):
        while self.timers and self.timers[0][0] <= until and max_steps > 0:
            max_steps -= 1
            t, _, fn = heapq.heappop(self.timers)
            self.time = max(self.time, t)
            fn()
        self.time = max(self.time, until)

    def emit(self, what, **details):
        self.sent.append((what, details))
        self.log(f"[{self.time:6.2f}]   {what} " + " ".join(f"{k}={v}" for k, v in details.items()))

    # data
    def skill_stat(self, owner, stat, rank):
        if self.kit and self.slot in self.kit and stat in self.kit[self.slot].stats:
            return self.kit[self.slot].stat(stat, rank)
        base = {3: -40.0, 5: 60.0, 15: 5.0, 18: 9.0, 30: 14.0, 17: 4.0, 22: 1.25, 2: 1.0, 14: 2.0}.get(stat, 0.0)
        per = {5: 25.0, 2: 1.0, 3: -10.0}.get(stat, 0.0)
        return base + per * (rank - 1)

    def skill_ref(self, owner):
        return self.kit.get(self.slot) if self.kit else None

    def slot_stat(self, owner, slot, stat, rank):
        """A stat of another slot of the owner (LoadSkillStats [.., slot]): the catalog kit when given."""
        sk = self.kit.get(slot) if self.kit else None
        return sk.stat(stat, rank) if sk is not None and stat in sk.stats else None

    def slot_rank(self, owner, slot):
        return 1

    def skill_rank(self, owner):
        return 1

    def skill_slot(self, owner):
        return None

    def property_kind(self, prop):
        return None

    def base_attribute(self, ent, prop):
        if prop == 0x10000167:
            return 1.0
        return None

    def attribute(self, ent, prop, mode=0):
        v = self.combat.attribute(ent, prop, mode)
        if mode == 0 and v == 0.0 and self.combat.kind(prop) != 0x16 and not self.combat.of(ent).mods.get(prop):
            return 1.0                     # numbers read by the scripts (attack speed ...) default to 1
        return v

    def conversation(self, key):
        self.log(f"[{self.time:6.2f}]   conversation {key}")

    def player(self):
        return "Batman"

    # entities
    def position(self, ent):
        if isinstance(ent, tuple):
            return ent
        if isinstance(ent, Missile):
            return tuple(ent.pos)
        return self.entities.get(ent, (0.0, 0.0, 0.0))

    def heading(self, ent):
        return self.headings.get(ent, 0.0) if not isinstance(ent, tuple) else getattr(ent, "yaw", 0.0) * math.pi / 180

    def radius(self, ent):
        return 0.5

    def alive(self, ent):
        if isinstance(ent, Missile):
            return ent.alive
        return ent in self.entities and self.health.get(ent, 1.0) > 0

    def exists(self, ent):
        if isinstance(ent, Missile):
            return ent.alive
        return isinstance(ent, str) and ent in self.entities

    def team(self, ent):
        if isinstance(ent, Missile):
            return self.team(ent.owner)
        return self.teams.get(ent, 0)

    def set_team(self, ent, team):
        if isinstance(ent, str):
            self.teams[ent] = int(team)

    def hostile(self, a, b):
        if isinstance(a, Missile):
            a = a.owner
        return a != b and (a == "Batman") != (b == "Batman")

    def kind_matches(self, ent, flags):
        if isinstance(ent, Missile):
            return bool(flags & 0x20)
        return flags & 0x100 != 0 and ent != "Batman" or (flags & 0x8 != 0 and ent == "Batman")

    def class_of(self, ent):
        return self.classes.get(ent, 0)

    def all_entities(self):
        return [e for e in self.entities if self.alive(e)]

    def find_targets(self, center, radius, flags):
        c = self.position(center)
        return [e for e in self.entities if e != "Batman" and self.alive(e)
                and math.dist(self.position(e)[:2], c[:2]) <= radius]

    def has_status(self, ent, status):
        return bool(statuses_on(self, ent).get(status))

    # vitals
    def vital(self, ent, vital, maximum=False):
        if vital == 2:
            return (self.max_health if maximum else self.health).get(ent, 0.0)
        if vital == 5 and ent in self.will:
            return 100.0 if maximum else self.will[ent]
        v = self.combat.of(ent).vitals.get(vital)
        return (v[1] if maximum else v[0]) if v else 0.0

    def set_vital(self, ent, vital, value):
        if vital == 2:
            self.health[ent] = max(0.0, min(self.max_health.get(ent, value), value))
        elif vital == 5 and ent in self.will:
            self.will[ent] = max(0.0, min(100.0, value))
        else:
            v = self.combat.of(ent).vitals.setdefault(vital, [0.0, 100.0])
            v[0] = max(0.0, min(v[1], value))

    def vitals_changed(self, ent):
        self.emit("vitals", ent=ent)

    # actions
    def face(self, owner, target):
        p = self.position(target)
        o = self.position(owner)
        if isinstance(owner, str) and abs(p[0] - o[0]) + abs(p[1] - o[1]) > 1e-6:
            self.headings[owner] = math.atan2(p[1] - o[1], p[0] - o[0])
        self.log(f"[{self.time:6.2f}]   face {target}")

    def run_scriptlet(self, ent, key, target=None, variables=None):
        self.log(f"[{self.time:6.2f}]   scriptlet {key:#x} on {ent}" + (f" (target {target})" if target else ""))
        g = graph_of(self, ent)
        if g is not None:
            g.scriptlet(key, variables)

    graphs = None                          # {entity: ics.graph.GraphInstance} (tests / simulation)

    def graph_for(self, ent):
        return (self.graphs or {}).get(ent)

    def stop_scriptlet(self, ent, key=None, handle=None):
        self.emit("stop scriptlet", ent=ent, key=f"{key:#x}" if key else handle)

    def start_cooldown(self, owner, seconds, slot=None):
        self.log(f"[{self.time:6.2f}]   cooldown {seconds:g} s")
        if slot is not None:
            self.combat.set_cooldown(owner, slot, self.time + seconds)

    def on_cooldown(self, ent, slot, end):
        self.emit("cooldown", ent=ent, slot=slot, end=round(end, 3))

    def spend(self, owner, amount):
        if owner in self.will:
            self.will[owner] = max(0.0, self.will[owner] - abs(amount))
        self.log(f"[{self.time:6.2f}]   spend {amount:g} Will")

    def damage(self, source, target, amount):
        if isinstance(target, Missile):
            return
        self.health[target] = self.health.get(target, 0.0) - amount
        self.log(f"[{self.time:6.2f}]   damage {amount:g} to {target} (health {self.health[target]:g})")

    def heal(self, source, target, amount):
        if target in self.health:
            self.health[target] = min(self.max_health.get(target, 1e9), self.health[target] + amount)
        self.log(f"[{self.time:6.2f}]   heal {amount:g} to {target}")

    def cast_time(self, owner):
        return 0.25

    def launch_missile(self, owner, missile_class, target, speed, max_range, scripts, **extra):
        m = Missile(self, owner, missile_class, target, speed, max_range, scripts, **extra)
        self.missiles.append(m)
        m.start()
        return m

    def missile_moved(self, missile, target):
        self.log(f"[{self.time:6.2f}]   missile -> {target}")

    # world effects (ics/script_nodes.py): logged
    def on_modifier(self, ent, attr, mod, added, value):
        self.emit("modifier" if added else "modifier removed", ent=ent, attr=f"{attr:#x}", op=mod.op,
                  value=mod.value, now=value)

    def on_attribute(self, ent, attr, old, new):
        raise_event(self, ent, EVENT_ATTRIBUTE, {PARAM_ATTRIBUTE: attr})

    def message(self, what, ent=None, **details):
        self.emit(what, ent=ent, **details)

    def spawn_entity(self, owner, cls, pos, props=None, visual=False):
        name = f"Spawn{next(self._spawned)}"
        self.entities[name] = tuple(pos[:3]) if pos else self.position(owner)
        self.teams[name] = self.team(owner)
        self.classes[name] = cls
        self.health[name] = self.max_health[name] = 100.0
        self.combat.of(name).creator = owner
        self.emit("spawn", cls=f"{cls:#x}", name=name)
        for s in missile_scripts(cls):
            start_script(s, name, self)
        return name

    def destroy(self, ent, delay=0.0):
        def gone():
            if isinstance(ent, str) and ent in self.entities and ent != "Batman":
                del self.entities[ent]
                self.emit("destroyed", ent=ent)
        self.after(delay, gone)

    def move(self, ent, pos, speed=0.0, teleport=False, quiet=False):
        if isinstance(ent, Missile):
            ent.pos = tuple(pos)
        elif isinstance(ent, str) and ent in self.entities:
            self.entities[ent] = tuple(float(x) for x in pos[:3])
        if not quiet:
            self.emit("teleport" if teleport else "move", ent=ent, pos=tuple(round(x, 2) for x in pos[:3]),
                      speed=round(speed, 2))

    def stop(self, ent):
        self.emit("stop", ent=ent)


def _collides(world, owner, ent):
    """A missile of owner's can run into ent: the world's collision rule (CastWorld.collides: not friendly, collision
    on; the missile script filters by kind / relation itself), else hostility (NullWorld)."""
    fn = getattr(world, "collides", None)
    return fn(owner, ent) if fn is not None else world.hostile(owner, ent)


class Missile:
    """A missile simulated on the server: it flies straight to its target and raises collision events
    on its scripts; it expires when the target is gone or out of range."""

    def __init__(self, world, owner, missile_class, target, speed, max_range, scripts, entity=None, offset=None,
                 lobbed=False, tether=False, slot=None, origin=None):
        self.world, self.owner, self.cls = world, owner, missile_class
        self.speed = max(speed, 1.0)
        self.max_range = max_range
        # origin: the entity it starts at when that is not its shooter (2026-10-28 15:00, tester report 2026-10-28
        # 15:00; meltdown-moving-target.md 6.2: Meltdown's jump missile, shot by AGL, starts at the old victim)
        self.origin = origin
        start = entity if entity is not None else (origin if origin is not None else owner)
        self.pos = tuple(world.position(start))
        if offset:
            self.pos = tuple(p + o for p, o in zip(self.pos, _vec(offset)))
        self.flown = 0.0
        self.alive = True
        self.carried = entity                  # an existing entity launched as the missile (SpawnEntity)
        self.lobbed, self.tether, self.slot = lobbed, tether, slot
        self.origin_slot = None                # the slot of the skill that launched it (set by LaunchMissile)
        self.instances = [Instance(s, self, world, {"ShooterIID": owner}) for s in scripts]
        self.target = target
        self.trip = 0

    def start(self):
        aim = {"TargetPosition": self.world.position(self.target)}
        if not isinstance(self.target, tuple):
            aim["TargetIID"] = self.target
        for inst in self.instances:
            scripts_on(self.world, self).append(inst)
            inst.start()
            inst.event(EVENT_SPAWN)
            # 2026-10-22 (data: 23 missile scripts take TargetIID / TargetPosition from event 0x100000EE, P "the
            # missile's target"): without it a homing missile (Green Lantern's Constrict) never knew its target
            inst.event(EVENT_MISSILE_TARGET, aim)
        if self.carried is not None:
            # 2026-10-22 (Sonic Shell 0x3400003A launches the shell 0x40000093 it spawned; the shell's script
            # 0x34000042 waits for 0x10000049 once when spawned and again when launched, then for 0x10000035 to
            # explode): the launched entity's own scripts get the missile events
            for inst in list(scripts_on(self.world, self.carried)):
                if not inst.var_by_name("ShooterIID"):
                    inst.vars_by_name("ShooterIID", self.owner)      # its damage checks CheckRelation(Shooter, ...)
                if LAUNCH_SETS_TARGET and "TargetIID" in aim and not inst.var_by_name("TargetIID"):
                    # 2026-11-03 (Blue Beetle's E shot 0x340004AA checks IsAlive($TargetIID) as soon as it is launched,
                    # before 0x100000EE below; P, [ics] spawn_event_after_chain)
                    inst.vars_by_name("TargetIID", aim["TargetIID"])
            raise_event(self.world, self.carried, EVENT_SPAWN)
            raise_event(self.world, self.carried, EVENT_MISSILE_TARGET, aim)
        self.fly_to(self.target)

    def fly_to(self, target):
        if REAIM_FROM_CURRENT and self.trip > 0 and target is not None and not isinstance(target, tuple):
            self._advance()
        self.target = target
        self.trip += 1
        trip = self.trip
        dest = self.world.position(target)
        dist = math.dist(self.pos[:2], dest[:2])
        self._leg = (self.world.time, tuple(self.pos), tuple(dest), self.speed, dist)
        if self.max_range and self.flown + dist > self.max_range * 1.5 + 1.0 and not (
                TETHER_RETURN_UNLIMITED and getattr(self, "returning", False)):
            # 2026-10-26 (grab-arm-carry.md 1, C: the return leg of a tether hit this check and the missile, whose beam is
            # Grab's arm, was gone 0.05 s after it turned back): a returning tether flies home whatever it has flown
            self.world.after(max(0.05, (self.max_range - self.flown) / self.speed), lambda: self.expire(trip))
            return
        if isinstance(target, tuple) and getattr(self.world, "segment_hits", True):
            # a skillshot at a point: the first hostile unit within 1 m of its line is hit on the way (the match's
            # world does the same each tick, World._missile_hits)
            hit = self._first_on_line(dest)
            if hit is not None:
                along, ent = hit
                self.world.after(along / self.speed, lambda: self.trip == trip and self.collide(ent))
        self.world.after(dist / self.speed, lambda: self.arrive(trip, target, dist))

    def _advance(self):
        """2026-10-28 15:00 (tester report 2026-10-28 15:00: Meltdown's orb never landed on a walking enemy;
        meltdown-moving-target.md 3.2 / 6.1, C: its script 0x340002BE sets the speed every 0.3 s, and each re-aim started
        a new trip from the launch point, so the arrival kept moving away): a re-aim in mid-flight starts where the
        missile is now, its client object's point (ObjectMissile) or else along its last leg; the stretch flown since the
        last aim counts in flown. Nothing moves when an arrival or a hit placed the missile since ([ics]
        missile_reaim_from_current)."""
        leg = getattr(self, "_leg", None)
        if leg is None:
            return
        t0, start, dest, speed, dist = leg
        ent = getattr(self, "entity", None)
        if ent is not None and getattr(ent, "pos", None) is not None:
            here = (float(ent.pos[0]), float(ent.pos[1]))
        else:
            f = 1.0 if dist <= 1e-6 else min(1.0, max(0.0, (self.world.time - t0) * speed / dist))
            here = (start[0] + (dest[0] - start[0]) * f, start[1] + (dest[1] - start[1]) * f)
        z = self.pos[2] if len(self.pos) > 2 else 0.0
        self.flown += math.hypot(here[0] - self.pos[0], here[1] - self.pos[1])
        self.pos = (here[0], here[1], z)

    def _first_on_line(self, dest):
        w = self.world
        start = self.pos
        dx, dy = dest[0] - start[0], dest[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return None
        best = None
        hit = getattr(self, "hit_set", set())
        for e in w.find_targets(((start[0] + dest[0]) / 2, (start[1] + dest[1]) / 2, 0.0), length / 2 + 1.0, 0x10108):
            if _key(e) in hit or not _collides(w, self.owner, e):
                continue
            p = w.position(e)
            t = ((p[0] - start[0]) * dx + (p[1] - start[1]) * dy) / length
            if not 0.0 <= t <= length:
                continue
            off = abs((p[0] - start[0]) * dy - (p[1] - start[1]) * dx) / length
            if off <= 1.0 and (best is None or t < best[0]):
                best = (t, e)
        if best is not None:
            self.hit_set = hit | {_key(best[1])}
        return best

    def set_speed(self, speed):
        if speed > 0 and self.alive and not getattr(self, "expired", False):
            self.speed = speed
            if getattr(self, "_tether_pending", False):
                return                             # the return speed of a tether that just hit (collide)
            if self.target is not None and not getattr(self, "returning", False):
                self.fly_to(self.target)

    def arrive(self, trip, target, dist):
        if not self.alive or trip != self.trip:
            return
        self.pos = self.world.position(target)
        self.flown += dist
        self._leg = None                           # placed: a re-aim from here starts here (_advance)
        if self.carried is not None and hasattr(self.world, "move"):
            self.world.move(self.carried, self.pos)
        if (isinstance(target, tuple) and self.tether and TETHER_RETRACT and TETHER_RETURN
                and not getattr(self, "returning", False) and self.world.alive(self.owner)):
            # 2026-10-25 22:07 (tester: Grab's arm is never seen, "an invisible projectile"): a tether that reaches the
            # end of its range with no hit was removed there after 0.4 s, so the arm (a beam from the missile back to
            # its creator) hardly showed; it retracts to the shooter first, then ends (0x10000005) ([ics] tether_retract)
            self._return(None)
            return
        if isinstance(target, tuple) or not self.world.alive(target):
            self.expire(trip)
            return
        if self.carried is not None and not self.instances and CARRIED_ARRIVE_COLLISION:
            # 2026-10-25 (kit-audit-2.md 11: Huntress Q, Blue Beetle E did no damage): a launched entity that reaches its
            # target collides there too, as on the way (collide)
            raise_event(self.world, self.carried, EVENT_COLLISION,
                        {"Collider": target, "SubEntity": 0, "EntityPosition": self.pos, 0xAE98CBC: 0})
        if getattr(self, "returning", False):
            if target is self._owner_target():
                self.end(trip)                     # back at the shooter: 0x10000005 (Missile.end)
            return
        for inst in self.instances:
            inst.event(EVENT_COLLISION, {"Collider": target, "SubEntity": 0, "EntityPosition": self.pos,
                                         0xAE98CBC: 0})          # 0xAE98CBC -> EtherealCollision: a solid hit
        if self.tether and self.trip == trip and self.alive and self._return(target):
            return
        # nothing redirected the missile: it is done
        if self.trip == trip and self.alive:
            if getattr(self, "destroy_pending", False) or any(
                    i.script.did in MISSILE_DESTROY_DELAY_SCRIPTS for i in self.instances):
                # 2026-10-30 (tester report 15:30: Meltdown's impact is lost; agl-r-impact-q-e.md 3.2, C traffic: the
                # object went 20 ms after its Vfx_OnCollision, while 0x340002BE S2 says DestroyEntity(SELF, 0.5 s), one
                # update tick after the hit): the script's own delayed DestroyEntity ends it, so the impact plays on the
                # object; a fallback ends it if the script never does ([ics] missile_destroy_delay_scripts)
                self.world.after(MISSILE_DESTROY_FALLBACK, lambda: self.end(trip))
                return
            self.world.after(0.0, lambda: self.end(trip))

    def _owner_target(self):
        return getattr(self, "_owner_ent", None) or self.owner

    def _return(self, hit):
        """2026-10-25 (tester: Atomic Green Lantern's Grab moves AGL to the enemy instead of pulling the enemy to him):
        a tethered missile that hits flies back to its shooter (Grab 0x340002C1 S1: SetMissileVelocity(ReturnVelocity),
        then S9 attaches to the target) dragging the target along; back at the shooter it ends (0x10000005).
        [ics] tether_return / tether_drag."""
        if not TETHER_RETURN:
            return False
        w = self.world
        owner = self.owner
        if owner is None or not w.alive(owner):
            return False
        self.returning = True
        self._owner_ent = owner
        for inst in list(getattr(self, "instances", ()) or ()):
            inst.event(0x10000106)                  # turned back (skill-mechanics-recipes.md 6, C: 4 scripts)
        if TETHER_DRAG and hit is not None and not isinstance(hit, tuple) and w.alive(hit) and hit is not owner                 and hasattr(w, "move"):
            op, hp = w.position(owner), w.position(hit)
            d = math.dist(op[:2], hp[:2]) or 1.0
            stop = 1.5 / d                          # stops in front of the shooter
            goal = [op[0] + (hp[0] - op[0]) * stop, op[1] + (hp[1] - op[1]) * stop, hp[2] if len(hp) > 2 else 0.0]
            # 2026-10-25 13:15 (tester's video: the arm shows now, but the minion only moved 0.5 m): a walking move was
            # cancelled by the grab's own stun ("stopped (crowd control)") and by the unit AI; the pull places the target
            # along the line every 0.05 s instead
            step = 0.05
            steps = max(1, int(math.dist(hp[:2], goal[:2]) / max(self.speed, 1.0) / step))
            start = list(hp)
            for i in range(1, steps + 1):
                f = i / steps
                p = [start[0] + (goal[0] - start[0]) * f, start[1] + (goal[1] - start[1]) * f, goal[2]]
                w.after(step * i, lambda p=p: w.move(hit, p, teleport=True, quiet=True) if w.alive(hit) else None)
        self.fly_to(owner)
        return True

    def collide(self, target):
        """The missile ran into target on its way (a skillshot aimed at a point)."""
        if not self.alive:
            return
        trip = self.trip
        hit = {"Collider": target, "SubEntity": 0, "EntityPosition": self.world.position(target), 0xAE98CBC: 0}
        if self.carried is not None and not self.instances:
            # a launched entity (Sonic Shell): its own scripts decide (a shell has no collision state and flies on)
            raise_event(self.world, self.carried, EVENT_COLLISION, hit)
            return
        before = self.pos
        self.pos = hit["EntityPosition"]
        self.flown += math.dist(before[:2], self.pos[:2])
        self._leg = None                           # placed (_advance)
        # 2026-10-25 19:28 (tester: AGL's Grab does not pull enemy champions; the simulator: the hit state's
        # SetMissileVelocity(ReturnVelocity) re-aimed the arm at its first point, it "arrived" at once and ended):
        # while a tether delivers its hit, a speed change only sets the return speed; then it flies back dragging
        tether = self.tether and not getattr(self, "returning", False) and TETHER_RETURN
        self._tether_pending = tether
        try:
            for inst in self.instances:
                inst.event(EVENT_COLLISION, hit)
        finally:
            self._tether_pending = False
        if tether and self.alive and self._return(target):
            return
        if self.trip == trip and self.alive:
            if isinstance(self.target, tuple) and getattr(self.world, "skillshot_pierce", False):
                # its script did not destroy it (DestroyEntity): it flies on through the line (Bat Scream's wave
                # damages every enemy on its way, less each hit; the batarang destroys itself after its bounces)
                self.fly_to(self.target)
                return
            self.world.after(0.0, lambda: self.end(trip))

    def expire(self, trip):
        if self.alive and trip == self.trip:
            for inst in self.instances:
                inst.event(EVENT_EXPIRED)
            if self.carried is not None:
                raise_event(self.world, self.carried, EVENT_EXPIRED)     # the shell explodes (0x34000042 S4 -> S2)
            if EXPIRE_LINGER > 0 and self.alive and trip == self.trip and self._busy():
                # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: The Joker's Last
                # Laugh balloon 0x34000118 goes S2 -> S3 on the expiry and explodes 0.5 s later in S1, then DestroyEntity(SELF);
                # ending the missile at the expiry removed its script first): a missile whose script is still busy after
                # the expiry stays where it is (no more collisions) until its own DestroyEntity, at most EXPIRE_LINGER s
                # ([ics] missile_expire_linger)
                self.expired = True
                self.trip += 1
                t = self.trip
                self.world.after(EXPIRE_LINGER, lambda: self.end(t))
                return
            self.end(trip)

    def _busy(self):
        """Is a script of the missile out of its idle state (a delay or a timer running after the expiry)?"""
        for inst in self.instances:
            if inst.removed:
                continue
            if any(r.state not in (0, None) for r in inst.regions):
                return True
        return False

    def end(self, trip):
        if self.alive and trip == self.trip:
            self.alive = False
            if self.tether and MISSILE_OWN_RETURN_EVENT:
                # 2026-10-23 23:30 (skill-second-stages.md 2): the tethered missile's own script ends on 0x10000005
                # too (Grab 0x340002C1 T6: S9,S1 -> S2: releases the grabbed target), not only the shooter's
                for inst in self.instances:
                    inst.event(0x10000005)
            for inst in self.instances:
                inst.removed = True
            self.world.scripts.pop(_key(self), None)
            if self.tether:
                # the tethered projectile came back: the shooter's script gets 0x10000005 (P)
                raise_event(self.world, self.owner, 0x10000005)
            self.world.log(f"[{self.world.time:6.2f}]   missile {self.cls:#x} gone")

    def redirect(self, target):
        if self.alive and target:
            self.world.missile_moved(self, target)
            self.fly_to(target)

    def __repr__(self):
        return f"missile {self.cls:#x}"


_guids = itertools.count(1)


class Instance:
    """One running script on one entity."""

    def __init__(self, script, owner, world, request=None):
        self.script, self.owner, self.world = script, owner, world
        self.vars = {}
        self.request = dict(request or {})
        self.markers = set()
        self.detected = []
        self.lists = []                        # the instance's entity list (5.4)
        self.current_event = None
        self.current_code = None
        self.params = {}
        self.pending = []                      # events posted with a delay, not yet delivered (IsEventPending)
        self.unknown = set()
        self.casting = 0
        self.guid = next(_guids)
        self.slot = None                       # the skill slot whose script this is
        self.status = None
        self.removed = False
        self._defaults()
        self.defaults_snapshot = dict(self.vars)     # what a re-entered state's locals start from (RESET_LOCALS)
        for name, value in self.request.items():
            self.vars_by_name(name, value)
        self.regions = [Region(self, g) for g in script.graphs]

    def __repr__(self):
        return f"<script {self.script.did:#x} #{self.guid} on {self.owner}>"

    def _defaults(self):
        """Default values from the server-only blocks, matched to each variable block by offset."""
        blocks = []
        for node in [self.script.raw] + list(_walk(self.script.raw)):
            pairs = [(f[0], f[3], node["fields"][i + 1][3]) for i, f in enumerate(node["fields"])
                     if f[2] == V.VAR_HASH and i + 1 < len(node["fields"])]
            if pairs:
                blocks.append(pairs)
        for d in self.script.raw.get("defaults", []):
            block = min((b for b in blocks if b[0][0] > d["offset"]), key=lambda b: b[0][0] - d["offset"], default=None)
            if not block:
                continue
            ordered = sorted((slot, h) for _o, h, slot in block)
            words, k = d["words"], 0
            for (slot, h), typ in zip(ordered, d["types"]):
                n = DEFAULT_WORDS.get(typ, 1)
                if typ == 0xA and (k >= len(words) or words[k] == 0):
                    n = 1
                w = words[k:k + n]
                k += n
                if typ == 3:
                    self.vars.setdefault(h, f32(w[0]) if w else 0.0)
                elif typ == 9:
                    self.vars.setdefault(h, tuple(f32(x) for x in w))
                elif typ in (0xD, 0xE):
                    # 0xE = enum (enum DID, value): 2026-10-25 19:28 (tester: no stealth effect, the champion stayed
                    # seen in a stealth strip): 0x340001CF's mask StealthRevealed = 4 read as 0, so its "revealed" test
                    # (attribute & mask) == mask always passed; 22 scripts carry such defaults
                    self.vars.setdefault(h, w[-1] if w else 0)
                elif typ in (1, 2, 0, 4):
                    self.vars.setdefault(h, w[0] if w else 0)
                elif typ == 7 and len(w) == 2:
                    self.vars.setdefault(h, struct.unpack("<d", struct.pack("<II", w[0], w[1]))[0])
                else:
                    self.vars.setdefault(h, 0)

    # --- lifecycle
    def start(self):
        if TOP_GRAPH_CHAINS:
            # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Star Sapphire's
            # Predator brain 0x340003D1 reads its owner with GetCreator($StarSapphireIID) in its top-level graph's own
            # enter chain, which never ran, so it waited for a live StarSapphireIID forever; 69 scripts have such a
            # chain): a top-level graph's enter chain runs when the instance starts, before its first state, as a nested
            # graph state's does when entered ([ics] top_graph_chains)
            for g in self.script.graphs:
                if g.slots[0] is not None and not self.removed:
                    run_nodes(self, g.slots[0], None)
        for r in self.regions:
            r.start()

    def event(self, ev, params=None):
        """Deliver an event; params (name -> value) are what SetVariable(var, #name) reads. Returns whether a graph
        took it (a transition fired on it); an event dropped on the way in (stopped instance, accept filter, loop cut)
        is not taken (2026-10-28 15:00, test-2026-10-28-1439-sweep.md S5: a skill use its script ignores)."""
        if self.removed:
            return False                        # stopped (a skipped cinematic's scene, a removed status)
        if ACCEPT_FILTER:
            # 2026-10-27 (skill-execution-model.md 0.7 / 6.5, C: the client VM drops events not in the record's sorted
            # accept list, 0x461430; ics delivered every event to every instance) [ics] script_accept_filter
            acc = accepted_events(self.script)
            if acc and ev not in acc:
                return False
        if EVENT_LOOP_LIMIT:
            # 2026-10-25 13:15 (tester's log: Atomic Green Lantern's passive ran its whole chain ~24 times per hit; the
            # simulator showed 66 re-entries of "any -> S2 on 0x1000001D" for one basic attack): an instance that gets
            # the same event more than EVENT_LOOP_LIMIT times within 20 ms drops the rest (a runaway loop)
            now = time.time()
            last = self.__dict__.setdefault("_ev_seen", {})
            key = ev
            if EVENT_LOOP_PER_TARGET and params:
                # 2026-10-28 15:00 (tester report 2026-10-28 15:00; meltdown-moving-target.md 3.6 / 6.4, C headless: one
                # Meltdown pulse on 5+ units raised 0x1000008A once per unit on AGL's passive, and the 5th and later got
                # no Rad stack): an event about a target (TargetIID / 0x9A6A765) counts per target; a runaway loop on
                # one target is still cut ([ics] event_loop_per_target)
                tgt = _event_target(params)
                if tgt is not None:
                    key = (ev, _key(tgt))
                    if len(last) > 256:
                        for k in [k for k, v in last.items() if now - v[0] > 1.0]:
                            del last[k]
            t0, n = last.get(key, (0.0, 0))
            n = n + 1 if now - t0 < 0.02 else 1
            last[key] = (t0 if n > 1 else now, n)
            if n > EVENT_LOOP_LIMIT:
                if n == EVENT_LOOP_LIMIT + 1 and hasattr(self.world, "log"):
                    self.world.log(f"[{self.script.did:#x}] event {ev:#x} loop cut (more than {EVENT_LOOP_LIMIT} in 20 ms)")
                return False
        saved = (self.params, self.current_event)
        self.params = {V.elf_hash(k) if isinstance(k, str) and not k.startswith("__") else k: v
                       for k, v in (params or {}).items()}
        taken = False
        try:
            for r in self.regions:              # each top-level graph sees the event
                self.current_event = ev
                taken = bool(r.event(ev)) or taken
        finally:
            self.current_event = None
            if saved[1] is not None:            # an event raised from inside another event's chain
                self.params, self.current_event = saved
        return taken

    def post(self, ev, delay, params=None):
        """PostEventDelayed (builtin 0x12): the event reaches this instance after the delay."""
        entry = (ev, self.world.time + delay)
        self.pending.append(entry)

        def deliver():
            if entry in self.pending:
                self.pending.remove(entry)
            self.event(ev, params)
        self.after(delay, deliver)

    def after(self, seconds, fn):
        self.world.after(seconds, lambda: None if self.removed else fn())

    def signal(self, code):
        """A result code of the cast in progress (5 cast point, 2 done) to every graph."""
        for r in self.regions:
            r.signal(code)

    def poll(self):
        """Re-check the transitions whose condition may have changed (a timer ran out)."""
        for r in self.regions:
            r.poll()

    def stop(self):
        """EndThisScript / status removal: the running state's exit chain runs, then the instance is gone."""
        if self.removed:
            return
        for r in self.regions:
            try:
                r.leave()
            except RecursionError:
                pass
        if TOP_GRAPH_CHAINS:
            for g in self.script.graphs:                # the top-level graphs' own exit chains (start above)
                if g.slots[2] is not None:
                    try:
                        run_nodes(self, g.slots[2], None)
                    except RecursionError:
                        pass
        self.removed = True
        try:
            scripts_on(self.world, self.owner).remove(self)
        except ValueError:
            pass

    # --- values
    def name(self, h):
        return self.script.names.get(h, f"{h:#x}")

    def vars_by_name(self, name, value):
        self.vars[V.elf_hash(name)] = value

    def var_by_name(self, name, default=None):
        return self.vars.get(V.elf_hash(name), default)

    def get(self, op):
        if op is None:
            return None
        if op.is_self():
            return self.owner
        if op.source == V.UNSET:
            return None if op.value == 0 else op.value
        if op.source == 0 and op.value in self.params:
            return self.params[op.value]        # the current event's parameter block
        if LOCAL_FRAMES and op.source >= 3 and op.value in _split_locals(self.script):
            key = (op.source, op.value)
            if key in self.vars:
                return self.vars[key]
            snap = getattr(self, "defaults_snapshot", {}) or {}
            return snap.get(op.value, 0)
        if op.value in self.vars:
            return self.vars[op.value]
        if op.source == 2 and OWNER_BLOCK:
            block = getattr(self.owner, "_owner_block", None)
            if block and op.value in block:
                return block[op.value]
        if (op.source == 2 and SLOT_COOLDOWN_VARS and isinstance(op.slot, int) and 0x20 <= op.slot < 0x20 + 8 * 16
                and op.slot % 8 == 0 and hasattr(self.world, "cooldown_end")):
            # 2026-11-03 (tester report 2026-11-03 00:34: Blue Beetle's ranged and melee Q / W / E share their cooldowns):
            # the owner block's f64 at 0x20 + 8 x slot is that slot's cooldown end (game time), written by the engine
            # (no script writes 0x28 / 0x30 / 0x38; Blue Beetle's 0x34000451 / 454 / 455 read them as "end - now" to keep
            # each form's cooldown in 0xD0 / 0xD8 / 0xE0 across a swap) ([ics] slot_cooldown_vars)
            return self.world.cooldown_end(self.owner, (op.slot - 0x20) // 8)
        if op.source == 1 and op.slot == 0 and op.value not in self.script.names:
            return op.value                 # literal held in a "value | 1 | 0" operand
        return 0

    def ent(self, op):
        """An entity operand: unset means the script's owner (0x992280, C)."""
        if op is None or op.is_unset() or op.is_self():
            return self.owner
        v = self.get(op)
        return v if v not in (None, 0) else None

    def number(self, op, default=0.0):
        if op is None or op.is_unset():
            return default
        return num(self.get(op))

    def set(self, op, value):
        if (op is not None and not op.is_unset() and LOCAL_FRAMES and op.source >= 3
                and op.value in _split_locals(self.script)):
            self.vars[(op.source, op.value)] = value  # a local of one frame (2026-11-02, [ics] local_frames)
            return
        if op is not None and not op.is_unset():
            self.vars[op.value] = value
            if op.source == 2 and OWNER_BLOCK and not op.is_self():
                # 2026-10-24 23:30 (tester: Atomic Wonder Woman's E always does its 2-charge slash, Q recasts at once;
                # aww-kit.md): source-2 operands are the entity's owner block, shared by all its scripts (the passive
                # writes the charge threshold there, Q / E / the W status read it). The instance's own copy is read
                # first, so per-skill slots that share an offset (the cost at 0xB4) do not collide.
                block = getattr(self.owner, "_owner_block", None)
                if block is None:
                    block = {}
                    try:
                        self.owner._owner_block = block
                    except AttributeError:
                        return
                block[op.value] = value

    def source(self):
        """The entity a script acts for: a missile's shooter, else the owner."""
        return self.owner.owner if isinstance(self.owner, Missile) else self.owner

    def evaluate(self, n):
        op = SERVER_EXPR.get(n.type) or EXPR_OPS.get(n.vt)
        kids = [c for c in n.children if c.role != "next"]
        if op == "var":
            return self.get(n.operands[0]) if n.operands else 0
        if op == "const":
            return _const(n)
        if n.vt == VT_COND:
            return bool(self.truth(self.evaluate(kids[0]))) if kids else False
        if n.vt in PREDICATE_VTS or (op is None and n.type_id in PREDICATES):
            return self.condition(n)                # a condition used as a value (an event inside a list)
        if op is None and n.type_id in HANDLERS:
            run_condition(self, n)                  # an action chain used as a value
            return True
        fn = EXPRESSIONS.get(op)
        if fn is not None:
            return fn(self, n, kids)
        self.unknown.add(f"expr {n.type} ({n.vt})")
        return self.evaluate(kids[0]) if kids else 0

    def truth(self, v):
        if isinstance(v, tuple):
            return any(v)
        return bool(v)

    def condition(self, n):
        """Evaluate a condition node: all / any lists, expression conditions, node predicates, events."""
        if n is None:
            return True
        kids = [c for c in n.children if c.role != "next"]
        if n.vt == VT_ALL:
            return all(run_condition(self, c) for c in kids)
        if n.vt == VT_ANY:
            return any(run_condition(self, c) for c in kids)
        if n.vt == VT_COND:
            return self.truth(self.evaluate(kids[0])) if kids else False
        if n.vt == VT_EVENT:
            return self.current_event is not None and bool(n.values) and self.current_event == n.values[-1]
        if n.vt == VT_NODECOND:                     # NOT(node chain); no node -> false
            return (not run_condition(self, n.next)) if n.next is not None else False
        return self.predicate(n)

    def predicate(self, n):
        h = BUILTIN_PREDICATES.get(n.vt) or (PREDICATES.get(n.type_id) if n.type_id is not None else None)
        if h:
            return bool(h(self, n, n.operands))
        if n.vt in (VT_ALL, VT_ANY, VT_COND, VT_NODECOND, VT_EVENT):
            return self.condition(n)
        if is_action(n):
            return run_condition(self, n)
        self.unknown.add(f"predicate {n.name()}")
        return False


def _const(n):
    vals = n.values
    if not vals:
        return 0
    v = vals[-1]
    typ = vals[0] if len(vals) > 1 and isinstance(vals[0], int) else None
    if isinstance(v, str):
        raw = v.encode("latin1")
        if len(raw) == 8:
            if typ == 7:                        # a double: game times, timers (-1.0 = a stopped timer)
                return struct.unpack("<d", raw)[0]
            if typ == 5:
                return struct.unpack("<q", raw)[0]
            return struct.unpack("<Q", raw)[0]  # 6 / 8: an IID or an 8-byte id (0 = none)
        return 0
    if typ == 3:
        return f32(v)
    if typ == 0:
        return bool(v)
    if typ == 1:
        return v - (1 << 32) if v & 0x80000000 else v
    return v


def is_action(n):
    """An action node (B: it has a next node), as opposed to a predicate or an expression."""
    if n.vt in (VT_ASSIGN, VT_LIST, VT_LOOP, VT_START_TIMER, VT_COPY, VT_POST_EVENT, VT_SWITCH, VT_SET_BOOL,
                VT_CLEAR, VT_DEBUG, VT_END_SCRIPT):
        return True
    return n.type_id is not None and n.type_id in HANDLERS and n.vt != VT_GET_ATTRIBUTE


def run_condition(inst, n):
    """A chain used as a condition (5.1): its actions run, its last node gives the result (true after an action)."""
    result = True
    while n is not None:
        if PREDICATE_FIRST and n.type_id in PREDICATES and n.type_id not in COND_ACTIONS:
            # 2026-10-25 (kit-audit-3.md 1, confirmed in the simulator): HasFlagAttribute 0x1000006A is also in HANDLERS
            # (the missile Mark), so inside AnyOf / NOT / triggers it ran as an action and was always true (40 scripts:
            # the shared stun / knock statuses, Starro R, Zatanna R, Superman E)
            return bool(inst.condition(n))
        if is_action(n) and n.type_id not in COND_ACTIONS:
            execute(inst, n, None)
            result = True
        elif n.type_id in COND_ACTIONS:
            result = bool(COND_ACTIONS[n.type_id](inst, n, n.operands))
        else:
            return bool(inst.condition(n))
        n = n.next
    return result


def _walk(raw):
    for c in raw["children"]:
        yield c
        yield from _walk(c)


def _event_trigger(n):
    """True when a trigger can only match while an event is being delivered (no need to poll it)."""
    if n is None:
        return True
    if n.vt == VT_EVENT or n.type_id in EVENT_TRIGGERS:
        return True
    if n.vt == VT_ALL:
        return any(_event_trigger(c) for c in n.children if c.role != "next")
    if n.vt == VT_ANY:
        return all(_event_trigger(c) for c in n.children if c.role != "next")
    return False


class Region:
    """A graph (state machine) running inside an instance."""

    def __init__(self, inst, graph, parent=None):
        self.inst, self.graph, self.parent = inst, graph, parent
        self.state = None
        self.child = None
        self.visit = 0

    def start(self):
        self.enter(0)

    def log(self, text):
        w = self.inst.world
        w.log(f"[{w.time:6.2f}] {self.inst.script.did:#x} {text}")

    def enter(self, index):
        inst = self.inst
        if inst.removed or self.__dict__.get("_dead"):
            return
        depth = getattr(inst, "depth", 0)
        if depth >= BURST_LIMIT:
            # 2026-10-22 (Toxic Growth 0x34000357 looped S0 -> S1 -> S2 -> S0 in one instant until Python's recursion
            # limit): the client evaluates transitions once per update, so a chain of transitions this deep waits
            # for the next tick
            visit = self.visit
            inst.after(UPDATE_INTERVAL, lambda: self.visit == visit and self.enter(index))
            return
        inst.depth = depth + 1
        try:
            self._enter(index)
        finally:
            inst.depth = depth

    def _enter(self, index):
        inst = self.inst
        # 2026-10-22: the "a hit counts as a collision" assumption of 2026-10-20 is gone: the missile script counts
        # its hits itself (0x3400003F S3: NumCollisions = ++NumCollisions after the damage, in the IfThenElse's
        # after chain, which the runtime now runs)
        self.leave()
        st0 = self.graph.states[index] if index < len(self.graph.states) else None
        if RESET_LOCALS and st0 is not None and st0.locals:
            # 2026-10-25 (skill-mechanics-recipes.md 5, C: Shazam's chain search state kept its DetectIter from the
            # last visit): a state's locals start from their defaults on each entry; only locals no other variable
            # block declares (variables are keyed by hash: a local named like a script variable aliases it)
            snap = getattr(inst, "defaults_snapshot", {})
            shared = _shared_locals(inst.script)
            for h in st0.locals:
                if h in shared:
                    continue
                if h in snap:
                    inst.vars[h] = snap[h]
                else:
                    inst.vars.pop(h, None)
        self.state = index
        self.visit += 1
        visit = self.visit
        st = self.graph.states[index] if index < len(self.graph.states) else None
        self.log(f"enter S{index}")
        self.child = None
        if st is None:
            return
        if st.is_graph and not GRAPH_ENTER_FIRST:
            self.child = Region(inst, st, self)
            self.child.start()
        if st.slots[1] is not None:
            self._updated_at = inst.world.time

            def update():
                if self.state != index or self.visit != visit or inst.removed:
                    return
                self._updated_at = inst.world.time
                run_nodes(inst, st.slots[1], None)
                if self.state == index and self.visit == visit and not self.check(code=None):
                    inst.after(UPDATE_INTERVAL, update)
            inst.after(UPDATE_INTERVAL, update)
        elif getattr(inst.world, "poll_conditions", True) and self._polled(index):
            def poll():
                if self.state != index or self.visit != visit or inst.removed:
                    return
                if not self.check(code=None):
                    inst.after(UPDATE_INTERVAL, poll)
            inst.after(UPDATE_INTERVAL, poll)
        if self.state == index and self.visit == visit:
            if st.slots[0] is not None:
                Chain(inst, st.slots[0], lambda code: self.finished(index, code)).run()
            else:
                self.finished(index, RESULT_DONE)
        if st.is_graph and GRAPH_ENTER_FIRST and self.state == index and self.visit == visit and self.child is None:
            # 2026-11-02 (tester report 2026-11-02 02:20: Superman's E Heat Vision does not push the enemy back): a
            # graph state's own enter chain runs before its sub-graph starts, as a hierarchical state machine enters a
            # parent before its child. The knockback status 0x340003F8 sets EffectSource and KnockbackDistance (6 m) in
            # its graph's enter; its sub-state S2, entered at once, dashed 0 m with them still unset
            # ([ics] graph_enter_before_children; false = the sub-graph first, as before)
            self.child = Region(inst, st, self)
            self.child.start()

    def _polled(self, index):
        """Transitions from this state whose condition can change without an event (checked every update)."""
        for t in self.graph.transitions:
            if t.sources and index not in t.sources:
                continue
            if t.trigger is not None and t.trigger.type_id != 0x10000019 and not _event_trigger(t.trigger):
                return True
        return False

    def leave(self):
        """Run the current state's exit chain (and its sub-graph's, innermost first)."""
        if self.state is None or self.state >= len(self.graph.states):
            return
        if self.__dict__.get("_own_anim_cast") == self.state:
            # 2026-11-03 (tester report 2026-11-03 16:09: after Superman's E punch he cannot move for about 2 s; headless:
            # the punch state's cast kept casting = 1 for good after the timed fallback, cast_holds_movement held him):
            # the cast graph_done_waits started for this state ends with it (later timers of it are void)
            self._own_anim_cast = None
            inst = self.inst
            inst.cast_id = getattr(inst, "cast_id", 0) + 1
            inst.casting = 0
            inst.graph_casting = 0
        st = self.graph.states[self.state]
        if (EXIT_UPDATE and st.slots[1] is not None and self.__dict__.get("_event_leave")
                and self.__dict__.get("_updated_at", 1e18) < self.inst.world.time - 1e-9 and not self.inst.removed):
            # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Mecha Wonder
            # Woman's W 0x340002CA stretches its dash box in S3's update, and the dash's end event left S3 before the
            # update of that tick ran, so the box stopped 1 m short): a state left by an event gets its update of the
            # current tick first, as the client's update runs before its event queue ([ics] update_before_event_exit)
            self._updated_at = self.inst.world.time
            run_nodes(self.inst, st.slots[1], None)
            if self.state is None or self.state >= len(self.graph.states) or self.graph.states[self.state] is not st:
                return
        if self.child is not None:
            self.child.leave()
            if STOP_LEFT_SUBGRAPHS:
                self.child.halt()
            self.child = None
        if st.slots[2] is not None:
            # 2026-10-25 19:28 (tester: AGL's R does not keep hitting; agl-e-r.md, C: the passive 0x340002B3's exit chain
            # raises 0x1000001D on its own script, which re-checked this graph while it was still leaving and fired the
            # same transition again: 3 Rad stacks and Sickness from one hit, so Meltdown jumped at once): no transition
            # of this graph fires while its exit chain runs ([ics] exit_chain_reentry_guard)
            self._leaving = EXIT_REENTRY_GUARD
            try:
                run_nodes(self.inst, st.slots[2], None)
            finally:
                self._leaving = False

    def halt(self):
        """A sub-graph its parent left: its pending polls, update chains and timers find it stopped.
        2026-11-02 (tester report 2026-11-02 01:43: Atomic Joker's R never stops dealing damage, even after his death):
        the parent's T0 left the burst graph after 8 s, but the left Region kept its state, so its own timer poll fired
        the next burst forever ([ics] stop_left_subgraphs; false = as before)."""
        self.state = None
        self.visit += 1
        self._dead = True

    def finished(self, index, code):
        if self.state != index:
            return
        if not self.check(code=COMPLETE) and not self.inst.casting and self.state == index:
            if self._waits_for_cast(index):
                # 2026-10-22: an instant skill without a Cast node (Poisoned Earth 0x34000354: BeginSkill + a graph
                # event) waits for the cast point / finished codes all the same: the animation's, timed like a cast
                start_cast(self.inst)
            elif GRAPH_DONE_WAITS and self._waits_for_done_of_own_animation(index):
                # 2026-11-03 (tester report 2026-11-03 14:40: Superman's E punch never shows; the run: Heat Vision S8 ->
                # S2 one ms after S8's enter): S8 raises the finisher's graph event and waits for OnCastSignal 2; the
                # chain's own result (RESULT_DONE is 2 too) fired it before the animation. A state that raises its own
                # animation and waits for 2 waits for that animation's end, as a cast does ([ics] graph_done_waits)
                start_cast(self.inst)
                self._own_anim_cast = index      # ended when the state is left (Region.leave)
            else:
                self.check(code=code)        # no cast running: the chain's own result (passives, delays)

    def _waits_for_done_of_own_animation(self, index):
        """The state waits for OnCastSignal 2, its enter chain raises a graph event, and the owner's animation graph
        hooks this script (so the graph will send the 2)."""
        waits = any((not t.sources or index in t.sources) and t.trigger is not None and t.trigger.type_id == 0x10000019
                    and t.trigger.values and t.trigger.values[-1] == RESULT_DONE for t in self.graph.transitions)
        if not waits:
            return False
        st = self.graph.states[index] if index < len(self.graph.states) else None
        first = st.slots[0] if st is not None else None
        if first is None or not any(n.type_id == 0x1000004E for n in first.chain()):
            return False
        g = graph_of(self.inst.world, self.inst.owner)
        return g is not None and g.hooks_script(getattr(self.inst.script, "did", 0))

    def _waits_for_cast(self, index):
        for t in self.graph.transitions:
            if t.sources and index not in t.sources:
                continue
            trig = t.trigger
            if trig is not None and trig.type_id == 0x10000019 and trig.values and trig.values[-1] in (
                    RESULT_CAST_POINT, RESULT_CAST_DONE):
                return True
        return False

    def signal(self, code):
        if self.child and self.child.signal(code):
            return True
        return self.check(code=code)

    def poll(self):
        if self.child and self.child.poll():
            return True
        return self.check(code=None)

    def check(self, code=None, use_event=False):
        """Fire the first transition that matches. An event can fire one transition only: it is consumed
        before the target state runs, so a state entered because of it does not see it again."""
        inst = self.inst
        if inst.removed or self.__dict__.get("_leaving") or self.__dict__.get("_dead"):
            return False
        saved = inst.current_event
        saved_code = inst.current_code
        if not use_event:
            inst.current_event = None
        inst.current_code = code if code not in (None, COMPLETE) else None
        fired = None
        # transitions with a trigger (field a = 2) come before the plain "when the chain ends" ones (a = 1):
        # 2026-10-21, basic attack 0x34000037 S1: T0 S1->S0 [1,1] must not win over T2 S1->S4 IsAlive [2,1]
        order = sorted(enumerate(self.graph.transitions), key=lambda it: 0 if it[1].a == 2 else 1)
        try:
            for i, t in order:
                if t.sources and self.state not in t.sources:
                    continue
                if (not t.sources and t.target == self.state and (code is None or not REENTER_ON_CODE) and not use_event
                        and ANY_NO_REENTER):
                    # 2026-10-23 18:00 (champion-kits-status.md 5: Starro's W re-entered S1 every tick, ~240
                    # scriptlets a second): a polled "any -> X" transition does not fire while already in X
                    continue
                polled = (POLL_ONCE_PER_TICK and not use_event and t.trigger is not None
                          and t.trigger.type_id != 0x10000019 and not _event_trigger(t.trigger))
                now = inst.world.time
                epoch = self.__dict__.get("_event_epoch", 0)
                last = self.__dict__.get("_polled_fired", {}).get(i, (-1e9, None))
                if polled and now - last[0] < UPDATE_INTERVAL * 0.5 and (not POLL_GUARD_EVENT_RESET or last[1] == epoch):
                    # 2026-10-25 (map-objectives-recipes.md 6 gap 2: the Doomsday pad 0x340001FA re-entered
                    # S0 -> S7 -> S0 2424 times at once): one polled transition fires at most once per tick; the
                    # state's own poll tries it again on the next one (a chain of different ones still runs at once)
                    # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Dex-Starr's
                    # Shred The World cat 0x3400072C hit a minion, and the enemy champion it ran into one tick later was
                    # skipped: its hit transition S3 -> S6 had fired 0.05 s before): an event that moved this graph since
                    # (a new collision) lifts the guard ([ics] poll_guard_event_reset)
                    continue
                if self.matches(t, code):
                    fired = (i, t)
                    if polled:
                        self.__dict__.setdefault("_polled_fired", {})[i] = (now, epoch)
                    break
        finally:
            inst.current_code = saved_code
        if fired is None:
            inst.current_event = saved
            return False
        i, t = fired
        self.log(f"S{self.state} -> S{t.target} (T{i})")
        inst.current_event = None if use_event else saved
        if use_event:
            inst.event_consumed = True
            self._event_epoch = self.__dict__.get("_event_epoch", 0) + 1
        self._event_leave = use_event
        try:
            self.enter(t.target)
        finally:
            self._event_leave = False
        if not use_event:
            inst.current_event = saved
        return True

    def matches(self, t, code):
        inst, trig = self.inst, t.trigger
        if trig is None:
            return code == COMPLETE
        typ = trig.type_id
        if typ == 0x10000019:
            return code is not None and code != COMPLETE and bool(trig.values) and code == trig.values[-1]
        if trig.vt in (VT_ALL, VT_ANY, VT_COND, VT_NODECOND, VT_EVENT):
            return inst.condition(trig)
        return run_condition(inst, trig)

    def event(self, ev):
        if self.child and self.child.event(ev):
            return True
        return self.check(use_event=True)


class Chain:
    """Runs a node chain; latent nodes call resume() later."""

    def __init__(self, inst, first, done):
        self.inst, self.done = inst, done
        self.nodes = list(first.chain())
        self.i = 0
        self.result = RESULT_DONE
        self.delay = 0.0                    # the result is reported this much later (cast point)

    def run(self):
        inst = self.inst
        depth = inst.__dict__.get("_chain_depth", 0)
        inst._chain_depth = depth + 1
        try:
            self._run()
        finally:
            inst._chain_depth = depth
            if not depth:
                flush_deferred_hooks(inst)

    def _run(self):
        while self.i < len(self.nodes):
            n = self.nodes[self.i]
            self.i += 1
            if self.inst.removed:
                return
            if execute(self.inst, n, self):
                return
        if self.delay > 0:
            self.inst.after(self.delay, lambda: self.done(self.result))
        else:
            self.done(self.result)

    def resume(self):
        self.run()


def run_nodes(inst, first, chain):
    """Run a nested chain (items of a list, a loop body) synchronously; latent nodes inside are not waited."""
    depth = inst.__dict__.get("_run_depth", 0)
    inst._run_depth = depth + 1              # read by World._death_events ([ics] death_status_end_after_chain)
    try:
        n = first
        while n is not None and not inst.removed:
            execute(inst, n, chain)
            n = n.next
    finally:
        inst._run_depth = depth


def _subs_by_kind(n, count_index=0):
    """IfThenElse / While / Switch: their child chains in the order of their type list (0 = no child)."""
    subs = [c for c in n.children if c.raw_via == "0x45FC62"]
    count = n.values[0] if n.values and isinstance(n.values[0], int) else len(subs)
    kinds = n.values[1:1 + count]
    out, k = [], 0
    for kind in kinds:
        if kind and k < len(subs):
            out.append(subs[k])
            k += 1
        else:
            out.append(None)
    return out


def execute(inst, n, chain):
    """Run one node. Returns True when the node finishes later (latent)."""
    h = BUILTIN_VT.get(n.vt)
    if h is not None:
        return h(inst, n, n.operands, chain)
    if n.vt in EXPR_OPS or n.type in SERVER_EXPR:
        inst.evaluate(n)
        return False
    if n.vt in PREDICATE_VTS:
        inst.condition(n)                   # a condition in a chain: evaluated, no effect
        return False
    t = n.type_id
    h = HANDLERS.get(t) if t is not None else None
    if h:
        return h(inst, n, n.operands, chain)
    if t in PREDICATES:
        PREDICATES[t](inst, n, n.operands)
        return False
    inst.unknown.add(n.name())
    return False


# --- builtin nodes (node registry ids 0x01-0x18, keyed by vtable) -------------------------------------------

def _assign(inst, n, ops, chain):                # 0x01: variable = expression
    value = next((c for c in n.children if c.role == "value"), None)
    inst.set(ops[0] if ops else None, inst.evaluate(value) if value else 0)
    return False


def _if(inst, n, ops, chain):                    # 0x07 IfThenElse: [3, then, else, after, condition type]
    cond = next((c for c in n.children if c.raw_via == "0x46001A"), None)
    slots = (_subs_by_kind(n) + [None, None, None])[:3]
    ok = cond is None or run_condition(inst, cond)
    if ok and slots[0] is not None:
        run_nodes(inst, slots[0], chain)
    if not ok and slots[1] is not None:
        run_nodes(inst, slots[1], chain)
    if slots[2] is not None:
        run_nodes(inst, slots[2], chain)
    return False


def _while(inst, n, ops, chain):                 # 0x0D While: [2, body, after, condition type]
    cond = next((c for c in n.children if c.raw_via == "0x46001A"), None)
    body, after = (_subs_by_kind(n) + [None, None])[:2]
    k = 0
    while k < WHILE_LIMIT and not inst.removed and run_condition(inst, cond):
        if body is not None:
            run_nodes(inst, body, chain)
        k += 1
    if after is not None:
        run_nodes(inst, after, chain)
    return False


def _any(inst, n, ops, chain):                   # 0x05 AnyOf in an action chain: a selector
    any(run_condition(inst, c) for c in n.children if c.role != "next")
    return False


def _all(inst, n, ops, chain):                   # 0x09 AllOf in an action chain: a sequence
    all(run_condition(inst, c) for c in n.children if c.role != "next")
    return False


def _switch(inst, n, ops, chain):                # 0x15 Switch(cases..., selector)
    children = _subs_by_kind(n)
    cases = ops[:-1]
    sel = inst.get(ops[-1]) if ops else None
    count = len(children)
    chosen = None
    for i, case in enumerate(cases):
        if _same(inst.get(case), sel):
            chosen = i
            break
    if chosen is None:
        chosen = count - 2 if count >= 2 else None
    if chosen is not None:
        j = chosen
        while j < count - 1 and children[j] is None and chosen < len(cases):
            j += 1                            # an empty case falls through to the next non-empty child
        if j < count - 1 and children[j] is not None:
            run_nodes(inst, children[j], chain)
    if count and children[-1] is not None:
        run_nodes(inst, children[-1], chain)
    return False


def _start_timer(inst, n, ops, chain):           # 0x02 StartTimer(timer, duration): now + duration, < 0 -> -1
    if len(ops) > 1:
        seconds = num(inst.get(ops[1]))
        inst.set(ops[0], ("timer", -1.0 if seconds < 0 else inst.world.time + seconds))
        if seconds >= 0 and not getattr(inst.world, "poll_conditions", True):
            # (with condition polling on, the state's own poll sees the timer run out; a poll per timer on top of
            # it doubled the timers of a zero-length timer loop at every turn, 0x340006C3)
            inst.after(seconds + 0.001, inst.poll)
    return False


def _timer_expired(inst, n, ops):                # 0x08 TimerExpired: false if -1, else end < now; unset = expired
    v = inst.get(ops[0]) if ops else None
    if isinstance(v, tuple) and len(v) == 2 and v[0] == "timer":
        return v[1] != -1.0 and inst.world.time >= v[1]
    if isinstance(v, float) and v == -1.0:
        return False                            # a stopped timer (a script assigns -1.0)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return inst.world.time >= v             # an end time copied from another timer / the game time
    if ops and getattr(inst, "status", None) is not None and inst.script.did in STATUS_TIMER_FIRST_WAIT:
        # 2026-10-29 tester report 2026-10-29 14:40 (Meltdown's first pulse at once; agl-qer-lift.md 3, C log + the
        # original video's ~1 s first pulse): in these status scripts a timer tested before it was ever started starts
        # now with the duration of the script's own StartTimer of the same variable ([ics] status_timer_first_wait)
        dur = _own_timer_duration(inst, ops[0])
        if dur is not None:
            seconds = num(inst.get(dur))
            if seconds > 0:
                inst.set(ops[0], ("timer", inst.world.time + seconds))
                if not getattr(inst.world, "poll_conditions", True):
                    inst.after(seconds + 0.001, inst.poll)
                return False
    # 2026-10-22 (full-combat-skills.md 5.1, C): a timer variable never started holds 0.0: already expired
    return True


_TIMER_DURATIONS = {}


def _own_timer_duration(inst, op):
    """The duration operand of the script's own StartTimer (0x02) of this timer variable, or None."""
    key = (inst.script.did, op.value)
    if key not in _TIMER_DURATIONS:
        found = None
        for raw in _walk(inst.script.raw):
            if raw.get("vt") == VT_START_TIMER:
                ops = V.Node(raw).operands
                if len(ops) > 1 and ops[0].value == op.value:
                    found = ops[1]
                    break
        _TIMER_DURATIONS[key] = found
    return _TIMER_DURATIONS[key]


def _copy(inst, n, ops, chain):                  # 0x11 Copy(destination, source)
    if len(ops) > 1:
        inst.set(ops[0], inst.get(ops[1]))
    return False


def _post_event(inst, n, ops, chain):            # 0x12 PostEventDelayed(delay)[event]
    ev = n.values[0] if n.values and isinstance(n.values[0], int) else 0
    delay = inst.number(ops[0]) if ops else 0.0
    if ev:
        inst.post(ev, max(0.0, delay))
    return False


def _set_bool(inst, n, ops, chain):              # 0x16 SetBool(var)[value]
    if ops:
        inst.set(ops[0], bool(n.values[-1]) if n.values else False)
    return False


def _clear(inst, n, ops, chain):                 # 0x17 ClearVariable(var): the default of its type
    if ops:
        old = inst.get(ops[0])
        if isinstance(old, bool):
            v = False
        elif isinstance(old, Frame) or isinstance(old, tuple) and len(old) == 3:
            v = (0.0, 0.0, 0.0)
        elif isinstance(old, float):
            v = 0.0
        else:
            v = 0
        inst.set(ops[0], v)
    return False


def _debug(inst, n, ops, chain):                 # 0x0C DebugLog(text): no effect
    return False


def _is_true(inst, n, ops):                      # 0x10 IsTrue(var)
    # 2026-10-21 (tester): "always the critical-hit animation" while this returned true for an unset roll
    return inst.truth(inst.get(ops[0])) if ops else True


def _has_param(inst, n, ops):                    # 0x14 HasEventParameter(#name)
    return bool(ops) and ops[0].value in inst.params


def _are_equal(inst, n, ops):                    # 0x18 AreEqual(a, b)
    return len(ops) > 1 and _same(inst.get(ops[0]), inst.get(ops[1]))


def _event_pending(inst, n, ops):                # 0x04 IsEventPending(id)[queued, in flight]
    ev = n.values[0] if n.values else 0
    queued = len(n.values) < 2 or n.values[1]
    flight = len(n.values) < 3 or n.values[2]
    return bool((queued and any(e == ev for e, _t in inst.pending)) or (flight and inst.current_event == ev))


def _end_script(inst, n, ops, chain):            # 0x10000002 (node) EndThisScript
    if inst.status is not None:
        remove_status(inst.world, inst.owner, inst.status, inst)
    else:
        inst.event(EVENT_INTERRUPT)
        inst.stop()
    return True


BUILTIN_VT = {
    VT_ASSIGN: _assign, VT_LIST: _if, VT_LOOP: _while, VT_ANY: _any, VT_ALL: _all, VT_SWITCH: _switch,
    VT_START_TIMER: _start_timer, VT_COPY: _copy, VT_POST_EVENT: _post_event, VT_SET_BOOL: _set_bool,
    VT_CLEAR: _clear, VT_DEBUG: _debug, VT_END_SCRIPT: _end_script,
}
BUILTIN_PREDICATES = {VT_TIMER_EXPIRED: _timer_expired, VT_IS_TRUE: _is_true, VT_HAS_PARAM: _has_param,
                      VT_EQUAL: _are_equal, VT_PENDING: _event_pending}


# --- expressions (evaluate = slot 10; full-combat-skills.md 5.3) -----------------------------------------------

def _num2(inst, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    b = inst.evaluate(kids[1]) if len(kids) > 1 else 0
    return a, b


def _arith(fn):
    def ev(inst, n, kids):
        a, b = _num2(inst, kids)
        if isinstance(a, tuple) or isinstance(b, tuple):
            va, vb = _vec(a), _vec(b)
            if isinstance(a, tuple) and isinstance(b, tuple):
                return tuple(fn(x, y) for x, y in zip(va, vb))
            if isinstance(a, tuple):
                return tuple(fn(x, num(b)) for x in va)
            return tuple(fn(num(a), y) for y in vb)
        r = fn(num(a), num(b))
        if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool) and a <= 0xFFFFF and b <= 0xFFFFF:
            return int(r) if r == int(r) else r
        return r
    return ev


def _cmp(fn):
    def ev(inst, n, kids):
        a, b = _num2(inst, kids)
        return fn(num(a), num(b))
    return ev


def _unary(fn):
    def ev(inst, n, kids):
        a = inst.evaluate(kids[0]) if kids else 0
        if isinstance(a, tuple):
            return tuple(fn(x) for x in _vec(a))
        return fn(num(a))
    return ev


def _div(x, y):
    return x / y if y else 0.0


def _degrees_flag(n):
    return bool(n.values[-1]) if n.values else True


def _yaw_of(v):
    if isinstance(v, Frame):
        return v.yaw
    x, y, _z = _vec(v)
    return math.degrees(math.atan2(y, x)) if (x or y) else 0.0


def _heading(inst, n, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    deg = _yaw_of(a) % 360.0
    return deg if _degrees_flag(n) else math.radians(deg)


def _with_heading(inst, n, kids):
    a, b = _num2(inst, kids)
    if HEADING_FROM_VECTOR and isinstance(b, tuple) and len(b) >= 2 and not isinstance(b, Frame) \
            and abs(num(b[0])) + abs(num(b[1])) > 1e-9:
        # 2026-11-03 (tester report 2026-11-03 14:4x: Superman's E pushes every target the same way; the original pushes
        # it on along the line from Superman): the knockback 0x340003F8 overwrites KnockbackHeading with Offset(source,
        # target), a vector, before this node; its heading is the vector's direction ([ics] heading_from_vector, P)
        angle = math.degrees(math.atan2(num(b[1]), num(b[0])))
    else:
        angle = num(b) if _degrees_flag(n) else math.degrees(num(b))
    if isinstance(a, Frame):
        return Frame(a, angle)
    x, y, z = _vec(a)                              # a plain vector: rotated by the angle
    r = math.radians(angle)
    return (x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r), z)


def _transform(inst, n, kids):                   # 0x38 frame (+) local offset
    a, b = _num2(inst, kids)
    pa, (ox, oy, oz) = _vec(a), _vec(b)
    r = math.radians(a.yaw) if isinstance(a, Frame) else 0.0
    if LOCAL_Y_FORWARD:
        # 2026-10-25 (skill-mechanics-recipes.md 3, C: 41 constant offsets are vec3(0, d, 0), only the two wall widths
        # pure X): a local frame is +Y forward, +X to the right (P for the sign)
        fx, fy = math.cos(r), math.sin(r)
        p = (pa[0] + ox * fy + oy * fx, pa[1] - ox * fx + oy * fy, pa[2] + oz)
    else:
        p = (pa[0] + ox * math.cos(r) - oy * math.sin(r), pa[1] + ox * math.sin(r) + oy * math.cos(r), pa[2] + oz)
    return Frame(p, a.yaw) if isinstance(a, Frame) else p


def _vadd(inst, n, kids):                        # 0x37 frame + vector (orientation kept)
    a, b = _num2(inst, kids)
    p = tuple(x + y for x, y in zip(_vec(a), _vec(b)))
    return Frame(p, a.yaw) if isinstance(a, Frame) else p


def _forward(inst, n, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    r = math.radians(_yaw_of(a) if isinstance(a, Frame) else 0.0)
    return (math.cos(r), math.sin(r), 0.0)


def _location(inst, n, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    return _vec(a)


def _normalize(inst, n, kids):
    a = _vec(inst.evaluate(kids[0]) if kids else 0)
    ln = math.sqrt(sum(x * x for x in a))
    return tuple(x / ln for x in a) if ln > 1e-6 else (0.0, 0.0, 0.0)


def _cross(inst, n, kids):
    a, b = _num2(inst, kids)
    ax, ay, az = _vec(a)
    bx, by, bz = _vec(b)
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


def _dot(inst, n, kids):
    a, b = _num2(inst, kids)
    return sum(x * y for x, y in zip(_vec(a), _vec(b)))


def _select(inst, n, kids):                      # 0x27 (c ? a : b), lazy
    if len(kids) < 3:
        return 0
    return inst.evaluate(kids[1]) if inst.truth(inst.evaluate(kids[0])) else inst.evaluate(kids[2])


def _or(inst, n, kids):                          # 0x10 short-circuit or
    a = inst.evaluate(kids[0]) if kids else False
    if a is True or (isinstance(a, bool) and a):
        return a
    return inst.evaluate(kids[1]) if len(kids) > 1 else a


def _and(inst, n, kids):                         # 0x13 short-circuit and
    a = inst.evaluate(kids[0]) if kids else False
    if not inst.truth(a):
        return a
    return inst.evaluate(kids[1]) if len(kids) > 1 else a


def _not(inst, n, kids):                         # 0x24: a non-bool operand gives false (C)
    a = inst.evaluate(kids[0]) if kids else False
    if isinstance(a, bool):
        return not a
    if a is None:
        return True
    return not inst.truth(a) if isinstance(a, (int, float)) else False


def _clamp(inst, n, kids):
    vals = [inst.evaluate(k) for k in kids[:3]]
    if len(vals) < 3:
        return vals[0] if vals else 0
    return min(max(num(vals[0]), num(vals[1])), num(vals[2]))


def _random(inst, n, kids):
    a, b = _num2(inst, kids)
    lo, hi = sorted((num(a), num(b)))
    if isinstance(a, int) and isinstance(b, int) and a <= 0xFFFFF and b <= 0xFFFFF:
        return random.randint(int(lo), int(hi))
    return random.uniform(lo, hi)


def _int32(inst, n, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    if isinstance(a, bool):
        return int(a)
    if isinstance(a, float):
        return int(a)
    if isinstance(a, int):
        return a if a <= 0xFFFFF else int(f32(a))
    return 0


def _as_float(inst, n, kids):
    return num(inst.evaluate(kids[0]) if kids else 0)


def _as_uint(inst, n, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    return int(num(a)) if isinstance(a, float) else (a if isinstance(a, int) else 0)


def _band(inst, n, kids):
    a, b = _num2(inst, kids)
    return int(a if isinstance(a, int) else num(a)) & int(b if isinstance(b, int) else num(b))


def _bitop(fn):
    def ev(inst, n, kids):
        a, b = _num2(inst, kids)
        ia = a if isinstance(a, int) else int(num(a))
        ib = b if isinstance(b, int) else int(num(b))
        return fn(ia, ib) & 0xFFFFFFFF
    return ev


def _comp(i):
    return lambda inst, n, kids: _vec(inst.evaluate(kids[0]) if kids else 0)[i]


def _len(inst, n, kids):
    return math.sqrt(sum(x * x for x in _vec(inst.evaluate(kids[0]) if kids else 0)))


def _len2(inst, n, kids):
    return sum(x * x for x in _vec(inst.evaluate(kids[0]) if kids else 0))


def _incr(d):
    def ev(inst, n, kids):
        a = inst.evaluate(kids[0]) if kids else 0
        if isinstance(a, int) and not isinstance(a, bool) and a <= 0xFFFFF:
            return a + d
        return num(a) + d
    return ev


def _round(inst, n, kids):
    a = inst.evaluate(kids[0]) if kids else 0
    r = math.floor(num(a) + 0.5)
    return int(r) if isinstance(a, int) else float(r)


def _deg2rad(inst, n, kids):
    a = num(inst.evaluate(kids[0]) if kids else 0)
    return math.radians(math.fmod(a, 360.0) % 360.0)


def _lerp(inst, n, kids):
    vals = [inst.evaluate(k) for k in kids[:3]]
    if len(vals) < 3:
        return vals[0] if vals else 0
    a, b, t = vals[0], vals[1], num(vals[2])
    if isinstance(a, tuple) or isinstance(b, tuple):
        return tuple(x + (y - x) * t for x, y in zip(_vec(a), _vec(b)))
    return num(a) + (num(b) - num(a)) * t


def _scale_by_level(inst, n, kids):              # 0x10000003 ScaleByLevel(level, base, delta)[zero if level 0]
    vals = [inst.evaluate(k) for k in kids[:3]]
    while len(vals) < 3:
        vals.append(0)
    level, base, delta = num(vals[0]), num(vals[1]), num(vals[2])
    if n.values and n.values[-1] and level == 0:
        return 0.0
    return base + (level - 1) * delta


def _get_attribute(inst, n, kids):               # 0x10000002 GetAttribute(entity)[attribute, mode]
    vals = [v for v in n.values if isinstance(v, int)]
    attr = next((v for v in vals if v >= 0x10000000), 0)
    mode = vals[-1] if len(vals) > 1 and vals[-1] < 4 else 0
    ent = inst.ent(n.operands[0]) if n.operands else inst.owner
    if isinstance(ent, Missile):
        ent = ent.owner
    w = inst.world
    try:
        return w.attribute(ent, attr, mode)
    except TypeError:                            # a World without modes
        return w.attribute(ent, attr)


EXPRESSIONS = {
    "+": _arith(lambda x, y: x + y), "-": _arith(lambda x, y: x - y), "*": _arith(lambda x, y: x * y),
    "/": _arith(_div), "idiv": _arith(_div), "max": _arith(max), "min": _arith(min),
    "mod": _arith(lambda x, y: math.fmod(x, y) if y else 0.0),
    "imod": _arith(lambda x, y: int(x) % int(y) if int(y) else 0),
    "<": _cmp(lambda x, y: x < y), ">": _cmp(lambda x, y: x > y), "<=": _cmp(lambda x, y: x <= y),
    ">=": _cmp(lambda x, y: x >= y),
    "==": lambda inst, n, kids: _same(*_num2(inst, kids)), "!=": lambda inst, n, kids: not _same(*_num2(inst, kids)),
    "++": _incr(1), "--": _incr(-1), "!": _not, "not": _not, "~": lambda inst, n, kids: (~int(num(
        inst.evaluate(kids[0]) if kids else 0))) & 0xFFFFFFFF,
    "or": _or, "and": _and, "select": _select, "clamp": _clamp, "random": _random,
    "abs": _unary(abs), "sqrt": _unary(lambda x: math.sqrt(x) if x > 0 else 0.0), "cos": _unary(math.cos),
    "sin": _unary(math.sin), "tan": _unary(math.tan), "atan": _unary(math.atan),
    "log": _unary(lambda x: math.log(x) if x > 0 else 0.0), "floor": _unary(math.floor), "ceil": _unary(math.ceil),
    "round": _round, "neg": _unary(lambda x: -x), "pow": _arith(lambda x, y: math.pow(x, y) if x > 0 or y == int(y) else 0.0),
    "int32": _int32, "int64": _int32, "float": _as_float, "double": _as_float, "uint32": _as_uint, "uint64": _as_uint,
    "&": _band, "|": _bitop(lambda a, b: a | b), "^": _bitop(lambda a, b: a ^ b), "<<": _bitop(lambda a, b: a << b),
    ">>": _bitop(lambda a, b: a >> b),
    "vec3": lambda inst, n, kids: tuple(num(inst.evaluate(c)) for c in kids[:3]),
    "length": _len, "len2": _len2, "normalize": _normalize, "dot": _dot, "cross": _cross,
    "vadd": _vadd, "transform": _transform, "x": _comp(0), "y": _comp(1), "z": _comp(2),
    "time": lambda inst, n, kids: float(inst.world.time), "heading": _heading, "with_heading": _with_heading,
    "deg2rad": _deg2rad, "rad2deg": _unary(math.degrees), "forward": _forward, "location": _location,
    "lerp": _lerp, "scale_by_level": _scale_by_level, "get_attribute": _get_attribute,
    "null": lambda inst, n, kids: 0,
}


# --- action nodes of the VM itself ---------------------------------------------------------------------------

def _subs(inst, n, chain):
    for c in n.children:
        if c.role == "sub":
            run_nodes(inst, c, chain)


def _stat_slot(inst, raw):
    """The slot field of InitSkill / LoadSkillStats: -1 = this script's slot, else that slot of the owner."""
    if raw in (None, 0xFFFFFFFF, -1):
        return inst.slot if inst.slot is not None else getattr(inst.owner, "slot", None)
    return raw


def _init_skill(inst, n, ops, chain):            # 0x10000050: InitSkill(SkillRank[, owner])[slot]
    owner = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else inst.owner
    owner = owner if owner else inst.owner
    if isinstance(owner, Missile):
        owner = owner.owner
    slot = _stat_slot(inst, n.values[0] if n.values else None)
    w = inst.world
    rank = w.slot_rank(owner, slot) if slot is not None and hasattr(w, "slot_rank") else None
    inst.set(ops[0] if ops else None, rank if rank is not None else w.skill_rank(owner))
    _subs(inst, n, chain)
    return False


def _load_stats(inst, n, ops, chain):            # 0x1000009F: LoadSkillStats(owner, vars...)[count, stats..., slot]
    vals = [v for v in n.values if isinstance(v, int)]
    if not vals:
        return False
    count = vals[0]
    stats = vals[1:1 + count]
    owner = inst.get(ops[0]) if ops and not ops[0].is_unset() else None
    if isinstance(inst.owner, Missile):
        owner = inst.owner.owner
    owner = owner or inst.owner
    # 2026-10-22: the value after the stat list is the slot whose stats are read (-1 = this script's own): Bat
    # Flight reads its echo multiplier from the passive's stat 5 ([1 5 5]), the batarang's missile its Q's ([.. 1])
    raw = vals[1 + count] if len(vals) > 1 + count else None
    slot = _stat_slot(inst, raw)
    w = inst.world
    own = raw in (None, 0xFFFFFFFF) or slot == inst.slot
    rank = inst.var_by_name("SkillRank", None) if own else None
    if not rank:
        rank = (w.slot_rank(owner, slot) if slot is not None and hasattr(w, "slot_rank") else None) or w.skill_rank(owner)
    rank = int(rank) if isinstance(rank, (int, float)) and rank == rank else 1
    overrides = w.combat.of(owner).stat_overrides.get(slot, {}) if hasattr(w, "combat") else {}
    for stat, op in zip(stats, ops[1:1 + count]):
        if stat in overrides:
            inst.set(op, overrides[stat])
            continue
        if slot is not None and hasattr(w, "slot_stat"):
            v = w.slot_stat(owner, slot, stat, rank)
            if v is not None:
                inst.set(op, v)
                continue
        inst.set(op, w.skill_stat(owner, stat, rank))
    return False


def _face(inst, n, ops, chain):                  # 0x1000003F: FaceTarget(target, -, FacingIDVariable)
    target = inst.get(ops[0]) if ops else None
    h = Handle("facing", inst.owner) if len(ops) > 2 else None
    if target and h is not None and hasattr(inst.world, "lock_facing"):
        inst.world.lock_facing(inst.source(), target, h)       # held until ReleaseFacing (2026-11-02, [ics] facing_locks)
    elif target:
        inst.world.face(inst.source(), target)
    if h is not None:
        inst.set(ops[2], h)
    return False


# Scriptlet variables a script passes (0x10000030 target, 0x100009EB shot speed). The shot itself is tracked by a
# status script (e.g. 0x34000470 for Batman's basic attack) that raises the impact event 0x10000126 on arrival.
VAR_SCRIPT_TARGET, VAR_SCRIPT_SPEED = 0x10000030, 0x100009EB


def _scriptlet(inst, n, ops, chain):             # 0x10000034: RunScriptlet(entity, -, var values...) [key, n, var ids]
    key = n.values[0] if n.values and isinstance(n.values[0], int) else None
    ent = inst.get(ops[0]) if ops else inst.owner
    if not key:
        return False                        # (a missile plays on its own object: World maps it, ics/world.py)
    count = n.values[1] if len(n.values) > 1 and isinstance(n.values[1], int) and n.values[1] < 8 else 0
    ids = [v for v in n.values[2:2 + count]]
    values = [inst.get(op) for op in ops[2:2 + count]]
    variables = list(zip(ids, values))
    target = dict(variables).get(VAR_SCRIPT_TARGET)
    if target is None and not variables:
        target = inst.var_by_name("TargetIID")
    inst.world.run_scriptlet(ent if ent is not None else inst.owner, key, target=target, variables=variables)
    return False


def _set_value(inst, n, ops, chain):             # 0x100000E2: Set(var, value) [value]
    if ops:
        inst.set(ops[0], n.values[-1] if n.values else 1)
    _subs(inst, n, chain)
    return False


def _cast(inst, n, ops, chain):                  # 0x10000026: Cast(TargetIID, TargetPosition)
    """Fills the targets from the skill use. The chain goes on at once (face the target, play the cast
    animation); when it ends, its result is the cast point (5), reported cast_time() seconds later."""
    for name, op in zip(("TargetIID", "TargetPosition"), ops):
        if name in inst.request:
            inst.set(op, inst.request[name])
    _subs(inst, n, chain)
    start_cast(inst)
    return False


GRAPH_HOOKS = {}                     # script DID -> {"codes": {code: s}, "exit": s or None} (load_graph_hooks)
GRAPH_EXIT_FALLBACK = 3.0            # [ics] graph_exit_fallback: s before a state without a self-ending trigger ends


def load_graph_hooks(path):
    """2026-10-25 (tester: skills start their animation and never finish; docs/re-notes/animation-deep-scan.md, C):
    data/skill_hooks.tsv (tools/graph_hooks.py) holds each skill script's graph state with its clip triggers: the
    turbineEventHookPayload codes 3 (hit) / 5 (missile out) / 6 (hold) at their times and the trigger that leaves the
    state (skill_to_cosmetic ...). The script's first state with timed codes is its cast."""
    import csv
    GRAPH_HOOKS.clear()
    try:
        rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="	"))
    except OSError:
        return 0
    found = {}
    for r in rows:
        try:
            did = int(r["script"], 16)
        except (KeyError, ValueError):
            continue
        leaves = set(filter(None, (r.get("leaves_on") or "").split(",")))
        codes, exit_at = {}, None
        for trig in filter(None, (t.strip() for t in (r.get("triggers") or "").split(";"))):
            try:
                _clip, rest = trig.split(":", 1)
                name, rest = rest.split("@", 1)
                when = rest.split("[", 1)[0]
                t = float(when)                      # "end+0.05" (clip-end relative) is unknown: skipped
            except ValueError:
                continue
            if "[code " in rest:
                code = int(rest.split("[code ", 1)[1].rstrip("]"))
                codes[code] = min(t, codes.get(code, t))
            if name in leaves:
                exit_at = t if exit_at is None else min(exit_at, t)
        if codes:
            try:
                speed = float((r.get("speeds") or "x1").split()[0].lstrip("x") or 1.0)
            except ValueError:
                speed = 1.0
            found.setdefault(did, []).append({"codes": codes, "exit": exit_at,
                                              "cosmetic": "skill_to_cosmetic" in leaves,
                                              "speed": speed, "bound": (r.get("binding") or "") == "speed-bound"})
    for did, states in found.items():
        # one timed state (or identical ones: the basic attack's normal / critical clips) is the cast; a chain of
        # different timed states (Katana's Thousand Cuts 1-5) keeps the fixed timing until chains are modelled
        if all(st == states[0] for st in states):
            GRAPH_HOOKS[did] = states[0]
    return len(GRAPH_HOOKS)


GRAPH_RUNTIME = False                # [ics] graph_runtime: cast signals from the entity's own graph (ics/graph.py)
GRAPH_START_GRACE = 0.15             # [ics] graph_start_grace: s for the graph to enter the script's state after Cast
START_SCRIPTLET_HOLD = {0x3400000A}  # [ics] start_scriptlet_hold: scripts whose StartScriptlet runs are held
GRAPH_COSMETIC_TAIL = True           # [ics] graph_cosmetic_tail: a script's skill_to_locomotion is dropped while the
                                     # graph plays the skill's _Cosmetic tail (2026-10-29, skill-animations-vs-original.md)
GRAPH_MISSILE_RELEASE = 0.5          # [ics] graph_missile_release: s after a cast's missiles are gone before its state ends
ACCEPT_FILTER = False                # [ics] script_accept_filter: an instance gets only its record's accepted events


def graph_of(world, owner):
    """The entity's graph runtime (ics/graph.GraphInstance) when [ics] graph_runtime is on, else None."""
    if not GRAPH_RUNTIME:
        return None
    fn = getattr(world, "graph_for", None)
    if fn is None:
        return None
    try:
        return fn(owner)
    except Exception:                    # noqa: BLE001
        return None


def start_cast(inst):
    """The cast in progress: cast point (5, and 3) after cast_time(), done (2) a little later; with the champion's graph
    timings (GRAPH_HOOKS) each hook code at its own time and 2 when the graph state is left. With [ics] graph_runtime
    and an owner whose graph hooks this script, the graph itself sends the codes (deliver_hook)."""
    g = graph_of(inst.world, inst.owner)
    if g is not None and g.hooks_script(getattr(inst.script, "did", 0)):
        _runtime_cast(inst, g)
        return
    _timed_cast(inst)


def _runtime_cast(inst, g):
    """2026-10-27 (skill-execution-model.md 6, tester: Zod R cut mid-channel by a timed code 2, Thousand Cuts and the
    multi-state basics on fixed timings, Batflight ending late): no timers; the codes come from the graph state the
    script's own graph events enter (code 2 = that state's exit, by any route). If the graph has not entered a state
    hooked to this script GRAPH_START_GRACE s after the Cast (a start event ics does not raise yet), the timed path
    runs instead, so a skill never waits for a state the graph will not reach."""
    did = inst.script.did
    inst.casting += 1
    inst.graph_casting = getattr(inst, "graph_casting", 0) + 1
    cast_id = getattr(inst, "cast_id", 0) + 1
    inst.cast_id = cast_id
    began = g.now()

    def check():
        if inst.cast_id != cast_id or not getattr(inst, "graph_casting", 0):
            return
        if g.in_state_of(did) or g.last_enter.get(did, -1e9) >= began - 0.05:
            return
        owner_d = getattr(inst.owner, "__dict__", {})
        if owner_d.get("graph_feed_pending", 0) > 0 and g.now() - began < GRAPH_START_GRACE + 0.5:
            # 2026-10-29 (tester report 2026-10-29 12:45; [ics] graph_feed_at_send): the start event is still on its way
            # to the client (and so to the graph); wait for it instead of falling back to the timed signals
            inst.after(0.05, check)
            return
        g.log(f"graph {g.label}: no state of script {did:#x} entered; timed cast signals")
        inst.graph_casting -= 1
        inst.casting = max(0, inst.casting - 1)
        _timed_cast(inst)
    if GRAPH_MISSILE_RELEASE > 0:
        state = {"gone": None}

        def watch():
            # 2026-10-27 (champion_check: Huntress' Grapple Bolt 0x3400070A waits in its state for 0x10000140 / 141 from
            # its missile script 0x3400073B, which ics ends without the expiry event): once every missile of the cast
            # is gone and the graph still holds the script's state, it goes back after GRAPH_MISSILE_RELEASE s
            # ([ics] graph_missile_release)
            if inst.cast_id != cast_id or not getattr(inst, "graph_casting", 0) or inst.removed:
                return
            ms = getattr(inst, "cast_missiles", None) or []
            if ms and not any(getattr(m, "alive", False) and not getattr(m, "expired", False) for m in ms)                     and g.in_state_of(did):
                state["gone"] = state["gone"] if state["gone"] is not None else g.now()
                if g.now() - state["gone"] >= GRAPH_MISSILE_RELEASE - 1e-6:
                    g.release(did, "its missiles are gone")
                    return
            else:
                state["gone"] = None
            inst.after(0.1, watch)
        inst.after(0.1, watch)
    if g.in_state_of(did) and g.last_enter.get(did, -1e9) >= began - 0.05:
        return
    inst.after(GRAPH_START_GRACE, check)


def deliver_hook(world, owner, code, did, offset=None, state=""):
    """A graph hook (turbineEventHookPayload) as event 0x1000000F {code}: to the owner's instances of script `did`,
    or to every instance when did is 0; an instance whose record does not accept 0x1000000F does not get it."""
    for inst in list(scripts_on(world, owner)):
        if inst.removed or (did and getattr(inst.script, "did", 0) != did):
            continue
        if code == RESULT_DONE and getattr(inst, "graph_casting", 0) and did:
            # the cast ends with the state's exit, also for a script that does not wait for the codes (Batflight
            # 0x34000038 accepts no 0x1000000F: its cast kept holding the champion's moves)
            inst.graph_casting -= 1
            inst.casting = max(0, inst.casting - 1)
            inst.cast_missiles = []
        acc = accepted_events(inst.script)
        if acc and EVENT_CAST_SIGNAL not in acc:
            continue
        if hasattr(world, "log"):
            world.log(f"[{getattr(world, 'time', 0.0):6.2f}] {inst.script.did:#x} graph hook {code} ({state})")
        if DEFER_HOOKS_IN_CHAIN and inst.__dict__.get("_chain_depth", 0):
            # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Green Arrow's
            # Bullseye 0x3400040C S1 raises its graph event before StartTimer(ShootTimer), the graph's enter hook 1 came
            # back at once and re-checked S1's transitions with the timer still unset = expired: S1 -> S4, cancelled):
            # the client's graph answers on its own update, so a hook raised while the instance runs a state's chain
            # is delivered when that chain has run ([ics] defer_graph_hooks_in_chain)
            inst.__dict__.setdefault("_deferred_hooks", []).append((code, offset))
            continue
        inst.last_missile_offset = tuple(offset) if offset else None    # MissileFireOffset (not read by a node yet)
        inst.signal(code)


def flush_deferred_hooks(inst):
    """The graph hooks held back while the instance ran a chain (DEFER_HOOKS_IN_CHAIN), in their order."""
    queue = inst.__dict__.pop("_deferred_hooks", None)
    while queue and not inst.removed:
        code, offset = queue.pop(0)
        inst.last_missile_offset = tuple(offset) if offset else None
        inst.signal(code)


EVENT_CAST_SIGNAL = 0x1000000F
PARAM_MISSILE_OFFSET = 0xA2103E4     # MissileFireOffset (0x9723D0 writes it next to the code, C)
_ACCEPTED = {}


def accepted_events(script):
    """The record's accepted-event list (top-level field 0x44AF56 count + 0x44AFBF ids; the client VM drops any other
    event, 0x461430; equal to the events its triggers name for all 875 scripts, skill-execution-model.md 0.7)."""
    did = getattr(script, "did", None)
    if did in _ACCEPTED:
        return _ACCEPTED[did]
    out = frozenset()
    raw = getattr(script, "raw", None)
    if isinstance(raw, dict):
        fl = raw.get("fields") or []
        for i, f in enumerate(fl):
            if f[2] == "0x44AF56":
                out = frozenset(y[3] for y in fl[i + 1:i + 1 + int(f[3])] if y[2] == "0x44AFBF")
                break
    _ACCEPTED[did] = out
    return out


def _timed_cast(inst):
    hooks = GRAPH_HOOKS.get(getattr(inst.script, "did", 0)) if GRAPH_HOOKS else None
    if hooks and _graph_cast(inst, hooks):
        return
    # 2026-10-21: the results are signals of the cast in progress, not the chain's end (basic attack 0x34000037:
    # S1 Cast -> S4 on IsAlive; S4 -> S2 (the shot) on 5; S2,S4 -> S3 on 2)
    inst.casting += 1
    point = inst.world.cast_time(inst.owner)
    bar = hasattr(inst.world, "cast_bar") and inst.world.cast_bar(inst.owner, point, "start")
    cast_id = getattr(inst, "cast_id", 0) + 1
    inst.cast_id = cast_id

    def cast_point():
        if bar:
            inst.world.cast_bar(inst.owner, point, "complete")
        inst.signal(RESULT_CAST_POINT)
        # 3 also comes at the cast point: unit attacks (0x340004A1: S1 -> S2 on 3, the state that applies the damage)
        # advance on it where the champions' scripts use 5 (2026-10-21)
        inst.signal(RESULT_CAST_DONE)

    started = getattr(inst.world, "time", None)

    def cast_end():
        # 2026-10-23 23:30 (tester: Grab's arm never stretches, Meltdown's throw cut; skill-second-stages.md 1): the
        # cast end (2) moves every AGL skill to S2 (skill_to_locomotion, EndSkill); the client's animation lasts while
        # a tethered missile is out (Grab S3 waits for 0x10000005), so 2 waits for it, up to CAST_WAITS_TETHER s
        now = getattr(inst.world, "time", None)
        out = [m for m in getattr(inst, "cast_missiles", ()) if m.alive and getattr(m, "tether", False)]
        if out and CAST_WAITS_TETHER and now is not None and started is not None and now - started < CAST_WAITS_TETHER:
            inst.after(0.1, cast_end)
            return
        inst.casting -= 1
        inst.cast_missiles = []
        inst.signal(RESULT_DONE)
    inst.after(point, cast_point)
    inst.after(point + CAST_RECOVERY, cast_end)


def _graph_cast(inst, hooks):
    """Cast signals timed by the graph: 3 / 5 / 6 at their trigger times, 2 at the state's exit trigger (else after
    GRAPH_EXIT_FALLBACK s: the state waits for a script event, e.g. a tether or a channel)."""
    codes = {c: t for c, t in hooks["codes"].items() if c in (3, 5, 6)}
    if not codes and hooks.get("exit") is None:
        return False
    inst.casting += 1
    cast_id = getattr(inst, "cast_id", 0) + 1
    inst.cast_id = cast_id
    started = getattr(inst.world, "time", None)
    # 2026-10-25 (champion-animation-matrix.md cause 3): the graph event reaches the client champion_scriptlet_delay
    # later and its movement states are replayed 0.1 s late; the hook times run from there ([ics] graph_hook_offset)
    # 2026-10-26 (deep-scan-animations.md 5: bots' 0x8D is not deferred as the local champion's): no offset for bots
    off = GRAPH_HOOK_OFFSET if getattr(inst.owner, "kind", "") == "champion" and not getattr(inst.owner, "bot", False)         else 0.0
    scale = 1.0
    if HOOKS_ATTACK_SPEED and hooks.get("bound") and hasattr(inst.world, "attribute"):
        # 2026-10-26 (deep-scan-animations.md 3, C: the client plays a speed-bound clip at playbackSpeed = 0x100006FE,
        # the attack speed; Gaslight Batman at 1.627 threw at 0.147 s while ics fired at 0.41 s): clip time x the clip's
        # static speed / attacks per second
        try:
            aps = float(inst.world.attribute(inst.owner, 0x100005FE) or 0.0)
        except Exception:                          # noqa: BLE001
            aps = 0.0
        if aps > 0.05:
            scale = float(hooks.get("speed", 1.0) or 1.0) / aps
    codes = {c: t * scale for c, t in codes.items()}
    for code, t in sorted(codes.items(), key=lambda kv: kv[1]):
        inst.after(max(0.0, t + off), lambda c=code: inst.signal(c) if inst.cast_id == cast_id else None)
    end = hooks.get("exit")
    end = max(end * scale, max(codes.values(), default=0.0)) + 0.01 + off if end is not None else GRAPH_EXIT_FALLBACK
    cosmetic = bool(hooks.get("cosmetic"))

    def cast_end():
        if inst.cast_id != cast_id:
            return
        now = getattr(inst.world, "time", None)
        out = [m for m in getattr(inst, "cast_missiles", ()) if m.alive and getattr(m, "tether", False)]
        if out and CAST_WAITS_TETHER and now is not None and started is not None and now - started < CAST_WAITS_TETHER:
            inst.after(0.1, cast_end)
            return
        inst.casting -= 1
        inst.cast_missiles = []
        if cosmetic and KEEP_COSMETIC_TAIL:
            if hasattr(inst.owner, "__dict__"):
                # 2026-10-27 (skill-execution-model.md 6.6.4: python -m ics.script_runtime crashed here, the NullWorld's
                # owner is a str)
                inst.owner.__dict__["cosmetic_until"] = time.time() + KEEP_COSMETIC_TAIL
        inst.signal(RESULT_DONE)
    inst.after(end, cast_end)
    return True


def _cooldown(inst, n, ops, chain):              # 0x10000007: StartCooldown(duration, SourceEntityDID, ...)[slot]
    slot = n.values[0] if n.values and isinstance(n.values[0], int) else 0xFFFFFFFF
    explicit = slot not in (0xFFFFFFFF, -1)
    slot = inst.slot if not explicit else slot
    seconds = inst.number(ops[0]) if ops else 0.0
    if explicit and SLOT_COOLDOWN_VARS and hasattr(inst.world, "restore_cooldown"):
        # 2026-11-03 (Blue Beetle's form swap, 0x34000451 / 454 / 455 graph S2): StartCooldown(TimeRemaining)[slot] puts
        # back the other form's saved cooldown, 0 = ready; it is a remaining time already reduced when it started
        inst.world.restore_cooldown(inst.source(), seconds, slot)
        _subs(inst, n, chain)
        return False
    try:
        inst.world.start_cooldown(inst.source(), seconds, slot=slot)
    except TypeError:
        inst.world.start_cooldown(inst.source(), seconds)
    _subs(inst, n, chain)
    return False


def _spend(inst, n, ops, chain):                 # 0x10000031: Spend(amount, entity) [resource]
    amount = num(inst.get(ops[0])) if ops else 0.0
    vital = n.values[0] if n.values and isinstance(n.values[0], int) else 0
    w = inst.world
    if SPEND_BY_VITAL and vital and hasattr(w, "set_vital"):
        # 2026-10-24 23:30 (aww-kit.md: Atomic Wonder Woman's passive adds +1 Rev with SpendCost(+1)[6], which drained
        # her bar): the amount is added, with its sign, to the node's vital (costs are negative, stat 3)
        ent = inst.ent(ops[1]) if len(ops) > 1 else inst.owner
        ent = inst.source() if ent is inst.owner else ent
        w.set_vital(ent, vital, w.vital(ent, vital) + amount)
        w.vitals_changed(ent)
    else:
        w.spend(inst.source(), -amount)
    _subs(inst, n, chain)
    return False


def _destroy(inst, n, ops, chain):               # 0x10000010: DestroyEntity(entity) [delay f32, flag]
    # 2026-10-21 (static analysis, script-nodes-names.md): its client execute plays _HFSM_DestroyEntityAction on the
    # entity and removes it after the delay; it was taken for a Delay. Missiles end with 0x10000010(SELF)[0 1].
    target = inst.ent(ops[0]) if ops else inst.owner
    vals = [v for v in n.values if isinstance(v, (int, float))]
    delay = max(0.0, num(vals[0])) if vals else 0.0
    if delay > 1000:                                # a raw f32 word
        delay = struct.unpack("<f", struct.pack("<I", int(delay) & 0xFFFFFFFF))[0]
    if isinstance(target, Missile):
        trip = target.trip
        if delay > 0 and target is inst.owner and inst.script.did in MISSILE_DESTROY_DELAY_SCRIPTS:
            target.destroy_pending = True          # Missile.arrive leaves the end to this (agl-r-impact-q-e.md 3.2)
        inst.after(delay, lambda: target.end(trip))
    elif target is not None and hasattr(inst.world, "destroy"):
        inst.world.destroy(target, delay)
    return False


def _mark(inst, n, ops, chain):                  # 0x1000006A as an action: set the bool attribute on the target
    target = inst.get(ops[0]) if ops else None
    if target:
        inst.markers.add(target)
        attr = next((v for v in n.values if isinstance(v, int)), 0)
        if attr and PREDICATE_FIRST:
            # 2026-10-25: as a predicate it reads the attribute from other scripts too (Gaslight Batman's E marks
            # 0x100003AB on its target, his passive's echo reads it), so the mark lives on the entity
            marks = getattr(inst.world, "entity_marks", None)
            if marks is None:
                holder = getattr(inst.world, "w", inst.world)
                marks = holder.__dict__.setdefault("entity_marks", {})
            marks.setdefault(_key(target), set()).add(attr)
    return False


def _entity_marked(world, ent, attr):
    marks = getattr(world, "entity_marks", None)
    if marks is None:
        marks = getattr(getattr(world, "w", None), "entity_marks", None) or {}
    return attr in marks.get(_key(ent), ())


def _detected(inst, n, ops, chain):              # 0x10000024: GetDetected(out entity, index)
    idx = int(num(inst.get(ops[1]))) if len(ops) > 1 else 0
    inst.set(ops[0] if ops else None, inst.detected[idx] if 0 <= idx < len(inst.detected) else 0)
    return False


def _offset(inst, n, ops, chain):                # 0x1000005A: Offset(from, to, out vector)
    a = inst.get(ops[0]) if ops else None
    b = inst.get(ops[1]) if len(ops) > 1 else None
    pa = inst.owner.pos if isinstance(a, Missile) else inst.world.position(a)
    pb = inst.world.position(b)
    if len(ops) > 2:
        inst.set(ops[2], tuple(q - p for p, q in zip(_vec(pa), _vec(pb))))
    return False


def _redirect(inst, n, ops, chain):              # 0x10000062: RedirectMissile(target, ...)
    target = inst.get(ops[0]) if ops else None
    if isinstance(inst.owner, Missile) and target:
        inst.owner.redirect(target)
    return False


def _set_variable(inst, n, ops, chain):          # 0x10000058: SetVariable(var, value | #event parameter)
    if not ops:
        return False
    src = ops[1] if len(ops) > 1 else None
    if src is not None and src.source == V.UNSET and src.value in inst.params:
        inst.set(ops[0], inst.params[src.value])
    elif src is not None and src.source == V.UNSET and src.value in inst.script.names:
        inst.set(ops[0], 0)                 # an event parameter this event does not carry
    else:
        inst.set(ops[0], inst.get(src) if src is not None else 0)
    return False


def _noop(inst, n, ops, chain):
    _subs(inst, n, chain)
    return False


RAISE_EVENT_SCRIPTLET, RAISE_EVENT_VAR = 0x100001E3, 0x780   # _HFSM_BehaviorRaiseEventAction, event variable


def _raise_graph_event(inst, n, ops, chain):     # 0x1000004E: RaiseGraphEvent(entity) [graph event 0x300000A4 table]
    ev = n.values[0] if n.values and isinstance(n.values[0], int) else 0
    ent = inst.ent(ops[0]) if ops else inst.owner
    if ev == 0x10000002 and ent is not None and time.time() < getattr(ent, "cosmetic_until", 0.0):
        # 2026-10-25 (champion-animation-matrix.md cause 2, C data: the script raises skill_to_locomotion right after the
        # cast end, 0.01-0.05 s into the state's cosmetic tail): kept off while the tail plays ([ics] keep_cosmetic_tail s)
        return False
    if ev == 0x10000002 and ent is not None and GRAPH_COSMETIC_TAIL:
        # 2026-10-29 (tester report 2026-10-29 12:45: AGL's R throw and every champion's skill tails cut; traffic: Meltdown's
        # script raised skill_to_locomotion at its code 2 = the skill state's hand-over to Meltdown_Cosmetic, which reached
        # the client 0.18 s into the 1.0 s clip; skill-animations-vs-original.md 2.2): with the graph runtime the cast end
        # never set cosmetic_until, so keep_cosmetic_tail was dead; now the graph says whether its _Cosmetic tail plays
        # ([ics] graph_cosmetic_tail; false = the script's event cuts the tail as in fase3-ig)
        g = graph_of(inst.world, ent)
        if g is not None and getattr(g, "in_cosmetic", None) and g.in_cosmetic():
            if hasattr(inst.world, "log"):
                inst.world.log(f"{inst.script.did:#x} skill_to_locomotion kept off: the cosmetic tail plays")
            return False
    if ev and ent is not None:
        inst.world.run_scriptlet(ent, RAISE_EVENT_SCRIPTLET, variables=[(RAISE_EVENT_VAR, ev)])
    return False


def _get_position(inst, n, ops, chain):          # 0x10000011: GetPosition(entity, out position): a frame
    if len(ops) > 1:
        ent = inst.ent(ops[0])
        if ent is None:
            inst.set(ops[1], Frame((0.0, 0.0, 0.0)))
            return False
        p = inst.world.position(ent)
        h = inst.world.heading(ent) if hasattr(inst.world, "heading") else 0.0
        inst.set(ops[1], Frame(p, math.degrees(h)))
    return False


def _fx_of(v):
    return v if isinstance(v, int) and v >> 24 == 0x1E else 0


def _hit_effect(inst, n, ops, chain):            # 0x1000007A: HitEffect(target, -, crit roll, ...) [key, ..., fx, crit fx]
    """2026-10-23 20:20 (skill-animations-and-skins.md 3.2: TargetHit has no client half, 0xAB4D80): the hit
    scriptlet (VFX_CBT_Hit_Shared 0x10000223) plays its fx record from variable 0x1000050A = values[5] (normal) or
    values[6] (critical, when the roll operand is true); without it no hit / impact FX showed."""
    vals = list(n.values)
    key = vals[0] if vals and isinstance(vals[0], int) else 0
    ent = inst.ent(ops[0]) if ops else inst.owner
    if key and ent is not None:
        crit = False
        if len(ops) > 2 and not ops[2].is_unset():
            try:
                crit = bool(inst.get(ops[2]))
            except Exception:                           # noqa: BLE001
                crit = False
        fx = _fx_of(vals[6]) if crit and len(vals) > 6 else 0
        fx = fx or (_fx_of(vals[5]) if len(vals) > 5 else 0)
        inst.world.run_scriptlet(ent, key, variables=[(0x1000050A, fx)] if fx else None)
    return False


def _start_scriptlet(inst, n, ops, chain):       # 0x10000103: StartScriptlet(entity, -, [duration], out handle) [key, n, ids..]
    """2026-10-23 20:20 (skill-animations-and-skins.md 3.1: client half 0x9CE300 sets 0x1000050A to the node's fx and
    passes the nested variable list): the scriptlet goes with its variables (values[1] = count, values[2..] = ids,
    operands 2.. = values) and 0x1000050A = the node's 0x1E fx record (persistent skill FX: auras, channel loops)."""
    vals = list(n.values)
    key = vals[0] if vals and isinstance(vals[0], int) else 0
    ent = inst.ent(ops[0]) if ops else inst.owner
    if key and ent is not None:
        count = vals[1] if len(vals) > 1 and isinstance(vals[1], int) and vals[1] < 8 else 0
        ids = [v for v in vals[2:2 + count] if isinstance(v, int)]
        variables = []
        for i, o in zip(ids, ops[2:2 + count]):
            try:
                variables.append((i, inst.get(o)))
            except Exception:                           # noqa: BLE001
                pass
        fx = next((_fx_of(v) for v in reversed(vals) if _fx_of(v)), 0)
        if fx and not any(i == 0x1000050A for i, _v in variables):
            variables.append((0x1000050A, fx))
        hold = next((float(v) for _i, v in variables if isinstance(v, (int, float)) and not isinstance(v, bool)
                     and 0 < float(v) < 120 and not _fx_of(v)), 0.0)
        if hold and getattr(inst.script, "did", 0) in START_SCRIPTLET_HOLD and hasattr(ent, "__dict__"):
            # tester report 2026-10-29 15:30 (recall: "it sounds and teleports but the animation does not show"): the
            # recall 0x3400000A S2 starts its channel fx (0x10000223 + fx 0x1E00009C, 0x1000033E = RecallDuration) and
            # then Fidgets_Disable 0x10000320 and Emote_Abort 0x100001F2 on the same champion, which end that run on
            # the client (the sound is a one-shot); the run is held for its duration ([ics] start_scriptlet_hold)
            ent.__dict__["hold_next_scriptlet"] = (key, hold)
        inst.world.run_scriptlet(ent, key, variables=variables or None)
        if hasattr(ent, "__dict__"):
            ent.__dict__.pop("hold_next_scriptlet", None)
    if ops:
        run = None
        w = getattr(inst.world, "w", None)
        if HANDLE_RUNS and key and w is not None and hasattr(ent, "eid"):
            # 2026-11-03 (tester report 2026-11-03 15:27: Superman's E target beacon and Blue Beetle's form effects; the
            # run: Heat Vision's StopScriptlet($ActiveScriptHandle) stopped the target's newest 0x10000223 run 0x16, not
            # its own 0x14): the handle names its own run ([ics] scriptlet_handle_runs)
            run = getattr(w, "live_scriptlets", {}).get((ent.eid, key))
        orders = getattr(w, "__dict__", {}).get("scriptlet_orders") if key and w is not None else None
        if orders is not None and hasattr(ent, "eid"):
            # 2026-11-03 (tester report 2026-11-03 22:16: Blue Beetle's passive particles gone; every 0x8D order ends
            # the runs earlier orders started, C 0x627E4D): the run rides along until its stop (ics/scriptlet_orders.py)
            orders.hold(ent, key, getattr(w, "live_scriptlets", {}).get((ent.eid, key)))
        inst.set(ops[-1], ("scriptlet", key, ent, run) if run is not None else ("scriptlet", key, ent))
    return False


def _conversation(inst, n, ops, chain):          # 0x100000D1: StartConversation [0, key, 1, 1, 0, 1, time limit]
    key = n.values[1] if len(n.values) > 1 and isinstance(n.values[1], int) else 0
    if key:
        inst.world.conversation(key)
    return False


def _get_player(inst, n, ops, chain):            # 0x10000187: GetPlayer(out player)
    if ops:
        inst.set(ops[0], inst.world.player())
    return False


def _get_agent(inst, n, ops, chain):             # 0x10000188: GetAgent(out agent, player): the player's champion
    if ops:
        inst.set(ops[0], inst.world.player())
    return False


HANDLERS = {
    0x100000D1: _conversation, 0x10000187: _get_player, 0x10000188: _get_agent,
    0x1000009C: _noop,      # [1, 0x10000016 | 2 | 0, ...] on a scene's enter / exit: an environment setting (guess)
    0x1000017B: _noop,      # [0, 1, 1, 0] on a scene's exit
    0x1000004E: _raise_graph_event, 0x10000011: _get_position, 0x1000007A: _hit_effect,
    0x10000103: _start_scriptlet,
    0x10000050: _init_skill, 0x1000009F: _load_stats, 0x1000003F: _face, 0x10000034: _scriptlet,
    0x100000E2: _set_value, 0x10000026: _cast, 0x10000007: _cooldown,
    0x10000031: _spend, 0x10000010: _destroy, 0x1000006A: _mark,
    0x10000058: _set_variable, 0x10000024: _detected, 0x1000005A: _offset, 0x10000062: _redirect,
    0x10000195: lambda inst, n, ops, chain: _skill_echo(inst, n, ops, chain),  # SkillEcho: 0x10000196 {Slot} to the owner's scripts ([ics] skill_echo_node)
}
COND_ACTIONS = {}            # action nodes that give a result when used as a condition (script_nodes.py)
EVENT_TRIGGERS = {0x1000013B, 0x10000055, 0x100000B1, 0x1000002C, 0x10000049, 0x1000017D, 0x1000003B,
                  0x10000019, 0x1000004A, 0x10000053, 0x10000067}


# --- predicates (used as conditions) -----------------------------------------------------------------

def _alive(inst, n, ops):                        # 0x1000003E: IsAlive(entity)
    e = inst.ent(ops[0]) if ops else inst.owner
    return bool(e) and inst.world.alive(e)


def _valid(inst, n, ops):                        # 0x1000001E: IsValid(entity)
    e = inst.get(ops[0]) if ops else None
    if ops and ops[0].is_self():
        e = inst.owner
    return bool(e)


def _kind(inst, n, ops):                         # 0x10000029: IsKind(entity) [flags: 0x10108 units, 0x1000 props]
    e = inst.ent(ops[0]) if ops else None
    flags = next((v for v in n.values if isinstance(v, int)), 0)
    return bool(e) and inst.world.kind_matches(e, flags)


def _valid_position(p):                          # 0x10000014: IsValidPosition(point): a ground-targeted use
    return isinstance(p, tuple) and any(abs(x) > 1e-6 for x in p[:3] if isinstance(x, (int, float)))


def _has_marker(inst, n, ops):                   # 0x1000006A: HasFlagAttribute(entity)[bool attribute]
    e = inst.ent(ops[0]) if ops else inst.owner
    attr = next((v for v in n.values if isinstance(v, int)), 0)
    if not e:
        return False
    if _entity_marked(inst.world, e, attr):
        return True
    if attr == MARKER_HIT:
        return e in inst.markers or inst.world.has_status(e, attr)
    if hasattr(inst.world, "combat"):
        return bool(inst.world.combat.flag(e, attr)) or inst.world.has_status(e, attr)
    return inst.world.has_status(e, attr)


def _on_event(inst, n, ops):                     # 0x1000013B / 0x10000055: event triggers used as predicates
    return inst.current_event is not None and bool(n.values) and inst.current_event == n.values[-1]


def _cast_signal(inst, n, ops):                  # 0x10000019 OnCastSignal as a predicate: the result code
    code = inst.current_code if inst.current_code is not None else inst.params.get(PARAM_CODE)
    return code is not None and bool(n.values) and code == n.values[-1]


PREDICATES = {
    0x1000003E: _alive, 0x1000001E: _valid, 0x10000029: _kind,
    0x1000006A: _has_marker, 0x1000013B: _on_event, 0x10000055: _on_event, 0x10000019: _cast_signal,
    0x10000014: lambda inst, n, ops: _valid_position(inst.get(ops[0]) if ops else None),
}


# --- missile classes -> scripts (the class's twin record 0x49 lists them) ---------------------------

# entity class -> its server scripts (DIDs). Set by the server from the game data (the class's template record
# 0x49xxxxxx, property 0x8E: ics/gamedata.py entity_scripts); the fallback is Sonic Batarang's missile only.
SCRIPT_RESOLVER = None
MISSILE_SCRIPTS = {0x40000090: (0x3400003F,)}


def missile_scripts(cls, override=0):
    out = []
    if override:
        try:
            return [V.load(override)]
        except OSError:
            pass
    if not isinstance(cls, int):
        return out
    dids = SCRIPT_RESOLVER(cls) if SCRIPT_RESOLVER else MISSILE_SCRIPTS.get(cls, ())
    for did in dids:
        try:
            out.append(V.load(did))
        except OSError:
            pass
    return out


# --- status effects and events between scripts --------------------------------------------------------
# A status effect record 0x48... names its own script (property 0x10000242); ApplySkill starts it on the target
# and sends it EVENT_STATUS_APPLIED with the caller's operands as parameters; it gets EVENT_STATUS_REMOVED when
# its duration ends. RaiseEvent sends an event to every script running on an entity. Which operand slot is which
# parameter was derived from the data (2026-10-21, ics_params.py: the slots callers fill vs. the parameters the
# receivers read); names where the ELF hash of a known name matches, raw hashes otherwise.
EVENT_STATUS_APPLIED, EVENT_STATUS_REMOVED = 0x10000006, 0x10000003
STATUS_RESOLVER = None               # status DID -> script DID (ics/gamedata.py status_script)
STACKS_RESOLVER = None               # status DID -> max stacks (property 0x10000063; > 1: one instance per use)
FLAGS_RESOLVER = None                # status DID -> status flag bits (property 0x10000334)
RECORD_RESOLVER = None               # (record DID, property) -> value, from the record read by kind (ics.combat)
EVENT_IMPACT = 0x10000126            # a tracked shot reached its target
APPLY_PARAMS = {1: ("EffectDuration",), 2: ("EffectRank", "StackCount"), 3: (0xC58DA9C, 0x9F942E2),
                5: ("SourceEntityDID",), 6: (0xCC58914,), 9: ("EffectSource",)}
# 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Green Arrow's Bullseye arrow
# 0x3400043D hit the bot champion for 5e-31): the receivers read slot 2 (TargetPosition, DashTargetPosition) as Position
# 0x6A0AB2E and slot 3 by its type: Bool 0x4965C (crit rolls), 0x5A05762 handles / counts, 0xD358722 numbers (Damage,
# BonusShield, HealthDelta, DamageMultiplier, NewDamage); 0xD358722 was filed under slot 2 ([ics] raise_event_float_param)
RAISE_PARAMS = {1: (0x9A6A765,), 2: ("Position",), 3: (0x5A05762, 0x4965C, 0xD358722)}
RAISE_PARAMS_OLD = {1: (0x9A6A765,), 2: ("Position", 0xD358722), 3: (0x5A05762, 0x4965C)}


def _params(inst, ops, table):
    out = {}
    for slot, names in table.items():
        if slot < len(ops) and not ops[slot].is_unset():
            v = inst.get(ops[slot])
            for name in names:
                out[name] = v
    return out


def scripts_on(world, ent):
    """The script instances running on an entity (skills, statuses)."""
    return world.scripts.setdefault(_key(ent), [])


def statuses_on(world, ent):
    return world.statuses.setdefault(_key(ent), {})


def _key(ent):
    return id(ent) if not isinstance(ent, (str, int, tuple)) else ent


_TARGET_PARAMS = ("TargetIID", 0x8DCD754, 0x9A6A765)      # TargetIID by name / by hash, RaiseEvent's IID parameter


def _event_target(params):
    """The entity an event is about (EVENT_LOOP_PER_TARGET), or None."""
    for k in _TARGET_PARAMS:
        v = params.get(k)
        if v is not None and not isinstance(v, (bool, float, tuple)) and not (isinstance(v, int) and v == 0):
            return v
    return None


def acting_entity(inst):
    """2026-10-28 15:00 (tester report 2026-10-28 15:00: Meltdown hit AGL's own side and never slowed;
    meltdown-moving-target.md 3.3 / 6.2, C ics, P strong for the original: the client's FindTargets takes SELF from the
    owner block and the relation team from the context's source descriptor 0x991F60, GetCreator's too, and of the 21
    status scripts with ApplyDamage that read EffectSource, 19 leave its source unset): the entity a script acts for in
    relation, damage credit, nested statuses and new missiles. A status acts for its applier (effect_source:
    apply_status' source argument, never its EffectSource parameter) when that is set and is not the status' own owner;
    dead or alive (its Entity keeps its team).
    Anything else: Instance.source() (a missile's shooter, else the owner). [ics] status_acts_for_source."""
    if STATUS_ACTS_FOR_SOURCE and getattr(inst, "status", None) is not None:
        src = getattr(inst, "effect_source", None)
        if isinstance(src, Missile):
            src = src.owner
        if src is not None and not (isinstance(src, int) and src == 0) and _key(src) != _key(inst.owner):
            return src
    return inst.source()


def raise_event(world, ent, ev, params=None):
    for inst in list(scripts_on(world, ent)):
        inst.event(ev, params)


_SHARED_LOCALS = {}


_SPLIT_LOCALS = {}


def _split_locals(script):
    """Names a script uses in two or more local frames (operand source 3, 4, 5 ... = the nesting depth of the variable
    block). 2026-11-02 (tester report 2026-11-03 00:32: Superman's E punch hit Swamp Thing, which the dash only touched):
    Heat Vision 0x340003D6 keeps its target in graph S1's TargetIID (source 3) and what the dash collides with in graph
    S7's own TargetIID (source 5); the original's frames are separate memory, ics kept one variable per name, so the
    collision replaced the target. These names are kept per (source, name) ([ics] local_frames; 95 scripts)."""
    did = getattr(script, "did", None)
    if did not in _SPLIT_LOCALS:
        srcs = collections.defaultdict(set)

        def walk(n):
            for o in getattr(n, "operands", ()):
                if isinstance(o.source, int) and 3 <= o.source < 16:
                    srcs[o.value].add(o.source)
            for c in getattr(n, "children", ()):
                walk(c)
        raw = getattr(script, "raw", None)
        if raw is not None:
            walk(V.Node(raw))
        _SPLIT_LOCALS[did] = {h for h, s in srcs.items() if len(s) > 1}
    return _SPLIT_LOCALS[did]


def _shared_locals(script):
    """Hashes declared by more than one state's locals, or by the script's own variables (RESET_LOCALS keeps them)."""
    did = script.did
    if did not in _SHARED_LOCALS:
        seen = collections.Counter()

        def walk(st):
            for h in (getattr(st, "locals", None) or {}):
                seen[h] += 1
            for c in getattr(st, "states", None) or []:
                walk(c)
        for g in script.graphs:
            walk(g)
        _SHARED_LOCALS[did] = {h for h, k in seen.items() if k > 1} | set(getattr(script, "variables", {}) or {})
    return _SHARED_LOCALS[did]


def recast_window(inst, ev=0x1000001D):
    """2026-10-25 (stolen-powers-audit.md 3: Super Strength carries in S3 and throws on a second 'skill used'): is the
    instance busy (graph 0 out of its idle S0) with a nested state waiting for the skill-used event? A cast then is the
    skill's second stage, not a new use, and its cooldown (started by the first stage) does not refuse it."""
    if inst is None or not getattr(inst, "regions", None):
        return False
    top = inst.regions[0]
    if top.state in (None, 0):
        return False

    def waits(region):
        if region is None:
            return False
        for t in region.graph.transitions:
            if t.sources and region.state not in t.sources:
                continue
            trig = t.trigger
            if trig is not None and _event_trigger(trig) and ev in [v for v in trig.values if isinstance(v, int)]:
                return True
        return waits(region.child)
    return waits(top.child)


def status_flags(status):
    return FLAGS_RESOLVER(status) if FLAGS_RESOLVER else 0


_COUNTED = {}


def _waits_for(script, events):
    """Does any transition of the script wait for one of these events (a trigger node holding the id)?"""
    def node_has(n):
        return any(v in events for v in n.values if isinstance(v, int)) or any(node_has(c) for c in n.children)

    def state_has(st):
        return any(t.trigger is not None and node_has(t.trigger) for t in st.transitions) or \
            any(state_has(c) for c in st.states)
    return any(state_has(g) for g in script.graphs)


def counted_status(script):
    """2026-10-25 (skill-mechanics-recipes.md 1, C: 9 status scripts wait for 0x100000D7, 10 for 0x100000A8): a status
    that counts its stacks itself (one instance, StackCount / EffectDuration updated by those events)."""
    did = getattr(script, "did", 0)
    if did not in _COUNTED:
        _COUNTED[did] = _waits_for(script, (EVENT_STACKS_CHANGED, EVENT_DURATION_CHANGED))
    return _COUNTED[did]


def _restack(world, source, target, status, current, params, stacks, count):
    """A re-apply of a running one-instance status: the stack count (count = absolute, else +1, clamped to [0, max]),
    the expiry reset, then 0x100000D7 {StackCount} when the count changed and 0x100000A8 {EffectDuration,
    DurationDelta}; never 0x10000006 again (189 status scripts go back to idle on it, C)."""
    old = int(getattr(current, "stack_count", 1) or 1)
    new = int(count) if count is not None else old + 1
    new = max(0, min(new, max(int(stacks or 1), 1)))
    if new == 0:
        remove_status(world, target, status, current)
        return None
    params = dict(params)
    params.setdefault("EffectSource", source)
    if source is not None:
        current.effect_source = source             # the latest applier, before its events (acting_entity)
    duration = num(params.get("EffectDuration", 0))
    left = max(0.0, getattr(current, "ends", world.time) - world.time)
    if duration > 0:
        current.duration = duration
        _expire_at(world, target, status, current, world.time + duration)
    current.stack_count = new
    if new != old:
        current.event(EVENT_STACKS_CHANGED, dict(params, StackCount=new, EffectDuration=duration))
    current.event(EVENT_DURATION_CHANGED, dict(params, EffectDuration=duration, DurationDelta=duration - left))
    return current


def apply_status(world, source, target, status, params, skill_world=None, count=None):
    """Start a status effect on target (or refresh it when it does not stack). Returns the instance, or None.
    count: AddStacks' absolute stack count (status_stack_model)."""
    running = statuses_on(world, target).setdefault(status, [])
    stacks = STACKS_RESOLVER(status) if STACKS_RESOLVER else 1
    if STATUS_STACK_MODEL and running and not running[0].removed and (stacks <= 1 or counted_status(running[0].script)):
        return _restack(world, source, target, status, running[0], params, stacks, count)
    if STATUS_STACK_MODEL and count is not None and count <= 0:
        return None
    if running and (stacks <= 1 or len(running) >= stacks):
        current = running[0]                       # refresh
    else:
        did = STATUS_RESOLVER(status) if STATUS_RESOLVER else 0
        if not did and RECORD_RESOLVER:
            # 2026-10-22: the pattern search of gamedata.status_script misses some records (0x48000646, Green
            # Lantern's root): the record read by property kind names the script too
            did = RECORD_RESOLVER(status, 0x10000242) or 0
        script = None
        if did:
            try:
                script = V.load(did)
            except OSError:
                world.log(f"status {status:#x}: script {did:#x} not decoded")
        if script is None:
            # 2026-10-22: a status record without a script (a mark such as Poison Ivy's 0x480008AC) still exists for
            # its duration, so HasStatus / RemoveStatus / GetStackCount see it
            script = _empty_script(status)
        current = Instance(script, target, skill_world or world)
        current.status = status
        current.started = world.time
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; meltdown-moving-target.md 6.2 and its skeptic review 1-2): the
        # applier, set before any chain of the status runs (its enter chain runs inside the applied event below)
        current.effect_source = source
        running.append(current)
        scripts_on(world, target).append(current)
        if hasattr(world, "status_mirror"):
            world.status_mirror(target, current, True)
        _record_flags_on(world, target, status, current, source)
        current.start()
    if source is not None:
        current.effect_source = source             # a refresh: the latest applier (acting_entity)
    params = dict(params)
    params.setdefault("EffectSource", source)
    scale = world.status_duration_scale(source, target, status) if hasattr(world, "status_duration_scale") else 1.0
    if scale != 1.0 and num(params.get("EffectDuration", 0)) > 0:
        params["EffectDuration"] = num(params["EffectDuration"]) * scale     # the target's resilience (items)
    if STATUS_STACK_MODEL and not hasattr(current, "stack_count"):
        current.stack_count = max(1, min(int(count or 1), max(int(stacks or 1), 1)))
        params.setdefault("StackCount", current.stack_count)
    current.event(EVENT_STATUS_APPLIED, params)
    duration = num(params.get("EffectDuration", 0))
    current.duration = duration
    if duration > 0:
        _expire_at(world, target, status, current, world.time + duration)
    return current


def _empty_script(did):
    return V.Script({"id": f"0x{did:08X}", "type": "script", "fields": [], "children": [], "status": "no script"})


def _expire_at(world, target, status, inst, when):
    inst.expires = getattr(inst, "expires", 0) + 1
    inst.ends = when
    mark = inst.expires
    world.after(max(0.0, when - world.time),
                lambda: mark == inst.expires and remove_status(world, target, status, inst, True))


def set_status_duration(world, inst, seconds, add=False):
    """SetStatusDuration (0x100000CA): remaining := seconds, or += seconds."""
    if inst is None or inst.removed:
        return
    before = max(0.0, getattr(inst, "ends", world.time) - world.time)
    left = before + seconds if add else seconds
    inst.duration = left
    if left <= 0 and add:
        remove_status(world, inst.owner, inst.status, inst, True)
        return
    _expire_at(world, inst.owner, inst.status, inst, world.time + left)
    if STATUS_STACK_MODEL and counted_status(inst.script):
        inst.event(EVENT_DURATION_CHANGED, {"EffectDuration": left, "DurationDelta": left - before})


def remove_status(world, target, status, inst=None, by_time=False):
    running = statuses_on(world, target).get(status) or []
    if inst is None:
        inst = running[0] if running else None
    if inst is None or inst not in running:
        return
    running.remove(inst)
    if not running:
        statuses_on(world, target).pop(status, None)
    inst.event(EVENT_STATUS_REMOVED, {"ExpiredByTime": 1 if by_time else 0, "ExplicitlyRemoved": 0 if by_time else 1})
    if not inst.removed:
        # the removal event normally sends the state machine to its idle state (exit chains ran); whatever is
        # left (a state without such a transition) runs its exit chain now
        for r in inst.regions:
            if r.state not in (0, None):
                r.leave()
                r.state = None
    inst.removed = True
    comb = getattr(world, "combat", None)
    for h, attr in getattr(inst, "record_mods", ()):
        if comb is not None:
            comb.remove_modifier(target, h, attr)
    inst.record_mods = []
    if hasattr(world, "status_mirror"):
        world.status_mirror(target, inst, False)
    try:
        scripts_on(world, target).remove(inst)
    except ValueError:
        pass


def _record_flags(status):
    """The flag attributes a status record sets for its whole duration: its list 0x1000046F of {0x10000450 attribute,
    0x10000453 op, 0x100004C3 value}, the op-6 (set) entries with a value (Rooted 0x100007FE, Stunned 0x100003F3,
    Crippled 0x10000B39, 0x100006F3 ...; 31 of the 232 status records with a list). Cached per status."""
    cache = _record_flags.__dict__.setdefault("cache", {})
    if status not in cache:
        out = []
        lst = RECORD_RESOLVER(status, 0x1000046F) if RECORD_RESOLVER else None
        for _k, _kind, m in lst if isinstance(lst, list) else ():
            if not isinstance(m, list):
                continue
            md = {k: v for k, _kd, v in m}
            if md.get(0x10000453) == 6 and md.get(0x10000450) and md.get(0x100004C3) is not None:
                out.append((int(md[0x10000450]), bool(md[0x100004C3])))
        cache[status] = out
    return cache[status]


def _record_flags_on(world, target, status, inst, source):
    """2026-11-02 (tester report 2026-11-02 01:45: Superman's W Frost Breath roots nobody in its inner cone): the root
    0x48000A06 is data only (its script 0x340002A9 shows the ice and the icon); the record's 0x1000046F sets Rooted.
    ics read none of these lists: each op-6 flag is now a modifier for the status' lifetime ([ics] status_record_flags)."""
    comb = getattr(world, "combat", None)
    if not STATUS_RECORD_FLAGS or comb is None:
        return
    inst.record_mods = [(comb.add_modifier(target, attr, 6, value, source), attr)
                        for attr, value in _record_flags(status)]


def status_instances(world, target):
    return [i for lst in statuses_on(world, target).values() for i in lst]


def start_script(script, owner, world, slot=None, initial=None):
    """Start a persistent script on an entity (a champion's skill, a unit's own script). A skill script then gets
    the re-init event (rank / level / stats changed: it loads its stats, 1.7). initial: named variables set first."""
    inst = Instance(script, owner, world, initial) if initial else Instance(script, owner, world)
    inst.slot = slot if slot is not None else (world.skill_slot(owner) if hasattr(world, "skill_slot") else None)
    scripts_on(world, owner).append(inst)
    inst.start()
    if inst.slot is not None:
        reinit(inst)
    return inst


def reinit(inst):
    """Event 0x10000008 (P: rank / level / stat change; with 0x1000000C, 0x100000A9, 0x100001B3 the re-init family
    every skill listens to, guarded by IsSlotSkillScript): the skill loads its stats again. 2026-10-22: 0x3400017E
    (Wonder Woman's basic attack) loads SkillDamage only on this event; without it every hit did 0."""
    inst.init_rank = inst.world.skill_rank(inst.owner) if hasattr(inst.world, "skill_rank") else 1
    inst.init_stats = getattr(inst.owner, "stats_version", 0)
    inst.event(EVENT_REINIT)


def activate(inst, target=None, point=None):
    """Use a running skill script: its targets and the 'skill used' event (0x1000001D: TargetIID, TargetPosition).
    Returns whether the script took the event (False: no transition waits for it now, e.g. AWW's Smite 0x34000255 while
    its buff 0x480006FD is up)."""
    inst.request = {}
    if target is not None:
        inst.request["TargetIID"] = target
    if point is not None and LOCAL_Y_FORWARD and not isinstance(point, Frame):
        # a client target point faces from the caster to it (its offsets then lie along the aim)
        o = inst.world.position(inst.owner) if hasattr(inst.world, "position") else None
        if o is not None:
            dx, dy = point[0] - o[0], point[1] - o[1]
            yaw = math.degrees(math.atan2(dy, dx)) if (dx or dy) else math.degrees(getattr(inst.owner, "heading", 0.0))
            point = Frame(tuple(point), yaw)
    if point is not None:
        inst.request["TargetPosition"] = point
    for name, value in inst.request.items():
        inst.vars_by_name(name, value)
    if inst.slot is not None and hasattr(inst.world, "skill_rank") and             getattr(inst, "init_rank", None) != inst.world.skill_rank(inst.owner):
        reinit(inst)                           # ranked up since the last use: the stats of the new rank
    elif inst.slot is not None and STATS_REINIT and             getattr(inst, "init_stats", 0) != getattr(inst.owner, "stats_version", 0):
        # 2026-10-26 (tester: an item's attack speed / damage did not change the attacks; measured: the skills load their
        # stats on 0x10000008 only, at start): the owner's stats changed since (an item, a level) -> load them again
        reinit(inst)
    params = dict(inst.request)
    ref = inst.world.skill_ref(inst.owner) if hasattr(inst.world, "skill_ref") else None
    if ref is not None:
        params["SourceEntityDID"] = ref
    inst.use_echoed = inst.echo_raised = False
    taken = bool(inst.event(EVENT_ACTIVATE, params))
    if SKILL_USED_BROADCAST and isinstance(inst.slot, int) and 1 <= inst.slot <= 4 \
            and (taken or not SKILL_USED_BROADCAST_TAKEN)             and (SKILL_USED_EVERY_USE or not (SKILL_ECHO_NODE and _has_echo(inst.script)))             and not (SKILL_USED_EVERY_USE and inst.echo_raised):
        # 2026-10-25 (kit-audit-2.md 4: Huntress / Flash / Green Lantern / Nightmare Catwoman passives count it): a Q/W/
        # E/R use raises 0x10000196 {Slot} on all the owner's scripts. 2026-10-28 15:00 (tester report; test-2026-10-28-
        # 1439-sweep.md S5: 10 of 16 Smite uses were ignored by the script): only a use the script took ([ics]
        # skill_used_broadcast_taken; false = every use, fase3-ie)
        raise_event(inst.world, inst.owner, 0x10000196, {"Slot": inst.slot})
        # 2026-11-03 (tester report 23:24: in the original the ranged W also starts Blue Beetle's passive when it is
        # detonated, a second press the script takes with no SkillEcho after it): every taken use raises the notice; the
        # use's own SkillEcho then adds no second one ([ics] skill_used_every_use; false = anim-22: SkillEcho only)
        inst.use_echoed = True
    return taken


_HAS_ECHO = {}


def _has_echo(script):
    """The script calls SkillEcho 0x10000195 itself (221 skill scripts, right after their cast point)."""
    did = getattr(script, "did", None)
    if did not in _HAS_ECHO:
        found = []

        def walk(n):
            if found:
                return
            if n.type_id == 0x10000195:
                found.append(True)
                return
            for c in n.children:
                walk(c)
        raw = getattr(script, "raw", None)
        if raw is not None:
            walk(V.Node(raw))
        _HAS_ECHO[did] = bool(found)
    return _HAS_ECHO[did]


def _skill_echo(inst, n, ops, chain):            # 0x10000195 SkillEcho(entity)
    """2026-11-03 (tester report 2026-11-03 16:11: Blue Beetle's passive does not start on his melee E / W): the
    original's "skill used" notice. 221 skill scripts call it right after their cast point; Blue Beetle's passive
    0x34000456 waits for 0x10000196 and reads its parameter Slot (0x5A364) to count the uses. It raises 0x10000196
    {Slot} on the owner's scripts (P: no client half; the meaning from its place and its listeners). ics raised the
    event at the activation, only when the script took the use; a script with this node raises it here
    ([ics] skill_echo_node)."""
    if SKILL_ECHO_NODE and isinstance(inst.slot, int) and 1 <= inst.slot <= 4 and getattr(inst, "status", None) is None:
        if SKILL_USED_EVERY_USE and getattr(inst, "use_echoed", False):
            inst.use_echoed = False          # this use's activation already raised it
            return False
        raise_event(inst.world, inst.owner, 0x10000196, {"Slot": inst.slot})
        inst.echo_raised = True              # raised inside the activation: it adds no second one
    return False


def use_skill(script, owner, world, target=None, point=None):
    """Start a skill script on its owner and send it the 'skill used' event."""
    inst = start_script(script, owner, world)
    activate(inst, target, point)
    return inst


from . import script_nodes  # noqa: E402,F401  (registers the combat and world nodes in HANDLERS / PREDICATES)


def _main(argv):
    did = int(argv[0], 16) if argv else 0x3400003B
    w = NullWorld()
    inst = use_skill(V.load(did), "Batman", w, target="Drone")
    w.run_until(5.0)
    unknown = set(inst.unknown)
    for lst in w.scripts.values():
        for i in lst:
            unknown |= i.unknown
    for m in w.missiles:
        for i in m.instances:
            unknown |= i.unknown
    if unknown:
        w.log("not implemented: " + ", ".join(sorted(map(str, unknown))))


if __name__ == "__main__":
    import sys
    from ics import script_runtime as _this       # the package module, where script_nodes registered its nodes
    _this._main(sys.argv[1:])
