"""One match's world: entities, movement, combat, and the bridge to the script runtime.

Nothing here knows a champion, a skill or a map. A skill cast looks up the caster's kit (catalog), loads the
skill's server script (0x34) and runs it; the script's actions arrive as calls on CastWorld below (face, run a
scriptlet, start a cooldown, spend Will, damage, launch a missile). Missiles are objects of their own class
whose server scripts come from the class's template (property 0x8E).
"""
import copy
import math
import struct
import time
import traceback

from . import combat as CB
from . import messages as M
from . import records
from . import script_model as V
from . import script_runtime as R
from . import prewarm
from . import scriptlet_orders
from . import skill_slots
from .wire import KIND_ARRAY, KIND_BOOL, KIND_DID, KIND_ENUM, KIND_F32, KIND_IID, KIND_INT, KIND_TABLE, KIND_U32
from .wire import pack_property

ENTITY_BASE_ID = 0x0200000000000100
RANK_ARRAY_PROPERTY = 0x100000AF       # champion: skill rank per slot (array of 0x10000167 ints)
RANK_ELEMENT_PROPERTY = 0x10000167
SKILL_RANKS_PROPERTY = 0x100006C1      # patched client: per slot nibble, 0 = may be ranked now
PROP_MOVE_SPEED = 0x100005E4
PROP_HIDDEN = 0x90F
PROP_ON_MAP = 0x2A1                  # bool: drawn and on the minimap (the minimap note needs it true)
PROP_MAP_CATEGORY = 0x100004DA       # enum: minimap note category (0 = no note; 9 MINION, 2 champion)
LANDBLOCK = 160.0
STAT_HEALTH, STAT_ATTACK_DAMAGE, STAT_ATTACK_SPEED, STAT_MOVE_SPEED = 0x10000426, 0x10000B76, 0x100006FE, 0x100005E4
STAT_WILL, STAT_HEALTH_REGEN, STAT_WILL_REGEN = 0x10000432, 0x10000140, 0x10000484   # champion stats records
NOT_SENT_STATS = {STAT_MOVE_SPEED}         # sent on its own ([ics] move_speed: the walk animation cap)
ATTR_ATTACKS_PER_SECOND = 0x100005FE         # read by the basic attack scripts
PROP_MAY_SHOP, PROP_ITEM_COUNT = 0x10000A23, 0x10000CD6
PROP_UNIT_FLAGS = 0x1000019D                       # unit flags: the attack check needs one in 0x555959
# CreateGameComponents (full-entities-engine.md 4, C): the client builds an entity's vitals (+0x80), floaty (+0x90) and
# status icon (+0xC0) components only if its PerceivedType 0x1000019D & this mask at construction
CREATE_GAME_COMPONENTS = 0x7F59FB
PROP_VISION_RADIUS = 0x10000133                     # f32: a fog-of-war vision source's radius
PROP_SECONDARY_VITAL = 0x1000000C     # enum: the champion's second vital (5 = Will), read once at creation
PROP_VITAL_NOTICES = 0x100000CE       # bool: the vitals' HUD notices on (listener 0xaafcd0)
EVENT_SKILL_USED, EVENT_SKILL_INTERRUPT = 0x1000001D, 0x10000009   # ScriptEvents for 0x20C9
PROP_CAMERA_YAW = 0x1000011E          # f32 degrees: the camera's yaw while it follows this champion
STOLEN_SLOTS = (7, 8)                                # D, F
STOLEN_PROPERTIES = {7: 0x100008F0, 8: 0x100008F1}   # champion: the Stolen Power skill tables
RECALL_SLOT, RECALL_PROPERTY = 6, 0x100008E4          # slot 6 = recall (full-combat-skills.md S3.5, C)
BONUS_SLOT, BONUS_PROPERTY = 9, 0x100008F2            # slot 9 = bonus (a used pad's skill)
ITEM_SKILL_PROPERTIES = {10: 0x100008E5, 11: 0x100008E7, 12: 0x100008E9, 13: 0x100008EB, 14: 0x100008ED,
                         15: 0x100008EE}                # item slots 10-15 (full-combat-skills.md S3.5, C)
PROP_TARGETING = 0x1000003D
PROP_COLOUR_OVERRIDE = 0x10000CF0          # team colour override (enum 0x30000230), read before the relative colour
PROP_SIDE = 0x100007A2                       # a layout placement's side (1 = enemy)
MOBILE_CREATION_TYPES = {7}                  # 0x2E001168 (the tutorial's ranged drone): a character
PLACED_CREATION_TYPES = {7, 8}               # client 0x580160: mobility 2 = gets the movement component (placed)


class Entity:
    def __init__(self, eid, name, class_id, pos, heading=0.0, team=0, kind="unit"):
        self.eid, self.name, self.class_id = eid, name, class_id
        self.pos = [float(v) for v in pos]
        self.heading, self.speed, self.move_speed = heading, 0.0, 4.5
        self.dest = None                  # walking towards this point
        self.path = []                    # the next points after dest (a path on the navmesh)
        self.follow = None                # (missiles) homing on this entity
        self.team, self.kind = team, kind
        self.health = self.max_health = None
        self.will = self.max_will = None
        self.alive = True
        self.sequence = 0
        self.module = (1, 1)              # movement module: character replay
        self.kit, self.ranks, self.ready_at = {}, {}, {}
        self.skill_insts = {}             # slot -> its running skill script
        self.attack_target, self.next_attack = None, 0.0
        self.extra_props = []
        self.aggro = None                 # unit: chase the champion within this radius (None = [ics] default)
        self.level, self.xp, self.skill_points, self.gold = 1, 0, 0, 0.0
        self.stats = {}                   # stats {stat property: value} (units: their stat block)
        self.base_stats = {}              # champion: {stat: (at level 1, per level)} (its stats record)
        self.item_add, self.item_pct = {}, {}   # bonuses of the items it holds (ics.shop)
        self.amp_add, self.amp_pct = {}, {}     # bonuses of its amplifier set's augments (ics.account, fase3-ie)
        self.inventory = [0] * 6          # artifact DID per shop slot (0 = empty)
        self.stolen = {}                  # slot 7 / 8 -> the Stolen Power's skill table
        self.world_state = 0
        self.scriptlet_keys = None        # keys its scriptlet tables accept (None = not known)
        self.hittable = False             # neutral, yet a target of the champion's effects (the practice targets)
        self.only_slot = None             # only this skill slot hurts it (the practice targets; Director only_skill)
        self.origin_slot = None           # an entity a skill spawned: that skill's slot (its scripts' damage)
        # what the client was last told ([ics] object_update_mode "delta", World.delta): {id: packed entry} (None = not
        # created on the client), the motion key and its stamp, the first full bundle's time, sent in the world or not
        self.client_props = self.client_motion = self.client_created_at = None
        self.client_motion_at, self.client_full_in_world = 0.0, False

    def __repr__(self):
        return self.name

    def distance_to(self, other):
        p = other.pos if isinstance(other, Entity) else other
        return math.hypot(p[0] - self.pos[0], p[1] - self.pos[1])


