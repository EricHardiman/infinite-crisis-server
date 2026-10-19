"""The Stolen Powers dictionary: find a power by name or champion, and dump
every power's full skill data.

The list (group, skill DID, power, champion version, icon) is
data/stolen_powers.tsv, taken from the catalog record 0x480003CD. The skill
data itself is read from the player's own install at run time (pack
0xA00000B3 + logs/props.txt, see skilldata.py); `python ic.py stolen-powers`
writes it to data/stolen_powers.json, which stays on the player's machine
(it is game data: never committed or shipped).

Config values that name a Stolen Power ([tutorial] camera_skill,
strength_skill) accept a DID (0x48000808) or a name: "Surveillance Camera"
(the base power) or "Surveillance Camera / Gaslight Batman" (a champion's
version).
"""
import json
import os

from . import skilldata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSV = os.path.join(HERE, "data", "stolen_powers.tsv")
JSON = os.path.join(HERE, "data", "stolen_powers.json")

# property ids worth a name in the summary (the rest are listed by id)
NAMES = {
    0x1000003D: "targeting",          # 1 = ground position, 14 = an entity, ...
    0x10000302: "icon",
    0x10000328: "script",
    0x100001C0: "name",
    0x100004AF: "texts",
    0x100004B3: "stats",
    0x100004B4: "stat list",
    0x100002A3: "category",
    0x100000E6: "description",
}
KIND_NAMES = {8: "enum", 9: "f32", 0x0A: "enum", 0x0B: "table", 0x0C: "array", 0x0E: "string",
              0x10: "int", 0x13: "u32", 0x15: "did", 0x16: "bool", 7: "iid"}


def catalog(path=TSV):
    """[{group, did, power, champion, icon}] from data/stolen_powers.tsv."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("#") or not ln.strip():
                continue
            parts = ln.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            rows.append({"group": int(parts[0]), "did": int(parts[1], 16), "power": parts[2],
                         "champion": parts[3], "icon": int(parts[4], 16) if parts[4] else 0})
    return rows


def label(row):
    return row["power"] + (f" / {row['champion']}" if row["champion"] else "")


def find(query, rows=None):
    """Rows whose power, champion or DID contains `query` (case-insensitive)."""
    rows = catalog() if rows is None else rows
    q = str(query).strip().lower()
    return [r for r in rows if q in label(r).lower() or q in f"{r['did']:#x}"]


def resolve(value, default=0):
    """A config value naming a Stolen Power -> its skill DID."""
    if value is None or value == "":
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text, 0)
    except ValueError:
        pass
    rows = catalog()
    exact = [r for r in rows if label(r).lower() == text.lower()]
    if exact:
        return exact[0]["did"]
    hits = find(text, rows)
    if len(hits) == 1:
        return hits[0]["did"]
    raise ValueError(f"Stolen Power '{text}': {len(hits)} matches "
                     f"({', '.join(label(r) for r in hits[:6])}{'...' if len(hits) > 6 else ''})")


def _plain(entries):
    out = []
    for key, kind, value in entries or ():
        e = {"id": f"{key:#010x}", "kind": KIND_NAMES.get(kind, f"{kind:#x}")}
        if key in NAMES:
            e["name"] = NAMES[key]
        if kind in (skilldata.KIND_TABLE, skilldata.KIND_ARRAY):
            e["value"] = _plain(value)
        elif kind == skilldata.KIND_STRING:
            e["value"] = {"token": f"{value[0]:#x}", "table": f"{value[1]:#x}"}
        elif kind == skilldata.KIND_F32:
            import struct
            e["value"] = round(struct.unpack("<f", struct.pack("<I", value))[0], 4)
        elif kind in (skilldata.KIND_DID, skilldata.KIND_U32):
            e["value"] = f"{value:#x}"
        else:
            e["value"] = value
        out.append(e)
    return out


def build(cfg, path=JSON):
    """Every power's slot collection -> data/stolen_powers.json. Returns the
    entries, or None when the game data can't be read (props.txt missing)."""
    out = []
    for row in catalog():
        table = skilldata.stolen_power(cfg, row["did"])
        if table is None:
            return None
        top = {k: v for k, _, v in table}
        out.append({"label": label(row), "did": f"{row['did']:#x}", "group": row["group"],
                    "power": row["power"], "champion": row["champion"],
                    "icon": f"{top.get(0x10000302, row['icon']):#x}",
                    "targeting": top.get(0x1000003D),
                    "script": f"{top[0x10000328]:#x}" if 0x10000328 in top else None,
                    "properties": _plain(table)})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    return out
