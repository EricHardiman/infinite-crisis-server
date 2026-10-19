"""Emotes (Ctrl+1..4) for the champion in a match.

2026-10-16 17:29 (tester): "program the actions of Ctrl+1, Ctrl+2, Ctrl+3,
Ctrl+4". The game maps them to the input actions Joke / Taunt / Laugh / Dance
(0x100000CC..CF -> emote codes 0x16 / 0x15 / 0x17 / 0x18, docs/re-notes/
hud2_re.txt) and hands them to a script method whose network message is still
unknown (no unhandled event was seen for them). So the server watches the keys
itself while the game window is in front (winctl.watch_keys; the keys still
reach the game) and raises the emote on the champion's behavior graph:
Emote_Joke 0x1000022E, Emote_Taunt 0x1000022C, Emote_Laugh 0x1000022D,
Emote_Dance 0x100001F1 (graph 0x1A0002E7; walking aborts them, the graph's
onEmoting). [app] emote_keys turns it off.
"""
import time

from . import log, winctl

EMOTES = {
    1: ("Joke", 0x1000022E),
    2: ("Taunt", 0x1000022C),
    3: ("Laugh", 0x1000022D),
    4: ("Dance", 0x100001F1),
}
MATCH_PHASES = ("IN_WORLD", "PLAYING")


class Emotes:
    def __init__(self, server):
        self.server = server
        self.cfg = server.cfg
        self.exe = self.cfg["game"]["patched_exe"]
        self._pids, self._pids_at = set(), 0.0
        self.last = 0.0

    def _game_in_front(self):
        if time.time() - self._pids_at > 5:
            self._pids, self._pids_at = set(winctl.pids_of(self.exe)), time.time()
        return winctl.foreground_pid() in self._pids

    def key(self, vk, ctrl):
        if not ctrl or not (0x31 <= vk <= 0x34) or not self._game_in_front():
            return
        self.play(vk - 0x30, "Ctrl+%d" % (vk - 0x30))

    def play(self, n, why):
        """Emote number n (1-4) on the champion of the running match."""
        if n not in EMOTES or time.time() - self.last < 0.4:
            return False
        name, event = EMOTES[n]
        for s in [s for s in self.server.sessions if not s.user.closed]:
            m = s.match
            if s.phase in MATCH_PHASES and m and getattr(m, "tutorial", None):
                self.last = time.time()
                log.info(f"emote {name} ({why}): graph event {event:#x}", s)
                s.later(0, lambda m=m: m.tutorial.raise_events([event], f"emote {name}"))
                return True
        return False


def start(server):
    """Start watching Ctrl+1..4 (Windows)."""
    if not server.cfg["app"].get("emote_keys", True):
        return None
    server.emotes = Emotes(server)
    return winctl.watch_keys(range(0x31, 0x35), server.emotes.key)
