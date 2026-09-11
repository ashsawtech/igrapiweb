"""rpsignaling call-signaling messages: build offer/ICE frames by template-splice and parse inbound frames."""
from __future__ import annotations
import json, os, re
from typing import Dict, List, Optional
from .thrift import write_varint

_ROOM = re.compile(rb'ROOM:\d+')

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

OFFER_TEMPLATE_OLD = {"room_id": "ROOM:1043081125430369", "session_id": "4240390136",
                      "sender_eimu": "2268686324", "participant_eimu": "17845669236366812"}

def load_offer_template() -> bytes:
    with open(os.path.join(_TEMPLATE_DIR, "offer_send.bin"), "rb") as f:
        return f.read()

def _read_tbinary_at(buf: bytes, hdr_pos: int):
    """Read the Thrift-compact BIN field at hdr_pos → (value_bytes, end_pos, len_start, len_end)."""
    i = hdr_pos + 1

    shift = 0; n = 0; ls = i
    while True:
        x = buf[i]; i += 1
        n |= (x & 0x7f) << shift
        if not (x & 0x80):
            break
        shift += 7
    return buf[i:i + n], i + n, ls, i

def _find_sdp_field(buf: bytes):
    """Locate the SDP BIN field by its ``v=0`` anchor → (hdr_pos, raw_sdp_bytes) or (-1, b'')."""
    v0 = buf.find(b"v=0")
    while v0 != -1:
        for k in (1, 2, 3):
            hdr = v0 - 1 - k
            if hdr < 0:
                break
            if (buf[hdr] & 0x0f) != 0x08:
                continue
            val, end, ls, le = _read_tbinary_at(buf, hdr)
            if le == v0 and buf[v0:v0 + 3] == b"v=0" and val[:3] == b"v=0":
                return hdr, val
        v0 = buf.find(b"v=0", v0 + 1)
    return -1, b""

def _find_bin_field(buf: bytes, value: bytes, search_from: int = 0):
    """Locate the BIN field whose value == `value` → hdr_pos or -1."""
    pos = buf.find(value, search_from)
    while pos != -1:
        lp = pos - 1

        length = len(value)
        exp = write_varint(length)
        if lp - len(exp) + 1 >= 0 and buf[lp - len(exp) + 1:lp + 1] == exp:
            hdr = lp - len(exp)
            if hdr >= 0 and (buf[hdr] & 0x0f) == 0x08:
                return hdr
        pos = buf.find(value, pos + 1)
    return -1

def _splice_bin(buf: bytearray, hdr_pos: int, new_value: bytes):
    """Replace the BIN value at hdr_pos (re-encoding its length varint). Returns new bytearray."""
    _, end, ls, le = _read_tbinary_at(bytes(buf), hdr_pos)
    return buf[:hdr_pos + 1] + bytearray(write_varint(len(new_value))) + bytearray(new_value) + buf[end:]

def _patch_dgw_len(frame: bytearray) -> bytearray:
    body_len = len(frame) - 6
    frame[3] = body_len & 0xff
    frame[4] = (body_len >> 8) & 0xff
    return frame

def template_meta(template: bytes) -> Dict:
    """Extract the template's own identity values (so callers can pass them as the `old_*`)."""
    out = {}
    m = _ROOM.search(template)
    if m:
        out["room_id"] = m.group(0).decode()
    _, sdp = _find_sdp_field(template)
    out["sdp"] = sdp.decode("utf-8", "replace")
    return out

