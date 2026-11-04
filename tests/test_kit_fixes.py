"""Kit fixes from the 2026-11-02 game test (python tests/test_kit_fixes.py; no ports).

The real match world as tests/test_meltdown.py runs it (test_match.FakeSession + World + pvp.start_match on a virtual
clock):
- Atomic Joker 0x40000962's R Jack in the Box (0x340004DA) stops after its bursts / MaxDuration ([ics]
  stop_left_subgraphs): the left burst graph kept firing forever;
- his passive The Punch Line (0x340004DE) starts when a direct hit (a turret's World.damage) would kill him ([ics]
  defeat_guard_all_damage);
- Blue Beetle 0x400007FA's E Stick And Move (0x34000455) hops with his back to the dash, fires at the enemy he hops
  away from and keeps that yaw after the landing ([ics] facing_locks).
"""
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from ics import config                                   # noqa: E402
from ics import script_runtime as R                       # noqa: E402
from ics.gamedata import Data                            # noqa: E402
import test_match as T                                   # noqa: E402
import test_meltdown as TM                               # noqa: E402

ENCOUNTER = 0x40000C82                                   # Crime Alley
ATOMIC_JOKER, BLUE_BEETLE, AWW = 0x40000962, 0x400007FA, 0x400003EC
STEP = 0.05
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


def world_with(cfg, data, variant, bot_dx=3.0):
    """A match world with the champion at its start and a still enemy bot bot_dx m east of it."""
    logs = []
    s = T.FakeSession()
    TM._clock["s"] = s
    spawn = T.pvp.spawn_point(ENCOUNTER, 1)
    w = T.World(data, cfg, ENCOUNTER, spawn, send=s.send, schedule=s.schedule, log=logs.append)
    nav = T.pvp.navgrid(data, ENCOUNTER, spawn[1:3])
    w.nav = nav.copy() if nav else None
    w.ground_z = spawn[6]
    ch = w.create_champion(variant, spawn)
    w.in_world = True
    m = T.pvp.start_match(w, s, ENCOUNTER)
    T.run(s, m, 3.0)
    ch.level = 6
    for sl in range(0, 5):
        if sl in ch.kit:
            ch.ranks[sl] = max(1, ch.ranks.get(sl, 0))
    w.recompute_stats(ch, refill=True)
    bot = w.create_bot_champion(AWW, 2 if ch.team != 2 else 1, "enemy bot", 0,
                                pos=[ch.pos[0] + bot_dx, ch.pos[1], ch.pos[2]])
    bot.move_speed = 0.0
    ch.heading = 0.0

    def tick(seconds, each=None):
        for _ in range(int(seconds / STEP)):
            s.clock += STEP
            w.tick(STEP, s.clock)
            s.run_due()
            bot.attack_target = None
            ch.attack_target = None
            if each:
                each()
    tick(0.5)
    return w, s, ch, bot, tick, logs


def jack_in_the_box(cfg, data):
    w, s, ch, bot, tick, logs = world_with(cfg, data, ATOMIC_JOKER)
    hits = []
    orig = w.damage

    def damage(source, target, amount):
        if target is bot:
            hits.append(s.clock)
        return orig(source, target, amount)
    w.damage = damage
    t0 = s.clock
    ok = w.cast(ch, 4, None, None)
    tick(14.0)
    w.damage = orig
    last = (hits[-1] - t0) if hits else -1
    check("Atomic Joker R is cast", ok)
    check("Atomic Joker R hits the bot", len(hits) >= 2, f"{len(hits)} hits")
    # TotalNumBursts 4 (stat 32) and MaxDuration 8 s (stat 19): at most one more missile already in flight
    check("Atomic Joker R stops after its bursts (<= 5 hits in 14 s)", len(hits) <= 5, f"{len(hits)} hits")
    check("Atomic Joker R's last hit within MaxDuration + a flight", 0 <= last <= 9.0, f"last hit at {last:.2f} s")


def punch_line(cfg, data):
    w, s, ch, bot, tick, logs = world_with(cfg, data, ATOMIC_JOKER)
    tick(0.5)
    guards = w.combat.of(ch).defeat_guards
    check("Atomic Joker holds a type-0 defeat guard (The Punch Line)", 0 in set(guards.values()), f"{guards}")
    mark = len(logs)
    w.damage(None, ch, ch.health + 50.0)                 # a turret's direct hit (Units._direct_attack)
    tick(0.5)
    check("a lethal direct hit leaves Atomic Joker alive (the passive takes over)", ch.alive and ch.health >= 1.0,
          f"alive {ch.alive} health {ch.health}")
    entered = any("0x340004de" in line and "S0 -> S2" in line for line in logs[mark:])
    check("The Punch Line's graph goes to its defeat state (0x1000011B)", entered)


