"""After a match the Champions / Amplifiers tabs ask with 0x21A4 / 0x2116 (fase3-in):
python tests/test_collections.py <config.toml>. The server answers with the login's champion data
(0x20ED), character list (0x209D) and item statuses (0x20B8)."""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import test_e2e as T
from icserver import config as config_mod, log
from icserver.server import Server
cfg = config_mod.load(sys.argv[1]); log.setup(cfg.log_dir, False)
server = Server(cfg); server.start()
u = T.login_and_menu(cfg, server)
for ev, body in ((0x21A4, struct.pack("<I", 0)), (0x2116, b"")):
    t0 = time.monotonic()
    u.send_event(T.SVC, ev, body)
    got = {e[2] for e in u.wait_for(lambda e: e[0] >= t0 and e[2] in (0x20ED, 0x209D, 0x20B8), 3)}
    time.sleep(2.2)
    got |= {e[2] for e in u.events if e[0] >= t0 and e[2] in (0x20ED, 0x209D, 0x20B8)}
    T.check(f"{ev:#x} -> champion data, character list, item statuses ({sorted(hex(g) for g in got)})",
            got == {0x20ED, 0x209D, 0x20B8})
print(f"{sum(ok for _, ok in T.CHECKS)}/{len(T.CHECKS)} checks passed")
os._exit(0 if all(ok for _, ok in T.CHECKS) else 1)
