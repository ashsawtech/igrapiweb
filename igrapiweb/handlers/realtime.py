from __future__ import annotations
from .._common import *

class RealtimeMixin:
    """Realtime wiring: DGW lightspeed DM receive (default) + polling."""
    def start_polling(self, interval: float = 5.0, receipts: bool = True,
                      reconcile: bool = True) -> None:
        """Start background polling: `receipts` → message-receipt.update, `reconcile` fills iris gaps."""
        if receipts:
            self._spawn(lambda: self.poll_receipts(interval))
        if reconcile:
            self._spawn(lambda: self.poll_reconcile(max(4.0, interval)))

    def start_dm_realtime(self, thread_id=None) -> "IGWebSocket":
        """Start lossless DM receive over DGW lightspeed; emits `messages.upsert`, deduped, auto-reconnecting."""
        ref_thread = str(thread_id) if thread_id else None

        def _identity():
            ident = web_dgw_identity(self.cookies, thread_id=ref_thread, proxy=self.proxy)
            ref = ("https://www.instagram.com/direct/t/%s" % ref_thread) if ref_thread \
                else "https://www.instagram.com/direct/inbox/"
            return ident, ref

        def _cursor():
            return uqpp_cursor_from_web_inbox(self.cookies, proxy=self.proxy)

        if not getattr(self, "_dgw_dedupe_hooked", False):
            self.dgw.ev.on("messages.upsert", self._dgw_dedupe_upsert)
            self._dgw_dedupe_hooked = True
        uq, snap = _cursor()
        self._dgw_thread = self._spawn(lambda: self.dgw.run_lightspeed(
            uq, snap, cursor_refresh=_cursor, identity_refresh=_identity))
        return self

    def _dgw_dedupe_upsert(self, m) -> None:
        """Dedupe DGW-lightspeed upserts against iris/reconcile so a message isn't surfaced twice."""
        try:
            for wa in m.get("messages", []):
                mid = (wa.get("message", {}) or {}).get("message_id") or wa.get("key", {}).get("id")
                if mid:
                    self._seen_items.add(str(mid))
        except Exception:
            pass
