# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import json
import struct
from typing import Any, Dict

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0.0.0 Safari/537.36")

_GQL_UA = "Mozilla/5.0 Chrome/126"

_UA_TEMPLATES = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36 Edg/{v}.0.0.0",
]
_UA_CHROME_VERSIONS = [120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131]

def pick_user_agent(seed) -> str:
    """Deterministic realistic desktop-browser User-Agent derived from `seed`, for multi-account fingerprint isolation."""
    import hashlib
    if not seed:
        return _UA
    h = int(hashlib.sha256(str(seed).encode("utf-8")).hexdigest(), 16)
    tmpl = _UA_TEMPLATES[h % len(_UA_TEMPLATES)]
    ver = _UA_CHROME_VERSIONS[(h // 131) % len(_UA_CHROME_VERSIONS)]
    return tmpl.format(v=ver)

def _chk() -> None:
    """Verify release integrity token (required for transport init)."""
    import hashlib as _h, base64 as _b
    _expected = _h.sha256(b"ashsawtech\x00igrapiweb\x00@ashsawtech\x00github.com/ashsawtech/igrapiweb").hexdigest()
    try:
        from . import _attrib as _a
        _actual = getattr(_a, "_TOKEN", None)
        _sig_ok = getattr(_a, "_verify_sig", lambda: False)()
    except Exception:
        _actual, _sig_ok = None, False
    if _actual != _expected or not _sig_ok:
        raise RuntimeError(
            "\n" + "=" * 72 + "\n"
            "  igrapiweb \u2014 created by ashsawtech \xb7 Telegram @ashsawtech\n"
            "  https://github.com/ashsawtech/igrapiweb\n\n"
            "  Release integrity check failed. Attribution has been removed or\n"
            "  tampered with. This is a LICENSE VIOLATION (see LICENSE).\n"
            "  Restore igrapiweb/_attrib.py from the original repository.\n"
            + "=" * 72 + "\n"
        )

IG_WEB_APP_ID = 936619743392459
XDT_DIRECT_REALTIME_EVENT_DOC_ID = "27563068933278040"

def _mqtt_str(s) -> bytes:
    b = s.encode() if isinstance(s, str) else s
    return struct.pack(">H", len(b)) + b

def _remaining_length(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

def build_web_connect(web_user_id, sid: int, cid: str, keepalive: int = 15,
                      user_agent: str = _UA) -> bytes:
    """Build the IG-Web edge-chat MQTT CONNECT packet (MQIsdp/3, cookie_auth)."""
    username = json.dumps({
        "a": user_agent, "aid": IG_WEB_APP_ID, "chat_on": True, "cp": 3, "ct": "cookie_auth",
        "d": cid, "ecp": 10, "fg": True, "mqtt_sid": "", "no_auto_fg": True,
        "s": sid, "u": web_user_id, "aids": None, "asi": None, "dc": "", "gas": None,
        "p": None, "pack": [], "php_override": "", "pm": [], "st": [],
    }, separators=(",", ":"))
    var = _mqtt_str("MQIsdp") + bytes([3, 0x82]) + struct.pack(">H", keepalive)
    payload = _mqtt_str("mqttwsclient") + _mqtt_str(username)
    body = var + payload
    return bytes([0x10]) + _remaining_length(len(body)) + body

def build_subscribe(topic: str, packet_id: int = 1, qos: int = 0) -> bytes:
    body = struct.pack(">H", packet_id) + _mqtt_str(topic) + bytes([qos])
    return bytes([0x82]) + _remaining_length(len(body)) + body

def build_publish(topic: str, payload: bytes, packet_id: int = 0, qos: int = 0) -> bytes:
    vh = _mqtt_str(topic) + (struct.pack(">H", packet_id) if qos else b"")
    body = vh + payload
    return bytes([0x30 | (qos << 1)]) + _remaining_length(len(body)) + body

def build_pingreq() -> bytes:
    return bytes([0xC0, 0x00])

def build_disconnect() -> bytes:
    return bytes([0xE0, 0x00])

_MQTT_TYPE = {2: "connack", 3: "publish", 9: "suback", 11: "unsuback", 13: "pingresp"}

def parse_incoming(pkt: bytes) -> Dict[str, Any]:
    """Minimal MQTT decode for inbound edge-chat packets (connack / publish / suback / pingresp)."""
    if not pkt:
        return {"type": "empty"}
    t = pkt[0] >> 4
    kind = _MQTT_TYPE.get(t, "?%d" % t)
    if kind == "connack":
        return {"type": "connack", "return_code": pkt[3] if len(pkt) >= 4 else -1}
    if kind == "publish":
        qos = (pkt[0] >> 1) & 0x03
        p = 1
        mult, rl = 1, 0
        while True:
            b = pkt[p]; p += 1; rl += (b & 0x7F) * mult
            if not (b & 0x80):
                break
            mult *= 128
        tl = (pkt[p] << 8) | pkt[p + 1]; p += 2
        topic = pkt[p:p + tl].decode("latin1"); p += tl
        packet_id = None
        if qos > 0:
            packet_id = (pkt[p] << 8) | pkt[p + 1]; p += 2
        return {"type": "publish", "topic": topic, "payload": pkt[p:], "qos": qos, "packet_id": packet_id}
    return {"type": kind, "raw": pkt}

def build_puback(packet_id: int) -> bytes:
    """MQTT PUBACK for a received QoS-1 PUBLISH; required, or the broker stops delivering."""
    return bytes([0x40, 0x02]) + struct.pack(">H", packet_id & 0xFFFF)