class World:
    def __init__(self, data, cfg, encounter, spawn, send, schedule, log):
        self.data, self.cfg, self.ic = data, cfg, cfg["ics"]
        self.encounter = encounter
        self.origin = tuple(spawn[:4])     # region, landblock x, landblock y, cell
        self.send, self.schedule, self.log = send, schedule, log
        scriptlet_orders.install(self)     # one 0x8D per object and moment, held runs ride along ([ics] scriptlet_orders)
        self.entities = {}
        self._next = ENTITY_BASE_ID
        self.in_world = False
        self.scriptlet_runs = 0
        self.live_scriptlets = {}          # (entity id, scriptlet key) -> instance number of its last run
        self.champion = None
        self.ground_z = 0.0
        self.scripts, self.statuses = {}, {}   # script instances / status effects per entity (script_runtime)
        self._rank_refresh = 1             # toggled 1 / 2 in the rank property: forces the HUD to re-read it
        self.scene_insts = {}              # cinematic -> its scenes' running script instances
        self.nav = None                    # the map's walkable grid (ics.navmesh), set by the session
        self.listeners = []                # callables (event, **details): "killed", "cast", "ranked" (ics.director)
        self.rank_filter = None            # callable(slot) -> may this slot be ranked now (the encounter's flow)
        self.cast_filter = None            # callable(slot) -> may the champion use this slot now (the flow's HUD)

    def fog(self):
        """Units out of the champion's sight are hidden (0x90F) and shown again when seen: the client's fog only
        darkens the ground, it does not hide network objects (movement-collision-fog-map.md 2; the earlier server
        did the same, fase3-by). Sight: [ics] fog_vision_radius and a clear line on the navmesh."""
        ch = self.champion
        radius = float(self.ic.get("fog_vision_radius", 0) or 0)
        if not ch or radius <= 0:
            return []
        # 2026-10-23 17:40 (tester: the drones give no vision; fog-vision-runtime.md): every allied unit / structure
        # with a vision radius (MatchUnit.vision) is a source too, not only the champion ([ics] fog_allied_vision)
        sources = [(ch, radius)] if ch.alive else []
        if self.ic.get("fog_allied_vision", True):
            for a in self.entities.values():
                mu = getattr(a, "match_unit", None)
                r = float(getattr(mu, "vision", 0) or 0)
                if a.alive and a.team == ch.team and a.kind in ("unit", "structure") and r > 0:
                    sources.append((a, r))
                elif getattr(a, "bot", False) and a.alive and a.team == ch.team:
                    sources.append((a, radius))      # an allied bot champion sees as far as the player
        out = []
        for e in self.entities.values():
            if e.kind not in ("unit", "champion") or e is ch or not e.alive or not e.team or e.team == ch.team:
                continue
            # 2026-10-25 16:12 (tester's video 5:45: Crime Alley's nook camp looked empty; it sits in a pit the navmesh
            # line from the street never reaches): neutral jungle units need range only ([ics] fog_neutral_by_range)
            by_range = e.team not in (1, 2) and self.ic.get("fog_neutral_by_range", True)
            # 2026-10-29 11:00 (tester: the turrets attack but give no vision; nothing near them shows unless the
            # champion or a minion is close): a structure stands on a navmesh hole, so the line from its centre was
            # never clear; structures see by range only ([ics] fog_structure_by_range)
            struct_range = self.ic.get("fog_structure_by_range", True)
            # tester report 2026-10-29 19:55 ("sometimes the enemy champion inside our vision range is not drawn until it
            # attacks me"; ca-ring-fog-bundles.md 3): the sight line ran on the match's navmesh copy, where every
            # structure (match_structure_radius, 3.2 m squares in the middle of the lane), liftable vehicle and closed
            # gate is a blocked square, so an enemy behind our own lane turret stayed hidden while the client drew lit
            # ground around it (its fog ignores turrets). Only the navmesh's own holes block the line ([ics]
            # fog_line_through_objects; false = objects block it, as before)
            through = bool(self.ic.get("fog_line_through_objects", True))
            # tester report 2026-10-30 15:30 (ca-fog-minimap-category.md 2): the client lights a full circle around
            # every allied source (vision_through_blockers), so the navmesh line is not needed inside it ([ics]
            # fog_sight_line)
            line = self._fog_sight_line()
            seen = any(e.distance_to(src) <= r and (self.nav is None or not line or by_range
                                                    or e.distance_to(src) <= 3.0
                                                    or (struct_range and src.kind == "structure")
                                                    or self.nav.line_clear(src.pos, e.pos, through_objects=through))
                       for src, r in sources)
            stealthed = False
            hook = getattr(self, "visibility", None)
            if seen and e.kind == "champion" and hook is not None and not hook(e, ch):
                seen, stealthed = False, True        # an enemy bot inside a stealth strip (Match.visible_to)
            off_map = (not seen) and self._fog_off_minimap(e)
            if seen == (not getattr(e, "hidden", False)) and off_map == bool(getattr(e, "off_map", False)):
                continue
            if e.kind == "champion" and seen == bool(getattr(e, "hidden", False)) and self.ic.get("fog_log_champions", True):
                self._fog_log(e, seen, sources, line, stealthed)
            e.hidden = not seen
            e.extra_props = [p for p in e.extra_props if p[0] != PROP_HIDDEN] + [(PROP_HIDDEN, KIND_BOOL, 1 if e.hidden else 0)]
            if off_map or getattr(e, "off_map", False):
                e.off_map = off_map
                if str(self.ic.get("fog_minimap_lever", "category") or "on_map").lower() == "category":
                    # tester report 2026-10-30 15:30 (the enemies stayed on the minimap with fase3-io's 0x2A1 = false;
                    # ca-fog-minimap-category.md 1, C 0xAAA670 rewrites 0x2A1 = true about every 0.4 s): the note's
                    # category 0x100004DA = 0 while out of sight (watcher 0xA6A8E0 -> remove 0xA4C030), the template's
                    # category in sight (-> add 0xA4BD80, which needs the client's own 0x2A1 true)
                    cat = 0 if off_map else self._fog_map_category(e)
                    e.extra_props = [p for p in e.extra_props if p[0] != PROP_MAP_CATEGORY] + [(PROP_MAP_CATEGORY,
                                                                                                 KIND_ENUM, cat)]
                else:
                    # tester report 2026-10-29 21:10 (78.png, the original's minimap: enemy minions and champions show
                    # only inside our team's vision, super minions always; ca-fog-minimap-ring.md 3): 0x2A1 false while
                    # out of sight ([ics] fog_minimap_lever "on_map", fase3-io)
                    e.extra_props = [p for p in e.extra_props if p[0] != PROP_ON_MAP] + [(PROP_ON_MAP, KIND_BOOL,
                                                                                             0 if off_map else 1)]
            out.append(e)
        return out

    def _fog_sight_line(self):
        """[ics] fog_sight_line: True / False, or "auto" = the navmesh line only when vision_through_blockers is off."""
        v = self.ic.get("fog_sight_line", "auto")
        if isinstance(v, str):
            if v.strip().lower() == "auto":
                return not self.ic.get("vision_through_blockers", True)
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    def _fog_log(self, e, seen, sources, line, stealthed):
        """[ics] fog_log_champions: one server.log line per fog change of an enemy champion: where it is, the nearest
        allied source (distance, its radius, whether the navmesh line is clear) and why."""
        near = None
        for src, r in sources:
            d = e.distance_to(src)
            if near is None or d - r < near[1] - near[2]:
                near = (src, d, r)
        where = f"({e.pos[0]:.1f}, {e.pos[1]:.1f})"
        if near is None:
            self.log(f"fog: {e.name} at {where} {'shown' if seen else 'hidden'} (no allied vision source)")
            return
        src, d, r = near
        clear = None if self.nav is None else self.nav.line_clear(src.pos, e.pos, through_objects=True)
        why = ("stealth strip" if stealthed else "in range" if seen else
               "out of range" if d > r else "line blocked" if line and clear is False else "?")
        self.log(f"fog: {e.name} at {where} {'shown' if seen else 'hidden'} ({why}); nearest source {src.name} at "
                 f"({src.pos[0]:.1f}, {src.pos[1]:.1f}), {d:.1f} m, radius {r:g}, navmesh line "
                 f"{'clear' if clear else 'blocked' if clear is False else '-'}")

    def _fog_template_value(self, e, prop, cache_name):
        """A property's values OR-ed (int) from the entity's class template (UnitData; 0 when there is no data)."""
        cache = self.__dict__.setdefault(cache_name, {})
        if e.class_id not in cache:
            cache[e.class_id] = None
            try:
                from .match.unitdata import UnitData
                ud = self.__dict__.setdefault("_unitdata", UnitData(self.data))
                vals = [int(v) for v in ud.template(e.class_id).get(prop, [])]
                cache[e.class_id] = vals[0] if vals else None
                if prop == 0x1000019D:
                    acc = 0
                    for v in vals:
                        acc |= v
                    cache[e.class_id] = acc
            except Exception:                            # noqa: BLE001 - no data (tests without packs)
                cache[e.class_id] = None
        return cache[e.class_id]

    def _fog_map_category(self, e):
        """The minimap note category an enemy gets back in sight: its template's 0x100004DA, else [ics]
        fog_minimap_categories by kind (9 MINION, 2 champion)."""
        cat = self._fog_template_value(e, PROP_MAP_CATEGORY, "_fog_tpl_category")
        if not cat:
            cat = int((self.ic.get("fog_minimap_categories") or {}).get(e.kind, 9 if e.kind == "unit" else 2) or 0)
        return int(cat)

    def _fog_off_minimap(self, e):
        """An enemy lane unit / champion out of sight leaves the minimap ([ics] fog_hide_minimap), except a super
        minion: unit flags 0x1000019D with a bit of [ics] fog_minimap_always_flags (0x400000 = elite: the super
        minions 0x40000C9C / 0x40000C9B carry 0x410000), from its bundle or its template."""
        if not self.ic.get("fog_hide_minimap", True) or e.team not in (1, 2):
            return False
        always = int(str(self.ic.get("fog_minimap_always_flags", 0x400000) or 0), 0)
        if always and e.kind == "unit":
            flags = next((int(p[2]) for p in e.extra_props if p[0] == 0x1000019D), 0)
            if not flags & always:
                flags = self._fog_template_value(e, 0x1000019D, "_fog_tpl_flags") or 0
            if flags & always:
                return False
        return True

    def snap_to_ground(self, ent):
        """2026-10-23 18:40 (tester: the champions appear and walk above the ground): a walker's height is the
        navmesh's at its spot (the clicked point's z is the picked geometry's, up to 0.6 m above the floor);
        [ics] ground_from_navmesh."""
        if self.nav is None or ent.kind not in ("champion", "unit") or not self.ic.get("ground_from_navmesh", True):
            return
        z = self.nav.height(ent.pos[0], ent.pos[1])
        if z is not None:
            ent.pos[2] = z
            if ent.dest is not None and len(ent.dest) > 2:
                gz = self.nav.height(ent.dest[0], ent.dest[1])
                if gz is not None:
                    ent.dest[2] = gz

    def _ground_fix_log(self, ent, before, where):
        """2026-10-30 (agl-floor-raider-pad-pct-prow.md 1): a champion found off the navmesh's height is logged (at most
        every 5 s) with the path that found it, so the next run names the code that lifted it."""
        now = time.time()
        if now - getattr(self, "_ground_fix_at", 0.0) >= 5.0:
            self._ground_fix_at = now
            self.log(f"{ent.name}: z {before:.3f} off the navmesh ({ent.pos[2]:.3f}) at ({ent.pos[0]:.1f}, "
                     f"{ent.pos[1]:.1f}), put back ({where})")

    def walk_to(self, ent, point):
        """Walk along a path on the map's navmesh (movement-collision-fog-map.md: the original server pathed; the
        client sends only the clicked point). False when no path exists (the order is ignored). Without a navmesh:
        a straight line, as before."""
        z = point[2] if len(point) > 2 else ent.pos[2]
        if not ent.alive and ent.kind in ("champion", "unit") and self.ic.get("dead_hold_still", True):
            # tester report 2026-10-29 12:45 (run 12:16:14.9: two move orders reached the server 65-75 ms after AGL's
            # death bundle, were accepted and World.tick walked the dead body while it fell; docs/re-notes/
            # unit-death-slide-levelup.md 2): a dead champion / unit takes no move ([ics] dead_hold_still)
            self.log(f"{ent.name}: move refused (dead)")
            return False
        if self._held(ent) or self._disabled(ent):
            # 2026-10-22 (full-combat-skills.md, client-movement.md 3): the client does not hold move orders while
            # stunned / rooted; the server ignores them (and dashes / knockbacks own the movement)
            self.log(f"{ent.name}: move refused (crowd control)")
            return False
        if self.ic.get("cast_holds_movement", True) and self.casting_skill(ent):
            # 2026-10-26 (tester: Bat Scream cast while moving slides the champion that way; it should stay on the spot):
            # a skill in its cast (not the basic attack) holds the champion; the last order runs when the cast ends
            ent.pending_move = tuple(point)
            return True
        if self.ic.get("basic_attack_holds_movement", True) and self._basic_attack_animating(ent):
            # 2026-11-04 (tester report 2026-11-04 00:56: he walks before the basic attack's animation ends; the graph
            # data: the attack states (Ranged_Basic_Left 104 ...) have no Lua early-out on movement, their Cosmetic tail
            # has onCosmeticEarlyOut): a move ordered while the graph is in the basic attack's state waits for its exit
            # (code 2, the clip's basicattack_to_basicattack), then runs ([ics] basic_attack_holds_movement, P)
            ent.pending_move = tuple(point)
            return True
        if self.nav is None or not self.ic.get("pathing", True):
            ent.dest, ent.path = [point[0], point[1], z], []
            return True
        pts = self.nav.path(ent.pos[:2], point[:2])
        if not pts:
            self.log(f"{ent.name}: no path to ({point[0]:.1f}, {point[1]:.1f})")
            return False
        if self.ic.get("ground_path_from_navmesh", True) and self.ic.get("ground_from_navmesh", True) and ent.kind in (
                "champion", "unit"):
            # 2026-10-30 (tester report 14:51 video: "AGL is very far off the floor"; traffic: the champion's bundles
            # carried z 200.13 -> 201.52 where the navmesh is 200.08 / 200.15, each one the client's last click height,
            # which the client picks on a plane at the champion's own drawn height, so it crept up; agl-floor-raider-pad-
            # pct-prow.md 1): every corner of the path takes the navmesh's height, never the clicked point's
            ent.path = [[x, y, self.nav.height(x, y) or z] for x, y in pts]
        else:
            ent.path = [[x, y, z] for x, y in pts]
        ent.dest = ent.path.pop(0)
        return True

    def emit(self, event, **details):
        for fn in list(self.listeners):
            try:
                fn(event, **details)
            except Exception:              # noqa: BLE001 - a listener must never stop the match
                self.log(f"listener error on {event}\n{traceback.format_exc()}")

    # ---- positions ----------------------------------------------------------------------------
    def wire_position(self, ent):
        """(region, landblock x, landblock y, cell, x, y, z): world coordinates are relative to the spawn
        landblock; the wire wants the landblock that holds the point."""
        region, lbx, lby, cell = self.origin
        cell = getattr(ent, "cell", cell)
        x, y, z = ent.pos
        dx, dy = math.floor(x / LANDBLOCK), math.floor(y / LANDBLOCK)
        return region, lbx + dx, lby + dy, cell, x - dx * LANDBLOCK, y - dy * LANDBLOCK, z

    def from_wire(self, p):
        """Client position (region, lbx, lby, x, y, z) -> world coordinates, or None (other region)."""
        if not p or p[0] != self.origin[0]:
            return None
        x = (p[1] - self.origin[1]) * LANDBLOCK + p[3]
        y = (p[2] - self.origin[2]) * LANDBLOCK + p[4]
        z = p[5]
        if self.ground_z and abs(z - self.ground_z) < 3.0:
            z = self.ground_z
        return [x, y, z]

    # ---- objects ------------------------------------------------------------------------------
    def new_id(self):
        eid, self._next = self._next, self._next + 1
        return eid

    def add(self, ent):
        self.entities[ent.eid] = ent
        return ent

    def properties(self, ent):
        if ent is self.champion:
            name, icon = self.data.champion_name(ent.class_id)
            props = M.champion_properties(name, ent.team, icon, ent.level, ent.xp, ent.skill_points,
                                          move_speed=ent.move_speed, currency=ent.gold, alive=ent.alive)
            ranks = [ent.ranks.get(slot, 0) for slot in range(6)]
            # patched client (icserver/patcher.py): per slot nibble, 0 = the "+" may be clicked now
            locked = sum((0 if self.rankable(slot) else 1) << (4 * slot) for slot in range(7))
            props += [(RANK_ARRAY_PROPERTY, KIND_ARRAY, [(RANK_ELEMENT_PROPERTY, KIND_INT, r) for r in ranks]),
                      (SKILL_RANKS_PROPERTY, KIND_INT, locked | (self._rank_refresh << 28))]
            props += self.stat_properties(ent)
            yaw = self.camera_yaw()
            if yaw is not None:
                props.append((PROP_CAMERA_YAW, KIND_F32, yaw))
            tables = self.champion_tables(ent)
            if tables:
                # 2026-10-23 20:20 (skill-animations-and-skins.md 5.4, P: 56 skill FX keys resolve only through the
                # world state's tables, e.g. Atomic Green Lantern's passive): instance property 0x7D2 = the template's
                # table list + the world state's ([ics] champion_script_tables)
                props.append((0x7D2, KIND_ARRAY, [(0x462, KIND_DID, t) for t in tables]))
            vital = int(getattr(ent, "resource_vital", 0) or self.ic.get("champion_secondary_vital", 5) or 0)
            if vital:
                # 2026-10-23 16:20 (tester: the buttons never dim without Will; docs/re-notes/skill-button-will.md):
                # the vitals attach (0x972940) reads the secondary vital type once, at creation; without it the
                # client keeps only Health and CanActivate compares the cost with Health. Will = 5
                props.append((PROP_SECONDARY_VITAL, KIND_ENUM, vital))
            vision = float(self.ic.get("champion_vision_radius", 0) or 0)
            if vision > 0:
                # the fog of war's vision source radius (movement-collision-fog-map.md 2: 0x10000133, default -1)
                props.append((PROP_VISION_RADIUS, KIND_F32, vision))
            props += [(STOLEN_PROPERTIES[slot], KIND_TABLE, block) for slot, block in sorted(ent.stolen.items())]
            props += skill_slots.properties(ent)          # swapped / overridden buttons (2026-11-02, [ics] slot_tables)
            if getattr(ent, "recall_block", None):
                props.append((RECALL_PROPERTY, KIND_TABLE, ent.recall_block))
            for slot, block in sorted((getattr(ent, "item_blocks", None) or {}).items()):
                if slot in ITEM_SKILL_PROPERTIES and block:
                    props.append((ITEM_SKILL_PROPERTIES[slot], KIND_TABLE, block))
            if getattr(ent, "bonus_block", None):
                props.append((BONUS_PROPERTY, KIND_TABLE, ent.bonus_block))
            icon = self.map_icon(ent.class_id) if self.ic.get("champion_map_icon", True) else 0
            if icon:
                props.append((0x10000083, KIND_DID, icon))     # its own minimap icon (map_icon)
            # the shop (shop-items-inventory.md 3.2): 0x10000A23 = may shop while alive; 0x10000CD6 items held
            props += [(PROP_MAY_SHOP, KIND_BOOL, 1 if self.ic.get("shop_anywhere", True) else 0),
                      (PROP_ITEM_COUNT, KIND_INT, sum(1 for d in ent.inventory if d))]
        elif ent.kind == "champion" and getattr(ent, "bot", False):
            props = self.bot_properties(ent)
        elif ent.kind == "unit":
            # wire_team: the team the client sees, when it differs from the server's (a match's neutral camp unit, [ics]
            # match_camp_wire_team, 2026-10-28 15:00 tester report; camps-colour-bar-positions.md 1)
            wire = getattr(ent, "wire_team", None)
            props = M.creature_properties(ent.team if wire is None else wire, ent.alive)
        else:
            props = []
        return props + list(ent.extra_props)

    # ---- bot champions (docs/re-notes/bot-champions.md) ------------------------------------------------------------
    def create_bot_champion(self, variant, team, name, player_iid, stolen=(), pos=None):
        """2026-10-25 (bot-champions.md 3.1, C path: a bot is the same object as the local champion without the
        player link): a champion agent with its own world id, stats, kit, Stolen Powers and running skill scripts."""
        ic = self.ic
        where = pos or getattr(self, "spawn_pos", None) or (self.champion.pos if self.champion else [0.0, 0.0, 0.0])
        ent = Entity(self.new_id(), name or self.data.champion_name(variant)[0], variant, list(where), team=team,
                     kind="champion")
        ent.bot, ent.player_iid = True, int(player_iid or 0)
        ent.move_speed = float(ic["move_speed"])
        ent.health = ent.max_health = int(ic["health"])
        ent.will = ent.max_will = int(ic["will"])
        if ic.get("champion_stats_from_data", True):
            ent.base_stats = self.data.champion_stats(variant)
            self.recompute_stats(ent, refill=True)
        if ic.get("champion_resource_from_data", True):
            ent.resource_vital = self.data.resource_vital(variant) or int(ic.get("champion_secondary_vital", 5) or 5)
            if ent.resource_vital != 5:
                ent.will = 0.0
        ent.kit = self.data.kit(variant)
        if ic.get("match_start_ranks") is not None:
            start = {int(k): int(v) for k, v in (ic.get("match_start_ranks") or {}).items()}
            ent.ranks = {slot: start.get(slot, 0) for slot in ent.kit}
        else:
            ent.ranks = {slot: int(ic["skill_rank"]) for slot in ent.kit}
        ent.skill_points = int(ic.get("match_start_skill_points", 1))
        saved = getattr(self, "stolen_choice", None)
        self.stolen_choice = [p for p in (stolen or ()) if p]
        try:
            self.give_stolen_powers(ent)
        finally:
            self.stolen_choice = saved
        ent.world_state = self.data.champion_world_state(variant)
        ent.scriptlet_keys = None              # a champion is not filtered (tables from several records)
        ent.client_vitals = True
        self.add(ent)
        self.start_kit(ent)
        self.champion_init_event(ent)
        self.log(f"bot champion {ent.name} ({variant:#x}) team {team}, id {ent.eid:#x}")
        prewarm.champion(self, ent)        # its statuses read now, not at their first hit ([ics] prewarm_statuses)
        return ent

    def bot_properties(self, ent):
        """bot-champions.md 1.2: the local champion's list with the bot's values and no HUD-only ids, plus the
        targeting / minimap ids its template holds server-side (the client does not read the 0x49 template)."""
        name, icon = self.data.champion_name(ent.class_id)
        props = M.champion_properties(ent.name or name, ent.team, icon, ent.level, ent.xp, 0, move_speed=ent.move_speed,
                                      alive=ent.alive, player_iid=getattr(ent, "player_iid", 0), hud=False)
        props += self.stat_properties(ent)
        tables = self.champion_tables(ent)
        if tables:
            props.append((0x7D2, KIND_ARRAY, [(0x462, KIND_DID, t) for t in tables]))
        vital = int(getattr(ent, "resource_vital", 0) or self.ic.get("champion_secondary_vital", 5) or 0)
        if vital:
            props.append((PROP_SECONDARY_VITAL, KIND_ENUM, vital))
        # 2026-10-26 (deep-scan-animations.md 4, C log: AI: Zod was sent 1.076, his base stat, while he attacked every
        # 0.69 s; the client plays the attack clips at this graph variable): the attack rate the server uses (items,
        # buffs), once ([ics] bot_attack_speed_actual)
        aps = float(ent.stats.get(0x100006FE) or 1.0) or 1.0
        if self.ic.get("bot_attack_speed_actual", True) and "_combat" in self.__dict__:
            aps = float(self.combat.attribute(ent, ATTR_ATTACKS_PER_SECOND) or aps) or aps
        props = [p for p in props if p[0] != 0x100006FE]
        props += [(0x10000AA7, KIND_BOOL, 1), (0x100001C3, KIND_ENUM, 0x28), (0x1000034C, KIND_ENUM, 0x1E),
                  (0x100006FE, KIND_F32, aps)]
        if not any(p[0] == PROP_MAP_CATEGORY for p in ent.extra_props):
            props.append((PROP_MAP_CATEGORY, KIND_ENUM, 2))  # World.fog keeps it in extra_props once it hides the bot
        if not any(p[0] == PROP_ON_MAP for p in ent.extra_props):
            props.append((PROP_ON_MAP, KIND_BOOL, 1))    # World.fog keeps it in extra_props once it hides the bot
        icon = self.map_icon(ent.class_id)
        if icon:
            props.append((0x10000083, KIND_DID, icon))
        return props

    def map_icon(self, cls):
        """2026-10-25 16:12 (tester: every champion's minimap icon showed Batman's face; the bots carried Gaslight
        Batman's 0x13000376): the champion's own minimap icon, its template's 0x10000083 (Blue Beetle 0x13001DC3,
        Sinestro 0x13001F73, ...)."""
        cache = self.__dict__.setdefault("_map_icons", {})
        if cls not in cache:
            from .match.unitdata import UnitData
            ud = self.__dict__.setdefault("_unitdata", UnitData(self.data))
            cache[cls] = int(ud.first(cls, 0x10000083, 0) or 0)
        return cache[cls]

    def bot_late_properties(self, ent):
        """The ids the client stores only on a CHANGE (bot-champions.md 1.2): unit flags 0 -> 8, the status tags,
        and for an ally the fog vision radius 0 -> [ics] bot_vision_radius."""
        if ent.eid not in self.entities:
            return
        self.send(f"{ent.name}: unit flags 0 (0x6)", M.set_property(ent.eid, PROP_UNIT_FLAGS, KIND_U32, 0))
        self.send(f"{ent.name}: unit flags 8 (0x6)", M.set_property(ent.eid, PROP_UNIT_FLAGS, KIND_U32, 8))
        for tag in self.ic.get("unit_targetable_tags", []) or []:
            self.send(f"{ent.name}: tag {tag} (0x6)", M.set_property(ent.eid, int(str(tag), 0), KIND_BOOL, 1))
        if self.champion is not None and ent.team == self.champion.team:
            r = float(self.ic.get("bot_vision_radius", 12.0) or 0)
            if r > 0:
                self.send(f"{ent.name}: vision 0 (0x6)", M.set_property(ent.eid, PROP_VISION_RADIUS, KIND_F32, 0.0))
                self.send(f"{ent.name}: vision {r:g} (0x6)", M.set_property(ent.eid, PROP_VISION_RADIUS, KIND_F32, r))
            self.see_through_blockers(ent)

    def see_through_blockers(self, ent):
        """ca-fog-ring-announcer.md 1 ([ics] vision_through_blockers): an allied fog vision source gets attribute
        0x100008CE = true by a set modifier (op 6). The fog draw 0xAAE0E0 then skips the occluder pass for its circle
        (0x974940(source, 0x100008CE), the attribute the foundries' templates carry); that pass drew the region
        BETWEEN the source and a vision blocker (map statics with 0x7EB 7 / 8, the liftable vehicles' 0x10000623) black."""
        if not self.ic.get("vision_through_blockers", True) or ent is None:
            return
        if ent is not self.champion and ent.eid not in self.entities:
            return
        if getattr(ent, "sees_through_blockers", False) and ent is not self.champion:
            return                                              # the champion's goes again after a full bundle
        ent.sees_through_blockers = True
        attr = 0x100008CE                                       # client-only: the server's combat never reads it
        # 2026-10-29 18:31 (tester: the strip by the fence is still black with the modifier alone; ca-fog-stealth-hover.md 1,
        # C 0x973730): an attribute read returns the default (false) and skips every modifier when the entity has no
        # base value of it (vt+0x60 = 0x970B80 -> 0x58B1C0, the entity's property); champions, turrets and minions have
        # none, so the 0x20F0 modifier never applied. [ics] vision_through_blockers_property: the base value by 0x6
        if self.ic.get("vision_through_blockers_property", True):
            self.send(f"{ent.name}: {attr:#x} = True (0x6)", M.set_property(ent.eid, attr, KIND_BOOL, 1))
            if self.ic.get("vision_through_blockers_in_bundle", True):
                # tester report 2026-10-29 19:55 (the fence strip still black; ca-ring-fog-bundles.md 2, C
                # object-update-bundles.md 0.3): 0x100008CE is net 1 with no template value on champions / minions, so the
                # next full bundle (every tick for a moving champion or minion in "bundle" mode) REMOVED the base value
                # and the attribute read fell back to false. It rides in the object's bundles too; false = 0x6 only
                ent.extra_props = [p for p in ent.extra_props if p[0] != attr] + [(attr, KIND_BOOL, 1)]
        n = CB.Handle("modifier", ent).n
        self.send(f"{ent.name}: modifier {attr:#x} op 6 = True (0x20f0)",
                  M.attribute_modifier_add(ent.eid, attr, 0, n, 6, KIND_BOOL, True))

    def bot_level(self, ent, level):
        """A bot's level-up (bot-champions.md 3.2): stats, the level by 0x6, vitals, a skill point per level."""
        gained = max(0, int(level) - ent.level)
        if not gained:
            return
        ent.level = int(level)
        ent.skill_points += gained
        self.recompute_stats(ent)
        self.send(f"{ent.name}: level {ent.level} (0x6)", M.set_property(ent.eid, 0x10000167, KIND_INT, ent.level))
        if gained and self.ic.get("level_up_scriptlet"):
            self.scriptlet(ent, int(self.ic["level_up_scriptlet"]), f"{ent.name}: _Advancement_LevelUp (0x8d)")
        self.vitals(ent)
        self.emit("bot_level", ent=ent, level=ent.level)

    def apply_facing_lock(self, ent):
        """A held facing lock (CastWorld.lock_facing) while the heading follows a movement: the model's yaw stays on the
        locked target through facing_offset. A lock runs out after [ics] facing_lock_max_seconds or at death."""
        lock = getattr(ent, "facing_lock", None)
        if lock is None:
            return
        if time.time() > lock["until"] or not ent.alive:
            self.drop_facing_lock(ent, "expired")
            return
        t = lock["target"]
        if t is not None and t.alive and abs(t.pos[0] - ent.pos[0]) + abs(t.pos[1] - ent.pos[1]) > 1e-3:
            lock["yaw"] = math.atan2(t.pos[1] - ent.pos[1], t.pos[0] - ent.pos[0])
        off = math.remainder(lock["yaw"] - ent.heading, math.tau)
        ent.facing_offset = off if abs(off) > 1e-3 else None

    def drop_facing_lock(self, ent, why):
        """The lock ends (ReleaseFacing, time limit, death): a standing champion's heading takes the model's yaw."""
        ent.facing_lock = None
        off = getattr(ent, "facing_offset", None)
        if off:
            ent.facing_offset = None
            if ent.dest is None:
                ent.heading = math.remainder(ent.heading + off, math.tau)
            self.update(ent, f"{ent.name}: facing lock {why}")

    def motion_due(self, ent):
        """bot-champions.md 3.5: a bot's movement goes when its velocity changes (start, stop, a new path corner,
        heading > 10 deg) or every 1 s while it moves; True = time to send a state (and it is noted as sent)."""
        key = (None if ent.dest is None else (round(ent.dest[0], 1), round(ent.dest[1], 1)), round(ent.speed, 2))
        last = getattr(ent, "_motion_sent", None)
        now = time.time()
        if (last is not None and last[0] == key and abs(math.remainder(ent.heading - last[1], math.tau)) < 0.175
                and (not ent.speed or now - last[2] < 1.0)):
            return False
        ent._motion_sent = (key, ent.heading, now)
        return True

    def forced_motion_label(self, ent):
        """2026-11-04 (tester report 03:15: the first Heat Vision knockback looked like a teleport; the per-tick motion
        states go unlabelled, so traffic.log never showed them): a label for the state of an entity in a forced movement
        (knockback / dash), None otherwise; the bytes are the same ([ics] log_forced_motion)."""
        c = self.__dict__.get("_combat")
        if not self.ic.get("log_forced_motion", True) or c is None or R._key(ent) not in c.states                 or c.of(ent).motion is None:
            return None
        return (f"{ent.name}: forced movement state ({ent.pos[0]:.2f}, {ent.pos[1]:.2f}) speed {float(ent.speed or 0):.1f}"
                f" heading {math.degrees(ent.heading):.0f}")

    def motion_update(self, ent):
        """A bot's throttled movement (motion_due) as a small state (0x4 with only 0xB0); None = nothing to send."""
        return self.motion_state(ent, getattr(ent, "_motion_sent", (0, 0, None))[2]) if self.motion_due(ent) else None

    def motion_state(self, ent, now=None):
        self.snap_to_ground(ent)
        return M.pvp_movement_state(ent.eid, now or time.time(), position=self.wire_position(ent), heading=ent.heading,
                                    speed=ent.speed, module=ent.module, tele_seq=getattr(ent, "tele_seq", 1),
                                    second_seq=1 if self.in_world else 0, **self.tilt(ent))

    def send_entity(self, ent, label=None):
        """A bot champion's movement goes as a motion-only state ([ics] bot_motion_only), anything else as a bundle.
        Delta mode ([ics] object_update_mode): every object, bots included, goes through World.update."""
        if (getattr(ent, "bot", False) and self.ic.get("bot_motion_only", False) and ent.sequence > 0
                and not self.delta_mode()):
            msg = self.motion_update(ent)
            if msg is not None:
                self.send(label, msg)
            return
        self.update(ent, label)

    def bundle(self, ent, now=None):
        self.snap_to_ground(ent)
        ent.sequence += 1
        # 2026-11-04 ([ics] spawn_state_backdate): a standing spawned skill object's creation state, stamped that much
        # earlier, is placed by the client at once (it replays states >= 0.1 s old, client-movement.md 0)
        now = now or (time.time() - float(ent.__dict__.pop("create_backdate", 0.0) or 0.0))
        props = self.properties(ent)
        if self.delta_mode():
            self.remember_full(ent, props, now)
        return M.create_object(ent.eid, ent.class_id, now, sequence=ent.sequence,
                               position=self.wire_position(ent), heading=ent.heading, speed=ent.speed,
                               tele_seq=getattr(ent, "tele_seq", 1), second_seq=1 if self.in_world else 0,
                               module=ent.module, properties=props,
                               parent=getattr(ent, "attach_parent", None), **self.tilt(ent))

    def send_champion(self, label, full=False):
        """The champion's full state the way the session sends it (with the player object's links), else a bundle.
        2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 12.3 e): in delta mode ([ics]
        object_update_mode) it is an update like any other (a script teleport = a motion state with the new seq A) unless
        full (the respawn, [ics] delta_full_on_life_change); the 0x6 toggles of vital_notices_on follow only a full
        bundle, the only message that removes the ids they set (0x1000019D)."""
        ch = self.champion
        if self.delta_mode() and not full and ch is not None and not self._full_needed(ch):
            self.update(ch, label, force=True)          # force: as the sender's bundle, never held by a carry
            return
        sender = getattr(self, "champion_sender", None)
        if sender is not None:
            sender(label)
        else:
            self.update(ch, label, full=True, toggles=False)
        self.vital_notices_on()

    # ---- object updates (docs/re-notes/object-update-bundles.md 7, 10-13) ------------------------------------------
    def delta_mode(self):
        """[ics] object_update_mode: "delta" = after an object's creation bundle, its updates are motion-only states and
        single property events (World.delta); "bundle" = a full 0x4 per update (fase3-ie)."""
        return str(self.ic.get("object_update_mode", "delta") or "bundle").lower() == "delta"

    def life_full(self):
        """[ics] delta_full_on_life_change: a champion's death and respawn stay full bundles in delta mode."""
        return bool(self.ic.get("delta_full_on_life_change", True))

    def motion_key(self, ent):
        """What the client's movement state of the object holds: wire position (to 0.01 m), heading, speed, the two
        sequence bytes, the movement module and the attach block. A state whose key did not change is not sent."""
        region, lbx, lby, cell, x, y, z = self.wire_position(ent)
        return ((region, lbx, lby, cell, round(x, 2), round(y, 2), round(z, 2)), round(ent.heading, 3),
                round(ent.speed, 2), getattr(ent, "tele_seq", 1), 1 if self.in_world else 0, ent.module,
                getattr(ent, "attach_parent", None), getattr(ent, "pitch", None), getattr(ent, "roll", None),
                getattr(ent, "facing_offset", None), getattr(ent, "vel_pitch", None))

    @staticmethod
    def tilt(ent):
        """2026-10-29 tester report 2026-10-29 17:45 (agl-arm-meteor-vehicle-tilt.md 3): the object's facing pitch / roll
        (rad, set by the match layer, e.g. a thrown vehicle's nose-down) and a facing offset (rad, a held rock's spin)
        for its movement state; {} = none."""
        out = {}
        # 2026-10-29 tester report 21:10 (liftable-aura-lift-throw-break.md 3): vel_pitch = the replayed velocity's pitch
        for k in ("pitch", "roll", "facing_offset", "vel_pitch"):
            v = getattr(ent, k, None)
            if v is not None:
                out[k] = v
        return out

    def remember_full(self, ent, props, now=None):
        """What a full bundle tells the client about the object (World.bundle, Session._objects): its property table,
        packed (the last entry of an id wins, as the client sets them in order), and its movement state."""
        now = time.time() if now is None else now
        ent.client_props = {pid: pack_property(pid, kind, value) for pid, kind, value in props}
        ent.client_motion, ent.client_motion_at = self.motion_key(ent), now
        ent.client_full_in_world = bool(self.in_world)
        if getattr(ent, "client_created_at", None) is None:
            ent.client_created_at = now

    def _full_needed(self, ent):
        """Delta mode: a full bundle still goes to an object the client does not have yet (or that was removed), at the
        first update in the world of one last sent while loading (second_seq 0; [ics] delta_full_after_load, the
        fase3-ie bots' "(in world)" re-send), and for [ics] delta_create_window s after its creation (12.3 c: an event
        that reaches an object whose creation is still running may be dropped)."""
        if getattr(ent, "client_props", None) is None:
            return True
        if self.in_world and not getattr(ent, "client_full_in_world", True) and self.ic.get("delta_full_after_load", True):
            return True
        window = float(self.ic.get("delta_create_window", 0.5) or 0.0)
        born = getattr(ent, "client_created_at", None)
        return window > 0 and born is not None and time.time() - born < window

    def delta(self, ent, label=None, motion=None):
        """2026-10-28 15:00 (tester report 2026-10-28 15:00: animations cut by updates; object-update-bundles.md 3 / 7 /
        12, C): an object the client already has is updated without a 0xBC, whose diff (0x62AFD0) removes every own id of
        network mode 1 / 3 it leaves out: the unit flags, tags, CC flags and order lock ics sets by 0x6 only. Sent, in
        the bundle's order: the 0xB0 state alone (pvp_movement_state, with the attach block) when the motion key changed
        (motion None), when the caller's throttle says so (True) or never (False); one 0x6 per id whose packed value
        differs from what the client was told (an equal value notifies nothing, 0x578DE0); one 0x86 per id of network
        mode 1 / 3 that left the list ([ics] delta_remove_missing; net-0 ids too with delta_remove_net0). Nothing when
        nothing changed. Returns False, sending nothing, when an array / table changed and [ics]
        delta_complex_as_bundle (the caller sends a full bundle: those values have only ever gone in bundles)."""
        sent = ent.client_props
        cur = {}
        for pid, kind, value in self.properties(ent):
            cur[pid] = (kind, value)
        complex_bundle = self.ic.get("delta_complex_as_bundle", True)
        changed = []
        for pid, (kind, value) in cur.items():
            entry = pack_property(pid, kind, value)
            if sent.get(pid) != entry:
                if complex_bundle and kind in (KIND_ARRAY, KIND_TABLE):
                    return False
                changed.append((pid, entry))
        gone = []
        if self.ic.get("delta_remove_missing", True):
            net0 = bool(self.ic.get("delta_remove_net0", False))
            gone = [pid for pid in sent if pid not in cur and (net0 or self.data.network_mode(pid) in (1, 3))]
        msgs, parts = [], []
        if motion is not False:
            self.snap_to_ground(ent)
            key = self.motion_key(ent)
            if motion or key != ent.client_motion:
                now = time.time()
                stamp = now
                back = float(self.ic.get("motion_state_backdate", 0.0) or 0.0)
                if back > 0 and not ent.speed:
                    # a stop / turn state stamped up to `back` s earlier, never before the previous state (P, 7)
                    stamp = max(float(getattr(ent, "client_motion_at", 0.0) or 0.0) + 0.001, now - back)
                msgs.append(M.pvp_movement_state(ent.eid, stamp, position=self.wire_position(ent), heading=ent.heading,
                                                 speed=ent.speed, module=ent.module,
                                                 tele_seq=getattr(ent, "tele_seq", 1),
                                                 second_seq=1 if self.in_world else 0,
                                                 parent=getattr(ent, "attach_parent", None), **self.tilt(ent)))
                ent.client_motion, ent.client_motion_at = key, stamp
                parts.append("0xb0")
        for pid, entry in changed:
            msgs.append(M.set_property_entry(ent.eid, entry))
            sent[pid] = entry
        for pid in gone:
            msgs.append(M.remove_property(ent.eid, pid))
            sent.pop(pid, None)
        if changed:
            parts.append(f"0x6 x{len(changed)}")
        if gone:
            parts.append("0x86 " + " ".join(f"{p:#x}" for p in gone))
        if msgs and not label and parts and parts[0] == "0xb0":
            label = self.forced_motion_label(ent)
        if msgs:
            self.send(f"{label} [delta: {', '.join(parts)}]" if label else None, b"".join(msgs))
        elif label:
            self.log(f"{label}: nothing changed (delta)")
        return True

    def resync(self, ent):
        """2026-10-28 15:00 (same report; object-update-bundles.md 12.3 c): delta mode's idle refresh, in place of the
        idle full bundle ([ics] delta_resync_seconds): the object's movement state (the client drops one that did not
        change, 0x609C70) and each listed property by 0x6 (an equal value notifies nothing, 0x578DE0); arrays / tables
        only when they may go by 0x6 (delta_complex_as_bundle false). Never a 0xBC, so nothing is removed."""
        if ent is None or getattr(ent, "client_props", None) is None:
            return False
        self.snap_to_ground(ent)
        now = time.time()
        msgs = [M.pvp_movement_state(ent.eid, now, position=self.wire_position(ent), heading=ent.heading,
                                     speed=ent.speed, module=ent.module, tele_seq=getattr(ent, "tele_seq", 1),
                                     second_seq=1 if self.in_world else 0, parent=getattr(ent, "attach_parent", None),
                                     **self.tilt(ent))]
        ent.client_motion, ent.client_motion_at = self.motion_key(ent), now
        complex_ok = not self.ic.get("delta_complex_as_bundle", True)
        for pid, kind, value in self.properties(ent):
            if kind in (KIND_ARRAY, KIND_TABLE) and not complex_ok:
                continue
            entry = pack_property(pid, kind, value)
            msgs.append(M.set_property_entry(ent.eid, entry))
            ent.client_props[pid] = entry
        self.send(None, b"".join(msgs))
        return True

    def champion_init_event(self, ent):
        """2026-10-23 18:00 (champion-kits-status.md 4: Arcane Green Lantern's passive spawns his Lantern on
        0x10000088, so his W / E did nothing): the init event match units get, raised on the champion's scripts too
        ([ics] champion_init_event, 0 = not)."""
        ev = int(self.ic.get("champion_init_event", 0x10000088) or 0)
        if ev and ent is not None:
            try:
                self.raise_event(ent, ev)
            except Exception:                              # noqa: BLE001
                self.log(f"{ent.name}: init event {ev:#x} failed\n{traceback.format_exc()}")

    def mirror_skill_scripts(self):
        """2026-10-23 22:10 (tester: still no skill animations; diag --scripts: every 0x8D of Atomic Green Lantern was
        accepted, result 0; skill-animations-and-skins.md 3.1 / 5.8): the client plays a skill's visuals from its own
        copy of the skill script (RunScriptlet / StartScriptlet / RunFx / RaiseGraphEvent client halves, local
        originator), which only the server creates (0x200F, the same form as status effects) and 0x20C9 drives. Each
        kit slot's script goes to the champion's effects component once the client has it ([ics]
        skill_script_mirror; P, the variable store is sent empty)."""
        ch = self.champion
        if ch is None or not self.ic.get("skill_script_mirror", True):
            return
        sent = getattr(ch, "mirrored_scripts", set())
        for slot in sorted(ch.kit):
            skill = ch.kit.get(slot)
            inst = ch.skill_insts.get(slot)
            if not skill or not skill.script or inst is None or skill.script in sent:
                continue
            sent.add(skill.script)
            self.send(f"{ch.name}: client copy of {skill.name} {skill.script:#x} (0x200f)",
                      M.effect_add(ch.eid, inst.guid, skill.script))
        ch.mirrored_scripts = sent

    def dress_spawned(self, ent):
        """2026-10-23 23:40 (tester: no crater for Scorched Earth, no arm for Grab, no marker for Meltdown;
        skill-second-stages.md 4): a missile / spawned skill object gets its world state, its scriptlet keys and the
        0x7D2 table list (class + world state, as the champion's) so its own effect keys resolve ([ics]
        spawned_object_tables)."""
        if not self.ic.get("spawned_object_tables", True):
            return
        ws = ent.world_state or self.data.champion_world_state(ent.class_id)
        if not ws:
            return
        ent.world_state = ws
        ent.scriptlet_keys = self.data.scriptlets(ent.class_id, ws, getattr(ent, "templates", []) or [])
        tables = list(self.data.record_tables(ent.class_id))
        tables += [t for t in self.data.record_tables(ws) if t not in tables]
        if tables and not any(p == 0x7D2 for p, _k, _v in ent.extra_props):
            ent.extra_props.append((0x7D2, KIND_ARRAY, [(0x462, KIND_DID, t) for t in tables]))

    def spawned_effects(self, ent):
        """The effect keys of a missile / spawned skill object that no script of its own plays ([ics]
        spawned_effect_scriptlets, in order, 0.1 s apart; only the keys its tables hold)."""
        names = self.ic.get("spawned_effect_scriptlets") or []
        keys = [k for k in (self.data.scriptlet_key(n) for n in names) if k]
        held = [k for k in keys if ent.scriptlet_keys is None or k in ent.scriptlet_keys]
        # 2026-10-25 10:40 (tester's video: Scorched Earth explodes and then shows its crater; it should slam, show the
        # crater, then explode): a key's own delay ([ics] spawned_effect_delays: name -> s), else 0.1 s apart
        delays = dict(self.ic.get("spawned_effect_delays") or {})
        # 2026-10-26 (grab-arm-carry.md 1: Grab's arm is the beam of its missile's Vfx_Active, which came 0.1 s late on a
        # missile that lives < 1 s): per-class delays first ([ics] spawned_effect_delays_by_class: class -> {name: s})
        delays.update((self.ic.get("spawned_effect_delays_by_class") or {}).get(f"0x{ent.class_id:08X}") or {})
        names = self.data.scriptlet_names()
        for i, key in enumerate(held):
            at = float(delays.get(names.get(key, ""), 0.1 * (i + 1)))
            self.schedule(at, lambda k=key: self.scriptlet(ent, k) if ent.eid in self.entities else None)

    def stat_scaling(self, rec, slot):
        """{stat: (base, base per rank, Mod, Mod per rank, formula)} of a skill record's slot block, for the stats with a
        scaling block on a known 0x3B formula (skill-mechanics-recipes.md 4)."""
        cache = self.__dict__.setdefault("_stat_scaling", {})
        key = (rec, slot)
        if key in cache:
            return cache[key]
        out = {}
        for _k, kind, v in self.data.record(rec) or []:
            if kind != KIND_TABLE:
                continue
            dd = records.as_dict(v)
            if dd.get(0x100000E6) != slot:
                continue
            for _k2, _kd, st in dd.get(0x100004B4) or []:
                sd = records.as_dict(st)
                d3 = records.as_dict(sd.get(0x100004D3) or [])
                d4 = records.as_dict(sd.get(0x100004D4) or [])
                f = d4.get(0x100004D7)
                if not d4 or f not in STAT_SCALING_FORMULAS or d4.get(0x100004B7) is None:
                    continue
                out[sd.get(0x100004B6)] = (d3.get(0x100004B7), d3.get(0x100004D2) or 0.0, d4.get(0x100004B7),
                                           d4.get(0x100004D2) or 0.0, STAT_SCALING_FORMULAS[f])
            break
        cache[key] = out
        return out

    def champion_tables(self, ent):
        if not self.ic.get("champion_script_tables", True):
            return []
        out = list(self.data.record_tables(ent.class_id))
        ws = self.data.champion_world_state(ent.class_id)
        if ws:
            out += [t for t in self.data.record_tables(ws) if t not in out]
        return out

    def camera_yaw(self):
        """The in-match camera yaw (degrees) for this encounter and the champion's team, or None ([ics]
        camera_yaw: {"0x40000C82": {"1": 0.0, "2": 180.0}}). 2026-10-23 17:50 (tester: the lane shows diagonally;
        docs/re-notes/pvp-camera-yaw.md): the camera reads f32 0x1000011E on the followed champion at its start
        (0x96AABF) and watches it (0x968F30); Crime Alley's intro 0x3500003C ends on heading 0."""
        table = (self.ic.get("camera_yaw") or {}).get(f"0x{self.encounter:08X}") or {}
        team = getattr(self.champion, "team", None) if self.champion else None
        v = table.get(str(team))
        return float(v) if v is not None else None

    def send_camera_yaw(self):
        """0x1000011E again as a change (the watcher turns the camera): yaw + 1, then the yaw."""
        yaw = self.camera_yaw()
        if yaw is None or self.champion is None:
            return
        ch = self.champion
        self.send(f"camera yaw {yaw + 1:g} (0x1000011e, 0x6)", M.set_property(ch.eid, PROP_CAMERA_YAW, KIND_F32, yaw + 1.0))
        self.send(f"camera yaw {yaw:g} (0x1000011e, 0x6)", M.set_property(ch.eid, PROP_CAMERA_YAW, KIND_F32, yaw))

    def vital_notices_on(self):
        """0x100000CE = true on the champion (a change, by 0x6): its listener 0xaafcd0 sets the vitals' notify flag
        [vit+0x64], without which no Will change reaches the HUD (UI_NotifyVitalChange, the dimmed buttons); the
        client sets it itself only for a non-0x02 IID (0xa16807). [ics] vital_notices; skill-button-will.md."""
        if self.champion is None or not self.ic.get("vital_notices", True):
            return
        self.send("vital notices on (0x100000ce = true, 0x6)",
                  M.set_property(self.champion.eid, PROP_VITAL_NOTICES, KIND_BOOL, 1))
        if self.ic.get("vision_as_change", True):
            # 2026-10-23 17:40 (fog-vision-runtime.md): the champion's vision radius and unit flags (Character 8) as
            # CHANGES, the only form the unit component stores (0xAB12C0 reads +0x8C / +0xA4 for vision sources)
            ch = self.champion
            r = float(self.ic.get("champion_vision_radius", 0) or self.ic.get("fog_vision_radius", 0) or 0)
            if r > 0:
                self.send("champion vision 0 (0x6)", M.set_property(ch.eid, PROP_VISION_RADIUS, KIND_F32, 0.0))
                self.send(f"champion vision {r:g} (0x6)", M.set_property(ch.eid, PROP_VISION_RADIUS, KIND_F32, r))
            # ca-fog-ring-announcer.md 2: the turret ring's phantom (0xA3A5F0) marks the local champion inside only when
            # its PerceivedType has Player 0x200000, so the player's champion is Character | Player
            flags = 8 | (0x200000 if self.ic.get("champion_player_flag", True) else 0)
            self.send("champion unit flags 0 (0x6)", M.set_property(ch.eid, 0x1000019D, 0x13, 0))
            self.send(f"champion unit flags 8{' | Player 0x200000' if flags != 8 else ''} (0x6)",
                      M.set_property(ch.eid, 0x1000019D, 0x13, flags))
            if self.ic.get("champion_flags_in_bundle", True):
                # tester report 2026-10-29 19:55 (still no turret ring; ca-ring-fog-bundles.md 1, C object-update-bundles.md
                # 0.3): with object_update_mode "bundle" every champion update is a full bundle whose 0xBC diff turns an
                # own net-1 id it leaves out back to the template value, so the Player bit lived until the next bundle
                # (19:48:39.968, 7 s after it was set). The flags ride in every later bundle (an equal value notifies
                # nothing, the cache keeps the change); false = by 0x6 only, as before
                ch.extra_props = [p for p in ch.extra_props if p[0] != 0x1000019D] + [(0x1000019D, KIND_U32, flags)]
            self.see_through_blockers(ch)

    def teleport(self, ent):
        """client-movement.md: a newer "teleport" sequence byte (seq A) makes the client snap the object to the new
        position with its velocity reset (0x60B5F0)."""
        ent.tele_seq = getattr(ent, "tele_seq", 1) % 255 + 1

    def say(self, key):
        """Start a conversation (0x2001). 2026-10-22 08:39 (tester: Superman still repeats lines, each 0x2001 went
        once): every conversation had instance 0xFFFFFFFF; with [ics] conversation_instances each gets its own."""
        inst = M.next_conversation_instance() if self.ic.get("conversation_instances", True) else 0xFFFFFFFF
        self.send(f"conversation {key:#x} (0x2001, instance {inst:#x})", M.start_conversation(key, instance_id=inst))
        return inst

    def update(self, ent, label=None, force=False, full=False, motion=None, toggles=True):
        """Send the entity's current state.
        2026-10-28 12:56 (tester: the meteorite's lift / throw has no proper animation; liftables-camps-animations.md 2):
        while the champion carries a liftable, its other updates (credits, XP, slot tables) wait until the carry ends
        ([ics] liftable_hold_champion_bundles; kept: a held update cannot turn the champion mid-clip). force = the
        carry's own updates (facing for the lift / throw).
        2026-10-28 15:00 (tester report 2026-10-28 15:00; docs/re-notes/object-update-bundles.md 3 / 7 / 12, C: a full
        bundle re-creates nothing, but its 0xBC removes the object's network-mode 1 / 3 ids it leaves out): with [ics]
        object_update_mode "delta" an object the client already has gets World.delta (motion-only state, 0x6 / 0x86);
        a full bundle (0xF2 + 0xB0 + 0xBC, as before) only to create it, when full (a creation retry, a champion's
        death / respawn with delta_full_on_life_change), within delta_create_window, at its first update in the world
        after loading, or when an array / table changed (delta_complex_as_bundle). motion: World.delta's (None = when
        it changed, True = always, False = never). After a full champion bundle in delta mode vital_notices_on restores
        the ids that bundle removed (toggles=False: the caller does it)."""
        if ent is self.champion and not force and getattr(ent, "bundle_hold", False):
            ent.bundle_held = label or "champion state"
            return
        if ent.eid not in self.entities and ent is not self.champion:
            return
        delta = self.delta_mode()
        if delta and not full and not self._full_needed(ent) and self.delta(ent, label, motion=motion):
            return
        self.send(label, self.bundle(ent))
        self._resend_looping(ent)
        if delta and toggles and ent is self.champion:
            self.vital_notices_on()

    def looping_run(self, eid, key):
        """The run number a re-sent looping key goes with. 2026-10-29 tester report 2026-10-29 14:40 (the Shards sphere
        restarted its burst at every re-send; agl-qer-lift.md 2, C client rule 0x6279D0 step 4: a live run number is
        only a signal): the key's last run number, so the client restarts it only when that run has ended ([ics]
        looping_resend_same_run; false = a new number per re-send)."""
        last = self.live_scriptlets.get((eid, key))
        if last is not None and self.ic.get("looping_resend_same_run", True):
            return last
        self.scriptlet_runs += 1
        self.live_scriptlets[(eid, key)] = self.scriptlet_runs
        return self.scriptlet_runs

    def _resend_looping(self, ent):
        """2026-10-28 09:36 (tester: AGL's shield sphere vanishes while it attacks and comes back when the attack ends):
        each basic attack's "faces the target" bundle re-creates the object and drops what its running scriptlets
        spawned; the keys in a scriptlet_restart loop (Shards_Active) go again right after ([ics]
        resend_looping_after_bundle). 2026-10-28 15:00 (object-update-bundles.md 3 / 6.1, C: a bundle re-creates nothing
        and drops no run; this starts a second run beside the first): it follows full bundles only, which in delta mode
        are the creation, its retries and the life changes."""
        live = self.__dict__.get("looping_scriptlets") or {}
        if not live or not self.ic.get("resend_looping_after_bundle", True):
            return
        now = time.time()
        sent = self.__dict__.get("scriptlet_sent_at") or {}
        for (eid, key), (variables, began, until, stop_key) in list(live.items()):
            if eid != ent.eid:
                continue
            if now > until or sent.get((eid, stop_key), 0.0) >= began or not getattr(ent, "alive", True):
                live.pop((eid, key), None)
                continue
            msg = M.start_scriptlets(eid, [(key, self.looping_run(eid, key))], 0, variables)
            self.schedule(float(self.ic.get("resend_looping_delay", 0.05) or 0.0),
                          lambda m=msg, k=key: self.send(f"{ent.name}: scriptlet {k:#x} again after its bundle (0x8d)", m))

    def vitals_component(self, ent):
        """Whether the client gave the object a vitals component (and floaty / status icon components): its PerceivedType
        0x1000019D (the class template's, or what the server sends with it) & CreateGameComponents. 2026-10-29 tester
        report 19:55 (the game froze and closed; diag: access violation at rva 0x6B1BD9 = 0xAB1BD9, the 0x42 handler
        0xAB2880 called the vitals method with [entity+0x80] = 0): Arcane Supergirl's Firewall 0x40000BEF (health stat
        1, no 0x1000019D in its template) took AGL's Scorched Earth and got vitals 0/1. A failing object's client_vitals
        turns false, so its status icons / floaty numbers stop too ([ics] vitals_need_perceived_type, false = as before)."""
        if ent is self.champion or getattr(ent, "bot", False) or not self.ic.get("vitals_need_perceived_type", True):
            return True
        cached = ent.__dict__.get("_vitals_component")
        if cached is not None:
            return cached
        flags = 0
        for prop, _kind, value in list(self.data.target_properties(ent.class_id)) + list(ent.extra_props):
            if prop == PROP_UNIT_FLAGS and isinstance(value, int):
                flags |= value
        ok = bool(flags & CREATE_GAME_COMPONENTS)
        if not ok:
            ent.client_vitals = False
            self.log(f"{ent.name}: no vitals component on the client (PerceivedType {flags:#x}): no 0x42 / status icons")
        ent._vitals_component = ok
        return ok

    def vitals(self, ent):
        if ent.health is None or ent.max_health is None or not getattr(ent, "client_vitals", True):
            # 0x42 only goes to objects with a vitals component: the client crashes otherwise (2026-10-21, tester:
            # the game closed at the end of the load, right after vitals went to the layout's doors and vehicles)
            return
        if not self.vitals_component(ent):
            return
        pairs = [(ent.health or 0, ent.max_health or 1)]
        if ent.max_will:
            pairs.append((ent.will, ent.max_will))
        # 2026-10-26 (deep-scan-s2c.md 1, C: 0x42's second list = the ablative (shield) layer per vital, drawn on the bar;
        # its third list = this update's damage / heal events, the floating numbers; both were always empty)
        hits = ent.__dict__.pop("floaty_hits", None) or []
        second = None
        if self.ic.get("vitals_shield_layer", True) and "_combat" in self.__dict__:
            sh = [v for v in self.combat.of(ent).shields.values() if v[0] == 2 and v[1] > 0]
            if sh:
                second = [(sum(v[1] for v in sh), sum(v[2] for v in sh))] + [(0, 0)] * (len(pairs) - 1)
        vots = []
        for dtype, vital, key, amount in hits[-8:]:
            a16 = int(round(max(-1023.0, min(1023.0, amount)) * 16))
            vots.append((dtype, vital, 0, [(key, a16)]))
        # 2026-10-22 (full-combat-skills.md 2 B.1): the values with the client serializer's long form above 16383
        # (M.vitals masks them with 0x7FFF); [ics] vitals_long_form = false for the old encoding
        msg = (M.vitals_long(ent.eid, pairs, second=second, vots=vots) if self.ic.get("vitals_long_form", True)
               else M.vitals(ent.eid, pairs))
        self.send(f"{ent.name} vitals {int(ent.health or 0)}/{ent.max_health}"
                  + (f", Will {int(ent.will)}/{ent.max_will}" if ent.max_will else "") + " (0x42)", msg)

    def floaty_key(self, ent):
        """0x42 element key (deep-scan-s2c.md 1.1): (character << 7) | (team & 7) << 4 | sub (0x10000637, sent as 0)."""
        if not isinstance(ent, Entity):
            return 0
        char = 0x80 if ent.kind == "champion" else 0
        team = getattr(ent, "wire_team", None)            # the team the client knows ([ics] match_camp_wire_team)
        team = getattr(ent, "team", 0) if team is None else team
        return char | ((int(team or 0) & 7) << 4)

    def queue_floaty(self, source, target, dtype, amount, vital):
        """A damage (negative, by type 1 Attack / 2 Power / 3 True) or heal (positive, vital 2) number for the target's
        next 0x42, keyed on the attacker ([ics] vitals_floaty_numbers)."""
        if not self.ic.get("vitals_floaty_numbers", True) or not isinstance(target, Entity):
            return
        if not (target is self.champion or getattr(target, "client_vitals", False)):
            return
        src = source.owner if isinstance(source, R.Missile) else source
        target.__dict__.setdefault("floaty_hits", []).append((dtype, vital, self.floaty_key(src), amount))

    def scriptlet(self, ent, key, label=None, target=None, variables=None):
        """Play a scriptlet on an object (0x8D); a key its tables do not hold is not sent. target: the scriptlet's
        target variable (0x108), e.g. what the guide arrows point at."""
        if isinstance(key, str):
            key = self.data.scriptlet_key(key)
        # the champion is not filtered: its tables come from several records (and its cinematic ones)
        if not key or (ent is not self.champion and ent.scriptlet_keys is not None and key not in ent.scriptlet_keys):
            return False
        self.scriptlet_runs += 1
        name = self.data.scriptlet_names().get(key, f"{key:#x}")
        if ent.kind == "prop" and key in (self.data.scriptlet_key("Object_Open"), self.data.scriptlet_key("Object_Closed")):
            self.set_blocking(ent, key == self.data.scriptlet_key("Object_Closed"))   # a gate opens / closes
        variables = list(variables or []) + ([(M.PROP_SCRIPT_TARGET, KIND_IID, target.eid)]
                                             if isinstance(target, Entity) else [])
        variables = variables or None
        self.send(label or f"{ent.name}: {name} (0x8d)" + (f" -> {target.name}" if variables else ""),
                  M.start_scriptlets(ent.eid, [(key, self.scriptlet_runs)], 0, variables))
        self.live_scriptlets[(ent.eid, key)] = self.scriptlet_runs
        self.graph_feed(ent, key, variables)
        return True

    def signal_scriptlet(self, ent, key, run=None, script=False):
        """2026-10-23 23:30 (tester: Scorched Earth's circle stays on the ground forever; skill-second-stages.md 3):
        StopScriptletKey signals the live run of that key; 0x8D with the run's own instance number and a signal bit
        ([ics] stop_scriptlet_signal, P: 1 as the client's own 0x57C4B0) signals it instead of starting a new run."""
        bit = self.ic.get("stop_scriptlet_signal", 1)
        if run is None:
            (self.__dict__.get("looping_scriptlets") or {}).pop((ent.eid, key), None)   # a held run stops with it
            run = self.live_scriptlets.pop((ent.eid, key), None)
        if bit is None or bit is False or run is None or ent.eid not in self.entities and ent is not self.champion:
            return False
        orders = self.__dict__.get("scriptlet_orders") if script else None
        if orders is not None:
            return orders.stop(ent, key, run)          # a script's StopScriptlet: 0x11F (ics/scriptlet_orders.py)
        name = self.data.scriptlet_names().get(key, f"{key:#x}")
        self.send(f"{ent.name}: stop {name} (0x8d signal {int(bit)}, run {run})",
                  M.start_scriptlets(ent.eid, [(key, run)], 0, signals=1 << int(bit)))
        return True

    def graph_event(self, ent, event, label=None):
        """An animation-graph event (name table 0x300000A4) on an entity: scriptlet 0x100001E3
        (_HFSM_BehaviorRaiseEventAction) with script variable 0x780 = the event, as the earlier server raised them."""
        return self.scriptlet(ent, 0x100001E3, label or f"{ent.name}: graph event {event:#x}",
                              variables=[(0x780, KIND_ENUM, event)])

    def _config_key(self, name):
        """A scriptlet key from [ics]: a name ("_Defeat_OnDead"), a "0x..." string or a number; 0 if unknown."""
        if isinstance(name, str):
            return int(name, 16) if name.lower().startswith("0x") else self.data.scriptlet_key(name)
        return int(name or 0)

    def death_fall(self, ent):
        """2026-10-28 15:00 (tester report 2026-10-28 15:00: no fall when the player kills or is killed;
        docs/re-notes/death-animation.md 2, C: the client never starts it itself): the champion falls into its graph's
        Death state, after the message that carried LifeState 2: the first of [ics] death_scriptlets that goes
        (_Defeat_OnDead 0x100001FA: CbtState_Death_Induce + the death cue), else the bare graph event [ics]
        death_graph_event (0x100001E3 + 0x780, the fase3-ie bots' form)."""
        for name in self.ic.get("death_scriptlets") or ():
            key = self._config_key(name)
            label = self.data.scriptlet_names().get(key, f"{key:#x}")
            if key and self.scriptlet(ent, key, f"{ent.name}: {label} (0x8d, falls)"):
                return True
        ev = int(self.ic.get("death_graph_event", 0x100000AD) or 0)
        return bool(ev) and self.graph_event(ent, ev, f"{ent.name} falls (graph event {ev:#x})")

    def death_overlay(self, ch, on):
        """2026-10-28 15:00 (same report; death-animation.md 3, 4, 10): the original's grey death screen
        _CDefeatSystem_DeathOverlay, opt-in ([ics] death_overlay_scriptlets, [] by default: our client already runs it
        by itself on the local death). Only on the session's champion: it has no local-player filter, a bot's would grey
        the player's screen. on=False (the respawn, the match end) stops each run it started with event 0x11F ([ics]
        death_overlay_stop); a 0x8D signal would stop nothing."""
        if ch is None or ch is not self.champion:
            return
        if not on:
            runs = ch.__dict__.pop("death_overlay_runs", None) or {}
            for key, run in runs.items() if self.ic.get("death_overlay_stop", True) else ():
                label = self.data.scriptlet_names().get(key, f"{key:#x}")
                self.send(f"{ch.name}: stop {label} (0x11f, run {run})", M.stop_scriptlet(ch.eid, key, run))
            return
        if getattr(self, "match_ended", False) and self.ic.get("death_overlay_skip_after_end", True):
            # 2026-10-29 (fase3-if review): a fall still pending when the match ended (a Clash death that takes the last
            # team health ends it inside World.damage) starts no death screen: Match.end's stop has already run
            # ([ics] death_overlay_skip_after_end)
            if self.ic.get("death_overlay_scriptlets"):
                self.log(f"{ch.name}: no death screen after the match end")
            return
        for name in self.ic.get("death_overlay_scriptlets") or ():
            key = self._config_key(name)
            label = self.data.scriptlet_names().get(key, f"{key:#x}")
            if key and self.scriptlet(ch, key, f"{ch.name}: {label} (0x8d, death screen)"):
                ch.__dict__.setdefault("death_overlay_runs", {})[key] = self.live_scriptlets[(ch.eid, key)]

    def _local_fall(self, ch, fall):
        """2026-10-28 15:00 (same report; death-animation.md 10.4): the local champion's fall (fall = true) and the opt-in
        death screen, [ics] death_fall_delay s after its death message, so its stop state (applied 0.1 s after its
        stamp) and its statuses' exit 0x8Ds (champion_scriptlet_delay late) land first. Dropped if the champion is
        alive again by then."""
        mark = ch.death_mark = object()

        def go():
            if ch.alive or getattr(ch, "death_mark", None) is not mark:
                return
            if fall:
                self.death_fall(ch)
            self.death_overlay(ch, True)
        delay = max(0.0, float(self.ic.get("death_fall_delay", 0.15) or 0.0))
        if delay > 0:
            self.schedule(delay, go)
        else:
            go()

    def _unit_fall(self, ent):
        """Tester report 2026-10-29 12:45 ("the drones' destruction animations do not play: when their health runs out
        they stand still a moment and disappear"; docs/re-notes/unit-death-slide-levelup.md 1): a dead unit got only its
        LifeState 2 bundle and the 0x3 corpse_seconds later. Every lane drone / camp creature holds _Defeat_OnDead
        0x100001FA (its world state's table: CbtState_Death_Induce + Vfx_OnExplode) and _Defeat_OnFade 0x100001FE, and
        the client never runs them itself (C): the first of [ics] unit_death_scriptlets goes unit_death_fall_delay s
        after the death bundle (its stop state and the killing hit's 0x8D land first), the first of
        unit_fade_scriptlets unit_fade_delay s after it ([] = none: the fase3-ih behaviour)."""
        def first(key_list, label):
            for name in self.ic.get(key_list) or ():
                key = self._config_key(name)
                text = self.data.scriptlet_names().get(key, f"{key:#x}")
                if key and self.scriptlet(ent, key, f"{ent.name}: {text} (0x8d, {label})"):
                    return True
            return False

        def go(key_list, label):
            if ent.eid in self.entities and not ent.alive:
                first(key_list, label)
        for key_list, delay_key, default, label in (("unit_death_scriptlets", "unit_death_fall_delay", 0.15, "falls"),
                                                     ("unit_fade_scriptlets", "unit_fade_delay", 2.0, "fades")):
            if not self.ic.get(key_list):
                continue
            delay = max(0.0, float(self.ic.get(delay_key, default) or 0.0))
            if delay > 0:
                self.schedule(delay, lambda k=key_list, lb=label: go(k, lb))
            else:
                go(key_list, label)

    def initial_scriptlets(self, ent):
        """The scriptlets that put a just-created prop in its resting state ([ics] prop_initial_scriptlets: the
        door's Object_Closed spawns its light wall 0x2E0010F4 / 0x2E000CD8). Played when the prop's tables hold them."""
        key = "prop_initial_scriptlets" if ent.kind == "prop" else "unit_initial_scriptlets"
        for name in self.ic.get(key) or ():
            self.scriptlet(ent, name)

    def spawn_in(self, ent):
        """A unit's spawn-in effect, right after its creation ([ics] unit_spawn_scriptlets, unit_spawn_delay).
        2026-10-22 (tester after fase3-gp: the drones pop up; original Part 1 video 1:18.4: a purple ring and glow
        where each drone appears): the drones' table 0x1D0002F8 _Entity_OnEnterWorld_Default runs Vfx_Spawn
        (0x1D0002F7 / F6: particles 0x18000B56 / 0x18000B58, a colour fade and the ring mesh 0x1700142A)."""
        names = self.ic.get("unit_spawn_scriptlets") or ()
        if not names or ent.kind != "unit":
            return

        def play():
            if ent.eid in self.entities:
                for name in names:
                    if self.scriptlet(ent, name, f"{ent.name}: {name} (0x8d, spawn-in)"):
                        break               # the first one the unit's tables hold (it runs the rest itself)
        delay = float(self.ic.get("unit_spawn_delay", 0.1) or 0)
        if delay > 0:
            self.schedule(delay, play)
        else:
            play()

    # ---- credits -----------------------------------------------------------------------------
    def bounty(self, killer, victim):
        """Credits for a kill (not in the client data: [ics] credits_per_kill) and the "+N" floaty over the victim."""
        ch = self.champion
        if killer is not ch or victim is ch or not ch:
            return
        table = self.ic.get("credits_per_kill") or {}
        amount = float(table.get(victim.kind, table.get("unit", 0)) or 0)
        if amount <= 0:
            return
        ch.gold += amount
        self.send(f"+{amount:g} credits over {victim.name} (0x100004d6)", M.floaty_currency(victim.eid, amount))
        self.refresh_champion(f"credits {ch.gold:.0f}")

    def experience(self, killer, victim):
        """XP for a kill and the level it reaches ([ics] xp_per_kill, xp_levels: not in the client data). An
        encounter flow sets the levels itself (the tutorial), so no XP then."""
        ch = self.champion
        if killer is not ch or victim is ch or not ch or self.rank_filter is not None:
            return
        amount = int((self.ic.get("xp_per_kill") or {}).get(victim.kind, 0) or 0)
        if amount <= 0:
            return
        ch.xp += amount
        levels = [int(x) for x in self.ic.get("xp_levels") or ()]
        level = 1 + sum(1 for need in levels if ch.xp >= need)
        level = min(level, int(self.ic.get("level_cap", 20)))
        if level > ch.level:
            self.log(f"{ch.name}: level {level} ({ch.xp} XP)")
            self.set_level(level)
        else:
            self.refresh_champion(f"{ch.name}: {ch.xp} XP")

    def income(self, dt):
        ch = self.champion
        rate = float(self.ic.get("credits_per_second", 0) or 0)
        # income_hold: a PvP match before its start ([ics] match_income_from_start, test-2026-10-28-1439-sweep.md S8)
        if ch and rate > 0 and self.in_world and not getattr(self, "income_hold", False):
            before = int(ch.gold)
            ch.gold += rate * dt
            if int(ch.gold) // 10 != before // 10:
                self.refresh_champion(f"credits {ch.gold:.0f}")

    # ---- Stolen Powers ---------------------------------------------------------------------
    def give_stolen_powers(self, ent):
        """Slots 7 (D) and 8 (F): the encounter's powers ([ics.encounters] stolen_powers) or the champion's default
        pair (its loadout's 0x1000064E). Each slot's whole skill definition goes in champion property 0x100008F0 /
        0x100008F1, and its script runs like any skill's."""
        enc = (self.ic.get("encounters") or {}).get(f"0x{self.encounter:08X}") or {}
        # 2026-10-23 14:00 (tester: the Stolen Powers picked in champion select were not the match's): the lobby's
        # choice (World.stolen_choice, set by the session) comes first
        chosen = [p for p in (getattr(self, "stolen_choice", None) or ()) if p]
        powers = list(chosen or enc.get("stolen_powers") or self.data.loadout(ent.class_id)["stolen"])[:2]
        targeting = enc.get("stolen_targeting") or {}
        ent.stolen = {}
        for slot, version in zip(STOLEN_SLOTS, powers):
            block, skill = self.data.stolen_power(int(version))
            if not block:
                continue
            t = int(targeting.get(str(slot), 0) or 0)
            if t:
                # the client's entity picker refused the tutorial's car (2026-10-16): F as a ground target
                block = [(k, kind, t if k == PROP_TARGETING else v) for k, kind, v in block]
            ent.stolen[slot] = block
            if skill and skill.script:
                skill.slot = slot
                ent.kit[slot] = skill
                ent.ranks[slot] = 1
        if ent.stolen:
            self.log(f"{ent.name}: Stolen Powers " + ", ".join(f"{s}={int(v):#x}" for s, v in zip(STOLEN_SLOTS, powers)))

    # ---- stats -------------------------------------------------------------------------------
    def recompute_stats(self, ent, refill=False):
        """A champion's stats: its record's value at level 1 + growth x (level - 1), plus its items' bonuses (op 9
        add, op 10 add percent). Health and Will keep their share of the new maximum."""
        if not ent.base_stats:
            return
        stats = {}
        amp_add, amp_pct = getattr(ent, "amp_add", {}), getattr(ent, "amp_pct", {})
        for stat in set(ent.base_stats) | set(ent.item_add) | set(ent.item_pct) | set(amp_add) | set(amp_pct):
            base, per = ent.base_stats.get(stat, (0.0, 0.0))
            stats[stat] = ((base + per * (ent.level - 1) + ent.item_add.get(stat, 0.0) + amp_add.get(stat, 0.0))
                           * (1.0 + ent.item_pct.get(stat, 0.0) + amp_pct.get(stat, 0.0)))
        if stats != ent.stats:
            ent.stats_version = getattr(ent, "stats_version", 0) + 1   # the skills reload their stats on next use
        ent.stats = stats
        hp_share = 1.0 if refill or not ent.max_health else (ent.health or 0) / ent.max_health
        will_share = 1.0 if refill or not ent.max_will else (ent.will or 0) / ent.max_will
        if stats.get(STAT_HEALTH):
            ent.max_health = int(round(stats[STAT_HEALTH]))
            ent.health = int(round(ent.max_health * hp_share))
        if stats.get(STAT_WILL):
            ent.max_will = int(round(stats[STAT_WILL]))
            ent.will = ent.max_will * will_share
        if stats.get(STAT_MOVE_SPEED) and self.ic.get("champion_move_speed_from_data", True):
            # 2026-10-24 00:40 (tester: the champions move so fast the animations look wrong): every champion walked at
            # [ics] move_speed 4.5 m/s; the data gives 3.65 (Gaslight Batman) - 3.9 (Arcane Harley) + growth and items.
            # A running slow / dash keeps its own value and restores this one when it ends.
            speed = float(stats[STAT_MOVE_SPEED])
            if hasattr(ent, "saved_move_speed"):
                ent.saved_move_speed = speed
            elif hasattr(ent, "base_move_speed"):
                if abs(ent.move_speed - ent.base_move_speed) < 1e-6:
                    ent.move_speed = speed              # no slow running now
                ent.base_move_speed = speed
            else:
                ent.move_speed = speed

    def stat_properties(self, ent):
        """The champion's stats as its f32 stat properties (the HUD's stats panel and tooltips read them)."""
        if not self.ic.get("send_stat_properties", True):
            return []
        return [(stat, KIND_F32, float(v)) for stat, v in sorted(ent.stats.items()) if stat not in NOT_SENT_STATS]

    # ---- progression -------------------------------------------------------------------------
    def max_rank(self, slot):
        table = self.ic.get("max_skill_ranks") or {}
        return int(table.get(str(slot), 0))

    def rank_level_needed(self, ent, slot, rank):
        """The champion level rank `rank` of `slot` needs. 2026-10-30 (tester: at level 19 the "+" and "Recommended"
        stayed on the R and nothing ranked; skill-rank-levels.md): [ics] rank_levels_from_client = the client's own
        rule (WLib InqCanRankSkill 0x926C -> 0x94E4): the skill block's array 0x1000099C when it has an entry for the
        rank, else [ics] rank_level_table (R 6 / 10 / 14 / 18, other slots 1 / 3 / 6 / 9). False = the fase3-gz rule
        (rank_min_levels, then rank r at level 2r - 1 under rank_level_rule), which put the 4th R rank at 20, above the
        level cap 19, so the 19th point could never be spent."""
        if self.ic.get("rank_levels_from_client", True):
            own = self.data.skill_rank_levels(getattr(ent, "class_id", 0)).get(slot) if self.data else None
            if own and 1 <= rank <= len(own):
                return int(own[rank - 1])
            table = self.ic.get("rank_level_table") or {}
            levels = table.get(str(slot), table.get("default")) or ()
            return int(levels[rank - 1]) if 1 <= rank <= len(levels) else 1
        gates = (self.ic.get("rank_min_levels") or {}).get(str(slot))
        if gates and rank <= len(gates):
            return int(gates[rank - 1])
        return 2 * rank - 1 if self.ic.get("rank_level_rule", True) else 1

    def rank_refusal(self, ent, slot):
        """Why `ent` may not put a point into `slot` now (None = it may), the encounter's flow aside."""
        if not ent:
            return "no champion"
        if ent.skill_points <= 0:
            return "no skill points"
        if slot not in ent.kit:
            return "no skill in that slot"
        rank = ent.ranks.get(slot, 0)
        if rank >= self.max_rank(slot):
            return f"at max rank {rank}"
        need = self.rank_level_needed(ent, slot, rank + 1)
        if ent.level < need:
            return f"rank {rank + 1} needs level {need} (level {ent.level})"
        return None

    def rankable(self, slot):
        # 2026-10-23 14:02 (tester: any skill can be ranked from the start, R only from level 6): the level each next
        # rank needs (rank_level_needed)
        if self.rank_refusal(self.champion, slot) is not None:
            return False
        return self.rank_filter(slot) if self.rank_filter else True

    def refuse_rank(self, slot, how="rank request"):
        """A rank the client asked for and the server will not apply: logged with the reason, and (2026-10-30, [ics]
        rank_refused_refresh) the champion's rank state sent again, so the client's "+" / Recommended follow the
        server instead of staying lit."""
        ch = self.champion
        why = self.rank_refusal(ch, slot) or ("not now (the encounter's flow)" if self.rank_filter else "refused")
        self.log(f"{how} slot {slot}: refused, {why} (level {ch.level if ch else 0}, "
                 f"points {ch.skill_points if ch else 0}, ranks {dict(sorted(ch.ranks.items())) if ch else {}})")
        if ch and self.ic.get("rank_refused_refresh", True):
            now = time.monotonic()
            if now - getattr(self, "_rank_refused_at", -10.0) >= 1.0:   # at most once a second (no ping / refresh loop)
                self._rank_refused_at = now
                self.refresh_champion(f"{ch.name}: rank state after a refused rank", force=True)

    def rank_skill(self, slot):
        """The player clicked a skill's "+" (patched client: ping 0x2136 'RANK'): one skill point into it."""
        ch = self.champion
        if not self.rankable(slot):
            self.refuse_rank(slot)
            return False
        ch.ranks[slot] = ch.ranks.get(slot, 0) + 1
        ch.skill_points -= 1
        self._rank_refresh = 3 - self._rank_refresh
        skill = ch.kit.get(slot)
        self.log(f"{ch.name}: {skill.name if skill else slot} rank {ch.ranks[slot]} ({ch.skill_points} points left)")
        self.update(ch, f"{ch.name} ranks slot {slot}")
        self.emit("ranked", slot=slot, rank=ch.ranks[slot])
        return True

    def set_level(self, level, skill_points=None):
        ch = self.champion
        gained = max(0, int(level) - ch.level)
        ch.level = int(level)
        ch.skill_points = ch.skill_points + gained if skill_points is None else int(skill_points)
        self.recompute_stats(ch)
        self.vitals(ch)
        self._rank_refresh = 3 - self._rank_refresh
        self.update(ch, f"{ch.name} level {ch.level} ({ch.skill_points} skill points)")
        if gained and self.ic.get("level_up_scriptlet"):
            # 2026-10-26 (deep-scan-s2c.md 3): the level-up effect (in the shared champion table 0x1D0000EF)
            self.scriptlet(ch, int(self.ic["level_up_scriptlet"]), f"{ch.name}: _Advancement_LevelUp (0x8d)")

    def refresh_champion(self, label="champion state", force=False):
        self._rank_refresh = 3 - self._rank_refresh
        self.update(self.champion, label, force=force)

    def remove(self, ent, label=None):
        self.entities.pop(ent.eid, None)
        self.set_blocking(ent, False)
        self.send(label or f"{ent.name} removed (0x3)", M.remove_object(ent.eid))
        # the client no longer has it: added again, it is created by a full bundle ([ics] object_update_mode)
        ent.client_props = ent.client_motion = ent.client_created_at = None

    # ---- creation ------------------------------------------------------------------------------
    def create_champion(self, variant, spawn):
        ic = self.ic
        ent = Entity(M.CHAMPION_AGENT_ID, self.data.champion_name(variant)[0], variant, spawn[4:7],
                     team=ic["team"], kind="champion")
        ent.move_speed = float(ic["move_speed"])
        ent.health = ent.max_health = int(ic["health"])
        ent.will = ent.max_will = int(ic["will"])
        if ic.get("champion_stats_from_data", True):
            # 2026-10-21: the champion's own stats record (base and growth per level); [ics] health / will are
            # only for a champion without one
            ent.base_stats = self.data.champion_stats(variant)
            self.recompute_stats(ent, refill=True)
        if ic.get("champion_resource_from_data", True):
            # 2026-10-24 23:30 (aww-kit.md: Atomic Wonder Woman's charges are vital 6, Rev): the champion's own resource
            # vital type; a non-Will resource starts empty and has no [ics] will_regen
            ent.resource_vital = self.data.resource_vital(variant) or int(ic.get("champion_secondary_vital", 5) or 5)
            if ent.resource_vital != 5:
                ent.will = 0.0
        ent.kit = self.data.kit(variant)
        ent.ranks = {slot: int(ic["skill_rank"]) for slot in ent.kit}
        self.give_stolen_powers(ent)
        self.champion = ent
        self.spawn_pos = list(ent.pos)
        self.start_kit(ent)
        self.champion_init_event(ent)
        self.log(f"champion {ent.name} ({variant:#x}): " + ", ".join(f"{s}={sk.name}" for s, sk in
                                                                      sorted(ent.kit.items())))
        prewarm.champion(self, ent)        # its statuses read now, not at their first hit ([ics] prewarm_statuses)
        return ent

    def placements(self, enc):
        """{name: placement} of the encounter's layout: every named placement (cinematic actors included) with
        the class the data gives it: a fighting variant (variants pack: health and a team), else the entity whose
        template names its world state (property 0x510: doors, the power core), else the bare world state
        (vehicles, the ranged drones). The match's champions' own placements are left out."""
        key = enc.get("layout_pack")
        if getattr(self, "_placements", None) and self._placements[0] == key:
            return self._placements[1]
        out = {}
        if key:
            variants = self.data.variants(enc["variants_pack"]) if enc.get("variants_pack") else {}
            classes = self.data.world_state_classes(enc)
            champions = {c["variant"] for c in self.data.roster}
            champion_states = self.data.champion_world_states(
                [self.champion.class_id if self.champion else 0] + list(enc.get("champions", ()))
                + list((self.ic["encounters"].get(f"0x{self.encounter:08X}") or {}).get("extra_champions", ())))
            overrides = self.ic.get("variant_overrides") or {}
            for e in self.data.layout(key):
                ws = e["wstate"]
                if not e["positions"] or ws in champion_states or e["name"] in out:
                    continue
                variant = variants.get(ws)
                cls = variant or classes.get(ws) or (ws if self.ic.get("spawn_world_states", True) else 0)
                if cls and f"0x{cls:08X}" in overrides:
                    cls = int(overrides[f"0x{cls:08X}"])
                if not cls or cls in champions:
                    continue
                p = e["positions"][0]
                w, _qx, _qy, qz = p["quat"]
                pos = [(p["lb"][0] - self.origin[1]) * LANDBLOCK + p["xyz"][0],
                       (p["lb"][1] - self.origin[2]) * LANDBLOCK + p["xyz"][1], p["xyz"][2]]
                out[e["name"]] = {"name": e["name"], "record": e["record"], "wstate": ws, "class": cls,
                                  "variant": variant, "pos": pos, "heading": 2 * math.atan2(qz, w) + math.pi / 2,
                                  "cell": p.get("cell", 0), "props": e.get("props", {})}
        self._placements = (key, out)
        return out

    def spawn_layout(self, enc, names=None):
        """Create the layout's placements (all but the cinematics' own records, or exactly `names`)."""
        if not self.ic.get("spawn_layout", True) or not enc.get("layout_pack"):
            return []
        out = []
        for name, pl in self.placements(enc).items():
            if names is None and pl["record"] >> 24 == 0x35:
                continue
            if names is not None and name not in names:
                continue
            out.append(self.spawn(pl["class"], pl["pos"], pl["heading"], side=pl["props"].get(PROP_SIDE),
                                  name=name, world_state=pl["wstate"], placement=pl, start=False))
        for x in out:
            if x.kit:
                self.start_kit(x)
        units = sum(1 for x in out if x.kind == "unit")
        self.log(f"layout {enc['layout_pack']:#x}: {units} units, {len(out) - units} props")
        return out

    def spawn(self, cls, pos, heading=0.0, side=None, name=None, world_state=0, placement=None, start=True):
        """One object of a class: a unit (a variant, or a world state of a character's creation type) gets its stat
        block, health and attack; a prop gets the movement module and a placed creation type. side 1 = the
        encounter's enemies, none = neutral (2026-10-21, tester: the human NPCs attacked Batman too)."""
        # an entity's world state: its template's property 0x510 (champion_world_state reads exactly that)
        ws = world_state or (cls if cls >> 24 == 0x2E else self.data.champion_world_state(cls))
        # a unit: an entity with an attack or a health stat (the practice target 0x40000BA9 has health, no attack)
        variant = cls if cls >> 24 == 0x40 and (self.data.unit_attack(cls) is not None
                                                 or STAT_HEALTH in self.data.unit_stats(cls)) else 0
        ctype = self.data.creation_type(ws) if ws else None
        mobile = bool(variant) or (cls == ws and ctype in MOBILE_CREATION_TYPES)
        props = (placement or {}).get("props", {})
        hostile = side == 1
        ent = Entity(self.new_id(), name or f"{cls:#x}", cls, pos, heading=heading,
                     team=self.ic["enemy_team"] if hostile else 0, kind="unit" if mobile else "prop")
        ent.side = side
        if not mobile and placement:
            # props keep the layout's cell (0xFB here), as the earlier server sent them when they showed
            # (2026-10-21, tester: no vehicles, doors ...; they were sent with cell 0)
            ent.cell = placement.get("cell", 0)
        for scale in (0x6B3, 0x6B4):
            if scale in props:
                ent.extra_props.append((scale, KIND_F32, struct.unpack("<f", struct.pack("<I", props[scale]))[0]))
        ent.templates = props.get(0x954, [])
        ent.world_state = ws
        ent.scriptlet_keys = self.data.scriptlets(cls, ws, ent.templates)
        if mobile:
            # base stats from the unit's stat block (2026-10-21: the tutorial drones and thugs have 200 health,
            # the Destroyer 1500; [ics] unit_health only for units without one)
            ent.stats = self.data.unit_stats(cls) if self.ic.get("unit_stats", True) else {}
            ent.health = ent.max_health = int(ent.stats.get(STAT_HEALTH) or self.ic["unit_health"])
            ent.move_speed = float(ent.stats.get(STAT_MOVE_SPEED) or 3.0)
            attack = self.data.unit_attack(cls) if variant else None
            borrow = int((self.ic.get("unit_attack_from") or {}).get(f"0x{ws:08X}", 0) or 0)
            if attack is None and borrow:
                # no template names this world state: another unit's attack and stats ([ics] unit_attack_from)
                attack = self.data.unit_attack(borrow)
                ent.stats = self.data.unit_stats(borrow) if self.ic.get("unit_stats", True) else {}
                ent.health = ent.max_health = int(ent.stats.get(STAT_HEALTH) or self.ic["unit_health"])
            if attack and self.ic.get("unit_ai", True):
                ent.kit = {0: attack}
                ent.ranks = {0: 1}
            # only variants are known to have a vitals component; 0x42 to one without crashes the client
            ent.client_vitals = bool(variant)
            if hostile and self.ic.get("unit_target_properties", True):
                # 2026-10-21 21:46 (tester: the drones cannot be targeted): the client attacks only an entity with
                # unit flags / targetable / category (its validator 0x9d01d0); the template has them, the client's
                # records do not. Neutral units (the thugs) stay untargetable.
                props_t = self.data.target_properties(variant or borrow or cls)
                # 2026-10-22 08:57 (diag --target: the drone passed the unit flags and failed "status tag check B"):
                # the validator reads the target's bool 0x10000029 (check B) and 0x10000249 (check C) through its unit
                # component; the tutorial template gives them as references (0x5... entries) the original server
                # resolved, the generic drone template and the client's class 0x48000168 have 1
                props_t = props_t + [(int(str(p), 0), KIND_BOOL, 1) for p in self.ic.get("unit_targetable_tags", [])]
                colour = int(self.ic.get("unit_colour_override", 1) or 0)
                if colour:
                    # 2026-10-22 08:13 (tester: the drones are red, the original's are purple): the generic drone
                    # template 0x49000A5C carries colour override 0x10000CF0 = 1, the tutorial's 0x49000C72 not;
                    # without it the client computes the enemy colour 5 (red) from PVP_Team (0xa7b0d0)
                    ent.extra_props.append((PROP_COLOUR_OVERRIDE, KIND_ENUM, colour))
                late = float(self.ic.get("unit_flags_delay", 0.8) or 0)
                if late > 0:
                    # 2026-10-21 23:30 (diag --target): the client's unit component caches the flags (+0xa4) only
                    # when 0x1000019D CHANGES; sent in the creation table they stayed 0 and every drone was refused.
                    # They are sent as a change a moment after the unit exists ([ics] unit_flags_delay).
                    late_ids = {PROP_UNIT_FLAGS} | {int(str(p), 0) for p in self.ic.get("unit_targetable_tags", [])}
                    ent.extra_props += [p for p in props_t if p[0] not in late_ids]
                    flags = [p for p in props_t if p[0] in late_ids]
                    if flags:
                        self.schedule(late, lambda e=ent, f=flags: self._late_flags(e, f))
                else:
                    ent.extra_props += props_t
        elif not self.ic.get("prop_movement_module", True):
            ent.module = None                     # the fase3-fx behaviour: no movement module
        if not mobile and ctype not in PLACED_CREATION_TYPES and self.ic.get("static_creation_type"):
            # 2026-10-21 (static analysis, actor-creation-and-environment.md): the client places a network
            # object only through its movement component, which exists for creation types 7 and 8 (table
            # 0x580160); entities of world-state type 5 become 6 and bare world states keep theirs (3, 5, 9), so
            # the doors, vehicles and the power core were never placed. 8 = UniqueDynamicMobile.
            ent.extra_props.append((0x50F, KIND_ENUM, int(self.ic["static_creation_type"])))
        self.add(ent)
        self.set_blocking(ent, True)
        if start and ent.kit:
            self.start_kit(ent)
        return ent

    def _late_flags(self, ent, flags):
        if ent.eid not in self.entities or not ent.alive:
            return
        if getattr(ent, "hold_flags", False):
            ent.pending_flags = flags          # the flow makes it targetable later (director "targetable")
            return
        ids = {p[0] for p in flags}
        ent.extra_props = [p for p in ent.extra_props if p[0] not in ids] + list(flags)
        # 2026-10-22 08:13 (diag --target: the flags were still 0 after a second bundle): a bundle does not go through
        # the property change path; event 0x6 sets one property the way the client's watchers see
        if not self.ic.get("unit_flags_event", True):
            self.update(ent, f"{ent.name}: unit flags {flags[0][2]:#x} (0x1000019D, in a full bundle)")
            return
        for prop, kind, value in flags:
            self.send(f"{ent.name}: {prop:#x} = {value:#x} (0x6 set property)", M.set_property(ent.eid, prop, kind, value))

    def set_blocking(self, ent, on):
        """A prop with a footprint ([ics] prop_blockers: the street vehicle, the gates) blocks paths on the navmesh
        (2026-10-21 22:52, tester: Batman walks through the first vehicle). An opened gate stops blocking."""
        if self.nav is None:
            return
        size = (self.ic.get("prop_blockers") or {}).get(f"0x{ent.world_state:08X}")
        if not size:
            return
        if on:
            hl, hw = float(size[0]), float(size[1])
            angle = ent.heading + (float(size[2]) if len(size) > 2 else -math.pi / 2)
            self.nav.block(ent.eid, ent.pos[0], ent.pos[1], hl, hw, angle)
        else:
            self.nav.unblock(ent.eid)

    def raise_skill_event(self, ent, slot, event, params=None):
        """An event for one skill's script only (0x20EA from the client)."""
        # 2026-10-29 tester report 19:55 (liftable-carry-throw-press.md 1): the match layer sees the press too (a carry
        # slot's press that no throw order follows, Liftables._press)
        self.emit("skill_press", ent=ent, slot=slot, key=event)
        inst = ent.skill_insts.get(slot)
        if inst is None:
            return
        acc = R.accepted_events(inst.script)
        if acc and event not in acc:
            # 2026-10-27 (skill-execution-model.md 1.2 / 6.5): the record's accept list decides (0x10000023 reaches
            # Green Arrow R, Deadshot R, Dex-Starr W, Flash R; every other script drops it, as the client VM does)
            # 2026-10-28 15:00 (test-2026-10-28-1439-sweep.md S13: 18 such lines, one per targeted press, by design):
            # logged once per script and event
            seen = self.__dict__.setdefault("_not_accepted_logged", set())
            if (inst.script.did, event) not in seen:
                seen.add((inst.script.did, event))
                self.log(f"{ent.name}: skill event {event:#x} on slot {slot}: not accepted by {inst.script.did:#x} "
                         f"(by design; logged once per script)")
            return
        try:
            inst.event(event, params)
        except Exception:                                  # noqa: BLE001
            self.log(f"{ent.name}: skill event {event:#x} on slot {slot} failed\n{traceback.format_exc()}")

    def graph_for(self, ent):
        """2026-10-27 (skill-execution-model.md 6, [ics] graph_runtime): the champion's (local or bot) running copy of its
        behaviour graph (ics/graph.py), made on first use; None for entities without one (units, props, missiles)."""
        if not R.GRAPH_RUNTIME or not isinstance(ent, Entity) or ent.kind != "champion":
            return None
        g = ent.__dict__.get("graph_rt", False)
        if g is not False:
            return g
        from . import graph as GR
        gdef = GR.data().for_variant(ent.class_id)
        g = None
        if gdef is not None:
            cw = CastWorld(self, ent, None)

            def after(seconds, fn):
                def run():
                    try:
                        fn()
                    except Exception:                           # noqa: BLE001
                        self.log(f"graph error\n{traceback.format_exc()}")
                self.schedule(max(0.001, float(seconds)), run)

            def deliver(code, did, offset, state):
                R.deliver_hook(cw, ent, code, did, offset, state)

            def speed():
                return cw.attribute(ent, 0x100005FE)

            def log(text):
                if self.ic.get("trace_scripts", True):
                    self.log(text)
            g = GR.GraphInstance(gdef, after, time.time, deliver, speed=speed, log=log, label=ent.name)
            self.log(f"{ent.name}: graph runtime on ({gdef.name}, {len(gdef.hooked)} hooked scripts)")
        ent.__dict__["graph_rt"] = g
        return g

    def graph_feed(self, ent, key, variables=None):
        """A 0x8D scriptlet on an entity also drives the server's copy of its graph (type 0x14 actions / 0x780)."""
        g = self.graph_for(ent) if R.GRAPH_RUNTIME else None
        if g is not None:
            try:
                g.scriptlet(key, variables)
            except Exception:                                   # noqa: BLE001
                self.log(f"{ent.name}: graph feed {key:#x} failed\n{traceback.format_exc()}")

    def raise_event(self, ent, event, params=None):
        """A script event on an entity's own scripts (e.g. 0x10000060 on the guide marker: the arrows show)."""
        R.raise_event(CastWorld(self, ent, None), ent, event, params)

    def start_unit_scripts(self, ent, force=False):
        if not (force or self.ic.get("run_unit_scripts")):
            return
        for did in self.data.entity_scripts(ent.class_id):
            try:
                R.start_script(V.load(did), ent, CastWorld(self, ent, None))
            except Exception as e:                 # noqa: BLE001 - a script must never stop the match
                self.log(f"{ent.name}: script {did:#x} not started ({e!r})")

    def play_scenes(self, cinematic, layout_pack):
        """A cinematic's scenes run their server scripts (the dialogue of the cinematic) and get their timeline's
        events at the scene's frames ([ics] scene_fps). The client plays the scene itself; this is the server half."""
        fps = float(self.ic.get("scene_fps", 30.0))
        for scene_did in self.data.cinematic_scenes(cinematic, layout_pack):
            sc = self.data.scene(scene_did)
            if not sc or not sc["script"]:
                continue
            try:
                script = V.load(sc["script"])
            except OSError:
                self.log(f"scene {scene_did:#x}: script {sc['script']:#x} not decoded")
                continue
            cw = CastWorld(self, self.champion, None)
            inst = R.Instance(script, self.champion, cw)
            for h, v in sc["vars"]:
                inst.vars[h] = v
            R.scripts_on(cw, self.champion).append(inst)
            self.scene_insts.setdefault(cinematic, []).append((inst, cw))
            inst.start()
            for frame, event in sc["events"]:
                cw.after(frame / fps, lambda inst=inst, event=event: inst.event(event))
            self.log(f"cinematic {cinematic:#x}: scene {scene_did:#x} runs script {sc['script']:#x} "
                     f"({len(sc['events'])} timed events)")

    def stop_scenes(self, cinematic):
        """The cinematic ended (or was skipped): its scene scripts stop. 2026-10-21 23:20 (tester: Superman repeats
        lines): the intro was skipped after 3 s and its script went on playing its conversations in the game."""
        for inst, cw in self.scene_insts.pop(cinematic, []):
            inst.removed = True
            running = R.scripts_on(cw, self.champion)
            if inst in running:
                running.remove(inst)

    def start_kit(self, ent):
        """Every skill script of the champion's kit runs from the start, as a state machine waiting for its
        'skill used' event (the passive works on its own)."""
        for slot in sorted(ent.kit):
            self.start_kit_slot(ent, slot)

    def start_kit_slot(self, ent, slot):
        skill = ent.kit.get(slot)
        if not skill or not skill.script:
            return
        try:
            ent.skill_insts[slot] = R.start_script(V.load(skill.script), ent, CastWorld(self, ent, skill))
        except OSError:
            self.log(f"{skill.name}: script {skill.script:#x} not decoded (python tools\\script_decoder.py all)")
        except Exception:                      # noqa: BLE001
            self.log(f"{skill.name}: script error at start\n{traceback.format_exc()}")

    def stop_kit_slot(self, ent, slot):
        """An item's skill leaves with the item: its script stops."""
        inst = ent.skill_insts.pop(slot, None)
        ent.kit.pop(slot, None)
        if inst is not None:
            running = R.scripts_on(CastWorld(self, ent, None), ent)
            if inst in running:
                running.remove(inst)

    # ---- simulation ----------------------------------------------------------------------------
    def tick(self, dt, now):
        """Move every entity one step; returns the entities whose state changed."""
        changed = []
        for ent in list(self.entities.values()) + ([self.champion] if self.champion else []):
            g = ent.__dict__.get("graph_rt") if R.GRAPH_RUNTIME else None
            if g:
                g.set_moving(ent.dest is not None)          # Propel: the graph's Lua early-outs
            pend = getattr(ent, "pending_move", None)
            if pend is not None and not self.casting_skill(ent) and not (
                    self.ic.get("basic_attack_holds_movement", True) and self._basic_attack_animating(ent)):
                ent.pending_move = None             # the move ordered during a cast (cast_holds_movement)
                if ent.alive and self.walk_to(ent, pend):
                    changed.append(ent)
            if ent.dest is not None and self._held(ent):
                ent.dest, ent.path, ent.speed = None, [], 0.0      # crowd control: it stops where it is
                changed.append(ent)
                continue
            if (ent.dest is not None and not ent.alive and ent.kind in ("champion", "unit")
                    and self.ic.get("dead_hold_still", True)):
                # tester report 2026-10-29 12:45 (AGL slid while falling): a dead body never walks; a destination set
                # anyhow ends here with a stop state ([ics] dead_hold_still)
                ent.dest, ent.path, ent.speed = None, [], 0.0
                changed.append(ent)
                continue
            if ent.kind == "unit" and ent.kit and ent.alive:
                self._unit_ai(ent)
            if ent.attack_target is not None and self.combat_frozen():
                ent.attack_target = None            # [ics] match_end_freeze_combat (2026-10-30, tester report 15:30)
            if ent.kind in ("champion", "unit") and ent.attack_target is not None and ent.alive:
                if self._attack_step(ent, now):
                    changed.append(ent)
            if ent.follow is not None and ent.follow.alive:
                ent.dest = list(ent.follow.pos)
            if ent.dest is None:
                if ent is self.champion and self.ic.get("ground_snap_standing_champion", True):
                    # 2026-10-30 (tester report 14:51 video, agl-floor-raider-pad-pct-prow.md 1): a standing champion
                    # is put back on the navmesh too (a script teleport / forced-movement end / spawn may leave the
                    # height of a clicked or scripted point); the per-tick state carries it
                    before = ent.pos[2]
                    self.snap_to_ground(ent)
                    if abs(ent.pos[2] - before) > 0.01:
                        self._ground_fix_log(ent, before, "standing")
                        changed.append(ent)
                continue
            dx, dy = ent.dest[0] - ent.pos[0], ent.dest[1] - ent.pos[1]
            dist = math.hypot(dx, dy)
            step = ent.move_speed * min(dt, 0.25)
            if dist <= max(step, 0.05):
                ent.pos = [ent.dest[0], ent.dest[1], ent.dest[2] if len(ent.dest) > 2 else ent.pos[2]]
                ent.dest, ent.speed = None, 0.0
                if ent.path:
                    ent.dest = ent.path.pop(0)        # the next corner of its path on the navmesh
                    ent.speed = ent.move_speed
            else:
                ent.heading = math.atan2(dy, dx)
                if getattr(ent, "facing_lock", None) is not None:
                    self.apply_facing_lock(ent)          # the model keeps the locked yaw (CastWorld.lock_facing)
                ent.pos = [ent.pos[0] + dx * step / dist, ent.pos[1] + dy * step / dist, ent.pos[2]]
                ent.speed = ent.move_speed
            self.snap_to_ground(ent)
            changed.append(ent)
        self._missile_hits()
        self.income(dt)
        if now >= getattr(self, "_fog_at", 0.0):
            self._fog_at = now + 0.4
            changed += self.fog()
        for bot in [e for e in self.entities.values() if getattr(e, "bot", False) and e.alive]:
            self._regen(bot, dt, now)
        ch = self.champion
        if ch and ch.max_will and ch.will < ch.max_will:
            before = int(ch.will)
            regen = ch.stats.get(STAT_WILL_REGEN) if ch.stats else None
            if regen is None:
                regen = self.ic.get("will_regen", 0) if getattr(ch, "resource_vital", 5) == 5 else 0.0
            ch.will = min(ch.max_will, ch.will + float(regen) * dt)
            if int(ch.will) != before and int(ch.will) % 5 == 0:
                self.vitals(ch)
        if ch and ch.alive and ch.max_health and ch.health < ch.max_health and ch.stats.get(STAT_HEALTH_REGEN):
            before = int(ch.health)
            ch.health = min(ch.max_health, ch.health + ch.stats[STAT_HEALTH_REGEN] * dt)
            if int(ch.health) != before and int(ch.health) % 10 == 0:
                self.vitals(ch)
        return changed

    def _regen(self, ent, dt, now):
        """A bot champion's Will / health regeneration (the local champion's rule); vitals at most [ics] bot_vitals_hz."""
        changed = False
        if ent.max_will and ent.will < ent.max_will:
            regen = ent.stats.get(STAT_WILL_REGEN) if ent.stats else None
            if regen is None:
                regen = self.ic.get("will_regen", 0) if getattr(ent, "resource_vital", 5) == 5 else 0.0
            ent.will = min(ent.max_will, ent.will + float(regen) * dt)
            changed = changed or bool(regen)
        if ent.max_health and ent.health < ent.max_health and ent.stats.get(STAT_HEALTH_REGEN):
            ent.health = min(ent.max_health, ent.health + ent.stats[STAT_HEALTH_REGEN] * dt)
            changed = True
        hz = float(self.ic.get("bot_vitals_hz", 4) or 4)
        if changed and now >= getattr(ent, "_vitals_at", 0.0) + max(0.5, 1.0 / hz):
            ent._vitals_at = now
            self.vitals(ent)

    def _unit_ai(self, ent):
        """The least a unit needs to fight (not in the data: the original server's AI is gone): attack the champion
        when it comes within [ics] unit_aggro_radius, give up past twice that. The attack itself is the unit's own
        script (its template's skill, World.start_kit)."""
        ch = self.champion
        if self._disabled(ent):
            return                            # stunned / AI suspended (SetAIEnabled) / forced movement
        # ent.aggro: the encounter's flow decides (0 = only when attacked, inf = always); None = [ics] radius
        aggro = float(self.ic.get("unit_aggro_radius", 8.0) if ent.aggro is None else ent.aggro)
        if ent.aggro is not None:
            # 2026-10-21 21:46 (tester: the drones cannot be targeted and never attack): a quiet unit still fights
            # a champion who walks up to it ([ics] unit_close_aggro)
            aggro = max(aggro, float(self.ic.get("unit_close_aggro", 3.0)))
        if ch is None or not ch.alive or ent.team == 0 or ent.team == ch.team:
            ent.attack_target = None          # neutral (the thugs) or friendly: not the champion's enemy
            return
        d = ent.distance_to(ch)
        if ent.attack_target is None and d <= aggro:
            ent.attack_target = ch
            self.log(f"{ent.name} attacks {ch.name}")
        elif ent.attack_target is not None and d > 2 * max(aggro, float(self.ic.get("unit_aggro_radius", 8.0))):
            ent.attack_target, ent.dest, ent.speed = None, None, 0.0

    def _missile_hits(self):
        """A missile flying to a point hits the first unit it passes (within 1 m) that it can collide with
        (CastWorld.collides); its script decides what the hit does (kind / relation checks)."""
        for m_ent in [e for e in self.entities.values() if e.kind == "missile" and e.follow is None]:
            missile = getattr(m_ent, "missile", None)
            if missile is None or not missile.alive or getattr(missile, "expired", False):
                continue
            hit = getattr(missile, "hit_set", set())
            # 2026-10-23 (Bat Scream at 15 m/s missed the minions it crossed): the whole stretch flown since the
            # last tick counts, not only where the missile is now
            prev = getattr(m_ent, "hit_from", None) or list(m_ent.pos)
            cur = list(m_ent.pos)
            m_ent.hit_from = cur
            near = []
            reach = self._missile_radius(missile)
            for e in list(self.entities.values()) + [self.champion]:
                if (e is None or e is m_ent or e.kind == "missile" or not e.alive or e.health is None
                        or e.eid in hit or not missile.world.collides(missile.owner, e)):
                    continue
                if _segment_distance(e.pos, prev, cur) <= reach + self._body_radius(e):
                    near.append((math.hypot(e.pos[0] - prev[0], e.pos[1] - prev[1]), e))
            for _d, e in sorted(near, key=lambda x: x[0]):
                trip = missile.trip
                hit.add(e.eid)
                missile.hit_set = hit
                missile.collide(e)
                # 2026-10-23 12:14 (tester: the batarang's bounce looked wrong): a redirected (bounce) or ended missile
                # takes no second hit in the same tick; only one flying on through its line (Bat Scream) does
                if not missile.alive or missile.trip != trip:
                    break

    def _body_radius(self, ent):
        """2026-10-28 12:2x-12:53 (tester: Grab does not always catch the enemy champion; log: about half of the casts
        aimed at Deathstroke never touched him): a missile meets a unit's body, not its centre point; the unit's own
        radius (structures / minions: match_unit.radius) or [ics] missile_target_radius by kind (0 = centre only)."""
        mu = getattr(ent, "match_unit", None)
        if mu is not None and getattr(mu, "radius", None):
            return float(mu.radius)
        table = self.ic.get("missile_target_radius") or {}
        return float(table.get(getattr(ent, "kind", ""), 0.0) or 0.0)

    def _missile_radius(self, missile):
        """How close a unit must pass to be hit: the launching skill's stat 22 (2026-10-23 16:20, tester: Bat
        Scream's wave must hit every enemy it touches; stat 22 = 3.0 on Bat Scream, 1.25 on Sonic Batarang, 1.1 on
        Bat Flight: its width / radius, P), else [ics] missile_hit_radius."""
        default = float(self.ic.get("missile_hit_radius", 1.0))
        if not self.ic.get("missile_radius_from_skill", True):
            return default
        owner = missile.owner if not isinstance(missile.owner, (int, str)) else None
        slot = missile.origin_slot
        skill = getattr(owner, "kit", {}).get(slot) if owner is not None and slot is not None else None
        if skill is None:
            return default
        rank = max(1, int((getattr(owner, "ranks", {}) or {}).get(slot, 1) or 1))
        r = skill.stat(22, rank)
        return max(default, float(r)) if r and r > 0 else default

    def _attack_step(self, ent, now):
        target = ent.attack_target
        if self._disabled(ent):
            return False
        if ent is not self.champion and self.ic.get("attack_waits_for_cast", True) and self.casting_skill(ent):
            # 2026-10-28 15:00 (tester report; test-2026-10-28-1439-sweep.md S4: AWW's basic attack started inside her
            # Savage Sweep's cast and cut it, no damage, no cooldown, recast at once): a bot's / unit's basic attack and
            # its chase (which sets dest past cast_holds_movement) wait while one of its skills is in its cast
            # ([ics] attack_waits_for_cast)
            return False
        c = self.__dict__.get("_combat")
        queued = getattr(ent, "attack_queued_until", 0.0)
        if queued and now > queued:
            ent.attack_queued_until = queued = 0.0
        if queued and self.ic.get("attack_waits_for_action_lock", True) and (self.casting_skill(ent)
                                                                             or self._skill_animating(ent)):
            # 2026-11-03 (tester report 2026-11-03 00:32: Superman's E punch has no animation; the run: its finisher graph
            # event at 00:32:34.295, the queued basic attack's 0x10000128 at .324 over it): the client holds an order
            # while a skill holds the action (full-combat-skills.md 1.4, C: 0x863860 buffers it), so the attack
            # QueueOrder 0x100000DB asks for starts when the skill's cast ends (its animation's end hook), as the bots'
            # attack_waits_for_cast. The action lock itself is not used: ics can leave one held (Wonder Woman's Q S6)
            return False
        if not target.alive or (target is not self.champion and target.eid not in self.entities):
            ent.attack_target = None
            return False
        basic = ent.kit.get(0)
        reach = basic.stat(18, 1) if basic and basic.stat(18, 1) > 0 else float(self.ic["basic_attack_range"])
        ov = (c.of(ent).stat_overrides.get(0) or {}).get(18) if c is not None and R._key(ent) in c.states else None
        if ov and float(ov) > 0 and self.ic.get("attack_range_override", True):
            # 2026-11-03 (tester report 2026-11-03 00:34: Blue Beetle's melee basic attack kept the ranged reach): his basic
            # attack 0x34000457 sets its own range with SetSkillStatOverride(IntendedRange)[-1, 18] at each re-init,
            # stat 17 (1 m) in melee form, 18 (5.25 m) in ranged ([ics] attack_range_override)
            reach = float(ov)
        radii = ent.kind == "champion" and self.ic.get("attack_range_radii", True)
        if radii:
            # 2026-10-29 tester report 18:31 (the champion chased a fleeing enemy champion inside its basic-attack
            # area without ever stopping to attack; basic-attack-chase-range.md 1, C: the client's attack validator
            # 0x9d01d0 step 11 = distance <= skill range + both collision radii 0x5897a0, the range ring 0xa39360 adds
            # the caster's): a champion's reach counts both bodies ([ics] attack_range_radii / attack_body_radius;
            # false = centre to centre, plus a structure's edge, as before)
            reach += self._attack_radius(ent) + self._attack_radius(target)
        elif self.ic.get("attack_reach_to_edge", True):
            # 2026-10-23 23:06 (tester: Atomic Green Lantern could not attack the turrets, Batman could): a structure's
            # navmesh footprint (1.6 m) keeps a short-range champion from ever reaching its centre; count the reach to
            # the target's edge, as the units do (units._reach)
            mu = getattr(target, "match_unit", None)
            reach += max(0.0, float(getattr(mu, "radius", 0.5) or 0.5) - 0.5) if mu is not None else 0.0
        dist = ent.distance_to(target)
        if dist > reach:
            k = (dist - reach * 0.8) / dist
            goal = [ent.pos[0] + (target.pos[0] - ent.pos[0]) * k, ent.pos[1] + (target.pos[1] - ent.pos[1]) * k,
                    ent.pos[2]]
            if self.nav is None or self.nav.line_clear(ent.pos, goal):
                ent.dest, ent.path = goal, []
            elif now >= getattr(ent, "repath_at", 0.0):
                ent.repath_at = now + 0.5         # a chase re-plans at most twice a second
                if not self.walk_to(ent, goal):
                    ent.dest, ent.path = goal, []     # off the mesh (a unit placed outside it): straight
            return False
        moving = ent.dest is not None
        ent.dest, ent.speed = None, 0.0
        if radii:
            ent.path = []           # in range: the rest of the chase path goes too (it is re-planned if the target leaves)
        if not (self.ic.get("attack_face_by_script", True) and ent.kind == "champion"):
            ent.heading = math.atan2(target.pos[1] - ent.pos[1], target.pos[0] - ent.pos[0])
        # 2026-11-04 (tester report 2026-11-04 00:56: he shoots with his back to the target): a champion's basic attack
        # script faces the target itself (FaceTarget($TargetIID)[1 0 0.15] in its S1, e.g. 0x34000457); the heading set
        # here first made that FaceTarget see no turn, so no facing reached the client ([ics] attack_face_by_script)
        if basic and now >= max(ent.next_attack, ent.ready_at.get(0, 0.0)):
            # the basic attack's own script sets its cooldown (1 / attack speed); next_attack only keeps the
            # orders from piling up while its cast runs
            ent.next_attack = now + 0.3
            self.cast(ent, 0, target, None)
        return moving

    def _attack_radius(self, ent):
        """A body's collision radius for the basic attack's reach (the client's 0x5897a0 = template radius x scale +
        0.05): a structure's / minion's own (match_unit.radius), else [ics] attack_body_radius by kind."""
        mu = getattr(ent, "match_unit", None)
        if mu is not None and getattr(mu, "radius", None):
            return float(mu.radius)
        table = self.ic.get("attack_body_radius") or {}
        return float(table.get(getattr(ent, "kind", ""), 0.0) or 0.0)

    # ---- skills --------------------------------------------------------------------------------
    def combat_frozen(self):
        """2026-10-30 (tester report 15:30, video: after the surrender passed the bot kept casting and attacking ~9 s and
        "killed" the player): once the match is over (Match.end sets match_ended) nothing fights any more
        ([ics] match_end_freeze_combat; docs/re-notes/bot-shop-towers-end.md 3)."""
        return bool(getattr(self, "match_ended", False)) and bool(self.ic.get("match_end_freeze_combat", True))

    def cast(self, ent, slot, target, point):
        skill = ent.kit.get(slot)
        if ent is not self.champion and self.combat_frozen():
            self.log(f"{ent.name}: cast of slot {slot} refused, the match is over")
            return False
        if skill is None or not skill.script:
            self.log(f"{ent.name}: no skill in slot {slot}")
            return False
        if getattr(ent, "carrying", None) is not None and slot == getattr(ent, "carry_slot", None) \
                and self.ic.get("liftable_props", True):
            # 2026-10-25 (crime-alley-props.md A.3): the press after a lift throws the carried object (the sub-skill's
            # second stage, played by ics/match/liftables.py), whatever the skill's own script waits for
            self.emit("throw", ent=ent, slot=slot, target=target, point=point)
            return True
        if ent is self.champion and slot and self.cast_filter is not None and not self.cast_filter(slot):
            # 2026-10-22 14:44 (tester cast D and F during the first wave): a skill whose button the tutorial has not
            # revealed yet cannot be used (the keys still reach the server while the button is hidden)
            self.log(f"{skill.name}: refused, its button is not shown yet (slot {slot})")
            return False
        now = time.time()
        inst = ent.skill_insts.get(slot)
        recast = bool(slot and self.ic.get("recast_while_waiting", True) and R.recast_window(inst))
        if slot and self.ready_at(ent, slot) > now and not recast:
            self.log(f"{skill.name}: on cooldown ({self.ready_at(ent, slot) - now:.1f} s left)")
            return False
        guard = float(self.ic.get("cast_repeat_guard", 0.4) or 0)
        last = ent.__dict__.setdefault("last_cast_at", {})
        if slot and not recast and guard > 0 and now - last.get(slot, -1e9) < guard:
            # 2026-10-25 19:28 (test-2026-10-25-1928.md 9, C logs: every R and most W presses were cast twice, the
            # second order 0.13-0.2 s later accepted because the cooldown starts only at the script's cast point)
            self.log(f"{skill.name}: repeated order ignored ({now - last[slot]:.2f} s after the last cast)")
            return False
        if inst is None:
            self.log(f"{skill.name}: its script is not running")
            return False
        if self.ic.get("validate_casts", True):
            # CanActivate 0x8709E0 with the server's state (full-combat-skills.md 1.3); the basic attack's own
            # script waits for its cooldown (IsSkillOffCooldown), so slot 0 is not refused for it
            rank = ent.ranks.get(slot, 1)
            cost = abs(skill.stat(3, rank)) if slot not in (0, 6) else 0.0
            err = self.combat.can_activate(ent, slot, cost=0.0 if recast else cost,
                                           resource=ent.will if ent.max_will else None,
                                           now=now, ignore_cooldown=slot == 0 or recast)
            if err:
                self.log(f"{skill.name}: refused, error {err:#x}")
                if ent is self.champion:
                    self.send(f"skill error {err:#x} (0x20dc)", M.skill_error(slot, err))
                    self._skill_event(ent, slot, EVENT_SKILL_INTERRUPT)
                return False
        mask = (self.ic.get("cast_target_kind_mask") or {}).get(getattr(skill, "id", "")) if slot else None
        if mask and isinstance(target, Entity):
            # 2026-10-30 tester report 15:30 (AGL's R must only be castable on enemy champions; agl-r-impact-q-e.md 3.3):
            # a unit-target order on a target whose kind flags miss the mask is refused as the client refuses an invalid
            # target (0x20DC Skill_InvalidTarget 0x1000003C) ([ics] cast_target_kind_mask)
            if not CastWorld(self, ent, None).kind_matches(target, int(str(mask), 0)):
                self.log(f"{skill.name}: refused, {target.name} is not a valid target (kind mask {int(str(mask), 0):#x})")
                if ent is self.champion:
                    self.send(f"skill error {0x1000003C:#x} (0x20dc)", M.skill_error(slot, 0x1000003C))
                    self._skill_event(ent, slot, EVENT_SKILL_INTERRUPT)
                return False
        if slot:
            self.log(f"{ent.name} casts {skill.name} (slot {slot}, script {skill.script:#x})"
                     + (f" on {target.name}" if target else "")
                     + (f" at ({point[0]:.1f}, {point[1]:.1f})" if point else ""))
        if (ent is self.champion or (getattr(ent, "bot", False) and self.ic.get("bot_cast_stop_state", True)))                 and slot and self.ic.get("cast_stop_state", True):
            # 2026-10-26 (deep-scan-animations.md 5: a bot casting while walking kept replaying its walk): bots too
            # 2026-10-25 (champion-animation-matrix.md cause 1, C path: the client keeps replaying the last walk state
            # until a newer one comes; 114 of 216 casts sent none): a stop state before the cast's scriptlets
            ent.dest, ent.path, ent.speed = None, [], 0.0
            self.update(ent, f"{ent.name} stops to cast")
        try:
            taken = R.activate(inst, target=target, point=tuple(point) if point else None)
        except Exception:                                  # noqa: BLE001
            self.log(f"{skill.name}: script error\n{traceback.format_exc()}")
            return False
        new = set(map(str, inst.unknown)) - getattr(inst, "reported", set())
        if new:
            inst.reported = getattr(inst, "reported", set()) | new
            self.log(f"{skill.name}: nodes not implemented yet: {', '.join(sorted(new))}")
        if slot and taken is False and getattr(ent, "bot", False) and ent is not self.champion \
                and self.ic.get("bot_cast_needs_taker", True):
            # 2026-10-28 15:00 (tester report; test-2026-10-28-1439-sweep.md S5: AWW "cast" W Smite 0x34000255 seven
            # times in 4.5 s while its buff 0x480006FD waited for a basic attack; its only 0x1000001D transition is gated
            # by NOT HasStatus 0x480006FD, so nothing happened and the bot never attacked): a use the script does not take
            # is no cast, and the bot leaves that slot alone [ics] bot_untaken_skill_backoff s so it attacks
            # ([ics] bot_cast_needs_taker). The stop state above stays before the activation (deep-scan-animations.md 5).
            back = float(self.ic.get("bot_untaken_skill_backoff", 1.0) or 0.0)
            if back > 0:
                ent.__dict__.setdefault("skill_backoff", {})[slot] = now + back
            self.log(f"{ent.name}: {skill.name} not taken by its script (slot {slot}): no cast"
                     + (f", the slot rests {back:g} s" if back > 0 else ""))
            return False
        if ent is self.champion and slot:
            self._skill_event(ent, slot, EVENT_SKILL_USED)
        if slot:
            ent.__dict__.setdefault("last_cast_at", {})[slot] = now
        else:
            ent.__dict__["basic_cast_at"] = now     # BotBrain.fight: [ics] bot_skill_waits_basic (S4)
        self.emit("cast", ent=ent, slot=slot, target=target, point=point)
        return True

    def _skill_event(self, ent, slot, event):
        """0x20C9 to the client's copy of the slot's skill script: 'skill used' 0x1000001D ends its range indicator
        (2026-10-23 17:40, tester: the indicator stayed until another button was clicked; the client script hides it
        only on 0x1000001D / 0x10000009, which only the server delivers). [ics] skill_used_event."""
        if self.ic.get("skill_used_event", True):
            self.send(f"skill script event {event:#x} slot {slot} (0x20c9)", M.skill_script_event(ent.eid, slot, event))

    def ready_at(self, ent, slot):
        return ent.ready_at.get(slot, 0.0)

    def immune(self, target, source, slot):
        """A target that only one skill hurts (the tutorial's practice targets: Director only_skill): damage from
        any other slot (0 = the basic attack, None = not a skill's) does nothing and raises "immune" (the flow's
        Superman lines 0x1CD / 0x1DB / 0x1B2)."""
        only = getattr(target, "only_slot", None)
        if only is None or slot == only or not self.ic.get("practice_target_only_skill", True):
            return False
        self.log(f"{target.name}: only skill slot {only} hurts it (hit by slot {slot})")
        self.emit("immune", ent=target, source=source, slot=slot)
        return True

    def _owner_entity(self, owner):
        if isinstance(owner, Entity):
            return owner
        return self.entities.get(owner) if isinstance(owner, int) else None

    def _death_events(self, target, killer):
        """2026-10-25 (kit-audit-2.md 1 / 8): a death raises 0x10000012 on the dead entity's scripts (clear stacks; 19
        scripts), 0x10000007 on each of its statuses, which then end (46 scripts), and 0x10000098 {victim 0x9A6A765} on
        the killer's scripts (Lex's drone, Green Lantern's passive, Hawkgirl W)."""
        try:
            cw = CastWorld(self, target, None)
            R.raise_event(cw, target, 0x10000012)
            defer = self.ic.get("death_status_end_after_chain", True)
            for status, insts in list(R.statuses_on(cw, target).items()):
                for inst in list(insts):
                    if defer and (inst.__dict__.get("_chain_depth", 0) or inst.__dict__.get("_run_depth", 0)):
                        # 2026-10-30 (tester, agl-r-impact-q-e.md 3.5): the death came from this status' own chain (a
                        # Meltdown pulse that kills): it ends once that chain has run, so the chain's PulsesRemaining - 1
                        # is counted before its exit chain jumps ([ics] death_status_end_after_chain)
                        if not getattr(inst, "removing", False):
                            inst.removing = True
                            cw.after(0.0, lambda i=inst, st=status: (
                                i.event(0x10000007), R.remove_status(cw, target, st, i)) if not i.removed else None)
                        continue
                    inst.event(0x10000007)
                    R.remove_status(cw, target, status, inst)
            if getattr(target, "match_unit", None) is not None and self.ic.get("run_jungle_scripts", True):
                # 2026-10-25 (map-objectives-recipes.md 4, C): a unit's own entity scripts (not its statuses) wait for
                # 0x10000007 {KillerIID} to drop their pad / reward
                own = set(self.data.entity_scripts(target.class_id))
                for inst in list(R.scripts_on(cw, target)):
                    if getattr(inst, "status", None) is None and getattr(inst.script, "did", 0) in own:
                        inst.event(0x10000007, {"KillerIID": killer if isinstance(killer, Entity) else None})
            if isinstance(killer, Entity) and killer is not target:
                R.raise_event(CastWorld(self, killer, None), killer, 0x10000098, {0x9A6A765: target})
        except Exception:                                  # noqa: BLE001
            self.log(f"{target.name}: death events failed\n" + traceback.format_exc())

    def damage(self, source, target, amount):
        if not isinstance(target, Entity) or not target.alive or target.health is None:
            return
        if self.combat_frozen():
            return                                  # the match is over ([ics] match_end_freeze_combat)
        if getattr(target, "safe_zone", False) and source is not target:
            # 2026-10-23 18:50 (tester: inside the white base zone a champion cannot be hurt): Match._auras_tick
            self.log(f"{target.name}: no damage inside the base aura")
            return
        c = self.__dict__.get("_combat")
        if (amount >= target.health and c is not None and R._key(target) in c.states and 0 in c.guarded(target)
                and self.ic.get("defeat_guard_all_damage", True)):
            # 2026-11-02 (tester report 2026-11-02 01:43: Atomic Joker's passive The Punch Line did not start when a
            # turret killed him): turrets, minions, bosses and objectives hit through here, past script_nodes.deal_damage's
            # defeat guard; a type-0 guard stops the lethal hit and raises 0x1000011B {KillerIID} the same way
            R.raise_event(CastWorld(self, target, None), target, 0x1000011B, {0x032C3FD4: source})
            amount = max(0.0, target.health - 1.0)
        target.health = max(0, target.health - amount)
        attacker = source
        if isinstance(attacker, Entity) and getattr(attacker, "missile", None) is not None:
            attacker = self._owner_entity(attacker.missile.owner) or attacker
        if (isinstance(attacker, Entity) and attacker.kind == "champion" and attacker.team != target.team
                and target.kind in ("unit", "champion")):
            # 2026-10-24 23:05 (tester: a champion hidden in a stealth zone is seen again for a moment when it attacks an
            # enemy minion or champion): [ics] match_stealth_reveal s
            self.reveal(attacker)
        if getattr(target, "in_stealth", False) and target.kind == "champion" and isinstance(attacker, Entity)                 and attacker is not target:
            # 2026-10-25 19:28 (tester: hidden until it attacks or takes damage): a hit champion is seen for a moment.
            # 2026-10-29 14:40 (tester: inside the field the enemies must lose sight of me unless I attack them or they
            # enter the field; hits already on their way still land): taking damage no longer reveals
            # ([ics] stealth_reveal_when_hit, true = as before)
            if self.ic.get("stealth_reveal_when_hit", False):
                self.reveal(target)
        # a hostile unit that is hit fights back (also one busy with someone else: the first drone and the human)
        if (target.kind == "unit" and target.kit and target.attack_target is not source and isinstance(source, Entity)
                and source is self.champion and target.team and target.team != source.team):
            target.attack_target = source
        self.log(f"{target.name} takes {amount:g} ({target.health:g}/{target.max_health})")
        self.emit("hit", ent=target, source=source)
        self.vitals(target)
        if target.health > 0:
            return
        target.alive = False
        self.log(f"{target.name} defeated")
        if self.ic.get("death_script_events", True):
            self._death_events(target, attacker)
        c = self.__dict__.get("_combat")
        if c is not None and R._key(target) in c.states:
            # a dead entity's forced movement and action locks end (its statuses run out on their own)
            st = c.of(target)
            st.motion, st.input_locks = None, 0
            st.locks.clear()
        self.emit("killed", ent=target, killer=source)
        self.bounty(source, target)
        self.experience(source, target)
        if self.champion and self.champion.attack_target is target:
            self.champion.attack_target = None
        if getattr(target, "bot", False):
            # 2026-10-25 (bot-champions.md 3.2): a bot champion keeps its object; LifeState 2 by 0x6 and the graph's
            # death machine, as the local champion's death_as_property path (Match respawns it)
            for e in list(self.entities.values()) + ([self.champion] if self.champion else []):
                if e.attack_target is target:
                    e.attack_target = None
            target.dest, target.path, target.speed, target.attack_target = None, [], 0.0, None
            # 2026-10-25 19:28 (tester: a defeated enemy champion slides across the map on the floor until it respawns):
            # the client kept dead-reckoning its last walking state; a stop state (speed 0) where it fell
            target._motion_sent = None
            # 2026-10-25 22:07 (tester: still sliding): the stop as a full bundle (the 0xB0-only state is not applied)
            # 2026-10-28 15:00 (tester report 2026-10-28 15:00; object-update-bundles.md 0.5 / 11.2: the 0xB0-only state is
            # applied, fase3-hx's stop worked): delta mode with delta_full_on_life_change = false sends it as a delta
            if self.delta_mode() and not self.life_full():
                self.update(target, f"{target.name} stops where it falls")
            else:
                self.send(f"{target.name} stops where it falls",
                          self.motion_state(target) if self.ic.get("bot_motion_only", False) and not self.delta_mode()
                          else self.bundle(target))
            self.send(f"{target.name} dead: LifeState 2 (0x6)",
                      M.set_property(target.eid, 0x100000FA, KIND_ENUM, M.LIFE_DEAD))
            # 2026-10-28 15:00 (tester report 2026-10-28 15:00; death-animation.md 9): the fall is _Defeat_OnDead
            # ([ics] death_scriptlets; the same Death state as the bare graph event, plus the death cue), at once
            self.death_fall(target)
            return
        if target is not self.champion:
            if self.ic.get("unit_death_in_place", True):
                # 2026-10-23 16:20 (tester: the drones walk away while they die): its death bundle carried the
                # movement it had; a dead unit stops where it falls
                target.dest, target.path, target.speed, target.attack_target = None, [], 0.0, None
                if hasattr(target, "lane_points"):
                    target.path = []
            self.update(target, f"{target.name} dead")
            if target.kind == "unit":
                self._unit_fall(target)
            if not getattr(target, "keep_body", False):
                self.schedule(float(self.ic["corpse_seconds"]), lambda: self.remove(target))
        else:
            for e in self.entities.values():
                if e.attack_target is target:
                    e.attack_target, e.dest, e.speed = None, None, 0.0
            # 2026-10-23 11:28 (tester: he slides while he falls): a dead champion stops where he is
            target.dest, target.path, target.speed, target.attack_target = None, [], 0.0, None
            wait = float(self.ic.get("respawn_seconds", 5.0))
            if self.ic.get("death_as_property", False):
                # 2026-10-23 09:45 (tester: at death the game froze, then he was back at the base): LifeState alone
                # (0x6). (A full bundle does not re-create a live object: object-update-bundles.md 3.)
                self.send(f"{target.name} dead: LifeState 2 (0x6)",
                          M.set_property(target.eid, 0x100000FA, KIND_ENUM, M.LIFE_DEAD))
                # 2026-10-23 10:17 (tester: Batman does not fall when he dies): the graph's death machine
                # (CbtState_Death_Induce: SM_Death, Death_A / Death_B by the Lua onStandardDeath)
                fall = True
            else:
                # 2026-10-28 15:00 (tester report 2026-10-28 15:00: no fall when killed; death-animation.md 1 / 6): the
                # LifeState 2 bundle (it carries the stop) goes even while a carry holds the champion's bundles ([ics]
                # death_bundle_force), then the fall ([ics] death_fall_local; it sat only in the branch above)
                # 2026-10-28 15:00 (object-update-bundles.md 11.3): a full bundle in delta mode too while [ics]
                # delta_full_on_life_change (the grey screen / fall with the delta form are untested); no vital-notice
                # toggles on the dead champion (as before: the respawn's send_champion sends them)
                self.update(target, f"{target.name} dead (LifeState 2)",
                            force=bool(self.ic.get("death_bundle_force", True)), full=self.life_full(), toggles=False)
                fall = bool(self.ic.get("death_fall_local", True))
            self._local_fall(target, fall)
            if self.ic.get("respawn_notices", True):
                # the dead panel counts down to the respawn (progression-meta.md 1.4; layout from static analysis)
                self.send(f"defeat status: dead for {wait:g} s (0x10000090, 0x100000bc)",
                          M.defeat_status(M.DEFEAT_DEAD, time.time() + wait) + M.defeat_status_entity(target.eid, M.DEFEAT_DEAD,
                                                                                time.time() + wait))
            self.schedule(wait, self.respawn)

    def use_object(self, ch, obj):
        """2026-10-25 16:29 (tester: a usable pad did nothing; C: the Raider drop 0x40000C49's template names a skill in
        0x100009BC, 0x480010AB: a ground area thrown from the bonus slot 9, 30 s, whose script clears slot 9 when
        done): a champion next to a usable object takes its skill into slot 9 (property 0x100008F2), the object goes."""
        if not isinstance(obj, Entity) or not obj.alive or not self.ic.get("usable_objects", True):
            return False
        from .match.unitdata import UnitData
        ud = self.__dict__.setdefault("_unitdata", UnitData(self.data))
        did = int(ud.first(obj.class_id, 0x100009BC, 0) or 0)
        if not did:
            return False
        reach = float(self.ic.get("usable_reach", 3.0))
        if ch.distance_to(obj) > reach:
            ch.dest, ch.path = None, []
            self.walk_to(ch, list(obj.pos))
            self.log(f"{ch.name} walks to {obj.name} to use it")
            return True
        sk = self.data.item_skill(did)
        if sk is None or not sk.script:
            return False
        sk.slot = BONUS_SLOT
        ch.kit[BONUS_SLOT] = sk
        ch.ranks[BONUS_SLOT] = 1
        e = self.data.record(did)
        blk = records.get(e, 0x1000003F) or records.get(e, 0x100008E5)
        from .gamedata import _wire_entries
        ch.bonus_block = _wire_entries(blk) if blk else []
        self.start_kit_slot(ch, BONUS_SLOT)
        self.remove(obj, f"{ch.name} uses {obj.name} (0x3)")
        seconds = float(sk.stat(14, 1) or 30.0)
        self.log(f"{ch.name}: bonus skill {did:#x} in slot 9 for {seconds:g} s")
        self.refresh_champion(f"{ch.name}: bonus skill (0x100008f2)") if ch is self.champion else self.update(ch)
        mark = object()
        ch.bonus_mark = mark
        self.schedule(seconds, lambda: self.clear_bonus(ch, mark))
        return True

    def clear_bonus(self, ch, mark=None):
        if mark is not None and getattr(ch, "bonus_mark", None) is not mark:
            return
        if BONUS_SLOT not in ch.kit:
            return
        self.stop_kit_slot(ch, BONUS_SLOT)
        ch.bonus_block = None
        self.log(f"{ch.name}: bonus skill gone")
        if ch is self.champion:
            self.refresh_champion(f"{ch.name}: bonus skill gone")

    def give_recall(self, ent):
        """2026-10-25 16:12 (tester: the back-to-base button does nothing; C: no champion definition has slot 6
        0x100008E4, the client sent no order): a recall skill in slot 6 running the game's recall script 0x3400000A
        (stat 14 = channel time, [ics] recall_seconds; moving 0.25 m or taking damage cancels it; S4 teleports to the
        position it had at its init event), its block sent as champion property 0x100008E4 so the HUD can use it.
        Started once the champion stands on its start point (the script takes that as home)."""
        script = int(str(self.ic.get("recall_script", "0x3400000A")), 0)
        if not script or not self.ic.get("recall_skill", True) or RECALL_SLOT in ent.kit:
            return
        from .gamedata import Skill
        seconds = float(self.ic.get("recall_seconds", 8.0))
        sk = Skill({"id": "recall:6", "slot": RECALL_SLOT, "key": "B", "name": "Recall", "script": f"0x{script:08X}",
                    "targeting": "5", "stats": f"14={seconds}"})
        ent.kit[RECALL_SLOT] = sk
        ent.ranks[RECALL_SLOT] = 1
        ent.recall_block = [(0x100000E6, KIND_ENUM, RECALL_SLOT), (0x10000328, KIND_DID, script),
                            (0x1000003D, KIND_ENUM, 5),
                            (0x100004B4, KIND_ARRAY, [(0x100004B3, KIND_TABLE,
                                                       [(0x100004D3, KIND_TABLE, [(0x100004B7, KIND_F32, seconds)]),
                                                        (0x100004B6, KIND_ENUM, 14)])])]
        icon = int(str(self.ic.get("recall_icon", 0) or 0), 0)
        if icon:
            ent.recall_block.append((0x10000302, KIND_DID, icon))
        self.start_kit_slot(ent, RECALL_SLOT)
        inst = ent.skill_insts.get(RECALL_SLOT)
        if inst is not None:
            inst.event(0x10000088)                  # S0 -> S1: HomePosition = here
        self.log(f"{ent.name}: recall in slot 6 ({seconds:g} s)")

    def reveal(self, ent):
        """A champion in a stealth strip is seen for [ics] match_stealth_reveal s: the server's visibility (Match.visible_to
        reads revealed_until) and the stealth status script's own "revealed" attribute 0x100006F3, which stops its
        effect and starts it again when cleared (0x340001CF T1 / T2)."""
        seconds = float(self.ic.get("match_stealth_reveal", 2.0) or 0)
        if seconds <= 0:
            return
        ent.revealed_until = time.time() + seconds
        if not getattr(ent, "in_stealth", False) or not self.ic.get("stealth_reveal_attribute", True):
            return
        c = self.combat
        h = getattr(ent, "_reveal_handle", None)
        if h is None:
            ent._reveal_handle = c.add_modifier(ent, 0x100006F3, 3, True, source=ent)
        mark = ent.revealed_until
        shimmer = int(str(self.ic.get("stealth_shimmer_key", 0) or 0), 0)
        if shimmer:
            # 2026-10-28 (stealth-rendering.md): the server-driven shimmer goes off while the champion is revealed
            self.signal_scriptlet(ent, shimmer)

        def clear():
            if getattr(ent, "revealed_until", 0) == mark and getattr(ent, "_reveal_handle", None) is not None:
                c.remove_modifier(ent, ent._reveal_handle, 0x100006F3)
                ent._reveal_handle = None
                if shimmer and getattr(ent, "in_stealth", False) and ent.alive:
                    self.scriptlet(ent, shimmer, f"{ent.name}: Vfx_Status_Stealth_Active again (0x8d)")
        self.schedule(seconds + 0.05, clear)

    def respawn_event(self, ent):
        """2026-10-25 (skill-mechanics-recipes.md 6, P: 10 scripts reset on it, Grundy, Zatanna): 0x10000016 respawned on
        the champion's scripts ([ics] respawn_script_event)."""
        if self.ic.get("respawn_script_event", True):
            self.schedule(0.0, lambda: self.raise_event(ent, 0x10000016))

    def respawn(self):
        """The champion back at the start with full health and Will (the original's respawn rules are not in the
        data read so far; 2026-10-21, tester: Batman died and the match could not go on)."""
        ch = self.champion
        ch.alive = True
        self.recompute_stats(ch, refill=True)
        ch.health, ch.will = ch.max_health, ch.max_will
        ch.pos = list(self.spawn_pos)
        ch.dest, ch.attack_target, ch.speed = None, None, 0.0
        ch.damage_ledger = {}                   # the kill card's damage of this life (deal_damage)
        self.log(f"{ch.name} respawns")
        self.respawn_event(ch)
        if "_combat" in self.__dict__:
            self.combat.world.on_cc(ch)        # the order lock (0x10000B2D) follows the state after death
        if self.ic.get("respawn_notices", True):
            self.send("defeat status: alive (0x10000090, 0x100000bc)",
                      M.defeat_status(M.DEFEAT_ALIVE, time.time()) + M.defeat_status_entity(ch.eid, M.DEFEAT_ALIVE, time.time()))
        if self.ic.get("death_as_property", False):
            self.send(f"{ch.name} alive: LifeState 4 (0x6)", M.set_property(ch.eid, 0x100000FA, KIND_ENUM, M.LIFE_ALIVE))
        self.vitals(ch)
        # 2026-10-23 14:01 (tester: after the respawn Batman only shows at the base once he is given an order): the
        # respawn is a teleport (seq A incremented) and goes with the player object's links ([ics] respawn_teleport)
        # 2026-10-28 15:00 (object-update-bundles.md 11.3): full in delta mode too while [ics] delta_full_on_life_change
        if self.ic.get("respawn_teleport", True):
            self.teleport(ch)
            self.send_champion(f"{ch.name} respawns (teleport {ch.tele_seq})", full=self.life_full())
        else:
            self.update(ch, f"{ch.name} respawns", full=self.life_full())
        self.get_up(ch)
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; death-animation.md 4): an opt-in death screen's run ends
        # (0x11F) after the get-up
        self.death_overlay(ch, False)

    def get_up(self, ch):
        """2026-10-23 11:28 (tester: after the respawn he stays lying down and slides until a skill is cast): the
        graph leaves the death machine (CbtState_Death_Recover), then the enter-world scriptlet plays. 2026-10-25 16:12
        (tester: the bots too): called for bot champions as well."""
        for ev in self.ic.get("respawn_graph_events") or ():
            self.graph_event(ch, int(str(ev), 0), f"{ch.name} gets up (graph event {int(str(ev), 0):#x})")
        for name in self.ic.get("respawn_scriptlets") or ():
            if self.scriptlet(ch, name, f"{ch.name}: {name} (0x8d, respawn)"):
                break


    # ---- combat (ics.combat; the script nodes' state) ---------------------------------------------------------
    @property
    def combat(self):
        """The match's combat state: attributes / modifiers, cooldowns, locks, shields, hotspots (ics/combat.py)."""
        c = self.__dict__.get("_combat")
        if c is None:
            c = self.__dict__["_combat"] = CB.Combat(None)
            c.world = CastWorld(self, self.champion, None)
            if R.FLAGS_RESOLVER is None:
                R.FLAGS_RESOLVER = lambda did, data=self.data: CB.status_flags(data, did)
            if R.RECORD_RESOLVER is None:
                R.RECORD_RESOLVER = lambda did, prop, data=self.data: CB.record_value(data, did, prop)
        return c

    def item_part(self, ent, attr):
        """The part of a champion's stat that its items give (World.recompute_stats folds them in): the stat with the
        items minus the stat without them; 0 when the stat is not an item stat or [ics] item_bonus_split is off."""
        if not self.ic.get("item_bonus_split", True):
            return 0.0
        e = ent.owner if isinstance(ent, R.Missile) else ent
        if not isinstance(e, Entity) or not getattr(e, "base_stats", None):
            return 0.0
        add, pct = getattr(e, "item_add", {}).get(attr, 0.0), getattr(e, "item_pct", {}).get(attr, 0.0)
        if not add and not pct:
            return 0.0
        base, per = e.base_stats.get(attr, (0.0, 0.0))
        naked = base + per * (e.level - 1)
        return (naked + add) * (1.0 + pct) - naked

    def _skill_animating(self, ent):
        """2026-11-03 (tester report 2026-11-03 14:40: Superman's E punch still cut; the run: the stage's cast-end signal
        came 1 ms after its finisher state and the queued attack's 0x10000128 went 30 ms before the finisher's end hook):
        the champion's animation graph (the server's copy of the original's graph) is still in a state a slot skill's
        script hooks ([ics] queued_attack_waits_graph)."""
        if not self.ic.get("queued_attack_waits_graph", True):
            return False
        g = ent.__dict__.get("graph_rt") or None
        if not g:
            return False
        return any(slot and not inst.removed and g.in_state_of(inst.script.did)
                   for slot, inst in (getattr(ent, "skill_insts", None) or {}).items())

    def _basic_attack_animating(self, ent):
        """The entity's graph is in a state its basic attack's script hooks (the swing, before its Cosmetic tail)."""
        g = ent.__dict__.get("graph_rt") or None
        inst = (getattr(ent, "skill_insts", None) or {}).get(0)
        return bool(g and inst is not None and not inst.removed and g.in_state_of(inst.script.did))

    def casting_skill(self, ent):
        """A skill of the entity (slot > 0) is in its cast (Cast node until the cast end)."""
        return any(slot and getattr(inst, "casting", 0) > 0 and not inst.removed
                   for slot, inst in (getattr(ent, "skill_insts", None) or {}).items())

    def _held(self, ent):
        """Crowd control holds the entity in place (stunned, rooted, input locked); a forced movement moves it."""
        c = self.__dict__.get("_combat")
        if c is None or R._key(ent) not in c.states:
            return False
        return not c.can_move(ent) and c.of(ent).motion is None

    def _disabled(self, ent):
        c = self.__dict__.get("_combat")
        if c is None or R._key(ent) not in c.states:
            return False
        st = c.of(ent)
        return c.stunned(ent) or st.motion is not None or bool(st.ai_off and ent.kind == "unit")

    def heal(self, source, target, amount):
        if not isinstance(target, Entity) or not target.alive or target.health is None or amount <= 0:
            return
        before = target.health
        target.health = min(target.max_health or target.health, target.health + amount)
        if target.health - before >= 1.0:
            self.queue_floaty(source, target, 0, float(target.health - before), 2)    # a green heal number
        if int(target.health) != int(before):
            self.log(f"{target.name} healed {amount:g} ({target.health:g}/{target.max_health})")
            self.vitals(target)

