"""Scan the player's install and refresh the catalog tables that come from the
game data (python ic.py catalog --scan).

    packs.tsv       every .rp pack: record count, record types, text tables
                    (+ hand-written notes from packs_notes.tsv)
    skills.tsv      every champion's skill set (basic, Q, W, E, R, passive)
                    and the implemented Stolen Powers (+ skills_notes.tsv)
    artifacts.tsv   artifacts (Artifact Foundry lists, pack 0xA00000B3)
    amplifiers.tsv  augments (list 0x48000A49) and mods (list 0x48000A4A)
    item_stats.tsv  the stat keys items use (Health 0x10000426, ...)

Only IDs, short names and numbers are written (no descriptions or other game
texts). Record layouts: catalog/README.md and docs/reverse-engineering.md.
"""
import csv
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from icserver import gamedata as gd  # noqa: E402
from icserver.gamedata import get, f32  # noqa: E402

DATA = os.path.join(ROOT, "catalog", "data")

# champion property -> (HUD slot, key)
SKILL_SLOTS = [(0x100008E3, 0, "Basic"), (0x100008E8, 1, "Q"), (0x100008EA, 2, "W"), (0x100008EC, 3, "E"),
               (0x100008E6, 4, "R"), (0x100008EF, 5, "Passive")]
STAT_COOLDOWN, STAT_COST = 18, 3
STOLEN_SLOTS = {0x48000808: (7, "D"), 0x48000A3B: (8, "F")}      # the ones the server implements

ARTIFACT_LISTS = (0x48000163, 0x48000EA9, 0x48000EAA, 0x4800118B, 0x480007B0)
AUGMENT_LIST, MOD_LIST = 0x48000A49, 0x48000A4A
FOUNDRY = 0x48000163
CATEGORY = {1: "Attack", 2: "Defense", 3: "Power", 4: "Utility"}
BRAND = {3: "Kord Industries", 4: "S.T.A.R. Labs", 5: "Lex Corp", 6: "Queen Industries", 7: "Holt Holdings",
         8: "Wayne Enterprises"}
OP = {9: "+", 10: "+%"}


def hx(v):
    return f"0x{int(v):08X}" if isinstance(v, int) and v else ""


def num(v):
    v = f32(v)
    return f"{v:g}" if isinstance(v, float) else ("" if v is None else str(v))


