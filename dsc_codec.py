#!/usr/bin/env python3
"""
Codec for Desynced "DS" clipboard strings (behaviors/blueprints), ported from the
official dsconvert.js (https://github.com/StageGames/DesyncedJavaScriptUtils).

Format: DS<type><base62-u32-decompressed-len><base62-data>
Inner data: optionally zlib-compressed, then a MessagePack-like binary format
customized for Lua tables (sparse-array vacancy bitmasks, 1-based/0-based key
shifting, and three non-standard type bytes: it repurposes 0xc1 (reserved/unused
in real MessagePack) and 0xc4/0xc5 (bin8/bin16 in real MessagePack) for
USERDATA/INVALID/DEADKEY, so this is NOT decodable with a stock MessagePack
library despite looking like one).

Table representation used by this module: a Lua table decodes to a Python
`list` if it was a pure array, or a `dict` if it has any hash-part entries
(dict keys are Python `int`, 0-based, for what were originally 1-based Lua
numeric keys, or `str` for everything else). encode_dsc() accepts the same
shapes, and also accepts numeric-looking string keys (e.g. from JSON, which
can't have int keys) -- it normalizes those to int automatically.
"""
import json
import struct
import sys
import zlib

BASE62_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
B62 = [255] * 256
for _i, _c in enumerate(BASE62_CHARS):
    B62[ord(_c)] = _i

MP_FixZero = 0x00
MP_FixMap = 0x80
MP_FixArray = 0x90
MP_FixStr = 0xA0
MP_Nil = 0xC0
MP_False = 0xC2
MP_True = 0xC3
MP_Float32 = 0xCA
MP_Float64 = 0xCB
MP_Uint8 = 0xCC
MP_Uint16 = 0xCD
MP_Uint32 = 0xCE
MP_Uint64 = 0xCF
MP_Int8 = 0xD0
MP_Int16 = 0xD1
MP_Int32 = 0xD2
MP_Int64 = 0xD3
MP_Str8 = 0xD9
MP_Str16 = 0xDA
MP_Str32 = 0xDB
MP_Array16 = 0xDC
MP_Array32 = 0xDD
MP_Map16 = 0xDE
MP_Map32 = 0xDF
MP_DESYNCED_USERDATA = 0xC1
MP_DESYNCED_INVALID = 0xC4
MP_DESYNCED_DEADKEY = 0xC5


# --- Base62 (custom framing, not a standard base62) ---

def b62_read_u32(data, idx, end):
    u = 0
    while idx < end:
        c = data[idx]
        idx += 1
        b = B62[c]
        if b == 255:
            if c <= 32:
                continue
            return 0, idx
        u = u * 31 + (b % 31)
        if b >= 31:
            return u, idx
    return 0, idx


def b62_write_u32(u):
    tok = BASE62_CHARS[31 + (u % 31)]
    u //= 31
    while u:
        tok = BASE62_CHARS[u % 31] + tok
        u //= 31
    return tok


