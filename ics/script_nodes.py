"""The server script nodes beyond the VM's own (ics/script_runtime.py): skills, attributes, damage, vitals, status
effects, icons, missiles, hotspots, spawned entities, forced movement, entity lists, teams, AI hooks.

Every node follows docs/re-notes/full-combat-skills.md (sections in brackets); operands are in stream order (the
order ics/script_model.py prints), "values" are the raw r1 / r4 fields in order. C = read in the client, P = probable.
Nodes whose meaning is unknown run as logged no-ops (LOGGED below) so a script never stops on them.

World hooks (NullWorld logs, ics/world.py CastWorld sends): position, heading, radius, alive, exists, team,
set_team, kind_matches, all_entities, find_targets, vital, set_vital, vitals_changed, damage, heal, spend, message,
spawn_entity, destroy, move, stop, run_scriptlet, stop_scriptlet, launch_missile, combat.
"""
import math
import random

from . import records
from . import script_runtime as R
from .combat import (Handle, Hotspot, relation, ATTR_CRIT_CHANCE, ATTR_CRIT_DAMAGE, ATTR_ATTACK_ARMOR,
                     ATTR_POWER_ARMOR, ATTR_ATTACK_PEN, ATTR_POWER_PEN, ATTR_ATTACK_PEN_PCT, ATTR_POWER_PEN_PCT,
                     ATTR_ATTACK_LIFESTEAL, ATTR_POWER_LIFESTEAL, ATTR_TARGETABLE, ATTR_STEALTH, PROP_LEVEL)

num = R.num
Missile = R.Missile

# events raised by the nodes on the owning script (full-combat-skills.md 4.4)
EV_DASH_ARRIVED, EV_DASH_FAILED, EV_DASH_STARTED, EV_DASH_INTERRUPTED = 0x100000C1, 0x100000C3, 0x100000C4, 0x100000C5
EV_KNOCKBACK_DONE = 0x100000A6
EV_TETHER_DONE = 0x10000005
VOT_TICK = 0.5                       # s between vital-over-time ticks (the client predicts with the 0x42 VOT list)
HOTSPOT_TICK = 0.25                  # s between hotspot occupancy checks
MOTION_TICK = 0.05
HOTSPOT_STATUS_DURATION = [True]     # [ics] hotspot_status_duration (set by ics/server.py)


def _combat(inst):
    return inst.world.combat


def _val(n, i, default=0):
    return n.values[i] if len(n.values) > i and isinstance(n.values[i], int) else default


def _op(ops, i):
    return ops[i] if len(ops) > i else None


def _set(inst, ops, i, value):
    if len(ops) > i:
        inst.set(ops[i], value)


def _ent(inst, ops, i):
    """Entity operand i (unset = the script's owner); a missile acts for its shooter where noted by callers."""
    return inst.ent(ops[i]) if len(ops) > i else inst.owner


def _real(e):
    return e.owner if isinstance(e, Missile) else e


def _int(v, default=0):
    """An integer from a variable value (raw words, floats, NaN-safe)."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v if v <= 0xFFFFF else _int(R.f32(v), default)
    if isinstance(v, float):
        return int(v) if math.isfinite(v) else default
    return default


def _slot(inst, value):
    """A slot field: -1 = the slot of this script (0x9921E0), else the number."""
    if value in (0xFFFFFFFF, -1, None):
        return inst.slot if inst.slot is not None else 0
    if value == 0xFFFFFFFE:
        return -2
    if value == 0xFFFFFFFD:
        return -3
    return value


def _now(inst):
    return inst.world.time


def _log(inst, text):
    w = inst.world
    w.log(f"[{w.time:6.2f}] {inst.script.did:#x} {text}")


def _msg(inst, what, ent=None, **details):
    if hasattr(inst.world, "message"):
        inst.world.message(what, ent, **details)


def _world_cfg(world, key, default=None):
    """An [ics] setting through a CastWorld (world.w.ic), or the default (simulations)."""
    ic = getattr(getattr(world, "w", None), "ic", None) or getattr(world, "ic", None)
    return ic.get(key, default) if hasattr(ic, "get") else default


def _cfg(inst, key, default=None):
    """An [ics] setting through the script's world (CastWorld.w.ic), or the default (simulations)."""
    w = getattr(inst.world, "w", None)
    ic = getattr(w, "ic", None) or getattr(inst.world, "ic", None)
    return ic.get(key, default) if hasattr(ic, "get") else default


def _call(inst, name, *args, default=None, **kw):
    fn = getattr(inst.world, name, None)
    return fn(*args, **kw) if fn else default


def _dist2d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _position(inst, v):
    """A position operand value: a frame / vector, or an entity's position."""
    if isinstance(v, tuple):
        return v
    if v in (None, 0):
        return None
    return inst.world.position(v)


# ---- skill state (1.8) -----------------------------------------------------------------------------------

def _holds_action_lock(inst, n, ops):            # 0x10000015 HoldsActionLock (C)
    owner = _combat(inst).of(inst.source()).action_owner
    return owner is None or owner is inst or getattr(owner, "removed", False)


def _begin_skill(inst, n, ops, chain):           # 0x1000000E BeginSkill: take the action lock if free (C)
    st = _combat(inst).of(inst.source())
    if st.action_owner is None or st.action_owner is inst or getattr(st.action_owner, "removed", False):
        st.action_owner = inst
    return False


def _end_skill(inst, n, ops, chain):             # 0x1000000A EndSkill: release the lock if this script holds it (C)
    st = _combat(inst).of(inst.source())
    if st.action_owner is inst:
        st.action_owner = None
    return False


def _is_slot_skill(inst, n, ops):                # 0x100000D2 IsSlotSkillScript (C)
    return inst.slot is not None and inst.status is None


def _skill_off_cooldown(inst, n, ops):           # 0x100000DF IsSkillOffCooldown(skill operand)[slot] (C)
    slot = _slot(inst, _val(n, 0, 0xFFFFFFFF))
    if ops and not ops[0].is_unset():
        mapped = _call(inst, "slot_of_skill", inst.source(), inst.get(ops[0]))
        if mapped is not None:
            slot = mapped
    return _combat(inst).cooldown_left(inst.source(), slot, _now(inst)) <= 0.0


def _show_skill_error(inst, n, ops, chain):      # 0x100000D8 ShowSkillError(entity)[error, slot] -> 0x20DC (C)
    _msg(inst, "skill_error", _ent(inst, ops, 0), slot=_slot(inst, _val(n, 1, 0xFFFFFFFF)), error=_val(n, 0))
    return False


def _set_disable_condition(inst, n, ops, chain):  # 0x100000FB SetSkillDisableCondition(entity, handle)[error, slot, add]
    error, slot, add = _val(n, 0), _slot(inst, _val(n, 1, 0xFFFFFFFF)), _val(n, 2)
    ent = _real(_ent(inst, ops, 0))
    st = _combat(inst).of(ent)
    if add:
        h = Handle("condition", ent)
        st.conditions.append((slot, error, h))
        _set(inst, ops, 1, h)
        _msg(inst, "disable_condition", ent, slot=slot, error=error, handle=h, add=True)
    else:
        h = inst.get(ops[1]) if len(ops) > 1 else None
        for c in list(st.conditions):
            if (h and c[2] == h) or (not h and c[0] == slot and c[1] == error):
                st.conditions.remove(c)
                _msg(inst, "disable_condition", ent, slot=c[0], error=c[1], handle=c[2], add=False)
                break
        _set(inst, ops, 1, 0)
    return False


def _set_usable_override(inst, n, ops, chain):   # 0x100000FC SetSkillUsableOverride(entity)[slot, enable, flag] -> 0x207B
    ent = _real(_ent(inst, ops, 0))
    slot, enable, flag = _slot(inst, _val(n, 0, 0xFFFFFFFF)), _val(n, 1), _val(n, 2)
    st = _combat(inst).of(ent)
    if enable:
        st.overrides[slot] = flag
    else:
        st.overrides.pop(slot, None)
    _msg(inst, "usable_override", ent, slot=slot, enable=enable, flag=flag)
    return False


def _ui_overlay(inst, n, ops, chain):            # 0x10000097 UpdateSkillUIOverlay(slot operand)[overlay, on, slot]
    slot = _slot(inst, _val(n, 2, 0xFFFFFFFF))
    if ops and not ops[0].is_unset():
        slot = _int(inst.get(ops[0]))
    _msg(inst, "ui_overlay", inst.source(), slot=slot, overlay=_val(n, 0), on=_val(n, 1))
    return False


def _stat_override(inst, n, ops, chain):         # 0x10000153 SetSkillStatOverride(value)[slot, stat]
    slot, stat = _slot(inst, _val(n, 0, 0xFFFFFFFF)), _val(n, 1)
    _combat(inst).of(inst.source()).stat_overrides.setdefault(slot, {})[stat] = num(inst.get(ops[0])) if ops else 0.0
    return False


def _clear_stat_override(inst, n, ops, chain):   # 0x1000008E ClearSkillStatOverride(entity)[slot]
    ent = _real(_ent(inst, ops, 0))
    slot = _slot(inst, _val(n, 0, 0xFFFFFFFF))
    _combat(inst).of(ent).stat_overrides.pop(slot, None)
    _call(inst, "clear_slot_presentation", ent, slot)     # 2026-11-02 (ics/skill_slots.py)
    if slot in getattr(ent, "slot_base", {}) and hasattr(inst.world, "revert_slot_skill"):
        # skill-mechanics-recipes.md 2 (C): every swapping script reverts its slot with this node
        inst.world.after(0.0, lambda: inst.world.revert_slot_skill(ent, slot))
    return False


def _set_slot_skill(inst, n, ops, chain):        # 0x10000089 SetSlotSkill(entity)[skill DID, flag]
    ent = _real(_ent(inst, ops, 0))
    did = _val(n, 0)
    # 2026-10-25 (skill-mechanics-recipes.md 2, C: all 16 nodes): the target slot is the record's 0x100000E6 (its
    # 0x1000003F / 0x100008E5 block), not the caller's slot (wrong for 9 of them); an explicit operand comes first
    slot = None
    if len(ops) > 2 and not ops[2].is_unset():
        slot = int(num(inst.get(ops[2])))
    if slot is None and did:
        slot = _record_slot(inst, did)
    if slot is None:
        slot = inst.slot
    if not _call(inst, "set_slot_skill", ent, slot, did, default=False):
        _log(inst, f"SetSlotSkill {did:#x} on slot {slot} (form swap; not applied)")
    return False


def _record_slot(inst, did):
    w = getattr(inst.world, "w", None)
    data = getattr(w, "data", None)
    if data is None:
        return None
    e = data.record(did)
    blk = records.get(e, 0x1000003F) or records.get(e, 0x100008E5)
    return records.as_dict(blk).get(0x100000E6) if blk else None


def _combo_state(inst, n, ops, chain):           # 0x1000017F SetSkillComboState(value)[7] (P: stored)
    _combat(inst).of(inst.source()).flags[("combo", _val(n, 0))] = inst.get(ops[0]) if ops else 0
    return False


def _reduce_cooldown(inst, n, ops, chain):       # 0x100000A3 ReduceCooldown(entity, seconds)[slot -1/-2/-3]
    ent = _real(_ent(inst, ops, 0))
    seconds = inst.number(_op(ops, 1))
    raw = _val(n, 0, 0xFFFFFFFF)
    c = _combat(inst)
    st = c.of(ent)
    now = _now(inst)
    if raw == 0xFFFFFFFE:
        slots = list(st.cooldowns)
    elif raw == 0xFFFFFFFD:
        slots = [s for s in st.cooldowns if s != inst.slot]
    else:
        slots = [_slot(inst, raw)]
    for s in slots:
        end = st.cooldowns.get(s, 0.0)
        if end > now:
            c.set_cooldown(ent, s, max(now, end - seconds))
    return False


def _reset_cooldown(inst, n, ops, chain):        # 0x100001AF ResetSkillCooldown(entity)[slot] (P, 5.9)
    ent = _real(_ent(inst, ops, 0))
    slot = _slot(inst, _val(n, 0, 0))
    if _combat(inst).of(ent).cooldowns.get(slot, 0.0) > _now(inst):
        _combat(inst).set_cooldown(ent, slot, _now(inst))
    return False


def _queue_order(inst, n, ops, chain):           # 0x100000DB QueueOrder(entity, target)[cmd, slot, ...] (P)
    ent = _real(_ent(inst, ops, 0))
    target = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else None
    _call(inst, "queue_order", ent, target, _val(n, 1, 0))
    return False


def _add_skill_target(inst, n, ops, chain):      # 0x1000000B AddSkillTarget(entity, target) (C)
    ent = _real(_ent(inst, ops, 0))
    t = inst.get(ops[1]) if len(ops) > 1 else None
    if t:
        _combat(inst).of(ent).skill_targets.append(t)
    return False


def _attached_skill(inst, n, ops, chain):        # 0x10000005 SetSkillAttached(entity)[flag]
    """2026-10-23 23:30 (tester: Atomic Green Lantern's Grab never pulls; skill-second-stages.md 2): after AddSkillTarget
    + SetSkillAttached the missile waits for 0x10000022 (attached -> S9: AttachEntity, the shooter's pull graph event)
    or 0x10000014 (failed -> drop); nothing raised them. P: raised on the script's own entity, by whether a live skill
    target other than itself is set ([ics] attached_skill_events)."""
    ent = _real(_ent(inst, ops, 0)) if ops else inst.source()
    _combat(inst).of(ent).flags["attached_skill"] = _val(n, 0)
    if _cfg(inst, "attached_skill_events", True):
        # 2026-10-25 (kit-audit-1.md 6: Atomic Wonder Woman's R does AddSkillTarget(SELF, SELF) and fell back to S0): the
        # entity itself counts as a valid skill target
        targets = [t for t in _combat(inst).of(ent).skill_targets
                   if t not in (None, 0) and (_real(t) is ent or _call(inst, "alive", t, default=False))]
        ev = 0x10000022 if targets else 0x10000014
        inst.after(0.0, lambda: None if getattr(inst, "removed", False) else inst.event(ev))
    return False


def _flag_node(key):
    def h(inst, n, ops, chain):
        ent = _real(_ent(inst, ops, 0)) if ops else inst.source()
        _combat(inst).of(ent).flags[key] = _val(n, 0)
        return False
    return h


def _collision(on):
    """0x1000006F DisableCollision / 0x10000070 EnableCollision (no fields; full-combat-skills.md 4.5, C): the
    script's entity leaves / rejoins collision. Server: an entity with collision off is not hit by missiles
    (CastWorld.collides). 2026-10-22: DisableCollision stored 0 (no field) and EnableCollision was a logged no-op."""
    def h(inst, n, ops, chain):
        if not _cfg(inst, "collision_toggle_own_entity", True):
            ent = _real(_ent(inst, ops, 0)) if ops else inst.source()
        else:
            # 2026-10-29 11:00 (tester: Grab pulls minions but never the enemy champion; agl-grab-arm.md 2, C: the client's
            # 0x97D860 / 0x97D720 take the script's own context entity (0x44C5C0), i.e. the missile for a missile script):
            # the shooter took the missile's DisableCollision before ([ics] collision_toggle_own_entity)
            ent = _ent(inst, ops, 0) if ops else inst.owner
        flags = _combat(inst).of(ent).flags
        if _cfg(inst, "collision_holders", True):
            # 2026-10-29 11:00 (same report; agl-grab-arm.md 2, C: 0x976990 keeps a list of 16-byte holder keys, one per
            # script run; Enable adds the run's key, Disable removes only that key and the body leaves collision only when
            # no holder of any kind is left): a run's DisableCollision undoes its own EnableCollision. A champion / unit /
            # structure is in collision by its template (P), so Robin's Vault Kick (Enable at the dash, Disable at its end)
            # no longer left him unhittable by every missile for the rest of the match ([ics] collision_holders)
            holds = flags.setdefault("collision_holds", set())
            if on:
                holds.add(inst.guid)
            else:
                holds.discard(inst.guid)
            kind = None
            kind_of = getattr(inst.world, "kind_of", None)
            if kind_of is not None and not isinstance(ent, Missile):
                try:
                    kind = kind_of(ent)
                except Exception:
                    kind = None
            template_holds = kind in ("champion", "unit", "structure", "prop")
            flags["collision_off"] = not holds and not template_holds
        else:
            flags["collision_off"] = not on
        return False
    return h


