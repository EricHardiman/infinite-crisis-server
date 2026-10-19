"""Byte-for-byte comparison with the original server's builders.

  python tests/test_compat.py <path to the old _server folder>

The old login_server.py is imported with a stubbed 'Crypto' package (its key
is never used here) and with its clocks frozen, then every message both
servers can build is compared.
"""
import os
import struct
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from icserver import messages as M          # noqa: E402
from icserver import tutorial1               # noqa: E402
from icserver.world import Mover             # noqa: E402

NOW = 1760000000.25


def load_old(old_dir):
    stub = types.ModuleType("Crypto")
    cipher = types.ModuleType("Crypto.Cipher")
    pub = types.ModuleType("Crypto.PublicKey")
    cipher.PKCS1_OAEP = cipher.PKCS1_v1_5 = None

    class _RSA:
        @staticmethod
        def import_key(data):
            return None
    pub.RSA = _RSA
    sys.modules.update({"Crypto": stub, "Crypto.Cipher": cipher, "Crypto.PublicKey": pub})
    keydir = os.path.join(old_dir, "keys")
    os.makedirs(keydir, exist_ok=True)
    if not os.path.exists(os.path.join(keydir, "server_private.pem")):
        open(os.path.join(keydir, "server_private.pem"), "wb").write(b"stub")
    sys.path.insert(0, old_dir)
    import login_server as old
    # freeze the clocks the old builders read
    old.time = types.SimpleNamespace(time=lambda: NOW, sleep=lambda s: None)

    class _DT:
        @staticmethod
        def now():
            return types.SimpleNamespace(timestamp=lambda: NOW, isoformat=lambda: "x")
    old.datetime = types.SimpleNamespace(datetime=_DT)
    old.log_line = lambda text: None
    # no live-override files
    old.current_spawn = lambda: old.SPAWN_POSITION
    old.current_module = lambda: (old.MOVEMENT_MODULE_SEQ, old.MOVEMENT_MODULE_TYPE)
    return old


FAILS = []


def same(name, a, b):
    if a == b:
        print(f"  same  {name}")
    else:
        FAILS.append(name)
        n = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
        print(f"  DIFF  {name}: lengths {len(a)} / {len(b)}, first difference at byte {n}")


def joined(msgs):
    return b"".join(m for _, m in msgs)


