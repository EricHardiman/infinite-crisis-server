"""End-to-end run with a simulated client (no game needed).

  python tests/test_e2e.py <config.toml>

Plays the whole flow the real client goes through -- SOAP login, login
handshake, queue, referral, game connection, lobby, loading, cinematic,
tutorial walk, ping -- and then the failure cases that used to break the old
server: a double Launch click, leaving the match and queueing again, and a
second login without restarting the server.
"""
import os
import socket
import struct
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from icserver import config as config_mod, log                # noqa: E402
from icserver.server import Server                             # noqa: E402
from icserver.wire import build_message, build_position, pack_compact, read_compact  # noqa: E402

SVC = 0x0600000000000403
SVC_INPUT = 0x0600000000000008
PLAYER = 0x0200000000000001
CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail and not cond else ""))


class Client:
    """Reads server frames on a socket in a thread and records them."""

    def __init__(self, port, name):
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.name = name
        self.events = []        # (time, dest, event id, body)
        self.packets = []       # (time, mask, payload)
        self.buf = b""
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                d = self.sock.recv(65536)
                if not d:
                    break
                self.buf += d
                while len(self.buf) >= 4:
                    n = struct.unpack_from("<I", self.buf)[0]
                    if len(self.buf) < 4 + n:
                        break
                    fr, self.buf = self.buf[4:4 + n], self.buf[4 + n:]
                    with self.lock:
                        if fr[0] == 0x02:
                            dest = struct.unpack_from("<Q", fr, 1)[0]
                            ev, pos = read_compact(fr, 10)
                            self.events.append((time.monotonic(), dest, ev, fr[pos:]))
                        else:
                            self.packets.append((time.monotonic(), struct.unpack_from("<I", fr, 1)[0], fr[5:]))
        except OSError:
            pass

    def send_event(self, dest, ev, body):
        self.sock.sendall(build_message(dest, ev, body))

    def ids(self, since=0.0):
        with self.lock:
            return [e[2] for e in self.events if e[0] >= since]

    def wait_for(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                hit = [e for e in self.events if pred(e)]
            if hit:
                return hit
            time.sleep(0.02)
        return []

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)   # wakes our reader thread so the FIN really goes out
        except OSError:
            pass
        self.sock.close()


def hello_blob(key_n):
    """A hello carrying an RSA blob encrypted to the server key (OAEP-SHA1)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    pub = rsa.RSAPublicNumbers(65537, key_n).public_key()
    blob = pub.encrypt(os.urandom(24), padding.OAEP(mgf=padding.MGF1(hashes.SHA1()),
                                                    algorithm=hashes.SHA1(), label=None))
    return b"\x00" * 12 + b"\x043des" + struct.pack("<I", len(blob)) + blob


def vit_cur(body):
    """Current value of a one-pair 0x42 vitals (in either of its two lists)."""
    return max(struct.unpack_from("<H", body, 2)[0], struct.unpack_from("<H", body, 7)[0])


def object_class(body):
    """Class DID from an object bundle (batch 0x4: base | count | compact 0xF2 (2 bytes) | u32 len | u32 class ...)."""
    return struct.unpack_from("<I", body, 1 + 1 + 2 + 4)[0]   # 0xF2 packs to 2 bytes


def attack_until_dead(g, u, eid, label):
    t = time.monotonic()
    g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, 0, eid) + b"\x00\x00")
    dead = u.wait_for(lambda e: e[0] >= t and e[2] == 0x42 and e[1] == eid
                      and struct.unpack_from("<H", e[3], 2 + 4 + 1)[0] == 0, 6)   # base, n, zeros, n, (cur, max)
    return bool(dead)


def login_and_menu(cfg, server):
    s = cfg["server"]
    req = urllib.request.Request(
        f"http://127.0.0.1:{s['soap_port']}/WebLoginApp-1.3/AuthenticateWS",
        data=b'<?xml version="1.0"?><SOAP-ENV:Envelope><SOAP-ENV:Body><SOAP1:AuthSelect>'
             b'<userName>tester</userName><password>x</password></SOAP1:AuthSelect></SOAP-ENV:Body></SOAP-ENV:Envelope>',
        method="POST")
    resp = urllib.request.urlopen(req, timeout=5).read().decode()
    check("SOAP login answers with the user server port", f"<userServerPort>{s['user_port']}<" in resp)
    check("SOAP login has no errorString", "errorString" not in resp)
    u = Client(s["user_port"], "user")
    u.sock.sendall(hello_blob(server.key.n))
    got = u.wait_for(lambda e: e[2] == 0x2080)
    check("account data delivered (11 messages + completed list + profile header + amplifier data, 0x2080 last)",
          got and u.ids()[-1] == 0x2080
          and len([i for i in u.ids() if i not in (0x214B, 0x2190, 0x2090, 0x2107)]) == 11,
          str([hex(i) for i in u.ids()]))
    return u


def conv_key(e):
    return struct.unpack_from("<I", e[3], 13)[0] if e[2] == 0x2001 else None


def rank(slot):
    """The patched client's RankSkill ping (type "KNAR", target = the slot)."""
    return struct.pack("<ffQI", 0.0, 0.0, slot, 0x52414E4B)