def stick_and_move(cfg, data):
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=2.5)
    w.nav = None                                         # Crime Alley's start has a wall 1.7 m west of it
    launched = []
    samples = []

    def sample():
        if w.combat.of(ch).motion is not None:
            samples.append((ch.heading, getattr(ch, "facing_offset", None) or 0.0))
    import ics.world as W
    orig = W.CastWorld.launch_missile

    def launch(self, owner, cls, target, speed, rng, scripts, **extra):
        launched.append((cls, self._ent(target)))
        return orig(self, owner, cls, target, speed, rng, scripts, **extra)
    W.CastWorld.launch_missile = launch
    try:
        point = (ch.pos[0] - 6.0, ch.pos[1], ch.pos[2])  # hop west, away from the bot in the east
        ok = w.cast(ch, 3, None, point)
        tick(2.5, sample)
    finally:
        W.CastWorld.launch_missile = orig
    check("Blue Beetle E is cast", ok)
    check("Blue Beetle E moves him west", ch.pos[0] < point[0] + 3.0, f"x {ch.pos[0]:.2f}")
    if samples:
        h, off = samples[len(samples) // 2]
        travel = abs(math.remainder(h - math.pi, math.tau))
        model = abs(math.remainder(h + off, math.tau))
        check("during the dash the heading of travel points west", travel < 0.2, f"heading {math.degrees(h):.0f}")
        check("during the dash the model faces east, back to the dash", model < 0.2,
              f"model yaw {math.degrees(h + off):.0f}")
    else:
        check("the dash runs a forced movement", False)
    check("Blue Beetle E shoots the bot he hops away from", any(t is bot for _c, t in launched),
          f"{[(hex(c), getattr(t, 'name', t)) for c, t in launched]}")
    check("after the landing the lock is gone and he keeps facing east",
          getattr(ch, "facing_lock", None) is None and not getattr(ch, "facing_offset", None)
          and abs(math.remainder(ch.heading, math.tau)) < 0.2, f"heading {math.degrees(ch.heading):.0f}")


def _button(ch, slot):
    from ics import records as RC
    blk = (getattr(ch, "slot_tables", None) or {}).get(slot)
    d = RC.as_dict(blk) if blk else {}
    return d.get(0x10000302), d.get(0x1000003D)


def infiltrator_mode(cfg, data):
    """Blue Beetle's R swaps Q / W / E (SetSlotSkill 0x48000A97 / A95 / A96): the HUD's slot tables follow."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE)
    sent0 = len(s.sent)
    ok = w.cast(ch, 4, None, None)
    tick(1.0)
    icon, targeting = _button(ch, 1)
    check("Infiltrator Mode is cast", ok)
    check("Infiltrator Mode: Q's button is the melee Q (icon 0x13001DE1, targeting 14)",
          icon == 0x13001DE1 and targeting == 14, f"icon {icon} targeting {targeting}")
    check("Infiltrator Mode: W and E buttons swapped too", _button(ch, 2)[0] and _button(ch, 3)[0],
          f"{_button(ch, 2)} {_button(ch, 3)}")
    check("the slot tables reach the client", any("slot 1 button" in (lb or "") for lb in s.labels(sent0)))
    redraws = [lb for lb in s.labels(sent0) if "buttons redrawn" in (lb or "")]
    check("one rank toggle after the swap's tables ([ics] slot_table_hud_refresh_once)", len(redraws) == 1,
          f"{len(redraws)} toggles")
    tick(3.5)                                            # R's own cooldown (stat 15 = 3 s)
    ok2 = w.cast(ch, 4, None, None)
    tick(1.0)
    icon, targeting = _button(ch, 1)
    check("Infiltrator Mode off: Q's button is the Energy Cannon again (0x13001DDF, targeting 13)",
          ok2 and icon == 0x13001DDF and targeting == 13, f"cast {ok2} icon {icon} targeting {targeting}")


def construct_teleport(cfg, data):
    """Arcane Green Lantern's Q: while the construct flies its button casts with no target (0x100000FA field 14 = 5)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000043B)
    w.nav = None
    ok = w.cast(ch, 1, None, (ch.pos[0] + 6.0, ch.pos[1], ch.pos[2]))
    tick(0.6)
    during = _button(ch, 1)[1]
    tick(3.0)
    after = _button(ch, 1)[1]
    check("Construct Champion is cast", ok)
    check("while the construct flies Q casts on the key press (targeting 5)", during == 5, f"targeting {during}")
    check("after the window Q aims again (targeting 13)", after in (None, 13), f"targeting {after}")


def heat_vision_knockback(cfg, data):
    """Superman's E pushes the enemy to KnockbackDistance (stat 17 = 6 m) from him (status 0x48000A0F, 0x340003F8)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B, bot_dx=3.5)
    w.nav = None
    x0 = bot.pos[0]
    n = len(s.sent)
    ok = w.cast(ch, 3, bot, None)
    labels = []
    tick(1.5, lambda: labels.append(w.forced_motion_label(bot)))       # what the session's per-tick send would log
    pushed = bot.pos[0] - x0
    check("Heat Vision is cast", ok)
    check("Heat Vision pushes the bot back (about 6 m - 3.5 m)", 1.5 <= pushed <= 3.5, f"pushed {pushed:.2f} m")
    states = [lb for lb in labels if lb and "forced movement state" in lb and bot.name in lb]
    check("the knockback's motion states are logged ([ics] log_forced_motion)", bool(states), f"{len(states)}")


def heat_vision_punch(cfg, data):
    """Superman's E second part: in its window E is a key press (targeting 5) that dashes and punches the target."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B, bot_dx=3.5)
    w.nav = None
    hits = []
    orig = w.damage

    def damage(source, target, amount):
        if target is bot:
            hits.append(amount)
        return orig(source, target, amount)
    w.damage = damage
    w.cast(ch, 3, bot, None)
    tick(1.0)
    during = _button(ch, 3)[1]
    first = len(hits)
    ok = w.cast(ch, 3, None, None)                       # the key press: no target, no point
    tick(2.0)
    w.damage = orig
    check("Heat Vision's window: E casts on the key press (targeting 5)", during == 5, f"targeting {during}")
    check("the key press dashes and punches (DamageB)", ok and len(hits) > first, f"cast {ok} hits {hits}")
    check("after the punch E aims at an entity again (14)", _button(ch, 3)[1] == 14, f"{_button(ch, 3)}")
    check("after the punch Superman is not held by a cast (he can walk)", not ch.skill_insts[3].casting,
          f"casting {ch.skill_insts[3].casting}")


def heat_vision_punch_through(cfg, data):
    """Heat Vision 0x340003D6: graph S1's TargetIID (operand source 3, the punch's target) and graph S7's own TargetIID
    (source 5, what the dash collides with) are two variables (local frames)."""
    from ics import script_model as SM
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B, bot_dx=3.5)
    inst = ch.skill_insts.get(3)
    h = SM.elf_hash("TargetIID")
    op3, op5 = SM.Operand(h, 3, 0), SM.Operand(h, 5, 0)
    inst.set(op3, "the target")
    inst.set(op5, "a collider")
    check("a local frame's TargetIID does not replace the outer one (Superman's E punch)",
          inst.get(op3) == "the target" and inst.get(op5) == "a collider", f"{inst.get(op3)} / {inst.get(op5)}")


