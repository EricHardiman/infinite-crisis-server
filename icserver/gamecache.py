"""A small cache of what the server reads from the player's packs at start
(data/game_cache.json, kept on the player's machine like champions.json).

2026-10-16 14:23 (tester: "server disconnected" messages, freezes, Batman
running through buildings): reading the prop scriptlet tables decompresses
three big packs in Python and took about 80 s on the tester's machine. It ran
in a background thread while the player was already in the match and starved
the network threads. Now it runs once, before the ports open, and the result is
cached here; the cache is rebuilt when a pack file changes (name, size, date).
Only DIDs and numbers are stored.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "game_cache.json")
VERSION = 1


def _signature(rp_dir):
    try:
        names = sorted(n for n in os.listdir(rp_dir) if n.lower().endswith(".rp"))
    except OSError:
        return ""
    parts = []
    for n in names:
        try:
            st = os.stat(os.path.join(rp_dir, n))
        except OSError:
            continue
        parts.append(f"{n}:{st.st_size}:{int(st.st_mtime)}")
    return f"v{VERSION}|{rp_dir}|" + ";".join(parts)


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get(rp_dir, name):
    """The cached value or None (also None when the packs changed)."""
    data = _load()
    if data.get("signature") != _signature(rp_dir):
        return None
    return data.get("values", {}).get(name)


def put(rp_dir, name, value):
    sig = _signature(rp_dir)
    data = _load()
    if data.get("signature") != sig:
        data = {"signature": sig, "values": {}}
    data.setdefault("values", {})[name] = value
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, PATH)
    except OSError:
        pass