# 0x3B attribute formulas of the skill stats' scaling blocks (units-and-ai.md 3.4, skill-mechanics-recipes.md 4):
# formula DID -> (attribute, GetAttribute mode: 0 current / 1 bonus, sign)
STAT_SCALING_FORMULAS = {
    0x3B0002EA: (0x10000B76, 1, 1), 0x3B0002E6: (0x10000B75, 1, 1), 0x3B0002E8: (0x10000B76, 0, 1),
    0x3B000360: (0x10000B76, 0, 1), 0x3B0002EE: (0x10000B75, 1, 1), 0x3B0002E9: (0x10000B76, 1, -1),
    0x3B00010B: (0x10000426, 1, 1), 0x3B000203: (0x10000426, 0, 1), 0x3B000149: (0x10000432, 1, 1),
    0x3B0002D0: (0x10000432, 1, -1)}


class CastWorld:
    """The script runtime's World for one caster (and one skill: its stats). Combat state is the match's
    (World.combat); the hooks below turn the runtime's effects into messages (full-combat-skills.md)."""

    def __init__(self, world, caster, skill):
        self.w, self.caster, self.skill = world, caster, skill
        self.calls = 0
        self._second, self._in_second = 0, 0
        ic = world.ic
        self.poll_conditions = bool(ic.get("script_poll_conditions", True))
        self.segment_hits = False          # point skillshots hit on the way through World._missile_hits
        self.skillshot_pierce = bool(ic.get("skillshot_pierce", True))
        self.mitigation = bool(ic.get("damage_mitigation", True))
        self.neutral_hittable = bool(ic.get("neutral_hittable", False))
        world.combat                       # the match's combat state exists (and the data resolvers are set)

    @property
    def time(self):                    # the game clock the scripts' timers compare against
        return time.time()

    def now(self):
        return time.time()

    @property
    def scripts(self):                 # shared by every skill and status of the match (events between them)
        return self.w.scripts

    @property
    def statuses(self):
        return self.w.statuses

    @property
    def combat(self):
        return self.w.combat

    def log(self, text):
        if self.w.ic.get("trace_scripts", True):
            self.w.log(f"script {text}")

    def after(self, seconds, fn):
        # runaway guard (a script looping on zero delays): at most [ics] script_timers_per_second per second.
        # 2026-10-22: it was 5000 timers in total, which stopped every long-lived skill script after a few minutes
        sec = int(time.time())
        if sec != self._second:
            self._second, self._in_second = sec, 0
        self._in_second += 1
        self.calls += 1
        if self._in_second > int(self.w.ic.get("script_timers_per_second", 2000)):
            if self._in_second == int(self.w.ic.get("script_timers_per_second", 2000)) + 1:
                self.w.log(f"{getattr(self.caster, 'name', self.caster)}: script timers dropped (runaway guard)")
            return

        def run():
            try:
                fn()
            except Exception:              # noqa: BLE001
                self.w.log(f"script error\n{traceback.format_exc()}")
        self.w.schedule(max(0.01, float(seconds)), run)

    # data
    def skill_stat(self, owner, stat, rank):
        if not self.skill:
            return 0.0
        if stat == 5 and self.skill.slot == 0 and 5 not in self.skill.stats:
            if getattr(self.caster, "stats", None) and STAT_ATTACK_DAMAGE in self.caster.stats:
                return float(self.caster.stats[STAT_ATTACK_DAMAGE])
            key = "basic_attack_damage" if self.caster is self.w.champion else "unit_attack_damage"
            return float(self.w.ic.get(key, 10))
        return self.scaled_stat(self.caster, self.skill, stat, rank, self.skill.stat(stat, rank))

    def scaled_stat(self, owner, sk, stat, rank, value):
        """2026-10-25 (skill-mechanics-recipes.md 4, C layout, P modes): a stat is its base block 0x100004D3 (+ per rank)
        plus its scaling block 0x100004D4: Mod (+ per rank) x the attribute of its 0x3B formula; the plain stat read
        dropped the scaling and took the Mod as the flat value when the base block was empty ([ics]
        skill_stat_scaling = false: the plain value)."""
        if sk is None or ":" not in str(getattr(sk, "id", "")) or not self.w.ic.get("skill_stat_scaling", True):
            return value
        ent = self._ent(owner)
        if isinstance(ent, R.Missile):
            ent = ent.owner
        if not isinstance(ent, Entity):
            return value
        rec, slot = str(sk.id).split(":")[:2]
        try:
            t = self.w.stat_scaling(int(rec, 16), int(slot)).get(stat)
        except ValueError:
            return value
        if not t:
            return value
        b3, p3, mod, per, (attr, mode, sign) = t
        r = max(0, int(rank) - 1)
        a = float(self.combat.attribute(ent, attr, mode) or 0.0)
        return (b3 or 0.0) + p3 * r + sign * (mod + per * r) * a

    def skill_ref(self, owner):
        return self.skill

    def status_duration_scale(self, source, target, status):
        """2026-10-26 (items: Resilience 0x100004AA 0.15 / 0.3, full-combat-skills.md: CC reduction, P): a status an
        enemy puts on a champion lasts (1 - resilience), capped at [ics] resilience_cap (G)."""
        cap = float(self.w.ic.get("resilience_cap", 0.6) or 0)
        t, s = self._ent(target), self._ent(source)
        if isinstance(s, R.Missile):
            s = s.owner
        if cap <= 0 or not isinstance(t, Entity) or t.kind != "champion" or not isinstance(s, Entity)                 or not s.team or s.team == t.team:
            return 1.0
        res = max(0.0, min(cap, float(self.combat.attribute(t, 0x100004AA) or 0.0)))
        return 1.0 - res

    def slot_stat(self, owner, slot, stat, rank):
        """A stat of a slot of the owner's kit (LoadSkillStats reads other slots too: the passive's echo)."""
        owner = self._ent(owner)
        if isinstance(owner, R.Missile):
            owner = owner.owner
        sk = getattr(owner, "kit", {}).get(slot) if isinstance(owner, Entity) else None
        if sk is None:
            return None
        if stat == 5 and slot == 0 and 5 not in sk.stats:
            return CastWorld(self.w, owner, sk).skill_stat(owner, stat, rank)
        if self.skill is not None and sk is self.skill:
            return self.scaled_stat(owner, sk, stat, rank, sk.stat(stat, rank))
        r = owner.ranks.get(slot, 1)
        return self.scaled_stat(owner, sk, stat, r, sk.stat(stat, r))

    def slot_rank(self, owner, slot):
        owner = self._ent(owner)
        if isinstance(owner, R.Missile):
            owner = owner.owner
        return owner.ranks.get(slot, 1) if isinstance(owner, Entity) and slot in owner.ranks else None

    def skill_slot(self, owner):
        return self.skill.slot if self.skill else None

    def skill_rank(self, owner):
        return self.caster.ranks.get(self.skill.slot, 1) if self.skill else 1

    def cast_time(self, owner):
        return 0.25

    def graph_for(self, ent):
        """The entity's graph runtime (World.graph_for), for script_runtime.start_cast / deliver_hook."""
        return self.w.graph_for(self._ent(ent))

    def conversation(self, key):
        """A conversation (dialogue line with voice) from a scene script (node 0x100000D1)."""
        if self.w.ic.get("scene_conversations", False):
            self.w.say(key)
        else:
            # 2026-10-22 08:56 (tester's video: every intro conversation went by twice, the director's once): the
            # client's cinematic plays its own conversations; the scene script's copy queued behind them
            self.w.log(f"conversation {key:#x} from a scene script: played by the client's cinematic, not sent")
        self.w.emit("conversation", key=key)     # the director queues its own lines after this one

    def player(self):
        # 2026-10-25 (bot-champions.md 3.2): a bot's scripts asking for "my agent" get the bot, not the player's champion
        if getattr(self.caster, "bot", False):
            return self.caster
        return self.w.champion

    def property_kind(self, prop):
        return self.w.data.property_kind(prop)

    def item_part(self, ent, attr):
        return self.w.item_part(self._ent(ent), attr)

    def queue_floaty(self, source, target, dtype, amount, vital):
        self.w.queue_floaty(self._ent(source), self._ent(target), dtype, amount, vital)

    def base_attribute(self, ent, prop):
        """An attribute's base value: the entity's stats (champion record / unit stat block), else [ics] attributes."""
        ent = self._ent(ent)
        if not isinstance(ent, Entity):
            return None
        if prop == PROP_MOVE_SPEED:
            # the speed the server moves it at ([ics] move_speed for the champion: the walk animation's cap), not the
            # stats record's: a slow scales that
            return float(getattr(ent, "base_move_speed", ent.move_speed))
        stats = getattr(ent, "stats", None) or {}
        if prop in stats:
            return float(stats[prop])
        roles = (self.w.ic.get("role_flag_attributes") or {}).get(f"0x{prop:08X}")
        if roles is not None:
            # 2026-10-25 (stolen-powers-audit.md 3, C: Teleport 0x34000304 accepts an ally only with HasFlagAttribute
            # 0x10000B4A (T4 of the script; the audit named 0x1000104A), which nothing sets; P: the original server flagged
            # teleport-eligible allies)
            mu = getattr(ent, "match_unit", None)
            return 1.0 if mu is not None and mu.role in roles else 0.0
        if prop == ATTR_ATTACKS_PER_SECOND and STAT_ATTACK_SPEED in stats:
            # likely: the basic attack's rate attribute is the stat block's Attack Speed (Destroyer 0.59)
            return float(stats[STAT_ATTACK_SPEED])
        if prop == RANK_ELEMENT_PROPERTY:
            return float(ent.level)
        zero = self.w.ic.get("attribute_zero_defaults") or ()
        if f"0x{prop:08X}" in zero:
            # 2026-10-26 (tester: items must change the champion's stats; measured: with no item, lifesteal, cooldown
            # reduction and resilience read 1.0, World.attribute's fallback for unknown multipliers): these start at 0
            return 0.0
        table = self.w.ic.get("attributes") or {}
        key = f"0x{prop:08X}"
        if key in table or f"{prop:#x}" in table:
            return float(table.get(key, table.get(f"{prop:#x}")))
        return None

    def attribute(self, ent, prop, mode=0):
        """GetAttribute: base + modifiers (ics.combat). A number the data does not give stays 1.0 as before."""
        e = self._ent(ent)
        if isinstance(e, R.Missile):
            e = e.owner
        c = self.combat
        v = c.attribute(e, prop, mode)
        if (mode == 0 and self.base_attribute(e, prop) is None and not c.of(e).mods.get(prop)
                and prop not in c.of(e).base and c.kind(prop) != KIND_BOOL):
            return 1.0
        return v

    # entities
    def _ent(self, e):
        if isinstance(e, R.Missile):
            return getattr(e, "entity", None) or e
        return e

    def position(self, ent):
        if isinstance(ent, (tuple, list)):
            return tuple(ent)
        if isinstance(ent, R.Missile):
            return tuple(ent.entity.pos) if getattr(ent, "entity", None) else tuple(ent.pos)
        return tuple(ent.pos) if isinstance(ent, Entity) else (0.0, 0.0, 0.0)

    def heading(self, ent):
        e = self._ent(ent)
        if isinstance(e, Entity):
            if getattr(e, "facing_lock", None) is not None and getattr(e, "facing_offset", None):
                # 2026-11-02: under a facing lock the scripts' facing is the model's (Blue Beetle's E aims its four
                # shots with FindTargets' box along his facing, back toward the enemies he hops away from)
                return e.heading + getattr(e, "facing_offset", 0.0)
            return e.heading
        return math.radians(getattr(ent, "yaw", 0.0))

    def radius(self, ent):
        mu = getattr(self._ent(ent), "match_unit", None)
        if mu is not None and self.w.ic.get("attack_reach_to_edge", True):
            return max(0.5, float(getattr(mu, "radius", 0.5) or 0.5))
        return 0.5

    def alive(self, ent):
        ent = self._ent(ent)
        if isinstance(ent, R.Missile):
            return ent.alive
        return isinstance(ent, Entity) and ent.alive

    def exists(self, ent):
        ent = self._ent(ent)
        if isinstance(ent, R.Missile):
            return ent.alive
        return isinstance(ent, Entity) and (ent.eid in self.w.entities or ent is self.w.champion)

    def team(self, ent):
        ent = self._ent(ent)
        if isinstance(ent, R.Missile):
            ent = ent.owner
        return getattr(ent, "team", 0) if isinstance(ent, Entity) else 0

    def set_team(self, ent, team):
        ent = self._ent(ent)
        if isinstance(ent, Entity) and ent.team != team:
            ent.team = int(team)
            self.w.update(ent, f"{ent.name} team {team}")

    def hostile(self, a, b):
        a, b = self._ent(a), self._ent(b)
        if isinstance(a, R.Missile):
            a = a.owner
        return isinstance(a, Entity) and isinstance(b, Entity) and a.team != b.team and b.team != 0

    def hittable(self, ent):
        ent = self._ent(ent)
        return bool(getattr(ent, "hittable", False))

    def immune(self, target, source, slot):
        target = self._ent(target)
        return isinstance(target, Entity) and self.w.immune(target, self._ent(source), slot)

    def collides(self, a, b):
        """A missile of a's runs into b (full-combat-skills.md 4.1: collision is the server's, the missile script
        filters by kind / relation itself): not on a's team, collision on (DisableCollision), and a neutral only when
        neutrals are hittable ([ics] neutral_hittable) or b is (the practice targets). 2026-10-22 14:10 (tester: the
        Sonic Batarang went through the practice targets): it was hostile(), which no neutral entity passes."""
        a, b = self._ent(a), self._ent(b)
        if isinstance(a, R.Missile):
            a = a.owner
        if not isinstance(a, Entity) or not isinstance(b, Entity) or a is b:
            return False
        if not self.w.ic.get("missile_hits_neutral_targets", True):
            return self.hostile(a, b)
        rel = CB.relation(a.team, b.team)
        if rel == 4:
            return False
        if rel == 1 and not (self.neutral_hittable or b.hittable):
            return False
        c = self.w.__dict__.get("_combat")
        if c is not None and R._key(b) in c.states and c.of(b).flags.get("collision_off"):
            return False
        return True

    def kind_matches(self, ent, flags):
        ent = self._ent(ent)
        if isinstance(ent, R.Missile):
            return bool(flags & 0x20)
        if not isinstance(ent, Entity):
            return False
        # 2026-10-28 09:36 (tester: Consume on a vehicle / meteorite does not make it vanish, it can still be lifted):
        # an object's own kind flags (property 0x1000019D: rock 0x22, vehicle 0x1080) answer IsKind first; Consume
        # 0x340001C4 destroys its target only when IsKind [0x82] holds ([ics] kind_flags_from_entity)
        own = getattr(ent, "kind_flags", 0)
        if own and flags & own and self.w.ic.get("kind_flags_from_entity", True):
            return True
        if flags & 0x8 and ent.kind == "champion":
            return True
        if flags & 0x100:
            if ent.kind == "champion" and self.w.ic.get("kind_unit_excludes_champion", True):
                # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Bullseye's
                # arrow 0x3400043D takes S4 -> S8 IsKind [0x10100] (the minion hit) before S4 -> S1 IsKind [8] (the
                # champion hit: thermite + full damage)): bit 0x100 is the non-champion units; 0x108 / 0x10108 name
                # champions with bit 8 ([ics] kind_unit_excludes_champion)
                return False
            return ent.kind in ("unit", "champion")
        if flags & 0x1000:
            return ent.kind == "prop"
        if flags & 0x20:
            return ent.kind == "missile"
        return False

    def kind_of(self, ent):
        ent = self._ent(ent)
        return getattr(ent, "kind", None)

    def class_of(self, ent):
        ent = self._ent(ent)
        if isinstance(ent, R.Missile):
            return ent.cls
        return getattr(ent, "class_id", 0)

    def all_entities(self):
        out = [e for e in self.w.entities.values() if e.alive and e.kind != "missile"]
        if self.w.champion and self.w.champion.alive:
            out.append(self.w.champion)
        return out

    def find_targets(self, center, radius, flags):
        c = self.position(center)
        out = [e for e in self.w.entities.values() if e.alive and e.health is not None
               and math.hypot(e.pos[0] - c[0], e.pos[1] - c[1]) <= radius]
        ch = self.w.champion
        if ch and ch.alive and math.hypot(ch.pos[0] - c[0], ch.pos[1] - c[1]) <= radius:
            out.append(ch)
        return sorted(out, key=lambda e: math.hypot(e.pos[0] - c[0], e.pos[1] - c[1]))

    def has_status(self, ent, status):
        return bool(R.statuses_on(self, self._ent(ent)).get(status))

    def level(self, ent):
        ent = self._ent(ent)
        return getattr(ent, "level", 1) if isinstance(ent, Entity) else None

    def entity_property(self, ent, prop):
        ent = self._ent(ent)
        if not isinstance(ent, Entity):
            return None
        for p, _kind, v in ent.extra_props:
            if p == prop:
                return v
        stats = getattr(ent, "stats", None) or {}
        return stats.get(prop)

    def vision_range(self, ent):
        r = float(self.w.ic.get("champion_vision_radius", 0) or self.w.ic.get("fog_vision_radius", 0) or 0)
        return r or 10.0

    def match_time(self):
        return time.time() - getattr(self.w, "match_start", time.time())

    def ground_z(self, p):
        return self.w.ground_z or (p[2] if len(p) > 2 else 0.0)

    def walkable(self, p):
        nav = self.w.nav
        return nav.walkable(p[0], p[1]) if nav is not None else True

    def clip_line(self, a, b, margin=0.0):
        """The furthest point of a -> b that stays on the navmesh (a dash stops at walls)."""
        nav = self.w.nav
        if nav is None or nav.line_clear(a, b):
            return None
        lo, hi = 0.0, 1.0
        for _ in range(12):
            mid = (lo + hi) / 2
            p = (a[0] + (b[0] - a[0]) * mid, a[1] + (b[1] - a[1]) * mid)
            if nav.line_clear(a, p):
                lo = mid
            else:
                hi = mid
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        k = max(0.0, lo - margin / d)
        return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] if len(a) > 2 else 0.0)

    def is_moving(self, ent):
        ent = self._ent(ent)
        return isinstance(ent, Entity) and ent.dest is not None

    # vitals
    def vital(self, ent, vital, maximum=False):
        ent = self._ent(ent)
        if not isinstance(ent, Entity):
            return 0.0
        if vital == 2:
            return float((ent.max_health if maximum else ent.health) or 0.0)
        if self._is_resource(ent, vital):
            return float(ent.max_will if maximum else ent.will)
        v = self.combat.of(ent).vitals.get(vital)
        return (v[1] if maximum else v[0]) if v else 0.0

    def _is_resource(self, ent, vital):
        """The vital that is the entity's one resource bar (ent.will): its resource_vital (Will 5, Rev 6, ...); vital 1 /
        5 for an entity without one (the earlier rule)."""
        if not ent.max_will:
            return False
        rv = getattr(ent, "resource_vital", 0)
        return vital == rv if rv else vital in (1, 5)

    def set_vital(self, ent, vital, value):
        ent = self._ent(ent)
        if not isinstance(ent, Entity):
            return
        if vital == 2 and ent.max_health:
            ent.health = max(0.0, min(ent.max_health, value))
        elif self._is_resource(ent, vital):
            ent.will = max(0.0, min(ent.max_will, value))
        else:
            v = self.combat.of(ent).vitals.setdefault(vital, [0.0, 100.0])
            v[0] = max(0.0, min(v[1], value))

    def vitals_changed(self, ent):
        ent = self._ent(ent)
        if isinstance(ent, Entity):
            self.w.vitals(ent)

    def heal(self, source, target, amount):
        self.w.heal(self._ent(source), self._ent(target), amount)

    # actions
    def face(self, owner, target):
        owner = self._ent(owner)
        p = self.position(target)
        if isinstance(owner, Entity) and abs(p[0] - owner.pos[0]) + abs(p[1] - owner.pos[1]) > 1e-3:
            want = math.atan2(p[1] - owner.pos[1], p[0] - owner.pos[0])
            turn = abs((want - owner.heading + math.pi) % (2 * math.pi) - math.pi)
            if (turn < math.radians(float(self.w.ic.get("face_min_turn_degrees", 20.0) or 0.0))
                    and owner.dest is None and self.combat.of(owner).motion is None):
                # 2026-10-28 10:19 (tester: the Shards sphere still vanishes on every hit): each facing bundle re-creates
                # the champion and drops the sphere; a champion standing and already facing its target gets none
                # ([ics] face_min_turn_degrees, 0 = always as before)
                return
            owner.heading = want
            if self.combat.of(owner).motion is None:
                owner.dest, owner.speed = None, 0.0
            self.w.update(owner, f"{owner.name} faces the target")

    def lock_facing(self, owner, target, handle):
        """FaceTarget 0x1000003F with an out handle ($FacingIDVariable): the champion faces the target until ReleaseFacing
        0x10000057 frees that handle (full-combat-skills.md 1.8: "drop the facing lock created by FaceTarget so movement
        steers the champion again"). 2026-11-02 (tester report 2026-11-02 01:48: Blue Beetle's E Stick And Move goes
        facing the direction; its script 0x34000455 faces the point behind his start, StartPosition - (Target - Start),
        right after DashToPosition): a moving champion keeps the heading of travel (the client moves him along it) and
        turns only the model (facing_offset, as a held prop's spin); a standing one turns as before ([ics] facing_locks)."""
        ent = self._ent(owner)
        if not isinstance(ent, Entity) or not self.w.ic.get("facing_locks", True):
            self.face(owner, target)
            return
        moving = ent.dest is not None or self.combat.of(ent).motion is not None
        if not moving:
            self.face(owner, target)
        p = self.position(target)
        if p is None or abs(p[0] - ent.pos[0]) + abs(p[1] - ent.pos[1]) <= 1e-3:
            yaw = ent.heading + (getattr(ent, "facing_offset", None) or 0.0)
        else:
            yaw = math.atan2(p[1] - ent.pos[1], p[0] - ent.pos[0])
        tgt = self._ent(target)
        ent.facing_lock = {"handle": handle, "target": tgt if isinstance(tgt, Entity) else None, "yaw": yaw,
                           "until": time.time() + float(self.w.ic.get("facing_lock_max_seconds", 6.0) or 1e9)}
        if moving:
            if ent.dest is not None:
                ent.heading = math.atan2(ent.dest[1] - ent.pos[1], ent.dest[0] - ent.pos[0])
            self.w.apply_facing_lock(ent)
            self.w.update(ent, f"{ent.name} faces {math.degrees(yaw):.0f} deg while moving (facing lock)")

    def slot_presentation(self, ent, slot, values):
        """SetSkillStatOverride 0x100000FA on a slot: its button's fields (ics/skill_slots.py)."""
        ent = self._ent(ent)
        if isinstance(ent, Entity) and slot is not None:
            skill_slots.present(self.w, ent, slot, values)

    def clear_slot_presentation(self, ent, slot):
        ent = self._ent(ent)
        if isinstance(ent, Entity) and slot is not None:
            skill_slots.cleared(self.w, ent, slot)

    def release_facing(self, owner, handle):
        """ReleaseFacing 0x10000057: the lock of that handle ends; the champion keeps the yaw its model has."""
        ent = self._ent(owner)
        lock = getattr(ent, "facing_lock", None) if isinstance(ent, Entity) else None
        if lock is None or (handle not in (None, 0) and lock["handle"] is not handle and lock["handle"] != handle):
            return
        self.w.drop_facing_lock(ent, "released")

    def run_scriptlet(self, ent, key, target=None, variables=None):
        """variables: [(property, value)] the script passes (e.g. 0x10000030 target, 0x100009EB shot speed);
        sent as the scriptlet's variable table, typed by the property's kind (catalog properties.tsv)."""
        ent, target = self._ent(ent), self._ent(target)
        if not isinstance(ent, Entity):
            return
        # 2026-10-29 (tester report 2026-10-29 12:45: AGL's and every champion's skill animations incomplete;
        # docs/re-notes/skill-animations-vs-original.md 2.1, C traffic): the local champion's 0x8D leaves
        # champion_scriptlet_delay (+ a scheduler tick, 0.13-0.17 s) late, but the server's copy of its graph was fed at
        # once, so every hook ran that much ahead of the client's clip (Meltdown's missile was created 8 ms before the
        # client got Meltdown_Start; Grab's code 5 fired when the client's throw began). The graph is now fed when the
        # message is sent ([ics] graph_feed_at_send; false = fed at once as before)
        feed_vars = variables
        feed_later = (bool(self.w.ic.get("graph_feed_at_send", True)) and ent is self.w.champion
                      and float(self.w.ic.get("champion_scriptlet_delay", 0.06) or 0) > 0
                      and not (self.w.ic.get("scriptlet_chained") or {}).get(f"0x{key:08X}")
                      and not (self.w.ic.get("scriptlet_delays") or {}).get(f"0x{key:08X}"))
        if feed_later:
            ent.__dict__["graph_feed_pending"] = ent.__dict__.get("graph_feed_pending", 0) + 1
        else:
            self.w.graph_feed(ent, key, variables)
        live = self.w.__dict__.get("looping_scriptlets") or {}
        after = float(self.w.ic.get("resend_looping_after_scriptlet", 0.0) or 0.0)
        if after > 0 and any(eid == ent.eid and k != key and key != v[3] for (eid, k), v in live.items()):
            # 2026-10-28 12:27 (tester: the Shards sphere still vanishes while attacking; traffic: it went with each basic
            # attack's scriptlet 0x10000128, after the facing bundle had been suppressed): another scriptlet on the
            # champion ends the sphere's run on the client, so the looping key goes again after it ([ics]
            # resend_looping_after_scriptlet s, 0 = off)
            self.w.schedule(after, lambda e=ent: self.w._resend_looping(e))
        self.w.scriptlet_runs += 1
        table = []
        # 2026-10-23 16:20 (tester: turret, Batman and ranged-minion shots fly straight; projectiles-homing.md): the
        # shot scriptlets' projectile action (type 2, exec 0x673280) takes its target from variable 0x10000030 (IID)
        # and its speed from 0x100009EB (f32); without them it flies along the facing. [ics] shot_scriptlet_variables
        shots = {int(str(k), 0) for k in (self.w.ic.get("shot_scriptlet_variables") or ())}
        use = self.w.ic.get("scriptlet_variables") or key in shots
        for prop, value in (variables if use else ()) or ():
            value = self._ent(value)
            kind = self.w.data.property_kind(prop)
            if isinstance(value, Entity):
                table.append((prop, KIND_IID, value.eid))
            elif kind == KIND_F32 and isinstance(value, (int, float)):
                table.append((prop, KIND_F32, R.num(value)))
            elif kind in (KIND_INT, KIND_DID, 0x13, KIND_ENUM) and isinstance(value, (int, float)):
                table.append((prop, kind, int(value)))
            elif prop == 0x780 and isinstance(value, (int, float)):
                table.append((prop, KIND_ENUM, int(value)))      # the graph event id (graph_event's own form)
            elif kind is None and isinstance(value, int) and value >> 24 in (0x1E, 0x13, 0x18, 0x2E, 0x40, 0x48):
                table.append((prop, KIND_DID, value))            # a record DID (0x1000050A = the 0x1E fx record)
            elif kind is None and isinstance(value, float):
                table.append((prop, KIND_F32, value))
        floors = (self.w.ic.get("scriptlet_variable_floors") or {}).get(f"0x{key:08X}") or {}
        if floors:
            # 2026-10-25 (tester: no Shards of Will sphere; agl-visuals.md 3, P): the sphere shells are gated on
            # 0x1000033E (ShieldPercentage), which is 0 at base; a floor lets the first shell spawn
            fl = {int(str(k), 0): float(v) for k, v in floors.items()}
            table = [(p, k, max(v, fl[p]) if p in fl and isinstance(v, (int, float)) else v) for p, k, v in table]
            have = {p for p, _k, _v in table}
            table += [(p, KIND_F32, v) for p, v in fl.items() if p not in have]
        if isinstance(target, Entity) and not any(p == M.PROP_SCRIPT_TARGET for p, _k, _v in table):
            table.append((M.PROP_SCRIPT_TARGET, KIND_IID, target.eid))
        variables = table or None
        msg = M.start_scriptlets(ent.eid, [(key, self.w.scriptlet_runs)], 0, variables)
        self.w.live_scriptlets[(ent.eid, key)] = self.w.scriptlet_runs
        hold = ent.__dict__.pop("hold_next_scriptlet", None)
        hold_defer = None
        if hold and hold[0] == key and hold[1] > 0 and str(self.w.ic.get("start_scriptlet_hold_mode", "defer")) == "defer":
            # 2026-10-30 (tester report 15:30: the recall's six converging lights never show; core-door-regen.md 6): the
            # held run goes once, after the scriptlets of its own tick, and is never re-sent: a re-send with the same
            # run number is a signal to the live run (client-scriptlets-graphs.md 1.4, C), P what ended the fx's
            # type-3 streak object ([ics] start_scriptlet_hold_mode "defer"; "resend" = below, fase3-ij)
            hold_defer = max(0.0, float(self.w.ic.get("start_scriptlet_hold_defer", 0.12) or 0.0))
            hold = None
        if hold and hold[0] == key and hold[1] > 0:
            # tester report 2026-10-29 15:30 (recall: sound and teleport, no visual; leash-recall-turretring-campicons.md
            # 2): a StartScriptlet run held for its duration (the recall's channel fx) is a looping key until its
            # StopScriptlet: re-sent with the same run number after the scriptlets that follow it on the object
            # (resend_looping_after_scriptlet / _after_bundle), which end it on the client ([ics] start_scriptlet_hold)
            began = time.time()
            self.w.__dict__.setdefault("looping_scriptlets", {})[(ent.eid, key)] = (variables, began, began + hold[1], 0)
        label = f"{ent.name}: scriptlet {key:#x} (0x8d)"
        defer = float(self.w.ic.get("champion_scriptlet_delay", 0.06) or 0)
        # 2026-10-25 11:00 (tester: AGL's Shards of Will shows no sphere; dialog-shield-disconnect.md 2, P): its status
        # sends Shards_Active 0x10000886 then Shards_Start 0x1000088C in the same tick and a later scriptlet on the
        # object replaces the running one before the sphere's frame; such keys go later ([ics] scriptlet_delays)
        sent = self.w.__dict__.setdefault("scriptlet_sent_at", {})
        sent[(ent.eid, key)] = time.time()
        chained = (self.w.ic.get("scriptlet_chained") or {}).get(f"0x{key:08X}")
        extra = (self.w.ic.get("scriptlet_delays") or {}).get(f"0x{key:08X}")
        if chained:
            # 2026-10-25 (stubborn-visuals.md 2, P): Shards_Start 0x1000088C already chains Shards_Active 0x10000886 on
            # the client; a second copy of ours replaced the first and dropped the sphere child. Ours is dropped when
            # the chaining key reached the same object within 0.5 s ([ics] scriptlet_chained {key: chaining key})
            parent = int(str(chained), 0)

            def send_unless_chained():
                if time.time() - sent.get((ent.eid, parent), 0.0) < 0.5 + float(extra or 0):
                    self.log(f"{label} dropped (chained by {parent:#x})")
                    return
                self.w.send(label, msg)
            self.w.schedule(max(float(extra or 0), 0.05), send_unless_chained)
            return
        restart = (self.w.ic.get("scriptlet_restart") or {}).get(f"0x{key:08X}")
        if restart:
            # 2026-10-25 23:13 (tester: the Shards of Will sphere shows now but goes before the shield ends; agl-e-r.md
            # 1.5.1: Active's run ends at once on the client and takes its spawned sphere with it): the key is sent again
            # every interval s until its stop key reaches the object or max s pass ([ics] scriptlet_restart: key ->
            # [interval, stop key, max s])
            every, stop_key, most = float(restart[0]), int(str(restart[1]), 0), float(restart[2])
            began = time.time()
            self.w.__dict__.setdefault("looping_scriptlets", {})[(ent.eid, key)] = (variables, began, began + most, stop_key)

            def again():
                if time.time() - began > most or sent.get((ent.eid, stop_key), 0.0) >= began or not getattr(ent, "alive", True):
                    return
                self.w.send(None, M.start_scriptlets(ent.eid, [(key, self.w.looping_run(ent.eid, key))], 0, variables))
                self.w.schedule(every, again)
            self.w.schedule(float(extra or 0) + every, again)
        if extra:
            defer = max(defer if ent is self.w.champion else 0.0, 0.0) + float(extra)
            self.w.schedule(defer, lambda: self.w.send(label, msg))
            return
        if hold_defer is not None:
            def send_held():
                self.w.send(label + " (held, once)", msg)
                if feed_later:
                    ent.__dict__["graph_feed_pending"] = max(0, ent.__dict__.get("graph_feed_pending", 1) - 1)
                    self.w.graph_feed(ent, key, feed_vars)
            self.w.schedule(max(hold_defer, defer if ent is self.w.champion else 0.0), send_held)
            return
        if ent is self.w.champion and defer > 0:
            # a champion bundle (facing the target) re-creates the object and cuts an animation sent at the same
            # moment; the earlier server sent the champion's scriptlets 0.06 s after it (2026-10-21, tester: no
            # animations)
            if feed_later:
                def send_and_feed():
                    self.w.send(label, msg)
                    ent.__dict__["graph_feed_pending"] = max(0, ent.__dict__.get("graph_feed_pending", 1) - 1)
                    self.w.graph_feed(ent, key, feed_vars)
                self.w.schedule(defer, send_and_feed)
            else:
                self.w.schedule(defer, lambda: self.w.send(label, msg))
        else:
            if feed_later:
                ent.__dict__["graph_feed_pending"] = max(0, ent.__dict__.get("graph_feed_pending", 1) - 1)
                self.w.graph_feed(ent, key, feed_vars)
            self.w.send(label, msg)

    def stop_scriptlet(self, ent, key=None, handle=None, run=None):
        """The client stops a scriptlet run itself when its script copy runs StopScriptlet; the 0x8D form that stops a
        run by instance is not known (full-combat-skills.md S3.9): logged. run: the handle's own run (StopScriptlet)."""
        ent = self._ent(ent)
        if run is not None and key and isinstance(ent, Entity):
            # 2026-11-03 ([ics] scriptlet_handle_runs): the run the handle started, not the key's newest; the key's
            # record is dropped only when it is that run
            if self.w.live_scriptlets.get((ent.eid, key)) == run:
                self.w.live_scriptlets.pop((ent.eid, key), None)
                (self.w.__dict__.get("looping_scriptlets") or {}).pop((ent.eid, key), None)
            defer = float(self.w.ic.get("champion_scriptlet_delay", 0.06) or 0)
            if ent is self.w.champion and defer > 0 and self.w.ic.get("champion_stop_deferred", True):
                self.w.schedule(defer, lambda: self.w.signal_scriptlet(ent, key, run=run, script=True))
            else:
                self.w.signal_scriptlet(ent, key, run=run, script=True)
            return
        defer = float(self.w.ic.get("champion_scriptlet_delay", 0.06) or 0)
        if (key and isinstance(ent, Entity) and ent is self.w.champion and defer > 0
                and self.w.ic.get("champion_stop_deferred", True)):
            # 2026-10-29 (tester report 2026-10-29 12:45: Scorched Earth incomplete; traffic 12:16:49.095-.097, C: the
            # skill's Vfx_Atm_Glt_Smash_Active start left champion_scriptlet_delay late, its stop at once, so the stop
            # landed 2 ms after the start and cut the smash): the champion's stops keep the starts' delay, in order
            # ([ics] champion_stop_deferred; false = sent at once as in fase3-ig)
            if self.w.ic.get("stop_takes_run_at_call", True):
                # 2026-11-03 (tester report 2026-11-03 14:42: Blue Beetle's form effects stay; the run: the passive
                # 0x34000456 stopped and restarted 0x10000BC6 at 14:42:50.380, the deferred stop then took the NEW run's
                # record, so the buff's end at 56.231 found nothing to stop): the run to stop is the one live now, sent
                # later ([ics] stop_takes_run_at_call)
                run = self.w.live_scriptlets.pop((ent.eid, key), None)
                (self.w.__dict__.get("looping_scriptlets") or {}).pop((ent.eid, key), None)
                self.w.schedule(defer, lambda: self.w.signal_scriptlet(ent, key, run=run, script=True) or self.log(
                    f"{ent.name}: stop scriptlet {key:#x}"))
                return
            self.w.schedule(defer, lambda: self.w.signal_scriptlet(ent, key, script=True) or self.log(
                f"{ent.name}: stop scriptlet {key:#x}"))
            return
        if key and isinstance(ent, Entity) and self.w.signal_scriptlet(ent, key, script=True):
            return
        self.log(f"{getattr(ent, 'name', ent)}: stop scriptlet {key:#x}" if key else
                 f"{getattr(ent, 'name', ent)}: stop scriptlet run")

    def start_cooldown(self, owner, seconds, slot=None):
        owner = self._ent(owner)
        if not isinstance(owner, Entity) or seconds <= 0:
            return
        if slot is None:
            if not self.skill:
                return
            slot = self.skill.slot
        cap = float(self.w.ic.get("cooldown_reduction_cap", 0.4) or 0)
        if slot and cap > 0 and owner.kind == "champion":
            # 2026-10-26 (tester: items must change the champion's stats; the skills' StartCooldown takes the plain
            # duration, the original server applied cooldown reduction 0x10000B7B itself, items give 0.05-0.15):
            # duration x (1 - CDR), CDR capped at [ics] cooldown_reduction_cap (G)
            cdr = max(0.0, min(cap, float(self.combat.attribute(owner, 0x10000B7B) or 0.0)))
            seconds *= 1.0 - cdr
        end = time.time() + seconds
        self.combat.set_cooldown(owner, slot, end)
        if owner is self.w.champion:
            name = self.skill.name if self.skill else f"slot {slot}"

            def ready():
                if owner.ready_at.get(slot, 0.0) <= time.time() + 0.01:
                    self.w.send(f"{name} ready (0x20f8)", M.skill_cooldown(slot, time.time()))
            self.w.schedule(seconds + 0.05, ready)

    def cooldown_end(self, ent, slot):
        """A slot's cooldown end (game time; 0 = never started): the owner block's 0x20 + 8 x slot (Instance.get)."""
        ent = self._ent(ent)
        return float(ent.ready_at.get(slot, 0.0)) if isinstance(ent, Entity) else 0.0

    def restore_cooldown(self, owner, seconds, slot):
        """StartCooldown with an explicit slot: the slot's cooldown becomes `seconds` from now, 0 = ready (0x20F8 with
        the end time either way). 2026-11-03, [ics] slot_cooldown_vars: Blue Beetle's forms keep their own cooldowns."""
        owner = self._ent(owner)
        if not isinstance(owner, Entity) or slot is None:
            return
        now = time.time()
        end = now + max(0.0, float(seconds or 0.0))
        self.combat.set_cooldown(owner, slot, end)         # on_cooldown sends the 0x20F8

    def on_cooldown(self, ent, slot, end):
        ent = self._ent(ent)
        if not isinstance(ent, Entity):
            return
        ent.ready_at[slot] = end
        if ent is self.w.champion and getattr(ent, "carrying", None) is not None and slot == getattr(ent, "carry_slot", None) \
                and self.w.ic.get("liftable_button_ready", True):
            # 2026-10-25 22:07 (test-2026-10-25-2207.md 3: Super Strength's 90 s cooldown greyed the button at the pick-up,
            # so the throw press never came): while carrying the client shows the slot ready; the cooldown is shown when
            # the object leaves the hands (Liftables._release)
            ent.carry_cooldown_end = end
            self.w.send(f"slot {slot} kept ready while carrying (0x20f8)", M.skill_cooldown(slot, time.time()))
            self.w.emit("carry_cooldown", ent=ent, slot=slot)    # the held throw indicator follows (Liftables._hold)
            return
        if ent is self.w.champion:
            left = max(0.0, end - time.time())
            self.w.send(f"slot {slot} cooldown {left:.1f} s (0x20f8)", M.skill_cooldown(slot, end))

    def spend(self, owner, amount):
        owner = self._ent(owner)
        if isinstance(owner, Entity) and owner.max_will:
            owner.will = max(0.0, min(owner.max_will, owner.will - abs(amount)))
            self.w.vitals(owner)

    def damage(self, source, target, amount):
        self.w.damage(self._ent(source), self._ent(target), amount)

    def destroy(self, ent, delay=0.0):
        """Node DestroyEntity: the entity's _HFSM_DestroyEntityAction scriptlet, then it is removed."""
        ent = self._ent(ent)
        if not isinstance(ent, Entity) or ent is self.w.champion:
            return
        hook = getattr(ent, "on_destroy", None)
        if hook is not None:
            # a map object with its own end (a liftable: fade out, respawn later). 2026-10-29 10:23 (tester: a consumed
            # vehicle vanished a second late and with no effect): its destroy action plays now, as for any other object
            # ([ics] liftable_consume_destroy_action)
            ent.on_destroy = None
            if self.w.ic.get("liftable_consume_destroy_action", True):
                self.w.scriptlet(ent, "_HFSM_DestroyEntityAction")
            self.w.schedule(delay, hook)
            return
        self.w.scriptlet(ent, "_HFSM_DestroyEntityAction")
        linger = float((self.w.ic.get("destroy_network_linger") or {}).get(f"0x{ent.class_id:08X}", 0) or 0)
        if linger > 0:
            # 2026-11-04 (tester report 02:47: Blue Beetle's Q exploded in 5 of 13 casts; same messages and timings each
            # time; the explosion is particle 0x18000BDB (6 emitters, 0.1-0.5 s) on 0x40000CD8, removed 0.3 s after its
            # Vfx_OnCollision by DestroyEntity [0.3, 0]): experiment, P. The object leaves the server's world at the
            # script's time; its network removal (0x3) waits linger s more ([ics] destroy_network_linger {class: s})
            def gone():
                if ent.eid in self.w.entities:
                    self.w.entities.pop(ent.eid, None)
                    self.w.set_blocking(ent, False)
                    self.w.schedule(linger, lambda: self.w.send(f"{ent.name} destroyed (0x3, {linger:g} s after)",
                                                                M.remove_object(ent.eid)))
            self.w.schedule(delay, gone)
            return
        self.w.schedule(delay, lambda: self.w.remove(ent, f"{ent.name} destroyed (0x3)") if ent.eid in self.w.entities
                        else None)

    def launch_missile(self, owner, missile_class, target, speed, max_range, scripts, **extra):
        m = ObjectMissile(self, owner, missile_class, target, speed, max_range, scripts, **extra)
        m.start()
        return m

    def missile_moved(self, missile, target):
        self.log(f"missile -> {self._ent(target)}")

    # spawned objects and movement
    def spawn_entity(self, owner, cls, pos, props=None, visual=False):
        """SpawnEntity: an object of the class at the point, on the owner's team, its creator = the owner, its own
        scripts started (full-combat-skills.md 4.3)."""
        w = self.w
        if not w.ic.get("spawn_script_entities", True) or not cls:
            return None
        if f"0x{cls:08X}" in {"0x" + str(c).upper().replace("0X", "") for c in w.ic.get("spawned_skip_classes") or ()}:
            # tester report 2026-10-29 15:30: the jungle heavy drop 0x400005E1 stayed as an icon ([ics] spawned_skip_classes)
            w.log(f"spawn {cls:#x} of {getattr(self._ent(owner), 'name', '?')}: skipped ([ics] spawned_skip_classes)")
            return None
        owner = self._ent(owner)
        try:
            ent = w.spawn(cls, list(pos[:3]), heading=getattr(owner, "heading", 0.0), start=False,
                          name=f"{cls:#x} of {getattr(owner, 'name', '?')}")
        except Exception:                          # noqa: BLE001 - a class the data does not describe
            w.log(f"spawn {cls:#x}: failed\n{traceback.format_exc()}")
            return None
        ent.team = getattr(owner, "team", 0)
        if self.skill is not None and getattr(self.skill, "slot", None) is not None \
                and w.ic.get("spawned_entity_skill_slot", True):
            # 2026-11-03 (tester report 14:43: Blue Beetle's E shots hit for 0; the shot 0x340004AA loads Damage with
            # LoadSkillStats($ShooterIID)[5 1, slot -1]): a skill's spawned object reads "this slot" as the slot of the
            # skill that made it, as a missile does (_stat_slot; P) ([ics] spawned_entity_skill_slot)
            ent.slot = self.skill.slot
        if f"0x{ent.class_id:08X}" in {str(c).upper().replace("0X", "0x") for c in w.ic.get("spawned_inert_classes") or ()}:
            # 2026-10-25 23:22 (tester: the game closed after the middle camp; diag: access violation at rva 0x6B1BD9 the
            # moment AGL's W hit the jungle heavy drop 0x400005E1, which attacked him and got vitals / status icons):
            # a jungle drop / pad is a pickup object, not a fighter: no AI, no health, not hit
            ent.kind, ent.kit, ent.health, ent.max_health, ent.client_vitals = "prop", {}, None, None, False
        elif (ent.health is not None and not ent.kit and w.ic.get("spawned_need_vitals_component", True)
              and not w.vitals_component(ent)):
            # 2026-10-29 tester report 19:55 (the game closed: Arcane Supergirl's Firewall 0x40000BEF, health stat 1, no
            # PerceivedType, was hit by AGL's Scorched Earth and got 0x42; the client has no vitals component for it): a
            # spawned skill object without an attack and without a client vitals component is not a fighter: no health,
            # not hit, not killed early ([ics] spawned_need_vitals_component, false = hittable as before)
            ent.kind, ent.health, ent.max_health = "prop", None, None
        self.combat.of(ent).creator = owner
        for prop, value in props or ():
            value = self._ent(value)
            if prop == 0x1000009C and isinstance(value, (int, float)):
                ent.team = int(value)
            elif prop == RANK_ELEMENT_PROPERTY and isinstance(value, (int, float)):
                ent.level = int(value)
        if isinstance(owner, Entity) and w.ic.get("missile_creator_property", True):
            ent.extra_props.append((0x100004E2, KIND_IID, owner.eid))      # its creator (agl-visuals.md 1)
        w.dress_spawned(ent)
        if ent.team in (1, 2) and w.ic.get("spawned_entity_team", True):
            # 2026-10-26 14:48 (tester: a red "lantern" follows the champion everywhere: Arcane Zatanna's companion
            # 0x40000C25, sent with no team, so the client drew it as an enemy): its creator's team, in the bundle and
            # as a change a moment later (the team tint runs only on a change, listener 0xA813F0)
            ent.extra_props = [p for p in ent.extra_props if p[0] != 0x1000009C] + [(0x1000009C, KIND_INT, ent.team)]
            w.schedule(0.5, lambda e=ent, t=ent.team: (
                w.send(f"{e.name}: team 0 (0x6)", M.set_property(e.eid, 0x1000009C, KIND_INT, 0)),
                w.send(f"{e.name}: team {t} (0x6)", M.set_property(e.eid, 0x1000009C, KIND_INT, t)))
                if e.eid in w.entities else None)
        back = float(w.ic.get("spawn_state_backdate", 0.1) or 0.0)
        if back > 0 and not ent.speed:
            # 2026-11-04 (tester report 2026-11-04 15:23: Blue Beetle's Q explosion shown in 2 of 16 casts; diag
            # --particles: its emitter 0x18000BDB started on the client in casts it did not show; client-movement.md 0,
            # C: the client places a network object by its movement states and replays only those >= 0.1 s old, so a
            # just-created object is not placed yet when its Vfx_OnCollision arrives 5-118 ms later): the creation
            # state of a standing spawned object is stamped 0.1 s earlier (the client's replay delay)
            ent.__dict__["create_backdate"] = back
        w.update(ent, f"spawn {ent.name}")
        if not w.data.entity_scripts(ent.class_id):
            w.spawned_effects(ent)
            blast = (w.ic.get("scriptless_spawn_blast") or {}).get(f"0x{ent.class_id:08X}")
            if blast and not visual and self.skill is not None and isinstance(owner, Entity):
                self._spawn_blast(ent, owner, blast)
            life = (w.ic.get("scriptless_spawn_lifetime") or {}).get(f"0x{ent.class_id:08X}")
            if life:
                # 2026-10-25 (agl-visuals.md 2): a scriptless skill object (Scorched Earth's crater) stays forever
                # otherwise: _Hotspot_Fizzle, then removed
                w.schedule(float(life), lambda e=ent: (w.scriptlet(e, "_Hotspot_Fizzle"),
                                                      w.schedule(0.5, lambda: w.remove(e, f"{e.name} gone (0x3)")
                                                                 if e.eid in w.entities else None))
                           if e.eid in w.entities else None)
        if not visual and ent.kit and getattr(ent, "kind", "") == "unit" and w.ic.get("spawned_unit_kit", True):
            # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Star Sapphire's
            # Predator 0x400005D2, a spawned unit with an attack (template 0x10000328), logged "Attack: its script is not
            # running" at every order: World.spawn makes it with start=False and nothing started its kit) ([ics]
            # spawned_unit_kit)
            w.start_kit(ent)
        if not visual:
            for did in w.data.entity_scripts(ent.class_id):
                try:
                    # 2026-10-25 (kit-audit-2.md 12: Lex Luthor's R drones dealt 0 damage for 0 s): a spawned entity's
                    # scripts know their shooter, as a missile's do
                    R.start_script(V.load(did), ent, CastWorld(w, ent, None),
                                   initial={"ShooterIID": owner} if isinstance(owner, Entity) else None)
                except Exception as e:             # noqa: BLE001
                    w.log(f"{ent.name}: script {did:#x} not started ({e!r})")
            if w.ic.get("spawned_entity_events", True):
                # 2026-10-22 (Sonic Shell's shell 0x40000093, script 0x34000042: S0 -> S5 on 0x10000049 when it is
                # created, S5 -> S4 on 0x10000049 again when launched): a created entity's scripts get 0x10000049
                if w.ic.get("spawn_event_after_chain", True):
                    # 2026-11-03 (tester report 2026-11-03 14:43: Blue Beetle's E shots never fly; the run: each shot
                    # 0x400008C4 destroyed 77 ms after its creation): its script 0x340004AA goes S0 -> S5 -> S3 on this
                    # event and destroys itself in S3 while its TargetIID is unset; the LaunchMissile of the same chain
                    # (0x34000455) brings the target. The event now comes after the spawning chain, as the client
                    # evaluates once per update (P) ([ics] spawn_event_after_chain)
                    self.after(0.0, lambda e=ent: R.raise_event(self, e, R.EVENT_SPAWN) if e.eid in w.entities else None)
                else:
                    R.raise_event(self, ent, R.EVENT_SPAWN)
            thrown = (w.ic.get("thrown_spawn_classes") or {}).get(f"0x{ent.class_id:08X}")
            if thrown is not None:
                self._thrown_fall(ent, owner, thrown)
        return ent

    def _spawn_blast(self, ent, owner, cfg):
        """2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; skill-mechanics-recipes.md 7.3: Green
        Lantern's Light spawns 0x40000359 and Nightmare Catwoman's Inevitability 0x40000D2B, classes with no server script
        in any template or decoded tree, so nothing dealt their damage; P, not their real behaviour, which lives in records
        not decoded yet): after the spawning skill's stat `delay_stat` s, every hostile unit / champion within its stat
        `radius_stat` m takes its stat `damage_stat` as power damage ([ics] scriptless_spawn_blast: class -> stats)."""
        from . import script_nodes as N
        w, sk = self.w, self.skill
        rank = max(1, int((getattr(owner, "ranks", {}) or {}).get(sk.slot, 1) or 1))
        delay = float(sk.stat(int(cfg.get("delay_stat", 14)), rank) or cfg.get("delay", 1.0))
        radius = float(sk.stat(int(cfg.get("radius_stat", 18)), rank) or cfg.get("radius", 3.0))
        amount = float(sk.stat(int(cfg.get("damage_stat", 5)), rank) or 0.0)
        cw = CastWorld(w, owner, sk)

        def land():
            if ent.eid not in w.entities or amount <= 0:
                return
            hit = [e for e in list(w.entities.values()) + [w.champion]
                   if e is not None and e is not ent and e is not owner and e.alive and e.health is not None
                   and e.kind in ("unit", "champion") and e.distance_to(ent) <= radius + self.radius(e)
                   and cw.hostile(owner, e)]
            w.log(f"{ent.name}: blast {amount:g} within {radius:g} m on {len(hit)} target(s) ([ics] scriptless_spawn_blast)")
            for e in hit:
                N.deal_damage(cw, owner, e, amount, 2, slot=sk.slot)
        w.schedule(max(0.0, delay), land)

    def _thrown_fall(self, ent, owner, cfg):
        """2026-10-25 (stolen-powers-audit.md 3 / 5.2, C states: Meteor Drop's meteor 0x4000044F runs the thrown-object
        scripts 0x34000167 / 0x34000347, which wait for thrown 0x1000001D {shooter}, launch 0x10000049, a collision
        0x10000002 {TargetIID, CollisionPosition} and the flight's end 0x10000035; a SpawnEntity'd object gets none):
        the sequence, the fall lasting the skill's stat 19 and hitting what is within its stat 18 ([ics]
        thrown_spawn_classes: class -> {fall, radius} defaults)."""
        w = self.w
        rank = max(1, int(getattr(owner, "ranks", {}).get(getattr(self.skill, "slot", 0), 1) or 1)) if self.skill else 1
        fall = (self.skill.stat(19, rank) if self.skill else 0) or float(cfg.get("fall", 2.0))
        radius = (self.skill.stat(18, rank) if self.skill else 0) or float(cfg.get("radius", 3.0))
        R.raise_event(self, ent, 0x1000001D, {0x9A6A765: owner})
        R.raise_event(self, ent, 0x10000049)

        def land():
            if ent.eid not in w.entities:
                return
            hit = sorted((e for e in list(w.entities.values()) + [w.champion]
                          if e is not None and e is not ent and e.alive and e.health is not None
                          and e.distance_to(ent) <= radius and self.collides(owner, e)),
                         key=lambda e: e.distance_to(ent))
            for e in hit:
                R.raise_event(self, ent, 0x10000002, {0x632FE62: e, 0x33016EE: tuple(ent.pos)})
            R.raise_event(self, ent, 0x10000035)
        w.schedule(float(fall), land)

    def move(self, ent, pos, speed=0.0, teleport=False, quiet=False):
        """Forced movement: walk at speed to pos (a dash / knockback), or put the entity there (teleport)."""
        ent = self._ent(ent)
        if isinstance(ent, R.Missile):
            ent.pos = tuple(pos)
            return
        if not isinstance(ent, Entity):
            return
        if speed > 0 and not teleport:
            if not hasattr(ent, "saved_move_speed"):
                ent.saved_move_speed = ent.move_speed
            ent.move_speed = speed
            ent.dest, ent.path = [pos[0], pos[1], pos[2] if len(pos) > 2 else ent.pos[2]], []
            ent.attack_target = None if ent.kind == "champion" else ent.attack_target
            return
        ent.pos = [pos[0], pos[1], pos[2] if len(pos) > 2 else ent.pos[2]]
        ent.dest, ent.path, ent.speed = None, [], 0.0
        if not quiet and ent.kind == "champion" and self.w.ic.get("script_teleport_snaps", True):
            # 2026-10-25 19:28 (tester: after the recall the champion's image stays where the recall began until a
            # click; the camera too): a script teleport (recall, Teleport) is a newer teleport sequence, which makes the
            # client snap; the local champion goes with its player links, as at the respawn
            self.w.teleport(ent)
            ent._motion_sent = None
            if ent is self.w.champion:
                self.w.send_champion(f"{ent.name} teleported (teleport {ent.tele_seq})")
                return
        if quiet and getattr(ent, "bot", False) and self.w.ic.get("pulled_champion_snaps", True):
            # 2026-10-25 22:07 (test-2026-10-25-2207.md 2: a champion Grab hits is not pulled): a remote champion's
            # bundle position is applied only with a newer teleport sequence (the recall's fix), so each drag step snaps
            self.w.teleport(ent)
            ent._motion_sent = None
        if not quiet or ent.kind != "prop":
            self.w.update(ent, None if quiet else f"{ent.name} teleported")

    def motion_end(self, ent, dest):
        ent = self._ent(ent)
        if not isinstance(ent, Entity):
            return
        if hasattr(ent, "saved_move_speed"):
            ent.move_speed = ent.saved_move_speed
            del ent.saved_move_speed
        if dest is not None:
            ent.pos = [dest[0], dest[1], dest[2] if len(dest) > 2 else ent.pos[2]]
        ent.dest, ent.path, ent.speed = None, [], 0.0
        self.w.update(ent, f"{ent.name} stops (forced movement ended)")

    def stop(self, ent):
        ent = self._ent(ent)
        if isinstance(ent, Entity):
            ent.__dict__["ai_move_token"] = ent.__dict__.get("ai_move_token", 0) + 1
        if isinstance(ent, Entity) and (ent.dest is not None or ent.speed):
            ent.dest, ent.path, ent.speed = None, [], 0.0
            self.w.update(ent, f"{ent.name} stops")

    def ai_move(self, mover, target, distance):
        mover = self._ent(mover)
        if isinstance(mover, Entity) and mover.kind == "champion" and self.w.ic.get("ai_move_champion", True):
            self._ai_chase(mover, self._ent(target), distance)
            return
        if not isinstance(mover, Entity) or mover.kind == "champion":
            return
        p = self.position(self._ent(target))
        self.w.walk_to(mover, list(p))

    def _ai_chase(self, mover, target, distance, step=0.1, limit=10.0):
        """2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Atomic Wonder Woman's
        Reclaimer 0x34000253 S1 runs at its target with AIMoveTo(-, MaxDistance, TargetIID, SELF) and hits in S2, entered
        on 0x1000009D; a champion mover was ignored, so she never arrived): the champion runs at the target (a point or a
        unit it follows) and 0x1000009D is raised on its scripts when it is within reach; StopAction on the move's handle
        or the script's own timers end it ([ics] ai_move_champion)."""
        w = self.w
        token = mover.__dict__.get("ai_move_token", 0) + 1
        mover.__dict__["ai_move_token"] = token
        reach = max(float(distance or 0.0), 0.0)
        start = time.time()

        def tick():
            if mover.__dict__.get("ai_move_token") != token or not mover.alive or time.time() - start > limit:
                return
            if isinstance(target, Entity) and not target.alive:
                return
            p = self.position(target)
            gap = math.hypot(p[0] - mover.pos[0], p[1] - mover.pos[1])
            if isinstance(target, Entity):
                gap -= self.radius(target) + self.radius(mover)
            if gap <= max(reach, 0.25):
                mover.dest, mover.path, mover.speed = None, [], 0.0
                mover.__dict__["ai_move_token"] = token + 1
                R.raise_event(self, mover, 0x1000009D)
                return
            mover.dest, mover.path = [p[0], p[1], mover.pos[2]], []
            w.schedule(step, tick)
        tick()

    def ai_target(self, unit, target, mode):
        unit, target = self._ent(unit), self._ent(target)
        if isinstance(unit, Entity) and unit.kind == "unit" and isinstance(target, Entity) and target.alive:
            unit.attack_target = target

    def queue_order(self, ent, target, slot):
        """QueueOrder after a leap / dash: the champion goes on attacking the skill's target (P)."""
        ent, target = self._ent(ent), self._ent(target)
        if (slot == 0 and isinstance(ent, Entity) and isinstance(target, Entity) and target.alive
                and self.hostile(ent, target)):
            ent.attack_target = target
            # 2026-11-03: this queued attack waits for the skill's EndSkill (World._attack_step); only a queued one, and
            # at most [ics] queued_attack_lock_wait s (ours, a safety: Wonder Woman's Q 0x34000185 can stay in S6 with
            # the lock in ics)
            ent.attack_queued_until = time.time() + float(self.w.ic.get("queued_attack_lock_wait", 2.0) or 0.0)

    def slot_instance(self, ent, slot):
        ent = self._ent(ent)
        return ent.skill_insts.get(slot) if isinstance(ent, Entity) else None

    def slot_of_script(self, ent, did):
        ent = self._ent(ent)
        for slot, sk in sorted(getattr(ent, "kit", {}).items()):
            if sk and sk.script == did:
                return slot
        return None

    def skill_targeting(self, ent, slot):
        ent = self._ent(ent)
        sk = getattr(ent, "kit", {}).get(slot)
        return sk.targeting if sk else 0

    def set_slot_skill(self, ent, slot, did):
        """SetSlotSkill 0x10000089 (skill-mechanics-recipes.md 2, C slot / revert, P stat merge): the slot runs the
        record's skill (its stats over the base slot's) beside the base instance, which keeps running; a record without
        a script keeps the slot's running state machine and only overlays its stats. 0x100000A9 {SkillSlot, script}
        after the swap. [ics] set_slot_skill = false: logged only (fase3-hs)."""
        w = self.w
        ent = self._ent(ent)
        if not isinstance(ent, Entity) or not w.ic.get("set_slot_skill", True) or slot is None:
            return False
        sk = w.data.item_skill(did)
        base = ent.__dict__.setdefault("slot_base", {})
        cur = ent.kit.get(slot)
        if not sk or not sk.script:
            if cur is None:
                return True
            if slot not in base:
                base[slot] = (cur, ent.skill_insts.get(slot))
            new = copy.copy(base[slot][0])
            new.stats = dict(new.stats)
            if sk:
                new.stats.update(sk.stats)
            ent.kit[slot] = new
            inst = ent.skill_insts.get(slot)
            if inst is not None:
                inst.world.skill = new
            w.log(f"{ent.name}: slot {slot} -> {did:#x} (no script: same state machine, stats overlaid)")
            skill_slots.swapped(w, ent, slot, did)
            return True
        new = copy.copy(sk)
        new.slot = slot
        if slot in base:
            self._stop_slot_instance(ent, slot)           # already swapped: the current override goes first
        else:
            base[slot] = (cur, ent.skill_insts.get(slot))
        if base[slot][0] is not None:
            new.stats = dict(base[slot][0].stats)
            new.stats.update(sk.stats)
        ent.kit[slot] = new
        cw = CastWorld(w, ent, new)
        try:
            ent.skill_insts[slot] = R.start_script(V.load(new.script), ent, cw, slot=slot)
        except Exception:                          # noqa: BLE001
            w.log(f"{ent.name}: slot {slot} swap to {did:#x} failed\n{traceback.format_exc()}")
            return True
        w.log(f"{ent.name}: slot {slot} -> {did:#x} (script {new.script:#x})")
        skill_slots.swapped(w, ent, slot, did)
        R.raise_event(cw, ent, 0x100000A9, {"SkillSlot": slot, 0x31D944: slot, 0x17AF14: new.script})
        return True

    def _stop_slot_instance(self, ent, slot):
        inst = ent.skill_insts.get(slot)
        if inst is not None:
            inst.removed = True
            running = R.scripts_on(CastWorld(self.w, ent, None), ent)
            if inst in running:
                running.remove(inst)

    def revert_slot_skill(self, ent, slot):
        """ClearSkillStatOverride 0x1000008E on a swapped slot: the base skill and its instance come back."""
        ent = self._ent(ent)
        base = getattr(ent, "slot_base", {}) if isinstance(ent, Entity) else {}
        if slot not in base:
            return
        sk, inst = base.pop(slot)
        if ent.skill_insts.get(slot) is not inst:
            self._stop_slot_instance(ent, slot)
        if sk is not None:
            ent.kit[slot] = sk
        if inst is not None:
            ent.skill_insts[slot] = inst
        self.w.log(f"{ent.name}: slot {slot} restored ({sk.script if sk else 0:#x})")
        skill_slots.reverted(self.w, ent, slot)
        R.raise_event(CastWorld(self.w, ent, None), ent, 0x100000A9,
                      {"SkillSlot": slot, 0x31D944: slot, 0x17AF14: sk.script if sk else 0})

    # combat hooks (ics.combat)
    def on_modifier(self, ent, attr, mod, added, value):
        ent = self._ent(ent)
        w = self.w
        if not isinstance(ent, Entity) or not w.ic.get("attribute_modifier_messages", True):
            return
        if not (ent is w.champion or getattr(ent, "client_vitals", False)):
            return                          # only objects with an attribute component (champion, variants)
        floaty = (w.ic.get("cc_floaty_status") or {}).get(f"0x{attr:08X}")
        if (added and floaty and (attr != 0x100005E4 or float(getattr(mod, "value", 0) or 0) < 0)
                and (ent is w.champion or not w.ic.get("cc_floaty_local_only", True))):
            # 2026-10-26 (deep-scan-s2c.md 2, C: the client shows "Stunned" / "Rooted" / ... over a head only on the
            # server's 0x20BD): a CC attribute modifier added -> its floaty status ([ics] cc_floaty_status: attr -> type)
            w.send(f"{ent.name}: floaty status {int(floaty)} (0x20bd)", M.floaty_status(ent.eid, int(floaty)))
        kind = self.combat.kind(attr)
        if kind not in (KIND_BOOL, KIND_F32, KIND_INT, 0x13, KIND_DID):
            return
        src = self._ent(mod.source)
        sid = src.eid if isinstance(src, Entity) else 0
        if added:
            w.send(f"{ent.name}: modifier {attr:#x} op {mod.op} = {mod.value} (0x20f0)",
                   M.attribute_modifier_add(ent.eid, attr, sid, mod.handle.n, mod.op, kind, mod.value, mod.team))
        else:
            w.send(f"{ent.name}: modifier {attr:#x} removed (0x20e8)",
                   M.attribute_modifier_remove(ent.eid, attr, mod.handle.n))

    def on_attribute(self, ent, attr, old, new):
        e = self._ent(ent)
        w = self.w
        if isinstance(e, Entity):
            if attr in CB.CC_FLAGS or attr == CB.ATTR_CANNOT_ACT:
                if w.ic.get("cc_property_events", True) and (e is w.champion or getattr(e, "client_vitals", False)):
                    if attr != CB.ATTR_CANNOT_ACT:
                        w.send(f"{e.name}: {attr:#x} = {int(bool(new))} (0x6)",
                               M.set_property(e.eid, attr, KIND_BOOL, 1 if new else 0))
                self.on_cc(e)
            elif attr == PROP_MOVE_SPEED:
                if not hasattr(e, "base_move_speed"):
                    e.base_move_speed = e.move_speed
                speed = max(0.0, float(new))
                if hasattr(e, "saved_move_speed"):
                    e.saved_move_speed = speed      # a dash is running: its end restores the slowed speed
                else:
                    e.move_speed = speed
                    if (w.ic.get("slow_motion_update", True) and e is not w.champion and float(e.speed or 0) > 0
                            and e.dest is not None and self.combat.of(e).motion is None):
                        # 2026-10-29 tester report 2026-10-29 14:40 (R / Rads Sickness: the target is not slowed;
                        # agl-qer-lift.md 3.3): a walking unit / bot gets its movement state with the new speed at
                        # once, not at its next throttled update ([ics] slow_motion_update)
                        e.speed = speed
                        w.update(e, f"{e.name} move speed {speed:.2f}")
        # OnAttributeChanged (0x100000B1): event 0x100000A2 {attribute} on the entity's scripts, posted (not nested)
        self.after(0.0, lambda: R.raise_event(self, ent, R.EVENT_ATTRIBUTE, {R.PARAM_ATTRIBUTE: attr}))

    def on_cc(self, ent):
        """Crowd control changed: stop the entity, drop its attack, lock the client's orders (0x10000B2D)."""
        e = self._ent(ent)
        w = self.w
        if not isinstance(e, Entity):
            return
        c = self.combat
        st = c.of(e)
        disabled = c.stunned(e) or st.motion is not None
        held = disabled or c.flag(e, CB.ATTR_ROOTED) or st.input_locks > 0
        if held and st.motion is None and (e.dest is not None or e.speed):
            e.dest, e.path, e.speed = None, [], 0.0
            w.update(e, f"{e.name} stopped (crowd control)")
        if disabled and c.stunned(e):
            e.attack_target = None
        if e is w.champion and w.ic.get("cc_cannot_act", True):
            want = bool(disabled or c.flag(e, CB.ATTR_CANNOT_ACT))
            if want != getattr(e, "sent_cannot_act", False):
                e.sent_cannot_act = want
                w.send(f"{e.name}: cannot act = {int(want)} (0x6 0x10000B2D)",
                       M.set_property(e.eid, CB.ATTR_CANNOT_ACT, KIND_BOOL, 1 if want else 0))

    def cast_bar(self, owner, seconds, phase):
        """The cast bar (Usage component): 0x2077 at the start (with the agent's f32 0x100004FD = the cast time),
        0x20CE when complete, 0x2096 when cancelled. Only for casts of at least [ics] cast_bar_min_seconds."""
        owner = self._ent(owner)
        w = self.w
        if owner is not w.champion or seconds < float(w.ic.get("cast_bar_min_seconds", 0.5) or 1e9):
            return False
        if phase == "start":
            w.send(f"cast bar {seconds:g} s (0x6 0x100004FD + 0x2077)",
                   M.set_property(owner.eid, 0x100004FD, KIND_F32, float(seconds)) + M.induction(owner.eid, 0.0))
        elif phase == "complete":
            w.send("cast bar complete (0x20ce)", M.induction_complete(owner.eid))
        else:
            w.send("cast bar cancelled (0x2096)", M.induction_cancelled(owner.eid))
        return True

    def status_mirror(self, ent, inst, add):
        e = self._ent(ent)
        w = self.w
        if not w.ic.get("status_mirror", False) or not isinstance(e, Entity):
            return
        if not (e is w.champion or getattr(e, "client_vitals", False)):
            return
        if add:
            w.send(f"{e.name}: effect {inst.script.did:#x} (0x200f)", M.effect_add(e.eid, inst.guid, inst.script.did))
        else:
            w.send(f"{e.name}: effect {inst.script.did:#x} ends (0x202b)", M.effect_remove(e.eid, inst.guid))

    def message(self, what, ent=None, **d):
        """The messages of the script nodes (ics/script_nodes.py), by kind."""
        w = self.w
        e = self._ent(ent)
        ch = w.champion
        eid = e.eid if isinstance(e, Entity) else 0
        name = getattr(e, "name", e)
        if what == "skill_error":
            if e is ch:
                w.send(f"skill error {d['error']:#x} slot {d['slot']} (0x20dc)", M.skill_error(d["slot"], d["error"]))
        elif what == "resource_error":
            if e is ch:
                w.send(f"not enough resource, slot {d['slot']} (0x2092)", M.skill_resource_error(d["slot"], d["kind"]))
        elif what == "disable_condition":
            if e is ch:
                w.send(f"skill condition {d['error']:#x} slot {d['slot']} {'on' if d['add'] else 'off'} (0x20a0)",
                       M.skill_disable_condition(d["slot"], d["error"], d["handle"].n, eid, d["add"]))
        elif what == "usable_override":
            if e is ch:
                w.send(f"slot {d['slot']} usable override {d['enable']} (0x207b)",
                       M.skill_usable_override(eid, d["slot"], d["enable"], d["flag"]))
        elif what == "ui_overlay":
            if e is ch:
                w.send(f"slot {d['slot']} overlay {d['overlay']} {d['on']} (0x1000015a)",
                       M.skill_ui_overlay(d["slot"], d["overlay"], d["on"]))
        elif what.startswith("icon_"):
            if not w.ic.get("status_icons", True) or not isinstance(e, Entity):
                return
            if not (e is ch or getattr(e, "client_vitals", False)):
                return
            h = d.get("handle")
            src = self._ent(d.get("source"))
            sid = src.eid if isinstance(src, Entity) else 0
            dur = float(d.get("duration") or 0.0)
            end = time.time() + dur if dur > 0 else 0.0
            if what == "icon_add":
                w.send(f"{name}: status icon {d['icon']:#x} (0x20c8)",
                       M.status_icon_add(eid, d["icon"], h.n, d.get("stacks", 0), sid, end, dur,
                                         d.get("priority", 0xFFFFFFFF)))
            elif what == "icon_update":
                w.send(f"{name}: status icon update (0x20a8)",
                       M.status_icon_update(eid, h.n, d.get("stacks", 0), sid, end, dur))
            elif what == "icon_remove":
                w.send(f"{name}: status icon removed (0x20e9)", M.status_icon_remove(eid, h.n))
            elif what == "icon_stats":
                w.send(f"{name}: status icon tooltip (0x20d0)", M.status_icon_tooltip(eid, h.n, d["icon"], d["pairs"]))
            elif what == "icon_refresh":
                w.send(f"{name}: status icon refresh (0x2127)", M.status_icon_refresh(eid, h.n))
        elif what == "floaty_status":
            if isinstance(e, Entity):
                w.send(f"{name}: floaty status {d['kind']} (0x20bd)", M.floaty_status(eid, d["kind"]))
        elif what == "teleport_effects":
            if e is ch:
                w.send(f"teleport effects {'start' if d['on'] else 'stop'}", M.teleport_effects(eid, d["on"]))
        elif what == "root_counter":
            if e is ch:
                w.send(f"root counter {d['on']} (0x2198)", M.root_counter(eid, d["on"]))
        elif what == "set_property":
            if isinstance(e, Entity):
                w.send(f"{name}: {d['prop']:#x} = {d['value']} (0x6)", M.set_property(eid, d["prop"], d["kind"], d["value"]))
        elif what == "currency":
            if e is ch and d.get("amount"):
                ch.gold += float(d["amount"])
                w.refresh_champion(f"credits +{d['amount']:g} (script)")
        elif what == "destruction":
            if not isinstance(e, Entity):
                return
            pos = w.wire_position(Entity(0, "", 0, d["pos"]))
            if d["shape"] == 2:
                half = (max(d["dim_x"], 0.1) / 2, max(d["length"], 0.1) / 2, max(d["dim_z"], 0.1) / 2)
                msg = M.destruction_box(eid, pos, half, d["magnitude"], d["level"], d["key"], d["fx"], d["flag"])
            else:
                msg = M.destruction_sphere(eid, pos, max(d["radius"], 0.1), d["magnitude"], d["level"], d["key"],
                                           d["fx"], d["flag"])
            if w.ic.get("destruction_events", False):
                w.send(f"{name}: destruction impulse (0x{'1' if d['shape'] == 2 else '8a'})", msg)
            else:
                self.log(f"{name}: destruction impulse (not sent: [ics] destruction_events)")
        else:
            self.log(f"{name}: {what} " + " ".join(f"{k}={v}" for k, v in d.items()))


