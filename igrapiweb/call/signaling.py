# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
"""rpsignaling DGW channel client: opens the WS channel, sends spliced offer/ICE frames, parses inbound."""
from __future__ import annotations
import json, threading, time, uuid
from typing import Callable, Dict, Optional
from ..protocol import IG_WEB_APP_ID
from ..transport import WSTransport
from . import messages as M

class IGWebCallSignaling:

    RPSIGNALING = ("wss://gateway.instagram.com/ws/rpsignaling"
                   "?x-dgw-appid=%d&x-dgw-appversion=0&x-dgw-authtype=6:0&x-dgw-version=5"
                   "&x-dgw-uuid=%s&x-dgw-tier=prod&x-dgw-loggingid=%s&x-dgw-deviceid=%s"
                   "&x-dgw-app-stream-group=group1")

    def __init__(self, cookies: Dict[str, str], dgw_uuid: str, *, proxy: Optional[str] = None,
                 user_agent: str = "Mozilla/5.0", device_id: Optional[str] = None):
        self.cookies = cookies
        self.dgw_uuid = str(dgw_uuid)
        self.proxy = proxy
        self.user_agent = user_agent
        self.device_id = device_id or str(uuid.uuid4())
        self.transport: Optional[WSTransport] = None
        self._alive = False
        self._seq = 0
        self.on_message: Optional[Callable[[dict, bytes], None]] = None

    @staticmethod
    def _open_frame(stream: int, headers: dict) -> bytes:
        import struct
        body = json.dumps(headers, separators=(",", ":")).encode()
        return bytes([0x0f, stream & 0xFF, 0x00]) + struct.pack("<H", len(body)) + b"\x00" + body

    @staticmethod
    def _ack_for(frame: bytes) -> Optional[bytes]:
        if not frame or frame[0] != 0x0d or len(frame) < 7:
            return None
        stream = frame[1]; seq = frame[6]
        return bytes([0x0c, stream, 0x00, 0x02, 0x00, 0x00, seq, 0x00])

    _PING = bytes([0x09])

    def connect(self, identity: Optional[dict] = None, short_thread: str = "") -> "IGWebCallSignaling":
        """Open the rpsignaling channel (empty ``{}`` OPEN on stream 0; auth rides the sessionid cookie)."""
        url = self.RPSIGNALING % (IG_WEB_APP_ID, self.dgw_uuid, uuid.uuid4(), uuid.uuid4())
        self.transport = WSTransport(url, self.cookies, proxy=self.proxy, user_agent=self.user_agent)
        self.transport.connect()
        self.transport.send(self._open_frame(0, {}))
        self._alive = True
        return self

    def send_offer(self, template: bytes, *, room_id: str, sdp: str, old_room_id: str,
                   **id_swaps) -> None:
        """Send an SDP offer by splicing it into a captured rpsignaling offer template (see messages)."""
        frame = M.build_offer_frame(template, room_id=room_id, sdp=sdp, old_room_id=old_room_id, **id_swaps)
        self.transport.send(frame)
        self._seq += 1

    def send_raw(self, frame: bytes) -> None:
        self.transport.send(frame); self._seq += 1

    def listen(self) -> None:
        """Receive loop: ack every 0x0d frame, parse it, and hand the fields to `on_message`."""
        self.transport.settimeout(None)
        threading.Thread(target=self._ping_loop, daemon=True).start()
        while self._alive:
            try:
                frame = self.transport.recv_raw()
            except Exception:
                self._alive = False
                break
            if frame and frame[0] == 0x09:
                try: self.transport.send(bytes([0x0a]))
                except Exception: pass
                continue
            if not frame or frame[0] != 0x0d:
                continue
            ack = self._ack_for(frame)
            if ack:
                try: self.transport.send(ack)
                except Exception: pass
            try:
                parsed = M.parse_incoming(frame)
            except Exception:
                parsed = {}
            if parsed and self.on_message:
                try: self.on_message(parsed, frame)
                except Exception: pass

    def _ping_loop(self) -> None:
        while self._alive:
            time.sleep(10)
            try: self.transport.send(self._PING)
            except Exception: break

    def disconnect(self) -> None:
        self._alive = False
        try:
            if self.transport: self.transport.close()
        except Exception:
            pass