def new_objects(u, since, classes):
    """Objects of these classes first created at or after `since` (later bundles
    of an object, such as a drone's death, are not new objects)."""
    first = {}
    with u.lock:
        for e in u.events:
            if e[2] == 0x4 and e[1] not in first:
                first[e[1]] = (e[0], object_class(e[3]))
    return sorted(eid for eid, (t, cls) in first.items() if t >= since and cls in classes)


def play_bridge(cfg, g, u, label):
    """Part 2 of the tutorial: from the end of the Catwoman cinematic to the
    Bat Scream unlock (pacing 0: every line at once)."""
    melee, ranged, target_cls, gate_cls = 0x40000A5C, 0x40000A5D, 0x40000BA9, 0x40000B0F
    said = lambda key, t0, timeout=5: u.wait_for(lambda e: e[0] >= t0 and conv_key(e) == key, timeout)
    lit = lambda element, t0, timeout=5: u.wait_for(
        lambda e: e[0] >= t0 and e[2] == 0x213D and struct.unpack_from("<II", e[3], 1) == (element, 7), timeout)
    gates = new_objects(u, 0.0, {gate_cls})

    def kill_all(eids, what):
        ok = all(attack_until_dead(g, u, eid, label) or attack_until_dead(g, u, eid, label) for eid in eids)
        check(f"[{label}] {what} defeated", ok)
        return ok

    def walk(xyz):
        g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IQI", 4, 0, 0) + build_position(1, 0x13, 0xCB, 0, *xyz) + b"\x00")

    def cast(slot, target, xyz):
        g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, slot, target) + build_position(1, 0x13, 0xCB, 0, *xyz) + b"\x00")

    t0 = time.monotonic()
    g.send_event(PLAYER, 0x2, bytes.fromhex("17010010") + struct.pack("<II", 4, 0x35000034))
    check(f"[{label}] after Catwoman: 'Selina has left it to us...' (0x1c9)", said(0x1C9, t0))
    time.sleep(0.5)
    pursuers = new_objects(u, t0, {melee})
    check(f"[{label}] two pursuer drones come", len(pursuers) == 2, str(pursuers))
    kill_all(pursuers, "the pursuers")

    t1 = time.monotonic() - 1.0
    check(f"[{label}] level 3: 'Use your new skill point...' (0x1c2) + W's '+' highlighted (element 4)",
          said(0x1C2, t1, 8) and lit(4, t1))
    t2 = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, rank(1))          # not the slot it waits for
    time.sleep(0.3)
    check(f"[{label}] Q's '+' is ignored while W is the one to unlock", not new_objects(u, t2, {target_cls}))
    g.send_event(SVC_INPUT, 0x2136, rank(2))
    time.sleep(0.6)
    tw = new_objects(u, t2, {target_cls})
    check(f"[{label}] W unlocked -> the yellow target drone (0x40000ba9)", len(tw) == 1, str(tw))
    if tw:
        pos = (49.6, 48.2, 200.0)
        g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, 0, tw[0]) + build_position(1, 0x13, 0xCB, 0, *pos) + b"\x00")
        check(f"[{label}] basic attacks do not hurt it: Superman says so (0x1cd)", said(0x1CD, t2, 6))
        g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 6, 0, 0) + build_position(1, 0x13, 0xCB, 0, 0, 0, 0) + b"\x00")
        t3 = time.monotonic()
        cast(2, tw[0], pos)
        check(f"[{label}] W (Sonic Shell) destroys it",
              u.wait_for(lambda e: e[0] >= t3 and e[2] == 0x42 and e[1] == tw[0] and vit_cur(e[3]) == 0, 4))
        check(f"[{label}] ...and W goes on cooldown (0x20f8 slot 2)",
              u.wait_for(lambda e: e[0] >= t3 and e[2] == 0x20F8 and struct.unpack_from("<I", e[3], 9)[0] == 2, 2))
    t4 = time.monotonic() - 1.0
    check(f"[{label}] 'More enemies!' (0x191)", said(0x191, t4, 5))
    time.sleep(0.5)
    around = new_objects(u, t4, {melee})
    check(f"[{label}] three drones around Batman", len(around) == 3, str(around))
    kill_all(around, "the three drones")
    t5 = time.monotonic() - 1.0
    check(f"[{label}] level 4: 'upgrade one of the skills' (0x1d3) + Q's AND W's '+' highlighted",
          said(0x1D3, t5, 8) and lit(30, t5) and lit(4, t5))
    t6 = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, rank(2))          # W this time (Q or W may be upgraded)
    check(f"[{label}] W upgraded -> the first gate of the bridge opens (0x3) + 'We need to keep moving.'",
          said(0x38D, t6, 3) and u.wait_for(lambda e: e[0] >= t6 and e[2] == 0x3 and e[1] in gates, 2))

    from icserver.bridge import along
    t7 = time.monotonic()
    walk(along(12.0, 0.8))
    check(f"[{label}] at the marker: 'Clear out those drones!' (0x1cc)", said(0x1CC, t7, 20))
    time.sleep(0.5)
    ambush = new_objects(u, t7, {melee, ranged})
    check(f"[{label}] ...2 melee + 1 ranged drone", len(ambush) == 3 and len(new_objects(u, t7, {ranged})) == 1,
          str(ambush))
    check(f"[{label}] ...and the gate behind closes again", new_objects(u, t7, {gate_cls}))
    kill_all(ambush, "the ambush")

    t8 = time.monotonic() - 1.0
    check(f"[{label}] Stolen Power: the D button (HUD element 22) + 'Place a camera here.' (0x196)",
          said(0x196, t8, 15) and u.wait_for(lambda e: e[0] >= t8 and e[2] == 0x213D
                                             and struct.unpack_from("<I", e[3], 1)[0] == 22, 2))
    check(f"[{label}] ...without the slot-7 skill property (it broke the champion's updates on the client)",
          not any(e[0] >= t8 and e[2] == 0x4 and struct.pack("<I", 0x48000808) in e[3] for e in list(u.events)))
    t9 = time.monotonic()
    cast(7, 0, along(12.5, 0.6))
    check(f"[{label}] D on the marked spot places the surveillance camera (0x40000265)",
          u.wait_for(lambda e: e[0] >= t9 and e[2] == 0x4 and object_class(e[3]) == 0x40000265, 2))
    check(f"[{label}] 'Keep fighting your way to the base.' (0x1d2): the middle gate opens",
          said(0x1D2, t9, 10) and u.wait_for(lambda e: e[0] >= t9 and e[2] == 0x3 and e[1] in gates, 2))
    time.sleep(0.5)
    at_gate = new_objects(u, t9, {melee, ranged})
    check(f"[{label}] four drones hit the last gate", len(at_gate) == 4, str(at_gate))
    check(f"[{label}] ...with a guide marker near them",
          u.wait_for(lambda e: e[0] >= t9 and e[2] == 0x4 and object_class(e[3]) == 0x40000A9C, 2))
    t10 = time.monotonic()
    walk(along(30.0, 0.8))
    check(f"[{label}] half way there the gate behind closes",
          u.wait_for(lambda e: e[0] >= t10 and e[2] == 0x4 and object_class(e[3]) == gate_cls, 12))
    kill_all(at_gate, "the gate drones")

    t11 = time.monotonic() - 1.0
    check(f"[{label}] level 5: 'Unlock your next skill.' (0x1d1) + E's '+' highlighted (element 28)",
          said(0x1D1, t11, 8) and lit(28, t11))
    t12 = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, rank(3))
    time.sleep(0.6)
    te = new_objects(u, t12, {target_cls})
    check(f"[{label}] E unlocked -> target drone", len(te) == 1, str(te))
    if te:
        t12b = time.monotonic()
        cast(2, te[0], along(35.5, 0.0))                  # W: it must survive
        time.sleep(1.5)
        check(f"[{label}] the E target drone is immune to W",
              not any(e[0] >= t12b and e[2] == 0x42 and e[1] == te[0] and vit_cur(e[3]) == 0 for e in list(u.events)))
        t13 = time.monotonic()
        cast(3, te[0], along(35.5, 0.0))
        check(f"[{label}] E (Bat Flight) lands on it and destroys it",
              u.wait_for(lambda e: e[0] >= t13 and e[2] == 0x42 and e[1] == te[0] and vit_cur(e[3]) == 0, 4))
    t14 = time.monotonic() - 1.0
    check(f"[{label}] 'Our enemy is sending more drones!' (0x1ae)", said(0x1AE, t14, 6))
    time.sleep(0.5)
    more = new_objects(u, t14, {melee, ranged})
    check(f"[{label}] ...four of them", len(more) == 4, str(more))
    kill_all(more, "the four drones")
    t15 = time.monotonic() - 1.0
    check(f"[{label}] skill point for the passive (0x1a1, element 19)", said(0x1A1, t15, 8) and lit(19, t15))
    t16 = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, rank(5))
    check(f"[{label}] 'Let's go!' (0x1e2): the last gate opens",
          said(0x1E2, t16, 10) and u.wait_for(lambda e: e[0] >= t16 and e[2] == 0x3 and e[1] in gates, 3))
    time.sleep(0.5)
    at_vehicle = new_objects(u, t16, {melee, ranged})
    check(f"[{label}] four drones hit a vehicle at the end of the bridge", len(at_vehicle) == 4, str(at_vehicle))
    kill_all(at_vehicle, "the vehicle drones")
    t17 = time.monotonic() - 1.0
    check(f"[{label}] level 6: 'unlock the Bat Scream' (0x1dc) + R's '+' highlighted (element 5)",
          said(0x1DC, t17, 8) and lit(5, t17))
    t18 = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, rank(4))
    check(f"[{label}] R unlocked: the camera spots drones (0x1a0)", said(0x1A0, t18, 4))
    time.sleep(0.6)
    far = new_objects(u, t18, {melee})
    check(f"[{label}] ...three drones two sections back", len(far) == 3, str(far))
    check(f"[{label}] ...with a red alert marker (0x4000025b)",
          u.wait_for(lambda e: e[0] >= t18 and e[2] == 0x4 and object_class(e[3]) == 0x4000025B, 2))
    check(f"[{label}] 'To view other areas, unlock your camera.' (0x1b0)", said(0x1B0, t18, 4))
    t19 = time.monotonic()
    name, value = b"User.CameraLocked", "False".encode("utf-16le")
    g.send_event(SVC_INPUT, 0x216E, bytes([len(name)]) + name + bytes([5]) + value + bytes.fromhex("330c0010"))
    check(f"[{label}] camera unlocked (preference 0x216e) -> 'Use the Bat Scream...' (0x1d0)",
          said(0x1CA, t19, 3) and said(0x1D0, t19, 4))
    t20 = time.monotonic()
    cast(4, 0, along(56.0, 30.0))                     # off to the side: a miss
    check(f"[{label}] a Bat Scream that misses: 'Take a moment, aim...' (0x3ac)", said(0x3AC, t20, 5))
    check(f"[{label}] ...R goes on a 10 s cooldown (0x20f8 slot 4)",
          u.wait_for(lambda e: e[0] >= t20 and e[2] == 0x20F8 and struct.unpack_from("<I", e[3], 9)[0] == 4, 2))
    time.sleep(10.2)
    t21 = time.monotonic()
    cast(4, 0, along(15.5, 0.0))
    check(f"[{label}] the Bat Scream along the bridge destroys all three",
          all(u.wait_for(lambda e, d=d: e[0] >= t21 and e[2] == 0x42 and e[1] == d and vit_cur(e[3]) == 0, 4)
              for d in far))
    check(f"[{label}] 'Good shot!' (0x1a5) ... 'Lock the camera back on Batman.' (0x19f)",
          said(0x1A5, t21, 5) and said(0x19F, t21, 5))
    t22 = time.monotonic()
    name, value = b"User.CameraLocked", "True".encode("utf-16le")
    g.send_event(SVC_INPUT, 0x216E, bytes([len(name)]) + name + bytes([4]) + value + bytes.fromhex("330c0010"))
    check(f"[{label}] camera locked again: 'We've got another car in our way.' (0x1c5)", said(0x1C5, t22, 4))
    check(f"[{label}] 'Protector, use Super Strength' (0x1c1) + the F button (HUD element 23)",
          said(0x1C1, t22, 25) and lit(23, t22, 25))
    play_finale(cfg, g, u, label, said, walk, cast)


