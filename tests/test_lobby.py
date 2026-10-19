"""Champion select (fase3-iy) with a simulated client: python tests/test_lobby.py <config.toml>

Coast City v AI (0x40000B6A, [match] maps "lobby"): 0x204C carries 2 teams of 1, 0x2016 and the object
creation wait for a lock event, and a lock event ends the lobby. The test sets its own lobby settings.
"""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import test_e2e as T
from icserver import config as config_mod, log
from icserver.server import Server

LOCK = 0x21F0        # a made-up lock event id for the test
cfg = config_mod.load(sys.argv[1]); log.setup(cfg.log_dir, False)
maps = cfg["match"].setdefault("maps", {})
entry = dict(maps.get("0x40000B6A") or {})
entry["lobby"] = {"teams": 2, "per_team": 1, "lock_events": [LOCK], "wait": 30.0, "lock_delay": 0.5,
                  "bot": {"champion": 0x40000086, "xyz": [137.47, 60.22, 250.19], "yaw": -1.2}}
entry.setdefault("packs", [0xA0000076])
entry["free"] = {"start_level": 6, "skill_points": 6, "level_up_seconds": 0, "tour": False,
                 "drone_class": 0x40000A5C}
maps["0x40000B6A"] = entry
server = Server(cfg); server.start()
u = T.login_and_menu(cfg, server)
t0 = time.monotonic()
u.send_event(T.SVC, 0x20EB, struct.pack("<II", 0x40000B6A, 0) + b"\x00" + struct.pack("<i", -1))
T.check("match found", u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20FA))
u.send_event(T.SVC, 0x20CA, b""); time.sleep(0.3)
g = T.Client(cfg["server"]["game_port"], "game"); g.sock.sendall(b"\x00" * 40)
time.sleep(1.0)
T.check("no 0x20AF before the lock (fase3-ja)", not [e for e in u.events if e[0] >= t0 and e[2] == 0x20AF])
t1 = time.monotonic()
g.send_event(T.SVC, 0x20F2, b"")
st = u.wait_for(lambda e: e[0] >= t1 and e[2] == 0x204C, 3)
body = st[-1][3] if st else b""
k = body.find(struct.pack("<II", 0x40000B6A, 0))
T.check("0x204C says 2 teams of 1", k >= 8 and struct.unpack_from("<II", body, k - 8) == (2, 1))
T.check("0x204C lists every champion", body.count(struct.pack("<I", 0x400006F9)) >= 1 and len(body) > 200)
g.send_event(T.SVC, 0x20D5, struct.pack("<I", 25))
time.sleep(cfg["timing"]["objects_max_wait"] + 1)
T.check("no 0x2016 before the lock", not [e for e in u.events if e[0] >= t1 and e[2] == 0x2016])
T.check("no objects before the lock", not [e for e in u.events + g.events if e[0] >= t1 and e[2] == 0x4])
t2 = time.monotonic()
g.send_event(T.SVC, 0x20E4, struct.pack("<IBI", 0x400006F9, 1, 1))     # fase3-iz: the client's lock request
slot = u.wait_for(lambda e: e[0] >= t2 and e[2] == 0x2029, 3)
T.check("0x20E4 answered with the slot, Green Arrow, locked",
        slot and struct.pack("<II", 0x400006F9, 0) + b"\x01" in slot[-1][3])
T.check("0x2016 after the lock", u.wait_for(lambda e: e[0] >= t2 and e[2] == 0x2016, 4))
ent = u.wait_for(lambda e: e[0] >= t2 and e[2] == 0x20AF, 2)
T.check("0x20AF after the lock: Green Arrow + the bot's Gaslight Batman",
        ent and struct.pack("<II", 0x400006F9, 0x40000086) in ent[-1][3])
T.check("objects after the lock", (u.wait_for(lambda e: e[0] >= t2 and e[2] == 0x4,
                                               cfg["timing"]["objects_max_wait"] + 3)
                                   or g.wait_for(lambda e: e[0] >= t2 and e[2] == 0x4, 1)))
T.check("the champion object is Green Arrow",
        any(T.object_class(e[3]) == 0x400006F9 for e in u.events + g.events if e[0] >= t2 and e[2] == 0x4))
t3 = time.monotonic()
g.send_event(T.PLAYER, 0x2, bytes.fromhex("5e010010") + bytes(8))      # load complete
time.sleep(cfg["timing"]["cinematic_delay"] + 2.5)
T.check("the bot (Gaslight Batman) is spawned", any(T.object_class(e[3]) == 0x40000086
                                                     for e in u.events + g.events if e[0] >= t3 and e[2] == 0x4))
T.check("free play: level 6 announced", "free play: level 6, 6 skill points" in
        open(os.path.join(cfg.log_dir, "server.log"), encoding="utf-8").read())
T.check("free play: training drone spawned", any(T.object_class(e[3]) == 0x40000A5C
                                                 for e in u.events + g.events if e[0] >= t3 and e[2] == 0x4))
t4 = time.monotonic()
g.send_event(T.SVC, 0x2136, struct.pack("<ffQI", 0, 0, 1, 0x52414E4B) + bytes(8))    # '+' on Q (RankSkill ping)
time.sleep(0.6)
T.check("free play: Q ranked with the '+'", "free play: slot 1 to rank 1, 5 points left" in
        open(os.path.join(cfg.log_dir, "server.log"), encoding="utf-8").read())
logtxt = open(os.path.join(cfg.log_dir, "server.log"), encoding="utf-8").read()
T.check("lobby events logged", "client event 0x20e4" in logtxt)
print(f"{sum(ok for _, ok in T.CHECKS)}/{len(T.CHECKS)} checks passed")
os._exit(0 if all(ok for _, ok in T.CHECKS) else 1)
