"""Minimal logging debugger for the (32-bit) Infinite Crisis client.

Attaches to InfiniteCrisis_patched.exe, plants int3 breakpoints at the RVAs in
BREAKPOINTS and logs a line (with a few values read from the stack/memory)
each time one is hit. Never pauses the game. Run with 64-bit Python:

    python tracer.py            # attach to the running client
Log: logs/trace.log
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys
import time

PROCESS_NAME = "InfiniteCrisis_patched.exe"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "trace.log")
# Create this file to make the tracer remove its breakpoints and detach (game keeps running).
STOP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "tracer.stop")
# Live experiments: write lines to logs/tracer.inject (consumed once):
#   poke8 <expr> <hex>      write a byte      poke32 <expr> <hex>   write a dword
#   call <rva> [arg ...]    call a cdecl game function on the MAIN thread (hijacked
#                           at the next SCRIPT CALL breakpoint hit, returns via a cave)
HACK_PLACE_PLAYER = False  # stopgap, see on_breakpoint
INJECT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "tracer.inject")
INJECT_HOOK_RVA = 0x69af20          # conn-mgr per-frame update (main thread); bp planted on demand
INJECT_CAVE_RVA = 0x6b4e92          # 14 bytes of int3 padding

# rva -> (name, [(label, expression)]). Expressions are evaluated by ev():
#   "esp+8"      register +- offset
#   "[esp+8]"    u32 read; nesting allowed: "[[esp+8]+8]"
#   "q[...]"     u64 read
BREAKPOINTS = {
#   0x70f960: ("delivery", [("dest", "q[[esp+4]+20]"), ("evt", "[[esp+4]+2c]")]),
    0x70faf4: ("delivery FAILED", []),
    0x24e070: ("game_router", [("evt", "[[esp+8]+8]"), ("dest", "q[[esp+c]+30]")]),
#   0x70d9c0: ("base_dispatch", [("evt", "[[esp+8]+8]"), ("dest", "q[[esp+c]+30]")]),
    0x70db7a: ("base_dispatch: NO RECEIVER (0x81960001)", []),
    0x70dac2: ("base_dispatch: dest not in receiver map", []),
    0x24ccd0: ("objmgr park event", [("key", "q[esp+8]"), ("dest", "q[esp+10]"), ("evt", "[[esp+18]+8]")]),
    0x298a90: ("EB set-local-player execute", [("receiver", "[[esp+8]+14]")]),
    0x298ac2: ("EB: receiver QI failed", []),
    0x2a8170: ("EB: broadcast", [("player", "q[esp+4]")]),
    0x24b2e0: ("objmgr SetLocalPlayer", [("player", "q[esp+4]")]),
    0x4aac90: ("209D char-list execute", [("receiver", "[[esp+8]+14]")]),
    0x4aacc2: ("209D: receiver QI failed", []),
    0x67e4b0: ("209D: handler", []),
    0x633090: ("209D: UI notifier", []),
    0x4fb290: ("209D: build script args", []),
    0x4fbd02: ("209D: calling GM_UI.RecvNotice_CharacterAdvancementData", []),
    0x6833d0: ("20ED champion-data handler", [("outer_count", "[[esp+c]+8]")]),
    0x683424: ("20ED: EMPTY twice -> error path", []),
    0x483910: ("20ED: client re-requests data", []),
    0x6733b0: ("2024 DeliverEncounterInfo handler", []),
    0x69b170: ("LOADING BIT 1 set", []),
    0x69b1c0: ("LOADING BIT 2 set", []),
    0x69b210: ("LOADING BIT 4 set", []),
    0x69b260: ("LOADING BIT 8 set", []),
    0x69be40: ("login-flow listener slot3 (bit 8 path)", []),
    0x298920: ("CE account/character-set execute", [("receiver", "[[esp+8]+14]")]),
    0x4241d0: ("CE: account object stores list (notice 0x12)", []),
    0x48a860: ("login flow: acts on first character entry", []),
    0x24ab70: ("batch(4) -> object batch", []),
    0x24bd30: ("object batch dispatch", [("dest", "q[[esp+8]+30]"), ("subcount", "[[esp+4]+28]")]),
    0x249230: ("F2: precheck for B0 sub-event", []),
    0x24d942: ("F2: REFUSED (no B0 in batch)", []),
    0x207dc0: ("entity factory: create from descriptor", []),
    0x207ee0: ("entity factory: create from batch", []),
    0x696a60: ("login flow: slot5 notice 0x11 (player object)", [("player_obj", "eax")]),
    0x696a00: ("login flow: 696a00 check", []),
    0x29be20: ("STACK native notice 0xb dispatch (first world frame rendered)", []),
    0x696af0: ("flow: world rendered -> clears pending bit 4 (+20%)", []),
    0x69cff0: ("0x20F5 camera/cinematic handler", [("mgr", "ecx"), ("cur_did", "[ecx+3c]"), ("busy", "[ecx+30]")]),
    0x4ac050: ("0x20F5 execute", []),
    0x3d16f9: ("render precheck FAIL: viewer cell not loaded (cellmgr vfunc+8)", []),
    0x3d1763: ("render precheck: after 188270 (player pos ok?)", [("al", "eax")]),
    0x3d1794: ("render precheck: player cell loaded?", [("al", "eax")]),
    0x3d17be: ("render precheck FAIL (late)", []),
    0x3d17c9: ("render precheck PASS", []),
    0x69d140: ("0x20F5 handler entry", [("mgr", "[base+17766b0]"), ("evt", "[esp+8]")]),
    0x2a6540: ("camera director: load cinematic", [("did", "[esp+4]"), ("state", "[ecx+d0]")]),
    0x2a5f20: ("camera director: state check (3 -> target local player)", [("state", "[ecx+d0]")]),
    0x3db7c0: ("STACK camera: add target", [("cam", "ecx")]),
    0x171af0: ("STACK PhysicsComponent::SetPosition", [("this", "ecx"), ("pos", "[esp+4]")]),
    0x172460: ("STACK physics vfunc +0x38 (calls SetPosition)", [("this", "ecx"), ("arg", "[esp+4]"), ("flags38", "[[esp+4]+38]")]),
    0x20aed0: ("B0 position update -> physics", [("this", "ecx"), ("new", "[esp+4]"), ("part02_flags", "[[esp+4]+b0]"), ("sub40", "[[esp+4]+b2]")]),
    0x6b5200: ("UI graph condition: player ready in world", [("pending", "[[base+17763c0]+68]"), ("charsys100", "[[[base+17758d4]+64]+100]")]),
    0x6b528e: ("UI graph condition: player ready -> TRUE", []),
    0x6b4090: ("UI graph action 3a (load screen?)", [("did", "[ecx+c]")]),
    0x6b4870: ("UI graph action cb", [("did", "[ecx+c]")]),
    0x6b47b0: ("UI graph action cc", []),
    0x6b46c0: ("UI graph action 179", []),
    0x6b3fb0: ("UI graph action 43", [("flag", "[ecx+c]")]),
    0x60d830: ("STACK listener setter fc/100/104", [("this", "ecx"), ("a", "[esp+4]"), ("b", "[esp+8]"), ("c", "[esp+c]")]),
    0x60a570: ("controlled agent changed (sets charsys+0x100 when != player)", [("new_lo", "[esp+10]"), ("new_hi", "[esp+14]")]),
    0x60a5a2: ("controlled agent: charsys+0x100 = 1", []),
    0x68a490: ("input handler 68a490", [("evt_type", "[[esp+4]+8]"), ("action", "[[esp+4]+c]"), ("ui_b1", "[[base+17771f0]+b0]"), ("cin30", "[[base+17766b0]+30]")]),
    0x68a4f7: ("input handler: past gates (looks up agent 45c150)", []),
    0x68a507: ("input handler: agent found", [("agent", "edi")]),
    0x670030: ("STACK issue command", [("this", "ecx"), ("agent", "[esp+4]"), ("cmd", "[esp+8]"), ("target", "[esp+c]"), ("busy_cc", "[ecx+cc]")]),
    0x670045: ("issue command: REJECTED", []),
    0x670076: ("issue command: agent check ok", []),
    0x67022c: ("issue command: passed 4686c0", []),
    0x48b030: ("STACK send command to server", [("cmd", "[esp+8]"), ("target", "[esp+c]")]),
    0xfa870: ("pathfinder RefineGoal", [("region", "[esp+c]"), ("lb_cell", "[esp+10]"), ("x", "[esp+18]"), ("y", "[esp+1c]"), ("z", "[esp+20]")]),
    0xfa89c: ("RefineGoal: direct CanGo ok", []),
    0xfa91d: ("RefineGoal: FAIL no nav record for landblock", []),
    0xfa992: ("RefineGoal: FAIL no nav section (f5c80)", []),
    0xfa9b8: ("RefineGoal: FAIL nav mesh name lookup", []),
    0xfa9cb: ("RefineGoal: searching nearest nav face", []),
    0x153e70: ("set movement module", [("comp", "ecx"), ("type", "[esp+4]"), ("seq", "[esp+10]")]),
    0x20a340: ("replay module init (rigid body + first teleport)", [("module", "ecx"), ("entity", "[ecx+4]"), ("phys", "[[ecx+4]]")]),
    0x20a270: ("replay module teleport", [("module", "ecx"), ("region", "[[esp+4]+4]"), ("lb", "[[esp+4]+8]"), ("phys", "[[ecx+4]]")]),
    0x209c70: ("physics: set position", [("pos", "[esp+4]"), ("region", "[[esp+4]+4]"), ("lb", "[[esp+4]+8]")]),
    0x17dd70: ("B0 state -> Position", [("state", "ecx"), ("state_pos_region", "[ecx+2c]"), ("state_pos_lb", "[ecx+30]")]),
    # flow listener (flow+0x18, iface id [0x186ced0]); slot +0x58 = 0x696cf0 sets flow+0x78
    0x696b20: ("STACK flow listener +0x2c (clears pending bit 1)", []),
    0x69a260: ("STACK flow listener +0x30", []),
    0x699360: ("STACK flow listener +0x24", []),
    0x696150: ("STACK flow listener +0x28", []),
    0x69af00: ("STACK flow listener +0x5c", []),
    0x696cf0: ("STACK flow listener +0x58 SETS flow+0x78", []),
    0x696a25: ("login flow: clears pending bit 8", []),
    0x699140: ("login flow: start (sets pending mask)", []),
    0x699b60: ("login flow: 699b60 finish", [("pending", "[ecx+68]")]),
    0x14ad90: ("WEF BuildCreationInfoFromEntityDesc", [("did", "[[esp+8]+8]")]),
    0x14ae42: ("WEF FAILED BuildCreationInfoFromEntityDesc", [("hr", "eax")]),
    0x14b706: ("WEF FAILED GetWorldEntityCreationInfo", []),
    0x14f3c3: ("WEF ERROR wstate missing parent .entity", []),
    0x14f4b0: ("WEF ERROR entity category not allowed in .wc", []),
    0x14f2bd: ("WEF assert site 14f2bd (wstate load failed?)", []),
    0x14f32b: ("WEF assert site 14f32b", []),
    0x14f406: ("WEF assert site 14f406", []),
    0x14f585: ("WEF FAILED ConstructStep1 (IID allocation / duplicate)", []),
    0x14f5ea: ("WEF FAILED ConstructStep2 (registration)", []),
    0x14f6af: ("WEF FAILED ConstructStep3 (component creation)", []),
    0x14f708: ("WEF FAILED ConstructStep4 (message registration)", []),
    0x14f762: ("WEF FAILED ConstructStep5 (OnEntityConstruction)", []),
    0x14f7b8: ("WEF FAILED ConstructStep6 (FinalizeEntity)", []),
    0x24cba0: ("objmgr: OBJECT READY (pending -> live)", []),
#   0x3e20e0: ("entity job run", [("a", "[esp+8]"), ("b", "[esp+10]")]),
    0x521be0: ("UI state event fired (native)", [("code", "[esp+4]")]),
    0x521d78: ("UI state event -> script", [("@script_invoke", "eax")]),
    0x49994a: ("tracker-enable glue: movie Invoke call", [("movie", "ecx"), ("invoke_fn", "eax")]),
    0x3e35d7: ("HOT env type eval: local player entity", [("entity", "esi")]),
    0x3e35ed: ("HOT env type eval: prop 0x956 read", [("eax", "eax"), ("value", "[ebp-4]")]),
    0x3e363c: ("HOT env type eval: falling back to region lookup", [("pos", "[ebp+8]")]),
    0x635dc0: ("STACK dialog: encounter conversation table loader (listener)", [("this", "ecx")]),
    0x613e20: ("STACK dialog: set conversation table", [("mgr", "ecx"), ("did", "[esp+4]"), ("loaded_before", "[ecx+128]")]),
    0x6478b1: ("STACK dialog: conversation table flag CLEARED", [("mgr", "esi")]),
    0x613c90: ("dialog: conversation lookup", [("mode", "[esp+8]"), ("key", "[esp+c]"), ("loaded", "[ecx+128]")]),
    0x677ae0: ("dialog: start conversation sequence", [("found", "[esp+4]"), ("flags", "[ecx+14c]")]),
    0x6b4ea0: ("fires DereferenceDIDs (0x28)", []),
    0x4baeb0: ("216a server-options execute", [("receiver", "[[esp+8]+14]")]),
    0x6742d0: ("216a handler", []),
    0x4a9bb0: ("2120 achievements execute", [("receiver", "[[esp+8]+14]")]),
    0x6839e0: ("2120 handler", []),
    0x4baf30: ("218b execute", [("receiver", "[[esp+8]+14]")]),
    0x6839b0: ("218b handler", []),
    0x4aaac0: ("2080 level/xp execute", [("receiver", "[[esp+8]+14]")]),
    0x67dfb0: ("2080 handler", []),
    0x4bae30: ("215d execute", [("receiver", "[[esp+8]+14]")]),
    0x676b80: ("215d handler", []),
    0x670db0: ("landing gate check", [("status", "[ecx+48]"), ("lvl", "[ecx+8c]"), ("f88", "[ecx+88]")]),
    0x670e41: ("LANDING GATE PASSED -> ProtectorAdvancementStatus", [("status", "esi")]),
    0x6c5b70: ("UI state machine: posted 0x6f DeliveredProtectorAdvancementStatus", [("accepted", "eax")]),
    0x6c5ac9: ("UI state machine: posted 0x69 WrapperOnlyResourcesLoaded", [("accepted", "eax")]),
    0x6c565d: ("UI state machine: queued hub event", [("code", "ebx"), ("accepted", "eax")]),
    0x4aaff0: ("20b8 item-statuses execute", [("receiver", "[[esp+8]+14]")]),
    0x688030: ("20b8 handler", []),
    0x67b2f0: ("ownables: try broadcast", [("sent", "[ecx+18]"), ("count", "[ecx+10]")]),
    0x4fea80: ("ownables: -> GM_UI.RecvNotice_ItemStatuses", []),
    0x4fa080: ("ownables: -> GM_UI.RecvNotice_AvailableCharacterList", []),
    0x5dd120: ("PACK LOAD by id", [("pack", "[esp+4]"), ("mgr", "ecx")]),
    # slot allocator 0x5d3400 found no free slot of the pack's category -> pack silently not loaded
    0x5dd1ca: ("PACK LOAD FAILED (no free slot / open failed)", [("pack", "edi"), ("category", "[ebp-3fc]")]),
    0x609e50: ("ResourcePackLoader: entry 609e50 (LoadParentRPs)", []),
    0x609f90: ("ResourcePackLoader: entry 609f90 (LoadMatchData)", []),
    0x60a1e0: ("ResourcePackLoader: entry 60a1e0 (lobby)", []),
    0x6bc620: ("lobby mgr: VerifyAndLoadAllNeededRPS", []),
    0x60a050: ("ResourcePackLoader: load request", [("who", "s[[esp+10]]"), ("count", "[[esp+4]+8]"), ("first", "[[[esp+4]]]")]),
    0x70fad4: ("delivery: event rejected/deserialize failed", []),
    0x24d8a0: ("F2 create/update object", [("id", "q[esp+4]")]),
    0x24ca10: ("F2: create new object", [("id", "q[esp+4]")]),
    0x6bc3c0: ("2028 lobby-room-created handler", []),
    # connection-manager notice listener (vtable 0x1206de8 slot 0): code 3 = connected
    # (login checklist bit 1), code 4 -> 0x69aaa0 (+0x70 bit 1, state 5 = enter world?)
    0x6ee8f0: ("FATAL ERROR raised (0xffffff)", [("caller", "[esp]"), ("caller2", "[esp+4]"), ("ebp_ret", "[ebp+4]"), ("ebp_ret2", "[[ebp]+4]")]),
    0x6f2120: ("game error log", [("fmt", "s[esp+8]"), ("arg", "s[esp+c]")]),
    0x699f00: ("20af enter-match handler", []),
    0x6bea40: ("lobby UI ready -> sends ConnectToLobby", []),
    0x6bde80: ("204c lobby state handler", [("room", "[esp+24]")]),
    0x6b84f0: ("206d handler (sets lobby+0x1c0)", [("room", "[esp+8]")]),
    0x6964b0: ("loading progress tick", [("step", "[esp+4]")]),
    0x696567: ("SERVER LOAD COMPLETE (UI 0x33)", []),
    0xbe2270: ("net: session-state change (posts 0x1006)", [("caller", "[esp]"), ("id_lo", "[esp+4]"), ("id_hi", "[esp+8]"), ("a3", "[esp+c]"), ("a4", "[esp+10]")]),
    0xbe2080: ("net: ServerSwitch handler", [("seq", "[[esp+4]+18]"), ("had_switch", "[ecx+1c0]"), ("cur_idx", "[ecx+1ac]")]),
    0xbe33e0: ("net: close all but current", [("cur_idx", "[ecx+1ac]")]),
    0xbe47f0: ("net: be47f0 (conn idx)", [("caller", "[esp]"), ("idx", "[esp+4]")]),
    0xbe27b0: ("net: be27b0", [("caller", "[esp]"), ("a1", "[esp+4]")]),
    0x705557: ("net: state==5 -> 6 check (705557)", [("caller", "[esp]")]),
    0x95cb: ("receiver 0x9530 -> notice 0x15 (after call)", [("evt_id", "[[ebp+8]+8]"), ("evt_c", "[[ebp+8]+c]"), ("evt_10", "[[ebp+8]+10]"), ("evt_14", "[[ebp+8]+14]")]),
    0x29ba50: ("notice 0x15 broadcast (EndCharacterSession)", [("ret0", "[esp]"), ("ret1", "[ebp+4]"), ("ret2", "[[ebp]+4]"), ("ret3", "[[[ebp]]+4]"), ("a1", "[esp+4]"), ("a2", "[esp+8]")]),
    0x69a040: ("conn-mgr DISCONNECT with reason", [("caller", "[esp]"), ("a1", "[esp+4]"), ("a2", "[esp+8]"), ("a3", "[esp+c]"), ("d0", "[ecx+d0]")]),
    0x69a190: ("conn-mgr listener 1206dcc slot -> disconnect", [("a1", "[esp+4]"), ("a2", "[esp+8]")]),
    0x69a1f0: ("conn-mgr listener 1206e00 slot -> disconnect", [("a1", "[esp+4]"), ("a2", "[esp+8]")]),
    0x69acc0: ("conn-mgr 69acc0 -> disconnect", [("a1", "[esp+4]")]),
    0x69add0: ("conn-mgr 69add0 -> disconnect", [("a1", "[esp+4]")]),
    0x69ae30: ("conn-mgr critical error -> disconnect", [("a1", "[esp+4]")]),
    0x6f8710: ("STREAM ERROR (deserialize)", [("caller", "[esp]")]),
    0x4479b0: ("2029 serializer called", [("this", "ecx"), ("stream_flags", "[[esp+4]+4]")]),
    0x447d01: ("2029 serializer end (write path)", []),
    0x4479c1: ("2029 cursor after base", [("pos", "[esi+c]"), ("end", "[esi+34]"), ("next4", "[[esi+c]]")]),
    0x4479ce: ("2029 cursor after S", [("pos", "[esi+c]"), ("next4", "[[esi+c]]"), ("S_u32a", "[edi+40]")]),
    0x447a52: ("2029 cursor before name", [("pos", "[esi+c]"), ("next4", "[[esi+c]]"), ("f70", "[edi+70]")]),
    0x447a68: ("2029 cursor after name", [("pos", "[esi+c]"), ("next4", "[[esi+c]]")]),
    0x447d1c: ("2029 read path before tail struct", [("this", "edi"), ("f70", "[edi+70]"), ("f9c", "[edi+9c]"), ("fa0", "[edi+a0]"), ("fac", "[edi+ac]"), ("fb0", "[edi+b0]")]),
    0x4b9195: ("2029 execute: decoded fields", [("this", "esi"), ("S0", "[esi+20]"), ("f68", "[esi+68]"), ("f70", "[esi+70]"),
                                                ("f9c", "[esi+9c]"), ("fa0", "[esi+a0]"), ("fac", "[esi+ac]"), ("fb0", "[esi+b0]")]),
    0x48a860: ("0xCE: acts on first character entry (sends 0x20d4)", [("local_id_lo", "[base+17579f0]"), ("local_id_hi", "[base+17579f4]")]),
    0x6bd0a0: ("2029 lobby player slot handler", [("local_id_lo", "[base+17579f0]"), ("local_id_hi", "[base+17579f4]"),("player_lo", "[esp+14]"), ("champion", "[esp+24]"), ("room", "[esp+30]")]),
    0x6bbb90: ("lobby slot filler", [("champion", "[esp+1c]")]),
    0x613e20: ("charsys: set selected champion", [("did", "[esp+4]")]),
    0x6b9080: ("2016 end-room-check handler", [("room", "[esp+8]")]),
    0x6b8ec0: ("lobby CheckTransitionToWorldLoad", [("transition_set", "[ecx+a8]")]),
    0x699e20: ("conn-mgr match-load check", [("flags70", "[ecx+70]")]),
    0x699e53: ("conn-mgr: ALL FLAGS SET -> loading match", []),
    0x699460: ("conn-mgr LoadMatchData_", []),
    0x699370: ("conn-mgr LoadParentRPs", [("count", "[ecx+ac]")]),
    0xbe2700: ("net: packet switch", [("type", "[[esp+8]+8]")]),
    0xbe3240: ("net: referral -> connect", [("port", "[[esp+4]+24]")]),
    0xbe32a7: ("net: referral address resolve FAILED (notice 6)", []),
    0xbe4950: ("net: ConnectRequest handler (login conn, posts code 2)", [("pkt", "[esp+4]"), ("conn", "[esp+8]"), ("this", "ecx")]),
    0xbe4550: ("net: handler that posts code 4 (world conn?)", [("pkt", "[esp+4]"), ("conn", "[esp+8]"), ("this", "ecx")]),
    0x69bcd0: ("conn-mgr connection notice", [("code", "[esp+4]"), ("a", "[esp+8]"), ("b", "[esp+c]")]),
    0x6bc44c: ("2028: -> UI state event 0x14 (lobby already set?)", []),
    0x615550: ("20fa found-match handler", [("a", "[esp+8]"), ("b", "[esp+c]")]),
    0x4ba780: ("20c0 joined-queue execute", [("receiver", "[[esp+8]+14]")]),
    0x637c70: ("20c0 joined-queue handler", [("did", "[[esp+8]]"), ("status", "[esp+14]")]),
    # GM_Skill.SendQuery_InqSkillToolTipInfo (query 0x10000164): binding 0x553b40 -> dispatch 0x51dfa0
    0x5544e9: ("skill tooltip query -> dispatch", [("powerset", "ecx"), ("slot", "eax")]),
    0x51dfc9: ("skill tooltip: listener lookup", [("entry", "eax")]),
    0x51e061: ("skill tooltip: calling handler", [("handler", "edx"), ("this", "ecx")]),
    0x5544ee: ("skill tooltip query returned", [("ok", "eax")]),
    0x66de10: ("skill tooltip worker", [("powerset", "[esp+4]"), ("slot", "[esp+8]")]),
    0x66deaf: ("skill tooltip: powerset record", [("rec", "[ebp-c]")]),
    0x66dede: ("skill tooltip: slot lookup 468930", [("ok", "eax"), ("out0", "[ebp-8]"), ("out1", "[ebp-4]")]),
    0x66df27: ("skill tooltip: building tooltip 65dd80", []),
    # ---- minimap image (2026-10-05 night): local-player property 0x100001d3 (encounter DID)
    # -> map manager listener 0x66a8e0 -> 0x64c2c0(did) reads twin prop 0x10000287 -> 0x49f4c0(image)
    0x60cbc0: ("map manager: registers 0x100001d3 listener on local player", []),
    0x64c2c0: ("map manager: encounter did -> map image", [("did", "[esp+4]")]),
    0x64c346: ("map manager: twin has 0x10000287, loading map image", [("img", "[ebp-4]")]),
    0x49f4c0: ("map: DeliverMapData to HUD", [("img", "[esp+4]")]),
    # ---- overhead nameplate = FloatyVitalsManager (native object vtable 0x1202d1c, ctor 0x66e720)
    # engine notice 0x26 -> 0x63a900(iid lo, hi) -> filter 0x60efc0(entity) -> 0x63a840 adds it;
    # system update 0x65ed60 flushes with 0x650a70 only when [obj+0x19] != 0 (UI movie loaded,
    # script notice 0x10000032 FloatyVitalsManager_OnLoadComplete) and [obj+0x18] == 0.
    0x63a900: ("floaty: notice 0x26 (entity iid)", [("lo", "[esp+4]"), ("hi", "[esp+8]")]),
    0x60efc0: ("floaty: filter", [("entity", "[esp+4]"), ("kind114", "[[esp+4]+114]"), ("flags118", "[[esp+4]+118]"), ("vitals80", "[[esp+4]+80]")]),
    0x60f018: ("floaty: filter passed kind==7/8 and (flag 8 or prop 0x10000831)", []),
    0x60f038: ("floaty: filter passed flag 0x80000 check", []),
    0x63a840: ("floaty: entity ADDED", [("entity", "[esp+4]"), ("n", "[ecx+1c]")]),
    0x650a70: ("floaty: flush arrays", [("n", "[ecx+1c]"), ("w18", "[ecx+18]")]),
    0x504440: ("floaty: send GM_UI.RecvNotice_UpdateFloatyVitalArray", [("n", "[[esp+4]+8]")]),
    0x650770: ("floaty: update one entity", [("entity", "[esp+4]")]),
    0x679410: ("floaty: display type for entity (prop 0x10000456 listener)", [("lo", "[esp+4]"), ("hi", "[esp+8]"), ("type", "[esp+c]")]),
    0x650c84: ("floaty: per-entity life state (needs 4 = Alive)", [("entity", "esi"), ("state", "eax")]),
    0x650cd7: ("floaty: add path reached visibility check", [("vis_top_byte", "[ebp-4]")]),
    0x650ce2: ("floaty: entity accepted into arrays", [("entity", "esi")]),
    0x680cd0: ("entity prop listener 680cd0 (map note / floaty)", [("entity", "[esp+4]"), ("prop", "[[esp+c]]")]),
    0x64b150: ("map note: create for entity", [("entity", "[esp+4]")]),
    0x64b36b: ("map note: ADDED (6144d0)", [("icon", "[ebp-c]"), ("category", "[ebp-20]"), ("team", "[ebp-10]")]),
    0x60cf60: ("map note: refresh -> AddMapNotes", []),
}

# Hardware write watchpoints (max 4): (label, address expression evaluated once
# after attach; "base" = image base). Logged with the writing instruction's rva
# (the instruction AFTER the write) and a stack-scan call chain.
# Label prefix "RW " = break on read or write (else write only). Override for a
# live session with logs/tracer.watches (lines "label|expr").
WATCHES = [
    ("flow+0x78 (ServerLoadComplete/pending bit 8 condition)", "[base+17763c0]+78"),
    ("charsys+0x100 (pending bit 8 condition)", "[[base+17758d4]+64]+100"),
    ("TEST flow+0x6c (login checklist; proves watchpoints work)", "[base+17763c0]+6c"),
    ("flow+0x68 (pending mask)", "[base+17763c0]+68"),
]
_wf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "tracer.watches")
if os.path.exists(_wf):
    WATCHES = [tuple(l.strip().split("|", 1)) for l in open(_wf) if "|" in l]

# Script calls fired constantly by the UI; not logged (they used to exhaust the
# 4000-line SCRIPT CALL budget within minutes).
NOISY_SCRIPT_CALLS = ("RecvNotice_ActionEnumEvent", "RecvNotice_SetAchievementData",
                      "RecvNotice_ForceOnSized", "RecvNotice_FPSUpdate")

# Breakpoints planted at run time (address only known from a register).
DYNAMIC = {
    "@script_invoke": ("SCRIPT CALL", [("name", "s[[esp+4]]")]),
}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

EXCEPTION_DEBUG_EVENT, CREATE_THREAD_DEBUG_EVENT, CREATE_PROCESS_DEBUG_EVENT = 1, 2, 3
EXIT_THREAD_DEBUG_EVENT, EXIT_PROCESS_DEBUG_EVENT, LOAD_DLL_DEBUG_EVENT = 4, 5, 6
DBG_CONTINUE, DBG_EXCEPTION_NOT_HANDLED = 0x00010002, 0x80010001
BREAKPOINTS_CODES = (0x80000003, 0x4000001F)   # native / WOW64 int3
SINGLE_STEP_CODES = (0x80000004, 0x4000001E)
WOW64_CONTEXT_FULL = 0x00010007


class WOW64_FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [("ControlWord", wt.DWORD), ("StatusWord", wt.DWORD), ("TagWord", wt.DWORD),
                ("ErrorOffset", wt.DWORD), ("ErrorSelector", wt.DWORD), ("DataOffset", wt.DWORD),
                ("DataSelector", wt.DWORD), ("RegisterArea", ctypes.c_byte * 80),
                ("Cr0NpxState", wt.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [("ContextFlags", wt.DWORD),
                ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD), ("Dr3", wt.DWORD),
                ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
                ("FloatSave", WOW64_FLOATING_SAVE_AREA),
                ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD), ("SegDs", wt.DWORD),
                ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD), ("Edx", wt.DWORD),
                ("Ecx", wt.DWORD), ("Eax", wt.DWORD),
                ("Ebp", wt.DWORD), ("Eip", wt.DWORD), ("SegCs", wt.DWORD), ("EFlags", wt.DWORD),
                ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
                ("ExtendedRegisters", ctypes.c_byte * 512)]


class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [("ExceptionCode", wt.DWORD), ("ExceptionFlags", wt.DWORD),
                ("ExceptionRecord", ctypes.c_void_p), ("ExceptionAddress", ctypes.c_void_p),
                ("NumberParameters", wt.DWORD), ("ExceptionInformation", ctypes.c_void_p * 15)]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD), ("dwFirstChance", wt.DWORD)]


class CREATE_THREAD_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("hThread", wt.HANDLE), ("lpThreadLocalBase", ctypes.c_void_p),
                ("lpStartAddress", ctypes.c_void_p)]


class CREATE_PROCESS_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("hFile", wt.HANDLE), ("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("lpBaseOfImage", ctypes.c_void_p), ("dwDebugInfoFileOffset", wt.DWORD),
                ("nDebugInfoSize", wt.DWORD), ("lpThreadLocalBase", ctypes.c_void_p),
                ("lpStartAddress", ctypes.c_void_p), ("lpImageName", ctypes.c_void_p),
                ("fUnicode", wt.WORD)]


class LOAD_DLL_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("hFile", wt.HANDLE), ("lpBaseOfDll", ctypes.c_void_p),
                ("dwDebugInfoFileOffset", wt.DWORD), ("nDebugInfoSize", wt.DWORD),
                ("lpImageName", ctypes.c_void_p), ("fUnicode", wt.WORD)]


class DEBUG_UNION(ctypes.Union):
    _fields_ = [("Exception", EXCEPTION_DEBUG_INFO), ("CreateThread", CREATE_THREAD_DEBUG_INFO),
                ("CreateProcessInfo", CREATE_PROCESS_DEBUG_INFO), ("LoadDll", LOAD_DLL_DEBUG_INFO),
                ("pad", ctypes.c_byte * 160)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("u", DEBUG_UNION)]


k32.OpenProcess.restype = wt.HANDLE
k32.OpenThread.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
k32.FlushInstructionCache.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64SetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.CloseHandle.argtypes = [wt.HANDLE]
psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD]
psapi.GetModuleBaseNameW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.LPWSTR, wt.DWORD]


def log(text):
    line = f"{time.strftime('%H:%M:%S')} {text}"
    try:
        print(line, flush=True)
    except OSError:
        pass
    for _ in range(20):   # the log can be briefly locked by a reader
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return
        except PermissionError:
            time.sleep(0.05)


def find_pid(name):
    arr = (wt.DWORD * 4096)()
    needed = wt.DWORD()
    psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed))
    buf = ctypes.create_unicode_buffer(260)
    for pid in arr[:needed.value // 4]:
        h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            continue
        size = wt.DWORD(260)
        ok = k32.QueryFullProcessImageNameW(wt.HANDLE(h), 0, buf, ctypes.byref(size))
        k32.CloseHandle(h)
        if ok and buf.value.lower().endswith("\\" + name.lower()):
            return pid
    return None


class Tracer:
    def __init__(self, pid):
        self.pid = pid
        self.hproc = k32.OpenProcess(0x1F0FFF, False, pid)
        if not self.hproc:
            raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")
        self.base = None
        self.orig = {}       # va -> original byte
        self.pending = {}    # thread id -> va to re-arm after single step
        self.counts = {}
        self.exc_logged = 0
        self.tids = set()
        self.inject_calls = []
        self.inject_saved = None
        self.inject_checked = 0.0

    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.hproc, addr, buf, n, ctypes.byref(got)) or got.value != n:
            raise OSError(f"read {addr:#x}")
        return buf.raw

    def write(self, addr, data):
        got = ctypes.c_size_t()
        if not k32.WriteProcessMemory(self.hproc, addr, data, len(data), ctypes.byref(got)):
            raise OSError(f"write {addr:#x}: {ctypes.get_last_error()}")
        k32.FlushInstructionCache(self.hproc, addr, len(data))

    def find_base(self):
        mods = (ctypes.c_void_p * 1024)()
        needed = wt.DWORD()
        if not psapi.EnumProcessModulesEx(self.hproc, mods, ctypes.sizeof(mods), ctypes.byref(needed), 3):
            raise OSError(f"EnumProcessModulesEx failed: {ctypes.get_last_error()}")
        buf = ctypes.create_unicode_buffer(260)
        for m in mods[:needed.value // ctypes.sizeof(ctypes.c_void_p)]:
            psapi.GetModuleBaseNameW(self.hproc, m, buf, 260)
            if buf.value.lower() == PROCESS_NAME.lower():
                return m
        raise OSError("main module not found")

    def arm(self):
        self.base = self.find_base()
        log(f"attached pid {self.pid}, image base {self.base:#x}, {len(BREAKPOINTS)} breakpoints")
        for rva in BREAKPOINTS:
            va = self.base + rva
            self.orig[va] = self.read(va, 1)
            self.write(va, b"\xCC")
        # "base" in watch expressions resolves through the context's Base attribute
        class _Ctx:
            pass
        c = _Ctx()
        c.Base = self.base
        self.watch_addrs = []
        for label, expr in WATCHES:
            try:
                self.watch_addrs.append((label, self.ev(expr, c)))
            except Exception as e:
                log(f"watch {label}: cannot resolve {expr}: {e}")
        for label, a in self.watch_addrs:
            log(f"watching {label} at {a:#x}")
        for tid in list(self.tids):
            self.set_watches(tid)

    def disarm(self):
        for va, byte in self.orig.items():
            try:
                self.write(va, byte)
            except OSError:
                pass
        # Clear hardware watchpoints: left armed after detach, the next watched
        # write raises a single-step exception nobody handles -> game crash.
        for tid in list(self.tids):
            h = k32.OpenThread(0x1FFFFF, False, tid)
            if not h:
                continue
            ctx = WOW64_CONTEXT()
            ctx.ContextFlags = 0x00010010
            if k32.Wow64GetThreadContext(h, ctypes.byref(ctx)):
                ctx.Dr0 = ctx.Dr1 = ctx.Dr2 = ctx.Dr3 = 0
                ctx.Dr7 = 0
                ctx.Dr6 = 0
                k32.Wow64SetThreadContext(h, ctypes.byref(ctx))
            k32.CloseHandle(h)

    def ev(self, expr, ctx):
        expr = expr.strip()
        if expr.startswith("s[") and expr.endswith("]"):
            raw = self.read(self.ev(expr[2:-1], ctx), 96)
            return raw.split(b"\x00")[0].decode("latin1")
        if expr.startswith("q[") and expr.endswith("]"):
            return struct.unpack("<Q", self.read(self.ev(expr[2:-1], ctx), 8))[0]
        if expr.startswith("[") and expr.endswith("]"):
            return struct.unpack("<I", self.read(self.ev(expr[1:-1], ctx), 4))[0]
        # split on the last top-level '+'
        depth = 0
        for i in range(len(expr) - 1, -1, -1):
            c = expr[i]
            if c == "]":
                depth += 1
            elif c == "[":
                depth -= 1
            elif c == "+" and depth == 0:
                return (self.ev(expr[:i], ctx) + int(expr[i + 1:], 16)) & 0xFFFFFFFF
        if expr.lower() == "base" and self.base:
            return self.base
        reg = expr.capitalize()
        if hasattr(ctx, reg):
            return getattr(ctx, reg)
        return int(expr, 16)

    def set_watches(self, tid):
        if not getattr(self, "watch_addrs", None):
            return
        h = k32.OpenThread(0x1FFFFF, False, tid)
        if not h:
            return
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = 0x00010010   # WOW64_CONTEXT_DEBUG_REGISTERS
        if k32.Wow64GetThreadContext(h, ctypes.byref(ctx)):
            dr7 = 0
            for i, (label, addr) in enumerate(self.watch_addrs[:4]):
                setattr(ctx, "Dr%d" % i, addr)
                rw = 0b11 if label.startswith("RW ") else 0b01   # read/write or write only
                dr7 |= (1 << (2 * i)) | (rw << (16 + 4 * i))   # local enable, 1 byte
            ctx.Dr7 = dr7
            ctx.Dr6 = 0
            k32.Wow64SetThreadContext(h, ctypes.byref(ctx))
        k32.CloseHandle(h)

    def check_watch(self, tid):
        """Return True if this single-step was a watchpoint hit (and log it)."""
        if not getattr(self, "watch_addrs", None):
            return False
        h = k32.OpenThread(0x1FFFFF, False, tid)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = 0x00010017   # FULL | DEBUG_REGISTERS
        k32.Wow64GetThreadContext(h, ctypes.byref(ctx))
        hit = ctx.Dr6 & 0xF
        if hit:
            for i, (label, addr) in enumerate(self.watch_addrs[:4]):
                if hit & (1 << i):
                    try:
                        val = self.read(addr, 4).hex()
                    except OSError:
                        val = "?"
                    self.watch_hits = getattr(self, "watch_hits", {})
                    self.watch_hits[i] = self.watch_hits.get(i, 0) + 1
                    if self.watch_hits[i] <= 40:
                        chain = []
                        bp = ctx.Ebp
                        for _ in range(10):   # frame-pointer walk: [ebp+4] = return address
                            try:
                                nbp, ret = struct.unpack("<II", self.read(bp, 8))
                            except OSError:
                                break
                            chain.append("%x" % (ret - self.base))
                            if nbp <= bp:
                                break
                            bp = nbp
                        log(f"WATCH {label} accessed: now {val} by rva {ctx.Eip - self.base:#x} (tid {tid}) "
                            f"frames: {' '.join(chain)}")
            ctx.Dr6 = 0
            ctx.ContextFlags = 0x00010010
            k32.Wow64SetThreadContext(h, ctypes.byref(ctx))
        k32.CloseHandle(h)
        return bool(hit)

    def stack_rvas(self, tid, depth=400, limit=24):
        """Return addresses inside the game image found on the thread's stack
        (a cheap call-stack guess for crash diagnosis)."""
        hthread = k32.OpenThread(0x1FFFFF, False, tid)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL
        k32.Wow64GetThreadContext(hthread, ctypes.byref(ctx))
        k32.CloseHandle(hthread)
        out = []
        raw = b""
        for d in (depth, 200, 100, 50, 20, 8):   # the read fails when it runs past the stack's end
            try:
                raw = self.read(ctx.Esp, d * 4); depth = d
                break
            except OSError:
                continue
        if not raw:
            return out
        self.last_regs = "eax=%x ecx=%x edx=%x esi=%x edi=%x ebp=%x esp=%x" % (
            ctx.Eax, ctx.Ecx, ctx.Edx, ctx.Esi, ctx.Edi, ctx.Ebp, ctx.Esp)
        for i in range(depth):
            v = int.from_bytes(raw[i * 4:i * 4 + 4], "little")
            if self.base and self.base + 0x1000 <= v < self.base + 0x1100000:
                out.append(v - self.base)
                if len(out) >= limit:
                    break
        return out

    def recover_breakpoint(self, tid, va):
        try:
            h = k32.OpenThread(0x1FFFFF, False, tid)
            ctx = WOW64_CONTEXT()
            ctx.ContextFlags = WOW64_CONTEXT_FULL
            k32.Wow64GetThreadContext(h, ctypes.byref(ctx))
            self.write(va, self.orig[va])
            ctx.Eip = va
            ctx.EFlags |= 0x100
            k32.Wow64SetThreadContext(h, ctypes.byref(ctx))
            k32.CloseHandle(h)
            self.pending[tid] = va
        except Exception as e:
            log(f"TRACER ERROR recovering breakpoint {va:#x}: {e}")

    def poll_inject(self):
        now = time.time()
        if now - self.inject_checked < 0.5:
            return
        self.inject_checked = now
        if not os.path.exists(INJECT_PATH):
            return
        try:
            lines = open(INJECT_PATH).read().splitlines()
            os.remove(INJECT_PATH)
        except OSError:
            return
        class _C: pass
        c = _C(); c.Base = self.base
        for line in lines:
            p = line.split()
            if not p:
                continue
            try:
                if p[0] in ("poke8", "poke32"):
                    a = self.ev(p[1], c); v = int(p[2], 16)
                    self.write(a, struct.pack("<B" if p[0] == "poke8" else "<I", v))
                    log(f"INJECT {p[0]} {a:#x} = {v:#x}")
                elif p[0] == "watch":
                    # watch <label>|<expr>  (label starting "RW " = read/write)
                    label, expr = line.split(None, 1)[1].split("|", 1)
                    a = self.ev(expr.strip(), c)
                    self.watch_addrs = (getattr(self, "watch_addrs", []) + [(label.strip(), a)])[-4:]
                    for t in list(self.tids):
                        self.set_watches(t)
                    log(f"INJECT watching {label.strip()} at {a:#x}")
                elif p[0] in ("call", "callthis"):
                    # callthis <rva> <ecx expr> [args]: thiscall (callee pops args;
                    # the cave still restores the saved context either way)
                    if p[0] == "callthis":
                        this = self.ev(p[2], c); rest = p[3:]
                    else:
                        this = None; rest = p[2:]
                    self.inject_calls.append((int(p[1], 16), [int(x, 16) for x in rest], this))
                    hv = self.base + INJECT_HOOK_RVA
                    if hv not in self.orig:
                        BREAKPOINTS[INJECT_HOOK_RVA] = ("inject hook (per-frame)", [])
                        self.orig[hv] = self.read(hv, 1)
                        self.write(hv, b"\xCC")
                    log(f"INJECT queued call rva {p[1]} args {p[2:]}")
            except Exception as e:
                log(f"INJECT failed '{line}': {e}")

    def try_inject_call(self, va, hthread, ctx):
        """At the hook breakpoint (function entry, main thread) divert into the
        queued cdecl function with the return address pointing at an int3 cave;
        when the cave traps, the saved context is restored (see run())."""
        if not self.inject_calls or va - self.base != INJECT_HOOK_RVA or self.inject_saved:
            return False
        rva, args, this = self.inject_calls.pop(0)
        saved = WOW64_CONTEXT()
        ctypes.memmove(ctypes.byref(saved), ctypes.byref(ctx), ctypes.sizeof(ctx))
        saved.Eip = va   # the int3 trap left Eip one past the breakpoint
        self.inject_saved = saved
        cave = self.base + INJECT_CAVE_RVA
        esp = ctx.Esp - 0x40 - 4 * (len(args) + 1)   # stay clear of the hook's frame
        self.write(esp, struct.pack("<I", cave) + b"".join(struct.pack("<I", a) for a in args))
        ctx.Esp = esp
        ctx.Eip = self.base + rva
        if this is not None:
            ctx.Ecx = this
        k32.Wow64SetThreadContext(hthread, ctypes.byref(ctx))
        k32.CloseHandle(hthread)
        log(f"INJECT calling rva {rva:#x} args {[hex(a) for a in args]}")
        return True

    def finish_inject_call(self, tid):
        hthread = k32.OpenThread(0x1FFFFF, False, tid)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL
        k32.Wow64GetThreadContext(hthread, ctypes.byref(ctx))
        log(f"INJECT call returned eax={ctx.Eax:#x}")
        k32.Wow64SetThreadContext(hthread, ctypes.byref(self.inject_saved))
        k32.CloseHandle(hthread)
        self.inject_saved = None

    def on_breakpoint(self, tid, va):
        hthread = k32.OpenThread(0x1FFFFF, False, tid)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL
        k32.Wow64GetThreadContext(hthread, ctypes.byref(ctx))
        self.poll_inject()
        if self.try_inject_call(va, hthread, ctx):
            return
        if va - self.base == 0x20aed0 and HACK_PLACE_PLAYER and not getattr(self, "placed", False):
            # STOPGAP: the server's position (0xB0) is queued in the motion
            # component but the entity is never placed in the world, so write the
            # spawn position straight into the physics object's Position (+0x7c:
            # +4 region, +8 landblock x, +9 y, +0xa cell) -- that is what made the
            # map start streaming in. ecx = motion component + 0x10.
            try:
                comp = ctx.Ecx - 0x10
                ent = struct.unpack("<I", self.read(comp + 4, 4))[0]
                phys = struct.unpack("<I", self.read(ent, 4))[0]
                self.write(phys + 0x80, struct.pack("<I", 1))
                self.write(phys + 0x84, bytes([0x13, 0xCB]) + struct.pack("<H", 0))
                self.placed = True
                log(f"HACK placed player physics object {phys:#x} (entity {ent:#x}) at region 1 landblock 13cb")
            except OSError as e:
                log(f"HACK place failed: {e}")
        name, fields = BREAKPOINTS[va - self.base]
        n = self.counts[va] = self.counts.get(va, 0) + 1
        if n <= (4000 if name == 'SCRIPT CALL' else 3000 if name.startswith('HOT ') else 400 if name.startswith(('PACK LOAD', 'UI state')) else 100):
            parts = []
            for label, expr in fields:
                try:
                    v = self.ev(expr, ctx)
                    if label.startswith("@"):
                        # dynamic breakpoint: plant one at the evaluated address
                        if v not in self.orig:
                            BREAKPOINTS[v - self.base] = DYNAMIC[label]
                            self.orig[v] = self.read(v, 1)
                            self.write(v, b"\xCC")
                            parts.append(f"planted {label} at rva {v - self.base:#x}")
                        continue
                    parts.append(f"{label}={v}" if isinstance(v, str) else f"{label}={v:#x}")
                except (OSError, ValueError):
                    parts.append(f"{label}=?")
            ret = "?"
            try:
                ret = f"{struct.unpack('<I', self.read(ctx.Esp, 4))[0] - self.base:#x}"
            except OSError:
                pass
            line = f"[{va - self.base:#08x}] {name} {' '.join(parts)} (tid {tid}, ret rva {ret})"
            if name.startswith("STACK "):
                line += " stack: " + " ".join("%x" % r for r in self.stack_rvas(tid))
            if name == "SCRIPT CALL" and any(x in line for x in NOISY_SCRIPT_CALLS):
                self.counts[va] -= 1   # constant UI chatter: don't log, don't use up the budget
            else:
                log(line + (" -- further hits muted" if n == 100 else ""))
        # step over the original instruction, then re-arm
        self.write(va, self.orig[va])
        ctx.Eip = va
        ctx.EFlags |= 0x100
        k32.Wow64SetThreadContext(hthread, ctypes.byref(ctx))
        k32.CloseHandle(hthread)
        self.pending[tid] = va

    def run(self):
        if not k32.DebugActiveProcess(self.pid):
            raise OSError(f"DebugActiveProcess failed: {ctypes.get_last_error()}")
        k32.DebugSetProcessKillOnExit(False)
        ev = DEBUG_EVENT()
        armed = False
        try:
            while True:
                got = k32.WaitForDebugEvent(ctypes.byref(ev), 500)
                now = time.time()
                if now - getattr(self, "stop_checked", 0) > 0.5:
                    self.stop_checked = now
                    if os.path.exists(STOP_PATH) and not got:
                        os.remove(STOP_PATH)
                        log("stop file seen, detaching")
                        return
                    if os.path.exists(STOP_PATH):
                        self.stop_requested = True
                if not got:
                    continue
                status = DBG_CONTINUE
                code = ev.dwDebugEventCode
                if code == CREATE_PROCESS_DEBUG_EVENT:
                    k32.CloseHandle(ev.u.CreateProcessInfo.hFile)
                    self.tids.add(ev.dwThreadId)
                elif code == CREATE_THREAD_DEBUG_EVENT:
                    self.tids.add(ev.dwThreadId)
                    if armed:
                        self.set_watches(ev.dwThreadId)
                elif code == EXIT_THREAD_DEBUG_EVENT:
                    self.tids.discard(ev.dwThreadId)
                elif code == LOAD_DLL_DEBUG_EVENT:
                    k32.CloseHandle(ev.u.LoadDll.hFile)
                elif code == EXIT_PROCESS_DEBUG_EVENT:
                    log("game process exited")
                    return
                elif code == EXCEPTION_DEBUG_EVENT:
                    rec = ev.u.Exception.ExceptionRecord
                    exc, addr = rec.ExceptionCode, rec.ExceptionAddress or 0
                    if exc in BREAKPOINTS_CODES:
                        if not armed:
                            self.arm()   # initial attach breakpoint
                            armed = True
                        elif self.inject_saved and addr == self.base + INJECT_CAVE_RVA:
                            self.finish_inject_call(ev.dwThreadId)
                        elif addr in self.orig:
                            try:
                                self.on_breakpoint(ev.dwThreadId, addr)
                            except Exception:
                                # never leave the thread parked after the int3: an
                                # escaping error used to kill the tracer and then
                                # the game (Eip one past a breakpoint byte).
                                import traceback
                                log("TRACER ERROR in on_breakpoint: " + traceback.format_exc().replace("\n", " | "))
                                self.recover_breakpoint(ev.dwThreadId, addr)
                    elif exc in SINGLE_STEP_CODES and (ev.dwThreadId in self.pending
                                                       or self.check_watch(ev.dwThreadId)):
                        if ev.dwThreadId in self.pending:
                            self.check_watch(ev.dwThreadId)
                            self.write(self.pending.pop(ev.dwThreadId), b"\xCC")
                    elif exc == 0x406D1388:
                        # MS_VC_EXCEPTION (SetThreadName): only raised because a
                        # debugger is attached and must be swallowed by it -- passing
                        # it back crashed the game when Play started a new thread.
                        status = DBG_CONTINUE
                    else:
                        if ev.u.Exception.dwFirstChance and self.exc_logged < 30:
                            self.exc_logged += 1
                            extra = ""
                            if exc == 0xE06D7363:   # MSVC C++ throw: name the thrown type
                                try:
                                    info = (rec.ExceptionInformation[2] or 0) & 0xFFFFFFFF
                                    u = lambda a: int.from_bytes(self.read(a, 4), "little")
                                    ct = u(u(u(info + 0xc) + 4) + 4)
                                    extra = " type " + self.read(ct + 8, 80).split(b"\0")[0].decode("ascii", "replace")
                                except Exception as e:
                                    extra = f" type ? ({e})"
                            log(f"first-chance exception {exc:#x}{extra} at rva {addr - (self.base or 0):#x}, "
                                f"stack rvas: {' '.join('%x' % r for r in self.stack_rvas(ev.dwThreadId))}"
                                f" | {getattr(self, 'last_regs', '')} tid {ev.dwThreadId}")
                        if not ev.u.Exception.dwFirstChance:
                            log(f"UNHANDLED exception {exc:#x} at {addr:#x} "
                                f"(rva {addr - (self.base or 0):#x})")
                        status = DBG_EXCEPTION_NOT_HANDLED
                k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, status)
                if getattr(self, "stop_requested", False) and not self.pending and not self.inject_saved:
                    os.remove(STOP_PATH)
                    log("stop file seen, detaching")
                    return
        finally:
            self.disarm()
            k32.DebugActiveProcessStop(self.pid)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    pid = find_pid(PROCESS_NAME)
    if not pid:
        sys.exit(f"{PROCESS_NAME} is not running")
    log(f"===== tracer start, pid {pid}")
    try:
        Tracer(pid).run()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        log("TRACER CRASH: " + traceback.format_exc().replace("\n", " | "))
        raise
