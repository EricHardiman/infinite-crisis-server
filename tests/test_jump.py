"""[tutorial] start_at: each jump into the bridge part starts where it should.

  python tests/test_jump.py <config.toml>

Uses the same simulated client as test_e2e.py, one short match per jump.
"""
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_e2e as E                                          # noqa: E402
from icserver import config as config_mod, log                # noqa: E402
from icserver.server import Server                             # noqa: E402

EXPECT = {                      # start_at -> (conversation it must reach, HUD element highlighted or None)
    "bridge": (0x1C9, None),
    "camera": (0x196, 22),
    "gate_fight": (0x1D2, None),
    "unlock_e": (0x1D1, 28),
    "e_practice": (0x190, None),
    "vehicle": (0x1E2, None),
    "scream": (0x1B0, None),
    "strength": (0x1C1, 23),
    "destroyer": (0x1D7, None),
}


def enter(cfg, u):
    """Queue, lobby, load, intro cinematic: until the tutorial starts."""
    s = cfg["server"]
    t0 = time.monotonic()
    u.send_event(E.SVC, 0x20EB, struct.pack("<II", 0x40000991, 0) + b"\x00" + struct.pack("<i", -1))
    u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20FA)
    u.send_event(E.SVC, 0x20CA, b"")
    time.sleep(0.3)
    g = E.Client(s["game_port"], "game")
    g.sock.sendall(b"\x00" * 40)
    u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20AF)
    g.send_event(E.SVC, 0x20F2, b"")
    g.send_event(E.SVC, 0x20D5, struct.pack("<I", 25))
    u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x4, 5)
    time.sleep(cfg["timing"]["link_delay"] + 0.2)
    g.send_event(E.PLAYER, 0x2, bytes.fromhex("5e010010") + bytes(8))
    u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20F5, cfg["timing"]["cinematic_delay"] + 2)
    g.send_event(E.PLAYER, 0x2, bytes.fromhex("17010010") + struct.pack("<II", 4, cfg["match"]["cinematic"]))
    return g


def main(cfg_path):
    cfg = config_mod.load(cfg_path)
    cfg["tutorial"]["pacing"] = 0.0
    log.setup(cfg.log_dir, cfg["debug"]["hexdump"])
    server = Server(cfg)
    server.start()
    u = E.login_and_menu(cfg, server)
    for where, (conv, element) in EXPECT.items():
        cfg["tutorial"]["start_at"] = where
        t0 = time.monotonic()
        g = enter(cfg, u)
        got = u.wait_for(lambda e: e[0] >= t0 and E.conv_key(e) == conv, 8)
        E.check(f"start_at = {where}: reaches conversation {conv:#x}", got)
        if element:
            E.check(f"start_at = {where}: HUD element {element} highlighted",
                    u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x213D
                               and struct.unpack_from("<II", e[3], 1) == (element, 7), 3))
        E.check(f"start_at = {where}: no part-1 marker (guide ping 1)",
                not [e for e in list(u.events) if e[0] >= t0 and e[2] == 0x4 and e[1] == 0x0200000000000031])
        g.close()
        time.sleep(0.6)
    u.close()
    bad = [n for n, ok in E.CHECKS if not ok]
    print(f"\n{len(E.CHECKS) - len(bad)}/{len(E.CHECKS)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
