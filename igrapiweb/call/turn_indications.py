"""Patch aioice's TURN client to relay media over Send/Data indications; import before any RTCPeerConnection."""
import asyncio
import time
from aioice import stun, turn
from aioice.stun import pack_bytes, unpack_bytes
from aioice.utils import random_transaction_id

PERMISSION_TTL = 240

STATS = {"perm_ok": 0, "perm_fail": 0, "sends": 0, "data_in": 0}

if "DATA" not in stun.ATTRIBUTES_BY_NAME:
    _e = (0x0013, "DATA", pack_bytes, unpack_bytes)
    stun.ATTRIBUTES.append(_e)
    stun.ATTRIBUTES_BY_TYPE[0x0013] = _e
    stun.ATTRIBUTES_BY_NAME["DATA"] = _e

_orig_datagram = turn.TurnClientMixin.datagram_received

_orig_parse = stun.parse_message

def _tolerant_parse(data, integrity_key=None):
    try:
        return _orig_parse(data, integrity_key)
    except Exception:
        import struct
        hl = stun.HEADER_LENGTH
        if len(data) < hl:
            raise
        mtype, length, _cookie, txid = struct.unpack("!HHI12s", data[0:hl])
        if len(data) != hl + length:
            raise
        attrs, pos = {}, hl
        while pos <= len(data) - 4:
            at, al = struct.unpack("!HH", data[pos:pos + 4])
            v = data[pos + 4:pos + 4 + al]
            ent = stun.ATTRIBUTES_BY_TYPE.get(at)
            if ent:
                name, unpk = ent[1], ent[3]
                try:
                    attrs[name] = unpk(v, transaction_id=txid) if unpk is stun.unpack_xor_address else unpk(v)
                except Exception:
                    attrs[name] = v
            pos += 4 + al + stun.padding_length(al)
        return stun.Message(message_method=stun.Method(mtype & 0x3EEF),
                            message_class=stun.Class(mtype & 0x0110),
                            transaction_id=txid, attributes=attrs)

stun.parse_message = _tolerant_parse

async def _ensure_permission(self, addr):
    perms = self.__dict__.setdefault("_ind_perms", {})
    if perms.get(addr, 0.0) > time.time():
        return
    waiters = self.__dict__.setdefault("_ind_perm_wait", {})
    if addr in waiters:
        await waiters[addr]
        return
    fut = asyncio.get_event_loop().create_future()
    waiters[addr] = fut
    try:
        req = stun.Message(message_method=stun.Method.CREATE_PERMISSION,
                           message_class=stun.Class.REQUEST)
        req.attributes["XOR-PEER-ADDRESS"] = addr
        await self.request_with_retry(req)
        perms[addr] = time.time() + PERMISSION_TTL
        STATS["perm_ok"] += 1
    except Exception as _e:
        perms[addr] = time.time() + 5.0
        STATS["perm_fail"] += 1
        STATS.setdefault("perm_err", []).append(repr(_e)[:80])
    finally:
        waiters.pop(addr, None)
        if not fut.done():
            fut.set_result(None)

async def _send_data(self, data, addr):
    await _ensure_permission(self, addr)
    msg = stun.Message(message_method=stun.Method.SEND, message_class=stun.Class.INDICATION,
                       transaction_id=random_transaction_id())
    msg.attributes["XOR-PEER-ADDRESS"] = addr
    msg.attributes["DATA"] = data
    self._send(bytes(msg))
    STATS["sends"] += 1

def _datagram_received(self, data, addr):
    data = bytes(data)
    if len(data) >= 4 and turn.is_channel_data(data):
        return _orig_datagram(self, data, addr)
    try:
        msg = stun.parse_message(data)
    except Exception:
        return
    if msg.message_class == stun.Class.INDICATION and msg.message_method == stun.Method.DATA:
        payload = msg.attributes.get("DATA")
        peer = msg.attributes.get("XOR-PEER-ADDRESS")
        if payload is not None and peer is not None and getattr(self, "receiver", None) is not None:
            STATS["data_in"] += 1
            try:
                inner = stun.parse_message(bytes(payload))
                code = inner.attributes.get("ERROR-CODE")
                STATS.setdefault("in_msgs", []).append(
                    "%s/%s%s" % (inner.message_class.name, inner.message_method.name,
                                 (" err=%r" % (code,)) if code else ""))
            except Exception:
                STATS.setdefault("in_msgs", []).append("non-stun/%d" % len(payload))
                if len(STATS.setdefault("in_hex", [])) < 3:
                    STATS["in_hex"].append(bytes(payload)[:40].hex())
            self.receiver.datagram_received(payload, peer)
        return
    return _orig_datagram(self, data, addr)

turn.TurnClientMixin.send_data = _send_data
turn.TurnClientMixin.datagram_received = _datagram_received

FORCE_RELAY = [False]

def set_relay_only(on: bool = True) -> None:
    FORCE_RELAY[0] = on

try:
    from aiortc import rtcicetransport as _it
    from aioice.ice import TransportPolicy as _TP
    _orig_gatherer_init = _it.RTCIceGatherer.__init__

    def _gatherer_init(self, *a, **k):
        _orig_gatherer_init(self, *a, **k)
        if FORCE_RELAY[0]:
            try:
                self._connection._transport_policy = _TP.RELAY
                STATS["relay_forced"] = STATS.get("relay_forced", 0) + 1
            except Exception as _e:
                STATS["relay_force_err"] = repr(_e)[:80]

    _it.RTCIceGatherer.__init__ = _gatherer_init
except Exception:
    pass

APPLIED = True
