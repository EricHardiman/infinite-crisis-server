"""Checks that the built-in Tutorial 1 tables still match the game's packs.

  python tests/test_layout.py <folder with 0xa0000256.rp and 0xa0000257.rp>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icserver import rp, tutorial1   # noqa: E402


def main(rp_dir):
    import math
    packs = rp.PackSet(rp_dir)
    entries = {e["name"]: e for e in rp.layout_entries(packs.pack(tutorial1.LAYOUT_PACK)) if e["positions"]}
    bad = 0
    for name, (ws, xyz, yaw) in tutorial1.LAYOUT.items():
        e = entries.get(name)
        if not e:
            print("MISSING", name); bad += 1; continue
        p = e["positions"][0]
        w, x, y, z = p["quat"]
        ok = (e["wstate"] == ws and all(abs(a - b) < 0.01 for a, b in zip(p["xyz"], xyz))
              and abs(2 * math.atan2(z, w) - yaw) < 0.002 and p["lb"] == (0x13, 0xCB))
        print(("ok  " if ok else "DIFF"), name)
        bad += not ok
    found = rp.variants_for_wstates(packs.pack(0xA0000257))
    for ws, var in tutorial1.VARIANTS.items():
        expected = found.get(ws)
        # documented choices: Trooper for the ranged drone (no variant names it),
        # the generic Soldier Drone 0x40000A5C (twin 0x49000A5C) for the melee one
        ok = expected == var or (ws, var) in ((0x2E001168, 0x40000A5D), (0x2E001167, 0x40000A5C))
        print(("ok  " if ok else "DIFF"), f"variant for {ws:#x}: {var:#x} (packs: {expected and hex(expected)})")
        bad += not ok
    print("ALL MATCH" if not bad else f"{bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