def heat_vision_diagonal(cfg, data):
    """The knockback goes on along the line from Superman (status 0x340003F8: Offset(source, target) as the heading)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B, bot_dx=0.0)
    w.nav = None
    bot.pos = [ch.pos[0] + 2.5, ch.pos[1] + 2.5, ch.pos[2]]
    p0 = list(bot.pos)
    w.cast(ch, 3, bot, None)
    tick(1.5)
    d = (bot.pos[0] - p0[0], bot.pos[1] - p0[1])
    ang = math.degrees(math.atan2(d[1], d[0]))
    check("Heat Vision pushes a target at 45 degrees on along 45 degrees", math.hypot(*d) > 1.0 and abs(ang - 45) < 10,
          f"pushed {math.hypot(*d):.2f} m toward {ang:.0f} deg")
    mark = len(logs)
    w.cast(ch, 3, None, None)
    tick(1.5)
    order = [l for l in logs[mark:] if "0x340003d6" in l and ("S8 -> S2" in l or "HeatVision_Finisher" in l)]
    check("the punch stage S8 waits for its finisher animation's end (hook 2 before S8 -> S2)",
          len(order) >= 2 and "Finisher" in order[0], f"{order}")


def stick_and_move_hits(cfg, data):
    """Blue Beetle's E shots (0x400008C4, script 0x340004AA) fly and hit: the spawn event after the chain, the target
    given at the launch, the damage read from the E's slot."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=2.5)
    w.nav = None
    hits = []
    orig = w.damage

    def damage(source, target, amount):
        if target is bot:
            hits.append(amount)
        return orig(source, target, amount)
    w.damage = damage
    w.cast(ch, 3, None, (ch.pos[0] - 6.0, ch.pos[1], ch.pos[2]))
    tick(2.5)
    w.damage = orig
    check("Blue Beetle's E shots hit the bot behind him (E stat 5)", hits and all(a > 0 for a in hits), f"{hits}")


