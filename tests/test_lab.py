"""Tutorial 2 lab with a simulated client (fase3-hb): python tests/test_lab.py <config.toml>

Needs the real packs (0xA00002E5, 0xA000009A) in the config's game folder; set
[match] event_packs_unchecked = true and small [debug] lab_interval / lab_start
(see tests/e2e.example.toml). Deletes logs/model_tour.json of that config.
"""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import test_e2e as T
from icserver import config as config_mod, log
from icserver.server import Server
cfg = config_mod.load(sys.argv[1]); log.setup(cfg.log_dir, False)
try: os.remove(os.path.join(cfg.log_dir, "model_tour.json"))
except OSError: pass
server = Server(cfg); server.start()
u = T.login_and_menu(cfg, server)
t0 = time.monotonic()
u.send_event(T.SVC, 0x20EB, struct.pack("<II", 0x40000A81, 0) + b"\x00" + struct.pack("<i", -1))
T.check("match found", u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20FA))
u.send_event(T.SVC, 0x20CA, b""); time.sleep(0.3)
g = T.Client(cfg["server"]["game_port"], "game"); g.sock.sendall(b"\x00" * 40)
enter = u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20AF)
SECOND = 0xA000024C if str(cfg["debug"].get("lab_tour", "")).startswith("models1") else 0xA000009A
T.check(f"enter match carries 2E5 and {SECOND:#X}", enter and struct.pack("<I", 0xA00002E5) in enter[-1][3]
        and struct.pack("<I", SECOND) in enter[-1][3])
g.send_event(T.SVC, 0x20F2, b""); u.wait_for(lambda e: e[2] == 0x206D)
g.send_event(T.SVC, 0x20D5, struct.pack("<I", 25)); time.sleep(cfg["timing"]["objects_min_delay"] + 1)
t1 = time.monotonic()
g.send_event(T.PLAYER, 0x2, bytes.fromhex("5e010010") + bytes(8))
T.check("lab objective list", u.wait_for(lambda e: e[0] >= t1 and e[2] == 0x2034, 4))
dc = cfg["debug"]
time.sleep(float(dc["lab_start"]) + 1.0)
import re
if str(dc.get("lab_tour", "")) == "batman":
    # fase3-ih: the Gaslight Batman champion tour (set a small [debug] champion_tour_interval)
    logtxt = open(os.path.join(cfg.log_dir, "server.log"), encoding="utf-8").read()
    m_ = re.findall(r"champion tour: (\d+) entries", logtxt)
    n = int(m_[-1]) if m_ else 0
    T.check(f"champion tour has entries ({n})", n >= (len(dc.get("champion_tour_only") or []) or 400))
    time.sleep(float(dc.get("champion_tour_interval", 3.0)) * n + 3.0)
    runs = [e for e in u.events if e[0] >= t1 and e[2] == 0x8D]
    T.check(f"one scriptlet per entry ({len(runs)} >= {n})", len(runs) >= n)
    T.check("objective text per entry", len([e for e in u.events if e[0] >= t1 and e[2] == 0x2009]) >= n)
    print(f"{sum(ok for _, ok in T.CHECKS)}/{len(T.CHECKS)} checks passed")
    os._exit(0 if all(ok for _, ok in T.CHECKS) else 1)
logtxt = open(os.path.join(cfg.log_dir, "server.log"), encoding="utf-8").read()
m_ = re.findall(r"lab: \d+ models, (\d+) entries", logtxt)
n_entries = int(m_[-1]) if m_ else 0
MODELS = str(cfg["debug"].get("lab_tour", "")).startswith("models")    # 2026-10-18: the Tutorial 2 models tour
T.check(f"lab has entries ({n_entries})", n_entries >= 1 if MODELS else n_entries > 5)
time.sleep(float(dc["lab_interval"]) * n_entries + 1.5)
created = [e for e in u.events if e[0] >= t1]
tut = __import__("icserver.tutorial1", fromlist=["x"])
wanted = set(tut.model_tour_list(cfg, cfg["debug"].get("lab_tour", "start"))) - set(tut.MODEL_TOUR_CRASHES_BARE)
seen = {ws for ws in wanted if any(e[2] == 4 and T.object_class(e[3]) & 0xFFFFFF == ws & 0xFFFFFF for e in created)}
T.check(f"every lab model shown ({len(seen & wanted)}/{len(wanted)})", wanted <= seen)
runs = [e for e in u.events if e[0] >= t1 and e[2] == 0x8D]
if MODELS:
    T.check("models tour: bare models, named in the log", not runs and "[pod]" in logtxt)
else:
    T.check(f"scriptlets run ({len(runs)})", len(runs) >= 1)
T.check("objective updates", len([e for e in u.events if e[0] >= t1 and e[2] == 0x2009]) >= min(n_entries, len(runs)))   # fase3-hy: models that closed the game are skipped
print(f"{sum(ok for _, ok in T.CHECKS)}/{len(T.CHECKS)} checks passed")
os._exit(0 if all(ok for _, ok in T.CHECKS) else 1)
