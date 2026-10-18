"""Free play on a champion-select map (2026-10-18, Coast City v AI as a test map): the locked champion's
levels and skill ranks, a training drone that cannot be destroyed, and a tour of the champion's animations.

2026-10-18 00:44 (tester): "level up in the HUD starting at level 6, every possible animation of the
champion, a drone that can be attacked but is indestructible". Settings: [match] maps <encounter> "free"."""
import os
import re
import struct
import time

from . import messages as M
from . import log, tutorial1
from .wire import KIND_ENUM

GRAPH_EVENT_TABLE = 0x300000A4          # name table in pack 0xA0000038: u32 id | u32 length | name
NAME_PACK = 0xA0000038
_graph_names = None                     # {name: id}
_tours = {}                             # variant -> [(id, name)]


def graph_event_names(cfg):
    """{name: id} of every animation-graph event (table 0x300000A4, pack 0xA0000038)."""
    global _graph_names
    if _graph_names is not None:
        return _graph_names
    from . import rp
    out = {}
    try:
        data = rp.PackSet(os.path.join(cfg.game_dir, "rp")).pack(NAME_PACK).data
        for mt in re.finditer(rb"[A-Za-z][A-Za-z0-9_]{2,80}", data):
            s, k = mt.group(), mt.start()
            if k < 8:
                continue
            ident, length = struct.unpack_from("<II", data, k - 8)
            if length == len(s) and ident >> 24 == 0x10 and k < 900000:    # the graph-event table only
                out.setdefault(s.decode(), ident)
    except (OSError, ValueError) as e:
        log.info(f"free play: graph event names not read ({e})")
    _graph_names = out
    return out


def champion_animations(cfg, champion):
    """[(graph event id, name)] of a champion: the names in its behavior-graph pack ("parent_pack") that are
    graph events. Read once per champion (a few MB; done when the lobby ends, before the world loads)."""
    variant = int(champion.get("variant", 0))
    if variant in _tours:
        return _tours[variant]
    names = graph_event_names(cfg)
    found = []
    from . import rp
    packs = [p for p in (champion.get("parent_pack"), champion.get("heavy_pack")) if p]
    seen = set()
    for pack in packs:
        try:
            data = rp.PackSet(os.path.join(cfg.game_dir, "rp")).pack(int(pack)).data
        except (OSError, ValueError):
            continue
        for mt in re.finditer(rb"[A-Za-z][A-Za-z0-9_]{2,80}", data):
            s = mt.group().decode()
            if s in names and s not in seen:
                seen.add(s)
                found.append((names[s], s))
    # the movement / idle states first would hide the rest: attacks, emotes, deaths and the like first
    first = ("Emote", "Taunt", "Laugh", "Joke", "Dance", "Attack", "Ability", "Skill", "Spawn", "Death", "Dead",
             "Stun", "Knock", "Cbt", "Recall", "Victory")
    found.sort(key=lambda e: (0 if any(w in e[1] for w in first) else 1, e[1]))
    _tours[variant] = found
    return found