def blue_beetle_forms(cfg, data):
    """Infiltrator Mode: each form keeps its own Q / W / E cooldowns; the melee basic attack reaches 1 m."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=3.0)
    w.nav = None
    w.cast(ch, 1, None, (bot.pos[0], bot.pos[1], bot.pos[2]))   # ranged Q: Energy Cannon, cooldown 7 s
    tick(1.0)
    ranged_q = ch.ready_at.get(1, 0.0) - s.clock
    w.cast(ch, 4, None, None)                            # melee form
    tick(1.0)
    melee_q = ch.ready_at.get(1, 0.0) - s.clock
    reach = (w.combat.of(ch).stat_overrides.get(0) or {}).get(18)
    check("the ranged Q is cooling down", ranged_q > 3.0, f"{ranged_q:.1f} s")
    check("the melee Q starts ready (its own cooldown)", melee_q <= 0.05, f"{melee_q:.1f} s")
    check("the melee basic attack's reach is stat 17 (1 m)", reach is not None and abs(float(reach) - 1.0) < 0.01,
          f"override {reach}")
    tick(3.0)
    w.cast(ch, 4, None, None)                            # back to ranged
    tick(1.0)
    back_q = ch.ready_at.get(1, 0.0) - s.clock
    check("back in ranged form the Energy Cannon keeps its remaining cooldown", 0.5 < back_q < ranged_q,
          f"{back_q:.1f} s (was {ranged_q:.1f} s)")


def _orders(s, eid, since=0):
    """[(index, label, event, body)] of the messages to eid from s.sent[since:]."""
    from ics.scriptlet_orders import _frame
    out = []
    for i, (label, data) in enumerate(s.sent[since:], since):
        f = _frame(data) if isinstance(data, (bytes, bytearray)) else None
        if f and f[0] == eid:
            out.append((i, label, f[2], bytes(data[f[3]:])))
    return out


def blue_beetle_passive_orders(cfg, data):
    """Blue Beetle's passive loop 0x10000BC3 rides along in his later 0x8D orders and stops with 0x11F ([ics]
    scriptlet_orders; C: each 0x8D first ends the runs earlier orders started on the object)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=3.0)
    w.nav = None
    loop, burst = bytes([0x10, 0x8B, 0xC3]), bytes([0x10, 0x8B, 0xC4])    # 0x10000BC3 / 0x10000BC4 as an entry key
    start = len(s.sent)
    w.cast(ch, 1, None, (bot.pos[0], bot.pos[1], bot.pos[2]))           # ranged Q: the passive's buff (6 s)
    tick(1.0)
    first = [o for o in _orders(s, ch.eid, start) if o[2] in (0x8D, 0x2073) and loop in o[3]]
    check("the passive's burst and loop go in one order", bool(first) and burst in first[0][3],
          f"{len(first)} orders with the loop")
    mid = len(s.sent)
    w.cast(ch, 2, None, (bot.pos[0], bot.pos[1], bot.pos[2]))           # W during the buff
    tick(1.0)
    later = [o for o in _orders(s, ch.eid, mid) if o[2] in (0x8D, 0x2073)]
    # 0x2073 (default): the scripts' orders do not end the loop; a 0x8D (the server's own) carries it again
    check("no later order to him ends the loop (additive, or a 0x8D carrying it)",
          later and all(o[2] == 0x2073 or loop in o[3] for o in later),
          f"{[(hex(o[2]), loop in o[3]) for o in later]}")
    tick(6.0)
    stops = [o for o in _orders(s, ch.eid, mid) if o[2] == 0x11F and o[3][1:5] == (0x10000BC3).to_bytes(4, "little")]
    check("the buff's end stops the loop with 0x11F", bool(stops))
    after = len(s.sent)
    w.cast(ch, 3, None, (bot.pos[0] + 2.0, bot.pos[1], bot.pos[2]))     # E after the buff
    tick(1.0)
    check("orders after the stop leave the loop out",
          not any(loop in o[3] for o in _orders(s, ch.eid, after) if o[2] in (0x8D, 0x2073)))
    check("no 0x8D signal stops any more",
          not any(o[2] == 0x8D and "signal" in (o[1] or "") for o in _orders(s, ch.eid, start)))


