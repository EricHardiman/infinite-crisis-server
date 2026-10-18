"""Build the game ID catalog: catalog/index.html (one self-contained page).

    python tools/build_catalog.py          (or: python ic.py catalog)

Every table comes from a TSV in catalog/data/ (first row = column names). Some
of them are refreshed here from the project's own sources when those exist:

    champions.tsv      <- data/champions.json (local; the TSV is what is committed)
    stolen_powers.tsv  <- data/stolen_powers.tsv (+ data/stolen_powers.json if built)
    scriptlets.tsv     <- data/batman_actions.tsv
    hud_elements.tsv   <- icserver/tutorial1.py HUD
    exe_patches.tsv    <- icserver/patcher.py PATCHES

The others (stages, skills, properties, network events, ...) are written by
hand. The page embeds all the data, so it opens straight from disk and works
on GitHub Pages. Only an index of IDs, names and relationships goes in here:
no game files, images or extracted texts.
"""
import csv
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
CAT = os.path.join(ROOT, "catalog")
DATA = os.path.join(CAT, "data")

# Menu: (group, [(section id, title, file, description)])
SECTIONS = [
    ("Game content", [
        ("champions", "Champions", "champions.tsv",
         "Every champion with its record (0x48), entity / variant (0x40), skill set and costumes. "
         "The variant is what the lobby and the server use to pick a champion."),
        ("skills", "Skills", "skills.tsv",
         "Champion skill sets (basic attack, Q, W, E, R, passive) and the Stolen Powers the server implements. "
         "Stats are 'stat id=base(per rank)': 3 = cost (Will, stored negative), 5 = damage, 15 = cooldown in "
         "seconds (it drops per rank in every champion's kit), 18 = range (probable). All 43 champions, from "
         "'python ic.py catalog --scan' on a full install."),
        ("stolen-powers", "Stolen Powers", "stolen_powers.tsv",
         "The 65 Stolen Powers: base powers and champion versions. Assign one by DID or name in config.toml "
         "([tutorial] camera_skill / strength_skill). Full data: python ic.py stolen-powers."),
        ("artifacts", "Artifacts", "artifacts.tsv",
         "In-match items from the Artifact Foundry lists (pack 0xA00000B3). The data is in the 0x49 twin of each "
         "0x40 DID; the '(n)' in the name is the tier."),
        ("amplifiers", "Amplifiers", "amplifiers.tsv",
         "Augments (list 0x48000A49) and mods (list 0x48000A4A), pack 0xA00000B3. Mods change a given artifact."),
        ("item-stats", "Item stats", "item_stats.tsv",
         "Stat keys used by artifacts and amplifiers (and champion stat sheets), from the Foundry filters (0x48000163)."),
        ("avatar-icons", "Avatar icons", "avatar_icons.tsv",
         "Protector (account) icons for the profile header and its icon picker: ownables of content type 3 "
         "(AvatarIcon_ContentType). Data in the 0x49 twin of each 0x40 DID, UI pack 0xA00000D0: picture "
         "0x100008F8, name / description / unlock text 0x10000B77-B79 (string table 0x2B0003BD). The server "
         "sends them all as owned ([account] unlock_avatar_icons). Names: python ic.py catalog --scan."),
        ("stages", "Stages", "stages.tsv",
         "Encounters (maps and modes) the client offers, with the training achievements and rewards."),
    ]),
    ("World", [
        ("world-objects", "World objects", "world_objects.tsv",
         "Props and scenery: world states (0x2E), their entities, what the server sends (carrier classes 0x4A...), "
         "scriptlet tables and where they are used."),
        ("world-states", "World states (all)", "world_states.tsv",
         "Inventory of every world state (0x2E) in the install (python ic.py worlds): packs, .entity, model names "
         "(rig bones, .hkx / .hkb files), a kind guessed from those names, templates, graphs, particles, names in the "
         "map layouts and every pack holding a record it uses (load those or the client may close)."),
        ("characters", "Characters", "characters.tsv",
         "Champions, drones, bosses and cinematic actors the server spawns or that appear in Tutorial 1."),
        ("animations", "Animations", "animations.tsv",
         "Animation graphs (0x1A) and their events and states. Graph event IDs come from a different name table than "
         "scriptlet keys, so the same number can mean different things."),
        ("animation-graphs", "Animation graphs", "animation_graphs.tsv",
         "Every Havok behavior graph (.hkb) in the packs and the animation clips (.hkx) it plays. "
         "Full list after 'python ic.py catalog --scan'."),
        ("vfx", "Effects", "vfx.tsv",
         "Visual and sound effect scriptlet keys the server uses or has tried."),
        ("sounds", "Sounds", "sounds.tsv",
         "Every Wwise sound event of audio\\Audio_SB.pck (python ic.py sounds): its bank and the game records "
         "that play it (a typed value of kind 0x2C). Event names are not in the data, only their ids."),
        ("sound-banks", "Sound banks", "sound_banks.tsv",
         "The 41 banks of Audio_SB.pck; names from the packs' 0x52 records (bank id = Wwise FNV hash of the name)."),
        ("cinematics", "Cinematics", "cinematics.tsv",
         "Cinematics (0x35) and cinematic scriptlets: when they play and what the server does around them."),
        ("conversations", "Conversations", "conversations.tsv",
         "Tutorial conversation lines, hints and objective texts by ID, described in our own words."),
    ]),
    ("Engine reference", [
        ("skill-slots", "Skill slots", "skill_slots.tsv",
         "HUD skill slots as the client numbers them, and the champion property that holds each slot's skill."),
        ("properties", "Properties", "properties.tsv",
         "The client's 3,800+ property descriptors: id and value kind (from tools/diag.py --props), with the meaning "
         "where known. Records and the network use these ids."),
        ("network-events", "Network events", "network_events.tsv",
         "Protocol events: who sends them and what they do. Byte layouts are in icserver/messages.py and "
         "docs/reverse-engineering.md."),
        ("scriptlets", "Scriptlets", "scriptlets.tsv",
         "Allowed scriptlet keys (animations, effects, sounds) per entity, with their probable names "
         "(name table 0x33000000)."),
        ("records", "Key records", "records.tsv",
         "Notable data records: catalogs and lists, configs, skill sets, stat sheets, name tables."),
        ("hud-elements", "HUD elements", "hud_elements.tsv",
         "HUD element ids for event 0x213D (1 restore, 2 hide, 7 highlight)."),
        ("packs", "Data packs", "packs.tsv",
         "Every .rp pack: record count, record types (DID prefix:count), English text tables, and what it holds "
         "when known. Refreshed by 'python ic.py catalog --scan'."),
        ("asset-types", "Asset types", "asset_types.tsv",
         "Record types by DID prefix (the top byte): what they hold, how many records and packs. Models, sounds and "
         "textures are listed by ID; the files themselves stay in the game's packs."),
        ("exe-patches", "Exe patches", "exe_patches.tsv",
         "Patches applied by python ic.py patch (file offset and purpose)."),
    ]),
]


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.reader((ln for ln in f if not ln.startswith("#")), delimiter="\t")]
    if not rows:
        return [], []
    head = rows[0]
    return head, [r + [""] * (len(head) - len(r)) for r in rows[1:] if any(c.strip() for c in r)]


