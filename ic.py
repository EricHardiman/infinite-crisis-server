"""Infinite Crisis preservation server -- one command for everything.

  python ic.py doctor          checks that everything is ready (and how to fix what isn't)
  python ic.py patch           creates the key (if missing) and InfiniteCrisis_patched.exe
  python ic.py patch --newkey  new key + new patched exe
  python ic.py server          server only (to open the game by hand or from Steam)
  python ic.py play            server + opens the game
  python ic.py client-args     shows the game's launch arguments
  python ic.py layout 0xa0000256   lists the entities placed in a pack (name, state, position)
  python ic.py variants 0xa0000257 lists which variant (with health/combat) each world state uses

Options: --config file.toml   --force (start even if doctor finds failures)
         --classic (player object = Batman 0x40000086; old spelling --clasico also works)
"""
import argparse
import bisect
import os
import subprocess
import sys
import time

from icserver import config as config_mod
from icserver import doctor, log, patcher


def client_args(cfg):
    s, g = cfg["server"], cfg["game"]
    base = f"http://{s['host']}:{s['soap_port']}/WebLoginApp-1.3"
    return ["--loginurl", f"{base}/AuthenticateWS", "--loginregion", g["region"],
            "--reportingurl", f"{base}/Metrics", "--language", g["language"]]


def launch_client(cfg):
    exe = cfg.game_file(cfg["game"]["patched_exe"])
    args = client_args(cfg)
    aff = cfg["game"]["cpu_affinity"]
    if os.name == "nt":
        affinity = f"/affinity {aff} " if aff else ""
        cmd = f'start "" {affinity}"{exe}" ' + " ".join(args)
        subprocess.Popen(cmd, shell=True, cwd=cfg.game_dir)
    else:
        subprocess.Popen([exe] + args, cwd=cfg.game_dir)
    print(f"Game launched: {exe}")


def cmd_doctor(cfg, args):
    print("Checking the installation...\n")
    results, ok = doctor.run(cfg)
    doctor.print_report(results)
    print("\nAll set. Use:  python ic.py play" if ok else "\nThere are failures: fix the ones marked FAIL.")
    return 0 if ok else 1


def cmd_patch(cfg, args):
    if args.newkey or not os.path.isfile(cfg.key_path):
        patcher.new_key(cfg.key_path)
        print(f"New key: {cfg.key_path}")
    src = cfg.game_file(cfg["game"]["exe"])
    dst = cfg.game_file(cfg["game"]["patched_exe"])
    try:
        carrier = cfg["combat"].get("prop_carriers") or None
        for line in patcher.build(src, dst, cfg.key_path, carrier=carrier):
            print("  " + line)
    except (OSError, ValueError) as e:
        print(f"Could not patch: {e}")
        return 1
    print(f"Done: {dst}")
    return 0


def _start_server(cfg, args):
    results, ok = doctor.run(cfg, quick=True)
    if not ok:
        doctor.print_report([x for x in results if x[0] != doctor.OK])
        if not args.force:
            print("\nNot starting because there are failures (use --force to try anyway).")
            return None
    from icserver.server import Server
    log.setup(cfg.log_dir, cfg["debug"]["hexdump"])
    server = Server(cfg)
    server.start()
    print(f"Logs in {cfg.log_dir}  (server.log, traffic.log, unhandled.log)")
    return server


def _wait():
    print("Server running. Ctrl+C to stop it.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nServer stopped.")


def cmd_server(cfg, args):
    if _start_server(cfg, args) is None:
        return 1
    print("Open the game with these arguments:")
    print(f'  {cfg["game"]["patched_exe"]} ' + " ".join(client_args(cfg)))
    _wait()
    return 0


