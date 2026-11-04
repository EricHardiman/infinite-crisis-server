"""Scriptlet orders as the client applies them: one 0x8D per object and moment, the held runs riding along, runs
stopped by event 0x11F.

What the client does (C, 2026-11-03, disassembly of InfiniteCrisis.exe):

- The 0x8D list handler 0x627E20 first calls 0x57CB60 (0x627E4D) with a filter object (vtable 0x15C9750, method
  0x6272D0 = the run's context byte +0x60, which 0x6279D0 sets on every run a network order starts). 0x57CB60 walks
  the object's runs (comp+0x18, count comp+0x0C) and stops each one the filter picks (0x57C4B0 -> 0x57B920 ->
  0x52D790). Only then are the order's entries started or signalled (0x6279D0). So every 0x8D to an object ends every
  run an earlier server order started on it: a loop the server keeps on (Blue Beetle's passive 0x10000BC3) dies at
  the next order to that object, even a "stop" order of another run.
- An 0x8D entry whose run number is no longer alive starts a NEW run (0x6279D0 step 4). ics sent its stops as 0x8D
  entries with signal bit 1: after the stop-all above the run was dead, so the "stop" started the effect again (Blue
  Beetle's yellow blaster stayed after his passive ended, until the next order).
- Event 0x11F (exec 0x675280) stops one run by key and number with 0x57C4B0 and touches nothing else; the client's
  own StopScriptlet (0x588A80) calls 0x57C4B0 with mode 1, the 0x11F u8.

What this module does (P: the original server's policy is not known; it must have kept such loops alive, since the
tester remembers the passive's particles for its whole buff):

- Consecutive 0x8D messages to one object (until another message goes out or the moment ends: the same scheduler
  step) go out as ONE order with all their entries (the message is a list), so a moment's effects no longer end each
  other. The order of the other messages on the wire is kept; a lone order goes out exactly as it was built.
- Runs started by a script's StartScriptlet (a handle: the script keeps them on until its StopScriptlet) are held:
  they ride along, with their own run number and variables, in every later 0x8D order to that object until they are
  stopped. The client restarts them there (stop-all, then a new run): a short blink, as anim-09's effect set (the
  tester accepted it, 2026-10-27 17:57). The client's additive path 0x2073 (0xA22DA0: no stop-all, live runs
  skipped) would avoid the blink, but it applies directly only when the object's +0x110 is the "none" DID
  (0xA883F0); to confirm with diag before using it.
- A script's StopScriptlet is event 0x11F (key, run, mode 1) instead of the 0x8D signal (the server's own stops,
  stealth shimmer, camps, keep their 0x8D signal).

[ics] scriptlet_orders (true; false = every scriptlet in an order of its own and 0x8D signal stops, as before),
scriptlet_orders_skip_encounters (encounters left as before: Tutorial 1), scriptlet_orders_scope ("champions": the
local and bot champions; "all": every object, a project-wide change for its own PR).
"""
import re
import struct

from . import messages as M
from .wire import pack_compact, read_compact

EVT_SCRIPTLETS = 0x8D
EVT_GONE = 0x3
EVT_ADD = 0x2073             # start scriptlets without the stop-all (0xA883F0 -> 0xA22DA0)
# vitals, attribute modifiers, status icons, cooldowns: no scriptlet or graph state, they do not split a moment's orders
NO_FLUSH = {0x42, 0x20F0, 0x20E8, 0x20C8, 0x20D0, 0x2127, 0x20E9, 0x20F8}
# the label CastWorld.run_scriptlet gives a script node's scriptlet (RunScriptlet / StartScriptlet / RunFx /
# RaiseGraphEvent): the runs the original's client copy of the skill script would start itself
_SCRIPT_LABEL = re.compile(r": scriptlet 0x[0-9a-f]+ \(0x8d\)( \(held, once\))?$")


def _frame(data):
    """(dest, flags, event, body offset) of a game message frame, or None."""
    if len(data) < 15 or data[4] != 0x02:
        return None
    dest = struct.unpack_from("<Q", data, 5)[0]
    flags = data[13]
    try:
        event, pos = read_compact(data, 14)
    except IndexError:
        return None
    return dest, flags, event, pos


def _first_entry_run(entries):
    """(key, run number) of the first entry of an 0x8D entry list."""
    key = entries[0] << 24
    low, pos = read_compact(entries, 1)
    run, _pos = read_compact(entries, pos)
    return key | low, run


