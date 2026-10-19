"""After a match the Champions / Amplifiers tabs ask with 0x21A4 / 0x2116 (fase3-in):
python tests/test_collections.py <config.toml>. The server answers with the login's champion data
(0x20ED), character list (0x209D) and item statuses (0x20B8). fase3-jg: the Amplifiers tab also needs the
amplifier sets (0x2090) and the store's amplifier data (0x2107), at login and on 0x2116."""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import test_e2e as T
from icserver import config as config_mod, log
from icserver.server import Server
cfg = config_mod.load(sys.argv[1]); log.setup(cfg.log_dir, False)
server = Server(cfg); server.start()
u = T.login_and_menu(cfg, server)
order = [e[2] for e in u.events]
b24 = [e[3] for e in u.events if e[2] == 0x2024]
T.check("0x2024 leaves out the maps not in the install (Metropolis Skyway 0x40000C28)",
        b24 and struct.pack("<I", 0x40000C28) not in b24[0] and struct.pack("<I", 0x40000B6A) in b24[0])
T.check("login sends 0x2090 and 0x2107 before 0x2080",
        0x2090 in order and 0x2107 in order and 0x2080 in order
        and order.index(0x2090) < order.index(0x2080) and order.index(0x2107) < order.index(0x2080))
b07 = [e[3] for e in u.events if e[2] == 0x2107]
T.check("0x2107 = u8 0 | u32 0 (no store entries)", b07 and b07[0][-5:] == b"\x00" + struct.pack("<I", 0))
b90 = [e[3] for e in u.events if e[2] == 0x2090]
T.check("0x2090 = 0 sets of 6", b90 and b90[0][-13:] == b"\x00" + struct.pack("<III", 0, 6, 0))
for ev, body in ((0x21A4, struct.pack("<I", 0)), (0x2116, b"")):
    t0 = time.monotonic()
    u.send_event(T.SVC, ev, body)
    got = {e[2] for e in u.wait_for(lambda e: e[0] >= t0 and e[2] in (0x20ED, 0x209D, 0x20B8), 3)}
    time.sleep(2.2)
    got |= {e[2] for e in u.events if e[0] >= t0 and e[2] in (0x20ED, 0x209D, 0x20B8)}
    want = {0x20ED, 0x209D, 0x20B8} if ev == 0x21A4 else {0x20B8}
    T.check(f"{ev:#x} -> {sorted(hex(w) for w in want)} ({sorted(hex(g) for g in got)})", got == want)
    if ev == 0x2116:
        T.check("0x2116 -> 0x2090 + 0x2107", {0x2090, 0x2107} <= {e[2] for e in u.events if e[0] >= t0})
# 10:23 (tester's logs): 0x2116 right after 0x21A4 got no answer (the 2 s limit)
t1 = time.monotonic()
u.send_event(T.SVC, 0x21A4, struct.pack("<I", 0)); time.sleep(0.3)
u.send_event(T.SVC, 0x2116, b"")
got = {e[2] for e in u.wait_for(lambda e: e[0] >= t1 and e[2] == 0x2107, 2) or []}
time.sleep(0.5)
got = {e[2] for e in u.events if e[0] >= t1 + 0.25}
T.check("0x2116 just after 0x21A4 is still answered (0x2115, 0x2090, 0x2107, 0x20B8)",
        {0x2115, 0x2090, 0x2107, 0x20B8} <= got)
b15 = [e[3] for e in u.events if e[2] == 0x2115]
from icserver import scorecard as SC, messages as MM
n_enc = 1 + len(MM.ENCOUNTERS)
entry_len = len(SC.encounter_stats_entry(0, SC.sample_stat_values(0)))
T.check(f"0x2115 = account encounter stats for {n_enc} encounters, totals 0x4000094C first",
        b15 and struct.pack("<I", n_enc) in b15[0] and len(b15[0]) >= n_enc * entry_len
        and struct.pack("<QBI", 0, 0, 0x4000094C) in b15[0])
print(f"{sum(ok for _, ok in T.CHECKS)}/{len(T.CHECKS)} checks passed")
os._exit(0 if all(ok for _, ok in T.CHECKS) else 1)
