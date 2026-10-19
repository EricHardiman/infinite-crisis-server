"""Read the game's data from the player's own install: records, property
kinds and the English string tables. Used by the catalog scanner
(tools/catalog_scan.py) and by anything that needs a record's contents.

Nothing read here is shipped: the catalog keeps only IDs, short names and
numbers (catalog/README.md).

Pack format: icserver/rp.py. Records: "u32 did | u32 0 | u32 count |
entries", entry = "u32 key | u32 key (| 0x40000000 = no value) | value",
value read by its kind (skilldata._Reader). Kinds come from, in order:
skilldata.BUILTIN_KINDS, catalog/data/properties.tsv (the client's descriptors)
and logs/props.txt (tools/diag.py --props) when present.

String tables (2026-10-16): after a pack's payload come zlib streams aligned
to 0x400, each chunked like the payload (0x20000-byte blocks whose last 4 bytes
are a trailer, counted from the stream's start). One stream holds ONE language
(English, French, German, Russian, in that order) with many tables back to
back: "u32 table (0x2B...) | u32 ? | u32 count", entries "u32 token | u32
nparts | nparts x (u32 len | len UTF-16 chars, padded to 4 bytes) | u32 m |
m x u32". A string is identified by (table, token). The older reader in
tools/skills.py missed most of them.
"""
import csv
import os
import re
import struct
import zlib

from . import rp, skilldata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PROPERTIES = os.path.join(ROOT, "catalog", "data", "properties.tsv")
KIND_CODES = {"iid": 7, "enum": 8, "f32": 9, "table": 0x0B, "array": 0x0C, "string": 0x0E, "int": 0x10,
              "u32": 0x13, "did": 0x15, "bool": 0x16, "bitfield": 0x0D}


def load_kinds(props_txt=None):
    kinds = dict(skilldata.BUILTIN_KINDS)
    if os.path.isfile(CATALOG_PROPERTIES):
        with open(CATALOG_PROPERTIES, encoding="utf-8", newline="") as f:
            rows = csv.reader(f, delimiter="\t")
            head = next(rows, [])
            if "kind_code" in head:
                i, k = head.index("id"), head.index("kind_code")
                for r in rows:
                    try:
                        kinds[int(r[i], 16)] = int(r[k], 16)
                    except (ValueError, IndexError):
                        pass
    if props_txt and os.path.isfile(props_txt):
        kinds.update(skilldata.load_kinds(props_txt))
    return kinds


def pack_header(path):
    """(record count, [DIDs]) without decompressing the records."""
    with open(path, "rb") as f:
        head = f.read(0x400 + 0x20000)
        if head[:4] != b"10PR":
            return 0, []
        size, count = struct.unpack_from("<II", head, 0xC)
        need = 4 * count
        raw = bytearray()
        p = 0x400
        while len(raw) < need:
            f.seek(p)
            raw += f.read(min(0x1FFFC, need - len(raw)))
            p += 0x20000
    return count, list(struct.unpack_from("<%dI" % count, raw, 0))


def text_streams(path):
    """The pack's tail zlib streams (decompressed), in file order."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"10PR":
        return []
    size = struct.unpack_from("<I", d, 0xC)[0]
    off = max(0x400, (0x400 + size - 0x10000) & ~0x3FF)
    out = []
    while off + 2 < len(d):
        if d[off] == 0x78 and d[off + 1] == 1:
            raw = bytearray()
            for k in range(off, len(d), 0x20000):
                raw += d[k:k + 0x1FFFC]
            z = zlib.decompressobj()
            try:
                x = z.decompress(bytes(raw))
                if len(x) < 12 or x[3] != 0x2B:
                    raise zlib.error
                used = len(raw) - len(z.unused_data)
                out.append(x)
                off = (off + used + 4 * (used // 0x1FFFC) + 0x3FF) & ~0x3FF
                continue
            except zlib.error:
                pass
        off += 0x400
    return out


_TABLE_START = re.compile(rb"[\x00-\xff]{3}\x2b[\x00-\x08]\x00\x00\x00[\x01-\xff][\x00-\x7f]\x00\x00", re.S)


def parse_stream(x):
    """[(table DID, {token: text})] from one decompressed stream."""
    tables, p = [], 0
    while p + 12 <= len(x):
        p0 = p
        try:
            did, lang, cnt = struct.unpack_from("<III", x, p)
            p += 12
            if did >> 24 != 0x2B or lang > 8 or cnt > 100000:
                m = _TABLE_START.search(x, p0 + 1)
                if not m:
                    break
                p = m.start()
                continue
            ent = {}
            for _ in range(cnt):
                tok, nparts = struct.unpack_from("<II", x, p)
                p += 8
                if nparts > 64:
                    raise struct.error
                parts = []
                for _ in range(nparts):
                    n = struct.unpack_from("<I", x, p)[0]
                    p += 4
                    if n > 40000:
                        raise struct.error
                    parts.append(x[p:p + 2 * n].decode("utf-16le", "replace"))
                    p = (p + 2 * n + 3) & ~3
                m = struct.unpack_from("<I", x, p)[0]
                if m > 1000:
                    raise struct.error
                p += 4 + 4 * m
                ent[tok] = "{}".join(parts)
            tables.append((did, ent))
        except (struct.error, UnicodeError):
            p = p0 + 1
    return tables


def plain(text):
    """Text without the UI's HTML tags and extra spaces."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