def open_app_window(url):
    """The app in a window of its own: Edge or Chrome app mode, else the browser."""
    import shutil
    import webbrowser
    candidates = []
    if os.name == "nt":
        pf = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")]
        candidates = [os.path.join(b, *rel) for b in pf if b for rel in (
            ("Microsoft", "Edge", "Application", "msedge.exe"), ("Google", "Chrome", "Application", "chrome.exe"))]
    candidates += [shutil.which(n) or "" for n in ("msedge", "google-chrome", "chromium", "chrome")]
    for exe in candidates:
        if exe and os.path.isfile(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1360,860"])
            return
    webbrowser.open(url)


def _app_url(cfg):
    s = cfg["server"]
    host = "127.0.0.1" if s["host"] in ("0.0.0.0", "", "::") else s["host"]
    return f"http://{host}:{s['soap_port']}/app"


def _switcher(cfg, server):
    """2026-10-16 16:58: the interface switch (icserver/interface.py) and its
    hotkey, for both interfaces."""
    from icserver import interface, winctl
    url = _app_url(cfg)
    server.launch_client = lambda: launch_client(cfg)
    server.switcher = interface.Switcher(server, server.launch_client, lambda: open_app_window(url))
    from icserver import emotes
    if emotes.start(server):
        print("Ctrl+1..4 in a match: emotes (Joke, Taunt, Laugh, Dance).")
    key = cfg["app"].get("switch_hotkey", "")
    if key and winctl.hotkey(key, server.switcher.toggle):
        print(f"{key.upper()} in the game: switch to the new interface.")


def cmd_app(cfg, args):
    """2026-10-16: the new interface. The server plus the app window; the app's
    Play button starts the game and the match loads right after the login."""
    from icserver import interface
    server = _start_server(cfg, args)
    if server is None:
        return 1
    interface.set_mode(cfg, "new")
    _switcher(cfg, server)
    url = _app_url(cfg)
    print(f"App: {url}")
    if cfg["app"].get("open_window", True):
        open_app_window(url)
    print("Press Play in the app: the game opens; log in and the match loads by itself.")
    _wait()
    return 0


def cmd_legacy(cfg, args):
    """Back to the legacy interface (the game's own menus) and play."""
    from icserver import interface
    interface.set_mode(cfg, "legacy")
    return cmd_play(cfg, args)


def cmd_play(cfg, args):
    """Opens the interface the player chose last (the legacy one, the game's own
    menus, on the first start; the app's Settings and the hotkey switch it)."""
    from icserver import interface
    if interface.mode(cfg) == "new":
        return cmd_app(cfg, args)
    server = _start_server(cfg, args)
    if server is None:
        return 1
    _switcher(cfg, server)
    launch_client(cfg)
    print("Log in with any username and password -> Play Now -> VS A.I. -> Tutorial -> Tutorial 1 -> Launch")
    _wait()
    return 0


def cmd_layout(cfg, args):
    import math
    from icserver import rp
    packs = rp.PackSet(os.path.join(cfg.game_dir, "rp"))
    for pack_id in args.args or ["0xa0000256"]:
        pack = packs.pack(int(pack_id, 16))
        print(f"== {pack.name}")
        for e in rp.layout_entries(pack):
            pts = e["positions"]
            where = ""
            if pts:
                p = pts[0]
                w, x, y, z = p["quat"]
                where = (f"lb {p['lb'][0]:02x}{p['lb'][1]:02x} ({p['xyz'][0]:.2f}, {p['xyz'][1]:.2f}, "
                         f"{p['xyz'][2]:.2f}) yaw {2 * math.atan2(z, w):.3f}"
                         + (f"  +{len(pts) - 1} path points" if len(pts) > 1 else ""))
            print(f"  {e['record']:08x} {e['name']:<20} {e['wstate']:08x}  {where}")
    return 0


def cmd_variants(cfg, args):
    from icserver import rp
    packs = rp.PackSet(os.path.join(cfg.game_dir, "rp"))
    for pack_id in args.args or ["0xa0000257"]:
        for ws, var in sorted(rp.variants_for_wstates(packs.pack(int(pack_id, 16))).items()):
            print(f"  state {ws:08x} -> variant {var:08x}")
    return 0


def cmd_entities(cfg, args):
    """Search EVERY pack for the entity (0x40...) of each world state; slow (minutes)."""
    import struct
    from icserver import rp
    wanted = [int(a, 16) for a in args.args] or [0x2E000AAB, 0x2E0007D4]
    rp_dir = os.path.join(cfg.game_dir, "rp")
    names = sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp"))
    found = {w: [] for w in wanted}
    for i, name in enumerate(names, 1):
        print(f"\r[{i}/{len(names)}] {name}        ", end="", flush=True)
        path = os.path.join(rp_dir, name)
        try:
            with open(path, "rb") as f:
                cat = struct.unpack("<I", f.read(8)[4:8])[0]
            pack = rp.Pack(path)
        except (OSError, ValueError) as e:
            print(f"\n  {name}: {e}")
            continue
        for ws, ent in rp.entity_classes_for(pack, wanted).items():
            found[ws].append(f"{ent:#010x} in {name} (category {cat:#x})")
        del pack
    lines = [f"{w:#010x}: " + ("; ".join(v) or "no entity") for w, v in found.items()]
    out = os.path.join(cfg.log_dir, "entities.txt")
    os.makedirs(cfg.log_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines) + f"\nSaved to {out}")
    return 0