def play_finale(cfg, g, u, label, said, walk, cast):
    """Part 3: Super Strength, the Destroyer, the victory."""
    from icserver.bridge import along
    melee, ranged = 0x40000A5C, 0x40000A5D
    t0 = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, struct.pack("<ffQI", *along(60.0, 0.0)[:2], 0, 1))   # Alt+click on the car
    check(f"[{label}] Alt+click on the car: Batman lifts it, 'Look out, more drones!' (0x1c0)", said(0x1C0, t0, 15))
    time.sleep(0.6)
    three = new_objects(u, t0, {melee, ranged})
    check(f"[{label}] ...three drones further on", len(three) == 3, str(three))
    t1 = time.monotonic()
    # a right-click on one of them throws the car at it
    g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, 0, three[0] if three else 0) + b"\x00\x00")
    time.sleep(1.5)
    check(f"[{label}] the thrown car destroys them",
          all(u.wait_for(lambda e, d=d: e[0] >= t1 and e[2] == 0x42 and e[1] == d and vit_cur(e[3]) == 0, 4)
              for d in three))
    check(f"[{label}] ...and the Destroyer's cinematic (0x35000028) plays",
          u.wait_for(lambda e: e[0] >= t1 and e[2] == 0x20F5 and struct.pack("<I", 0x35000028) in e[3], 5))
    t2 = time.monotonic()
    g.send_event(PLAYER, 0x2, bytes.fromhex("17010010") + struct.pack("<II", 4, 0x35000028))
    check(f"[{label}] after it: 'You know what to do.' (0x1d7)", said(0x1D7, t2, 4))
    time.sleep(0.6)
    boss = new_objects(u, t1, {0x40000EB2})       # spawned before its cinematic (fase3-em)
    small = new_objects(u, t2, {melee, ranged})
    seen = sorted({hex(object_class(e[3])) for e in list(u.events) if e[0] >= t2 and e[2] == 0x4})
    check(f"[{label}] ...the Destroyer and four drones", len(boss) == 1 and len(small) == 4, f"{boss} {small} {seen}")
    if len(small) == 4:
        at_car, ahead = small[:2], small[2:]
        ok = all(attack_until_dead(g, u, d, label) or attack_until_dead(g, u, d, label) for d in at_car)
        check(f"[{label}] the two drones at the second car defeated", ok)
        t3 = time.monotonic() - 1.0
        check(f"[{label}] ...level 7 and a skill point: 'Use your skill point.' (0x195)", said(0x195, t3, 5))
        g.send_event(SVC_INPUT, 0x2136, struct.pack("<ffQI", 133.5, 13.35, 0, 1))   # lift the second car
        time.sleep(1.0)
        t4 = time.monotonic()
        g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, 0, ahead[0]) + b"\x00\x00")
        check(f"[{label}] the second car thrown at the two drones ahead destroys them",
              all(u.wait_for(lambda e, d=d: e[0] >= t4 and e[2] == 0x42 and e[1] == d and vit_cur(e[3]) == 0, 5)
                  for d in ahead))
        t5 = time.monotonic() - 1.0
        check(f"[{label}] 'We will not allow this machine to stand in our way!' (0x1c7)", said(0x1C7, t5, 5))
    if boss:
        t6 = time.monotonic()
        ok = any(attack_until_dead(g, u, boss[0], label) for _ in range(8))
        check(f"[{label}] the Destroyer defeated (it does not fight back)", ok)
        check(f"[{label}] ...the ending cinematic (0x35000025)",
              u.wait_for(lambda e: e[0] >= t6 and e[2] == 0x20F5 and struct.pack("<I", 0x35000025) in e[3], 6))
        t7 = time.monotonic()
        g.send_event(PLAYER, 0x2, bytes.fromhex("17010010") + struct.pack("<II", 4, 0x35000025))
        check(f"[{label}] ...VICTORY in the world first (announcement 0x100002eb)",
              u.wait_for(lambda e: e[0] >= t7 and e[2] == 0x2 and struct.pack("<I", 0x100002EB) in e[3][:8], 3))
        check(f"[{label}] ...then the match end: movie preference reset 0x216a, notice 0x1000000e, "
              "completed list 0x214b, stats 0x2045",
              u.wait_for(lambda e: e[0] >= t7 and e[2] == 0x216A and b"HasSeenPostEncounterVideo" in e[3], 10)
              and u.wait_for(lambda e: e[0] >= t7 and e[2] == 0x2 and struct.pack("<I", 0x1000000E) in e[3], 3)
              and u.wait_for(lambda e: e[0] >= t7 and e[2] == 0x214B, 3)
              and u.wait_for(lambda e: e[0] >= t7 and e[2] == 0x2045, 3))