def _activate_slot(inst, n, ops, chain):         # 0x10000136 ActivateSlotSkill(target, position, slot)[event] (P)
    target = inst.get(ops[0]) if ops and not ops[0].is_unset() else None
    point = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else None
    slot = _int(inst.get(ops[2])) if len(ops) > 2 and not ops[2].is_unset() else inst.slot
    other = _call(inst, "slot_instance", inst.source(), slot)
    if other is not None and other is not inst:
        inst.after(0.0, lambda: R.activate(other, target, point))
    return False


def _get_targeting(inst, n, ops, chain):         # 0x10000148 GetSkillTargetingType(out, entity)[slot] (C)
    slot = _slot(inst, _val(n, 0, 0xFFFFFFFF))
    if len(ops) > 2 and not ops[2].is_unset():
        slot = _int(inst.get(ops[2]))
    _set(inst, ops, 0, _call(inst, "skill_targeting", inst.source(), slot, default=0) or 0)
    return False


def _in_range_and_angle(inst, n, ops):           # 0x10000052 IsInRangeAndAngle(min, max, angle, target, source)[r, r]
    target = inst.get(ops[3]) if len(ops) > 3 else None
    if target in (None, 0):
        return False
    src = inst.get(ops[4]) if len(ops) > 4 and not ops[4].is_unset() else inst.source()
    sp, tp = _position(inst, src), _position(inst, target)
    if sp is None or tp is None:
        return False
    d2 = (tp[0] - sp[0]) ** 2 + (tp[1] - sp[1]) ** 2
    mn = inst.number(_op(ops, 0))
    if mn and d2 < mn * mn:
        return False
    r = inst.number(_op(ops, 1))
    w = inst.world
    # 2026-10-23 18:00 (champion-kits-status.md 3: cone skills such as Katana's Slash missed every target 2 m away):
    # with the max operand unset the radius flags alone made a ~1 m range; only a set max range limits the distance
    ranged = len(ops) > 1 and not ops[1].is_unset() or not _cfg(inst, "range_angle_needs_max", True)
    if ranged and _val(n, 0) and not isinstance(src, tuple):
        r += _call(inst, "radius", src, default=0.5)
    if ranged and _val(n, 1) and not isinstance(target, tuple):
        r += _call(inst, "radius", target, default=0.5)
    if ranged and r > 0 and d2 > r * r:
        return False
    angle = inst.number(_op(ops, 2))
    if angle and angle not in (0.0, 360.0) and not isinstance(src, tuple):
        h = w.heading(src) if hasattr(w, "heading") else 0.0
        to = math.atan2(tp[1] - sp[1], tp[0] - sp[0])
        diff = abs((math.degrees(to - h) + 180.0) % 360.0 - 180.0)
        if diff > angle:
            return False
    return True


def _slot_of_script(inst, n, ops, chain):        # 0x100000F5 GetSkillSlotOfScript(out, entity)[script] (C)
    did = _val(n, 0) or inst.script.did
    ent = _real(_ent(inst, ops, 1))
    slot = _call(inst, "slot_of_script", ent, did)
    if slot is None:
        slot = inst.slot if did == inst.script.did and inst.slot is not None else 0xFFFFFFFF
    _set(inst, ops, 0, slot)
    return False


def _set_charges(inst, n, ops, chain):           # 0x10000169 SetCharges(value)[key] (P)
    _combat(inst).of(inst.source()).charges[_val(n, 0)] = inst.get(ops[0]) if ops else 0
    return False


def _get_charges(inst, n, ops, chain):           # 0x1000016B GetCharges(out)[key]: unchanged when nothing stored
    st = _combat(inst).of(inst.source())
    if _val(n, 0) in st.charges:
        _set(inst, ops, 0, st.charges[_val(n, 0)])
    return False


def _grant_currency(inst, n, ops, chain):        # 0x10000065 GrantCurrency(entity, amount)[type, flags] (P)
    ent = _real(_ent(inst, ops, 0))
    amount = inst.number(_op(ops, 1))
    _msg(inst, "currency", ent, amount=amount, type=_val(n, 0), flags=_val(n, 1))
    return False


# ---- attributes, vitals, damage (2) ----------------------------------------------------------------------

def _add_modifier(inst, n, ops, chain):          # 0x10000008 AddAttributeModifier(source, target, {value, handle, viewer})
    count = _val(n, 0)
    src = inst.get(ops[0]) if ops and not ops[0].is_unset() else inst.source()
    target = _real(_ent(inst, ops, 1))
    if target is None:
        return False
    c = _combat(inst)
    for k in range(count):
        attr, op = _val(n, 1 + 3 * k), _val(n, 2 + 3 * k)
        value_op, handle_op, viewer_op = _op(ops, 2 + 3 * k), _op(ops, 3 + 3 * k), _op(ops, 4 + 3 * k)
        value = inst.get(value_op) if value_op is not None and not value_op.is_unset() else 0
        if c.kind(attr) == 0x16 and (value_op is None or value_op.is_unset()):
            value = True                 # an unset value on a flag: set it (the stun's Stunned = true)
        team = -1
        if viewer_op is not None and not viewer_op.is_unset():
            v = inst.get(viewer_op)
            if isinstance(v, int) and not isinstance(v, bool) and v < 0x100:
                team = v
        h = c.add_modifier(target, attr, op, value, source=src, team=team)
        if handle_op is not None:
            old = inst.get(handle_op)
            if isinstance(old, Handle) and old.kind == "modifier":
                c.remove_modifier(target, old, attr)        # the same handle variable re-used: replace
            inst.set(handle_op, h)
    return False


def _remove_modifier(inst, n, ops, chain):       # 0x10000033 RemoveAttributeModifier(source, target, handles...)
    count = _val(n, 0)
    target = _real(_ent(inst, ops, 1))
    c = _combat(inst)
    for k in range(count):
        attr = _val(n, 1 + k)
        hop = _op(ops, 2 + k)
        h = inst.get(hop) if hop is not None else None
        if isinstance(h, Handle):
            if not c.remove_modifier(target, h, attr):
                c.remove_modifier(h.owner, h, attr)
        if hop is not None:
            inst.set(hop, 0)
    return False


def _get_vital(inst, n, ops, chain):             # 0x100000CE GetVital(entity, out, handle)[vital, temp, max] (C)
    ent = _real(_ent(inst, ops, 0))
    vital, temp, maximum = _val(n, 0, 2), _val(n, 1), _val(n, 2)
    if temp:
        h = inst.get(ops[2]) if len(ops) > 2 and not ops[2].is_unset() else None
        st = _combat(inst).of(ent)
        if isinstance(h, Handle) and h in st.shields:
            s = st.shields[h]
            v = s[2] if maximum else s[1]
        else:
            v = sum((s[2] if maximum else s[1]) for s in st.shields.values() if s[0] == vital)
    else:
        v = inst.world.vital(ent, vital, bool(maximum)) if hasattr(inst.world, "vital") else 0.0
    _set(inst, ops, 1, float(v))
    return False


def _vital_threshold(inst, n, ops):              # 0x1000001A VitalThreshold(threshold, entity)[vital, %, negate, cmp]
    vital, pct, negate, cmp = _val(n, 0, 2), _val(n, 1), _val(n, 2), _val(n, 3, 1)
    ent = _real(_ent(inst, ops, 1))
    w = inst.world
    if not hasattr(w, "vital"):
        return True
    cur = w.vital(ent, vital, False)
    t = inst.number(_op(ops, 0))
    if pct:
        t *= w.vital(ent, vital, True)
    if negate:
        t = -t
    ok = {2: cur != t, 3: cur == t, 4: cur < t, 5: cur <= t, 6: cur > t}.get(cmp, cur >= t)
    if not ok and negate and cmp == 1 and inst.slot is not None:
        _msg(inst, "resource_error", ent, slot=inst.slot, kind=2 if vital == 2 else 1)
    return ok


def _add_temp_vital(inst, n, ops, chain):        # 0x10000093 AddTempVital(amount, entity, -, out handle, duration)
    vital, pct = _val(n, 0, 2), _val(n, 1)
    target = _real(inst.ent(ops[1])) if len(ops) > 1 else inst.owner
    amount = inst.number(_op(ops, 0))
    if pct:
        amount *= inst.world.vital(target, vital, True) if hasattr(inst.world, "vital") else 0.0
    h = Handle("shield", target)
    _combat(inst).of(target).shields[h] = [vital, amount, amount, inst.source()]
    _set(inst, ops, 3, h)
    duration = inst.number(_op(ops, 4))
    if duration > 0:
        inst.world.after(duration, lambda: _drop_shield(inst.world, target, h))
    _call(inst, "vitals_changed", target)
    return False


def _drop_shield(world, ent, h):
    if world.combat.of(ent).shields.pop(h, None) is not None and hasattr(world, "vitals_changed"):
        world.vitals_changed(ent)


def _remove_temp_vital(inst, n, ops, chain):     # 0x10000092 RemoveTempVital(entity, handle) (C)
    ent = _real(_ent(inst, ops, 0))
    h = inst.get(ops[1]) if len(ops) > 1 else None
    if isinstance(h, Handle):
        _drop_shield(inst.world, h.owner if h.owner is not None else ent, h)
    _set(inst, ops, 1, 0)
    return False


def _start_vot(inst, n, ops, chain):             # 0x10000040 StartVitalOverTime(amount/s, target, max, out handle, duration)
    vital, pct, is_damage, _show, _c, kind = (_val(n, i) for i in range(6))
    vital = vital or 2
    target = _real(inst.ent(ops[1])) if len(ops) > 1 else inst.owner
    rate = inst.number(_op(ops, 0))
    duration = inst.number(_op(ops, 4))
    h = Handle("vot", target)
    w = inst.world
    # source: a status' applier (R.acting_entity; meltdown-moving-target.md 6.2: Radiation Sickness' DoT is AGL's)
    vot = {"vital": vital, "rate": rate, "pct": pct, "damage": is_damage, "kind": kind, "source": R.acting_entity(inst),
           "ends": w.time + duration if duration > 0 else None, "last": w.time}
    _combat(inst).of(target).vots[h] = vot
    _set(inst, ops, 3, h)

    def tick():
        st = w.combat.of(target)
        if h not in st.vots or not w.alive(target):
            return
        end = vot["ends"]
        _vot_apply(w, target, vot, min(w.time, end) if end is not None else w.time)
        if end is not None and w.time + 1e-6 >= end:
            st.vots.pop(h, None)
            return
        w.after(min(VOT_TICK, end - w.time) if end is not None else VOT_TICK, tick)
    w.after(VOT_TICK if duration <= 0 else min(VOT_TICK, duration), tick)
    return False


def _vot_apply(w, target, vot, until):
    """The amount of a vital-over-time effect from its last tick to until (a stop applies the partial tick)."""
    dt = max(0.0, until - vot["last"])
    vot["last"] = until
    if dt <= 0:
        return
    vital, kind = vot["vital"], vot["kind"]
    amount = vot["rate"] * dt
    if vot["pct"]:
        amount *= w.vital(target, vital, True)
    # values [vital, %, a, b, c, kind]: kind = the damage type (0 = a regeneration / heal, 1 attack, 2 power,
    # 3 true); data: DamageOverTime [2 0 1 1 0 2], Constrict's root [2 0 0 1 0 2], HealthRegen [2 0 0 0 0 0]
    if kind or vot["damage"] or amount < 0:
        if vital == 2:
            deal_damage(w, vot["source"], target, abs(amount), kind or 3, flags=(0, 0, 0, 0, 1))
        else:
            w.set_vital(target, vital, w.vital(target, vital) - abs(amount))
            w.vitals_changed(target)
    elif amount > 0:
        if vital == 2:
            heal(w, vot["source"], target, amount)
        else:
            w.set_vital(target, vital, w.vital(target, vital) + amount)
            w.vitals_changed(target)


def _stop_vot(inst, n, ops, chain):              # 0x10000009 StopVitalOverTime(entity, handle) (C)
    ent = _real(_ent(inst, ops, 0))
    h = inst.get(ops[1]) if len(ops) > 1 else None
    if isinstance(h, Handle):
        owner = h.owner if h.owner is not None else ent
        vot = _combat(inst).of(owner).vots.pop(h, None)
        if vot is not None and inst.world.alive(owner):
            end = vot["ends"]
            _vot_apply(inst.world, owner, vot, min(inst.world.time, end) if end is not None else inst.world.time)
    _set(inst, ops, 1, 0)
    return False


def _add_redirect(inst, n, ops, chain):          # 0x10000149 AddDamageRedirect(fraction, ..., handle, -, linked)
    target = inst.owner if not isinstance(inst.owner, Missile) else inst.source()
    h = Handle("redirect", target)
    linked = inst.get(ops[5]) if len(ops) > 5 and not ops[5].is_unset() else None
    _combat(inst).of(target).redirects[h] = (inst.number(_op(ops, 0)), linked, _val(n, 2))
    _set(inst, ops, 3, h)
    return False


def _remove_redirect(inst, n, ops, chain):       # 0x1000014A RemoveDamageRedirect(entity, handle)
    h = inst.get(ops[1]) if len(ops) > 1 else None
    if isinstance(h, Handle):
        _combat(inst).of(h.owner).redirects.pop(h, None)
    _set(inst, ops, 1, 0)
    return False


DAMAGE_PIPELINE_EVENTS = [True]              # [ics] damage_pipeline_events (set by ics/server.py)
OWNER_DAMAGED_EVENT = [True]                 # [ics] owner_damaged_event (set by ics/server.py)


