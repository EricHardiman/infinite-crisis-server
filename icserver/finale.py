"""Tutorial 1, part 3: from the end of the Bat Scream to the victory.

Follows the tutorial's dialogue and the original's video (2026-10-15 12:01):

  car_intro    0x1C5 "We've got another car in our way..." (the vehicle at the
               end of the bridge) "...Give Batman a copy of my Super Strength."
  strength     0x1C1 "Protector, use Super Strength to clear the way.": the
               Stolen Power on F (Superman's Super Strength); a marker on the car
  carrying     Batman lifts the car (F on it; while F sends nothing: an Alt+click
               on it, or walking into it); hint 26 "Super Strength and moving"
  throw        0x1C0 "Look out, more drones!" (3 drones a bit further on),
               0x1B4 "Throw the car!": a right-click (or F / an attack) throws
               it; it explodes where it lands and destroys the drones
  destroyer_cinematic   cinematic 0x35000028: the sphere falls before the last
               gate and opens (its own lines 0x1CF "Looks like we've really got
               their attention now...")
  reach        0x1D7 "You know what to do." -- "Use what you've learned to reach
               the Destroyer": another car (a different model) blocks the way,
               a melee and a ranged drone hit it (they turn on Batman only when
               attacked); a marker on the car once Batman can see it. The two
               drones down: level 7 and a skill point (any skill).
  carrying2 / throw2    lift that car and throw it at the two drones further on
  destroyer    0x1C7 "We will not allow this machine to stand in our way!" --
               "Defeat the Destroyer": it does not fight back; Batman hits it
               from further away than other targets
  ending       cinematic 0x35000025 ("You did it, Protector!", the last gate
               opens), then the victory

Every spot is a guess from the video and the layout (pack 0xA0000256: the
Destroyer at (152.75, 24.0), the last gate at (159.9, 28.0)); [tutorial]
finale_positions = { name = [x, y], ... } moves any of them.
"""
import math
import struct
import time

from . import batman
from . import messages as M
from . import stolenpowers
from .bridge import Z, along
from .wire import KIND_DID, KIND_ENUM, KIND_F32, KIND_IID, KIND_INT

SLOT_F = 8
HUD_SKILL_BUTTON_F = 23                  # SkillButtonStolenPower2
HINT_SUPER_STRENGTH = 26                 # "Super Strength and moving"
DESTROYER_CINEMATIC = 0x35000028         # actors: the Destroyer (layout record 0x35000028)
ENDING_CINEMATIC = 0x35000025            # actors: Gaslight Batman by the last gate, the Gate
DESTROYER_WS = 0x2E000AB5
DESTROYER_VARIANT = 0x40000EB2
# 12:32: 0x2E00074D / 4E were a wrong reading (no such world states: the car
# was invisible). The layout 0x1D000771 (pack 0xA0000256) places
# 02PaddyWagonA / B with world states 0x2E00034D / 0x2E00034E.
# [tutorial] car_b_wstate = 0x2E000AAB brings back the street's police wagon.
CAR_B_WS = 0x2E00034D
# 13:35: the street at car B runs from y ~11.5 (south wall) to the crates
# behind it; the car's box reaches into both walls ([tutorial] finale_obstacles)
# so there is no way round ([tutorial] car_b_box = [half length, half width])
CAR_B_BOX = (7.5, 1.6)
# 17:36 (static analysis): in the original's intro cinematic 0x35000026 the
# paddy wagons explode with their OWN scriptlet Vfx_OnExplode (0x10000079), no
# variables, and nothing else (no behavior property, no Destructible state).
# Our car rejected it because its allowed-scriptlet list comes from property
# 0x7D2 (the world state's script templates), which a carrier-built prop never
# gets: the server now sends it (tutorial1.WSTATE_SCRIPT_TABLES).
# [tutorial] car_explode_keys
CAR_EXPLODE_KEYS = (0x10000079,)
# 12:18 (diag --scripts): the wagon accepts only 0x5 and Vfx_OnExplode; Vfx_OnCollision
# (0x10000016) and Vfx_OnInit (0x10000078) are rejected. 0x5 is tried in their place
CAR_COLLISION_KEYS = (0x5,)
CAR_THROWN_KEYS = ()                     # Vfx_OnThrown 0x1000087A: rejected by the wagon
CAR_INIT_KEYS = (0x5,)                   # once when the car appears (the table's other key)
# 14:15 (logs\records): the paddy wagon's 0x1C000021 is a Havok behavior graph
# (env_gas_vehicle_paddy_wagon_behavior.hkb): states Idle01 / Idle02, each an
# idle clip and a crash clip (env_gas_deco_vehicle_a_cin_car_a/b_crash.hkx),
# behavior strings State_to_State, IdleState01, IdleState02. The world state
# sets property 0x100003F2 (an enum) to IdleState01 (0x10000117): the crash is
# tried by setting it to State_to_State (0x10000050), then IdleState02
# (0x10000116) ([tutorial] car_crash_states, one every car_crash_step s)
CAR_BEHAVIOR_PROPERTY = 0x100003F2
VICTORY_KEYS = (0x10000A9E,)             # Cinematic_Victory (scriptlet name; tried on Batman)
# The model's origin is not the middle of the car: along / across its line
# (yaw). 16:14: the tester's Alt+click gave (0.66, 0.47); 17:36: the paddy
# wagon's skeleton 0x2D000238 (bone pivots: front at +Y, rear at -Y, symmetric
# left/right) puts the middle ~0.68 m along and 0 across: the 0.47 m across was
# the "to one side" ([tutorial] car_model_origin = [along, across])
# 20:22: the bridge's car (0x2E00034E) was right with no offset: it keeps none
MODEL_ORIGIN = {0x2E00034D: (0.68, 0.0)}
CARRY_ORIGIN = (0.68, 0.0)               # the wagon's middle from its origin, along its yaw (carried)
# the Destroyer's own scriptlets (diag 14:54): Cinematic_Startup,
# CinematicCharacter_State00; then CinematicCharacter_State01, Vfx_Spawn
DESTROYER_START_KEYS = (0x10000E5B,)      # was (0x100007EB, 0x10000E5B): Startup now at its frame
# the cinematic 0x35000028's keys on its Destroyer actor: (seconds after it starts, key)
DESTROYER_CINEMATIC_KEYS = ((115 / 30.0, 0x100003A6), (125 / 30.0, 0x100007EB))
DESTROYER_ACTOR_TABLES = (0x1D0003BA, 0x1D000774, 0x1D000385)
DESTROYER_OPEN_KEYS = (0x10000E5C, 0x10000032)
CAR_CRASH_STATES = (0x10000050, 0x10000116)
# Batman's Super Strength (17:36, his animation graph 0x1A0002E7 and the skill
# scripts 0x34000164 / 0x34000161): SuperStrength_InitObjectPickup puts him in
# the graph's SuperStrength_Car machine at Pickup_Start (he bends down to grab
# it and HOLDS that pose), SuperStrength_PickupObject lifts it (Pickup, then
# Hold: the car idle / walk / run clips with the hands up, driven by the same
# speed as normal walking: nothing more to send while carrying),
# SuperStrength_ThrowObject throws it (the car leaves his hands at 0.20 s), and
# _Combat_GoToLocomotion brings back normal walking. ANY other scriptlet on
# Batman while carrying (0x100005D4 was a Stargirl effect, not a carry state;
# basic attacks, skills) drops him out of the Hold state.
# [tutorial] lift_keys (one every lift_step s), carry_keys, throw_keys
LIFT_KEYS = (0x100007A2, 0x100007A1)
# 19:00: with those two Batman bent down, grabbed the car and STAYED crouched
# (the graph's Pickup_Start waits for the event CarPickup, which PickupObject
# does not raise without the original's attach). _HFSM_BehaviorRaiseEventAction
# (0x100001E3, in his table) raises any graph event: its variable 0x780 (enum)
# is the event, as the client's own raise-event script node passes it
# ([tutorial] lift_events, raised with the last lift key; throw_end_events)
RAISE_EVENT_KEY, RAISE_EVENT_VAR = 0x100001E3, 0x780
EV_CAR_PICKUP, EV_TO_LOCOMOTION = 0x10000246, 0x100000BB
THROW_KEYS = (0x100007A0,)
THROW_SKILL = 0x480003C9                 # Super Strength's throw (ground target, 9 m, range markers)
LOCOMOTION_KEYS = (0x100002FD,)          # _Combat_GoToLocomotion
CARRY_KEYS = ()
# Vfx_Stp_Detonate_Matter_Explosion_Hit (the Detonate power's blast),
# Vfx_OnExplode, Vfx_Inf_Explode (names table 0x33000000)
BLAST_KEYS = (0x100005B4, 0x10000079, 0x100001A0)
SPHERE_WS = 0x2E000AC5                   # "PowerCore" of the layout
DESTROYER_RING_WS = 0x2E001157           # env_pvp_phase_pod: the crater ring (tester 2026-10-17 10:37)
SPHERE_KEYS = (0x1000018E, 0x10000347, 0x10000076)     # old start keys: rejected (diag 2026-10-17 12:30:21)
# (seconds after the Destroyer cinematic starts, key) on the PowerCore: frame 115 = 0x100003A6
SPHERE_CINEMATIC_KEYS = ()
# (seconds after the cinematic starts, graph event) on the phase pod (13:28)
SPHERE_CINEMATIC_EVENTS = ()   # with a graph set: ((0.6, 0x10000154), (115 / 30.0, 0x100004A5))