def scarab_skill_used(cfg, data):
    """Blue Beetle's ranged W: the launch and the detonation (a second press) each raise "skill used" 0x10000196 once
    ([ics] skill_used_every_use; the tester: in the original either one starts the passive)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=6.0)
    w.nav = None
    raised = []
    real = R.raise_event

    def spy(world, ent, event, params=None, *a, **k):
        if event == 0x10000196 and ent is ch:
            raised.append(dict(params or {}).get("Slot"))
        return real(world, ent, event, params, *a, **k)
    R.raise_event = spy
    try:
        w.cast(ch, 2, None, (bot.pos[0], bot.pos[1], bot.pos[2]))
        tick(0.6)
        launch = list(raised)
        w.cast(ch, 2, None, None)
        tick(0.6)
        both = list(raised)
    finally:
        R.raise_event = real
    check("the W's launch raises 'skill used' once", launch == [2], f"{launch}")
    check("the W's detonation raises it once more", both == [2, 2], f"{both}")


def basic_attack_turn_and_hold(cfg, data):
    """A champion's basic attack turns him to a target behind him (its script's FaceTarget reaches the client) and a
    move ordered during the swing waits for the swing's graph state to end ([ics] attack_face_by_script,
    basic_attack_holds_movement)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=-3.0)
    w.nav = None
    ch.heading = 0.0                                     # facing east, the bot west
    n = len(s.sent)
    ch.attack_target = bot
    w._attack_step(ch, time.time())
    ch.attack_target = None
    swinging, held, headings = [], [], []
    x0 = ch.pos[0]

    def each():
        if w._basic_attack_animating(ch):
            swinging.append(True)
            headings.append(ch.heading)
            if not held:
                w.walk_to(ch, (ch.pos[0] + 4.0, ch.pos[1], ch.pos[2]))
                held.append((ch.dest is None, getattr(ch, "pending_move", None) is not None))
    tick(1.2, each)
    turned = bool(headings) and abs(abs(headings[-1]) - math.pi) < 0.3
    check("the basic attack turns him to a target behind him (the facing reaches the client)",
          turned and any("faces the target" in (lb or "") for lb in s.labels(n)),
          f"heading {math.degrees(headings[-1]) if headings else None}")
    check("a move ordered during the swing waits", bool(held) and held[0] == (True, True), f"{held} swing {len(swinging)}")
    check("the waiting move runs when the swing's state ends",
          getattr(ch, "pending_move", None) is None and ch.pos[0] > x0 + 0.5, f"moved {ch.pos[0] - x0:.2f} m")


def quiet_messages_keep_one_order(cfg, data):
    """A vitals message between two scriptlets of one moment leaves them in one 0x8D (Superman's beam
    Vfx_Sup_Heat_Vision_Active and the next step's orders, 2026-11-04; [ics] scriptlet_orders_quiet_messages)."""
    from ics import messages as M
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B)
    n = len(s.sent)
    w.send(f"{ch.name}: scriptlet 0x10000abe (0x8d)", M.start_scriptlets(ch.eid, [(0x10000ABE, 901)]))
    w.send(f"{ch.name} vitals (0x42)", M.build_message(ch.eid, 0x42, b"\x00"))
    w.send(f"{ch.name}: scriptlet 0x10000ab7 (0x8d)", M.start_scriptlets(ch.eid, [(0x10000AB7, 902)]))
    s.run_due()
    orders = [o for o in _orders(s, ch.eid, n) if o[2] == 0x8D]
    beam, step = bytes([0x10, 0x8A, 0xBE]), bytes([0x10, 0x8A, 0xB7])
    check("a vitals message does not split a champion's moment (one 0x8D with both)",
          len(orders) == 1 and beam in orders[0][3] and step in orders[0][3], f"{len(orders)} orders")