def write_tsv(path, head, rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def hx(v):
    return f"0x{int(v):08X}" if v not in (None, "", 0) else ""


# ---- refresh from the project's sources ------------------------------------------------
def refresh_champions():
    src = os.path.join(ROOT, "data", "champions.json")
    if not os.path.isfile(src):
        return False
    with open(src, encoding="utf-8") as f:
        roster = json.load(f)
    done = {"Gaslight Batman": "playable (Tutorial 1)"}
    rows = []
    for c in sorted(roster, key=lambda c: c["name"]):
        costumes = [s["variant"] for s in c.get("costume_info", [])]
        rows.append([hx(c["id"]), c["name"], hx(c["variant"]), hx(c.get("skills_key")), hx(c.get("skills_pack")),
                     hx(c.get("tex384")), " ".join(hx(v) for v in costumes),
                     done.get(c["name"], "data only")])
    write_tsv(os.path.join(DATA, "champions.tsv"),
              ["id", "name", "variant", "skill_set", "skill_pack", "portrait_icon", "costume_variants",
               "server_status"], rows)
    return True


def refresh_stolen_powers():
    head, rows = read_tsv_commented(os.path.join(ROOT, "data", "stolen_powers.tsv"))
    if not rows:
        return False
    extra = {}
    js = os.path.join(ROOT, "data", "stolen_powers.json")
    if os.path.isfile(js):
        with open(js, encoding="utf-8") as f:
            extra = {int(e["did"], 16): e for e in json.load(f)}
    implemented = {0x48000808: "implemented (D)", 0x48000A3B: "implemented (F)"}
    # without the local JSON, keep the targeting / script already in the catalog
    old = {}
    cur = os.path.join(DATA, "stolen_powers.tsv")
    if os.path.isfile(cur):
        head, cur_rows = read_tsv(cur)
        if "targeting" in head:
            ti, si = head.index("targeting"), head.index("script")
            old = {int(r[0], 16): {"targeting": r[ti], "script": r[si]} for r in cur_rows}
    out = []
    for group, did, power, champion, icon in rows:
        d = int(did, 16)
        e = extra.get(d) or old.get(d, {})
        out.append([hx(d), power, champion or "(base power)", group, hx(int(icon, 16)) if icon else "",
                    str(e.get("targeting", "")), e.get("script") or "",
                    implemented.get(d, "data only")])
    write_tsv(os.path.join(DATA, "stolen_powers.tsv"),
              ["id", "power", "champion", "group", "icon", "targeting", "script", "server_status"], out)
    return True


def read_tsv_commented(path):
    """data/stolen_powers.tsv: comment lines, no header row."""
    if not os.path.isfile(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        rows = [ln.rstrip("\n").split("\t") for ln in f if ln.strip() and not ln.startswith("#")]
    return ["group", "did", "power", "champion", "icon"], [(r + [""] * 5)[:5] for r in rows]


def refresh_scriptlets():
    src = os.path.join(ROOT, "data", "batman_actions.tsv")
    if not os.path.isfile(src):
        return False
    with open(src, encoding="utf-8") as f:
        rows = [ln.rstrip("\n").split("\t") for ln in f if ln.strip() and not ln.startswith("#")]
    used = {0x10000164: "Q", 0x10000163: "W", 0x10000165: "E", 0x10000162: "R",
            0x10000195: "basic attack (right)", 0x10000196: "basic attack (left)",
            0x10000188: "basic shot VFX (right)", 0x10000189: "basic shot VFX (left)",
            0x100007A2: "car lift", 0x100007A1: "car lift",
            0x100009EC: "Cinematic_Intro: graph event Spawn through action type 0x737 + Vfx_Bmg_Spawn; the only "
                        "thing that lights the antennas (23:29), but its spawn rope shows; off since fase3-ix",
            0x100009EB: "Cinematic_Hidden: action type 0x737 with SpawnIdle; makes Batman invisible (fase3-is, "
                        "23:19); not used",
            0x100000B8: "critical basic attack (arms, crit_keys)", 0x1000017E: "critical shot VFX (crit_keys)",
            0x1000017C: "critical shot VFX stop (crit_stop_keys)",
            # fase3-jc: John Stewart's kit (icserver/kits.py)
            0x100010F1: "John Stewart Q Full Auto", 0x100010ED: "John Stewart W Claymore (placed)",
            0x100010FC: "John Stewart W Claymore", 0x100010E6: "John Stewart W Claymore (goes off / expires)",
            0x100010E5: "John Stewart E Forward Base rank 1", 0x100010EA: "John Stewart E Forward Base rank 2",
            0x100010EC: "John Stewart E Forward Base rank 3", 0x100010EF: "John Stewart E Forward Base rank 4",
            0x100010E8: "John Stewart E Forward Base ends", 0x100010F3: "John Stewart R Omni Turret",
            0x100010F4: "John Stewart R turret rank 1", 0x100010F6: "John Stewart R turret rank 2",
            0x100010F9: "John Stewart R turret rank 3", 0x100010FB: "John Stewart R turret rank 4",
            0x100010F7: "John Stewart R turret shot rank 1", 0x100010DF: "John Stewart R turret shot rank 2",
            0x100010E2: "John Stewart R turret shot rank 3", 0x100010E7: "John Stewart R turret shot rank 4",
            0x100010F8: "John Stewart R turret ends"}
    out = []
    for r in rows:
        k = int(r[0], 16)
        out.append([hx(k), r[1] if len(r) > 1 else "", "Gaslight Batman", "yes" if k in used else "",
                    used.get(k, "")])
    other = os.path.join(DATA, "scriptlets_other.tsv")
    if os.path.isfile(other):                  # drones, gates, cars, ... (hand-written)
        head, more = read_tsv(other)
        for r in more:
            d = dict(zip(head, r))
            out.append([d.get("id", ""), d.get("probable_name", ""), d.get("entity", ""),
                        d.get("used_by_server", ""), d.get("notes", "")])
    write_tsv(os.path.join(DATA, "scriptlets.tsv"), ["id", "probable_name", "entity", "used_by_server", "notes"], out)
    return True


def refresh_hud():
    try:
        from icserver import tutorial1
    except Exception:
        return False
    hud = dict(tutorial1.HUD)
    hud.setdefault("SkillButtonStolenPower1 (D)", 22)
    hud.setdefault("SkillButtonStolenPower2 (F)", 23)
    hud.setdefault("SkillButtonStolenPowerTSkill", 21)
    hud.setdefault("Portrait", 18)
    rows = sorted(([str(v), k] for k, v in hud.items()), key=lambda r: int(r[0]))
    write_tsv(os.path.join(DATA, "hud_elements.tsv"), ["id", "element"], rows)
    return True


def refresh_patches():
    try:
        from icserver import patcher
    except Exception:
        return False
    rows = [[f"0x{off:X}", str(len(new)), desc] for off, _orig, new, desc in patcher.PATCHES]
    write_tsv(os.path.join(DATA, "exe_patches.tsv"), ["file_offset", "bytes", "purpose"], rows)
    return True


# ---- page -----------------------------------------------------------------------------
def build():
    os.makedirs(DATA, exist_ok=True)
    refreshed = [name for name, fn in (("champions", refresh_champions), ("stolen powers", refresh_stolen_powers),
                                       ("scriptlets", refresh_scriptlets), ("HUD elements", refresh_hud),
                                       ("exe patches", refresh_patches)) if fn()]
    groups = []
    for group, sections in SECTIONS:
        items = []
        for sid, title, fname, desc in sections:
            path = os.path.join(DATA, fname)
            head, rows = read_tsv(path) if os.path.isfile(path) else ([], [])
            items.append({"id": sid, "title": title, "file": f"data/{fname}", "description": desc,
                          "columns": head, "rows": rows})
        groups.append({"group": group, "sections": items})
    with open(os.path.join(CAT, "template.html"), encoding="utf-8") as f:
        page = f.read()
    blob = json.dumps(groups, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = page.replace("/*__CATALOG__*/null", blob)
    out = os.path.join(CAT, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    total = sum(len(s["rows"]) for g in groups for s in g["sections"])
    print(f"catalog: {total} entries in {sum(len(g['sections']) for g in groups)} sections -> {out}")
    if refreshed:
        print(f"refreshed from the project's sources: {', '.join(refreshed)}")
    return out


if __name__ == "__main__":
    build()