# the road from the end of the bridge (s = 66) towards the Destroyer
ROAD_FROM, ROAD_TO = along(66.0, 0.0)[:2], (152.75, 24.0)
ROAD_YAW = math.atan2(ROAD_TO[1] - ROAD_FROM[1], ROAD_TO[0] - ROAD_FROM[0])
# 14:15: straight across the road the car left a gap (in the picture) between
# its front and the building corner at (137, 11.6); it now runs from the crates
# (131.5, 18.4) to that corner. 14:30: the paddy wagon's model lies 90 degrees
# off its yaw (tutorial1.MODEL_YAW_OFFSET): until then it stood ALONG the road
# while its walking box was across it
# 15:09: the tester's two Alt+clicks for its ends; 15:21: between the last
# two, (132.9, 16.2) and (134.1, 10.5); 17:25: its ends again, (133.4, 17.2)
# and (134.6, 10.8); 20:14: (133.1, 17.2) and (134.6, 10.6)
CAR_B_YAW = math.atan2(10.6 - 17.2, 134.6 - 133.1)

POSITIONS = {
    "strength_melee1": along(69.0, -1.8), "strength_melee2": along(70.5, 0.4),
    "strength_ranged": along(69.5, 2.4),
    # 13:24: it was too far ahead of its drones; 13:35: Batman walked past it
    # at y 11.5: 1.4 m further south, across the street
    # 17:25: the middle of the tester's two end pings
    "car_b": (133.85, 13.9, Z),
    # 13:12 (Alt+clicks in game): the two drones hitting the car stand between
    # Batman and it
    # 14:15: the turned car covers the old spots; the drones stand off its west side
    "car_b_melee": (130.1, 15.6, Z), "car_b_ranged": (130.9, 13.4, Z),
    "ahead_melee": (145.5, 19.6, Z), "ahead_ranged": (146.6, 17.6, Z),
    "destroyer": (152.75, 24.0, Z),
    "sphere": (152.5, 28.0, Z),
}
# the bridge's marker steps 11-13 are behind Batman by then (14+ would collide
# with other object ids: guide ping = 0x...30 + step, player pings from 0x...40)
MARKER_STEP = {"car_a": 11, "car_b": 12, "destroyer": 13}

OBJ_STRENGTH = ("Place your cursor on the vehicle and press <font color='#FFFF00'>('F')</font> "
                "to lift it with <font color='#66FFFF'>Super Strength</font>")
OBJ_THROW = ("Aim your cursor at the drones and <font color='#FFFF00'>Left-click</font> "
             "to throw the vehicle")                                             # 03dbf934
OBJ_REACH = "Use what you've learned to reach the Destroyer"
OBJ_WAIT = "Another car blocks the way"                     # 03ebf934
OBJ_RANK = "Use your skill point: click a highlighted button to upgrade a skill"
OBJ_DESTROYER = ("Defeat the Destroyer using <font color='#00FF00'>Basic Attacks (Right-click)</font> "
                 "and <font color='#66FFFF'>Skills</font>")                       # 03fbf934
OBJ_VICTORY = "<font color='#FFFF00'>VICTORY</font>"

CONV_SECONDS = {0x1C5: 16.0, 0x1C1: 3.0, 0x1C0: 2.0, 0x1B4: 1.5, 0x1D7: 1.8, 0x1C7: 3.2, 0x195: 1.8}


def bridge_mod():
    from . import bridge
    return bridge


