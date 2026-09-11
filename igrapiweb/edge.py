# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import json, threading, time, uuid
from typing import Any, Callable, Dict, Optional
from .protocol import (_UA, build_web_connect, build_subscribe, build_publish, 
                       build_pingreq, build_disconnect, parse_incoming, build_puback)
from .transport import WSTransport
from .emitter import _Emitter
from .parsers import _message_sync_to_wa

class IGWebEdgeChat:
    """MQTT-over-WS client for edge-chat.instagram.com (the simple /pubsub skywalker channel)."""

    def __init__(self, cookies: Dict[str, str], web_user_id, proxy: Optional[str] = None,
                 user_agent: str = _UA, ev: Optional[_Emitter] = None):
        self.cookies = cookies
        self.web_user_id = web_user_id
        self.proxy = proxy
        self.user_agent = user_agent
        self.ev = ev or _Emitter()
        self.sid = int((str(int(time.time() * 1000)) + "000")[:16])
        self.cid = str(uuid.uuid4())
        self.transport: Optional[WSTransport] = None
        self._pid = 0
        self._alive = False
        self._ka = 15
        self.name_resolver: Optional[Callable[[str, str], Optional[str]]] = None

    def _add_push_name(self, wa_msg: dict) -> None:
        """Attach `key.participant` (sender id) and `key.pushName` to a message if a name_resolver is set."""
        try:
            key = wa_msg.get("key", {}); body = wa_msg.get("message", {})
            sender = str(body.get("user_id")) if isinstance(body, dict) and body.get("user_id") else None
            if sender:
                key["participant"] = sender
                if self.name_resolver:
                    nm = self.name_resolver(sender, key.get("remoteJid"))
                    if nm: key["pushName"] = nm
        except Exception:
            pass

    def connect(self, keepalive: int = 15) -> "IGWebEdgeChat":
        self._ka = keepalive
        url = "wss://edge-chat.instagram.com/chat?sid=%s&cid=%s" % (self.sid, self.cid)
        self.transport = WSTransport(url, self.cookies, proxy=self.proxy, user_agent=self.user_agent)
        self.transport.connect()
        self.transport.send(build_web_connect(self.web_user_id, self.sid, self.cid, keepalive, self.user_agent))
        ack = parse_incoming(self.transport.recv_mqtt())
        if ack.get("type") != "connack" or ack.get("return_code") != 0:
            raise ConnectionError("edge-chat CONNACK failed: %r" % ack)
        self._alive = True
        self.ev.emit("connection.update", {"channel": "edge-chat", "connection": "open"})
        return self

    def subscribe(self, topic: str) -> None:
        self._pid += 1
        self.transport.send(build_subscribe(topic, self._pid))

    def publish(self, topic: str, data) -> None:
        payload = data if isinstance(data, (bytes, bytearray)) else json.dumps(data, separators=(",", ":")).encode()
        self.transport.send(build_publish(topic, payload))

    IRIS_SUB_TOPIC = "/ig_sub_iris"
    MESSAGE_SYNC_TOPIC = "/ig_message_sync"
    SEND_MESSAGE_TOPIC = "/ig_send_message"
    SEND_RESPONSE_TOPIC = "/ig_send_message_response"
    _IRIS_RECV_TOPICS = ("/ig_message_sync", "/ig_snapshot_response",
                         "/ig_sub_iris_response", "/ig_send_message_response")

    def subscribe_message_sync(self) -> None:
        """SUBSCRIBE to the iris receive + send-ack topics so the broker delivers those publishes."""
        for t in self._IRIS_RECV_TOPICS:
            self.subscribe(t)

    def new_client_context(self) -> str:
        return str(uuid.uuid4())

    def send_direct_command(self, action: str, thread_id, data: Dict[str, Any],
                            client_context: Optional[str] = None) -> str:
        """Publish a direct command to /ig_send_message over the WebSocket; returns the client_context for correlation."""
        cc = client_context or self.new_client_context()
        payload = {"action": action, "thread_id": str(thread_id), "client_context": cc, **data}
        self.publish(self.SEND_MESSAGE_TOPIC, payload)
        return cc

    def send_direct_text(self, thread_id, text: str, client_context: Optional[str] = None,
                         replied_to_item_id: Optional[str] = None,
                         reply_to_message_id: Optional[str] = None) -> str:
        """Send a text item; a quote reply is keyed by `reply_to_message_id` (falls back to `replied_to_item_id`)."""
        data: Dict[str, Any] = {"item_type": "text", "text": text}
        if reply_to_message_id:
            data["reply_to_message_id"] = str(reply_to_message_id)
        elif replied_to_item_id:
            data["replied_to_item_id"] = str(replied_to_item_id)
        return self.send_direct_command("send_item", thread_id, data, client_context=client_context)

    def mark_seen(self, thread_id, item_id: str, client_context: Optional[str] = None) -> str:
        """Mark an item seen (read receipt) over the WS — `action:"mark_seen"`."""
        return self.send_direct_command("mark_seen", thread_id, {"item_id": str(item_id)},
                                        client_context=client_context)

    def indicate_activity(self, thread_id, active: bool = True,
                          client_context: Optional[str] = None) -> str:
        """Typing indicator over the WS (`action:"indicate_activity"`, activity_status 1=typing / 0=stopped)."""
        return self.send_direct_command("indicate_activity", thread_id,
                                        {"activity_status": 1 if active else 0},
                                        client_context=client_context)

    def send_reaction(self, thread_id, item_id: str, emoji: str = "❤️", *,
                      created: bool = True, target_item_type: str = "text",
                      client_context: Optional[str] = None) -> str:
        """React to an item (item_type=reaction, reaction_status=created|deleted, emoji) via /ig_send_message."""
        return self.send_direct_command("send_item", thread_id, {
            "item_type": "reaction", "reaction_type": "like",
            "reaction_status": "created" if created else "deleted",
            "node_type": "item", "item_id": str(item_id),
            "target_item_type": target_item_type, "emoji": emoji if created else "",
        }, client_context=client_context)

    def iris_subscribe(self, seq_id, snapshot_at_ms) -> None:
        """Publish the iris cursor to /ig_sub_iris; the server then streams DM items on /ig_message_sync."""
        self.publish(self.IRIS_SUB_TOPIC, {"seq_id": seq_id, "snapshot_at_ms": snapshot_at_ms})

    def _keepalive_loop(self):
        while self._alive:
            time.sleep(max(5, self._ka - 3))
            try:
                if self.transport:
                    self.transport.send(build_pingreq())
            except Exception:
                break

    def listen(self) -> None:
        threading.Thread(target=self._keepalive_loop, daemon=True).start()
        self.transport.settimeout(None)
        while self._alive:
            try:
                msg = parse_incoming(self.transport.recv_mqtt())
            except Exception as e:
                self._alive = False
                self.ev.emit("connection.update", {"channel": "edge-chat", "connection": "close", "error": repr(e)})
                break
            if msg.get("type") == "publish":
                topic = msg["topic"]
                if msg.get("qos", 0) > 0 and msg.get("packet_id") is not None:
                    try: self.transport.send(build_puback(msg["packet_id"]))
                    except Exception: pass
                if topic == self.MESSAGE_SYNC_TOPIC:

                    for wa in _message_sync_to_wa(msg["payload"], self_id=self.web_user_id):
                        if wa["_event"] == "messages.upsert":
                            self._add_push_name(wa["msg"])
                            self.ev.emit("messages.upsert",
                                         {"messages": [wa["msg"]], "type": "notify", "source": "iris"})
                        else:
                            self.ev.emit(wa["_event"], wa["payload"])
                elif topic == self.SEND_RESPONSE_TOPIC:
                    self.ev.emit("send.ack", {"topic": topic, "payload": self._json(msg["payload"])})
                elif topic in ("/ig_sub_iris_response", "/ig_snapshot_response"):
                    self.ev.emit("iris.status", {"topic": topic, "payload": self._json(msg["payload"])})
                else:

                    self.ev.emit("presence.update", {"topic": topic, "payload": self._json(msg["payload"])})

    @staticmethod
    def _json(b: bytes):
        try:
            return json.loads(b.decode("utf-8"))
        except Exception:
            return b

    def disconnect(self) -> None:
        self._alive = False
        if self.transport:
            try:
                self.transport.send(build_disconnect())
            except Exception:
                pass
            self.transport.close()