def deal_damage(world, source, target, amount, dtype=1, crit=False, flags=(0, 1, 1, 0, 1), slot=None):
    """The damage pipeline (2 A.5; mitigation, crit and lifesteal are server-only formulas, P): crit, armor and
    penetration, redirects, shields, health, lifesteal, then the combat event 0x10000020 on both sides."""
    if target is None or amount <= 0 or not world.alive(target):
        return 0.0
    immune = getattr(world, "immune", None)
    if immune is not None and immune(target, source, slot):
        return 0.0                     # a target that only the flow's skill hurts (the practice targets)
    c = world.combat
    guards = c.guarded(target)
    if 100 in guards:
        return 0.0
    attr = c.attribute
    raw = float(amount)
    if crit:
        raw *= float(attr(source, ATTR_CRIT_DAMAGE) or 2.0) if source is not None else 2.0
    if getattr(world, "mitigation", True) and dtype in (1, 2):
        armor = float(attr(target, ATTR_ATTACK_ARMOR if dtype == 1 else ATTR_POWER_ARMOR) or 0.0)
        pct = float(attr(source, ATTR_ATTACK_PEN_PCT if dtype == 1 else ATTR_POWER_PEN_PCT) or 0.0) if source else 0.0
        flat = float(attr(source, ATTR_ATTACK_PEN if dtype == 1 else ATTR_POWER_PEN) or 0.0) if source else 0.0
        eff = max(0.0, armor * (1.0 - min(max(pct, 0.0), 1.0)) - flat)
        raw = raw * 100.0 / (100.0 + eff)
    for _h, (fraction, linked, _kind) in list(c.of(target).redirects.items()):
        if linked is not None and fraction and world.alive(linked):
            part = raw * float(fraction)
            raw -= part
            deal_damage(world, source, linked, part, 3, flags=(0, 0, 0, 0, 1))
    dealt = raw
    shields = {h: v[1] for h, v in c.of(target).shields.items()}
    left = c.absorb(target, raw)
    if DAMAGE_PIPELINE_EVENTS[0]:
        # 2026-10-25 (kit-audit-3.md 2: Poison Ivy E, Superman passive, Wonder Woman W, Zatanna E, Stargirl R waited for
        # their shield to break): a drained shield raises 0x1000008C {VitalExpiredHandle 0x09E49315} on its owner
        for h, before in shields.items():
            cur = c.of(target).shields.get(h)
            if before > 0 and cur is not None and cur[1] <= 0:
                R.raise_event(world, target, 0x1000008C, {0x09E49315: h})
    if 0 in guards and hasattr(world, "vital"):
        hp = world.vital(target, 2)
        if left >= hp and DAMAGE_PIPELINE_EVENTS[0]:
            # 2026-10-25 (kit-audit-3.md 2: Nightmare Superman and Solomon Grundy could never die): a type-0 defeat guard
            # that stops a lethal hit raises 0x1000011B {KillerIID 0x032C3FD4} on the entity (its passive decides)
            R.raise_event(world, target, 0x1000011B, {0x032C3FD4: source})
        left = min(left, max(0.0, world.vital(target, 2) - 1.0)) if 0 in c.guarded(target) else left
    if dealt > 0 and hasattr(world, "queue_floaty"):
        # 2026-10-26 (deep-scan-s2c.md 1, C: the floating damage numbers come only from 0x42's third list)
        world.queue_floaty(source, target, int(dtype or 1), -float(dealt), 0)
    if left > 0:
        world.damage(source, target, left)
    elif hasattr(world, "vitals_changed"):
        world.vitals_changed(target)
    if dealt > 0 and OWNER_DAMAGED_EVENT[0]:
        # 2026-10-25 (kit-audit-1.md 2: 29 scripts of 6 champions, e.g. Doomsday's passive, Atrocitus / Dex-Starr rage,
        # Arcane Harley and Atomic Poison Ivy R): the damaged entity's scripts get 0x100000ED, the attacker in 0xC89C7B4
        R.raise_event(world, target, 0x100000ED, {0xC89C7B4: source})
    if dealt > 0 and _world_cfg(world, "match_stats_ledger", True):
        # 2026-10-25 (hud-shop-timeline-kills.md 6.3): the end page's per-player damage stats
        who_ = source.owner if isinstance(source, Missile) else source
        champ_src = getattr(who_, "kind", "") == "champion"
        champ_tgt = getattr(target, "kind", "") == "champion"
        if champ_src:
            st = who_.__dict__.setdefault("match_stats", {})
            for k in ("dealt", f"dealt_{dtype}") + (("dealt_champ", f"dealt_champ_{dtype}") if champ_tgt else ()):
                st[k] = st.get(k, 0.0) + dealt
        if champ_tgt:
            st = target.__dict__.setdefault("match_stats", {})
            for k in ("taken",) + (("taken_champ", f"taken_champ_{dtype}") if champ_src else ()):
                st[k] = st.get(k, 0.0) + dealt
            if amount > dealt:
                st["reduced"] = st.get("reduced", 0.0) + (amount - dealt)
    if dealt > 0 and hasattr(target, "__dict__") and _world_cfg(world, "kill_card_damage_ledger", True):
        # 2026-10-25 (hud-shop-timeline-kills.md 5.3): damage taken this life by attacker / skill slot / damage type,
        # for the death screen's kill card (reset at the respawn)
        who = source.owner if isinstance(source, Missile) else source
        key = getattr(who, "eid", None)
        if key is not None:
            rec = target.__dict__.setdefault("damage_ledger", {}).setdefault(
                key, {"total": 0.0, "slots": {}, "types": {}, "by_type": {}})
            rec["total"] += dealt
            s_ = slot if isinstance(slot, int) and 1 <= slot <= 4 else 0
            if s_:
                rec["slots"][s_] = rec["slots"].get(s_, 0.0) + dealt
                rec["types"][s_] = dtype
            rec["by_type"][dtype] = rec["by_type"].get(dtype, 0.0) + dealt
    if dealt > 0 and _world_cfg(world, "damage_family_events", True):
        # 2026-10-25 (skill-mechanics-recipes.md 6, C params: Atrocitus W, Swamp Thing / Raven passives wait for them):
        # 0x100000E7 {HealthDelta, DamageType, ResponsibleIID} on the victim; 0x10000145 {SourceIID, SkillSlot} when a
        # champion's Q / W / E / R did it
        R.raise_event(world, target, 0x100000E7, {0x4AC3A1: -dealt, "DamageType": dtype, 0x335FDC4: source})
        owner = source.owner if isinstance(source, Missile) else source
        if isinstance(slot, int) and 1 <= slot <= 4 and getattr(owner, "kind", "") == "champion":
            R.raise_event(world, target, 0x10000145, {0xC89C7B4: owner, 0x31D944: slot})
    if source is not None and len(flags) > 2 and flags[1] and dtype in (1, 2) and dealt > 0:
        steal = float(attr(source, ATTR_ATTACK_LIFESTEAL if dtype == 1 else ATTR_POWER_LIFESTEAL) or 0.0)
        if 0.0 < steal < 5.0:
            heal(world, source, source, dealt * steal)
    params = {R.PARAM_A: source, R.PARAM_B: target, R.PARAM_VALUE: dealt,
              "IncomingDamageType": dtype, "TriggeringDamageType": dtype, "DamageAmount": dealt}
    for ent in (target, source):
        if ent is not None:
            R.raise_event(world, ent, R.EVENT_COMBAT, params)
    return dealt


def heal(world, source, target, amount):
    if amount <= 0 or target is None or not world.alive(target):
        return 0.0
    if hasattr(world, "heal"):
        world.heal(source, target, amount)
    for ent, key in ((source, "healed"), (target, "heal_received")):
        if getattr(ent, "kind", "") == "champion":
            st = ent.__dict__.setdefault("match_stats", {})
            st[key] = st.get(key, 0.0) + amount
    return amount


def _damage_slot(inst):
    """The skill slot behind a script's damage: the script's own (a skill / basic attack), a status script's, or the
    slot of the skill that launched the missile running it (Missile.origin_slot)."""
    if inst.slot is not None:
        return inst.slot
    owner = inst.owner
    if isinstance(owner, Missile):
        return owner.origin_slot if owner.origin_slot is not None else owner.slot
    slot = getattr(inst, "status_slot", None)
    return slot if slot is not None else getattr(owner, "origin_slot", None)   # an entity a skill spawned


def _apply_damage(inst, n, ops, chain):          # 0x1000001D ApplyDamage(amount, target, crit, slot, source, out ok, DID)
    amount = inst.number(_op(ops, 0))
    target = inst.get(ops[1]) if len(ops) > 1 else None
    if len(ops) > 1 and ops[1].is_self():
        target = inst.owner
    # an unset source: a status' applier (R.acting_entity, meltdown-moving-target.md 6.2), else the owner / shooter
    src = inst.get(ops[4]) if len(ops) > 4 and not ops[4].is_unset() else R.acting_entity(inst)
    crit = bool(inst.get(ops[2])) if len(ops) > 2 and not ops[2].is_unset() else False
    flags = tuple(_val(n, i) for i in range(4)) + (_val(n, 6, 1),)
    dtype = _val(n, 4, 1) or 1
    w = inst.world
    ok = bool(target) and not isinstance(target, tuple) and amount > 0 and w.alive(target)
    if amount <= 0 and _cfg(inst, "zero_damage_probe", True):
        # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Bullseye's arrow
        # 0x3400043D S1 runs ApplyDamage($ZeroDamage, target, .., $DamageSuccess) and deals the real hit only when
        # DamageSuccess holds; 0x34000453 / 0x340004CF / 0x3400077A do the same): a zero hit on a live target that can be
        # damaged succeeds without dealing anything ([ics] zero_damage_probe)
        tgt = _real(target)
        probe = bool(tgt) and not isinstance(tgt, tuple) and w.alive(tgt)
        immune = getattr(w, "immune", None)
        if probe and immune is not None and immune(tgt, _real(src), _damage_slot(inst)):
            probe = False
        if probe and hasattr(w, "combat") and 100 in w.combat.guarded(tgt):
            probe = False
        _set(inst, ops, 5, probe)
        return False
    if _cfg(inst, "damage_success_first", True):
        # 2026-10-25 (skill-mechanics-recipes.md 5, C: Shazam's chain 0x340006FF stopped after one hop): the damage
        # pipeline's 0x10000020 re-checks this instance mid-chain; DamageSuccess must already be written then
        _set(inst, ops, 5, bool(ok))
    dealt = deal_damage(w, _real(src), _real(target), amount, dtype, crit, flags, slot=_damage_slot(inst)) if ok else 0.0
    _set(inst, ops, 5, bool(ok and dealt >= 0))     # out: DamageSuccess (missile 0x3400003F ends when it is false)
    if ok and inst.slot == 0 and getattr(inst, "status", None) is None and _cfg(inst, "basic_hit_event", True):
        # 2026-10-24 23:30 (tester: Atomic Wonder Woman's W never empowers her next basic attack; aww-kit.md): a basic
        # attack's hit raises 0x1000008B {TargetIID} on the attacker's scripts (her W status 0x3400026A waits for it;
        # Zod and Arcane Green Lantern count it too)
        R.raise_event(w, _real(src), 0x1000008B, {"TargetIID": target})
    slot = _damage_slot(inst)
    if ok and isinstance(slot, int) and 1 <= slot <= 4 and getattr(inst, "status", None) is None             and _cfg(inst, "skill_hit_event", True):
        # 2026-10-25 (kit-audit-1.md 1: 21 scripts of 7 champions wait for it, e.g. Atomic Wonder Woman's R refills her
        # Rev, Catwoman / Blue Beetle / Atrocitus / Dex-Starr passives): a Q/W/E/R hit raises 0x1000008A {TargetIID,
        # slot 0x31D944} on the attacker's scripts, the skill twin of 0x1000008B
        R.raise_event(w, _real(src), 0x1000008A, {"TargetIID": target, 0x31D944: slot})
    elif (ok and isinstance(slot, int) and 1 <= slot <= 4 and getattr(inst, "status", None) is not None
          and _val(n, 1) == 1 and _cfg(inst, "skill_hit_event", True) and _cfg(inst, "status_skill_hit_event", True)):
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00: a Meltdown hit must slow the enemy; meltdown-moving-target.md
        # 1.5 / 3.4 / 6.3, P from the game's own description: each pulse gives Radiation Sickness stacks): the damage of
        # a status a champion's Q/W/E/R applied is that skill's hit too, when the node triggers on-hit effects (value b =
        # 1; proc damage has 0, so a listener cannot feed itself). Raised after the current chain, as the client VM
        # queues events (0x96DED0): Meltdown's jump test sees the stacks from before its pulse ([ics]
        # status_skill_hit_event)
        actor, victim = _real(src), _real(target)
        if actor is not None and actor is not victim and getattr(actor, "kind", "champion") == "champion":
            params = {"TargetIID": target, 0x31D944: slot}
            w.after(0.0, lambda: R.raise_event(w, actor, 0x1000008A, params))
    return False


def _roll_critical(inst, n, ops, chain):         # 0x1000010B RollCritical(out roll, target, -) (A.5, P)
    chance = num(_combat(inst).attribute(inst.source(), ATTR_CRIT_CHANCE) or 0.0)
    _set(inst, ops, 0, bool(chance > 0 and random.random() < chance))
    return False


def _get_level(inst, n, ops, chain):             # 0x1000004B GetLevel(out, entity): property 0x10000167 (C)
    ent = _real(_ent(inst, ops, 1))
    lvl = _call(inst, "level", ent)
    if lvl is None:
        lvl = _combat(inst).base_value(ent, PROP_LEVEL) or 1
    _set(inst, ops, 0, _int(num(lvl), 1) if lvl else 1)
    return False


def _defeat_type(inst, n, ops, chain):           # 0x10000162 SetDefeatType(out handle, entity)[enable, type] (P)
    ent = _real(_ent(inst, ops, 1))
    st = _combat(inst).of(ent)
    if _val(n, 0):
        h = Handle("defeat", ent)
        st.defeat_guards[h] = _val(n, 1)
        _set(inst, ops, 0, h)
    else:
        h = inst.get(ops[0]) if ops else None
        if isinstance(h, Handle):
            st.defeat_guards.pop(h, None)
        else:
            for k, v in list(st.defeat_guards.items()):
                if v == _val(n, 1):
                    del st.defeat_guards[k]
        _set(inst, ops, 0, 0)
    return False


def _skill_stat_override(inst, n, ops, chain):   # 0x100000FA SetSkillStatOverride(entity)[slot .. TFX ..] (P)
    """2026-10-28 15:00 (test-2026-10-28-1439-sweep.md S11, P): not a floaty text (it was run as ShowFloatyStatus and
    logged "floaty_text"). Vtable 0x15FD158 (factory 0x99C5E0) has purecall 0x134D420 in slots 7 and 10: a server-only
    node. Values: 0 = the skill slot (0xFFFFFFFF = this skill), 11 = a TFX DID (AWW's passive 0x34000265: slots 1 / 2 / 3
    with 0x1300148F / 90 / 91, the empowered-skill effects; its counterpart is ClearSkillStatOverride), 13 / 14 = a
    pair (Super Strength 0x34000164: (1, 1) then (1, 13)). Its wire message is unknown (O): logged, nothing sent, as
    before."""
    slot = _val(n, 0)
    _msg(inst, "skill_stat_override (P, not sent)", _real(_ent(inst, ops, 0)),
         slot=("this" if slot == 0xFFFFFFFF else slot), tfx=f"{_val(n, 11):#x}", pair=(_val(n, 13), _val(n, 14)))
    # 2026-11-02: the button's presentation (name, description, icon, targeting) goes to the client as the slot's table
    # (ics/skill_slots.py; [ics] slot_tables)
    own = slot in (0xFFFFFFFF, -1, None)
    if not (own and inst.slot is None):                   # a status script's "this skill" has no button
        _call(inst, "slot_presentation", _real(_ent(inst, ops, 0)), _slot(inst, slot), list(n.values))
    return False


def _floaty_number(inst, n, ops, chain):         # 0x10000118 ShowFloatingNumber(value)[...] (P: no message found)
    _msg(inst, "floaty_number", inst.source(), value=inst.number(_op(ops, 0)))
    return False


def _display_floaty(inst, n, ops, chain):        # 0x100001AD DisplayFloatyStatus(entity)[id] -> 0x20BD (C)
    _msg(inst, "floaty_status", _real(_ent(inst, ops, 0)), kind=_val(n, 0))
    return False


# ---- status effects (3) ----------------------------------------------------------------------------------

def _status_target(inst, ops, i):
    t = inst.get(ops[i]) if len(ops) > i and not ops[i].is_unset() else inst.owner
    if len(ops) > i and ops[i].is_self():
        t = inst.owner
    return _real(t)


def _apply_skill(inst, n, ops, chain):           # 0x10000027 ApplySkill(target, duration, rank, value, effect, DID, handle, slot, ok, source)
    status = _val(n, 0)
    if not status and len(ops) > 4 and not ops[4].is_unset():
        status = _int(inst.get(ops[4])) if not isinstance(inst.get(ops[4]), int) else inst.get(ops[4])
    target = _status_target(inst, ops, 0)
    ok = False
    current = None
    if status and target is not None and not isinstance(target, tuple) and inst.world.alive(target):
        params = R._params(inst, ops, R.APPLY_PARAMS)
        if len(ops) > 9 and not ops[9].is_unset():
            params["EffectSource"] = inst.get(ops[9])
        params.setdefault("SourceEntityDID", inst.var_by_name("SourceEntityDID") or
                          _call(inst, "skill_ref", inst.source()))
        # the applier: a status' own applier for the statuses it applies (R.acting_entity, meltdown-moving-target.md 6.2:
        # Radiation Sickness' slow 0x48000294 is AGL's)
        current = R.apply_status(inst.world, R.acting_entity(inst), target, status, params, inst.world)
        ok = current is not None
        if current is not None and len(ops) > 7 and not ops[7].is_unset():
            current.slot_applied = inst.get(ops[7])
        if current is not None and getattr(current, "status_slot", None) is None:
            current.status_slot = _damage_slot(inst)     # its damage counts as the applying skill's
    if len(ops) > 6 and not ops[6].is_unset():
        inst.set(ops[6], current if current is not None else 0)
    _set(inst, ops, 8, ok)
    return False


