"""Game textures (records 0x13......) as PNG, for the companion app.

Read from the player's own install and cached on the player's machine
(data/texcache/); nothing is shipped with the project.

Record layout (2026-10-16, checked on wallpapers, portraits, skill and avatar
icons): u32 did | u32 2 | u32 type (1 = 2D; 5-8 also seen) | u32 flags |
u32 3 | u32 width | u32 height | 4-byte format | u32 size | pixels.
Formats: b"DXT1", b"DXT3", b"DXT5", and 0x15 = A8R8G8B8 (bytes B G R A).
Only the first (largest) image is decoded.

The decoding runs in a separate process (render() through a process pool) so a
running match never waits for it.
"""
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "texcache")


# ---- PNG -------------------------------------------------------------------------
def _png(width, height, rgba):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    stride = width * 4
    raw = b"".join(b"\x00" + bytes(rgba[y * stride:(y + 1) * stride]) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---- DXT -------------------------------------------------------------------------
def _c565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def _color_block(data, o, out, w, x0, y0, alpha=None, dxt1=False):
    c0, c1, bits = struct.unpack_from("<HHI", data, o)
    a, b = _c565(c0), _c565(c1)
    if c0 > c1 or not dxt1:
        pal = (a + (255,), b + (255,),
               tuple((2 * a[i] + b[i]) // 3 for i in range(3)) + (255,),
               tuple((a[i] + 2 * b[i]) // 3 for i in range(3)) + (255,))
    else:
        pal = (a + (255,), b + (255,), tuple((a[i] + b[i]) // 2 for i in range(3)) + (255,), (0, 0, 0, 0))
    for py in range(4):
        y = y0 + py
        row = (y * w + x0) * 4
        for px in range(4):
            col = pal[(bits >> (2 * (4 * py + px))) & 3]
            k = row + px * 4
            out[k:k + 3] = bytes(col[:3])
            out[k + 3] = col[3] if alpha is None else alpha[4 * py + px]


def _decode_dxt(fmt, w, h, data):
    out = bytearray(w * h * 4)
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    size = 8 if fmt == b"DXT1" else 16
    pw, ph = bw * 4, bh * 4
    tmp = bytearray(pw * ph * 4) if (pw, ph) != (w, h) else out
    o = 0
    for by in range(bh):
        for bx in range(bw):
            if o + size > len(data):
                break
            alpha = None
            if fmt == b"DXT3":
                bits = int.from_bytes(data[o:o + 8], "little")
                alpha = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
                o += 8
            elif fmt == b"DXT5":
                a0, a1 = data[o], data[o + 1]
                bits = int.from_bytes(data[o + 2:o + 8], "little")
                if a0 > a1:
                    pal = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
                else:
                    pal = [a0, a1] + [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
                alpha = [pal[(bits >> (3 * i)) & 7] for i in range(16)]
                o += 8
            _color_block(data, o, tmp, pw, bx * 4, by * 4, alpha, fmt == b"DXT1")
            o += 8
    if tmp is not out:
        for y in range(h):
            out[y * w * 4:(y + 1) * w * 4] = tmp[y * pw * 4:y * pw * 4 + w * 4]
    return out


def _decode_argb(w, h, data):
    out = bytearray(w * h * 4)
    n = min(len(data) // 4, w * h)
    out[0:n * 4:4] = data[2:n * 4:4]
    out[1:n * 4:4] = data[1:n * 4:4]
    out[2:n * 4:4] = data[0:n * 4:4]
    out[3:n * 4:4] = data[3:n * 4:4]
    return out


def _downscale(w, h, rgba, max_size):
    """Nearest-neighbour shrink so the larger side is at most max_size."""
    if not max_size or max(w, h) <= max_size:
        return w, h, rgba
    k = max(w, h) / max_size
    nw, nh = max(1, int(w / k)), max(1, int(h / k))
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = int(y * k) * w
        for x in range(nw):
            s = (sy + int(x * k)) * 4
            d = (y * nw + x) * 4
            out[d:d + 4] = rgba[s:s + 4]
    return nw, nh, out


def decode_record(rec, max_size=0):
    """A texture record's bytes -> PNG bytes (None if the format is unknown)."""
    if len(rec) < 40:
        return None
    _did, two, _t, _flags, three, w, h = struct.unpack_from("<7I", rec, 0)
    fmt = rec[28:32]
    size = struct.unpack_from("<I", rec, 32)[0]
    if two != 2 or three != 3 or not (0 < w <= 4096 and 0 < h <= 4096):
        return None
    data = rec[36:36 + size]
    if fmt in (b"DXT1", b"DXT3", b"DXT5"):
        if w > 512 or h > 512:
            # big wallpapers: decode, then shrink (pure Python is slow on 4 MB of pixels)
            pass
        rgba = _decode_dxt(fmt, w, h, data)
    elif struct.unpack("<I", fmt)[0] == 0x15:
        rgba = _decode_argb(w, h, data)
    else:
        return None
    w, h, rgba = _downscale(w, h, rgba, max_size)
    return _png(w, h, rgba)


# ---- finding the record ------------------------------------------------------------
_index = {}


def _where(rp_dir, did):
    from . import gamedata
    if rp_dir not in _index:
        _index[rp_dir] = gamedata.Game(rp_dir).index()
    return _index[rp_dir].get(did)


_packs = {}


def _record(rp_dir, did):
    name = _where(rp_dir, did)
    if not name:
        return None
    from .rp import Pack
    key = (rp_dir, name)
    if key not in _packs:
        if len(_packs) > 6:                          # keep memory bounded
            _packs.pop(next(iter(_packs)))
        _packs[key] = Pack(os.path.join(rp_dir, name))
    pk = _packs[key]
    pat = struct.pack("<II", did, 2)
    k = pk.data.find(pat)
    while k >= 0:
        if struct.unpack_from("<I", pk.data, k + 16)[0] == 3:
            return pk.data[k:k + 36 + struct.unpack_from("<I", pk.data, k + 32)[0]]
        k = pk.data.find(pat, k + 1)
    return None


def render(rp_dir, did, max_size=0):
    """Worker (runs in the pool's process): the PNG path for a texture, or ''."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{did:08x}_{max_size}.png")
    if os.path.isfile(path):
        return path
    try:
        rec = _record(rp_dir, did)
        png = decode_record(rec, max_size) if rec else None
    except Exception:                                # noqa: BLE001 -- a bad texture is just missing
        png = None
    if not png:
        return ""
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)
    return path


_pool = None


def png_path(rp_dir, did, max_size=0, timeout=60.0):
    """The cached PNG for a texture, decoding it in a worker process first."""
    path = os.path.join(CACHE, f"{did:08x}_{max_size}.png")
    if os.path.isfile(path):
        return path
    global _pool
    if _pool is None:
        import concurrent.futures
        _pool = concurrent.futures.ProcessPoolExecutor(max_workers=1)
    try:
        return _pool.submit(render, rp_dir, did, max_size).result(timeout=timeout)
    except Exception:                                # noqa: BLE001
        return ""
