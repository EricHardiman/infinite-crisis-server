"""The local champion's skill buttons as the client's HUD reads them: the slot tables (champion properties 0x100008E3
basic, 0x100008E8 Q, 0x100008EA W, 0x100008EC E, 0x100008E6 R, 0x100008EF passive; kind 0x0B, the whole skill block, as
the Stolen Powers' 0x100008F0 / 0x100008F1 go).

2026-11-02 (tester report 2026-11-02, game test of Superman / Arcane Green Lantern / Blue Beetle): three second stages
needed a click instead of a key press (AGL's Q teleport, Superman's E punch, Blue Beetle's W detonation) and Blue Beetle's
Infiltrator Mode left the buttons of the ranged form. The scripts change the button two ways, and ics told the client
neither:

- SetSlotSkill 0x10000089 swaps the slot's skill for another record's skill block (Blue Beetle R: 0x48000A97 / A95 / A96,
  each with its own icon 0x10000302, targeting 0x1000003D and script); skill-mechanics-recipes.md 2 ran the swap on the
  server only.
- SetSkillStatOverride 0x100000FA overrides the button's presentation. Its fields, read from the 61 nodes in the 875
  scripts against the slot blocks: 2 / 3 = name (0x100001C0: string id, table 0x2B......), 7 / 8 = description
  (0x1000003E), 11 = icon (0x10000302, 0x1300....), 12 = 0x100002A3 (0x48000154 / 0x48000156: the same values the base
  and swapped blocks of Blue Beetle's Q hold), 14 = targeting type 0x1000003D (only 1, 5, 7, 13 and 14 occur: 5 = no
  target, the key press casts at once, in all three second stages; Super Strength sets 13 after the lift). Fields 13 /
  16 / 17 / 18 / 19 (small numbers 1 / 2) are not placed (O).
- ClearSkillStatOverride 0x1000008E [slot] ends both (the swap revert stays in CastWorld.revert_slot_skill).

The table sent is the champion's skill-set block for the slot, the swapped record's block over it (entries by id; the
stat list stat by stat, as Data.stolen_power merges a version), then the presentation fields. [ics] slot_tables.
"""
import time
from . import records
from .gamedata import SKILL_BLOCK_PROPERTIES, _wire_entries

PROP_NAME, PROP_DESC, PROP_ICON, PROP_INDICATOR, PROP_TARGETING = (0x100001C0, 0x1000003E, 0x10000302, 0x100002A3,
                                                                   0x1000003D)
PROP_STATS, PROP_STAT_ID = 0x100004B4, 0x100004B6
KIND_STRING_PAIR = 0x0E


def enabled(w):
    return bool(w.ic.get("slot_tables", True))


def _skill_set_block(w, ent, slot):
    ss = getattr(w.data, "_skill_set", {}).get(ent.class_id)
    prop = SKILL_BLOCK_PROPERTIES.get(slot)
    if not ss or prop is None:
        return None
    blk = records.get(w.data.record(ss), prop)
    return _wire_entries(blk) if isinstance(blk, list) else None


def _record_block(w, did):
    e = w.data.record(did)
    blk = records.get(e, 0x100008E5) or records.get(e, 0x1000003F)
    return _wire_entries(blk) if isinstance(blk, list) else None


def _merge(base, over):
    """over's entries replace base's by id (the stat list stat by stat); base's other entries stay."""
    merged = {k: (k, kind, v) for k, kind, v in base}
    order = [k for k, _kind, _v in base]
    for k, kind, v in over:
        if k == PROP_STATS and k in merged and isinstance(v, list) and isinstance(merged[k][2], list):
            def sid(el):
                return records.as_dict(el[2]).get(PROP_STAT_ID) if isinstance(el[2], list) else None
            mine = {sid(el) for el in v}
            v = [el for el in merged[k][2] if sid(el) not in mine] + list(v)
        if k not in merged:
            order.append(k)
        merged[k] = (k, kind, v)
    return [merged[k] for k in order]


def _presented(block, fields):
    out = []
    for k, kind, v in block:
        if k in fields:
            kind, v = fields[k]
        out.append((k, kind, v))
    for k, (kind, v) in fields.items():
        if not any(e[0] == k for e in block):
            out.append((k, kind, v))
    return out