def build_offer_frame(template: bytes, *, room_id: str, sdp: str,
                      old_room_id: str,
                      session_id: Optional[str] = None, old_session_id: Optional[str] = None,
                      sender_eimu: Optional[str] = None, old_sender_eimu: Optional[str] = None,
                      participant_eimu: Optional[str] = None, old_participant_eimu: Optional[str] = None) -> bytes:
    """Build an offer-send rpsignaling frame by splicing this call's SDP + ids into a captured template."""
    buf = bytearray(template)

    hdr, _ = _find_sdp_field(bytes(buf))
    if hdr == -1:
        raise ValueError("template SDP field not found")
    sdp_bytes = sdp if isinstance(sdp, (bytes, bytearray)) else sdp.encode()
    buf = _splice_bin(buf, hdr, bytes(sdp_bytes))

    swaps = [(old_room_id.encode(), room_id.encode())]
    if session_id and old_session_id:
        swaps.append((old_session_id.encode(), session_id.encode()))
    if sender_eimu and old_sender_eimu:
        swaps.append((old_sender_eimu.encode(), sender_eimu.encode()))
    if participant_eimu and old_participant_eimu:
        swaps.append((old_participant_eimu.encode(), participant_eimu.encode()))
    for old, new in swaps:
        if old == new:
            continue
        h = _find_bin_field(bytes(buf), old)
        if h == -1:
            raise ValueError("template field not found: %r" % old[:24])
        buf = _splice_bin(buf, h, new)
    return bytes(_patch_dgw_len(buf))

CAND_TEMPLATE_OLD = {
    "room_id": "ROOM:1451733323514685", "session_id": "2054108283",
    "token": "GANsbGEoEE1ESHBKUEZ0YXhQaWtpR3gW+oz0kICWlAUA", "id9": "3300283498",
    "eimu": "17850823124954628",
    "candidate": "candidate:2405741513 1 udp 2122129151 100.121.181.73 37669 typ host generation 0 ufrag jWkM network-id 2",
}

def load_candidate_template() -> bytes:
    with open(os.path.join(_TEMPLATE_DIR, "candidate_send.bin"), "rb") as f:
        return f.read()

def build_candidate_frame(template: bytes, *, candidate: str, room_id: str, session_id: str,
                          token: str, id9: str, eimu: str, old: Dict = CAND_TEMPLATE_OLD) -> bytes:
    """Splice this call's ids + one ICE candidate line into a captured type-3 template frame."""
    buf = bytearray(template)
    for oldv, newv in [(old["candidate"], candidate), (old["room_id"], room_id),
                       (old["session_id"], session_id), (old["token"], token),
                       (old["id9"], id9), (old["eimu"], eimu)]:
        if not newv or oldv == newv:
            continue
        h = _find_bin_field(bytes(buf), oldv.encode())
        if h == -1:
            raise ValueError("candidate template field not found: %r" % oldv[:24])
        buf = _splice_bin(buf, h, newv.encode() if isinstance(newv, str) else newv)
    return bytes(_patch_dgw_len(buf))

def parse_candidates(frame: bytes) -> List[str]:
    """Pull ICE candidate lines out of an inbound type-3 rpsignaling frame (they are plaintext)."""
    return [m.decode("latin1") for m in re.findall(rb'candidate:[ -~]+', frame)]

def answer_ids(answer_frame: bytes) -> Dict:
    """Extract the ids the SFU echoes in its answer (room/session/token/id9/eimu)."""
    from .thrift import Reader, decode_struct
    out = {}
    m = _ROOM.search(answer_frame)
    if m:
        out["room_id"] = m.group(0).decode()
    body = answer_frame
    i = body.find(b"\x80", 5)
    if i != -1:
        body = body[i + 1:]
    try:
        for fid, ct, val in decode_struct(Reader(body)):
            if fid == 3 and isinstance(val, (bytes, bytearray)):
                out["session_id"] = bytes(val).decode("latin1")
            elif fid == 5 and isinstance(val, (bytes, bytearray)):
                out["token"] = bytes(val).decode("latin1")
            elif fid == 9 and isinstance(val, (bytes, bytearray)):
                out["id9"] = bytes(val).decode("latin1")
            elif fid == 17 and isinstance(val, (bytes, bytearray)):
                out["eimu"] = bytes(val).decode("latin1")
    except Exception:
        pass
    return out