class Orders:
    """Wraps World.send: buffers a moment's 0x8D messages per object and adds the object's held runs to them."""

    def __init__(self, world, send):
        self.w, self.raw_send = world, send
        self.pending = {}          # dest -> [label, flags, [(run or None, entry count, entry bytes)]]
        self.held = {}             # dest -> {run: (key, entry bytes or None)}
        self.flush_due = False

    # the script side ------------------------------------------------------------------------------------------
    def hold(self, ent, key, run):
        """A StartScriptlet run (a script handle keeps it on): it rides along in the object's later orders."""
        if run is None or not hasattr(ent, "eid"):
            return
        held = self.held.setdefault(ent.eid, {})
        if held.get(run, (0, None))[1] is None:
            sent = next((u[2] for u in (self.pending.get(ent.eid) or [None, None, ()])[2] if u[0] == run), None)
            held[run] = (key, sent)

    def stop(self, ent, key, run):
        """Stop one run (run None = every run of the key) with 0x11F, mode 1 as the client's own StopScriptlet."""
        eid = getattr(ent, "eid", None)
        if eid is None:
            return False
        name = self.w.data.scriptlet_names().get(key, f"{key:#x}")
        self.send(f"{getattr(ent, 'name', eid)}: stop {name} (0x11f, run {'all' if run is None else run})",
                  M.stop_scriptlet(eid, key, 0xFFFFFFFF if run is None else run, 1))
        return True

    # the wire side --------------------------------------------------------------------------------------------
    def send(self, label, data):
        f = _frame(data) if isinstance(data, (bytes, bytearray)) else None
        if f is None:
            return self.raw_send(label, data)
        dest, flags, event, pos = f
        if event == EVT_SCRIPTLETS and label and "(0x8d signal" in label:
            pass                       # a signal order (the server's own stops) goes as it is, after the waiting ones
        elif event == EVT_SCRIPTLETS and len(data) > pos + 1 and data[pos] == 0 and self._in_scope(dest):
            count, epos = read_compact(data, pos + 1)
            entries = bytes(data[epos:])
            run = None
            if count == 1:
                key, run = _first_entry_run(entries)
                held = self.held.get(dest)
                if held is not None and run in held:
                    held[run] = (key, entries)
            p = self.pending.setdefault(dest, [[], flags, []])
            if label:
                p[0].append(label)
            p[2].append((run, count, entries, bool(label and _SCRIPT_LABEL.search(label)), label))
            if not self.flush_due:
                self.flush_due = True
                self.w.schedule(0.0, self.flush)
            return None
        if self.pending and not (event in NO_FLUSH and self.w.ic.get("scriptlet_orders_quiet_messages", True)):
            # any other message: the waiting orders go first, the order on the wire is kept. 2026-11-04 (tester report
            # 01:59: Superman's beam middle sometimes missing; the run 01:54:58.731 / .742: Vfx_Sup_Heat_Vision_Active
            # and the next step's orders were split by vitals / modifier / status icon messages, and the second 0x8D
            # ended the beam): messages that carry no scriptlet or graph state do not split a champion's moment
            self.flush()
        if event == 0x11F and len(data) >= pos + 10:
            key, run = struct.unpack_from("<II", data, pos + 1)
            held = self.held.get(dest) or {}
            for r in [r for r, (k, _e) in held.items() if k == key and (run == 0xFFFFFFFF or r == run)]:
                held.pop(r, None)
        elif event == EVT_GONE:
            self.held.pop(dest, None)
        return self.raw_send(label, data)

    def _in_scope(self, dest):
        """[ics] scriptlet_orders_scope: "champions" (the local and bot champions) or "all" (every object)."""
        if str(self.w.ic.get("scriptlet_orders_scope", "champions")) == "all":
            return True
        ent = self.w.entities.get(dest) if dest != getattr(self.w.champion, "eid", None) else self.w.champion
        return getattr(ent, "kind", None) == "champion"

    def flush(self):
        self.flush_due = False
        for dest in list(self.pending):
            self._flush_one(dest)

    def _flush_one(self, dest):
        _labels, flags, units = self.pending.pop(dest)
        event = self.event()
        if event == EVT_SCRIPTLETS:
            self._order(dest, flags, EVT_SCRIPTLETS, units, ride=True)
            return
        # 0x2073: the scripts' own runs go additively (as the original's client copies started them, nothing ends them
        # early); the server's own orders (falls, get-ups, carries) keep 0x8D and its stop-all, with the held runs
        # riding along after it
        native = [u for u in units if not u[3]]
        script = [u for u in units if u[3]]
        if native:
            self._order(dest, flags, EVT_SCRIPTLETS, native, ride=True)
        if script:
            self._order(dest, flags, EVT_ADD, script, ride=False)

    def _order(self, dest, flags, event, units, ride):
        runs = {u[0] for u in units if u[0] is not None}
        labels = [u[4] for u in units if u[4]]
        riding = [] if not ride else [
            (run, 1, entries, True, None) for run, (key, entries) in (self.held.get(dest) or {}).items()
            if entries is not None and run not in runs]
        units = list(units) + riding           # the new entries first, then the held runs
        count = sum(u[1] for u in units)
        body = b"\x00" + pack_compact(count) + b"".join(u[2] for u in units)
        if event != EVT_SCRIPTLETS:
            labels = [lbl.replace("(0x8d)", f"({event:#x})") for lbl in labels]
        if len(units) == 1 and len(labels) <= 1:
            # a lone order goes out as it was built
            return self.raw_send(labels[0] if labels else None, M.build_message(dest, event, body, flags))
        label = " + ".join(labels) if labels else None
        if label and riding:
            label += f" (+{len(riding)} held run{'s' if len(riding) > 1 else ''})"
        self.raw_send(label, M.build_message(dest, event, body, flags))

    def event(self):
        """[ics] scriptlet_orders_event: 0x2073 (default since 2026-11-04: the client's additive start 0xA22DA0, no
        stop-all, live run numbers skipped; diag --orders showed the champion's +0x110 = the "none" DID, the direct
        path) for the scripts' own runs, or 0x8D for every order (anim-23)."""
        ev = self.w.ic.get("scriptlet_orders_event", EVT_SCRIPTLETS)
        ev = int(str(ev), 0) if isinstance(ev, str) else int(ev or EVT_SCRIPTLETS)
        return ev if ev in (EVT_SCRIPTLETS, EVT_ADD) else EVT_SCRIPTLETS


def install(world):
    """Wrap world.send when [ics] scriptlet_orders is on and the encounter is not skipped."""
    ic = world.ic
    if not ic.get("scriptlet_orders", True):
        return None
    skip = {int(str(e), 0) for e in (ic.get("scriptlet_orders_skip_encounters") or ())}
    if world.encounter in skip:
        return None
    orders = Orders(world, world.send)
    world.send = orders.send
    world.scriptlet_orders = orders
    return orders


def of(world):
    """The world's Orders, or None (off, skipped encounter, a test world)."""
    w = getattr(world, "w", world)
    return getattr(w, "__dict__", {}).get("scriptlet_orders")