def _add_stacks(inst, n, ops, chain):            # 0x100000D9 AddStacks(target, duration, -, value, -, DID, count) (P)
    status = _val(n, 0)
    target = _status_target(inst, ops, 0)
    count = max(1, _int(inst.number(_op(ops, 6), 1.0), 1))
    stacks = R.STACKS_RESOLVER(status) if R.STACKS_RESOLVER else 1
    if not status or target is None:
        return False
    params = R._params(inst, ops, R.APPLY_PARAMS)
    if R.STATUS_STACK_MODEL:
        # 2026-10-25 (skill-mechanics-recipes.md 1, P strong: the decays pass --GetStackCount): the absolute count, once
        absolute = _int(inst.number(_op(ops, 6), 1.0), 1)
        R.apply_status(inst.world, R.acting_entity(inst), target, status, params, inst.world, count=absolute)
        return False
    for _ in range(min(count, max(stacks, 1))):
        R.apply_status(inst.world, R.acting_entity(inst), target, status, params, inst.world)
    return False


def _match_statuses(inst, target, handle=None, status=0, flags=0):
    w = inst.world
    if isinstance(handle, R.Instance):
        return [handle] if not handle.removed else []
    running = R.statuses_on(w, target)
    if status:
        return list(running.get(status, []))
    if flags:
        return [i for did, lst in running.items() if R.status_flags(did) & flags for i in lst]
    return []


def _has_status(inst, n, ops):                   # 0x100000A4 HasStatus(target, statusVar, handle)[status, flags] (C)
    target = _status_target(inst, ops, 0)
    if target is None:
        return False
    status = _val(n, 0)
    if len(ops) > 1 and not ops[1].is_unset():
        v = inst.get(ops[1])
        status = v if isinstance(v, int) else status
    h = inst.get(ops[2]) if len(ops) > 2 and not ops[2].is_unset() else None
    if status:
        return bool(R.statuses_on(inst.world, target).get(status)) or inst.world.has_status(target, status)
    if _val(n, 1):
        return bool(_match_statuses(inst, target, flags=_val(n, 1)))
    if isinstance(h, R.Instance):
        return not h.removed and h.owner is target
    return False


def _remove_status(inst, n, ops, chain):         # 0x10000018 RemoveStatus(target, handle, -, slot)[flags, status, all]
    flags, status = _val(n, 0), _val(n, 1)
    h = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else None
    explicit_target = len(ops) > 0 and not ops[0].is_unset()
    if not explicit_target and not h and not status and not flags:
        # (-, -, -, -)[0 0 0]: the running status removes itself (48 uses)
        if inst.status is not None:
            if _cfg(inst, "status_self_remove_after_chain", True):
                # 2026-10-28 15:00 (tester report 2026-10-28 15:00; meltdown-moving-target.md 3.7 / 6.5, P for the VM
                # rule: 10 status scripts have nodes after their self-removal, Meltdown's jump then decrements AGL's
                # PulsesRemaining): the removal happens once the current chain has run, so the rest of it still runs
                # (a jump gave the next target one pulse too many) ([ics] status_self_remove_after_chain)
                if not getattr(inst, "removing", False):
                    inst.removing = True
                    w = inst.world
                    w.after(0.0, lambda: R.remove_status(w, inst.owner, inst.status, inst))
                return False
            R.remove_status(inst.world, inst.owner, inst.status, inst)
            return True
        return False
    target = _status_target(inst, ops, 0)
    if isinstance(h, R.Instance):
        target = h.owner
    victims = _match_statuses(inst, target, h, status, flags)
    if not victims and not explicit_target and not h and status and inst.status == status:
        victims = [inst]
    for v in victims:
        R.remove_status(inst.world, v.owner, v.status, v)
    if h is not None and len(ops) > 1:
        inst.set(ops[1], 0)
    return inst.removed


def _set_status_duration(inst, n, ops, chain):   # 0x100000CA SetStatusDuration(target, handle, -, seconds)[0, status, add]
    status, add = _val(n, 1), _val(n, 2)
    h = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else None
    seconds = inst.number(_op(ops, 3))
    target = _status_target(inst, ops, 0)
    if isinstance(h, R.Instance):
        victims = [h]
    elif status:
        victims = _match_statuses(inst, target, None, status)
    else:
        victims = [inst] if inst.status is not None else []
    for v in victims:
        R.set_status_duration(inst.world, v, seconds, bool(add))
        for ih, info in _combat(inst).of(v.owner).icons.items():
            if info.get("instance") is v:
                _msg(inst, "icon_update", v.owner, handle=ih, stacks=info.get("stacks", 0),
                     duration=getattr(v, "duration", 0.0), source=info.get("source"))
    return False


def _stack_count(inst, n, ops, chain):           # 0x100000FE GetStackCount(target, out)[status] (P)
    target = _status_target(inst, ops, 0)
    running = R.statuses_on(inst.world, target).get(_val(n, 0), [])
    _set(inst, ops, 1, sum(int(getattr(i, "stack_count", 1) or 1) for i in running))
    return False


def _load_status_stats(inst, n, ops, chain):     # 0x10000177 LoadStatusStats(source, vars...)[count, stats] (P)
    count = _val(n, 0)
    stats = [_val(n, 1 + k) for k in range(count)]
    ref = inst.var_by_name("SourceEntityDID")
    rank = inst.var_by_name("EffectRank") or inst.var_by_name("SkillRank") or 1
    rank = _int(num(rank), 1) if rank else 1
    for k, stat in enumerate(stats):
        op = _op(ops, 1 + k)
        if op is None:
            continue
        if hasattr(ref, "stat"):
            value = ref.stat(stat, rank)
        else:
            value = inst.world.skill_stat(inst.source(), stat, rank)
        inst.set(op, value)
    return False


def _disable_actions(inst, n, ops, chain):       # 0x1000005B DisableActions(entity, out handle)[family, 1, priority] (P)
    ent = _real(_ent(inst, ops, 0))
    h = Handle("action", ent)
    st = _combat(inst).of(ent)
    st.locks[h] = (_val(n, 0), _val(n, 2))
    _set(inst, ops, 1, h)
    _call(inst, "on_cc", ent)
    return False


def stop_action(world, h):
    """End whatever a handle names: an action lock, a dash / knockback, an attachment, an AI move."""
    if not isinstance(h, Handle):
        return False
    ent = h.owner
    st = world.combat.of(ent)
    if h in st.locks:
        del st.locks[h]
        if hasattr(world, "on_cc"):
            world.on_cc(ent)
        return True
    m = st.motion
    if m is not None and m.get("handle") == h:
        _end_motion(world, ent, interrupted=True)
        return True
    if h.kind == "ai_move" and hasattr(world, "stop"):
        world.stop(ent)
        return True
    if h.kind == "attach":
        st.flags.pop(("attached", h.n), None)
        return True
    return False


def _stop_action(inst, n, ops, chain):           # 0x10000081 StopAction(entity, handle)
    h = inst.get(ops[1]) if len(ops) > 1 else None
    stop_action(inst.world, h)
    return False


def _lock_input(inst, n, ops, chain):            # 0x100000AD LockInput(entity)[on] (C client half; server: moves ignored)
    ent = _real(_ent(inst, ops, 0))
    st = _combat(inst).of(ent)
    st.input_locks = max(0, st.input_locks + (1 if _val(n, 0) else -1))
    _call(inst, "on_cc", ent)
    return False


def _set_untargetable(inst, n, ops, chain):      # 0x100000C8 SetUntargetable(entity)[flag] (P)
    ent = _real(_ent(inst, ops, 0))
    st = _combat(inst).of(ent)
    key = ("untargetable", inst.guid)
    if _val(n, 0) and key not in st.flags:
        st.flags[key] = _combat(inst).add_modifier(ent, ATTR_TARGETABLE, 6, False, source=inst.source())
    elif not _val(n, 0) and key in st.flags:
        _combat(inst).remove_modifier(ent, st.flags.pop(key), ATTR_TARGETABLE)
    return False


def _is_stealthed(inst, n, ops):                 # 0x10000143 IsStealthed(target) (P: the stealth attribute)
    t = _status_target(inst, ops, 0)
    return t is not None and _combat(inst).flag(t, ATTR_STEALTH)


def _is_revealed(inst, n, ops):                  # 0x10000144 IsRevealed(target)[1] (P: no vision model -> false)
    return False


def _combat_event(inst, n, ops):                 # 0x1000002C OnCombatEventByKind(-> A, B, value)[event, maskA, maskB]
    ev = _val(n, 0)
    if inst.current_event != ev or R.PARAM_A not in inst.params:
        return False
    a, b = inst.params.get(R.PARAM_A), inst.params.get(R.PARAM_B)
    w = inst.world
    if _val(n, 1) and not w.kind_matches(a, _val(n, 1)):
        return False
    if _val(n, 2) and not w.kind_matches(b, _val(n, 2)):
        return False
    _set(inst, ops, 0, a)
    _set(inst, ops, 1, b)
    _set(inst, ops, 2, inst.params.get(R.PARAM_VALUE, 0))
    return True


def _icon_entity(inst, ops, i):
    return _real(_ent(inst, ops, i))


def _add_icon(inst, n, ops, chain):              # 0x100000A7 AddStatusIcon(out handle, entity, stacks, source, duration, DID, src2, icon var)
    ent = _icon_entity(inst, ops, 1)
    icon = _val(n, 0)
    if len(ops) > 7 and not ops[7].is_unset():
        icon = inst.get(ops[7]) or icon
    stacks = _int(inst.number(_op(ops, 2)))
    source = inst.get(ops[3]) if len(ops) > 3 and not ops[3].is_unset() else None
    duration = inst.number(_op(ops, 4))
    h = Handle("icon", ent)
    _combat(inst).of(ent).icons[h] = {"icon": icon, "stacks": stacks, "source": source, "duration": duration,
                                      "instance": inst if inst.status is not None else None}
    _set(inst, ops, 0, h)
    _msg(inst, "icon_add", ent, handle=h, icon=icon, stacks=stacks, duration=duration, source=_real(source),
         priority=_val(n, 1, 0xFFFFFFFF))
    return False


def _icon_handle(inst, ops, n_icon=None):
    h = inst.get(ops[0]) if ops and not ops[0].is_unset() else None
    ent = _icon_entity(inst, ops, 1)
    st = _combat(inst).of(ent)
    if isinstance(h, Handle):
        return ent, h, st.icons.get(h) or _combat(inst).of(h.owner).icons.get(h)
    if n_icon:
        for k, info in st.icons.items():
            if info["icon"] == n_icon:
                return ent, k, info
    return ent, None, None


def _update_icon(inst, n, ops, chain):           # 0x100000A8 UpdateStatusIcon(handle, entity, stacks, duration, source)
    ent, h, info = _icon_handle(inst, ops)
    if info is None:
        return False
    if len(ops) > 2 and not ops[2].is_unset():
        info["stacks"] = _int(inst.number(ops[2]))
    if len(ops) > 3 and not ops[3].is_unset():
        info["duration"] = inst.number(ops[3])
    if len(ops) > 4 and not ops[4].is_unset():
        info["source"] = inst.get(ops[4])
    _msg(inst, "icon_update", ent, handle=h, stacks=info["stacks"], duration=info["duration"],
         source=_real(info["source"]))
    return False


def _remove_icon(inst, n, ops, chain):           # 0x100000A6 RemoveStatusIcon(handle, entity)[0 0 1] -> 0x20E9
    ent, h, info = _icon_handle(inst, ops)
    if h is not None and info is not None:
        _combat(inst).of(h.owner if h.owner is not None else ent).icons.pop(h, None)
        _msg(inst, "icon_remove", ent, handle=h)
    if ops:
        inst.set(ops[0], 0)
    return False


def _icon_stats(inst, n, ops, chain):            # 0x1000016A UpdateStatusIconStats(handle, entity, DID, values)[icon, n, (i, attr)]
    icon, count = _val(n, 0), _val(n, 1)
    ent, h, info = _icon_handle(inst, ops, icon)
    pairs = []
    for k in range(count):
        idx, attr = _val(n, 2 + 2 * k), _val(n, 3 + 2 * k)
        pairs.append((idx, attr, inst.number(_op(ops, 3 + k))))
    if h is not None:
        _msg(inst, "icon_stats", ent, handle=h, icon=icon or (info or {}).get("icon", 0), pairs=pairs)
    return False


def _refresh_icon(inst, n, ops, chain):          # 0x10000116 RefreshStatusIcon(handle, entity)[icon] -> 0x2127 (P)
    ent, h, _info = _icon_handle(inst, ops, _val(n, 0))
    if h is not None:
        _msg(inst, "icon_refresh", ent, handle=h)
    return False


def _stop_scriptlet(inst, n, ops, chain):        # 0x10000102 StopScriptlet(entity, handle)[fx] (C client half)
    ent = _real(_ent(inst, ops, 0))
    h = inst.get(ops[1]) if len(ops) > 1 else None
    key = h[1] if isinstance(h, tuple) and len(h) in (3, 4) and h[0] == "scriptlet" else None
    run = h[3] if isinstance(h, tuple) and len(h) == 4 and h[0] == "scriptlet" else None
    if run is not None:
        _call(inst, "stop_scriptlet", ent, key=key, run=run)     # that handle's own run (2026-11-03)
    else:
        _call(inst, "stop_scriptlet", ent, key=key)
    fx = _val(n, 0)
    if fx:
        inst.world.run_scriptlet(ent, 0x100003EA, variables=[(0x1000050A, fx)])
    _set(inst, ops, 1, 0)
    return False


def _stop_scriptlet_key(inst, n, ops, chain):    # 0x10000012 StopScriptletKey(entity)[key] (C)
    ent = _real(_ent(inst, ops, 0))
    _call(inst, "stop_scriptlet", ent, key=_val(n, 0))
    return False


def _run_fx_scriptlet(inst, n, ops, chain):      # 0x1000013A RunFxScriptlet: RunScriptlet + variable 0x1000050A = fx (C)
    key = _val(n, 0) or 0x100003EA
    fx = n.values[-1] if n.values and isinstance(n.values[-1], int) else 0
    ent = _real(_ent(inst, ops, 0))
    count = _val(n, 1) if _val(n, 1) < 8 else 0
    ids = [_val(n, 2 + k) for k in range(count)]
    variables = [(i, inst.get(o)) for i, o in zip(ids, ops[2:2 + count])] + ([(0x1000050A, fx)] if fx else [])
    if ent is not None:
        inst.world.run_scriptlet(ent, key, variables=variables)
    return False


# ---- missiles, hotspots, spawned entities, movement (4) ---------------------------------------------------

