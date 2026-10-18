"""Champions of the install that are missing from data/champions.json.

2026-10-16 (tester: "enable Zod, Arcane Harley Quinn, Arcane Zatanna,
Nightmare Catwoman, Deathstroke, Deadshot, Dex-Starr, Raven and Huntress").
champions.json (43 champions) came from the earlier project; every champion of
the install has its own cluster of consecutive packs, found here by their
record ids alone (pack headers), so a roster entry can be built for any of them:

  light pack      0x52 bank + 0x48 champion record C (tex384 0x10000384,
                  tex799 0x10000799) + two 0x13 pictures
  wallpaper pack  0x48 C+1 ("pregame heavy", wallpaper 0x100005B0) + one 0x13
  skills pack     the skill set (the 0x48 closest to C: C+2, Dex-Starr C-2)
                  + three more 0x48 + a 0x2B text table
  parent pack     the behavior graph (0x1A / 0x1F chr_<name>_behavior.hkb)
  heavy pack      0x40 V + 0x49 V, the twin naming C (V = the variant,
                  0x49 V = heavy_dbpc; the grid icon is its 0x1000072E)

Checked on Krypto (0xA00002F4-F8) against champions.json and on Zod
(0xA0000375-79). Costume variants are not built yet (costume_info = []).
Only DIDs are kept (data/game_cache.json); the names come from the behavior
graph's file name.
"""
import os
import re
import struct
import zlib

from . import gamedata

NAME_FIXES = {"Dexstarr": "Dex-Starr"}
GRID_ICON = 0x1000072E


def _packs(rp_dir):
    out = {}
    for name in sorted(os.listdir(rp_dir)):
        if not name.lower().endswith(".rp"):
            continue
        try:
            pid = int(name[:-3], 16)
            _n, ids = gamedata.pack_header(os.path.join(rp_dir, name))
        except (OSError, ValueError, struct.error):
            continue
        out[pid] = (name, ids)
    return out


def _data(rp_dir, name, cache):
    if name not in cache:
        from .rp import Pack
        cache[name] = Pack(os.path.join(rp_dir, name)).data
    return cache[name]


def _prop_after(data, key, around):
    """The u32 after the first "key key" pair at or after offset `around`."""
    pat = struct.pack("<II", key, key)
    k = data.find(pat, around)
    return struct.unpack_from("<I", data, k + 8)[0] if k >= 0 else 0


def find_champions(rp_dir, known_ids=(), known_names=(), known_packs=(), known_variants=()):
    """[roster entry] for every champion cluster in the install whose champion
    record is not in known_ids."""
    packs = _packs(rp_dir)
    where = {}
    for pid, (_name, ids) in packs.items():
        for d in ids:
            where.setdefault(d, pid)
    cache, out = {}, []
    known = set(known_ids)
    known_names = {n.lower().replace(" ", "").replace("-", "") for n in known_names}
    for light, (lname, ids) in sorted(packs.items()):
        kinds = sorted(d >> 24 for d in ids)
        # 2026-10-16 16:36: a light pack without its 0x52 sound bank is either a
        # costume (skip: its graph names a known champion) or a champion that
        # was never released (John Stewart: own graph and skill set, pregame
        # record C-1 instead of C+1). Those are kept when their name is new.
        late = kinds == [0x13, 0x13, 0x48]
        if kinds != [0x13, 0x13, 0x48, 0x52] and not late:
            continue
        c = next(d for d in ids if d >> 24 == 0x48)
        if c in known:
            continue
        skills = None
        for pregame in ((c + 1, c - 1) if late else (c + 1,)):
            wall = where.get(pregame)
            if wall is not None and sorted(d >> 24 for d in packs[wall][1]) == [0x13, 0x48]:
                break
        else:
            continue
        near = [p for p in range(light - 6, light + 7) if p in packs]
        graph = lambda p: any(d >> 24 in (0x1A, 0x1F) for d in packs[p][1])     # noqa: E731
        # the skill set: in the pack with a text table, no graph and several 0x48
        # records, the one closest to C (C+2 for most; Dex-Starr's is C-2)
        for p in sorted(near, key=lambda p: abs(p - light)):
            recs = [d for d in packs[p][1] if d >> 24 == 0x48]
            if len(recs) >= 2 and any(d >> 24 == 0x2B for d in packs[p][1]) and not graph(p):
                skills = p
                skills_key = min(recs, key=lambda d: abs(d - c))
                break
        # the parent pack: the champion's own pack with its 0x52 sound bank and a
        # text table (it usually holds the behavior graph too; Huntress keeps
        # the graph in her heavy pack), else the nearest pack with a graph
        def score(p):
            kinds = {d >> 24 for d in packs[p][1]}
            return (-(2 * (0x52 in kinds) + (0x2B in kinds) + graph(p)), abs(p - light))
        cands = sorted((p for p in near if p not in (light, wall, skills)
                        and ({0x52, 0x2B} <= {d >> 24 for d in packs[p][1]} or graph(p))), key=score)
        parent = cands[0] if cands else None
        if late and skills is not None:
            # an unreleased champion's parent: the graph pack holding its skill set
            own = [p for p in near if p not in (light, wall, skills) and graph(p) and skills_key in packs[p][1]]
            parent = own[0] if own else None
        if skills is None or parent is None:
            continue
        try:
            entry = _entry(rp_dir, packs, near, cache, c, light, wall, skills, parent, skills_key, pregame)
        except (OSError, ValueError, zlib.error, struct.error):
            entry = None
        if entry:
            entry["unreleased"] = late
            out.append(entry)
    # 2026-10-16 17:07 (tester: Zod, Raven, Deathstroke... twice in the game's
    # champion list, the second with another champion's portrait, loading a
    # skin). Sound-bank-less clusters are mostly costumes, and a costume can come
    # before its champion's cluster, so they are judged only after every
    # released champion is known: a costume's variant is a known costume
    # variant, or its name / graph pack is a released champion's.
    def norm(n):
        return n.lower().replace(" ", "").replace("-", "")
    released = [e for e in out if not e["unreleased"]]
    names = set(known_names) | {norm(e["name"]) for e in released}
    packs_ = set(known_packs) | {e["parent_pack"] for e in released}
    variants = set(known_variants) | {e["variant"] for e in released}
    kept, seen = list(released), set()
    for e in out:
        if not e["unreleased"]:
            continue
        key = norm(e["name"])
        if (key in names or key in seen or e["variant"] in variants or not e["name_pack"] or e["name_pack"] in packs_
                or e["name"].startswith("Champion ") or "skin" in key):
            continue
        seen.add(key)
        kept.append(e)
    return kept