def _segment_distance(p, a, b):
    """2D distance from point p to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-9 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dy * t))


class ObjectMissile(R.Missile):
    """A missile that is also an object of its class on the client (its model and effects come with it)."""

    def start(self):
        w = self.world.w
        self.entity = None
        carried = self.world._ent(self.carried) if self.carried is not None else None
        if isinstance(carried, Entity):
            # LaunchMissile of an entity SpawnEntity made (op0): that object flies (2026-10-22)
            self.entity = carried
            carried.kind = "missile"
            carried.move_speed = self.speed
            carried.missile = self
        elif w.ic.get("missile_objects", True):
            owner = self.world._ent(self.owner)
            # origin: a missile shot for its applier from a status' owner starts there (Missile.pos; 2026-10-28 15:00,
            # tester report 2026-10-28 15:00, meltdown-moving-target.md 6.2: Meltdown's jump); team and 0x100004E2 stay
            # the shooter's
            from_origin = getattr(self, "origin", None) is not None
            pos = list(owner.pos) if isinstance(owner, Entity) and not from_origin else list(self.pos)
            pos[2] += 1.0
            ent = Entity(w.new_id(), f"missile {self.cls:#x}", self.cls, pos, team=getattr(owner, "team", 0),
                         kind="missile")
            ent.move_speed = self.speed
            ent.module = (1, 1)
            if isinstance(owner, Entity) and w.ic.get("missile_creator_property", True):
                # 2026-10-25 (tester: Grab never shows AGL's arm; agl-visuals.md 1, C): the missile's Vfx_Active beam
                # (scriptlet action type 2, exec 0x673280) ends at the object's own 0x100004E2 = its creator; the same
                # binding draws 271 tethers / lassos / returning shots across the packs
                ent.extra_props.append((0x100004E2, KIND_IID, owner.eid))
            w.dress_spawned(ent)
            w.add(ent)
            self.entity = ent
            w.update(ent, f"missile {self.cls:#x} created")
            w.spawned_effects(ent)
        super().start()

    def set_speed(self, speed):
        if self.entity is not None and speed > 0:
            self.entity.move_speed = speed
        super().set_speed(speed)

    def fly_to(self, target):
        t = self.world._ent(target)
        if not isinstance(t, Entity) and self.max_range:
            # aimed at a point: it flies on in that direction to the end of its range (2026-10-21, tester: the
            # batarang thrown at the ground stopped at the cursor), hitting what it meets (World.tick)
            here = self.entity.pos if self.entity is not None else list(self.pos)
            p = self.world.position(target)
            dx, dy = p[0] - here[0], p[1] - here[1]
            d = math.hypot(dx, dy) or 1.0
            left = max(0.5, self.max_range - self.flown)
            target = (here[0] + dx / d * left, here[1] + dy / d * left, here[2])
        if self.entity is not None:
            if isinstance(t, Entity):
                self.entity.follow = t
            else:
                self.entity.follow, self.entity.dest = None, list(self.world.position(target))
            self.entity.missile = self
        super().fly_to(target)

    def end(self, trip):
        was = self.alive
        super().end(trip)
        if was and not self.alive and self.entity is not None:
            self.entity.follow = self.entity.dest = None
            ent, w = self.entity, self.world.w
            if ent.eid not in w.entities:
                return
            if self.carried is not None and w.ic.get("spawned_entity_events", True):
                # a launched entity stays where it landed: its own script removes it (Sonic Shell explodes, then
                # DestroyEntity(SELF)); a fallback removes one whose script never does
                ent.speed = 0.0
                w.schedule(float(w.ic.get("launched_entity_linger", 5.0)),
                           lambda: w.remove(ent, f"{ent.name} gone (0x3)") if ent.eid in w.entities else None)
                return
            w.remove(ent, f"missile {self.cls:#x} gone (0x3)")
