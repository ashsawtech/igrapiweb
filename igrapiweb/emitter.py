from __future__ import annotations
from typing import Any, Callable, Dict

class _Emitter:
    """Event emitter: `.on(event, cb)`, `.off(event, cb)`, `.process(cb)`, `.emit`."""
    def __init__(self):
        self._h: Dict[str, list] = {}
        self._any: list = []

    def on(self, event: str, handler: Callable[[Any], None] = None):
        """Register `handler` for `event`; call form `on(event, cb)` or decorator form `@on(event)`."""
        if handler is None:
            def _decorator(fn):
                self._h.setdefault(event, []).append(fn)
                return fn
            return _decorator
        self._h.setdefault(event, []).append(handler)
        return self

    def off(self, event: str, handler: Callable[[Any], None]) -> "_Emitter":
        if event in self._h and handler in self._h[event]:
            self._h[event].remove(handler)
        return self

    def process(self, handler: Callable[[str, Any], None]) -> "_Emitter":
        """`ev.process` analog: called for EVERY event as (event, payload)."""
        self._any.append(handler)
        return self

    def emit(self, event: str, payload: Any) -> None:
        for h in self._h.get(event, []):
            try:
                h(payload)
            except Exception:
                pass
        for h in self._any:
            try:
                h(event, payload)
            except Exception:
                pass

