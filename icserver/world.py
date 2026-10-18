"""Per-match world state: the controlled champion's walk and the server-side
entities (drones, scenery) with a minimal combat model."""
import math


class Mover:
    """Straight-line walk toward the clicked point (server-driven, like the
    old server). Positions are in the spawn landblock's frame."""

    def __init__(self, spawn, speed):
        self.spawn = tuple(spawn)
        self.pos = list(spawn[4:7])
        self.target = None
        self.heading = 0.0
        self.speed = 0.0
        self.move_speed = speed
        self.tele_seq = 1
        self.arrived = False
        self.ground_z = 0.0      # > 0: clicked heights near it are snapped to it
        # name -> (cx, cy, half_length, half_width, yaw): areas Batman cannot walk
        # into (the server moves him in straight lines, so without these he walks
        # through anything; 2026-10-14: the street vehicle must block the way)
        self.obstacles = {}
        self.radius = 0.6

    def place(self, xyz, heading):
        """Teleport (new teleport sequence so the client snaps instead of walking)."""
        self.pos, self.target, self.speed, self.heading = list(xyz), None, 0.0, heading
        self.tele_seq = (self.tele_seq % 255) + 1

    def position(self):
        return self.spawn[:4] + tuple(self.pos)

    def order(self, target):
        """target = (region, lb_x, lb_y, x, y, z) from the client; False if rejected."""
        if not target or target[0] != self.spawn[0]:
            return False
        z = target[5]
        # The clicked height creeps up from click to click (2026-10-14: 200.0 ->
        # 201.7 on the same street, Batman floating over the ground). The
        # tutorial street is flat: snap heights close to the ground.
        if self.ground_z and abs(z - self.ground_z) < 3.0:
            z = self.ground_z
        self.target = [(target[1] - self.spawn[1]) * 160.0 + target[3],
                       (target[2] - self.spawn[2]) * 160.0 + target[4], z]
        return True

    def tick(self, dt):
        """Advance; True when the position changed (an update must be sent)."""
        if self.target is None:
            return False
        dt = min(dt, 0.25)
        px, py, pz = self.pos
        tx, ty, tz = self.target
        if self.obstacles:
            path = self.plan(px, py, tx, ty)
            if not path:
                self.target, self.speed = None, 0.0          # nowhere to go
                return True
            tx, ty = path[-1]                                # the click, or the free spot nearest to it
            self.target = [tx, ty, tz]
            if len(path) > 1:                                # around a corner first
                gx, gy = path[0]
                if math.hypot(gx - px, gy - py) <= max(self.move_speed * dt, 0.05):
                    self._path.pop(0)
                return self._step(px, py, pz, gx, gy, pz, dt, final=False)
        return self._step(px, py, pz, tx, ty, tz, dt, final=True)

    def _step(self, px, py, pz, tx, ty, tz, dt, final):
        dx, dy = tx - px, ty - py
        dist = math.hypot(dx, dy)
        step = self.move_speed * dt
        if not final and dist <= max(step, 0.05):
            self.pos, self.speed = [tx, ty, pz], self.move_speed
            return True
        if dist <= max(step, 0.05):
            self.pos, self.target, self.speed = [tx, ty, tz], None, 0.0
            self.arrived = True
        else:
            k = step / dist
            self.heading = math.atan2(dy, dx)
            nxt = [px + dx * k, py + dy * k, pz + (tz - pz) * k]
            if self.blocked(nxt[0], nxt[1]) and not self.blocked(px, py):
                self.target, self.speed = None, 0.0          # stop at the obstacle
                return True
            self.speed = self.move_speed
            self.pos = nxt
        return True

    # -- walking around obstacles ------------------------------------------
    # An obstacle is either a box (cx, cy, half_length, half_width, yaw), which
    # is grown by Batman's radius, or a polygon [[x, y], ...] given directly as
    # the line his CENTRE cannot cross: the clicks the client snaps to the edge
    # of the walkable area (2026-10-14: the wagon and the boxes) are such points.
    EDGE_TOLERANCE = 0.08

    def polygons(self):
        key = tuple((k, tuple(map(tuple, v)) if v and isinstance(v[0], (list, tuple)) else tuple(v))
                    for k, v in sorted(self.obstacles.items()))
        if getattr(self, "_poly_key", None) == key:
            return self._polys
        polys = []
        for v in self.obstacles.values():
            if v and isinstance(v[0], (list, tuple)):
                pts = [(float(x), float(y)) for x, y in v]
            else:
                cx, cy, hl, hw, yaw = v
                hl, hw = hl + self.radius, hw + self.radius
                c, s = math.cos(yaw), math.sin(yaw)
                pts = [(cx + u * c - w * s, cy + u * s + w * c)
                       for u, w in ((hl, hw), (-hl, hw), (-hl, -hw), (hl, -hw))]
            area = sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))
            if area < 0:
                pts.reverse()                                # counter-clockwise
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            polys.append((pts, (min(xs), min(ys), max(xs), max(ys))))
        self._poly_key, self._polys, self._path_key = key, polys, None
        return polys

    @staticmethod
    def _inside(pts, x, y):
        inside = False
        j = len(pts) - 1
        for i in range(len(pts)):
            (xi, yi), (xj, yj) = pts[i], pts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _edge_distance(pts, x, y):
        best = math.inf
        for i in range(len(pts)):
            (ax, ay), (bx, by) = pts[i - 1], pts[i]
            dx, dy = bx - ax, by - ay
            n = dx * dx + dy * dy
            k = 0.0 if n == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / n))
            best = min(best, math.hypot(x - ax - k * dx, y - ay - k * dy))
        return best

    def blocked(self, x, y):
        for pts, (x0, y0, x1, y1) in self.polygons():
            if x0 < x < x1 and y0 < y < y1 and self._inside(pts, x, y) \
                    and self._edge_distance(pts, x, y) > self.EDGE_TOLERANCE:
                return True
        return False

    def segment_clear(self, ax, ay, bx, by):
        """True when the straight walk from a to b stays out of every obstacle
        (running along an edge is fine)."""
        dx, dy = bx - ax, by - ay
        for pts, (x0, y0, x1, y1) in self.polygons():
            if max(ax, bx) < x0 or min(ax, bx) > x1 or max(ay, by) < y0 or min(ay, by) > y1:
                continue
            ts = [0.0, 1.0]
            for i in range(len(pts)):
                (px, py), (qx, qy) = pts[i - 1], pts[i]
                ex, ey = qx - px, qy - py
                den = dx * ey - dy * ex
                if abs(den) < 1e-12:
                    continue
                t = ((px - ax) * ey - (py - ay) * ex) / den
                u = ((px - ax) * dy - (py - ay) * dx) / den
                if 0.0 < t < 1.0 and -1e-9 <= u <= 1 + 1e-9:
                    ts.append(t)
            # the deepest point inside lies where a corner pokes into the walk:
            # test the corners' projections on the segment as well as midpoints
            nn = dx * dx + dy * dy
            if nn > 0:
                for qx, qy in pts:
                    t = ((qx - ax) * dx + (qy - ay) * dy) / nn
                    if 0.0 < t < 1.0:
                        ts.append(t)
            ts.sort()
            probes = ts[1:-1] + [(t0 + t1) / 2 for t0, t1 in zip(ts, ts[1:]) if t1 - t0 > 1e-6]
            for tm in probes:
                x, y = ax + dx * tm, ay + dy * tm
                if self._inside(pts, x, y) and self._edge_distance(pts, x, y) > self.EDGE_TOLERANCE:
                    return False
        return True

    def free_goal(self, px, py, tx, ty):
        """The clicked point, or the free spot nearest to it when it is inside
        an obstacle (Batman walks up to the edge instead of ignoring the click)."""
        if not self.blocked(tx, ty):
            return tx, ty
        for i in range(1, 61):
            r = 0.1 * i
            best = None
            for k in range(24):
                a = k * math.pi / 12
                x, y = tx + r * math.cos(a), ty + r * math.sin(a)
                if not self.blocked(x, y):
                    d = math.hypot(x - px, y - py)
                    if best is None or d < best[0]:
                        best = (d, x, y)
            if best:
                return best[1], best[2]
        return None

    def _corners(self):
        """Walk-around points just outside each convex corner."""
        out = []
        for pts, _ in self.polygons():
            n = len(pts)
            for i in range(n):
                (ax, ay), (bx, by), (cx, cy) = pts[i - 1], pts[i], pts[(i + 1) % n]
                if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) <= 0:
                    continue                                 # concave corner: never on a shortest path
                n1 = (by - ay, -(bx - ax))                   # outward normals (counter-clockwise)
                n2 = (cy - by, -(cx - bx))
                l1, l2 = math.hypot(*n1) or 1, math.hypot(*n2) or 1
                ox, oy = n1[0] / l1 + n2[0] / l2, n1[1] / l1 + n2[1] / l2
                lo = math.hypot(ox, oy) or 1
                x, y = bx + ox / lo * 0.2, by + oy / lo * 0.2
                if not self.blocked(x, y):
                    out.append((x, y))
        return out

    def plan(self, px, py, tx, ty):
        """Waypoints to the click (last one = where Batman ends up); cached
        until the click or the obstacles change."""
        self.polygons()
        key = (round(tx * 4), round(ty * 4))
        if getattr(self, "_path_key", None) == key and self._path:
            if self.segment_clear(px, py, *self._path[0]):
                return self._path
        goal = self.free_goal(px, py, tx, ty)
        self._path_key, self._path = key, []
        if goal is None:
            return self._path
        if self.segment_clear(px, py, *goal):
            self._path = [goal]
            return self._path
        nodes = [(px, py), goal] + [c for c in self._corners() if math.hypot(c[0] - px, c[1] - py) > 0.05]
        dist, prev, todo = {0: 0.0}, {}, set(range(len(nodes)))
        while todo:
            i = min((n for n in todo if n in dist), key=dist.get, default=None)
            if i is None or i == 1:
                break
            todo.discard(i)
            for j in todo:
                d = dist[i] + math.dist(nodes[i], nodes[j])
                if d < dist.get(j, math.inf) and self.segment_clear(*nodes[i], *nodes[j]):
                    dist[j], prev[j] = d, i
        if 1 not in dist:
            # no way round (a closed gate across the bridge): walk straight and
            # stop at the obstacle instead of not moving at all
            self._path = [goal]
            return self._path
        j, path = 1, []
        while j != 0:
            path.append(nodes[j])
            j = prev[j]
        direct = math.dist((px, py), goal)
        if dist[1] > max(2.5 * direct, direct + 15.0):
            # a "way round" that long goes outside the mapped walls (2026-10-14
            # 15:17: Batman went behind the building to get past the vehicle):
            # walk straight and stop at the obstacle instead
            self._path = [goal]
            return self._path
        self._path = path[::-1]
        return self._path

    def distance_to(self, xy):
        return math.hypot(self.pos[0] - xy[0], self.pos[1] - xy[1])