class Game:
    """The player's rp folder: records by DID and English texts."""

    def __init__(self, rp_dir, props_txt=None):
        self.rp_dir = rp_dir
        self.kinds = load_kinds(props_txt)
        self.packs = rp.PackSet(rp_dir)
        self._where = None
        self._texts = None

    def pack_files(self):
        try:
            return sorted(n for n in os.listdir(self.rp_dir) if n.lower().endswith(".rp"))
        except OSError:
            return []

    def index(self):
        """{DID: pack file name} for every record of every pack (headers only)."""
        if self._where is None:
            self._where = {}
            for name in self.pack_files():
                try:
                    _, ids = pack_header(os.path.join(self.rp_dir, name))
                except (OSError, struct.error):
                    continue
                for did in ids:
                    self._where.setdefault(did, name)
        return self._where

    def record(self, did, pack=None):
        """The record's top-level entries [(key, kind, value)], or None."""
        name = pack or self.index().get(did)
        if not name:
            return None
        try:
            data = self.packs.pack(name).data
        except (OSError, ValueError, zlib.error):
            return None
        pat = struct.pack("<II", did, 0)
        k = data.find(pat)
        while k >= 0:
            try:
                r = skilldata._Reader(data, k + 8, self.kinds)
                n = r.u32()
                if 0 < n < 400:
                    out = []
                    for _ in range(n):
                        key, word = r.u32(), r.u32()
                        if word == key | 0x40000000:
                            out.append((key, None, None))
                            continue
                        kind, value = r.value(key)
                        out.append((key, kind, value))
                    return out
            except (ValueError, struct.error):
                pass
            k = data.find(pat, k + 1)
        return None

    def world_state(self, did, partial=False):
        """A world state (0x2E) record: "u32 did | u32 7 | u32 .entity (0x2D) |
        u32 0 | u32 count | entries". Returns (entity, entries) or None.
        partial: 2026-10-16 22:47 - the entries read before the first value this
        reader cannot size (vectors such as 0x24E / 0x667 / 0x4B9) instead of
        None; the meteor rocks' 0x7D2 comes first and was lost that way."""
        name = self.index().get(did)
        if not name:
            return None
        try:
            data = self.packs.pack(name).data
        except (OSError, ValueError, zlib.error):
            return None
        # 2026-10-16 14:57: record_starts() of a 114 MB pack takes 10-20 s and was
        # recomputed for every world state; the record's own header is searched
        # directly instead ("did | 7")
        pat = struct.pack("<II", did, 7)
        off = data.find(pat)
        while off >= 0:
            try:
                _did, seven, entity, zero, n = struct.unpack_from("<5I", data, off)
                if seven != 7 or zero != 0 or not 0 < n < 400:
                    raise ValueError("not a world state header")
                r = skilldata._Reader(data, off + 20, self.kinds)
                out = []
                try:
                    for _ in range(n):
                        key, word = r.u32(), r.u32()
                        if word == key | 0x40000000:
                            out.append((key, None, None))
                            continue
                        kind, value = r.value(key)
                        out.append((key, kind, value))
                except (ValueError, struct.error):
                    if not (partial and out):
                        raise
                return entity, out
            except (ValueError, struct.error):
                pass
            off = data.find(pat, off + 1)
        return None

    def world_state_raw(self, did, size=4096):
        """The first bytes of a world state record (from its "did | 7" header), or b""."""
        name = self.index().get(did)
        if not name:
            return b""
        try:
            data = self.packs.pack(name).data
        except (OSError, ValueError, zlib.error):
            return b""
        off = data.find(struct.pack("<II", did, 7))
        return data[off:off + size] if off >= 0 else b""

    def texts(self):
        """{(table DID, token): English text} from every pack."""
        if self._texts is None:
            self._texts = {}
            for name in self.pack_files():
                try:
                    streams = text_streams(os.path.join(self.rp_dir, name))
                except OSError:
                    continue
                if streams:            # the first stream is English
                    for did, ent in parse_stream(streams[0]):
                        for tok, text in ent.items():
                            self._texts.setdefault((did, tok), text)
        return self._texts

    def text(self, value):
        """A string value (token, table) -> plain English text ('' if unknown)."""
        if not value:
            return ""
        token, table = value
        return plain(self.texts().get((table, token), ""))


def get(entries, key, default=None):
    for k, _kind, v in entries or ():
        if k == key:
            return v
    return default


def f32(v):
    return round(struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0], 4) if isinstance(v, int) else v
