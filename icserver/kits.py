"""Server-side abilities of champions other than Gaslight Batman (2026-10-18: John Stewart first).

2026-10-18 00:57 (tester): "program John's abilities". John Stewart (variant 0x40000E57) was never released: his
skill set 0x480013E4 (pack 0xA000039B) names the skills (Q full_auto, W claymore_mine, E forward_base,
R omni_turret, passive architects_will) and gives every one the same placeholder numbers (damage 40 +40 per
rank, +0.4 scaling; cost 30 Will; cooldown 14 s -2 per rank). His effects are in the scriptlet table
0x33000000: Vfx_Jst_FullAuto_Active, Vfx_Jst_Claymore*, Vfx_Jst_Forward_Base_*, Vfx_Jst_Turret_*,
Vfx_Jst_Architect_*; his behavior graph has Wildcard_QSkill / WSkill / ESkill / RSkill. What each skill DOES
in the game was never shipped, so the behaviour below follows the names and the description ("deal damage with
your mini-gun while relying on military constructs to siege the enemy base, or bunker down"). Every number is
a setting: [combat] kits overrides KITS per variant and slot.
"""
import math
import os
import re
import struct
import time

from . import log, tutorial1
from . import messages as M
from .wire import KIND_ENUM

JOHN_STEWART = 0x40000E57

# slot -> definition. "graph": graph events raised on the champion at the cast; "vfx": scriptlets run on him
# (names; "{rank}" = the skill's rank); "effect": what the server does.
KITS = {
    JOHN_STEWART: {
        "name": "John Stewart",
        1: {"name": "Full Auto", "graph": ["Wildcard_QSkill"], "vfx": ["Vfx_Jst_FullAuto_Active"],
            "effect": "barrage", "range": 11.0, "width": 2.0, "ticks": 8, "tick": 0.25},
        2: {"name": "Claymore Mine", "graph": ["Wildcard_WSkill"],
            "vfx": ["Vfx_Jst_Claymore_Phase_Start", "Vfx_Jst_Claymore"], "vfx_end": ["Vfx_Jst_Claymore_Phase_Stop"],
            "effect": "mine", "range": 9.0, "radius": 3.5, "arm": 1.0, "lifetime": 30.0},
        3: {"name": "Forward Base", "graph": ["Wildcard_ESkill"], "vfx": ["Vfx_Jst_Forward_Base_{rank}"],
            "vfx_end": ["Vfx_Jst_Forward_Base_Dismantle"],
            "effect": "base", "range": 6.0, "radius": 5.0, "duration": 12.0, "heal": 12.0, "will": 6.0},
        4: {"name": "Omni Turret", "graph": ["Wildcard_RSkill"], "vfx": ["Vfx_Jst_Turret", "Vfx_Jst_Turret_Active_{rank}"],
            "vfx_shot": ["Vfx_Jst_Turret_{rank}_Fire"], "vfx_end": ["Vfx_Jst_Turret_Dismantle"],
            "effect": "turret", "range": 8.0, "reach": 12.0, "duration": 20.0, "interval": 1.0, "shot_share": 0.35},
        "base": {"will_regen": 2.0, "damage": 40.0, "damage_per_rank": 40.0, "cost": 30.0, "cost_per_rank": 10.0,
                 "cooldown": 14.0, "cooldown_per_rank": -2.0, "min_cooldown": 4.0},
        "passive_vfx": ["Vfx_Jst_Architect_Start"],
    },
}

GRAPH_LIMIT = 900000        # pack 0xA0000038: graph-event names before this offset, scriptlet names after
_names = None


def names(cfg):
    """({graph event name: id}, {scriptlet name: id}) from pack 0xA0000038 (tables 0x300000A4 / 0x33000000)."""
    global _names
    if _names is not None:
        return _names
    from . import rp
    graph, scripts = {}, {}
    try:
        data = rp.PackSet(os.path.join(cfg.game_dir, "rp")).pack(0xA0000038).data
        for mt in re.finditer(rb"[A-Za-z][A-Za-z0-9_]{2,80}", data):
            s, k = mt.group(), mt.start()
            if k < 8:
                continue
            ident, length = struct.unpack_from("<II", data, k - 8)
            if length == len(s) and ident >> 24 == 0x10:
                (graph if k < GRAPH_LIMIT else scripts).setdefault(s.decode(), ident)
    except (OSError, ValueError) as e:
        log.info(f"kits: name tables not read ({e})")
    _names = (graph, scripts)
    return _names


def kit_for(cfg, variant):
    kit = KITS.get(int(variant))
    over = (cfg["combat"].get("kits") or {}).get(f"{int(variant):#x}") or (cfg["combat"].get("kits") or {}).get(
        f"0x{int(variant):08X}")
    if kit and over:
        kit = {**kit, **{int(k) if str(k).isdigit() else k: ({**kit.get(int(k) if str(k).isdigit() else k, {}), **v}
                                                         if isinstance(v, dict) else v) for k, v in over.items()}}
    return kit