def _entry(rp_dir, packs, near, cache, c, light, wall, skills, parent, skills_key, pregame=None):
    pregame = pregame or c + 1
    ldata = _data(rp_dir, packs[light][0], cache)
    k = ldata.find(struct.pack("<I", c))
    tex384 = _prop_after(ldata, 0x10000384, k)
    tex799 = _prop_after(ldata, 0x10000799, k)
    wdata = _data(rp_dir, packs[wall][0], cache)
    wallpaper = _prop_after(wdata, 0x100005B0, wdata.find(struct.pack("<I", pregame)))
    variant = heavy = grid = 0
    needle = struct.pack("<I", c)
    best = None
    for p in near:
        ids = packs[p][1]
        pairs = [d for d in ids if d >> 24 == 0x40 and (0x49000000 | (d & 0xFFFFFF)) in ids]
        if not pairs or p == parent:
            continue
        data = _data(rp_dir, packs[p][0], cache)
        for v in pairs:
            twin = data.find(struct.pack("<I", 0x49000000 | (v & 0xFFFFFF)))
            hit = data.find(needle, twin) if twin >= 0 else -1
            if twin >= 0 and 0 <= hit - twin < 0x8000 and (best is None or hit - twin < best[0]):
                best = (hit - twin, v, p, _prop_after(data, GRID_ICON, twin))
    if best is None:
        return None
    _dist, variant, heavy, grid = best
    import collections
    names = collections.Counter()
    for p in [parent, heavy] + [q for q in near if q not in (parent, heavy)]:
        if p in (light, wall, skills):
            continue
        names = collections.Counter(x.decode() for x in re.findall(rb"chr_([a-z0-9_]+?)_behavior\.hk",
                                                                  _data(rp_dir, packs[p][0], cache)))
        if names:
            break
    name_pack = 0xA0000000 | p if names else 0
    raw = min(names, key=lambda n: (len(n), n)) if names else f"champion_{c:08x}"
    name = " ".join(w.capitalize() for w in raw.split("_"))
    name = NAME_FIXES.get(name, name)
    return {"name": name, "id": c, "variant": variant, "heavy_pack": 0xA0000000 | heavy,
            "light_pack": 0xA0000000 | light, "parent_pack": 0xA0000000 | parent,
            "wallpaper_pack": 0xA0000000 | wall, "skills_pack": 0xA0000000 | skills,
            "heavy_dbpc": 0x49000000 | (variant & 0xFFFFFF), "pregame_heavy": pregame, "skills_key": skills_key,
            "tex384": tex384, "tex799": tex799, "wallpaper": wallpaper, "grid_icon": grid,
            "costumes": [], "costume_info": [], "powerset_candidates": [], "powerset_dbpc": 0,
            "name_pack": name_pack, "added_by": "roster.py"}


def extend(cfg, roster, log=None):
    """Append the install's champions missing from the roster (cached)."""
    if not cfg["account"].get("extra_champions", True):
        return roster
    from . import gamecache
    rp_dir = os.path.join(cfg.game_dir, "rp")
    found = gamecache.get(rp_dir, "extra_champions_v3")
    if found is None:
        try:
            packs_of = {c.get(k) for c in roster for k in ("parent_pack", "heavy_pack")}
            packs_of |= {s.get("heavy_pack") for c in roster for s in c.get("costume_info", [])}
            variants = {c["variant"] for c in roster} | {s["variant"] for c in roster for s in c.get("costume_info", [])}
            found = find_champions(rp_dir, [c["id"] for c in roster], [c["name"] for c in roster], packs_of, variants)
        except OSError as e:
            if log:
                log(f"extra champions: {e!r}")
            return roster
        gamecache.put(rp_dir, "extra_champions_v3", found)
    have = {c["id"] for c in roster}
    names = {c["name"].lower() for c in roster}
    added, seen_v = [], set()
    for c in found:             # never the same name or variant twice
        if (c["id"] in have or c["name"].lower() in names or "skin" in c["name"].lower()
                or c["variant"] in seen_v):
            continue
        names.add(c["name"].lower())
        seen_v.add(c["variant"])
        added.append(c)
    if not cfg["account"].get("unreleased_champions", True):
        added = [c for c in added if not c.get("unreleased")]
    if log:
        log(f"extra champions from the install: {', '.join(c['name'] for c in added) or 'none'}")
    return roster + added
