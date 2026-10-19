"""Low-level wire encoding for the Infinite Crisis client protocol.

Every format here was worked out by the original infinite-crisis-server project
(EricHardiman/infinite-crisis-server). The client addresses (rva ...) are kept
in the docstrings so the formats can be checked against the disassembly.
These functions are pure: they never touch sockets, clocks or global state.
"""
import math
import struct


# ---- packed integers -------------------------------------------------------

def pack_compact(value):
    """Turbine packed uint (reader rva 0x21430): <0x80 1 byte; <0x4000 2 bytes
    (0x80|hi, lo); <0x20000000 4 bytes (0xC0|b3, b2, u16 LE low); else 0xE0 + u32."""
    if value < 0x80:
        return bytes([value])
    if value < 0x4000:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    if value < 0x20000000:
        return bytes([0xC0 | (value >> 24), (value >> 16) & 0xFF]) + struct.pack("<H", value & 0xFFFF)
    return b"\xE0" + struct.pack("<I", value)


def read_compact(buf, pos):
    """Inverse of pack_compact; returns (value, new_pos)."""
    b0 = buf[pos]
    if b0 < 0x80:
        return b0, pos + 1
    if b0 < 0xC0:
        return ((b0 & 0x3F) << 8) | buf[pos + 1], pos + 2
    if b0 < 0xE0:
        return (((b0 & 0x1F) << 24) | (buf[pos + 1] << 16)
                | struct.unpack_from("<H", buf, pos + 2)[0]), pos + 4
    return struct.unpack_from("<I", buf, pos + 1)[0], pos + 5


# ---- strings -----------------------------------------------------------------

def string_info(text):
    """StringInfo (rva 0x1a9580), literal form: u8 mode 1 | compact length +
    UTF-16 | variables table (u8 size class | compact count)."""
    return b"\x01" + pack_compact(len(text)) + text.encode("utf-16le") + b"\x00" + pack_compact(0)


def wstring(text):
    """compact length + UTF-16 (rva 0x215d0)."""
    return pack_compact(len(text)) + text.encode("utf-16le")


# ---- frames and messages -------------------------------------------------------

def build_frame(packets_mask, payload, header=0x01):
    """u32 len | u8 header | [header&1: u32 packet bitmask, then the packets]
    (client receive path rva 0x70b6c0 -> frame parser 0x70af10)."""
    frame = bytes([header]) + struct.pack("<I", packets_mask) + payload
    return struct.pack("<I", len(frame)) + frame


def build_message(dest_id, event_id, event_body, flags=0x02):
    """Game message frame (frame header 0x02, parser rva 0x70af10):
      u32 len | u8 0x02 | u64 dest | u8 flags | compact event_id | event body
    flags bit 0x02 lets the message past the client's delivery gate (rva
    0xbe1b50) while it is still loading."""
    frame = (b"\x02" + struct.pack("<Q", dest_id) + bytes([flags])
             + pack_compact(event_id) + event_body)
    return struct.pack("<I", len(frame)) + frame


def build_batch(sub_events):
    """Batch event 0x4 body (serializer rva 0x47770): u8 base | compact count |
    per sub-event: compact event id | u32 length | body (no base byte)."""
    out = b"\x00" + pack_compact(len(sub_events))
    for event_id, body in sub_events:
        out += pack_compact(event_id) + struct.pack("<I", len(body)) + body
    return out


class ClientMessage:
    __slots__ = ("dest", "flags", "event_id", "body")

    def __init__(self, dest, flags, event_id, body):
        self.dest, self.flags, self.event_id, self.body = dest, flags, event_id, body

    def __repr__(self):
        return f"<event {self.event_id:#x} dest {self.dest:#018x} body {self.body.hex()}>"


class FrameReader:
    """Splits a client TCP stream into frames (u32 len | payload) and yields
    the game messages (payload starting with 0x02). Other frames (time
    packets, acks) are counted and skipped, exactly like the old server."""

    def __init__(self):
        self.buf = b""
        self.skipped = 0

    def feed(self, data):
        self.buf += data
        out = []
        while len(self.buf) >= 4:
            n = struct.unpack_from("<I", self.buf, 0)[0]
            if len(self.buf) < 4 + n:
                break
            payload, self.buf = self.buf[4:4 + n], self.buf[4 + n:]
            if len(payload) < 11 or payload[0] != 0x02:
                self.skipped += 1
                continue
            dest = struct.unpack_from("<Q", payload, 1)[0]
            event_id, pos = read_compact(payload, 10)
            out.append(ClientMessage(dest, payload[9], event_id, payload[pos:]))
        return out


# ---- positions -----------------------------------------------------------------