def cmd_dump(cfg, args):
    """Dump for studying the vehicle and the meteors: searches EVERY pack for the
    requested records (and the ones they name: .entity 0x2D, states 0x2E,
    entities 0x40/0x49, cinematics 0x35), who references them, and the key
    strings. Writes logs\\dump.txt. Slow (several minutes)."""
    import struct
    from icserver import rp
    # args: DIDs (hex) and/or texts; a text hit adds the record that holds it
    # (and, one round later, the records that name that one) to the dump
    def _hex(a):
        try:
            return int(a, 16)
        except ValueError:
            return None
    wanted = [d for d in (_hex(a) for a in args.args) if d is not None]
    arg_texts = [a.encode() for a in args.args if _hex(a) is None]
    if not wanted and not arg_texts:
        wanted = [0x2E000AAB, 0x2D0008BC, 0x2E0007D4, 0x35000034, 0x35000025]
    texts = arg_texts or [b"meteor", b"Meteor", b"DestVehicle", b"vehicle", b"Vehicle"]
    follow_refs = bool(arg_texts)
    rp_dir = os.path.join(cfg.game_dir, "rp")
    names = sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp"))
    out_lines, seen, refs, hits = [], set(), {}, {}
    todo = list(wanted)
    MAX = 6000

    def hexdump(b):
        rows = []
        for i in range(0, len(b), 32):
            chunk = b[i:i + 32]
            asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
            rows.append(f"    {i:05x} {chunk.hex()}  {asc}")
        return rows

    for rnd in range(3):            # follow references 2 levels deep
        if not todo and (rnd or not texts):
            break
        batch = [d for d in todo if d not in seen]
        todo = []
        seen.update(batch)
        pats = {d: struct.pack("<I", d) for d in batch}
        for i, name in enumerate(names, 1):
            print(f"\r[round {rnd + 1}] [{i}/{len(names)}] {name}        ", end="", flush=True)
            try:
                pack = rp.Pack(os.path.join(rp_dir, name))
            except (OSError, ValueError):
                continue
            ids = set(pack.ids)
            starts = None
            for d, pat in pats.items():
                k = pack.data.find(pat)
                if k < 0:
                    continue
                if starts is None:
                    starts = pack.record_starts()
                    offs = [o for o, _ in starts]
                while k >= 0:
                    j = bisect.bisect_right(offs, k) - 1
                    rec_off, rec_did = starts[j] if j >= 0 else (0, 0)
                    if rec_did == d and rec_off == k and d in ids:
                        end = offs[j + 1] if j + 1 < len(offs) else len(pack.data)
                        body = pack.data[k:min(end, k + MAX)]
                        out_lines.append(f"== record {d:08x} in {name} ({end - k} bytes)")
                        out_lines += hexdump(body)
                        for q in range(0, len(body) - 3):
                            v = struct.unpack_from("<I", body, q)[0]
                            if v >> 24 in (0x2D, 0x2E, 0x40, 0x49, 0x35, 0x3A, 0x1D) and v != d and (v & 0xFFFFFF) < 0x40000:
                                todo.append(v)
                    else:
                        refs.setdefault(d, set()).add(f"{rec_did:08x}@{name}")
                        if follow_refs and rec_did >> 24 in (0x2E, 0x40, 0x49, 0x1D, 0x35):
                            todo.append(rec_did)
                    k = pack.data.find(pat, k + 1)
            if rnd == 0:
                for t in texts:
                    k = pack.data.find(t)
                    n = 0
                    while k >= 0 and n < 40:
                        ctx = pack.data[max(0, k - 24):k + 64]
                        if arg_texts:
                            if starts is None:
                                starts = pack.record_starts()
                                offs = [o for o, _ in starts]
                            j = bisect.bisect_right(offs, k) - 1
                            if j >= 0:
                                todo.append(starts[j][1])
                                hits.setdefault(t.decode(), []).append(f"   (in record {starts[j][1]:08x})")
                        hits.setdefault(t.decode(), []).append(
                            f"{name}+{k:x}: " + "".join(chr(c) if 32 <= c < 127 else "." for c in ctx))
                        k = pack.data.find(t, k + 1)
                        n += 1
            del pack
        todo = sorted(set(todo) - seen)[:60]
    out_lines.append("== references (record that contains the DID)")
    for d in sorted(refs):
        out_lines.append(f"  {d:08x}: " + ", ".join(sorted(refs[d])[:40]))
    out_lines.append("== strings")
    for t, v in hits.items():
        out_lines += [f"  [{t}] {x}" for x in v[:40]]
    out = os.path.join(cfg.log_dir, "dump.txt")
    os.makedirs(cfg.log_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")
    print(f"\nSaved to {out}")
    return 0


def cmd_carriers(cfg, args):
    """Finds entities (0x40...) whose world state resembles the vehicle's
    (same property 0x50F, "creation type") to use them as carriers.
    Writes logs\\carriers.txt. Slow (several minutes)."""
    import re
    import struct
    from icserver import rp
    target = int(args.args[0], 16) if args.args else 0x2E000AAB
    rp_dir = os.path.join(cfg.game_dir, "rp")
    names = sorted(f for f in os.listdir(rp_dir) if f.lower().endswith(".rp"))
    ent_ws = {}            # entity -> (world state, pack)
    ws_info = {}           # world state -> (0x50F value or None, header hex, size, pack)
    pat510 = re.compile(re.escape(struct.pack("<II", 0x510, 0x510)) + rb"(....)", re.S)
    for i, name in enumerate(names, 1):
        print(f"\r[{i}/{len(names)}] {name}        ", end="", flush=True)
        try:
            pack = rp.Pack(os.path.join(rp_dir, name))
        except (OSError, ValueError):
            continue
        twins = set(d for d in pack.ids if d >> 24 == 0x49)
        for m in pat510.finditer(pack.data):
            ws = struct.unpack("<I", m.group(1))[0]
            if ws >> 24 != 0x2E:
                continue
            k = m.start()
            for j in range(k - 4, max(0, k - 8000), -1):
                if pack.data[j + 3] == 0x49:
                    v = struct.unpack_from("<I", pack.data, j)[0]
                    if v in twins and pack.data[j + 4:j + 8] in (b"\0\0\0\0", b"\x03\0\0\0", b"\x04\0\0\0"):
                        ent_ws.setdefault(0x40000000 | (v & 0xFFFFFF), (ws, name))
                        break
        starts = None
        for d in pack.ids:
            if d >> 24 != 0x2E or d in ws_info:
                continue
            k = pack.data.find(struct.pack("<II", d, 7))
            if k < 0:
                continue
            head = pack.data[k:k + 96]
            m = re.search(re.escape(struct.pack("<II", 0x50F, 0x50F)) + rb"(....)", head, re.S)
            v50f = struct.unpack("<I", m.group(1))[0] if m else None
            ws_info[d] = (v50f, head[:64].hex(), name)
        del pack
    tv = ws_info.get(target, (None, "", ""))
    lines = [f"target {target:08x}: 0x50F={tv[0]} header {tv[1]} ({tv[2]})", ""]
    rows = []
    for ent, (ws, pk) in ent_ws.items():
        info = ws_info.get(ws, (None, "", ""))
        score = (info[0] == tv[0]) * 2 + (info[1][16:24] == tv[1][16:24])
        rows.append((score, ent, ws, info, pk))
    rows.sort(key=lambda r: (-r[0], r[1]))
    for score, ent, ws, info, pk in rows[:300]:
        lines.append(f"{score} entity {ent:08x} -> state {ws:08x} 0x50F={info[0]} ({pk}) header {info[1][:96]}")
    out = os.path.join(cfg.log_dir, "carriers.txt")
    os.makedirs(cfg.log_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved to {out} ({len(rows)} entities)")
    return 0


def cmd_stolen_powers(cfg, args):
    """stolen-powers            -> list all, write data/stolen_powers.json
    stolen-powers <text>      -> search (power, champion or DID) with details"""
    from icserver import stolenpowers as sp
    rows = sp.catalog()
    if args.args:
        hits = sp.find(" ".join(args.args), rows)
        if not hits:
            print("No Stolen Power matches that.")
            return 1
        data = {}
        if os.path.isfile(sp.JSON):
            with open(sp.JSON, encoding="utf-8") as f:
                data = {e["did"]: e for e in __import__("json").load(f)}
        for r in hits:
            e = data.get(f"{r['did']:#x}", {})
            extra = (f"  targeting {e.get('targeting')}  script {e.get('script')}" if e else "")
            print(f"{r['did']:#x}  {sp.label(r):45s} icon {r['icon']:#x}{extra}")
        if not data:
            print("(run 'python ic.py stolen-powers' once for the full data: targeting, script, properties)")
        return 0
    built = sp.build(cfg)
    for r in rows:
        print(f"{r['did']:#x}  group {r['group']:2d}  {sp.label(r)}")
    if built is None:
        print("\nOnly the list: the skill data needs logs\\props.txt (python tools\\diag.py --props).")
    else:
        print(f"\n{len(built)} Stolen Powers with their full skill data -> {sp.JSON}")
    print('Use a name in config.toml, e.g. camera_skill = "Surveillance Camera / Gaslight Batman".')
    return 0


def cmd_catalog(cfg, args):
    """catalog -> catalog/index.html (the game ID catalog, see catalog/README.md)"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import build_catalog
    if getattr(args, "scan", False) or "scan" in args.args:
        import catalog_scan
        catalog_scan.scan(cfg)
    build_catalog.build()
    return 0


def cmd_sounds(cfg, args):
    """sounds -> catalog/data/sounds.tsv + sound_banks.tsv: every Wwise event of
    audio\\Audio_SB.pck with its bank and the game records that play it (reads
    every pack: a few minutes). Then the catalog page is rebuilt."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import build_catalog
    from icserver import audio
    pck = os.path.join(cfg.game_dir, "audio", "Audio_SB.pck")
    print(f"Reading {pck} ...")
    evs = audio.events(pck)
    print(f"{len(evs)} sound events; scanning the packs for their users ...")
    names, users = audio.scan_packs(os.path.join(cfg.game_dir, "rp"), set(evs))
    write_sound_tables(evs, names, users)
    build_catalog.build()
    return 0


def write_sound_tables(evs, names, users):
    import csv
    data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog", "data")

    def notes(fn):
        try:
            with open(os.path.join(data, fn), encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f, delimiter="\t"))
        except OSError:
            return {}
        if not rows:
            return {}
        h = rows[0]
        return {r[0]: dict(zip(h, r)) for r in rows[1:] if r}
    old = notes("sounds.tsv")
    by_bank = {}
    rows = []
    for eid, e in sorted(evs.items(), key=lambda kv: (names.get(kv[1]["bank"], ""), kv[0])):
        key = f"0x{eid:08X}"
        bank = names.get(e["bank"], f"0x{e['bank']:08X}")
        by_bank.setdefault(e["bank"], 0)
        by_bank[e["bank"]] += 1
        used = " ".join(f"0x{u:08X}" for u in sorted(users.get(eid, ()))[:12])
        o = old.get(key, {})
        rows.append([key, bank, str(e["actions"]), used, o.get("server_status", "data only"), o.get("notes", "")])
    with open(os.path.join(data, "sounds.tsv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "bank", "actions", "played_by", "server_status", "notes"])
        w.writerows(rows)
    with open(os.path.join(data, "sound_banks.tsv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "name", "events"])
        for bid in sorted(set(by_bank) | set(names)):
            w.writerow([f"0x{bid:08X}", names.get(bid, ""), str(by_bank.get(bid, 0))])
    print(f"sounds.tsv: {len(rows)} events; sound_banks.tsv: {len(set(by_bank) | set(names))} banks")


def cmd_find(cfg, args):
    """find <text or ID> -> every catalog row (all sections) that matches"""
    import csv
    if not args.args:
        print("Usage: python ic.py find <text or ID>   e.g. find 0x48000808 / find camera")
        return 1
    q = " ".join(args.args).strip().lower()
    qid = None
    try:
        qid = int(q, 16) if q.startswith("0x") else None
    except ValueError:
        pass
    data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog", "data")
    hits = 0
    for name in sorted(os.listdir(data)):
        if not name.endswith(".tsv") or name.endswith("_notes.tsv") or name == "scriptlets_other.tsv":
            continue
        with open(os.path.join(data, name), encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f, delimiter="\t"))
        if not rows:
            continue
        head = rows[0]
        for r in rows[1:]:
            cells = [c.lower() for c in r]
            ok = any(q in c for c in cells)
            if not ok and qid is not None:
                for c in r:
                    for tok in c.replace(",", " ").replace(";", " ").split():
                        try:
                            if tok.lower().startswith("0x") and int(tok.split(":")[0], 16) == qid:
                                ok = True
                        except ValueError:
                            pass
            if ok:
                hits += 1
                print(f"[{name[:-4]}] " + " | ".join(f"{h}={v}" for h, v in zip(head, r) if v))
    if not hits:
        print("No match in the catalog (catalog/data/*.tsv).")
    return 0


def cmd_client_args(cfg, args):
    print(" ".join(client_args(cfg)))
    return 0


def cmd_worlds(cfg, args):
    """worlds -> catalog/data/world_states.tsv: every world state (0x2E) of the install, its model
    names, kind, templates, graphs, particles, layout names and the packs it needs (tools/world_scan.py)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import world_scan
    world_scan.scan(args.args[0] if args.args else cfg.game_dir)
    print("Now: python ic.py catalog")
    return 0


def main(argv):
    p = argparse.ArgumentParser(description="Infinite Crisis preservation server")
    p.add_argument("command", choices=["doctor", "patch", "server", "play", "app", "legacy", "sounds", "worlds", "client-args", "layout", "variants", "entities", "dump", "carriers",
                                        "stolen-powers", "catalog", "find"])
    p.add_argument("args", nargs="*")
    p.add_argument("--config")
    p.add_argument("--newkey", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--scan", action="store_true", help="catalog: re-read the game data first")
    p.add_argument("--classic", "--clasico", dest="classic", action="store_true",
                   help="player object = Batman (0x40000086), like the previous emulator")
    args = p.parse_args(argv)
    try:
        cfg = config_mod.load(args.config)
    except Exception as e:
        print(f"Could not read the configuration: {e}")
        return 1
    if args.classic:
        cfg["match"]["player_class"] = 0x40000086
        print("Classic mode: the player object is Batman (0x40000086) again.")
    return {"doctor": cmd_doctor, "patch": cmd_patch, "server": cmd_server,
            "play": cmd_play, "app": cmd_app, "legacy": cmd_legacy, "sounds": cmd_sounds, "worlds": cmd_worlds, "client-args": cmd_client_args, "layout": cmd_layout,
            "variants": cmd_variants, "entities": cmd_entities, "dump": cmd_dump,
            "carriers": cmd_carriers, "stolen-powers": cmd_stolen_powers,
            "catalog": cmd_catalog, "find": cmd_find}[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
