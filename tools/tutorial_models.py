"""Every model (world state 0x2E) of Tutorial 1 and Tutorial 2, in one table:

    catalog/data/tutorial_models.tsv

python tools/tutorial_models.py [game folder]      (or: python ic.py tutorial-models)

2026-10-18 12:00 (tester): "detect all the models of Tutorial 1 and 2 and keep them in a list, so we know better
where to look for what". A model is listed when its world state record is in one of the tutorials' packs
(Tutorial 1: zone 0xA000024C, placement 0xA0000256; Tutorial 2: zone 0xA00002E5, mission 0xA00002E6, 0xA00002E7)
or when one of their layouts or cinematics places it.

Columns: id | tutorial (1, 2 or 1+2) | packs (the tutorial packs holding its record) | entity (.entity 0x2D) |
model (short rig / asset name; static map meshes have none) | kind (guessed from the names; without names:
animated object = has a graph set, scripted object = has templates, static scenery = neither) | templates (0x7D2) |
graph_set (0x5B5) | placed_as (names in the tutorial layouts / cinematics) | server (what the server does with it:
the config / code names it, or "closes the client") | notes.

Only IDs and short asset names are written (no game files, no texts). Reading the packs takes a few minutes.
"""
import bisect
import csv
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from icserver import gamedata, rp  # noqa: E402

TUTORIAL_PACKS = {0xA000024C: "1", 0xA0000256: "1", 0xA00002E5: "2", 0xA00002E6: "2", 0xA00002E7: "2"}
KINDS = [("meteor", r"meteor"), ("crater", r"crater"), ("lava", r"lava|magma"), ("explosion", r"explo|blast|impact"),
         ("fire", r"fire|flame|burn|ember"), ("smoke", r"smoke|plume|steam|fog"), ("dust", r"dust|debris|rubble"),
         ("shockwave", r"shock|wave"), ("electric", r"electr|lightning|spark"), ("turret", r"turret"),
         ("powercore", r"powercore|power_core"), ("pod", r"drop_pod|phase_pod"),
         ("vehicle", r"vehicle|car_|wagon|truck|carriage"), ("drone", r"drone|minion|tripod"),
         ("character", r"^chr_"), ("gate", r"gate|door|barrier|wall"), ("lamp", r"lamp|light|torch"),
         ("building", r"build|house|roof|bridge|tower|stair"), ("crate", r"crate|barrel|box"),
         ("tree", r"tree|bush|plant|foliage")]
SERVER_FILES = ("icserver/config.py", "icserver/tutorial1.py", "icserver/bridge.py", "icserver/finale.py",
                "icserver/session.py", "icserver/champion_fx.py", "icserver/freeplay.py")


def short(names):
    """One model name from a rig's bone names: the longest common prefix, cut at an underscore."""
    names = [n for n in names if not n.lower().endswith(("_root", "_parent", "_ground"))] or names
    if not names:
        return ""
    p = os.path.commonprefix(names)
    if len(names) > 1:
        p = p[: p.rfind("_")] if "_" in p else p
    return re.sub(r"_(rig|Root|Parent|Ground)$", "", p.rstrip("_"))


def kind_of(text):
    for k, pat in KINDS:
        if re.search(pat, text, re.I):
            return k
    return ""


def server_mentions():
    """{world state: [where the server names it]} from the code and config defaults."""
    out = {}
    for rel in SERVER_FILES:
        try:
            src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"0x2[Ee]00[0-9A-Fa-f]{4}", src):
            line = src[src.rfind("\n", 0, m.start()) + 1: src.find("\n", m.end())]
            key = re.search(r'"([a-z_]+)"\s*:', line) or re.search(r"([A-Z_]{4,})\s*=", line)
            out.setdefault(int(m.group(0), 16), set()).add(
                f"{os.path.basename(rel)}:{key.group(1)}" if key else os.path.basename(rel))
    return out


def crashes():
    try:
        from icserver import tutorial1
        return set(tutorial1.MODEL_TOUR_CRASHES_BARE)
    except Exception:
        return set()


