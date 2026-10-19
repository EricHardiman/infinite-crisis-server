"""Gaslight Batman's skills that are not part of the first tutorial steps:
W (Sonic Shell), E (Bat Flight), R (Bat Scream) and his Stolen Power, the
surveillance camera (D). Q (Sonic Batarang) still lives in tutorial1.py.

Each function takes the context `ctx` (the Tutorial): it gives the match
(`ctx.match`), `run_scripts`, `schedule`, `log` and `skill_hit(entity, damage,
slot)`, which applies the damage with the target's immunities. The scriptlet
keys are the ones the action tour showed on Batman (docs/batman_actions.md).
Damage, ranges and speeds are first guesses ([combat] overrides them).
"""
import math
import time

from . import messages as M
from .wire import KIND_IID

SLOT_Q, SLOT_W, SLOT_E, SLOT_R, SLOT_PASSIVE, SLOT_RECALL, SLOT_D = 1, 2, 3, 4, 5, 6, 7

# W: Batman_Gaslight_Sonic_Shell + Vfx_Bmg_Sonic_Shell (the shell flies to the
# point and explodes there, hurting every enemy around it).
W_CAST_KEYS = (0x10000163, 0x10000177)
W_RANGE, W_SPEED, W_RADIUS, W_DAMAGE = 11.0, 14.0, 3.0, 120
# E: Batman_Gaslight_Bat_Flight + Vfx_Bmg_Flight + Vfx_Bmg_Flight_Active; he
# flies to the point and lands with Vfx_Bmg_Flight_Stop, hurting enemies there.
E_CAST_KEYS = (0x10000165, 0x10000178, 0x10000182)
E_STOP_KEYS = (0x1000016F,)
E_RANGE, E_SPEED, E_RADIUS, E_DAMAGE = 9.0, 14.0, 3.0, 100
HIT_KEYS = (0x10000223, 0x10000209)          # VFX_CBT_Hit_Shared + physical reaction

# D: Gaslight Batman's Surveillance Camera. The skill record is 0x48000808
# (pack 0xA00000B3, "Gaslight Batman's Surveillance Camera"); the camera it
# places is entity 0x40000265 (world state 0x2E000E6C, .entity 0x2D000BFD,
# template 0x1D000244 "Surveillance Camera"). The client reads the skill of
# skill slot N from the champion property in the table at VA 0x15EDA28; slot 7
# (Secondary1, the "D" button) is property 0x100008F0.
CAMERA_SKILL = 0x48000808
CAMERA_ENTITY = 0x40000265
SLOT_SKILL_PROPERTY = {0: 0x100008E3, 1: 0x100008E8, 2: 0x100008EA, 3: 0x100008EC, 4: 0x100008E6,
                       5: 0x100008EF, 6: 0x100008E4, 7: 0x100008F0, 8: 0x100008F1}
HUD_SKILL_BUTTON_D = 22                       # SkillButtonStolenPower1 (UIHUDElementID)


def _num(ctx, key, default):
    return float(ctx.match.cfg["combat"].get(key, default))


def _clamp(origin, point, max_range):
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    d = math.hypot(dx, dy)
    if d <= max_range or d < 1e-6:
        return (point[0], point[1], origin[2]), d
    k = max_range / d
    return (origin[0] + dx * k, origin[1] + dy * k, origin[2]), max_range


def _face(m, xy):
    bx, by, _ = m.mover.pos
    if abs(xy[0] - bx) + abs(xy[1] - by) > 1e-3:
        m.mover.heading = math.atan2(xy[1] - by, xy[0] - bx)


def root(ctx, now, seconds=None, reason="cast"):
    """17:36: casting while walking, Batman went on walking and the cast never
    showed. He stops where he casts and stays for the cast ([combat] cast_root)."""
    m = ctx.match
    m.mover.target = None
    m.mover.speed = 0.0
    if seconds is None:
        seconds = _num(ctx, "cast_root", 0.35)
    if seconds > 0 and hasattr(ctx, "locked_until"):
        ctx.locked_until = max(ctx.locked_until, now + seconds)
        ctx.lock_reason = reason
        ctx.lock_logged = False


def _enemies_near(m, xy, radius):
    return [e for e in m.entities.values()
            if e.alive and e.attackable and e.distance_to(xy) <= radius]


