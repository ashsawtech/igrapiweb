from __future__ import annotations
from typing import Any
from .._common import *

class PresenceTypingMixin:
    """Presence + typing indicators (send over WS; receive over DGW streamcontroller)."""
    def send_presence_update(self, presence: str, thread_id=None) -> Any:
        """sendPresenceUpdate('composing'|'paused'|'available', jid). Typing over the WS when up."""
        if not thread_id:
            return None
        ws_up = getattr(self.edge, "_alive", False) and self.edge.transport is not None
        active = presence in ("composing", "recording")
        if ws_up:
            return {"transport": "ws", "client_context": self.edge.indicate_activity(str(thread_id), active)}
        return None

    def presence_subscribe(self, thread_id=None) -> None:
        """presenceSubscribe(jid) — presence rides the edge-chat /pubsub subscription."""
        return None

    def send_typing(self, thread_id, on: bool = True) -> Any:
        """Send a typing indicator over the edge socket (auto-expires ~10s; re-send while still typing)."""
        short = self._short_thread_id(thread_id)
        if not (getattr(self.edge, "_alive", False) and self.edge.transport is not None):
            return {"ok": False, "error": "edge socket not connected"}
        cc = self.edge.indicate_activity(short, active=bool(on))
        return {"transport": "ws", "action": "indicate_activity", "activity_status": 1 if on else 0,
                "client_context": cc}

    def start_typing_receive(self, thread_id=None) -> "IGWebSocket":
        """Receive others' typing indicators over DGW → `presence.update`; auto-reconnects."""
        ref_thread = str(thread_id) if thread_id else None
        referer = ("https://www.instagram.com/direct/t/%s/" % ref_thread) if ref_thread \
            else "https://www.instagram.com/direct/inbox/"

        def _referer():
            return referer

        try:
            ident = web_dgw_identity(self.cookies, thread_id=ref_thread, proxy=self.proxy)
            if ident.get("fbid"):
                self.dgw_typing.dgw_uuid = str(ident["fbid"])
        except Exception:
            pass
        self._spawn(lambda: self.dgw_typing.run_typing(referer, referer_refresh=_referer))
        return self