def _launch(inst, n, ops, kind="straight"):
    cls = next((v for v in n.values[:1] if isinstance(v, int) and v >> 24 == 0x40), None)
    override = next((v for v in n.values[1:2] if isinstance(v, int) and v >> 24 == 0x34), 0)
    target = inst.get(ops[1]) if len(ops) > 1 else None
    rng = inst.number(_op(ops, 2))
    speed = inst.number(_op(ops, 3))
    offset = inst.get(ops[5]) if len(ops) > 5 and not ops[5].is_unset() else None
    existing = inst.get(ops[0]) if ops and not ops[0].is_unset() else None
    slot = inst.get(ops[7]) if len(ops) > 7 and not ops[7].is_unset() else None
    w = inst.world
    if not target:
        return None
    if existing not in (None, 0) and cls is None:
        cls = _call(inst, "class_of", existing, default=0) or 0
        scripts = []                    # the spawned entity runs its own scripts already
    else:
        scripts = R.missile_scripts(cls, override)
    if not isinstance(cls, int) or (not cls and existing in (None, 0)):
        # an entity launched as the missile that does not exist (its SpawnEntity made nothing): nothing flies
        _log(inst, "LaunchMissile: no class and no entity to launch")
        return None
    extra = {"entity": existing if existing not in (None, 0) else None, "offset": offset,
             "lobbed": kind == "lobbed", "tether": kind == "tether", "slot": slot}
    shooter = inst.source()
    if existing in (None, 0) and getattr(inst, "status", None) is not None:
        actor = R.acting_entity(inst)
        if R._key(actor) != R._key(shooter):
            # 2026-10-28 15:00 (tester report 2026-10-28 15:00: Meltdown ended after one pulse; meltdown-moving-target.md
            # 3.3 / 6.2, C headless): a new missile a status launches is its applier's (its 0x100004E2, team, the shooter
            # stats LoadSkillStats($ShooterIID) reads, the hit event to the applier's script) and starts at the status'
            # owner. Not an entity a status launches itself (knock-ups 0x340003E7 / 0x34000655 launch SELF).
            shooter = actor
            extra["origin"] = inst.owner
    try:
        m = w.launch_missile(shooter, cls, target, speed, rng, scripts, **extra)
    except TypeError:
        m = w.launch_missile(shooter, cls, target, speed, rng, scripts)
    if m is not None and getattr(inst, "casting", 0):
        inst.cast_missiles = list(getattr(inst, "cast_missiles", [])) + [m]   # the cast's end waits for a tether
    if m is not None and getattr(m, "origin_slot", None) is None:
        m.origin_slot = inst.slot if inst.slot is not None else _damage_slot(inst)
    if m is not None and len(ops) > 4:
        inst.set(ops[4], m)
    if m is not None and kind == "lobbed" and len(ops) > 6 and not ops[6].is_unset():
        inst.set(ops[6], Handle("lobbed", inst.owner))   # a thrown / knocked-up entity's motion handle (0x340003E7)
    return m


def _missile(inst, n, ops, chain):               # 0x1000005E LaunchMissile(entity, target, range, speed, out, offset)
    _launch(inst, n, ops)
    return False


def _lobbed(inst, n, ops, chain):                # 0x10000154 LaunchLobbedMissile (P: a straight flight to the point)
    _launch(inst, n, ops, "lobbed")
    return False


def _tethered(inst, n, ops, chain):              # 0x1000005F LaunchTetheredMissile (P: out and back, 0x10000005)
    _launch(inst, n, ops, "tether")
    return False


def _missile_velocity(inst, n, ops, chain):      # 0x10000134 SetMissileVelocity(missile, speed) (P)
    m = inst.get(ops[0]) if ops and not ops[0].is_unset() else inst.owner
    if isinstance(m, Missile):
        m.set_speed(inst.number(_op(ops, 1)))
    return False


def _hotspot(inst, n, ops, chain, aura=False):   # 0x10000059 CreateHotspot / 0x10000122 CreateAura (4.2)
    a, b, c_, mask, kinds, shape = (_val(n, i) for i in range(6))
    w = inst.world
    # owner: the team, relation and status source; a status' applier (R.acting_entity, meltdown-moving-target.md 6.2;
    # Arcane Harley's Delirium aura 0x34000781 buffs her allies, Fear Incarnate's 0x3400048B fears her victim's allies).
    # here: where an aura sits / a hotspot starts by default, the status' owner (SELF)
    owner = R.acting_entity(inst)
    here = inst.source()
    lifetime = inst.number(_op(ops, 0))
    rank = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else 1
    durations = (lifetime, inst.number(_op(ops, 4)), inst.number(_op(ops, 6)))
    radius, length = inst.number(_op(ops, 7)), inst.number(_op(ops, 8))
    height, width = inst.number(_op(ops, 9)), inst.number(_op(ops, 10))
    where = inst.get(ops[12]) if len(ops) > 12 and not ops[12].is_unset() else None
    if len(ops) > 12 and ops[12].is_self():
        where = inst.owner
    if aura:
        attached, position = (where if where not in (None, 0) and not isinstance(where, tuple) else here), None
    else:
        attached = None
        position = _position(inst, where) or w.position(here)
    hs = Hotspot(owner, shape, radius, length, height, width, mask, kinds, (a, b, c_), durations, rank,
                 position=position, attached=attached, lifetime=lifetime)
    hs.slot = _damage_slot(inst)                       # the statuses it applies count as this skill's
    if getattr(inst, "status", None) is not None and R._key(owner) != R._key(inst.owner):
        # 2026-10-28 15:00 (tester report 2026-10-28 15:00; meltdown-moving-target.md 6.2, with the applier's side): the
        # status' own carrier is no target of the aura it carries, as SELF in FindTargets (the aura's flag [0] "include
        # the owner" is 0 in every hotspot and aura of the data); and a status it holds on a unit that already had it is
        # not the aura's to remove. Solomon Grundy's plague 0x340006AB (spreads to the victim's allies) re-infected its
        # own carrier and recursed through the infected's auras otherwise ([ics] status_acts_for_source)
        hs.exclude = inst.owner
    w.combat.add_hotspot(hs)
    visual = _val(n, 11) if not aura else 0
    if visual and hasattr(w, "spawn_entity"):
        hs.visual = w.spawn_entity(owner, visual, position, visual=True)
    _set(inst, ops, 13, hs.visual if (not aura and hs.visual is not None) else hs.handle)
    if not aura and hs.visual is not None:
        w.combat.of(hs.visual).flags["hotspot"] = hs.handle
    if lifetime > 0:
        hs.ends = w.time + lifetime
    _hotspot_tick(w, hs)
    if lifetime > 0:
        w.after(lifetime, lambda: end_hotspot(w, hs))
    return False


def _hotspot_tick(w, hs):
    if not hs.alive:
        return
    if hs.attached is not None and not w.alive(hs.attached) and not (hasattr(w, "exists") and w.exists(hs.attached)):
        end_hotspot(w, hs)
        return
    center = hs.center(w)
    reach = max(hs.radius, hs.length, hs.width or 0.0) + 1.0
    found = []
    exclude = getattr(hs, "exclude", None)             # a status' carrier (_hotspot)
    for e in w.find_targets(center, reach, hs.kinds) if center is not None else []:
        if exclude is not None and R._key(e) == R._key(exclude):
            continue
        if hs.kinds and not w.kind_matches(e, hs.kinds):
            continue
        if hs.mask and not relation_matches(w, hs.owner, e, hs.mask):
            continue
        if hs.contains(w, e):
            found.append(e)
    keys = {R._key(e): e for e in found}
    for k, e in keys.items():
        if k not in hs.inside:
            inst_a = None
            if hs.a:
                dur_a = 0.0
                ends = getattr(hs, "ends", None)
                if ends is not None and HOTSPOT_STATUS_DURATION[0]:
                    # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; champion_check: Arcane
                    # Zatanna's Silent Sorceress aura status 0x3400064C deals TotalDamage / EffectDuration per second, and a
                    # 0 s EffectDuration made it 0): the status held while inside gets the hotspot's remaining time
                    # ([ics] hotspot_status_duration)
                    dur_a = max(0.0, ends - w.time)
                had = exclude is not None and bool(R.statuses_on(w, e).get(hs.a))
                inst_a = R.apply_status(w, hs.owner, e, hs.a, {"EffectDuration": dur_a, "EffectRank": hs.rank,
                                                              "EffectSource": hs.owner})
                if had:
                    inst_a = None                      # a refresh of its own status: not removed on leaving (_hotspot)
            inst_b = None
            if hs.b:
                inst_b = R.apply_status(w, hs.owner, e, hs.b, {"EffectDuration": hs.dur_b, "EffectRank": hs.rank,
                                                               "EffectSource": hs.owner})
            for i in (inst_a, inst_b):
                if i is not None and getattr(i, "status_slot", None) is None:
                    i.status_slot = getattr(hs, "slot", None)
            hs.inside[k] = (e, inst_a)
    for k in [k for k in hs.inside if k not in keys]:
        _leave_hotspot(w, hs, k)
    w.after(HOTSPOT_TICK, lambda: _hotspot_tick(w, hs))


def _leave_hotspot(w, hs, k):
    e, inst_a = hs.inside.pop(k)
    if inst_a is not None and not inst_a.removed:
        R.remove_status(w, e, hs.a, inst_a)
    if hs.c and w.alive(e):
        R.apply_status(w, hs.owner, e, hs.c, {"EffectDuration": hs.dur_c, "EffectRank": hs.rank,
                                              "EffectSource": hs.owner})


def end_hotspot(w, hs):
    if not hs.alive:
        return
    hs.alive = False
    for k in list(hs.inside):
        _leave_hotspot(w, hs, k)
    w.combat.hotspots.pop(hs.handle, None)
    if hs.visual is not None and hasattr(w, "destroy"):
        w.destroy(hs.visual, 0.0)


def _destroy_hotspot(inst, n, ops, chain):       # 0x1000002D DestroyHotspot(-, hotspot entity, handle)[1]
    w = inst.world
    for i in (2, 1, 0):
        v = inst.get(ops[i]) if len(ops) > i and not ops[i].is_unset() else None
        if len(ops) > i and ops[i].is_self():
            v = inst.owner
        hs = None
        if isinstance(v, Handle):
            hs = w.combat.hotspots.get(v)
        elif v not in (None, 0):
            h = w.combat.of(v).flags.get("hotspot")
            hs = w.combat.hotspots.get(h) if h else None
        if hs is not None:
            end_hotspot(w, hs)
        if len(ops) > i and i > 0 and isinstance(v, Handle):
            inst.set(ops[i], 0)
    return False


def _resize_hotspot(inst, n, ops, chain):        # 0x10000137 ResizeHotspot(hotspot, -, length, width, height, -, handle)
    w = inst.world
    for i in (6, 0):
        v = inst.get(ops[i]) if len(ops) > i and not ops[i].is_unset() else None
        h = v if isinstance(v, Handle) else (w.combat.of(v).flags.get("hotspot") if v not in (None, 0) else None)
        hs = w.combat.hotspots.get(h) if h else None
        if hs is not None:
            hs.length, hs.width, hs.height = (inst.number(_op(ops, 2)), inst.number(_op(ops, 3)),
                                              inst.number(_op(ops, 4)))
            hs.shape = _val(n, 0, hs.shape)
            break
    return False


def _spawn(inst, n, ops, chain):                 # 0x100000A0 SpawnEntity(position, backup, scatter, -, out IID, props...)[..., class, n, ids]
    cls = _val(n, 6)
    count = _val(n, 7)
    ids = [_val(n, 8 + k) for k in range(count)]
    pos = _position(inst, inst.get(ops[0]) if ops and not ops[0].is_unset() else None)
    if pos is None:
        pos = _position(inst, inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else None)
    w = inst.world
    owner = inst.source()
    if pos is None:
        pos = w.position(owner)
    scatter = inst.number(_op(ops, 2))
    if scatter > 0:
        a = random.uniform(0, 2 * math.pi)
        d = random.uniform(0, scatter)
        pos = (pos[0] + d * math.cos(a), pos[1] + d * math.sin(a), pos[2] if len(pos) > 2 else 0.0)
    props = [(pid, inst.get(o)) for pid, o in zip(ids, ops[5:5 + count])]
    ent = w.spawn_entity(owner, cls, pos, props) if cls and hasattr(w, "spawn_entity") else None
    if ent is not None and not isinstance(ent, (str, int)) and getattr(ent, "origin_slot", None) is None:
        try:
            ent.origin_slot = _damage_slot(inst)       # its scripts' damage counts as this skill's (Sonic Shell)
        except AttributeError:
            pass
    _set(inst, ops, 4, ent if ent is not None else 0)
    return False


def _spawn_from_shooter(inst, n, ops, chain):    # 0x100001B0 SpawnFromShooter(entity)[class, 1, 1] (P)
    ent = _real(_ent(inst, ops, 0))
    cls = _val(n, 0)
    if cls and hasattr(inst.world, "spawn_entity"):
        inst.world.spawn_entity(ent, cls, inst.world.position(ent), [])
    return False


def _get_properties(inst, n, ops, chain):        # 0x10000155 GetEntityProperties(entity, vars...)[n, props] (C: reads)
    ent = _ent(inst, ops, 0)
    count = _val(n, 0)
    for k in range(count):
        prop = _val(n, 1 + k)
        v = _call(inst, "entity_property", _real(ent), prop)
        _set(inst, ops, 1 + k, v if v is not None else 0)
    return False


def _get_creator(inst, n, ops, chain):           # 0x100000A5 GetCreator(out) (C: the context / source entity)
    owner = inst.owner
    if isinstance(owner, Missile):
        c = owner.owner
    else:
        c = _combat(inst).of(owner).creator or inst.params.get(R.V.elf_hash("EffectSource")) or owner
        if inst.status is not None and inst.var_by_name("EffectSource"):
            c = inst.var_by_name("EffectSource")
    _set(inst, ops, 0, c)
    return False


def _attach(inst, n, ops, chain):                # 0x1000008F AttachEntity(child, parent, offset, out handle, -, out ok) (P)
    raw = _ent(inst, ops, 0)
    if isinstance(raw, Missile) and _cfg(inst, "attach_missile_itself", True):
        # 2026-10-25 11:30 (tester: when Grab hits a drone, the drone and AGL swap places): AttachEntity(SELF, Target)
        # in a missile script attaches the MISSILE (the hand) to the target; _real turned it into the shooter, who then
        # followed the target while the tether dragged the target to him. The missile's flight is the server's own.
        parent = _real(inst.get(ops[1])) if len(ops) > 1 and not ops[1].is_unset() else inst.source()
        ok = parent is not None and inst.world.alive(parent)
        h = Handle("attach", raw)
        _set(inst, ops, 3, h if ok else 0)
        _set(inst, ops, 5, bool(ok))
        return False
    child = _real(raw)
    parent = _real(inst.get(ops[1])) if len(ops) > 1 and not ops[1].is_unset() else inst.source()
    if _cfg(inst, "attach_parent_first", True):
        # 2026-10-25 (champion-animation-matrix.md cause 7, P: Arcane Green Lantern's passive dragged the champion onto
        # its lantern every 0.1 s; Grab attaches the target to the missile): AttachEntity is (parent, child)
        child, parent = parent, child
    w = inst.world
    ok = child is not None and parent is not None and w.alive(parent) if hasattr(w, "alive") else True
    h = Handle("attach", child)
    if ok:
        st = w.combat.of(child)
        st.flags[("attached", h.n)] = parent

        def follow():
            if st.flags.get(("attached", h.n)) is not parent or not w.alive(parent):
                st.flags.pop(("attached", h.n), None)
                return
            if hasattr(w, "move"):
                w.move(child, w.position(parent), quiet=True)
            w.after(0.1, follow)
        follow()
    _set(inst, ops, 3, h if ok else 0)
    _set(inst, ops, 5, bool(ok))
    return False


def _pick_up(inst, n, ops, chain):               # 0x10000042 PickUpEntity(entity, out ok) (P)
    e = _real(_ent(inst, ops, 0))
    ok = e is not None and inst.world.alive(e) and not any(
        k[0] == "attached" for k in inst.world.combat.of(e).flags if isinstance(k, tuple))
    _set(inst, ops, 1, bool(ok))
    return False


def _get_radius(inst, n, ops, chain):            # 0x10000120 GetEntityRadius(entity, out) (C)
    _set(inst, ops, 1, float(_call(inst, "radius", _real(_ent(inst, ops, 0)), default=0.5)))
    return False


def _is_moving(inst, n, ops):                    # 0x100000E1 IsMoving(entity)[walking too] (P)
    e = _real(_ent(inst, ops, 0))
    forced = _combat(inst).of(e).motion is not None
    if _cfg(inst, "is_moving_flag_walks", True):
        # 2026-10-29 11:00 (tester: Grab never pulls the enemy champion; agl-grab-arm.md 2.3, P): r1 = 0 is a forced
        # movement only (knockback / dash / pull), r1 = 1 any movement. Grab 0x340002C1 pulls only when NOT
        # IsMoving(target)[0] (else S11: damage, no pull), so a walking bot was never pulled; recall 0x3400000A tests
        # IsMoving(SELF)[0] next to "moved more than 0.25 m" (walking is that test's job), the get-up 0x34000131 waits
        # for NOT IsMoving(SELF)[0] (the knock flight). Off = r1 0 walking only, 1 walking or forced, as before
        if forced:
            return True
        return bool(_val(n, 0)) and bool(_call(inst, "is_moving", e, default=False))
    if _call(inst, "is_moving", e, default=False):
        return True
    return bool(_val(n, 0)) and forced