def refresh(w, ent, slot, why):
    """Recompute the slot's table and let the client see it (a 0x6 in delta mode, the bundle otherwise)."""
    if ent is not w.champion or not enabled(w) or slot not in SKILL_BLOCK_PROPERTIES:
        return False
    swap = getattr(ent, "slot_swap_blocks", {}).get(slot)
    fields = getattr(ent, "slot_presentation", {}).get(slot)
    tables = ent.__dict__.setdefault("slot_tables", {})
    if swap is None and not fields:
        if slot not in tables:
            return False
        base = _skill_set_block(w, ent, slot)
        if base:
            tables[slot] = base               # the base block back (the instance value overrides the template's)
        else:
            tables.pop(slot, None)
    else:
        base = _skill_set_block(w, ent, slot) or []
        block = _merge(base, swap) if swap else base
        tables[slot] = _presented(block, fields or {})
    once = w.ic.get("slot_table_hud_refresh_once", True)
    if w.ic.get("slot_table_hud_refresh", True) and hasattr(w, "_rank_refresh") and not once:
        # 2026-11-03 (tester report 2026-11-03 00:34: Blue Beetle's buttons changed only when that slot's cooldown ended;
        # P): the rank property toggle the HUD re-reads after a rank-up (World.rank_up) goes with the new table, so the
        # buttons are redrawn at once
        w._rank_refresh = 3 - w._rank_refresh
    w.update(ent, f"{ent.name}: slot {slot} button ({why}) (0x6 {SKILL_BLOCK_PROPERTIES[slot]:#x})")
    if w.ic.get("slot_table_hud_refresh", True) and hasattr(w, "_rank_refresh") and once:
        # 2026-11-03 (tester report 23:26: after R the buttons still waited ~2-3 s, until R's cooldown ended; the run: a
        # form swap refreshes six slots in a few steps over ~0.12 s, six toggles brought the value back, and the HUD's
        # check (code cave D, every frame) saw no change): one toggle when the tables stop changing,
        # slot_table_hud_refresh_delay s after the last one (P, the value is ours), in an update of its own ([ics]
        # slot_table_hud_refresh_once; false = a toggle per slot, anim-19)
        delay = float(w.ic.get("slot_table_hud_refresh_delay", 0.1) or 0.0)
        w.__dict__["_rank_refresh_at"] = time.time() + delay

        def toggle():
            at = w.__dict__.get("_rank_refresh_at")
            if at is None or time.time() + 1e-6 < at:
                return                         # a later table change has its own check
            w.__dict__.pop("_rank_refresh_at", None)
            w._rank_refresh = 3 - w._rank_refresh
            w.update(ent, f"{ent.name}: buttons redrawn (rank property toggle, 0x6)")
        w.schedule(delay, toggle)
    return True


def swapped(w, ent, slot, did):
    """SetSlotSkill: the record's block becomes the slot's."""
    if ent is not w.champion or not enabled(w):
        return
    blk = _record_block(w, did)
    if blk:
        ent.__dict__.setdefault("slot_swap_blocks", {})[slot] = blk
        refresh(w, ent, slot, f"form swap {did:#x}")


def reverted(w, ent, slot):
    if ent is not w.champion or not enabled(w):
        return
    if getattr(ent, "slot_swap_blocks", {}).pop(slot, None) is not None:
        refresh(w, ent, slot, "form swap ended")


def present(w, ent, slot, values):
    """SetSkillStatOverride 0x100000FA's values -> the fields it overrides on the slot's button."""
    if ent is not w.champion or not enabled(w):
        return

    def val(i):
        return values[i] if i < len(values) and isinstance(values[i], int) else 0
    fields = {}
    if val(2):
        fields[PROP_NAME] = (KIND_STRING_PAIR, (val(2), val(3)))
    if val(7):
        fields[PROP_DESC] = (KIND_STRING_PAIR, (val(7), val(8)))
    if val(11):
        fields[PROP_ICON] = (0x15, val(11))
    if val(12):
        fields[PROP_INDICATOR] = (0x15, val(12))
    if val(14):
        fields[PROP_TARGETING] = (0x08, val(14))
    if not fields:
        return
    cur = ent.__dict__.setdefault("slot_presentation", {}).setdefault(slot, {})
    cur.update(fields)
    refresh(w, ent, slot, "presentation " + ", ".join(f"{k:#x}" for k in fields))


def cleared(w, ent, slot):
    if ent is not w.champion or not enabled(w):
        return
    if getattr(ent, "slot_presentation", {}).pop(slot, None):
        refresh(w, ent, slot, "presentation cleared")


def properties(ent):
    """The changed slot tables for World.properties (a full bundle must carry them, or the client drops them)."""
    return [(SKILL_BLOCK_PROPERTIES[slot], 0x0B, block)
            for slot, block in sorted((getattr(ent, "slot_tables", None) or {}).items()) if block]
