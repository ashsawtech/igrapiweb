from __future__ import annotations
import time, threading
from typing import Any, Dict, List, Optional
from ._common import *
from .handlers.messages import MessagesMixin
from .handlers.groups import GroupsMixin
from .handlers.receipts import ReceiptsMixin
from .handlers.presence import PresenceTypingMixin
from .handlers.realtime import RealtimeMixin
from .handlers.calls import CallsMixin
from .handlers.social import SocialMixin
from .handlers.feed import FeedMixin
from .handlers.stories import StoriesMixin
from .handlers.keepalive import KeepAliveMixin
from .handlers.recovery import RecoveryMixin

class IGWebSocket(MessagesMixin, GroupsMixin, ReceiptsMixin, PresenceTypingMixin, RealtimeMixin, CallsMixin, SocialMixin, FeedMixin, StoriesMixin, KeepAliveMixin, RecoveryMixin):
    """An Instagram Web client: DM receive via DGW lightspeed, DM send via web GraphQL, presence/typing via edge-chat."""
    def __init__(self, cookies: Dict[str, str] = None, web_user_id=None,
                 proxy: Optional[str] = None, save_path: Optional[str] = None, user_agent: Optional[str] = None):

        self.cookies = cookies or {}
        self.web_user_id = web_user_id
        self.proxy = proxy
        self.save_path = save_path
        self.ev = _Emitter()

        self.user = {"id": str(web_user_id or self.cookies.get("ds_user_id") or "")}
        self.user_agent = user_agent or pick_user_agent(self.user["id"] or self.cookies.get("sessionid", "")[:16])
        self.edge = IGWebEdgeChat(cookies, web_user_id, proxy=proxy, ev=self.ev, user_agent=self.user_agent)
        self.dgw = IGWebDGW(cookies, web_user_id, proxy=proxy, ev=self.ev, user_agent=self.user_agent)
        self.dgw_typing = IGWebDGW(cookies, web_user_id, proxy=proxy, ev=self.ev, user_agent=self.user_agent)
        self._threads: List[threading.Thread] = []
        self._seen_items = set()
        self._poll_alive = False
        self._receipt_alive = False
        self._receipt_threads = set()
        self._receipt_state = {}
        self._name_maps = {}
        self._thread_short = {}

        self.default_send = "graphql"
        self._gql_tokens = None
        self._gql_tokens_ts = 0.0
        self._want = {}
        self._pipe_alive = False
        self._dgw_running = False
        self.edge.name_resolver = self._resolve_push_name
        self.dgw.name_resolver = self._resolve_sender

        self.ev.on("messages.upsert", self._track_thread_from_upsert)

    def _member_map(self, thread_id) -> dict:
        """Cached member map for a thread, keyed by both pk and eimu → {name,nickname,full_name,username}."""
        tid = str(thread_id or "")
        if tid and tid not in self._name_maps:
            try: self._name_maps[tid] = thread_members(self.cookies, tid, proxy=self.proxy)
            except Exception: self._name_maps[tid] = {}
        return self._name_maps.get(tid) or {}

    def _resolve_push_name(self, user_id, thread_id) -> Optional[str]:
        """Resolve a sender id (pk or eimu) to a display name for `pushName`; self → 'You'."""
        nm = (self._member_map(thread_id).get(str(user_id)) or {}).get("name")
        if not nm and str(user_id) == str(self.web_user_id):
            nm = "You"
        return nm

    def _resolve_sender(self, user_id, thread_id) -> dict:
        """Resolve a sender id (pk or eimu) to rich identity {name,nickname,full_name,username} for group messages."""
        info = self._member_map(thread_id).get(str(user_id))
        if info:
            return {"pushName": info.get("name"), "pushNickname": info.get("nickname"),
                    "pushFullName": info.get("full_name"), "pushUsername": info.get("username")}
        if str(user_id) == str(self.web_user_id):
            return {"pushName": "You"}
        return {}

    def refresh_names(self, thread_id) -> dict:
        """Force-refresh the member/pushName map for a thread."""
        self._name_maps[str(thread_id)] = thread_members(self.cookies, str(thread_id), proxy=self.proxy)
        return self._name_maps[str(thread_id)]

    def _track_thread_from_upsert(self, m) -> None:
        for wa in (m.get("messages") or []):
            key = wa.get("key") or {}
            jid = key.get("remoteJid")
            if jid:
                self._receipt_threads.add(str(jid))
            iid = key.get("id")
            if iid:
                self._seen_items.add(str(iid))

    def _spawn(self, fn):
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        self._threads.append(t)
        return t

    def _short_thread_id(self, thread_id) -> str:
        """Return the short thread_v2 id, resolving (and caching) a 128-bit `/direct/t/` id when needed."""
        s = str(thread_id)
        if len(s) < 25 or not s.isdigit():
            return s
        if s not in self._thread_short:
            self._thread_short[s] = thread_v2_id_from_web(self.cookies, s, proxy=self.proxy) or s
        return self._thread_short[s]

    def _gql_token_bundle(self, force: bool = False) -> dict:
        """Cached GraphQL token bundle for the web send path, re-scraped after ~8 min or on `force`."""
        if force or not self._gql_tokens or (time.time() - self._gql_tokens_ts) > 480:
            self._gql_tokens = web_graphql_scrape_tokens(self.cookies, proxy=self.proxy, user_agent=self.user_agent)
            self._gql_tokens_ts = time.time()
        return self._gql_tokens

    def connect(self, presence: bool = True, message_sync: Optional[bool] = None,
                dm_realtime: bool = False, dm_receive: str = "dgw",
                thread_id=None, send: Optional[str] = None, keep_alive: bool = True) -> "IGWebSocket":
        """Bring up realtime as persistent pipes (DGW-lightspeed receive + edge-chat send/presence); a watchdog re-opens dropped pipes. dm_receive=dgw|iris|both, send=ws|graphql."""
        if send:
            self.default_send = send
        if message_sync is None:
            message_sync = dm_receive in ("iris", "both")
        self._want = {"presence": presence, "message_sync": message_sync,
                      "use_dgw": dm_receive in ("dgw", "both"), "thread_id": thread_id,
                      "dm_realtime": dm_realtime}
        self.ev.emit("connection.update", {"connection": "connecting"})
        self._open_pipes()
        if keep_alive:
            self._spawn(self._keepalive_loop)
        self.ev.emit("connection.update", {"connection": "open"})
        self.ev.emit("creds.update", {"user": self.user})
        return self

    def _open_pipes(self) -> None:
        """Open (or re-open) the edge-chat send/presence pipe and the DGW receive pipe per `self._want`."""
        w = self._want
        self.edge.connect()
        if w["presence"]:
            self.edge.subscribe("/pubsub")
        if w["message_sync"]:
            self._start_iris()
        self._spawn(self.edge.listen)
        if w["use_dgw"] and not getattr(self, "_dgw_running", False):
            self._dgw_running = True
            self.start_dm_realtime(thread_id=w["thread_id"])
        if w["dm_realtime"]:

            self._dgw_direct = IGWebDGW(self.cookies, self.web_user_id, proxy=self.proxy, ev=self.ev,
                                        user_agent=self.user_agent)
            self._dgw_direct.name_resolver = self._resolve_sender
            self._spawn(self._dgw_direct.run_forever)

    def _start_iris(self) -> None:
        """Subscribe to iris message-sync and register the inbox cursor; falls back to REST polling on failure."""
        try:
            self.edge.subscribe_message_sync()
            seq_id, snap = iris_cursor_from_web_inbox(self.cookies, proxy=self.proxy)
            if seq_id is not None and snap is not None:
                self.edge.iris_subscribe(seq_id, snap)
                self.ev.emit("iris.status", {"subscribed": True, "seq_id": seq_id})
            else:
                self.ev.emit("iris.status", {"subscribed": False, "reason": "no cursor"})
        except Exception as e:
            self.ev.emit("iris.status", {"subscribed": False, "error": repr(e)})

    def listen(self) -> None:
        try:
            while any(t.is_alive() for t in self._threads):
                time.sleep(1)
        except KeyboardInterrupt:
            self.disconnect()

    def disconnect(self) -> None:
        self._poll_alive = False
        self._receipt_alive = False
        self._reconcile_alive = False
        self._pipe_alive = False
        try:
            self.edge.disconnect()
        except Exception:
            pass
        for d in (self.dgw, getattr(self, "dgw_typing", None), getattr(self, "_dgw_direct", None)):
            if d:
                try: d.stop()
                except Exception: pass
        self.ev.emit("connection.update", {"connection": "close"})

    def save(self, path: Optional[str] = None) -> None:
        self.save_state(path)

    def end(self) -> None:
        self.disconnect()

    def logout(self) -> Any:
        self.disconnect()
        return None

    @staticmethod
    def _wa_message(thread=None, item=None, event=None) -> dict:
        """Normalize a DM into {key:{remoteJid,id,fromMe}, message, _raw}."""
        key = {"fromMe": False}
        tid = (getattr(thread, "id", None) or (thread.get("thread_id") if isinstance(thread, dict) else None)) if thread is not None else None
        iid = (getattr(item, "id", None) or (item.get("item_id") if isinstance(item, dict) else None)) if item is not None else None
        if tid:
            key["remoteJid"] = str(tid)
        if iid:
            key["id"] = str(iid)
        return {"key": key, "message": item if item is not None else event, "_raw": {"thread": thread, "item": item, "event": event}}