def route(obstacles, start, goal, radius=0.5):
    """Points from start to goal walking around the obstacles (the server's
    own NPCs use it too: 2026-10-14 the fleeing human ran through the wagon)."""
    probe = Mover((0, 0, 0, 0, start[0], start[1], 0.0), 1.0)
    probe.obstacles = dict(obstacles)
    probe.radius = radius
    path = probe.plan(start[0], start[1], goal[0], goal[1]) if obstacles else [tuple(goal[:2])]
    return [tuple(start[:2])] + [tuple(p) for p in path]


class Entity:
    """A server-created object: a drone (character variant with vitals) or a
    piece of scenery (bare world state)."""

    def __init__(self, eid, name, class_id, pos, yaw, team, health=None, attackable=False):
        self.eid = eid
        self.name = name
        self.class_id = class_id
        self.pos = list(pos)              # landblock-local x, y, z
        self.heading = yaw + math.pi / 2  # create_object turns heading back into yaw
        self.team = team
        self.health = health
        self.max_health = health
        self.attackable = attackable
        self.alive = True
        self.sequence = 0

    def distance_to(self, xy):
        return math.hypot(self.pos[0] - xy[0], self.pos[1] - xy[1])


class Combat:
    """Basic attack of the controlled champion: walk into range, then hit
    every interval. The drones do not fight back yet (Phase 3)."""

    def __init__(self, damage, interval, attack_range):
        self.damage = damage
        self.interval = interval
        self.range = attack_range
        self.target = None          # Entity
        self.next_hit = 0.0

    def engage(self, entity, now):
        self.target = entity
        self.next_hit = max(self.next_hit, now)

    def stop(self):
        self.target = None