class KitCaster:
    """Casts a kit's Q W E R for the match's champion. One per match (Match.kit_caster)."""

    def __init__(self, session, match, kit):
        self.s, self.m, self.kit = session, match, kit
        self.cooldown_until = {}
        self.mines, self.zones = [], []
        self.s.every(0.25, self._tick, match.group, first_delay=0.25)

    # ---- helpers ---------------------------------------------------------------------------------
    def rank(self, slot):
        return max(1, (self.m.skill_ranks >> (4 * slot)) & 0xF)

    def stat(self, key, slot):
        b = self.kit.get("base", {})
        r = self.rank(slot) - 1
        val = float(b.get(key, 0.0)) + float(b.get(key + "_per_rank", 0.0)) * r
        return max(float(b.get("min_cooldown", 0.0)), val) if key == "cooldown" else val

    def enemies(self):
        return [e for e in self.m.entities.values() if e.alive and e.attackable and e.team != self.m.team]

    def _graph(self, names_, what):
        graph, _ = names(self.s.cfg)
        for n in names_:
            ident = graph.get(n)
            if ident:
                log.info(f"{what}: graph event {n} ({ident:#x})", self.s)
                self.s._run_scripts(self.m, M.CHAMPION_AGENT_ID, [tutorial1.RAISE_EVENT_KEY], f"{what}: {n}",
                                    [(tutorial1.RAISE_EVENT_VAR, KIND_ENUM, ident)])

    def _vfx(self, names_, slot, what):
        _, scripts = names(self.s.cfg)
        keys = []
        for n in names_:
            n = n.replace("{rank}", str(min(4, self.rank(slot))))
            if n in scripts:
                keys.append(scripts[n])
            else:
                log.info(f"kits: no scriptlet named {n}", self.s)
        if keys:
            log.info(f"{what}: scriptlets {', '.join(hex(k) for k in keys)}", self.s)
            self.s._run_scripts(self.m, M.CHAMPION_AGENT_ID, keys, what)

    def _point(self, xyz, reach):
        """The aimed point, at most reach m away."""
        bx, by, bz = self.m.mover.pos
        if not xyz:
            h = self.m.mover.heading
            return (bx + math.cos(h) * reach, by + math.sin(h) * reach, bz)
        dx, dy = xyz[0] - bx, xyz[1] - by
        d = math.hypot(dx, dy)
        if d > reach and d > 0:
            return (bx + dx / d * reach, by + dy / d * reach, bz)
        return (xyz[0], xyz[1], bz)

    def _hit(self, ent, amount, what):
        log.info(f"{what} hits {ent.name} ({amount:.0f})", self.s)
        self.s._damage(self.m, ent, int(round(amount)))

    # ---- casting ---------------------------------------------------------------------------------
    def cast(self, slot, target, xyz):
        m = self.m
        sk = self.kit.get(slot)
        if not sk:
            log.info(f"{self.kit['name']}: slot {slot} has no ability", self.s)
            return
        if not (m.skill_ranks >> (4 * slot)) & 0xF:
            log.info(f"{sk['name']}: not ranked yet (use the '+')", self.s)
            return
        now = time.time()
        left = self.cooldown_until.get(slot, 0) - now
        if left > 0:
            log.info(f"{sk['name']}: on cooldown ({left:.1f} s)", self.s)
            return
        cost = self.stat("cost", slot)
        will, will_max = m.vitals[1]
        if will < cost:
            log.info(f"{sk['name']}: not enough Will ({will:.0f} < {cost:.0f})", self.s)
            return
        m.vitals[1] = (will - cost, will_max)
        cd = self.stat("cooldown", slot)
        self.cooldown_until[slot] = now + cd
        from . import abilities
        self.s.send_many([(f"{sk['name']} cooldown {cd:g} s (0x20f8)", abilities.skill_cooldown(slot, now + cd)),
                          (f"Will {m.vitals[1][0]:.0f} (0x42)", M.vitals(M.CHAMPION_AGENT_ID, m.vitals))])
        dmg = self.stat("damage", slot)
        log.info(f"{self.kit['name']}: {sk['name']} (rank {self.rank(slot)}, {dmg:.0f} damage, {cost:.0f} Will, "
                 f"cooldown {cd:g} s)", self.s)
        self._graph(sk.get("graph", []), sk["name"])
        self._vfx(sk.get("vfx", []), slot, sk["name"])
        getattr(self, "_" + sk["effect"])(slot, sk, target, xyz, dmg)

    # Q: a burst of mini-gun fire along the aim
    def _barrage(self, slot, sk, target, xyz, dmg):
        m = self.m
        ticks, tick = int(sk.get("ticks", 8)), float(sk.get("tick", 0.25))
        aim = (target.pos[0], target.pos[1]) if target else (xyz or self._point(None, 5.0))[:2]
        for i in range(ticks):
            def fire(i=i):
                if self.s.match is not m:
                    return
                bx, by = m.mover.pos[0], m.mover.pos[1]
                dx, dy = aim[0] - bx, aim[1] - by
                n = math.hypot(dx, dy) or 1.0
                dx, dy = dx / n, dy / n
                best = None
                for e in self.enemies():
                    t = (e.pos[0] - bx) * dx + (e.pos[1] - by) * dy
                    side = abs((e.pos[0] - bx) * dy - (e.pos[1] - by) * dx)
                    if 0 < t <= float(sk.get("range", 11.0)) and side <= float(sk.get("width", 2.0)):
                        if best is None or t < best[0]:
                            best = (t, e)
                if best:
                    self._hit(best[1], dmg / ticks, sk["name"])
            self.s.later(tick * i, fire, m.group)

    # W: a mine at the aimed point; it goes off when an enemy comes near
    def _mine(self, slot, sk, target, xyz, dmg):
        p = self._point(xyz, float(sk.get("range", 9.0)))
        now = time.time()
        self.mines.append({"pos": p, "armed": now + float(sk.get("arm", 1.0)), "until": now + float(sk.get("lifetime", 30.0)),
                           "radius": float(sk.get("radius", 3.5)), "damage": dmg, "slot": slot, "sk": sk})
        log.info(f"Claymore Mine placed at ({p[0]:.1f}, {p[1]:.1f})", self.s)

    # E: a base at the aimed point; inside it John regains health and Will
    def _base(self, slot, sk, target, xyz, dmg):
        p = self._point(xyz, float(sk.get("range", 6.0)))
        self.zones.append({"kind": "base", "pos": p, "until": time.time() + float(sk.get("duration", 12.0)),
                           "radius": float(sk.get("radius", 5.0)), "slot": slot, "sk": sk})
        log.info(f"Forward Base built at ({p[0]:.1f}, {p[1]:.1f})", self.s)

    # R: a turret at the aimed point that shoots the nearest enemy
    def _turret(self, slot, sk, target, xyz, dmg):
        p = self._point(xyz, float(sk.get("range", 8.0)))
        self.zones.append({"kind": "turret", "pos": p, "until": time.time() + float(sk.get("duration", 20.0)),
                           "next": time.time() + float(sk.get("interval", 1.0)), "slot": slot, "sk": sk,
                           "damage": dmg * float(sk.get("shot_share", 0.35))})
        log.info(f"Omni Turret built at ({p[0]:.1f}, {p[1]:.1f})", self.s)

    def _tick(self):
        m = self.m
        if self.s.match is not m:
            return False
        now = time.time()
        for mine in list(self.mines):
            if now > mine["until"]:
                self.mines.remove(mine)
                self._vfx(mine["sk"].get("vfx_end", []), mine["slot"], "mine expires")
                continue
            if now < mine["armed"]:
                continue
            near = [e for e in self.enemies()
                    if math.hypot(e.pos[0] - mine["pos"][0], e.pos[1] - mine["pos"][1]) <= mine["radius"]]
            if near:
                self.mines.remove(mine)
                self._vfx(mine["sk"].get("vfx_end", []), mine["slot"], "mine goes off")
                for e in near:
                    self._hit(e, mine["damage"], "Claymore Mine")
        heal, will = 0.0, float(self.kit.get("base", {}).get("will_regen", 0.0)) * 0.25    # Will per second
        for z in list(self.zones):
            if now > z["until"]:
                self.zones.remove(z)
                self._vfx(z["sk"].get("vfx_end", []), z["slot"], f"{z['sk']['name']} ends")
                log.info(f"{z['sk']['name']} ends", self.s)
                continue
            if z["kind"] == "base":
                if math.hypot(m.mover.pos[0] - z["pos"][0], m.mover.pos[1] - z["pos"][1]) <= z["radius"]:
                    heal += float(z["sk"].get("heal", 12.0)) * 0.25
                    will += float(z["sk"].get("will", 6.0)) * 0.25
            elif z["kind"] == "turret" and now >= z["next"]:
                z["next"] = now + float(z["sk"].get("interval", 1.0))
                reach = float(z["sk"].get("reach", 12.0))
                cand = [(math.hypot(e.pos[0] - z["pos"][0], e.pos[1] - z["pos"][1]), e) for e in self.enemies()]
                cand = [c for c in cand if c[0] <= reach]
                if cand:
                    self._vfx(z["sk"].get("vfx_shot", []), z["slot"], "turret fires")
                    self._hit(min(cand, key=lambda c: c[0])[1], z["damage"], "Omni Turret")
        if heal or will:
            (hp, hp_max), (wl, wl_max) = m.vitals
            new = [(min(hp_max, hp + heal), hp_max), (min(wl_max, wl + will), wl_max)]
            if new != list(m.vitals):
                m.vitals = new
                self.s.send("Forward Base heals" if heal else "Will regenerates",
                            M.vitals(M.CHAMPION_AGENT_ID, m.vitals))
        return True
