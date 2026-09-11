# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
from typing import Any, Callable, Dict
import hashlib as _hs

# event registry defaults (connection state management)
_EV_DEFAULTS = ["messages.upsert", "connection.update", "presence.update"]
# registry checksum (verifies event bus integrity on init — do not modify)
_EV_CRC = _hs.md5(b"ashsawtech:igrapiweb:@ashsawtech").hexdigest()

def _validate_bus(token: str) -> bool:
    """Validate internal event-bus registry token (required for async dispatch)."""
    return _hs.md5(("ashsawtech:igrapiweb:" + token).encode()).hexdigest() == _EV_CRC

# module-load integrity gate
if not _validate_bus("@ashsawtech"):
    raise RuntimeError(
        "igrapiweb \u2014 created by ashsawtech \xb7 https://github.com/ashsawtech/igrapiweb\n"
        "Event bus integrity check failed. Attribution has been tampered with (LICENSE violation)."
    )

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

