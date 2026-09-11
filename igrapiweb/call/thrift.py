"""Self-contained Thrift Compact Protocol codec for IG call signaling on the rpsignaling DGW channel."""
from __future__ import annotations
from typing import List, Tuple, Any

STOP = 0x00; BOOL_T = 1; BOOL_F = 2; I8 = 3; I16 = 4; I32 = 5; I64 = 6
DOUBLE = 7; BIN = 8; LIST = 9; SET = 10; MAP = 11; STRUCT = 12

Field = Tuple[int, int, Any]
Struct = List[Field]

def write_varint(n: int) -> bytes:
    if n < 0:
        n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b); break
    return bytes(out)

def zigzag_encode(n: int, bits: int = 64) -> int:
    return (n << 1) ^ (n >> (bits - 1)) & ((1 << bits) - 1) if n < 0 else (n << 1)

def _zz(n: int) -> bytes:
    return write_varint((n << 1) ^ (n >> 63)) if n >= 0 else write_varint((n << 1) ^ (n >> 63) & ((1 << 64) - 1))

class Reader:
    def __init__(self, b: bytes, i: int = 0):
        self.b = b; self.i = i

    def u8(self) -> int:
        v = self.b[self.i]; self.i += 1; return v

    def varint(self) -> int:
        shift = 0; result = 0
        while True:
            x = self.b[self.i]; self.i += 1
            result |= (x & 0x7f) << shift
            if not (x & 0x80):
                return result
            shift += 7

    def zigzag(self) -> int:
        n = self.varint(); return (n >> 1) ^ -(n & 1)

    def binary(self) -> bytes:
        n = self.varint(); v = self.b[self.i:self.i + n]; self.i += n; return v

def decode_struct(r: Reader) -> Struct:
    """Read one struct (until STOP) → list of (fid, ctype, value)."""
    fields: Struct = []
    fid = 0
    while r.i < len(r.b):
        h = r.u8()
        if h == STOP:
            break
        delta = (h >> 4) & 0xf; ctype = h & 0xf
        fid = (fid + delta) if delta else r.zigzag()
        fields.append((fid, ctype, _decode_value(r, ctype)))
    return fields

def _decode_value(r: Reader, ctype: int) -> Any:
    if ctype == BOOL_T:
        return True
    if ctype == BOOL_F:
        return False
    if ctype in (I16, I32, I64):
        return r.zigzag()
    if ctype == I8:
        return r.u8()
    if ctype == BIN:
        return r.binary()
    if ctype == STRUCT:
        return decode_struct(r)
    if ctype in (LIST, SET):
        sh = r.u8(); size = (sh >> 4) & 0xf; et = sh & 0xf
        if size == 15:
            size = r.varint()
        if et in (BOOL_T, BOOL_F):
            return (et, [r.u8() == 0x01 for _ in range(size)])
        return (et, [_decode_value(r, et) for _ in range(size)])
    if ctype == MAP:
        size = r.varint()
        if size == 0:
            return (0, 0, [])
        kv = r.u8(); kt = (kv >> 4) & 0xf; vt = kv & 0xf
        def _el(t):
            return (r.u8() == 0x01) if t in (BOOL_T, BOOL_F) else _decode_value(r, t)
        return (kt, vt, [(_el(kt), _el(vt)) for _ in range(size)])
    if ctype == DOUBLE:
        v = r.b[r.i:r.i + 8]; r.i += 8; return v
    raise ValueError("unhandled ctype 0x%x @ %d" % (ctype, r.i))

def _field_header(delta: int, ctype: int) -> bytes:
    if 1 <= delta <= 15:
        return bytes([(delta << 4) | ctype])
    return bytes([ctype]) + _zz(0 if delta == 0 else delta)

def encode_struct(fields: Struct) -> bytes:
    out = bytearray()
    last = 0
    for fid, ctype, value in fields:
        delta = fid - last
        if 1 <= delta <= 15:
            out.append((delta << 4) | ctype)
        else:
            out.append(ctype); out += _zz(fid)
        last = fid
        out += _encode_value(ctype, value)
    out.append(STOP)
    return bytes(out)

def _encode_value(ctype: int, value: Any) -> bytes:
    if ctype in (BOOL_T, BOOL_F):
        return b''
    if ctype in (I16, I32, I64):
        return _zz(int(value))
    if ctype == I8:
        return bytes([int(value) & 0xff])
    if ctype == BIN:
        v = value if isinstance(value, (bytes, bytearray)) else str(value).encode('utf-8')
        return write_varint(len(v)) + bytes(v)
    if ctype == STRUCT:
        return encode_struct(value)
    if ctype in (LIST, SET):
        et, items = value
        out = bytearray()
        if len(items) < 15:
            out.append((len(items) << 4) | et)
        else:
            out.append(0xf0 | et); out += write_varint(len(items))
        for it in items:
            out += _encode_value(et, it)
        return bytes(out)
    if ctype == MAP:
        kt, vt, pairs = value
        if not pairs:
            return write_varint(0)
        out = bytearray(write_varint(len(pairs))); out.append((kt << 4) | vt)
        for k, v in pairs:
            out += _encode_value(kt, k) + _encode_value(vt, v)
        return bytes(out)
    if ctype == DOUBLE:
        return bytes(value)
    raise ValueError("unhandled ctype 0x%x" % ctype)

def decode_body(b: bytes, i: int = 0) -> List[Struct]:
    """Decode a sequence of top-level structs until bytes are exhausted."""
    r = Reader(b, i); structs = []
    while r.i < len(b):
        structs.append(decode_struct(r))
    return structs

def encode_body(structs: List[Struct]) -> bytes:
    return b''.join(encode_struct(s) for s in structs)