IGWebSocket.sendMessage = IGWebSocket.send_message
IGWebSocket.readMessages = IGWebSocket.read_messages
IGWebSocket.sendPresenceUpdate = IGWebSocket.send_presence_update
IGWebSocket.presenceSubscribe = IGWebSocket.presence_subscribe

def make_ig_web_socket(*, sessionid: Optional[str] = None, cookies: Optional[dict] = None,
                       web_user_id=None, csrftoken: str = "",
                       proxy: Optional[str] = None, save_path: Optional[str] = None,
                       username: Optional[str] = None, password: Optional[str] = None,
                       user_agent: Optional[str] = None) -> IGWebSocket:
    """Build an :class:`IGWebSocket` from a web session: pass one of `sessionid`, `cookies`, or `username`+`password`."""
    if not cookies and sessionid:
        cookies = cookies_from_sessionid(sessionid, csrftoken)

    if not cookies and username and password:
        boot = IGWebSocket({}, web_user_id, proxy=proxy, save_path=save_path, user_agent=user_agent)
        boot.set_credentials(username, password)
        if boot.auto_login().get("ok"):
            return boot
        raise ValueError("credential login failed (2FA/checkpoint?) — set a resolver or pass a sessionid")
    if not cookies:
        raise ValueError("make_ig_web_socket needs `sessionid`, `cookies`, or username+password")
    if not web_user_id:
        web_user_id = cookies.get("ds_user_id")
    sock = IGWebSocket(cookies, web_user_id, proxy=proxy, save_path=save_path, user_agent=user_agent)
    if username and password:
        sock.set_credentials(username, password)
    return sock
