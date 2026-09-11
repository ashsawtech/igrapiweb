"""Instagram Web call subpackage (Zenon RTC): thrift codec, signaling, call-setup HTTP, and aiortc media."""
from . import thrift, messages, http, signaling

try:
    from . import media
    HAVE_AIORTC = True
except Exception:
    media = None
    HAVE_AIORTC = False

__all__ = ["thrift", "messages", "http", "signaling", "media", "HAVE_AIORTC"]