def build_position(region, lb_x, lb_y, cell, x, y, z):
    """Position (reader rva 0x7c610): u8 flags | [0x01: u8 region, or 1 when
    0x40] | [0x02: u8 landblock x, y] | [0x08: u16 cell] | [0x10: f32 x, y, z]."""
    flags = 0x02 | 0x08 | 0x10
    out = b""
    if region == 1:
        flags |= 0x01 | 0x40
    else:
        flags |= 0x01
        out += bytes([region])
    return bytes([flags]) + out + bytes([lb_x, lb_y]) + struct.pack("<H", cell) + struct.pack("<fff", x, y, z)


def parse_client_position(buf, pos=0):
    """Inverse of build_position; returns (region, lb_x, lb_y, x, y, z) or None."""
    try:
        flags = buf[pos]; pos += 1
        region = 0
        if flags & 0x01:
            if flags & 0x40:
                region = 1
            else:
                region = buf[pos]; pos += 1
        if not flags & 0x02:
            return None
        lb_x, lb_y = buf[pos], buf[pos + 1]; pos += 2
        if flags & 0x04:
            pos += 2
        if flags & 0x08 and not flags & 0x80:
            pos += 2
        if not flags & 0x10:
            return None
        x, y, z = struct.unpack_from("<fff", buf, pos)
        return region, lb_x, lb_y, x, y, z
    except (IndexError, struct.error):
        return None


def facing_yaw(heading):
    """Model yaw (radians, wrapped to [-pi, pi]) that faces the heading of
    travel: the model's forward axis at yaw 0 is +y, headings are from +x."""
    yaw = heading - math.pi / 2
    return (yaw + math.pi) % (2 * math.pi) - math.pi


# ---- properties ------------------------------------------------------------------

KIND_IID, KIND_ENUM, KIND_F32, KIND_STRING, KIND_INT, KIND_U32, KIND_DID, KIND_BOOL = \
    7, 8, 9, 0x0E, 0x10, 0x13, 0x15, 0x16
KIND_ARRAY = 0x0C     # value: list of (element property id, kind, value)
KIND_TABLE = 0x0B     # value: list of (property id, kind, value): a nested property table
KIND_ENUM2 = 0x0A     # read like an enum (VA 0x4feb20)


def pack_value(kind, value):
    """A property value by kind (readers rva 0x107d60 / 0x107590)."""
    if kind == KIND_IID:
        return struct.pack("<Q", value)
    if kind in (KIND_ENUM, KIND_ENUM2):
        return bytes([value >> 24]) + pack_compact(value & 0xFFFFFF)
    if kind == KIND_F32:
        return struct.pack("<f", value)
    if kind == KIND_STRING:
        if isinstance(value, tuple):
            # StringInfo token form (rva 0x1a9580): u8 mode 0 | u32 token | u32
            # string table | variables table (u8 size class | compact count)
            return b"\x00" + struct.pack("<II", value[0], value[1]) + b"\x00" + pack_compact(0)
        return string_info(value)
    if kind == KIND_TABLE:
        # a property collection (reader VA 0x503330): the same format as an
        # object's property table
        return property_table(value)
    if kind == KIND_INT:
        return pack_compact(value)
    if kind in (KIND_U32, KIND_DID):
        return struct.pack("<I", value)
    if kind == KIND_BOOL:
        return bytes([1 if value else 0])
    if kind == KIND_ARRAY:
        # u32 count | per element: packed property id (it gives the element its
        # type) | value (array reader rva 0x101290, element reader rva 0x109740)
        return struct.pack("<I", len(value)) + b"".join(
            pack_property_id(eid) + pack_value(ekind, evalue) for eid, ekind, evalue in value)
    raise ValueError(f"property kind {kind:#x} not supported")


def pack_property_id(prop_id):
    """Packed property id (reader rva 0xfc420)."""
    if 0x10000000 <= prop_id < 0x10004000:
        return bytes([0x40 | ((prop_id >> 8) & 0x3F), prop_id & 0xFF])
    if prop_id < 0x4000:
        return bytes([prop_id >> 8, prop_id & 0xFF])
    return b"\x80" + struct.pack("<I", prop_id)


def pack_property(prop_id, kind, value):
    """One property-table entry: u32 id | packed id | value by kind
    (value readers rva 0x107d60 / 0x107590)."""
    return struct.pack("<I", prop_id) + pack_property_id(prop_id) + pack_value(kind, value)


def property_table(entries):
    """u8 size class | compact count | entries (reader rva 0x103330)."""
    return bytes([0]) + pack_compact(len(entries)) + b"".join(pack_property(*e) for e in entries)


def hexdump(data):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hexpart:<48}  {text}")
    return "\n".join(lines)