def main(game_dir):
    rp_dir = os.path.join(game_dir, "rp")
    g = gamedata.Game(rp_dir)
    idx = g.index()
    packs = {}

    def pack(name):
        if name not in packs:
            if len(packs) > 8:
                packs.pop(next(iter(packs)))
            packs[name] = rp.Pack(os.path.join(rp_dir, name))
        return packs[name]

    def pack_name(pid):
        return f"0x{pid:08x}.rp"

    tut, in_packs, placed = {}, {}, {}
    for pid, t in TUTORIAL_PACKS.items():
        name = pack_name(pid)
        if not os.path.isfile(os.path.join(rp_dir, name)):
            print(f"{name} not in the install, skipped")
            continue
        pk = pack(name)
        for did in pk.ids:
            if did >> 24 == 0x2E:
                tut.setdefault(did, set()).add(t)
                in_packs.setdefault(did, set()).add(f"0x{pid:08X}")
        try:
            for e in rp.layout_entries(pk):
                ws = e["wstate"]
                if ws >> 24 == 0x2E:
                    tut.setdefault(ws, set()).add(t)
                    placed.setdefault(ws, set()).add(e["name"])
        except Exception as ex:          # layouts are optional
            print(f"{name}: layouts not read ({ex!r})")
        print(f"{name}: {sum(1 for d in pk.ids if d >> 24 == 0x2E)} world states")

    # the entities' asset names (rig bones, .hkx), read the way world_scan.py reads records
    import world_scan
    recs = {}
    for ws in tut:
        try:
            r = g.world_state(ws, partial=True)
        except Exception:
            r = None
        if not r:
            # the reader stops at a value it cannot size before the first entry: keep the entity at least
            raw = g.world_state_raw(ws, 16)
            if len(raw) >= 12 and struct.unpack_from("<I", raw, 4)[0] == 7:
                r = (struct.unpack_from("<I", raw, 8)[0], [])
            elif idx.get(ws):
                # some map pieces have "did | 2 | .entity | 0" headers (0x2E0002A7, zone 0xA000024C)
                d = pack(idx[ws]).data
                k = d.find(struct.pack("<II", ws, 2))
                if k >= 0 and struct.unpack_from("<I", d, k + 8)[0] >> 24 == 0x2D:
                    r = (struct.unpack_from("<I", d, k + 8)[0], [])
        recs[ws] = r
    wanted = {}
    for ws, r in recs.items():
        if r and r[0]:
            wanted.setdefault(idx.get(r[0]), set()).add(r[0])
    ent_names = {}
    for name, ents in wanted.items():
        if not name:
            continue
        for did, blob in world_scan.record_slices(pack(name)):
            if did in ents:
                ent_names[did] = [n for n in world_scan.names_of(blob) if not n.endswith((".hkx", ".hkb"))]

    def entity_names(ent):
        return ent_names.get(ent, [])

    mentions, crash = server_mentions(), crashes()
    rows = []
    for ws in sorted(tut):
        entity, templates, graph = 0, [], 0
        rec = recs.get(ws)
        if rec:
            entity, entries = rec
            for key, _kind, value in entries:
                if key == 0x7D2 and isinstance(value, list):
                    templates = [v for (_k2, _kd, v) in value if isinstance(v, int)]
                elif key == 0x5B5 and isinstance(value, int):
                    graph = value
        names = entity_names(entity) if entity else []
        model = short(names)
        where = sorted(placed.get(ws, ()))
        kind = kind_of(" ".join([model] + names[:6] + where))
        if not kind:
            # no asset names: static map meshes carry none (their .entity only points to mesh / collision
            # records); say what the record itself shows
            kind = ("animated object" if graph else "scripted object" if templates
                    else "static scenery" if entity else "no record")
        server = sorted(mentions.get(ws, ()))
        if ws in crash:
            server.append("closes the client ~3 s after it appears (never spawn)")
        rows.append([f"0x{ws:08X}", "+".join(sorted(tut[ws])), " ".join(sorted(in_packs.get(ws, ()))) or
                     (idx.get(ws, "")[:10].upper().replace("0XA", "0xA") + " (placed)" if idx.get(ws) else ""),
                     f"0x{entity:08X}" if entity else "", model, kind,
                     " ".join(f"0x{t:08X}" for t in templates), f"0x{graph:08X}" if graph else "",
                     " ".join(where)[:200], "; ".join(server), ""])
    out = os.path.join(ROOT, "catalog", "data", "tutorial_models.tsv")
    notes = {}
    if os.path.isfile(out):          # hand-written notes survive a re-run
        with open(out, encoding="utf-8") as f:
            for r in csv.reader(f, delimiter="\t"):
                if r and r[0].startswith("0x") and len(r) > 10 and r[10]:
                    notes[r[0]] = r[10]
    for r in rows:
        r[10] = notes.get(r[0], "")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "tutorial", "packs", "entity", "model", "kind", "templates", "graph_set", "placed_as",
                    "server", "notes"])
        w.writerows(rows)
    print(f"tutorial_models.tsv: {len(rows)} models "
          f"({sum(1 for r in rows if '1' in r[1])} in Tutorial 1, {sum(1 for r in rows if '2' in r[1])} in Tutorial 2)")


if __name__ == "__main__":
    here = sys.argv[1] if len(sys.argv) > 1 else None
    if not here:
        from icserver import config
        here = config.load(os.path.join(ROOT, "config.toml")).game_dir
    main(here)