def write(name, head, rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    with open(os.path.join(DATA, name), "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    print(f"  {name}: {len(rows)} rows")


def notes(name, key="id"):
    path = os.path.join(DATA, name)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    head = rows[0]
    return {r[head.index(key)].upper(): dict(zip(head, r)) for r in rows[1:] if r}


# ---- packs --------------------------------------------------------------------------
# record type = the DID's top byte (known or probable meaning)
ASSET_TYPES = {
    0x10: "?", 0x13: "image / texture", 0x15: "file resource (text, data)", 0x17: "model part (debris model seen)",
    0x18: "particle effect", 0x1A: "animation behavior graph (Havok .hkb)", 0x1C: "object behavior graph",
    0x1D: "script / object template", 0x1E: "status effect", 0x1F: "behavior script (Lua) / graph",
    0x24: "font glyph table", 0x2B: "string table", 0x2D: "entity setup (.entity: skeleton, model)",
    0x2E: "world state", 0x30: "enum / name table", 0x33: "name table", 0x34: "server script",
    0x35: "cinematic", 0x3B: "scaling formula", 0x40: "entity class / item", 0x48: "data record",
    0x49: "data record (twin of a 0x40)", 0x52: "sound bank (Wwise)",
}
CLIP = re.compile(rb"([A-Za-z0-9_\-]{3,100}\.(hkx|hkb))", re.I)


def scan_packs(game):
    manual = notes("packs_notes.tsv")
    totals, where = {}, {}
    rows = []
    for name in game.pack_files():
        path = os.path.join(game.rp_dir, name)
        try:
            count, ids = gd.pack_header(path)
        except OSError:
            continue
        kinds = {}
        for did in ids:
            kinds[did >> 24] = kinds.get(did >> 24, 0) + 1
        for k, v in kinds.items():
            totals[k] = totals.get(k, 0) + v
            where[k] = where.get(k, 0) + 1
        types = " ".join(f"{k:02X}:{v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:6])
        try:
            streams = gd.text_streams(path)
            tables = len(gd.parse_stream(streams[0])) if streams else 0
        except OSError:
            tables = 0
        pid = name[:-3].upper().replace("0X", "0x")
        m = manual.get(pid.upper(), {})
        rows.append([pid, str(count), types, str(tables), str(os.path.getsize(path)), m.get("contents", ""),
                     m.get("notes", "")])
    write("packs.tsv", ["id", "records", "record_types", "text_tables", "bytes", "contents", "notes"], rows)
    write("asset_types.tsv", ["id", "meaning", "records", "packs"],
          [[f"0x{k:02X}", ASSET_TYPES.get(k, ""), str(v), str(where[k])] for k, v in sorted(totals.items())])


def scan_animations(game):
    """Every behavior graph (0x1A / 0x1F records with an .hkb name) and the
    animation clips (.hkx) it plays."""
    rows = []
    for name in game.pack_files():
        _count, ids = gd.pack_header(os.path.join(game.rp_dir, name))
        if not any(d >> 24 in (0x1A, 0x1F) for d in ids):
            continue
        try:
            pack = game.packs.pack(name)
        except (OSError, ValueError):
            continue
        starts = pack.record_starts()
        for i, (off, did) in enumerate(starts):
            if did >> 24 not in (0x1A, 0x1F):
                continue
            end = starts[i + 1][0] if i + 1 < len(starts) else len(pack.data)
            names = [m.group(1).decode() for m in CLIP.finditer(pack.data, off, min(end, off + 0x400000))]
            graph = next((n for n in names if n.lower().endswith(".hkb")), "")
            clips = sorted({n for n in names if n.lower().endswith(".hkx")})
            if graph or clips:
                rows.append([hx(did), graph, name[:-3].upper().replace("0X", "0x"), str(len(clips)), " ".join(clips)])
    # the same graph can sit in several packs: one row, every pack listed
    merged = {}
    for r in rows:
        if r[0] in merged:
            merged[r[0]][2] += " " + r[2]
        else:
            merged[r[0]] = r
    write("animation_graphs.tsv", ["id", "graph", "pack", "clips", "clip_files"], list(merged.values()))


# ---- skills -------------------------------------------------------------------------
def skill_row(game, rid, champion, slot, key, block):
    """Stats as "stat id=base(+per rank)". Stat ids seen so far: 3 = cost
    (Will, stored negative), 5 = damage, 18 = probably the cooldown."""
    stats = []
    for _k, _kind, st in get(block, 0x100004B4) or []:
        sid = get(st, 0x100004B6)
        val = get(st, 0x100004D3) or get(st, 0x100004D4) or []
        base, per = get(val, 0x100004B7), get(val, 0x100004D2)
        if sid is None or base is None:
            continue
        stats.append(f"{sid}={num(base)}" + (f"(+{num(per)}/rank)".replace("+-", "-") if per is not None else ""))
    return [rid, champion, str(slot), key, game.text(get(block, 0x100001C0)), hx(get(block, 0x10000302)),
            str(get(block, 0x1000003D, "") or ""), hx(get(block, 0x10000328)), " ".join(stats)]


def scan_skills(game, roster):
    manual = notes("skills_notes.tsv")
    rows = []
    for c in sorted(roster, key=lambda c: c["name"]):
        sk = c.get("skills_key")
        rec = game.record(sk) if sk else None
        if not rec:
            continue
        for prop, slot, key in SKILL_SLOTS:
            block = get(rec, prop)
            if block:
                rows.append(skill_row(game, f"0x{sk:08X}:{slot}", c["name"], slot, key, block))
    from icserver import skilldata
    for did, (slot, key) in STOLEN_SLOTS.items():
        # a version's block goes on top of its base power's (skilldata.stolen_power)
        pack = game.index().get(did)
        if not pack:
            continue
        base = skilldata.base_of(game.packs.pack(pack).data, did, game.kinds)
        merged = {}
        for d in ([base] if base and base != did else []) + [did]:
            for k, kind, v in get(game.record(d), skilldata.SKILL_BLOCK) or []:
                merged[k] = (k, kind, v)
        block = list(merged.values())
        if block:
            rows.append(skill_row(game, f"0x{did:08X}", "(Stolen Power)", slot, key, block))
    out = []
    for r in rows:
        m = manual.get(r[0].upper(), {})
        out.append(r + [m.get("server_status", "data only"), m.get("notes", "")])
    # hand-written rows the scan did not produce (e.g. packs missing) are kept
    have = {r[0].upper() for r in out}
    for rid, m in manual.items():
        if rid not in have:
            out.append([m.get("id", rid), m.get("champion", ""), m.get("slot", ""), m.get("key", ""), m.get("name", ""),
                        "", "", "", "", m.get("server_status", ""), m.get("notes", "")])
    write("skills.tsv", ["id", "champion", "slot", "key", "name", "icon", "targeting", "script", "stats",
                         "server_status", "notes"], out)


# ---- items --------------------------------------------------------------------------
def twin(game, cls):
    return game.record(0x49000000 | (cls & 0xFFFFFF))


def stat_names(game):
    names = {}
    for _k, _kind, c in get(game.record(FOUNDRY), 0x10000844) or []:
        label = game.text(get(c, 0x1000083A))
        for _k2, _kind2, sk in get(c, 0x10000845) or []:
            names.setdefault(sk, (label, get(c, 0x10000843), get(c, 0x10000837)))
    return names


def scan_items(game):
    names = stat_names(game)
    sn = lambda k: names.get(k, (f"0x{k:08X}",))[0] if k else "?"     # noqa: E731
    if names:
        write("item_stats.tsv", ["id", "name", "foundry_group", "foundry_filter"],
              [[hx(k), v[0], str(v[1] or ""), str(v[2] or "")] for k, v in sorted(names.items())])
    lists = {L: [v for _k, _kind, v in get(game.record(L), 0x1000042C) or []] for L in ARTIFACT_LISTS}
    arts = sorted({v for vs in lists.values() for v in vs})
    rows = []
    for cls in arts:
        e = twin(game, cls)
        if not e:
            continue
        name = game.text(get(e, 0x10000372))
        tier = re.search(r"\((\d)\)$", name)
        stats = []
        for _k, _kind, blk in get(e, 0x10000684) or []:
            op = OP.get(get(blk, 0x1000068B), "?")
            for k, _kind2, v in get(blk, 0x1000068C) or []:
                stats.append(f"{sn(k)} {op}{num(v)}")
        passives = [hx(v) for _k, _kind, blk in get(e, 0x100004EA) or [] for k, _kk, v in blk if k == 0x1000037D]
        rows.append([hx(cls), name, CATEGORY.get(get(e, 0x1000048A), str(get(e, 0x1000048A, ""))),
                     tier.group(1) if tier else "", num(get(e, 0x1000036C)), hx(get(e, 0x10000698)),
                     hx(get(e, 0x10000436)), hx(get(e, 0x100008E1)), " ".join(passives), "; ".join(stats),
                     " ".join(hx(L) for L, vs in lists.items() if cls in vs), "data only"])
    if rows:
        write("artifacts.tsv", ["id", "name", "category", "tier", "cost", "upgrade_from", "icon", "active_skill",
                                "passives", "stats", "foundry_lists", "server_status"], rows)
    amps = []
    for cls in [v for _k, _kind, v in get(game.record(AUGMENT_LIST), 0x1000099F) or []]:
        e = twin(game, cls)
        stats = [f"{sn(get(b, 0x10000958))} {OP.get(get(b, 0x10000952), '?')}{num(get(b, 0x10000954))}"
                 for _k, _kind, b in get(e, 0x10000950) or []]
        amps.append([hx(cls), game.text(get(e, 0x10000951)), "augment", BRAND.get(get(e, 0x10000956), ""),
                     "; ".join(stats), "", "data only"])
    for cls in [v for _k, _kind, v in get(game.record(MOD_LIST), 0x1000099F) or []]:
        e = twin(game, cls)
        targets = []
        for _k, _kind, b in get(e, 0x10000989) or []:
            art = hx(get(b, 0x1000098B))
            if get(b, 0x1000098C) is not None:
                targets.append(f"{art} -{num(get(b, 0x1000098C))} credits")
            elif get(b, 0x10000988) is not None:
                targets.append(f"{art} keyword {hx(get(b, 0x10000988))}")
            else:
                targets.append(f"{art} {sn(get(b, 0x10000985))} {OP.get(get(b, 0x10000986), '?')}"
                               f"{num(get(b, 0x10000984))}")
        amps.append([hx(cls), game.text(get(e, 0x1000097D)), "mod", BRAND.get(get(e, 0x1000097B), ""), "",
                     "; ".join(targets), "data only"])
    if amps:
        write("amplifiers.tsv", ["id", "name", "type", "brand", "stats", "targets", "server_status"], amps)


def scan_avatar_icons(game):
    """The profile's Protector icons (icserver/cosmetics.py)."""
    from icserver import cosmetics
    icons = cosmetics.avatar_icons(game.rp_dir, names=True)
    rows = [[hx(wc), hx(0x49000000 | (wc & 0xFFFFFF)), hx(pic), name, "implemented",
             "Sent as owned (0x20B8, content type 3)."] for wc, pic, name in icons]
    if rows:
        write("avatar_icons.tsv", ["id", "record", "picture", "name", "server_status", "notes"], rows)


def scan(cfg):
    rp_dir = os.path.join(cfg.game_dir, "rp")
    game = gd.Game(rp_dir, os.path.join(cfg.log_dir, "props.txt"))
    print(f"scanning {rp_dir} ({len(game.pack_files())} packs)")
    scan_packs(game)
    roster = []
    for p in (os.path.join(ROOT, "data", "champions.json"),):
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                roster = json.load(f)
    scan_skills(game, roster)
    scan_items(game)
    scan_avatar_icons(game)
    scan_animations(game)


if __name__ == "__main__":
    from icserver import config as cfgmod
    scan(cfgmod.load(sys.argv[1] if len(sys.argv) > 1 else None))
