"""Diagnostics inside the running game (Windows only).

Uses the debugger tools\\tracer.py (from the earlier project) and
writes everything to logs\\diag.log.

What it watches:

  Skills (default)
    The "+" button calls GM_Advancement.SendQuery_InqCanRankSkill. Inside the
    exe that query only gets an answer if a game script registered a handler
    for it (id 0x10000063). With no handler, the answer is left with a garbage
    error and the UI never sends RankSkill: exactly what is observed (the "+"
    shows up but does nothing).
    This diagnostic logs:
      - every handler the scripts register while the match loads
        (that is why it must be started BEFORE clicking Launch),
      - whether the query finds a handler and which error it returns,
      - whether the UI gets as far as sending RankSkill.

  Walking (--walk)
    The movement component's maximum speed (+0x2d0), which caps the walking
    animation.

Options (the old Spanish spellings still work: --caminar, --arreglar, ...):
    --walk        also watch the walking animation
    --walk-only   only the walking diagnostic (no skills)
    --fix         set the maximum speed to 7.0 if it is 0 (with --walk)
    --hfsm        log whether the skill state machine (HFSM) is running
    --scripts     log when the game receives orders to start scriptlets (skills)
                  and errors while building objects (that part alone: --entities)
    --packs       log every data pack (.rp) the game tries to load, whether it fails,
                  and the table of pack "slots" per category
    --ranks       log the skill-rank queries that go through the patched exe's caves,
                  whether property 0x100006C1 is read and which rank/recommended the HUD
                  ends up using per slot
    --q           log every attack/skill order the client builds (when pressing Q), whether
                  it rejects it and whether it sends it to the server
    --stolen      the Stolen Power on D (skill slot 7): whether the HUD reads its skill, what
                  the D button gets, and how far pressing D gets (execution, order, packet)
    --props       when loading ends, write the client's whole property descriptor table to
                  logs\\props.txt (id, raw descriptor bytes, names): it tells the value kind of
                  every property, e.g. the Stolen Power slot 0x100008F0 the D button needs
    --fog         log whether the game updates the fog of war (vision range) and what stops it,
                  and whether it gets as far as DRAWING it (vision sources, texture, draw filters)
    --team        3 s into the match, set the game's LOCAL team to 1 (Batman's):
                  without it every object counts as an enemy and does not show on the minimap
    --notes       log why a ping / marker / Batman does or does not show on the minimap
    --minimap     log whether the minimap's map reaches the HUD and, 8 s and 25 s into the
                  match, ask the game to load it (what the player's property 0x100001D3
                  would do): if the minimap stops being green, we know the fix
    --create      log every object the game creates: class, whether it has an initial
                  position, its components' result and whether the position was applied (vehicle)
    --place       log the FIRST physical placement of each object (PhysicsComponent::SetPosition)
                  with the first bytes of its position, to see whether the vehicle gets placed
    --started     when loading finishes, mark the match as "started" (what event 0x2053
                  would do), so the game starts its match systems
    --reward      the Champion Unlocked ribbon chain at the end page (0x212E/0x2124/0x2125)
    --replay      playing again in the same login: local player id, loading steps, timeouts
    --force       make the InqCanRankSkill query answer "no error"
                  to see whether the game sends RankSkill to the server

Usage:
    1. Open the game and stay in the menu (without entering the match).
    2. In another console:  python tools\\diag.py --walk --force
    3. Play Tutorial 1 up to the "+", click it two or three times and walk a bit.
    4. Ctrl+C in the diagnostic's console and send me logs\\diag.log and logs\\unhandled.log.
"""
import ctypes
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from icserver import config as config_mod   # noqa: E402

# --- skills (rva = virtual address - 0x400000)
RVA_REGISTER = 0x4788B0       # registration of a script handler: (id, function)
RVA_QUERY = 0x524B5D          # GM_Advancement.SendQuery_InqCanRankSkill reached the exe
RVA_QUERY_LIST = 0x50E86E     # esi = list of InqCanRankSkill handlers (0 = none)
RVA_QUERY_RESULT = 0x524BCF   # al = was there a handler?, [ebp+0xc] = eError returned to the UI
RVA_NOTICE = 0x52455D         # the UI's rank query (InqSkillRank), native rva 0x524500
RVA_NOTICE_LIST = 0x50E5AE    # esi = list of InqSkillRank handlers
RVA_RANKSKILL = 0x524F1A      # the UI actually sends RankSkill (native rva 0x524e80)
RVA_LOAD_DONE = 0x68EA40      # end of loading: "match started" branch if [[0x1777068]+0x4bc] != 0

ADVANCEMENT_IDS = {
    0x10000009: "Query InqXPForLevel",
    0x10000011: "Notice SkillRanked",
    0x10000054: "Query InqSkillRank",
    0x10000063: "Query InqCanRankSkill",
    0x1000006A: "Notice RankSkill",
    0x1000009B: "Query InqNextRecommendedSkillToRank",
    0x1000023C: "Notice ShowExperienceRings",
    0x10000302: "Query InqSkillPointsAvailableString",
    0x10000423: "Notice XPGained",
    0x100004F7: "Query InqLevelCap",
}

# --- data packs
RVA_PACK_LOAD = 0x5DD120      # loads a pack by id: [esp+4] = id, ecx = manager
RVA_PACK_OPENED = 0x5DD186    # after opening the file: eax < 0 = could not be opened
RVA_PACK_FAILED = 0x5DD1CA    # no free slot for the pack's category (or category -1)

# --- physical placement (previous project's tracer.py: PhysicsComponent::SetPosition)
RVA_SET_POSITION = 0x171AF0
PROP_SPOTS = ((43.66, 52.61), (54.05, 44.80), (12.5, 60.0), (15.0, 56.5), (24.0, 66.0), (30.0, 55.0))

