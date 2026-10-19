"""Champion abilities: the start of the server-side ability engine (step 4 of the
Batman plan, docs/batman_actions.md / tools/skills.py).

For now: the slots of a kit, its cooldowns, and the client's cooldown display.

Client event 0x20F8 (handler rva 0x4bc7c0, reader rva 0x439bd0):
  u8 0 | u64 agent IID | u32 skill slot | f64 end time (game clock)
The client shows the remaining time (end - now, VA 0xa0e320) on the skill
button through GM_UI.RecvNotice_StartSkillCooldown(slot, seconds).
"""
import struct

from . import messages as M
from .wire import build_message

EVT_SKILL_COOLDOWN = 0x20F8

# The client's skill slot indices (the "+" button asks for slot 1 = Q).
SLOT_BASIC, SLOT_Q, SLOT_W, SLOT_E, SLOT_R, SLOT_PASSIVE = 0, 1, 2, 3, 4, 5

# Gaslight Batman (pack 0xA0000122, record 0x48000615). Cooldowns: a first
# guess from the stat lists (Sonic Batarang: stat 18 = 9); [combat] cooldowns
# overrides them per slot.
GASLIGHT_BATMAN = {
    SLOT_Q: {"name": "Sonic Batarang", "cooldown": 9.0},
    SLOT_W: {"name": "Sonic Shell", "cooldown": 12.0},
    SLOT_E: {"name": "Bat Flight", "cooldown": 14.0},
    SLOT_R: {"name": "Bat Scream", "cooldown": 80.0},
}


def skill_cooldown(slot, end_time, agent=M.CHAMPION_AGENT_ID, dest=M.LOCAL_PLAYER_ID):
    return build_message(dest, EVT_SKILL_COOLDOWN, b"\x00" + struct.pack("<QId", agent, slot, float(end_time)))


class Cooldowns:
    def __init__(self, kit, overrides=None):
        self.kit = kit
        self.overrides = {int(k): float(v) for k, v in (overrides or {}).items()}
        self.ready_at = {}

    def duration(self, slot):
        if slot in self.overrides:
            return self.overrides[slot]
        return float(self.kit.get(slot, {}).get("cooldown", 0.0))

    def remaining(self, slot, now):
        return max(0.0, self.ready_at.get(slot, 0.0) - now)

    def start(self, slot, now):
        """Put the slot on cooldown; returns the client message (None = no cooldown)."""
        d = self.duration(slot)
        if d <= 0:
            return None
        self.ready_at[slot] = now + d
        return (f"{self.kit.get(slot, {}).get('name', slot)} cooldown {d:g} s (0x20f8)",
                skill_cooldown(slot, now + d))
