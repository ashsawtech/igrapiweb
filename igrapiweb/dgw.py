# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import json, struct, threading, time, uuid
from typing import Callable, Dict, Optional
from .protocol import _UA, IG_WEB_APP_ID
from .transport import WSTransport
from .emitter import _Emitter
from .parsers import _scrape_json_objects, _dgw_direct_to_wa, _dgw_lightspeed_to_wa

class IGWebDGW:
    """Meta DGW streamcontroller client for the DM realtime GraphQL subscription (subscribe replays a captured handshake; receive is a frame-agnostic brace-scan)."""

    _DATA = None

    def __init__(self, cookies: Dict[str, str], web_user_id, proxy: Optional[str] = None,
                 user_agent: str = _UA, ev: Optional[_Emitter] = None):
        self.cookies = cookies
        self.web_user_id = web_user_id
        self.proxy = proxy
        self.user_agent = user_agent
        self.ev = ev or _Emitter()
        self.device_id = str(uuid.uuid4())
        self.dgw_uuid = str(web_user_id)
        self._rt: Optional[WSTransport] = None
        self._rt_alive = False
        self.transport: Optional[WSTransport] = None
        self._alive = False
        self._stop = False
        self.raw_hook: Optional[Callable[[bytes], None]] = None

        self.name_resolver: Optional[Callable[[str, str], dict]] = None

    @classmethod
    def _frames(cls) -> dict:
        if cls._DATA is None:
            import os
            p = os.path.join(os.path.dirname(__file__), "data", "dgw_web_sub.json")
            try:
                cls._DATA = json.load(open(p))
            except Exception:
                cls._DATA = {}
        return cls._DATA

    def _url(self) -> str:
        return ("wss://gateway.instagram.com/ws/streamcontroller"
                "?x-dgw-appid=%d&x-dgw-appversion=0&x-dgw-authtype=6:0&x-dgw-version=5"
                "&x-dgw-uuid=%s&x-dgw-tier=prod&x-dgw-deviceid=%s&x-dgw-app-stream-group=group1"
                % (IG_WEB_APP_ID, self.web_user_id, self.device_id))

    def connect(self) -> "IGWebDGW":
        self.transport = WSTransport(self._url(), self.cookies, proxy=self.proxy, user_agent=self.user_agent)
        self.transport.connect()

        try:
            self.transport.settimeout(8)
            self.transport.recv_raw()
        except Exception:
            pass
        self._alive = True
        self.ev.emit("connection.update", {"channel": "dgw", "connection": "open"})
        return self

    _PING = bytes([0x09])

    def subscribe_direct(self) -> None:
        """Replay the ordered DGW subscribe handshake (method frames + bodies) to start the direct-event stream."""
        import base64 as _b
        for fr in self._frames().get("handshake", []):
            try:
                self.transport.send(_b.b64decode(fr["b64"]))
                time.sleep(0.35)
            except Exception:
                break

    def _keepalive(self, sock=None):

        sock = sock or self.transport
        while self._alive and self.transport is sock:
            time.sleep(10)
            try:
                sock.send(self._PING)
            except Exception:
                break

    STREAM_DIRECT = 1
    STREAM_PRESENCE = 2

    def _ack_for(self, frame: bytes) -> Optional[bytes]:
        """Build the DGW data-ack (0x0c) for a 0x0d data frame, echoing its stream and seq."""
        if len(frame) < 7 or frame[0] != 0x0d:
            return None
        return bytes([0x0c, frame[1], 0x00, 0x02, 0x00, 0x00, frame[6], 0x00])

    def listen(self) -> None:
        self.transport.settimeout(None)
        threading.Thread(target=self._keepalive, args=(self.transport,), daemon=True).start()
        while self._alive:
            try:
                frame = self.transport.recv_raw()
            except Exception as e:
                self._alive = False
                self.ev.emit("connection.update", {"channel": "dgw", "connection": "close", "error": repr(e)})
                break
            op = frame[0] if frame else 0
            if self.raw_hook:
                try: self.raw_hook(frame)
                except Exception: pass
            if op == 0x0d:
                stream = frame[1] if len(frame) > 1 else -1
                ack = self._ack_for(frame)
                if ack:
                    try: self.transport.send(ack)
                    except Exception: pass
                objs = _scrape_json_objects(frame)
                for obj in objs:
                    if obj.get("resumed") or obj.get("code") in (200,):
                        continue
                    if stream == self.STREAM_DIRECT:
                        for wa in _dgw_direct_to_wa(obj):
                            self.ev.emit(wa["_event"],
                                         {"messages": [wa["msg"]], "type": "notify", "source": "dgw"}
                                         if wa["_event"] == "messages.upsert"
                                         else wa["payload"])
                    elif stream == self.STREAM_PRESENCE:
                        self.ev.emit("presence.update", {"source": "dgw", "payload": obj})
                    else:
                        self.ev.emit("dgw.status", {"stream": stream, "payload": obj})

    UQPP_SYNC_DOC_ID = "27931342966497053"

    def _url_lightspeed(self) -> str:
        return ("wss://gateway.instagram.com/ws/lightspeed"
                "?x-dgw-appid=%d&x-dgw-appversion=0&x-dgw-authtype=6:0&x-dgw-version=5"
                "&x-dgw-uuid=%s&x-dgw-tier=prod&x-dgw-deviceid=%s&x-dgw-app-stream-group=group1"
                % (IG_WEB_APP_ID, self.dgw_uuid, uuid.uuid4()))

    @staticmethod
    def _dgw_data_frame(stream: int, body: bytes, seq: int = 0) -> bytes:
        """Build a DGW `0d` data send frame wrapping `body`, with the per-stream send_seq byte."""
        payload = bytes([seq & 0xFF]) + b"\x80" + body
        return bytes([0x0d, stream & 0xFF, 0x00]) + struct.pack("<H", len(payload)) + b"\x00" + payload

    @staticmethod
    def _dgw_open_frame(stream: int, headers: dict) -> bytes:
        """Build a DGW `0f` open send frame carrying `headers` as JSON."""
        body = json.dumps(headers, separators=(",", ":")).encode()
        return bytes([0x0f, stream & 0xFF, 0x00]) + struct.pack("<H", len(body)) + b"\x00" + body

    def connect_lightspeed(self, seq_id, snapshot_at_ms) -> "IGWebDGW":
        """Open the lightspeed DM channel and send the UQPP sync subscription (seq_id/snapshot from the web inbox cursor)."""
        old = getattr(self, "transport", None)
        if old:
            try: old.close()
            except Exception: pass
        self.transport = WSTransport(self._url_lightspeed(), self.cookies, proxy=self.proxy,
                                     user_agent=self.user_agent)
        self.transport.connect()
        inner = {"database": 223, "epoch_id": 0, "failure_count": 0,
                 "last_applied_cursor": json.dumps({"seq_id": int(seq_id or 0)}, separators=(",", ":")),
                 "sync_params": json.dumps({"user_agent": "WMI Web",
                                            "snapshot_at_ms": int(snapshot_at_ms or 0),
                                            "prevalidated_graphql_doc_id": self.UQPP_SYNC_DOC_ID},
                                           separators=(",", ":")),
                 "version": -3}
        body = {"app_id": str(IG_WEB_APP_ID), "device_id": self.device_id,
                "payload": json.dumps(inner, separators=(",", ":")), "request_id": 4, "type": 2}

        frame = self._dgw_open_frame(0, {}) + self._dgw_data_frame(0, json.dumps(body, separators=(",", ":")).encode())
        self.transport.send(frame)
        self._alive = True
        self.ev.emit("connection.update", {"channel": "dgw-lightspeed", "connection": "open"})
        return self

    def _url_realtime(self) -> str:
        return ("wss://gateway.instagram.com/ws/realtime"
                "?x-dgw-appid=%d&x-dgw-appversion=0&x-dgw-authtype=6:0&x-dgw-version=5"
                "&x-dgw-uuid=%s&x-dgw-tier=prod&x-dgw-deviceid=%s&x-dgw-app-stream-group=group1"
                % (IG_WEB_APP_ID, self.dgw_uuid, uuid.uuid4()))

    def connect_realtime(self, identity: dict, referer: str) -> None:
        """Open and authenticate the DGW realtime channel (Falco); runs its own ack/ping loop in a background thread."""
        old_rt = getattr(self, "_rt", None)
        if old_rt:
            try: old_rt.close()
            except Exception: pass
        self._rt = WSTransport(self._url_realtime(), self.cookies, proxy=self.proxy, user_agent=self.user_agent)
        self._rt.connect()
        headers = {"x-dgw-app-XRSS-method": "Falco", "x-dgw-app-xrs-body": "true",
                   "x-dgw-app-XRS-Accept-Ack": "RSAck", "x-dgw-app-XRSS-http_referer": referer}
        body = {"deviceId": self.device_id, "familyDeviceId": None, "osBuildNumber": None,
                "sessionId": str(uuid.uuid4()), "appId": str(IG_WEB_APP_ID), "appVersion": "1.0.0",
                "bundleId": None, "consentState": None,
                "identity": {"appScopedIdentity": {"uid": str(identity.get("appScopedIdentity")),
                                                   "identifier": str(identity.get("appScopedIdentity")),
                                                   "claims": [identity.get("claim")]}},
                "pushPhase": "C3", "ambientState": identity.get("ambientState")}
        frame = self._dgw_open_frame(0, headers) + \
            self._dgw_data_frame(0, json.dumps(body, separators=(",", ":")).encode())
        self._rt.send(frame)
        self._rt_alive = True
        rt = self._rt

        def _rt_loop():
            rt.settimeout(None)
            while self._rt_alive and self._rt is rt:
                try:
                    fr = rt.recv_raw()
                except Exception:
                    break
                if fr and fr[0] == 0x0d:
                    a = self._ack_for(fr)
                    if a:
                        try: rt.send(a)
                        except Exception: break

        def _rt_ping():
            while self._rt_alive and self._rt is rt:
                time.sleep(10)
                try: rt.send(self._PING)
                except Exception: break
        threading.Thread(target=_rt_loop, daemon=True).start()
        threading.Thread(target=_rt_ping, daemon=True).start()

    def connect_dm(self, seq_id, snapshot_at_ms, identity: dict, referer: str) -> "IGWebDGW":
        """DM receive: authenticate realtime (Falco), then open lightspeed with the UQPP sync."""
        if identity.get("fbid"):
            self.dgw_uuid = str(identity["fbid"])
        self.connect_realtime(identity, referer)
        time.sleep(0.5)
        self.connect_lightspeed(seq_id, snapshot_at_ms)
        return self

    def listen_lightspeed(self) -> None:
        """Receive DM deltas on lightspeed, acking every `0d` frame; emits messages.upsert / reaction / receipt updates."""
        self.transport.settimeout(None)
        threading.Thread(target=self._keepalive, args=(self.transport,), daemon=True).start()
        while self._alive:
            try:
                frame = self.transport.recv_raw()
            except Exception as e:
                self._alive = False
                self.ev.emit("connection.update",
                             {"channel": "dgw-lightspeed", "connection": "close", "error": repr(e)})
                break
            if self.raw_hook:
                try: self.raw_hook(frame)
                except Exception: pass
            if not frame or frame[0] != 0x0d:
                continue
            ack = self._ack_for(frame)
            if ack:
                try: self.transport.send(ack)
                except Exception: pass
            for wa in _dgw_lightspeed_to_wa(frame, self_id=str(self.web_user_id)):
                ev = wa["_event"]
                if ev == "messages.upsert":
                    self._attach_sender(wa["msg"])
                    self.ev.emit(ev, {"messages": [wa["msg"]], "type": "notify", "source": "dgw-lightspeed"})
                else:
                    self.ev.emit(ev, wa["payload"])

    def _attach_sender(self, wa_msg: dict) -> None:
        """Attach the sender (key.participant = sender_fbid, an eimu) and resolved push names to a DGW upsert."""
        try:
            key = wa_msg.get("key", {}); body = wa_msg.get("message", {}) or {}
            sender = str(body.get("sender_fbid") or body.get("user_id") or "") or None
            if not sender:
                return
            key["participant"] = sender
            if self.name_resolver:
                info = self.name_resolver(sender, key.get("remoteJid")) or {}
                for k, v in info.items():
                    if v:
                        key[k] = v
        except Exception:
            pass

    TYPING_SUB_DOC_ID = "27868809652705105"

    def _url_streamcontroller(self) -> str:
        return ("wss://gateway.instagram.com/ws/streamcontroller"
                "?x-dgw-appid=%d&x-dgw-appversion=0&x-dgw-authtype=6:0&x-dgw-version=5"
                "&x-dgw-uuid=%s&x-dgw-tier=prod&x-dgw-deviceid=%s&x-dgw-app-stream-group=group1"
                % (IG_WEB_APP_ID, self.dgw_uuid, uuid.uuid4()))

    def connect_typing(self, referer: str) -> "IGWebDGW":
        """Open streamcontroller and subscribe XDT_DIRECT_REALTIME_EVENT (typing indicator); then call listen_typing()."""
        self.transport = WSTransport(self._url_streamcontroller(), self.cookies, proxy=self.proxy,
                                     user_agent=self.user_agent)
        self.transport.connect()
        headers = {"x-dgw-app-XRSS-method": "FBGQLS:XDT_DIRECT_REALTIME_EVENT",
                   "x-dgw-app-XRSS-doc_id": self.TYPING_SUB_DOC_ID,
                   "x-dgw-app-XRSS-routing_hint": "IGDTypingIndicatorClientSubscription",
                   "x-dgw-app-xrs-body": "true", "x-dgw-app-XRS-Accept-Ack": "RSAck",
                   "x-dgw-app-XRSS-http_referer": referer}
        body = {"input_data": {"user_id": str(self.web_user_id)},
                "%options": {"useOSSResponseFormat": True, "client_has_ods_usecase_counters": True}}
        frame = self._dgw_open_frame(0, headers) + \
            self._dgw_data_frame(0, json.dumps(body, separators=(",", ":")).encode())
        self.transport.send(frame)
        self._alive = True
        self.ev.emit("connection.update", {"channel": "dgw-streamcontroller", "connection": "open"})
        return self

    def listen_typing(self) -> None:
        """Receive typing deltas on streamcontroller, acking each `0d`; emits presence.update (composing|paused)."""
        self.transport.settimeout(None)
        threading.Thread(target=self._keepalive, args=(self.transport,), daemon=True).start()
        while self._alive:
            try:
                frame = self.transport.recv_raw()
            except Exception as e:
                self._alive = False
                self.ev.emit("connection.update",
                             {"channel": "dgw-streamcontroller", "connection": "close", "error": repr(e)})
                break
            if self.raw_hook:
                try: self.raw_hook(frame)
                except Exception: pass
            if not frame or frame[0] != 0x0d:
                continue
            ack = self._ack_for(frame)
            if ack:
                try: self.transport.send(ack)
                except Exception: pass
            for obj in _scrape_json_objects(frame):
                if obj.get("resumed") or obj.get("code") in (200,):
                    continue
                for wa in _dgw_direct_to_wa(obj, self_id=str(self.web_user_id)):
                    self.ev.emit(wa["_event"],
                                 {"messages": [wa["msg"]], "type": "notify", "source": "dgw"}
                                 if wa["_event"] == "messages.upsert" else wa["payload"])

    def run_typing(self, referer: str, reconnect_delay: float = 3.0,
                   referer_refresh: Optional[Callable[[], str]] = None) -> None:
        """Connect → subscribe → listen for typing on streamcontroller, reconnecting on drop."""
        self._stop = False
        while not self._stop:
            try:
                if referer_refresh:
                    try: referer = referer_refresh()
                    except Exception: pass
                self.connect_typing(referer)
                self.listen_typing()
            except Exception as e:
                self.ev.emit("connection.update",
                             {"channel": "dgw-streamcontroller", "connection": "close", "error": repr(e)})
            if self._stop:
                break
            time.sleep(reconnect_delay)

    def run_lightspeed(self, seq_id, snapshot_at_ms, reconnect_delay: float = 3.0,
                       cursor_refresh: Optional[Callable[[], tuple]] = None,
                       identity_refresh: Optional[Callable[[], tuple]] = None) -> None:
        """Authenticate realtime + subscribe lightspeed + listen, reconnecting on drop; refreshers keep the hmac_ttl claim and cursor fresh."""
        self._stop = False
        identity, referer = None, None
        while not self._stop:
            try:
                if cursor_refresh:
                    try: seq_id, snapshot_at_ms = cursor_refresh()
                    except Exception: pass
                if identity_refresh:
                    try: identity, referer = identity_refresh()
                    except Exception: pass
                if identity:
                    self.connect_dm(seq_id, snapshot_at_ms, identity, referer)
                else:
                    self.connect_lightspeed(seq_id, snapshot_at_ms)
                self.listen_lightspeed()
            except Exception as e:
                self.ev.emit("connection.update",
                             {"channel": "dgw-lightspeed", "connection": "close", "error": repr(e)})
            if self._stop:
                break
            time.sleep(reconnect_delay)

    def run_forever(self, reconnect_delay: float = 3.0) -> None:
        """Connect → subscribe → listen, auto-reconnecting on drop; stop with .stop()."""
        self._stop = False
        while not self._stop:
            try:
                self.connect()
                self.subscribe_direct()
                self.listen()
            except Exception as e:
                self.ev.emit("connection.update", {"channel": "dgw", "connection": "close", "error": repr(e)})
            if self._stop:
                break
            time.sleep(reconnect_delay)

    def stop(self) -> None:
        self._stop = True
        self.disconnect()

    def disconnect(self) -> None:
        self._alive = False
        self._rt_alive = False
        for t in (self.transport, getattr(self, "_rt", None)):
            if t:
                try: t.close()
                except Exception: pass