def sonic_shell(ctx, point, target, now):
    """W: the shell flies to the point (or the target) and explodes."""
    m = ctx.match
    if target is not None and not (target.attackable and target.alive):
        target = None                                   # a prop (gate, camera, vehicle) is no target
    aim = tuple(target.pos) if target is not None else point
    if aim is None:
        return []
    land, dist = _clamp(m.mover.pos, aim, _num(ctx, "w_range", W_RANGE))
    _face(m, land)
    m.combat.stop()
    root(ctx, now, reason="Sonic Shell")
    m.sequence += 1
    variables = [(M.PROP_SCRIPT_TARGET, KIND_IID, target.eid)] if target is not None else None
    ctx.run_scripts(M.CHAMPION_AGENT_ID, W_CAST_KEYS, "Sonic Shell", variables)
    flight = max(0.25, dist / _num(ctx, "w_speed", W_SPEED))
    radius, damage = _num(ctx, "w_radius", W_RADIUS), int(_num(ctx, "w_damage", W_DAMAGE))

    def explode():
        hit = _enemies_near(m, land[:2], radius)
        if (target is not None and target.alive and target.attackable and target not in hit
                and target.distance_to(land[:2]) <= radius + 1.0):
            hit.append(target)
        ctx.log(f"Sonic Shell explodes at ({land[0]:.1f}, {land[1]:.1f}): "
                + (", ".join(e.name for e in hit) or "nothing hit"))
        out = []
        for e in hit:
            ctx.run_scripts(e.eid, HIT_KEYS, f"Sonic Shell hits {e.name}",
                            [(M.PROP_SCRIPT_TARGET, KIND_IID, M.CHAMPION_AGENT_ID)])
            out += ctx.skill_hit(e, damage, SLOT_W)
        return out
    ctx.schedule(flight, explode)
    return [("Batman faces the Sonic Shell point", m.champion_bundle(now))]


def bat_flight(ctx, point, target, now):
    """E: Batman flies to the point and hurts the enemies where he lands."""
    m = ctx.match
    if time.time() < getattr(ctx, "flying_until", 0.0):
        return []                                       # already in the air
    if target is not None and not (target.attackable and target.alive):
        target = None
    aim = tuple(target.pos) if target is not None else point
    if aim is None:
        return []
    land, dist = _clamp(m.mover.pos, aim, _num(ctx, "e_range", E_RANGE))
    goal = m.mover.free_goal(m.mover.pos[0], m.mover.pos[1], land[0], land[1]) if m.mover.obstacles else land[:2]
    if goal is None:
        ctx.log("Bat Flight: no free spot to land")
        return []
    speed = _num(ctx, "e_speed", E_SPEED)
    dist = math.hypot(goal[0] - m.mover.pos[0], goal[1] - m.mover.pos[1])
    flight = max(0.2, dist / speed)
    m.combat.stop()
    _face(m, goal)
    ctx.run_scripts(M.CHAMPION_AGENT_ID, E_CAST_KEYS, "Bat Flight")
    normal = float(m.cfg["timing"]["move_speed"])       # never the flight speed of an earlier cast
    m.mover.move_speed = speed
    m.mover.target = [goal[0], goal[1], m.mover.pos[2]]
    started = time.time()
    ctx.flying_until = started + flight * 3 + 1.0     # cleared on landing
    radius, damage = _num(ctx, "e_radius", E_RADIUS), int(_num(ctx, "e_damage", E_DAMAGE))

    def wait_landing():
        # he lands when the mover reaches the point (it may go round a corner),
        # or at the latest after three times the straight flight time
        if m.mover.target is not None and time.time() - started < flight * 3:
            ctx.schedule(0.05, wait_landing)
            return []
        return land_now()

    def land_now():
        ctx.flying_until = 0.0
        m.mover.move_speed = normal
        ctx.run_scripts(M.CHAMPION_AGENT_ID, E_STOP_KEYS, "Bat Flight lands")
        bx, by, _ = m.mover.pos
        hit = _enemies_near(m, (bx, by), radius)
        if (target is not None and target.alive and target.attackable and target not in hit
                and target.distance_to((bx, by)) <= radius + 1.5):
            hit.append(target)                          # the drone it was aimed at
        if not hit:
            live = [e for e in m.entities.values() if e.alive and e.attackable]
            near = min(live, key=lambda e: e.distance_to((bx, by)), default=None)
            ctx.log(f"Bat Flight lands at ({bx:.1f}, {by:.1f}): nothing hit"
                    + (f" (nearest: {near.name} {near.distance_to((bx, by)):.1f} m away)" if near else ""))
        else:
            ctx.log(f"Bat Flight lands at ({bx:.1f}, {by:.1f}): " + ", ".join(e.name for e in hit))
        out = []
        for e in hit:
            ctx.run_scripts(e.eid, HIT_KEYS, f"Bat Flight hits {e.name}",
                            [(M.PROP_SCRIPT_TARGET, KIND_IID, M.CHAMPION_AGENT_ID)])
            out += ctx.skill_hit(e, damage, SLOT_E)
        return out
    ctx.schedule(min(flight, 0.1), wait_landing)
    m.sequence += 1
    return [("Batman takes flight", m.champion_bundle(now))]


