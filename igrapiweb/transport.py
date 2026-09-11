# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import threading
from typing import Dict, List, Optional
from urllib.parse import urlsplit
from .protocol import _UA

class WSTransport:
    def __init__(self, url: str, cookies: Dict[str, str], proxy: Optional[str] = None,
                 origin: str = "https://www.instagram.com", user_agent: str = _UA, timeout: float = 30.0,
                 extra_headers: Optional[List[str]] = None):
        self.url = url
        self.cookies = cookies or {}
        self.proxy = proxy
        self.origin = origin
        self.user_agent = user_agent
        self.timeout = timeout
        self.extra_headers = extra_headers or []
        self.ws = None
        self._buf = bytearray()
        self._send_lock = threading.Lock()

    def connect(self) -> None:
        import websocket
        cookie_hdr = "; ".join("%s=%s" % (k, v) for k, v in self.cookies.items() if v)
        kw = dict(header=["User-Agent: " + self.user_agent] + self.extra_headers,
                  cookie=cookie_hdr, origin=self.origin, timeout=self.timeout)
        if self.proxy:
            p = urlsplit(self.proxy if "://" in self.proxy else "http://" + self.proxy)
            kw["http_proxy_host"] = p.hostname
            kw["http_proxy_port"] = p.port
            kw["proxy_type"] = p.scheme if p.scheme in ("http", "socks4", "socks5", "socks5h") else "http"
            if p.username:
                from urllib.parse import unquote
                kw["http_proxy_auth"] = (unquote(p.username), unquote(p.password or ""))
        self.ws = websocket.create_connection(self.url, **kw)

    def send(self, data: bytes) -> None:
        import websocket
        with self._send_lock:
            self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)

    def recv_raw(self) -> bytes:
        """One raw WS binary message (used by the DGW channel, where 1 WS msg ≈ 1 DGW frame)."""
        frame = self.ws.recv()
        if frame is None or frame == b"" or frame == "":
            raise ConnectionError("ws closed")
        return frame if isinstance(frame, (bytes, bytearray)) else frame.encode("latin1", "ignore")

    def recv_mqtt(self) -> bytes:
        """Return one full MQTT control packet (framed by remaining-length), buffering WS frames."""
        while True:
            pkt = self._extract()
            if pkt is not None:
                return pkt
            frame = self.ws.recv()
            if frame is None or frame == b"" or frame == "":
                raise ConnectionError("ws closed")
            if isinstance(frame, str):
                frame = frame.encode("latin1", "ignore")
            self._buf.extend(frame)

    def _extract(self) -> Optional[bytes]:
        if len(self._buf) < 2:
            return None
        mult, val, i = 1, 0, 1
        while True:
            if i >= len(self._buf):
                return None
            b = self._buf[i]; val += (b & 0x7F) * mult; i += 1
            if not (b & 0x80):
                break
            mult *= 128
        total = i + val
        if len(self._buf) < total:
            return None
        pkt = bytes(self._buf[:total]); del self._buf[:total]
        return pkt

    def settimeout(self, t):
        if self.ws:
            self.ws.settimeout(t)

    def close(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            finally:
                self.ws = None

