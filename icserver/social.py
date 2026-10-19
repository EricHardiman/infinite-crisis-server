"""Friends, presence and chat for the companion app.

2026-10-16 16:51 (tester): "the friends list, the chat and those social bits are
missing". Everyone who opens the app on this server (the player, or friends on
the same network pointing their app at it) is a user, known by name. Friends
lists, the chat history and who has read what are kept in data/social.json;
presence (online / away / busy / in game) lives in memory: a user is online
while their app polls (every few seconds) and offline 20 s after it stops.
"""
import json
import os
import threading
import time

from .config import ROOT

ONLINE_FOR = 20.0          # seconds without a poll before a user shows offline
KEEP_MESSAGES = 2000
STATUSES = ("online", "away", "busy")


def _clean(name):
    return " ".join(str(name or "").split())[:24]


def _key(name):
    return _clean(name).lower()


class Social:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.path = cfg["app"].get("social_file") or os.path.join(ROOT, "data", "social.json")
        self.seen = {}          # key -> (time, display name, status, in_game)
        self.data = self._load()

    # ---- storage -----------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data.setdefault("friends", {})      # key -> [display names]
        data.setdefault("names", {})        # key -> display name
        data.setdefault("messages", [])     # {id, from, to, text, t}
        data.setdefault("read", {})         # key -> {friend key: last read id}
        data.setdefault("next_id", 1)
        return data

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- presence ------------------------------------------------------------------
    def touch(self, me, status=None, in_game=False):
        k = _key(me)
        if not k:
            raise ValueError("no name")
        old = self.seen.get(k)
        status = status if status in STATUSES else (old[2] if old else "online")
        self.seen[k] = (time.time(), _clean(me), status, in_game)
        if self.data["names"].get(k) != _clean(me):
            self.data["names"][k] = _clean(me)
            self._save()
        return k

    def presence(self, name):
        s = self.seen.get(_key(name))
        if not s or time.time() - s[0] > ONLINE_FOR:
            return "offline"
        return "ingame" if s[3] and s[2] == "online" else s[2]

    # ---- API -------------------------------------------------------------------------
    def overview(self, me, status=None, in_game=False):
        with self.lock:
            k = self.touch(me, status, in_game)
            read = self.data["read"].get(k, {})
            friends = []
            for name in self.data["friends"].get(k, []):
                fk = _key(name)
                unread = sum(1 for m in self.data["messages"]
                             if _key(m["from"]) == fk and _key(m["to"]) == k and m["id"] > read.get(fk, 0))
                last = max((m["id"] for m in self.data["messages"]
                            if {_key(m["from"]), _key(m["to"])} == {k, fk}), default=0)
                friends.append({"name": self.data["names"].get(fk, name), "status": self.presence(name),
                                "unread": unread, "last": last,
                                "is_friend_back": k in {_key(n) for n in self.data["friends"].get(fk, [])}})
            # people who added me and I have not added back
            requests = [self.data["names"].get(fk, fk) for fk, lst in self.data["friends"].items()
                        if fk != k and k in {_key(n) for n in lst}
                        and fk not in {_key(n) for n in self.data["friends"].get(k, [])}]
            return {"me": _clean(me), "status": self.presence(me), "friends": friends, "requests": requests}

    def friend(self, me, name, remove=False):
        with self.lock:
            k, fk = _key(me), _key(name)
            if not fk:
                return {"ok": False, "error": "Type a name"}
            if fk == k:
                return {"ok": False, "error": "That's you"}
            self.data["names"].setdefault(k, _clean(me))
            lst = self.data["friends"].setdefault(k, [])
            lst[:] = [n for n in lst if _key(n) != fk]
            if not remove:
                lst.append(_clean(name))
                self.data["names"].setdefault(fk, _clean(name))
            self._save()
            return {"ok": True}

    def messages(self, me, other, since=0):
        with self.lock:
            k, ok_ = _key(me), _key(other)
            msgs = [m for m in self.data["messages"] if {_key(m["from"]), _key(m["to"])} == {k, ok_}
                    and m["id"] > since][-200:]
            if msgs:
                self.data["read"].setdefault(k, {})[ok_] = max(m["id"] for m in msgs)
                self._save()
            return {"messages": msgs, "status": self.presence(other)}

    def send(self, me, to, text):
        text = str(text or "").strip()[:500]
        if not text:
            return {"ok": False, "error": "Empty message"}
        with self.lock:
            m = {"id": self.data["next_id"], "from": _clean(me), "to": _clean(to), "text": text, "t": time.time()}
            self.data["next_id"] += 1
            self.data["messages"].append(m)
            del self.data["messages"][:-KEEP_MESSAGES]
            self._save()
            return {"ok": True, "message": m}