# R: Batman_Gaslight_Bat_Scream + Vfx_Bmg_Scream; Scream_Stop when it is over.
# "The Bat Scream is my greatest attack. It can travel for miles, damaging all
# enemies in its path." (0x1D8): a long straight line from Batman through the
# cursor that goes through walls and gates. Its real size is unknown: 60 m x 3 m.
R_CAST_KEYS = (0x10000162, 0x10000173)
R_STOP_KEYS = (0x10000176,)
R_RANGE, R_WIDTH, R_SPEED, R_DAMAGE, R_DURATION = 60.0, 3.0, 40.0, 400, 1.2


def bat_scream(ctx, point, target, now):
    """R: a sonic wave along a line; every enemy in it is hit once."""
    m = ctx.match
    if target is not None and not (target.attackable and target.alive):
        target = None
    aim = tuple(target.pos) if target is not None else point
    if aim is None:
        return []
    bx, by, _ = m.mover.pos
    dx, dy = aim[0] - bx, aim[1] - by
    n = math.hypot(dx, dy)
    if n < 0.05:
        dx, dy = math.cos(m.mover.heading), math.sin(m.mover.heading)
    else:
        dx, dy = dx / n, dy / n
    length, half = _num(ctx, "r_range", R_RANGE), _num(ctx, "r_width", R_WIDTH) / 2
    speed, damage = _num(ctx, "r_speed", R_SPEED), int(_num(ctx, "r_damage", R_DAMAGE))
    m.combat.stop()
    # 16:32: cast while walking, Batman slid on during the scream: he stops
    # where he casts (speed 0) and stays there for the cast ([combat] r_root)
    root(ctx, now, _num(ctx, "r_root", 1.0), "Bat Scream")
    _face(m, (bx + dx, by + dy))
    m.sequence += 1
    ctx.run_scripts(M.CHAMPION_AGENT_ID, R_CAST_KEYS, "Bat Scream")
    hits = []
    for e in m.entities.values():
        if not (e.alive and e.attackable):
            continue
        t = (e.pos[0] - bx) * dx + (e.pos[1] - by) * dy
        side = abs((e.pos[0] - bx) * dy - (e.pos[1] - by) * dx)
        # 16:14: some drones were missed: right next to Batman (t ~ 0) and at the
        # wave's edge; the wave starts 1 m behind him and the drones are ~1 m wide
        if -1.0 < t <= length and side <= half + 1.0:
            hits.append((t, e))
    hits.sort(key=lambda p: p[0])
    ctx.log(f"Bat Scream towards ({bx + dx * length:.1f}, {by + dy * length:.1f}): "
            + (", ".join(f"{e.name} at {t:.0f} m" for t, e in hits) or "nothing in its path"))
    for t, e in hits:
        def hit(e=e):
            if not e.alive:
                return []
            ctx.run_scripts(e.eid, HIT_KEYS, f"Bat Scream hits {e.name}",
                            [(M.PROP_SCRIPT_TARGET, KIND_IID, M.CHAMPION_AGENT_ID)])
            return ctx.skill_hit(e, damage, SLOT_R)
        ctx.schedule(max(0.1, t / speed), hit)
    duration = max(_num(ctx, "r_duration", R_DURATION), length / speed)
    ctx.schedule(duration, lambda: (ctx.run_scripts(M.CHAMPION_AGENT_ID, R_STOP_KEYS, "Bat Scream over"), [])[1])
    hit_list = [e for _, e in hits]
    if hasattr(ctx, "scream_result"):
        ctx.schedule(duration + 0.2, lambda: ctx.scream_result(hit_list))
    return [("Batman faces the Bat Scream", m.champion_bundle(now))]