def play_match(cfg, server, u, label, bridge=False, before_connect=None):
    s = cfg["server"]
    t0 = time.monotonic()
    u.send_event(SVC, 0x20EB, struct.pack("<II", 0x40000991, 0) + b"\x00" + struct.pack("<i", -1))
    check(f"[{label}] queue joined + match found", u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20FA))
    u.send_event(SVC, 0x20CA, b"")
    time.sleep(0.3)
    referral = [p for p in u.packets if p[1] == 0x800 and p[0] >= t0]
    check(f"[{label}] referral to the game port", referral and
          struct.unpack_from("<H", referral[-1][2], 12)[0] == s["game_port"])
    # double Launch click: must be ignored, no second referral
    n_ref = len(referral)
    u.send_event(SVC, 0x20EB, struct.pack("<II", 0x40000991, 0) + b"\x00" + struct.pack("<i", -1))
    time.sleep(0.3)
    check(f"[{label}] second Launch click ignored (no new referral)",
          len([p for p in u.packets if p[1] == 0x800 and p[0] >= t0]) == n_ref)

    if before_connect:
        before_connect()
    g = Client(s["game_port"], "game")
    g.sock.sendall(b"\x00" * 40)       # game hello
    check(f"[{label}] enter match 0x20af on the login link", u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x20AF))
    time.sleep(0.2)
    check(f"[{label}] welcome + ServerSwitch on the game link", {0x40000, 0x100} <= {p[1] for p in g.packets})

    t_lobby = time.monotonic()
    g.send_event(SVC, 0x20F2, b"")
    check(f"[{label}] lobby data (0x2029 ... 0x206d)", u.wait_for(lambda e: e[0] >= t_lobby and e[2] == 0x206D))
    g.send_event(SVC, 0x20D5, struct.pack("<I", 10))
    time.sleep(cfg["timing"]["objects_min_delay"] + 0.3)
    early = [e for e in u.events if e[0] >= t_lobby and e[2] == 0x4]
    check(f"[{label}] objects NOT created before the client reports {cfg['timing']['objects_min_percent']}%",
          not early)
    g.send_event(SVC, 0x20D5, struct.pack("<I", 25))
    objs = u.wait_for(lambda e: e[0] >= t_lobby and e[2] == 0x4, 2)
    check(f"[{label}] objects created right after 25%", objs and objs[0][1] == 0x0200000000000002)
    if objs:
        player = [e for e in u.events if e[0] >= t_lobby and e[2] == 0x4 and e[1] == PLAYER]
        check(f"[{label}] player object uses player_class",
              player and object_class(player[0][3]) == cfg["match"]["player_class"])
    time.sleep(cfg["timing"]["link_delay"] + 0.2)

    t_load = time.monotonic()
    g.send_event(PLAYER, 0x2, bytes.fromhex("5e010010") + bytes(8))
    cin = u.wait_for(lambda e: e[0] >= t_load and e[2] == 0x20F5, cfg["timing"]["cinematic_delay"] + 2)
    check(f"[{label}] intro cinematic after load complete", cin)
    for pre in cfg["match"].get("pre_cinematics") or []:
        t_pre = time.monotonic()
        g.send_event(PLAYER, 0x2, bytes.fromhex("17010010") + struct.pack("<II", 4, pre))
        check(f"[{label}] next intro cinematic after {pre:#x}",
              u.wait_for(lambda e: e[0] >= t_pre and e[2] == 0x20F5, 2))
    t_cin = time.monotonic()
    g.send_event(PLAYER, 0x2, bytes.fromhex("17010010") + struct.pack("<II", 4, cfg["match"]["cinematic"]))
    check(f"[{label}] tutorial starts (objective list 0x2034)",
          u.wait_for(lambda e: e[0] >= t_cin and e[2] == 0x2034, 3))
    check(f"[{label}] HUD + vitals + conversation 0x1ba",
          {0x213D, 0x42, 0x2001} <= set(u.ids(t_cin)))

    # walk to the first guide ping in landblock 13cb
    t1 = cfg["tutorial"]["walk_targets"][0]
    t2 = (36.9, 57.6, 200.0)          # the second marker (next to the drone and the human)
    t_walk = time.monotonic()
    pos = build_position(1, 0x13, 0xCB, 0, *t1)
    g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IQI", 4, 0, 0) + pos + b"\x00")
    arrived = u.wait_for(lambda e: e[0] >= t_walk and e[2] == 0x2009, 8)
    moves = [e for e in u.events if e[0] >= t_walk and e[2] == 0x4 and e[1] == 0x0200000000000002]
    check(f"[{label}] walking updates streamed", len(moves) > 20, f"{len(moves)} updates")
    check(f"[{label}] arrival completes step 1 (objective update 0x2009)", arrived)

    # Phase 2: scenery at tutorial start, the first drone after target 2, combat
    props = {0x2E000AAB, 0x2E0010F3, 0x40000B0F} | {(p << 24) | 0x000AAB for p in range(0x4A, 0x50)}
    meteor_ws = int(cfg["tutorial"].get("meteor_wstate", 0x2E000BB3))
    meteor_did = struct.pack("<I", meteor_ws)
    scenery = [e for e in u.events if e[0] >= t_cin and e[2] == 0x4 and e[1] >= 0x0200000000000100
               and object_class(e[3]) in props and meteor_did not in e[3]]
    n_expected = 9 if cfg["combat"].get("prop_try_all_carriers", True) else 4    # 3 gates
    check(f"[{label}] scenery spawned at tutorial start (vehicle, gates)", len(scenery) == n_expected, str(len(scenery)))
    if cfg["tutorial"].get("meteors", True) and cfg["tutorial"].get("meteor_objects", False):
        check(f"[{label}] meteors (meteor {meteor_ws:#x}) fall",
              # fase3-hx: the small meteors come 2.4-2.9 s after the start: wait for them
              u.wait_for(lambda e: e[0] >= t_cin and e[2] == 0x4 and (
                  object_class(e[3]) & 0xFFFFFF in (meteor_ws & 0xFFFFFF, 0x0002EC, 0x00131C, 0x000013, 0x0004E5, 0x000928)
                  or meteor_did in e[3]), 6) != [])
    t_walk2 = t_walk
    # the drone and the human appear (fighting) after the knockdown at the first marker,
    # with the second guide ping at them
    drone = u.wait_for(lambda e: e[0] >= t_walk and e[2] == 0x4 and e[1] >= 0x0200000000000100
                       and object_class(e[3]) == 0x40000A5C, 8)
    check(f"[{label}] first drone (Soldier Drone 0x40000a5c) appears after the first marker", drone)
    check(f"[{label}] ...with a second guide ping at it",
          u.wait_for(lambda e: e[0] >= t_walk and e[2] == 0x4 and e[1] == 0x0200000000000032, 3))
    pos = build_position(1, 0x13, 0xCB, 0, *t2)
    t_arr2 = time.monotonic()
    g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IQI", 4, 0, 0) + pos + b"\x00")
    check(f"[{label}] walking up to it: 'A corrupted drone' (0x1b8)",
          u.wait_for(lambda e: e[0] >= t_arr2 and e[2] == 0x2001 and struct.unpack_from("<I", e[3], 13)[0] == 0x1B8, 8))
    if drone:
        # right-click on the GROUND next to the drone (the real client cannot target it)
        t_click = time.monotonic()
        x, y, z = (35.3, 56.3, 200.0)
        g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IQI", 4, 0, 0) + build_position(1, 0x13, 0xCB, 0, x + 1.0, y, z) + b"\x00")
        eid = drone[0][1]
        killed = u.wait_for(lambda e: e[0] >= t_click and e[2] == 0x42 and e[1] == eid
                            and vit_cur(e[3]) == 0, 8)
        check(f"[{label}] click on the ground next to the drone attacks it until defeated", killed)
        keys = cfg["scripts"].get("basic_attack_keys") or []
        first = keys[0] if keys else 0
        did = int(first[0] if isinstance(first, list) else first)
        if did:
            want = bytes([did >> 24]) + pack_compact(did & 0xFFFFFF)
            # (the knockdown / get-up scripts may run on the champion in between)
            runs = u.wait_for(lambda e: e[0] >= t_click and e[2] == 0x8D and e[1] == 0x0200000000000002
                              and e[3][2:5] == want, 1)
            body = runs[0][3] if runs else b"\xff" * 5
            check(f"[{label}] each hit orders the champion to run the basic-attack scriptlet (0x8d)",
                  body[0] == 0 and body[1] == (len(first) if isinstance(first, list) else 1) and body[2:5] == bytes([did >> 24]) + pack_compact(did & 0xFFFFFF))
        u.wait_for(lambda e: e[0] >= t_walk2 and e[2] == 0x4 and e[1] > drone[0][1], 3)
        time.sleep(0.3)
        with u.lock:
            ids = sorted({e[1] for e in u.events if e[0] >= t_walk2 and e[2] == 0x4 and e[1] > drone[0][1]
                          and object_class(e[3]) >> 24 == 0x40 and object_class(e[3]) not in (0x40000C71, 0x40000B0F, 0x400004FD)})
        check(f"[{label}] wave of 2 drones after the first one", len(ids) == 2, str(len(ids)))
        check(f"[{label}] the human fighting the drone (thug 0x40000c71) appears and leaves",
              any(e[2] == 0x4 and object_class(e[3]) == 0x40000C71 for e in list(u.events))
              and u.wait_for(lambda e: e[0] >= t_click and e[2] == 0x3 and e[1] == drone[0][1] + 1, 8))   # it runs around the wagon first
        for eid in ids:
            attack_until_dead(g, u, eid, label)
        lv = u.wait_for(lambda e: e[0] >= t_walk2 and e[2] == 0x2001 and struct.unpack_from("<I", e[3], 13)[0] == 0x1DF, 5)
        check(f"[{label}] wave cleared -> 'Good job!' (0x1df) + level up", lv)
        check(f"[{label}] level up reveals the Q upgrade button (HUD element 30) highlighted",
              u.wait_for(lambda e: e[0] >= t_walk2 and e[2] == 0x213D and struct.unpack_from("<II", e[3], 1) == (30, 7), 2))
        check(f"[{label}] level up reveals the skill bar (HUD element 14)",
              u.wait_for(lambda e: e[0] >= t_walk2 and e[2] == 0x213D and struct.unpack_from("<I", e[3], 1)[0] == 14, 2))
        # The patched client sends its skill-rank queries as pings (type "KNAR"):
        # a HUD refresh asks for slots 0-5 at once (must be ignored), a click on
        # the Q "+" asks for slot 1 alone (unlocks the skill).
        rank = lambda slot: struct.pack("<ffQI", 0.0, 0.0, slot, 0x52414E4B)
        t_rank = time.monotonic()
        for slot in range(6):
            g.send_event(SVC_INPUT, 0x2136, rank(slot))
        is_practice = lambda e: e[0] >= t_rank and e[2] == 0x4 and object_class(e[3]) == 0x40000BA9
        check(f"[{label}] a HUD refresh (rank queries for slots 0-5) does not unlock the skill",
              not u.wait_for(is_practice, 1.0))
        t_click = time.monotonic()
        g.send_event(SVC_INPUT, 0x2136, rank(1))
        check(f"[{label}] a lone rank query for Q (the '+' click) brings the practice target drones (0x40000ba9)",
              u.wait_for(is_practice, 2))
        check(f"[{label}] ...and the champion carries the skill ranks (property 0x100006C1)",
              any(e[0] >= t_click and e[2] == 0x4 and struct.pack("<I", 0x100006C1) in e[3]
                  for e in list(u.events)))
        time.sleep(0.5)                       # both target drones (created together)
        targets = sorted({e[1] for e in list(u.events) if is_practice(e)})
        if len(targets) == 2:
            dead = lambda eid, t0: u.wait_for(lambda e: e[0] >= t0 and e[2] == 0x42 and e[1] == eid
                                              and vit_cur(e[3]) == 0, 1.5)
            # basic attack (command 2, ability 0) on a target drone: immune
            t_basic = time.monotonic()
            g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, 0, targets[0]) + build_position(1, 0x13, 0xCB, 0, 42.8, 59.6, 200.0) + b"\x00")
            check(f"[{label}] target drones are immune to basic attacks", not dead(targets[0], t_basic))
            g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 6, 0, 0) + build_position(1, 0x13, 0xCB, 0, 0, 0, 0) + b"\x00")
            # Q (command 2, ability 1) on one: the Batarang ricochets and destroys both
            t_q = time.monotonic()
            g.send_event(SVC_INPUT, 0x20EE, struct.pack("<IIQ", 2, 1, targets[0]) + build_position(1, 0x13, 0xCB, 0, 42.8, 59.6, 200.0) + b"\x00")
            check(f"[{label}] Q (Sonic Batarang) destroys the target drone and ricochets to the other",
                  u.wait_for(lambda e: e[0] >= t_q and e[2] == 0x42 and e[1] == targets[0]
                             and vit_cur(e[3]) == 0, 3)
                  and u.wait_for(lambda e: e[0] >= t_q and e[2] == 0x42 and e[1] == targets[1]
                                 and vit_cur(e[3]) == 0, 3))
        else:
            check(f"[{label}] two practice target drones", False, str(targets))
        if bridge:
            play_bridge(cfg, g, u, label)

    t_ping = time.monotonic()
    g.send_event(SVC_INPUT, 0x2136, struct.pack("<ffQI", 27.9, 64.4, 0, 1))
    check(f"[{label}] player ping created", u.wait_for(lambda e: e[0] >= t_ping and e[2] == 0x4
                                                       and e[1] == 0x0200000000000041, 2))
    check(f"[{label}] player ping removed later",
          u.wait_for(lambda e: e[0] >= t_ping and e[2] == 0x3, cfg["timing"]["ping_lifetime"] + 2))

    g.send_event(SVC_INPUT, 0x7777, b"\x01\x02\x03")      # unknown -> unhandled.log
    time.sleep(0.3)
    return g