def explosion_linger(cfg, data):
    """[ics] destroy_network_linger (the sandbox's experiment): Energy Cannon's explosion object 0x40000CD8 leaves the
    server's world at the script's DestroyEntity [0.3, 0] and reaches the client's removal 1 s later."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=4.0)
    w.nav = None
    w.ic["destroy_network_linger"] = {"0x40000CD8": 1.0}
    n = len(s.sent)
    gone_server, sent_at = [], []

    def each():
        if any("0x40000cd8" in (lb or "") and "spawn" in (lb or "") for lb in s.labels(n)) and not gone_server:
            if not any(e.class_id == 0x40000CD8 for e in w.entities.values()):
                gone_server.append(s.clock)
        if not sent_at and any("destroyed (0x3, 1 s after)" in (lb or "") for lb in s.labels(n)):
            sent_at.append(s.clock)
    w.cast(ch, 1, None, (bot.pos[0], bot.pos[1], bot.pos[2]))
    tick(2.5, each)
    check("the explosion object leaves the server at the script's time and the client 1 s later",
          gone_server and sent_at and 0.9 <= sent_at[0] - gone_server[0] <= 1.1,
          f"server {gone_server[:1]} client {sent_at[:1]}")


def prewarm_and_spawn_stamp(cfg, data):
    """[ics] prewarm_statuses: Superman's kit statuses (Heat Vision's knockback 0x48000A0F) are resolved at his
    creation; [ics] spawn_state_backdate: Energy Cannon's explosion object is created with its state 0.1 s old."""
    from ics import messages as M
    data._scripts.pop(("status", 0x48000A0F), None)       # as in a fresh server: not read yet
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B)
    check("Heat Vision's knockback status is resolved at Superman's creation",
          ("status", 0x48000A0F) in data._scripts)
    w, s, ch, bot, tick, logs = world_with(cfg, data, BLUE_BEETLE, bot_dx=4.0)
    w.nav = None
    stamps, real = [], M.create_object

    def spy(eid, cls, now, *a, **k):
        if cls == 0x40000CD8:
            stamps.append(time.time() - now)
        return real(eid, cls, now, *a, **k)
    M.create_object = spy
    try:
        w.cast(ch, 1, None, (bot.pos[0], bot.pos[1], bot.pos[2]))
        tick(1.5)
    finally:
        M.create_object = real
    check("the explosion object's creation state is stamped 0.1 s earlier", stamps and abs(stamps[0] - 0.1) < 0.02,
          f"{stamps}")


def frost_breath_root(cfg, data):
    """Superman's W roots an enemy in its inner cone (status 0x48000A06: its record's 0x1000046F sets Rooted)."""
    w, s, ch, bot, tick, logs = world_with(cfg, data, 0x4000002B, bot_dx=1.5)
    w.nav = None
    ok = w.cast(ch, 2, None, tuple(bot.pos))
    rooted = []
    tick(0.6, lambda: rooted.append(bool(w.combat.flag(bot, 0x100007FE))))
    tick(1.5)
    check("Frost Breath is cast", ok)
    check("Frost Breath roots the bot in its inner cone", any(rooted), f"{sum(rooted)} rooted ticks")
    check("the root ends with its status", not w.combat.flag(bot, 0x100007FE))


def main():
    cfg = config.load()
    cfg["ics"]["trace_scripts"] = True
    cfg["ics"]["match_waves"]["stagger"] = 0.0
    cfg["ics"]["match_waves"]["first"] = 1.0
    cfg["ics"]["match_pre_start"] = 13.0
    cfg["ics"]["liftable_gallery"] = False
    cfg["ics"]["base_aura_invulnerable"] = False          # the scenes stand at the team's start
    data = Data(cfg.game_dir)
    TM.setup(cfg, data)
    R.STOP_LEFT_SUBGRAPHS = bool(cfg["ics"].get("stop_left_subgraphs", True))
    time.time = TM._virtual_time
    try:
        for fn in (jack_in_the_box, punch_line, stick_and_move, infiltrator_mode, construct_teleport,
                   heat_vision_knockback, heat_vision_punch, heat_vision_punch_through, heat_vision_diagonal,
                   stick_and_move_hits, blue_beetle_forms, blue_beetle_passive_orders, scarab_skill_used,
                   basic_attack_turn_and_hold, quiet_messages_keep_one_order,
                   explosion_linger, prewarm_and_spawn_stamp,
                   frost_breath_root):
            fn(cfg, data)
    finally:
        time.time = TM._real_time
        TM._clock["s"] = None
    bad = [name for name, ok in CHECKS if not ok]
    print(f"{len(CHECKS) - len(bad)}/{len(CHECKS)} kit fix checks")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
