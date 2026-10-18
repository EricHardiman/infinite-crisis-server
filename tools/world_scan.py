"""Inventory of every world state (0x2E) in the player's install:

    catalog/data/world_states.tsv
        id | packs | entity (.entity 0x2D) | name (rig / graph / particle names found
        in it and in the records it uses) | kind (meteor, crater, fire, smoke, ...
        guessed from those names) | templates (0x1D) | graphs (0x1A/0x1C) |
        particles (0x18) | placed_as (names it has in the map layouts) |
        used_by (records that name it: event templates 0x1D, other world states) |
        needs_packs (every pack holding a record it uses, two levels deep)

python tools/world_scan.py [game folder [cache.pickle]]   (or: python ic.py worlds)

Only IDs, short asset names (rig bones, .hkb / .hkx file names) and numbers are
written, as in the other catalog tables. The scan reads every pack once (a few
minutes); refs are found by reading each record as aligned u32 values and
keeping the ones that are record IDs of some pack.
"""
import bisect
import csv
import io
import os
import pickle
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from icserver import gamedata, rp  # noqa: E402

DATA = os.path.join(ROOT, "catalog", "data")
KEEP = {0x2E, 0x2D, 0x1D, 0x1C, 0x1A, 0x18, 0x17, 0x1E}      # record types whose refs / names matter
# asset names: rig bones (vfx_env_event_meteor_dust_cloud_rig_Root), .hkx / .hkb files; shader
# parameters (Sampler_FogMask, c_DistanceFogColor) are left out, they matched "fog" / "smoke"
NAME = re.compile(rb"(?:vfx|env|chr|stp|prp|fx|pvp|lev|wpn|veh|ui)_[A-Za-z0-9_]{3,60}|[A-Za-z0-9_]{3,60}\.hk[xb]")
KINDS = [  # (kind, pattern) checked in order on the joined names
    ("meteor", r"meteor"), ("crater", r"crater"), ("lava", r"lava|magma"), ("explosion", r"explo|blast|impact"),
    ("fire", r"fire|flame|burn|ember"), ("smoke", r"smoke|plume|steam|fog"), ("dust", r"dust|debris|rubble"),
    ("shockwave", r"shock|wave"), ("electric", r"electr|lightning|spark"), ("turret", r"turret"),
    ("powercore", r"powercore|power_core"), ("vehicle", r"vehicle|car_|wagon|truck"), ("drop pod", r"drop_pod"),
]


HEAD = re.compile(rb"(?=(...[\x2e\x2d\x1d\x1c\x1a\x18\x17\x1e])([\x00\x07])\x00\x00\x00)", re.S)


def record_slices(pack):
    """(did, bytes) of the records worth reading. Starts come from the record headers ("did | 7 |
    .entity | 0" for world states, "did | 0" for the rest; one regex pass), which is more reliable
    than the first occurrence of the DID (a reference can come first); rp.Pack.record_starts()
    adds the boundaries of the other record types."""
    data, ids = pack.data, set(pack.ids)
    first = {}
    for m in HEAD.finditer(data):
        did = struct.unpack("<I", m.group(1))[0]
        if did not in ids:
            continue
        seven = m.group(2) == b"\x07"
        if (did >> 24 == 0x2E) != seven:
            continue
        first.setdefault(did, m.start())
    bounds = sorted(set(first.values()) | {o for o, d in pack.record_starts() if d >> 24 not in KEEP})
    for did, off in first.items():
        i = bisect.bisect_right(bounds, off)
        end = bounds[i] if i < len(bounds) else len(data)
        yield did, data[off:min(end, off + 400000)]


def names_of(blob):
    out = []
    for m in NAME.finditer(blob):
        s = m.group(0).decode("ascii", "replace")
        if s not in out:
            out.append(s)
    return out


def short_name(s):
    """vfx_env_event_meteor_dust_cloud_rig_Root -> vfx_env_event_meteor_dust_cloud (one name per model)."""
    s = re.sub(r"_rig(_.*)?$", "", s)
    return re.sub(r"_(Parent|Root|Root_Jnt|Setup|Body\w*|Jnt|Main)$", "", s)