def main(cfg_path):
    cfg = config_mod.load(cfg_path)
    cfg["tutorial"]["pacing"] = float(os.environ.get("IC_PACING", "0"))   # the logic, not the original's timing
    log.setup(cfg.log_dir, cfg["debug"]["hexdump"])
    server = Server(cfg)
    server.start()

    print("login + menus")
    u = login_and_menu(cfg, server)
    print("match 1")
    g = play_match(cfg, server, u, "match 1", bridge=True)
    with open(os.path.join(cfg.log_dir, "unhandled.log"), encoding="utf-8") as f:
        check("unknown client event written to unhandled.log", "event 0x7777" in f.read())

    print("the client leaves the finished match world (0x12D), keeps its game link, plays again")
    g.send_event(SVC, 0x12D, b"")
    time.sleep(0.5)
    sess = server.sessions[-1]
    check("session back in MENU after 0x12D (game link kept open)", sess.phase == "MENU", sess.phase)
    check("after 0x12D: no 0x3 removals (the client's teardown destroys its objects)",
          not u.wait_for(lambda e: e[2] == 0x3 and e[1] == 0x0200000000000002, 0.5))

    print("the end page asks for its banners and rewards (Champion Unlocked)")
    t_end = time.monotonic()
    check("no reward set (0x2125) sent in the world at match end",
          not u.wait_for(lambda e: e[2] == 0x2125 and e[0] < t_end, 0.1))
    u.send_event(SVC, 0x212E, b"\x00")
    check("0x212E answered with an empty 0x211F", u.wait_for(lambda e: e[0] >= t_end and e[2] == 0x211F
                                                              and e[3] == b"\x00\x00\x00"))
    t_ask = time.monotonic()
    u.send_event(SVC, 0x2124, b"\x00")
    hit = u.wait_for(lambda e: e[0] >= t_ask and e[2] == 0x2125)
    check("0x2124 answered with the pending reward 0x2125 (set 0x40000B07, Gaslight Batman)",
          hit and struct.unpack_from("<III", hit[-1][3], 5) == (0x40000B07, 0x40000B08, 0)
          and struct.unpack_from("<I", hit[-1][3], 17)[0] == 0x40000086)
    u.send_event(SVC, 0x2128, struct.pack("<III", 0x40000B07, 0, 0x40000B08) + b"\x00" * 20)
    time.sleep(0.3)
    t_ask = time.monotonic()
    u.send_event(SVC, 0x2124, b"\x00")
    check("after the claim (0x2128) no reward is pending",
          not u.wait_for(lambda e: e[0] >= t_ask and e[2] == 0x2125, 0.5))
    t_m2 = time.monotonic()

    def old_link_closes():
        # 20:17: the real client closes its old game link right after the new referral
        g.close()
        time.sleep(0.3)
    g2 = play_match(cfg, server, u, "match 2", before_connect=old_link_closes)
    check("[match 2] set local player (0xEB) sent again before the lobby data",
          u.wait_for(lambda e: e[0] >= t_m2 and e[2] == 0xEB and e[3][1:9] == struct.pack("<Q", 0x0200000000000001)))
    check("[match 2] the old link's close did not end the new match", sess.match is not None
          and getattr(sess.match, "seq_base", 0) > 0, f"match={sess.match}")
    g2.close()
    time.sleep(0.5)
    check("session back in MENU after the game link closed", sess.phase == "MENU", sess.phase)

    print("log out and log in again without restarting the server")
    u.close()
    time.sleep(0.5)
    u2 = login_and_menu(cfg, server)
    g3 = play_match(cfg, server, u2, "second login")
    g3.close()
    u2.close()
    time.sleep(0.3)

    bad = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    if bad:
        print("FAILED:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
