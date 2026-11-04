"""The PvP mode layer (ics/match) on a simulated session: every PvP map starts its match in a World, spawns its
structures / objectives / camps, sends the match HUD, walks a minion wave down a lane, lets a structure die in the
protection order and ends on the map's win condition (core, team health, surrender).

    python tests\\test_match.py
"""
import copy
import heapq
import itertools
import math
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ics import config                                   # noqa: E402
from ics import match as pvp                             # noqa: E402
from ics import navmesh                                  # noqa: E402
from ics.gamedata import Data                            # noqa: E402
from ics.match import maps                               # noqa: E402
from ics import script_runtime as R                       # noqa: E402
from ics.world import CastWorld, World                   # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail and not cond else ""))


class FakeSession:
    """What the mode layer uses of a session; World's timers run on the simulated clock."""

    def __init__(self):
        self.sent = []
        self.cinematics = []
        self.over = None
        self.clock = time.time()
        self.timers, self.seq = [], itertools.count()

    def send(self, label, data):
        self.sent.append((label or "", data))

    def schedule(self, delay, fn):
        heapq.heappush(self.timers, (self.clock + float(delay), next(self.seq), fn))

    def run_due(self):
        while self.timers and self.timers[0][0] <= self.clock:
            heapq.heappop(self.timers)[2]()

    def play_cinematic(self, did):
        self.cinematics.append(did)

    def match_over(self, winner, seconds):
        self.over = (winner, seconds)

    def labels(self, since=0):
        return [lbl for lbl, _ in self.sent[since:]]


def make(cfg, data, encounter, team=1):
    s = FakeSession()
    spawn = pvp.spawn_point(encounter, team)
    w = World(data, cfg, encounter, spawn, send=s.send, schedule=s.schedule, log=lambda t: None)
    nav = pvp.navgrid(data, encounter, spawn[1:3])
    w.nav = nav.copy() if nav else None
    w.ground_z = spawn[6]
    w.create_champion(cfg["ics"]["champion"], spawn)
    w.in_world = True
    m = pvp.start_match(w, s, encounter)
    return s, w, m


def run(s, m, seconds, step=0.25):
    n = int(round(seconds / step))
    for _ in range(n):
        s.clock += step
        m.tick(step, s.clock)
        m.world.tick(step, s.clock)
        s.run_due()


def kill(w, ent):
    w.damage(None, ent, (ent.health or 0) + 1)


def common(name, cfg, data, encounter):
    print(f"{name} ({encounter:#x})")
    s, w, m = make(cfg, data, encounter)
    spec, mode = maps.map_for(encounter)
    labels = s.labels()
    skip = set((cfg["ics"].get("match_skip_roles") or {}).get(spec.get("key"), ()))
    n_struct = sum(1 for st in spec["structures"] if st["role"] not in skip) * 2
    alive = [mu for mu in m.structures if mu.ent.alive]
    check("every structure of both teams spawned", len(alive) == n_struct, f"{len(alive)} / {n_struct}")
    # Gotham Heights' cores are invulnerable scenery on a raised platform (their health is the team's, fase3-hq)
    alive = [mu for mu in alive if not mu.invulnerable or mu.role != "core"]
    check("structures have their data health", all((mu.ent.max_health or 0) >= 1 for mu in alive),
          [(mu.role, mu.ent.max_health) for mu in alive])
    props = {p[0]: p[2] for p in alive[0].ent.extra_props}
    check("structure: team, LifeState, minimap", props.get(0x1000009C) in (1, 2) and props.get(0x100000FA) == 4
          and props.get(0x2A1) == 1, props)
    check("objectives spawned", len(m.objectives.points) + (1 if m.objectives.device else 0)
          == len([o for o in spec.get("objectives", ()) if o["role"] != "beacon"
                  or not (cfg["ics"].get("match_beacons") or {}).get(spec["key"])]), len(m.objectives.points))
    check("match clock sent (0x10000109)", any("0x10000109" in lbl for lbl in labels))
    check("scoreboard sent (0x1000005b)", any("0x1000005b" in lbl for lbl in labels))
    check("intro cinematic played", s.cinematics[:1] == [spec["intro"]] or not spec.get("intro"), s.cinematics)
    check("the map's navmesh is loaded", w.nav is not None)
    if w.nav is not None:
        off = [mu for mu in alive if not w.nav.nearest(mu.ent.pos[0], mu.ent.pos[1], max_r=3.0)]
        check("structures on (or next to) the navmesh", not off, [str(mu) for mu in off])
    ch = w.champion
    start = maps.spawn_point(encounter, ch.team)
    check("champion at its team's start point", math.hypot(ch.pos[0] - start[4], ch.pos[1] - start[5]) < 0.01)
    return s, w, m, spec, mode


def lane_and_core(name, cfg, data, encounter):
    s, w, m, spec, mode = common(name, cfg, data, encounter)
    run(s, m, 13.0 + 46.0)
    lanes = list(spec["lanes"])
    wave = [mu for mu in m.waves.minions if mu.ent.alive]
    check(f"first wave on {len(lanes)} lane(s) x 2 teams", len(wave) == len(lanes) * 2 * 4, len(wave))
    check("minions have data stats (health, speed)", all((mu.ent.max_health or 0) > 100 and mu.ent.move_speed > 2
                                                         for mu in wave),
          [(mu.ent.name, mu.ent.max_health, mu.ent.move_speed) for mu in wave[:3]])
    first = wave[0]
    start = list(first.ent.pos)
    moves_before = sum(1 for lbl in s.labels() if first.ent.name in lbl)
    run(s, m, 10.0)
    walked = math.hypot(first.ent.pos[0] - start[0], first.ent.pos[1] - start[1])
    check("a minion walks its lane (>= 15 m in 10 s)", walked >= 15.0, f"{walked:.1f} m")
    if w.nav is not None:
        check("the minion stays on the navmesh", w.nav.nearest(first.ent.pos[0], first.ent.pos[1], max_r=1.5) is not None,
              first.ent.pos)
    sends = sum(1 for lbl in s.labels() if first.ent.name in lbl) - moves_before
    check("movement sent as states, not every tick (<= 20 in 10 s)", 0 < sends <= 20, sends)
    # structure order: the enemy core cannot be damaged while its defences stand
    core = m.core(2)
    hp = core.ent.health
    w.damage(w.champion, core.ent, 500)
    check("enemy core protected while its turrets stand", core.ent.health == hp and core.ent.alive, core.ent.health)
    check("the core is not yet attackable on the client (no 0x100007D9)",
          not any(core.ent.name + ": attackable" in lbl for lbl in s.labels()))
    for role in ("turret", "inner_turret", "dampener", "core_turret"):
        for mu in [x for x in m.structures if x.team == 2 and x.role == role and x.ent.alive]:
            kill(w, mu.ent)
            check(f"{role} {mu.lane or ''} destroyed", not mu.ent.alive)
    s.clock += 1
    run(s, m, 0.5)
    check("dampener count / billboard sent", any("0x100002eb" in lbl for lbl in s.labels()))
    check("the unprotected core is attackable on the client (0x100007D9 = true)",
          any(core.ent.name + ": attackable" in lbl for lbl in s.labels()))
    check("announcer: a structure's death plays its event (0x2039)",
          any("announcer event" in lbl and "0x2039" in lbl for lbl in s.labels()), [l for l in s.labels() if "0x2039" in l][:5])
    kill(w, core.ent)
    check("core destroyed -> match over, team 1 wins", m.over and m.winner == 1, m.status())
    run(s, m, 13.0)                 # 2026-10-29: after the end cinematic ([ics] match_end_timing "notice" <= 12 s)
    check("match-ended notice (0x1000000e) and session.match_over", any("0x1000000e" in lbl for lbl in s.labels())
          and s.over and s.over[0] == 1, s.over)
    return s, w, m


# ---- death animation (docs/re-notes/death-animation.md; tester report 2026-10-28 15:00) ----------------------------
ON_DEAD, ON_RESPAWN, DEATH_OVERLAY, RAISE_EVENT = 0x100001FA, 0x100001FC, 0x10000843, 0x100001E3


def frames(s, since=0):
    """[(send index, label, dest, event, body)] of every message frame sent since `since` (one send may hold several):
    u32 len | 0x02 | u64 dest | u8 flags | compact event | body (ics/wire.py build_message)."""
    from ics.wire import read_compact
    out = []
    for i, (lbl, data) in enumerate(s.sent[since:], since):
        p = 0
        while p + 4 <= len(data):
            n = struct.unpack_from("<I", data, p)[0]
            fr, p = data[p + 4:p + 4 + n], p + 4 + n
            if len(fr) > 10 and fr[0] == 2:
                ev, q = read_compact(fr, 10)
                out.append((i, lbl, struct.unpack_from("<Q", fr, 1)[0], ev, fr[q:]))
    return out


def scriptlet_of(body):
    """(key, run) of a 0x8D body's first entry: u8 0 | compact count | u8 key >> 24 | compact low 24 bits | compact run."""
    from ics.wire import read_compact
    _n, q = read_compact(body, 1)
    lo, r = read_compact(body, q + 1)
    return (body[q] << 24) | lo, read_compact(body, r)[0]


def entry_run(body, key):
    """The run of key's entry in a 0x8D body, or None: a champion's order may hold several entries (one order per object
    and moment, ics/scriptlet_orders.py); an entry is u8 key >> 24 | compact low 24 bits | compact run | u32 flags 0."""
    from ics.wire import pack_compact, read_compact
    first, run = scriptlet_of(body)
    if first == key:
        return run
    pat = bytes([key >> 24]) + pack_compact(key & 0xFFFFFF)
    k = body.find(pat, 2)
    while k >= 0:
        run, q = read_compact(body, k + len(pat))
        if body[q:q + 4] == bytes(4):
            return run
        k = body.find(pat, k + 1)
    return None


def stop_key(body):
    """The scriptlet key a 0x11F body stops (u8 0 | u32 key | u32 run | u8 flag)."""
    return struct.unpack_from("<I", body, 1)[0]


def graph_var(body):
    """The 0x780 graph event in a 0x8D's variable table (u32 0x780 | 07 80 | enum: u8 high byte, compact rest), or None."""
    from ics.wire import read_compact
    k = body.find(b"\x80\x07\x00\x00\x07\x80")
    return None if k < 0 else (body[k + 6] << 24) | read_compact(body, k + 7)[0]


def life(body):
    """LifeState 0x100000FA in a 0x4 / 0x6 body (fa 00 00 10 | 40 fa | 00 value), or None."""
    k = body.find(b"\xfa\x00\x00\x10\x40\xfa\x00")
    return body[k + 7] if k >= 0 else None


def stand_up_test(class_id):
    """A test on 0x8D bodies: true when it raises a main-machine wildcard of the champion's graph that leaves its Death
    state (all of them but CbtState_Death_Induce 0x100000AD / CbtState_Dead 0x1000010B; Death has no transition of its
    own, death-animation.md 2.1): a 0x100001E3 run with such a 0x780, or a key data/skill_graphs.json maps to one."""
    import json
    with open(os.path.join(ROOT, "data", "skill_graphs.json"), encoding="utf-8") as f:
        sg = json.load(f)
    g = sg["graphs"][sg["variants"][f"0x{class_id:08X}"]]
    main_m = next(mm for mm in g["machines"] if any(wc["n"] == "CbtState_Death_Induce" for wc in mm["wild"]))
    wild = {g["events"][wc["n"]] for wc in main_m["wild"] if wc["n"] in g["events"]} - {0x100000AD, 0x1000010B}
    keys = {int(k, 16) for k, evs in list(sg["shared_scriptlets"].items()) + list(g["scriptlets"].items())
            if set(evs) & wild}

    def test(body):
        key = scriptlet_of(body)[0]
        return graph_var(body) in wild if key == RAISE_EVENT else key in keys
    test.wild, test.keys = wild, keys
    return test


def death_animation(cfg, data):
    """2026-10-28 15:00 (tester report 2026-10-28 15:00: the fall to the ground does not play when the player kills or
    is killed; death-animation.md 9.5 / 10.4): the local champion's and a bot's death and respawn messages."""
    print("death animation (death-animation.md)")
    import copy
    from ics import messages as MM
    from ics.wire import read_compact

    def defaults(w):                    # the defaults under test, whatever config.toml sets (the match's own [ics] copy)
        for k in ("death_scriptlets", "death_fall_local", "death_fall_delay", "death_bundle_force",
                  "death_overlay_scriptlets", "death_overlay_stop", "death_overlay_skip_after_end",
                  "bot_getup_scriptlets", "bot_getup_delays"):
            w.ic[k] = copy.deepcopy(config.DEFAULTS["ics"][k])
    fr = MM.stop_scriptlet(0x0200000000000002, DEATH_OVERLAY, 7)
    ev, q = read_compact(fr, 14)
    check("0x11F (stop a scriptlet run): u8 0 | u32 key | u32 run | u8 flag (death-animation.md 4)",
          ev == 0x11F and fr[5:13] == struct.pack("<Q", 0x0200000000000002)
          and fr[q:] == bytes.fromhex("00430800100700000000"), fr.hex())

    # the local champion (Gotham Divided)
    s, w, m = make(cfg, data, 0x40000399)
    defaults(w)
    run(s, m, 14.0)
    ch = w.champion
    turret = next(mu for mu in m.structures if mu.team == 2 and mu.role == "turret")
    stands_up = stand_up_test(ch.class_id)
    check("graph data: Global_Locomotion leaves Death and _Defeat_OnRespawn raises it, _Defeat_OnDead does not",
          0x100000AA in stands_up.wild and ON_RESPAWN in stands_up.keys and ON_DEAD not in stands_up.keys)

    def die():
        ch.pos = list(turret.ent.pos)
        run(s, m, 0.5)                  # out of the base aura (invulnerable inside, fase3-hq)
        n = len(s.sent)
        w.damage(turret.ent, ch, ch.health + 1)
        return n

    def seq(n, who=None):
        who = who or ch
        return [(i, e, b) for i, _l, d, e, b in frames(s, n) if d == who.eid]

    def first(rows, ev, pred, after=-1):
        return next((i for i, e, b in rows if e == ev and i > after and pred(b)), None)

    def keyed(rows, key):
        return [i for i, e, b in rows if e == 0x8D and entry_run(b, key) is not None]

    def bare(rows):
        return [i for i, e, b in rows if e == 0x8D and entry_run(b, RAISE_EVENT) is not None and graph_var(b) == 0x100000AD]

    def overlay_or_stop(n):
        return [(i, e) for i, _l, _d, e, b in frames(s, n)
                if (e == 0x11F and stop_key(b) == DEATH_OVERLAY) or (e == 0x8D and entry_run(b, DEATH_OVERLAY) is not None)]
    n = die()
    rows = seq(n)
    dead = first(rows, 0x4, lambda b: life(b) == 2)
    check("death: the LifeState 2 bundle at once; the fall waits death_fall_delay (the stop state and the statuses' "
          "exit 0x8Ds land first)", dead is not None and not keyed(rows, ON_DEAD) and not bare(rows), rows[:3])
    s.clock += float(w.ic.get("death_fall_delay", 0.15) or 0.0) + 0.05
    s.run_due()
    rows = seq(n)
    fall = keyed(rows, ON_DEAD)
    check("death: then one _Defeat_OnDead 0x100001FA to the champion (the fall: CbtState_Death_Induce + the death "
          "cue), no second fall by the bare graph event", dead is not None and len(fall) == 1 and dead < fall[0]
          and not bare(rows),
          (dead, fall, bare(rows)))
    check("death: no death screen by default (death_overlay_scriptlets = []: the client runs its own), no 0x11F",
          not overlay_or_stop(n), overlay_or_stop(n))
    s.clock += 30
    s.run_due()
    rows = seq(n)
    back = first(rows, 0x4, lambda b: life(b) == 4, fall[0] if fall else -1)
    ups = keyed(rows, ON_RESPAWN)
    check("respawn: the LifeState 4 bundle, then one _Defeat_OnRespawn (Global_Locomotion: back on his feet)",
          ch.alive and back is not None and len(ups) == 1 and back < ups[0], (back, ups))
    lying = [(i, hex(scriptlet_of(b)[0])) for i, e, b in rows
             if e == 0x8D and fall and fall[0] < i < (back or 1 << 30) and stands_up(b)]
    check("nothing stands the dead champion up before the respawn (no main-machine wildcard but Death_Induce / Dead)",
          fall and back and not lying, lying)
    check("respawn: no 0x11F by default", not overlay_or_stop(n))

    w.ic["death_fall_local"] = False                        # the match's own copy of [ics]
    n = die()
    s.clock += 0.5
    s.run_due()
    rows = seq(n)
    check("death_fall_local = false: the LifeState 2 bundle only, no fall (fase3-ie)",
          first(rows, 0x4, lambda b: life(b) == 2) is not None and not keyed(rows, ON_DEAD) and not bare(rows))
    w.ic["death_fall_local"] = True
    s.clock += 30
    s.run_due()

    w.ic["death_overlay_scriptlets"] = ["_CDefeatSystem_DeathOverlay"]       # the opt-in death screen
    n = die()
    s.clock += 0.5
    s.run_due()
    rows = seq(n)
    dead, fall = first(rows, 0x4, lambda b: life(b) == 2), keyed(rows, ON_DEAD)
    over = [(i, entry_run(b, DEATH_OVERLAY)) for i, e, b in rows if e == 0x8D and entry_run(b, DEATH_OVERLAY) is not None]
    check("death_overlay_scriptlets opt-in: _CDefeatSystem_DeathOverlay 0x10000843 on the champion after the fall",
          dead is not None and len(fall) == 1 and len(over) == 1 and dead < fall[0] <= over[0][0], (dead, fall, over))   # <=: one order, the fall first
    s.clock += 30
    s.run_due()
    rows = seq(n)
    ups, stops = keyed(rows, ON_RESPAWN), [(i, b) for i, e, b in rows if e == 0x11F and stop_key(b) == DEATH_OVERLAY]
    check("opt-in: at the respawn, after the get-up, 0x11F stops that run (u8 0 | 0x10000843 | its run | u8 0)",
          over and len(ups) == 1 and len(stops) == 1 and ups[0] < stops[0][0]
          and stops[0][1] == b"\x00" + struct.pack("<IIB", DEATH_OVERLAY, over[0][1], 0), (ups, stops))
    n = die()
    s.clock += 0.5
    s.run_due()
    over = [entry_run(b, DEATH_OVERLAY) for i, e, b in seq(n) if e == 0x8D and entry_run(b, DEATH_OVERLAY) is not None]
    m.end(2, "death test")
    stops = [b for i, e, b in seq(n) if e == 0x11F and stop_key(b) == DEATH_OVERLAY]
    s.clock += 30
    s.run_due()
    check("opt-in: the match end stops it (the original's grey ended at its end cinematic), and only once",
          len(over) == 1 and stops == [b"\x00" + struct.pack("<IIB", DEATH_OVERLAY, over[0], 0)]
          and len([e for i, e, b in seq(n) if e == 0x11F and stop_key(b) == DEATH_OVERLAY]) == 1, (over, stops))

    # 2026-10-29 (fase3-if review): in Clash the local death that takes the last team health ends the match inside
    # World.damage, before its fall is scheduled; the fall still plays, the opt-in death screen does not start after the
    # end (Match.end's stop had nothing to stop, and no 0x11F would ever follow: [ics] death_overlay_skip_after_end)
    s, w, m = make(cfg, data, 0x40000E68)                   # Crime Alley Clash 1v1
    defaults(w)
    w.ic["death_overlay_scriptlets"] = ["_CDefeatSystem_DeathOverlay"]
    run(s, m, 14.0)
    ch = w.champion
    turret = next(mu for mu in m.structures if mu.team != ch.team and mu.role == "turret")
    m.team_health[ch.team] = 20.0                           # this death takes the last 20 (match_clash_health_loss)
    n = die()
    ended = m.over
    s.clock += 0.5
    s.run_due()
    rows = seq(n)
    check("Clash: the death that ends the match still falls (_Defeat_OnDead), but starts no death screen after the "
          "end and leaves no run to stop (death_overlay_skip_after_end)", ended and len(keyed(rows, ON_DEAD)) == 1
          and not overlay_or_stop(n) and not ch.__dict__.get("death_overlay_runs"), (ended, overlay_or_stop(n)))
    w.ic["death_overlay_skip_after_end"] = False
    n = len(s.sent)
    w.death_overlay(ch, True)
    s.run_due()                                 # the moment's orders (ics/scriptlet_orders.py), no time passes
    check("death_overlay_skip_after_end = false: a death screen may start after the end (the fase3-if review's case)",
          [e for i, e in overlay_or_stop(n)] == [0x8D], overlay_or_stop(n))
    w.ic["death_overlay_skip_after_end"] = True

    # a death in the middle of a real Super Strength carry (Crime Alley; its script 0x34000164 gets EVENT_END at the drop)
    s, w, m = make(cfg, data, 0x40000C82)
    defaults(w)
    run(s, m, 14.0)
    ch = w.champion
    car = next(e for e in m.liftables.props if e.liftable == "vehicle")
    block, skill = data.stolen_power(0x480003CB)
    skill.slot = 7
    ch.kit[7], ch.ranks[7], ch.stolen[7] = skill, 1, block
    w.start_kit_slot(ch, 7)
    ch.pos, ch.safe_zone = [car.pos[0] - 2.0, car.pos[1], car.pos[2]], False
    run(s, m, 0.5)
    w.cast(ch, 7, car, None)
    for _ in range(40):
        run(s, m, 0.05, step=0.05)
        if getattr(ch, "carry_ready", False):
            break
    carrying, held = getattr(ch, "carrying", None) is car, bool(getattr(ch, "bundle_hold", False))
    n = len(s.sent)
    kill(w, ch)
    dead = first(seq(n), 0x4, lambda b: life(b) == 2)
    check("carry: the death bundle (LifeState 2) goes at once although the carry holds the champion's bundles "
          "(death_bundle_force)", carrying and held and dead is not None, (carrying, held, dead))
    run(s, m, 1.0, step=0.05)                   # the carry drops (Liftables.tick) and its script gets EVENT_END
    s.clock += 30
    s.run_due()
    rows = seq(n)
    fall = keyed(rows, ON_DEAD)
    back = first(rows, 0x4, lambda b: life(b) == 4, fall[0] if fall else -1)
    stands_up = stand_up_test(ch.class_id)
    lying = [(i, hex(scriptlet_of(b)[0])) for i, e, b in rows
             if e == 0x8D and fall and fall[0] < i < (back or 1 << 30) and stands_up(b)]
    check("carry: the vehicle drops, the fall follows the death bundle, nothing stands the carrier up until the "
          "respawn", getattr(car, "carried_by", 0) is None and dead is not None and len(fall) == 1 and dead < fall[0]
          and back is not None
          and not lying and any(f"{car.name} dropped" in lbl for lbl in s.labels(n)), (fall, back, lying))

    # a bot champion (Crime Alley v AI, the tester's bot Atomic Wonder Woman)
    s = FakeSession()
    spawn = pvp.spawn_point(0x40000C82, 1)
    w = World(data, cfg, 0x40000C82, spawn, send=s.send, schedule=s.schedule, log=lambda t: None)
    nav = pvp.navgrid(data, 0x40000C82, spawn[1:3])
    w.nav = nav.copy() if nav else None
    w.ground_z = spawn[6]
    w.create_champion(cfg["ics"]["champion"], spawn)
    w.in_world = True
    m = pvp.start_match(w, s, 0x40000C82, [
        {"iid": 1, "name": "Player", "team": 1, "index": 0, "champion": cfg["ics"]["champion"], "bot": False},
        {"iid": 0x0200000000F00000, "name": "Bot 0", "team": 2, "index": 0, "champion": 0x400003EC, "bot": True}])
    bot = next(p.agent for p in m.score.players if p.bot and p.agent is not None)
    defaults(w)
    run(s, m, 14.0)
    bot.safe_zone = False
    n = len(s.sent)
    w.damage(w.champion, bot, (bot.health or 0) + 1)
    s.run_due()                                 # the moment's orders (ics/scriptlet_orders.py), no time passes
    rows = seq(n, bot)
    stop, prop = first(rows, 0x4, lambda b: life(b) == 2), first(rows, 0x6, lambda b: life(b) == 2)
    fall = keyed(rows, ON_DEAD)
    check("bot death: stop bundle (LifeState 2) < 0x6 LifeState 2 < _Defeat_OnDead, at once, no bare graph event",
          None not in (stop, prop) and len(fall) == 1 and stop < prop < fall[0] and not bare(rows), (stop, prop, fall))
    check("bot death: no death screen and no 0x11F for a bot (no local-player filter)", not overlay_or_stop(n))
    run(s, m, 30.0)
    rows = seq(n, bot)
    alive = first(rows, 0x6, lambda b: life(b) == 4)
    back = first(rows, 0x4, lambda b: life(b) == 4, alive if alive is not None else 1 << 30)
    ups = keyed(rows, ON_RESPAWN)
    stands_up = stand_up_test(bot.class_id)
    lying = [(i, hex(scriptlet_of(b)[0])) for i, e, b in rows
             if e == 0x8D and fall and fall[0] < i < (alive or 1 << 30) and stands_up(b)]
    check("bot respawn: 0x6 LifeState 4 < bundle < _Defeat_OnRespawn, one per bot_getup_delays entry (fase3-ie: two "
          "each); nothing stands it up before", bot.alive and None not in (alive, back) and ups and back < ups[0]
          and len(ups) == len(w.ic.get("bot_getup_delays") or [0.15]) and not lying, (alive, back, ups, lying))
    w.ic["death_scriptlets"] = []
    bot.safe_zone = False
    n = len(s.sent)
    w.damage(w.champion, bot, (bot.health or 0) + 1)
    s.run_due()                                 # the moment's orders (ics/scriptlet_orders.py), no time passes
    rows = seq(n, bot)
    check("death_scriptlets = []: a bot's fall is the bare graph event 0x100001E3 + 0x780 = 0x100000AD (fase3-ie)",
          len(bare(rows)) == 1 and not keyed(rows, ON_DEAD), rows[-3:])
    w.ic["death_scriptlets"] = ["_Defeat_OnDead"]


# ---- object updates (docs/re-notes/object-update-bundles.md 13; tester report 2026-10-28 15:00) -------------------
UPDATE_KEYS = ("object_update_mode", "delta_remove_missing", "delta_remove_net0", "delta_complex_as_bundle",
               "delta_full_on_life_change", "delta_full_after_load", "delta_create_window", "delta_player_object",
               "delta_vitals_with_motion", "delta_resync_seconds", "motion_state_backdate")


def unit_death_slide_levelup(cfg, data):
    """Tester report 2026-10-29 12:45 (docs/re-notes/unit-death-slide-levelup.md): a dead drone / camp creature plays
    _Defeat_OnDead then _Defeat_OnFade before its 0x3; a dead champion takes no move; the 0x2104 layout and icon."""
    print("unit death, dead slide, level-up icon (unit-death-slide-levelup.md)")
    import copy
    from ics import matchend
    from ics import messages as MM
    on_fade = 0x100001FE

    def defaults(w):                    # the defaults under test, whatever config.toml sets
        for k in ("unit_death_scriptlets", "unit_death_fall_delay", "unit_fade_scriptlets", "unit_fade_delay",
                  "dead_hold_still", "corpse_seconds"):
            w.ic[k] = copy.deepcopy(config.DEFAULTS["ics"][k])

    s, w, m = make(cfg, data, 0x40000C82)
    defaults(w)
    run(s, m, 13.0 + 47.0)              # the first wave at 45 s
    mu = next((x for x in m.waves.minions if x.ent.alive), None)
    check("CA: a lane drone to kill", mu is not None)
    if mu is None:
        return
    ent = mu.ent

    def rows(n):
        return [(i, e, b) for i, _l, d, e, b in frames(s, n) if d == ent.eid]

    def keyed(r, key):
        return [i for i, e, b in r if e == 0x8D and scriptlet_of(b)[0] == key]
    n = len(s.sent)
    kill(w, ent)
    r = rows(n)
    dead = next((i for i, e, b in r if e == 0x4 and life(b) == 2), None)
    check("drone death: the LifeState 2 bundle at once, no fall before unit_death_fall_delay",
          dead is not None and not keyed(r, ON_DEAD), r[:3])
    s.clock += float(w.ic["unit_death_fall_delay"]) + 0.05
    s.run_due()
    r = rows(n)
    fall = keyed(r, ON_DEAD)
    check("drone death: then one _Defeat_OnDead 0x100001FA (fall + Vfx_OnExplode)",
          len(fall) == 1 and dead is not None and dead < fall[0], (dead, fall))
    s.clock += float(w.ic["unit_fade_delay"])
    s.run_due()
    r = rows(n)
    fade = keyed(r, on_fade)
    gone = [i for i, e, b in r if e == 0x3]
    check("drone death: then one _Defeat_OnFade 0x100001FE, before the 0x3", len(fade) == 1 and fall and fade[0] > fall[0]
          and not gone, (fade, gone))
    s.clock += float(w.ic["corpse_seconds"])
    s.run_due()
    gone = [i for i, e, b in rows(n) if e == 0x3]
    check("drone death: removed (0x3) corpse_seconds after the death", len(gone) == 1 and gone[0] > fade[0], gone)
    # the keys off: as fase3-ig
    w.ic["unit_death_scriptlets"], w.ic["unit_fade_scriptlets"] = [], []
    mu2 = next((x for x in m.waves.minions if x.ent.alive), None)
    if mu2 is not None:
        ent = mu2.ent
        n = len(s.sent)
        kill(w, ent)
        s.clock += 5.0
        s.run_due()
        r = rows(n)
        check("unit_death_scriptlets / unit_fade_scriptlets [] -> no fall, no fade (fase3-ig)",
              not keyed(r, ON_DEAD) and not keyed(r, on_fade) and any(e == 0x3 for _i, e, _b in r))
    defaults(w)

    # a dead champion never walks (AGL slid while falling, run 12:16:14.9)
    ch = w.champion
    turret = next(x for x in m.structures if x.team == 2 and x.role == "turret")
    ch.pos = list(turret.ent.pos)
    run(s, m, 0.5)
    w.damage(turret.ent, ch, ch.health + 1)
    at = list(ch.pos)
    target = [at[0] + 3.0, at[1], at[2]]
    check("dead champion: walk_to refuses the move", not w.walk_to(ch, target) and ch.dest is None, ch.dest)
    ch.dest, ch.path = list(target), []
    w.tick(0.25, s.clock)
    check("dead champion: a destination left on the body is cleared, it does not move",
          ch.dest is None and math.hypot(ch.pos[0] - at[0], ch.pos[1] - at[1]) < 1e-6, (ch.dest, ch.pos, at))
    w.ic["dead_hold_still"] = False
    check("dead_hold_still false -> the move is accepted (fase3-ig)", w.walk_to(ch, target) or w.nav is not None)
    ch.dest, ch.path = None, []
    defaults(w)

    # 0x2104: the icon and the client's field order
    agl = 0x4000080C
    icon = matchend.champion_icon({"level_up_icon": "tex384"}, data, agl)
    want = data.champion_name(agl)[1]                    # a costume: its champion's tex384 (the kill card's)
    check("level-up icon: AGL's tex384 from data/champions.json", icon and icon == want, (icon, want))
    check("level-up icon: \"\" -> 0", matchend.champion_icon({"level_up_icon": ""}, data, agl) == 0)
    # tester report 2026-10-30 15:30: the default is the grid icon (UI pack), AGL 0x13001652 for its costume too
    gi = matchend.champion_icon(config.DEFAULTS["ics"], data, agl)
    check("level-up icon: default = AGL's grid_icon 0x13001652", gi == 0x13001652, hex(gi or 0))
    body = frames(FakeSend(MM.character_level(agl, "X", 2, 1, 720, 15, 120, 0, 0.25, 0.8, icon=icon)), 0)[0][4]
    head = struct.unpack_from("<II", body, 1)
    k = 9 + len(MM.string_info("X"))
    nums = struct.unpack_from("<IIIIIffI", body, k) if len(body) >= k + 32 else None
    check("0x2104 client layout: champion, icon | level, prev, total, earned, bonus, pct, prev pct, to next",
          head == (agl, icon) and nums is not None and nums[:5] == (2, 1, 15, 120, 0) and nums[7] == 720
          and abs(nums[5] - 0.25) < 1e-6 and abs(nums[6] - 0.8) < 1e-6, (head, nums, body.hex()))


class FakeSend:
    """frames() over one built message."""
    def __init__(self, data):
        self.sent = [("", data)]


def frame0(data):
    """(dest, event, body) of the first message frame in data (ics/wire.py build_message)."""
    from ics.wire import read_compact
    fr = data[4:4 + struct.unpack_from("<I", data, 0)[0]]
    ev, q = read_compact(fr, 10)
    return struct.unpack_from("<Q", fr, 1)[0], ev, fr[q:]


def sub_events(body):
    """[(sub-event, body)] of a 0x4 batch body: u8 base | compact n | n x (compact id | u32 length | body)."""
    from ics.wire import read_compact
    n, p = read_compact(body, 1)
    out = []
    for _ in range(n):
        ev, p = read_compact(body, p)
        ln = struct.unpack_from("<I", body, p)[0]
        out.append((ev, body[p + 4:p + 4 + ln]))
        p += 4 + ln
    return out


def batch_ids(body):
    return [ev for ev, _b in sub_events(body)]


def b0_tail(body):
    """(heading, speed, seq A, seq B) of a 0x4 batch whose last sub-event is the 0xB0 (it ends f32 heading, f32 speed,
    i16 facing, u8 seq A, u8 seq B)."""
    h, sp = struct.unpack_from("<ff", body, len(body) - 12)
    return h, sp, body[-2], body[-1]


def object_updates(cfg, data):
    """2026-10-28 15:00 (tester report 2026-10-28 15:00: animations cut by object updates; object-update-bundles.md 7 /
    12 / 13): [ics] object_update_mode "delta" = an object is created by a full bundle, then updated by motion-only
    states, 0x6 and 0x86, never a 0xBC that removes the ids ics sets by 0x6 only; the old full bundles one key away."""
    print("object updates (object-update-bundles.md)")
    import copy
    from types import SimpleNamespace
    from ics import messages as MM
    from ics.session import Session
    from ics.world import Entity
    from ics.wire import KIND_BOOL, KIND_F32, build_message
    saved = {k: copy.deepcopy(cfg["ics"].get(k)) for k in UPDATE_KEYS}

    def defaults(w):                    # the defaults under test, whatever config.toml sets
        for k in UPDATE_KEYS:
            w.ic[k] = copy.deepcopy(config.DEFAULTS["ics"][k])
        # 2026-10-29: the default went back to "bundle" (tester 10:28); these checks test the delta path itself
        w.ic["object_update_mode"] = "delta"
        w.ic["delta_create_window"] = 0.0     # the simulated clock outruns time.time(): the window is checked below

    def to(s, n, eid):
        return [(ev, b) for _i, _l, dest, ev, b in frames(s, n) if dest == eid]

    def only_b0(rows):
        return [b for ev, b in rows if ev == 4 and batch_ids(b) == [0xB0]]

    def full(rows):
        return [b for ev, b in rows if ev == 4 and batch_ids(b) == [0xF2, 0xB0, 0xBC]]

    def has(rows, ev, prop):
        return [b for e, b in rows if e == ev and struct.pack("<I", prop) in b]

    try:
        iid = 0x0200000000000123
        check("0x86 = u8 0 | u32 id (serializer 0x839500): one property removed, as a full bundle removes an omitted id",
              MM.remove_property(iid, 0x10000029) == build_message(iid, 0x86, b"\x00" + struct.pack("<I", 0x10000029)))
        wpos, same = (1, 0x13, 0xCB, 0xFB, 12.5, 40.25, 200.0), []
        for parent in (None, (0,), (0x0200000000000002, 0x10, 0x100000B0, 0, 1)):
            a = dict(sub_events(frame0(MM.create_object(iid, 0x40000CA0, 99.0, position=wpos, heading=1.1, speed=2.5,
                                                        tele_seq=3, second_seq=1, parent=parent))[2]))[0xB0]
            b = dict(sub_events(frame0(MM.pvp_movement_state(iid, 99.0, wpos, 1.1, 2.5, tele_seq=3, second_seq=1,
                                                             parent=parent))[2]))[0xB0]
            same.append(a == b)
        check("a motion-only state's 0xB0 = a bundle's for the same state, the attach block (flag 0x04) included", all(same),
              same)
        ones = (0x1000019D, 0x10000029, 0x10000249, 0x100003F3, 0x10000B2D, 0x10000C66, 0x100000FA, 0x7D2)
        zeros = (0x90F, 0x1000035E, 0x10000133, 0x100008E5)
        check("network modes read from MasterProperty 0x32000000: the 0x6-only ids, LifeState and 0x7D2 = 1; 0x90F, credits, "
              "vision and an item block = 0; the camera yaw 0x1000011E = 3 (properties-complete.md 3)",
              [data.network_mode(p) for p in ones] == [1] * len(ones) and [data.network_mode(p) for p in zeros] == [0] * 4
              and data.network_mode(0x1000011E) == 3 and len(data._net_modes or {}) >= 3000,
              {f"{p:#x}": data.network_mode(p) for p in ones + zeros})

        s = FakeSession()
        spawn = pvp.spawn_point(0x40000C82, 1)
        w = World(data, cfg, 0x40000C82, spawn, send=s.send, schedule=s.schedule, log=lambda t: None)
        nav = pvp.navgrid(data, 0x40000C82, spawn[1:3])
        w.nav = nav.copy() if nav else None
        w.ground_z = spawn[6]
        defaults(w)
        w.create_champion(cfg["ics"]["champion"], spawn)
        w.in_world = True
        rows = [{"iid": 1, "name": "Player", "team": 1, "index": 0, "champion": cfg["ics"]["champion"], "bot": False},
                {"iid": 0x0200000000F00000, "name": "Bot 0", "team": 2, "index": 0, "champion": 0x40000262, "bot": True}]
        m = pvp.start_match(w, s, 0x40000C82, rows)
        bot = next(p.agent for p in m.score.players if p.bot and p.agent is not None)
        ch = w.champion
        run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 4.0)
        mu = next((x for x in m.waves.minions if x.ent.alive), None)
        rm = to(s, 0, mu.ent.eid) if mu else []
        first = next((b for ev, b in rm if ev == 4), b"")
        moves = only_b0(rm)
        check("delta: a minion is created by a full bundle (0xF2 + 0xB0 + 0xBC), then walks by motion-only states, no "
              "second bundle", mu is not None and first and batch_ids(first) == [0xF2, 0xB0, 0xBC] and len(full(rm)) == 1
              and moves and any(b0_tail(b)[1] > 0 for b in moves), (len(full(rm)), len(moves)))
        turret = next(x.ent for x in m.structures if x.ent.alive and x.role == "turret")
        w.update(turret, "turret refresh")
        n = len(s.sent)
        w.update(turret, "turret again")
        check("delta: an update with nothing changed sends nothing", len(s.sent) == n, s.labels(n))
        w.update(bot, None, motion=False)
        hid = next((p[2] for p in bot.extra_props if p[0] == 0x90F), 0)
        bot.extra_props = [p for p in bot.extra_props if p[0] != 0x90F] + [(0x90F, KIND_BOOL, 0 if hid else 1)]
        n = len(s.sent)
        w.update(bot, None, motion=False)                   # Session._tick's bot branch when motion_due says no
        r = to(s, n, bot.eid)
        check("delta: a standing bot's fog flip 0x90F reaches the client by one 0x6 with no state (fase3-hy's 'invisible "
              "bot': 0x90F went only in full bundles)", len(r) == 1 and has(r, 6, 0x90F), [hex(ev) for ev, _b in r])
        # probes a turret never has (it keeps its tags 0x10000029 / 0x10000249 in extra_props): Stunned (net 1) and the
        # credits id (net 0)
        turret.extra_props += [(0x100003F3, KIND_BOOL, 1), (0x1000035E, KIND_F32, 5.0)]
        n = len(s.sent)
        w.update(turret, "two ids added")
        added = to(s, n, turret.eid)
        turret.extra_props = [p for p in turret.extra_props if p[0] not in (0x100003F3, 0x1000035E)]
        n = len(s.sent)
        w.update(turret, "two ids dropped")
        r = to(s, n, turret.eid)
        check("delta: added ids go by 0x6; an id of network mode 1 that leaves the list goes by one 0x86 (u8 0 | u32 id), "
              "a net-0 one stays on the client (as a bundle left it)", len(has(added, 6, 0x100003F3)) == 1
              and len(has(added, 6, 0x1000035E)) == 1 and [b for ev, b in r if ev == 0x86]
              == [b"\x00" + struct.pack("<I", 0x100003F3)] and not [ev for ev, _b in r if ev == 4], (added, r))
        w.ic["delta_remove_net0"] = True
        n = len(s.sent)
        w.update(turret, "net-0 id dropped")
        check("delta_remove_net0 = true: the net-0 id goes by 0x86 too",
              [b for ev, b in to(s, n, turret.eid) if ev == 0x86] == [b"\x00" + struct.pack("<I", 0x1000035E)])
        w.ic["delta_remove_net0"] = False
        w.update(ch, "champion state")
        w.vital_notices_on()
        n = len(s.sent)
        ch.gold += 25.0
        w.refresh_champion("credits probe")
        ch.heading += 1.0
        w.update(ch, "facing probe")
        r = to(s, n, ch.eid)
        check("delta: the champion's credits go by 0x6 and its facing by a motion-only state; no 0xBC or 0x86 removes its "
              "0x6-only unit flags 0x1000019D", has(r, 6, 0x1000035E) and only_b0(r) and not full(r)
              and not [ev for ev, _b in r if ev == 0x86], [(hex(ev), batch_ids(b) if ev == 4 else "") for ev, b in r])
        w.teleport(bot)
        n = len(s.sent)
        w.update(bot, "teleport probe")
        r = only_b0(to(s, n, bot.eid))
        check("delta: a teleport is a motion-only state with the new seq A (the client snaps, 0x60B5F0)",
              r and b0_tail(r[-1])[2] == bot.tele_seq, r and b0_tail(r[-1]))
        w.teleport(ch)
        n = len(s.sent)
        w.send_champion("champion teleport probe")
        r = to(s, n, ch.eid)
        check("delta: send_champion (a script teleport) is a motion-only state with the new seq A, without the "
              "vital-notice toggles, which follow full bundles only (12.3 e)", only_b0(r) and not full(r)
              and b0_tail(only_b0(r)[-1])[2] == ch.tele_seq and not any("unit flags" in lbl for lbl in s.labels(n)))
        e = mu.ent
        out = []
        for parent in ((ch.eid, 0x10, 0x100000B0, 0, 1), (0,)):
            e.attach_parent = parent
            n = len(s.sent)
            w.update(e, "attach probe")
            b0 = [dict(sub_events(b))[0xB0] for b in only_b0(to(s, n, e.eid))]
            out.append(b0[-1][0] if b0 else None)
            out.append(struct.unpack_from("<Q", b0[-1], 3)[0] if b0 else None)
        e.attach_parent = None
        check("delta: attach / detach go as motion-only states with the 0x04 parent block (the parent's IID, then 0)",
              out == [0x66, ch.eid, 0x66, 0], out)
        probe = w.spawn(0x40000CA0, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]], name="delta probe")
        n = len(s.sent)
        w.update(probe, "probe created")
        probe.pos[0] += 1.0
        w.update(probe, "probe moved")
        r = to(s, n, probe.eid)
        w.remove(probe)
        w.add(probe)
        n2 = len(s.sent)
        w.update(probe, "probe again")
        check("delta: creation = a full bundle, the next update a motion-only state; removed (0x3) and added again = a "
              "full bundle again", len(full(r)) == 1 and len(only_b0(r)) == 1 and full(to(s, n2, probe.eid)),
              [batch_ids(b) for ev, b in r if ev == 4])
        w.ic["delta_create_window"] = 60.0
        win = w.spawn(0x40000CA0, [ch.pos[0] + 4.0, ch.pos[1], ch.pos[2]], name="window probe")
        w.update(win, "window probe created")
        win.pos[0] += 1.0
        n = len(s.sent)
        w.update(win, "window probe moved")
        inside = full(to(s, n, win.eid))
        w.ic["delta_create_window"] = 0.0
        win.pos[0] += 1.0
        n = len(s.sent)
        w.update(win, "window probe moved later")
        check("delta_create_window: within it an update is still a full bundle (a creation job may drop a 0x6 / 0xB0)",
              inside and only_b0(to(s, n, win.eid)))
        w.in_world = False
        late = w.spawn(0x40000CA0, [ch.pos[0] + 5.0, ch.pos[1], ch.pos[2]], name="load probe")
        w.update(late, "load probe created")
        w.in_world = True
        n = len(s.sent)
        w.update(late, "load probe in the world")
        r1 = full(to(s, n, late.eid))
        late.pos[0] += 1.0
        n = len(s.sent)
        w.update(late, "load probe moved")
        check("delta_full_after_load: an object sent while loading gets one full bundle (second_seq 1) at its first update "
              "in the world, then deltas", r1 and dict(sub_events(r1[0]))[0xB0][-1] == 1 and only_b0(to(s, n, late.eid)))
        msl = Entity(w.new_id(), "missile probe", 0x40000090, [ch.pos[0], ch.pos[1], ch.pos[2] + 1.0], team=1,
                     kind="missile")
        msl.speed = msl.move_speed = 10.0
        w.add(msl)
        w.update(msl, "missile probe created")
        stub = SimpleNamespace(ic=w.ic, user=SimpleNamespace(send=lambda d, label=None: s.send(label, d)))
        Session._missile_motion(stub, w, msl)
        msl.heading += 0.5
        n = len(s.sent)
        Session._missile_motion(stub, w, msl)
        s.clock += 0.2
        s.run_due()
        r = to(s, n, msl.eid)
        check("delta: a missile's turn is a motion-only state and Vfx_Active is not replayed (a bundle drops no run, the "
              "replay only started a second beam)", only_b0(r) and not full(r) and not [ev for ev, _b in r if ev == 0x8D],
              [hex(ev) for ev, _b in r])
        ch.ranks[1] = ch.ranks.get(1, 0) + 1
        n = len(s.sent)
        w.update(ch, "rank probe")
        r = to(s, n, ch.eid)
        check("delta_complex_as_bundle: a changed array (the rank array 0x100000AF) goes in a full bundle, followed by "
              "vital_notices_on's unit-flag toggles (that bundle removed 0x1000019D)", full(r)
              and any("champion unit flags 8" in lbl for lbl in s.labels(n)))
        w.ic["delta_complex_as_bundle"] = False
        ch.ranks[1] += 1
        n = len(s.sent)
        w.update(ch, "rank probe 2")
        r = to(s, n, ch.eid)
        check("delta_complex_as_bundle = false: the rank array goes by 0x6 (entry reader 0x509740, as in a 0xBC), no bundle",
              has(r, 6, 0x100000AF) and not full(r))
        w.ic["delta_complex_as_bundle"] = True
        ch.ranks[1] -= 2
        n = len(s.sent)
        w.resync(ch)
        r = to(s, n, ch.eid)
        check("delta_resync_seconds: the idle resync is the movement state and scalar properties by 0x6, never a 0xBC",
              len(only_b0(r)) == 1 and len([1 for ev, _b in r if ev == 6]) >= 10 and not full(r)
              and not has(r, 6, 0x100000AF), len(r))
        mv = next((x.ent for x in m.waves.minions if x.ent.alive and x.ent.speed > 0 and x.ent is not e), None)
        n = len(s.sent)
        if mv is not None:
            R.apply_status(CastWorld(w, ch, None), ch, mv, 0x48000293, {"EffectDuration": 2.0})
        r = to(s, n, mv.eid) if mv is not None else []
        stop = [b for _i, lbl, dest, ev, b in frames(s, n) if mv is not None and dest == mv.eid
                and "stopped (crowd control)" in lbl]
        check("delta: a walking minion's stun: Stunned 0x100003F3 by 0x6, then its stop as a motion-only state (the stop "
              "bundle removed the flag in the same burst, 12.2.4)", has(r, 6, 0x100003F3) and stop
              and all(batch_ids(b) == [0xB0] for b in stop) and not [ev for ev, _b in r if ev == 0x86],
              [(hex(ev), batch_ids(b) if ev == 4 else "") for ev, b in r])
        ch.safe_zone = False
        n = len(s.sent)
        w.damage(None, ch, (ch.health or 0) + 1)
        dead = [b for _i, lbl, dest, ev, b in frames(s, n) if dest == ch.eid and ev == 4 and "dead (LifeState 2)" in lbl]
        check("delta_full_on_life_change: the local champion's death stays a full bundle (LifeState 2 in its 0xBC)",
              dead and batch_ids(dead[0]) == [0xF2, 0xB0, 0xBC] and life(dead[0]) == 2, dead and batch_ids(dead[0]))
        run(s, m, float(w.ic.get("respawn_seconds", 5.0)) + 0.5)
        w.ic["delta_full_on_life_change"] = False
        n = len(s.sent)
        w.damage(None, ch, (ch.health or 0) + 1)
        r = [(ev, b) for _i, lbl, dest, ev, b in frames(s, n) if dest == ch.eid and "dead (LifeState 2)" in lbl]
        check("delta_full_on_life_change = false: the death is a delta (LifeState 2 by 0x6, no bundle)",
              ch.alive is False and r and not full(r) and any(ev == 6 and life(b) == 2 for ev, b in r),
              [(hex(ev), batch_ids(b) if ev == 4 else "") for ev, b in r])
        run(s, m, float(w.ic.get("respawn_seconds", 5.0)) + 0.5)
        # Session._tick itself in delta mode, on a stub session: the champion's walk, a bot's throttle and fog flip
        w.ic["delta_full_on_life_change"] = True
        sess = SimpleNamespace(ic=w.ic, cfg={"timing": {"idle_resend": 5.0}}, log=lambda t: None,
                               user=SimpleNamespace(send=lambda d, label=None: s.send(label, d), closed=False),
                               match=SimpleNamespace(world=w, director=None, mode=None, in_world=True, mode_error=False,
                                                     last_tick=0.0, last_sent=time.monotonic(), linked=True))
        sess._champion_vitals = Session._champion_vitals
        sess._player_bundle = lambda *a, **k: b""
        sess._missile_motion = lambda ww, ent: Session._missile_motion(sess, ww, ent)
        ch.attack_target = bot.attack_target = None
        ch.dest, ch.path = [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]], []
        bot.dest, bot.path = [bot.pos[0] + 3.0, bot.pos[1], bot.pos[2]], []
        n = len(s.sent)
        for _ in range(4):
            time.sleep(0.02)
            Session._tick(sess)
        rc, rb = to(s, n, ch.eid), to(s, n, bot.eid)
        hid = next((p[2] for p in bot.extra_props if p[0] == 0x90F), 0)
        bot.extra_props = [p for p in bot.extra_props if p[0] != 0x90F] + [(0x90F, KIND_BOOL, 0 if hid else 1)]
        n = len(s.sent)
        time.sleep(0.02)
        Session._tick(sess)                                  # the bot walks on: changed, but not motion_due
        rb2 = to(s, n, bot.eid)
        check("Session._tick (delta): the champion walks by 0xB0-only states every tick; a walking bot gets one state at "
              "its throttle (motion_due), then its fog flip 0x90F by 0x6 with no state", len(only_b0(rc)) >= 3
              and not full(rc) and len(only_b0(rb)) == 1 and not full(rb) and has(rb2, 6, 0x90F) and not only_b0(rb2),
              (len(only_b0(rc)), len(full(rc)), len(only_b0(rb)), [hex(ev) for ev, _b in rb2]))
        ch.dest = bot.dest = None
        # Session._encounter_property with [ics] player_rebind "bundle": the champion's full bundle again (its stub here),
        # then the encounter events; in delta mode followed by the unit-flag toggles (nothing else would re-set them)
        rebind = SimpleNamespace(ic=w.ic, _objects=lambda link: w.bundle(ch),
                                 send_many=lambda pairs: [s.send(lbl, d) for lbl, d in pairs])
        n = len(s.sent)
        Session._encounter_property(rebind, SimpleNamespace(world=w, encounter=0x40000C82), "bundle")
        lbls = s.labels(n)
        flags8 = [i for i, lbl in enumerate(lbls) if "champion unit flags 8" in lbl]
        check("delta: a player_rebind \"bundle\" (a full champion bundle) is followed by vital_notices_on's unit-flag "
              "toggles", full(to(s, n, ch.eid)) and flags8 and flags8[-1] > max(
                  i for i, lbl in enumerate(lbls) if "0x100001d3" in lbl), lbls)
        w.ic["object_update_mode"] = "bundle"
        n = len(s.sent)
        ch.gold += 5.0
        w.refresh_champion("bundle mode probe")
        w.update(turret, "bundle mode probe")
        r = to(s, n, ch.eid) + to(s, n, turret.eid)
        check("object_update_mode = \"bundle\": every update is the full 0x4 again (fase3-ie)", len(full(r)) == 2
              and not only_b0(r), [batch_ids(b) for ev, b in r if ev == 4])
    finally:
        cfg["ics"].update(saved)


SWEEP_KEYS = ("match_clock_follows_wall", "attack_waits_for_cast", "bot_cast_clears_attack", "bot_skill_waits_basic",
              "bot_skill_waits_cast", "bot_cast_needs_taker", "bot_untaken_skill_backoff", "bot_turret_aggro_retreat",
              "bot_dive_health", "bot_rank_order_all_slots", "match_income_from_start", "kill_feed_shows_credit",
              "raider_warn_when_free", "rank_min_levels", "rank_level_rule", "match_start_ranks", "credits_per_second",
              "match_camp_centre", "bot_cast_stop_state", "cast_stop_state")


def log_sweep(cfg, data):
    """2026-10-28 15:00 (tester report 2026-10-28 15:00; docs/re-notes/test-2026-10-28-1439-sweep.md): the log sweep's
    fixes S2 and S4-S10 (Crime Alley v AI against AI Atomic Wonder Woman, as in the tester's run). S1 / S3 (the record
    lookups) are checked in tests/test_ics.py."""
    print("log sweep (test-2026-10-28-1439-sweep.md)")
    import copy
    saved = {k: copy.deepcopy(cfg["ics"].get(k)) for k in SWEEP_KEYS}
    for k in SWEEP_KEYS:                    # the defaults under test, whatever config.toml sets
        cfg["ics"][k] = copy.deepcopy(config.DEFAULTS["ics"][k])
    try:
        _log_sweep(cfg, data)
    finally:
        for k, v in saved.items():
            if v is None:
                cfg["ics"].pop(k, None)
            else:
                cfg["ics"][k] = v


def _sweep_bot_match(cfg, data, logs):
    s = FakeSession()
    spawn = pvp.spawn_point(0x40000C82, 1)
    w = World(data, cfg, 0x40000C82, spawn, send=s.send, schedule=s.schedule, log=logs.append)
    nav = pvp.navgrid(data, 0x40000C82, spawn[1:3])
    w.nav = nav.copy() if nav else None
    w.ground_z = spawn[6]
    w.create_champion(cfg["ics"]["champion"], spawn)
    w.in_world = True
    m = pvp.start_match(w, s, 0x40000C82, [
        {"iid": 1, "name": "Player", "team": 1, "index": 0, "champion": cfg["ics"]["champion"], "bot": False},
        {"iid": 0x0200000000F00000, "name": "Bot 0", "team": 2, "index": 0, "champion": 0x400003EC, "bot": True}])
    bot = next(p.agent for p in m.score.players if p.bot and p.agent is not None)
    return s, w, m, bot


def client_rank_ok(slot, rank, level, own=None):
    """The client's InqCanRankSkill level rule (WLib 0x94E4, skill-rank-levels.md), written out independently of ics:
    the skill's array 0x1000099C when it has the rank, else R 6/10/14/18 and every other slot 1/3/6/9."""
    if own and 1 <= rank <= len(own):
        return level >= own[rank - 1]
    table = [6, 10, 14, 18] if slot == 4 else [1, 3, 6, 9]
    return level >= table[rank - 1]


def rank_levels_1_to_19(cfg, data):
    """2026-10-30 tester report (level 19: the R's "+" and Recommended stayed, nothing ranked): every champion variant
    levels 1 -> 19 (level_cap) spending each point as its build order (0x1000034B) says, the order the client's
    Recommended follows; the server must accept each of them, end with 0 points and 4/4/4/4/3, and agree with the
    client's level rule at every level and slot."""
    print("skill ranks: levels 1 -> 19 for every champion (skill-rank-levels.md)")
    logs = []
    s, w, m, _bot = _sweep_bot_match(cfg, data, logs)
    ch = w.champion
    cap = int(w.ic.get("level_cap", 19))
    check("rank levels: level_cap is 19 (the client's InqLevelCap default; 19 points)", cap == 19, cap)
    variants = []
    for c in data.roster:
        for v in [c["variant"]] + [x["variant"] for x in c.get("costume_info") or []]:
            if v not in variants:
                variants.append(v)
    own_tables = {}
    bad_order, bad_end, disagree, refused = [], [], [], []
    for v in variants:
        own = data.skill_rank_levels(v)
        if own:
            own_tables[v] = own
        order = [int(x) for x in data.loadout(v).get("skill_order") or ()]
        ch.class_id, ch.kit = v, data.kit(v)
        ch.ranks = {0: 1}
        ch.level, ch.skill_points = 1, int(w.ic.get("match_start_skill_points", 1))
        for lv in range(1, cap + 1):
            if lv > 1:
                ch.level, ch.skill_points = lv, ch.skill_points + 1
            for slot in range(1, 6):
                nxt = ch.ranks.get(slot, 0) + 1
                if nxt > w.max_rank(slot) or slot not in ch.kit:
                    continue
                theirs = client_rank_ok(slot, nxt, lv, own.get(slot))
                ours = w.rank_refusal(ch, slot) is None
                if theirs != ours:
                    disagree.append((hex(v), lv, slot, nxt, ours, theirs))
            slot = order[lv - 1] if lv - 1 < len(order) else None
            if slot is None:
                bad_order.append((hex(v), lv, "no entry"))
                continue
            if not w.rank_skill(slot):
                refused.append((hex(v), lv, slot, w.rank_refusal(ch, slot)))
        ranks = tuple(ch.ranks.get(k, 0) for k in (1, 2, 3, 4, 5))
        if ch.skill_points != 0 or ranks != (4, 4, 4, 4, 3):
            bad_end.append((hex(v), ch.skill_points, ranks))
    check(f"rank levels: {len(variants)} variants (54 champions) checked", len(variants) >= 150, len(variants))
    check("rank levels: every build order (the client's Recommended) is accepted point by point, levels 1-19",
          not refused and not bad_order, (refused[:5], bad_order[:5]))
    check("rank levels: level 19 ends with 0 points and ranks 4/4/4/4/3 for every variant", not bad_end, bad_end[:5])
    check("rank levels: the server's rule equals the client's at every level / slot / next rank", not disagree,
          disagree[:5])
    ga = next((t for vv, t in own_tables.items() if data.champion_name(vv)[0] == "Green Arrow"), None)
    check("rank levels: the data's own tables are read (Green Arrow R [1, 6, 11, 16], Starro E [2])",
          ga == {4: [1, 6, 11, 16]} and any(t == {3: [2]} for t in own_tables.values()), own_tables)

    # the cause: the fase3-gz rule left the 19th point unspendable (4th R rank at 20 > level_cap 19)
    w.ic["rank_levels_from_client"] = False
    ch.class_id, ch.kit = cfg["ics"]["champion"], data.kit(cfg["ics"]["champion"])
    ch.ranks = {0: 1, 1: 4, 2: 4, 3: 4, 4: 3, 5: 3}
    ch.level, ch.skill_points = 19, 1
    check("rank levels: rank_levels_from_client = false reproduces the report (R rank 4 refused at 19, 1 point left)",
          not w.rankable(4) and not any(w.rankable(sl) for sl in range(6)), w.rank_refusal(ch, 4))
    w.ic["rank_levels_from_client"] = True
    check("rank levels: with the client's rule the 4th R rank goes at level 19", w.rankable(4), w.rank_refusal(ch, 4))
    ch.level = 17
    n, logs[:] = len(s.sent), []
    w._rank_refused_at = -10.0
    ok = w.rank_skill(4)
    check("rank levels: a refused rank is logged with its reason", not ok and any(
        "refused, rank 4 needs level 18 (level 17" in t for t in logs), logs[-2:])
    check("rank levels: ... and the champion's rank state goes again (rank_refused_refresh)", len(s.sent) > n,
          s.labels(n))

    # bots: the same rule, every point spent by 19
    bot_end = []
    for v in variants[::7]:
        s2, w2, m2, b2 = _sweep_bot_match(cfg, data, [])
        br = m2.bots.brains[0]
        b2.class_id, b2.kit = v, data.kit(v)
        b2.ranks, b2.skill_points = {0: 1}, 1
        for lv in range(1, cap + 1):
            if lv > 1:
                b2.level, b2.skill_points = lv, b2.skill_points + 1
            for _ in range(3):
                if b2.skill_points <= 0:
                    break
                br.rank_up()
        if b2.skill_points:
            bot_end.append((hex(v), b2.skill_points, dict(b2.ranks)))
    check("rank levels: bots spend every point by level 19 too", not bot_end, bot_end[:5])


def _log_sweep(cfg, data):
    far = time.time() + 1e6

    # ---- S2: the match clock keeps a stall (2.77 s at AWW's first Savage Sweep) ----
    s, w, m = make(cfg, data, 0x40000C82)
    t0, fired = m.t, []
    m.later(2.5, lambda: fired.append(m.t))
    s.clock += 2.8
    m.tick(2.8, s.clock)
    t1 = m.t
    s.clock += 0.1
    m.tick(0.1, s.clock)
    check("S2: a 2.8 s tick moves the match clock 2.8 s (was 1.0) and fires the timer due at +2.5 s in that tick; "
          "+0.1 s = 2.9 s in all", abs(t1 - t0 - 2.8) < 1e-6 and abs(m.t - t0 - 2.9) < 1e-6 and fired == [t1],
          (t1 - t0, m.t - t0, fired))
    m.ic["match_clock_follows_wall"] = False
    t2 = m.t
    s.clock += 2.8
    m.tick(2.8, s.clock)
    check("S2: match_clock_follows_wall = false: a 2.8 s tick moves it 1.0 s (fase3-ie)", abs(m.t - t2 - 1.0) < 1e-6,
          m.t - t2)

    # ---- S8: no passive credits before the start ----
    s, w, m = make(cfg, data, 0x40000C82)
    ch = w.champion
    g0 = ch.gold
    run(s, m, 10.0)
    held = ch.gold == g0 and getattr(w, "income_hold", False) and not m.begun
    run(s, m, 3.5)
    g1 = ch.gold
    run(s, m, 10.0)
    check("S8: no passive credits during the intro / countdown; from the start credits_per_second (2 / s)",
          held and m.begun and not w.income_hold and abs((ch.gold - g1) - 20.0) < 1.0, (g0, g1, ch.gold, m.begun))
    cfg["ics"]["match_income_from_start"] = False
    s, w, m = make(cfg, data, 0x40000C82)
    g0 = w.champion.gold
    run(s, m, 5.0)
    check("S8: match_income_from_start = false: paid before the start (fase3-ie)", w.champion.gold > g0 + 9.0,
          w.champion.gold - g0)
    cfg["ics"]["match_income_from_start"] = True

    # ---- the bot match ----
    logs = []
    s, w, m, bot = _sweep_bot_match(cfg, data, logs)
    run(s, m, 14.0)
    ch = w.champion
    brain = m.bots.brains[0]
    brain.next_decision = float("inf")              # the test drives the brain
    bot.ranks.update({1: 0, 2: 1, 3: 1, 4: 0})
    for slot in (1, 4, 7, 8):
        bot.ready_at[slot] = far
    bot.safe_zone = ch.safe_zone = False
    p = brain.route[len(brain.route) // 2]
    ch.pos = [p[0], p[1], ch.pos[2]]
    bot.pos = [p[0] + 1.5, p[1], bot.pos[2]]
    bot.dest, bot.path, bot.attack_target = None, [], None
    casts = []
    orig_cast = w.cast

    def rec(ent, slot, target, point):
        ok = orig_cast(ent, slot, target, point)
        casts.append((ent, slot, ok, w.casting_skill(ent)))
        return ok
    w.cast = rec

    # S4: the skill order clears the attack target; no basic attack and no other skill inside the cast
    bot.attack_target = ch
    n = len(s.sent)
    ok = brain.try_skill(3, ch, True, s.clock)
    check("S4: a bot's Savage Sweep clears its attack target first (as the player's order) and is in its cast",
          ok and bot.attack_target is None and w.casting_skill(bot), (ok, bot.attack_target))
    labels = s.labels(n)
    stop = next((i for i, lbl in enumerate(labels) if "stops to cast" in lbl and bot.name in lbl), None)
    scr = next((i for i, lbl in enumerate(labels) if ("0x8d" in lbl or "0x2073" in lbl) and bot.name in lbl), None)
    check("S4/S5: a taken activation keeps its stop state before the cast's scriptlets (deep-scan-animations.md 5)",
          stop is not None and scr is not None and stop < scr, (stop, scr, labels[:6]))
    bot.attack_target = ch                          # an attack order while the cast runs
    del casts[:]
    brain.fight(ch, s.clock)                         # Smite is ready: no skill while the sweep casts
    inside = []
    for _ in range(25):
        if not w.casting_skill(bot):
            break
        run(s, m, 0.1, 0.1)
        inside.append(w.casting_skill(bot))
    during = [c for c in casts if c[0] is bot]
    check("S4: while the sweep casts, no basic attack (slot 0) and no other skill start (bot_skill_waits_cast)",
          inside and not any(c[1] == 0 for c in during if c[3]) and not any(c[1] for c in during),
          [(c[1], c[2], c[3]) for c in during])
    run(s, m, 0.5, 0.1)
    check("S4: the basic attack starts once the cast is over", any(c[0] is bot and c[1] == 0 for c in casts),
          [(c[1], c[2], c[3]) for c in casts])
    basic = bot.skill_insts.get(0)
    in_cast = brain.basic_in_cast()
    del casts[:]
    brain.fight(ch, s.clock)
    skills = [c[1] for c in casts if c[0] is bot and c[1]]
    bot.basic_cast_at = time.time() - 2.0
    capped = not brain.basic_in_cast()
    check("S4: while its basic attack is in its cast the brain casts no skill (Smite ready); at most "
          "bot_skill_waits_basic (1.5) s after the attack started", in_cast and getattr(basic, "casting", 0) > 0
          and not skills and capped, (in_cast, getattr(basic, "casting", None), skills, capped))

    # S5: AWW's W Smite 0x34000255 while its buff 0x480006FD is up
    bot.attack_target = None
    bot.dest, bot.path = None, []
    run(s, m, 1.5, 0.1)
    bot.ready_at.pop(2, None)
    broadcasts = []
    orig_raise = R.raise_event

    def rraise(world, owner, ev, params=None, *a, **k):
        if ev == 0x10000196:
            broadcasts.append(dict(params or {}))
        return orig_raise(world, owner, ev, params, *a, **k)
    R.raise_event = rraise
    try:
        ok1 = w.cast(bot, 2, None, None)
        n1 = len(broadcasts)
        bot.last_cast_at.pop(2, None)            # the run's casts came 0.7 s apart (past cast_repeat_guard)
        ok2 = w.cast(bot, 2, None, None)
        n2 = len(broadcasts)
    finally:
        R.raise_event = orig_raise
    back = bot.__dict__.get("skill_backoff", {}).get(2, 0.0)
    check("S5: Smite taken, then (buff up) not taken: no cast, no 'skill used' broadcast 0x10000196, the slot rests "
          "bot_untaken_skill_backoff s", ok1 and not ok2 and n1 == 1 and n2 == 1 and back > time.time() + 0.5,
          (ok1, ok2, n1, n2, back - time.time()))
    bot.attack_target = None
    brain.fight(ch, s.clock)
    check("S5: the brain then attacks (the basic attack uses the buff up) instead of casting Smite again",
          bot.attack_target is ch, bot.attack_target)
    m.ic["bot_cast_needs_taker"] = False
    bot.__dict__.pop("skill_backoff", None)
    bot.last_cast_at.pop(2, None)
    ok3 = w.cast(bot, 2, None, None)
    check("S5: bot_cast_needs_taker = false: the ignored use counts as a cast (fase3-ie)", ok3)
    m.ic["bot_cast_needs_taker"] = True
    w.cast = orig_cast

    # ---- S6: an enemy turret targets the bot ----
    turret = next(mu for mu in m.structures if mu.team == ch.team and mu.role == "turret" and mu.ent.alive)
    bot.ready_at[2] = bot.ready_at[3] = far
    tx, ty = turret.ent.pos[0], turret.ent.pos[1]
    hx, hy = brain.home()[:2]
    d = math.hypot(hx - tx, hy - ty) or 1.0
    px, py = tx + (hx - tx) / d * (turret.range - 1.0), ty + (hy - ty) / d * (turret.range - 1.0)
    near = w.nav.nearest(px, py, max_r=3.0) if w.nav is not None else (px, py)
    bot.pos = [near[0], near[1], bot.pos[2]]
    bot.health = bot.max_health
    brain.state, brain.goal = "fight", None
    turret.target = bot
    brain.decide(s.clock)
    goal = brain.goal
    check("S6: a bot an enemy turret targets backs off (state evade, no attack target, its goal out of the turret's "
          "range)", brain.state == "evade" and bot.attack_target is None and goal is not None
          and math.hypot(goal[0] - tx, goal[1] - ty) > turret.range + 1.5,
          (brain.state, bot.attack_target, goal, turret.range))
    brain.next_decision = 0.0
    states = set()
    for _ in range(40):
        run(s, m, 0.1, 0.1)
        states.add(brain.state)
        if bot.distance_to(turret.ent) > turret.range + 1.5:
            break
    check("S6: ... and walks out of the turret's range, backing off", bot.distance_to(turret.ent) > turret.range + 1.5
          and bot.alive and "evade" in states, (bot.distance_to(turret.ent), turret.range, states))
    brain.next_decision = float("inf")
    # the dive rule: GL low under his turret with an allied minion of the bot there (the old rule then allowed the chase)
    ch.pos = [tx + 1.0, ty, ch.pos[2]]
    ch.health = ch.max_health * 0.1
    bot.pos = [ch.pos[0] + 3.0, ch.pos[1], bot.pos[2]]
    minion = m.units.spawn(m.map["minions"]["melee"], (tx + 1.5, ty + 1.0), bot.team, "minion", name="test minion")
    bot.health = bot.max_health * 0.5
    low = brain.pick_target()
    bot.health = bot.max_health * 0.9
    # 2026-10-30 (tester report 15:30): GL at 10 % is within two of AWW's hits here, a near-certain kill the bot may now
    # take under a free turret (bot_dive_kill_share; checked in bot_shop_towers_end_1530); off for this fase3-ij check
    kill_share = m.ic.get("bot_dive_kill_share", 0.2)
    m.ic["bot_dive_kill_share"] = 0.0
    free = brain.pick_target()                  # fase3-ij bot_dive_needs_tank: the turret is not busy with a minion
    m.ic["bot_dive_kill_share"] = kill_share
    turret.target = minion.ent
    high = brain.pick_target()
    turret.target = None
    check("S6: an enemy champion under an enemy turret is chased only with bot_dive_health (0.7) of the bot's health "
          "and (fase3-ij) only while that turret shoots one of the bot's minions",
          low is not ch and free is not ch and high is ch,
          (getattr(low, "name", low), getattr(free, "name", free), getattr(high, "name", high)))
    m.units.remove(minion)
    w.remove(minion.ent, "test minion gone")
    ch.health = ch.max_health

    # ---- S9: a turret's last blow after GL's hit: the kill feed and the announcer name GL ----
    n = len(s.sent)
    m._on_hit(bot, ch)
    m.t += 5.0
    m._champion_died(bot, turret.ent)
    run(s, m, 0.3, 0.1)
    feed = [d for lbl, d in s.sent[n:] if "(0x217a)" in lbl]
    lbls = [lbl for lbl in s.labels(n) if "(0x217a)" in lbl]
    voice = [d for lbl, d in s.sent[n:] if "(0x2039)" in lbl and "announcer event" in lbl]
    check("S9: a kill finished by GL's turret 5 s after GL's hit: the kill feed names GL (0x217A killer IID)",
          lbls and f"by {ch.name}" in lbls[0] and struct.pack("<Q", ch.eid) in feed[0], lbls)
    check("S9: ... and the announcer's 0x2039 carries the champions' entity fields (source class 0x10000814)",
          voice and struct.pack("<I", 0x10000814) in voice[0], len(voice))
    m.ic["kill_feed_shows_credit"] = False
    run(s, m, 1.0)
    n = len(s.sent)
    m._on_hit(bot, ch)
    m._champion_died(bot, turret.ent)
    lbls = [lbl for lbl in s.labels(n) if "(0x217a)" in lbl]
    check("S9: kill_feed_shows_credit = false: the feed names the turret (fase3-ie)",
          lbls and f"by {turret.ent.name}" in lbls[0], lbls)
    m.ic["kill_feed_shows_credit"] = True

    # ---- S7: the bot's rank order (AWW 0x400003EC: [3, 1, 2, 3, 5, 4, 2, 3, ...]) ----
    def level_up(to, use_all):
        s2, w2, m2, b2 = _sweep_bot_match(cfg, data, [])
        m2.ic["bot_rank_order_all_slots"] = use_all
        br = m2.bots.brains[0]
        r_at = None
        for lv in range(1, to + 1):
            if lv > 1:
                w2.bot_level(b2, lv)
            for _ in range(3):
                if b2.skill_points <= 0:
                    break
                br.rank_up()
            if r_at is None and b2.ranks.get(4, 0) >= 1:
                r_at = lv
        return {k: v for k, v in b2.ranks.items() if k in (1, 2, 3, 4, 5)}, r_at
    ranks, r_at = level_up(8, True)
    check("S7: levels 1-8 follow the loadout's order with the trait counted: {3: 3, 1: 1, 2: 2, 5: 1, 4: 1}, R at 6",
          ranks == {3: 3, 1: 1, 2: 2, 5: 1, 4: 1} and r_at == 6, (ranks, r_at))
    ranks, r_at = level_up(8, False)
    check("S7: bot_rank_order_all_slots = false reproduces the run (trait at 5, 6, 7; R at 8)",
          ranks.get(5) == 3 and r_at == 8, (ranks, r_at))
    ranks, r_at = level_up(11, True)
    check("S7: a gated entry is retried, not skipped (R rank 2 at 11 under rank_min_levels [6, 11, ...])",
          ranks.get(4) == 2, ranks)

    # ---- S10: the Raider's warnings wait for its pad (the fase3-ie middle camp, [ics] match_camp_centre) ----
    cfg["ics"]["match_camp_centre"] = True
    try:
        s, w, m = make(cfg, data, 0x40000C82)
    finally:
        cfg["ics"]["match_camp_centre"] = False
    c = (m.ic.get("match_raider") or {}).get("crime_alley") or {}
    at = float(c.get("at", 300.0))
    run(s, m, 13.0 + at + 2.0, step=1.0)
    middle = next(cp for cp in m.camps if cp.spec.get("middle"))
    warn = [lbl for lbl in s.labels() if "announcer line 0x2b8" in lbl or "announcer line 0x2bb" in lbl]
    raider = [e for e in w.entities.values() if getattr(getattr(e, "match_unit", None), "boss", None) == "raider"]
    check("S10: the middle camp holds the Raider's pad at 302 s: no warning 696 / 699 and no Raider yet",
          any(x.ent.alive for x in middle.members) and not warn and not raider, (warn, len(raider)))
    n = len(s.sent)
    t_clear = m.t
    for x in middle.members:
        if x.ent.alive:
            w.damage(w.champion, x.ent, (x.ent.health or 0) + 1)
    run(s, m, 2.0)
    first = [lbl for lbl in s.labels(n) if "announcer line 0x2b8" in lbl]
    run(s, m, 30.0)
    raider = [e for e in w.entities.values() if getattr(getattr(e, "match_unit", None), "boss", None) == "raider"]
    second = [lbl for lbl in s.labels(n) if "announcer line 0x2bb" in lbl]
    check("S10: once the pad is cleared: warning 696 at once, 699 20 s later, the Raider 30 s after the clear",
          first and second and len(raider) == 1, (first, second, len(raider), m.t - t_clear))
    m._spawn_camp(middle)                       # the pad taken again
    m.ic["raider_warn_when_free"] = False
    n = len(s.sent)
    m.bosses._schedule_raider(c, m.t + 31.0, (80.0, 97.66))
    # 2026-10-30: the announcer queue may hold the -10 s line a few seconds behind other lines (no slack before)
    run(s, m, 26.0)
    old = [lbl for lbl in s.labels(n) if "announcer line 0x2b8" in lbl or "announcer line 0x2bb" in lbl]
    check("S10: raider_warn_when_free = false: the warnings go on schedule with the pad taken (fase3-ie)",
          len(old) == 2 and any(x.ent.alive for x in middle.members), old)


LEASH_KEYS = ("match_leash_rules", "match_minion_chase_margin", "match_minion_leash_anchor", "match_minion_leash_ignore",
              "match_minion_return_max", "match_minion_lane_rejoin", "bot_leash_rules", "bot_dive_needs_tank",
              "bot_leash", "bot_chase_margin", "bot_leash_ignore", "turret_warning_flags_in_bundle",
              "spawned_skip_classes", "start_scriptlet_hold")


def fog_ring_announcer(cfg, data):
    """Tester report 2026-10-29 17:45 (docs/re-notes/ca-fog-ring-announcer.md): the champion is Character | Player,
    allied vision sources ignore vision blockers (0x100008CE), announcer items go one at a time."""
    print("fog blockers / ring Player flag / announcer queue (tester report 2026-10-29 17:45)")
    defaults = config.DEFAULTS["ics"]
    for k in ("champion_player_flag", "vision_through_blockers", "vision_through_blockers_property", "announcer_queue", "announcer_queue_gaps",
              "announcer_queue_max_wait", "announcer_queue_kill_events"):
        cfg["ics"][k] = copy.deepcopy(defaults[k])
    s, w, m = make(cfg, data, 0x40000C82)
    n0 = len(s.sent)
    w.vital_notices_on()
    sent = s.sent[n0:]
    flags = [d for lbl, d in sent if lbl.startswith("champion unit flags 8")]
    check("ring: the champion's unit flags change carries Player 0x200000 | Character 8",
          bool(flags) and struct.pack("<I", 0x200008) in flags[-1], [lbl for lbl, _ in sent][:12])
    check("fog: the champion gets 0x100008CE (vision ignores blockers) by a set modifier",
          any("modifier 0x100008ce op 6" in lbl for lbl, _ in sent), [lbl for lbl, _ in sent][:12])
    # 2026-10-29 18:31 (ca-fog-stealth-hover.md 1): the attribute's base value by 0x6 before the modifier (an attribute
    # with no base value ignores its modifiers, 0x973730)
    labels = [lbl for lbl, _ in sent]
    prop = [i for i, lbl in enumerate(labels) if lbl.endswith("0x100008ce = True (0x6)")]
    mod = [i for i, lbl in enumerate(labels) if "modifier 0x100008ce op 6" in lbl]
    check("fog: the champion also gets the property 0x100008CE = true by 0x6, before the modifier",
          bool(prop) and bool(mod) and prop[0] < mod[0]
          and any(struct.pack("<I", 0x100008CE) in d for lbl, d in sent if lbl.endswith("(0x6)")), labels[:14])
    run(s, m, 2.0)
    ally = [mu for mu in m.structures if mu.team == m.local_team()]
    check("fog: allied structures get 0x100008CE too", bool(ally) and all(
        getattr(mu.ent, "sees_through_blockers", False) for mu in ally if mu.ent.alive and mu.vision > 0),
          [(mu.ent.name, getattr(mu.ent, "sees_through_blockers", False)) for mu in ally])
    n0 = len(s.sent)
    m.line(0x2A0)
    m.line(0x2A1)
    first = s.labels(n0)
    run(s, m, 3.0)
    later = s.labels(n0)
    check("announcer: two lines at once -> the second waits for the gap",
          sum("0x2a1 channel" in x for x in first) == 0 and sum("0x2a0 channel" in x for x in first) == 1
          and sum("0x2a1 channel" in x for x in later) == 1, later)
    cfg["ics"]["announcer_queue"] = False
    s, w, m = make(cfg, data, 0x40000C82)
    n0 = len(s.sent)
    m.line(0x2A0)
    m.line(0x2A1)
    check("announcer: announcer_queue = false sends both at once",
          sum("channel" in x for x in s.labels(n0)) == 2, s.labels(n0))
    cfg["ics"]["announcer_queue"] = True



def ring_fog_bundles(cfg, data):
    """Tester report 2026-10-29 19:55 (docs/re-notes/ca-ring-fog-bundles.md): the champion's Player flag and the
    vision sources' 0x100008CE ride in their own bundles (a full bundle's 0xBC removed the 0x6-only values), and the
    server's sight line is not stopped by the squares objects block on the match navmesh."""
    print("ring flags / fog attribute in bundles, sight line through objects (tester report 2026-10-29 19:55)")
    from ics.world import Entity
    defaults = config.DEFAULTS["ics"]
    keys = ("champion_player_flag", "champion_flags_in_bundle", "vision_through_blockers",
            "vision_through_blockers_property", "vision_through_blockers_in_bundle", "fog_line_through_objects",
            "fog_allied_vision", "fog_vision_radius")
    for k in keys:
        cfg["ics"][k] = copy.deepcopy(defaults[k])
    s, w, m = make(cfg, data, 0x40000C82)
    w.vital_notices_on()
    b = w.bundle(w.champion)
    flags = struct.pack("<I", 0x1000019D) in b and struct.pack("<I", 0x200008) in b
    attr = struct.pack("<I", 0x100008CE) in b
    check("ring: after vital_notices_on the champion's own bundle carries unit flags 0x200008 (Character | Player) and "
          "0x100008CE, so its 0xBC no longer removes them", flags and attr, (flags, attr))
    run(s, m, 2.0)
    ally = [mu for mu in m.structures if mu.team == m.local_team() and mu.ent.alive and mu.vision > 0]
    check("fog: allied structures keep 0x100008CE in their bundle properties", bool(ally) and all(
        any(p[0] == 0x100008CE for p in mu.ent.extra_props) for mu in ally), [mu.ent.name for mu in ally])
    cfg["ics"]["champion_flags_in_bundle"] = False
    cfg["ics"]["vision_through_blockers_in_bundle"] = False
    s2, w2, m2 = make(cfg, data, 0x40000C82)
    w2.vital_notices_on()
    b2 = w2.bundle(w2.champion)
    check("ring: champion_flags_in_bundle / vision_through_blockers_in_bundle = false: by 0x6 only, as fase3-im",
          struct.pack("<I", 0x1000019D) not in b2 and struct.pack("<I", 0x100008CE) not in b2)
    cfg["ics"]["champion_flags_in_bundle"] = True
    cfg["ics"]["vision_through_blockers_in_bundle"] = True

    # the sight line behind our own lane turret (65, 77.5; a 3.2 m blocked square on the match navmesh)
    cfg["ics"]["fog_allied_vision"] = False            # the champion as the only source (the turret sees by range)
    cfg["ics"]["fog_sight_line"] = True                # the navmesh line on (fog_minimap_category tests "auto")
    results = []
    for through in (True, False):
        cfg["ics"]["fog_line_through_objects"] = through
        s3, w3, m3 = make(cfg, data, 0x40000C82)
        ch = w3.champion
        ch.pos = [59.5, 77.5, ch.pos[2]]
        foe = w3.add(Entity(w3.new_id(), "test foe", 0x40000BF8, [70.5, 77.5, ch.pos[2]], team=2, kind="unit"))
        blocked = not w3.nav.line_clear(ch.pos, foe.pos)
        w3.fog()
        results.append((blocked, getattr(foe, "hidden", False)))
    cfg["ics"]["fog_allied_vision"] = defaults["fog_allied_vision"]
    cfg["ics"]["fog_line_through_objects"] = defaults["fog_line_through_objects"]
    cfg["ics"]["fog_sight_line"] = defaults["fog_sight_line"]
    check("fog: an enemy 11 m away behind our lane turret is seen (fog_line_through_objects); false = the turret's "
          "blocked square hides it, as before", results == [(True, False), (True, True)], results)

def fog_minimap_category(cfg, data):
    """Tester report 2026-10-30 15:30 (docs/re-notes/ca-fog-minimap-category.md): out of sight an enemy lane minion and
    the enemy bot leave the minimap by note category 0x100004DA = 0 (the client rewrites 0x2A1 itself), super minions
    keep theirs, in sight the template's category comes back; inside a source's radius an enemy is seen even when the
    navmesh line crosses a hole (fog_sight_line "auto" with vision_through_blockers); a fog line per champion change."""
    print("minimap by note category, sight without the navmesh line (tester report 2026-10-30 15:30)")
    from ics.wire import KIND_ENUM, pack_property
    defaults = config.DEFAULTS["ics"]
    keys = ("vision_through_blockers", "fog_hide_minimap", "fog_minimap_always_flags", "fog_allied_vision",
            "fog_vision_radius", "fog_minimap_lever", "fog_minimap_categories", "fog_sight_line", "fog_log_champions",
            "fog_line_through_objects")
    for k in keys:
        cfg["ics"][k] = copy.deepcopy(defaults[k])
    cfg["ics"]["fog_allied_vision"] = False
    s, w, m = make(cfg, data, 0x40000C82)
    lines = []
    w.log = lines.append
    ch = w.champion
    ch.pos = [10.0, 77.5, ch.pos[2]]
    lane = m.units.spawn(0x40000BF8, (100.0, 77.5), 2, "minion", heading=0.0, name="test far minion")
    sup = m.units.spawn(0x40000C9C, (100.0, 78.5), 2, "minion", heading=0.0, name="test far super")
    bot = next((e for e in w.entities.values() if getattr(e, "bot", False) and e.team != ch.team), None)
    if bot is None:
        bot = w.create_bot_champion(ch.class_id, 2, "test bot", 0, pos=[120.0, 77.5, ch.pos[2]])
    bot.pos = [120.0, 77.5, ch.pos[2]]
    cat = lambda ent: [p[2] for p in w.properties(ent) if p[0] == 0x100004DA]     # noqa: E731
    onm = lambda ent: [p[2] for p in w.properties(ent) if p[0] == 0x2A1]          # noqa: E731
    w.fog()
    got = (lane.ent.hidden, cat(lane.ent), onm(lane.ent), sup.ent.hidden, cat(sup.ent), bot.hidden, cat(bot), onm(bot))
    check("minimap: out of sight the lane minion and the bot carry one 0x100004DA = 0 and keep 0x2A1 = 1 (the client's "
          "own value); the super minion keeps its note (9)", got == (True, [0], [1], True, [9], True, [0], [1]), got)
    k = len(s.sent)
    w.update(lane.ent, None)
    entry = pack_property(0x100004DA, KIND_ENUM, 0)
    check("minimap: the minion's next update carries 0x100004DA = 0", any(entry in d for _l, d in s.sent[k:]),
          len(s.sent) - k)
    lane.ent.pos = [12.0, 77.5, ch.pos[2]]
    bot.pos = [14.0, 77.5, ch.pos[2]]
    w.fog()
    check("minimap: back in sight the template's category returns (minion 9, bot 2), still no 0x2A1 = 0",
          (lane.ent.hidden, cat(lane.ent), bot.hidden, cat(bot)) == (False, [9], False, [2])
          and onm(bot) == [1] and onm(lane.ent) == [1],
          (lane.ent.hidden, cat(lane.ent), bot.hidden, cat(bot), onm(bot)))
    check("fog log: one line per enemy champion change (hidden, then shown in range)",
          sum(1 for t in lines if t.startswith("fog: ") and bot.name in t) == 2 and any("(in range)" in t for t in lines),
          [t for t in lines if t.startswith("fog: ")])

    # a jungle mouth: AGL at (55, 88), the enemy in the lane at (60, 81.5), 8.2 m, the navmesh line crosses a hole
    ch.pos = [55.0, 88.0, ch.pos[2]]
    lane.ent.pos = [60.0, 81.5, ch.pos[2]]
    blocked = w.nav is not None and not w.nav.line_clear(ch.pos, lane.ent.pos, through_objects=True)
    w.fog()
    shown_auto = not lane.ent.hidden
    w.ic["fog_sight_line"] = True                     # World keeps its own [ics] table
    w.fog()
    hidden_line = lane.ent.hidden
    w.ic["fog_sight_line"] = "auto"
    w.ic["vision_through_blockers"] = False
    w.fog()
    hidden_auto_off = lane.ent.hidden
    check("sight: 8.2 m from AGL behind a corner (navmesh line blocked) the enemy is shown with fog_sight_line auto; "
          "true, or auto without vision_through_blockers, hides it as before",
          blocked and shown_auto and hidden_line and hidden_auto_off, (blocked, shown_auto, hidden_line, hidden_auto_off))
    cfg["ics"]["fog_minimap_lever"] = "on_map"
    s2, w2, m2 = make(cfg, data, 0x40000C82)
    w2.champion.pos = [10.0, 77.5, w2.champion.pos[2]]
    far = m2.units.spawn(0x40000BF8, (100.0, 77.5), 2, "minion", heading=0.0, name="test far minion")
    w2.fog()
    got = ([p[2] for p in w2.properties(far.ent) if p[0] == 0x2A1], [p[2] for p in w2.properties(far.ent)
                                                                    if p[0] == 0x100004DA])
    check("minimap: fog_minimap_lever on_map: 0x2A1 = 0 and the template's category untouched, as fase3-io",
          got == ([0], [9]), got)
    for k in keys:
        cfg["ics"][k] = copy.deepcopy(defaults[k])


def fog_minimap_ring(cfg, data):
    """Tester report 2026-10-29 21:10 (docs/re-notes/ca-fog-minimap-ring.md): allied structures carry 0x100008CE in their
    creation bundle; enemies out of sight leave the minimap (0x2A1 false) except super minions; the camp heavy carries
    a minimap note and the nook pad's capturable circle is off; the ring phantom's filter patch."""
    print("fog attribute at creation, minimap visibility, camp notes, ring filter patch (tester report 2026-10-29 21:10)")
    from ics.world import Entity
    from icserver import patcher
    defaults = config.DEFAULTS["ics"]
    keys = ("vision_through_blockers", "vision_through_blockers_property", "vision_through_blockers_at_creation",
            "fog_hide_minimap", "fog_minimap_always_flags", "fog_allied_vision", "fog_vision_radius",
            "match_camp_map_note", "match_camp_map_notes", "match_nook_pad_map_note")
    for k in keys:
        cfg["ics"][k] = copy.deepcopy(defaults[k])
    s, w, m = make(cfg, data, 0x40000C82)
    mine = [mu for mu in m.structures if mu.team == m.local_team()]
    theirs = [mu for mu in m.structures if mu.team != m.local_team()]
    has = lambda mu: any(p[0] == 0x100008CE and p[2] for p in mu.ent.extra_props)      # noqa: E731
    check("fog: every allied structure's creation bundle carries 0x100008CE = true (not the enemy's)",
          mine and all(has(mu) for mu in mine) and not any(has(mu) for mu in theirs),
          [(mu.ent.name, has(mu)) for mu in m.structures])
    cfg["ics"]["vision_through_blockers_at_creation"] = False
    s1, w1, m1 = make(cfg, data, 0x40000C82)
    check("fog: vision_through_blockers_at_creation = false: no 0x100008CE before the late 0x6, as fase3-in",
          not any(any(p[0] == 0x100008CE for p in mu.ent.extra_props) for mu in m1.structures))
    cfg["ics"]["vision_through_blockers_at_creation"] = True

    def on_map(ent):
        vals = [p[2] for p in w.properties(ent) if p[0] == 0x2A1]
        return vals
    cfg["ics"]["fog_allied_vision"] = False
    cfg["ics"]["fog_minimap_lever"] = "on_map"           # the fase3-io lever (fog_minimap_category tests the default)
    s2, w2, m2 = make(cfg, data, 0x40000C82)
    w = w2
    ch = w2.champion
    ch.pos = [10.0, 77.5, ch.pos[2]]
    lane = m2.units.spawn(0x40000BF8, (100.0, 77.5), 2, "minion", heading=0.0, name="test far minion")
    sup = m2.units.spawn(0x40000C9C, (100.0, 78.5), 2, "minion", heading=0.0, name="test far super")
    bot = next((e for e in w2.entities.values() if getattr(e, "bot", False) and e.team != ch.team), None)
    if bot is None:
        bot = w2.create_bot_champion(ch.class_id, 2, "test bot", 0, pos=[120.0, 77.5, ch.pos[2]])
    bot.pos = [120.0, 77.5, ch.pos[2]]
    w2.fog()
    got = (lane.ent.hidden, on_map(lane.ent), sup.ent.hidden, on_map(sup.ent),
           bot is not None and bot.hidden, bot is not None and on_map(bot))
    check("minimap: an enemy lane minion and the enemy bot out of sight are hidden with one 0x2A1 = 0 (off the "
          "minimap); a super minion (unit flags 0x410000) is hidden but stays on it (0x2A1 = 1)",
          got == (True, [0], True, [1], True, [0]), got)
    lane.ent.pos = [12.0, 77.5, ch.pos[2]]
    w2.fog()
    check("minimap: back in sight the minion is shown with 0x2A1 = 1 again",
          lane.ent.hidden is False and on_map(lane.ent) == [1], (lane.ent.hidden, on_map(lane.ent)))
    cfg["ics"]["fog_hide_minimap"] = False
    s3, w3, m3 = make(cfg, data, 0x40000C82)
    w = w3
    w3.champion.pos = [10.0, 77.5, w3.champion.pos[2]]
    far = m3.units.spawn(0x40000BF8, (100.0, 77.5), 2, "minion", heading=0.0, name="test far minion")
    w3.fog()
    check("minimap: fog_hide_minimap = false: hidden by 0x90F only, still on the minimap (fase3-in)",
          far.ent.hidden and on_map(far.ent) == [1], (far.ent.hidden, on_map(far.ent)))
    cfg["ics"]["fog_hide_minimap"] = defaults["fog_hide_minimap"]
    cfg["ics"]["fog_allied_vision"] = defaults["fog_allied_vision"]
    cfg["ics"]["fog_minimap_lever"] = defaults["fog_minimap_lever"]

    s4, w4, m4 = make(cfg, data, 0x40000C82)
    run(s4, m4, 13.0 + 45.0 + 6.0)
    camps = [mu for mu in m4.units.by_eid.values() if mu.role == "camp" and mu.ent.alive]
    heavy = [mu for mu in camps if mu.cls == 0x40000CA1]
    small = [mu for mu in camps if mu.cls == 0x40000CA0]
    cat = lambda mu: next((p[2] for p in mu.ent.extra_props if p[0] == 0x100004DA), None)      # noqa: E731
    check("camps: each camp's heavy creature carries minimap note 9 with icon 0x13000141, the small ones none",
          heavy and small and all(cat(mu) == 9 and any(p[0] == 0x10000083 and p[2] == 0x13000141
                                                          for p in mu.ent.extra_props) for mu in heavy)
          and all(cat(mu) is None for mu in small), [(mu.ent.name, cat(mu)) for mu in camps])
    pad = getattr(m4, "nook_pad", None)
    check("camps: the nook pad (the Raider) keeps its template's capturable circle on the minimap (no 0x100004DA = 0)",
          pad is not None and not any(p[0] == 0x100004DA and p[2] == 0 for p in pad.extra_props),
          pad is not None and pad.extra_props)

    entry = [p for p in patcher.PATCHES if p[3].startswith("perception filter")]
    exe = os.path.join(cfg.game_dir, "InfiniteCrisis.exe")
    ok_bytes = None
    if entry and os.path.isfile(exe):
        with open(exe, "rb") as f:
            f.seek(entry[0][0])
            ok_bytes = f.read(len(entry[0][1])) in (entry[0][1], entry[0][2])
    check("ring: the perception filter patch (jne at va 0x852146 -> nops) is listed and matches the installed exe",
          len(entry) == 1 and entry[0][2] == bytes.fromhex("84c09090f6465801") and ok_bytes is not False,
          (entry, ok_bytes))


def street_occluder_ring(cfg, data):
    """Tester report 2026-10-29 23:03 (docs/re-notes/ca-street-occluder-ring.md): the black strip by the fence is the fog
    occluder pass against the street piece 0x2E001207 (map static #0xB8 of 13BB, 0x7EB = 7); the exe patch skips the pass
    for every source; diag --ring probes the rest of the perception filter and the ring's draw path."""
    print("street occluder exe patch, ring diag probes (tester report 2026-10-29 23:03)")
    from icserver import patcher
    entry = [p for p in patcher.PATCHES if p[3].startswith("fog occluder pass")]
    va = 0xAAE224
    ok_target = False
    if len(entry) == 1:
        off, orig, new, _desc = entry[0]
        jne = orig[4] == 0x0F and orig[5] == 0x85 and va + 10 + struct.unpack_from("<i", orig, 6)[0]
        jmp = new[0] == 0xE9 and va + 5 + struct.unpack_from("<i", new, 1)[0]
        ok_target = off == va - 0x400C00 and jne == jmp == 0xAAE36A and new[5:] == b"\x90" * 5
    check("occluder: the patch turns the cmp/jne at va 0xaae224 into a jmp to the same skip branch 0xaae36a",
          ok_target, entry)
    exe = os.path.join(cfg.game_dir, "InfiniteCrisis.exe")
    cur = None
    if entry and os.path.isfile(exe):
        with open(exe, "rb") as f:
            f.seek(entry[0][0])
            cur = f.read(len(entry[0][1]))
    check("occluder: the installed exe holds the original (or already patched) bytes there",
          cur is None or cur in (entry[0][1], entry[0][2]), cur and cur.hex())
    # the occluder body the fase3-io diag named for every source: map static #0xB8 of landblock 13BB
    pk = data.packs.pack(0xA0C112BA).data
    ws = None
    k = pk.find(struct.pack("<II", 0xB8, 0x01113BB0))
    while k >= 0 and ws is None:
        flags, typ = struct.unpack_from("<II", pk, k - 8)
        if flags & 0x0C == 0x0C and typ == 7:
            ws = struct.unpack_from("<I", pk, k + 8)[0]
        k = pk.find(struct.pack("<II", 0xB8, 0x01113BB0), k + 1)
    check("occluder: map static #0xB8 of 13BB is the street piece 0x2E001207 and its 0x7EB is 7 (a vision blocker)",
          ws == 0x2E001207 and data.record_u32(0x2E001207, 0x7EB) == 7, (ws and hex(ws), data.record_u32(0x2E001207, 0x7EB)))
    with open(os.path.join(ROOT, "tools", "diag.py"), encoding="utf-8") as f:
        src = f.read()
    check("ring: diag --ring probes the filter's base / PerceivedType / relation tests and the draw path",
          all(f"0x{a:X}:" in src for a in (0x452220, 0x45227A, 0x45228E, 0x685294, 0x6852F5, 0x68535A)))



def hover_listener_gate(cfg, data):
    """Tester report 2026-10-30 18:12 (docs/re-notes/hover-listener-iid-gate.md): no hover highlight on any minion. The
    controlled-agent handler 0xa16730 registers the 0x3CB listener 0xa5d5f0 (soft selection, outline, attack cursor) only
    for an agent whose IID top byte is not 2 (0x4daf10); the exe patch nops the jne at va 0xa16809."""
    print("hover listener gate exe patch (tester report 2026-10-30 18:12)")
    from icserver import patcher
    entry = [p for p in patcher.PATCHES if p[3].startswith("controlled agent listeners")]
    va = 0xA16807
    ok = False
    if len(entry) == 1:
        off, orig, new, _desc = entry[0]
        ok = (off == va - 0x400C00 and orig[:4] == bytes.fromhex("84c00f85")
              and va + 8 + struct.unpack_from("<i", orig, 4)[0] == 0xA168DA and new == orig[:2] + bytes([0x90]) * 6)
    check("hover: the patch nops the jne at va 0xa16809 (to 0xa168da, past the 0x3CB / LifeState listeners)", ok, entry)
    exe = os.path.join(cfg.game_dir, "InfiniteCrisis.exe")
    cur = None
    if entry and os.path.isfile(exe):
        with open(exe, "rb") as f:
            f.seek(entry[0][0])
            cur = f.read(len(entry[0][1]))
    check("hover: the installed exe holds the original (or already patched) bytes there",
          cur is None or cur in (entry[0][1], entry[0][2]), cur and cur.hex())
    names = data.scriptlet_names()
    keys = data.scriptlets(0x40000BF8)
    check("hover: a lane minion's tables hold _Selection_SoftSelection_Valid / _Invalid (0x100001E4 / 0x100001E6), "
          "the hover scriptlets 0xa4ecc0 runs", names.get(0x100001E4) == "_Selection_SoftSelection_Valid"
          and 0x100001E4 in keys and 0x100001E6 in keys, len(keys))

def ring_phantom_strip(cfg, data):
    """Tester report 2026-10-30 11:23 (docs/re-notes/ca-ring-phantom-strip.md): the fog's base bake reads terrain map layer
    0x10000002 of 13BB (0x84A of 0x820113BB -> image 0x3E00000D), whose red channel is 0 everywhere, so no area of the
    block is baked dark; diag --ring probes the ring phantom's create call / result and the units' own phantoms, and
    --fogpoly / --nofog look at the fog's polygons and turn the fog off, all at instruction starts of the exe."""
    print("ring phantom probes, fog base layer of 13BB (tester report 2026-10-30 11:23)")
    stat = data.packs.pack(0xA0C112BA).data
    k = stat.find(struct.pack("<III", 0x846, 0x846, 0x10000002))
    img = struct.unpack_from("<III", stat, k + 12) if k >= 0 else None
    ok_entry = img is not None and img[0] == img[1] == 0x849
    check("fog base: 0x820113BB's terrain map for layer 0x10000002 (0x846) names the image 0x3E00000D (0x849)",
          ok_entry and img[2] == 0x3E00000D, img)
    reds = None
    pk = data.packs.pack(0xA00002E5)
    if 0x3E00000D in pk.ids:
        for o in pk.find_all(0x3E00000D, struct.pack("<III", 64, 64, 0x15)):
            n = struct.unpack_from("<I", pk.data, o + 16)[0]
            if n == 64 * 64 * 4:
                px = struct.unpack_from("<4096I", pk.data, o + 20)
                reds = {(q >> 16) & 0xFF for q in px}
                break
    check("fog base: image 0x3E00000D is 64 x 64 A8R8G8B8 with red 0 in every texel (base bake v = 1 - R = 1: "
          "nothing baked dark)", reds == {0}, reds)
    exe = os.path.join(cfg.game_dir, "InfiniteCrisis.exe")
    want = {0xA2AAF6: "ffd0", 0xA2AAF8: "8b0d", 0x97978F: "8b06", 0xAAB4B6: "f30f104744", 0xAAE5B0: "55"}
    got = {}
    if os.path.isfile(exe):
        with open(exe, "rb") as f:
            for va, hx in want.items():
                f.seek(va - 0x400C00)
                got[va] = f.read(len(hx) // 2).hex()
    check("ring / fog diag: the new probes sit on instruction starts in the installed exe "
          "(call eax, after it, after the unit phantom's create, the fan loop, RenderFogScene)",
          not got or got == want, {hex(a): v for a, v in got.items()})
    with open(os.path.join(ROOT, "tools", "diag.py"), encoding="utf-8") as f:
        src = f.read()
    check("ring / fog diag: --ring has the create / result / unit phantom probes, --fogpoly and --nofog exist",
          all(f"0x{a:X}:" in src for a in (0x62AAF6, 0x62AAF8, 0x57978F)) and "def fog_hit" in src
          and '"--fogpoly"' in src and '"--nofog"' in src)


def strip_static_shadow_pad(cfg, data):
    """Tester report 2026-10-30 13:18 (docs/re-notes/ca-strip-static-shadow.md): the strip went away only with
    DrawStaticEntities off. diag --strip hides render nodes (bit 0x800 of node +0x220, the bit the 0x2A1 path sets) and
    switches graphics settings off; the probes sit on instruction starts; no 13BB static in the strip's area carries the
    cast-shadows flag 0x4A8 (node flag 0x400) while the server's stealth tiles do; the nook pad stands on the terrain."""
    print("strip: static render nodes, graphics settings, nook pad height (tester report 2026-10-30 13:18)")
    exe = os.path.join(cfg.game_dir, "InfiniteCrisis.exe")
    want = {0x78165C: "e87f10eaff", 0x624D67: "6800080000", 0x624A2F: "6800040000", 0x7942B5: "833d4457860100"}
    got = {}
    if os.path.isfile(exe):
        with open(exe, "rb") as f:
            for va, hx in want.items():
                f.seek(va - 0x400C00)
                got[va] = f.read(len(hx) // 2).hex()
    check("strip: model node attach calls RenderComponent 0x6226E0 at 0x78165c; 0x2A1 -> node flag 0x800, 0x4A8 -> "
          "node flag 0x400; the shadow pass tests Render.ShadowMapQuality 0x1865744 (installed exe)",
          not got or got == want, {hex(a): v for a, v in got.items() if v != want[a]})
    with open(os.path.join(ROOT, "tools", "diag.py"), encoding="utf-8") as f:
        src = f.read()
    check("diag: --strip (--franja) probes 0x38165c and steps from 0xaae5b0; settings ShadowMapQuality / SSAO / "
          "reflections / decals / lights; the fence pieces and the stealth tiles",
          '"--franja": "--strip"' in src and "bps[0x38165C]" in src and all(
              f"(0x{a:X}," in src for a in (0x1865744, 0x1865778, 0x18656D8, 0x186575A, 0x1865758))
          and all(f"0x{i:X}" in src for i in (0x24C, 0x246, 0x243)) and "0x2E000D36, 0x2E000D37" in src)

    def ws_has(ws, prop):
        for pid in (0xA00002E5, 0xA00002E6):
            pk = data.packs.pack(pid)
            if ws in pk.ids:
                for o in pk.find_all(ws, struct.pack("<I", 7)):
                    n = struct.unpack_from("<I", pk.data, o + 16)[0]
                    rec = pk.data[o:o + 20 + 64 * max(n, 1)]
                    return any(rec.find(struct.pack("<2I", prop, k)) >= 0 for k in (prop, prop | 0x40000000))
        return None
    stat = data.packs.pack(0xA0C112BA).data
    near = []
    # statics entries of 0x820113BB `flags | type | index | 0x01113BB0 | world state | x y z | quaternion`: the 4 fences
    # on the strip's north edge and the lamp west of it
    for idx in (0x24C, 0x246, 0x243, 0xD7, 0x11E):
        q = stat.find(struct.pack("<II", idx, 0x01113BB0))
        if q >= 0 and struct.unpack_from("<I", stat, q - 4)[0] == 7:
            near.append((idx, struct.unpack_from("<I", stat, q + 8)[0]))
    check("strip: the fence pieces #0x24c / 0x246 / 0x243 / 0xd7 (0x2E001324 / 12F6 / 04D7 / 097C) and the lamp #0x11e "
          "carry no cast-shadows 0x4A8; the stealth tiles 0x2E000D36 / D37 do",
          [w for _, w in near] == [0x2E001324, 0x2E0012F6, 0x2E0004D7, 0x2E00097C, 0x2E001219]
          and not any(ws_has(w, 0x4A8) for _, w in near) and ws_has(0x2E000D36, 0x4A8) and ws_has(0x2E000D37, 0x4A8),
          [(hex(i), hex(w), ws_has(w, 0x4A8)) for i, w in near])
    h = None
    at = 0x38E1A44
    if struct.unpack_from("<I", stat, at)[0] == 0x800113BB:
        h = struct.unpack_from("<H", stat, at + 0x450 + 2 * ((80 // 5) * 33 + 95 // 5))[0] * 2000 / 65535
        h2 = struct.unpack_from("<H", stat, at + 0x450 + 2 * ((80 // 5) * 33 + 100 // 5))[0] * 2000 / 65535
        h = (h, h2)
    pk = data.packs.pack(0xA00002E6)
    box = None
    for o in pk.find_all(0x2D000ADC, struct.pack("<3I", 0, 0, 0)):
        if pk.data.find(b"hk_2012", o, o + 600) >= 0:
            box = struct.unpack_from("<6f", pk.data, o + 56)
    check("nook pad: the terrain at (80, 95 / 100) is 199.98 m and the pad's model (.entity 0x2D000ADC) spans z 0 .. "
          "0.092 m from its origin", h and all(abs(v - 199.98) < 0.01 for v in h) and box
          and abs(box[2]) < 1e-6 and abs(box[5] - 0.092) < 0.001, (h, box))
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 1.0)
    pad = getattr(m, "nook_pad", None)
    check("nook pad: spawned at the nook markers' height ([ics] match_nook_pad_z 200.2; 199.98 sank its north third "
          "under the paved floor, tester 14:51)", pad is not None and abs(pad.pos[2] - 200.2) < 1e-6,
          getattr(pad, "pos", None))


def strip_two_bit_candidates(cfg, data):
    """Tester report 2026-10-30 19:46 (docs/re-notes/ca-strip-two-bit-candidates.md): the strip went away in the diag
    --strip "bit 9" step and one other bit step, so the culprit's 13BB index is 0x200 | (1 << k). The instantiated
    entries with such an index are 0x201 / 0x202 / 0x204 (crates), 0x208 (bush) and 0x240 (west fence); 0x280 is a
    type-16 start point. diag --strip2 hides them one at a time and logs the recorded count when a cycle starts."""
    print("strip: two-bit 13BB candidates, diag --strip2 (tester report 2026-10-30 19:46)")
    stat = data.packs.pack(0xA0C112BA).data
    rec = stat.find(struct.pack("<II", 0x820113BB, 0))
    while rec >= 0 and struct.unpack_from("<I", stat, rec + 16)[0] != 0x16A:
        rec = stat.find(struct.pack("<II", 0x820113BB, 0), rec + 1)
    found = {}
    o = rec
    while rec >= 0:
        o = stat.find(struct.pack("<I", 0x01113BB0), o + 1, rec + 0x18000)
        if o < 0:
            break
        fl, typ, idx = struct.unpack_from("<3I", stat, o - 12)
        if fl & 0x04 and fl < 0x100 and idx < 0x400:
            ws = struct.unpack_from("<I", stat, o + 4)[0] if fl & 0x08 else 0
            found[idx] = (typ, ws)
    two = {i: v for i, v in found.items() if i & 0x200 and bin(i).count("1") == 2}
    made = sorted(i for i, (t, _w) in two.items() if t in (7, 8, 0x15))
    check("13BB: the entries whose index is 0x200 | (1 << k) and that the client instantiates (types 7 / 8 / 21) are "
          "0x201 / 0x202 / 0x204 / 0x208 / 0x240; 0x280 is type 16",
          made == [0x201, 0x202, 0x204, 0x208, 0x240] and two.get(0x280, (0,))[0] == 16
          and two.get(0x208, (0, 0))[1] == 0x2E000800, ([hex(i) for i in made], {hex(i): v for i, v in two.items()}))
    with open(os.path.join(ROOT, "tools", "diag.py"), encoding="utf-8") as f:
        src = f.read()
    check("diag: --strip2 (--franja2) hides the candidates one at a time (#0x208 first), re-reads the IIDs when a cycle "
          "starts and logs the recorded count there (not '0 statics' at the first fog frame)",
          '"--franja2": "--strip2"' in src and "STRIP2_CANDIDATES" in src and "def strip_resolve" in src
          and all(f"(0x{i:X},)" in src for i in (0x208, 0x240, 0x201, 0x202, 0x204))
          and "starts: {n} statics of block 13BB recorded" in src
          and src.index("(0x208,)") < src.index("(0x240,)"))


def strip3_bit9_list(cfg, data):
    """Tester recording 2026-10-30 21:33 (docs/re-notes/ca-strip-two-bit-candidates.md 8): the strip went away only in
    the --strip2 bit-9 / every-static controls. diag --strip3 numbers the bit-9 statics that get a render node (the
    instantiated type-7 entries of 0x820113BB whose world state has no fracture data 0x800: breakables never pass the
    attach probe) and runs code steps + one at a time. Its table must be exactly those entries."""
    print("strip: the bit-9 statics of diag --strip3 (tester recording 2026-10-30 21:33)")
    stat = data.packs.pack(0xA0C112BA).data
    rec = stat.find(struct.pack("<II", 0x820113BB, 0))
    while rec >= 0 and struct.unpack_from("<I", stat, rec + 16)[0] != 0x16A:
        rec = stat.find(struct.pack("<II", 0x820113BB, 0), rec + 1)
    entries = {}
    o = rec
    while rec >= 0:
        o = stat.find(struct.pack("<I", 0x01113BB0), o + 1, rec + 0x18000)
        if o < 0:
            break
        fl, typ, idx = struct.unpack_from("<3I", stat, o - 12)
        if fl & 0x0C == 0x0C and fl < 0x100 and idx < 0x400 and typ == 7:
            entries[idx] = struct.unpack_from("<I4f", stat, o + 4)[:4]   # world state, x, y, z

    frac = {}

    def fractures(ws):
        if ws not in frac:
            frac[ws] = None
            for pid in (0xA000024C, 0xA000009A, 0xA00002E5, 0xA00002E6):
                pk = data.packs.pack(pid)
                if ws in pk.ids:
                    for p in pk.find_all(ws, struct.pack("<I", 7)):
                        r = pk.data[p:p + 0x400]
                        frac[ws] = any(r.find(struct.pack("<2I", 0x800, k)) >= 0 for k in (0x800, 0x40000800))
                        break
                if frac[ws] is not None:
                    break
        return frac[ws]
    bit9 = {i: v for i, v in entries.items() if i & 0x200 and not fractures(v[0])}
    with open(os.path.join(ROOT, "tools", "diag.py"), encoding="utf-8") as f:
        src = f.read()
    a = src.index("STRIP3_INFO = {")
    table = eval(src[a + len("STRIP3_INFO = "):src.index("}", a) + 1])         # noqa: S307 (our own source)
    bad = [hex(i) for i, (ws, x, y, z) in table.items()
           if i not in bit9 or bit9[i][0] != ws or max(abs(bit9[i][1] - x), abs(bit9[i][2] - y)) > 0.01]
    check("13BB: the bit-9 statics that are not breakables are the 53 of diag's STRIP3_INFO (30 x 0x2E0005D6, "
          "7 x 0x2E0012E8, 5 fence pieces 0x2E0004D6 / 4D7, ...); the breakables #0x208 / #0x246 / #0x24c are not",
          len(bit9) == 53 and set(table) == set(bit9) and not bad
          and sum(1 for v in bit9.values() if v[0] == 0x2E0005D6) == 30
          and not {0x208, 0x246, 0x24C, 0x207, 0x201} & set(bit9),
          (len(bit9), len(table), sorted(hex(i) for i in set(bit9) ^ set(table)), bad))
    check("diag: --strip3 (--franja3) numbers the recorded bit-9 statics when a cycle starts and runs a control, "
          "12 code steps (bit k = 1 / = 0, k = 0..5) and one step per static",
          '"--franja3": "--strip3"' in src and "def strip3_steps" in src and "STRIP3_CODE_BITS = 6" in src
          and "for want in (1, 0):" in src and '"ONE: #' in src
          and "steps = st[\"steps\"] = self.strip3_steps()" in src)


def agl_floor_pad_platform(cfg, data):
    """Tester report 2026-10-30 14:51 video (docs/re-notes/agl-floor-raider-pad-pct-prow.md): the champion's z stays on
    the navmesh whatever height the client clicks (path corners, standing champion, the champion + player bundle), and
    the Power Core Turrets get their platform piece (match_structure_platforms), mirrored per team, made once."""
    print("champion on the navmesh, PCT platform (tester report 2026-10-30 14:51)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 1.0)
    ch = w.champion
    ch.pos = [62.0, 76.0, 200.08]
    zs = []
    for k in range(6):
        w.walk_to(ch, [62.0 + 2.0 * (k % 3), 77.0, 200.65 + 0.15 * k])     # the creeping click heights of the run
        for _ in range(20):
            s.clock += 0.05
            w.tick(0.05, s.clock)
            s.run_due()
            zs.append(ch.pos[2])
    nav = w.nav.height(ch.pos[0], ch.pos[1])
    check("walk: every step's z is the navmesh's (clicks at 200.65 .. 201.40 over a 200.08 lane)",
          nav is not None and all(abs(z - 200.0797) < 0.01 for z in zs), (min(zs), max(zs)))
    ch.pos[2] = 201.518                                 # the run's last bundle height (15:01:42)
    ch.dest = None
    s.clock += 0.05
    w.tick(0.05, s.clock)
    check("standing: a champion left at 201.52 is put back on the navmesh at the next tick ([ics] "
          "ground_snap_standing_champion)", abs(ch.pos[2] - nav) < 0.01, ch.pos)
    path_z = None
    if w.walk_to(ch, [70.0, 77.0, 201.0]):
        path_z = [p[2] for p in [ch.dest] + ch.path]
    check("walk_to: the path corners carry the navmesh's height, not the click's 201.0 ([ics] ground_path_from_navmesh)",
          path_z and all(abs(z - 200.0797) < 0.02 for z in path_z), path_z)
    plats = [e for e in w.entities.values() if e.name.endswith("platform")]
    spec = cfg["ics"]["match_structure_platforms"]["crime_alley"]["core_turret"]
    by_team = {e.team: e for e in plats}
    pcts = {mu.team: mu.ent for mu in m.structures if mu.role == "core_turret"}
    ok = len(plats) == 2 and set(by_team) == {1, 2} and all(p.class_id == int(spec["world_state"]) for p in plats)
    yaw = math.radians(float(spec.get("yaw", 0.0)))          # 2026-10-30: the tester turned it 180 degrees
    mirrored = ok and abs(math.cos(by_team[1].heading - yaw) - 1.0) < 1e-6 and abs(math.cos(by_team[2].heading - yaw) + 1.0) < 1e-6
    under = ok and all(math.hypot(by_team[t].pos[0] - pcts[t].pos[0], by_team[t].pos[1] - pcts[t].pos[1]) < 0.01
                       for t in (1, 2) if t in pcts)
    check("PCT platform: one 0x2E000A8E per team under its Power Core Turret, team 1 facing east, team 2 west "
          "([ics] match_structure_platforms)", ok and mirrored and under,
          [(hex(p.class_id), p.team, [round(v, 2) for v in p.pos], round(p.heading, 3)) for p in plats])


def ring_bodies_strip_layers(cfg, data):
    """Tester report 2026-10-30 12:05 (docs/re-notes/ca-ring-bodies-strip-layers.md): the ring's phantom takes only
    bodies whose world-object type matches its preset mask 0xA08 (0x5bb8a0); a champion class lists no entity script,
    so nothing on the client ever holds collision on it (0x976990); 13BB's terrain index arrays cover every cell (the
    strip is no index hole); diag --ring probes the overlap-add and the holds, --layers steps the WorldRender toggles."""
    print("ring bodies, terrain index coverage, --layers (tester report 2026-10-30 12:05)")
    exe = os.path.join(cfg.game_dir, "InfiniteCrisis.exe")
    want = {0x5BB8A0: "c7415400000100c7410c080a0000", 0x638636: "8545e8", 0x976990: "55",
            0x7F1948: "68d46c5e01", 0x7F1955: "8d4630"}
    got = {}
    if os.path.isfile(exe):
        with open(exe, "rb") as f:
            for va, hx in want.items():
                f.seek(va - 0x400C00)
                got[va] = f.read(len(hx) // 2).hex()
    check("ring / layers: ring filter preset (kind 0x10000, mask 0xA08), overlap-add test, collision-hold entry, "
          "DrawLandscape = WorldRender +0x30 in the installed exe", not got or got == want,
          {hex(a): v for a, v in got.items() if v != want[a]})
    stat = data.packs.pack(0xA0C112BA).data
    at = 0x38E1A44
    rec_ok = struct.unpack_from("<I", stat, at)[0] == 0x800113BB
    cover = []
    if rec_ok:
        for base, per_patch in ((0x19D4, False), (0x49D8, True)):
            n = struct.unpack_from("<I", stat, at + base - 4)[0]
            idx = struct.unpack_from("<%dH" % n, stat, at + base)
            cells = {}
            for k in range(0, n, 3):
                t = idx[k:k + 3]
                if per_patch:   # far patches: 16 x 81 vertices, 9 x 9 per 40 m patch, row-major
                    p = {v // 81 for v in t}
                    if len(p) != 1:
                        continue
                    p = p.pop()
                    cell = (p, min((v % 81) // 9 for v in t), min((v % 81) % 9 for v in t))
                else:           # near grid: y * 33 + x
                    cell = (min(v % 33 for v in t), min(v // 33 for v in t))
                if len(set(t)) == 3:
                    cells[cell] = cells.get(cell, 0) + 1
            cover.append((n, len(cells), all(c == 2 for c in cells.values())))
    check("13BB terrain: both index arrays (near grid 0x19D4, far patches 0x49D8) draw 2 triangles in every one of "
          "the 1024 cells (the black strip is no hole in the index buffers)",
          rec_ok and cover == [(6144, 1024, True), (6144, 1024, True)], cover)
    agl = [c for c in data.roster if c.get("name") == "Atomic Green Lantern"]
    classes = [agl[0]["variant"]] + [ci["variant"] for ci in agl[0].get("costume_info", [])] if agl else []
    check("ring: no Atomic Green Lantern class lists an entity script (nothing makes the client run EnableCollision "
          "on the champion)", classes and all(not data.entity_scripts(c) for c in classes),
          {hex(c): data.entity_scripts(c) for c in classes})
    with open(os.path.join(ROOT, "tools", "diag.py"), encoding="utf-8") as f:
        src = f.read()
    check("diag: --ring probes the overlap-add 0x638636 and the collision holds 0x976990; --layers steps the "
          "WorldRender toggles", all(f"0x{a:X}:" in src for a in (0x238636, 0x576990)) and '"--layers"' in src
          and '(0x30, "DrawLandscape")' in src and '"--capas": "--layers"' in src)


def click_assist(cfg, data):
    """Tester report 2026-10-29 18:31 (docs/re-notes/ca-fog-stealth-hover.md 3): a right click next to a visible enemy
    that the client's hover pick missed (move order with no pick, our champion or an ally) attacks that enemy."""
    print("click assist (tester report 2026-10-29 18:31)")
    import types
    from ics.session import Session
    cfg["ics"]["click_assist_radius"] = copy.deepcopy(config.DEFAULTS["ics"]["click_assist_radius"])
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + 45.0 + 4.0)
    ch = w.champion
    foe = next((mu.ent for mu in m.units.by_eid.values() if mu.role == "minion" and mu.team != ch.team
                and mu.ent.alive), None)
    ally = next((mu.ent for mu in m.units.by_eid.values() if mu.role == "minion" and mu.team == ch.team
                 and mu.ent.alive), None)
    fake = types.SimpleNamespace(ic=cfg["ics"])
    if foe is not None:
        foe.hidden = False
    near = [foe.pos[0] + 0.7, foe.pos[1], foe.pos[2]] if foe else None
    far = [foe.pos[0] + 2.5, foe.pos[1], foe.pos[2]] if foe else None
    got = [Session._click_assist(fake, w, ch, near, None), Session._click_assist(fake, w, ch, near, ch),
           Session._click_assist(fake, w, ch, near, ally), Session._click_assist(fake, w, ch, far, None)]
    check("click assist: a move order 0.7 m from a visible enemy minion (no pick / own champion / ally picked) "
          "attacks it; 2.5 m away it stays a move", foe is not None and got[:3] == [foe] * 3 and got[3] is None,
          [g and g.name for g in got])
    if foe is not None:
        foe.hidden = True
    hid = Session._click_assist(fake, w, ch, near, None)
    if foe is not None:
        foe.hidden = False
    cfg["ics"]["click_assist_radius"] = {}
    off = Session._click_assist(fake, w, ch, near, None)
    cfg["ics"]["click_assist_radius"] = copy.deepcopy(config.DEFAULTS["ics"]["click_assist_radius"])
    check("click assist: not on an enemy hidden by the fog; [ics] click_assist_radius = {} = off",
          hid is None and off is None, (hid, off))


def aggro_indicator(cfg, data):
    """Tester report 2026-10-29 21:10 (docs/re-notes/aggro-recall-scorepanel.md 1): an enemy minion that takes the local
    champion runs CbtState_Aggro + CbtState_Aggro_Active (0x100000CE = 1 as a run variable); dropping him stops both by
    0x11F; [] roles = nothing."""
    print("aggro indicator (tester report 2026-10-29 21:10)")
    for k in ("match_aggro_roles", "match_aggro_flag", "match_aggro_flag_mode", "match_aggro_scriptlets"):
        cfg["ics"][k] = config.DEFAULTS["ics"][k]
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + 45.0 + 4.0)
    mins = [mu for mu in m.units.by_eid.values() if mu.role == "minion" and mu.team == 2 and mu.ent.alive]
    check("aggro: an enemy wave is on the lane", bool(mins), len(mins))
    if not mins:
        return
    mu, ch = mins[0], w.champion
    n0 = len(s.sent)
    mu.target = ch
    m.units.aggro_indicator(mu)
    lbl = s.labels(n0)
    check("aggro: CbtState_Aggro then CbtState_Aggro_Active on the minion",
          any("CbtState_Aggro (0x8d)" in x for x in lbl) and any("CbtState_Aggro_Active (0x8d)" in x for x in lbl), lbl)
    var = [b for lb, b in s.sent[n0:] if "CbtState_Aggro" in (lb or "")]
    check("aggro: the runs carry variable 0x100000CE (the 0x22 gate), no 0x6 on the unit",
          var and all(struct.pack("<I", 0x100000CE) in b for b in var)
          and not any("aggro flag" in x for x in lbl), [b.hex() for b in var][:1])
    key = w.data.scriptlet_key("CbtState_Aggro_Active")
    check("aggro: the active key is held (re-sent after the unit's bundles)",
          (mu.ent.eid, key) in (w.__dict__.get("looping_scriptlets") or {}))
    n1 = len(s.sent)
    m.units.aggro_indicator(mu)
    check("aggro: nothing again while the target stays", len(s.sent) == n1)
    mu.target = None
    m.units.aggro_indicator(mu)
    lbl = s.labels(n1)
    check("aggro: dropping the champion stops both keys by 0x11F and ends the hold",
          sum("(0x11f, aggro off)" in x for x in lbl) == 2
          and (mu.ent.eid, key) not in (w.__dict__.get("looping_scriptlets") or {}), lbl)
    m.units.ic["match_aggro_roles"] = []
    n2 = len(s.sent)
    mu.target = ch
    m.units.aggro_indicator(mu)
    check("aggro: match_aggro_roles [] -> no indicator", len(s.sent) == n2, s.labels(n2))
    mu.target = None
    m.units.ic["match_aggro_roles"] = config.DEFAULTS["ics"]["match_aggro_roles"]


def leash_turret_ring_camp_drop(cfg, data):
    """Tester report 2026-10-29 15:30 (docs/re-notes/leash-recall-turretring-campicons.md): minions and bots leash,
    the turret warning ring's flags ride in the creation bundle, the jungle heavy drop is not spawned."""
    print("leash / turret ring / camp drop (tester report 2026-10-29 15:30)")
    defaults = config.DEFAULTS["ics"]
    for k in LEASH_KEYS:
        cfg["ics"][k] = defaults[k]

    # turret ring: the enemy turret's creation bundle carries 0x1000019D with the Turret bit, 0x10000C5D and the range
    s, w, m = make(cfg, data, 0x40000C82)
    tur = next(mu for mu in m.structures if mu.team == 2 and mu.role == "turret")
    props = {p[0]: p[2] for p in tur.ent.extra_props}
    check("ring: enemy turret's bundle has 0x1000019D & 0x10, 0x10000C5D, 0x10000C5B and 0x10000133 > 0",
          (props.get(0x1000019D, 0) & 0x10) and props.get(0x10000C5D) == 1 and props.get(0x10000C5B) == 1
          and (props.get(0x10000133) or 0) > 0, props)
    n0 = len(s.sent)
    run(s, m, 1.5)
    lbl = s.labels(n0)
    check("ring: then the flags (0, then the value) and the enemy range as changes",
          any(f"{tur.ent.name}: unit flags cleared" in x for x in lbl) and any(f"{tur.ent.name}: vision 0" in x
                                                                              for x in lbl), lbl[:20])

    # minions: a champion kiting an enemy minion away from the lane is dropped at the anchor, the minion goes back
    run(s, m, 13.0 + 45.0 + 4.0)
    for mu in list(m.units.by_eid.values()):
        if mu.role == "minion" and mu.team == 1:
            kill(w, mu.ent)
    run(s, m, 0.5)
    mins = [mu for mu in m.units.by_eid.values() if mu.role == "minion" and mu.team == 2 and mu.ent.alive]
    check("leash: an enemy wave is on the lane", bool(mins), len(mins))
    if not mins:
        return
    mu = mins[0]
    ch = w.champion
    ch.safe_zone = False
    ch.pos = [mu.ent.pos[0], mu.ent.pos[1] + 1.5, ch.pos[2]]
    mu.next_think = 0.0
    run(s, m, 1.0)
    check("leash: the minion takes the champion next to it", mu.target is ch, mu.target)
    worst, dropped = 0.0, None
    for i in range(80):                                   # 20 s of kiting: always 1.8 m ahead of it, away from the lane
        ch.pos = [mu.ent.pos[0], mu.ent.pos[1] + 1.8, ch.pos[2]]
        run(s, m, 0.25)
        worst = max(worst, m.units.lane_distance(mu))
        if mu.target is not ch and dropped is None:
            dropped = i * 0.25
    anchor = float(cfg["ics"]["match_minion_leash_anchor"])
    check("leash: the minion drops the kiting champion (at most anchor + 2 m from its lane)",
          dropped is not None and worst <= anchor + 2.0, (dropped, round(worst, 2)))
    ch.pos = list(maps.spawn_point(0x40000C82, 1)[4:7])
    run(s, m, float(cfg["ics"]["match_minion_return_max"]) + 1.0)
    check("leash: the minion is back by its lane", mu.ent.alive is False or
          m.units.lane_distance(mu) <= float(cfg["ics"]["match_minion_lane_rejoin"]) + 0.5,
          round(m.units.lane_distance(mu), 2))
    # out of its range: a champion that steps away is dropped at the next think
    mins = [x for x in m.units.by_eid.values() if x.role == "minion" and x.team == 2 and x.ent.alive]
    mu = mins[0]
    mu.ignore, mu.returning_until, mu.leash_from = {}, 0.0, None
    ch.pos = [mu.ent.pos[0], mu.ent.pos[1] + 1.5, ch.pos[2]]
    mu.next_think = 0.0
    run(s, m, 0.75)
    took = mu.target is ch
    ch.pos = [mu.ent.pos[0], mu.ent.pos[1] + 20.0, ch.pos[2]]
    mu.next_think = 0.0
    run(s, m, 0.5)
    check("leash: out of its acquisition range the minion drops the champion", took and mu.target is not ch,
          (took, mu.target))
    cfg["ics"]["match_leash_rules"] = False
    w.ic["match_leash_rules"] = False
    check("leash: match_leash_rules = false keeps the old 12 m rule", m.units._leash_on(mu) is False)
    w.ic["match_leash_rules"] = True
    cfg["ics"]["match_leash_rules"] = True

    # bots: no dive under a free enemy turret; leash from where the chase began
    s = FakeSession()
    spawn = pvp.spawn_point(0x40000C82, 1)
    w = World(data, cfg, 0x40000C82, spawn, send=s.send, schedule=s.schedule, log=lambda t: None)
    nav = pvp.navgrid(data, 0x40000C82, spawn[1:3])
    w.nav = nav.copy() if nav else None
    w.ground_z = spawn[6]
    w.create_champion(cfg["ics"]["champion"], spawn)
    w.in_world = True
    m = pvp.start_match(w, s, 0x40000C82, [
        {"iid": 1, "name": "Player", "team": 1, "index": 0, "champion": cfg["ics"]["champion"], "bot": False},
        {"iid": 0x0200000000F00000, "name": "Bot 0", "team": 2, "index": 0, "champion": 0x400003EC, "bot": True}])
    run(s, m, 13.0 + 47.0)                                # the first wave is out
    brain = m.bots.brains[0]
    bot, ch = brain.ent, w.champion
    mine = next(mu for mu in m.structures if mu.team == 1 and mu.role == "turret")   # the player's turret
    ch.pos = [mine.ent.pos[0], mine.ent.pos[1] + 2.0, ch.pos[2]]
    mine.target = None
    check("bot: a champion under his own free turret is not taken", ch not in brain.leash_filter([ch]))
    minion = next((mu.ent for mu in m.units.by_eid.values() if mu.role == "minion" and mu.team == 2), None)
    if minion is not None:
        mine.target = minion
        # the fase3-ij rule; with bot_tower_tactics (2026-10-30 18:12) a champion 2 m from the turret is a dive whatever
        # the turret shoots (bot_trade_depth; bot_tower_tactics_1812)
        m.ic["bot_tower_tactics"] = False
        check("bot: ... but is while that turret shoots one of the bot's minions (bot_tower_tactics off)",
              ch in brain.leash_filter([ch]))
        m.ic["bot_tower_tactics"] = True
    mine.target = None
    ch.pos = [80.0, 77.0, ch.pos[2]]
    bot.pos = [82.0, 77.0, bot.pos[2]]
    brain.target, brain.chase_from = None, None
    brain.note_chase(ch)
    brain.target = ch
    bot.pos = [82.0 + float(cfg["ics"]["bot_leash"]) + 1.0, 77.0, bot.pos[2]]
    ch.pos = [bot.pos[0] + 2.0, 77.0, ch.pos[2]]
    out = brain.leash_filter([ch])
    check("bot: leash, a chase that went more than bot_leash m is dropped and the champion ignored",
          ch not in out and ch.eid in brain.ignore and ch not in brain.leash_filter([ch]), out)

    # camp drop: the heavy drop 0x400005E1 is not spawned
    cw = CastWorld(w, bot, None)
    got = cw.spawn_entity(bot, 0x400005E1, list(bot.pos))
    check("camp drop: SpawnEntity of the heavy drop 0x400005E1 is skipped ([ics] spawned_skip_classes)", got is None)
    w.ic["spawned_skip_classes"] = []
    got = cw.spawn_entity(bot, 0x400005E1, list(bot.pos))
    check("camp drop: spawned_skip_classes = [] spawns it as before", got is not None)
    w.ic["spawned_skip_classes"] = list(defaults["spawned_skip_classes"])

    # 2026-10-29 19:55 crash: Arcane Supergirl's Firewall 0x40000BEF (health stat 1, no PerceivedType) got 0x42
    wall = cw.spawn_entity(bot, 0x40000BEF, list(bot.pos))
    n0 = len(s.sent)
    w.damage(ch, wall, 40) if wall is not None else None
    check("Firewall 0x40000BEF: no client vitals component, spawned inert, never sent 0x42 ([ics] vitals_need_perceived_type)",
          wall is not None and wall.health is None and not w.vitals_component(wall)
          and not any("(0x42)" in lbl for lbl in s.labels(n0)), wall and (wall.health, wall.kind))
    check("... minions / bot champions keep their vitals (PerceivedType & 0x7F59FB)",
          w.vitals_component(bot) and all(w.vitals_component(mu.ent) for mu in m.structures if mu.ent.client_vitals))

    # recall: the channel fx run is held (fase3-ij: a looping key until its StopScriptlet; start_scriptlet_hold_mode
    # "resend", the 2026-10-30 default "defer" is checked in core_door_regen_1530)
    ch = w.champion
    run(s, m, 0.5)
    ch.safe_zone = False
    was_mode = w.ic.get("start_scriptlet_hold_mode")
    w.ic["start_scriptlet_hold_mode"] = "resend"
    n0 = len(s.sent)
    w.cast(ch, 6, None, None)
    run(s, m, 0.2)
    live = w.__dict__.get("looping_scriptlets") or {}
    check("recall (mode resend): the channel fx 0x10000223 is held as a looping key ([ics] start_scriptlet_hold)",
          (ch.eid, 0x10000223) in live, list(live)[:5])
    run(s, m, 1.0)
    again = [x for x in s.labels(n0) if "0x10000223 again" in x]
    check("recall (mode resend): it goes again (same run) after Fidgets_Disable / Emote_Abort", bool(again),
          s.labels(n0)[:25])
    w.ic["start_scriptlet_hold_mode"] = was_mode


def unit_separation(cfg, data):
    """Tester report 2026-10-30 13:18 ("the minions pass through each other"; docs/re-notes/unit-separation-pick-body.md):
    units stacked on one spot spread to their radii and settle (no more states), a wave spreads around its target and
    every member still reaches it and swings, units keep off a champion, and match_unit_separation = false is the old
    stacking."""
    print("unit separation (tester report 2026-10-30 13:18)")
    for k in ("match_unit_separation", "match_separation_roles", "match_separation_push", "match_separation_resync",
              "match_separation_shuffle_min", "match_separation_slack", "match_separation_target_holds",
              "match_separation_unpin"):
        cfg["ics"][k] = copy.deepcopy(config.DEFAULTS["ics"][k])

    def setup(on=True):
        cfg["ics"]["match_unit_separation"] = on
        s, w, m = make(cfg, data, 0x40000C82)
        run(s, m, 13.0 + 46.0 + 1.0)
        wave = [mu for mu in m.waves.minions if mu.ent.alive]
        melee = min(wave, key=lambda mu: mu.range)
        p = list(melee.ent.pos)
        for mu in list(m.units.by_eid.values()):
            if mu.role in ("minion", "camp"):
                m.units.remove(mu)
        far = maps.spawn_point(0x40000C82, 1)
        w.champion.pos = [far[4], far[5], w.champion.pos[2]]
        group = [m.units.spawn(melee.cls, p, 1, "minion", name=f"sep {i}") for i in range(5)]
        return s, w, m, group, melee.cls, p

    def min_gap(group):
        return min(math.hypot(a.ent.pos[0] - b.ent.pos[0], a.ent.pos[1] - b.ent.pos[1])
                   for i, a in enumerate(group) for b in group[i + 1:])

    s, w, m, group, cls, p = setup()
    r = m.units._body_radius(group[0].ent)
    run(s, m, 3.0)
    gap = min_gap(group)
    check("separation: 5 minions spawned on one spot spread to about two radii apart", gap >= 2 * r - 0.25, (gap, r))
    on_mesh = all(w.nav is None or w.nav.walkable(mu.ent.pos[0], mu.ent.pos[1]) for mu in group)
    check("separation: every pushed minion stands on the walkable mesh", on_mesh)
    n0 = len(s.sent)
    run(s, m, 4.0)
    states = sum(1 for lbl in s.labels(n0) if ": state (" in lbl and lbl.startswith("sep "))
    check("separation: once apart they settle (no oscillation: at most 2 states in 4 s)", states <= 2, states)
    still = all(not mu.moving and mu.shuffle is None for mu in group)
    check("separation: ... and stand still", still)

    # a wave on one enemy: spread around it, every member in reach, swinging
    foe = m.units.spawn(cls, (p[0] + 3.0, p[1]), 2, "minion", name="sep foe")
    foe.ent.max_health = foe.ent.health = 1e7
    hp0 = foe.ent.health
    for mu in group:
        mu.target, mu.path = foe.ent, []          # the wave's pick (some stand beyond their 3 m vision)
    run(s, m, 6.0)
    reach = [round(mu.ent.distance_to(foe.ent) - m.units._reach(mu, foe.ent), 2) for mu in group]
    check("separation: every wave member reaches its target", all(d <= 0.0 for d in reach) and
          all(mu.target is foe.ent for mu in group), reach)
    gap = min_gap(group)
    check("separation: around the target they keep apart (>= 2 radii - 0.3)", gap >= 2 * r - 0.3, (gap, r))
    check("separation: and they hit it", foe.ent.health < hp0, (foe.ent.health, hp0))
    n0 = len(s.sent)
    run(s, m, 4.0)
    states = sum(1 for lbl in s.labels(n0) if ": state (" in lbl and lbl.startswith("sep ") and "foe" not in lbl)
    check("separation: around the target no oscillation (at most 1 state per member in 4 s)", states <= len(group),
          states)

    # a champion standing in the way is an obstacle
    ch = w.champion
    ch.pos = [group[0].ent.pos[0], group[0].ent.pos[1], ch.pos[2]]
    run(s, m, 2.0)
    rc = m.units._body_radius(ch)
    d = min(mu.ent.distance_to(ch) for mu in group if mu.ent.alive)
    check("separation: minions step off a champion standing on them (or stay in reach of their target)",
          d >= r + rc - 0.3 or all(mu.ent.distance_to(foe.ent) <= m.units._reach(mu, foe.ent) for mu in group), d)

    s, w, m, group, cls, p = setup(False)
    run(s, m, 3.0)
    check("separation: match_unit_separation = false keeps them stacked (as before)", min_gap(group) < 0.05,
          min_gap(group))
    cfg["ics"]["match_unit_separation"] = True


def chase_range(cfg, data):
    """Tester report 2026-10-29 18:31 (docs/re-notes/basic-attack-chase-range.md): a champion ordered to attack an enemy
    champion that runs away stops and attacks as soon as the target is within the basic attack's range + both collision
    radii (the client's validator 0x9d01d0 step 11), and chases again when it leaves."""
    print("basic attack on a fleeing champion (tester report 2026-10-29 18:31)")
    logs = []
    s, w, m, bot = _sweep_bot_match(cfg, data, logs)
    run(s, m, 14.0)
    ch = w.champion
    brain = m.bots.brains[0]
    brain.next_decision = float("inf")              # the test drives the bot
    bot.safe_zone = ch.safe_zone = False
    p = brain.route[len(brain.route) // 2]
    basic = ch.kit.get(0)
    stat = basic.stat(18, 1) if basic and basic.stat(18, 1) > 0 else float(w.ic["basic_attack_range"])
    radii = 2 * float(w.ic["attack_body_radius"]["champion"])
    casts = []
    orig_cast = w.cast

    def rec(ent, slot, target, point):
        if ent is ch and slot == 0:
            casts.append((m.t, target))
            return True                             # the swing itself is not under test
        return orig_cast(ent, slot, target, point)
    w.cast = rec

    def flee(gap):
        """The bot walks straight away from the champion at the champion's speed, gap m past stat 18."""
        ch.pos = [p[0], p[1], ch.pos[2]]
        ch.dest, ch.path, ch.speed = None, [], 0.0
        bot.pos = [p[0] + stat + gap, p[1], bot.pos[2]]
        bot.attack_target, bot.path = None, []
        bot.move_speed = ch.move_speed
        bot.dest = [bot.pos[0] + 30.0, bot.pos[1], bot.pos[2]]
        ch.next_attack = 0.0
        ch.ready_at.pop(0, None)
        ch.attack_target = bot
        del casts[:]
    try:
        flee(radii * 0.6)                           # past stat 18, inside stat 18 + both radii (the client's ring)
        run(s, m, 0.05, 0.05)
        check("a fleeing target past stat 18 but inside stat 18 + both radii: the champion stops and attacks "
              "(attack_range_radii)", casts and ch.dest is None and casts[0][1] is bot,
              (len(casts), ch.dest, round(ch.distance_to(bot), 2), stat, radii))
        bot.pos[0] += 6.0                           # the target leaves the range
        bot.dest = [bot.pos[0] + 30.0, bot.pos[1], bot.pos[2]]
        run(s, m, 0.1, 0.05)
        check("the target leaves the range: the champion chases it again", ch.dest is not None
              and ch.attack_target is bot, (ch.dest, ch.attack_target))
        w.ic["attack_range_radii"] = False
        flee(radii * 0.6)
        run(s, m, 0.5, 0.05)
        check("attack_range_radii = false: centre to centre, the same target is chased and never attacked (fase3-il)",
              not casts and ch.dest is not None, (len(casts), ch.dest))
    finally:
        w.ic["attack_range_radii"] = True
        w.cast = orig_cast


def carry_press_facing(cfg, data):
    """Tester report 2026-10-29 19:55 (docs/re-notes/liftable-carry-throw-press.md, minion-attack-facing.md): the carry's
    throw indicator follows the slot's kept-ready 0x20F8, an unanswered throw press throws, carry states are snapped,
    the landed vehicle plays its pieces' break keys, a minion in reach sends its turn toward the target."""
    print("carry indicator / throw press / break keys / minion facing (tester report 2026-10-29 19:55)")
    from ics.world import CastWorld
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 3.0)
    ch = w.champion
    ch.stolen[7] = data.stolen_power(0x480003CB)[0]           # Super Strength in slot 7

    class _Inst:
        slot, removed = 7, False

        def post(self, *a):
            pass

    def lift_rock():
        rock = next(e for e in m.liftables.props if e.liftable == "rock" and getattr(e, "carried_by", None) is None)
        ch.pos = [rock.pos[0] - 2.0, rock.pos[1], ch.pos[2]]
        ch.dest, ch.path, ch.speed, ch.carry_cooldown_end = None, [], 0.0, None
        run(s, m, 0.5)
        m.liftables.lift(ch, rock, _Inst())
        return rock
    rock = lift_rock()
    n0 = len(s.sent)
    run(s, m, 1.0, 0.05)
    check("rock: ready, but no throw indicator before the slot's kept-ready 0x20F8 (liftable_indicator_after_cooldown)",
          getattr(ch, "carry_ready", False) and not any("throw indicator on" in lbl for lbl in s.labels(n0)),
          s.labels(n0))
    CastWorld(w, ch, None).on_cooldown(ch, 7, time.time() + 90.0)    # Super Strength's StartCooldown (0x34000164 S3)
    run(s, m, 0.2, 0.05)
    lab = s.labels(n0)
    i_ready = next((i for i, lbl in enumerate(lab) if "kept ready while carrying (0x20f8)" in lbl), None)
    i_ind = next((i for i, lbl in enumerate(lab) if "throw indicator on (0x2180)" in lbl), None)
    check("rock: the indicator (0x2180 / 0x20F9) follows the kept-ready 0x20F8, the vehicle carry's order",
          i_ready is not None and i_ind is not None and i_ready < i_ind, (i_ready, i_ind))
    seq0 = getattr(rock, "tele_seq", 1)
    w.walk_to(ch, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    run(s, m, 0.25, 0.05)
    check("carry: the walking carry's state has a newer teleport sequence (liftable_carry_snap)",
          getattr(rock, "tele_seq", 1) != seq0, (seq0, getattr(rock, "tele_seq", 1)))
    run(s, m, 1.0, 0.05)
    n1 = len(s.sent)
    w.raise_skill_event(ch, 7, 0x10000023)
    run(s, m, 0.5, 0.05)
    if int(w.ic.get("liftable_throw_on_press", 1) or 0) >= 2:
        check("throw press: one press with no throw order keeps the carry", ch.carrying is rock
              and not getattr(rock, "flying", False))
    else:
        # 2026-10-30 tester report 11:23 (liftable-softlock.md 4): the first unanswered press throws
        check("throw press: the first unanswered press throws (liftable_throw_on_press 1)",
              any(f"{ch.name} throws {rock.name}" in lbl for lbl in s.labels(n1)), s.labels(n1)[-8:])
    w.raise_skill_event(ch, 7, 0x10000023)
    run(s, m, 0.8, 0.05)
    check("throw press: the n-th unanswered press in a row throws (liftable_throw_on_press)",
          getattr(ch, "carrying", None) is None and any(f"{ch.name} throws {rock.name}" in lbl for lbl in s.labels(n1)),
          s.labels(n1)[-12:])
    run(s, m, 2.5)
    rock = lift_rock()
    run(s, m, 2.0, 0.05)
    w.raise_skill_event(ch, 7, 0x10000023)
    m.liftables.throw(ch, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])     # the client's order right after the press
    run(s, m, 0.5, 0.05)
    check("throw press: a press the order follows throws once (no fallback count)",
          getattr(ch, "carry_unanswered", 0) == 0 and getattr(ch, "carrying", None) is None)
    run(s, m, 2.5)
    w.ic["liftable_throw_on_press"] = 0
    try:
        rock = lift_rock()
        run(s, m, 2.0, 0.05)
        for _ in range(3):
            w.raise_skill_event(ch, 7, 0x10000023)
            run(s, m, 0.5, 0.05)
        check("liftable_throw_on_press = 0: presses never throw (as before)", ch.carrying is rock)
    finally:
        w.ic["liftable_throw_on_press"] = 1
    m.liftables.throw(ch, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    run(s, m, 2.5)
    car = next(e for e in m.liftables.props if e.liftable == "vehicle")
    n2 = len(s.sent)
    m.liftables._break_keys(car)
    run(s, m, 0.3, 0.05)
    brk = [lbl for lbl in s.labels(n2) if "(0x8d, break)" in lbl]
    check("landing: the vehicle's pieces' break keys go to it (liftable_land_break_keys), only names its tables hold",
          any("Destructible_OnCompletelyDestroyed" in lbl for lbl in brk)
          and any("Destructible_OnBreak_Front_T1" in lbl for lbl in brk) and len(brk) <= 6, brk)
    # a minion in reach of its target turns toward it (minion-attack-facing.md)
    mu = next(u for u in m.units.by_eid.values() if u.role == "minion" and u.ent.alive and u.team != ch.team)
    ent = mu.ent

    def facing_case():
        ch.pos = [ent.pos[0], ent.pos[1] + 1.0, ent.pos[2]]          # straight "north" of the minion, in reach
        ch.dest, ch.path = None, []
        mu.target, mu.moving, mu.path = ch, False, []
        ent.heading = mu.sent_heading = 0.0                           # last sent facing: "east"
        mu.next_attack = float("inf")                                 # the swing itself is not under test
        n = len(s.sent)
        m.units.act(mu, 0.05, s.clock)
        return [lbl for lbl in s.labels(n) if lbl.startswith(f"{ent.name}: state")]
    states = facing_case()
    check("minion: in reach of a target 90 degrees off its last facing, it sends a state facing the target "
          "(match_attack_face_turn)", len(states) == 1 and abs(math.remainder(ent.heading - math.pi / 2, math.tau)) < 1e-6
          and abs(math.remainder(mu.sent_heading - math.pi / 2, math.tau)) < 1e-6, (states, ent.heading))
    n = len(s.sent)
    m.units.act(mu, 0.05, s.clock)
    check("minion: no second state while the facing holds", not [lbl for lbl in s.labels(n)
                                                                 if lbl.startswith(f"{ent.name}: state")])
    w.ic["match_attack_face_turn"] = 0.0
    try:
        states = facing_case()
        check("match_attack_face_turn = 0: no turn state (as before)", not states, states)
    finally:
        w.ic["match_attack_face_turn"] = 0.15
    mu.next_attack = 0.0


def aura_probe(cfg, data):
    """Tester report 2026-10-29 23:03 (scorecard-accolades-meteor-aura.md 2): [ics] liftable_aura_probe plays its logged
    steps on a lying meteorite (colour, a key of its tables, a forced key of the hologram table, a base key)."""
    print("meteorite aura probe (tester report 2026-10-29 23:03)")
    old = cfg["ics"].get("liftable_aura_probe")
    cfg["ics"]["liftable_aura_probe"] = [
        {"at": 1.0, "kind": "rock", "colour": 0},
        {"at": 2.0, "kind": "rock", "key": "Vfx_Active_Red"},
        {"at": 3.0, "kind": "rock", "key": "Vfx_Active_Red", "force": True},
        {"at": 4.0, "kind": "rock", "target": "base", "key": "Vfx_Active_State2"}]
    try:
        s, w, m = make(cfg, data, 0x40000C82)
        run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 8.0)
        rocks = [e for e in m.liftables.props if e.liftable == "rock"]
        lbls = s.labels()
        r0 = rocks[0].name if rocks else "?"
        probe = [lbl for lbl in lbls if lbl.startswith("aura probe")]
        check("aura probe: colour 0 by override + team change, a forced hologram key, the base's State2; an unforced key "
              "outside the rock's tables is not sent",
              rocks and f"aura probe 0: {r0} colour 0 (0x6 override, team 3 -> 0)" in probe
              and f"aura probe 2: {r0}: Vfx_Active_Red (0x8d) forced (not in its tables)" in probe
              and not any(lbl.startswith("aura probe 1:") for lbl in probe)
              and any(lbl.startswith("aura probe 3:") and "Vfx_Active_State2" in lbl for lbl in probe)
              and all(sum(1 for lbl in probe if lbl.startswith(f"aura probe 2: {r.name}:")) == 1 for r in rocks),
              probe[:8])
        cfg["ics"]["liftable_aura_probe"] = []
        s2, w2, m2 = make(cfg, data, 0x40000C82)
        run(s2, m2, 13.0 + cfg["ics"]["match_waves"]["first"] + 8.0)
        check("aura probe: [] sends nothing", not any(lbl.startswith("aura probe") for lbl in s2.labels()))
    finally:
        cfg["ics"]["liftable_aura_probe"] = old


def aura_lift_throw_break(cfg, data):
    """Tester report 2026-10-29 21:10 (docs/re-notes/liftable-aura-lift-throw-break.md): the meteorite's red tint while it
    lies pickable, Super Strength's input back at the toss / grab, the toss caught at TossDuration, an early throw order
    kept, the flight as states with their 3D velocity at their own time, no Vfx_OnExplode at the vehicle's landing."""
    print("meteorite aura / lift timing / smooth throw / vehicle landing (tester report 2026-10-29 21:10)")
    from ics import messages as M
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 3.0)
    ch = w.champion
    ch.stolen[7] = data.stolen_power(0x480003CB)[0]

    class _Inst:
        slot, removed = 7, False

        def __init__(self):
            self.posts = []

        def post(self, ev, delay, *a):
            self.posts.append((round(m.t, 3), ev))

    # the movement block's motion pitch (bit 0x40, f32 after the speed); None leaves the bytes as before
    pos = (1, 0x10, 0x10, 0xFB, 1.0, 2.0, 3.0)
    plain = M.movement_block(100.0, pos, 0.5, 4.0)
    up = M.movement_block(100.0, pos, 0.5, 4.0, vel_pitch=0.25)
    k = plain.index(struct.pack("<ff", 0.5, 4.0))
    check("movement block: vel_pitch sets motion bit 0x40 and puts its f32 right after the speed (C 0x57E530)",
          up[k - 2] == plain[k - 2] | 0x40 and up[k + 8:k + 12] == struct.pack("<f", 0.25)
          and up[:k - 2] == plain[:k - 2] and up[k + 12:] == plain[k + 8:] and len(up) == len(plain) + 4,
          (plain.hex(), up.hex()))

    # the meteorite's tint: override 5, then the team as a change; off at the grab
    rocks = [e for e in m.liftables.props if e.liftable == "rock"]
    lbls = s.labels()
    check("rock aura: each meteorite gets colour override 5 and a team change 3 -> 0 (liftable_aura)",
          all(any(lbl == f"{r.name}: colour override 5 (0x6)" for lbl in lbls)
              and any(lbl == f"{r.name}: team 0, aura on (0x6)" for lbl in lbls) for r in rocks)
          and all(getattr(r, "aura_on", False) for r in rocks), [lbl for lbl in lbls if "aura" in lbl][:6])
    base = m.liftables.bases.get(rocks[0].lift_spec.get("index"))
    check("rock base: its own idle key Vfx_Active_State1 is played (the old names are not in its table 0x1D0004AA)",
          base is not None and any(lbl == f"{base.name}: Vfx_Active_State1 (0x8d)" for lbl in lbls),
          [lbl for lbl in lbls if "crater" in lbl][:6])
    rock = rocks[0]
    ch.pos = [rock.pos[0] - 2.0, rock.pos[1], ch.pos[2]]
    ch.dest, ch.path, ch.speed = None, [], 0.0
    run(s, m, 0.5)
    inst, t_lift, n0 = _Inst(), m.t, len(s.sent)
    m.liftables.lift(ch, rock, inst)
    run(s, m, 0.6, 0.05)
    grab = float((cfg["ics"].get("super_strength_cast_signals") or {}).get("rock_grab", 0.22))
    check("rock: 0x100000BB posted to Super Strength at the grab (0x34000177 S3; liftable_input_back), once",
          [ev for _t, ev in inst.posts] == [0x100000BB] and abs(inst.posts[0][0] - t_lift - grab) <= 0.05 + 1e-6,
          (inst.posts, t_lift))
    check("rock aura: off when lifted (team 3)", any(lbl == f"{rock.name}: team 3, aura off (0x6)" for lbl in s.labels(n0))
          and not rock.aura_on)
    # the rock's flight: states at their own time, 3D velocity (it comes down from the hand)
    run(s, m, 1.0, 0.05)
    n1 = len(s.sent)
    m.liftables.throw(ch, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    vel = []
    for _ in range(30):
        run(s, m, 1 / 30, 1 / 30)
        if getattr(rock, "flying", False) and getattr(rock, "vel_pitch", None) is not None:
            vel.append((rock.speed, rock.vel_pitch))
    check("rock flight: a state per tick with a downward velocity pitch (liftable_throw_velocity)",
          len(vel) >= 10 and all(p < 0 for _v, p in vel), vel[:4])
    # a vehicle: input back at the toss, caught at TossDuration (never before Hold + 0.05), early order kept
    car = next(e for e in m.liftables.props if e.liftable == "vehicle")
    ch.pos = [car.pos[0] - 2.0, car.pos[1], car.pos[2]]
    ch.dest, ch.path, ch.speed = None, [], 0.0
    run(s, m, 3.0)
    _c, toss_at, catch_at, ready_at = m.liftables._toss_timeline(ch)
    check("toss: caught 0.3 s after the toss (TossDuration, the lob's landing ends S7) but not before Hold + 0.05 "
          "(AGL: catch 0.875, ready 0.975)", abs(catch_at - max(toss_at + 0.3, 0.45 + 0.375 + 0.05)) < 1e-6
          and abs(ready_at - catch_at - 0.1) < 1e-6, (toss_at, catch_at, ready_at))
    inst, t_lift = _Inst(), m.t
    m.liftables.lift(ch, car, inst)
    run(s, m, 0.35, 0.05)
    m.liftables.throw(ch, [ch.pos[0] + 7.0, ch.pos[1], ch.pos[2]])      # an order during the lift
    check("an order during the lift is kept, not thrown yet (liftable_throw_early_queue)",
          getattr(ch, "carry_queued_throw", None) is not None and ch.carrying is car and not getattr(car, "flying", False))
    n2 = len(s.sent)
    t_order = m.t
    run(s, m, ready_at - (m.t - t_lift) + 0.1, 0.05)
    check("vehicle: 0x100000BB posted at the toss (0x34000161 S7), once", [ev for _t, ev in inst.posts] == [0x100000BB]
          and abs(inst.posts[0][0] - t_lift - toss_at) <= 0.05 + 1e-6, (inst.posts, t_lift, toss_at))
    check("the kept order throws once the carry is ready", any(f"{ch.name} throws {car.name}" in lbl
                                                             for lbl in s.labels(n2)) and m.t - t_order < 1.0)
    states = []
    for _ in range(60):
        run(s, m, 1 / 30, 1 / 30)
        if getattr(car, "flying", False):
            states.append((round(m.t, 3), list(car.pos), car.speed, getattr(car, "vel_pitch", None)))
    ups = [p for _t, _pos, _v, p in states if p is not None]
    check("vehicle flight: a state per tick, the velocity pitched up then down along the lob (liftable_throw_velocity)",
          len(states) >= 12 and ups and ups[0] > 0 and ups[-1] < 0 and all(b <= a + 1e-9 for a, b in zip(ups, ups[1:])),
          [(t, round(v, 2), p and round(p, 2)) for t, _p, v, p in states[:5]])
    run(s, m, 1.0)
    landing = s.labels(n2)
    # 2026-10-30 tester report 12:05 (liftable-lift-throw-wreck.md 2): Vfx_OnExplode comes back, after the break keys
    first = lambda key: next((i for i, lbl in enumerate(landing) if f"{car.name}: {key}" in lbl), None)  # noqa: E731
    check("vehicle landing: no Vfx_OnExplode at the landing frame (it deletes the intact pieces, C 0x62EBF0); impulse, "
          "break keys, DestroyEntity's action go first", first("Vfx_OnExplode (0x8d)") is None
          and first("destruction impulse (0x8a)") is not None
          and first("Destructible_OnCompletelyDestroyed") is not None
          and (first("Vfx_OnExplode (0x8d, late)") is None
               or first("Vfx_OnExplode (0x8d, late)") > first("Destructible_OnCompletelyDestroyed")), landing[-10:])
    saved_explode = w.ic.get("liftable_land_explode")
    w.ic["liftable_land_explode"] = {"vehicle": 0.3}
    try:
        car2 = next(e for e in m.liftables.props if e.liftable == "vehicle")
        n3 = len(s.sent)
        car2.broken = False
        m.liftables._explode_late(car2)
        run(s, m, 0.5)
        check("liftable_land_explode: Vfx_OnExplode the given s after the landing",
              any(f"{car2.name}: Vfx_OnExplode (0x8d, late)" in lbl for lbl in s.labels(n3)))
    finally:
        w.ic["liftable_land_explode"] = saved_explode


def throw_walk_to_range_1530(cfg, data):
    """Tester report 2026-10-30 15:30 (docs/re-notes/liftable-throw-walk-to-range.md): the vehicle throw's slot table lets
    the client send a far point (0x100006D5 = 0); a point beyond the range walks the carrier into range and throws there;
    a point in range throws at once; another order cancels the walk; the unanswered press throws at the aimed point."""
    print("vehicle throw: walk into range, then throw (tester report 2026-10-30 15:30)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 3.0)
    ch = w.champion
    ch.stolen[7] = data.stolen_power(0x480003CB)[0]
    L = m.liftables
    rng = 9.0

    class _Inst:
        slot, removed = 7, False

        def post(self, ev, delay, *a):
            pass

    flights = []
    orig_fly = L._fly

    def fly(c, obj, point, dist, info):
        flights.append((obj, tuple(point[:2]), (c.pos[0], c.pos[1])))
        return orig_fly(c, obj, point, dist, info)
    L._fly = fly
    used = set()

    def lift_car():
        car = next(e for e in L.props if e.liftable == "vehicle" and e.eid not in used
                   and getattr(e, "carried_by", None) is None and not getattr(e, "flying", False)
                   and not getattr(e, "broken", False))
        used.add(car.eid)
        ch.pos = [car.pos[0] - 2.0, car.pos[1], car.pos[2]]
        ch.dest, ch.path, ch.speed, ch.attack_target = None, [], 0.0, None
        run(s, m, 0.5)
        L.lift(ch, car, _Inst())
        run(s, m, 2.5, 1 / 30)
        return car

    def far_point(d):
        for k in range(16):
            a = k * math.tau / 16
            p = [ch.pos[0] + math.cos(a) * d, ch.pos[1] + math.sin(a) * d, ch.pos[2]]
            pts = w.nav.path(ch.pos[:2], p[:2]) if w.nav is not None else [p[:2]]
            if pts and math.hypot(pts[-1][0] - p[0], pts[-1][1] - p[1]) < 0.1 and len(pts) <= 2:
                return p
        return None
    try:
        car = lift_car()
        blk = {k: v for k, _kind, v in ch.stolen.get(7) or []}
        check("throw table: the carry slot's 0x100006D5 is 0, so the client sends a point beyond the range "
              "(liftable_throw_far_order)", ch.carrying is car and blk.get(0x100006D5) == 0 and blk.get(0x1000003D) == 1,
              (ch.carrying, blk.get(0x100006D5), blk.get(0x1000003D)))
        # in range: thrown at once at the point
        p_in = far_point(5.0)
        L.throw(ch, p_in)
        check("in range: thrown at once, no walk", getattr(ch, "carry_walk", None) is None
              and getattr(ch, "carry_phase", None) == "throw" and ch.dest is None)
        run(s, m, 1.0, 1 / 30)
        check("in range: the vehicle flies to the aimed point", flights and flights[-1][0] is car
              and math.hypot(flights[-1][1][0] - p_in[0], flights[-1][1][1] - p_in[1]) < 0.01, flights[-1:])
        run(s, m, 2.0)
        # out of range: walks (carry speed), then throws at the point once within range
        car = lift_car()
        p_far = far_point(15.0)
        start = list(ch.pos)
        n_fl = len(flights)
        L.throw(ch, p_far)
        check("out of range: no throw yet, the carrier walks toward the point at carry speed",
              getattr(ch, "carry_walk", None) is not None and ch.carrying is car and not getattr(car, "flying", False)
              and ch.dest is not None and ch.move_speed <= float(w.ic.get("liftable_carry_speed", 3.5)) + 1e-6,
              (getattr(ch, "carry_walk", None), ch.dest, ch.move_speed))
        t0 = m.t
        while len(flights) == n_fl and m.t - t0 < 6.0:
            run(s, m, 1 / 30, 1 / 30)
        thrown_at = flights[-1][2] if len(flights) > n_fl else None
        d_at = math.hypot(thrown_at[0] - p_far[0], thrown_at[1] - p_far[1]) if thrown_at else None
        check("out of range: thrown once within range, after walking about 6 m",
              thrown_at is not None and d_at <= rng + 0.05 and d_at > rng - 0.5
              and math.hypot(thrown_at[0] - start[0], thrown_at[1] - start[1]) > 5.0, (thrown_at, d_at))
        check("out of range: the vehicle flies to the aimed point (not clamped, not the facing)",
              len(flights) > n_fl and flights[-1][0] is car
              and math.hypot(flights[-1][1][0] - p_far[0], flights[-1][1][1] - p_far[1]) < 0.01, flights[-1:])
        run(s, m, 2.0)
        # another order cancels the walk; the carry goes on
        car = lift_car()
        p_far = far_point(15.0)
        n_fl = len(flights)
        L.throw(ch, p_far)
        run(s, m, 0.3, 1 / 30)
        w.walk_to(ch, far_point(4.0))                # the player's move order
        run(s, m, 0.3, 1 / 30)
        check("cancel: a move order ends the walk to throw; still carrying, nothing thrown",
              getattr(ch, "carry_walk", None) is None and ch.carrying is car and len(flights) == n_fl
              and getattr(ch, "carry_ready", False))
        run(s, m, 1.5, 1 / 30)
        # the unanswered press throws at the aimed point (walking into range again), not toward the facing
        ch.dest, ch.path, ch.speed = None, [], 0.0
        w.raise_skill_event(ch, 7, 0x10000023)
        run(s, m, 0.5, 1 / 30)
        cw = getattr(ch, "carry_walk", None)
        check("press: the unanswered press goes for the aimed point (liftable_press_aim), walking into range",
              cw is not None and math.hypot(cw["point"][0] - p_far[0], cw["point"][1] - p_far[1]) < 0.01
              and len(flights) == n_fl, cw)
        t0 = m.t
        while len(flights) == n_fl and m.t - t0 < 8.0:
            run(s, m, 1 / 30, 1 / 30)
        check("press: then thrown at the aimed point", len(flights) > n_fl
              and math.hypot(flights[-1][1][0] - p_far[0], flights[-1][1][1] - p_far[1]) < 0.01, flights[-1:])
        run(s, m, 2.0)
        # a stop (skill order of another slot: destination cleared, path left over) cancels too
        car = lift_car()
        p_far = far_point(15.0)
        L.throw(ch, p_far)
        run(s, m, 0.2, 1 / 30)
        ch.dest, ch.speed = None, 0.0
        run(s, m, 0.1, 1 / 30)
        check("cancel: another skill's order (the destination cleared) ends the walk", getattr(ch, "carry_walk", None)
              is None and ch.carrying is car)
        # liftable_throw_walk = []: thrown at once, clamped to the range (as before)
        w.ic["liftable_throw_walk"] = []
        try:
            n_fl = len(flights)
            here = (ch.pos[0], ch.pos[1])
            L.throw(ch, p_far)
            run(s, m, 1.0, 1 / 30)
            d = math.hypot(flights[-1][1][0] - here[0], flights[-1][1][1] - here[1]) if len(flights) > n_fl else None
            check("liftable_throw_walk = []: thrown at once, clamped to the range", getattr(ch, "carry_walk", None) is None
                  and d is not None and abs(d - rng) < 0.05, d)
        finally:
            w.ic["liftable_throw_walk"] = ["vehicle"]
    finally:
        L._fly = orig_fly


def lift_throw_wreck_1205(cfg, data):
    """Tester report 2026-10-30 12:05 (docs/re-notes/liftable-lift-throw-wreck.md): the vehicle's toss onto the champion
    as snapped states with the lob's 3D velocity (it crept along the ground at speed 0 before), the carried vehicle
    turned and stopped with the champion at the throw, and the wreck removed with the explosion (Vfx_OnExplode after the
    break keys)."""
    print("vehicle lift / throw / wreck (tester report 2026-10-30 12:05)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 3.0)
    ch = w.champion
    ch.stolen[7] = data.stolen_power(0x480003CB)[0]

    class _Inst:
        slot, removed = 7, False

        def post(self, ev, delay, *a):
            pass

    car = next(e for e in m.liftables.props if e.liftable == "vehicle")
    ch.pos = [car.pos[0] - 2.0, car.pos[1], car.pos[2]]
    ch.dest, ch.path, ch.speed = None, [], 0.0
    run(s, m, 0.5)
    _c, toss_at, catch_at, ready_at = m.liftables._toss_timeline(ch)
    ground, seq0 = car.pos[2], getattr(car, "tele_seq", 1)
    m.liftables.lift(ch, car, _Inst())
    toss, t0 = [], m.t
    while m.t - t0 < catch_at + 0.02:
        run(s, m, 1 / 30, 1 / 30)
        if getattr(car, "tossing", False):
            toss.append((round(m.t - t0, 3), car.speed, getattr(car, "vel_pitch", None), getattr(car, "tele_seq", 1),
                         car.pos[2]))
    pitches = [p for _t, _v, p, _q, _z in toss]
    check("toss: every state snapped (newer teleport sequence) with the lob's speed and a velocity pitch going from up "
          "to down (liftable_toss_velocity)", len(toss) >= 5 and all(v > 0.5 for _t, v, _p, _q, _z in toss)
          and all(p is not None for p in pitches) and pitches[0] > 0 and pitches[-1] < pitches[0]
          and len({q for *_r, q, _z in toss}) == len(toss) and toss[0][3] != seq0, toss[:4])
    check("toss: the first state leaves the ground at the toss frame (f 0.00 sent)",
          any(lbl == f"{car.name} tossed onto {ch.name} (f 0.00)" for lbl in s.labels()) and toss[0][4] >= ground - 1e-6)
    run(s, m, 0.2, 1 / 30)
    check("catch: the velocity pitch and facing offset leave the carried vehicle's state",
          ch.carrying is car and getattr(car, "vel_pitch", None) is None and getattr(car, "facing_offset", None) is None
          and abs(car.pos[2] - ch.pos[2] - 2.5) < 0.01, (getattr(car, "vel_pitch", None), car.pos))
    # the champion walks with it, then throws while walking
    run(s, m, 1.6, 1 / 30)
    ch.dest, ch.speed = [ch.pos[0], ch.pos[1] + 6.0, ch.pos[2]], ch.move_speed
    ch.heading = math.pi / 2
    run(s, m, 0.2, 1 / 30)
    m.liftables._carry(ch, car, force=True)
    walking = car.speed
    n0 = len(s.sent)
    m.liftables.throw(ch, [ch.pos[0] + 6.0, ch.pos[1], ch.pos[2]])
    lbls = s.labels(n0)
    check("throw while walking: the carried vehicle is stopped and turned with the champion at once "
          "(liftable_throw_turn_object)", walking > 0 and car.speed == 0.0 and abs(car.heading) < 1e-6
          and any(lbl == f"{car.name} carried over the head" for lbl in lbls), (walking, car.speed, car.heading, lbls[:4]))
    n1 = len(s.sent)
    marks = []
    for _ in range(90):
        run(s, m, 1 / 30, 1 / 30)
        for lbl in s.labels(n1):
            marks.append((round(m.t, 3), lbl))
        n1 = len(s.sent)
    at = lambda key: next((t for t, lbl in marks if lbl.startswith(f"{car.name}: {key}")), None)  # noqa: E731
    land = next((t for t, lbl in marks if lbl.startswith(f"{car.name}: rebuild pieces at the landing")), None)
    brk, boom = at("Destructible_OnCompletelyDestroyed"), at("Vfx_OnExplode (0x8d, late)")
    check("landing: the break keys on the intact wreck, then Vfx_OnExplode 0.75 s after the landing removes it "
          "(liftable_land_explode)", None not in (land, brk, boom) and brk < boom
          and abs(boom - land - 0.75) <= 0.05, (land, brk, boom))
    # the switches back
    w.ic["liftable_toss_velocity"], w.ic["liftable_land_explode"] = [], {}
    w.ic["liftable_attach_rebuild_attached_only"] = False
    try:
        car2 = next(e for e in m.liftables.props if e.liftable == "vehicle" and e is not car)
        ch.pos = [car2.pos[0] - 2.0, car2.pos[1], car2.pos[2]]
        ch.dest, ch.path, ch.speed = None, [], 0.0
        run(s, m, 0.5)
        n_lift = len(s.sent)
        m.liftables.lift(ch, car2, _Inst())
        old, t0 = [], m.t
        while m.t - t0 < catch_at:
            run(s, m, 1 / 30, 1 / 30)
            if getattr(car2, "tossing", False):
                old.append((car2.speed, getattr(car2, "vel_pitch", None)))
        check("liftable_toss_velocity [] = the toss states at speed 0 with no velocity pitch, as before",
              old and all(v == 0.0 and p is None for v, p in old), old[:3])
        run(s, m, 1.5, 1 / 30)
        check("liftable_attach_rebuild_attached_only false = the 0x8B piece rebuild over the head at the catch, as before",
              any(f"{car2.name}: rebuild pieces, over the head (0x8b)" in lbl for lbl in s.labels(n_lift)))
        n2 = len(s.sent)
        m.liftables.throw(ch, [ch.pos[0] + 6.0, ch.pos[1], ch.pos[2]])
        run(s, m, 3.0, 1 / 30)
        check("liftable_land_explode {} = no Vfx_OnExplode (the wreck stays until its removal)",
              not any(f"{car2.name}: Vfx_OnExplode" in lbl for lbl in s.labels(n2))
              and any(f"{car2.name}: Destructible_OnBreak" in lbl for lbl in s.labels(n2)))
    finally:
        w.ic["liftable_toss_velocity"], w.ic["liftable_land_explode"] = ["vehicle"], {"vehicle": 0.75}
        w.ic["liftable_attach_rebuild_attached_only"] = True


def superstrength_softlock(cfg, data):
    """Tester report 2026-10-30 11:23 (docs/re-notes/liftable-softlock.md): the Super Strength soft-lock of 11:16:33 -
    the input back once per lift, no lift of a thrown / gone object or through a stale TargetIID, the real slot table
    kept across a lift during the previous restore, the watchdog (object gone, lift / carry timeouts), and Super
    Strength usable after all of it. Runs the real script 0x34000164."""
    print("Super Strength soft-lock (tester report 2026-10-30 11:23)")
    s, w, m = make(cfg, data, 0x40000C82)
    logs = []
    m.log = w.log = logs.append
    for k in ("liftable_throw_on_press", "liftable_carry_timeout", "liftable_lift_timeout", "liftable_watchdog",
              "liftable_lift_guard", "liftable_keep_base_block", "liftable_input_back_per_lift"):
        w.ic[k] = copy.deepcopy(config.DEFAULTS["ics"][k])
    run(s, m, 14.0)
    ch = w.champion
    block, skill = data.stolen_power(0x480003CB)
    skill.slot = 7
    ch.kit[7], ch.ranks[7], ch.stolen[7] = skill, 1, block
    w.start_kit_slot(ch, 7)
    ch.safe_zone = False
    inst = ch.skill_insts[7]
    L = m.liftables

    def fresh():                                    # the 90 s cooldown and the repeat guard run on the wall clock
        ch.ready_at.pop(7, None)
        w.combat.of(ch).cooldowns.pop(7, None)
        ch.__dict__.get("last_cast_at", {}).clear()

    def near(obj):
        ch.pos = [obj.pos[0] - 2.0, obj.pos[1], obj.pos[2]]
        ch.dest, ch.path, ch.speed = None, [], 0.0
        run(s, m, 0.3, 0.05)

    def lying(kind, but=()):
        return next(e for e in L.props if e.liftable == kind and getattr(e, "carried_by", None) is None
                    and not getattr(e, "flying", False) and not getattr(e, "broken", False) and e not in but)

    def cast_lift(obj):
        fresh()
        near(obj)
        n = len(s.sent)
        w.cast(ch, 7, obj, None)
        for _ in range(60):
            run(s, m, 0.05, 0.05)
            if getattr(ch, "carry_ready", False):
                break
        return n

    def can_walk():
        ok = w.walk_to(ch, [ch.pos[0] + 1.0, ch.pos[1], ch.pos[2]])
        ch.dest, ch.path, ch.speed = None, [], 0.0
        return ok

    # 1. the first lift of the match (as 11:07:35): input back, cooldown kept ready, the champion can walk
    rock = lying("rock")
    n0 = cast_lift(rock)
    check("1st lift: carried, Super Strength's S4 got its input back (the slot's kept-ready 0x20F8), he can walk",
          ch.carrying is rock and any("kept ready while carrying (0x20f8)" in lbl for lbl in s.labels(n0)) and can_walk(),
          s.labels(n0)[-6:])
    pt = [ch.pos[0] + 4.0, ch.pos[1], ch.pos[2]]
    fresh()
    w.cast(ch, 7, None, pt)                         # the client's throw order (target 0x0)
    run(s, m, 0.25, 0.05)
    check("1st throw: thrown, in flight", getattr(rock, "flying", False) or getattr(rock, "broken", False))
    # 2. 11:16:33.659: a slot-7 order with target 0x0 right after the throw: the VM's TargetIID is still the rock
    run(s, m, 0.2, 0.05)
    fresh()
    nr = len(logs)
    w.cast(ch, 7, None, [ch.pos[0] + 2.0, ch.pos[1], ch.pos[2]])
    run(s, m, 0.1, 0.05)
    check("a target-0x0 order after the throw does not re-lift the thrown rock (liftable_lift_guard: stale TargetIID / "
          "in flight), and Super Strength's script is ended", getattr(ch, "carrying", None) is None
          and getattr(rock, "carried_by", None) is None
          and any("does not lift" in t for t in logs[nr:]), logs[nr:][-5:])

    class _Inst:
        slot, removed = 7, False

        def __init__(self, req=None):
            self.posts = []
            if req is not None:
                self.request = req

        def post(self, ev, delay, *a):
            self.posts.append(ev)
    fake = _Inst()
    L.lift(ch, rock, fake)
    check("a thrown / landed object cannot be lifted; the request ends Super Strength (0x10000009)",
          getattr(ch, "carrying", None) is None and fake.posts == [0x10000009], fake.posts)
    other = lying("rock", (rock,))
    near(other)
    stale = _Inst({})
    L.lift(ch, other, stale)
    check("a lift through a stale TargetIID (the order had none) is refused",
          getattr(ch, "carrying", None) is None and stale.posts == [0x10000009], stale.posts)
    # 3. a second lift soon after the throw, while the slot restore (liftable_slot_restore_delay) is pending
    car = lying("vehicle")
    n1 = cast_lift(car)
    check("2nd lift (a vehicle, 0.6 s after the throw): input back again (once per lift, not per script instance), "
          "the champion can walk while carrying (no S4 input hold)", ch.carrying is car and getattr(ch, "carry_ready", False)
          and any("kept ready while carrying (0x20f8)" in lbl for lbl in s.labels(n1)) and can_walk(),
          (getattr(ch, "carrying", None), s.labels(n1)[-6:]))
    fresh()
    w.cast(ch, 7, None, [ch.pos[0] + 5.0, ch.pos[1], ch.pos[2]])
    run(s, m, 4.0, 0.05)
    check("after the 2nd throw the slot holds Super Strength's own table again (liftable_keep_base_block)",
          getattr(ch, "carrying", None) is None and ch.stolen[7] == block and getattr(ch, "carry_base_block", None) is None,
          (len(ch.stolen[7]), len(block)))
    # the race itself: a lift whose previous restore is still pending
    r2 = lying("rock", (rock, other))
    cast_lift(r2)
    fresh()
    w.cast(ch, 7, None, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    run(s, m, 0.45, 0.05)                           # thrown, the restore still waits
    r3 = lying("rock", (rock, other, r2))
    cast_lift(r3)
    fresh()
    w.cast(ch, 7, None, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    run(s, m, 4.0, 0.05)
    check("a lift during the previous carry's pending restore: Super Strength's table comes back, not the throw "
          "skill's (11:16:59.425's 1432-byte slot table)", ch.stolen[7] == block, (len(ch.stolen[7]), len(block)))
    # 4. the object removed in the champion's hands (the 11:16:34.551 ghost): released at once
    r4 = lying("rock", (rock, other, r2, r3))
    cast_lift(r4)
    nl = len(logs)
    L._gone(r4)
    run(s, m, 0.1, 0.05)
    check("watchdog: the carried object is gone -> the carry ends at once (speed, carry state, Super Strength's script)",
          getattr(ch, "carrying", None) is None and ch not in L.carriers and not hasattr(ch, "carry_saved_speed")
          and any("ended (the object is gone)" in t for t in logs[nl:]), logs[nl:][-4:])
    run(s, m, 4.0, 0.05)
    check("watchdog: Super Strength's table is back after the ghost carry", ch.stolen[7] == block)
    # 5. a lift that never gets ready (its Hold lost) is made ready; a carry kept too long is thrown
    r5 = other                                      # the one the stale-target request left lying
    fresh()
    near(r5)
    L._hold = lambda *a: None                       # the scheduled Hold is lost
    w.cast(ch, 7, r5, None)
    run(s, m, 1.0, 0.05)
    del L._hold
    stuck = getattr(ch, "carrying", None) is r5 and not getattr(ch, "carry_ready", False)
    run(s, m, 2.5, 0.05)
    check("watchdog: a lift not ready after liftable_lift_timeout s is made ready",
          stuck and getattr(ch, "carry_ready", False), (stuck, getattr(ch, "carry_ready", None)))
    w.ic["liftable_carry_timeout"] = 1.0
    try:
        run(s, m, 1.5, 0.05)
        check("watchdog: a carry longer than liftable_carry_timeout s is thrown (liftable_carry_timeout_action)",
              getattr(r5, "flying", False) or getattr(r5, "broken", False), logs[-3:])
    finally:
        w.ic["liftable_carry_timeout"] = config.DEFAULTS["ics"]["liftable_carry_timeout"]
    run(s, m, 4.0, 0.05)
    # 6. Super Strength still works after all of it
    car2 = lying("vehicle")
    cast_lift(car2)
    check("after every path above, Super Strength lifts again (S0 -> S4, carried, ready)", ch.carrying is car2
          and getattr(ch, "carry_ready", False) and inst.regions and ch.stolen[7] != block, getattr(ch, "carrying", None))
    fresh()
    w.cast(ch, 7, None, [ch.pos[0] + 5.0, ch.pos[1], ch.pos[2]])
    run(s, m, 4.0, 0.05)
    check("... and throws it, the slot back to Super Strength", getattr(ch, "carrying", None) is None
          and ch.stolen[7] == block)


def power_core_turret(cfg, data):
    """2026-10-29 tester report from the original-game video (docs/re-notes/power-core-turret.md): Crime Alley's third
    tower a side, the core's shield ring while it stands, its kept body and death keys, elites while it is down, its
    respawn, and the added parked vehicles."""
    print("power core turret / core shield / supers / vehicles (tester report 2026-10-29, original video)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 3.0)
    ct = {mu.team: mu for mu in m.structures if mu.role == "core_turret"}
    core = {mu.team: mu for mu in m.structures if mu.role == "core"}
    # 2026-10-30 tester report 13:00 (turret-pct-composite.md): team 1 is the lane-body twin 0x40000C8E again
    check("CA: a Power Core Turret per team (0x40000C8E / 0x40000C8D, match_structure_classes) at "
          "match_structure_pos (27 / 133, 77.5)",
          sorted(ct) == [1, 2] and ct[1].cls == 0x40000C8E and ct[2].cls == 0x40000C8D
          and all(abs(ct[t].ent.pos[0] - x) < 0.6 and abs(ct[t].ent.pos[1] - 77.5) < 0.6 for t, x in ((1, 27.0), (2, 133.0))),
          {t: (hex(mu.cls), mu.ent.pos[:2]) for t, mu in ct.items()})
    props = {p[0]: p[2] for p in ct[1].ent.extra_props} if 1 in ct else {}
    check("Power Core Turret: data health (3500 / 3000), minimap 3, turret flags 0x210, warning ring 0x10000C5D",
          ct and ct[1].ent.max_health == 3500 and ct[2].ent.max_health == 3000 and props.get(0x2A1) == 1
          and any(p[0] == 0x1000019D and (p[2] & 0x10) for p in ct[1].ent.extra_props) and props.get(0x10000C5D) == 1,
          (ct[1].ent.max_health if ct else None, ct[2].ent.max_health if ct else None, props.get(0x2A1)))
    check("the core is protected while its Power Core Turret stands; the turret needs the inner turret down first",
          m.protected(core[2]) and any(mode == "all" and ct[2] in deps for mode, deps in core[2].requires)
          and m.protected(ct[2]))
    lbls = s.labels()
    check("core shield: both cores play Vfx_Indestructible (match_core_shield)",
          all(any(lbl and lbl.startswith(core[t].ent.name + ":") and "Vfx_Indestructible (0x8d" in lbl for lbl in lbls)
              for t in (1, 2)) and core[2].shielded, [lbl for lbl in lbls if lbl and "Indestructible" in lbl])
    for role in ("turret", "dampener", "inner_turret"):    # the enemy lane / second structures down (in order)
        for mu in [x for x in m.structures if x.team == 2 and x.role == role]:
            kill(w, mu.ent)
    run(s, m, 1.0)
    comp1 = dict(m.waves.composition("mid", 1))
    comp2 = dict(m.waves.composition("mid", 2))
    # 2026-10-29 tester report 21:10 (power-core-turret.md 8.6): the supers come with the second structure, not the third
    check("supers: the red x 120 dampener down (Power Core Turret standing) -> team 1's waves bring the elites "
          "0x40000C9C / 0x40000C9B (match_supers_on_structure_down); team 2's stay normal",
          ct[2].ent.alive and comp1.get("melee") == 0x40000C9C and comp1.get("ranged") == 0x40000C9B
          and comp2.get("melee") == m.map["minions"]["melee"], (comp1, comp2))
    was_down = cfg["ics"].get("match_supers_on_structure_down")
    w.ic["match_supers_on_structure_down"] = {}
    check("match_supers_on_structure_down = {}: normal waves with the dampener down",
          dict(m.waves.composition("mid", 1)).get("melee") == m.map["minions"]["melee"])
    w.ic["match_supers_on_structure_down"] = was_down
    before = len(s.sent)
    kill(w, ct[2].ent)
    run(s, m, 1.5)
    after = s.labels(before)
    check("Power Core Turret down: its body stays (match_keep_body_roles) and plays _Defeat_OnDead (graph Death)",
          ct[2].ent.eid in w.entities and not ct[2].ent.alive
          and any(lbl and lbl.startswith(ct[2].ent.name + ":") and "_Defeat_OnDead" in lbl for lbl in after), after[-12:])
    check("core shield: the red core plays Vfx_Indestructible_Stop and becomes attackable",
          any(lbl and lbl.startswith(core[2].ent.name + ":") and "Vfx_Indestructible_Stop" in lbl for lbl in after)
          and not core[2].shielded and not m.protected(core[2]) and core[1].shielded)
    was = cfg["ics"].get("match_core_turret_supers")
    w.ic["match_core_turret_supers"] = {"crime_alley": {"melee": "0x40000C9C", "ranged": "0x40000C9B"}}
    w.ic["match_supers_on_structure_down"] = {}
    check("match_core_turret_supers (the fase3-in rule, off by default): elites while the Power Core Turret is down",
          dict(m.waves.composition("mid", 1)).get("melee") == 0x40000C9C)
    w.ic["match_core_turret_supers"] = was
    w.ic["match_supers_on_structure_down"] = was_down
    old_eid = ct[2].ent.eid
    before = len(s.sent)
    # 2026-10-30 (core-door-regen.md 2-3): the core no longer shoots, so team 1's waves would take the exposed red core
    # within the 300 s and end the match; it is kept out of reach while the respawn is checked
    core[2].invulnerable = True
    run(s, m, float(cfg["ics"]["match_core_turret_respawn"]) + 2.0)
    core[2].invulnerable = False
    new = next(mu for mu in m.structures if mu.role == "core_turret" and mu.team == 2)
    after = s.labels(before)
    check("Power Core Turret and dampener respawn after 300 s: old body gone, shield back, waves normal",
          new.ent.alive and new.ent.eid != old_eid and old_eid not in w.entities and core[2].shielded
          and m.protected(core[2]) and dict(m.waves.composition("mid", 1)).get("melee") == m.map["minions"]["melee"]
          and any(lbl and "Vfx_Indestructible (0x8d" in lbl and lbl.startswith(core[2].ent.name) for lbl in after))
    # the added parked vehicles (power-core-turret.md 6): on their spot, yaw, footprint blocked, 1.75 m lane-side walkable
    added = [sp for sp in (cfg["ics"].get("liftable_props_added_by_map") or {}).get("crime_alley") or ()
             if sp.get("enabled", True)]
    cars = [e for e in m.liftables.props if e.liftable == "vehicle"]
    ok_cars = []
    for sp in added:
        e = next((c for c in cars if abs(c.pos[0] - sp["pos"][0]) < 0.01 and abs(c.pos[1] - sp["pos"][1]) < 0.01), None)
        lane_side = 1.0 if sp["pos"][1] < 77.5 else -1.0
        ok_cars.append(e is not None and e.lift_spec.get("yaw") == sp["yaw"] and not w.nav.walkable(e.pos[0], e.pos[1])
                       and w.nav.walkable(e.pos[0], e.pos[1] + lane_side * 1.75))
    check("added vehicles: police car, gaslight pickup, red convertible, dark truck on their spots and yaw, blocked, "
          "lane free", len(added) == 4 and all(ok_cars), ok_cars)


def structures_2110(cfg, data):
    """2026-10-29 tester report 21:10 (power-core-turret.md 8): the Power Core Turret's Vfx_Fade_In, the x 40 / 120
    dampener back on its ring (no gear plate, no server head), the heads without team keys, the vehicles' classes."""
    print("Crime Alley structures / heads / vehicles (tester report 2026-10-29 21:10)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 3.0)
    lbls = s.labels()
    ct1 = next(mu for mu in m.structures if mu.role == "core_turret" and mu.team == 1)
    mine = [lbl for lbl in lbls if lbl and lbl.startswith(ct1.ent.name + ":") and "(0x8d)" in lbl]
    # 2026-10-30 tester report 13:00 (turret-pct-composite.md): the lane body plays Vfx_Active only
    check("Power Core Turret: Vfx_Active only, no Vfx_AI_Active / Object_Reset (match_structure_scriptlets)",
          [lbl.split(": ")[1].split(" ")[0] for lbl in mine] == ["Vfx_Active"], mine)
    damp = {mu.team: mu for mu in m.structures if mu.role == "dampener"}
    check("x 40 / 120: the dampener class 0x40000C88 / 0x40000C87 again (match_role_swaps {}), no inner turret",
          sorted(damp) == [1, 2] and damp[1].cls == 0x40000C88 and damp[2].cls == 0x40000C87
          and abs(damp[1].ent.pos[0] - 40.0) < 0.6 and abs(damp[2].ent.pos[0] - 120.0) < 0.6
          and not any(mu.role == "inner_turret" for mu in m.structures), {t: hex(mu.cls) for t, mu in damp.items()})
    check("the dampener: no gear plate and no server head (its own Vfx_AI_Active head), its keys played",
          not any(lbl and lbl.startswith(f"spawn {damp[1].ent.name} plate") or lbl.startswith(f"spawn {damp[1].ent.name} head")
                  for lbl in lbls if lbl)
          and getattr(damp[1], "head", None) is None
          and any(lbl and lbl.startswith(damp[1].ent.name + ":") and "Vfx_AI_Active (0x8d" in lbl for lbl in lbls))
    check("order: lane turret -> dampener -> Power Core Turret -> core",
          m.protected(damp[2]) and m.protected(ct1) and any(damp[1] in deps for _mode, deps in ct1.requires))
    tur = next(mu for mu in m.structures if mu.role == "turret" and mu.team == 1)
    head = getattr(tur, "head", None)
    hl = [lbl for lbl in lbls if head is not None and lbl and lbl.startswith(head.name + ":")]
    # 2026-10-29 tester report 23:03 (two heads, the white one wrong): no server head when the body's own
    # Vfx_AI_Active makes one (match_turret_head_skip_own_child)
    check("lane turret: no server-made head (its own Vfx_AI_Active head), no Vfx_Active_Blue / _Red anywhere",
          head is None and not any("Vfx_Active_" in lbl for lbl in lbls if lbl and "head" in lbl), hl)
    n = len(s.sent)
    tur.target = object()
    m.units._turret_target(tur, None)
    tur.target = None
    check("target lost: no Vfx_Active_* on the head", not any("Vfx_Active_" in lbl for lbl in s.labels(n) if lbl))
    cars = {(round(e.pos[0], 2), round(e.pos[1], 2)): e for e in m.liftables.props if e.liftable == "vehicle"}
    conv = cars.get((107.4, 72.8))
    truck = cars.get((35.5, 81.85))
    police = cars.get((124.5, 81.9))
    check("vehicles: the red convertible 0x4000081C on the south curb (was the white sports car), the dark gaslight truck "
          "0x4000081B by the blue x 40 turret, the police car 0x40000459 by the red base",
          conv is not None and conv.class_id == 0x4000081C and truck is not None and truck.class_id == 0x4000081B
          and police is not None and police.class_id == 0x40000459,
          {k: hex(e.class_id) for k, e in cars.items()})


def heads_raider_end_2303(cfg, data):
    """2026-10-29 tester report 23:03 (docs/re-notes/turret-heads-coredeath.md): one head per turret (the body's own
    Vfx_AI_Active head, no server copy), the blue Power Core Turret on the lane body, the Raider's kill voice by team,
    and the match end that waits for the end cinematic (billboard + victory voice at frame 225, 0x1000000E after it)."""
    print("turret heads / Power Core Turret body / Raider voice / end timing (tester report 2026-10-29 23:03)")
    from ics.wire import KIND_ENUM
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 3.0)
    lbls = s.labels()
    tur = {mu.team: mu for mu in m.structures if mu.role == "turret"}
    check("lane turrets: no server-made head (match_turret_head_skip_own_child), their own Vfx_AI_Active played",
          all(getattr(mu, "head", None) is None for mu in tur.values())
          and not any(lbl.startswith(f"spawn {mu.ent.name} head") for mu in tur.values() for lbl in lbls)
          and all(any(lbl.startswith(mu.ent.name + ": Vfx_AI_Active (0x8d") for lbl in lbls) for mu in tur.values()),
          [lbl for lbl in lbls if "head" in lbl][:4])
    ct = {mu.team: mu for mu in m.structures if mu.role == "core_turret"}
    check("Power Core Turret team 1: class 0x40000C8E on the lane body 0x2E000AA0 (2026-10-30 13:00), 3500 HP, "
          "server flag head 0x2E000AC3; team 2 0x40000C8D (0x2E000AA0 by data), the same",
          ct[1].cls == 0x40000C8E and ct[1].ent.world_state == 0x2E000AA0 and ct[1].ent.max_health == 3500
          and all(getattr(ct[t], "head", None) is not None and ct[t].head.class_id == 0x2E000AC3 for t in (1, 2))
          and ct[2].cls == 0x40000C8D and ct[2].ent.world_state == 0x2E000AA0,
          (hex(ct[1].cls), hex(ct[1].ent.world_state or 0)))
    saved = {k: cfg["ics"].get(k) for k in ("match_turret_head_skip_own_child", "match_structure_classes")}
    cfg["ics"]["match_turret_head_skip_own_child"] = False
    try:
        s2, w2, m2 = make(cfg, data, 0x40000C82)
    finally:
        cfg["ics"].update(saved)
    heads = [mu.head for mu in m2.structures if getattr(mu, "head", None) is not None]
    ct2 = next(mu for mu in m2.structures if mu.role == "core_turret" and mu.team == 1)
    check("switches off: the server heads come back (with the body's side); match_structure_classes gives team 1 the "
          "lane-body twin 0x40000C8E (fase3-ip..ir)",
          len(heads) == 4 and all((0x100007A2, KIND_ENUM, 3 if h.team == 1 else 5) in h.extra_props for h in heads)
          and ct2.cls == 0x40000C8E and ct2.ent.world_state == 0x2E000AA0, (len(heads), hex(ct2.cls)))
    # the Raider's kill voice by team
    c = (m.ic.get("match_raider") or {}).get("crime_alley") or {}
    voices = {}
    for team in (1, 2):
        mu = m.bosses.spawn_boss(int(str(c["cls"]), 0), (80.0, 97.66), 180.0, "raider", ())
        mu.boss_cfg = dict(c, respawn=0)
        n = len(s.sent)
        mu.ent.alive = False
        m.bosses.on_killed(mu, type("Killer", (), {"team": team})())
        run(s, m, 6.0)
        voices[team] = [lbl for lbl in s.labels(n) if "event 61 " in lbl or "line 0x2bd" in lbl]
    check("Raider killed by our team: only event 61 (697); by the enemy: only line 701 (0x2BD) "
          "(match_boss_kill_voice_by_team)",
          len(voices[1]) == 1 and "event 61 " in voices[1][0] and len(voices[2]) == 1 and "line 0x2bd" in voices[2][0],
          voices)
    # the end: billboard and victory voice at the cinematic's frame 225, 0x1000000E after the 11.5 s cinematic
    s3, w3, m3 = make(cfg, data, 0x40000C82)
    run(s3, m3, 14.0)
    n = len(s3.sent)
    t0 = m3.t
    m3.end(1, "test")
    seen = {}
    for _ in range(int(14.0 / 0.25)):
        run(s3, m3, 0.25)
        for lbl in s3.labels(n):
            for key, pat in (("bill", "billboard type 9 "), ("voice", "event 29 "), ("end", "(0x1000000e)")):
                if pat in lbl and key not in seen:
                    seen[key] = m3.t - t0
    check("end: the end cinematic 0x3500003A starts at once, VICTORY (billboard 9) at ~7.5 s, the victory voice "
          "(event 29) after it, 0x1000000E at ~12 s (match_end_timing)",
          s3.cinematics and s3.cinematics[-1] == 0x3500003A and 7.4 <= seen.get("bill", 0) <= 8.0
          and seen.get("voice", 0) >= seen.get("bill", 99) and seen.get("voice", 99) <= 11.5
          and 11.9 <= seen.get("end", 0) <= 12.6, (seen, [hex(c) for c in s3.cinematics]))
    saved = cfg["ics"].get("match_end_timing")
    cfg["ics"]["match_end_timing"] = {}
    try:
        s4, w4, m4 = make(cfg, data, 0x40000C82)
        run(s4, m4, 14.0)
        n = len(s4.sent)
        m4.end(1, "test")
        at_once = any("billboard type 9 " in lbl for lbl in s4.labels(n))
        run(s4, m4, 4.5)
        notice = any("(0x1000000e)" in lbl for lbl in s4.labels(n))
    finally:
        cfg["ics"]["match_end_timing"] = saved
    check("match_end_timing {}: the fase3-io timing (billboard at once, 0x1000000E match_end_hold s later)",
          at_once and notice, (at_once, notice))


def turret_plate_head_scorecard_1123(cfg, data):
    """2026-10-30 tester report 11:23 (docs/re-notes/scorecard-panel-turret-head.md): the Power Core Turret on its gear
    plate, structures pick only targets they keep (no Target_Acquired / Target_Lost in the same tick), 0x2104 with the
    encounter after its accolade lists."""
    print("Power Core Turret plate / turret target flapping / 0x2104 encounter (tester report 2026-10-30 11:23)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 3.0)
    lbls = s.labels()
    ct = {mu.team: mu for mu in m.structures if mu.role == "core_turret"}
    # 2026-10-30 tester report 12:05 ("the tower's base is not the correct one"): the plate went again
    check("Power Core Turrets: no gear plate (match_turret_plates without core_turret, 2026-10-30 12:05)",
          not any(lbl and "core_turret" in lbl and "plate" in lbl for lbl in lbls),
          [lbl for lbl in lbls if lbl and "plate" in lbl])
    saved = cfg["ics"].get("match_turret_plates")
    cfg["ics"]["match_turret_plates"] = {"turret": 0x2E000A9F, "inner_turret": 0x2E000A9F, "core_turret": 0x2E000A9F}
    try:
        s2, w2, m2 = make(cfg, data, 0x40000C82)
        run(s2, m2, 1.0)
    finally:
        cfg["ics"]["match_turret_plates"] = saved
    check("match_turret_plates with core_turret: each Power Core Turret on the gear plate 0x2E000A9F (fase3-ir)",
          all(any(lbl and lbl.startswith(f"spawn {ct[t].ent.name} plate (0x2e000a9f)") for lbl in s2.labels())
              for t in (1, 2)))

    # the flap: a minion just outside the turret's reach (range + its radius) but inside range + 1 m
    run(s, m, 13.0 + 45.0 + 4.0)
    tur = next(mu for mu in m.structures if mu.role == "turret" and mu.team == 1)
    foes = [mu for mu in m.units.by_eid.values() if mu.role == "minion" and mu.team == 2 and mu.ent.alive]
    check("flap: an enemy minion exists", bool(foes), len(foes))
    if not foes:
        return
    foe = foes[0]
    for mu in list(m.units.by_eid.values()):
        if mu.role == "minion" and mu is not foe:
            kill(w, mu.ent)
    w.champion.pos = [5.0, 77.5, w.champion.pos[2]]
    reach = m.units._reach(tur, foe.ent)
    # these checks look at Target_Acquired / Target_Lost, which 2026-10-30 12:05 stopped for client-child heads
    m.ic["match_turret_own_head_no_target_keys"] = False

    def place(d):
        foe.ent.pos = [tur.ent.pos[0] + d, tur.ent.pos[1], foe.ent.pos[2]]
        foe.next_think = 1e18
        tur.target = None
        n = len(s.sent)
        m.units.think(tur, s.clock)
        m.units.act(tur, 0.05, s.clock)
        got = [lbl for lbl in s.labels(n) if lbl and lbl.startswith(tur.ent.name + ":")]
        return tur.target, got
    gap = (reach + tur.range + 1.0) / 2.0
    t_out, l_out = place(gap)
    check("flap: a minion between the reach and range + 1 m is not picked (no Target_Acquired / Target_Lost pair, "
          "match_turret_pick_in_reach)", t_out is None and not any("0x1000014a" in x or "0x1000002c" in x for x in l_out)
          and reach < tur.range + 1.0, (round(reach, 2), tur.range, l_out))
    t_in, l_in = place(reach - 0.3)
    check("flap: within the reach it is picked and kept through act() (Target_Acquired only)",
          t_in is foe.ent and any("0x1000014a" in x for x in l_in) and not any("0x1000002c" in x for x in l_in), l_in)
    m.ic["match_turret_pick_in_reach"] = False
    try:
        t_old, l_old = place(gap)
    finally:
        m.ic["match_turret_pick_in_reach"] = True
    check("match_turret_pick_in_reach false: the fase3-ip flap (acquired and lost in the same tick)",
          t_old is None and any("0x1000014a" in x for x in l_old) and any("0x1000002c" in x for x in l_old), l_old)
    m.ic["match_turret_own_head_no_target_keys"] = True

    # 0x2104's trailing u32 = the encounter (0xA7E0A0 param_21), 0 by default in the builder
    from ics import messages as MM
    body = frames(FakeSend(MM.character_level(0x4000080C, "X", 2, 1, 720, 15, 120, 0, 0.25, 0.8,
                                              encounter=0x40000C82)), 0)[0][4]
    body0 = frames(FakeSend(MM.character_level(0x4000080C, "X", 2, 1, 720, 15, 120, 0, 0.25, 0.8)), 0)[0][4]
    check("0x2104: u32 encounter + u8 0 after the six empty accolade lists (0 when not given)",
          struct.unpack_from("<I", body, len(body) - 5)[0] == 0x40000C82 and body[-1] == 0
          and struct.unpack_from("<I", body0, len(body0) - 5)[0] == 0 and len(body) == len(body0)
          and body[-29:-5] == bytes(24), body.hex())


def pct_look_turret_head_1205(cfg, data):
    """2026-10-30 tester report 12:05 (docs/re-notes/turret-head-pct-look.md): the Power Core Turret's own parts
    (0x40000C8F / 0x2E000AC4, no gear plate, Object_Reset after its keys) and no Target_Acquired / Target_Lost on a
    turret whose head is the client's own child (0x10000C66 still goes)."""
    print("Power Core Turret look / turret head on target (tester report 2026-10-30 12:05)")
    from ics.wire import KIND_ENUM
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 3.0)
    ct1 = next(mu for mu in m.structures if mu.role == "core_turret" and mu.team == 1)
    keys = [lbl.split(": ")[1].split(" ")[0] for lbl in s.labels()
            if lbl and lbl.startswith(ct1.ent.name + ":") and "(0x8d)" in lbl]
    check("Power Core Turret: the lane body plays Vfx_Active only (2026-10-30 13:00, turret-pct-composite.md)",
          keys == ["Vfx_Active"], keys)
    # 2026-10-30 tester report 13:00: the server-made parts (flag head, cylinder) with the body's side, no plate
    lbls = s.labels()
    for t, side in ((1, 3), (2, 5)):
        mu = next(x for x in m.structures if x.role == "core_turret" and x.team == t)
        parts = getattr(mu, "parts", None) or []
        check(f"Power Core Turret t{t}: cylinder 0x2E000A9A (side {side}, Vfx_Startup) and flag head 0x2E000AC3, no plate",
              len(parts) == 1 and parts[0].class_id == 0x2E000A9A and (0x100007A2, KIND_ENUM, side) in parts[0].extra_props
              and abs(parts[0].pos[2] - mu.ent.pos[2] + 0.25) < 1e-6
              and any(lbl.startswith(parts[0].name + ": Vfx_Startup") for lbl in lbls if lbl)
              and mu.head is not None and mu.head.class_id == 0x2E000AC3
              and not any(lbl.startswith(f"spawn {mu.ent.name} plate") for lbl in lbls if lbl),
              [(hex(p.class_id), p.extra_props[-2:]) for p in parts])
    m.units.remove(ct1)
    check("Power Core Turret falls: its head and cylinder leave with it",
          all(x.eid not in w.entities for x in [ct1.head] + ct1.parts))

    tur = next(mu for mu in m.structures if mu.role == "turret" and mu.team == 2)
    foe = w.champion
    n = len(s.sent)
    m.units._turret_target(tur, foe)
    tur.target = foe
    m.units._turret_target(tur, None)
    tur.target = None
    got = [lbl for lbl in s.labels(n) if lbl]
    check("own-head turret: target 0x10000C66 set and cleared, no Target_Acquired / Target_Lost "
          "(match_turret_own_head_no_target_keys)",
          sum("(0x10000C66" in x for x in got) == 2 and not any("0x1000014a" in x or "0x1000002c" in x for x in got), got)
    m.ic["match_turret_own_head_no_target_keys"] = False
    try:
        n = len(s.sent)
        m.units._turret_target(tur, foe)
        tur.target = foe
        m.units._turret_target(tur, None)
        tur.target = None
    finally:
        m.ic["match_turret_own_head_no_target_keys"] = True
    got = [lbl for lbl in s.labels(n) if lbl]
    check("match_turret_own_head_no_target_keys false: Target_Acquired / Target_Lost as before",
          any("0x1000014a" in x for x in got) and any("0x1000002c" in x for x in got), got)


def bot_shop_towers_end_1530(cfg, data):
    """2026-10-30 tester report 15:30 (docs/re-notes/bot-shop-towers-end.md): (1) a bot shops only in its base aura, a
    whole visit at once along its loadout's list, the held line's next tier first, saving for the step it cannot pay;
    (2) no minion / structure / champion under an enemy turret its minions do not hold, and it steps out of such a
    range; (3) after the match is over nothing fights: the bot is stopped, its casts refused, no damage."""
    print("bots: shop at base in order, no tower dive, nothing after the match is over (2026-10-30 15:30)")
    s, w, m, bot = _sweep_bot_match(cfg, data, [])
    brain = m.bots.brains[0]
    order = list(data.loadout(bot.class_id).get("artifacts") or ())
    check("AWW's loadout list starts 0x4CF, 0x925, 0x929, 0x4F2, 0x4B7, 0x40000D1A, 0x4E3 (the test's premise)",
          order[:7] == [0x400004CF, 0x40000925, 0x40000929, 0x400004F2, 0x400004B7, 0x40000D1A, 0x400004E3],
          [hex(x) for x in order[:7]])

    # (1) shopping
    bot.inventory = [0] * 6
    bot.in_base_aura, bot.gold = False, 5000.0
    brain.bought_at = -1e9
    brain.shop()
    check("shop: alive outside its base aura the bot buys nothing", not any(bot.inventory) and bot.gold == 5000.0,
          (bot.inventory, bot.gold))
    bot.alive_was = bot.alive
    bot.alive = False
    brain.bought_at = -1e9
    brain.shop()
    bot.alive = bot.alive_was
    check("shop: dead outside its base aura neither (bot_shop_when_dead false: the original's script shops only with "
          "0x10000A23)", not any(bot.inventory), bot.inventory)
    bot.in_base_aura, bot.gold = True, 500.0 + 100.0 + 150.0 + 700.0
    brain.bought_at = -1e9
    n = len(s.sent)
    brain.shop()
    held = [d for d in bot.inventory if d]
    check("shop: at base one visit buys 0x4CF, the vial 0x925 and at once its upgrade 0x929, then saves 700 for "
          "0x4F2 (750): nothing out of order", sorted(held) == sorted([0x400004CF, 0x40000929]) and abs(bot.gold - 700.0)
          < 1e-6, ([hex(d) for d in held], bot.gold))
    check("shop: one 0x20E2 inventory message for the visit", sum(1 for lbl in s.labels(n) if "(0x20e2)" in lbl) == 1,
          [lbl for lbl in s.labels(n) if "0x20e2" in lbl])
    bot.gold = 700.0 + 1000.0
    brain.bought_at = -1e9
    brain.shop()
    held = [d for d in bot.inventory if d]
    check("shop: with 1700: 0x4F2 (750), then it saves for its upgrade 0x4B7 (1000 more) instead of buying the next "
          "line 0x4E3 (750, affordable)", 0x400004F2 in held and 0x400004E3 not in held and 0x400004B7 not in held
          and abs(bot.gold - 950.0) < 1e-6, ([hex(d) for d in held], bot.gold))
    bot.gold = 950.0 + 1000.0
    brain.bought_at = -1e9
    brain.shop()
    held = [d for d in bot.inventory if d]
    check("shop: then the upgrade 0x4B7 replaces 0x4F2 in its slot (price 1000)", 0x400004B7 in held
          and 0x400004F2 not in held and abs(bot.gold - 950.0) < 1e-6, ([hex(d) for d in held], bot.gold))
    # going home to shop
    far = brain.route[len(brain.route) // 2] if brain.route else [bot.pos[0] + 40.0, bot.pos[1]]
    bot.pos = [far[0], far[1], bot.pos[2]]
    bot.in_base_aura = False
    w.champion.pos = [far[0] + 60.0, far[1] + 60.0, w.champion.pos[2]]
    bot.gold = 100.0
    brain.state, brain.base_left_at, brain.plan_checked_at = "push", -1e9, -1e9
    check("shop: with little to spend it stays in its lane", not brain.wants_to_shop(s.clock))
    bot.gold = 3000.0
    brain.plan_checked_at = -1e9
    check("shop: with bot_shop_recall_value credits of buys it goes home to shop", brain.wants_to_shop(s.clock))
    brain.plan_checked_at = -1e9
    check("shop: ... once per bot_shop_recall_gap s", not brain.wants_to_shop(s.clock + 1.0))

    # (2) towers: the player's (team 1) turret is the bot's enemy shooter
    s, w, m, bot = _sweep_bot_match(cfg, data, [])
    run(s, m, 13.0 + 47.0)                                # the first wave is out
    brain = m.bots.brains[0]
    brain.next_decision = float("inf")
    m.ic["bot_tower_tactics"] = False                    # the 15:30 rules (18:12 ones: bot_tower_tactics_1812)
    ch = w.champion
    ch.pos = [ch.pos[0] + 200.0, ch.pos[1] + 200.0, ch.pos[2]]   # out of the way
    for mu in [x for x in m.units.by_eid.values() if x.role == "minion"]:
        mu.ent.pos = [mu.ent.pos[0] + 300.0, mu.ent.pos[1] + 300.0, mu.ent.pos[2]]   # the wave out of the way
    turret = next(mu for mu in m.structures if mu.team == ch.team and mu.role == "turret" and mu.ent.alive)
    tx, ty = turret.ent.pos[0], turret.ent.pos[1]
    hx, hy = brain.home()[:2]
    d = math.hypot(hx - tx, hy - ty) or 1.0
    ux, uy = (hx - tx) / d, (hy - ty) / d                 # from the turret towards the bot's base
    bait = m.units.spawn(m.map["minions"]["melee"], (tx + ux * 2.0, ty + uy * 2.0), ch.team, "minion", name="bait")
    bot.health = bot.max_health
    bot.pos = [tx + ux * (turret.range + 5.0), ty + uy * (turret.range + 5.0), bot.pos[2]]
    turret.target = None
    sight = m.ic.get("bot_sight", 9.0)
    m.ic["bot_sight"] = turret.range + 10.0              # the bait in sight from out of the turret's range
    t1 = brain.pick_target()
    check("towers: an enemy minion under the enemy turret with none of the bot's minions there is not taken",
          t1 is not bait.ent, getattr(t1, "name", t1))
    tank1 = m.units.spawn(m.map["minions"]["melee"], (tx + ux * 3.0, ty + uy * 3.0), bot.team, "minion", name="tank 1")
    turret.target = tank1.ent
    t2 = brain.pick_target()
    check("towers: ... nor with one minion of the bot tanking (bot_tower_min_tanks 2)", t2 is not bait.ent,
          getattr(t2, "name", t2))
    tank2 = m.units.spawn(m.map["minions"]["melee"], (tx + ux * 3.5, ty - uy * 0.5), bot.team, "minion", name="tank 2")
    t3 = brain.pick_target()
    check("towers: ... but is with two of its minions in range and the turret shooting one of them",
          t3 is bait.ent, getattr(t3, "name", t3))
    turret.target = None
    t4 = brain.pick_target()
    check("towers: the turret free again (not on the bot's minions): not taken", t4 is not bait.ent,
          getattr(t4, "name", t4))
    m.ic["bot_tower_awareness"] = False
    t5 = brain.pick_target()
    m.ic["bot_tower_awareness"] = True
    check("towers: bot_tower_awareness = false: the fase3-ir rule (any allied minion near the turret = covered) takes it",
          t5 is bait.ent, getattr(t5, "name", t5))
    m.ic["bot_sight"] = sight
    # standing in the range, not targeted yet: steps out
    for x in (tank1, tank2):
        m.units.remove(x)
        w.remove(x.ent, "test minion gone")
    near = w.nav.nearest(tx + ux * (turret.range - 1.5), ty + uy * (turret.range - 1.5), max_r=3.0) \
        if w.nav is not None else (tx + ux * (turret.range - 1.5), ty + uy * (turret.range - 1.5))
    bot.pos = [near[0], near[1], bot.pos[2]]
    brain.state, brain.goal, brain.target = "push", None, None
    turret.target = None
    brain.decide(s.clock)
    goal = brain.goal
    check("towers: a bot standing in an enemy turret's range its minions do not hold walks out before it is targeted",
          brain.state == "evade" and bot.attack_target is None and goal is not None
          and math.hypot(goal[0] - tx, goal[1] - ty) > turret.range + 1.5, (brain.state, goal, turret.range))
    # a champion under his turret: only a near-certain kill
    ch.pos = [tx + ux * 1.0, ty + uy * 1.0, ch.pos[2]]
    bot.pos = [ch.pos[0] + ux * 2.0, ch.pos[1] + uy * 2.0, bot.pos[2]]
    bot.health = bot.max_health
    ch.health = ch.max_health * 0.5
    brain.target, brain.chase_from, brain.ignore = None, None, {}
    c1 = brain.pick_target()
    dmg = float(bot.stats.get(0x10000B76, 0.0) or 0.0)
    ch.health = max(1.0, min(ch.max_health * 0.1, dmg))
    c2 = brain.pick_target()
    check("towers: an enemy champion under his free turret: not at half health, yes for a near-certain kill",
          c1 is not ch and c2 is ch, (getattr(c1, "name", c1), getattr(c2, "name", c2), dmg))
    ch.health = ch.max_health
    m.units.remove(bait)
    w.remove(bait.ent, "test minion gone")

    # (3) the match is over: nothing fights
    ch.pos = [bot.pos[0] + 1.5, bot.pos[1], ch.pos[2]]
    ch.safe_zone = bot.safe_zone = False
    bot.attack_target = ch
    bot.dest, bot.path = [bot.pos[0] + 5.0, bot.pos[1], bot.pos[2]], []
    brain.state = "fight"
    m.end(1, "test")
    hp = ch.health
    run(s, m, 9.0, 0.1)
    check("match over: the bot is frozen (no target, no path, state over)",
          bot.attack_target is None and bot.dest is None and brain.state == "over",
          (bot.attack_target, bot.dest, brain.state))
    bot.ready_at.clear()
    bot.__dict__.pop("last_cast_at", None)
    check("match over: a bot's cast is refused", not w.cast(bot, 1, ch, None))
    w.damage(bot, ch, 100.0)
    check("match over: no damage, the player loses no health in 9 s (tester's video: the bot 'killed' him)",
          ch.health == hp and ch.alive, (hp, ch.health))
    bot.attack_target = ch
    run(s, m, 0.5, 0.1)
    check("match over: an attack target set anyhow is dropped by World.tick", bot.attack_target is None)
    m.ic["bot_tower_tactics"] = True


def bot_tower_tactics_1812(cfg, data):
    """2026-10-30 tester report 18:12 ("now it doesn't go in to attack the tower"; docs/re-notes/bot-shop-towers-end.md
    4): with bot_tower_tactics the bot sieges the enemy turret its minions hold, leaves the moment the turret targets it,
    comes back when the turret is on a minion again, trades with the player only out of the turret's range or in a
    timed short trade (and steps out after the hit), and never dives alone."""
    print("bots: tower tactics - siege behind minions, out when targeted, back in, trades, no dive (2026-10-30 18:12)")
    s, w, m, bot = _sweep_bot_match(cfg, data, [])
    run(s, m, 13.0 + 47.0)                                # the first wave is out
    brain = m.bots.brains[0]
    brain.next_decision = float("inf")
    check("tactics: bot_tower_tactics is on by default", m.ic.get("bot_tower_tactics") is True and brain.tactics())
    ch = w.champion
    ch.pos = [ch.pos[0] + 200.0, ch.pos[1] + 200.0, ch.pos[2]]   # out of the way
    for mu in [x for x in m.units.by_eid.values() if x.role == "minion"]:
        mu.ent.pos = [mu.ent.pos[0] + 300.0, mu.ent.pos[1] + 300.0, mu.ent.pos[2]]   # the wave out of the way
    turret = next(mu for mu in m.structures if mu.team == ch.team and mu.role == "turret" and mu.ent.alive
                  and m.units.attackable(mu.ent))
    tx, ty = turret.ent.pos[0], turret.ent.pos[1]
    hx, hy = brain.home()[:2]
    d = math.hypot(hx - tx, hy - ty) or 1.0
    ux, uy = (hx - tx) / d, (hy - ty) / d                 # from the turret towards the bot's base

    def at(k, side=0.0):
        return [tx + ux * k - uy * side, ty + uy * k + ux * side, bot.pos[2]]

    def decide():
        s.clock += 0.01
        brain.decide(s.clock)

    bot.health = bot.max_health
    bot.pos = at(turret.range + 5.0)
    brain.state, brain.goal, brain.target = "push", None, None
    turret.target = None
    t0 = brain.pick_target()
    check("tactics: no minion of the bot at the turret: it does not go for the turret", t0 is not turret.ent,
          getattr(t0, "name", t0))
    tank = m.units.spawn(m.map["minions"]["melee"], at(3.0), bot.team, "minion", name="tank")
    turret.target = tank.ent
    decide()
    check("siege: one of its minions tanking the turret: the bot attacks the TURRET (from out of bot_sight 9 m too)",
          brain.state == "fight" and brain.target is turret.ent and bot.attack_target is turret.ent,
          (brain.state, getattr(brain.target, "name", None), bot.distance_to(turret.ent)))
    # in range, sieging: the gap while the turret has no target (a minion just died) does not send it out
    bot.pos = at(turret.range - 3.0)
    turret.target = None
    decide()
    check("siege: in the turret's range, the turret between two targets (tank still there): it stays on the turret",
          brain.state == "fight" and bot.attack_target is turret.ent,
          (brain.state, getattr(bot.attack_target, "name", None)))
    turret.target = tank.ent
    # the last tank about to die (less health than one turret shot): it leaves before the turret turns on it
    shot = float(turret.ent.stats.get(0x10000B76, 0.0) or 0.0)
    hp = tank.ent.health
    check("siege: the turret has an attack damage stat (the test's premise)", shot > 0, shot)
    tank.ent.health = max(1.0, shot * 0.5)
    decide()
    check("siege: the last tank has less health than a turret shot: it steps out first (bot_siege_tank_shots 1)",
          brain.state == "evade" and bot.attack_target is None, (brain.state, shot, tank.ent.health))
    tank.ent.health = hp
    # targeted: out at once
    bot.pos = at(turret.range - 3.0)
    brain.state, brain.goal = "fight", None
    turret.target = bot
    decide()
    goal = brain.goal
    check("retreat: the turret targets the bot: it drops the turret and walks out of its range",
          brain.state == "evade" and bot.attack_target is None and goal is not None
          and math.hypot(goal[0] - tx, goal[1] - ty) > turret.range + 1.0, (brain.state, goal))
    decide()
    check("retreat: ... and keeps walking out while still targeted", brain.state == "evade", brain.state)
    # out of range, the turret back on a minion: back in
    bot.pos = at(turret.range + 2.5)
    turret.target = tank.ent
    decide()
    check("retreat: the turret on its minion again: it goes back in and attacks the turret (no 2 s wait)",
          brain.state == "fight" and bot.attack_target is turret.ent,
          (brain.state, getattr(bot.attack_target, "name", None)))
    m.units.remove(tank)
    w.remove(tank.ent, "test minion gone")
    turret.target = None
    # never stands in the range alone
    bot.pos = at(turret.range - 2.0)
    brain.state, brain.goal, brain.target = "push", None, None
    decide()
    check("no dive: in the range with no minion of its: it steps out",
          brain.state == "evade" and bot.attack_target is None, brain.state)

    # the player champion near / under his turret
    brain.state, brain.goal, brain.target, brain.ignore, brain.chase_from = "push", None, None, {}, None
    bot.health = bot.max_health
    ch.health = ch.max_health * 0.5
    reach = brain.reach(ch)
    ch.pos = at(turret.range + 1.0)
    bot.pos = at(turret.range + 1.0 + reach * 0.5)
    c1 = brain.pick_target()
    check("trade: the player at the edge of his turret's range, the bot hitting from out of it: it takes him",
          c1 is ch, (getattr(c1, "name", c1), reach))
    ch.pos = at(1.5)
    bot.pos = at(1.5 + reach * 0.5)
    c2 = brain.pick_target()
    check("no dive: the player deep under his free turret at half health: not taken", c2 is not ch,
          getattr(c2, "name", c2))
    tank = m.units.spawn(m.map["minions"]["melee"], at(3.0, 1.0), bot.team, "minion", name="tank")
    turret.target = tank.ent
    c3 = brain.pick_target()
    check("no dive: ... nor with its minion tanking (the hit point deeper than bot_trade_depth)", c3 is not ch,
          getattr(c3, "name", c3))
    # a short trade at the edge while the minion tanks: only when the turret's next shot leaves time to get out
    ch.pos = at(turret.range - 0.5)
    bot.pos = at(turret.range - 0.5 + reach * 0.5)
    tank.ent.pos = at(turret.range - 2.0, 1.0)
    brain._now = s.clock
    turret.next_attack = s.clock + 0.05
    c4 = brain.pick_target()
    turret.next_attack = s.clock + 3.0
    c5 = brain.pick_target()
    check("trade: the player at the edge of the range, its minion tanking: not just before the turret's shot, yes "
          "right after it", c4 is not ch and c5 is ch, (getattr(c4, "name", c4), getattr(c5, "name", c5)))
    bot.health = bot.max_health * 0.4
    c6 = brain.pick_target()
    bot.health = bot.max_health
    check("trade: ... not below bot_trade_health", c6 is not ch, getattr(c6, "name", c6))
    # it lands the hit (the bot is the turret's champion aggressor now): it steps out
    turret.next_attack = s.clock + 3.0
    decide()
    hit_target = brain.target                             # (a skill cast leaves no attack target: bot_cast_clears_attack)
    m.aggressors[bot.eid] = (m.t, ch.team)
    decide()
    goal = brain.goal
    check("trade: it engages, and once it has hit him (champion aggressor) it steps out of the turret's range",
          hit_target is ch and brain.state == "evade" and bot.attack_target is None and goal is not None
          and math.hypot(goal[0] - tx, goal[1] - ty) > turret.range + 1.0,
          (getattr(hit_target, "name", hit_target), brain.state, goal))
    bot.pos = at(turret.range + 2.5)
    decide()
    check("trade: out of the range, it does not go back for the turret while it is still the aggressor (2 s)",
          bot.attack_target is not turret.ent, (brain.state, getattr(bot.attack_target, "name", None)))
    m.aggressors.pop(bot.eid, None)
    ch.pos = [ch.pos[0] + 200.0, ch.pos[1] + 200.0, ch.pos[2]]
    m.ic["bot_tower_tactics"] = False
    check("tactics off: the 15:30 rules (one tank is not enough: no structure taken)",
          brain.pick_target() is not turret.ent)
    m.ic["bot_tower_tactics"] = True
    m.units.remove(tank)
    w.remove(tank.ent, "test minion gone")

    # a whole lane: the bot with its waves against the player's turret (the player kept away) damages the turret and
    # is not killed under it
    s, w, m, bot = _sweep_bot_match(cfg, data, [])
    brain = m.bots.brains[0]
    ch = w.champion
    hits, deaths, logs = [], [], []
    dmg0 = w.damage

    def damage(src, victim, amount, *a, **k):
        mu = getattr(victim, "match_unit", None)
        if mu is not None and mu.role in ("turret", "inner_turret", "core_turret") and m._champion_of(src) is bot:
            hits.append((round(m.t, 1), mu.ent.name, amount))
        return dmg0(src, victim, amount, *a, **k)
    w.damage = damage
    far = [ch.pos[0], ch.pos[1], ch.pos[2]]
    for _ in range(int(300 / 0.5)):
        ch.pos = list(far)
        ch.dest, ch.path = None, []
        ch.health = ch.max_health
        was = bot.alive
        run(s, m, 0.5)
        if was and not bot.alive:
            deaths.append(round(m.t, 1))
    w.damage = dmg0
    print(f"    (lane: {len(hits)} hits on turrets, first {hits[:2]}, deaths {deaths})")
    check("lane: in 5 min with its waves against the player's turret (player kept in base) the bot hits the turret",
          len(hits) > 0, (len(hits), hits[:3]))
    check("lane: ... and is not killed", not deaths, deaths)


def core_door_regen_1530(cfg, data):
    """2026-10-30 tester report 15:30 (docs/re-notes/core-door-regen.md): the blue core turned 170 deg clockwise, the
    core never shoots (no warning ring), enemy minions reach and hit an exposed core from its rim, the always-lit decor
    doors, a damaged dampener's regen, the recall fx sent once after its tick (no same-run re-sends)."""
    from ics.match.units import heading_from_yaw
    print("core yaw / unarmed core / minions on the core / decor doors / dampener regen / recall fx "
          "(tester report 2026-10-30 15:30)")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 14.0)                                       # the match has begun
    core = {mu.team: mu for mu in m.structures if mu.role == "core"}
    turn = lambda a, b: abs(math.remainder(a - b, math.tau)) < 1e-6        # noqa: E731
    # 2026-10-30 tester report 19:46 (ca-strip-two-bit-candidates.md 3): the blue core ends as red's mirror, yaw 90 (-80
    # turned 190 deg clockwise); the red one keeps -90; the two are a half turn apart (prows at the lane)
    check("blue core yaw 90 (match_structure_yaw_add 0: -80 + 170 = -80 - 190); the red one keeps -90, a half turn apart",
          turn(core[1].ent.heading, heading_from_yaw(90.0)) and turn(core[2].ent.heading, heading_from_yaw(-90.0))
          and turn(core[1].ent.heading, core[2].ent.heading + math.pi)
          and turn(heading_from_yaw(-80.0 - 190.0), core[1].ent.heading),
          (core[1].ent.heading, core[2].ent.heading))
    props = {p[0]: p[2] for p in core[1].ent.extra_props}
    check("cores unarmed (match_unarmed_roles): no attack, 0x10000C5D / 0x10000C5B false in the bundle",
          all(core[t].attack is None and getattr(core[t], "unarmed", False) for t in (1, 2))
          and props.get(0x10000C5D) == 0 and props.get(0x10000C5B) == 0, props.get(0x10000C5D))

    # the blue base laid open, then one red melee minion at the core's rim (no blue units about)
    for role in ("turret", "dampener", "core_turret"):
        for mu in [x for x in m.structures if x.team == 1 and x.role == role]:
            kill(w, mu.ent)
    w.champion.pos = [5.0, 60.0, w.champion.pos[2]]
    run(s, m, 1.0)

    def clear_blue():
        for mu in [x for x in list(m.units.by_eid.values()) if x.team == 1 and x.role == "minion" and x.ent.alive]:
            kill(w, mu.ent)
    clear_blue()
    probe = m.units.spawn(m.map["minions"]["melee"], (17.5, 74.3), 2, "minion", name="test minion t2")
    n0 = len(s.sent)
    hp0 = core[1].ent.health
    for _ in range(12):
        clear_blue()
        run(s, m, 0.25)
    shots = [lbl for lbl in s.labels(n0) if lbl and lbl.startswith(core[1].ent.name + ":") and ("target" in lbl
                                                                                               or "0x100002e0" in lbl
                                                                                               or "0x1000029d" in lbl)]
    check("the exposed blue core is not protected and never targets / shoots the minion at its rim",
          not m.protected(core[1]) and core[1].target is None and not shots and probe.ent.alive, shots[:4])
    check("a red melee minion 3.2 m from the core's centre (0.2 m from its rim) takes it and hits it "
          "(match_structure_sight_to_edge)", probe.target is core[1].ent and core[1].ent.health < hp0,
          (getattr(probe.target, "name", None), hp0, core[1].ent.health, probe.ent.pos[:2]))
    was = w.ic.get("match_structure_sight_to_edge")
    w.ic["match_structure_sight_to_edge"] = False
    d = math.hypot(probe.ent.pos[0] - core[1].ent.pos[0], probe.ent.pos[1] - core[1].ent.pos[1])
    cands = m.units.enemies_near(probe, max(probe.vision, probe.range + 1.0), ("core",))
    check("... match_structure_sight_to_edge = false: the centre rule (out of its 3 m sight there)",
          (core[1].ent not in cands) == (d > max(probe.vision, probe.range + 1.0)), (d, probe.vision))
    w.ic["match_structure_sight_to_edge"] = was
    was_unarmed = cfg["ics"].get("match_unarmed_roles")
    cfg["ics"]["match_unarmed_roles"] = []
    s2, w2, m2 = make(cfg, data, 0x40000C82)
    cfg["ics"]["match_unarmed_roles"] = was_unarmed
    c2 = next(mu for mu in m2.structures if mu.role == "core" and mu.team == 1)
    check("match_unarmed_roles = []: the core keeps the data's attack 0x34000014 (as before)",
          c2.attack is not None and not getattr(c2, "unarmed", False))

    # decor doors: lit, team / side / scale, never opened
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + 3.0)
    doors = list(getattr(m, "decor_doors", ()))
    dprops = [{p[0]: p[2] for p in e.extra_props} for e in doors]
    lbls = s.labels()
    check("decor doors (match_decor_doors): two 0x2E000CD7 walls, team 1 side 3 / team 2 side 5, scale 0.4, "
          "Object_Closed played, still there after the start",
          len(doors) == 2 and all(e.eid in w.entities for e in doors)
          and [(p.get(0x1000009C), p.get(0x100007A2)) for p in dprops] == [(1, 3), (2, 5)]
          and all(abs(p.get(0x6B4, 0) - 0.4) < 1e-6 for p in dprops)
          and all(any(lbl and lbl.startswith(e.name + ":") and "Object_Closed" in lbl for lbl in lbls) for e in doors)
          and m.begun, [(e.name, e.pos[:2]) for e in doors])

    # dampener regen: the red lane turret down, the dampener hit once, then left alone
    tur2 = next(mu for mu in m.structures if mu.team == 2 and mu.role == "turret")
    damp2 = next(mu for mu in m.structures if mu.team == 2 and mu.role == "dampener")
    kill(w, tur2.ent)
    run(s, m, 0.5)
    w.damage(None, damp2.ent, 1000)
    hp_hit = damp2.ent.health
    run(s, m, 5.0)
    hp_5 = damp2.ent.health
    run(s, m, 10.0)
    hp_15 = damp2.ent.health
    rule = (cfg["ics"].get("match_structure_regen") or {}).get("dampener") or {}
    check("dampener regen (match_structure_regen): none within 'after' s of the hit, then per_second HP / s",
          hp_hit == 2000 and hp_5 == hp_hit and hp_15 > hp_hit
          and abs((hp_15 - hp_hit) - float(rule.get("per_second", 0)) * (15.0 - float(rule.get("after", 10)))) < 20.0,
          (hp_hit, hp_5, hp_15))
    w.ic["match_structure_regen"] = {}
    h = damp2.ent.health
    w.damage(None, damp2.ent, 100)
    run(s, m, 15.0)
    check("... match_structure_regen = {}: no regen", damp2.ent.health == h - 100, (h, damp2.ent.health))
    w.ic["match_structure_regen"] = cfg["ics"].get("match_structure_regen")

    # recall fx: sent once after its tick (start_scriptlet_hold_mode "defer"), never re-sent with its run number
    ch = w.champion
    ch.safe_zone = False
    n0 = len(s.sent)
    w.cast(ch, 6, None, None)
    run(s, m, 0.05)
    early = [x for x in s.labels(n0) if "0x10000223" in x]
    run(s, m, 2.0)
    fx = [x for x in s.labels(n0) if "0x10000223" in x]
    live = w.__dict__.get("looping_scriptlets") or {}
    check("recall fx (start_scriptlet_hold_mode defer): one 0x10000223 'held, once' after its tick, no 'again', "
          "not a looping key", not early and len(fx) == 1 and "held, once" in fx[0] and (ch.eid, 0x10000223) not in live,
          s.labels(n0)[:20])


def turret_death_head_rearm_1812(cfg, data):
    """2026-10-30 tester report 18:12 (docs/re-notes/turret-death-head-rearm.md): a lane turret at 0 HP plays its data
    death (_Defeat_OnDead: blast + graph Death, then Vfx_Stop) and its wreck stays; match_keep_body_roles without it =
    the old removal after corpse_seconds; after a fight the client-made head is re-armed (0x11F stop of every
    Vfx_AI_Active run, then a new run), once per min_gap."""
    print("lane turret death / head re-arm (tester report 2026-10-30 18:12)")
    for k in ("match_keep_body_roles", "match_structure_death_scriptlets", "match_turret_head_rearm"):
        cfg["ics"][k] = copy.deepcopy(config.DEFAULTS["ics"][k])
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 14.0)
    tur = {mu.team: mu for mu in m.structures if mu.role == "turret"}
    t2 = tur[2]
    check("the lane turret's head is its own client child (no server head, Vfx_AI_Active key)",
          m.units._own_head_key(t2) and getattr(t2, "head", None) is None)
    foe = m.units.spawn(m.map["minions"]["melee"], (t2.ent.pos[0] - 30.0, t2.ent.pos[1]), 1, "minion", name="probe t1")
    foe.ent.move_speed = 0.0
    m.units._turret_target(t2, foe.ent)
    t2.target = foe.ent
    n0 = len(s.sent)
    m.units._drop_target(t2)
    run(s, m, 1.0)
    early = [x for x in s.labels(n0) if "head re-arm" in x]
    run(s, m, 3.0)
    got = [x for x in s.labels(n0) if "head re-arm" in x]
    check("fight over: no re-arm before 'after' s, then 0x11F stop of Vfx_AI_Active and a new Vfx_AI_Active run",
          not early and len(got) == 2 and "0x11f" in got[0] and "Vfx_AI_Active (0x8d" in got[1], got)
    stop = next(d for lbl, d in s.sent[n0:] if "0x11f, head re-arm" in (lbl or ""))
    check("the stop names every run of the key (instance 0xFFFFFFFF)", struct.pack("<II", 0x10000D63, 0xFFFFFFFF) in stop)
    m.units._turret_target(t2, foe.ent)
    t2.target = foe.ent
    n1 = len(s.sent)
    m.units._drop_target(t2)
    run(s, m, 4.0)
    check("a second fight within min_gap: no second re-arm", not [x for x in s.labels(n1) if "head re-arm" in x])
    m.units._turret_target(t2, foe.ent)
    t2.target = foe.ent
    n2 = len(s.sent)
    m.units._drop_target(t2)
    m.units._turret_target(t2, foe.ent)
    t2.target = foe.ent
    run(s, m, 25.0)
    check("a new target before 'after' s: no re-arm", not [x for x in s.labels(n2) if "head re-arm" in x])
    m.units.remove(foe)

    n3 = len(s.sent)
    kill(w, t2.ent)
    run(s, m, 1.5)
    after = s.labels(n3)
    name = t2.ent.name + ":"
    check("lane turret down: _Defeat_OnDead then Vfx_Stop on the body (match_structure_death_scriptlets)",
          any(x.startswith(name) and "_Defeat_OnDead" in x for x in after)
          and any(x.startswith(name) and "Vfx_Stop" in x for x in after), after[-10:])
    run(s, m, 30.0)
    check("its wreck stays (match_keep_body_roles), dead", t2.ent.eid in w.entities and not t2.ent.alive)

    was = copy.deepcopy(cfg["ics"]["match_keep_body_roles"]), copy.deepcopy(cfg["ics"]["match_structure_death_scriptlets"])
    cfg["ics"]["match_keep_body_roles"] = ["core_turret"]
    cfg["ics"]["match_structure_death_scriptlets"] = {"core_turret": ["_Defeat_OnDead"]}
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 14.0)
    t1 = next(mu for mu in m.structures if mu.role == "turret" and mu.team == 1)
    n4 = len(s.sent)
    kill(w, t1.ent)
    run(s, m, 6.0)
    check("fase3-in settings: no death key, the body is removed after corpse_seconds",
          t1.ent.eid not in w.entities and not any("_Defeat_OnDead" in x for x in s.labels(n4)))
    cfg["ics"]["match_keep_body_roles"], cfg["ics"]["match_structure_death_scriptlets"] = was


def main():
    cfg = config.load()
    cfg["ics"]["trace_scripts"] = False
    cfg["ics"]["match_waves"]["stagger"] = 0.0           # a whole wave at once (the counts below)
    cfg["ics"]["match_pre_start"] = 13.0                   # no intro cinematic here: the short wait
    cfg["ics"]["liftable_gallery"] = False                 # a test aid the tester may have on in config.toml
    # the lift / toss / throw timelines below are measured from the lift / throw call; [ics] liftable_face_lead (fase3-ii,
    # agl-qer-lift.md 4) shifts them all by its lead and is checked on its own (liftable_face_lead_check)
    cfg["ics"]["liftable_face_lead"] = 0.0
    cfg["ics"]["showroom_prefetch"] = False                # the showroom test reads the list itself
    cfg["ics"]["match_stealth_overrides"] = {}             # the stealth checks test maps.py's layout (stealth-alignment.md)
    cfg["ics"]["stealth_margin"] = 0.5                     # ... and the hide area of the 2026-10-26 default
    data = Data(cfg.game_dir)

    print("navmesh fixes (maps-complete.md 2.4)")
    for mp, want in ((0xA0C11AF2, 1579), (0xA0C11AD2, 1574), (0xA0C122E2, 1690)):
        buf = data.packs.pack(mp).data
        blob = next(k for c, _r, k in navmesh.find_blobs(buf) if c == 0x10000003)
        n = len(navmesh.parse_blob(buf, blob))
        check(f"{mp:#x}: {want} champion-agent triangles", n == want, n)

    # ---- Gotham Divided: three lanes, the full core flow, a champion death, camps, the meteor storm schedule ----
    s, w, m = lane_and_core("Gotham Divided", cfg, data, 0x40000399)
    check("GD: beacons are won by kills (no captured beacon objects)",
          not any(c.role == "beacon" for c in m.objectives.points))
    check("meteor storm scheduled", any(e[1] == "meteor_storm" for e in m.objectives.events))
    s, w, m = make(cfg, data, 0x40000399)
    run(s, m, 13.0 + 61.0)
    check("GD: the 4 camps spawned at 60 s", all(len(c.members) == 3 for c in m.camps), [len(c.members) for c in m.camps])
    camp = m.camps[2]                                   # (0 / 1 / 3 are led by a buff destroyer)
    ch = w.champion
    ch.pos = [camp.spec["pos"][0] + 3.0, camp.spec["pos"][1], ch.pos[2]]
    w.damage(ch, camp.members[0].ent, 1.0)
    run(s, m, 1.0)
    check("a camp fights back when provoked", all(mu.target is ch for mu in camp.members if mu.ent.alive),
          [mu.target for mu in camp.members])
    ch.pos = list(maps.spawn_point(0x40000399, 1)[4:7])
    run(s, m, 15.0)
    home = all(math.hypot(mu.ent.pos[0] - mu.home[0], mu.ent.pos[1] - mu.home[1]) < 1.0 and mu.ent.health == mu.ent.max_health
               for mu in camp.members)
    check("leash: the camp walks home and heals when the champion leaves", home,
          [(mu.ent.pos[:2], mu.home[:2], mu.ent.health) for mu in camp.members])

    # champion death -> kill feed, scoreboard, respawn time by level
    s, w, m = make(cfg, data, 0x40000399)
    run(s, m, 14.0)
    ch = w.champion
    turret = next(mu for mu in m.structures if mu.team == 2 and mu.role == "turret")
    ch.pos = list(turret.ent.pos)
    run(s, m, 0.5)              # the base aura's tick sees the champion leave (it is invulnerable inside, fase3-hq)
    n = len(s.sent)
    w.damage(turret.ent, ch, ch.health + 1)
    p = m.score.by_agent(ch)
    check("champion death counted", p.deaths == 1)
    check("kill feed sent (0x217a)", any("0x217a" in lbl for lbl in s.labels(n)))
    check("respawn time from the level table", float(w.ic["respawn_seconds"]) == float(cfg["ics"]["match_respawn_seconds"][0]))
    start = maps.spawn_point(0x40000399, 1)
    check("respawn point = the team's start", w.spawn_pos[:2] == start[4:6], w.spawn_pos)
    s.clock += 20
    s.run_due()
    check("champion respawned", ch.alive and math.hypot(ch.pos[0] - start[4], ch.pos[1] - start[5]) < 0.01)

    # a minion killed by the champion pays the data's credits and XP
    run(s, m, 46.0)
    mu = next(x for x in m.waves.minions if x.team == 2 and x.ent.alive)
    ch.pos = [mu.ent.pos[0] + 1.0, mu.ent.pos[1], mu.ent.pos[2]]
    gold, xp = ch.gold, ch.xp
    w.damage(ch, mu.ent, mu.ent.health + 1)
    check("last hit: credits from the formula", ch.gold > gold, ch.gold - gold)
    check("last hit: XP from the formula", ch.xp > xp, ch.xp - xp)

    death_animation(cfg, data)              # the fall at death, the get-up at the respawn (death-animation.md)
    unit_death_slide_levelup(cfg, data)     # drone deaths, the dead slide, the level-up icon (fase3-ih)
    log_sweep(cfg, data)                    # the 2026-10-28 log sweep (test-2026-10-28-1439-sweep.md S2, S4-S10)
    object_updates(cfg, data)               # creation bundle, then deltas (object-update-bundles.md 13)
    rank_levels_1_to_19(cfg, data)          # 2026-10-30: the 19th skill point (skill-rank-levels.md)

    # ---- Coast City: two lanes, relays and the Doomsday Device ----
    s, w, m = lane_and_core("Coast City", cfg, data, 0x40000270)
    s, w, m = make(cfg, data, 0x40000270)
    run(s, m, 14.0)
    ch = w.champion
    for cap in m.objectives.points:
        ch.pos = list(cap.mu.ent.pos)
        run(s, m, 11.0)
    check("CC: the champion captured the 3 relays", m.objectives.owned(1, "relay") == 3, m.status())
    core = m.core(2)
    before = core.ent.health
    dev = m.objectives.device
    check("CC: the Doomsday Device starts locked", dev.state == "locked", dev.state)
    run(s, m, cfg["ics"]["match_device"]["unlock"] - m.t + 0.5)
    check("CC: the Device unlocks on schedule (line 234)", dev.state == "open"
          and any("0xea channel" in lbl for lbl in s.labels()), dev.state)
    ch.pos = list(dev.mu.ent.pos)
    run(s, m, cfg["ics"]["match_device"]["seconds"] + 0.5)
    check("CC: the champion captures the Device", dev.owner == 1 or dev.state == "held", (dev.owner, dev.state))
    ch.pos = list(maps.spawn_point(0x40000270, 1)[4:7])
    run(s, m, cfg["ics"]["match_device"]["fire_after"] + 2.0)
    check("CC: the captured Doomsday Device strikes the enemy core", core.ent.health < before, (before, core.ent.health))
    check("CC: then neutral and locked again", dev.owner == 0 and dev.state == "locked", (dev.owner, dev.state))

    # ---- Crime Alley v AI: one lane, surrender ----
    s, w, m = lane_and_core("Crime Alley v AI", cfg, data, 0x40000C82)
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 14.0)
    m.vote_surrender(None, True)
    check("surrender refused before 0x1000021C (600 s)", not m.over and m.surrender is None)
    m.t = 601.0
    m.on_notice(0x10000454, b"\x01")
    check("surrender vote passes (one human) -> team 2 wins", m.over and m.winner == 2, m.status())
    check("surrender notices sent (0x10000455 / 0x10000456)", any("0x10000455" in lbl for lbl in s.labels())
          and any("0x10000456" in lbl for lbl in s.labels()))

    # ---- Crime Alley Clash: team health ----
    s, w, m, spec, mode = common("Crime Alley Clash 1v1", cfg, data, 0x40000E68)
    check("Clash: team health from the UI record (200 / 200)", m.team_health == {1: 200.0, 2: 200.0}, m.team_health)
    check("team health bar sent (0x100004fb)", any("0x100004fb" in lbl for lbl in s.labels()))
    run(s, m, 14.0)
    m.hurt_team(2, 199.0)
    check("Clash: team 2 still alive at 1", not m.over)
    m.hurt_team(2, 5.0)
    check("Clash: team health 0 -> team 1 wins", m.over and m.winner == 1)

    # ---- Gotham Heights: domination ----
    s, w, m, spec, mode = common("Gotham Heights", cfg, data, 0x4000013E)
    check("GH: team health 500 / 500", m.team_health == {1: 500.0, 2: 500.0}, m.team_health)
    run(s, m, 13.0 + 46.0)
    check("GH: minion waves on the two rings", len(m.waves.minions) == 16, len(m.waves.minions))
    # fase3-ii (tester report 2026-10-29 14:40, gh-freeze-holes-picking.md F1): the kept Door ate every move click
    check("GH: the base doors go after the start (base_gate_keep_after_open false)",
          m.gates and not any(g.eid in w.entities for g in m.gates), [g.eid in w.entities for g in m.gates])
    # fase3-ij (tester report 2026-10-29 15:30, gh-ca-floor-spawn.md 1-2): a floor copy without the obstruction stays
    floors = [f for f in getattr(m, "gate_floors", []) if f.eid in w.entities]
    check("GH: each base door leaves a floor copy (same world state, 0x83C / 0x8C1 = 0)",
          len(floors) == 2 and all(f.world_state in (0x2E00084A, 0x2E000845) for f in floors)
          and all({(p[0], p[2]) for p in f.extra_props} >= {(0x83C, 0), (0x8C1, 0)} for f in floors),
          [(hex(f.world_state), f.extra_props) for f in floors])
    check("GH: the N capture point stands on its pad static (80, 127.93)",
          any(abs(c.mu.ent.pos[0] - 80.0) < 0.01 and abs(c.mu.ent.pos[1] - 127.93) < 0.01 for c in m.objectives.points),
          [tuple(c.mu.ent.pos[:2]) for c in m.objectives.points])
    ch = w.champion
    cap = m.objectives.points[0]
    ch.pos = list(cap.mu.ent.pos)
    run(s, m, 11.0)
    check("GH: point captured by presence", cap.owner == 1, (cap.owner, cap.control))
    foe = next((mu for mu in m.waves.minions if mu.team == 2 and mu.ent.alive), None)
    if foe is not None:
        foe.ent.pos = [cap.mu.ent.pos[0] + 4.0, cap.mu.ent.pos[1], foe.ent.pos[2]]
        foe.path = []
        hp = foe.ent.health
        run(s, m, 3.0)
        check("GH: an owned point shoots an enemy in 9 m (0x340000D5)", cap.mu.target is foe.ent or foe.ent.health < hp,
              (cap.mu.target, hp, foe.ent.health))
    check("GH: owner property 0x10000456 sent", any("0x10000456" in lbl for lbl in s.labels()))
    h = m.team_health[2]
    run(s, m, 10.0)
    check("GH: holding more points drains the enemy", m.team_health[2] < h, (h, m.team_health[2]))
    m.team_health[2] = 1.0
    run(s, m, 2.0)
    check("GH: enemy team health 0 -> team 1 wins", m.over and m.winner == 1, m.status())

    # ---- bot champions (bot-champions.md 3.7 step 9) ----
    print("bot champions (Crime Alley v AI)")
    s = FakeSession()
    spawn = pvp.spawn_point(0x40000C82, 1)
    w = World(data, cfg, 0x40000C82, spawn, send=s.send, schedule=s.schedule, log=lambda t: None)
    nav = pvp.navgrid(data, 0x40000C82, spawn[1:3])
    w.nav = nav.copy() if nav else None
    w.ground_z = spawn[6]
    w.create_champion(cfg["ics"]["champion"], spawn)
    w.in_world = True
    rows = [{"iid": 1, "name": "Player", "team": 1, "index": 0, "champion": cfg["ics"]["champion"], "bot": False},
            {"iid": 0x0200000000F00000, "name": "Bot 0", "team": 2, "index": 0, "champion": 0x40000262, "bot": True}]
    m = pvp.start_match(w, s, 0x40000C82, rows)
    bots = [p.agent for p in m.score.players if p.bot and p.agent is not None]
    check("a bot slot has a champion agent", len(bots) == 1 and bots[0].kind == "champion" and bots[0].eid in w.entities)
    bot = bots[0]
    props = {p[0]: p for p in w.properties(bot)}
    check("bot bundle: player IID 0x10000064 = the lobby slot", props.get(0x10000064, (0, 0, 0))[2] == 0x0200000000F00000)
    check("bot bundle: script tables 0x7D2 and no HUD-only ids", 0x7D2 in props and 0x100001AF not in props
          and 0x1000035E not in props)
    check("the bot has a brain on a lane", m.bots.brains and m.bots.brains[0].lane == "mid")
    run(s, m, 13.0 + 40.0)
    check("the bot left its base", math.hypot(bot.pos[0] - spawn[4], bot.pos[1] - spawn[5]) > 5.0
          or any(b.state != "base" for b in m.bots.brains), bot.pos)
    # call for help (2026-10-28): the bot's team turns on the champion that hits it, at once
    ch = w.champion
    helper = None
    for _ in range(8):
        helper = next((mu for mu in m.waves.minions if mu.team == bot.team and mu.ent.alive), None)
        if helper is not None:
            break
        run(s, m, 5.0)
    check("call for help: an allied minion of the bot exists", helper is not None)
    if helper is not None:
        ch.pos = [helper.ent.pos[0] + 3.0, helper.ent.pos[1], ch.pos[2]]
        bot.pos = [helper.ent.pos[0] + 2.0, helper.ent.pos[1] + 1.0, bot.pos[2]]
        ch.safe_zone = False
        m._on_hit(bot, ch)
        check("call for help: an allied minion of the hit champion re-thinks at once and targets the attacker",
              helper.next_think == 0.0 and (m.units.think(helper, 1e9) or helper.target is ch), helper.target)
    before = len(s.sent)
    w.damage(w.champion, bot, (bot.health or 0) + 1)
    p = m.score.by_agent(bot)
    hp = m.score.by_agent(w.champion)
    check("a bot kill counts (death for the bot, kill for the human)", p.deaths == 1 and hp.kills == 1,
          (p.deaths, hp.kills))
    run(s, m, 30.0)
    removed = any("(0x3)" in lbl and bot.name in lbl for lbl in s.labels(before))
    check("the bot respawns without being removed", bot.alive and bot.eid in w.entities and not removed)

    # K/D/A credit (timeline-kda-endscreen.md 2): a missile's hit counts for its champion; a turret's last blow goes to
    # the last enemy champion who hit the victim
    from types import SimpleNamespace
    missile = SimpleNamespace(eid=0x7F0001, missile=SimpleNamespace(owner=w.champion), team=1, kind="missile")
    m._on_hit(bot, missile)
    turret = next(mu for mu in m.structures if mu.team == 1 and mu.ent.alive)
    k0, a0 = hp.kills, hp.assists
    m._champion_died(bot, turret.ent)
    check("K/D/A: a turret kill after the champion's missile hit is the champion's kill", hp.kills == k0 + 1
          and p.deaths == 2, (hp.kills, p.deaths))
    k1 = hp.kills
    run(s, m, 30.0)
    m._champion_died(bot, turret.ent)
    check("K/D/A: no recent champion hit -> nobody's kill", hp.kills == k1 and p.deaths == 3, (hp.kills, p.deaths))

    # end page rows (timeline-kda-endscreen.md 3): own account IID per row, 6 upgrade slots, the champion DID
    rows = m.end_rows()
    accounts = [r[2]["account"] for r in rows]
    check("0x2045 rows: one distinct non-zero account IID per row", len(set(accounts)) == len(rows) and all(accounts),
          [hex(a) for a in accounts])
    check("0x2045 rows: 6 upgrade slots and the champion DID", all(len(r[2]["upgrades"]) == 6 and r[2]["champion"]
                                                                  for r in rows))
    import ics.messages as MM
    entry = MM._end_stats_entry(*rows[0])
    champ_did, level = struct.unpack_from("<II", entry, 24)
    ups = struct.pack("<I", 6) + b"".join(struct.pack("<II", d, s_) for d, s_ in rows[0][2]["upgrades"])
    check("0x2045 entry: +0x1C champion DID, +0x20 level, the +0x2FC list carries the slots",
          champ_did == rows[0][2]["champion"] and level >= 1 and ups in entry, (hex(champ_did), level))

    # timeline (timeline-kda-endscreen.md 1): event times = now + (at - match time); re-placed when the intro moves
    # the start
    print("timeline (Crime Alley v AI)")
    s, w, m = make(cfg, data, 0x40000C82)
    m.on_notice(0x100002AD)
    n_ev = [d for lbl, d in s.sent if "(0x100002ab)" in lbl]

    def ev_time(d, handle):
        at = d.find(struct.pack("<IQ", handle, MM.LOCAL_PLAYER_ID))
        return struct.unpack_from("<d", d, at + 29)[0] if at >= 0 else None
    tl_names = sorted(cfg["ics"]["match_timeline"])
    h_start = 900 + tl_names.index("start")
    start_ev = next((d for d in n_ev if ev_time(d, h_start) is not None), None)
    check("timeline: the start mark at now + (0 - match time)", start_ev is not None
          and abs(ev_time(start_ev, h_start) - (time.time() - m.t)) < 1.0,
          start_ev and (ev_time(start_ev, h_start) - time.time(), m.t))
    now_sent = struct.unpack_from("<d", start_ev, len(start_ev) - 8)[0] if start_ev else 0
    check("timeline: 'now' is the wall clock", abs(now_sent - time.time()) < 1.0, now_sent - time.time())
    n = len(s.sent)
    m.intro_done()
    removed = [lbl for lbl in s.labels(n) if "(0x100002ac)" in lbl]
    again = [d for lbl, d in s.sent[n:] if "(0x100002ab)" in lbl and ev_time(d, h_start) is not None]
    check("timeline: the intro's end removes the marks and places them again on the new start",
          len(removed) >= 2 and again and abs(ev_time(again[0], h_start) - (time.time() + 42.0)) < 1.0,
          (removed, again and ev_time(again[0], h_start) - time.time()))
    jungle = [t for t, _n, fn in m._timers if (getattr(fn, "__defaults__", None) or (None,))[0] == 671]
    check("timeline: 'jungle online' plays at the camps' first time (45 s on Crime Alley)",
          jungle and abs(jungle[0] - m._camps_first()) < 0.01 and m._camps_first() == 45.0, jungle)

    # 2026-10-30 (tester report 13:18; timeline-tooltip-camp-prespawn.md 1): the hover tooltip's picture
    # (didExaminationIcon, descriptor [6]) = the unit's Character_Billboard_Icon 0x100001FC from the data
    def ev_icons(handle):
        for d in n_ev:
            at = d.find(struct.pack("<IQ", handle, MM.LOCAL_PLAYER_ID))
            if at >= 0:
                return struct.unpack_from("<III", d, at + 12)
        return None
    pics = {nm: ev_icons(900 + k) for k, nm in enumerate(tl_names)}
    check("timeline: tooltip pictures from the data (drones 0x13000F9D, jungle / Raider 0x13001A37), strip icons 0, "
          "the start mark none", pics.get("drones") == (2, 0, 0x13000F9D) and pics.get("jungle") == (3, 0, 0x13001A37)
          and pics.get("raider") == (2, 0, 0x13001A37) and pics.get("start") == (1, 0, 0),
          {k: v and [hex(x) for x in v] for k, v in pics.items()})
    raider_ev = next((d for d in n_ev if ev_time(d, 900 + tl_names.index("raider")) is not None), None)
    check("timeline: the Raider's mark at its match_raider time (300 s)", raider_ev is not None
          and abs(ev_time(raider_ev, 900 + tl_names.index("raider")) - ev_time(start_ev, h_start) - 300.0) < 0.01)
    check("timeline: the tooltip title goes as the entry's StringInfo", start_ev is not None
          and ("Match start".encode() in start_ev or "Match start".encode("utf-16-le") in start_ev))
    saved = cfg["ics"]["match_timeline_icons"]
    cfg["ics"]["match_timeline_icons"] = False
    try:
        s5, w5, m5 = make(cfg, data, 0x40000C82)
        m5.on_notice(0x100002AD)
    finally:
        cfg["ics"]["match_timeline_icons"] = saved
    check("timeline: match_timeline_icons false = no pictures (fase3-ir)",
          not any(" icon 0x" in lbl for lbl in s5.labels() if "(0x100002ab)" in lbl)
          and any("(0x100002ab)" in lbl for lbl in s5.labels()))

    # ---- liftable props and the turret warning ring (crime-alley-props.md) ----
    print("liftables")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + cfg["ics"]["match_waves"]["first"] + 3.0)
    lifts = list(m.liftables.props)
    # 2026-10-29 (power-core-turret.md 6): plus the enabled vehicles of [ics] liftable_props_added_by_map
    n_cars = 2 + sum(1 for sp in (cfg["ics"].get("liftable_props_added_by_map") or {}).get("crime_alley") or ()
                     if sp.get("enabled", True))
    check(f"CA: 5 meteorites and {n_cars} vehicles spawned", sorted(e.liftable for e in lifts).count("rock") == 5
          and sum(e.liftable == "vehicle" for e in lifts) == n_cars, [e.name for e in lifts])
    car = next(e for e in lifts if e.liftable == "vehicle")
    check("vehicles: the intact rebuild 0x8B is sent (destructible-vehicles.md)",
          any("rebuild intact (0x8b)" in lbl and car.name in lbl for lbl in s.labels()))
    flags = [p for p in car.extra_props if p[0] == 0x1000019D]
    check("a vehicle carries Super Strength's target flags 0x1080", flags and flags[-1][2] == 0x1080, flags)
    turret = next(mu for mu in m.structures if mu.role == "turret")
    tp = {p[0]: p[2] for p in turret.ent.extra_props}
    check("structures register for the warning ring (0x10000C5D / 0x10000C5B)", tp.get(0x10000C5D) == 1
          and tp.get(0x10000C5B) == 1, tp.get(0x10000C5D))
    ch = w.champion
    ch.pos = [car.pos[0] - 2.0, car.pos[1], car.pos[2]]
    drone = next((mu.ent for mu in m.units.by_eid.values() if mu.ent.alive and mu.role == "minion"
                  and mu.team != ch.team), None)
    check("an enemy drone to throw at", drone is not None)
    ch.stolen[7] = data.stolen_power(0x480003CB)[0]           # Super Strength in slot 7, as the tester had it

    class _Inst:                                              # the 0x34000164 instance the lift came from
        slot, removed = 7, False

        def post(self, *a):
            pass
    # parked vehicles block paths (vehicles-carry-collision.md 2, tester 2026-10-28 13:52)
    nav = w.nav
    cx, cy = car.pos[0], car.pos[1]
    check("a parked vehicle's footprint is not walkable (liftable_blockers)", nav is not None
          and not nav.walkable(cx, cy) and nav.walkable(cx + math.cos(car.heading) * 6.0, cy + math.sin(car.heading) * 6.0))
    ux, uy = math.cos(car.heading), math.sin(car.heading)            # along the vehicle (it stands against a wall)
    way, line = None, None
    for side in (1.0, -1.0):
        a_pt = (cx - ux * 3.5 - uy * side * 0.5, cy - uy * 3.5 + ux * side * 0.5)
        b_pt = (cx + ux * 3.5 - uy * side * 0.5, cy + uy * 3.5 + ux * side * 0.5)
        if nav is not None and nav.walkable(*a_pt) and nav.walkable(*b_pt):
            line, way = nav.line_clear(a_pt, b_pt), nav.path(a_pt, b_pt)
            break
    check("a path along a parked vehicle goes round it, not through it", way is not None and line is False
          and len(way) > 1 and all(nav.walkable(x, y) for x, y in way), (line, way))
    # the SUV against the raised wall north of it (vehicle-lift-and-position.md 1, tester 2026-10-28 15:00): same yaw, its
    # long side 0.15-0.35 m from the wall = agent 0x10000003's boundary edge + its radius (.entity box 0x2D00061C: half
    # width 1.0, centred 0.177 m forward = liftable_blockers' 4th element)
    box = cfg["ics"]["liftable_blockers"]["0x2E000795"]
    radius = next(r for c, r, _k in navmesh.find_blobs(data.packs.pack(maps.map_for(0x40000C82)[0]["map_pack"]).data)
                  if c == 0x10000003)
    uses = {}
    for tri in (nav.tris if nav is not None else ()):
        for i in range(3):
            k = tuple(sorted((tuple(round(v, 3) for v in tri[i][:2]), tuple(round(v, 3) for v in tri[(i + 1) % 3][:2]))))
            uses[k] = uses.get(k, 0) + 1
    rim = [k for k, n in uses.items() if n == 1]

    def to_rim(px, py, dx, dy):
        hits = []
        for (ax, ay), (bx_, by_) in rim:
            ex, ey = bx_ - ax, by_ - ay
            den = dx * ey - dy * ex
            if abs(den) > 1e-12:
                t, u = ((ax - px) * ey - (ay - py) * ex) / den, ((ax - px) * dy - (ay - py) * dx) / den
                if 0.0 <= u <= 1.0 and t > 1e-6:
                    hits.append(t)
        return min(hits, default=99.0)
    bx, by = cx + ux * box[3], cy + uy * box[3]                      # the box centre
    gaps = [to_rim(bx + ux * a, by + uy * a, -uy, ux) + radius - box[1] for a in (-2.5, 0.0, 2.5)]
    check("SUV: same yaw (245), its long side 0.15-0.35 m from the wall north of it (navmesh edge + agent radius)",
          car.lift_spec.get("world_state") == "0x2E000795" and car.lift_spec.get("yaw") == 245.0
          and all(0.15 <= g <= 0.35 for g in gaps), [round(g, 3) for g in gaps])
    check("SUV: its blocker is the .entity box (blocked 1.1 m south of the box centre, walkable at 1.75 m)",
          nav is not None and not nav.walkable(bx + uy * 1.1, by - ux * 1.1) and nav.walkable(bx + uy * 1.75, by - ux * 1.75))
    before_lift = len(s.sent)
    parked, t_lift, feed = list(car.pos), m.t, []
    # what the champion's graph gets (replayed below in a copy of it: graph_runtime is off in this test)
    w.graph_feed = lambda ent, key, variables=None: feed.append((m.t - t_lift, key, variables)) if ent is ch else None
    m.liftables.lift(ch, car, _Inst())
    check("lifted: the vehicle's footprint is walkable again", nav is None or nav.walkable(cx, cy))
    w.refresh_champion("credits during the carry")         # held until the carry ends (liftable_hold_champion_bundles)
    marks, track = [(0.0, lbl or "") for lbl in s.labels(before_lift)], []
    # the toss timeline below, in 0.05 s steps up to 0.1 s past ready (fase3-im: liftable_car_pickup_at "graph" = ready at
    # 1.21 s; 0.05 = 0.81 s)
    for _ in range(int(math.ceil((m.liftables._toss_timeline(ch)[3] + 0.1) / 0.05))):
        n0 = len(s.sent)
        run(s, m, 0.05, step=0.05)
        marks += [(m.t - t_lift, lbl or "") for lbl in s.labels(n0)]
        track.append((m.t - t_lift, list(car.pos), ch.carry_ready))
    del w.graph_feed
    check("lift: the champion carries the vehicle over the head", ch.carrying is car and car.pos[2] > ch.pos[2] + 1.5,
          (getattr(ch, "carrying", None), car.pos))
    lift_labels = s.labels(before_lift)
    champ_bundles = [lbl for lbl in lift_labels if lbl and lbl.startswith(ch.name) and "(0x" not in lbl
                     and "graph event" not in lbl]
    check("lift: one champion bundle (the facing, with the throw skill), none mid-clip "
          "(liftables-camps-animations.md 2)", len(champ_bundles) == 1 and "throw skill" in champ_bundles[0]
          and not any("throw skill" in lbl and "while carrying" in lbl for lbl in lift_labels)
          and not any("credits during the carry" in (lbl or "") for lbl in lift_labels), champ_bundles)
    check("lift: the vehicle is not attached (liftable_attach_kinds) and rides 2.5 m over the champion "
          "(0x34000161's AttachmentOffset; vehicles-carry-collision.md 1)",
          getattr(car, "attach_parent", None) is None and not any("attached to" in (lbl or "") for lbl in lift_labels)
          and abs(car.pos[2] - ch.pos[2] - 2.5) < 0.01, car.pos)
    # 2026-10-30 (vehicle-lift-old-vs-ics.md 3.1): an unattached vehicle's pieces are not rebuilt at the catch
    # (liftable_attach_rebuild_attached_only; the switch back is checked in lift_throw_wreck_1205)
    check("lift: no 0x8B piece rebuild over the head for a vehicle carried by its own states "
          "(liftable_attach_rebuild_attached_only)",
          any("carried over the head" in (lbl or "") for lbl in lift_labels)
          and not any("rebuild pieces, over the head (0x8b)" in (lbl or "") for lbl in lift_labels))
    # the lift = 0x34000161's order (vehicle-lift-and-position.md 2; tester 2026-10-28 15:00: "starts lifting, then cuts
    # to already holding it"): CarPickup, the toss in states < 2 m, the catch's PickupObject in Hold, ready after it
    gt = m.liftables._graph_times
    near = lambda a, b: all(abs(a[k] - v) < 1e-3 for k, v in b.items())                  # noqa: E731
    stub = lambda did: type("Champion", (), {"class_id": did})()                          # noqa: E731
    check("lift timeline from the champion's own graph, its SM_SuperStrength_Car found by structure (Gaslight "
          "Batman / AGL 0.45 / +0.0125 / +0.375 s; Joker's renamed states +0.01 / +0.3; Batman 0.4103 / +0.1597)",
          near(gt(ch), {"car_pickup": 0.45, "hook": 0.0125, "hold": 0.375})
          and near(gt(stub(0x40000213)), {"car_pickup": 0.45, "hook": 0.01, "hold": 0.3})
          and near(gt(stub(0x40000280)), {"car_pickup": 0.4103, "hook": 0.1597, "hold": 0.3897}),
          (gt(ch), gt(stub(0x40000213)), gt(stub(0x40000280))))
    # the census' six "no machine" graphs name it SM_SuperStrength_Car_Throw (Wonder Woman 0x40000260, Doomsday
    # 0x4000015A: AGL's timings); a class with no graph gets CAR_TIMES (vehicle-lift-and-position.md 8)
    check("lift timeline: Wonder Woman's / Doomsday's SM_SuperStrength_Car_Throw found by structure; no graph = the "
          "fallback timings", near(gt(stub(0x40000260)), {"car_pickup": 0.45, "hook": 0.0125, "hold": 0.375})
          and near(gt(stub(0x4000015A)), {"car_pickup": 0.45, "hook": 0.0125, "hold": 0.375})
          and gt(stub(0)) == {"car_pickup": 0.45, "hook": 0.0125, "hold": 0.375},
          (gt(stub(0x40000260)), gt(stub(0x4000015A)), gt(stub(0))))
    was = w.ic.get("liftable_car_pickup_at", 0.05)
    w.ic["liftable_car_pickup_at"] = "graph"                 # the switch: CarPickup at Car_Pickup's start frame
    g_car, g_toss, g_catch, g_ready = m.liftables._toss_timeline(ch)
    w.ic["liftable_car_pickup_at"] = was
    check("liftable_car_pickup_at = \"graph\": CarPickup at Car_Pickup's start frame (0.45 s, the whole bend), toss "
          "at its grab hook, catch liftable_toss_seconds later, ready liftable_attach_seconds after it",
          abs(g_car - 0.45) < 1e-6 and abs(g_toss - 0.4625) < 1e-6
          and abs(g_catch - max(g_toss + float(w.ic.get("liftable_toss_seconds", 0.65)), 0.45 + 0.375 + 0.05)) < 1e-6
          and abs(g_ready - g_catch - float(w.ic.get("liftable_attach_seconds", 0.1))) < 1e-6,
          (g_car, g_toss, g_catch, g_ready))
    car_at, toss_at, catch_at, ready_at = m.liftables._toss_timeline(ch)
    at = lambda text: next((t for t, lbl in marks if text in lbl), None)                  # noqa: E731
    t_car, t_pick = at(f"{ch.name}: graph event CarPickup"), at("SuperStrength_PickupObject")
    want = cfg["ics"].get("liftable_car_pickup_at")
    want = gt(ch)["car_pickup"] if want is None or isinstance(want, str) or float(want) < 0 else float(want)
    check("lift: graph event CarPickup once, at liftable_car_pickup_at (fase3-im default \"graph\": Car_Pickup's start "
          "frame, the whole bend; 0.05 = the original's Vfx_Event9)",
          t_car is not None and car_at - 1e-6 <= t_car <= car_at + 0.05 + 1e-6 and abs(car_at - want) < 1e-9
          and sum(f"{ch.name}: graph event CarPickup" in lbl for _t, lbl in marks) == 1, (t_car, car_at, want))
    path = [parked] + [p for t, p, _r in track if t <= catch_at + 0.05 + 1e-6]
    hops = [math.dist(a, b) for a, b in zip(path, path[1:])]
    near_ch = [math.hypot(p[0] - ch.pos[0], p[1] - ch.pos[1]) for p in path]
    tossed = [lbl for _t, lbl in marks if lbl.startswith(f"{car.name} tossed onto ")]
    check("toss: no PickupObject / over-the-head state before the catch; the vehicle flies from its spot onto the "
          "champion in states < 2 m apart (fase3-ie: one 3.4-4.2 m state, which the client places at once), above "
          "the hold height on the way", t_pick is not None and t_pick >= catch_at - 1e-6
          and (at(f"{car.name} carried over the head") or 0.0) >= catch_at - 1e-6
          and (len(tossed) == int(cfg["ics"]["liftable_toss_steps"]) - 1 if not w.ic.get("liftable_toss_timed", True)
               else len(tossed) >= 3) and max(hops) < 2.0
          and all(b <= a + 1e-6 for a, b in zip(near_ch, near_ch[1:])) and near_ch[-1] < 0.01
          and (max(p[2] for p in path) > ch.pos[2] + 2.5 + 0.2 or float(cfg["ics"]["liftable_toss_arc"]) < 0.5),
          (t_pick, round(max(hops), 2), len(tossed), [round(d, 2) for d in near_ch]))
    order = [next((i for i, (_t, lbl) in enumerate(marks) if text in lbl), -1) for text in
             (f"{ch.name}: graph event CbtState_DisableHit", f"{car.name} carried over the head",
              f"{ch.name}: SuperStrength_PickupObject", f"{car.name}: SuperStrength_PickupObject")]
    t_ready = next((t for t, _p, r in track if r), None)
    check("catch (0x34000161 S9): DisableHit, the vehicle on the hold point, PickupObject on the champion and the "
          "vehicle at the catch time; ready to throw liftable_attach_seconds later",
          -1 not in order and order == sorted(order) and catch_at - 1e-6 <= t_pick <= catch_at + 0.05 + 1e-6
          and t_ready is not None and ready_at - 1e-6 <= t_ready <= ready_at + 0.05 + 1e-6,
          (order, t_pick, catch_at, t_ready, ready_at))
    from ics import graph as GR
    queue, seq, clock, seen = [], itertools.count(), [0.0], set()
    gi = GR.GraphInstance(GR.data().for_variant(ch.class_id),
                          lambda d, fn: heapq.heappush(queue, (clock[0] + d, next(seq), fn)), lambda: clock[0],
                          lambda *a: None)

    def replay(until):
        while queue and queue[0][0] <= until + 1e-9:
            clock[0], _n, fn = heapq.heappop(queue)
            fn()
            seen.update(gi.state_names())
        clock[0] = until
    for t, key, variables in feed:
        replay(t)
        gi.scriptlet(key, variables)
        seen.update(gi.state_names())
    replay(1.5)
    check("graph: the catch's PickupCar reaches SuperStrength_Car_Hold and plays Car_Catch (fase3-ie sent it in "
          "Car_Pickup, which drops it)", "SuperStrength_Car_Catch" in seen
          and any(n == "SuperStrength_PickupCar" and ok for _t, n, ok in gi.events),
          [(round(t, 3), n, ok) for t, n, ok in gi.events])
    ch.pos[0] += 2.0
    run(s, m, 0.5)
    check("carry: the vehicle follows the champion", abs(car.pos[0] - ch.pos[0]) < 0.01)
    w.walk_to(ch, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    walk_from = len(s.sent)
    run(s, m, 0.5)
    check("carry while walking: the vehicle has no destination of its own (liftable_no_dest), keeps over him and "
          "gets his speed", car.dest is None and abs(car.pos[0] - ch.pos[0]) < 0.01
          and abs(car.pos[2] - ch.pos[2] - 2.5) < 0.01 and (ch.speed == 0 or abs(car.speed - ch.speed) < 0.01),
          (car.dest, car.pos, ch.pos, car.speed, ch.speed))
    car_bundles = [d for _lbl, d in s.sent[walk_from:] if d[5:13] == struct.pack("<Q", car.eid) and d[14:15] == b""]
    check("carry while walking: not a vehicle bundle every tick (liftable_carry_resend)", len(car_bundles) <= 3,
          len(car_bundles))
    run(s, m, 1.0)
    target = [ch.pos[0] + 6.0, ch.pos[1], ch.pos[2]]
    if drone is not None:
        drone.pos = list(target)
        hp0 = drone.health
    before_throw = len(s.sent)
    m.liftables.throw(ch, target)
    run(s, m, 0.5)
    mid_throw = s.labels(before_throw)
    # fase3-im (liftable-throw-destruction.md 2 / 3): a vehicle carried by its own states (not attached) is not rebuilt
    # in mid-air at the launch, and the throw's turn is a movement state, not a full champion bundle
    check("throw: no mid-air 0x8B for a vehicle that was never attached (liftable_detach_rebuild_attached_only), no "
          "Super Strength bundle mid-clip", not any("rebuild pieces, detached (0x8b)" in (lbl or "") for lbl in mid_throw)
          and not any("Super Strength again" in (lbl or "") for lbl in mid_throw), mid_throw)
    throws = [(lbl, d) for lbl, d in s.sent[before_throw:] if (lbl or "").startswith(f"{ch.name} throws {car.name}")]
    check("throw: one turn toward the point; the movement state alone in delta mode (liftable_throw_face_motion_only, "
          "fase3-im) and in bundle mode (liftable_throw_face_motion_bundle, 2026-10-30)", len(throws) == 1
          and (("movement state only" in throws[0][0] and len(throws[0][1]) < 120)
               if w.delta_mode() or w.ic.get("liftable_throw_face_motion_bundle", True)
               else "movement state only" not in throws[0][0]), [(lbl, len(d)) for lbl, d in throws])
    mode, kept = w.ic.get("object_update_mode"), (ch.client_props, ch.client_motion, ch.client_created_at)
    w.ic["object_update_mode"] = "delta"
    w.remember_full(ch, w.properties(ch))
    ch.client_created_at = time.time() - 60.0
    n_face = len(s.sent)
    m.liftables._face(ch, "test turn")
    faced = s.sent[n_face:]
    w.ic["object_update_mode"] = mode
    ch.client_props, ch.client_motion, ch.client_created_at = kept
    check("liftable_throw_face_motion_only in delta mode: the turn is one movement state (no 0xBC table)",
          len(faced) == 1 and "movement state only" in faced[0][0] and len(faced[0][1]) < 120,
          [(lbl, len(d)) for lbl, d in faced])
    check("throw: the carry's throw indicator went on (0x20F9 0) and goes off at the press (0x20F9 1) (fase3-ih)",
          any("throw indicator on (0x20f9 0)" in (lbl or "") for lbl in s.labels(before_lift))
          and any("throw indicator off (0x20f9 1)" in (lbl or "") for lbl in mid_throw),
          [lbl for lbl in s.labels(before_lift) if "indicator" in (lbl or "")])
    run(s, m, 0.3)
    if drone is not None:
        drone.pos, drone.dest, drone.path = list(target), None, []   # fase3-ih: the lob lasts 0.8 s, the drone walks
    check("throw: still in the air 0.5 s after the press (liftable_throw_min_seconds, fase3-ih)",
          not any(f"{car.name}: destruction impulse" in (lbl or "") for lbl in s.labels(before_throw)))
    run(s, m, 0.7)
    # 2026-10-29 tester report 21:10 (liftable-aura-lift-throw-break.md 4): the landing no longer sends Vfx_OnExplode
    check("throw: the vehicle lands at the point and blows up (impulse, break keys; no Vfx_OnExplode)",
          car.pos[0] > ch.pos[0] + 5.0
          and any("destruction impulse" in lbl and car.name in lbl for lbl in s.labels(before_throw))
          and not any("Vfx_OnExplode" in lbl and car.name in lbl for lbl in s.labels(before_throw)), car.pos)
    run(s, m, 0.3)                  # fase3-im: the impulse 0.05 s after the landing rebuild, DestroyEntity's action 0.15 s
    # fase3-ij (throw-padlock-coredeath.md 1): the carry indicator by 0x2180 / 0x217F, the original's landing impulse
    # (0x8A to the vehicle, twice) and snapped flight states (a newer teleport sequence)
    check("throw: the carry indicator starts by 0x2180 and ends by 0x217F at the press (fase3-ij)",
          any("throw indicator on (0x2180)" in (lbl or "") for lbl in s.labels(before_lift))
          and any("throw indicator off (0x217f)" in (lbl or "") for lbl in mid_throw))
    check("throw: the landing sends the destruction impulse to the vehicle and Destructible_IgnoreAOI (fase3-ij)",
          any(f"{car.name}: destruction impulse (0x8a)" in (lbl or "") for lbl in s.labels(before_throw))
          and any(f"{car.name}: Destructible_IgnoreAOI" in (lbl or "") for lbl in s.labels(before_throw)),
          [lbl for lbl in s.labels(before_throw) if car.name in (lbl or "")])
    landing = s.labels(before_throw)
    i_reb = next((i for i, lbl in enumerate(landing) if f"{car.name}: rebuild pieces at the landing (0x8b)" in lbl), None)
    i_imp = next((i for i, lbl in enumerate(landing) if f"{car.name}: destruction impulse (0x8a)" in lbl), None)
    check("throw: the pieces are rebuilt on the landing frame before the impulse (liftable_land_rebuild, fase3-im)",
          i_reb is not None and i_imp is not None and i_reb < i_imp, (i_reb, i_imp))
    check("throw: DestroyEntity's _HFSM_DestroyEntityAction_Optional plays on the landed vehicle (0x3400015F S4, "
          "liftable_land_destroy_after, fase3-im); _HFSM_DestroyEntityAction is not in its tables",
          any(f"{car.name}: _HFSM_DestroyEntityAction_Optional (0x8d, DestroyEntity)" in lbl for lbl in landing)
          and not any(f"{car.name}: _HFSM_DestroyEntityAction (0x8d" in lbl for lbl in landing),
          [lbl for lbl in landing if "Destroy" in lbl])
    check("throw: each flight state has a newer teleport sequence (liftable_throw_snap, fase3-ij)",
          getattr(car, "tele_seq", 1) > 5, getattr(car, "tele_seq", 1))
    check("after the throw clip: Super Strength's slot table goes back in one bundle (liftable_slot_restore_delay)",
          any("Super Strength again" in (lbl or "") for lbl in s.labels(before_throw))
          and not getattr(ch, "bundle_hold", False))
    if drone is not None:
        check("the blast hurts a hostile in range", drone.health < hp0 or not drone.alive, (hp0, drone.health))
    check("the champion is free again after the throw", getattr(ch, "carrying", None) is None)
    rock = next(e for e in m.liftables.props if e.liftable == "rock")
    ch.pos = [rock.pos[0] - 2.0, rock.pos[1], ch.pos[2]]
    run(s, m, 1.0)
    before_rock = len(s.sent)
    m.liftables.lift(ch, rock, _Inst())
    run(s, m, 1.0)
    rock_labels = s.labels(before_rock)
    check("rock: no full champion bundle after the pickup key (the clip runs undisturbed)",
          not any(lbl and lbl.startswith(ch.name) and "(0x" not in lbl and "graph event" not in lbl
                  for lbl in rock_labels[next(i for i, lbl in enumerate(rock_labels) if "pick up" in (lbl or "")):])
          and not any("while carrying" in (lbl or "") and "throw skill" in (lbl or "") for lbl in rock_labels),
          rock_labels)
    check("rock: no 0x8B rebuild for a meteorite (no destruction record)",
          not any("rebuild pieces" in (lbl or "") and rock.name in lbl for lbl in rock_labels))
    m.liftables.throw(ch, [ch.pos[0] + 3.0, ch.pos[1], ch.pos[2]])
    run(s, m, 2.0)
    check("a meteorite flies straight to its range (8.5 m) and fades", rock.pos[0] > ch.pos[0] + 8.0
          and rock not in m.liftables.props, rock.pos)
    # Consume 0x340001C4: IsKind [0x82] on a rock / vehicle, then DestroyEntity (2026-10-28 09:36 tester report)
    from ics.world import CastWorld
    eaten = next(e for e in m.liftables.props if e.liftable == "rock")
    cw = CastWorld(w, ch, None)
    check("IsKind 0x82 holds for a meteorite and a vehicle, not for a minion",
          cw.kind_matches(eaten, 0x82) and cw.kind_matches(car, 0x82)
          and (drone is None or not cw.kind_matches(drone, 0x82)))
    cw.destroy(eaten, 0.3)
    run(s, m, 1.5)
    check("Consume: the meteorite is gone and can no longer be lifted", eaten not in m.liftables.props
          and eaten.eid not in w.entities)
    run(s, m, 11.0 + cfg["ics"]["liftable_respawn_seconds"])
    check("the vehicle respawns at its spot", sum(e.liftable == "vehicle" for e in m.liftables.props) == n_cars
          and car not in m.liftables.props)
    # liftable_vehicle_toss = false: the fase3-ie order (vehicle-lift-and-position.md 2.1), on the truck
    respawn = float(w.ic.get("respawn_seconds") or 20.0) + 1.0
    if not ch.alive:
        s.clock += respawn
        s.run_due()
    truck = next(e for e in m.liftables.props if e.liftable == "vehicle" and e.world_state == 0x2E000F04)
    ch.pos = [truck.pos[0] + 2.0, truck.pos[1], truck.pos[2]]
    w.ic["liftable_vehicle_toss"] = False                     # the match's own copy of [ics]
    n0 = len(s.sent)
    m.liftables.lift(ch, truck, _Inst())
    run(s, m, 0.2, step=0.05)
    w.ic["liftable_vehicle_toss"] = True
    old = s.labels(n0)
    check("liftable_vehicle_toss = false: the fase3-ie order (PickupObject and over the head 0.11 s in, no toss)",
          any(f"{truck.name}: SuperStrength_PickupObject" in lbl for lbl in old)
          and any(f"{truck.name} carried over the head" in lbl for lbl in old)
          and not any("tossed onto" in lbl for lbl in old), old)
    run(s, m, 0.5)
    # [ics] liftable_face_lead (fase3-ii, agl-qer-lift.md 4): the throw key waits the lead after the "throws" bundle
    w.ic["liftable_face_lead"] = 0.13
    n1, t_throw, seen_at = len(s.sent), m.t, {}
    m.liftables.throw(ch, [ch.pos[0] + 6.0, ch.pos[1], ch.pos[2]])
    for _ in range(8):
        k = len(s.sent)
        run(s, m, 0.05, step=0.05)
        for lbl in s.labels(k):
            seen_at.setdefault(lbl or "", round(m.t - t_throw, 3))
    w.ic["liftable_face_lead"] = 0.0
    thr = next((t for lbl, t in seen_at.items() if f"throw {truck.name} (0x8d)" in lbl), None)
    check("liftable_face_lead: the throw 0x8D goes the lead after the facing bundle (the turn first), not in its tick",
          any(f"throws {truck.name}" in (lbl or "") for lbl in s.labels(n1)[:3]) and thr is not None and thr >= 0.13 - 1e-6,
          (thr, s.labels(n1)[:4]))
    run(s, m, 1.6)
    # a carrier killed mid-toss drops the vehicle where it is, no catch (vehicle-lift-and-position.md 7.6)
    suv = next(e for e in m.liftables.props if e.liftable == "vehicle" and e.world_state == 0x2E000795)
    ch.pos = [suv.pos[0] - 2.0, suv.pos[1], suv.pos[2]]
    _c, toss_at, catch_at, _r = m.liftables._toss_timeline(ch)
    m.liftables.lift(ch, suv, _Inst())
    run(s, m, toss_at + 0.25, step=0.05)
    m.liftables.throw(ch, [ch.pos[0] + 6.0, ch.pos[1], ch.pos[2]])        # pressed while the vehicle is in the air
    check("a throw pressed mid-toss is refused: ready only liftable_attach_seconds after the catch",
          getattr(ch, "carrying", None) is suv and not ch.carry_ready and not getattr(suv, "flying", False),
          (getattr(ch, "carrying", None), ch.carry_ready, getattr(suv, "flying", False)))
    n0 = len(s.sent)
    kill(w, ch)
    run(s, m, catch_at, step=0.05)
    dropped = s.labels(n0)
    check("a champion killed mid-toss drops the vehicle where it is (it blows up); no catch, no more toss states",
          getattr(ch, "carrying", None) is None and getattr(suv, "carried_by", 0) is None
          and any(f"{suv.name} dropped" in lbl for lbl in dropped) and not any(
              "SuperStrength_PickupObject" in lbl or f"{suv.name} tossed onto" in lbl for lbl in dropped), dropped)
    s.clock += respawn
    s.run_due()
    # 2026-10-29 (fase3-if review): the documented switch-back liftable_attach_kinds = ["rock", "vehicle"] also works
    # with the toss on: the catch attaches the vehicle (it was carried by its own states whatever the key said)
    s2, w2, m2 = make(cfg, data, 0x40000C82)
    run(s2, m2, 14.0)
    ch2 = w2.champion
    car2 = next(e for e in m2.liftables.props if e.liftable == "vehicle")
    ch2.pos, ch2.safe_zone = [car2.pos[0] - 2.0, car2.pos[1], car2.pos[2]], False
    ch2.stolen[7] = data.stolen_power(0x480003CB)[0]
    w2.ic["liftable_attach_kinds"] = ["rock", "vehicle"]      # the match's own copy of [ics]
    w2.ic["liftable_vehicle_toss"] = True
    _c, _t, _catch, ready2 = m2.liftables._toss_timeline(ch2)
    n0 = len(s2.sent)
    m2.liftables.lift(ch2, car2, _Inst())
    run(s2, m2, ready2 + 0.1, step=0.05)
    caught = s2.labels(n0)
    check("liftable_attach_kinds = [\"rock\", \"vehicle\"] with the toss: tossed, then attached to the champion at the "
          "catch (not carried by its own states), ready to throw after it",
          getattr(car2, "attach_parent", None) is not None and car2.attach_parent[0] == ch2.eid and ch2.carry_ready
          and any(f"{car2.name} tossed onto" in lbl for lbl in caught)
          and any(f"{car2.name} attached to {ch2.name}" in lbl for lbl in caught)
          and not any(f"{car2.name} carried over the head" in lbl for lbl in caught), caught)
    n0 = len(s2.sent)
    m2.liftables.throw(ch2, [ch2.pos[0] + 6.0, ch2.pos[1], ch2.pos[2]])
    run(s2, m2, 0.5)
    check("... and the throw detaches it", getattr(car2, "attach_parent", None) is None
          and any(f"{car2.name} detached" in lbl for lbl in s2.labels(n0)), s2.labels(n0))

    # ---- stealth strips: the owner's shimmer by the server (stealth-rendering.md, 2026-10-28) ----
    if not ch.alive:                    # the mid-toss kill above: wait out that death's own respawn time (by level)
        s.clock += float(w.ic.get("respawn_seconds") or 20.0) + 1.0
        s.run_due()
    strip = m.stealth[0]
    ch.pos = [strip.pos[0], strip.pos[1], ch.pos[2]]
    run(s, m, 0.5)
    check("stealth: entering a strip starts Vfx_Status_Stealth_Active on the champion", ch.in_stealth
          and any("Vfx_Status_Stealth_Active" in lbl and "stop" not in lbl for lbl in s.labels()))
    try:
        w.reveal(ch)                    # 2026-10-28 10:35: an attack inside the strip raised and froze the match
        run(s, m, float(cfg["ics"].get("match_stealth_reveal", 2.0)) + 0.5)
        ok = True
    except Exception as e:              # noqa: BLE001
        ok = repr(e)
    check("stealth: a reveal inside the strip works and the shimmer comes back", ok is True
          and any("Vfx_Status_Stealth_Active again" in lbl for lbl in s.labels()), ok)
    ch.pos = [strip.pos[0] + 20.0, strip.pos[1] - 10.0, ch.pos[2]]
    run(s, m, 0.5)
    check("stealth: leaving it signals the shimmer off", not ch.in_stealth
          and any("stop Vfx_Status_Stealth_Active" in lbl for lbl in s.labels()))

    # ---- stealth tiles on the jungle-mouth corners' collision faces (stealth-alignment.md, tester 2026-10-28 15:00) --
    ca, _mode = maps.map_for(0x40000C82)
    buf = data.packs.pack(ca["map_pack"]).data
    _cls, agent_r, blob = next(b for b in navmesh.find_blobs(buf) if b[0] == 0x10000003)
    ox, oy = ca["landblock"][0] * navmesh.LANDBLOCK, ca["landblock"][1] * navmesh.LANDBLOCK
    owner = {}
    for tri in navmesh.parse_blob(buf, blob):
        p = [(round(x - ox, 3), round(y - oy, 3)) for x, y, _z in tri]
        for k in range(3):
            owner.setdefault(tuple(sorted((p[k], p[(k + 1) % 3]))), []).append(p[(k + 2) % 3])
    faces = []                                          # rim + agent radius = where a champion's body stops
    for (a, b), opp in owner.items():
        if len(opp) == 1:
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            d = ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
            ob = (-d[1], d[0]) if (opp[0][0] - a[0]) * d[1] - (opp[0][1] - a[1]) * d[0] > 0 else (d[1], -d[0])
            faces.append(((a[0] + agent_r * ob[0], a[1] + agent_r * ob[1]), d, ob, seg))

    def against_face(ent):
        """(worst |offset| m, angle deg, deepest offset m, + = past the face) of the tile's long edge lying along a
        collision face, or None"""
        yaw, half_long, half_short = ent.tile
        u, best = (math.cos(yaw), math.sin(yaw)), None
        for side in (1.0, -1.0):
            nrm = (-u[1] * side, u[0] * side)
            mx, my = ent.pos[0] + half_short * nrm[0], ent.pos[1] + half_short * nrm[1]
            for (ax, ay), d, ob, seg in faces:
                ang = math.degrees(math.acos(min(1.0, abs(u[0] * d[0] + u[1] * d[1]))))
                if seg < 1.0 or nrm[0] * ob[0] + nrm[1] * ob[1] < 0.9 or ang > 3.0:
                    continue
                offs = [((mx + t * u[0] - ax) * ob[0] + (my + t * u[1] - ay) * ob[1])
                        for t in (half_long * (k / 4.0 - 1.0) for k in range(9))
                        if -0.05 <= (mx + t * u[0] - ax) * d[0] + (my + t * u[1] - ay) * d[1] <= seg + 0.05]
                if len(offs) >= 3 and abs(offs[len(offs) // 2]) < 1.5:
                    fit = (round(max(abs(o) for o in offs), 3), round(ang, 2), round(max(offs), 3))
                    best = min(best or fit, fit)
        return best

    flush = [i for i, sp in enumerate(ca["stealth"]) if sp.get("flush")]
    # 2026-10-29 18:31 (tester: the side fields still stand off the edge): the navmesh-face layout (fase3-if) is the
    # one with [ics] match_stealth_render_faces = false; the shipped one lies on the drawn faces (checked below)
    cfg["ics"]["match_stealth_render_faces"] = False
    # 2026-10-29 19:55 (tester: the vertical fields a little further toward the lane): the face / render / corner checks
    # below measure the layouts without [ics] match_stealth_lane_shift; the shipped shift is checked on its own
    lane_shift = float(cfg["ics"].get("match_stealth_lane_shift", 0.0) or 0.0)
    cfg["ics"]["match_stealth_lane_shift"] = 0.0
    _sn, _wn, mn = make(cfg, data, 0x40000C82)
    cfg["ics"]["match_stealth_render_faces"] = True
    _s0, _w0, m0 = make(cfg, data, 0x40000C82)
    cfg["ics"]["match_stealth_lane_shift"] = lane_shift
    fits = {i: against_face(mn.stealth[i]) for i in flush if i < len(mn.stealth)}
    check("stealth: the 4 jungle-mouth tiles lie along their corner's collision faces (navmesh rim + 0.525 m; long "
          "edge <= 0.3 m from the face on the walkable side, <= 3 deg)", len(m.stealth) == len(ca["stealth"])
          and len(fits) == 4 and all(f and f[0] <= 0.3 and f[2] <= 0.05 for f in fits.values()), fits)

    def mirrored(ta, tb):
        """tile tb = tile ta mirrored about x 80 (a tile is the same rectangle after a 180 deg turn)"""
        turn = (math.degrees(ta.tile[0] + tb.tile[0]) - 180.0) % 180.0
        return (abs(ta.pos[0] + tb.pos[0] - 160.0) < 0.01 and abs(ta.pos[1] - tb.pos[1]) < 0.01
                and min(turn, 180.0 - turn) < 0.01)
    check("stealth: left / right mouths mirrored (x -> 160 - x, yaw -> 180 - yaw)", len(flush) == 4 and all(
        mirrored(mn.stealth[a], mn.stealth[b]) for a, b in ((flush[0], flush[1]), (flush[2], flush[3]))))

    def on_render_face(ent):
        """worst distance (m) of the tile's obstacle-side long edge from a maps.py stealth_render_faces line, or None"""
        yaw, hl, hs = ent.tile
        u = (math.cos(yaw), math.sin(yaw))
        best = None
        for (fx, fy), fdeg, (nx, ny) in ca.get("stealth_render_faces", ()):
            fd = (math.cos(math.radians(fdeg)), math.sin(math.radians(fdeg)))
            if abs(u[0] * fd[1] - u[1] * fd[0]) > 0.05:
                continue
            ex, ey = ent.pos[0] - hs * nx, ent.pos[1] - hs * ny          # the edge's midpoint on the wall side
            offs = [abs((ex + t * u[0] - fx) * nx + (ey + t * u[1] - fy) * ny) for t in (-hl, 0.0, hl)]
            if max(offs) < 0.5:
                best = min(best or 9.0, round(max(offs), 3))
        return best
    rend = [i for i, sp in enumerate(ca["stealth"]) if sp.get("render")]
    rfits = {i: on_render_face(m0.stealth[i]) for i in rend}
    check("stealth: with match_stealth_render_faces the west / east vertical tiles and the east diagonal lie on the "
          "drawn walls (pillar x 52.90, chain link x 106.95 and 157 deg; <= 0.03 m) and moved 0.15-0.4 m from fase3-if",
          len(rend) == 3 and all(f is not None and f <= 0.03 for f in rfits.values())
          and all(0.15 <= math.hypot(m0.stealth[i].pos[0] - mn.stealth[i].pos[0],
                                     m0.stealth[i].pos[1] - mn.stealth[i].pos[1]) <= 0.4 for i in rend)
          and all(m0.stealth[i].pos[:2] == mn.stealth[i].pos[:2] for i in flush if i not in rend), rfits)
    lane = [i for i, sp in enumerate(ca["stealth"]) if sp.get("lane_dir")]
    moved = {i: (round(m.stealth[i].pos[0] - m0.stealth[i].pos[0], 3), round(m.stealth[i].pos[1] - m0.stealth[i].pos[1], 3))
             for i in range(len(m.stealth))}
    check("stealth: [ics] match_stealth_lane_shift moves the two vertical jungle-mouth tiles toward the lane (-y) by the "
          "shift, keeps their wall edge (x) and leaves every other tile in place",
          lane_shift > 0 and len(lane) == 2 and all(moved[i] == (0.0, round(-lane_shift, 3)) for i in lane)
          and all(moved[i] == (0.0, 0.0) for i in moved if i not in lane)
          and all(on_render_face(m.stealth[i]) is not None and on_render_face(m.stealth[i]) <= 0.03 for i in lane), moved)

    def nearest_corner(ent, px, py):
        yaw, hl, hs = ent.tile
        u, n_ = (math.cos(yaw), math.sin(yaw)), (-math.sin(yaw), math.cos(yaw))
        return min((round(math.hypot(ent.pos[0] + a * hl * u[0] + b * hs * n_[0] - px,
                                     ent.pos[1] + a * hl * u[1] + b * hs * n_[1] - py), 3), a, b)
                   for a in (1, -1) for b in (1, -1))
    starts = [nearest_corner(m0.stealth[flush[0]], 52.725, 83.125), nearest_corner(m0.stealth[flush[1]], 107.075, 83.125),
              nearest_corner(mn.stealth[flush[0]], 52.725, 83.125), nearest_corner(mn.stealth[flush[1]], 107.075, 83.125)]
    check("stealth: each vertical tile starts at its garden corner (side face x 52.725 / 107.075, lane face y 83.125)",
          all(c[0] < 0.3 for c in starts), starts)
    hidden = ((52.1, 84.0), (107.9, 84.0), (52.1, 86.5), (107.9, 86.5), (55.0, 87.6), (105.0, 87.6))
    # the vertical tiles reach 1 m further toward the lane with match_stealth_lane_shift (their south end y 82.2 + the
    # 0.5 m margin): the lane points in front of the mouths are 1 m further south than before
    seen = ((49.5, 85.0), (110.5, 85.0), (51.7, 82.0 - lane_shift), (108.3, 82.0 - lane_shift), (53.57, 88.97),
            (106.43, 88.97))
    check("stealth: a champion in either corner or along the fence is hidden; one in the passage, on the lane in "
          "front of the mouth or past the diagonal is not", all(m.strip_of(q) is not None for q in hidden)
          and all(m.strip_of(q) is None for q in seen),
          ([q for q in hidden if m.strip_of(q) is None], [q for q in seen if m.strip_of(q) is not None]))

    class _Hidden:                                         # a champion standing in a strip, not revealed
        def __init__(self, x, y):
            self.pos, self.in_stealth, self.revealed_until = [x, y, 0.0], True, 0.0
    # the bend point 0.6 m lower than before: the lane-shifted vertical tile ends 1 m lower (match_stealth_lane_shift)
    bend, south, along = _Hidden(52.6, 86.4), _Hidden(51.7, 83.5), _Hidden(55.5, 88.3)   # tiles 4 + 6 / 4 / 6
    m.ic["match_stealth_any_shared"] = True
    shared = (m.visible_to(bend, along), m.visible_to(along, bend), m.visible_to(south, along))
    m.ic["match_stealth_any_shared"] = False
    first_only = m.visible_to(bend, along)
    m.ic["match_stealth_any_shared"] = True
    check("stealth: at the L's bend both tiles count (champion and enemy in the diagonal tile see each other; the "
          "vertical tile's far end stays hidden); match_stealth_any_shared = false: the first tile only",
          shared == (True, True, False) and first_only is False, (shared, first_only))
    cfg["ics"]["match_stealth_overrides"] = {"crime_alley": {"4": {"pos": [51.7, 84.0]}, "5": {"pos": [108.3, 84.0]}}}
    _s2, _w2, m2 = make(cfg, data, 0x40000C82)
    cfg["ics"]["match_stealth_overrides"] = {}
    check("stealth: [ics] match_stealth_overrides moves a tile (the vertical tiles back at y 84.0, yaw kept)",
          [tuple(round(v, 2) for v in m2.stealth[i].pos[:2]) for i in (4, 5)] == [(51.7, 84.0), (108.3, 84.0)]
          and abs(m2.stealth[4].tile[0] - math.radians(90.0)) < 1e-6 and m2.stealth[6].pos[:2] == m.stealth[6].pos[:2],
          [m2.stealth[i].pos[:2] for i in (4, 5, 6)])

    # ---- the tester's map tour (/tour) ----
    from ics.match.tour import Tour
    said = []
    tour = Tour(m, said.append)
    tour.command(["tour"])
    check("tour: stops built and the champion moved to the first", len(tour.stops) >= 20 and said
          and math.hypot(w.champion.pos[0] - tour.stops[0]["pos"][0], w.champion.pos[1] - tour.stops[0]["pos"][1]) < 3.0,
          (len(tour.stops), said[:1]))
    tour.command(["tour", "5"])
    check("tour: /tour 5 goes to stop 5", tour.i == 4 and said[-1].startswith("Parada 5/"), said[-1:])
    tour.showroom(["vitrina"])
    first = getattr(tour, "_shown", None)
    tour.showroom(["vitrina"])
    check("showroom: the map's placeable world states, one at a time in front of the champion",
          len(tour.showroom_list()) > 50 and first is not None and first.eid not in w.entities
          and tour._shown.eid in w.entities and said[-1].startswith("Vitrina 2/"), (len(tour.showroom_list()), said[-1:]))
    tour.vehicle(["vehiculo", "6"])
    check("vehiculo 6: the gallery's sixth vehicle (0x2E000F04) alone in front", said[-1].startswith("Vehiculo 6/7")
          and tour._shown.world_state == 0x2E000F04, said[-2:])

    # ---- bosses and scheduled objectives (map-objectives-recipes.md) ----
    print("bosses")
    s, w, m = make(cfg, data, 0x40000C82)
    run(s, m, 13.0 + cfg["ics"]["match_raider"]["crime_alley"]["at"] - 5.0)
    # 2026-10-28 15:00 (tester report: no camp in the centre; the side camps stand on the upper sidewalk by each jungle
    # mouth; camps-colour-bar-positions.md 3): two camps of 1 Heavy Tripod + 3 Tripods on the original's slots
    check("CA: no camp in the centre (tester 2026-10-28 15:00): two camps, none 'middle', both > 25 m from x = 80",
          len(m.camps) == 2 and not any(c.spec.get("middle") for c in m.camps)
          and min(abs(c.spec["pos"][0] - 80.0) for c in m.camps) > 25, [c.spec["pos"] for c in m.camps])
    tripods = [0x40000CA1, 0x40000CA0, 0x40000CA0, 0x40000CA0]
    check("CA: each camp = 1 Heavy Tripod + 3 Tripods, each unit within 0.05 m of its slot (on the navmesh, not snapped)",
          all([mu.cls for mu in c.members] == tripods and len(c.spec.get("slots") or ()) == 4
              and all(math.hypot(mu.ent.pos[0] - x, mu.ent.pos[1] - y) < 0.05
                      for mu, (x, y) in zip(c.members, c.spec["slots"])) for c in m.camps),
          [[(hex(mu.cls), [round(v, 2) for v in mu.ent.pos[:2]]) for mu in c.members] for c in m.camps])
    west, east = sorted(m.camps, key=lambda c: c.spec["pos"][0])
    check("CA: the east camp is the west's mirror (x -> 160 - x) within 0.8 m, slot by slot (the original's own east)",
          all(math.hypot(160.0 - a[0] - b[0], a[1] - b[1]) < 0.8 for a, b in zip(west.spec["slots"], east.spec["slots"])),
          list(zip(west.spec["slots"], east.spec["slots"])))
    spawn_fx = [(i, lbl) for i, lbl in enumerate(s.labels()) if lbl and "camp 0" in lbl
                and ("spawn camp 0" in lbl or "Vfx_Spawn_Alt01" in lbl)]
    check("camps: Vfx_Spawn_Alt01 (overlay + sparkles) follows each camp unit's bundle "
          "(liftables-camps-animations.md 3)", any("Vfx_Spawn_Alt01" in lbl for _i, lbl in spawn_fx)
          and spawn_fx[0][1].startswith("spawn camp 0"), spawn_fx[:4])
    labels = s.labels()
    stop_i = next((i for i, lbl in enumerate(labels) if lbl.startswith("camp 0 ") and "stop Vfx_Spawn_Alt01" in lbl), None)
    flag_i = next((i for i, lbl in enumerate(labels) if lbl.startswith("camp 0 ") and "0x1000019d = " in lbl), None)
    check("camps: the phase-in run is signalled to stop, then the unit gets its targeting flags "
          "(jungle-camps-spawn.md)", stop_i is not None and flag_i is not None and stop_i < flag_i, (stop_i, flag_i))
    check("camps: phasing complete -> attackable again", all(not mu.invulnerable for c in m.camps for mu in c.members))
    # 2026-10-28 15:00 (tester report: grey drones with no overhead bar; camps-colour-bar-positions.md 1 / 8.3)
    from ics.wire import KIND_BOOL, KIND_ENUM, KIND_INT
    heavy = west.members[0].ent
    minion = next((mu.ent for mu in m.waves.minions if mu.ent.alive), None)
    check("camps: the client sees PVP_Team 0 and colour index 6 (yellow), the server keeps team 3; a minion sends its own",
          (0x1000009C, KIND_INT, 0) in w.properties(heavy) and (0x100007A2, KIND_ENUM, 6) in w.properties(heavy)
          and heavy.team == 3 and heavy.match_unit.team == 3 and w.floaty_key(heavy) == 0
          and (minion is None or (0x1000009C, KIND_INT, minion.team) in w.properties(minion)),
          [p for p in w.properties(heavy) if p[0] in (0x1000009C, 0x100007A2)])

    def camp_at(name, text):
        return [i for i, lbl in enumerate(labels) if lbl.startswith(name + ":") and text in lbl]
    born = next(i for i, lbl in enumerate(labels) if lbl.startswith(f"spawn {heavy.name} "))
    t3, t0 = camp_at(heavy.name, "team 3 (0x6)"), camp_at(heavy.name, "team 0 (0x6")
    check("camps: PVP_Team also goes as a change after the creation bundle, 3 then 0 (the tint runs on a change, 0xA813F0)",
          t3 and t0 and born < t3[0] < t0[0], (born, t3, t0))
    seq = {n: (camp_at(n, "stop Vfx_Spawn_Alt01"), camp_at(n, "0x1000019d = "), camp_at(n, "FloatyVitals 0x1000072c = 1"))
           for n in sorted({mu.ent.name for c in m.camps for mu in c.members})}
    check("camps: each unit gets FloatyVitals 0x1000072C = 1 (the overhead bar's push gate) after its phase-in stop and "
          "its unit flags 0x1000019D (camps-colour-bar-positions.md 8.3)",
          all(len(st) == len(f) == len(v) >= (1 if n.endswith("0x40000ca1") else 3)
              and all(a < c and b < c for a, b, c in zip(st, f, v)) for n, (st, f, v) in seq.items()),
          {n: [len(x) for x in v] for n, v in seq.items()})
    tag = struct.pack("<I", 0x1000072C)
    born_msgs = [d for lbl, d in s.sent if lbl.startswith("spawn camp ")]
    done = [d for lbl, d in s.sent if lbl.startswith(f"{heavy.name}: phasing complete (bundle)")]
    check("camps: FloatyVitals stays in extra_props (the phase-end bundle carries it), never in a creation bundle",
          all((0x1000072C, KIND_BOOL, 1) in mu.ent.extra_props for c in m.camps for mu in c.members)
          and len(born_msgs) >= 8 and not any(tag in d for d in born_msgs) and done and tag in done[-1]
          and struct.pack("<I", 0x100007A2) in born_msgs[0], (len(born_msgs), len(done)))
    s2, w2, m2 = make(cfg, data, 0x40000C82)
    first = cfg["ics"]["match_camps_first_by_map"]["crime_alley"]
    phase = cfg["ics"]["match_camp_phase_seconds"]
    run(s2, m2, 13.0 + first - phase + 1.0)
    cm = m2.camps[0].members
    hp = [mu.ent.health for mu in cm]
    w2.damage(w2.champion, cm[0].ent, 50.0)
    check("camps: phasing units (spawned by the line minus match_camp_phase_seconds) take no damage and are not provoked",
          len(cm) == 4 and all(mu.invulnerable for mu in cm) and [mu.ent.health for mu in cm] == hp
          and m2.camps[0].provoker is None, (len(cm), hp))
    check("camps: no targeting flags while phasing", not any(lbl.startswith("camp 0 ") and "0x1000019d" in lbl
                                                            for lbl in s2.labels()))
    check("camps: no FloatyVitals (no overhead bar) while phasing, as in the original (camps-colour-bar-positions.md 2.5)",
          not any(lbl.startswith("camp ") and "FloatyVitals" in lbl for lbl in s2.labels()))
    n0 = len(s2.sent)
    # full=True: a FULL bundle (object_update_mode "delta" sends a delta otherwise, which re-sends nothing)
    w2.update(cm[0].ent, "camp 0 test bundle", full=True)
    run(s2, m2, 0.2)
    check("camps: a full bundle while phasing re-sends the phase-in run",
          any("0x10000347" in lbl and "again after its bundle" in lbl for lbl in s2.labels(n0)), s2.labels(n0)[:4])
    check("camps: still phasing just before the 'Phasing Complete' time", all(mu.invulnerable for mu in cm))
    run(s2, m2, first + 0.3 - m2.t)
    check("camps: phase over at the 'Phasing Complete' time", all(not mu.invulnerable for mu in cm), m2.t)
    # 2026-10-30 (tester report 13:18; timeline-tooltip-camp-prespawn.md 2): the first camps phase in from the
    # "Online in 30 seconds" line and are solid match_camp_prespawn_appear_before s before the jungle time
    pre, before = cfg["ics"]["match_camp_prespawn_from"], cfg["ics"]["match_camp_prespawn_appear_before"]
    s4, w4, m4 = make(cfg, data, 0x40000C82)
    run(s4, m4, 13.0 + first + pre - 0.5)
    check("camps: none before the 30-seconds line", not any(c.members for c in m4.camps), m4.t)
    run(s4, m4, 1.5)
    cm4 = [mu for c in m4.camps for mu in c.members]
    check("camps: the first camps are spawned and phasing from the 30-seconds line (Vfx_Spawn_Alt01 sent)",
          cm4 and all(mu.invulnerable and mu.phasing for mu in cm4)
          and any("Vfx_Spawn_Alt01" in lbl for lbl in s4.labels()), (m4.t, len(cm4)))
    run(s4, m4, first - before - 0.5 - m4.t)
    check("camps: still phasing half a second before they appear", all(mu.invulnerable for mu in cm4), m4.t)
    run(s4, m4, 0.75)
    check("camps: solid and attackable match_camp_prespawn_appear_before s before the jungle time",
          all(not mu.invulnerable and not mu.phasing for mu in cm4), m4.t)
    saved = cfg["ics"]["match_camp_prespawn_from"]
    cfg["ics"]["match_camp_prespawn_from"] = 0.0
    try:
        s6, w6, m6 = make(cfg, data, 0x40000C82)
        run(s6, m6, 13.0 + first - phase - 0.5)
        no_early = not any(c.members for c in m6.camps)
        run(s6, m6, 1.0)
    finally:
        cfg["ics"]["match_camp_prespawn_from"] = saved
    check("camps: match_camp_prespawn_from 0 = the fase3-ir 3 s phase before the line",
          no_early and all(c.members for c in m6.camps if not c.spec.get("boss")), m6.t)
    # the fase3-ie switch-backs ([ics] match_camp_centre / _slots / _wire_team / _vitals_tags). The match reads the shared
    # [ics] dict when its camps spawn, so the keys are restored once they have
    keys = {"match_camp_centre": True, "match_camp_slots": False, "match_camp_wire_team": None,
            "match_camp_vitals_tags": []}
    saved = {k: cfg["ics"].get(k) for k in keys}
    cfg["ics"].update(keys)
    try:
        s3, w3, m3 = make(cfg, data, 0x40000C82)
        run(s3, m3, 13.0 + first + 1.5)
    finally:
        cfg["ics"].update(saved)
    c3 = m3.camps
    ring = c3[1].members if len(c3) == 3 else []
    p3 = w3.properties(ring[0].ent) if ring else []
    check("camps, fase3-ie switch-backs: the middle camp first on the Raider pad, no slots (the ring), team 3 on the "
          "wire, no team change, no FloatyVitals", len(c3) == 3 and c3[0].spec.get("middle") is True
          and abs(c3[0].spec["pos"][1] - 97.66) < 0.1 and len(ring) == 4
          and math.hypot(ring[0].ent.pos[0] - c3[1].spec["pos"][0], ring[0].ent.pos[1] - c3[1].spec["pos"][1]) < 0.05
          and not all(math.hypot(mu.ent.pos[0] - x, mu.ent.pos[1] - y) < 0.05
                      for mu, (x, y) in zip(ring, c3[1].spec["slots"]))
          and (0x1000009C, KIND_INT, 3) in p3 and (0x100007A2, KIND_ENUM, 0) in p3
          and not any("FloatyVitals" in lbl or "the client's team" in lbl for lbl in s3.labels()),
          [(c.spec["pos"], len(c.members)) for c in c3])
    run(s, m, 7.0)
    raider = [e for e in w.entities.values() if getattr(getattr(e, "match_unit", None), "boss", None) == "raider"]
    check("CA: the Raider spawns on schedule (300 s, no middle camp to clear)", len(raider) == 1)
    if raider:
        rn, rl = raider[0].name, s.labels()
        rf = [i for i, lbl in enumerate(rl) if lbl.startswith(rn + ":") and "0x1000019d = " in lbl]
        rv = [i for i, lbl in enumerate(rl) if lbl.startswith(rn + ":") and "FloatyVitals 0x1000072c = 1" in lbl]
        check("CA: the Raider (role camp) is team 0 / colour 6 on the client and gets FloatyVitals after its unit flags, "
              "never 0x10000B2D", (0x1000009C, KIND_INT, 0) in w.properties(raider[0])
              and (0x100007A2, KIND_ENUM, 6) in w.properties(raider[0]) and rf and rv and rf[0] < rv[0]
              and not any(p[0] == 0x10000B2D for p in w.properties(raider[0]))
              and not any(lbl.startswith(rn + ":") and "0x10000b2d" in lbl.lower() for lbl in rl), (rn, rf, rv))
    pad = getattr(m, "nook_pad", None)
    check("CA: the relay 0x4000089D stands at the nook, locked, then unlocked with the Raider (deep-scan-maps.md)",
          pad is not None and pad.class_id == 0x4000089D and any("Vfx_Locked" in l for l in s.labels())
          and any("Vfx_Unlocked" in l for l in s.labels()), getattr(pad, "class_id", None))
    unlock = [l for l in s.labels() if l.startswith("nook pad:") and ("stop Vfx_Locked" in l or "Vfx_Unlocked" in l)]
    check("CA: the unlock stops Vfx_Locked (0x11F, every run) before Vfx_Unlocked (fase3-ih, padlock stayed)",
          len(unlock) >= 2 and "stop Vfx_Locked (0x11f" in unlock[0] and "Vfx_Unlocked" in unlock[1], unlock)
    check("CA: the lane spawners 0x2E000D03 stand on both mouths",
          sum(1 for e in w.entities.values() if getattr(e, "world_state", 0) == 0x2E000D03) == 2)
    # 2026-10-29 (tester report 2026-10-29 12:45; ca-holes-pedestal-turrets.md P1 / O2)
    peds = sorted((round(e.pos[0], 2), e.team) for e in w.entities.values() if getattr(e, "world_state", 0) == 0x2E000A36)
    check("CA: the base hologram pedestals 0x2E000A36 under the holograms (1.0 / 159.0, 77.5; tester 14:40 and 16:40 moved them)",
          peds == [(1.0, 1), (159.0, 2)], peds)
    heads = [mu.head for mu in m.structures if getattr(mu, "head", None) is not None]
    # 2026-10-29 tester report 23:03: no server heads by default (match_turret_head_skip_own_child); heads_raider_end_2303
    # checks a server head's side with the switch off
    check("CA: every turret head carries its body's side 0x100007A2 (3 / 5) and gets the team as a change",
          (not heads and m.ic.get("match_turret_head_skip_own_child", True)) or heads and all((0x100007A2, KIND_ENUM, 3 if h.team == 1 else 5) in h.extra_props for h in heads)
          and all(any(lbl == f"{h.name}: team {h.team} (0x6)" for lbl in s.labels()) for h in heads),
          [(h.name, [p for p in h.extra_props if p[0] == 0x100007A2]) for h in heads])
    w.damage(w.champion, raider[0], raider[0].health + 1)
    run(s, m, 2.0)
    check("CA: the Raider's own script drops its pad 0x40000C49", any(e.class_id == 0x40000C49 for e in w.entities.values()))
    check("CA: Raider kill -> announcer event 61", any("event 61 " in lbl for lbl in s.labels()))
    # 2026-10-28 (map-audit-all.md 11): Gotham Divided's lids follow the terrain sites flattened in the installed pack
    from icserver import terrainfix
    s, w, m = make(cfg, data, 0x40000399)
    specs = cfg["ics"]["match_socket_covers"]["gotham_divided"]
    check("GD: every lid names a terrain site of icserver/terrainfix.py",
          {sp.get("terrain_site") for sp in specs} <= set(terrainfix.SITES), [sp.get("terrain_site") for sp in specs])
    check("GD: a lid on every socket the installed pack has not flattened",
          len(m.covers) == sum(1 for sp in specs if not m._socket_flattened(sp["terrain_site"])), len(m.covers))
    exits1 = {(40.0, 150.0), (35.0, 125.0), (10.0, 120.0)}
    m._socket_flattened = lambda site: site == "gotham_divided_lane_exits_team1"
    m._spawn_socket_covers()
    at = {(round(e.pos[0], 2), round(e.pos[1], 2)) for e in m.covers}
    check("GD: team 1's lane exits flattened -> their 3 lids left out; team 2's 3 and the 2 pit lids stay",
          len(m.covers) == 5 and not (at & exits1), sorted(at))
    m.ic["match_socket_covers_skip_flat"] = False
    m._spawn_socket_covers()
    check("GD: match_socket_covers_skip_flat = false -> all 8 lids", len(m.covers) == 8, len(m.covers))
    s, w, m = make(cfg, data, 0x40000399)
    pods = cfg["ics"]["match_pods"]["gotham_divided"]
    run(s, m, 13.0 + pods["at"] + pods["raider"]["after"] + 1.0)
    check("GD: two phase pods and the Raider", len(m.bosses.pods) == 2 and any(
        getattr(getattr(e, "match_unit", None), "boss", None) == "raider" for e in w.entities.values()))
    raider = next(e for e in w.entities.values() if getattr(getattr(e, "match_unit", None), "boss", None) == "raider")
    w.damage(w.champion, raider, raider.health + 1)
    run(s, m, 1.0)
    check("GD: Raider kill buff 0x48000E4B on the killer's team",
          bool(R.statuses_on(CastWorld(w, w.champion, None), w.champion).get(0x48000E4B)))
    for p in m.bosses.pods:
        w.champion.pos = list(p["mu"].ent.pos)
        run(s, m, 11.0)
    run(s, m, 45.0)
    check("GD: both pods engaged -> the Leviathan", any(
        getattr(getattr(e, "match_unit", None), "boss", None) == "leviathan" and e.alive for e in w.entities.values()))
    lead = next(mu for mu in m.camps[0].members if mu.cls == 0x40000940)
    w.damage(w.champion, lead.ent, lead.ent.health + 1)
    run(s, m, 3.5)                  # the line may wait behind another announcer item ([ics] announcer_queue)
    check("GD: killing the Regen destroyer gives team 1 the Regen beacon (0x2069, line 674)",
          any("beacon regen tier 1 to team 1" in lbl for lbl in s.labels()) and any("0x2a2 channel" in lbl for lbl in s.labels()))
    s, w, m = make(cfg, data, 0x4000013E)
    run(s, m, 14.0)
    cn = m.bosses.cannon
    check("GH: the Orbital Cannon is there, unlocked", cn is not None and cn["state"] == "unlocked")
    w.champion.pos = list(cn["mu"].ent.pos)
    run(s, m, 11.0)
    w.champion.pos = list(maps.spawn_point(0x4000013E, 1)[4:7])
    run(s, m, 10.0)
    check("GH: a cannon firing takes 125 team health from the enemy", m.team_health[2] <= 375.0, m.team_health)
    run(s, m, 60.0)
    check("GH: the cannon goes neutral and locked after 65 s", cn["state"] == "locked" and cn["owner"] == 0, cn)
    run(s, m, 121.0)
    check("GH: unlocked again 120 s later", cn["state"] == "unlocked", cn["state"])

    leash_turret_ring_camp_drop(cfg, data)
    aggro_indicator(cfg, data)
    fog_ring_announcer(cfg, data)
    ring_fog_bundles(cfg, data)
    fog_minimap_ring(cfg, data)
    fog_minimap_category(cfg, data)
    street_occluder_ring(cfg, data)
    hover_listener_gate(cfg, data)
    ring_phantom_strip(cfg, data)
    ring_bodies_strip_layers(cfg, data)
    strip_static_shadow_pad(cfg, data)
    strip_two_bit_candidates(cfg, data)
    strip3_bit9_list(cfg, data)
    agl_floor_pad_platform(cfg, data)
    click_assist(cfg, data)
    unit_separation(cfg, data)
    chase_range(cfg, data)
    carry_press_facing(cfg, data)
    aura_lift_throw_break(cfg, data)
    aura_probe(cfg, data)
    superstrength_softlock(cfg, data)
    lift_throw_wreck_1205(cfg, data)
    throw_walk_to_range_1530(cfg, data)
    power_core_turret(cfg, data)
    structures_2110(cfg, data)
    heads_raider_end_2303(cfg, data)
    turret_plate_head_scorecard_1123(cfg, data)
    pct_look_turret_head_1205(cfg, data)
    bot_shop_towers_end_1530(cfg, data)
    bot_tower_tactics_1812(cfg, data)
    core_door_regen_1530(cfg, data)
    turret_death_head_rearm_1812(cfg, data)

    ok = sum(results)
    print(f"\n{ok} / {len(results)} checks passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
