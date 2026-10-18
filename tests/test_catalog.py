"""Catalog checks (python tests/test_catalog.py).

Fails on structural problems in catalog/data/*.tsv (wrong column count,
malformed or duplicate IDs, unknown status values) and lists the game IDs the
server's code uses that no catalog table mentions yet (a reminder to document
them; not a failure).
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "catalog", "data")
HEX = re.compile(r"^0x[0-9A-Fa-f]{1,8}(:\d+)?$")
STATUS = re.compile(r"^(implemented|playable|shown only|visible without effect|sent|handled|ignored|off|data only|"
                    r"not started|partial|yes|no)\b", re.I)
# tables whose first column may repeat (one row per entity / variant / kind)
REPEATS = {"scriptlets.tsv", "conversations.tsv", "animations.tsv", "vfx.tsv", "properties.tsv",
           "network_events.tsv", "hud_elements.tsv", "exe_patches.tsv", "scriptlets_other.tsv"}
CODE_PREFIXES = (0x2E, 0x35, 0x40, 0x48, 0x49, 0x1A, 0x1C, 0x1D)


def main():
    errors, ids = [], set()
    for name in sorted(os.listdir(DATA)):
        if not name.endswith(".tsv"):
            continue
        with open(os.path.join(DATA, name), encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f, delimiter="\t"))
        if not rows:
            errors.append(f"{name}: empty file")
            continue
        head, seen = rows[0], set()
        for n, r in enumerate(rows[1:], 2):
            if len(r) != len(head):
                errors.append(f"{name}:{n}: {len(r)} columns, header has {len(head)}")
                continue
            key = r[0]
            if head[0] == "id" and key and not HEX.match(key) and not key.isdigit():
                errors.append(f"{name}:{n}: malformed id {key!r}")
            if name not in REPEATS and key in seen:
                errors.append(f"{name}:{n}: duplicate id {key}")
            seen.add(key)
            for col, v in zip(head, r):
                if col.endswith("status") and v and not STATUS.match(v):
                    errors.append(f"{name}:{n}: unknown status {v!r}")
                for tok in re.findall(r"0x[0-9A-Fa-f]{6,8}", v):
                    ids.add(int(tok, 16))
    missing = set()
    for folder in ("icserver",):
        for fn in os.listdir(os.path.join(ROOT, folder)):
            if fn.endswith(".py"):
                with open(os.path.join(ROOT, folder, fn), encoding="utf-8") as f:
                    for tok in re.findall(r"\b0x[0-9A-Fa-f]{8}\b", f.read()):
                        v = int(tok, 16)
                        if v >> 24 in CODE_PREFIXES and v & 0xFFFFFF and v not in ids:
                            missing.add(v)
    print(f"{len(ids)} distinct IDs in the catalog")
    if missing:
        print(f"note: {len(missing)} game IDs used in icserver/*.py are not in the catalog yet:")
        print("  " + " ".join(f"0x{v:08X}" for v in sorted(missing)))
    for e in errors:
        print("ERROR", e)
    print("catalog OK" if not errors else f"{len(errors)} catalog error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