def main(old_dir):
    old = load_old(old_dir)
    roster = old.ROSTER
    print("connection and account")
    same("hello reply", old.build_hello_reply(b""), M.hello_reply(NOW))
    same("referral", old.build_referral("127.0.0.1", 9001), M.referral("127.0.0.1", 9001))
    same("server switch", old.build_frame(0x100, struct.pack("<I", 1)), M.server_switch(1))
    same("time packet", old.build_frame(0x01000000, struct.pack(">d", NOW)), M.time_packet(NOW))
    same("initial events (11 messages)", joined(old.build_initial_events()), joined(M.initial_events(roster, 30, "Player")))

    print("queue, lobby, match entry")
    did, qflags = 0x40000991, 0
    body = struct.pack("<II", did, qflags) + b"\x00" + struct.pack("<I", 0xFFFFFFFF)
    old.QUEUE_STATE.clear()
    r = old.client_event_replies(old.SVC_PLAYER_SYSTEM, 0x20EB, body)
    same("join queue replies", joined(r), M.joined_queue(did, qflags) + M.match_found(1, 30))
    r = old.client_event_replies(old.SVC_PLAYER_SYSTEM, 0x20CA, b"")
    same("accept match replies", joined(r), M.players_accepted(1) + M.lobby_room_created(did, qflags)
         + M.referral("127.0.0.1", 9001))
    same("enter match 0x20af", old.build_enter_match(), M.enter_match(did, 0x40000086, [0xA0000076]))
    same("end room check 0", old.build_message(old.SVC_PLAYER_SYSTEM, 0x2016, b"\x00" + struct.pack("<I", 0)),
         M.end_room_check(0))
    old.threading = types.SimpleNamespace(Timer=lambda *a, **k: types.SimpleNamespace(start=lambda: None),
                                          Lock=old.threading.Lock)
    r = old.client_event_replies(old.SVC_PLAYER_SYSTEM, 0x20F2, b"")
    same("connect to lobby replies", joined(r), M.lobby_player(0x40000086, "Player", 1, 1)
         + M.lobby_state(did, qflags, 0x40000086, 1) + M.end_room_check(1) + M.all_loaded(1))
    r = old.client_event_replies(old.SVC_PLAYER_SYSTEM, 0x20D5, struct.pack("<I", 25))
    same("loading percent echo", joined(r), M.loading_percent(1, 25, 1))

    print("world objects")
    spawn = tuple(old.SPAWN_POSITION)
    mover = Mover(spawn, 6.0)
    champ_props = M.champion_properties("Gaslight Batman", 1, 318767845)
    same("champion property list", repr(old.CHAMPION_PROPERTIES).encode(), repr(champ_props).encode())
    for in_world in (False, True):
        old.QUEUE_STATE["in_world"] = in_world
        for seq, link in ((1, False), (2, True), (5, True)):
            o = old.build_match_objects(sequence=seq, link_agent=link)
            links = ({M.PROP_CONTROLLED_AGENT: M.CHAMPION_AGENT_ID, M.PROP_PLAYER_ENTITY_LINK_2: M.CHAMPION_AGENT_ID}
                     if link else {})
            common = dict(position=mover.position(), sequence=seq, heading=0.0, speed=0.0, tele_seq=1,
                          second_seq=1 if in_world else 0, module=(1, 1))
            n = (M.create_object(M.CHAMPION_AGENT_ID, 0x40000086, NOW, properties=champ_props, **common)
                 + M.create_object(M.LOCAL_PLAYER_ID, 0x40000086, NOW, iid_properties=links,
                                   properties=M.PLAYER_PROPERTIES
                                   + (M.player_late_properties(did) if seq >= 2 else []), **common))
            same(f"match objects seq {seq} link {link} in_world {in_world}", o, n)
    # a walking frame
    old.MOVER.update(spawn=spawn, pos=[30.0, 55.0, 200.1], target=[40.0, 57.0, 200.0], heading=0.3, speed=6.0)
    o = old.build_create_object(old.CHAMPION_AGENT_ID, class_id=0x40000086, position=spawn[:4] + (30.0, 55.0, 200.1),
                                sequence=3, heading=0.3, speed=6.0, tele_seq=1, properties=old.CHAMPION_PROPERTIES)
    n = M.create_object(M.CHAMPION_AGENT_ID, 0x40000086, NOW, position=spawn[:4] + (30.0, 55.0, 200.1), sequence=3,
                        heading=0.3, speed=6.0, tele_seq=1, second_seq=1, module=(1, 1), properties=champ_props)
    same("walking champion bundle", o, n)
    same("remove object", old.build_remove_object(0x0200000000000031), M.remove_object(0x0200000000000031))
    same("vitals", old.build_vitals(old.CHAMPION_AGENT_ID, old.CHAMPION_VITALS),
         M.vitals(M.CHAMPION_AGENT_ID, [(600, 600), (100, 100)]))
    same("cinematic", old.build_message(old.LOCAL_PLAYER_ID, 0x20F5, bytes(1) + struct.pack("<II", 1, 0x35000026)),
         M.cinematic(0x35000026))

    print("tutorial 1")

    class FakeMatch:
        team, module, second_seq = 1, (1, 1), 1
        vitals = [(600, 600), (100, 100)]
        cfg = {"tutorial": {"meteors": False, "pacing": 0}, "combat": {"ping_cell": 0}}   # Phase 3 additions: not in the old server
        entities = {}

        def spawn(self, name, now, attackable=True):   # Phase 2 drone spawn: not in the old server
            return []
    fm = FakeMatch()
    fm.mover = Mover(spawn, 6.0)
    tut = tutorial1.Tutorial(fm, targets=[(36.0, 57.5, 200.0), (44.0, 58.5, 200.0)], drone_step=99)  # old targets
    old.TUTORIAL["step"] = 0
    old.QUEUE_STATE["avatar_seq"] = 0          # skip the old resend inside tutorial_start
    captured = []
    old.threading = types.SimpleNamespace(Timer=lambda d, fn: types.SimpleNamespace(start=lambda: captured.append(fn)),
                                          Lock=old.threading.Lock)
    old.send_user = lambda msg: SENT.append(msg)
    SENT = []
    old.tutorial_start()
    captured[0]()                              # run the delayed deliver()
    same("tutorial start batch", b"".join(SENT), joined(tut.start(NOW)))
    # Phase 3 paces the lines (same messages, another order) and moved the
    # Basic Attack hint (0x2162, hint 17) from the drone step to the wave.
    basic_hint = M.tutorial_hint(tutorial1.HINT_BASIC_ATTACK)
    for step_xy in ((36.0, 57.5), (44.0, 58.5)):
        old.MOVER["pos"] = [step_xy[0], step_xy[1], 200.0]
        fm.mover.pos = [step_xy[0], step_xy[1], 200.0]
        o = sorted(m for _, m in old.tutorial_arrived() if m != basic_hint) if old.at_tutorial_target() else []
        n = sorted(m for _, m in tut.arrived(NOW))
        same(f"tutorial arrival at {step_xy} (same messages)", b"".join(o), b"".join(n))
    old.PLAYER_PING["count"] = 0
    body = struct.pack("<ffQI", 27.9, 64.4, 0, 1)
    o = joined(old.answer_ping(body))
    n = tutorial1.player_ping(fm, body, 1, NOW)[1]
    same("player ping", o, n)

    print()
    print("ALL SAME" if not FAILS else f"{len(FAILS)} DIFFERENCES: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "ics")))