def _is_in_front(inst, n, ops):                  # 0x1000016F IsInFront(target, -, observer) (P: front half-space)
    t = inst.get(ops[0]) if ops else None
    o = _real(_ent(inst, ops, 2))
    if t in (None, 0) or o is None:
        return False
    tp, op_ = _position(inst, t), inst.world.position(o)
    h = inst.world.heading(o) if hasattr(inst.world, "heading") else 0.0
    return (tp[0] - op_[0]) * math.cos(h) + (tp[1] - op_[1]) * math.sin(h) >= 0.0


def _start_motion(inst, ent, dest, speed, handle, kind, events=True, follow=None, timeout=0.0):
    """A forced movement (dash / knockback): the entity moves at speed to dest; events on the owning script."""
    w = inst.world
    st = w.combat.of(ent)
    if st.motion is not None:
        _end_motion(w, ent, interrupted=True)
    start = w.position(ent)
    dist = _dist2d(start, dest)
    speed = max(speed, 0.1)
    m = {"handle": handle, "kind": kind, "dest": dest, "inst": inst, "events": events, "follow": follow,
         "done": False}
    st.motion = m
    w.move(ent, dest, speed=speed) if hasattr(w, "move") else None
    _call(inst, "on_cc", ent)
    duration = dist / speed
    if timeout and duration > timeout:
        duration = timeout

    def arrive():
        if st.motion is m and not m["done"]:
            _end_motion(w, ent, interrupted=False)
    w.after(duration, arrive)
    if events and kind == "dash":
        inst.after(0.0, lambda: inst.event(EV_DASH_STARTED))
        # 4.4: the dash raises 0x10000002 for every unit / prop it touches on the way (charge-through hits)
        for along, e in _entities_on_line(w, ent, start, dest, 1.0):
            def touch(e=e):
                if st.motion is m and not m["done"]:
                    inst.event(R.EVENT_COLLISION, {"Collider": e, "SubEntity": 0, "EntityPosition": w.position(e),
                                                   0xAE98CBC: 0})
            w.after(max(0.0, min(along / speed, duration - 0.02)), touch)
    return m