# --- object factory step 3: (rva of the "test" after each component creator) -> (creator, register)
COMPONENT_CHECKS = {r - 0x400000: (c - 0x400000, "ecx") for r, c in (
    (0x606435, 0x6045a0), (0x60646a, 0x604610), (0x60647c, 0x604680), (0x60648e, 0x6046f0),
    (0x6064a0, 0x604760), (0x6064b2, 0x6047d0), (0x6064c4, 0x604840), (0x6064da, 0x6048b0),
    (0x60650b, 0x604990), (0x60653b, 0x604a70), (0x606551, 0x604ae0), (0x606574, 0x604b50),
    (0x60658a, 0x604bc0), (0x6065a0, 0x604c30), (0x6065b6, 0x604ca0), (0x6065cc, 0x604d10),
    (0x6065ee, 0x604d80), (0x60661c, 0x604df0), (0x60663f, 0x604e60), (0x606662, 0x604ed0))}
COMPONENT_CHECKS.update({r - 0x400000: (c - 0x400000, "eax") for r, c in (
    (0xa9d7ec, 0xa9d1f0), (0xa9d82a, 0xa9d260), (0xa9d842, 0xa9d2d0), (0xa9d878, 0xa9d340),
    (0xa9d8ab, 0xa9d3b0), (0xa9d8dc, 0xa9d420), (0xa9d8f4, 0xa9d490), (0xa9d90c, 0xa9d500),
    (0xa9d936, 0xa9d570), (0xa9d972, 0xa9d5e0), (0xa9d986, 0xa9d650), (0xa9d9a0, 0xa9d6c0))})

# --- walking
RVA_WALK_ENTRY = 0x2097E0
RVA_WALK_CLAMP = 0x2098F6     # movss xmm0, [eax+0x2d0]   (eax = movement component)
RVA_WALK_RESULT = 0x20991F
MAX_SPEED_FIX = 7.0

# --- local team written by --team
TEAM_POKE = 1

# --- minimap: Tutorial 1 encounter
MINIMAP_ENCOUNTER = 0x40000991


# Old Spanish flag spellings, still accepted (users have scripts that use them).
FLAG_ALIASES = {
    "--caminar": "--walk",
    "--arreglar": "--fix",
    "--forzar": "--force",
    "--iniciada": "--started",
    "--solo-caminar": "--walk-only",
    "--entidades": "--entities",
    "--rangos": "--ranks",
    "--niebla": "--fog",
    "--equipo": "--team",
    "--notas": "--notes",
    "--minimapa": "--minimap",
    "--crear": "--create",
    "--colocar": "--place",
    "--finpartida": "--matchend",
}


