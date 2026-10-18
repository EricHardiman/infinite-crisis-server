"""John Stewart's kit (fase3-jc, icserver/kits.py) with a simulated client: python tests/test_kits.py <config.toml>

Coast City v AI with the champion select: lock John Stewart (0x40000E57), rank Q W E R with the '+', cast each
one at the training drone and check the log: the graph events, the scriptlets, the hits, cooldown and Will.
"""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import test_e2e as T
from icserver.wire import build_position
from icserver import config as config_mod, log
from icserver.server import Server

LOCK = 0x21F0        # a made-up lock event id for the test
cfg = config_mod.load(sys.argv[1]); log.setup(cfg.log_dir, False)
maps = cfg["match"].setdefault("maps", {})
entry = dict(maps.get("0x40000B6A") or {})
entry["lobby"] = {"teams": 2, "per_team": 1, "lock_events": [LOCK], "wait": 30.0, "lock_delay": 0.5,
                  "bot": {"champion": 0x40000086, "xyz": [137.47, 60.22, 250.19], "yaw": -1.2}}
entry.setdefault("packs", [0xA0000076])
entry["free"] = {"start_level": 6, "skill_points": 6, "level_up_seconds": 0, "tour": False, "drone_offset": [6.0, 0.0],
                 "drone_class": 0x40000A5C}
maps["0x40000B6A"] = entry
server = Server(cfg); server.start()
u = T.login_and_menu(cfg, server)
JOHN = 0x40000E57
u.send_event(T.SVC, 0x20EB, struct.pack("<II", 0x40000B6A, 0) + b"\x00" + struct.pack("<i", -1))
T.check("match found", u.wait_for(lambda e: e[2] == 0x20FA))
u.send_event(T.SVC, 0x20CA, b""); time.sleep(0.3)
g = T.Client(cfg["server"]["game_port"], "game"); g.sock.sendall(b"\x00" * 40)
time.sleep(1.0)
g.send_event(T.SVC, 0x20F2, b""); time.sleep(0.5)
g.send_event(T.SVC, 0x20D5, struct.pack("<I", 25)); time.sleep(0.3)
t2 = time.monotonic()
g.send_event(T.SVC, 0x20E4, struct.pack("<IBI", JOHN, 1, 1))
T.check("John Stewart is the champion object",
        u.wait_for(lambda e: e[0] >= t2 and e[2] == 0x4 and T.object_class(e[3]) == JOHN,
                   cfg["timing"]["objects_max_wait"] + 4)
        or g.wait_for(lambda e: e[0] >= t2 and e[2] == 0x4 and T.object_class(e[3]) == JOHN, 1))
t3 = time.monotonic()
g.send_event(T.PLAYER, 0x2, bytes.fromhex("5e010010") + bytes(8))
time.sleep(cfg["timing"]["cinematic_delay"] + 2.5)
drones = T.new_objects(u, t3, {0x40000A5C}) or T.new_objects(g, t3, {0x40000A5C})
T.check("training drone spawned", bool(drones))
drone = drones[0] if drones else 0
for slot in (1, 2, 3, 4):
    g.send_event(T.SVC, 0x2136, T.rank(slot)); time.sleep(0.5)
LOG = os.path.join(cfg.log_dir, "server.log")
def logged(text):
    return text in open(LOG, encoding="utf-8").read()
T.check("Q W E R ranked", all(logged(f"free play: slot {s} to rank 1") for s in (1, 2, 3, 4)))
DRONE_XYZ = (26.19, 57.44, 250.2)
def cast(slot):
    g.send_event(T.SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, slot, drone)
                 + build_position(1, 0x23, 0xE3, 0, *DRONE_XYZ) + b"\x00")
cast(3); time.sleep(0.5)
T.check("E: Forward Base built", logged("John Stewart: Forward Base (rank 1") and logged("Forward Base built at"))
T.check("E: Wildcard_ESkill raised", logged("Forward Base: graph event Wildcard_ESkill"))
cast(1); time.sleep(2.5)
T.check("Q: Full Auto cast", logged("John Stewart: Full Auto (rank 1, 40 damage, 30 Will, cooldown 14 s)"))
T.check("Q: the barrage hits the drone", logged("Full Auto hits Training Drone"))
cast(1); time.sleep(0.3)
T.check("Q: second cast refused by the cooldown", logged("Full Auto: on cooldown"))
cast(2); time.sleep(1.8)
T.check("W: Claymore Mine placed and goes off on the drone", logged("Claymore Mine placed") and
        logged("Claymore Mine hits Training Drone"))
time.sleep(6.0)
cast(4); time.sleep(2.5)
T.check("R: Omni Turret built and shoots the drone", logged("Omni Turret built") and logged("Omni Turret hits Training Drone"))
T.check("the drone stays indestructible", logged("Training Drone hit (") and not logged("Training Drone defeated"))
T.check("John's scriptlets resolved", not logged("kits: no scriptlet named"))
print(f"{sum(ok for _, ok in T.CHECKS)}/{len(T.CHECKS)} checks passed")
os._exit(0 if all(ok for _, ok in T.CHECKS) else 1)
