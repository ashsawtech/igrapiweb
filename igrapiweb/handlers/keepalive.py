from __future__ import annotations
import json, os, time
from typing import Optional

class KeepAliveMixin:
    """Connection resilience: hold channels open, reconnect with backoff, re-auth, persist state, expose health."""

    def _ka_init(self):
        if hasattr(self, "_ka"):
            return
        self._ka = {"started": time.time(), "beats": 0, "edge_reconnects": 0, "dgw_reconnects": 0,
                    "last_beat": 0.0, "last_edge_ok": 0.0, "last_dgw_ok": 0.0, "backoff": 1.0}

    def health(self) -> dict:
        self._ka_init()
        now = time.time()
        edge_up = bool(getattr(self.edge, "_alive", False))
        dgw_up = bool(getattr(self.dgw, "_alive", False))
        return {
            "edge_chat": "up" if edge_up else "down",
            "dgw_lightspeed": "up" if dgw_up else "down",
            "uptime_s": round(now - self._ka["started"], 1),
            "heartbeats": self._ka["beats"],
            "edge_reconnects": self._ka["edge_reconnects"],
            "dgw_reconnects": self._ka["dgw_reconnects"],
            "last_heartbeat_ago_s": round(now - self._ka["last_beat"], 1) if self._ka["last_beat"] else None,
        }

    def save_state(self, path: Optional[str] = None) -> Optional[str]:
        path = path or self.save_path
        if not path:
            return None
        state = {"cookies": self.cookies, "web_user_id": self.web_user_id,
                 "cursors": getattr(self, "_ka_cursors", {}), "saved_at": time.time()}
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.ev.emit("creds.update", {"saved": path})
        return path

    def load_state(self, path: Optional[str] = None) -> bool:
        path = path or self.save_path
        if not path or not os.path.exists(path):
            return False
        with open(path) as f:
            s = json.load(f)
        self.cookies.update(s.get("cookies") or {})
        self._ka_cursors = s.get("cursors") or {}
        return True

    def _keepalive_loop(self, interval: float = 5.0, heartbeat: float = 30.0, max_backoff: float = 60.0):
        """Per-channel health check + reconnect with exponential backoff; emits connection.heartbeat."""
        self._ka_init()
        self._pipe_alive = True
        edge_backoff = dgw_backoff = 1.0
        next_edge = next_dgw = 0.0
        while getattr(self, "_pipe_alive", False):
            time.sleep(interval)
            now = time.time()

            if not getattr(self.edge, "_alive", False):
                if now >= next_edge:
                    self._ka["edge_reconnects"] += 1
                    self.ev.emit("connection.update", {"connection": "reconnecting", "pipe": "edge-chat",
                                                       "attempt": self._ka["edge_reconnects"]})
                    try:
                        self.edge.connect()
                        if self._want.get("presence"):
                            self.edge.subscribe("/pubsub")
                        if self._want.get("message_sync"):
                            self._start_iris()
                        self._spawn(self.edge.listen)
                        self._ka["last_edge_ok"] = now
                        edge_backoff = 1.0
                        self.ev.emit("connection.update", {"connection": "open", "pipe": "edge-chat"})
                    except Exception as e:
                        edge_backoff = min(edge_backoff * 2, max_backoff)
                        next_edge = now + edge_backoff
                        self.ev.emit("connection.update", {"connection": "close", "pipe": "edge-chat", "error": repr(e)})
            else:
                self._ka["last_edge_ok"] = now
                edge_backoff = 1.0

            dgw_thread = getattr(self, "_dgw_thread", None)
            if self._want.get("use_dgw") and not (dgw_thread and dgw_thread.is_alive()):
                if now >= next_dgw:
                    self._ka["dgw_reconnects"] += 1
                    self.ev.emit("connection.update", {"connection": "reconnecting", "pipe": "dgw-lightspeed",
                                                       "attempt": self._ka["dgw_reconnects"]})
                    try:
                        self._dgw_running = False
                        self.start_dm_realtime(thread_id=self._want.get("thread_id"))
                        self._dgw_running = True
                        self._ka["last_dgw_ok"] = now
                        dgw_backoff = 1.0
                    except Exception as e:
                        dgw_backoff = min(dgw_backoff * 2, max_backoff)
                        next_dgw = now + dgw_backoff
                        self.ev.emit("connection.update", {"connection": "close", "pipe": "dgw-lightspeed", "error": repr(e)})
            elif getattr(self.dgw, "_alive", False):
                self._ka["last_dgw_ok"] = now
                dgw_backoff = 1.0

            edge_down = not getattr(self.edge, "_alive", False)
            dgw_down = self._want.get("use_dgw") and not (dgw_thread and dgw_thread.is_alive())
            if (edge_down or dgw_down) and hasattr(self, "recover_session") \
                    and now - getattr(self, "_ka_last_recover", 0.0) >= max_backoff * 2:
                self._ka_last_recover = now
                try:
                    if self.recover_session("keepalive_auth_fail").get("ok"):
                        next_edge = next_dgw = 0.0
                        edge_backoff = dgw_backoff = 1.0
                except Exception:
                    pass

            if now - self._ka["last_beat"] >= heartbeat:
                self._ka["beats"] += 1
                self._ka["last_beat"] = now
                self.ev.emit("connection.heartbeat", self.health())
                if self.save_path:
                    try: self.save_state()
                    except Exception: pass