def main():
    sys.argv[:] = [FLAG_ALIASES.get(a, a) for a in sys.argv]
    if os.name != "nt":
        sys.exit("This diagnostic only works on Windows, with the game open.")
    walk = "--walk" in sys.argv
    fix = "--fix" in sys.argv
    force = "--force" in sys.argv
    started = "--started" in sys.argv
    skills = "--walk-only" not in sys.argv

    cfg = config_mod.load()
    # the debugger (tracer.py) now lives in tools\; [debug] old_server_dir
    # still overrides it with the earlier project's copy
    old = cfg["debug"].get("old_server_dir") or ""
    here = os.path.dirname(os.path.abspath(__file__))
    src = old if old and os.path.isfile(os.path.join(old, "tracer.py")) else here
    if not os.path.isfile(os.path.join(src, "tracer.py")):
        sys.exit(f"Can't find tracer.py in {here}")
    sys.path.insert(0, src)
    import tracer as T

    os.makedirs(cfg.log_dir, exist_ok=True)
    T.LOG_PATH = os.path.join(cfg.log_dir, "diag.log")
    T.STOP_PATH = os.path.join(cfg.log_dir, "diag.stop")
    T.INJECT_PATH = os.path.join(cfg.log_dir, "diag.inject")
    T.WATCHES = []
    T.HACK_PLACE_PLAYER = False
    bps = {}
    if "--hfsm" in sys.argv:
        # gmHFSMComponent update (rva 0x577b30, profiler scope "gmHFSMComponent"):
        # the champion's skill state machine (data 0x3a000052 for Gaslight Batman).
        bps[0x577B30] = ("HOT hfsm", [("component", "ecx")])
    if "--scripts" in sys.argv or "--entities" in sys.argv:
        # WorldEntityFactory error paths (the client builds an object from its
        # world state; when that fails the object never shows up). Each hit is
        # an object the server created that the client could not build.
        regs = [("eax", "eax"), ("ebx", "ebx"), ("ecx", "ecx"), ("edx", "edx"), ("esi", "esi"), ("edi", "edi")]
        for rva, what in ((0x14AE42, "BuildCreationInfoFromEntityDesc"),
                          (0x14B706, "GetWorldEntityCreationInfo"),
                          (0x14F3C2, "entity WITHOUT a world state (edi = entity)"),
                          (0x14F585, "step 1 (IID)"), (0x14F5EA, "step 2 (record)"),
                          (0x14F6AF, "step 3 (components)"), (0x14F708, "step 4 (messages)"),
                          (0x14F762, "step 5 (construction)"), (0x14F7B8, "step 6 (finalize)")):
            bps[rva] = (f"STACK ERROR creating object: {what}", regs)
        # every object built from a world state: edi = world state, eax = parent .entity
        bps[0x14F3F6] = ("object built", [("entity", "edi"), ("world_state", "eax")])
        # step 3 (components): the client factory (rva 0x69d7a0) and the shared one
        # (rva 0x206400) create one component each; only a failure (HRESULT < 0) is logged
        for rva, (creator, reg) in COMPONENT_CHECKS.items():
            bps[rva] = (f"component {creator:#x}", [(reg, reg)])
        # patched exe: class 0x4F... = prop without an entity (vehicle, meteor) -> Gate + its state
        bps[0x997F6F] = ("PROP received (cave X)", [("class", "eax")])
        bps[0x14F32B] = ("ERROR: the carrier entity is not in the loaded packs", [("entity", "edi")])
        # the component that fails for the vehicle (creator rva 0x204760 -> init rva 0x1693a0):
        # which .entity it resolves from the class, the creation type, and its result
        # (only for our props: the map builds ~100 objects with it during loading)
        for rva in (0x1693BA, 0x1693FB, 0x16940D):
            bps[rva] = ("HOT component 0x204760", [])
    if "--scripts" in sys.argv:
        # CScriptComponent::OnSync (rva 0x227c70): the server's "start / stop
        # scriptlet" orders for an entity. The stack shows which network event
        # delivers them; [arg+0xd0] = number of orders.
        bps.update({
            0x227C70: ("STACK script sync", [("arg", "[esp+4]"), ("orders", "[[esp+4]+d0]")]),
            0x2279D0: ("STACK start scriptlet", [("did", "[esp+8]"), ("instance", "[esp+c]")]),
            0x2278D0: ("STACK scriptlet op1", [("did", "[esp+8]"), ("x", "[esp+c]")]),
            # Event 0x8D (the server's "run scriptlet" order) reached the entity.
            0x227E20: ("order 0x8d received", [("orders", "[[esp+8]+8]"),
                                                  ("local_id", "[base+176a710]")]),
            # Result of each order: 0 = started, 1 = skipped (same originator),
            # 0x80070057 = not a scriptlet DID, 0x8000ffff = entity has no script context.
            0x227E97: ("order result", [("result", "[ebp+c]")]),
            # The DID check (rva 0x1235c0) against the entity's table of allowed
            # scriptlets (script component +0x3c): the table is listed in full.
            0x227A23: ("allowed scriptlets table", [("did", "esi")]),
            0x227A28: ("scriptlet allowed?", [("al", "eax")]),
        })
    if "--packs" in sys.argv:
        # Resource packs (rp\\0x%08x.rp). 0x9dd120 loads one pack by id: it opens
        # the file (0x9da330), reads the header's category (word 1) and takes a
        # free slot of that category (0x9d3400); no free slot = the pack is
        # silently not loaded. ecx = pack manager: [+4] slots of 0x28 bytes
        # (+0x14 category, +0x1c loaded pack id or -1), [+0xc] slot count.
        bps.update({
            RVA_PACK_LOAD: ("PACK LOAD requested", [("pack", "[esp+4]")]),
            RVA_PACK_FAILED: ("PACK LOAD FAILED (no free slot or could not be opened)",
                              [("pack", "edi"), ("category", "[ebp+fffffc04]")]),
            RVA_PACK_OPENED: ("pack opened", [("pack", "edi"), ("result", "eax"),
                                               ("category", "[ebp+fffffc04]")]),
            0x5DB236: ("RP ERROR: the requested pack was not found", [("pack", "[edi+1c]")]),
            0x609E50: ("ResourcePackLoader: LoadParentRPs", []),
            0x609F90: ("ResourcePackLoader: LoadMatchData", []),
            0x60A1E0: ("ResourcePackLoader: lobby", []),
            0x60A050: ("STACK ResourcePackLoader: load request", [("count", "[[esp+4]+8]"),
                                                                     ("first", "[[[esp+4]]]")]),
        })
    if "--ranks" in sys.argv:
        # Skill ranks through the patched exe's caves (patcher.py): what the rank
        # queries ask, whether the champion is found and the property 0x100006C1
        # read, and what the HUD's skill loop ends up with per slot.
        bps.update({
            0x5E7939: ("rank: query (cave A)", [("iid_lo", "[ebp+8]"), ("iid_hi", "[ebp+c]"),
                                                       ("slot", "[ebp+10]"), ("output", "[[ebp+14]]")]),
            0x5E7943: ("rank: local champion", [("agent", "eax"), ("iid_lo", "[eax+100]"), ("iid_hi", "[eax+104]")]),
            0x7369E5: ("rank: property 0x100006C1 (cave B)", [("read", "eax"), ("value", "[esp]")]),
            0x725A8B: ("rank: recommended, property (cave C)", [("read", "eax"), ("value", "edx")]),
            0x71F97A: ("can rank up? property (cave E)", [("read", "eax"), ("value", "edx"),
                                                               ("slot", "[ebp+10]")]),
            0xFAAFC6: ("HUD: the property changed, refresh skills (cave D)", [("value", "edx")]),
            0x67C8B6: ("HUD skill: rank", [("slot", "edi"), ("rank", "[ebp+ffffffe8]")]),
            0x67C8CD: ("HUD skill: recommended", [("slot", "edi"), ("recommended", "[ebp+ffffffe0]")]),
            0x639D60: ("HUD skill: mark for refresh", [("slot", "[esp+4]"), ("flag", "[esp+8]")]),
        })
    if "--q" in sys.argv:
        # Using a skill (Q): the client's command sender (rva 0x670030; the order
        # goes out as event 0x20EE through rva 0x48b030). Shows whether pressing Q
        # reaches it, which ability number it carries, and where it is refused.
        bps.update({
            0x670030: ("skill/attack order", [("command", "[esp+8]"), ("ability", "[esp+c]"),
                                                     ("target_lo", "[[esp+10]]")]),
            0x670045: ("...order REJECTED by the client", []),
            0x670072: ("...can act? (0x5cfaf0)", [("al", "eax")]),
            0x6700B1: ("...does the ability accept a target? (0x461850)", [("al", "eax")]),
            0x48B030: ("order SENT to the server (0x20ee)", [("command", "[esp+8]"), ("ability", "[esp+c]")]),
        })
    if "--stolen" in sys.argv:
        # The Stolen Power on D (skill slot 7, Secondary1). Shows whether the HUD
        # refresh reads its skill (property 0x100008F0 through VA 0x85d1c0), what
        # the HUD gets for it (SkillUpdate, VA 0x8f7870: icon, rank, "can be
        # activated"), and, when D is pressed or the button clicked, how far the
        # order gets (aimed-skill execution VA 0xa75d20, its targeting type, the
        # command sender VA 0xa70030 and the packet to the server).
        bps.update({
            0x45D1C0: ("HOT skill of slot (0x85d1c0)", [("slot", "[esp+8]")]),
            0x45D1E8: ("HOT ...skill of slot found?", [("al", "eax")]),
            0x4F7870: ("HOT HUD SkillUpdate", [("slot", "[esp+4]"), ("icon", "[esp+1c]"), ("rank", "[esp+20]"),
                                               ("can_activate", "[esp+24]"), ("can_rank_err", "[[esp+2c]]")]),
            0x675D20: ("aimed skill: execute", [("arg", "[esp+4]"), ("aimed", "[ecx+ec]")]),
            0x675D3D: ("...targeting type of the skill (0x85f6f0)", [("type", "eax")]),
            0x670030: ("skill/attack order", [("command", "[esp+8]"), ("ability", "[esp+c]")]),
            0x670045: ("...order REJECTED by the client", []),
            0x48B030: ("order SENT to the server (0x20ee)", [("command", "[esp+8]"), ("ability", "[esp+c]")]),
        })
    if "--fog" in sys.argv:
        # Fog of war (CFogOfWarComponent update, rva 0x6b3520): who owns one, and
        # which check stops it (no owner / no valid position / game state 7).
        bps[0x6B3520] = ("HOT fog: update", [("component", "ecx")])
        bps[0x6B355A] = ("HOT fog: owner position", [("pos", "eax"), ("valid", "[eax+4]"),
                                                           ("cell", "[eax+8]")])
        bps[0x6B359C] = ("HOT fog: game state (7 = does not update)", [("state", "eax")])
        bps[0x6B35A1] = ("HOT fog: UPDATING", [("component", "esi")])
        # what the update computes and draws (2026-10-14: it updates, but the
        # area out of sight stays clear): vision sources (stride 0x60, radius +0x40)
        bps[0x6AE0E0] = ("HOT fog: vision sources", [("component", "ecx"), ("count", "[ecx+188]")])
        bps[0x6AE16B] = ("HOT fog: source", [("radius_f32", "[esi+40]"), ("x_f32", "[esi+34]"),
                                                 ("y_f32", "[esi+38]")])
        bps[0x6A5074] = ("HOT fog: fog texture (re)created", [("component", "esi"),
                                                                     ("texture", "[esi+a8]")])
        bps[0x6AE5B0] = ("HOT fog: draw", [("component", "ecx"), ("texture", "[ecx+a8]"),
                                                 ("f8", "[ecx+f8]")])
        bps[0x6AE65B] = ("HOT fog: DRAWS (passed the first filter)",
                         [("WorldRender_Fog_38_39_3a", "[[[base+1773518]+dc]+38]"),
                          ("map", "[[base+17758f4]+70]")])
        bps[0x6AE7C9] = ("HOT fog: darken? (low byte 1 = yes; 0 = the champion sees everything)",
                         [("flag", "[ebp+b]")])
        bps[0x6AE8C5] = ("HOT fog: camera cell", [("info", "[ebp+ffffff70]"),
                                                            ("bytes", "[ebp+ffffff74]"), ("world", "ebx")])
        bps[0x6AE900] = ("HOT fog: valid cell", [])
        bps[0x6AE97A] = ("HOT fog: draw textures", [("t1", "edi"), ("t2", "eax")])
    if "--team" in sys.argv:
        bps.setdefault(0x6B35A1, ("HOT fog: UPDATING", [("component", "esi")]))
    if "--notes" in sys.argv:
        # Minimap notes (pings, markers, Batman): the map manager gets every new
        # entity (rva 0x65a510 -> filter 0x188e40 -> note reader 0x64b150), which
        # needs "show on the map" 0x100007D8 at that moment, a team that is not
        # an enemy's, and then adds the note (icon, category, variant).
        bps[0x65A510] = ("HOT notes: new entity", [("iid_lo", "[esp+4]"), ("iid_hi", "[esp+8]")])
        bps[0x65A53B] = ("HOT notes: eligible? (al)", [("al", "eax"), ("entity", "esi"),
                                                     ("iid_lo", "[esi+100]")])
        bps[0x64B18F] = ("HOT notes: show on the map (low byte)", [("show", "[ebp+b]"),
                                                                       ("other", "[ebp+ffffffff]"),
                                                                       ("iid_lo", "[esi+100]")])
        # to the HUD: a new note goes out through rva 0x4b4dc0 (Flash
        # GM_MapManager.*); it gives up when the HUD movie is missing (0x4b4e32,
        # [ebp-0x24] = 0) or the note list is not found (0x4b4e6d, eax = 0).
        # Positions go every frame through UpdateMapNotes (rva 0x4f5610).
        bps[0x4B4DC0] = ("HOT notes: note sent to the HUD", [("iid_lo", "[esp+4]"), ("icon", "[esp+18]")])
        bps[0x4B4E2F] = ("HOT notes: HUD (0 = no movie, not drawn)", [("movie", "[ebp+ffffffdc]")])
        bps[0x4B4E6D] = ("HOT notes: HUD note list (0 = not found)", [("list", "eax")])
        # the per-frame note updater (rva 0x66a7c0 -> 0x65bc50): it stops when
        # the local player's 0x100000CF agent is not found (0x65bc67, eax = 0);
        # else walks its list ([ebx+0x48], count [ebx+0x50], entity iid +0x30)
        bps[0x66A7C0] = ("HOT notes: note manager tick (needs map=1 and delivered=1)",
                         [("map", "[ecx+6c]"), ("delivered", "[ecx+c8]")])
        bps[0x65BC67] = ("HOT notes: local agent for the minimap (0 = none, it stops)", [("agent", "eax")])
        bps[0x65BC71] = ("HOT notes: tracking list", [("count", "[ebx+50]")])
        bps[0x65BD27] = ("HOT notes: tracking", [("type", "[esi+48]"), ("iid_lo", "[esi+30]")])
        bps[0x4F5610] = ("HOT notes: UpdateMapNotes (positions to the HUD)", [("a", "[esp+4]"), ("b", "[esp+8]")])
        bps[0x64B323] = ("HOT notes: reading the object's team (al=1 read; type 0x10 = int)",
                         [("al", "eax"), ("type", "[[ebp+ffffffd8]+c]"), ("value", "[ebp+ffffffdc]"),
                          ("local_team", "[[base+1777068]+bc]"), ("iid_lo", "[esi+100]")])
        bps[0x64B34F] = ("HOT notes: relation (2 = enemy, not drawn)", [("relation", "eax"),
                                                                            ("iid_lo", "[esi+100]")])
        bps[0x64B370] = ("HOT notes: NOTE (0 = new, otherwise = update)", [("existing", "eax"), ("icon", "[ebp+fffffff4]"),
                                                     ("category", "ebx"), ("variant", "[ebp+8]"),
                                                     ("iid_lo", "[esi+100]")])
    if "--minimap" in sys.argv:
        # Minimap image: the map manager M = [[0x17758d4]+0x50] (vtable rva
        # 0x1203a9c) turns the encounter DID into the map image (rva 0x64c2c0,
        # thiscall, 1 arg) and gives it to the HUD (DeliverMapData, rva 0x49f4c0).
        # Normally a change of the local player's property 0x100001D3 triggers it.
        bps[0x64C2C0] = ("map: encounter -> minimap image", [("encounter", "[esp+4]"), ("M", "ecx")])
        bps[0x49F4C0] = ("map: DeliverMapData to the HUD", [("image", "[esp+4]")])
        bps[0x60D810] = ("map: re-deliver to the HUD", [("loaded", "[ecx+54]"), ("image", "[ecx+58]")])
        bps.setdefault(0x6B35A1, ("HOT fog: UPDATING", [("component", "esi")]))
    if "--create" in sys.argv:
        # Object creation (rva 0x14f540): the vehicle sent as its bare world state
        # builds every component (diag 2026-10-14 15:27) but is never placed.
        # info = creation info ([info+30] = class), pos = initial position (null =
        # the object is never placed), then the component step's result.
        bps[0x14F565] = ("HOT create object", [("info", "ebx"), ("class", "[ebx+30]"), ("pos", "[ebp+10]"),
                                              ("arg4", "[ebp+14]"), ("arg5", "[ebp+18]")])
        bps[0x14F634] = ("HOT components created", [("result", "eax"), ("object", "esi"), ("pos", "[ebp+10]")])
        bps[0x14F65E] = ("HOT initial position applied", [("object", "esi"), ("pos", "eax")])
    if "--matchend" in sys.argv:
        # The end of a match (static analysis 2026-10-15, VA = rva + 0x400000):
        # who makes the client leave the world, the connection status codes,
        # and the flags that gate loading the next match.
        bps.update({
            0x6809E0: ("NotifyMatchEnded reached the end page", []),
            0x699B60: ("STACK LEAVE WORLD (teardown, then event 0x12d)", [("ret", "[esp+0]")]),
            0x69BCD0: ("connection status", [("code", "[esp+4]"), ("a", "[esp+8]"), ("b", "[esp+c]")]),
            0x6B52A0: ("STACK address/port check (may leave)", [("ret", "[esp+0]")]),
            0x6BC480: ("exit lobby (0x2021) received", [("room", "[esp+4]")]),
            0x699E20: ("world load check", [("flags70", "[[base+17763c0]+70]"),
                                            ("flags68", "[[base+17763c0]+68]")]),
            0x699F00: ("0x20AF (enter match) handler", [("flags70", "[[base+17763c0]+70]")]),
            0x691BF0: ("end-of-match stats (0x2045) received", []),
            0x6795E0: ("end page fill (0xa795e0)", []),
            0x6724A0: ("post-match movie lookup", [("encounter", "[esp+4]")]),
        })
    if "--reward" in sys.argv:
        # The Champion Unlocked ribbon (static analysis 2026-10-15): end page asks
        # 0x212E -> server 0x211F -> UI asks 0x2124 -> server 0x2125 -> RewardSetsData.
        bps.update({
            0x67EBB0: ("reward: 0x2125 arrived", [("count", "[[esp+8]+8]")]),
            0x67ED01: ("reward: item type (7 = champion)", [("type", "eax")]),
            0x641300: ("reward: to the UI (RewardSetsData)", [("set", "[[esp+4]]"), ("source", "[[esp+4]+4]")]),
            0x634900: ("reward: UI asks for achievement banners", [("table", "[ecx+c]")]),
            0x68B7F0: ("reward: 0x211F received", []),
            0x60B3E0: ("reward: UI asks for pending rewards (0x2124)", []),
            0x6411D0: ("reward: claimed (Continue)", [("a", "[esp+4]"), ("b", "[esp+8]")]),
            0x613070: ("reward: showcase movie lookup", [("achievement", "[esp+4]")]),
        })
    if "--replay" in sys.argv:
        # Playing again in the same login (static analysis 2026-10-15).
        bps.update({
            0x235250: ("replay: set local player id", [("id", "q[esp+4]"), ("ret", "[esp+0]")]),
            0x3D14B0: ("replay: world reset (teardown)", [("ret", "[esp+0]")]),
            0x6964B0: ("replay: loading step", [("add", "[esp+4]"), ("ret", "[esp+0]"),
                                                ("room", "[[base+1777068]+4bc]")]),
            0x696A60: ("replay: local player arrived", []),
            0x69B134: ("replay: 0x2016 watchdog fired", [("ret", "[esp+0]")]),
            0x69ACA7: ("replay: 60 s without server updates", [("ret", "[esp+0]")]),
            0x69A040: ("replay: disconnect with error", [("ret", "[esp+0]")]),
        })
    if "--place" in sys.argv:
        bps[RVA_SET_POSITION] = ("SetPosition (only the first 100)", [])
    if started:
        # Mark the match "started" while it loads (first pack of the match).
        bps.setdefault(RVA_PACK_LOAD, ("PACK LOAD requested", [("pack", "[esp+4]")]))
    if skills:
        bps.update({
            RVA_REGISTER: ("HOT handler registration", [("id", "[esp+4]")]),
            RVA_QUERY: ("InqCanRankSkill query from the + button", []),
            RVA_QUERY_LIST: ("InqCanRankSkill handlers", [("list", "esi")]),
            RVA_QUERY_RESULT: ("InqCanRankSkill answer", [("had_handler", "eax"),
                                                              ("eError", "[ebp+c]")]),
            RVA_NOTICE: ("the UI queries the rank (InqSkillRank)", []),
            RVA_NOTICE_LIST: ("InqSkillRank handlers", [("list", "esi")]),
            RVA_RANKSKILL: ("the UI sends RankSkill", [("slot", "eax")]),
            RVA_LOAD_DONE: ("end of loading (match started branch)", [("started", "[[base+1777068]+4bc]")]),
        })
    if walk:
        bps.update({
            RVA_WALK_ENTRY: ("HOT walk: animation", [("entity", "[esp+4]")]),
            RVA_WALK_CLAMP: ("HOT walk: cap", [("component", "eax"), ("max_u32", "[eax+2d0]")]),
            RVA_WALK_RESULT: ("HOT walk: forward speed", [("fwd_u32", "[ebp+fffffff4]")]),
        })
    if "--props" in sys.argv:
        bps.setdefault(RVA_LOAD_DONE, ("end of loading (match started branch)",
                                       [("started", "[[base+1777068]+4bc]")]))
    T.BREAKPOINTS = bps

    class Diag(T.Tracer):
        fixed = set()
        registered = set()
        hfsms = set()
        tables_seen = set()
        pack_mgrs = set()
        poked = False
        placed = set()
        ours = set()
        ours_lines = 0
        near_lines = 0

        def dump_pack_slots(self, mgr):
            n = min(self.u32(mgr + 0xC), 256)
            arr = self.u32(mgr + 0x4)
            cats = {}
            for i in range(n):
                e = arr + 0x28 * i
                cat, pack = self.u32(e + 0x14), self.u32(e + 0x1C)
                cats.setdefault(cat, []).append(pack)
            T.log(f"*** pack slots ({n}) per category:")
            for cat in sorted(cats):
                packs = cats[cat]
                used = " ".join(f"{p:#x}" for p in packs if p != 0xFFFFFFFF)
                T.log(f"    category {cat:#x}: {len(packs)} slots, free "
                      f"{sum(p == 0xFFFFFFFF for p in packs)}; loaded: {used or '-'}")

        def dump_scriptlet_table(self, holder):
            """Walk the allowed-scriptlet table (layout from rva 0x1235c0):
            [holder] -> T; T+0x18 groups, T+0x20 count; group G: hash with
            G+0x24 bucket count (bit 31 = one inline bucket at G+0x30), G+0x30
            buckets, node = {next, did}; G+0x4c sub-groups, G+0x54 count."""
            t = self.u32(holder)
            if not t:
                T.log("*** scriptlet table: EMPTY (the script component has none)")
                return
            seen = []

            def group(g, depth):
                if depth > 3 or len(seen) > 400:
                    return
                if self.u32(g + 0x28):
                    nb = self.u32(g + 0x24)
                    heads = ([self.u32(g + 0x30)] if nb >> 31 else
                             [self.u32(self.u32(g + 0x30) + 4 * i) for i in range(min(nb & 0x7FFFFFFF, 512))])
                    for node in heads:
                        hops = 0
                        while node and hops < 64:
                            seen.append(self.u32(node + 4))
                            node = self.u32(node)
                            hops += 1
                n_sub = min(self.u32(g + 0x54), 32)
                subs = self.u32(g + 0x4c)
                for i in range(n_sub):
                    sg = self.u32(subs + 4 * i)
                    if sg:
                        group(sg, depth + 1)

            n = min(self.u32(t + 0x20), 32)
            arr = self.u32(t + 0x18)
            T.log(f"*** scriptlet table {t:#x}: {n} groups")
            for i in range(n):
                try:
                    group(self.u32(arr + 4 * i), 0)
                except OSError as e:
                    T.log(f"    group {i}: could not be read ({e})")
            T.log("*** allowed scriptlets: " + (" ".join(f"{d:#x}" for d in sorted(set(seen))) or "none"))

        props_done = False

        def dump_props(self):
            """The property manager (global at rva 0x1766cb4, VA 0x5058d0 returns it;
            lookup VA 0x4fee60): [+0x20] bucket count (bit 31 = one inline bucket at
            +0x2c), [+0x2c] buckets, node = descriptor {+4 next, +8 id, +0x12 owner
            category, ...}. Writes every node's first 0x40 bytes and any strings its
            pointers lead to."""
            self.props_done = True
            mgr = self.u32(self.base + 0x1766CB4)
            if not mgr:
                T.log("PROPS: no property manager at rva 0x1766cb4")
                return
            nb = self.u32(mgr + 0x20)
            heads = ([self.u32(mgr + 0x2C)] if nb >> 31 else
                     [self.u32(self.u32(mgr + 0x2C) + 4 * i) for i in range(min(nb & 0x7FFFFFFF, 1 << 16))])
            path = os.path.join(cfg.log_dir, "props.txt")
            n = 0
            with open(path, "w") as f:
                f.write(f"# property manager {mgr:#x}, {nb & 0x7FFFFFFF} buckets; base {self.base:#x}\n")
                f.write("# id | first 0x40 bytes of the descriptor | strings at its pointers\n")
                for node in heads:
                    hops = 0
                    while node and hops < 4096:
                        try:
                            raw = self.read(node, 0x40)
                        except OSError:
                            break
                        words = struct.unpack("<16I", raw)
                        names = []
                        for i, w in enumerate(words):
                            if 0x10000 < w < 0x7FFF0000 and w != node:
                                try:
                                    b = self.read(w, 64)
                                except OSError:
                                    continue
                                txt = b.split(b"\0")[0]
                                if len(txt) >= 3 and all(32 <= c < 127 for c in txt):
                                    names.append(f"+{4 * i:#x}:{txt.decode()}")
                        f.write(f"{words[2]:08x} {raw.hex()} {' '.join(names)}\n")
                        n += 1
                        node = words[1]
                        hops += 1
            T.log(f"PROPS: {n} property descriptors written to {path}")

        def ctx(self, tid):
            h = T.k32.OpenThread(0x1FFFFF, False, tid)
            c = T.WOW64_CONTEXT()
            c.ContextFlags = T.WOW64_CONTEXT_FULL
            T.k32.Wow64GetThreadContext(h, ctypes.byref(c))
            T.k32.CloseHandle(h)
            return c

        def u32(self, addr):
            return struct.unpack("<I", self.read(addr, 4))[0]

        map_first = None
        map_tries = []

        def minimap_poke(self):
            """Queue the map manager's 'encounter -> map image' call (tracer inject)."""
            import time
            now = time.time()
            if self.map_first is None:
                self.map_first = now
            due = [t for t in (8.0, 25.0) if t not in self.map_tries and now - self.map_first >= t]
            if not due:
                return
            self.map_tries.append(due[0])
            holder = self.u32(self.base + 0x17758D4)
            mgr = self.u32(holder + 0x50) if holder else 0
            vt = self.u32(mgr) - self.base if mgr else 0
            if not mgr or vt != 0x1203A9C:
                T.log(f"MINIMAP: can't find the map manager (holder {holder:#x} M {mgr:#x} "
                      f"vtable rva {vt:#x}, expected 0x1203a9c)")
                return
            if self.read(mgr + 0x6C, 1)[0]:
                T.log(f"MINIMAP: the map was already loaded (patched exe), image {self.u32(mgr + 0x70):#x}")
                self.map_tries.append(99.0)
                return
            with open(T.INJECT_PATH, "a") as f:
                f.write(f"callthis 64c2c0 {mgr:x} {MINIMAP_ENCOUNTER:x}\n")
            T.log(f"MINIMAP: asking manager {mgr:#x} for the image of encounter {MINIMAP_ENCOUNTER:#x}")

        def team_poke(self):
            """The minimap and the pings compare an object's team with the LOCAL
            team at [[0x1777068]+0xbc] (rva 0x64b33a -> relation 0x453380); in the
            17:47 diag every object came out "enemy" (2), Batman's own team too:
            that local team is not set. Write Batman's team there (1) once."""
            import time
            if not hasattr(self, "team_t0"):
                self.team_t0 = time.time()
            if time.time() - self.team_t0 < 3.0:
                return
            self.team_done = True
            lobby = self.u32(self.base + 0x1777068)
            if not lobby:
                T.log("TEAM: no match object at [0x1777068]")
                return
            vals = {o: self.u32(lobby + o) for o in (0xB4, 0xB8, 0xBC, 0xC0, 0xC4)}
            T.log("TEAM: match " + f"{lobby:#x} " + " ".join(f"+{o:#x}={v:#x}" for o, v in vals.items()))
            self.write(lobby + 0xBC, struct.pack("<I", TEAM_POKE))
            T.log(f"TEAM: local team [+0xbc] set to {TEAM_POKE} (was {vals[0xBC]:#x}); "
                  "pings you make now should show on the minimap")

        def on_breakpoint(self, tid, va):
            rva = va - self.base
            if "--props" in sys.argv and not self.props_done:
                # the first breakpoint of any kind (also when the diag is started
                # after the match loaded)
                try:
                    self.dump_props()
                except OSError as e:
                    T.log(f"PROPS: could not read the table: {e}")
            try:
                if rva == 0x6B35A1 and "--minimap" in sys.argv and len(self.map_tries) < 2:
                    self.minimap_poke()
                if rva == 0x6B35A1 and "--team" in sys.argv and not getattr(self, "team_done", False):
                    self.team_poke()
                if rva == RVA_REGISTER:
                    did = self.u32(self.ctx(tid).Esp + 4)
                    if did not in self.registered:
                        self.registered.add(did)
                        name = ADVANCEMENT_IDS.get(did)
                        if name:
                            T.log(f"*** the game registered an Advancement handler: {name} ({did:#x})")
                elif rva in (RVA_PACK_LOAD, RVA_PACK_FAILED):
                    c = self.ctx(tid)
                    if (started and not self.poked and rva == RVA_PACK_LOAD
                            and self.u32(c.Esp + 4) in (0xA000010B, 0xA0000122, 0xA0000076, 0xA000024C)):
                        lobby = self.u32(self.base + 0x1777068)
                        if lobby:
                            self.write(lobby + 0x4BC, struct.pack("<I", 1))
                            self.poked = True
                            T.log(f"STARTED: [lobby {lobby:#x} +0x4bc] = 1 during loading "
                                  "(what event 0x2053 would do)")
                    mgr = c.Ecx if rva == RVA_PACK_LOAD else c.Esi
                    if rva == RVA_PACK_FAILED or mgr not in self.pack_mgrs:
                        self.pack_mgrs.add(mgr)
                        self.dump_pack_slots(mgr)
                elif rva == RVA_SET_POSITION:
                    c = self.ctx(tid)
                    pos = self.u32(c.Esp + 4)
                    raw = self.read(pos, 32)
                    w = struct.unpack("<8I", raw)
                    x, y = struct.unpack_from("<ff", raw, 16)
                    first = c.Ecx not in self.placed
                    # ours: created by the server (landblock still -1 on the first placement)
                    if first and w[2] == 0xFFFFFFFF:
                        self.ours.add(c.Ecx)
                    near = any(abs(x - px) < 3 and abs(y - py) < 3 for px, py in PROP_SPOTS)
                    tag = None
                    if first and len(self.placed) < 5000:
                        tag = "placed for the first time"
                    elif c.Ecx in self.ours and self.ours_lines < 300:
                        self.ours_lines += 1
                        tag = "server object"
                    elif near and self.near_lines < 300:
                        self.near_lines += 1
                        tag = "near a prop"
                    self.placed.add(c.Ecx)
                    if tag:
                        words = " ".join(f"{v:08x}" for v in w)
                        floats = []
                        for off in range(0, 29, 4):
                            f = struct.unpack_from("<f", raw, off)[0]
                            floats.append(f"{f:.2f}" if abs(f) < 1e5 else "-")
                        T.log(f"*** {tag}{' (NEAR A PROP)' if near else ''}: component {c.Ecx:#x} "
                              f"pos {words} (as float: {' '.join(floats)})")
                elif rva == 0x227A23:
                    holder = self.ctx(tid).Ecx
                    if holder not in self.tables_seen:      # once per entity
                        self.tables_seen.add(holder)
                        self.dump_scriptlet_table(holder)
                elif rva == 0x577B30:
                    comp = self.ctx(tid).Ecx
                    if comp not in self.hfsms:
                        self.hfsms.add(comp)
                        T.log(f"*** HFSM active: component {comp:#x} (total {len(self.hfsms)})")
                elif rva == RVA_QUERY_RESULT:
                    c = self.ctx(tid)
                    found = c.Eax & 0xFF
                    err = self.u32(c.Ebp + 0xC)
                    reg = 0x10000063 in self.registered
                    if not self.registered:
                        T.log("WARNING: saw no handler registrations; the diagnostic was started "
                              "after the match loaded (start it in the menu, before Launch)")
                    T.log(f"*** InqCanRankSkill: handler={'yes' if found else 'NO'} eError={err:#x} "
                          f"(0 = can rank up; registered during loading: {'yes' if reg else 'no'})")
                    if force and err != 0:
                        self.write(c.Ebp + 0xC, struct.pack("<I", 0))
                        T.log("FORCED: eError set to 0, the UI should send RankSkill")
                elif rva == RVA_LOAD_DONE:
                    lobby = self.u32(self.base + 0x1777068)
                    flag = self.u32(lobby + 0x4BC)
                    T.log(f"*** end of loading: match started = {flag:#x}")
                    if started and not flag:
                        self.write(lobby + 0x4BC, struct.pack("<I", 1))
                        T.log("STARTED: [lobby+0x4bc] set to 1 ('match started' branch of end of loading)")
                elif rva in (0x1693BA, 0x1693FB, 0x16940D):
                    c = self.ctx(tid)
                    if rva == 0x1693BA:
                        cls = self.u32(c.Esi + 0x30)
                        self.comp_watch = (cls in (0x2E000AAB, 0x2E0007D4) or 0x4A <= cls >> 24 <= 0x4F
                                           or cls in (0x40000B0F, 0x400001BD, 0x4000081B, 0x40000B0A, 0x40000092))
                        if self.comp_watch:
                            T.log(f"*** component 0x204760: class {cls:#x} -> .entity {self.u32(c.Ebp + 0xC):#x}")
                        if cls in (0x2E000AAB, 0x2E0007D4):
                            # the CLIENT builds the vehicle by itself (12:04:36, during the intro):
                            # who, and which object (entity pointer = creation info's owner)
                            try:
                                stack = " ".join("%x" % r for r in self.stack_rvas(tid))
                            except Exception:            # noqa: BLE001
                                stack = "?"
                            T.log(f"*** THE CLIENT CREATES {cls:#x} by itself: info {c.Esi:#x} "
                                  f"[info+4] {self.u32(c.Esi + 4):#x} stack: {stack}")
                    elif getattr(self, "comp_watch", False):
                        if rva == 0x1693FB:
                            T.log(f"*** component 0x204760: type {c.Eax:#x}")
                        else:
                            T.log(f"*** component 0x204760: result {self.u32(c.Esi):#x}")
                    self.counts[va] = 10 ** 9
                elif rva in COMPONENT_CHECKS:
                    creator, reg = COMPONENT_CHECKS[rva]
                    c = self.ctx(tid)
                    hr = c.Ecx if reg == "ecx" else c.Eax
                    if hr & 0x80000000:
                        T.log(f"*** COMPONENT FAILED: creator rva {creator:#x} error {hr:#x}")
                    self.counts[va] = 10 ** 9          # the generic line only for failures (above)
                elif rva == RVA_WALK_CLAMP:
                    c = self.ctx(tid)
                    motion = c.Eax
                    cur = struct.unpack("<f", self.read(motion + 0x2D0, 4))[0]
                    if motion not in self.fixed:
                        T.log(f"movement component {motion:#x}: max speed = {cur:.3f}")
                        if fix and cur == 0.0:
                            self.write(motion + 0x2D0, struct.pack("<f", MAX_SPEED_FIX))
                            T.log(f"FIX: max speed of {motion:#x} set to {MAX_SPEED_FIX}")
                        self.fixed.add(motion)
            except OSError as e:
                T.log(f"could not read memory at rva {rva:#x}: {e}")
            super().on_breakpoint(tid, va)

    pid = T.find_pid(T.PROCESS_NAME)
    if not pid:
        sys.exit(f"{T.PROCESS_NAME} is not running. Open it with 'python ic.py play' and stay in the menu.")
    T.log(f"===== diag, pid {pid}, skills={skills} walk={walk} fix={fix} force={force}")
    print("Diagnostic running. Play Tutorial 1; Ctrl+C to finish. Log:", T.LOG_PATH)
    d = Diag(pid)
    try:
        d.run()
    except KeyboardInterrupt:
        pass
    finally:
        adv = sorted(i for i in d.registered if i in ADVANCEMENT_IDS)
        T.log(f"===== end: {len(d.registered)} handlers registered; Advancement ones: "
              + (", ".join(ADVANCEMENT_IDS[i] for i in adv) or "NONE"))
        T.log("registered ids: " + " ".join(f"{i:#x}" for i in sorted(d.registered)))


if __name__ == "__main__":
    main()