def _entities_on_line(w, me, start, dest, width):
    """(distance along, entity) of the entities within width of the segment start -> dest, nearest first."""
    dx, dy = dest[0] - start[0], dest[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return []
    out = []
    mid = ((start[0] + dest[0]) / 2, (start[1] + dest[1]) / 2, 0.0)
    for e in w.find_targets(mid, length / 2 + width, 0x11108):
        if e is me or e == me:
            continue
        p = w.position(e)
        t = ((p[0] - start[0]) * dx + (p[1] - start[1]) * dy) / length
        off = abs((p[0] - start[0]) * dy - (p[1] - start[1]) * dx) / length
        if -width <= t <= length + width and off <= width:
            out.append((max(0.0, t), e))
    return sorted(out, key=lambda x: x[0])


def _end_motion(w, ent, interrupted):
    st = w.combat.of(ent)
    m = st.motion
    if m is None or m["done"]:
        return
    m["done"] = True
    st.motion = None
    if hasattr(w, "motion_end"):
        w.motion_end(ent, None if interrupted else m["dest"])
    if hasattr(w, "on_cc"):
        w.on_cc(ent)
    inst = m["inst"]
    if not m["events"] or inst.removed:
        return
    if m["kind"] == "dash":
        inst.event(EV_DASH_INTERRUPTED if interrupted else EV_DASH_ARRIVED)
    elif m["kind"] == "knockback":
        inst.event(EV_KNOCKBACK_DONE)


def _dash_to_position(inst, n, ops, chain):      # 0x100000EA DashToPosition(entity, target, speed, max, min, wall, out h, out started)
    ent = _real(_ent(inst, ops, 0))
    target = inst.get(ops[1]) if len(ops) > 1 else None
    w = inst.world
    dest = _position(inst, target)
    start = w.position(ent) if ent is not None else None
    if ent is None or dest is None or start is None or not _combat(inst).can_move(ent) and \
            _combat(inst).of(ent).motion is None:
        _set(inst, ops, 7, False)
        inst.after(0.0, lambda: inst.event(EV_DASH_FAILED))
        return False
    speed = inst.number(_op(ops, 2), 10.0) or 10.0
    mx, mn = inst.number(_op(ops, 3)), inst.number(_op(ops, 4))
    wall = inst.number(_op(ops, 5))
    dx, dy = dest[0] - start[0], dest[1] - start[1]
    d = math.hypot(dx, dy)
    if d < 1e-3:
        dx, dy, d = math.cos(w.heading(ent)), math.sin(w.heading(ent)), 1.0
        want = mn
    else:
        want = d
    if mx > 0:
        want = min(want, mx)
    if mn > 0:
        want = max(want, mn)
    dest = (start[0] + dx / d * want, start[1] + dy / d * want, start[2] if len(start) > 2 else 0.0)
    snapped = _call(inst, "clip_line", start, dest, wall)
    if snapped is not None:
        dest = snapped
    h = Handle("dash", ent)
    _set(inst, ops, 6, h)
    _set(inst, ops, 7, True)
    _start_motion(inst, ent, dest, speed, h, "dash", timeout=num(_val(n, 0)) if _val(n, 0) < 1000 else 0.0)
    return False


def _dash_to_entity(inst, n, ops, chain):        # 0x1000013E DashToEntity(entity, target, speed, out h, out started)
    ent = _real(_ent(inst, ops, 0))
    target = _real(inst.get(ops[1])) if len(ops) > 1 else None
    w = inst.world
    if ent is None or target in (None, 0) or not w.alive(target):
        _set(inst, ops, 4, False)
        inst.after(0.0, lambda: inst.event(EV_DASH_FAILED))
        return False
    speed = inst.number(_op(ops, 2), 10.0) or 10.0
    stop = R.f32(_val(n, 0)) if _val(n, 0) else 1.0
    tp, sp = w.position(target), w.position(ent)
    d = _dist2d(sp, tp)
    keep = stop * (_call(inst, "radius", target, default=0.5) + _call(inst, "radius", ent, default=0.5))
    k = max(0.0, d - keep) / d if d > 1e-3 else 0.0
    dest = (sp[0] + (tp[0] - sp[0]) * k, sp[1] + (tp[1] - sp[1]) * k, sp[2] if len(sp) > 2 else 0.0)
    h = Handle("dash", ent)
    _set(inst, ops, 3, h)
    _set(inst, ops, 4, True)
    timeout = R.f32(_val(n, 2)) if _val(n, 2) else 15.0
    _start_motion(inst, ent, dest, speed, h, "dash", follow=target, timeout=timeout)
    return False


def _knockback(inst, n, ops, chain):             # 0x100000C6 Knockback(entity, source, duration, speed, distance, out h)
    ent = _real(_ent(inst, ops, 0))
    src = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else inst.source()
    w = inst.world
    duration, speed, distance = (inst.number(_op(ops, i)) for i in (2, 3, 4))
    if not distance:
        distance = speed * duration
    if not speed:
        speed = distance / duration if duration > 0 else 10.0
    sp = _position(inst, src)
    ep = w.position(ent) if ent is not None else None
    h = Handle("knockback", ent)
    _set(inst, ops, 5, h)
    if ep is None or sp is None:
        return False
    dx, dy = ep[0] - sp[0], ep[1] - sp[1]
    d = math.hypot(dx, dy)
    if d < 1e-3:
        hd = w.heading(_real(src)) if not isinstance(src, tuple) else 0.0
        dx, dy, d = math.cos(hd), math.sin(hd), 1.0
    dest = (ep[0] + dx / d * distance, ep[1] + dy / d * distance, ep[2] if len(ep) > 2 else 0.0)
    snapped = _call(inst, "clip_line", ep, dest, 0.0)
    if snapped is not None:
        dest = snapped
    _start_motion(inst, ent, dest, speed, h, "knockback")
    return False


def _cancel_movement(inst, n, ops, chain):       # 0x1000001B CancelMovement(entity) (P)
    ent = _real(_ent(inst, ops, 0))
    _call(inst, "stop", ent)
    return False


def _movement_mode(inst, n, ops, chain):         # 0x100000F1 SetMovementMode(entity)[mode, priority] (P: recorded)
    ent = _real(_ent(inst, ops, 0))
    _combat(inst).of(ent).movement_modes[_val(n, 1)] = _val(n, 0)
    return False


def _snap_to_ground(inst, n, ops, chain):        # 0x100000B0 SnapToGround(position)[reset orientation, own z] (C)
    p = inst.get(ops[0]) if ops else None
    if not isinstance(p, tuple):
        return False
    z = _call(inst, "ground_z", p)
    if _val(n, 1) or z is None:
        z = inst.world.position(inst.source())[2] if z is None else z
    q = (p[0], p[1], float(z))
    inst.set(ops[0], R.Frame(q, 0.0 if _val(n, 0) else getattr(p, "yaw", 0.0)))
    return False


def _find_position(inst, ops, teleport=False, backup=None):
    """FindScatterPosition / FindValidPosition: a pathable point near the center (random within the radius)."""
    w = inst.world
    p = inst.get(ops[0]) if ops and not ops[0].is_unset() else None
    center = inst.get(ops[1]) if len(ops) > 1 and not ops[1].is_unset() else None
    if len(ops) > 1 and ops[1].is_self():
        center = inst.owner
    base = _position(inst, p) or _position(inst, center) or w.position(inst.source())
    radius = inst.number(_op(ops, 2))
    out = base
    for _ in range(10):
        if radius > 0:
            a, d = random.uniform(0, 2 * math.pi), random.uniform(0, radius)
            cand = (base[0] + d * math.cos(a), base[1] + d * math.sin(a), base[2] if len(base) > 2 else 0.0)
        else:
            cand = tuple(base[:3])
        if _call(inst, "walkable", cand, default=True):
            out = cand
            break
    else:
        if backup is not None:
            out = backup
    inst.set(ops[0], R.Frame(out, getattr(p, "yaw", 0.0)))
    if teleport:
        who = _real(_ent(inst, ops, 3))
        if who is not None and hasattr(w, "move"):
            w.move(who, out, teleport=True)
    return out


def _find_scatter(inst, n, ops, chain):          # 0x10000025 FindScatterPosition(pos, center, radius, entity)[..., teleport]
    out = _find_position(inst, ops, teleport=bool(n.values and n.values[-1] == 1 and len(n.values) >= 7))
    if len(ops) > 3 and not ops[3].is_unset() and not ops[3].is_self() and _cfg(inst, "hotspot_follows_position", True):
        # 2026-10-28 (tester: "the champions' R do no damage to the enemy champion"; with centred box hotspots, Mecha
        # Wonder Woman's W 0x340002CA moves its dash box every update with node_10000025($CurrentPosition, -, -,
        # $HotspotIID) [1 ..] and resizes it with 0x10000137): the hotspot named by operand 3 moves to the point, keeping
        # its facing ([ics] hotspot_follows_position)
        w = inst.world
        v = inst.get(ops[3])
        h = v if isinstance(v, Handle) else (w.combat.of(v).flags.get("hotspot")
                                             if v not in (None, 0) and hasattr(w, "combat") else None)
        hs = w.combat.hotspots.get(h) if h and hasattr(w, "combat") else None
        if hs is not None and hs.attached is None and out is not None:
            yaw = getattr(hs.position, "yaw", None)
            hs.position = R.Frame(tuple(out[:3]), yaw) if yaw is not None else tuple(out[:3])
    return False


def _find_valid(inst, n, ops, chain):            # 0x10000109 / 0x10000146 FindValidPosition(2)
    backup = _position(inst, inst.get(ops[1])) if len(ops) > 1 and not ops[1].is_unset() else None
    _find_position(inst, ops, backup=backup)
    return False


def _teleport_effects(on):
    def h(inst, n, ops, chain):                  # 0x1000007D / 0x1000007F Begin / EndTeleport -> 0x218A / 0x2189 (P)
        _msg(inst, "teleport_effects", _real(_ent(inst, ops, 0)), on=on)
        return False
    return h


def _camera_heading(inst, n, ops, chain):        # 0x10000141 GetCameraHeading(out)[+180]: the champion's facing (C/P)
    h = math.degrees(inst.world.heading(inst.source())) + (180.0 if _val(n, 0) else 0.0)
    old = inst.get(ops[0]) if ops else None
    if isinstance(old, tuple):
        r = math.radians(h)
        _set(inst, ops, 0, (math.cos(r), math.sin(r), 0.0))
    else:
        _set(inst, ops, 0, h % 360.0)
    return False


def _destruction(inst, n, ops, chain):           # 0x10000085 DestructionImpulse -> 0x8A sphere / 0x1 box (C)
    origin, shape, level, default_mag = _val(n, 0), _val(n, 1, 1), _val(n, 2), _val(n, 3)
    fx, key = _val(n, 4), _val(n, 5)
    pos = _position(inst, inst.get(ops[4])) if len(ops) > 4 and not ops[4].is_unset() else None
    if pos is None:
        pos = inst.world.position(inst.owner)
    mag = inst.number(_op(ops, 5)) if len(ops) > 5 and not ops[5].is_unset() else R.f32(default_mag)
    _msg(inst, "destruction", inst.source(), shape=shape, pos=tuple(pos[:3]), radius=inst.number(_op(ops, 0)),
         length=inst.number(_op(ops, 1)), dim_x=inst.number(_op(ops, 2)), dim_z=inst.number(_op(ops, 3)),
         magnitude=mag, level=level, key=key, fx=fx, flag=_val(n, 8), origin=origin,
         heading=inst.world.heading(inst.source()) if hasattr(inst.world, "heading") else 0.0)
    return False


# ---- entity lists, teams, predicates, AI (5) ---------------------------------------------------------------

def _list_clear(inst, n, ops, chain):            # 0x100000C1 ClearList
    inst.lists = []
    return False


def _list_add(inst, n, ops, chain):              # 0x100000C2 AddToList(value)
    v = inst.get(ops[0]) if ops else None
    if ops and ops[0].is_self():
        v = inst.owner
    if inst.lists and type(v) is not type(inst.lists[0]) and not (
            isinstance(v, (int, float)) and isinstance(inst.lists[0], (int, float))):
        return False                             # all elements have the first one's type (C)
    inst.lists.append(v)
    return False


def _list_count(inst, n, ops, chain):            # 0x100000C3 ListCount(out)
    _set(inst, ops, 0, len(inst.lists))
    return False


def _list_has(inst, n, ops):                     # 0x100000C4 IsInList(value)
    v = inst.get(ops[0]) if ops else None
    if ops and ops[0].is_self():
        v = inst.owner
    return any(R._same(x, v) for x in inst.lists)


def _list_item(inst, n, ops, chain):             # 0x100000C5 ListItem(out, index)
    i = _int(inst.number(_op(ops, 1)))
    _set(inst, ops, 0, inst.lists[i] if 0 <= i < len(inst.lists) else 0)
    return False


def _list_remove(inst, n, ops, chain):           # 0x100000CD RemoveFromList(value)[ordered]
    v = inst.get(ops[0]) if ops else None
    for i, x in enumerate(inst.lists):
        if R._same(x, v):
            if _val(n, 0):
                del inst.lists[i]
            else:
                inst.lists[i] = inst.lists[-1]
                inst.lists.pop()
            break
    return False


def _list_find(inst, n, ops, chain):             # 0x100000F9 FindInList(value, out index)
    v = inst.get(ops[0]) if ops else None
    idx = next((i for i, x in enumerate(inst.lists) if R._same(x, v)), -1)
    _set(inst, ops, 1, idx)
    return False


def _team_of(inst, e):
    if isinstance(e, int) and not isinstance(e, bool) and e < 0x10000:
        return e
    if isinstance(e, float):
        return int(e)
    return _call(inst, "team", _real(e), default=0)


def relation_matches(w, a, b, mask):
    """CheckRelation semantics (C 0x993860): (relation(teamA, teamB) & mask) != 0."""
    ta = w.team(_real(a)) if hasattr(w, "team") else 0
    tb = w.team(_real(b)) if hasattr(w, "team") else 0
    rel = relation(ta, tb)
    if rel == 1 and not getattr(w, "neutral_hittable", True) and not _hittable(w, a, b):
        return False
    return bool(rel & mask)


def _hittable(w, a, b):
    """A neutral entity the flow made a target of the champion's effects (the practice targets, World.hittable)."""
    fn = getattr(w, "hittable", None)
    return bool(fn and (fn(_real(a)) or fn(_real(b))))


def _get_team(inst, n, ops, chain):              # 0x1000007B GetTeam(entity, out) (C)
    _set(inst, ops, 1, _team_of(inst, _ent(inst, ops, 0)))
    return False


def _set_team(inst, n, ops, chain):              # 0x1000007E SetTeam(entity, team)
    ent = _real(_ent(inst, ops, 0))
    team = _team_of(inst, inst.get(ops[1]) if len(ops) > 1 else 0)
    _call(inst, "set_team", ent, team)
    return False


def _team_member(inst, n, ops, chain):           # 0x10000082 GetTeamMember(out, index, team)[mask] (C)
    mask = _val(n, 0, 7)
    idx = _int(inst.number(_op(ops, 1)))
    me = inst.source()
    my_team = _team_of(inst, me)
    want = inst.get(ops[2]) if len(ops) > 2 and not ops[2].is_unset() else None
    w = inst.world
    members = []
    kind = _call(inst, "kind_of", me)
    for e in _call(inst, "all_entities", default=[]) or []:
        if kind is not None and _call(inst, "kind_of", e) != kind:
            continue
        t = _team_of(inst, e)
        if want not in (None, 0, -1, 0xFFFFFFFF):
            if t != _team_of(inst, want):
                continue
        elif not (relation(my_team, t) & mask):
            continue
        members.append((t, e))
    members.sort(key=lambda x: x[0])              # teams in order, members in roster order
    _set(inst, ops, 0, members[idx][1] if 0 <= idx < len(members) else 0)
    return False


def _track_team(inst, n, ops, chain):            # 0x10000083 TrackTeam(team)[subscribe]
    on = bool(_val(n, 0))
    _combat(inst).of(inst.source()).flags[("track_team", inst.guid)] = on
    if on and _cfg(inst, "team_member_events", True) and hasattr(inst.world, "all_entities"):
        # 2026-10-25 (skill-mechanics-recipes.md 6, C params: 15 scripts wait for 0x1000007B {TeamMemberIID}): the team's
        # champions as "joined" once the script subscribes
        me = inst.source()
        team = getattr(me, "team", 0)
        for e in inst.world.all_entities():
            if e is not me and getattr(e, "kind", "") == "champion" and team and getattr(e, "team", 0) == team:
                inst.post(0x1000007B, 0.0, {"TeamMemberIID": e})
    return False


def _check_relation(inst, n, ops):               # 0x10000028 CheckRelation(a, b)[mask 2 enemy, 3 +neutral, 4 ally, 7 all]
    mask = _val(n, 0, 3)
    a = inst.get(ops[0]) if ops else None
    b = inst.get(ops[1]) if len(ops) > 1 else None
    if ops and ops[0].is_self():
        a = inst.owner
    if len(ops) > 1 and ops[1].is_self():
        b = inst.owner
    if a in (None, 0) or b in (None, 0):
        return False
    ta, tb = _team_of(inst, a), _team_of(inst, b)
    rel = relation(ta, tb)
    if rel == 1 and not getattr(inst.world, "neutral_hittable", True) and not _hittable(inst.world, a, b):
        return False
    return bool(rel & mask)


def _exists(inst, n, ops):                       # 0x100000EF EntityExists(e) (C)
    e = inst.get(ops[0]) if ops else None
    if ops and ops[0].is_self():
        e = inst.owner
    if e in (None, 0) or isinstance(e, tuple):
        return False
    if isinstance(e, Missile):
        return e.alive
    return bool(_call(inst, "exists", e, default=True))


def _is_class(inst, n, ops):                     # 0x10000072 IsClass(e)[class DID] (C)
    e = _real(_ent(inst, ops, 0))
    if isinstance(_ent(inst, ops, 0), Missile):
        return _ent(inst, ops, 0).cls == _val(n, 0)
    return e is not None and _call(inst, "class_of", e) == _val(n, 0)


def _is_targetable(inst, n, ops):                # 0x1000001C IsTargetable(e): attribute 0x10000029 (C)
    e = _real(_ent(inst, ops, 0))
    return e is not None and bool(_combat(inst).flag(e, ATTR_TARGETABLE))


def _controller_mode(inst, n, ops):              # 0x100000DC IsInControllerMode(e)[66/71/74] (C; 74 = attached)
    e = _real(_ent(inst, ops, 0))
    if _val(n, 0) == 74:
        return any(isinstance(k, tuple) and k[0] == "attached" for k in _combat(inst).of(e).flags)
    return False


def _can_see(inst, n, ops):                      # 0x1000003C CanSee(observer, target)[flag] (P: no vision model)
    a, b = inst.get(ops[0]) if ops else None, inst.get(ops[1]) if len(ops) > 1 else None
    if ops and (ops[0].is_self() or ops[0].is_unset() and _cfg(inst, "can_see_default_self", True)):
        # 2026-11-02 (tester report 2026-11-02 01:48: Blue Beetle's E fired none of its shots; 0x34000455 asks
        # CanSee(-, $LoopingIID)): an unset observer is SELF, as the other entity operands ([ics] can_see_default_self)
        a = inst.owner
    return a not in (None, 0) and b not in (None, 0) and inst.world.alive(_real(b))


def _best_target(inst, n, ops, chain=None):      # 0x10000020 GetBestPerceivedTarget(unit, out, -)[2, kinds, ...] (P)
    unit = _real(_ent(inst, ops, 0))
    kinds = _val(n, 1)
    w = inst.world
    rng = _call(inst, "vision_range", unit, default=None) or 10.0
    best, bd = None, None
    for e in w.find_targets(w.position(unit), rng, kinds):
        if e is unit or (kinds and not w.kind_matches(e, kinds)) or not relation_matches(w, unit, e, 2):
            continue
        d = _dist2d(w.position(unit), w.position(e))
        if bd is None or d < bd:
            best, bd = e, d
    _set(inst, ops, 1, best if best is not None else 0)
    return best is not None


def _is_local_player(inst, n, ops):              # 0x1000003D IsLocalPlayer(e)[via owner] (C client; P server)
    e = _real(_ent(inst, ops, 0))
    p = inst.world.player() if hasattr(inst.world, "player") else None
    return e is not None and (e is p or e == p or _combat(inst).of(e).creator in (p,))


def _missile_lost(inst, n, ops):                 # 0x100000AE (P: the missile has no target any more)
    m = inst.owner
    return isinstance(m, Missile) and (m.target in (None, 0) or not isinstance(m.target, tuple)
                                       and not inst.world.alive(m.target))


def _ai_move(inst, n, ops, chain):               # 0x1000004F AIMoveTo(-, range, target, mover, out handle)[flag] (P)
    mover = _real(_ent(inst, ops, 3))
    target = inst.get(ops[2]) if len(ops) > 2 and not ops[2].is_unset() else None
    h = Handle("ai_move", mover)
    if target not in (None, 0):
        _call(inst, "ai_move", mover, _real(target) if not isinstance(target, tuple) else target,
              inst.number(_op(ops, 1)))
    _set(inst, ops, 4, h)
    return False


def _ai_target(inst, n, ops, chain):             # 0x1000000D SetAITarget(target, unit)[mode] (P)
    target = _real(inst.get(ops[0])) if ops and not ops[0].is_unset() else None
    unit = _real(_ent(inst, ops, 1))
    _call(inst, "ai_target", unit, target, _val(n, 0))
    return False


def _ai_enabled(inst, n, ops, chain):            # 0x10000139 SetAIEnabled(unit, handle)[enable] (P)
    unit = _real(_ent(inst, ops, 0))
    st = _combat(inst).of(unit)
    if _val(n, 0):
        h = inst.get(ops[1]) if len(ops) > 1 else None
        st.ai_off.discard(h)
        if not isinstance(h, Handle):
            st.ai_off.clear()
        _set(inst, ops, 1, 0)
    else:
        h = Handle("ai", unit)
        st.ai_off.add(h)
        _set(inst, ops, 1, h)
    _call(inst, "on_cc", unit)
    return False


def _vision_range(inst, n, ops, chain):          # 0x10000004 GetVisionRange(out, entity)[+bonus] (C)
    e = _real(_ent(inst, ops, 1))
    r = _call(inst, "vision_range", e, default=None)
    if r is None:
        r = 10.0
    if _val(n, 0):
        r += num(_combat(inst).attribute(e, 0x10000642) or 0.0)
    _set(inst, ops, 0, float(r))
    return False


def _reaction_handler(inst, n, ops, chain):      # 0x1000014D AddReactionHandler(entity, out handle)[0x3F] (P)
    _set(inst, ops, 1, Handle("reaction", _real(_ent(inst, ops, 0))))
    _log(inst, f"reaction handler {_val(n, 0):#x} (0x3F records are not run yet)")
    return False


def _clear_handle(i):
    def h(inst, n, ops, chain):                  # 0x1000014C RemoveReactionHandler, 0x100000B2, 0x10000119 ...
        _set(inst, ops, i, 0)
        return False
    return h


def _attach_handler(inst, n, ops, chain):        # 0x10000168 AttachHandlerScript(out handle, params)[start, 0x3F, event, n]
    _set(inst, ops, 0, Handle("handler", inst.owner) if _val(n, 0) else 0)
    return False


def _graph_variable(inst, n, ops, chain):        # 0x1000002F SetGraphVariable(value, entity)[var, notify] (C client half)
    ent = _real(_ent(inst, ops, 1))
    _msg(inst, "graph_variable", ent, var=_val(n, 0), value=inst.number(_op(ops, 0)))
    return False


def _set_property_100004ff(inst, n, ops, chain):  # 0x1000005C SetProperty_100004FF(entity)[value] (C)
    _msg(inst, "set_property", _real(_ent(inst, ops, 0)), prop=0x100004FF, kind=0x08, value=_val(n, 0))
    return False


def _root_counter(inst, n, ops, chain):          # 0x100001B8 PushRootCounter(entity)[on] -> 0x2198 (C)
    _msg(inst, "root_counter", _real(_ent(inst, ops, 0)), on=_val(n, 0))
    return False


def _position_query(inst, n, ops, chain):        # 0x10000191 PositionQuery(entity, position, out) (C call, P meaning)
    p = _position(inst, inst.get(ops[1])) if len(ops) > 1 else None
    _set(inst, ops, 2, bool(p is not None and _call(inst, "walkable", p, default=True)))
    return False


def _lane(inst, n, ops, chain):                  # 0x100001B3 SetLane(entity, lane)[flag, 0] (P)
    _combat(inst).of(_real(_ent(inst, ops, 0))).flags["lane"] = inst.get(ops[1]) if len(ops) > 1 else 0
    return False


def _get_lane(inst, n, ops, chain):              # 0x100001B6 GetLane(entity, out) (P)
    _set(inst, ops, 1, _combat(inst).of(_real(_ent(inst, ops, 0))).flags.get("lane", 0))
    return False


def _match_time(inst, n, ops, chain):            # 0x10000152 GetMatchTime(out) (P)
    _set(inst, ops, 0, float(_call(inst, "match_time", default=inst.world.time)))
    return False


def _latency(inst, n, ops, chain):               # 0x100001A5 GetLatencyWindow(entity, out f32) (P: 0)
    _set(inst, ops, 1, 0.0)
    return False


def _start_script_on(inst, n, ops, chain):       # 0x10000030 StartScriptOn(entity)[script 0x34] (P)
    did = _val(n, 0)
    ent = _real(_ent(inst, ops, 0))
    try:
        R.start_script(R.V.load(did), ent, inst.world)
    except OSError:
        _log(inst, f"StartScriptOn {did:#x}: not decoded")
    return False


def _source_position(inst, n, ops, chain):       # 0x10000147 GetSourcePosition(out, -) (P: the creator's position)
    src = _combat(inst).of(inst.source()).creator or inst.source()
    _set(inst, ops, 0, R.Frame(inst.world.position(src), 0.0))
    return False


def _current_range(inst, n, ops, chain):         # 0x1000016E GetCurrentRange(out) (P: the skill's range stat 18)
    _set(inst, ops, 0, inst.world.skill_stat(inst.source(), 18, inst.world.skill_rank(inst.source())))
    return False


def _vehicle_driver(inst, n, ops, chain):        # 0x100000E8 GetVehicleDriver(out, entity) (P: who is attached to it)
    e = _real(_ent(inst, ops, 1))
    driver = 0
    for k, st in inst.world.combat.states.items():
        for f, v in st.flags.items():
            if isinstance(f, tuple) and f[0] == "attached" and v is e:
                driver = k
    _set(inst, ops, 0, driver if not isinstance(driver, int) else 0)
    return False


def _set_tracked(inst, n, ops, chain):           # 0x10000117 SetTracked(object, out made)[flag] (P)
    _set(inst, ops, 1, bool(_val(n, 0)))
    return False


def _hidden(inst, n, ops, chain):                # 0x100001A9 SetHidden(entity)[on] (P)
    ent = _real(_ent(inst, ops, 0))
    st = _combat(inst).of(ent)
    st.hidden = max(0, st.hidden + (1 if _val(n, 0) else -1))
    _msg(inst, "hidden", ent, on=st.hidden > 0)
    return False


def _champion_trigger(inst, n, ops):             # 0x1000018A IsChampion(class) trigger
    return _call(inst, "class_of", inst.source()) == _val(n, 0)


def _event_value_trigger(inst, n, ops):          # 0x10000049 / 0x1000017D / 0x1000003B (event, id) triggers
    return inst.current_event is not None and bool(n.values) and inst.current_event == n.values[0]


def _attribute_trigger(inst, n, ops):            # 0x100000B1 OnAttributeChanged[0x100000A2, attribute] (C)
    if not n.values or inst.current_event != n.values[0]:
        return False
    want = n.values[-1] if len(n.values) > 1 else 0
    got = inst.params.get(R.PARAM_ATTRIBUTE)
    if not want:
        return True
    from .combat import ALIASES
    return got == want or (want in ALIASES and ALIASES[want][1] == got) or (got in ALIASES and ALIASES[got][1] == want)


def _false(inst, n, ops):
    return False


def _true(inst, n, ops):
    return True


def _release_facing(inst, n, ops, chain):       # 0x10000057 ReleaseFacing(handle) (full-combat-skills.md 1.8, C)
    """2026-11-02: frees the facing lock FaceTarget took with that handle (CastWorld.release_facing; was a logged no-op)."""
    h = inst.get(ops[0]) if ops else None
    _call(inst, "release_facing", inst.source(), h)
    return False


def _logged(name):
    """A node whose meaning is unknown (or that has no server effect): a no-op that logs once per script."""
    def h(inst, n, ops, chain):
        seen = getattr(inst, "logged_nodes", None)
        if seen is None:
            seen = inst.logged_nodes = set()
        if name not in seen:
            seen.add(name)
            _log(inst, f"{name}: no server effect (logged no-op)")
        return False
    return h


def _raise_event_node(inst, n, ops, chain):      # 0x1000006B: RaiseEvent(entity, iid, position, value) [event]
    ev = n.values[0] if n.values and isinstance(n.values[0], int) else 0
    ent = inst.ent(ops[0]) if ops else inst.owner
    vals = list(n.values)
    # 2026-10-23 18:00 (champion-kits-status.md 1: Cyborg's basic attack RaiseEvent(SELF) [0x1000001D 0x34000237]
    # activated all his skills): the second value is the script the event is for; only its instances get it
    did = vals[1] if len(vals) > 1 and isinstance(vals[1], int) and vals[1] >> 24 == 0x34 else 0
    follow = (_cfg(inst, "raise_event_follow", {}) or {}).get(f"0x{ev:08X}") if ev else None
    obj = _real(ent)
    if ev == 0x10000037 and getattr(obj, "liftable", None) and not inst.removed and hasattr(inst.world, "w"):
        # 2026-10-25 (crime-alley-props.md A.3, C: no script starts the lift's sub-skill; the original server's code
        # did): a map liftable's lift / carry / throw (ics/match/liftables.py)
        inst.world.w.emit("lift", ent=inst.source(), obj=obj, inst=inst)
    if follow and getattr(obj, "liftable", None) and _cfg(inst, "liftable_input_back", True):
        # 2026-10-29 tester report 21:10 (liftable-aura-lift-throw-break.md 2, C scripts): the sub-skill raised
        # 0x100000BB itself, the vehicle's 0x34000161 at S7 (the toss), the rock's 0x34000177 at S3 (the grab):
        # ics/match/liftables.py posts it then ([ics] liftable_input_back; false = the fixed delay below)
        follow = None
    if follow and not inst.removed:
        # 2026-10-25 (stolen-powers-audit.md 3, C: Super Strength 0x34000164 raises 0x10000037 (pickup) on its target and
        # waits for 0x100000BB, which the lift clip's end raised in the original): the raising instance gets the follow
        # event after the clip's time ([ics] raise_event_follow: event -> [follow event, s])
        inst.post(int(str(follow[0]), 0), float(follow[1]))
    if did and not _cfg(inst, "raise_event_script_target", True):
        did = 0
    if ev and ent is not None and not inst.removed and did:
        params = R._params(inst, ops, R.RAISE_PARAMS)
        for other in list(R.scripts_on(inst.world, ent)):
            if getattr(getattr(other, "script", None), "did", None) == did:
                other.event(ev, params)
        if ev == R.EVENT_IMPACT and inst.status is not None:
            R.remove_status(inst.world, inst.owner, inst.status, inst)
    elif ev and ent is not None and not inst.removed and ent is inst.owner and _cfg(inst, "raise_event_self_deferred", True):
        # 2026-10-25 (map-objectives-recipes.md 6 gap 1, C: the GH cannon controller's RaiseEvent(SELF, 0x10000107) was
        # delivered mid-chain and its unset timer read expired, skipping the 65 s neutral phase): the raising instance
        # gets its own event once the current chain is done; the owner's other scripts at once
        params = R._params(inst, ops, R.RAISE_PARAMS)
        for other in list(R.scripts_on(inst.world, ent)):
            if other is inst:
                inst.post(ev, 0.0, params)
            else:
                other.event(ev, params)
        if ev == R.EVENT_IMPACT and inst.status is not None:
            R.remove_status(inst.world, inst.owner, inst.status, inst)
    elif ev and ent is not None and not inst.removed:
        R.raise_event(inst.world, ent, ev, R._params(inst, ops, R.RAISE_PARAMS))
        if ev == R.EVENT_IMPACT and inst.status is not None:
            # assumption (2026-10-21): a shot tracker (e.g. 0x34000470, 99 stacks) ends when its shot arrives; its
            # exit chain then plays the destruction impulse at the target. Only 0x340005F7 removes itself
            # explicitly (node 0x10000018), the others raise the impact on every tick otherwise.
            R.remove_status(inst.world, inst.owner, inst.status, inst)
    return False


def _find_targets(inst, n, ops, chain):          # 0x10000047 FindTargets(range, length, dimA, dimB, -, out count, center)
    add_radius, shape, kinds, mask, max_count = _val(n, 0), _val(n, 1, 1), _val(n, 2), _val(n, 3), _val(n, 4, 12)
    sort, include_self = _val(n, 5), _val(n, 6)
    w = inst.world
    rng = inst.number(_op(ops, 0))
    length, dim_a, dim_b = inst.number(_op(ops, 1)), inst.number(_op(ops, 2)), inst.number(_op(ops, 3))
    center = inst.get(ops[6]) if len(ops) > 6 and not ops[6].is_unset() else None
    me = inst.source()
    # the relation's side: a status' applier (2026-10-28 15:00, tester report 2026-10-28 15:00: Meltdown's pulses hit AGL's
    # side; meltdown-moving-target.md 3.3 / 6.2, C client 0x9CCE60: SELF from the owner block, the team from the source
    # descriptor 0x991F60). SELF (the exclusion, the radius added, the box heading) stays the owner.
    rel = R.acting_entity(inst)
    if center in (None, 0):
        center = inst.owner.pos if isinstance(inst.owner, Missile) else w.position(inst.owner)
    else:
        center = _position(inst, center)
    if add_radius and not isinstance(inst.owner, Missile):
        rng += _call(inst, "radius", me, default=0.5)
    reach = max(rng, length, dim_a, dim_b) + 1.0
    h = w.heading(me) if hasattr(w, "heading") else 0.0
    found = []
    for e in w.find_targets(center, reach, kinds):
        if (e is me or e == me) and not include_self:
            continue
        if kinds and not w.kind_matches(e, kinds):
            continue
        if mask and not relation_matches(w, rel, e, mask):
            continue
        p = w.position(e)
        dx, dy = p[0] - center[0], p[1] - center[1]
        if shape == 2 and length:
            fwd = dx * math.cos(h) + dy * math.sin(h)
            side = -dx * math.sin(h) + dy * math.cos(h)
            if not (-0.5 <= fwd <= length + 0.5 and abs(side) <= max(dim_a, dim_b, 0.5) / 2 + 0.5):
                continue
        elif math.hypot(dx, dy) > rng + (_call(inst, "radius", e, default=0.0) if shape in (1, 7) else 0.0):
            continue
        found.append(e)
    if sort or max_count:
        found.sort(key=lambda e: _dist2d(w.position(e), center))
    if max_count:
        found = found[:max_count]
    inst.detected = found
    _set(inst, ops, 5, len(found))
    return False


# ---- registration ----------------------------------------------------------------------------------------

ACTIONS = {
    # skill state
    0x1000000E: _begin_skill, 0x1000000A: _end_skill, 0x100000D8: _show_skill_error,
    0x100000FB: _set_disable_condition, 0x100000FC: _set_usable_override, 0x10000097: _ui_overlay,
    0x10000153: _stat_override, 0x1000008E: _clear_stat_override, 0x10000089: _set_slot_skill,
    0x1000017F: _combo_state, 0x100000A3: _reduce_cooldown, 0x100001AF: _reset_cooldown,
    0x100000DB: _queue_order, 0x1000000B: _add_skill_target, 0x10000005: _attached_skill,
    0x10000105: _flag_node("primed"), 0x10000136: _activate_slot, 0x10000148: _get_targeting,
    0x100000F5: _slot_of_script, 0x10000169: _set_charges, 0x1000016B: _get_charges, 0x10000065: _grant_currency,
    0x10000075: _logged("SetTargetingMode? 0x10000075"), 0x10000057: _release_facing,
    # attributes, vitals, damage
    0x10000008: _add_modifier, 0x10000033: _remove_modifier, 0x100000CE: _get_vital, 0x10000093: _add_temp_vital,
    0x10000092: _remove_temp_vital, 0x10000040: _start_vot, 0x10000009: _stop_vot, 0x10000149: _add_redirect,
    0x1000014A: _remove_redirect, 0x1000001D: _apply_damage, 0x1000010B: _roll_critical, 0x1000004B: _get_level,
    0x10000162: _defeat_type, 0x100000FA: _skill_stat_override, 0x10000118: _floaty_number, 0x100001AD: _display_floaty,
    # statuses, icons, scriptlets
    0x10000027: _apply_skill, 0x100000D9: _add_stacks, 0x10000018: _remove_status, 0x100000CA: _set_status_duration,
    0x100000FE: _stack_count, 0x10000177: _load_status_stats, 0x1000005B: _disable_actions, 0x10000081: _stop_action,
    0x100000AD: _lock_input, 0x100000C8: _set_untargetable, 0x100000A7: _add_icon, 0x100000A8: _update_icon,
    0x100000A6: _remove_icon, 0x1000016A: _icon_stats, 0x10000116: _refresh_icon, 0x10000102: _stop_scriptlet,
    0x10000012: _stop_scriptlet_key, 0x1000013A: _run_fx_scriptlet, 0x1000006B: _raise_event_node,
    # world effects
    0x1000005E: _missile, 0x10000154: _lobbed, 0x1000005F: _tethered, 0x10000134: _missile_velocity,
    0x10000059: lambda i, n, o, c: _hotspot(i, n, o, c, False), 0x10000122: lambda i, n, o, c: _hotspot(i, n, o, c, True),
    0x1000002D: _destroy_hotspot, 0x10000137: _resize_hotspot, 0x100000A0: _spawn, 0x100001B0: _spawn_from_shooter,
    0x10000155: _get_properties, 0x100000A5: _get_creator, 0x1000008F: _attach, 0x10000042: _pick_up,
    0x10000120: _get_radius, 0x100000EA: _dash_to_position, 0x1000013E: _dash_to_entity, 0x100000C6: _knockback,
    0x1000001B: _cancel_movement, 0x100000F1: _movement_mode, 0x100000B0: _snap_to_ground,
    0x10000025: _find_scatter, 0x10000109: _find_valid, 0x10000146: _find_valid,
    0x1000007D: _teleport_effects(True), 0x1000007F: _teleport_effects(False), 0x10000141: _camera_heading,
    0x10000085: _destruction, 0x10000047: _find_targets,
    0x10000078: _logged("CenterCameraOn? 0x10000078 (client camera)"),
    0x1000014B: _logged("SetCameraMode? 0x1000014B"), 0x10000150: _logged("ShowMinimapTargetingRing2 (client UI)"),
    0x10000022: _logged("ShowMinimapTargetingRing (client UI)"), 0x10000056: _logged("HideMinimapTargetingRing"),
    0x1000006F: _collision(False), 0x10000070: _collision(True),
    0x10000114: _logged("SetCollisionLayer 0x10000114"), 0x10000151: _logged("Unk_0151 (missile bookkeeping)"),
    0x100000DD: _logged("DestructionRaycast 0x100000DD (event 0x8 not built)"),
    0x1000017E: _logged("SetDestructibleState? 0x1000017E"),
    # lists, teams, AI
    0x100000C1: _list_clear, 0x100000C2: _list_add, 0x100000C3: _list_count, 0x100000C5: _list_item,
    0x100000CD: _list_remove, 0x100000F9: _list_find, 0x1000007B: _get_team, 0x1000007E: _set_team,
    0x10000082: _team_member, 0x10000083: _track_team, 0x1000004F: _ai_move, 0x1000000D: _ai_target,
    0x10000139: _ai_enabled, 0x10000004: _vision_range, 0x1000014D: _reaction_handler,
    0x1000014C: _clear_handle(1), 0x10000168: _attach_handler, 0x1000002F: _graph_variable,
    0x10000020: lambda i, n, o, c: (_best_target(i, n, o), False)[1],
    # single-use nodes (5.9) and data-only nodes
    0x1000005C: _set_property_100004ff, 0x100001B8: _root_counter, 0x10000191: _position_query,
    0x100001B3: _lane, 0x100001B6: _get_lane, 0x10000152: _match_time, 0x100001A5: _latency,
    0x10000030: _start_script_on, 0x10000147: _source_position, 0x1000016E: _current_range,
    0x100000E8: _vehicle_driver, 0x10000117: _set_tracked, 0x100001A9: _hidden,
    0x100001A7: _flag_node("lifesteal_tracking"),
    0x100000B2: _clear_handle(0), 0x10000119: _clear_handle(0),
}
for _id, _name in {
        0x1000011E: "reveal / hide to a team (P)", 0x100000E5: "trigger re-armed (P)", 0x100000C7: "UINotify (client HUD)",
        0x10000108: "RecordPlayerAction (P)", 0x10000174: "Unk_0174", 0x100000A1: "link entities (P)",
        0x10000172: "Unk_0172", 0x100001B9: "BeginFakeDeath (P)", 0x100000DA: "Unk_00DA", 0x10000135: "missile returned (P)",
        0x1000010E: "end untargetable (P)", 0x1000009E: "vitals link (C call)", 0x10000087: "SetUsageObject (P)",
        0x10000090: "SetObjectState (P)", 0x100000E4: "SetPhysicsEnabled (P)", 0x1000010D: "SetWorldState (P)",
        0x10000063: "SetEnumProperty (P)", 0x10000186: "level-up bookkeeping (P)", 0x10000189: "level-up bookkeeping (P)",
        0x10000016: "SpawnGeneratorUnit (match rules)", 0x10000039: "SendMissionEvent (match rules)",
        0x1000003A: "UI_ShowMovie (client UI flow)", 0x1000004D: "UI_SendStateMachineEvent (client UI flow)",
        0x100000CB: "UI_ShowMovie2 (client UI flow)", 0x100000CC: "UI_DestroyGameFront (client UI flow)",
        0x10000043: "UI_Unk_0043 (client UI flow)", 0x10000179: "UI_SetHUDVisibility (client UI flow)",
        0x1000018F: "UI_ExitWorldLoadWrapper (client UI flow)", 0x10000060: "SetTutorialMarker (tutorial)",
        0x10000086: "Unk_0086", 0x100000B8: "SetImpactState (P)", 0x100000BB: "PlaySound (client audio)",
        0x100000BD: "Unk_00BD", 0x100000EC: "SetCurrencyOption (P)", 0x1000010A: "SetGeneratorEntry (match rules)",
        0x10000111: "ShowTutorialHint (the director sends hints)", 0x1000011A: "ShowAnnouncement (match rules)",
        0x10000121: "UpdateObjective (the director sends objectives)", 0x10000138: "Unk_0138",
        0x1000015D: "Unk_015D", 0x10000167: "NotifyHUDElement (the director drives the HUD)",
        0x10000181: "TutorialSetup_0181", 0x10000182: "TutorialSetup_0182", 0x10000183: "ActivateArtifacts (shop)",
        0x1000019B: "BreakDestructible (P)", 0x1000019D: "Unk_019D", 0x100001A3: "ShowTrainingFloatyText (tutorial)",
        0x100000C0: "Unk_00C0"}.items():
    ACTIONS.setdefault(_id, _logged(f"{_name} {_id:#x}"))

PREDICATE_NODES = {
    0x10000015: _holds_action_lock, 0x100000D2: _is_slot_skill, 0x100000DF: _skill_off_cooldown,
    0x10000052: _in_range_and_angle, 0x1000001A: _vital_threshold, 0x100000A4: _has_status,
    0x10000143: _is_stealthed, 0x10000144: _is_revealed, 0x1000002C: _combat_event,
    0x100000E1: _is_moving, 0x1000016F: _is_in_front, 0x100000C4: _list_has, 0x10000028: _check_relation,
    0x100000EF: _exists, 0x10000072: _is_class, 0x1000001C: _is_targetable, 0x100000DC: _controller_mode,
    0x1000003C: _can_see, 0x10000173: _true, 0x1000003D: _is_local_player, 0x100000AE: _missile_lost,
    0x100000F3: _false, 0x100000B1: _attribute_trigger, 0x10000049: _event_value_trigger,
    0x1000017D: _event_value_trigger, 0x1000003B: _event_value_trigger, 0x1000018A: _champion_trigger,
    0x10000048: _false, 0x10000115: _false, 0x1000015E: _false, 0x100001B7: _false, 0x1000013C: _false,
    0x100001A2: _false, 0x100001A4: _false, 0x100001B1: _false, 0x1000004A: _event_value_trigger,
    0x10000053: _event_value_trigger, 0x10000067: _event_value_trigger, 0x100000E6: _false, 0x1000006E: _false,
}

R.HANDLERS.update(ACTIONS)
R.PREDICATES.update(PREDICATE_NODES)
R.COND_ACTIONS[0x10000020] = lambda inst, n, ops: _best_target(inst, n, ops)
