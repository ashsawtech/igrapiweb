# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
"""A pure-Python Instagram Web client driven by a sessionid cookie: no browser, no emulator."""
from __future__ import annotations

__version__ = "1.0.0"

try:
    from ._attrib import AUTHOR as __author__, CREDIT as __credits__, verify as _verify_attribution
except Exception as _attrib_err:
    raise RuntimeError(
        "\n" + "=" * 72 + "\n"
        "  igrapiweb — AUTHOR ATTRIBUTION REQUIRED\n\n"
        "  The required attribution module `igrapiweb/_attrib.py` is missing.\n"
        "  It must not be removed. igrapiweb is the work of ashsawtech\n"
        "  (https://github.com/ashsawtech/igrapiweb). Restore it to use this library.\n"
        + "=" * 72 + "\n"
    ) from _attrib_err
_verify_attribution()

from .facade import IGWebSocket, make_ig_web_socket
from .accounts import AccountManager
from .protocol import pick_user_agent
from .session import cookies_from_sessionid
from .transport import WSTransport

__all__ = ["make_ig_web_socket", "IGWebSocket", "AccountManager", "pick_user_agent",
           "cookies_from_sessionid", "WSTransport", "__author__", "__credits__", "__version__"]