def parse_incoming(frame: bytes) -> Dict:
    """Resilient parse of a received rpsignaling frame → the call fields present (any may be absent)."""
    out: Dict = {}
    m = _ROOM.search(frame)
    if m:
        out["room_id"] = m.group(0).decode()

    text = frame.decode("utf-8", "replace")
    dec = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, end = dec.raw_decode(text, idx)
        except ValueError:
            idx = text.find("{", idx + 1)
            continue
        if isinstance(obj, dict):
            if "display_name" in obj or "ig_thread_id" in obj:
                out["ring_data"] = obj
            elif "peer_id" in obj and "server_info_data" in obj:
                out["collision_context"] = obj
                out.setdefault("server_info_data", obj.get("server_info_data"))
                out.setdefault("peer_id", obj.get("peer_id"))
            idx = text.find("{", end)
        else:
            idx = text.find("{", idx + 1)

    s = frame.find(b"v=0")
    if s != -1:

        seg = frame[s:]

        txt = seg.decode("utf-8", "replace")

        lines = txt.split("\n")
        good = []
        for ln in lines:
            ln = ln.rstrip("\r")
            if ln and (ln[:2] in ("v=", "o=", "s=", "t=", "a=", "m=", "c=", "b=", "i=", "u=", "e=", "p=", "z=", "k=", "r=")):

                good.append("".join(ch for ch in ln if 32 <= ord(ch) < 127))
            elif good:
                break
        if good:
            out["sdp"] = "\r\n".join(good) + "\r\n"
    return out

T6_TEMPLATE_OLD = {"room_id": 'ROOM:1043081125430369', "msg_id": '2212574488425358537', "token": 'GANsbGEoEEFZdXdNeWtVSVRKaXhoVkoWwpGg/6er2gMA', "id9": '1574552042', "eimu": '17850823124954628'}

def load_type6_template() -> bytes:
    with open(os.path.join(_TEMPLATE_DIR, "type6_ack.bin"), "rb") as f:
        return f.read()

def parse_type6(frame: bytes) -> Dict:
    """Extract {room_id, msg_id(f3), token(f5), id9(f9)} from an inbound type-6 SFU ping so we can ACK it."""
    from .thrift import Reader, decode_struct
    out = {}
    m = _ROOM.search(frame)
    if m:
        out["room_id"] = m.group(0).decode()
    body = frame
    i = body.find(b"\x80", 5)
    if i != -1:
        body = body[i + 1:]
    try:
        for fid, ct, val in decode_struct(Reader(body)):
            if fid == 3 and isinstance(val, (bytes, bytearray)):
                out["msg_id"] = bytes(val).decode("latin1")
            elif fid == 5 and isinstance(val, (bytes, bytearray)):
                out["token"] = bytes(val).decode("latin1")
            elif fid == 9 and isinstance(val, (bytes, bytearray)):
                out["id9"] = bytes(val).decode("latin1")
    except Exception:
        pass
    return out

def is_type6(frame: bytes) -> bool:
    b = frame; i = b.find(b"\x80", 5); bb = b[i + 1:] if i != -1 else b
    return len(bb) >= 2 and bb[0] == 0x15 and (((bb[1] >> 1) ^ -(bb[1] & 1)) == 6)

def build_type6_ack(template: bytes, *, room_id: str, msg_id: str, token: str, id9: str, eimu: str,
                    old: Dict = T6_TEMPLATE_OLD) -> bytes:
    """Build our type-6 ACK (f6=200) by echoing the SFU ping's room/msg_id/token/id9 + our eimu."""
    buf = bytearray(template)
    for oldv, newv in [(old["msg_id"], msg_id), (old["room_id"], room_id), (old["token"], token),
                       (old["id9"], id9), (old["eimu"], eimu)]:
        if not newv or oldv == newv:
            continue
        h = _find_bin_field(bytes(buf), oldv.encode())
        if h == -1:
            continue
        buf = _splice_bin(buf, h, newv.encode() if isinstance(newv, str) else newv)
    return bytes(_patch_dgw_len(buf))
