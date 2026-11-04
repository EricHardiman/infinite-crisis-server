"""Read ahead, at a champion's creation (the loading screen), the status effects its kit can apply.

2026-11-04 (tester report 2026-11-04 15:25: the first Heat Vision knockback of the match looked like a teleport; the
run: the knockback status 0x340003F8 started 0.13 s after the hit, 3 ms in the later casts): the first ApplySkill of a
status resolves its script (Data.status_script, the record read from its pack, whose record list is built on the
first read: 2.2 s cold for 0x48000A0F) and loads it, on the game thread, in the middle of the skill. The scripts and
data are the game's; only when they are read changes.

2026-11-05 (tester report: Blue Beetle's Q explosion missing at the first cast only; the run 16:12:51.015 -> .084: the
first SpawnEntity of the explosion object 0x40000CD8 read its class data (world state, scriptlet tables, creation
type) for 69 ms, so the script's own collision delay ran out meanwhile and Vfx_OnCollision went 1 ms after the
creation instead of ~0.1 s): the object classes the kit's scripts name (SpawnEntity, missiles) and their own scripts
are read too ([ics] prewarm_spawn_classes).

[ics] prewarm_statuses, prewarm_spawn_classes (true; false = read on first use, as before).
"""
from . import script_model as V
from . import script_runtime as R

APPLY_SKILL = 0x10000027


def _status_dids(script):
    """The status records a script's ApplySkill nodes name (their first value)."""
    out = []
    raw = getattr(script, "raw", None)
    if raw is None:
        return out

    def walk(n):
        if n.type_id == APPLY_SKILL and n.values and isinstance(n.values[0], int) and n.values[0] >> 24 == 0x48:
            out.append(n.values[0])
        for c in n.children:
            walk(c)
    walk(V.Node(raw))
    return out


def _class_dids(script):
    """The entity classes (0x40......) a script's nodes name (SpawnEntity, LaunchMissile, ...)."""
    out = []
    raw = getattr(script, "raw", None)
    if raw is None:
        return out

    def walk(n):
        out.extend(v for v in n.values if isinstance(v, int) and v >> 24 == 0x40)
        for c in n.children:
            walk(c)
    walk(V.Node(raw))
    return out


def _read_class(data, cls):
    """What World.spawn / dress_spawned read for a class (as Data.prepare does for an encounter's classes)."""
    ws = data.champion_world_state(cls)
    data.scriptlets(cls, ws or 0)
    data.record_tables(cls)
    if ws:
        data.record_tables(ws)
        data.creation_type(ws)
    data.unit_attack(cls)
    data.unit_stats(cls)
    return data.entity_scripts(cls) or []


def champion(world, ent, depth=2):
    """Resolve and load the statuses the champion's skill scripts (and those statuses' own scripts) apply."""
    if not world.ic.get("prewarm_statuses", True) or R.STATUS_RESOLVER is None:
        return 0
    todo, seen_scripts, seen = [], set(), set()
    for skill in (getattr(ent, "kit", None) or {}).values():
        did = getattr(skill, "script", None)
        if isinstance(did, int) and did:
            todo.append((did, 0))
    n = 0
    while todo:
        did, level = todo.pop()
        if did in seen_scripts:
            continue
        seen_scripts.add(did)
        try:
            script = V.load(did)
        except (OSError, ValueError):
            continue
        if world.ic.get("prewarm_spawn_classes", True) and level < depth + 1:
            for cls in _class_dids(script):
                if cls in seen:
                    continue
                seen.add(cls)
                try:
                    for sdid in _read_class(world.data, cls):
                        if isinstance(sdid, int):
                            todo.append((sdid, level + 1))
                except Exception:                          # noqa: BLE001 - a class the data does not describe
                    continue
        for status in _status_dids(script):
            if status in seen:
                continue
            seen.add(status)
            try:
                sdid = R.STATUS_RESOLVER(status)
                if R.STACKS_RESOLVER is not None:
                    R.STACKS_RESOLVER(status)
            except Exception:                              # noqa: BLE001 - a record the data does not describe
                continue
            n += 1
            if sdid and level < depth:
                todo.append((sdid, level + 1))
    return n