class FreePlay:
    """Runs on a Match whose [match] maps entry has "free". The session gives it send / later / run_scripts."""

    def __init__(self, session, match, cfg):
        self.s, self.m, self.cfg = session, match, dict(cfg or {})

    # ---- levels and ranks -----------------------------------------------------------------------
    def start(self):
        m, c = self.m, self.cfg
        m.free_play = self
        m.level = int(c.get("start_level", 6))
        m.skill_points = int(c.get("skill_points", m.level))
        m.skill_ranks = 0
        m.sequence += 1
        log.info(f"free play: level {m.level}, {m.skill_points} skill points", self.s)
        out = [(f"free play: level {m.level}, {m.skill_points} skill points", m.champion_bundle(time.time()))]
        every = float(c.get("level_up_seconds", 0) or 0)
        if every > 0:
            self.s.every(every, self._level_up, m.group, first_delay=every)
        out += self._objectives()
        if c.get("drone", True):
            out += self._drone()
        if c.get("tour", True):
            self.s.later(float(c.get("tour_start", 8.0)), self._tour_start, m.group)
        return out

    def max_rank(self, slot):
        ranks = self.cfg.get("max_ranks") or [0, 5, 5, 5, 3]
        return int(ranks[slot]) if 0 <= slot < len(ranks) else 0

    def rank(self, slot):
        return (self.m.skill_ranks >> (4 * slot)) & 0xF

    def rank_slots(self):
        """Slots whose '+' shows: a skill point left, rank below its maximum, and the level allows the next
        rank (Q/W/E: rank < (level + 1) // 2; R: levels 6, 11, 16)."""
        m = self.m
        if m.skill_points <= 0:
            return ()
        out = []
        for slot in (1, 2, 3, 4):
            r = self.rank(slot)
            if r >= self.max_rank(slot):
                continue
            if slot == 4 and m.level < 6 + 5 * r:
                continue
            if slot != 4 and r >= (m.level + 1) // 2:
                continue
            out.append(slot)
        return tuple(out)

    def rank_up(self, slot):
        m = self.m
        if slot not in self.rank_slots():
            log.info(f"free play: '+' on slot {slot} refused (level {m.level}, points {m.skill_points}, "
                     f"rank {self.rank(slot)})", self.s)
            return []
        m.skill_ranks = (m.skill_ranks & ~(0xF << (4 * slot))) | ((self.rank(slot) + 1) << (4 * slot))
        m.skill_points -= 1
        m.hud_refresh += 1
        m.sequence += 1
        log.info(f"free play: slot {slot} to rank {self.rank(slot)}, {m.skill_points} points left", self.s)
        return [(f"skill slot {slot} rank {self.rank(slot)}", m.champion_bundle(time.time()))]

    def _level_up(self):
        m = self.m
        if self.s.match is not m:
            return False
        if m.level >= int(self.cfg.get("max_level", 20)):
            return False
        m.level += 1
        m.skill_points += 1
        m.hud_refresh += 1
        m.sequence += 1
        log.info(f"free play: level {m.level} ({m.skill_points} skill points)", self.s)
        self.s.send(f"level {m.level}", m.champion_bundle(time.time()))
        return True

    # ---- objective text (the tour's labels) ------------------------------------------------------
    def _objectives(self):
        return [("objective list (0x2034)", M.objective_list(
            [tutorial1.objective_one("Free play")],
            [M.objective_category(1, "Free play", state=tutorial1.OBJECTIVE_CATEGORY_SHOW)]))]

    def _text(self, text):
        self.s.send(f"objective: {text}", M.objective_update(tutorial1.objective_one(text)))

    # ---- training drone ----------------------------------------------------------------------
    def _drone(self):
        """A drone that takes hits but never dies (health back to full on every hit: Match damage hook)."""
        from .world import Entity
        m, c = self.m, self.cfg
        sx, sy, sz = m.mover.spawn[4:7]
        dx, dy = (float(v) for v in (c.get("drone_offset") or [6.0, 0.0]))
        eid = m._next_eid
        m._next_eid += 1
        cls = int(c.get("drone_class", 0x40000A5C))
        hp = int(c.get("drone_health", 1000))
        ent = Entity(eid, "Training Drone", cls, (sx + dx, sy + dy, sz), 3.1416, int(c.get("drone_team", 2)),
                     health=hp, attackable=True)
        ent.invulnerable = True
        ent.no_fog = True
        m.entities[eid] = ent
        log.info(f"free play: training drone {eid:#x} ({cls:#x}) at ({sx + dx:.1f}, {sy + dy:.1f})", self.s)
        return [("spawn Training Drone", m.entity_bundle(ent, time.time())),
                ("Training Drone vitals (0x42)", M.vitals(eid, [(hp, hp)]))]

    # ---- animation tour ----------------------------------------------------------------------
    def _tour_start(self):
        m = self.m
        if self.s.match is not m:
            return
        champ = next((c for c in (self.s.server.roster or []) if int(c.get("variant", 0)) == m.champion), None)
        anims = getattr(m, "free_anims", None) or []
        if not anims:
            self._text("No animations found for this champion")
            log.info(f"free play: no graph events found for {m.champion:#x} ({champ and champ.get('name')})", self.s)
            return
        gap = float(self.cfg.get("tour_interval", 4.0))
        getup = next((i for i, n in anims if n == "CbtState_GetUp"), None)
        log.info(f"free play: animation tour of {len(anims)} graph events, every {gap:g} s", self.s)
        for i, (ident, name) in enumerate(anims):
            def show(i=i, ident=ident, name=name):
                if self.s.match is not m:
                    return
                label = f"Animation {i + 1}/{len(anims)}: {name}"
                log.info(f"free play: {label} ({ident:#x})", self.s)
                self._text(label)
                self.s._run_scripts(m, M.CHAMPION_AGENT_ID, [tutorial1.RAISE_EVENT_KEY], f"tour {name}",
                                    [(tutorial1.RAISE_EVENT_VAR, KIND_ENUM, ident)])
                if getup and any(w in name for w in ("Dead", "Death", "Knock", "Incapac", "Cower", "Stun")):
                    # a fall or a death is followed by the get-up, or he stays down
                    self.s.later(gap * 0.6, lambda: self.s._run_scripts(
                        m, M.CHAMPION_AGENT_ID, [tutorial1.RAISE_EVENT_KEY], "tour get up",
                        [(tutorial1.RAISE_EVENT_VAR, KIND_ENUM, getup)]) if self.s.match is m else None, m.group)
            self.s.later(gap * i, show, m.group)
        self.s.later(gap * len(anims) + 0.5, lambda: self._text("Animation tour finished"), m.group)
