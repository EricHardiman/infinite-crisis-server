"""Finds game records by their ID (DID) in all the packs and copies them out.

Usage:
    python tools\\extract_records.py 0x34000037 0x34000038 ...
    python tools\\extract_records.py            (no IDs: Gaslight Batman's scriptlets)
    python tools\\extract_records.py vehicles   (the tutorial's cars and what they refer to)
    python tools\\extract_records.py destruction (the paddy wagon's destruction and script records)
    python tools\\extract_records.py uistate  (the UI state machine data of pack 0xA00000D0: the
               end-of-match VICTORY, the reward screens); add --swf for its 0x20 records too
    python tools\\extract_records.py achievements (every record, in all packs, that defines an
               achievement: the Training ones give the "Champion Unlocked" panel)
    --all      also copy EVERY place the ID appears in its pack (<DID>@<offset>.bin, 8 KB each):
               records carry no size table, so the first match is not always the record
    --follow   also copy the records the found ones refer to (0x1D scripts,
               0x2D models / rigs, 0x1E / 0x34 scriptlets, 0x2E world states)

Writes logs\\records\\<DID>.bin (the record's bytes) and logs\\records\\index.txt
(which pack each one is in). Send me the logs\\records folder zipped up.
Only reads the packs; modifies nothing.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from icserver import config as config_mod   # noqa: E402
from icserver.rp import Pack                 # noqa: E402

# Scriptlets that Gaslight Batman's class (twin 0x49000086) refers to.
DEFAULT = [0x34000037, 0x34000038, 0x34000039, 0x3400003A, 0x3400003B, 0x34000048]
# The street's police wagon (DestVehicle) and the 02PaddyWagonA / B of layout 0x1D000771
VEHICLES = [0x2E000AAB, 0x2E00034D, 0x2E00034E]
FOLLOW_PREFIXES = (0x1D, 0x2D, 0x1E, 0x34, 0x2E, 0x31, 0x36)
# 0x2E00034D (02PaddyWagonA): destruction property 0x5B5 -> 0x1C000021, script
# table 0x1D0000BB (the copy found first was not the record), skeleton 0x2D000238
DESTRUCTION = [0x1C000021, 0x1D0000BB, 0x1700163E, 0x2E00034D]


UI_PACK = 0xA00000D0
UI_TYPES = (0x24, 0x27, 0x2B, 0x40, 0x48, 0x49, 0x52)


def dump_pack_types(pack_id, types):
    """Every record of the given DID types (top byte) in one pack, plus its ID list."""
    cfg = config_mod.load()
    rp_dir = os.path.join(cfg.game_dir, "rp")
    names = [n for n in os.listdir(rp_dir) if n.lower() == f"{pack_id:#010x}.rp"] if os.path.isdir(rp_dir) else []
    path = os.path.join(rp_dir, names[0] if names else f"{pack_id:#010x}.rp")
    if not os.path.isfile(path):
        sys.exit(f"Can't find {path}.")
    out_dir = os.path.join(cfg.log_dir, "records", f"{pack_id:#010x}")
    os.makedirs(out_dir, exist_ok=True)
    pack = Pack(path)
    starts = pack.record_starts()
    lines, total = [], 0
    for j, (off, did) in enumerate(starts):
        end = starts[j + 1][0] if j + 1 < len(starts) else len(pack.data)
        if did >> 24 not in types:
            continue
        with open(os.path.join(out_dir, f"{did:#010x}.bin"), "wb") as f:
            f.write(pack.data[off:end])
        total += end - off
        lines.append(f"{did:#010x} {end - off} bytes")
    with open(os.path.join(out_dir, "ids.txt"), "w") as f:
        f.write("\n".join(f"{d:#010x}" for d in pack.ids) + "\n")
    with open(os.path.join(out_dir, "index.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(lines)} records ({total // 1024} KB) written to {out_dir}")
    print("Zip that folder and send it.")


# achievement definition properties read by the client (0xa43530)
ACHIEVEMENT_KEYS = (0x10000BAE, 0x10000BAD, 0x10000C58, 0x10000A25)


def dump_achievements():
    cfg = config_mod.load()
    rp_dir = os.path.join(cfg.game_dir, "rp")
    out_dir = os.path.join(cfg.log_dir, "records", "achievements")
    os.makedirs(out_dir, exist_ok=True)
    pats = [struct.pack("<I", k) for k in ACHIEVEMENT_KEYS]
    files = sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp"))
    lines = []
    for i, name in enumerate(files, 1):
        print(f"\r[{i}/{len(files)}] {name}          ", end="", flush=True)
        try:
            pack = Pack(os.path.join(rp_dir, name))
        except Exception as e:      # noqa: BLE001
            lines.append(f"{name}: could not be read ({e})")
            continue
        if not any(p in pack.data for p in pats):
            continue
        starts = pack.record_starts()
        for j, (off, did) in enumerate(starts):
            end = starts[j + 1][0] if j + 1 < len(starts) else len(pack.data)
            if end - off > 1 << 20 or did >> 24 not in (0x40, 0x48, 0x49, 0x4A, 0x1D, 0x1E):
                continue
            data = pack.data[off:end]
            hits = [hex(k) for k, p in zip(ACHIEVEMENT_KEYS, pats) if p in data]
            if not hits:
                continue
            with open(os.path.join(out_dir, f"{did:#010x}.bin"), "wb") as f:
                f.write(data)
            lines.append(f"{did:#010x} in {name}, {len(data)} bytes, keys {' '.join(hits)}")
    with open(os.path.join(out_dir, "index.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n{len(lines)} records written to {out_dir}. Zip that folder and send it.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args == ["achievements"]:
        return dump_achievements()
    if args == ["uistate"]:
        return dump_pack_types(UI_PACK, UI_TYPES + ((0x20,) if "--swf" in sys.argv else ()))
    follow = "--follow" in sys.argv
    if args == ["vehicles"]:
        args, follow = [hex(d) for d in VEHICLES], True
    if args == ["destruction"]:
        args = [hex(d) for d in DESTRUCTION]
        sys.argv.append("--all")
    wanted = [int(a, 16) for a in args] or DEFAULT
    refs = extract(wanted, follow)
    if follow and refs:
        print(f"\nFollowing {len(refs)} referenced records...")
        extract(sorted(refs)[:200], False, append=True)


def extract(wanted, follow, append=False):
    cfg = config_mod.load()
    rp_dir = os.path.join(cfg.game_dir, "rp")
    if not os.path.isdir(rp_dir):
        sys.exit(f"Can't find the folder {rp_dir}. Check 'dir' in config.toml.")
    out_dir = os.path.join(cfg.log_dir, "records")
    os.makedirs(out_dir, exist_ok=True)
    pending = set(wanted)
    found_refs = set()
    lines = []
    files = sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp"))
    for i, name in enumerate(files, 1):
        if not pending:
            break
        print(f"\r[{i}/{len(files)}] {name}          ", end="", flush=True)
        try:
            pack = Pack(os.path.join(rp_dir, name))
        except Exception as e:      # noqa: BLE001
            lines.append(f"{name}: could not be read ({e})")
            continue
        hit = pending.intersection(pack.ids)
        if not hit:
            continue
        starts = pack.record_starts()
        for j, (off, did) in enumerate(starts):
            if did not in hit:
                continue
            end = starts[j + 1][0] if j + 1 < len(starts) else len(pack.data)
            data = pack.data[off:end]
            with open(os.path.join(out_dir, f"{did:#010x}.bin"), "wb") as f:
                f.write(data)
            lines.append(f"{did:#010x} in {name}, {len(data)} bytes")
            pending.discard(did)
            if "--all" in sys.argv:
                pat = struct.pack("<I", did)
                k, n = pack.data.find(pat), 0
                while k >= 0 and n < 40:
                    with open(os.path.join(out_dir, f"{did:#010x}@{k:08x}.bin"), "wb") as f:
                        f.write(pack.data[k:k + 8192])
                    n += 1
                    k = pack.data.find(pat, k + 1)
                lines.append(f"  {n} places in {name} (--all)")
                # where the pack's ID list puts it: the records around it, and
                # the bytes between the neighbours found before and after it
                pos = {d: o for o, d in starts}
                i = pack.ids.index(did)
                around = pack.ids[max(0, i - 4):i + 5]
                lines.append(f"  list index {i}/{len(pack.ids)}: " + " ".join(
                    f"{d:#010x}@{pos[d]:08x}" if d in pos else f"{d:#010x}@?" for d in around))
                prev = next((pos[d] for d in reversed(pack.ids[max(0, i - 50):i]) if d in pos), None)
                nxt = next((pos[d] for d in pack.ids[i + 1:i + 50] if d in pos and (prev is None or pos[d] > prev)), None)
                if prev is not None and nxt is not None and 0 < nxt - prev <= 4 << 20:
                    with open(os.path.join(out_dir, f"{did:#010x}_region@{prev:08x}.bin"), "wb") as f:
                        f.write(pack.data[prev:nxt])
                    lines.append(f"  region {prev:#x}..{nxt:#x} ({nxt - prev} bytes) written")
            # other scriptlets / script records it refers to
            for k in range(0, len(data) - 3):
                v = struct.unpack_from("<I", data, k)[0]
                if v in wanted or v == did:
                    continue
                if v >> 24 == 0x34 and (v & 0xFFFFFF) < 0x4000:
                    found_refs.add(v)
                elif follow and v >> 24 in FOLLOW_PREFIXES and 0 < (v & 0xFFFFFF) < 0x20000:
                    found_refs.add(v)
    for did in sorted(pending):
        lines.append(f"{did:#010x} NOT FOUND")
    if found_refs:
        lines.append("other scriptlets referenced: " + " ".join(f"{d:#010x}" for d in sorted(found_refs)))
    with open(os.path.join(out_dir, "index.txt"), "a" if append else "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    print(f"\nDone: {out_dir}")
    return found_refs if follow else set()


if __name__ == "__main__":
    main()
