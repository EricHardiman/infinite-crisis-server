"""The overview movie's preference queues the player at once (fase3-fs):
JoinQueue answers arrive before the client's own JoinQueue, which then only
gets them again, and AcceptMatch still refers it to the game port.

    python tests/test_movie_queue.py tests/e2e.example.toml
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_e2e as T                       # noqa: E402
from icserver import config as config_mod, log   # noqa: E402
from icserver.server import Server         # noqa: E402


def main(cfg_path):
    cfg = config_mod.load(cfg_path)
    cfg["match"]["queue_on_movie_end"] = True       # off by default since 16:23; tests the option
    log.setup(cfg.log_dir, cfg["debug"]["hexdump"])
    server = Server(cfg)
    server.start()
    u = T.login_and_menu(cfg, server)
    t0 = time.monotonic()
    name = b"User.SawEncounterOverviewMovie@0x40000991"
    value = "True".encode("utf-16-le")
    u.send_event(T.SVC, 0x216E, bytes([len(name)]) + name + bytes([4]) + value + bytes.fromhex("330c0010"))
    T.check("movie preference -> joined queue + match found",
            u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20FA, 2.0))
    sess = server.sessions[-1]
    T.check("session QUEUED after the movie", sess.phase == "QUEUED", sess.phase)
    t1 = time.monotonic()
    u.send_event(T.SVC, 0x20EB, struct.pack("<II", 0x40000991, 0x00300000) + b"\x01" + struct.pack("<i", -1))
    T.check("client's own JoinQueue answered again", u.wait_for(lambda e: e[0] >= t1 and e[2] == 0x20FA, 2.0))
    T.check("same match kept", sess.match is not None and sess.phase == "QUEUED", sess.phase)
    u.send_event(T.SVC, 0x20CA, b"")
    time.sleep(0.3)
    T.check("AcceptMatch -> referral", sess.phase == "REFERRED", sess.phase)
    # fase3-gf: Exit Match before the end (0x12D on an unfinished match), then Launch again
    u.send_event(T.SVC, 0x12D, b"")
    time.sleep(0.4)
    T.check("Exit Match mid-match -> back in the menus", sess.phase == "MENU" and sess.match is None, sess.phase)
    t3 = time.monotonic()
    u.send_event(T.SVC, 0x20EB, struct.pack("<II", 0x40000991, 0x00300000) + b"\x01" + struct.pack("<i", -1))
    T.check("...and Launch works again", u.wait_for(lambda e: e[0] >= t3 and e[2] == 0x20FA, 2.0))
    u.send_event(T.SVC, 0x20CA, b"")
    time.sleep(0.3)
    # fase3-fz: queue_on_movie_end off (default): the client back on the Launch
    # screen after the movie (banner request 0x212E) is queued by the server
    cfg["match"]["queue_on_movie_end"] = False
    u2 = T.login_and_menu(cfg, server)
    s2 = server.sessions[-1]
    t2 = time.monotonic()
    u2.send_event(T.SVC, 0x216E, bytes([len(name)]) + name + bytes([4]) + value + bytes.fromhex("330c0010"))
    time.sleep(0.5)
    T.check("movie start alone does not queue", s2.phase == "MENU", s2.phase)
    u2.send_event(T.SVC, 0x212E, b"")
    T.check("back on the Launch screen after the movie -> queued",
            u2.wait_for(lambda e: e[0] >= t2 and e[2] == 0x20FA, 2.0))
    T.check("session QUEUED", s2.phase == "QUEUED", s2.phase)
    u2.send_event(T.SVC, 0x212E, b"")
    time.sleep(0.5)
    T.check("a later banner request does nothing more", s2.phase == "QUEUED", s2.phase)

    log.flush()
    failed = [n for n, ok in T.CHECKS if not ok]
    print(f"{len(T.CHECKS) - len(failed)}/{len(T.CHECKS)} checks passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "e2e.example.toml"))