class Finale:
    def __init__(self, tut):
        self.t = tut
        self.m = tut.match
        self.stage = None
        self.car = None                  # the entity Batman carries / will carry
        self.carrying = False
        self.flying = False              # a thrown car in the air
        self.last_carry = 0.0
        self.flags = set()

    # ---- helpers -------------------------------------------------------------------
    @property
    def b(self):
        return self.t.bridge

    @property
    def tc(self):
        return self.m.cfg["tutorial"]

    def pos(self, name):
        raw = (self.tc.get("finale_positions") or {}).get(name)
        if raw:
            return (float(raw[0]), float(raw[1]), float(raw[2]) if len(raw) > 2 else Z)
        return POSITIONS[name]

    def _stage(self, name):
        self.stage = name
        self.t.log(f"tutorial (finale): {name}")

    def objective(self, text):
        return self.t._objective(text)

    def _car_named(self, name):
        return next((e for e in self.m.entities.values()
                     if e.name == name and not getattr(e, "removed", False)), None)

    def _marker(self, name, xyz):
        step = MARKER_STEP[name]
        self.t.step = step
        self.t.targets[step] = tuple(xyz)
        ping = self.t.ping(step, time.time())
        self.t.log(f"tutorial: marker '{name}' at ({xyz[0]:.1f}, {xyz[1]:.1f})")
        return [(f"guide ping '{name}'", ping)] if ping else []

    def _unmark(self, name):
        return self.t.remove_ping(MARKER_STEP[name])

    # ---- the start -------------------------------------------------------------------
    def start(self, now):
        """The camera is locked on Batman again: another car blocks the way."""
        if self.stage:
            return []
        for key, sec in CONV_SECONDS.items():
            from . import tutorial1
            tutorial1.CONV_SECONDS.setdefault(key, sec)
        self._stage("car_intro")
        self.car = self._car_named("BridgeVehicle")
        if self.car is None:
            # 2026-10-17 21:53 (tester: the second car forward again): with start_at the car was made here
            # with the model-origin and back offsets, while the bridge's own _lets_go puts it at its raw spot
            # (the one the tester approved in fase3-fq): the same raw spot and yaw now
            self.car = self._spawn_car("BridgeVehicle", self.b.pos("vehicle"), None,
                                       yaw=float(self.tc.get("bridge_vehicle_yaw", bridge_mod().VEHICLE_YAW)),
                                       raw=True)[1]
        msgs = self.t.say(0x1C5) + self.objective(OBJ_WAIT)
        self.t.schedule(0.5, self.t_after(self._strength, 0.3))
        return msgs

    def t_after(self, fn, margin=0.3):
        return lambda: self.t.after_speech(margin * float(self.tc.get("pacing", 1.0)), fn)

    def _spawn_car(self, name, xyz, wstate, yaw=None, box=None, raw=False):
        from . import bridge, tutorial1
        m = self.m
        ws = int(wstate or self.tc.get("bridge_vehicle_wstate", bridge.VEHICLE_WS) or bridge.VEHICLE_WS)
        yaw = bridge.VEHICLE_YAW if yaw is None else yaw
        tutorial1.EXTRA_SPAWNS[name] = (ws, tuple(xyz), yaw)
        before = set(m.entities)
        # the model's origin is not its middle: spawn it so it LOOKS centred on xyz
        ou, ow = self._model_origin(ws)
        c, s_ = math.cos(yaw), math.sin(yaw)
        # 21:40: both cars a little towards their rear (the model's front is at
        # its yaw - pi: the rear along +yaw). [tutorial] car_back_shift m
        back = float(self.tc.get("car_back_shift", -0.8))
        # 08:02 (tester): the second car (the bridge's) 0.8 m further to its rear.
        # 2026-10-16 14:02 (tester): +1.6 moved it FORWARD; -1.6 (fase3-fn) moved it
        # towards the side of the bridge: this offset runs along the car's long
        # axis, which on the bridge lies ACROSS the road. 14:41 (tester's answer):
        # back to the original spot, no extra offset. {"BridgeVehicle": metres}
        # in config.toml moves it again (+ = one side of the road, - = the other).
        back += float((self.tc.get("car_extra_back_shift") or {}).get(name, 0.0))
        if raw:
            back, ou, ow = 0.0, 0.0, 0.0
        xyz = (xyz[0] + back * c, xyz[1] + back * s_, xyz[2])
        shown = (xyz[0] + ou * c - ow * s_, xyz[1] + ou * s_ + ow * c, xyz[2])
        msgs = m.spawn(name, time.time(), attackable=False, xyz=shown)
        new = [m.entities[e] for e in m.entities if e not in before]
        car = new[0] if new else None
        hl, hw = box or m.cfg["combat"].get("vehicle_box", [4.0, 1.6])
        m.mover.obstacles[name] = (xyz[0], xyz[1], float(hl), float(hw), yaw)
        if car is not None:
            car.ws = ws
            self.t.resend(car)
            init = [int(k) for k in self.tc.get("car_init_keys", list(CAR_INIT_KEYS)) or []]
            if init:
                self.t.schedule(0.5, lambda: (self.t.run_scripts(car.eid, tuple(init), f"{name} init (Vfx_OnInit)"),
                                              [])[1])
        return msgs, car

    def _model_origin(self, ws):
        custom = self.tc.get("car_model_origin")
        if custom:
            return float(custom[0]), float(custom[1])
        return MODEL_ORIGIN.get(ws, (0.0, 0.0))

    def _strength(self):
        """'Protector, use Super Strength to clear the way.': F."""
        self._stage("strength")
        msgs = self.t.say(0x1C1) + self.give_super_strength()
        if self.car is not None:
            msgs += self._marker("car_a", self.car.pos)
        return msgs + self.objective(OBJ_STRENGTH)

    def give_super_strength(self):
        from . import skilldata
        m = self.m
        if self.tc.get("stolen_power_property", "auto"):
            table = skilldata.slot_table(m.cfg, SLOT_F, stolenpowers.resolve(self.tc.get("strength_skill"), skilldata.SUPER_STRENGTH_VERSION))
            if table:
                m.stolen_powers[SLOT_F] = table
        m.hud_refresh += 1
        m.sequence += 1
        self.t.log("tutorial: Stolen Power (Super Strength) on F"
                   + (" (skill collection 0x100008F1 sent)" if SLOT_F in m.stolen_powers else ""))
        return [("Stolen Power: Super Strength on F", m.champion_bundle(time.time())),
                ("HUD element 23 (F button) restored (0x213d)", M.hud_element(HUD_SKILL_BUTTON_F, 1)),
                ("highlight the F button (0x213d)", M.hud_element(HUD_SKILL_BUTTON_F, 7))]

    def _f_skill(self, throw):
        """Slot 8 (F): Super Strength, or while carrying its throw skill
        0x480003C9 (2026-10-16, base power 0x480003CB's linked skills
        0x10000855): ground target, 9 m range (stat 0x17), its ground markers
        0x100006D7 / 0x100006D8, so F shows the range ring and F + click
        throws. The version's name and icon are kept ([tutorial] throw_skill)."""
        from . import skilldata
        m = self.m
        base = skilldata.slot_table(m.cfg, SLOT_F, stolenpowers.resolve(self.tc.get("strength_skill"),
                                                                         skilldata.SUPER_STRENGTH_VERSION))
        table = base
        if throw:
            t = skilldata.slot_table(m.cfg, SLOT_F, int(self.tc.get("throw_skill", THROW_SKILL) or 0))
            if t and base:
                keep = {k: (k, kind, v) for k, kind, v in base if k in (0x100001C0, 0x10000302)}
                table = [keep.get(k, (k, kind, v)) for k, kind, v in t]
                # 22:51: the throw record has no targeting type of its own: the lift's (ground) is added
                if not any(k == skilldata.TARGETING_PROPERTY for k, _, _ in table):
                    table += [e for e in base if e[0] == skilldata.TARGETING_PROPERTY]
            elif t:
                table = t
        if not table:
            return []
        m.stolen_powers[SLOT_F] = table
        m.hud_refresh += 1
        m.sequence += 1
        return [(f"F: {'throw (0x480003C9)' if throw else 'Super Strength'} skill", m.champion_bundle(time.time()))]

    # ---- Super Strength: lift and throw -----------------------------------------------
    def can_lift(self):
        return self.stage in ("strength", "car_b_ready") and self.car is not None and not self.carrying

    def lift(self, how, xyz=None):
        """F (or an Alt+click on the car / walking into it): Batman lifts the car."""
        m = self.m
        if not self.can_lift():
            return []
        if xyz is not None and math.hypot(xyz[0] - self.car.pos[0], xyz[1] - self.car.pos[1]) > 4.0:
            near = m.mover.distance_to(self.car.pos) <= float(self.tc.get("f_lift_near", 6.0))
            if not (how == "F" and near):
                # (F with the cursor off the car still lifts it when Batman is next to it)
                self.t.log(f"Super Strength ({how}): not on the car")
                return []
        d = m.mover.distance_to(self.car.pos)
        if d > float(self.tc.get("lift_range", 4.5)):
            # walk up to it first, then lift
            self.flags.add("walk_to_car")
            bx, by, _ = m.mover.pos
            k = (d - 2.5) / d
            m.mover.target = [bx + (self.car.pos[0] - bx) * k, by + (self.car.pos[1] - by) * k, m.mover.pos[2]]
            self.t.log(f"Super Strength ({how}): Batman walks to the car ({d:.1f} m)")
            return []
        self.flags.discard("walk_to_car")
        self.carrying = True
        # 2026-10-16: with the car overhead Batman walked at full speed while the
        # hands-up walk animation is slower: he slid. [tutorial] carry_move_speed
        m.mover.move_speed = float(self.tc.get("carry_move_speed", 3.0) or m.cfg["timing"]["move_speed"])
        m.mover.obstacles.pop(self.car.name, None)
        m.combat.stop()
        # he stops and faces the car (the scriptlets come after this bundle:
        # [scripts] champion_defer)
        bx, by, _ = m.mover.pos
        m.mover.target, m.mover.speed = None, 0.0
        m.mover.heading = math.atan2(self.car.pos[1] - by, self.car.pos[0] - bx)
        m.sequence += 1
        # 17:36 (his animation graph): SuperStrength_InitObjectPickup (bend down
        # and grab: Pickup_Start holds that pose), then SuperStrength_PickupObject
        # (the lift; then the hands-up Hold state, whose walk needs nothing more).
        # The car stays where it is until the lift, then goes straight up: it
        # used to slide into Batman at ground height first (he sank "under the
        # map"). [tutorial] lift_keys, lift_step, lift_attach
        car_var = [(M.PROP_SCRIPT_TARGET, KIND_IID, self.car.eid)]
        keys = [int(k) for k in self.tc.get("lift_keys") or LIFT_KEYS]
        step = float(self.tc.get("lift_step", 0.5))
        car = self.car

        def lift_key(key):
            if self.carrying and self.car is car:          # not when already thrown
                self.t.run_scripts(M.CHAMPION_AGENT_ID, (key,), f"Batman lifts the car ({key:#x})",
                                   car_var, car.eid)
            return []
        for i, key in enumerate(keys):
            self.t.schedule(0.05 + step * i, lambda key=key: lift_key(key))
        lifted = 0.05 + step * max(0, len(keys) - 1)
        events = [int(e) for e in self.tc.get("lift_events", [EV_CAR_PICKUP]) or []]
        if events:
            self.t.schedule(lifted + 0.05, lambda: self._raise_events(events, "Batman lifts the car", car))
        # 19:21: he could walk off during the pickup and the car followed late:
        # he stays put until the car is overhead ([tutorial] lift_lock)
        lock = float(self.tc.get("lift_lock", lifted + 0.8))
        if lock > 0 and hasattr(self.t, "lock"):
            self.t.locked_until = max(self.t.locked_until, time.time() + lock)
            self.t.lock_reason = "lifting the car"
            self.t.lock_logged = False
        self.lift_started = time.time() + lifted + float(self.tc.get("lift_attach", 0.1))
        self.t.schedule(self.lift_started - time.time() + 0.02, lambda: self._carry(time.time(), force=True))
        if self.tc.get("throw_skill", THROW_SKILL):
            self.t.schedule(self.lift_started - time.time() + 0.05, lambda: self._f_skill(True))
            # 2026-10-17 21:28 (tester's pictures of the original): with the car overhead the big yellow
            # range ring and the small ring at the cursor are already on screen, and a left click throws.
            # Those rings are the throw skill's own aim (F). The server presses F for the player once the
            # throw skill is on F, when the game window is in front ([tutorial] throw_auto_aim, s after it).
            aim = float(self.tc.get("throw_auto_aim", 0.4) or 0)
            if aim > 0:
                self.t.schedule(self.lift_started - time.time() + 0.05 + aim, lambda: self._auto_aim(car))
        hold = [int(k) for k in (self.tc.get("carry_keys") or CARRY_KEYS)]
        if hold:
            self.t.schedule(lifted + float(self.tc.get("pickup_seconds", 0.8)), lambda: (self.t.run_scripts(
                M.CHAMPION_AGENT_ID, tuple(hold), "Batman holds the car", car_var,
                self.car.eid if self.car else 0), [])[1])
        self.t.log(f"tutorial: Batman lifts {self.car.name} ({how})")
        first = self.stage == "strength"
        msgs = [("Batman stops at the car", m.champion_bundle(time.time()))]
        msgs += self._unmark("car_a" if first else "car_b")
        msgs.append((f"tutorial hint {HINT_SUPER_STRENGTH}", M.tutorial_hint(HINT_SUPER_STRENGTH)))
        if first:
            self._stage("carrying")
            msgs += self.t.say(0x1C0) + self._strength_drones()
            self.t.schedule(0.5, self.t_after(lambda: self.t.say(0x1B4) + self.objective(OBJ_THROW), 0.2))
        else:
            self._stage("carrying2")
            msgs += self.objective(OBJ_THROW)
        return msgs

    def _auto_aim(self, car):
        """Press F in the game (winctl) so the throw's aim rings show while the car is overhead."""
        from . import winctl
        if not (self.carrying and self.car is car):
            return []
        emotes = getattr(getattr(self.m.session, "server", None), "emotes", None)
        if emotes is not None:
            in_front = emotes._game_in_front()
        else:
            exe = self.m.cfg["game"].get("patched_exe", "")
            in_front = bool(exe) and winctl.foreground_pid() in set(winctl.pids_of(exe))
        if in_front and winctl.press_key(int(self.tc.get("throw_aim_key", 0x46))):
            self.t.log("tutorial: the throw's aim shown (F pressed for the player)")
        else:
            self.t.log("tutorial: throw aim not pressed (game window not in front / not Windows)")
        return []

    def _raise_events(self, events, what, car=None):
        """Graph events on Batman through _HFSM_BehaviorRaiseEventAction."""
        if car is not None and not (self.carrying and self.car is car):
            return []
        kind = int(self.tc.get("raise_event_kind", KIND_ENUM))
        for ev in events:
            self.t.run_scripts(M.CHAMPION_AGENT_ID, (RAISE_EVENT_KEY,), f"{what}: graph event {ev:#x}",
                               [(RAISE_EVENT_VAR, kind, ev)])
        return []

    def _back_to_locomotion(self, delay):
        keys = [int(k) for k in self.tc.get("locomotion_keys") or LOCOMOTION_KEYS]
        if keys:
            self.t.schedule(delay, lambda: (self.t.run_scripts(M.CHAMPION_AGENT_ID, keys,
                                                               "Batman back to walking"), [])[1])
        events = [int(e) for e in self.tc.get("throw_end_events", []) or []]
        if events:
            self.t.schedule(delay, lambda: self._raise_events(events, "Batman back to walking"))

    def _carry(self, now, force=False):
        """The car above Batman's head, following him (from the moment he
        lifts it; before that it stays where it stood)."""
        m = self.m
        if not (self.carrying and self.car):
            return []
        if now < getattr(self, "lift_started", 0.0):
            return []
        bx, by, bz = m.mover.pos
        # its middle (not its origin) over his head; its long axis across his
        # shoulders, as he faces
        heading = m.mover.heading
        line = heading + float(self.tc.get("carry_yaw", math.pi / 2))
        car_yaw = line + float(self.tc.get("carry_model_yaw", -math.pi / 2))
        # 12:18 (tester): the car hung to one side of Batman and above his hands.
        # The model's middle is 0.68 m from its origin along the car's own yaw
        # (skeleton 0x2D000238, both wagons): the offset now follows the car's
        # yaw (it went along the carry line) for both cars ([tutorial]
        # carry_origin = [along, across]); lower, on his hands (carry_height)
        ou, ow = [float(v) for v in (self.tc.get("carry_origin") or CARRY_ORIGIN)]
        c, s_ = math.cos(car_yaw), math.sin(car_yaw)
        xyz = (bx + ou * c - ow * s_, by + ou * s_ + ow * c, bz + float(self.tc.get("carry_height", 2.1)))
        # 20:22: with speed 0 (only put where Batman was, 4 times a second) the
        # car trailed behind him while he walked. It now moves as he does: his
        # speed along his heading (its own heading is his), sent with each of
        # his movement updates, and speed 0 the moment he stops (16:14: without
        # that stop update it ran on ahead). [tutorial] carry_follow_speed
        speed = float(m.mover.speed) if self.tc.get("carry_follow_speed", True) else 0.0
        moved = math.hypot(xyz[0] - self.car.pos[0], xyz[1] - self.car.pos[1]) > 0.05 or \
            abs(xyz[2] - self.car.pos[2]) > 0.05 or abs(speed - getattr(self.car, "speed", 0.0)) > 0.01
        if not (force or moved or now - self.last_carry > 1.0):
            return []
        self.last_carry = now
        self.car.pos = list(xyz)
        self.car.heading = car_yaw
        self.car.speed = speed
        return [(f"{self.car.name} carried", m.entity_bundle(self.car, now))]

    def carry_tick(self, now):
        """With each of Batman's movement updates (session)."""
        return self._carry(now)

    def throw(self, xyz, how):
        """Right-click (or F / an attack order) while carrying: the car flies to
        xyz (at most throw_range m away), explodes and destroys the drones there."""
        m = self.m
        if not self.carrying or self.car is None:
            return []
        bx, by, bz = m.mover.pos
        if xyz is None:
            xyz = (bx + math.cos(m.mover.heading) * 6, by + math.sin(m.mover.heading) * 6, bz)
        dx, dy = xyz[0] - bx, xyz[1] - by
        dist = math.hypot(dx, dy) or 1e-6
        rng = float(self.tc.get("throw_range", 14.0))
        if dist > rng:
            xyz = (bx + dx / dist * rng, by + dy / dist * rng, xyz[2])
            dist = rng
        # 2026-10-17 22:51 (tester: the throw looked odd; server.log 22:48:33: an attack order on a drone
        # 0.3 m away threw the car at Batman's feet): at least throw_min_distance m along that direction
        low = float(self.tc.get("throw_min_distance", 0.0) or 0.0)
        if 0 < dist < low:
            if dist < 0.05:
                dx, dy, dist = math.cos(m.mover.heading), math.sin(m.mover.heading), 1.0
            xyz = (bx + dx / dist * low, by + dy / dist * low, xyz[2])
            dx, dy, dist = xyz[0] - bx, xyz[1] - by, low
        self.carrying = False
        m.mover.move_speed = float(m.cfg["timing"]["move_speed"])
        self.flying = True
        if self.tc.get("throw_skill", THROW_SKILL):
            self.t.schedule(float(self.tc.get("throw_seconds", 0.9)), lambda: self._f_skill(False))
        car = self.car
        m.mover.target = None
        m.mover.speed = 0.0
        m.combat.stop()
        m.mover.heading = math.atan2(dy, dx)
        # 2026-10-16: he kept walking during the throw (a move / attack order
        # right after it): he stays put for the whole throw ([tutorial] throw_lock)
        lock = float(self.tc.get("throw_lock", self.tc.get("throw_seconds", 0.9)) or 0)
        if lock > 0:
            self.t.locked_until = max(self.t.locked_until, time.time() + lock)
            self.t.lock_reason = "throwing the car"
            self.t.lock_logged = False
        m.sequence += 1
        keys = [int(k) for k in self.tc.get("throw_keys") or THROW_KEYS]
        if keys:
            self.t.run_scripts(M.CHAMPION_AGENT_ID, keys, "Batman throws the car (SuperStrength_ThrowObject)",
                               [(M.PROP_SCRIPT_TARGET, KIND_IID, car.eid)], car.eid)
        self.t.log(f"tutorial: Batman throws {car.name} at ({xyz[0]:.1f}, {xyz[1]:.1f}) ({how})")
        self._back_to_locomotion(float(self.tc.get("throw_seconds", 0.9)))
        flight = max(0.3, dist / float(self.tc.get("throw_speed", 16.0)))
        # 2026-10-16 15:14 (tester): the flight "looks a bit odd": 10 jumps and a
        # half turn around the vertical axis (the car spun like a top). Smoother
        # (20 steps) and no spin by default ([tutorial] throw_steps, throw_spin)
        steps = int(self.tc.get("throw_steps", 20))
        windup = float(self.tc.get("throw_windup", 0.2))      # the car leaves his hands 0.20 s into the throw
        sx, sy, sz = car.pos
        # 12:18 (tester): the car flew in a straight line. A higher arc
        # ([tutorial] throw_arc m) and a tumble ([tutorial] throw_spin turns)
        arc = float(self.tc.get("throw_arc", 4.0))
        spin = float(self.tc.get("throw_spin", 0.0)) * 2 * math.pi
        yaw0 = car.heading
        for i in range(1, steps + 1):
            f = i / steps
            p = (sx + (xyz[0] - sx) * f, sy + (xyz[1] - sy) * f,
                 sz + (Z - sz) * f + arc * math.sin(math.pi * f))

            # 2026-10-17 15:26 (tester's video: the car shoots off in a straight line until it hits
            # something): a carrier follows its heading at the sent speed and ignores a speed-0 update,
            # so the car flew on along its own yaw. It now faces the throw (throw_face_target) and the
            # last update is a crawl (throw_end_speed, 0.01 m/s) instead of 0.
            face = math.atan2(xyz[1] - sy, xyz[0] - sx) if self.tc.get("throw_face_target", True) else yaw0

            def fly(p=p, last=(i == steps), yaw=face + spin * f):
                end = float(self.tc.get("throw_end_speed", 0.01))
                return self.m.move_entity(car, p, time.time(), speed=end if last else dist / flight, heading=yaw)

            # 2026-10-17 15:44 (tester's video: still a straight line): a carrier keeps the height it
            # was created at, so moving updates cannot make an arc. "respawn": the car is removed as it
            # leaves Batman's hands, a copy is created at each point of the arc (the one before removed in
            # the same tick) and the car itself is created again where it lands (throw_mode)
            def hop(p=p, first=(i == 1), last=(i == steps), yaw=face + spin * f):
                from .world import Entity
                now = time.time()
                out = []
                prev = getattr(self, "flight_copy", None)
                if last:
                    car.pos, car.heading, car.speed, car.sequence = list(p), yaw, 0.0, 0
                    out.append((f"{car.name} lands", self.m.entity_bundle(car, now)))
                    self.flight_copy = None
                else:
                    cid = self.m._next_eid
                    self.m._next_eid += 1
                    copy = Entity(cid, f"{car.name} (flight)", car.class_id, p, 0.0, car.team)
                    copy.heading = yaw
                    copy.extra_props = list(getattr(car, "extra_props", []))
                    out.append((f"{car.name} in flight", self.m.entity_bundle(copy, now)))
                    self.flight_copy = cid
                if first:
                    out.append((f"{car.name} leaves his hands (0x3)", M.remove_object(car.eid)))
                if prev:
                    out.append((f"{car.name} flight step goes (0x3)", M.remove_object(prev)))
                return out
            self.t.schedule(windup + flight * f, hop if self.tc.get("throw_mode", "respawn") == "respawn" else fly)
        thrown = [int(k) for k in self.tc.get("car_thrown_keys", list(CAR_THROWN_KEYS)) or []]
        if thrown:
            self.t.schedule(windup + 0.3, lambda: (self.t.run_scripts(car.eid, tuple(thrown),
                                                                      f"{car.name} thrown (Vfx_OnThrown)"), [])[1])
        self.t.schedule(windup + flight + 0.05, lambda: self._explode(car, (xyz[0], xyz[1], Z)))
        return [("Batman throws", m.champion_bundle(time.time()))]

    def _explode(self, car, xyz):
        from . import tutorial1
        m = self.m
        self.flying = False
        radius = float(self.tc.get("blast_radius", 4.5))
        damage = int(self.tc.get("blast_damage", 2000))
        hit = [e for e in m.entities.values() if e.alive and e.attackable and getattr(e, "kind", None) != "boss"
               and e.distance_to(xyz[:2]) <= radius]
        self.t.log(f"tutorial: the car explodes at ({xyz[0]:.1f}, {xyz[1]:.1f}): "
                   + (", ".join(e.name for e in hit) or "nothing hit"))
        out = []
        ws = int(self.tc.get("blast_wstate", tutorial1.METEOR_DUST_CLASS) or 0)
        if ws:
            eid, msg = self.t._prop_object(ws, xyz, time.time(), int(self.tc.get("blast_carrier_slot", 0)),
                                           float(self.tc.get("blast_scale", 0.5)), "blast")
            out.append(msg)
            self.t.schedule(0.3, lambda: (self.t.run_scripts(eid, tutorial1.METEOR_PROBE_KEYS, "blast"), [])[1])
            self.t.schedule(float(self.tc.get("blast_lifetime", 3.0)),
                            lambda: [("blast removed (0x3)", M.remove_object(eid))])
        # 13:13: the vehicle takes no scriptlets; in the client's property
        # descriptors Destructible_AdvanceState (0x10000063) is an INT property,
        # so the wrecked state is tried as a property of the car itself: one
        # step, then the next, then the wreck goes ([tutorial] car_break_property)
        prop = int(self.tc.get("car_break_property", 0x10000063) or 0)
        car.pos = [xyz[0], xyz[1], Z]
        car.speed = 0.0
        if self.car is car:
            self.car = None
        if prop:
            base = [p for p in getattr(car, "extra_props", []) if p[0] != prop]
            for step in (1, 2):
                def advance(step=step):
                    if getattr(car, "removed", False):
                        return []
                    car.extra_props = base + [(prop, KIND_INT, step)]
                    return [(f"{car.name} breaks: property {prop:#x} = {step}", m.entity_bundle(car, time.time()))]
                if step == 1:
                    out += advance()
                else:
                    self.t.schedule(0.3, advance)
        states = [int(v) for v in (self.tc.get("car_crash_states", CAR_CRASH_STATES) or [])]
        step_s = float(self.tc.get("car_crash_step", 1.0))
        for i, value in enumerate(states):
            def crash(value=value):
                if getattr(car, "removed", False):
                    return []
                car.extra_props = [p for p in getattr(car, "extra_props", []) if p[0] != CAR_BEHAVIOR_PROPERTY] \
                    + [(CAR_BEHAVIOR_PROPERTY, KIND_ENUM, value)]
                return [(f"{car.name} behavior: property {CAR_BEHAVIOR_PROPERTY:#x} = {value:#x}",
                         m.entity_bundle(car, time.time()))]
            if i == 0:
                out += crash()
            else:
                self.t.schedule(step_s * i, crash)
        # 2026-10-16 (the thrown object's own script 0x34000167): on collision the
        # original runs Vfx_OnCollision on the object, then Vfx_OnExplode; the fire
        # and debris belong to the collision step ([tutorial] car_collision_keys,
        # car_explode_delay)
        coll = [int(k) for k in self.tc.get("car_collision_keys", list(CAR_COLLISION_KEYS)) or []]
        if coll:
            self.t.run_scripts(car.eid, tuple(coll), f"{car.name} collides (Vfx_OnCollision)")
        keys = [int(k) for k in (self.tc.get("car_explode_keys") or CAR_EXPLODE_KEYS)]
        if keys:
            delay = float(self.tc.get("car_explode_delay", 0.2))
            if coll and delay > 0:
                self.t.schedule(delay, lambda: (self.t.run_scripts(car.eid, tuple(keys), f"{car.name} explodes"),
                                                [])[1])
            else:
                self.t.run_scripts(car.eid, tuple(keys), f"{car.name} explodes")
        def gone():
            car.removed = True
            m.entities.pop(car.eid, None)
            return [(f"{car.name} wreck removed (0x3)", M.remove_object(car.eid))]
        self.t.schedule(float(self.tc.get("wreck_seconds", 4.0)), gone)
        blast = [int(k) for k in self.tc.get("blast_keys") or BLAST_KEYS]
        for e in hit:
            # the explosion on each drone it catches (Vfx_Stp_Detonate_Matter_Explosion_Hit)
            self.t.run_scripts(e.eid, tuple(blast) + tuple(batman.HIT_KEYS), f"the blast hits {e.name}",
                               [(M.PROP_SCRIPT_TARGET, KIND_IID, M.CHAMPION_AGENT_ID)])
            out += self.t.attacked(e, time.time())
            self.t.damage(e, damage)
        return out

    # ---- the drones ----------------------------------------------------------------------
    def _strength_drones(self):
        return self.b.spawn_group("finale_strength", [("FinaleMelee1", "melee", self.pos("strength_melee1")),
                                                      ("FinaleMelee2", "melee", self.pos("strength_melee2")),
                                                      ("FinaleRanged", "ranged", self.pos("strength_ranged"))])

    def killed(self, ent, now):
        group = getattr(ent, "group", None)
        if group == "finale_destroyer":
            return self._destroyer_down()
        left = self.b.group_left(group)
        msgs = self.b._drones_objective(group) if group == "finale_strength" else []
        if left:
            return msgs
        self.t.log(f"tutorial: the {group} drones are defeated")
        if group == "finale_strength":
            return msgs + self._destroyer_cinematic()
        if group == "finale_car_b":
            return msgs + self._car_b_cleared()
        if group == "finale_ahead":
            return msgs + self._to_destroyer()
        return msgs

    # ---- the Destroyer ---------------------------------------------------------------------
    def _destroyer_cinematic(self):
        self._stage("destroyer_cinematic")
        if self.carrying and self.car:
            # still carrying (the drones were beaten by hand): put the car down
            self.carrying = False
            m = self.m
            m.mover.move_speed = float(m.cfg["timing"]["move_speed"])
            self.car.removed = True
            m.entities.pop(self.car.eid, None)
            out = [("car put away (0x3)", M.remove_object(self.car.eid))]
            self.car = None
        else:
            out = []
        # 12:32: the cinematic alone shows the drones walking out and the
        # Destroyer standing: the sphere (the PowerCore) falling is the server's
        cin = int(self.tc.get("destroyer_cinematic", DESTROYER_CINEMATIC) or 0)
        in_cin = bool(cin and self.tc.get("sphere_in_cinematic", True))
        if not in_cin:
            out += self._sphere()
        if self.tc.get("destroyer_in_cinematic", True):
            out += self._spawn_destroyer()
        if not cin:
            return out + self._after_destroyer_cinematic()
        if in_cin:
            # 2026-10-17 12:32 (tester's video of the original + diag): the sphere falls INSIDE the
            # cinematic (1 s in), lands with a dust ring and opens at ~frame 115. Our client's
            # cinematic does not draw it, so the server drops the PowerCore during the cinematic and
            # runs its own key 0x100003A6 (in its allowed table, diag 12:30:21; the same key the
            # cinematic gives its Destroyer actor at frame 115) at that frame (sphere_cinematic_keys)
            delay = float(self.tc.get("sphere_cinematic_delay", 0.5)) * float(self.tc.get("pacing", 1.0))
            self.t.schedule(delay + float(self.tc.get("sphere_cinematic_start", 0.5)), self._sphere)
            # 13:28: graph events on the sphere (scriptlet 0x100001E3 + variable 0x780 = event id):
            # Spawn 0x10000154, Activate 0x100001C1, OpenIdle 0x100004A5, ClosedIdle 0x100004A6
            for at, ev in self.tc.get("sphere_cinematic_events", SPHERE_CINEMATIC_EVENTS) or []:
                def sphere_event(ev=int(ev), at=float(at)):
                    sid = getattr(self, "sphere_id", None)
                    if sid:
                        self.t.run_scripts(sid, (RAISE_EVENT_KEY,), f"the sphere at {at:g} s: graph event {ev:#x}",
                                           [(RAISE_EVENT_VAR, KIND_ENUM, ev)])
                    return []
                self.t.schedule(delay + float(at), sphere_event)
            # 2026-10-17 14:28 (fase3-ho): the sphere's core: the PowerCore with its cinematic template
            if int(self.tc.get("sphere_core_wstate", 0) or 0):
                self.t.schedule(delay + float(self.tc.get("sphere_cinematic_start", 0.5)), self._sphere_core)
                for at, key in self.tc.get("sphere_core_keys") or []:
                    def core_key(key=int(key), at=float(at)):
                        cid = getattr(self, "core_id", None)
                        if cid:
                            self.t.run_scripts(cid, [key], f"the sphere core at {at:g} s into the cinematic")
                        return []
                    self.t.schedule(delay + float(at), core_key)
            for at, key in self.tc.get("sphere_cinematic_keys", SPHERE_CINEMATIC_KEYS) or []:
                def sphere_key(key=int(key), at=float(at)):
                    sid = getattr(self, "sphere_id", None)
                    if sid:
                        self.t.run_scripts(sid, [key], f"the sphere at {at:g} s into the cinematic")
                    return []
                self.t.schedule(delay + float(at), sphere_key)
        else:
            delay = (1.0 + float(self.tc.get("sphere_fall_seconds", 2.0))) * float(self.tc.get("pacing", 1.0))
        self.t.schedule(delay, lambda: [(f"Destroyer cinematic {cin:#x} (0x20f5)", M.cinematic(cin))])
        # 2026-10-17 11:12 (tester: "check the Destroyer's cinematic"): the cinematic record
        # 0x35000028 (pack 0xA0000256) keys its Destroyer actor at frame 115 with 0x100003A6 and
        # at frame 125 with Cinematic_Startup 0x100007EB (and each drone at frame 1 with
        # Cinematic_Hidden 0x100009EB, at 125 with Cinematic_Intro 0x100009EC). The server ran
        # Cinematic_Startup before the cinematic and never 0x100003A6: now both at their frames
        # (30 frames a second) on the spawned Destroyer ([tutorial] destroyer_cinematic_keys)
        for at, key in self.tc.get("destroyer_cinematic_keys", DESTROYER_CINEMATIC_KEYS) or []:
            def frame_key(key=int(key), at=float(at)):
                boss = self._boss()
                if boss is not None and self.stage == "destroyer_cinematic":
                    self.t.run_scripts(boss.eid, [key], f"Destroyer cinematic key at {at:g} s")
                return []
            self.t.schedule(delay + float(at), frame_key)
        auto = float(self.tc.get("cinematic_timeout", 60.0) or 0)
        if auto:
            self.t.schedule(delay + auto, lambda: self._after_destroyer_cinematic()
                            if self.stage == "destroyer_cinematic" else [])
        return out

    def _boss(self):
        return next((e for e in self.m.entities.values() if e.name == "Destroyer"), None)

    def _spawn_destroyer(self):
        """The Destroyer (chr_Min_DDD_Guardian). 14:54 (diag --scripts): its
        scriptlet table has Cinematic_Startup, Cinematic_Hidden and
        CinematicCharacter_State00 / 01: it is spawned before the cinematic so
        the cinematic finds it, with Cinematic_Startup + State00 (the closed
        sphere); State01 when the cinematic ends ([tutorial] destroyer_start_keys,
        destroyer_open_keys)."""
        if self._boss() is not None:
            return []
        b = self.b
        msgs = b.spawn_drone("Destroyer", "destroyer", self.pos("destroyer"), "finale_destroyer",
                             face=self.pos("car_b")[:2], aggressive=False,
                             health=int(self.tc.get("destroyer_health", 3000)))
        boss = self._boss()
        if boss:
            boss.hit_range = float(self.tc.get("destroyer_hit_range", 7.0))   # Batman hits it from afar
            boss.click_radius = 3.5
            boss.kind = "boss"
            if self.tc.get("destroyer_actor_props", True):
                # 11:12: as the cinematic's actor: scale 0.85 (0x6B4), 0x954 = 2, 0x100007A2 = 1 and
                # templates 0x1D000774 + 0x1D000385 (0x1D000385 is shared with the PowerCore and the
                # drop pod: probably the closed sphere), after its own table 0x1D0003BA
                from .wire import KIND_ARRAY
                tables = [int(t) for t in self.tc.get("destroyer_actor_tables", DESTROYER_ACTOR_TABLES) or []]
                boss.actor_props = [(0x6B4, KIND_F32, float(self.tc.get("destroyer_actor_scale", 0.85))),
                                    (0x954, KIND_INT, 2), (0x100007A2, KIND_ENUM, 1)]
                if tables:
                    boss.actor_props.append((0x7D2, KIND_ARRAY, [(0x462, KIND_DID, t) for t in tables]))
            skeys = tuple(int(k) for k in (self.tc.get("destroyer_start_keys") or DESTROYER_START_KEYS))
            self.t.schedule(0.3, lambda: (self.t.run_scripts(boss.eid, skeys, "Destroyer start"), [])[1])
        return msgs

    def _sphere(self):
        """The big sphere (PowerCore, world state 0x2E000AC5; its layout record
        0x1D000789 has it at (152.5, 28.0) dropping from z 215 to 210) falls
        before the last gate and opens; it stays (the Destroyer is still in it)."""
        ws = int(self.tc.get("sphere_wstate", SPHERE_WS) or 0)
        if not ws:
            return []
        # 12:32 (video of the original): the sphere opens around the Destroyer: its spot by default
        x, y, _ = self.pos("destroyer" if self.tc.get("sphere_at", "destroyer") == "destroyer" else "sphere")
        top = float(self.tc.get("sphere_from_height", 15.0))
        fall = float(self.tc.get("sphere_fall_seconds", 2.0))
        slot = int(self.tc.get("sphere_carrier_slot", 0))
        # 13:28 (tester: the PowerCore is "another part", not the sphere): the sphere is the phase
        # pod 0x2E001157, whose graph 0x1A000E0B (pack 0xA0000256) has entrance / raider_open /
        # OpenIdle states; its record names no graph, so sphere_graph is sent as its 0x5B5
        graph = int(self.tc.get("sphere_graph", 0) or 0)
        extra = [(0x5B5, KIND_DID, graph)] if graph else []
        # 15:02 (tester, tour of pack 0xA0000256: model 37 = the closed sphere 0x2E000FC7, 38 = the
        # open one 0x2E00101D): the closed sphere's own templates (0x7D2) go with its graph set
        tables = [int(t) for t in self.tc.get("sphere_templates") or []]
        if tables:
            from .wire import KIND_ARRAY
            extra.append((0x7D2, KIND_ARRAY, [(0x462, KIND_DID, t) for t in tables]))
        eid, msg = self.t._prop_object(ws, (x, y, Z + top), time.time(), slot,
                                       float(self.tc.get("sphere_scale", 1.0)), "sphere", extra=extra,
                                       heading=float(self.tc.get("sphere_yaw", 0.0)),
                                       scripts=bool(self.tc.get("sphere_scripts", False)))
        self.sphere_id = eid
        self.t.log(f"tutorial: the sphere falls at ({x:.1f}, {y:.1f})")
        mode = self.tc.get("sphere_fall_mode", "respawn")
        if top > 0 and mode == "respawn":
            # 2026-10-17 15:44 (tester's video): with moving updates it stayed 12 m up (a carrier keeps
            # the height it was created at; updates move it on the ground plane only) and with the same
            # id a re-creation is ignored (13:21). Each step is a NEW object one step lower; the one
            # above is removed in the same tick (sphere_fall_step s; the last one is the sphere)
            step_s = max(0.05, float(self.tc.get("sphere_fall_step", 0.1)))
            steps = max(1, int(round(fall / step_s)))
            scale = float(self.tc.get("sphere_scale", 1.0))
            yaw = float(self.tc.get("sphere_yaw", 0.0))
            for i in range(1, steps + 1):
                z = Z + top * (1 - (i / steps) ** 2)

                def drop(z=z):
                    old_id = self.sphere_id
                    nid, nmsg = self.t._prop_object(ws, (x, y, z), time.time(), slot, scale, "sphere step",
                                                    extra=extra, heading=yaw, scripts=False)
                    self.sphere_id = nid
                    gone = ("the sphere's previous step goes (0x3)", M.remove_object(old_id))
                    overlap = float(self.tc.get("sphere_step_overlap", 0.0) or 0.0)
                    if overlap > 0:
                        # 21:53: the step above stays while this one fades in
                        self.t.schedule(overlap, lambda: [gone])
                        return [nmsg]
                    return [nmsg, gone]
                self.t.schedule(fall * i / steps, drop)
        elif top > 0 and mode == "move":
            # 2026-10-17 15:26 (tester's video: the sphere appears as if teleported): a carrier prop
            # ignores re-creations (13:21: it stayed in the sky) but follows updates with a speed > 0,
            # so it falls with moving updates at a crawl (sphere_fall_speed, 0.01 m/s: no sideways
            # drift) every sphere_fall_step s and lands with the last one
            from . import tutorial1
            from .world import Entity
            yaw = float(self.tc.get("sphere_yaw", 0.0))
            ent = Entity(eid, "Sphere", tutorial1.prop_class(ws, self.m.cfg, slot), (x, y, Z + top),
                         yaw - math.pi / 2, None)
            ent.heading = yaw
            ent.extra_props = list(extra)
            ent.sequence = 1
            self.sphere_ent = ent
            step_s = max(0.05, float(self.tc.get("sphere_fall_step", 0.1)))
            crawl = float(self.tc.get("sphere_fall_speed", 0.01))
            steps = max(1, int(round(fall / step_s)))
            for i in range(1, steps + 1):
                z = Z + top * (1 - (i / steps) ** 2)
                self.t.schedule(fall * i / steps, lambda z=z: self.m.move_entity(
                    ent, (x, y, z), time.time(), speed=crawl, heading=yaw))
        else:
            steps = 8 if top > 0 else 0
            for i in range(1, steps + 1):
                z = Z + top * (1 - (i / steps) ** 2)
                self.t.schedule(fall * i / steps, lambda z=z: [self.t._prop_object(
                    ws, (x, y, z), time.time(), slot, float(self.tc.get("sphere_scale", 1.0)), "sphere", eid)[1]])
        # 2026-10-17 22:51 (tester: the crater shows before the sphere's impact animation): the dust and
        # the crater ring come sphere_impact_delay s after the sphere appears
        impact = float(self.tc.get("sphere_impact_delay", 0.0) or 0.0)
        open_ws = int(self.tc.get("sphere_open_wstate", 0) or 0)
        open_at = float(self.tc.get("sphere_open_at", 0.0) or 0.0)
        if open_ws and open_at > 0:
            # 15:02: the closed sphere is swapped for the open one (model 38) when it opens
            def open_sphere():
                out = [("the closed sphere goes (0x3)", M.remove_object(self.sphere_id))]
                oeid, omsg = self.t._prop_object(open_ws, (x, y, Z), time.time(), slot, float(self.tc.get(
                    "sphere_scale", 1.0)), "open sphere", scripts=False,
                    heading=float(self.tc.get("sphere_yaw", 0.0)))
                self.open_sphere_id = oeid
                self.t.log(f"tutorial: the sphere opens ({open_ws:#x})")
                return out + [omsg]
            self.t.schedule(open_at, open_sphere)
        keys = [int(k) for k in self.tc.get("sphere_keys") or []]
        if keys:
            self.t.schedule(fall + 0.1, lambda: (self.t.run_scripts(self.sphere_id, keys, "the sphere lands"), [])[1])
        dust = int(self.tc.get("sphere_dust_wstate", 0) or 0)
        if dust:
            # 15:44 (tester: no dust when it lands; video of the original: a dust ring 9:35-9:36.5): the
            # meteors' dust cloud at the landing, with the meteor probe keys, removed after a while
            def put_dust():
                from . import tutorial1
                did, dmsg = self.t._prop_object(dust, (x, y, Z), time.time(), 0,
                                                float(self.tc.get("sphere_dust_scale", 1.5)), "sphere dust")
                self.t.schedule(0.1, lambda: (self.t.run_scripts(did, tutorial1.METEOR_PROBE_KEYS, "sphere dust"), [])[1])
                self.t.schedule(float(self.tc.get("sphere_dust_lifetime", 3.0)),
                                lambda: [("sphere dust removed (0x3)", M.remove_object(did))])
                return [dmsg]
            # 23:09 (tester: no opening animation once the dust and the ring both came at the impact): the dust
            # comes with the sphere again (it hides its fade-in); only the crater ring waits for the impact
            self.t.schedule(fall, put_dust)
        ring = int(self.tc.get("destroyer_ring_wstate", DESTROYER_RING_WS) or 0)
        if ring:
            # 2026-10-17 10:37 (tester, lab "Model 14/16"): the crater ring around the Destroyer
            # is env_pvp_phase_pod 0x2E001157; it appears when the sphere lands and stays
            rx, ry = (self.pos("destroyer")[:2] if self.tc.get("destroyer_ring_at", "destroyer") == "destroyer"
                      else (x, y))
            ox, oy = (float(v) for v in (self.tc.get("destroyer_ring_offset") or [0.0, 0.0]))
            rx, ry = rx + ox, ry + oy

            def put_ring():
                reid, rmsg = self.t._prop_object(ring, (rx, ry, Z), time.time(), 0, float(self.tc.get(
                    "destroyer_ring_scale", 1.0)), "destroyer ring", scripts=bool(self.tc.get(
                        "destroyer_ring_scripts", False)), heading=float(self.tc.get("destroyer_ring_yaw", 0.0)))
                self.ring_id = reid
                self.t.log(f"tutorial: the Destroyer's crater ring {ring:#x} at ({rx:.1f}, {ry:.1f})")
                return [rmsg]
            self.t.schedule(fall + impact, put_ring)
        return [msg]

    def _sphere_core(self):
        """2026-10-17 14:28 (fase3-ho): the sphere itself. Pack 0xA0000256 gives the PowerCore actor
        of cinematic 0x35000025 the template 0x1D00078A (its 0x954) and a template there spawns the
        phase pod (the crater ring) together with explosion pieces on CinematicCharacter_State02 /
        State03. The PowerCore is created with that template (sphere_core_templates, as 0x7D2) and
        its graph set (sphere_core_graph) and gets sphere_core_keys [[s into the cinematic, key]]."""
        from .wire import KIND_ARRAY
        ws = int(self.tc.get("sphere_core_wstate", 0) or 0)
        if not ws:
            return []
        x, y, _ = self.pos("destroyer")
        extra = []
        tables = [int(t) for t in self.tc.get("sphere_core_templates") or []]
        if tables:
            extra.append((0x7D2, KIND_ARRAY, [(0x462, KIND_DID, t) for t in tables]))
        graph = int(self.tc.get("sphere_core_graph", 0) or 0)
        if graph:
            extra.append((0x5B5, KIND_DID, graph))
        eid, msg = self.t._prop_object(ws, (x, y, Z + float(self.tc.get("sphere_core_height", 0.0))),
                                       time.time(), 0, float(self.tc.get("sphere_core_scale", 1.0)),
                                       "sphere core", extra=extra, scripts=False,
                                       heading=float(self.tc.get("sphere_yaw", 0.0)))
        self.core_id = eid
        self.t.log(f"tutorial: the sphere core {ws:#x} at ({x:.1f}, {y:.1f}), templates "
                   f"{' '.join(f'{t:#x}' for t in tables) or '-'}, graph {graph:#x}")
        return [msg]

    def cinematic_done(self, did, now):
        """A cinematic finished on the client (notice state 4). None = not ours."""
        if did == int(self.tc.get("destroyer_cinematic", DESTROYER_CINEMATIC) or 0):
            return self._after_destroyer_cinematic() if self.stage == "destroyer_cinematic" else []
        if did == int(self.tc.get("ending_cinematic", ENDING_CINEMATIC) or 0):
            return self._victory() if self.stage == "ending" else []
        return None

    def _after_destroyer_cinematic(self):
        """The sphere has opened: the Destroyer, a car with two drones hitting it,
        two more drones further on."""
        self._stage("reach")
        b = self.b
        msgs = self.t.say(0x1D7) + self.objective(OBJ_REACH)
        msgs += self._spawn_destroyer()
        boss = self._boss()
        if boss is not None:
            # the cinematic is over: the sphere opens (CinematicCharacter_State01)
            okeys = tuple(int(k) for k in (self.tc.get("destroyer_open_keys") or DESTROYER_OPEN_KEYS))
            self.t.schedule(0.2, lambda: (self.t.run_scripts(boss.eid, okeys, "the Destroyer's sphere opens"), [])[1])
        cmsgs, self.car = self._spawn_car("FinaleCarB", self.pos("car_b"), int(self.tc.get("car_b_wstate", CAR_B_WS)),
                                          float(self.tc.get("car_b_yaw", CAR_B_YAW)),
                                          self.tc.get("car_b_box") or CAR_B_BOX)
        msgs += cmsgs + self._obstacles()
        if self.car is not None and self.tc.get("car_b_behavior_state", 0x10000116):
            # the behavior graph's second car (IdleState02: cin_car_b idle / crash)
            self.car.extra_props = list(getattr(self.car, "extra_props", [])) + [
                (CAR_BEHAVIOR_PROPERTY, KIND_ENUM, int(self.tc.get("car_b_behavior_state", 0x10000116)))]
        msgs += b.spawn_group("finale_car_b", [("FinaleCarMelee", "melee", self.pos("car_b_melee")),
                                               ("FinaleCarRanged", "ranged", self.pos("car_b_ranged"))],
                              aggressive=False, face=self.pos("car_b")[:2])
        b.hit_targets["finale_car_b"] = "FinaleCarB"
        b._start_hitting()
        b.wake_on_attack.add("finale_ahead")
        msgs += b.spawn_group("finale_ahead", [("FinaleAheadMelee", "melee", self.pos("ahead_melee")),
                                               ("FinaleAheadRanged", "ranged", self.pos("ahead_ranged"))],
                              aggressive=False, face=self.pos("car_b")[:2])
        return msgs + self.objective(OBJ_REACH)

    def _obstacles(self):
        """[tutorial] finale_obstacles: scenery around car B the client lets
        Batman walk through (crates, fences), same format as [combat] obstacles:
        ["Name", [[x, y], ...]] (polygon) or ["Name", x, y, half_len, half_width, yaw]."""
        obs = self.m.mover.obstacles
        for ob in self.tc.get("finale_obstacles") or []:
            name, rest = str(ob[0]), ob[1:]
            if len(rest) == 1:
                obs[name] = [(float(x), float(y)) for x, y in rest[0]]
            else:
                obs[name] = tuple(float(v) for v in rest)
            self.t.log(f"tutorial: obstacle {name}")
        return []

    def _car_b_cleared(self):
        """The two drones at the car are down: level 7, a skill point for any
        skill; the car can be lifted."""
        self._stage("car_b_ready")
        msgs = self.b.level_up(7)
        msgs += self.b.prompt_rank((batman.SLOT_Q, batman.SLOT_W, batman.SLOT_E, batman.SLOT_R), 0x195,
                                   objective=OBJ_RANK)
        if self.car is not None:
            msgs += self._marker("car_b", self.car.pos)
        self.t.schedule(4.0, lambda: self.objective(OBJ_STRENGTH) if self.stage == "car_b_ready" else [])
        return msgs

    def _to_destroyer(self):
        self._stage("destroyer")
        boss = next((e for e in self.m.entities.values() if e.name == "Destroyer" and e.alive), None)
        msgs = self.t.say(0x1C7) + self.objective(OBJ_DESTROYER)
        if boss:
            msgs += self._marker("destroyer", boss.pos)
        return msgs

    def _destroyer_down(self):
        self._stage("ending")
        m = self.m
        msgs = self._unmark("destroyer")
        # 17:36: "Defeat the Destroyer..." stayed up: it goes the moment it falls
        # (19:21: the text went but its strip stayed: the objective goes inactive)
        msgs.append(("objective 1 cleared: the Destroyer is down (0x2009)",
                     M.objective_update(M.objective(1, text="", banner="", active=False))))
        cin = int(self.tc.get("ending_cinematic", ENDING_CINEMATIC) or 0)
        if not cin:
            return msgs + self._victory()
        hide = bool(self.tc.get("cinematic_hide_champion", True))

        def start():
            # 17:36: Batman vanished seconds before the cinematic: he is hidden
            # (the cinematic has its own Batman) only as it starts
            out = []
            if hide and self.stage == "ending":
                m.champion_hidden = True
                m.sequence += 1
                out.append(("Batman hidden for the ending", m.champion_bundle(time.time())))
            at = float(self.tc.get("victory_in_cinematic", 18.5))
            if at > 0:
                self.t.schedule(at, lambda: self._victory_banner() if self.stage == "ending" else [])
            # 22:09: when the cinematic itself ended, the camera went back to
            # Batman before the match ended: the match ends just BEFORE its end
            # (the ending cinematic lasts ~23.0 s; [tutorial] match_end_in_cinematic)
            end_at = float(self.tc.get("match_end_in_cinematic", 22.6))
            if end_at > 0:
                self.t.schedule(end_at, lambda: self._victory() if self.stage == "ending" else [])
            return out + [(f"ending cinematic {cin:#x} (0x20f5)", M.cinematic(cin))]
        delay = float(self.tc.get("ending_delay", 1.0)) * float(self.tc.get("pacing", 1.0))
        self.t.schedule(delay, start)
        auto = float(self.tc.get("cinematic_timeout", 60.0) or 0)
        if auto:
            self.t.schedule(delay + auto, lambda: self._victory() if self.stage == "ending" else [])
        return msgs

    def _victory_banner(self):
        """The big boxed VICTORY (+ Batman's Cinematic_Victory). 21:40: it
        belongs INSIDE the ending cinematic, after Superman's last line, over
        the base; [tutorial] victory_in_cinematic s after the cinematic starts."""
        m = self.m
        if getattr(self, "victory_shown", False):
            return []
        self.victory_shown = True
        msgs = []
        # 20:32 (the UI pack 0xA00000D0): ShowAnnouncement's field a is the
        # billboard type: 2 the plain strip, 9 MatchWin / 11 Team1Victory = the
        # big boxed WinLoss billboard; d / e the source / target team
        if self.tc.get("send_match_ended_event", True):
            # 0x2038: the client's UI event MatchEnded (0x12)
            from . import scorecard
            msgs.append((f"match ended (0x2038) room {m.room_id}", scorecard.match_ended(m.room_id)))
        ann = self.tc.get("victory_announcement", ["VICTORY", 9, 0, 0, m.team, m.team, 0])
        if ann:
            fields = list(ann) + ["", 9, 0, 0, m.team, m.team, 0][len(ann):]
            text, a, b_, c, d, e, flag = fields[:7]
            msgs.append((f"announcement '{text}' (notice 0x100002eb, a={int(a)}, b={int(b_):#x}, c={int(c):#x})",
                         M.show_announcement(str(text), int(a), int(b_), int(c), int(d), int(e), int(flag))))
        banner = self.tc.get("victory_banner", "")
        if banner:
            msgs.append(("objective 1: VICTORY banner (0x2009)",
                         M.objective_update(M.objective(1, text="", active=True, banner=banner))))
        if self.tc.get("victory_timeline_banner", False):
            msgs += M.timeline_banner("VICTORY", now=time.time() - getattr(self.t, "started_at", time.time()))
        # 08:02 (tester): no "Victory" voice. 2026-10-16 (static analysis): Flash's
        # billboard plays no sound and no client code plays a victory line; the
        # best candidate is the announcer dialog line CODE_UI_ANC_Congratulations_Victory
        # (0x250) as a conversation (0x2001), sent with the billboard
        # ([tutorial] victory_voice_lines; [] = off)
        for line in [int(v) for v in self.tc.get("victory_voice_lines", [0x250]) or []]:
            msgs.append((f"victory voice: announcer line {line:#x} (0x2001)", M.start_conversation(line)))
        vkeys = tuple(int(k) for k in (self.tc.get("victory_keys") or VICTORY_KEYS))
        if vkeys:
            self.t.run_scripts(M.CHAMPION_AGENT_ID, vkeys, "Batman: Cinematic_Victory")
        self.t.log("tutorial: VICTORY banner")
        return msgs

    def _victory(self):
        """The ending cinematic is over: the match ends (21:40: right away; the
        camera must not come back to Batman first). Without the banner yet
        (no cinematic, or it was cut short), banner first and victory_hold s."""
        m = self.m
        self._stage("victory")
        self.t.phase = "done"
        self.t.log("tutorial: VICTORY -- Tutorial 1 complete")
        m.finished = True                 # the next JoinQueue starts a new match (session)
        shown = getattr(self, "victory_shown", False)
        msgs = [] if shown else self._victory_banner()
        if not self.tc.get("send_match_end", True):
            if m.champion_hidden:
                m.champion_hidden = False
                m.sequence += 1
                msgs.append(("Batman visible again", m.champion_bundle(time.time())))
            return msgs
        hold = float(self.tc.get("victory_end_delay", 0.0) if shown else self.tc.get("victory_hold", 6.0))
        if hold > 0:
            self.t.schedule(hold, lambda: self._match_end())
        else:
            msgs += self._match_end()
        return msgs

    def _match_end(self):
        """The match-ended notice (the client goes home and shows the results),
        with everything the results page needs at the same time."""
        from . import progress
        m = self.m
        secs = time.time() - getattr(self.t, "started_at", time.time())
        team = int(self.tc.get("winning_team", 0) or m.team)
        msgs = [("objective 1 cleared (0x2009)", M.objective_update(M.objective(1, text="", active=False, banner=""))),
                ("objective tracker off (0x2075)", M.objective_tracker_enabled(False))]
        if self.tc.get("replay_post_match_movie", True):
            # the client plays Batman's story only while this preference is not
            # set (it keeps it in UserPreferences.ini): reset it every time
            pref = f"User.HasSeenPostEncounterVideo@{m.encounter:#010x}"
            msgs.append((f"preference {pref} = False (0x216a)", M.server_preferences([(pref, False)])))
        # (Flash: uWinningTeam, uPlayerTeam, fMatchDuration, nTier, fTargetTime)
        msgs.append((f"match ended: team {team} wins (notice 0x1000000e)", M.match_ended(team, secs, b=m.team)))
        done = progress.complete(m.cfg, m.encounter)
        msgs.append((f"completed encounters (0x214b): {', '.join(hex(d) for d in done)}",
                     M.completed_encounters(done, m.encounter)))
        if self.tc.get("send_match_stats", True):
            msgs.append(("end-of-match stats (0x2045)", M.end_of_match_stats(secs)))
        reward = int(self.tc.get("reward_champion", 0x40000086) or 0)
        roster = getattr(self.t, "roster", None)
        tut = {d[1]: n for n, d in __import__("icserver.scorecard", fromlist=["TUTORIALS"]).TUTORIALS.items()}
        if self.tc.get("send_achievements", True) and m.encounter in tut:
            # 21:08 (the achievement records): Tutorial n's training achievement
            # newly complete (0x2120) and its pending reward (0x2125: the reward
            # set's item is the champion -> the "Champion Unlocked" panel, then
            # its showcase movie)
            from . import scorecard
            n = tut[m.encounter]
            msgs.append((f"achievement progress: Tutorial {n} newly complete (0x2120)",
                         scorecard.tutorial_completed(n, int(time.time()))))
            reward = int(self.tc.get("reward_champion", 0x40000086) or 0)
            if reward:
                # 2026-10-15 (static analysis): the client passes a 0x2125 to the UI
                # only once, on arrival; in the world nothing listens and it is lost
                # (a resend with the same instance id is ignored). The end page asks
                # for it: 0x212E -> 0x211F -> 0x2124 -> this 0x2125 (session.py)
                pending = (f"pending reward: {reward:#x} for Tutorial {n} (0x2125)",
                           scorecard.tutorial_reward(n, int(time.time()) & 0x7FFFFFFF, reward))
                sess = getattr(m, "session", None)
                if sess is not None:
                    sess.pending_reward = pending
                if self.tc.get("reward_at_match_end", False) or sess is None:
                    msgs.append(pending)
        if self.tc.get("send_scorecard", True):
            # 20:32: the home page after the movie was empty: it is the
            # scorecard (MISSION COMPLETE for a tutorial), which shows only when
            # it has ALL its data. Sent now and again after the movie.
            from . import scorecard
            bundle = lambda: scorecard.scorecard_bundle(
                str(m.cfg["account"].get("player_name", "Player")),
                account_level=int(m.cfg["account"].get("level", 30)), encounter=m.encounter,
                level=int(getattr(m, "level", 7) or 7))
            msgs += bundle()
            sess = getattr(m, "session", None)
            for delay in self.tc.get("scorecard_resend", [5.0, 25.0, 60.0]) or []:
                if sess is not None:
                    # on the session's clock: the match's ends when the client leaves
                    # not into a new match's load (21:35: the 25 s resend landed in it)
                    sess.later(float(delay), lambda: sess.send_many(bundle())
                               if sess.match is None or sess.match is m else None, sess.group)
                else:
                    self.t.schedule(float(delay), bundle)
        if reward and roster:
            # the home screen's "Champion Unlocked": the champion's item turns
            # owned (0x20B8 again: the client passes only the changed items to
            # its UI) and the ribbon "item fulfilled" (0x2095)
            msgs.append((f"item statuses (0x20b8): {reward:#x} owned", M.item_statuses(roster)))
            ribbon = int(self.tc.get("reward_ribbon_icon", 0) or 0)
            if ribbon:
                # 0x2095 is a small "upgrade unlocked" ribbon (its DID is an icon)
                msgs.append((f"ribbon: icon {ribbon:#x} (0x2095)",
                             M.item_fulfilled(1, ribbon, str(self.tc.get("reward_text", "Gaslight Batman")))))
        exit_delay = float(self.tc.get("exit_lobby_delay", -1))
        if exit_delay >= 0:
            self.t.schedule(exit_delay, lambda: [(f"exit lobby (0x2021) room {m.room_id}",
                                                  M.exit_lobby(m.room_id))])
        self.t.log("tutorial: match ended (notice, completed list, stats)")
        return msgs

    # ---- every tick ---------------------------------------------------------------------------
    def update(self, now):
        if not self.stage:
            return []
        m = self.m
        out = self._carry(now)
        if self.can_lift() and self.car is not None:
            d = m.mover.distance_to(self.car.pos)
            touch = float(self.tc.get("lift_on_touch", 3.0) or 0)
            if SLOT_F in m.stolen_powers and self.tc.get("skill_buttons_only", True):
                touch = 0          # 2026-10-16: with Super Strength on F, only F (or Alt+click) lifts
            if ("walk_to_car" in self.flags and d <= float(self.tc.get("lift_range", 4.5))) or (touch and d <= touch):
                out += self.lift("walked up to it")
        if self.stage == "reach" and "car_b_seen" not in self.flags and self.car is not None:
            d = m.mover.distance_to(self.car.pos)
            if d <= float(self.tc.get("vision_radius", 14.0)):
                self.flags.add("car_b_seen")
                out += self._marker("car_b", self.car.pos)
        return out

    def wants_ping(self, xyz):
        """An Alt+click: lift the car if it is on it."""
        return self.can_lift() and self.car is not None and \
            math.hypot(xyz[0] - self.car.pos[0], xyz[1] - self.car.pos[1]) <= 4.0