def b62_read_data(data, idx, end):
    if idx >= end:
        return None
    checksum_idx = end - 1
    buf = bytearray((((checksum_idx - idx) * 4) // 6) + 4)
    datalen = 0
    chksum = 0
    while idx < checksum_idx:
        bits = 0
        i = 0
        while i < 6 and idx < checksum_idx:
            c = data[idx]
            idx += 1
            b = B62[c]
            if b == 255:
                if c <= 32:
                    continue
                return None
            bits = bits * 62 + b
            i += 1
        chksum = (chksum + bits) % 0x100000000
        if i == 6:
            buf[datalen] = bits & 0xFF; bits >>= 8; datalen += 1
            buf[datalen] = bits & 0xFF; bits >>= 8; datalen += 1
            buf[datalen] = bits & 0xFF; bits >>= 8; datalen += 1
            buf[datalen] = bits & 0xFF; datalen += 1
        elif i == 5:
            buf[datalen] = bits & 0xFF; bits >>= 8; datalen += 1
            buf[datalen] = bits & 0xFF; bits >>= 8; datalen += 1
            buf[datalen] = bits & 0xFF; datalen += 1
        elif i == 3:
            buf[datalen] = bits & 0xFF; bits >>= 8; datalen += 1
            buf[datalen] = bits & 0xFF; datalen += 1
        elif i == 2:
            buf[datalen] = bits & 0xFF; datalen += 1
    if B62[data[idx]] != (chksum % 62):
        print(f"WARNING: checksum mismatch (got {B62[data[idx]]}, expected {chksum % 62})", file=sys.stderr)
    return bytes(buf[:datalen])


CHARS_FOR_BYTES = [0, 2, 3, 5]  # indexed by remaining-byte-count (1,2,3) -> char count; 6 chars for a full 4-byte chunk


def b62_write_data(data):
    out = []
    chksum = 0
    i = 0
    remaining = len(data)
    n = remaining
    while remaining > 0:
        nchars = 6 if remaining > 3 else CHARS_FOR_BYTES[remaining]
        b0 = data[i] if i < n else 0
        b1 = data[i + 1] if i + 1 < n else 0
        b2 = data[i + 2] if i + 2 < n else 0
        b3 = data[i + 3] if i + 3 < n else 0
        bits = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)
        chksum = (chksum + bits) % 0x100000000
        tok = ""
        for _ in range(nchars):
            tok = BASE62_CHARS[bits % 62] + tok
            bits //= 62
        out.append(tok)
        remaining -= 4
        i += 4
    out.append(BASE62_CHARS[chksum % 62])
    return "".join(out)


def get_int_packed(buf, p):
    """p is a 1-element list used as a mutable index cursor."""
    res = cnt = 0
    while True:
        b = buf[p[0]]
        p[0] += 1
        res |= (b >> 1) << (7 * cnt)
        cnt += 1
        if not (b & 1):
            break
    return res


def push_int_packed(out, v):
    while True:
        b = v & 127
        v >>= 7
        out.append((b << 1) | (1 if v else 0))
        if not v:
            break


# --- Decode ---

def decode_dsc(s):
    data = [ord(c) for c in s]
    idx, end = 0, len(data)
    while idx < end and B62[data[idx]] == 255:
        idx += 1
    while end > idx and B62[data[end - 1]] == 255:
        end -= 1
    assert end - idx >= 5, "Too short"
    assert data[idx] == ord('D') and data[idx + 1] == ord('S'), "Missing DS prefix"
    type_char = chr(data[idx + 2])
    idx += 3

    decompress_len, idx = b62_read_u32(data, idx, end)

    raw = b62_read_data(data, idx, end)
    assert raw is not None, "Failed to decode base62 data"

    buf = zlib.decompress(raw) if decompress_len else raw

    return type_char, parse_msgpack(buf)


def parse_msgpack(buf):
    p = [0]

    def read(n):
        v = buf[p[0]:p[0] + n]
        p[0] += n
        return v

    def parse_table(sz, is_map):
        if is_map:
            size_node = 1 << (sz >> 1)
            size_array = get_int_packed(buf, p) if (sz & 1) else 0
            get_int_packed(buf, p)  # Lua memory layout hint, skip
        else:
            size_array = sz
            size_node = 0

        t = {} if is_map else []
        total = size_array + size_node
        i = 0
        while i < total:
            vacancy_bits = buf[p[0]]
            p[0] += 1
            i_end = min(total, i + 8)
            mask = 1
            while i < i_end:
                if not (vacancy_bits & mask):
                    val = parse()
                    if i < size_array:
                        if isinstance(t, list):
                            t.append(val)
                        else:
                            t[i] = val
                    else:
                        if buf[p[0]] == MP_DESYNCED_DEADKEY:
                            p[0] += 1
                            get_int_packed(buf, p)
                        else:
                            key = parse(is_key=True)
                            if isinstance(key, int):
                                t[key - 1] = val
                            else:
                                try:
                                    t[int(key) - 1] = val
                                except (ValueError, TypeError):
                                    t[key] = val
                            get_int_packed(buf, p)  # Lua memory layout, skip
                i += 1
                mask <<= 1
        return t

    def parse(is_key=False):
        tp = buf[p[0]]
        p[0] += 1
        if tp == MP_Nil:
            return None
        if tp == MP_False:
            return False
        if tp == MP_True:
            return True
        if tp == MP_FixZero:
            return 0
        if tp == MP_Float32:
            return struct.unpack_from('<f', read(4))[0]
        if tp == MP_Float64:
            return struct.unpack_from('<d', read(8))[0]
        if tp == MP_Uint8:
            return struct.unpack_from('<B', read(1))[0]
        if tp == MP_Uint16:
            return struct.unpack_from('<H', read(2))[0]
        if tp == MP_Uint32:
            return struct.unpack_from('<I', read(4))[0]
        if tp == MP_Uint64:
            return struct.unpack_from('<Q', read(8))[0]
        if tp == MP_Int8:
            return struct.unpack_from('<b', read(1))[0]
        if tp == MP_Int16:
            return struct.unpack_from('<h', read(2))[0]
        if tp == MP_Int32:
            return struct.unpack_from('<i', read(4))[0]
        if tp == MP_Int64:
            return struct.unpack_from('<q', read(8))[0]
        if tp == MP_Str8:
            n = struct.unpack_from('<B', read(1))[0]
            return read(n).decode('utf-8')
        if tp == MP_Str16:
            n = struct.unpack_from('<H', read(2))[0]
            return read(n).decode('utf-8')
        if tp == MP_Str32:
            n = struct.unpack_from('<I', read(4))[0]
            return read(n).decode('utf-8')
        if tp == MP_FixStr:
            return ""
        if tp == MP_Array16:
            n = struct.unpack_from('<H', read(2))[0]
            return parse_table(n, False)
        if tp == MP_Array32:
            n = struct.unpack_from('<I', read(4))[0]
            return parse_table(n, False)
        if tp == MP_FixArray:
            return parse_table(0, False)
        if tp == MP_Map16:
            n = struct.unpack_from('<H', read(2))[0]
            return parse_table(n, True)
        if tp == MP_Map32:
            n = struct.unpack_from('<I', read(4))[0]
            return parse_table(n, True)
        if tp == MP_FixMap:
            return parse_table(0, True)
        if tp == MP_DESYNCED_USERDATA:
            raise ValueError(f"Userdata type {get_int_packed(buf, p)} not supported")
        if tp < MP_FixMap:
            return tp  # positive fixint
        if tp < MP_FixArray:
            return parse_table(tp - MP_FixMap, True)
        if tp < MP_FixStr:
            return parse_table(tp - MP_FixArray, False)
        if tp < MP_Nil:
            n = tp - MP_FixStr
            return read(n).decode('utf-8')
        if tp > MP_Map32:
            return tp - 256  # negative fixint
        raise ValueError(f"Unknown type byte: 0x{tp:02x}")

    return parse()


# --- Encode ---

def _is_int_str(s):
    if s in ("", "-"):
        return False
    body = s[1:] if s[0] == "-" else s
    return body.isdigit()


def _normalize_keys(v):
    """JSON objects can only have string keys; treat numeric-looking ones as
    the int keys our table representation (and the wire format) expects."""
    return {(int(k) if isinstance(k, str) and _is_int_str(k) else k): val for k, val in v.items()}


def serialize(out, v, is_table_key=False):
    if v is None:
        if is_table_key:
            raise ValueError("Unable to serialize table key of type 'None'")
        out.append(MP_Nil)
    elif isinstance(v, bool):
        if is_table_key:
            raise ValueError("Unable to serialize table key of type 'bool'")
        out.append(MP_True if v else MP_False)
    elif isinstance(v, (int, float)):
        _serialize_number(out, v)
    elif isinstance(v, str):
        _serialize_string(out, v)
    elif isinstance(v, (dict, list)):
        if is_table_key:
            raise ValueError("Unable to serialize table key of type 'table'")
        _serialize_table(out, v)
    else:
        raise TypeError(f"cannot serialize unsupported type {type(v)}")


def _serialize_number(out, v):
    if isinstance(v, float) and not v.is_integer():
        out.append(MP_Float64)
        out.extend(struct.pack('<d', v))
        return
    n = int(v)
    if n > 0xFFFFFFFF:
        out.append(MP_Uint64)
        out.extend(struct.pack('<Q', n))
    elif n > 0xFFFF:
        out.append(MP_Uint32)
        out.extend(struct.pack('<I', n))
    elif n > 0xFF:
        out.append(MP_Uint16)
        out.extend(struct.pack('<H', n))
    elif n > 0x7F:
        out.append(MP_Uint8)
        out.append(n)
    elif n >= 0:
        out.append(n)
    elif n >= -32:
        out.append(n + 256)
    elif n >= -128:
        out.append(MP_Int8)
        out.extend(struct.pack('<b', n))
    elif n >= -32768:
        out.append(MP_Int16)
        out.extend(struct.pack('<h', n))
    elif n >= -2147483648:
        out.append(MP_Int32)
        out.extend(struct.pack('<i', n))
    else:
        # The reference JS encoder emits MP_Uint64 here and calls a DataView
        # method (setUint64) that doesn't actually exist -- a dead/broken
        # path for numbers below INT32_MIN. We implement it properly as a
        # signed Int64 instead of reproducing the crash.
        out.append(MP_Int64)
        out.extend(struct.pack('<q', n))


def _serialize_string(out, v):
    encoded = v.encode('utf-8')
    n = len(encoded)
    if n < 32:
        out.append(MP_FixStr | n)
    elif n < 256:
        out.append(MP_Str8)
        out.append(n)
    elif n < 65536:
        out.append(MP_Str16)
        out.extend(struct.pack('<H', n))
    else:
        out.append(MP_Str32)
        out.extend(struct.pack('<I', n))
    out.extend(encoded)


def _serialize_table(out, v):
    if isinstance(v, list):
        v = dict(enumerate(v))
    else:
        v = _normalize_keys(v)

    # Scan how far the "array part" extends, allowing exactly one gap (a
    # missing index immediately followed by a present one).
    size_array = 0
    array_keys = 0
    while True:
        if size_array in v:
            array_keys += 1
        elif (size_array + 1) not in v:
            break
        size_array += 1

    all_keys = list(v.keys())
    key_count = len(all_keys)
    map_keys = key_count - array_keys
    keys = [k for k in all_keys if not (isinstance(k, int) and not isinstance(k, bool) and 0 <= k < size_array)]

    if map_keys:
        sz = (len(bin(map_keys - 1)[2:]) << 1) | (1 if size_array else 0)
    else:
        sz = size_array

    if sz < 16:
        out.append((MP_FixMap if map_keys else MP_FixArray) | sz)
    elif sz < 65536:
        out.append(MP_Map16 if map_keys else MP_Array16)
        out.extend(struct.pack('<H', sz))
    else:
        out.append(MP_Map32 if map_keys else MP_Array32)
        out.extend(struct.pack('<I', sz))

    size_node = 0
    if map_keys:
        size_node = 1 << (sz >> 1)
        if size_array:
            push_int_packed(out, size_array)
        out.append(0)  # Lua table memory-layout hint; unused by any decoder here

    total = size_array + size_node
    last = size_array + map_keys
    i = 0
    vacancy_bits = 0
    while i != total:
        bit = i & 7
        vacant = (i >= last) or (i < size_array and i not in v)
        vacancy_bits = (vacancy_bits if bit else 0) | ((1 if vacant else 0) << bit)
        i += 1
        if i == total or bit == 7:
            out.append(vacancy_bits)
            start = i - 1 - bit
            for j in range(start, i):
                if j >= last or (j < size_array and j not in v):
                    continue
                if j < size_array:
                    serialize(out, v[j])
                else:
                    key = keys[j - size_array]
                    serialize(out, v[key])
                    if isinstance(key, int) and not isinstance(key, bool):
                        serialize(out, key + 1, is_table_key=True)
                    else:
                        serialize(out, key, is_table_key=True)
                    out.append(0)  # Lua table memory-layout hint; unused by any decoder here


def encode_dsc(type_char, obj):
    raw = bytearray()
    serialize(raw, obj)
    raw = bytes(raw)

    compressed_length = 0
    payload = raw
    comp = zlib.compress(raw, 9)
    if len(comp) < len(raw):
        compressed_length = len(raw)
        payload = comp

    parts = ["DS" + (type_char[:1] if type_char else "?")]
    parts.append(b62_write_u32(compressed_length))
    parts.append(b62_write_data(payload))
    return "".join(parts)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('decode', 'encode'):
        mode, rest = sys.argv[1], sys.argv[2:]
    else:
        mode, rest = 'decode', sys.argv[1:]  # back-compat: bare path == decode

    if mode == 'decode':
        path = rest[0] if rest else 'observer'
        with open(path) as f:
            s = f.read().strip()
        type_char, obj = decode_dsc(s)
        print(f"// Type: {type_char}")
        print(json.dumps(obj, indent=2, default=str))
    else:
        if not rest:
            print("usage: dsc_codec.py encode <infile.json> [type_char]", file=sys.stderr)
            sys.exit(1)
        path = rest[0]
        type_char = rest[1] if len(rest) > 1 else 'C'
        with open(path) as f:
            obj = json.load(f)
        print(encode_dsc(type_char, obj))
