"""Account cosmetics the server gives every player: the Protector (account)
icons shown on the profile header and its icon picker.

How the client finds them (2026-10-16, UI pack 0xA00000D0 ActionScript):
- gameplay.singleton.OwnablesManager.RecvNotice_ItemStatuses builds its lists
  from the 0x20B8 item statuses (DID, status, content type, owned, count);
  GetAllOwnableDatasOfType(AvatarIcon_ContentType = 3) is what the profile's
  icon picker (ProtectorIconSubmenu, OnItemStatusesChange) lists, keeping the
  ones with OWNABLE_UI_STATE_OWNED.
- ProtectorIconManager (query GM_Character.RequestProtectorIcons 0x1000047D)
  gives each icon's picture and texts from the game data, matched on the
  ownable DID (didIconWC).
- The icons' own records: 134 twins 0x49xxxxxx in pack 0xA00000D0 with
  property 0x100008F8 (picture 0x13...), 0x10000B77 / B78 / B79 (name,
  description, unlock description: string table 0x2B0003BD) and 0x10000AB9
  (bool). The ownable DID is the class 0x40 + the same low 24 bits.
Choosing an icon sends notice UI_SetProtectorIcon 0x1000047E (icon, slot) to
the client's C++; the server's answer is 0x2154 (scorecard.protector_icon_slot).

Only DIDs are read here; the pictures and texts stay in the player's install.
"""
import os

ICON_PICTURE = 0x100008F8
ICON_NAME = 0x10000B77
AVATAR_ICON_CONTENT_TYPE = 3
UI_PACK = "0xa00000d0.rp"

_cache = {}


def avatar_icons(rp_dir, props_txt=None, names=False):
    """[(ownable DID 0x40..., picture DID 0x13..., name)] from the player's packs.
    names=True also looks up the English names (reads every pack's string
    tables: slow, only for the catalog scan); otherwise name is ''."""
    if names:
        return _scan(rp_dir, props_txt, True)
    if rp_dir in _cache:
        return _cache[rp_dir]
    from . import gamecache, gamedata
    cached = gamecache.get(rp_dir, "avatar_icons")
    if cached is not None:
        _cache[rp_dir] = [tuple(x) for x in cached]
        return _cache[rp_dir]
    out = _scan(rp_dir, props_txt, False)
    _cache[rp_dir] = out
    gamecache.put(rp_dir, "avatar_icons", [list(x) for x in out])
    return out


def _scan(rp_dir, props_txt, names):
    from . import gamedata
    out = []
    game = gamedata.Game(rp_dir, props_txt)
    index = game.index()
    for did in sorted(d for d, pack in index.items() if d >> 24 == 0x49 and pack.lower() == UI_PACK):
        rec = game.record(did)
        keys = {k for k, _kind, _v in rec or ()}
        if ICON_PICTURE in keys and ICON_NAME in keys:
            out.append((0x40000000 | (did & 0xFFFFFF), gamedata.get(rec, ICON_PICTURE) or 0,
                        game.text(gamedata.get(rec, ICON_NAME)) if names else ""))
    return out


AUGMENTS_CONTENT_TYPE, MODS_CONTENT_TYPE = 12, 13
AMPLIFIERS_TSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "catalog", "data", "amplifiers.tsv")


def amplifiers():
    """[(DID, content type)] for every augment / mod in the catalog."""
    import csv
    out = []
    try:
        with open(AMPLIFIERS_TSV, encoding="utf-8", newline="") as f:
            rows = csv.reader(f, delimiter="\t")
            head = next(rows)
            i, t = head.index("id"), head.index("type")
            for r in rows:
                try:
                    did = int(r[i], 16)
                except (ValueError, IndexError):
                    continue
                ctype = {"augment": AUGMENTS_CONTENT_TYPE, "mod": MODS_CONTENT_TYPE}.get(r[t].strip().lower())
                if ctype:
                    out.append((did, ctype))
    except (OSError, StopIteration, ValueError):
        pass
    return out


def ownables(cfg, log=None):
    """[(DID, content type)] to add to every 0x20B8 item statuses delivery."""
    acc = cfg["account"]
    extra = []
    if acc.get("unlock_amplifiers", True):
        extra = amplifiers()
        if log:
            log(f"amplifiers: {sum(1 for _d, c in extra if c == AUGMENTS_CONTENT_TYPE)} augments, "
                f"{sum(1 for _d, c in extra if c == MODS_CONTENT_TYPE)} mods unlocked")
    if not acc.get("unlock_avatar_icons", True):
        return extra
    try:
        icons = avatar_icons(os.path.join(cfg.game_dir, "rp"), os.path.join(cfg.log_dir, "props.txt"))
    except Exception as e:                 # never stop the server for this
        if log:
            log(f"avatar icons: {e!r}")
        return extra
    if log:
        log(f"avatar icons: {len(icons)} unlocked (content type {AVATAR_ICON_CONTENT_TYPE})"
            if icons else "avatar icons: none found in the packs")
    return [(wc, AVATAR_ICON_CONTENT_TYPE) for wc, _pic, _name in icons] + extra
