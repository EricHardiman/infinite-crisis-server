"""`python ic.py doctor`: checks everything before starting and says how to fix
each problem."""
import glob
import os
import socket
import sys

from . import crypto, patcher

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"

REQUIRED_PACKS = {
    0xA0000037: "generic player",
    0xA0000076: "Gaslight Batman (heavy pack)",
    0xA00000B3: "encounters, pings and strings",
    0xA0000103: "menu icons",
    0xA0000256: "Tutorial 1: conversations, cinematics and drone positions",
    0xA0000257: "tutorial drones",
    0xA0C112CA: "Tutorial 1 map",
}


def run(cfg, quick=False):
    """Returns (results, ok). results = [(status, message, fix or '')]."""
    r = []

    def add(status, msg, fix=""):
        r.append((status, msg, fix))

    # Python
    if sys.version_info >= (3, 11):
        add(OK, f"Python {sys.version.split()[0]}")
    else:
        add(FAIL, f"Python {sys.version.split()[0]} is too old", "install Python 3.11 or newer (64-bit)")
    if crypto.BACKEND:
        add(OK, f"RSA library: {crypto.BACKEND}")
    else:
        add(FAIL, "no RSA library", "pip install pycryptodome")

    # Config
    add(OK if cfg.path else WARN, f"configuration: {cfg.path or 'defaults (no config.toml)'}",
        "" if cfg.path else "copy config.example.toml to config.toml and set the game folder")

    # Game folder
    gdir = cfg.game_dir
    exe = cfg.game_file(cfg["game"]["exe"])
    if not os.path.isdir(gdir):
        add(FAIL, f"game folder does not exist: {gdir}", "fix [game] dir in config.toml")
        return r, False
    add(OK, f"game folder: {gdir}")
    if not os.path.isfile(exe):
        add(FAIL, f"{cfg['game']['exe']} is not in the game folder", "check [game] dir")
    else:
        size = os.path.getsize(exe)
        if size != patcher.KNOWN_SIZE:
            add(FAIL, f"{cfg['game']['exe']} is {size} bytes (expected {patcher.KNOWN_SIZE})",
                "this server only works with the unmodified 2015 Steam client")
        else:
            info = patcher.inspect(exe)
            states = {s for _, s in info["patches"]}
            if states == {"original"} and info["rsa"] == "found":
                if not quick:
                    digest = patcher.sha256(exe)
                    add(OK if digest == patcher.KNOWN_SHA256 else WARN,
                        f"{cfg['game']['exe']}: 2015 version recognized"
                        + ("" if digest == patcher.KNOWN_SHA256 else " (different hash, but the patches fit)"))
                else:
                    add(OK, f"{cfg['game']['exe']}: 2015 version recognized")
            else:
                add(FAIL, f"{cfg['game']['exe']} is already modified or a different version",
                    "restore the original: Steam > Properties > Verify integrity of game files")

    # Data packs
    rp_dir = os.path.join(gdir, "rp")
    packs = glob.glob(os.path.join(rp_dir, "*.rp"))
    if len(packs) >= 600:
        add(OK, f"data packs: {len(packs)} .rp files")
    else:
        add(FAIL, f"data packs: only {len(packs)} .rp files in {rp_dir} (should be 616)",
            "install the full Steam version: steam://install/345520")
    names = {os.path.basename(p).lower() for p in packs}
    for pack, what in REQUIRED_PACKS.items():
        if f"0x{pack:08x}.rp" not in names:
            add(FAIL, f"missing pack 0x{pack:08x}.rp ({what})", "verify the game files in Steam")

    # Roster
    ch = cfg.champions_path()
    add(OK if ch else FAIL, f"champion list: {ch or 'not found'}",
        "" if ch else "copy champions.json from the original project (_server) into the data\\ folder")

    # Key + patched exe
    key = None
    if os.path.isfile(cfg.key_path):
        try:
            key = crypto.load_key(cfg.key_path)
            add(OK if key.bits == 1024 and key.e == 65537 else FAIL, f"server key: {cfg.key_path}",
                "" if key.bits == 1024 else "generate a new one: python ic.py patch --newkey")
        except Exception as e:
            add(FAIL, f"could not read the key: {e}", "generate a new one: python ic.py patch --newkey")
    else:
        add(FAIL, "no server key", "python ic.py patch   (creates it and patches the exe)")
    patched = cfg.game_file(cfg["game"]["patched_exe"])
    if not os.path.isfile(patched):
        add(FAIL, f"{cfg['game']['patched_exe']} does not exist", "python ic.py patch")
    elif key is not None:
        info = patcher.inspect(patched, key)
        missing = [d for d, s in info["patches"] if s != "patched"]
        if missing:
            add(FAIL, f"the patched exe is missing patches: {', '.join(missing)}", "python ic.py patch")
        elif not info["key_match"]:
            add(FAIL, "the patched exe was made with a DIFFERENT key: login would fail silently",
                "python ic.py patch   (redoes it with the current key)")
        else:
            add(OK, f"{cfg['game']['patched_exe']}: {len(info['patches'])} patches and key correct")

    # Ports
    s = cfg["server"]
    for name, port in (("login", s["soap_port"]), ("user", s["user_port"]), ("game", s["game_port"])):
        try:
            probe = socket.create_server((s["host"], port))
            probe.close()
            add(OK, f"port {port} ({name}) free")
        except OSError:
            add(FAIL, f"port {port} ({name}) is in use",
                "close the old server (login_server.py / tracer.py) or another copy of this one")

    return r, all(st != FAIL for st, _, _ in r)


def print_report(results):
    for status, msg, fix in results:
        print(f"  [{status}] {msg}")
        if fix and status != OK:
            print(f"          -> {fix}")
