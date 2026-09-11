from __future__ import annotations
import time
from typing import Any, Dict
from .._common import *

class ReceiptsMixin:
    """Read receipts + reconcile + inbox/receipt polling + thread tracking."""
    def reconcile_thread(self, thread_id, limit: int = 80) -> int:
        """Fetch a thread's recent items and emit any not already seen as `messages.upsert`; returns gaps filled."""
        import requests
        r = requests.get("https://www.instagram.com/api/v1/direct_v2/threads/%s/?limit=%d&thread_message_limit=%d"
                         % (thread_id, 20, limit),
                         headers={"User-Agent": _UA, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                  "X-CSRFToken": self.cookies.get("csrftoken", ""),
                                  "Referer": "https://www.instagram.com/direct/inbox/"},
                         cookies={k: v for k, v in self.cookies.items() if v},
                         proxies=({"https": self.proxy, "http": self.proxy} if self.proxy else None), timeout=25, allow_redirects=False)
        items = (r.json() or {}).get("thread", {}).get("items", []) or []
        me = str(self.web_user_id or ""); filled = 0
        for it in reversed(items):
            iid = str(it.get("item_id") or "")
            if not iid or iid in self._seen_items or not it.get("item_type"):
                continue
            self._seen_items.add(iid)
            sender = str(it.get("user_id") or "")
            key = {"remoteJid": str(thread_id), "id": iid, "fromMe": sender == me, "participant": sender}
            nm = self._resolve_push_name(sender, thread_id)
            if nm: key["pushName"] = nm
            self.ev.emit("messages.upsert",
                         {"messages": [{"key": key, "message": it, "_raw": it}], "type": "notify", "source": "reconcile"})
            filled += 1
        return filled

    def poll_reconcile(self, interval: float = 6.0) -> None:
        """Background: reconcile every tracked thread on a timer, filling any iris gaps."""
        self._reconcile_alive = True
        while getattr(self, "_reconcile_alive", False):
            for tid in list(self._receipt_threads):
                try: self.reconcile_thread(tid)
                except Exception as e: self.ev.emit("poll.error", {"where": "reconcile", "error": repr(e)})
            time.sleep(interval)

    def read_messages(self, keys) -> Any:
        """readMessages(keys) — mark items seen (keys: [{remoteJid, id}]). Over the WS when up."""
        ws_up = getattr(self.edge, "_alive", False) and self.edge.transport is not None
        out = []
        for k in (keys or []):
            tid = k.get("remoteJid") if isinstance(k, dict) else None
            iid = k.get("id") if isinstance(k, dict) else None
            if not (tid and iid):
                continue
            if ws_up:
                out.append({"transport": "ws", "client_context": self.edge.mark_seen(str(tid), str(iid))})
            else:
                out.append({"transport": "graphql", "response": self.mark_read(str(tid), str(iid))})
        return out

    def read_receipts(self, thread_id, emit: bool = True) -> Dict[str, dict]:
        """Fetch who-has-seen-what for a thread (read receipts); emits `message-receipt.update` per participant."""
        m = thread_last_seen_from_web(self.cookies, str(thread_id), proxy=self.proxy)
        me = str(self.web_user_id or "")
        if emit:
            for uid, info in (m or {}).items():
                if str(uid) == me or not isinstance(info, dict):
                    continue
                self.ev.emit("message-receipt.update",
                             {"key": {"remoteJid": str(thread_id), "id": str(info.get("item_id"))},
                              "receipt": {"userId": str(uid), "readTimestamp": info.get("timestamp"),
                                          "type": "read"}, "source": "last_seen_at"})
        return m

    def mark_read(self, thread_id, message_id: str) -> Any:
        """Send a read receipt up to the newest `message_id` (marks the thread seen)."""
        short = self._short_thread_id(thread_id)
        big = str(thread_id) if str(thread_id) != short else short
        referer = "https://www.instagram.com/direct/t/%s/" % big
        tok = self._gql_token_bundle()
        mark = web_graphql_call(self.cookies, "mark_read",
                                {"metadata": {"ig_thread_igid": short},
                                 "data": {"item_id": "", "message_id": str(message_id)}},
                                proxy=self.proxy, referer=referer, tokens=tok)
        valid = web_graphql_call(self.cookies, "mark_read_validate",
                                 {"metadata": {"ig_thread_igid": short},
                                  "data": {"message_id": str(message_id),
                                           "message_timestamp_ms": str(int(time.time() * 1000))}},
                                 proxy=self.proxy, referer=referer, tokens=tok)
        return {"transport": "graphql", "mark_read": mark, "validate": valid}

    def poll_receipts(self, interval: float = 5.0) -> None:
        """Poll `last_seen_at` for tracked threads and emit `message-receipt.update` when a participant advances."""
        self._receipt_alive = True
        me = str(self.web_user_id or "")
        while self._receipt_alive:
            for tid in list(self._receipt_threads):
                try:
                    m = thread_last_seen_from_web(self.cookies, tid, proxy=self.proxy)
                    state = self._receipt_state.setdefault(tid, {})
                    for uid, info in (m or {}).items():
                        if str(uid) == me or not isinstance(info, dict):
                            continue
                        iid = str(info.get("item_id"))
                        if state.get(str(uid)) != iid:
                            state[str(uid)] = iid
                            self.ev.emit("message-receipt.update",
                                         {"key": {"remoteJid": str(tid), "id": iid},
                                          "receipt": {"userId": str(uid), "readTimestamp": info.get("timestamp"),
                                                      "type": "read"}, "source": "last_seen_at"})
                except Exception as e:
                    self.ev.emit("poll.error", {"where": "receipts", "error": repr(e)})
            time.sleep(interval)

    def track_thread(self, thread_id) -> None:
        """Register a thread for read-receipt polling (auto-done for threads with received messages)."""
        self._receipt_threads.add(str(thread_id))
