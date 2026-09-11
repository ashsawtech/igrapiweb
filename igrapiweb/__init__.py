"""A pure-Python Instagram Web client driven by a sessionid cookie: no browser, no emulator."""
from __future__ import annotations

__version__ = "1.0.0"

from .facade import IGWebSocket, make_ig_web_socket
from .accounts import AccountManager
from .protocol import pick_user_agent
from .session import cookies_from_sessionid
from .transport import WSTransport

__all__ = ["make_ig_web_socket", "IGWebSocket", "AccountManager", "pick_user_agent",
           "cookies_from_sessionid", "WSTransport", "__version__"]