def scan(game_dir, log=print, cache=None):
    """cache: a pickle file for the raw scan (kept between runs while the table's columns are tuned)."""
    if cache and os.path.isfile(cache):
        with open(cache, "rb") as f:
            return build(*pickle.load(f), log=log)
    rp_dir = os.path.join(game_dir, "rp")
    names = sorted(n for n in os.listdir(rp_dir) if n.lower().endswith(".rp"))
    where = {}
    for n in names:
        try:
            _c, ids = gamedata.pack_header(os.path.join(rp_dir, n))
        except (OSError, struct.error):
            continue
        for d in ids:
            where.setdefault(d, []).append(n[:10].upper().replace("0XA", "0xA"))
    log(f"{len(names)} packs, {len(where)} record ids")
    refs, nm, entity_of, placed = {}, {}, {}, {}
    for i, n in enumerate(names):
        try:
            pack = rp.Pack(os.path.join(rp_dir, n))
        except (OSError, ValueError):
            continue
        for did, blob in record_slices(pack):
            if did in refs:
                continue
            body = blob[: len(blob) // 4 * 4]
            vals = {v for (v,) in struct.iter_unpack("<I", body)} if body else set()
            refs[did] = {v for v in vals if v in where and v != did and v & 0xFFFFFF}
            nm[did] = names_of(blob)
            if did >> 24 == 0x2E and len(blob) >= 12:
                ent = struct.unpack_from("<I", blob, 8)[0]
                if ent >> 24 == 0x2D:
                    entity_of[did] = ent
        try:
            for e in rp.layout_entries(pack):
                placed.setdefault(e["wstate"], set()).add(e["name"])
        except Exception:      # a pack without layouts or an odd one: placements are optional
            pass
        if (i + 1) % 50 == 0:
            log(f"  {i + 1}/{len(names)} packs")
    if cache:
        with open(cache, "wb") as f:
            pickle.dump((where, refs, nm, entity_of, placed), f)
    return build(where, refs, nm, entity_of, placed, log=log)


def build(where, refs, nm, entity_of, placed, log=print):

    used_by = {}
    for r, vals in refs.items():
        for v in vals:
            if v >> 24 == 0x2E:
                used_by.setdefault(v, set()).add(r)
    rows = []
    for ws in sorted(d for d in refs if d >> 24 == 0x2E):
        level1 = set(refs[ws]) | ({entity_of[ws]} if ws in entity_of else set())
        level2 = set(level1)
        for r in level1:
            level2 |= refs.get(r, set())
        name_list, raw = [], []
        for r in [entity_of.get(ws)] + sorted(level2):
            if r is None or r >> 24 not in (0x2D, 0x1A, 0x18, 0x17):
                continue
            for s in nm.get(r, []):
                raw.append(s)
                s = short_name(s)
                if s not in name_list and not any(s.startswith(n + "_") for n in name_list):
                    name_list.append(s)
        joined = " ".join(raw + sorted(placed.get(ws, ()))).lower()
        kinds = [k for k, pat in KINDS if re.search(pat, joined)]
        packs_needed = sorted({p for r in level2 for p in where.get(r, [])})
        pick = lambda t: " ".join(f"0x{r:08X}" for r in sorted(level2) if r >> 24 == t)
        rows.append([f"0x{ws:08X}", " ".join(where.get(ws, [])),
                     f"0x{entity_of[ws]:08X}" if ws in entity_of else "",
                     " ".join(name_list[:6]), " ".join(kinds),
                     " ".join(f"0x{r:08X}" for r in sorted(refs[ws]) if r >> 24 == 0x1D),
                     (pick(0x1A) + " " + pick(0x1C)).strip(), pick(0x18),
                     " ".join(sorted(placed.get(ws, ()))[:6]),
                     " ".join(f"0x{r:08X}" for r in sorted(used_by.get(ws, ()))[:8]), " ".join(packs_needed)])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(["id", "packs", "entity", "names", "kind", "templates", "graphs", "particles", "placed_as",
                "used_by", "needs_packs"])
    w.writerows(rows)
    with open(os.path.join(DATA, "world_states.tsv"), "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    log(f"world_states.tsv: {len(rows)} world states")
    return rows


if __name__ == "__main__":
    game = sys.argv[1] if len(sys.argv) > 1 else None
    if not game:
        from icserver import config
        game = config.load(None).game_dir
    scan(game, cache=sys.argv[2] if len(sys.argv) > 2 else None)
