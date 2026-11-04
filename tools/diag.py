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
    --hover       (--raton) the unit under the mouse each frame (0xa81b30 from the selection tick) and
                  every scored candidate, one line per change: why an enemy gets no hover outline; also the
                  champion's 0x3CB write and the outline colour the client picks (alpha 0 = no outline)
    --bodytest    (--cuerpos) HEAVY, run it 20-30 s only with minions on screen, then Ctrl+C: why a unit /
                  the champion has no "Rigid body character" (docs/re-notes/unit-pick-body-cell-test.md): the
                  character's position, the per-step build gate 0x5c9dd0, the landblock test 0x5c9b20 (which
                  block refuses) and every body removal; one line per change per unit
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
    --encounters  the play menu's encounter list (Play -> VS Player / VS A.I.): how many encounters the
                  query has, whether each encounter's template loads on the client (0 = not loaded:
                  the tile shows 'undefined'), and the QueueKey JoinQueue builds from it
    --replay      playing again in the same login: local player id, loading steps, timeouts
    --anims       while a character loads, log every behavior-graph clip as it is linked to its animation:
                  clip name, animationName (.hkx) and the loaded animation's signature (duration, frames,
                  data size, first data bytes). python tools\\anim_names.py turns it into clip DID -> name.
                  Start it in the menu, BEFORE Launch (linking happens while the match loads)
    --shards      Atomic Green Lantern's E sphere (docs/re-notes/agl-e-r.md): the 0x8D scriptlets that arrive,
                  the "run key" actions (type 0x17), the "spawn child world state" action (type 0x0C) for
                  0x2E000C89, whether the world manager creates it and whether its owner instance removes it
    --bundles     (Spanish: --paquetes) what an object update does on the client (docs/re-notes/object-update-bundles.md):
                  each 0xBC property table with its object and every property it REMOVES, each 0xB0 movement state
                  (pushed or dropped), and, with the call stack, every end of a scriptlet's persistent attachment
                  (spawned child such as the Shards sphere, render effect such as the camps' phase-in, beam such as
                  Grab's arm): the stack tells whether a bundle, a 0x8D stop or something else ended it
    --camps       (Spanish: --campamentos) the jungle creatures' colour and overhead bar
                  (docs/re-notes/camps-colour-bar-positions.md): the team colour the client computes for each
                  object (team, local team, relation, colour index: 6 = neutral yellow, 0 = none), whether the
                  bar manager registers it (VitalDisplayType 0x10000831, accepted), every bar pushed to Flash
                  (add / remove, PerceivedType: 0 = the bar never attaches, display type), every bar fade and every
                  bar held back because its FloatyVitals 0x1000072C is false (a camp unit while it phases in)
    --ring        the turret warning ring (docs/re-notes/leash-recall-turretring-campicons.md 3): every call of
                  its registration 0xA7CA20 (entity added) and the gate each structure stops at: Turret bit of the
                  cached unit flags, 0x10000C5D, allied, range ([ebp-0x3C] f32 bits; 0xBF800000 = -1 = refused);
                  the phantom, every gate of its perception filter, the callback, and the draw path (effect DID,
                  ring object, state changes; docs/re-notes/ca-street-occluder-ring.md 2.3), the phantom's create call
                  and result and every unit's own perception phantom (docs/re-notes/ca-ring-phantom-strip.md 1).
                  Start it in the menu, BEFORE Launch: the structures register while the match loads
    --fogpoly     (Spanish: --niebla-poligonos) every vision source's polygon as the fog draws it (centre and
                  vertices in metres, once per 4 s per source; docs/re-notes/ca-ring-phantom-strip.md 2)
    --nofog       (Spanish: --sin-niebla) EXPERIMENT, changes the running game's memory only: turns the fog of war's
                  compose off (one flat value). If the black strip by the fence stays, it is not the fog
    --layers      (Spanish: --capas) EXPERIMENT, changes the running game's memory only: switches the client's own
                  WorldRender draw toggles off one at a time, 5 s each (DrawLandscape, DrawStaticEntities, ...; the
                  log names the one that is off), then puts every one back. Stand still where the black strip by
                  the fence shows and record the screen (or one screenshot per step): the step where the strip
                  changes names the layer it belongs to (docs/re-notes/ca-ring-bodies-strip-layers.md 2)
    --strip       (Spanish: --franja) EXPERIMENT, changes the running game's memory only
                  (docs/re-notes/ca-strip-static-shadow.md): which static draws the black strip by the fence. Start
                  it in the menu, BEFORE Launch (it records every map static's render component while the map loads).
                  In the match, stand where the strip shows: from 10 s after the first frame, 5 s steps switch off
                  one graphics setting (dynamic shadows, SSAO, reflections, decals, lights) and then hide map statics
                  (all of block 13BB, the fence pieces one by one, then ten "bit" groups whose answers spell the
                  static's index); the cycle repeats every 2.5 minutes. Record the screen: each STRIP line in
                  diag.log names the step, so the steps where the strip goes away name the culprit
    --strip2      (Spanish: --franja2) EXPERIMENT, same probes as --strip, start it in the menu too
                  (docs/re-notes/ca-strip-two-bit-candidates.md): hides the candidate statics ONE AT A TIME, 6 s
                  each (the bush #0x208 first, then #0x240, the crates #0x201 / #0x202 / #0x204, the fence pieces
                  over the strip, a bush), then two controls (every bit-9 static, every static). Each STRIP line names
                  the static that is hidden: the step where the strip goes away is the culprit
    --strip3      (Spanish: --franja3) EXPERIMENT, same probes as --strip, start it in the menu too
                  (docs/re-notes/ca-strip-two-bit-candidates.md 8): finds the culprit among the bit-9 statics (the
                  only group whose hiding removed the strip, 21:33 recording). The first cycle starts 75 s after the
                  match's first frame (time to walk there). When a cycle starts it numbers them
                  #1..#N (nearest to the strip first) and logs the list; then 6 s steps: a control (all of them),
                  12 "code" steps (#n with code bit k set, then with bit k clear, k = 0..5: the steps that clear the
                  strip spell the culprit's number) and one step per static (#1, #2, ...). Record the whole cycle
                  (~6.5 min) without moving the camera
    --storepage   (Spanish: --tiendaweb) why SHOP does not load the store page (docs/re-notes/store-fix.md 5.7): the
                  URL the store screen gets from InqStoreURL, every URL the browser's NavigateByInfo checks and
                  whether it is dropped (al 0: empty URL or a URL CEF cannot parse). Start it in the menu, then click
                  SHOP
    --mapload     (Spanish: --mapa) what a map tries to load and what it does NOT find (docs/re-notes/map-load-holes.md):
                  every failed lookup of the client's data resolver (DID, data type, who asked, the static or
                  landscape block being built), statics the block loader drops, and per terrain batch of each
                  landblock its material, blend mask and layer textures (ok / MISSING). Repeats are muted; a
                  summary is written when the diagnostic ends. Start it in the menu, BEFORE Launch
    --mapload-all (Spanish: --mapa-todo) also list EVERY record the client loads (one line per load, in
                  logs\\mapload.tsv, not in diag.log); slower loading
    --mapload-fill (Spanish: --mapa-rellenar) EXPERIMENT, changes the running game's memory only: before a
                  landblock's terrain mesh is built, raise the lowered terrain vertices of Crime Alley's dampener
                  sockets (40 / 120, 75 / 80) to the street height around them. If the black octagon turns into
                  street, the hole is the terrain itself (see map-load-holes.md). OBSOLETE since fase3-if: python
                  ic.py patch writes the same bytes into the map pack ([game] terrain_sockets, map-audit-all.md 6 /
                  11), and on a patched pack this mode finds nothing to raise
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
import zlib

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

# --- animation linking (--anims): instruction right after the asset loader call in rva 0x899de0
RVA_ANIM_LINK = 0x899EA5      # mov edi, eax: eax = hkaAnimationBinding, esi = animationName, ebp = clip

# --- map load (--mapload; docs/re-notes/map-load-holes.md, static analysis 2026-10-28). Every record goes through
# the resolver 0x43ce00 (thiscall on [0x1b57e64]+4, args: mode, handle {db type | DID}, flags), usually via the
# wrapper 0x43a1e0; a get that fails returns 0 and each caller decides what to do (most skip silently).
RVA_DB_LOADED = 0x3CEE2       # 0x43cee2: after a real (uncached) load, mgr vt+0x98: eax = object or 0; ebx = handle
RVA_DB_FAILED = 0x3CF15       # 0x43cf15: the get returns 0: esi = 0 not found / not loadable, else its finaliser failed
RVA_DB_PENDING = 0x3CEB4      # 0x43ceb4: an async request for the DID exists but is not ready: returns 0
RVA_DB_WRAPPER_RET = 0x3A200  # return address inside the wrapper 0x43a1e0: the real caller is one frame up
RVA_DID_INVALID = 0x1757E6C   # [0x1b57e6c]: the "no DID" value
DB_TYPE_NAMES = {0x09: "texture 0x13", 0x0C: "nav index 0x85", 0x0E: "terrain 0x80", 0x21: "property collection 0x83",
                 0x23: "statics 0x82", 0x24: "landblock info 0x81", 0x2E: "environment 0x08", 0x3B: "navmesh 0x90",
                 0x46: "region 0x01", 0x4A: "material 0x14"}
# return addresses of the callers that matter for the map (rva = VA - 0x400000)
MAPLOAD_CALLERS = {
    0x13E2E0: "LandBlockMesh terrain 0x80 (0x53e290)", 0x13D9F0: "landblock info 0x81 (0x53d9b0)",
    0x313C3C: "terrain batch material (0x713c10)", 0x313CCC: "terrain batch blend mask (0x713c10)",
    0x313852: "terrain layer texture A (0x7137b0)", 0x3138BD: "terrain layer texture B (0x7137b0)",
    0x313928: "terrain layer texture C (0x7137b0)", 0x312057: "far landscape patch texture (0x712030)",
    0x3142E8: "landscape render block terrain 0x80 (0x714280)",
}
# Crime Alley's dampener sockets (black-ground-shapes.md 2.2, C: two terrain vertices 20 m below the street on each
# side); --mapload-fill raises them to the street height around them (x, y in metres inside the landblock)
FILL_SPOTS = ((40.0, 75.0), (40.0, 80.0), (120.0, 75.0), (120.0, 80.0))

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
    "--objetivo": "--target",
    "--dialogo": "--dialog",
    "--equipo": "--team",
    "--notas": "--notes",
    "--minimapa": "--minimap",
    "--crear": "--create",
    "--colocar": "--place",
    "--finpartida": "--matchend",
    "--tienda": "--shop",
    "--grafo": "--graph",
    "--gestos": "--emotes",
    "--aspectos": "--skins",
    "--visibilidad": "--visibility",
    "--escudo": "--shards",
    "--destruccion": "--destruction",
    "--lanzar": "--throwpress",
    "--estadisticas": "--endstats",
    "--marcador": "--timelinekda",
    "--brazo": "--arm",
    "--mapa": "--mapload",
    "--mapa-todo": "--mapload-all",
    "--mapa-rellenar": "--mapload-fill",
    "--paquetes": "--bundles",
    "--campamentos": "--camps",
    "--tiendaweb": "--storepage",
    "--movimientos": "--moves",
    "--raton": "--hover",
    "--puntuacion": "--scorecard",
    "--niebla-poligonos": "--fogpoly",
    "--sin-niebla": "--nofog",
    "--capas": "--layers",
    "--franja": "--strip",
    "--franja2": "--strip2",
    "--franja3": "--strip3",
    "--cuerpos": "--bodytest",
    "--cabezas": "--heads",
}


def main():
    sys.argv[:] = [FLAG_ALIASES.get(a, a) for a in sys.argv]
    if ("--strip2" in sys.argv or "--strip3" in sys.argv) and "--strip" not in sys.argv:
        sys.argv.append("--strip")              # --strip2 / --strip3 run the --strip probes with their own step lists
    if os.name != "nt":
        sys.exit("This diagnostic only works on Windows, with the game open.")
    walk = "--walk" in sys.argv
    fix = "--fix" in sys.argv
    force = "--force" in sys.argv
    started = "--started" in sys.argv
    mapload_all = "--mapload-all" in sys.argv
    mapload_fill = "--mapload-fill" in sys.argv
    mapload = "--mapload" in sys.argv or mapload_all or mapload_fill
    skills = ("--walk-only" not in sys.argv and "--anims" not in sys.argv and "--graph" not in sys.argv
              and "--emotes" not in sys.argv and "--skins" not in sys.argv and "--visibility" not in sys.argv
              and "--shards" not in sys.argv and "--destruction" not in sys.argv and "--endstats" not in sys.argv
              and "--timelinekda" not in sys.argv and "--bundles" not in sys.argv and "--camps" not in sys.argv
              and "--arm" not in sys.argv and "--storepage" not in sys.argv and "--ring" not in sys.argv
              and "--throwpress" not in sys.argv and "--scorecard" not in sys.argv
              and "--fogpoly" not in sys.argv and "--nofog" not in sys.argv and "--layers" not in sys.argv
              and "--strip" not in sys.argv and "--bodytest" not in sys.argv
              and "--heads" not in sys.argv and "--orders" not in sys.argv and "--particles" not in sys.argv
              and not mapload)

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
            # 2026-11-04 (the game closed at loading twice with --ranks, access violation rva 0x18B360 after cave E2):
            # cave E2 was rewritten 2026-10-16 and 0x71F97A fell inside "cmp ecx, [ebp+0xc]" (0x71F979-B), so the
            # breakpoint byte broke the instruction. Now right after its GetSkillRank call (eax = the rank)
            0x71F987: ("rank for the UI (cave E2)", [("rank", "eax"), ("slot", "[ebp+10]")]),
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
    if "--target" in sys.argv:
        # 2026-10-21 22:52 (tester: the drones cannot be selected): the client's attack validator VA 0x9d01d0
        # (targeting-and-relations.md). Each line is one check and its result; the last one before "REJECTED" is
        # the one that fails. al = 1 passes.
        V = -0x400000
        bps.update({
            0x9D01D0 + V: ("HOT target: validator", [("champion", "[esp+4]"), ("target", "[esp+8]"), ("slot", "[esp+c]")]),
            0x9D0202 + V: ("HOT target: relation (1 neutral 2 enemy 4 ally) vs skill mask", [("relation", "eax"),
                                                                                            ("mask", "[ebp+10]")]),
            0x9D022C + V: ("HOT target: champion has the skill (0x85d420)", [("al", "eax")]),
            0x9D0263 + V: ("HOT target: 0x85fb90 index check", [("al", "eax")]),
            0x9D029B + V: ("HOT target: status tag check A", [("al", "eax")]),
            0x9D02AD + V: ("HOT target: relation again", [("relation", "eax")]),
            0x9D02CB + V: ("HOT target: visible (fog component +0x5c)", [("al", "eax")]),
            0x9D02EA + V: ("HOT target: champion may act (0x9cfaf0)", [("al", "eax")]),
            0x9D0323 + V: ("HOT target: unit flags (component +0xa4 or 0x1000019D)", [("flags", "eax")]),
            0x9D032E + V: ("HOT target: flags accepted (0x8618c0)", [("al", "eax")]),
            0x9D035C + V: ("HOT target: status tag check B", [("al", "eax")]),
            0x9D036E + V: ("HOT target: skill needs no targetable flag (0x861910)", [("al", "eax")]),
            0x9D037E + V: ("HOT target: targetable 0x10000AA7 (0x9cfac0)", [("al", "eax")]),
            0x9D0394 + V: ("HOT target: 0x9d0180(target, 0x82)", [("al", "eax")]),
            0x9D03C5 + V: ("HOT target: 0x100001C3 readable", [("al", "eax"), ("value", "[ebp+c]")]),
            0x9D0402 + V: ("HOT target: status tag check C", [("al", "eax")]),
            0x9D041B + V: ("HOT target: target alive / may be acted on (0x9cfaf0)", [("al", "eax")]),
            0x9D047F + V: ("HOT target: ACCEPTED", []),
            0x9D0209 + V: ("HOT target: REJECTED", []),
            # the right click's decision 0xa86a00 (one line each, they run once per click)
            0xA86A47 + V: ("ORDER: hover pick (0xa81b30)", [("entity", "eax"), ("iid", "q[eax+100]")]),
            0xA86B11 + V: ("ORDER: interact check (0x9d0490; 0x10000031 = stop)", [("result", "eax"),
                                                                                  ("may_interact", "[ebp+18]")]),
            0xA86BB8 + V: ("ORDER: attack validator (0x9d01d0, slot 0)", [("al", "eax"), ("may_attack", "[ebp+1c]")]),
            0xA8A140 + V: ("ORDER: right click (0xa8a140)", []),
            0x88B030 + V: ("ORDER: sent to the server (0x20ee)", [("command", "[esp+8]"), ("ability", "[esp+c]")]),
        })
        # 2026-10-22: each validator call becomes one line (entry values > every check > ACCEPTED / REJECTED), logged
        # when the chain changes for that champion / target / slot
        T.GROUP_PREFIX = "HOT target:"
        T.GROUP_ENTRY = "HOT target: validator"
        T.GROUP_ENDS = ("HOT target: ACCEPTED", "HOT target: REJECTED")
    if "--moves" in sys.argv:
        # 2026-10-29 (tester report 2026-10-29 14:40: on Gotham Heights the champion stops taking move orders; traffic:
        # no 0x20EE command 4 after the first one, skills still sent; gh-freeze-holes-picking.md F1): where the order
        # API 0xa70030 drops a right click. One line per step; the last one before nothing / "SENT" is the culprit.
        # The click point is the Position object at [ebp+18] (+4 landblock, +0xc cell, then raw dwords).
        V = -0x400000
        bps.update({
            0xA8A140 + V: ("MOVE: right click (0xa8a140)", []),
            0xA86A47 + V: ("MOVE: hover pick (0xa81b30)", [("entity", "eax"), ("iid", "q[eax+100]")]),
            0xA70030 + V: ("MOVE: order API", [("command", "[esp+8]"), ("ability", "[esp+c]"), ("lock_cc", "[ecx+cc]")]),
            0xA70072 + V: ("MOVE: may act (0x9cfaf0: LifeState 4, no 0x10000B2D)", [("al", "eax")]),
            0xA700F8 + V: ("MOVE: click snapped to the navmesh (0x4fb400, 2.5 m)", [
                ("al", "eax"), ("landblock", "[ebp+1c]"), ("cell", "[ebp+24]"), ("w28", "[ebp+28]"),
                ("w2c", "[ebp+2c]"), ("w30", "[ebp+30]"), ("w34", "[ebp+34]"), ("w38", "[ebp+38]")]),
            0xA70224 + V: ("MOVE: held by the order buffer (0x8686c0; al 1 = held)", [
                ("al", "eax"), ("lock70", "[esi+b8]"), ("lock74", "[esi+bc]"), ("slot8c", "[esi+d4]")]),
            0x88B030 + V: ("MOVE: SENT to the server (0x20ee)", [("command", "[esp+8]"), ("ability", "[esp+c]")]),
        })
    if "--hover" in sys.argv:
        # 2026-10-29 (tester report 2026-10-29 18:31: no hover outline on enemy minions / champions, several clicks to
        # attack; ca-fog-stealth-hover.md 3): the selection tick 0xa88700 picks the unit under the cursor (0xa81b30) and
        # writes it to the champion's 0x3CB; the outline (0xa4edd0) follows it. One line per change: the tick's result
        # (entity 0 = nothing picked) and every scored candidate (flags 1 = render ray, 2 = the 0.8 m box sweep;
        # priority 3 = render / part type 4; score is an f32: 0 = refused, 0x41200000 = 10)
        V = -0x400000
        bps.update({
            0xA88784 + V: ("HOVER: tick pick (0xa81b30)", [("entity", "eax"), ("iid", "q[eax+100]")]),
            0xA82299 + V: ("HOVER: candidate", [("iid", "q[edi+100]"), ("entity", "edi"), ("flags", "[esi+10]"),
                                                ("priority", "[esi+14]"), ("best_priority", "[ebp-24]"),
                                                # 2026-10-29: score = f32 just stored by 0xA16A60 (fst [ebp-3c]); the
                                                # candidate wins when score > best_score [ebp-2c] (0xA822A7 jbe)
                                                ("score", "[ebp-3c]"), ("best_score", "[ebp-2c]")]),
            # tester report 2026-10-30 15:30 (no hover highlight on any minion, ally or enemy; unit-pick-body-cell-
            # test.md 3): 0xa168f0 = the write of the pick into the champion's 0x3CB (new IID; 0 = nothing hovered,
            # which also clears the outline a right click set); 0xa4edec = right after 0xa1d020 in the outline
            # 0xa4edd0: the colour's alpha [eax+c] (0x3f800000 = drawn green, 0 = refused: target not LifeState 4 or
            # not the 0x3CB unit)
            0xA168F0 + V: ("HOVER: 0x3CB write (0xa168f0)", [("new_iid", "q[[esp+4]]")]),
            0xA4EDEC + V: ("HOVER: outline colour (0xa1d020)", [("iid", "q[esi+100]"), ("alpha", "[eax+c]"),
                                                               ("green", "[eax+4]")]),
            # tester report 2026-10-30 18:12 (hover-listener-iid-gate.md): the 0x3CB listener 0xa5d5f0 is registered by
            # 0xa16730 only when the agent's IID top byte is not 2 (al = 1 at 0xa16807 = refused; patch "controlled
            # agent listeners" nops the jne); 0xa5d709 = the listener's 0x3CB case (the new hovered IID);
            # 0xa4edab = _Selection_SoftSelection_Valid 0x100001E4 / _Invalid 0x100001E6 started on the hovered unit
            0xA16807 + V: ("HOVER: agent listener gate (0xa16730, al 1 = top byte 2: not registered)",
                           [("agent", "q[edi+100]"), ("al", "b:eax")]),
            0xA5D709 + V: ("HOVER: 0x3CB listener (0xa5d5f0)", [("new_iid", "q[ebp-10]")]),
            0xA4EDAB + V: ("HOVER: soft selection start (0x588a00)", [("iid", "q[ebx+100]"), ("key", "[esi+58]")]),
        })
    if "--bodytest" in sys.argv:
        # tester report 2026-10-30 15:30 (no hover highlight; the turret ring never meets the champion; unit-pick-body-
        # cell-test.md 2): a module-1 character (0x5d1600 -> 0x5c6030) gets its type 0x200 rigid body from 0x5c6320
        # only through 0x5c9dd0, which the PhysicsWorldManager step (0x5d3650 -> 0x5ca0c0) runs on EVERY character
        # EVERY step: so a missing body = the landblock test 0x5c9b20 keeps failing for the character's position
        # (+0x44), or that position was never valid. HOVER-style lines (one per change per unit, keyed on the IID).
        # Heavy (traps every physics step per bodiless character): 20-30 s only.
        bps.update({
            # the character's position set (snap / attach): region, landblock x | y << 8 | cell << 16, instance (low
            # 16 bits), world, the two body slots (+0x70 / +0x74, 0 = none)
            0x1C9EF9: ("HOVER: body position set (0x5c9e90)", [("iid", "[[esi+10]+100]"), ("region", "[esi+48]"),
                                                                ("lb_cell", "[esi+4c]"), ("inst", "[esi+50]"),
                                                                ("world", "[esi+40]"), ("body70", "[esi+70]"),
                                                                ("body74", "[esi+74]")]),
            # the per-step gate in 0x5c9dd0 (al = 0x5c9b20's verdict; 1 = 0x5c6320 builds the body now)
            0x1C9DF7: ("HOVER: body build gate (0x5c9dd0, al 0 = refused)", [("iid", "[[esi+10]+100]"), ("al", "b:eax")]),
            0x1C9E1B: ("HOVER: body build gate (0x5c9dd0 +0x23 path, al 0 = refused)",
                       [("iid", "[[esi+10]+100]"), ("al", "b:eax")]),
            # inside 0x5c9b20 (args = &character+0x44, &character+0x28; for a character [ebp+8]-0x34 = its entity):
            # 0x5becb0 = the landblocks the position + shape box cover (al 0 = position refused, count = blocks)
            0x1C9B58: ("HOVER: cell test landblocks (0x5becb0)", [("iid", "[[[ebp+8]-34]+100]"), ("al", "b:eax"),
                                                                  ("count", "[ebp-a8]"), ("region", "[[ebp+8]+4]"),
                                                                  ("lb_cell", "[[ebp+8]+8]"), ("inst", "[[ebp+8]+c]")]),
            # 0x5c86d0 per landblock (al 0 = this block refuses: not in the physics manager's loaded list +0x94 /
            # no block object / block not ready)
            0x1C9BCB: ("HOVER: cell test one block (0x5c86d0)", [("iid", "[[[ebp+8]-34]+100]"), ("al", "b:eax"),
                                                                 ("block_region", "[ebp-2c]"), ("block_lb", "[ebp-28]"),
                                                                 ("block_inst", "[ebp-24]")]),
            # the body removed (0x5c3290: invalid position, failed test, new world)
            0x1C3290: ("HOVER: body removal (0x5c3290)", [("iid", "[[ecx+10]+100]"), ("body70", "[ecx+70]"),
                                                          ("body74", "[ecx+74]"), ("bodya0", "[ecx+a0]")]),
            # the character object created / its body built (as --ring)
            0x1D1600: ("HOVER: character object created (movement module)", [("iid", "[[[esp+4]]+100]"),
                                                                              ("world", "[ecx+38]")]),
            0x1C6320: ("HOVER: character body built (type 0x200)", [("iid", "[[ecx+10]+100]"), ("flags", "[ecx+20]")]),
        })
    if "--dialog" in sys.argv:
        # 2026-10-22 08:39 (tester: Superman repeats lines although each 0x2001 is sent once): the 0x2001 handler
        # 0xa13b90 calls the dialog system's vt+8 (entity, u32, key, speakers, u8, 0, instance, time limit); the update
        # 0xa89c40 walks its active conversations (0xa83b10 / 0xa7fad0 per conversation)
        V = -0x400000
        bps.update({
            0xA13BE4 + V: ("DIALOG: start conversation", [("fn", "edx"), ("entity", "[esp]"), ("a", "[esp+4]"),
                                                          ("key", "[esp+8]"), ("u8", "[esp+10]"), ("instance", "[esp+18]")]),
            0xA13B80 + V: ("DIALOG: 0x2047 call", [("fn", "edx")]),
        })
    if "--shop" in sys.argv:
        # 2026-10-23 (tester: the shop lists no items): the catalogue is built by the client when 0x100001D3 changes
        # on the player object (0xa91670 -> 0xa908f0: encounter -> 0x49 template -> 0x1000081E -> manager vtable +4
        # and 0xa8ebb0). Rvas = Ghidra address - 0x400000. Each hit says the step was reached.
        bps.update({
            # 2026-10-23: the map / shop listeners attach on a key-0x26 broadcast of the player object's bundle
            0x29BD00: ("MAP: key-0x26 broadcast (0x69bd00)", [("iid_lo", "[esp+4]"), ("iid_hi", "[esp+8]")]),
            0x29BD90: ("MAP: local player object ready (0x69bd90)", []),
            0x24DAC0: ("MAP: object finalised (0x64dac0)", [("ecx", "ecx")]),
            0x66A8E0: ("MAP: map property listener (0xa6a8e0)", [("obj", "[esp+4]"), ("arg2", "[esp+8]"),
                                                                  ("value", "[esp+c]")]),
            0x2904D0: ("SHOP: Upgrade manager created (0xa904d0)", []),
            0x64C2C0: ("MAP: LoadMap (0xa4c2c0; from the HUD cave N: ret rva 0x4c4fa4)", [("arg", "[esp+4]")]),
            0x691670: ("SHOP: encounter property 0x100001D3 changed (0xa91670)", [("ecx", "ecx"), ("arg", "[esp+4]")]),
            0x6908F0: ("SHOP: build the catalogue (0xa908f0)", [("ecx", "ecx"), ("arg", "[esp+4]")]),
            0x68EBB0: ("SHOP: catalogue list handed to the UI (0xa8ebb0)", [("ecx", "ecx"), ("arg", "[esp+4]")]),
            # 2026-10-23 (shop-ui-items.md): Flash's items query 0x100002CC -> 0xa44fe0; [eax+8] = items in the list
            0x645001: ("SHOP: Flash asks for the items (0xa45001)", [("count", "[eax+8]")]),
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
        # tester report 2026-10-29 19:55 (the fence strip still black; ca-ring-fog-bundles.md 2): the occluder pass per
        # source. 0xaae209: al = attribute 0x100008CE of the source (1 = no occluder pass, its circle has no black
        # region); 0xaae32e: a body the pass keeps as an occluder (type 0x800 = a drawn static; IID top byte 1 = map
        # static, 2 = a server object such as a liftable vehicle)
        bps[0x6AE209] = ("HOT fog: occluder pass (skip al 1 = 0x100008CE true)",
                         [("src_lo", "[esi]"), ("src_hi", "[esi+4]"), ("skip", "eax"), ("radius_f32", "[ebp+fffffff0]")])
        bps[0x6AE32E] = ("HOT fog: occluder body", [("src_lo", "[esi]"), ("body_type", "[ebp+ffffffbc]"),
                                                     ("body_lo", "[ebp+ffffffc0]"), ("body_hi", "[ebp+ffffffc4]")])
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
    if "--destruction" in sys.argv:
        # Destructible vehicles (docs/re-notes/destructible-vehicles.md, 2026-10-26): at which step a
        # CDestructionComponent object drops out. comp = the destruction component (entity+0x58).
        bps.update({
            0x22F960: ("DEST start 0x62f960", [("comp", "ecx"), ("entity", "[ecx+4]"), ("record", "[ecx+8]"),
                                               ("built", "[ecx+80]")]),
            0x230FC0: ("DEST build check 0x630fc0", [("comp", "ecx"), ("built", "[ecx+80]"), ("pieces", "[ecx+18]"),
                                                     ("ctype", "[[ecx+4]+114]"), ("arg", "[esp+4]")]),
            0x230BF0: ("DEST build check (attached) 0x630bf0", [("comp", "ecx"), ("built", "[ecx+80]"),
                                                                ("pieces", "[ecx+18]"), ("ctype", "[[ecx+4]+114]")]),
            0x230650: ("DEST intact pieces at a frame 0x630650 (types 6 / 9)", [("comp", "ecx"), ("frame", "[esp+4]")]),
            0x231050: ("DEST event 0x8B reset 0x631050", [("iid", "q[esp+8]")]),
            0x230453: ("DEST intact pieces built 0x6303f0", [("comp", "esi"), ("pieces", "[esi+18]"),
                                                            ("record_pieces", "[[esi+8]+58]")]),
            0x22FB20: ("DEST state 0x10D / 0x138 applied 0x62fb20", [("comp", "ecx"), ("state", "[esp+4]"),
                                                                     ("count", "[[esp+4]+10]")]),
            0x22C4EA: ("DEST piece render instance 0x62c4ea", [("piece", "esi"), ("def", "[esi+40]")]),
            # 2026-10-29 tester report 19:55 (the thrown vehicle does not explode; liftable-carry-throw-press.md 3): the
            # 0x8A impulse (radius / magnitude are f32 bits), its scans (entity / piece lists), whether hits were found
            # (0x631FA0 runs only then) and each piece's health when the magnitude is subtracted (0x62BC00)
            0x232370: ("DEST 0x8A impulse 0x632370", [("pos", "[esp+4]"), ("radius", "[esp+8]"),
                                                       ("magnitude", "[esp+c]"), ("level", "[esp+10]")]),
            0x231B00: ("DEST impulse piece bodies 0x631b00", [("count", "[[esp+4]+8]")]),
            0x231940: ("DEST impulse entities 0x631940", [("count", "[[esp+4]+8]")]),
            0x231FA0: ("DEST impulse applied 0x631fa0", [("impulse", "[esp+4]"), ("hits", "[[esp+4]+34]")]),
            0x22BC00: ("DEST piece damage 0x62bc00", [("piece", "ecx"), ("health", "[ecx+44]"), ("amount", "[esp+4]")]),
            # 2026-10-29 tester report 21:10 (the landed vehicle vanishes; liftable-aura-lift-throw-break.md 4): a piece
            # removed by Vfx_OnExplode's action 0x28 (CDestructionComponent vfunc +0x4C = 0x62ED00 -> 0x62EBF0: render
            # instance and body destroyed, out of the active list)
            0x22ED00: ("DEST piece removed by id 0x62ed00", [("comp", "ecx"), ("piece_id", "[esp+4]"),
                                                            ("active", "[ecx+18]")]),
            0x22EBF0: ("DEST piece removed 0x62ebf0", [("comp", "ecx"), ("piece", "[esp+4]"), ("active", "[ecx+18]")]),
        })
    if "--throwpress" in sys.argv:
        # 2026-10-29 tester report 19:55 (a carried meteorite could not be thrown: the slot-7 presses reached the server
        # as 0x20EA, no 0x20EE order followed; liftable-carry-throw-press.md 1): how far a press gets in the client's
        # order path (dispatcher 0xa85da0 -> targeting start 0xa26420 (sends 0x20EA) -> quick cast 0xa76320 -> order API
        # 0xa70030 / 0xa70600 -> point check 0xa25d80 -> buffer 0x8686c0 -> hold check 0x863860 -> 0x20EE)
        bps.update({
            0x685DA0: ("PRESS dispatcher 0xa85da0", [("agent", "[esp+4]"), ("slot", "[esp+8]"), ("press", "[esp+c]"),
                                                     ("targeting", "[ecx+ec]")]),
            0x626420: ("PRESS targeting start 0xa26420", [("slot", "[esp+8]"), ("busy", "[ecx+110]")]),
            0x676320: ("PRESS quick cast 0xa76320", [("quick", "[esp+8]"), ("type", "[esp+c]"), ("slot", "[ecx+ec]")]),
            0x670030: ("ORDER api 0xa70030", [("cmd", "[esp+8]"), ("slot", "[esp+c]")]),
            0x670600: ("ORDER point 0xa70600", [("slot", "[esp+c]"), ("type", "[esp+10]")]),
            0x625D80: ("ORDER point check 0xa25d80", [("slot", "[esp+c]")]),
            0x4686C0: ("ORDER buffer 0x8686c0", [("cmd", "[esp+8]"), ("slot", "[esp+c]")]),
            0x463860: ("ORDER hold check 0x863860", [("slot", "[esp+8]"), ("lock", "[ecx+70]"), ("current", "[ecx+78]")]),
        })
    if "--arm" in sys.argv:
        # Grab's arm (docs/re-notes/grab-arm-carry.md 1.4, 2026-10-28): the type-2 beam action 0x673280 resolves its
        # target at 0x67338E; IID 0 = the binding to 0x100004E2 failed, AGL's IID = the beam was built (then its parts)
        bps.update({
            0x273280: ("ARM beam action start 0x673280", [("ecx", "ecx")]),
            0x27338E: ("ARM beam target resolved", [("target", "q[ebp+ffffffd8]"), ("eax", "eax")]),
            # 2026-10-28 (grab-beam.md: the per-frame end-point checks; the first one that stops firing is the cause)
            0x3499EA: ("ARM source end resolved (missile)", [("eax", "eax")]),
            0x349C07: ("ARM target end resolved (AGL)", [("eax", "eax")]),
            0x34981B: ("ARM end: entity found", [("eax", "eax")]),
            0x349845: ("ARM end: render model present", [("eax", "eax")]),
            0x349865: ("ARM end: model active", [("eax", "eax")]),
            0x34989E: ("ARM end: attach point found", [("eax", "eax")]),
            0x3498C1: ("ARM end: attach point found (2)", [("eax", "eax")]),
            0x34CC05: ("ARM draw pass reached", [("ecx", "ecx")]),
            0x34CC0C: ("ARM draw pass failure counter", [("eax", "eax")]),
        })
        if T.GROUP_PREFIX is None:
            # 2026-10-29 (docs/re-notes/agl-qer-lift.md 1, C diag 14:19 run: the per-frame checks used up their
            # 100-line budget on the map's beams at 14:20:01-02 and the intro cinematic's at 14:20:06-10, so no Grab
            # beam was ever seen): the per-frame checks are grouped per beam, one line per beam (source IID > target
            # IID) whenever its chain of results changes: entity / model / active / attach of each end, then DRAWN or
            # FAILED. 0x749960 entry (ecx = beam) opens the chain; 0x74CC05 / 0x74CC0C close it.
            T.GROUP_PREFIX = "ARM:"
            T.GROUP_ENTRY = "ARM: beam"
            T.GROUP_ENDS = ("ARM: DRAWN", "ARM: FAILED")
            bps.update({
                0x349960: ("ARM: beam", [("src", "q[ecx+68]"), ("dst", "q[ecx+78]")]),
                0x34981B: ("ARM: entity", [("ok", "z:eax")]),
                0x349845: ("ARM: model", [("ok", "z:ecx")]),
                0x349865: ("ARM: active", [("ok", "b:eax")]),
                0x34989E: ("ARM: attach(fallback)", [("ok", "b:eax")]),
                0x3498C1: ("ARM: attach", [("ok", "b:eax")]),
                0x3499EA: ("ARM: SRC", [("ok", "b:eax")]),
                0x349C07: ("ARM: DST", [("ok", "b:eax")]),
                0x34CC05: ("ARM: DRAWN", [("beam_src", "q[esi+68]")]),
                0x34CC0C: ("ARM: FAILED", [("beam_src", "q[esi+68]")]),
            })
    if mapload:
        # What a map loads and what it does not find (docs/re-notes/map-load-holes.md, 2026-10-28; tester: hollow
        # black sections on Crime Alley). Every handler below is custom (on_breakpoint -> mapload_hit): one line per
        # new fact, repeats only counted. Labels start with "MAP" (rva = VA - 0x400000).
        bps.update({
            # the data resolver 0x43ce00: failures (and, with --mapload-all, every real load)
            RVA_DB_FAILED: ("MAP get failed", []),
            RVA_DB_PENDING: ("MAP get pending", []),
            # landblock: 0x53e290 LandBlockMesh(position) and 0x714280 landscape render block(position): which block
            0x13E290: ("MAP LandBlockMesh", []),
            0x314280: ("MAP landscape render block", []),
            # statics of the block (0x548550): esi = the 0x70-byte entry (+0x20 type, +0x28 index, +0x2c IID,
            # +0x30 world state); 0x54af70 (al = 0: world state not loaded / creation type 0 -> silently dropped),
            # then the block's filter vt+0x18 (al = 0: skipped); 0x5486ab = next entry
            0x148645: ("MAP static entry", []),
            0x14864E: ("MAP static check", []),
            0x148695: ("MAP static filter", []),
            0x1486AB: ("MAP static next", []),
            # near terrain batches (0x713c10, edi = batch: +0x68 material 0x14, +0x64 blend mask 0x13, +4 layer count,
            # [+0] layer indices into the block's palette); layers resolved by 0x4db370 on the region (al = 0: the
            # whole block's terrain is not built); layer textures in 0x7137b0 (edi = layer descriptor +0x10 / +0x14
            # / +0x58, each got through the resolver: 0 = left unbound)
            0x313C3C: ("MAP terrain batch material", []),
            0x313CCC: ("MAP terrain batch mask", []),
            0x313D3E: ("MAP terrain layer", []),
            0x313852: ("MAP terrain layer texture", []),
            0x3138BD: ("MAP terrain layer texture", []),
            0x313928: ("MAP terrain layer texture", []),
            0x313D97: ("MAP terrain batch end", []),
            0x313DB5: ("MAP terrain batch end", []),
        })
        if mapload_all:
            bps[RVA_DB_LOADED] = ("MAP loaded", [])
        if mapload_fill:
            # before the vertices are built from the terrain record's heights: render (0x712860, [esp+4] = terrain
            # object) and collision / LandBlockMesh (0x53bb00, [esp+8] = terrain object)
            bps[0x312860] = ("MAP fill (render mesh)", [])
            bps[0x13BB00] = ("MAP fill (LandBlockMesh)", [])
    if "--scorecard" in sys.argv:
        # 2026-10-29 tester report 23:03 (the score screen's rewards panel; scorecard-accolades-meteor-aura.md 1): the
        # UI state machine's events to Flash (106 = LoadScorecard_Accolades, 72 = _Summary, 91 = _Stats, 100 =
        # LoadScorecardScreen) and the order in which the scorecard's data reach Flash (the Accolades tab animates
        # only if the accolades notice comes after every other piece). RVAs of the GM_* RecvNotice natives.
        bps.update({
            0x521BE0: ("SC UIStateMachineEvent to Flash", [("event", "[esp+4]")]),
            0x4E3AC0: ("SC EndOfMatchStats to Flash", [("duration", "[esp+a0]"), ("encounter", "[esp+a8]"),
                                                      ("ranked", "[esp+ac]")]),
            0x500350: ("SC HeaderNameAndProtectorIcons to Flash", []),
            0x4908D0: ("SC AccountEndOfMatchLevelAndXP to Flash", [("level", "[esp+4]"), ("prev", "[esp+8]")]),
            0x48FF50: ("SC CharacterLevelAndXP to Flash", [("character", "[esp+4]")]),
            0x490CE0: ("SC SoftCurrencyReward to Flash", [("base", "[esp+4]"), ("daily", "[esp+8]")]),
            0x4CEE70: ("SC AccoladesEarned to Flash", [("encounter", "[esp+4]"), ("ranked", "[esp+8]"),
                                                       ("champion", "[esp+c]"), ("names", "[[esp+10]+8]")]),
            # 2026-10-30 tester report 13:18 (the Summary tab still empty after the late 0x2104;
            # scorecard-summary-tab-conditions.md 3): every C++ gate between a message and Flash's accolades notice.
            # 0x8CEE70's own gate: [ebp-a0] = 0 -> no Flash target, the notice is dropped
            0x4CEEE6: ("SC accolades notice: Flash target (0 = dropped)", [("target", "[ebp+ffffff60]")]),
            # 0x2188 handler 0xA61DA0: manager +0x64 = 0 -> returns at once; then its accolade count (0 -> returns)
            0x661DAE: ("SC 0x2188 handler gate (+0x64; 0 = returns)", [("gate", "[eax+64]"),
                                                                       ("count", "[[ebp+24]+8]")]),
            0x661E86: ("SC 0x2188 accolade build (al 0 = no Flash call)", [("al", "eax")]),
            0x661F17: ("SC 0x2188 Flash notice returned (al 1 = delivered)", [("al", "eax")]),
            # 0x2104 handler 0xA7E0A0: its encounter (param_21) / first-map flag (param_22), the accolade build's
            # result (0xA56DB0 al 0 = encounter record not found or list lengths differ) and the Flash call
            0x67E0A0: ("SC 0x2104 handler", [("champion", "[esp+c]"), ("level", "[esp+18]"), ("prev", "[esp+1c]"),
                                            ("encounter", "[esp+54]"), ("flag", "[esp+58]")]),
            0x67E321: ("SC 0x2104 accolade build (al 0 = no Flash call)", [("al", "eax")]),
            0x67E3C9: ("SC 0x2104 Flash notice returned (al 1 = delivered)", [("al", "eax")]),
            # inside 0xA56DB0: the encounter record (0 = not found -> returns 0)
            0x656E2C: ("SC accolade build: encounter record (0 = not found)", [("record", "[ebp+fffffff8]")]),
            # Flash's Init request 0x100004E6 (RequestAccountEndOfMatchAccoladesEarned) -> 0xA1A190 replays the cache
            0x5313AE: ("SC Flash asks for the accolades (Init)", []),
            0x61A19C: ("SC accolades replay from the cache", [("encounter", "[eax]"), ("ranked", "[eax+4]"),
                                                             ("champion", "[eax+8]"), ("names", "[eax+14]")]),
            0x61A1C5: ("SC accolades replay returned (al 1 = delivered)", [("al", "eax")]),
            # the post-encounter movie (the scorecard's ShowTab waits for its dialog) and the level-up ribbon
            0x497AC0: ("SC PlayEndOfMatchEncounterMovie to Flash", []),
            0x48E780: ("SC Ribbon_CharacterLevelChanged to Flash", []),
        })
    if "--endstats" in sys.argv:
        # The end page's stats grid (docs/re-notes/end-stats-2045.md, 2026-10-26): the last label before a first-chance
        # exception is the crash site. Use with --matchend.
        bps.update({
            0x679AA6: ("END page has read the Scorecard columns", []),
            0x672860: ("END grid builder entered", [("ecx", "ecx")]),
            0x672AAF: ("END grid section count call (0 = will crash)", [("grid", "ecx")]),
            0x672B2E: ("END per-section label / stat list", [("ecx", "ecx")]),
            0x672DEF: ("END stat-list count call (0 = will crash)", [("list", "ecx")]),
            0x673020: ("END one stat read", [("entry", "ecx"), ("stat", "[[esp]]")]),
            0x67A338: ("END grid builder returned", []),
            0x67A44B: ("END Flash call made", []),
            0x67A450: ("END Flash call returned", []),
            0x67A4C3: ("END second row loop", []),
        })
    if "--timelinekda" in sys.argv:
        # 2026-10-28 (docs/re-notes/timeline-kda-endscreen.md): the strip's StartTimeline / AddTimelineEvent as Flash gets
        # them (f64 = lo / hi dwords), the K/D/A scorecard (your IID), and the end page's per-row upgrades / power graph
        # (Flash ScorecardManager waits for one of each per row). Use with --matchend --endstats.
        bps.update({
            0x498F50: ("TL Flash StartTimeline", [("now_lo", "[esp+4]"), ("now_hi", "[esp+8]")]),
            0x4B33E0: ("TL Flash AddTimelineEvent", [("handle", "[esp+c]"), ("severity", "[esp+10]"),
                                                     ("time_lo", "[esp+2c]"), ("time_hi", "[esp+30]"),
                                                     ("now_lo", "[esp+34]"), ("now_hi", "[esp+38]")]),
            0x4E7D90: ("KDA Flash UpdateMatchScorecard", [("rows", "[[esp+4]+8]"), ("you_lo", "[esp+34]"),
                                                          ("you_hi", "[esp+38]"), ("team", "[esp+3c]")]),
            0x63AC70: ("END row upgrades (0xa3ac70; count 0 = no Flash data)", [("acct_lo", "[esp+4]"),
                                                                                ("acct_hi", "[esp+8]"),
                                                                                ("count", "[[esp+10]+8]")]),
            0x506DD0: ("END Flash UpdateCurrentUpgrades", [("iid_lo", "[esp+4]"), ("iid_hi", "[esp+8]")]),
            0x507A00: ("END Flash UpdatePowerGraphValues", [("iid_lo", "[esp+4]"), ("iid_hi", "[esp+8]")]),
            0x4E76D0: ("END Flash SetEndOfMatchStatsHeader", []),
        })
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
    if "--encounters" in sys.argv:
        # The play menu (static analysis 2026-10-22): GM_Encounter.InqPVPEncounters = 0xA68030 on the encounter
        # manager (this - 0x40 = the 0x2024 DIDs, this - 0x30 the queue flags); per encounter it loads the template
        # (0x8535D0 -> 0x49......, pointer at [ebp-0x14]; 0 = not loaded: no name, type, images); 0xA35FB0 reads
        # the template's 0x100001D2 record (names, images); JoinQueue's QueueKey (0x86E060) is (0, 0) when the
        # template does not load.
        bps.update({
            0x668030: ("encounters: menu query InqPVPEncounters", [("count", "[ecx+ffffffc8]"),
                                                                   ("first", "[[ecx+ffffffc0]]"),
                                                                   ("first_flags", "[[ecx+ffffffd0]]")]),
            0x668377: ("encounters: template loaded? (0 = no)", [("index_x4", "esi"), ("template", "[ebp+ffffffec]")]),
            0x635FC4: ("encounters: names record", [("encounter", "[ebp+8]"), ("record", "[ebp+fffffffc]")]),
            0x635FDD: ("encounters: names record loaded? (0 = no)", [("ptr", "eax")]),
            0x46E079: ("encounters: JoinQueue key, template loaded? (0 = no)", [("encounter", "[ebp+c]"),
                                                                              ("template", "[ebp+fffffff8]")]),
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
    if "--skins" in sys.argv:
        # 2026-10-25 (skin-overlay-fix.md 5): which entity / world state builds the base model over a costume
        bps.update({
            0x14B9A0: ("SKIN entity construction (0x54b9a0)", [("iid_lo", "[[esp+8]+10]"), ("iid_hi", "[[esp+8]+14]")]),
            0x24D8A0: ("SKIN 0xF2 create bundle (0x64d8a0)", [("iid_lo", "[esp+4]"), ("iid_hi", "[esp+8]"),
                                                            ("ws_field", "[[esp+c]+28]")]),
            0x14D5C0: ("SKIN ChangeWorldState (0x54d5c0)", [("new_ws", "[esp+c]")]),
            0x21AEB0: ("SKIN model component setup (0x61aeb0)", [("ecx", "ecx")]),
            0x2A5AE0: ("SKIN cinematic actor spawn (0x6a5ae0)", []),
        })
    if "--shards" in sys.argv:
        # 2026-10-25 (docs/re-notes/agl-e-r.md 1.5): where Shards of Will's sphere (world state 0x2E000C89) is lost.
        # Shards_Start 0x1000088C runs Shards_Active 0x10000886 with a type 0x17 action (0x671fa0, key at
        # [[ecx+24]+c]+6c); Active's 0x0C actions (execute 0x6852b0: ws DID ecx+0x34, keep 0x67C = byte ecx+0x124)
        # build a spawn request (0x683af0: world manager vt+0x30 at 0x683c58, result in eax at 0x683c5a) and, with
        # keep set, a persistent instance (0x655360) whose end (0x666b40) destroys the child (0x65f860)
        bps.update({
            0x2279D0: ("SHARDS 0x8d scriptlet started", [("did", "[esp+8]")]),
            0x271FA0: ("SHARDS type 0x17 run key", [("key", "[[[ecx+24]+c]+6c]"), ("targets", "[ecx+68]")]),
            0x271CE0: ("SHARDS type 0x17 instance end", [("key", "[[[ecx+24]+c]+6c]"), ("reason", "[esp+8]"),
                                                         ("stop_flags", "[[[ecx+24]+c]+70]")]),
            0x2852B0: ("SHARDS type 0x0C spawn execute", [("ws", "[ecx+34]"), ("keep_byte", "[ecx+124]"),
                                                          ("ctx_flags", "[[[esp+8]]+50]")]),
            0x283C5A: ("SHARDS spawn: world manager create returned", [("result", "eax"), ("pending", "[esi+34]")]),
            0x255360: ("SHARDS persistent child instance created", [("request", "[esp+c]")]),
            0x266B40: ("SHARDS persistent child instance END (child removed)", [("request", "[ecx+5c]"),
                                                                                 ("reason", "[esp+8]")]),
            0x25F860: ("SHARDS spawned child destroyed", [("request", "ecx")]),
        })
    if "--bundles" in sys.argv:
        # 2026-10-28 (docs/re-notes/object-update-bundles.md, tester report 2026-10-28 15:00): a 0x4 bundle to a live
        # object rebuilds nothing (0x64d8a0); its 0xBC table goes to 0x62afd0 (ecx = the object's property component,
        # [ecx+4] = the entity), which sets every sent id through 0x6's path and REMOVES the object's own network-mode
        # 1 / 3 ids the table omits (vt+0x54 at 0x62b0cb, id in eax at 0x62b0c7); its 0xB0 is one more movement state
        # (0x60afa0, ebx = the movement component + 0x10: dropped before creation at 0x60afb4, pushed or not at
        # 0x60b00b, al). With the call stack, every end of a scriptlet's persistent attachment ([ecx+18]+8 = the owner
        # IID): spawned child 0x666b40 (Shards sphere), render effect 0x65ca30 (camp phase-in), beam 0x659b00 (Grab).
        # In the stack: 0x22afd0..0x22b1a0 / 0x178de0 / 0x177e10..0x177f90 = a bundle's or 0x6's property change, 0x2298d0 /
        # 0x20afa0 = a movement state, 0x2279d0 / 0x134bf0 = a 0x8D start / signal from the server.
        bps.update({
            0x22AFD0: ("HOT BUNDLE 0xBC table (0x62afd0)", [("iid_lo", "[[ecx+4]+100]"), ("iid_hi", "[[ecx+4]+104]"),
                                                          ("ids_sent", "[[esp+4]+8]")]),
            0x22B0C7: ("HOT BUNDLE 0xBC REMOVES an omitted property", [("id", "eax"),
                                                                       ("iid_lo", "[[[ebp+fffffffc]+4]+100]")]),
            0x20AFB4: ("HOT BUNDLE 0xB0 dropped (movement not created yet)", [("iid_lo", "[[ebx+fffffff4]+100]")]),
            0x20B00B: ("HOT BUNDLE 0xB0 state (low byte: 1 pushed, 0 duplicate / older)",
                       [("pushed", "eax"), ("iid_lo", "[[ebx+fffffff4]+100]")]),
            0x266B40: ("STACK BUNDLE scriptlet child END (0x666b40)", [("owner_lo", "[[ecx+18]+8]"),
                                                                       ("request", "[ecx+5c]")]),
            0x25CA30: ("STACK BUNDLE scriptlet render effect END (0x65ca30)", [("owner_lo", "[[ecx+18]+8]"),
                                                                               ("effect", "[ecx+5c]")]),
            0x259B00: ("STACK BUNDLE scriptlet beam END (0x659b00)", [("owner_lo", "[[ecx+18]+8]"),
                                                                      ("beam", "[ecx+5c]")]),
        })
    if "--heads" in sys.argv:
        # 2026-10-30 (tester report 15:30: "the top part of the turrets is still lost"; core-door-regen.md 5): the head
        # is the client child of the turret body's Vfx_AI_Active run (type-0x0C spawn); a run ends only when its
        # children end, by a signal / stop, or with its object (client-scriptlets-graphs.md 1.4, C). With the stack:
        # every end of a spawned child (0x666b40, owner IID = [[ecx+18]+8]) and of a render effect (0x65ca30), every run
        # removed (0x57baf0, ecx = the run list owner, [esp+4] = the run) and every 0x8D start / signal from the server
        # (0x6279d0, did / instance). The head's END line carries the body's IID (server.log "spawn turret ..."); the
        # STACK frames under it name what ended it (0x2279d0 / 0x134bf0 = a server 0x8D, 0x22afd0.. = a property
        # change, 0x2298d0 / 0x20afa0 = a movement state).
        bps.update({
            0x266B40: ("STACK HEADS spawned child END (0x666b40)", [("owner_lo", "[[ecx+18]+8]"),
                                                                    ("owner_hi", "[[ecx+18]+c]"), ("request", "[ecx+5c]")]),
            0x25CA30: ("STACK HEADS render effect END (0x65ca30)", [("owner_lo", "[[ecx+18]+8]"), ("effect", "[ecx+5c]")]),
            0x17BAF0: ("STACK HEADS scriptlet run removed (0x57baf0)", [("ecx", "ecx"), ("run", "[esp+4]")]),
            0x2279D0: ("HOT HEADS 0x8D start / signal (0x6279d0)", [("did", "[esp+8]"), ("instance", "[esp+c]")]),
        })
    if "--storepage" in sys.argv:
        # 2026-10-28 15:00 (tester: SHOP showed the browser's chrome://version page; store-fix.md 5.7 with the skeptic's
        # correction 1): fallback when server.log shows "web ticket request (0x95)" but no "store page: GET /store".
        # The store URL is a narrow ref-counted string object (char pointer first). InqStoreURL 0xa97320 pushes
        # &app+0x144 before its copy call 0xa97331, so [esp] = the string object and [[esp]] = its chars;
        # NavigateByInfo's check 0x832f54 passes the nav info in ECX (+0 = the URL's chars) to IsValid 0x8308c0, whose
        # AL (0x832f59) is 0 when the request is dropped (empty URL or cef_parse_url failed). An empty url = the
        # AuthSelect pair was not read (restart the client: the URL is read once per client process); a good url with
        # AL 1 and still no GET = the CEF side.
        bps.update({
            0x697331: ("STOREPAGE: InqStoreURL (0xa97331): the URL the store screen gets", [("url", "s[[[esp]]]")]),
            0x432F54: ("STOREPAGE: NavigateByInfo checks a URL (0x832f54)", [("url", "s[[ecx]]")]),
            0x432F59: ("STOREPAGE: IsValid (0x832f59): al 1 = navigates, 0 = dropped", [("eax", "eax")]),
        })
    if "--camps" in sys.argv:
        # 2026-10-28 15:00 (tester: the jungle drones are grey and show no overhead bar; camps-colour-bar-positions.md
        # 1-2): 0xa7b171 = 0xa7b0d0 after it chose the colour (esi = entity, edi = its team, ebx = the local team,
        # [ebp-8] = relation, [ebp-4] = colour index 0x100007A2: 3 ally, 5 enemy, 6 neutral, 1 override, 0 none);
        # 0xa0f012 = the bar manager's registration filter 0xa0efc0 after reading VitalDisplayType 0x10000831
        # ([ebp+8]; 0 = no bar for a non-character); 0xa3a925 = its verdict (al) in the entity-added hook 0xa3a900;
        # 0xa50d31 = 0xa50a70 about to push one bar to Flash (bl = add, [ebp-8] = PerceivedType read from the unit
        # component's change-only cache: 0 = OverheadVitalsBase never attaches the bar, [ebp-0x88] = display type,
        # [ebp-0x90] = attach type 0x10000B92); 0x8bed90 = a bar fade (FadeFloatyVitals). Match the IIDs with the
        # camp units' ids in server.log.
        bps.update({
            0x67B171: ("HOT CAMPS team colour (0xa7b0d0)", [("iid_lo", "[esi+100]"), ("iid_hi", "[esi+104]"),
                                                            ("team", "edi"), ("local_team", "ebx"),
                                                            ("relation", "[ebp+fffffff8]"), ("colour", "[ebp+fffffffc]")]),
            0x60F012: ("HOT CAMPS bar register: VitalDisplayType 0x10000831", [("iid_lo", "[esi+100]"),
                                                                                ("iid_hi", "[esi+104]"),
                                                                                ("display", "[ebp+8]")]),
            0x63A925: ("HOT CAMPS bar register: accepted (low byte)", [("accepted", "eax"), ("iid_lo", "[esi+100]"),
                                                                       ("iid_hi", "[esi+104]")]),
            0x650D31: ("HOT CAMPS bar push to Flash", [("iid_lo", "[esi+100]"), ("iid_hi", "[esi+104]"), ("add", "ebx"),
                                                       ("perceived", "[ebp+fffffff8]"), ("display", "[ebp+ffffff78]"),
                                                       ("attach", "[ebp+ffffff70]")]),
            0x4BED90: ("HOT CAMPS bar fade", [("iid_lo", "[esp+4]"), ("iid_hi", "[esp+8]"), ("fade_out", "[esp+c]")]),
            # 2026-10-28 15:00 (tester report 2026-10-28 15:00; camps-colour-bar-positions.md 8.2-8.3): 0xa50c60 runs
            # only when the FloatyVitals check 0x974940(entity, tag list 0x16016AC = {0x1000072C}) at 0xa50c3b returned
            # false (al = 0 clears "visible": no push). Not 0xa50c59 right after the call, which every bar entry hits
            # every frame. Expected from fase3-if on: lines for camp IIDs only while they phase in (and the Raider's
            # first second), then one "bar push to Flash" line each with perceived 0x100
            0x650C60: ("HOT CAMPS bar held back: FloatyVitals 0x1000072C false", [("iid_lo", "[esi+100]"),
                                                                                  ("iid_hi", "[esi+104]")]),
        })
    if "--ring" in sys.argv:
        # tester report 2026-10-29 15:30 (no turret warning ring; leash-recall-turretring-campicons.md 3): 0xa7ca20 =
        # the ring manager's entity-added hook (vtable 0x1605074 slot 1). edi = entity after 0xa7ca5a; al after
        # 0x9d0180(ent, 0x10) (Turret bit, unit component cache +0xA4); [ebp-1] = 0x10000C5D; al after 0x85c130 =
        # allied (1 = refused); [ebp-0x3C] = range r (f32 bits) and 0xa7cbab = registered
        bps.update({
            0x67CA60: ("HOT RING entity added", [("iid_lo", "[ebp+8]"), ("iid_hi", "[ebp+c]"), ("entity", "edi")]),
            0x67CA6B: ("HOT RING Turret bit (al 0 = refused)", [("al", "eax"), ("iid_lo", "[ebp+8]")]),
            0x67CA89: ("HOT RING 0x10000C5D (low byte 0 = refused)", [("c5d", "[ebp+ffffffff]"), ("iid_lo", "[ebp+8]")]),
            0x67CAA2: ("HOT RING allied (al 1 = refused)", [("al", "eax"), ("iid_lo", "[ebp+8]")]),
            0x67CB3C: ("HOT RING range", [("range_bits", "[ebp+ffffffc4]"), ("iid_lo", "[ebp+8]")]),
            0x67CBAB: ("HOT RING registered", [("iid_lo", "[ebp+8]"), ("iid_hi", "[ebp+c]")]),
            # tester report 2026-10-29 19:55 (ring still hidden; ca-ring-fog-bundles.md 1): the ring's phantom callback
            # 0xa3a5f0 (a unit enters / leaves r + 5.5 m): the entity, then the Player-bit test 0xa3a69d (al 0 = the
            # champion's unit flags lack 0x200000) and 0xa3a6c5 = entry +0x4C written (the ring may show)
            0x63A5F0: ("HOT RING phantom: unit enters / leaves", [("entity", "[esp+8]"), ("iid_lo", "[[esp+8]+100]"),
                                                                 ("iid_hi", "[[esp+8]+104]"), ("inside", "[esp+c]")]),
            0x63A69D: ("HOT RING phantom: Player bit 0x200000 (al 0 = missing)", [("al", "eax"),
                                                                                ("iid_lo", "[esi+100]")]),
            0x63A6C5: ("HOT RING phantom: our champion inside (ring may show)", [("inside", "[ebp+10]")]),
            # tester report 2026-10-29 21:10 (no phantom line at all; ca-fog-minimap-ring.md 2): 0xa7cbf4 = the phantom
            # built by 0xa2a710 (al 1 = yes); 0x852144 = the perception filter's top-byte-2 test on a body (al 1 = refused
            # unless `python ic.py patch` applied the fase3-io nop)
            0x67CBF4: ("HOT RING phantom built (al 1 = yes)", [("al", "eax"), ("iid_lo", "[ebp+8]")]),
            0x452144: ("HOT RING filter: body IID top byte 2 (al 1 = refused in the unpatched exe)",
                       [("al", "eax"), ("body_lo", "[ebx+8]"), ("body_hi", "[ebx+c]")]),
            # tester report 2026-10-29 23:03 (ring still hidden with the perception-filter patch;
            # ca-street-occluder-ring.md 2): the rest of the filter 0x852210 and the ring's draw path 0xa84fb0.
            # 0x852220: eax != 0 = refused by 0x852110 (no entity, 0x403 true, base filter); 0x85227a: PerceivedType
            # test al (0 = refused; mask 0x210000); 0x85228e: relation eax (4 same team, 1 neutral, 2 enemy / unknown)
            # against the mask 2, with the turret's team cached when the phantom was built and the body's team
            # (-1 = not cached). Then the draw: 0xa85294 = the ring effect DID read from 0x100000E4 (equal to the null
            # DID = nothing is drawn), 0xa852f5 = the ring object (0 = not created), 0xa8535a = a ring state change
            # (new / old: 1 approaching, 2 one of our minions, 3 two or more, 5 inside the range / targeted, 6 hidden)
            0x452220: ("HOT RING filter: base checks (eax != 0 = refused)", [("eax", "eax"), ("body_lo", "[edi+8]"),
                                                                             ("body_hi", "[edi+c]")]),
            0x45227A: ("HOT RING filter: PerceivedType (al 0 = refused)", [("al", "eax"), ("mask", "[esi+70]"),
                                                                           ("iid_lo", "[edi+100]")]),
            0x45228E: ("HOT RING filter: relation (refused when rel & 2 = 0)", [("rel", "eax"), ("turret_team", "[esi+68]"),
                                                                                ("body_team", "[esp+4]"),
                                                                                ("iid_lo", "[edi+100]")]),
            0x685294: ("HOT RING draw: effect DID from 0x100000E4", [("did", "ecx"), ("null_did", "[base+17759ec]"),
                                                                    ("option_186ce4f", "[base+146ce4f]")]),
            0x6852F5: ("HOT RING draw: ring object (0 = not created)", [("obj", "eax"), ("state", "edi")]),
            0x68535A: ("HOT RING state change", [("new", "edi"), ("old", "[esi]"), ("option_186ce4f", "[base+146ce4f]")]),
            # tester report 2026-10-30 11:23 (ring still hidden; ca-ring-phantom-strip.md 1): the 11:05 diag was attached
            # 64 s after the structures' bundles (11:06:21), so their registration was missed, and NOT ONE call of the
            # filter 0x852210 (0x452220 follows its first call unconditionally) came in 16 minutes. These say whether the
            # ring's phantom is created at all and whether ics units build their own perception phantoms:
            # 0xa2aaf6 = the physics service's create call in 0xa2a710 (eax = its function, the implementation to
            # decompile next; ebx = the turret entity); 0xa2aaf8 = right after it, the handle (4 words; equal to the
            # null id [0x1b67ee0..] = refused); 0x97978f = a unit component's own phantom (0x9793f0, key 0x4934ae2)
            # right after its create call, handle at [comp+0x38] (null id = not created)
            0x62AAF6: ("HOT RING phantom create call", [("create_fn", "eax"), ("service", "ecx"),
                                                        ("turret_lo", "[ebx+100]"), ("turret_hi", "[ebx+104]")]),
            0x62AAF8: ("HOT RING phantom create result (h = null = refused)",
                       [("h0", "[ebp+ffffff74]"), ("h1", "[ebp+ffffff78]"), ("h2", "[ebp+ffffff7c]"),
                        ("h3", "[ebp+ffffff80]"), ("null0", "[base+1767ee0]"), ("null2", "[base+1767ee8]")]),
            0x57978F: ("HOT RING unit perception phantom created (h = null = not created)",
                       [("iid_lo", "[[edi+4]+100]"), ("iid_hi", "[[edi+4]+104]"), ("h0", "[edi+38]"),
                        ("h2", "[edi+40]"), ("null0", "[base+1767ee0]"), ("null2", "[base+1767ee8]")]),
            # tester report 2026-10-30 12:05 (AGL walked to (88.6, 79.0), 6.4 m from the enemy lane turret, inside its
            # phantom box (half size 9 + 5.5), and still no filter line; ca-ring-bodies-strip-layers.md 1): the
            # phantom service's overlap-add 0x6385d0 (static VA) runs for every collidable a phantom of the service
            # starts to overlap, BEFORE the filter: 0x638636 = `test [ebp-0x18], eax` with eax = the phantom filter's
            # kind mask (vt+0x24 = filter +0xC: the ring's preset 0x5bb8a0 gives 0xA08 = Shadow solid entity 8 | Rigid
            # body character 0x200 | Rigid body sub entity 0x800, names from 0x5b1e60) and [ebp-0x18] the candidate's
            # world-object type (Havok property 0 read by 0x573050), [ebp-0x14] / [ebp-0x10] its IID (property 5).
            # kind & mask = 0 = refused without calling the filter 0x852210. No line naming the champion (body_lo 0x2)
            # = no body of our champion ever overlaps any phantom of the service.
            0x238636: ("HOT RING overlap candidate (kind & mask = 0: refused before the filter)",
                       [("kind", "[ebp+ffffffe8]"), ("mask", "eax"), ("body_lo", "[ebp+ffffffec]"),
                        ("body_hi", "[ebp+fffffff0]"), ("phantom", "[ebp+8]")]),
            # 0x976990 = a unit's collision component (entity +0xB8) adds / drops a script run's collision hold
            # (EnableCollision 0x97D720 / DisableCollision 0x97D860); its body (0x9793f0, key 0x4934AE2) exists only
            # while some hold is set
            0x576990: ("HOT RING collision hold (enable 1 / disable 0)", [("enable", "[esp+8]"),
                                                                          ("iid_lo", "[[ecx+4]+100]"),
                                                                          ("iid_hi", "[[ecx+4]+104]")]),
            # tester report 2026-10-30 13:18 (minions pass through each other, no hover outline; unit-separation-pick-
            # body.md 2): the movement module's character (replay module 1 attach 0x60bac0 -> 0x60a340 -> 0x5d1600, also
            # module 0x10000005) is created at 0x5d1600 (param = {entity, physics shape}; world = [ecx+38], 0 = none
            # yet); its rigid body, world-object type 0x200 "Rigid body character" (in the ring's mask 0xA08), is built
            # by 0x5c6320 only once the character has a world and passes the cell test 0x5c9b20 (flags byte 2 set = a
            # second, type 0x400 body: property 0x991 false). A "character object" line with no "character body" line
            # for the same IID = the unit never got the body the ring / the pick sweep would see
            0x1D1600: ("HOT RING character object created (movement module)", [("iid_lo", "[[[esp+4]]+100]"),
                                                                                ("iid_hi", "[[[esp+4]]+104]"),
                                                                                ("world", "[ecx+38]")]),
            0x1C6320: ("HOT RING character body built (type 0x200)", [("iid_lo", "[[ecx+10]+100]"),
                                                                       ("iid_hi", "[[ecx+10]+104]"),
                                                                       ("flags", "[ecx+20]")]),
        })
    if "--fogpoly" in sys.argv or "--nofog" in sys.argv:
        # tester report 2026-10-30 11:23 (the strip by the fence still black with the occluder pass patched out;
        # ca-ring-phantom-strip.md 2). --fogpoly: RenderFogEntities 0xaab3b0 draws every vision source as a fan from
        # its centre over its polygon ([entry] vertices of 0x30 bytes, count [entry+4], centre +0x44 / +0x48; the
        # collector 0xaa5170 starts it as an octagon of the radius). 0xaab4b6 = an entry about to be drawn; the
        # handler prints the source and its polygon in world metres (once per 4 s per source).
        # --nofog: EXPERIMENT, running memory only: on the first fog render (0xaae5b0) WorldRender +0x36 (EnableFog) is
        # set to 0 and the fog's clear colour 0x1b76958 (4 f32, 0 in .bss) to (0, 1, 0, 1), the colour 0x18706c8 the fan
        # gives a vertex left on the circle, so the fog texture is one flat value (the normal compose clears to white
        # 0x18706e8 first and draws the fans over it). If the strip by the fence is still black, it is NOT the fog.
        if "--fogpoly" in sys.argv:
            bps[0x6AB4B6] = ("FOGPOLY source polygon", [])
        if "--nofog" in sys.argv:
            bps[0x6AE5B0] = ("FOGPOLY fog render (nofog experiment)", [])
    if "--layers" in sys.argv:
        # tester report 2026-10-30 12:05 (the strip stays black with --nofog; ca-ring-bodies-strip-layers.md 2): the
        # WorldRender draw toggles registered by 0x7f1310 (byte fields of the object at [[0x1b73518] + 0xDC]):
        # +0x2E AllowOutdoorMultiPassShadows, +0x30 DrawLandscape, +0x32 DrawFloor, +0x35 DrawFrills, +0x37 / +0x38
        # / +0x39 Distance / Ground / Mask fog, +0x3A / +0x3B / +0x3C / +0x3D Dynamic / Static / Opaque /
        # Translucent entities, +0x3E DrawCellMeshes. Stepped from the fog render 0xaae5b0 (every frame; EnableFog
        # +0x36 is never touched by this experiment, so it keeps firing)
        bps[0x6AE5B0] = ("FOGPOLY fog render (layers experiment)", [])
    if "--strip" in sys.argv:
        # tester report 2026-10-30 13:18 (the strip went away only with DrawStaticEntities off, not with Opaque /
        # Translucent entities off; docs/re-notes/ca-strip-static-shadow.md): 0x78165c = the model node's attach
        # (0x781640) calling RenderComponent 0x6226e0 with ecx = the render component (node +0x264), esi = the node;
        # the component's entity is [rc+4] (IID q[ent+0x100], world state [ent+0x110]) and its node [rc+0xA0]. A node
        # with bit 0x800 in its flags +0x220 is skipped by every draw / list pass (0x77DF70 is what the property
        # 0x2A1 path sets). Steps run from the fog render 0xaae5b0 (every frame), like --layers
        bps[0x38165C] = ("STRIP model node attached (0x78165c)", [])
        bps[0x6AE5B0] = ("STRIP fog render (step clock)", [])
    if "--visibility" in sys.argv:
        # 2026-10-25 (map-object-census.md fix 4): which world objects the client decides to draw. 0x61cb30 draws an
        # object only if 0x2A1 && 0x76A && !0x90F (ecx = entity, its world state at +0x110); 0x544a50 builds a static
        # from the layout (counted around Coast City's hole at (80, 70)). The socket covers' world states:
        # 0x2E0000E3 (Crime Alley), 0x2E0003F0 (Gotham Divided)
        bps.update({
            0x21CB30: ("HOT VIS draw check (0x61cb30)", [("entity", "ecx"), ("world_state", "[ecx+110]")]),
            0x144A50: ("HOT VIS static built (0x544a50)", [("ecx", "ecx"), ("arg", "[esp+4]")]),
        })
    if "--emotes" in sys.argv:
        # 2026-10-24 (tester: Alt+Numpad emotes send nothing; docs/re-notes/emotes.md): where the emote key dies
        bps.update({
            0x68A8E0: ("EMOTE input handler (emote action)", [("action", "[esp+4]")]),
            0x60AB70: ("EMOTE action -> emote code", []),
            0x564060: ("EMOTE run the player's emote script method", [("player", "ecx"), ("code", "[esp+4]")]),
            0x0A1C90: ("EMOTE script RPC native (0x9F builder)", []),
            0x1624F0: ("EMOTE 0x9F event built", []),
        })
    if "--graph" in sys.argv:
        # 2026-10-23 (docs/re-notes/client-skill-instances.md 3): where a champion's skill animation dies after its
        # 0x8D scriptlet started (diag --scripts: every order accepted, result 0, yet no animation on screen).
        bps.update({
            0x2279D0: ("GRAPH 0x8d scriptlet started", [("did", "[esp+8]")]),
            0x5789C0: ("GRAPH client slot script added", [("did", "[esp+4]")]),
            0x576A80: ("GRAPH script instance appended", []),
            0x616E60: ("GRAPH 0x20C9 received", []),
            0x56DED0: ("GRAPH event fan-out by script DID", [("event", "[esp+4]"), ("did", "[esp+8]")]),
            # graph-event action 0x672930: [eax+4] = the behaviour-graph component (0 = silent no-op)
            0x27299D: ("GRAPH graph-event action: graph component", [("component", "[eax+4]")]),
            0x2729A9: ("GRAPH event about to reach the graph", [("event", "esi")]),
            0x15BD30: ("GRAPH graph raise: entity flags (+0x118)", [("flags", "[[ecx+4]+118]")]),
            0x15BD43: ("GRAPH flag 0x40 set: dropped unless bit 8", []),
            0x15BD82: ("GRAPH queued (graph not ready)", []),
            0x15BD9F: ("GRAPH delivered to the graph", []),
            0x15AF83: ("GRAPH event index in the graph (-1 = unknown event)", [("index", "eax")]),
            # fase3-hk: a 0x8D entry with a live instance number signals that run (StopScriptletKey on the wire, P)
            0x17B510: ("GRAPH 0x8d signals a live scriptlet run (stop)", []),
            0x17C4B0: ("GRAPH scriptlet run signalled by key", []),
        })
    if "--orders" in sys.argv:
        # 2026-11-03 (anim-24, docs/reverse-engineering.md "Every 0x8D replaces the server's runs"): the 0x2073 handler
        # 0xA883F0 starts its list directly (0xA22DA0, no stop-all) only when the object's +0x110 equals the global
        # 0x1B759EC; logs both for every 0x8D list (0x627E20: ecx = script component, [ecx+4] = its object) and 0x2073.
        bps.update({
            0x227E20: ("ORDERS 0x8d list", [("iid_lo", "[[ecx+4]+100]"), ("obj_110", "[[ecx+4]+110]"),
                                            ("none_1b759ec", "[base+17759ec]")]),
            0x6883F0: ("ORDERS 0x2073 received", [("iid_lo", "[[esp+4]+100]"), ("obj_110", "[[esp+4]+110]"),
                                                  ("none_1b759ec", "[base+17759ec]")]),
            0x622DA0: ("ORDERS 0x2073 started directly (no stop-all)", []),
            0x688423: ("ORDERS 0x2073 went to the other manager's list (not started here)", []),
        })
    if "--particles" in sys.argv:
        # 2026-11-04 (anim-29, docs/reverse-engineering.md "Energy Cannon's explosion"): the scriptlet action type 0x11
        # (particle emitter, vtable 0x15CECD8, execute slot +0x28 = 0x67F650): one line per emitter the client starts,
        # with a few words of the action (one of them is the particle record, e.g. 0x18000BDB for Blue Beetle's Q)
        bps.update({
            0x27F650: ("PARTICLES type 0x11 emitter started", [("a20", "[ecx+20]"), ("a24", "[ecx+24]"),
                                                               ("a28", "[ecx+28]"), ("a2c", "[ecx+2c]"),
                                                               ("a30", "[ecx+30]"), ("a34", "[ecx+34]")]),
        })
    if "--anims" in sys.argv:
        # Havok behavior linking (static analysis 2026-10-18, function rva 0x899de0, the one that logs
        # "Animation loaded directly from clip's animationName"): for each clip generator (ebp) it calls the
        # asset loader with animationName ([ebp+0x60] & ~1, in esi); right after the call eax is the
        # hkaAnimationBinding (or 0) and [eax+0xc] the hkaSplineCompressedAnimation.
        bps[RVA_ANIM_LINK] = ("ANIM link", [])
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

        def cstr(self, addr, limit=200):
            if not addr:
                return ""
            raw = self.read(addr, limit)
            return raw.split(b"\0")[0].decode("ascii", "replace")

        def log_anim_link(self, tid):
            """One line per linked clip: ANIM clip=<name> anim=<animationName> binding=.. dur=.. tracks=..
            frames=.. blocks=.. data=<size> head=<first 32 data bytes hex>. hkaSplineCompressedAnimation fields
            as in uesrv/havok_anim.py (duration @0xc, tracks @0x10, numFrames @0x28, numBlocks @0x2c,
            data hkArray @0x74)."""
            c = self.ctx(tid)
            clip = self.cstr(self.u32(c.Ebp + 0x20) & ~1)
            name = self.cstr(c.Esi)
            binding = c.Eax
            line = f"ANIM clip={clip!r} anim={name!r} binding={binding:#x}"
            if binding:
                anim = self.u32(binding + 0xC)
                if anim:
                    dur = struct.unpack("<f", self.read(anim + 0xC, 4))[0]
                    tracks, frames, blocks = self.u32(anim + 0x10), self.u32(anim + 0x28), self.u32(anim + 0x2C)
                    data, size = self.u32(anim + 0x74), self.u32(anim + 0x78)
                    blob = self.read(data, size) if data and 0 < size < 0x400000 else b""
                    head = blob[:32].hex()
                    crc = zlib.crc32(blob) & 0xFFFFFFFF
                    line += (f" anim_obj={anim:#x} dur={dur:.4f} tracks={tracks} frames={frames} "
                             f"blocks={blocks} data={size} head={head} crc={crc:08x}")
            T.log(line)

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

        # ---- --mapload (docs/re-notes/map-load-holes.md) -------------------------------------------------------
        ml_rvas = frozenset(r for r, (n, _) in bps.items() if n.startswith("MAP "))
        ml_retired = set()          # VAs whose int3 is no longer re-armed (budget used up)
        ml_hits = {}                # rva -> hits
        ml_budget = {RVA_DB_LOADED: 300000, RVA_DB_FAILED: 200000, RVA_DB_PENDING: 50000}
        ml_fail = {}                # (kind, db type, DID) -> [count, caller, context]
        ml_block = {}               # thread -> "13bb" (landblock being built)
        ml_static = {}              # thread -> (ws, type, iid, pos) of the static entry being checked
        ml_batch = {}               # thread -> terrain batch being built
        ml_lines = set()            # texts already logged (terrain batches, blocks)
        ml_drops = {}               # (ws, type) -> [count, first iid, first pos]
        ml_loads = {}               # DID prefix -> loads (with --mapload-all)
        ml_invalid = None
        ml_tsv = None
        ml_filled = set()

        def write(self, addr, data):
            # a retired breakpoint keeps its original byte (the tracer re-arms by writing 0xCC after the step)
            if data == b"\xCC" and addr in self.ml_retired:
                return
            super().write(addr, data)

        def ml_db(self, handle):
            """(db type, DID) of a resolver handle {db type or db object, DID}."""
            return self.u32(handle), self.u32(handle + 4)

        def ml_type_name(self, dbt, did):
            name = DB_TYPE_NAMES.get(dbt) if dbt < 0x100 else None
            return f"db {dbt:#x} ({name})" if name else (f"db {dbt:#x}" if dbt < 0x100 else f"prefix {did >> 24:#04x}")

        def ml_callers(self, ebp):
            """Return addresses up the ebp chain from the resolver's frame (wrapper 0x43a1e0 skipped)."""
            out = []
            for _ in range(5):
                if not ebp:
                    break
                try:
                    ret, ebp = self.u32(ebp + 4), self.u32(ebp)
                except OSError:
                    break
                r = ret - self.base
                if not 0x1000 <= r < 0x1100000:
                    break
                if r != RVA_DB_WRAPPER_RET:
                    out.append(r)
            first = next((MAPLOAD_CALLERS[r] for r in out if r in MAPLOAD_CALLERS), None)
            chain = "<".join(f"{r + 0x400000:#x}" for r in out[:4]) or "?"
            return f"{first} [{chain}]" if first else chain

        def ml_context(self, tid):
            st = self.ml_static.get(tid)
            if st:
                ws, typ, iid, pos = st
                return f"static t{typ} ws {ws:#x} iid {iid:#x} at {pos}"
            blk = self.ml_block.get(tid)
            return f"landblock {blk}" if blk else ""

        def ml_entry_pos(self, entry):
            """Position of a statics entry: the first (x, y, z) in it that looks like a point of the block."""
            raw = self.read(entry, 0x70)
            for off in range(0, 0x64, 4):
                x, y, z = struct.unpack_from("<fff", raw, off)
                if -1.0 <= x <= 161.0 and -1.0 <= y <= 161.0 and 150.0 <= z <= 300.0 and (x or y):
                    return f"({x:.2f}, {y:.2f}, {z:.2f})"
            return "(?)"

        def ml_retire(self, va, rva):
            n = self.ml_hits[rva] = self.ml_hits.get(rva, 0) + 1
            if n == self.ml_budget.get(rva, 1 << 62):
                self.ml_retired.add(va)
                T.log(f"MAP: breakpoint rva {rva:#x} retired after {n} hits (the game slows down otherwise)")

        def ml_position_block(self, pos):
            """Landblock "13bb" of a Position (+4 region, +8 x, +9 y)."""
            raw = self.read(pos + 8, 2)
            return f"{raw[0]:02x}{raw[1]:02x}"

        def ml_fill(self, obj):
            """--mapload-fill: raise the dampener-socket vertices of the terrain object's height arrays (LOD 0 at
            +0x3c, LOD 1 at +0xe0: {u16 *, count 0x441}; z = u16 * 2000 / 65535, vertex (x, y) = [x / 5 * 33 + y / 5])
            to the median of their unlowered neighbours, and level the normals around them (+0xc4 / +0x168, 3 f32
            each) when they look like unit vectors. Only vertices 15-25 m below every axis neighbour are touched."""
            if obj in self.ml_filled:
                return
            self.ml_filled.add(obj)
            for h_off, n_off in ((0x3C, 0xC4), (0xE0, 0x168)):
                ptr, cnt = self.u32(obj + h_off), self.u32(obj + h_off + 4)
                if cnt != 0x441 or not ptr:
                    continue
                h = list(struct.unpack("<1089H", self.read(ptr, 2178)))
                changed = []
                for x, y in FILL_SPOTS:
                    i, j = int(x / 5), int(y / 5)
                    if not (0 < i < 32 and 0 < j < 32):
                        continue
                    v = h[i * 33 + j]
                    around = [h[(i + di) * 33 + (j + dj)] for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                    high = [a for a in around if a > v]
                    # 1 m = 32.8 units; a socket vertex sits ~20 m (650 units) below the street
                    if len(high) < 2 or not all(450 <= a - v <= 820 for a in high):
                        continue
                    ring = sorted(h[(i + di) * 33 + (j + dj)] for di in (-1, 0, 1) for dj in (-1, 0, 1)
                                  if (di or dj) and h[(i + di) * 33 + (j + dj)] - v >= 450)
                    new = ring[len(ring) // 2]
                    self.write(ptr + 2 * (i * 33 + j), struct.pack("<H", new))
                    h[i * 33 + j] = new
                    changed.append((x, y, v * 2000 / 65535, new * 2000 / 65535, i, j))
                if not changed:
                    continue
                T.log(f"MAP FILL: terrain object {obj:#x} heights +{h_off:#x}: " + ", ".join(
                    f"({x:.0f}, {y:.0f}) {a:.2f} -> {b:.2f} m" for x, y, a, b, _, _ in changed))
                nptr, ncnt = self.u32(obj + n_off), self.u32(obj + n_off + 4)
                if ncnt != 0x441 or not nptr:
                    T.log(f"MAP FILL: no normals array at +{n_off:#x} (count {ncnt:#x}); heights only")
                    continue
                sx, sy, sz = struct.unpack("<fff", self.read(nptr + 12 * (2 * 33 + 2), 12))
                if abs(sx * sx + sy * sy + sz * sz - 1.0) > 0.05:
                    T.log(f"MAP FILL: normals at +{n_off:#x} are not unit f32 vectors ({sx:.3f} {sy:.3f} {sz:.3f}); "
                          "heights only")
                    continue
                done = set()
                for _, _, _, _, i, j in changed:
                    for di in (-1, 0, 1):
                        for dj in (-1, 0, 1):
                            a, b = i + di, j + dj
                            if (a, b) in done or not (0 < a < 32 and 0 < b < 32):
                                continue
                            done.add((a, b))
                            zx = (h[(a + 1) * 33 + b] - h[(a - 1) * 33 + b]) * 2000 / 65535 / 10.0
                            zy = (h[a * 33 + b + 1] - h[a * 33 + b - 1]) * 2000 / 65535 / 10.0
                            ln = (zx * zx + zy * zy + 1.0) ** 0.5
                            self.write(nptr + 12 * (a * 33 + b), struct.pack("<fff", -zx / ln, -zy / ln, 1.0 / ln))
                T.log(f"MAP FILL: {len(done)} normals at +{n_off:#x} recomputed")

        def ml_flush_batch(self, tid, ok):
            b = self.ml_batch.pop(tid, None)
            if not b:
                return
            layers = "; ".join(
                f"type {t:#x}" + ("" if found else " NOT IN THE REGION TABLE") +
                ("" if not tex else " [" + ", ".join(f"{slot} {d:#x} {'ok' if r else 'MISSING'}" for slot, d, r in tex) + "]")
                for t, found, tex in b["layers"])
            bad = (not ok or not b["mat_ok"] or not b.get("mask_ok", True)
                   or any(not f or any(not r for _, _, r in tex) for _, f, tex in b["layers"]))
            text = (f"block {b['block']} batch {b['index']}: material {b['mat']:#x} {'ok' if b['mat_ok'] else 'MISSING'}, "
                    f"mask {b.get('mask', 0):#x} {'ok' if b.get('mask_ok') else 'MISSING'}, layers: {layers or '-'}; "
                    f"built {'yes' if ok else 'NO (the whole block terrain is dropped)'}")
            if text not in self.ml_lines:
                self.ml_lines.add(text)
                T.log(("MAP TERRAIN PROBLEM " if bad else "MAP terrain ") + text)

        def mapload_hit(self, tid, va, rva):
            c = self.ctx(tid)
            if self.ml_invalid is None:
                self.ml_invalid = self.u32(self.base + RVA_DID_INVALID)
            if rva in (RVA_DB_FAILED, RVA_DB_PENDING, RVA_DB_LOADED):
                self.ml_retire(va, rva)
                dbt, did = self.ml_db(c.Ebx)
                if did in (0, self.ml_invalid):
                    return
                if rva == RVA_DB_LOADED:
                    pre = did >> 24
                    self.ml_loads[pre] = self.ml_loads.get(pre, 0) + 1
                    if self.ml_tsv is None:
                        self.ml_tsv = open(os.path.join(cfg.log_dir, "mapload.tsv"), "w", encoding="utf-8")
                        self.ml_tsv.write("time\tthread\tdb_type\tdid\tresult\tcaller\tcontext\n")
                    import time
                    self.ml_tsv.write(f"{time.strftime('%H:%M:%S')}\t{tid}\t{dbt:#x}\t{did:#010x}\t"
                                      f"{'ok' if c.Eax else 'NOT FOUND'}\t{self.ml_callers(c.Ebp)}\t"
                                      f"{self.ml_context(tid)}\n")
                    return
                kind = "pending" if rva == RVA_DB_PENDING else ("finaliser failed" if c.Esi else "NOT FOUND")
                key = (kind, dbt, did)
                rec = self.ml_fail.get(key)
                if rec is None:
                    rec = self.ml_fail[key] = [0, self.ml_callers(c.Ebp), self.ml_context(tid)]
                rec[0] += 1
                if rec[0] in (1, 10, 100, 1000, 10000):
                    more = "" if rec[0] == 1 else f" (asked {rec[0]} times so far)"
                    T.log(f"MAP {kind}: {did:#010x} {self.ml_type_name(dbt, did)} caller {rec[1]}"
                          + (f" while building {rec[2]}" if rec[2] else "") + more)
                return
            if rva in (0x13E290, 0x314280):
                blk = self.ml_position_block(self.u32(c.Esp + 4))
                self.ml_block[tid] = blk
                text = f"block {blk}: {'LandBlockMesh (terrain mesh / collision)' if rva == 0x13E290 else 'landscape render build'}"
                if text not in self.ml_lines:
                    self.ml_lines.add(text)
                    T.log("MAP " + text)
                return
            if rva == 0x148645:
                e = c.Esi
                iid = self.u32(e + 0x2C)
                self.ml_static[tid] = (self.u32(e + 0x30), self.u32(e + 0x20), iid, self.ml_entry_pos(e))
                self.ml_block[tid] = f"{(iid >> 4) & 0xFFFF:04x}"
                return
            if rva in (0x14864E, 0x148695):
                if c.Eax & 0xFF:
                    return
                ws, typ, iid, pos = self.ml_static.get(tid) or (self.u32(c.Esi + 0x30), self.u32(c.Esi + 0x20),
                                                                self.u32(c.Esi + 0x2C), "(?)")
                why = ("dropped: world state not loaded or creation type 0" if rva == 0x14864E
                       else "skipped by the block's filter (vt+0x18)")
                rec = self.ml_drops.setdefault((ws, typ, why), [0, iid, pos])
                rec[0] += 1
                # waypoints (type 21, world state 0x2E000000) are expected to drop: only the first is shown
                if rec[0] == 1:
                    T.log(f"MAP static {why}: t{typ} ws {ws:#x} iid {iid:#x} at {pos}"
                          + (" (waypoint; further ones only counted)" if typ == 0x15 else ""))
                return
            if rva == 0x1486AB:
                self.ml_static.pop(tid, None)
                return
            if rva == 0x313C3C:
                self.ml_flush_batch(tid, False) if tid in self.ml_batch else None
                e = c.Edi
                self.ml_batch[tid] = {"block": self.ml_block.get(tid, "?"), "index": self.u32(c.Ebp + 0x10),
                                      "mat": self.u32(e + 0x68), "mat_ok": bool(c.Eax), "layers": [], "edi": e}
                if not c.Eax:
                    self.ml_flush_batch(tid, False)
                return
            b = self.ml_batch.get(tid)
            if rva == 0x313CCC and b:
                b["mask"], b["mask_ok"] = self.u32(b["edi"] + 0x64), bool(c.Eax)
            elif rva == 0x313D3E and b:
                # type id = palette[(layer index [batch+0] [esi]) * 0x14] of the block ([[ebp+0xc]+4])
                k = self.u32(self.u32(b["edi"]) + 4 * c.Esi)
                t = self.u32(self.u32(self.u32(c.Ebp + 0xC) + 4) + 0x14 * k)
                b["layers"].append((t, bool(c.Eax & 0xFF), []))
            elif rva in (0x313852, 0x3138BD, 0x313928) and b and b["layers"]:
                off, slot = {0x313852: (0x10, "A"), 0x3138BD: (0x14, "B"), 0x313928: (0x58, "C")}[rva]
                b["layers"][-1][2].append((slot, self.u32(c.Edi + off), bool(c.Eax)))
            elif rva in (0x313D97, 0x313DB5):
                self.ml_flush_batch(tid, rva == 0x313D97)
            elif rva == 0x312860 and mapload_fill:
                self.ml_fill(self.u32(c.Esp + 4))
            elif rva == 0x13BB00 and mapload_fill:
                self.ml_fill(self.u32(c.Esp + 8))

        def mapload_summary(self):
            T.log("===== MAP summary")
            for (kind, dbt, did), (n, caller, ctx) in sorted(self.ml_fail.items(), key=lambda kv: -kv[1][0]):
                T.log(f"MAP {kind} x{n}: {did:#010x} {self.ml_type_name(dbt, did)} caller {caller}"
                      + (f" while building {ctx}" if ctx else ""))
            for (ws, typ, why), (n, iid, pos) in sorted(self.ml_drops.items(), key=lambda kv: -kv[1][0]):
                T.log(f"MAP static {why} x{n}: t{typ} ws {ws:#x} (first iid {iid:#x} at {pos})")
            if self.ml_loads:
                T.log("MAP loads per DID prefix: " + " ".join(f"{p:#04x}={n}" for p, n in sorted(self.ml_loads.items())))
            if not self.ml_fail and not self.ml_drops:
                T.log("MAP: nothing failed to load (was the diagnostic started before Launch?)")
            if self.ml_tsv:
                self.ml_tsv.close()

        LAYERS = [(0x30, "DrawLandscape"), (0x3B, "DrawStaticEntities"), (0x3A, "DrawDynamicEntities"),
                  (0x3C, "DrawOpaqueEntities"), (0x3D, "DrawTranslucentEntities"), (0x35, "DrawFrills"),
                  (0x3E, "DrawCellMeshes"), (0x32, "DrawFloor"), (0x39, "EnableMaskFog"), (0x38, "EnableGroundFog"),
                  (0x37, "EnableDistanceFog"), (0x2E, "AllowOutdoorMultiPassShadows")]

        def layers_step(self):
            """--layers: one WorldRender draw toggle off at a time, 5 s each, then all back (running memory only)."""
            import time
            now = time.monotonic()
            st = getattr(self, "layers_state", None)
            if st is None:
                wr = self.u32(self.u32(self.base + 0x1773518) + 0xDC)
                if not wr:
                    return
                saved = {off: self.read(wr + off, 1) for off, _ in self.LAYERS}
                st = self.layers_state = {"wr": wr, "saved": saved, "i": -1, "t": now, "done": False}
                T.log(f"LAYERS WorldRender {wr:#x}: " + " ".join(f"{n}={saved[o].hex()}" for o, n in self.LAYERS)
                      + " (01 = on). Stand still where the strip shows; from 10 s on, each step switches ONE toggle "
                      "off for 5 s")
                st["t"] = now + 5.0
            if st["done"] or now - st["t"] < 5.0:
                return
            wr, saved = st["wr"], st["saved"]
            if st["i"] >= 0:
                off, _name = self.LAYERS[st["i"]]
                self.write(wr + off, saved[off])
                self.__dict__.get("saved_writes", {}).pop(wr + off, None)
            st["i"] += 1
            st["t"] = now
            if st["i"] >= len(self.LAYERS):
                st["done"] = True
                T.log("LAYERS done: every toggle is back as it was")
                return
            off, name = self.LAYERS[st["i"]]
            # 2026-10-30 (tester report 13:00): through restore_on_detach, so a Ctrl+C in the middle of a step puts
            # the toggle back when the tracer detaches
            self.restore_on_detach(wr + off, b"\x00")
            T.log(f"LAYERS step {st['i'] + 1}/{len(self.LAYERS)}: {name} (WorldRender +{off:#x}) OFF for 5 s")

        # --strip (tester report 2026-10-30 13:18; docs/re-notes/ca-strip-static-shadow.md). Graphics settings: the
        # globals 0x7c55e0 registers (static VA, size, value written, name); the client's settings watcher (0x7c83d0)
        # and the shadow passes (0x794280: no shadow map when 0x1865744 == 0) read them every frame
        STRIP_SETTINGS = [(0x1865744, 4, 0, "Render.ShadowMapQuality = 0 (dynamic shadow maps off)"),
                          (0x1865778, 1, 0, "Render.EnableSSAO = 0 (screen-space ambient occlusion off)"),
                          (0x18656D8, 4, 0, "Render.SurfaceReflections = 0 (reflections off)"),
                          (0x186575A, 1, 0, "Render.EnableDecals = 0 (decals off)"),
                          (0x1865758, 1, 0, "Render.EnableNonGlobalLights = 0 (point / spot lights off)"),
                          (0x1865759, 1, 0, "Render.EnableUniqueLights = 0")]
        # statics of 13BB by entry index (IID = index | 0x01113BB0 << 32): the pieces whose box touches the strip
        STRIP_NAMED = [("the 4 fence pieces on the strip's north edge (#0x24c, #0x246, #0x243, #0xd7)",
                        (0x24C, 0x246, 0x243, 0xD7)),
                       ("fence #0x24c 0x2E001324 (71.5, 83.65), x 71.1-74.3", (0x24C,)),
                       ("fence #0x246 0x2E0012F6 (74.5, 83.65), x 74.1-78.4", (0x246,)),
                       ("fence #0x243 0x2E0004D7 (78.7, 83.66), x 78.3-81.7", (0x243,)),
                       ("chain-link fence #0xd7 0x2E00097C (83.9, 83.46), x 83.8-88.0", (0xD7,)),
                       ("street collision piece #0xb8 0x2E001207 (whole lane)", (0xB8,)),
                       ("rain volume #0xbb 0x2E001185 (whole map)", (0xBB,)),
                       ("lamp + light #0x11e 0x2E001219 (64.5, 83.2)", (0x11E,))]
        STRIP_BITS = 10                         # 13BB entry indices go up to ~0x2a0
        # --strip2 (tester report 2026-10-30 19:46, docs/re-notes/ca-strip-two-bit-candidates.md): the strip went away in
        # the "bit 9" step and in one other bit step the tester did not note, so its index is 0x200 | (1 << k). The 13BB
        # entries with exactly two bits, 9 and one more, that the client instantiates (types 7 / 8 / 21; 0x280 is a
        # type-16 start point), nearest first; then the bit-9 statics next to the strip (in case a step was missed), then
        # two controls. One at a time, 6 s each
        STRIP2_CANDIDATES = [
            ("#0x208 0x2E000800 (85.56, 86.54) scale 1.15: the garden bush north of the east end of the strip "
             "(breakable)", (0x208,)),
            ("#0x240 0x2E0004D6 (53.34, 85.63): west garden side fence", (0x240,)),
            ("#0x201 0x2E0012EC (19.04, 62.13): breakable crate", (0x201,)),
            ("#0x202 0x2E0012F0 (26.40, 64.01): breakable crate", (0x202,)),
            ("#0x204 0x2E0012EF (27.40, 87.90): breakable crate", (0x204,)),
            ("#0x243 0x2E0004D7 (78.68, 83.66): the lane fence piece over the strip (bits 0, 1, 6, 9)", (0x243,)),
            ("#0x246 0x2E0012F6 (74.48, 83.65): lane fence piece (bits 1, 2, 6, 9; breakable)", (0x246,)),
            ("#0x24c 0x2E001324 (71.48, 83.65): lane fence piece (bits 2, 3, 6, 9; breakable)", (0x24C,)),
            ("#0x247 0x2E0012F6 (71.54, 87.85): garden fence (bits 0, 1, 2, 6, 9)", (0x247,)),
            ("#0x207 0x2E000821 (78.85, 87.40): garden bush (bits 0, 1, 2, 9; breakable)", (0x207,)),
        ]
        # --strip3 (tester recording 2026-10-30 21:33, docs/re-notes/ca-strip-two-bit-candidates.md 8): the strip went
        # away only in the --strip2 controls (every bit-9 static: 51 render nodes; every static), never with one of the
        # candidates (#0x208 / #0x201 / #0x202 / #0x204 / #0x246 / #0x24c / #0x247 / #0x207 had NO recorded node: the
        # breakables, world states with fracture data 0x800, never pass the attach probe; #0x240 / #0x243 did and
        # changed nothing). The bit-9 statics that are not breakables, from 0x820113BB (index: world state, x, y, z),
        # nearest to the strip (x 70-85.5, y 81.8-83.4) first; the diag numbers the RECORDED ones in this order
        STRIP3_INFO = {
            0x243: (0x2E0004D7, 78.68, 83.66, 199.98), 0x262: (0x2E0005D6, 78.01, 85.82, 201.50),
            0x23F: (0x2E0004D6, 83.31, 90.95, 199.98), 0x258: (0x2E0005D6, 62.07, 85.37, 201.50),
            0x242: (0x2E0004D6, 59.54, 83.67, 199.98), 0x269: (0x2E0005D6, 96.20, 85.76, 202.28),
            0x209: (0x2E0012E8, 98.09, 83.22, 200.09), 0x274: (0x2E0005D6, 98.38, 84.24, 201.33),
            0x241: (0x2E0004D6, 56.23, 83.66, 199.98), 0x273: (0x2E0005D6, 81.80, 97.87, 202.04),
            0x275: (0x2E0005D6, 61.39, 69.83, 202.46), 0x26A: (0x2E0005D6, 65.18, 97.59, 203.99),
            0x25F: (0x2E0005D6, 71.19, 66.63, 206.25), 0x25A: (0x2E0005D6, 68.01, 65.78, 206.25),
            0x256: (0x2E0012FF, 53.62, 83.66, 199.98), 0x26B: (0x2E0005D6, 95.99, 68.76, 203.97),
            0x240: (0x2E0004D6, 53.34, 85.63, 199.98), 0x272: (0x2E0005D6, 98.44, 96.79, 202.04),
            0x25E: (0x2E0005D6, 56.96, 66.05, 206.25), 0x257: (0x2E0005D6, 48.43, 94.63, 201.50),
            0x263: (0x2E0005D6, 48.66, 69.15, 203.24), 0x268: (0x2E0005D6, 109.92, 93.63, 201.50),
            0x20F: (0x2E0012E8, 115.49, 83.66, 200.09), 0x270: (0x2E0005D6, 117.10, 81.79, 203.50),
            0x261: (0x2E0005D6, 36.01, 84.27, 206.25), 0x22C: (0x2E001322, 120.06, 88.45, 200.09),
            0x20B: (0x2E0012E8, 122.92, 70.86, 200.09), 0x20A: (0x2E0012E8, 127.01, 84.70, 200.09),
            0x260: (0x2E0005D6, 32.24, 64.08, 206.25), 0x25D: (0x2E0005D6, 27.68, 90.11, 206.25),
            0x271: (0x2E0005D6, 128.68, 83.05, 203.50), 0x22A: (0x2E00131F, 126.72, 63.07, 187.61),
            0x259: (0x2E0005D6, 28.35, 62.99, 206.25), 0x22B: (0x2E001313, 130.38, 94.62, 200.10),
            0x26F: (0x2E0005D6, 134.23, 87.41, 201.81), 0x284: (0x2E001402, 17.50, 77.50, 199.78),
            0x25C: (0x2E0005D6, 21.59, 59.34, 206.25), 0x20C: (0x2E0012E8, 138.49, 91.67, 200.09),
            0x26C: (0x2E0005D6, 136.80, 64.79, 203.80), 0x265: (0x2E0005D6, 14.65, 91.01, 206.25),
            0x278: (0x2E000A3B, 142.50, 77.50, 200.12), 0x23C: (0x2E00132F, 11.62, 77.57, 200.37),
            0x26E: (0x2E0005D6, 145.13, 89.11, 202.64), 0x264: (0x2E0005D6, 10.18, 62.80, 201.81),
            0x228: (0x2E001237, 145.60, 60.98, 200.02), 0x267: (0x2E0005D6, 8.58, 64.45, 200.20),
            0x25B: (0x2E0005D6, 5.69, 92.00, 206.25), 0x26D: (0x2E0005D6, 147.82, 61.89, 203.99),
            0x229: (0x2E00131F, 146.04, 53.77, 190.66), 0x20D: (0x2E0012E8, 152.10, 91.75, 200.09),
            0x283: (0x2E00036E, 0.03, 70.23, 200.11), 0x20E: (0x2E0012E8, 159.82, 82.45, 200.09),
            0x227: (0x2E001312, 157.44, 59.41, 200.12),
        }
        STRIP3_CODE_BITS = 6                    # numbers #1..#63

        def strip3_label(self, idx):
            ws, x, y, z = self.STRIP3_INFO.get(idx, (0, 0.0, 0.0, 0.0))
            return f"#{idx:#x} {ws:#010x} ({x:.2f}, {y:.2f}, {z:.2f})" if ws else f"#{idx:#x} (not in the table)"

        def strip3_steps(self):
            """--strip3: number the recorded bit-9 statics that have a live node (table order, then the rest by
            index), log the list, and return the steps: control, 12 code steps, one per static."""
            rcs = self.__dict__.get("strip_rcs", {})
            live = []
            for idx in rcs:
                if not idx & 0x200:
                    continue
                for rc in rcs[idx]:
                    try:
                        node = self.u32(rc + 0xA0)
                        if node and self.u32(node + 0x264) == rc:
                            live.append(idx)
                            break
                    except OSError:
                        continue
            order = list(self.STRIP3_INFO)
            live.sort(key=lambda i: (order.index(i) if i in order else len(order), i))
            num = {idx: n + 1 for n, idx in enumerate(live)}
            self.strip3_num = num
            T.log(f"STRIP3 list: {len(live)} bit-9 statics with a render node (#n = number, code = n in binary):")
            for idx in live:
                T.log(f"STRIP3   #{num[idx]:2d} code {num[idx]:06b}: {self.strip3_label(idx)}")
            steps = [("statics", f"control: ALL {len(live)} listed bit-9 statics (#1-#{len(live)})",
                      lambda i, s=frozenset(live): i in s)]
            for want in (1, 0):
                for k in range(self.STRIP3_CODE_BITS):
                    group = [i for i in live if (num[i] >> k) & 1 == want]
                    steps.append(("statics", f"code bit {k} = {want}: #" + ", #".join(str(num[i]) for i in group)
                                  + " (" + ", ".join(f"{i:#x}" for i in group) + ")",
                                  lambda i, s=frozenset(group): i in s))
            steps += [("statics", f"ONE: #{num[i]} {self.strip3_label(i)}", lambda j, s=i: j == s) for i in live]
            return steps

        def strip_steps(self):
            if "--strip3" in sys.argv:
                return []                       # built when the cycle starts (strip3_steps), after the IID re-read
            if "--strip2" in sys.argv:
                steps = [("statics", name, lambda i, s=frozenset(idx): i in s) for name, idx in self.STRIP2_CANDIDATES]
                steps.append(("statics", "control: every 13BB static whose index has bit 9 (as the 19:46 step 26)",
                              lambda i: (i >> 9) & 1))
                steps.append(("statics", "control: EVERY static of block 13BB", lambda i: True))
                return steps
            steps = [("setting", s) for s in self.STRIP_SETTINGS]
            steps.append(("statics", "EVERY static of block 13BB (should look like DrawStaticEntities off)",
                          lambda i: True))
            steps += [("statics", name, lambda i, s=frozenset(idx): i in s) for name, idx in self.STRIP_NAMED]
            steps.append(("tiles", "the server's stealth tiles (0x2E000D36 / 0x2E000D37, all 16; they cast "
                          "shadows: 0x4A8 = 1)", lambda i: True))
            steps += [("statics", f"bit {b}: the 13BB statics whose index has bit {b} (0x{1 << b:x}) set",
                       lambda i, b=b: (i >> b) & 1) for b in range(self.STRIP_BITS)]
            return steps

        def strip_attach(self, tid):
            """A model node attached to a render component: remember the component of every 13BB static."""
            c = self.ctx(tid)
            rc = c.Ecx
            # 2026-10-30 (tester report 19:46: the breakable fence pieces #0x246 / #0x24c recorded no render node): every
            # component is kept, and strip_resolve() reads its entity's IID again when the steps start, so a static
            # whose IID is set after its model attached is found too
            self.__dict__.setdefault("strip_any", set()).add(rc)
            ent = self.u32(rc + 4)
            if not ent:
                return
            iid_lo, iid_hi = self.u32(ent + 0x100), self.u32(ent + 0x104)
            if iid_hi >> 24 != 1:
                # server objects: only the stealth tiles (they stay all match; their world states carry 0x4A8, the
                # cast-shadows flag: RenderComponent 0x624500 case 0x4a8 -> node flag 0x400, the shadow casters pass
                # 0x761320); kept apart from the 13BB index groups
                ws = self.u32(ent + 0x110)
                if ws in (0x2E000D36, 0x2E000D37):
                    tiles = self.__dict__.setdefault("strip_tiles", set())
                    if rc not in tiles:
                        tiles.add(rc)
                        T.log(f"STRIP stealth tile {iid_hi:#x}:{iid_lo:#x} world state {ws:#x}: render component "
                              f"{rc:#x} node {c.Esi:#x}")
                return
            if iid_hi != 0x01113BB0:
                return
            rcs = self.__dict__.setdefault("strip_rcs", {})
            if rc in rcs.get(iid_lo, ()):
                return
            rcs.setdefault(iid_lo, set()).add(rc)
            if any(iid_lo in idx for _, idx in self.STRIP_NAMED):
                T.log(f"STRIP static #{iid_lo:#x} world state {self.u32(ent + 0x110):#x}: render component {rc:#x} "
                      f"node {c.Esi:#x}")

        def strip_resolve(self):
            """Every recorded render component whose entity is now a 13BB static joins its index group (IIDs read
            again: set after the attach for some statics). Returns (statics, render nodes)."""
            rcs = self.__dict__.setdefault("strip_rcs", {})
            for rc in list(self.__dict__.get("strip_any", ())):
                try:
                    ent = self.u32(rc + 4)
                    if not ent or self.u32(ent + 0x104) != 0x01113BB0:
                        continue
                    rcs.setdefault(self.u32(ent + 0x100), set()).add(rc)
                except OSError:
                    continue
            return len(rcs), sum(len(v) for v in rcs.values())

        def strip_undo(self, st):
            for addr, orig in st.pop("undo", []):
                try:
                    if orig is None:                                    # a node flag word: clear only our bit
                        cur = self.u32(addr)
                        self.write(addr, struct.pack("<I", cur & ~0x800))
                    else:
                        self.write(addr, orig)
                except OSError:
                    pass
                self.__dict__.get("saved_writes", {}).pop(addr, None)

        def strip_step(self):
            """--strip: one graphics setting off, or a set of statics hidden, 5 s each; the cycle repeats."""
            import time
            now = time.monotonic()
            st = getattr(self, "strip_state", None)
            step_s = 6.0 if "--strip2" in sys.argv or "--strip3" in sys.argv else 5.0
            tag = "3" if "--strip3" in sys.argv else "2" if "--strip2" in sys.argv else ""
            if st is None:
                # 2026-10-30 (tester run 19:41: "0 statics recorded" was logged at the first fog frame, before the map's
                # statics attached, while the steps then hid 201 nodes): the count is logged when each cycle starts
                # --strip3: 75 s (recording 21:33: the tester reached the strip ~60 s after the first frame, so the
                # first --strip2 cycle's steps 1-10 were lost)
                wait = 75.0 if tag == "3" else 10.0
                st = self.strip_state = {"i": -1, "t": now + wait, "cycle": 1, "steps": self.strip_steps()}
                T.log(f"STRIP{tag}: stand still where the strip shows; the steps start in {wait:.0f} s, "
                      + (f"{len(st['steps'])} steps" if st["steps"] else "the step list is logged when the cycle starts")
                      + f", {step_s:.0f} s each (the statics recorded so far are counted when the cycle starts)")
                return
            if now < st["t"]:
                return
            self.strip_undo(st)
            st["i"] += 1
            steps = st["steps"]
            if st["i"] == 0:
                n, nodes = self.strip_resolve()
                rcs = self.__dict__.get("strip_rcs", {})
                msg = (f"STRIP cycle {st['cycle']} starts: {n} statics of block 13BB recorded, {nodes} render nodes"
                       + ("" if n else " (NONE: the diagnostic was started after the map loaded; the statics steps "
                                       "will do nothing. Start it in the menu, before Launch)"))
                if "--strip2" in sys.argv:
                    msg += "; candidates: " + ", ".join(
                        f"#{i:#x} {len(rcs.get(i, ()))} node(s)" for _n, idx in self.STRIP2_CANDIDATES for i in idx)
                T.log(msg)
                if "--strip3" in sys.argv:
                    # 2026-10-30 (recording 21:33): the list is numbered from the nodes recorded by now, every cycle
                    steps = st["steps"] = self.strip3_steps()
                    T.log(f"STRIP3 cycle {st['cycle']}: {len(steps)} steps of {step_s:.0f} s (~{len(steps) * step_s / 60:.1f} "
                          "min): 1 control, 12 code steps, then one static at a time")
            if st["i"] >= len(steps):
                T.log(f"STRIP cycle {st['cycle']} done: everything is back as it was; the next cycle starts in 15 s")
                st["cycle"] += 1
                st["i"] = -1
                st["t"] = now + 15.0
                return
            st["t"] = now + step_s
            kind, what = steps[st["i"]][0], steps[st["i"]][1]
            label = f"STRIP cycle {st['cycle']} step {st['i'] + 1}/{len(steps)}"
            undo = st["undo"] = []
            if kind == "setting":
                va, size, value, name = what
                addr = self.base + va - 0x400000
                orig = self.read(addr, size)
                new = struct.pack("<I" if size == 4 else "<B", value)
                self.restore_on_detach(addr, new)
                undo.append((addr, orig))
                T.log(f"{label}: {name} for 5 s (was {orig.hex()})")
                return
            pick = steps[st["i"]][2]
            hidden = 0
            groups = (sorted(self.__dict__.get("strip_rcs", {}).items()) if kind == "statics"
                      else [(0, self.__dict__.get("strip_tiles", set()))])
            for idx, rcs in groups:
                if not pick(idx):
                    continue
                for rc in rcs:
                    try:
                        node = self.u32(rc + 0xA0)
                        if not node or self.u32(node + 0x264) != rc:     # detached / freed: leave it alone
                            continue
                        addr = node + 0x220
                        cur = self.u32(addr)
                        if cur & 0x800:
                            continue                                    # already hidden by the game
                        self.restore_on_detach(addr, struct.pack("<I", cur | 0x800))
                        undo.append((addr, None))
                        hidden += 1
                    except OSError:
                        continue
            T.log(f"{label}: hidden for {step_s:.0f} s: {what} ({hidden} render nodes)")

        def fog_hit(self, tid, rva):
            """--fogpoly / --nofog (docs/re-notes/ca-ring-phantom-strip.md 2)."""
            import time
            c = self.ctx(tid)
            if rva == 0x6AE5B0 and "--layers" in sys.argv:
                self.layers_step()
                if "--nofog" not in sys.argv:
                    return
            if rva == 0x6AE5B0:
                if getattr(self, "nofog_done", False):
                    return
                self.nofog_done = True
                wr = self.u32(self.u32(self.base + 0x1773518) + 0xDC)
                if not wr:
                    T.log("FOGPOLY nofog: no WorldRender yet; nothing changed")
                    return
                old = self.read(wr + 0x36, 4)
                # 2026-10-30 (tester report 13:00): both writes are undone when the diag stops (restore_on_detach)
                self.restore_on_detach(self.base + 0x1776958, struct.pack("<4f", 0.0, 1.0, 0.0, 1.0))
                self.restore_on_detach(wr + 0x36, b"\x00")
                T.log(f"FOGPOLY nofog: WorldRender {wr:#x} bytes +0x36..+0x39 were {old.hex()}; EnableFog (+0x36) = 0 "
                      "and the fog clear colour = (0, 1, 0, 1), the colour of a lit circle's rim. The fog is now one flat value: is the strip by the fence "
                      "still black?")
                return
            entry = c.Edi
            iid_lo, iid_hi = self.u32(entry + 0x10), self.u32(entry + 0x14)
            last = getattr(self, "poly_last", None)
            if last is None:
                last = self.poly_last = {}
            now = time.monotonic()
            if now - last.get((iid_lo, iid_hi), -99.0) < 4.0 or len(last) > 400:
                return
            last[(iid_lo, iid_hi)] = now
            verts, count = self.u32(entry), self.u32(entry + 4)
            cx, cy = struct.unpack("<ff", self.read(entry + 0x44, 8))
            pts = []
            for k in range(min(count, 24)):
                raw = self.read(verts + k * 0x30, 0x24)
                dx, dy = struct.unpack_from("<ff", raw, 0)
                sx, sy = struct.unpack_from("<ff", raw, 0x10)
                moving = raw[0x20]
                # 0xaab3b0: point = centre + (dx * sx, dy * sy) (sx / sy = the radius for a vertex the collector left
                # on the circle, flag 1); a clipped vertex (flag 0) keeps its own scale
                pts.append(f"({cx + dx * sx:.1f},{cy + dy * sy:.1f}{'' if moving else ' c'})")
            T.log(f"FOGPOLY source {iid_hi:#x}:{iid_lo:#x} centre ({cx:.2f}, {cy:.2f}) {count} vertices: "
                  + " ".join(pts))

        def on_breakpoint(self, tid, va):
            rva = va - self.base
            if rva in self.ml_rvas:
                try:
                    self.mapload_hit(tid, va, rva)
                except OSError as e:
                    T.log(f"MAP: could not read memory at rva {rva:#x}: {e}")
                self.counts[va] = 10 ** 9          # no generic line: mapload_hit logs what is new
                super().on_breakpoint(tid, va)
                return
            if "--props" in sys.argv and not self.props_done:
                # the first breakpoint of any kind (also when the diag is started
                # after the match loaded)
                try:
                    self.dump_props()
                except OSError as e:
                    T.log(f"PROPS: could not read the table: {e}")
            if rva in (0x38165C, 0x6AE5B0) and "--strip" in sys.argv:
                try:
                    if rva == 0x38165C:
                        self.strip_attach(tid)
                    else:
                        self.strip_step()
                except OSError as e:
                    T.log(f"STRIP: could not read memory at rva {rva:#x}: {e}")
                self.counts[va] = 10 ** 9          # no generic line: the STRIP handlers log what matters
                super().on_breakpoint(tid, va)
                return
            if (rva == 0x6AB4B6 and "--fogpoly" in sys.argv) or (rva == 0x6AE5B0 and ("--nofog" in sys.argv
                                                                                    or "--layers" in sys.argv)):
                try:
                    self.fog_hit(tid, rva)
                except OSError as e:
                    T.log(f"FOGPOLY: could not read memory at rva {rva:#x}: {e}")
                self.counts[va] = 10 ** 9          # no generic line: fog_hit logs what it found
                super().on_breakpoint(tid, va)
                return
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
                elif rva == RVA_ANIM_LINK:
                    self.log_anim_link(tid)
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
        if mapload:
            d.mapload_summary()
        adv = sorted(i for i in d.registered if i in ADVANCEMENT_IDS)
        T.log(f"===== end: {len(d.registered)} handlers registered; Advancement ones: "
              + (", ".join(ADVANCEMENT_IDS[i] for i in adv) or "NONE"))
        T.log("registered ids: " + " ".join(f"{i:#x}" for i in sorted(d.registered)))


if __name__ == "__main__":
    main()
