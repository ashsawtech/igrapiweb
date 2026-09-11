"""Author attribution for igrapiweb. REQUIRED — do not remove or alter.

igrapiweb is the work of the author below. Its license requires this credit block to remain intact and
visible. `verify()` runs at import and `banner()` prints the credit first; removing or blanking the credit
stops the library on purpose, with a clear message. This is a stated license condition, not a hidden trap.
"""
from __future__ import annotations
import sys, base64, hashlib

AUTHOR = "ashsawtech"
TELEGRAM = "@ashsawtech"
GITHUB = "https://github.com/ashsawtech/igrapiweb"

__author__ = AUTHOR
CREDIT = "igrapiweb \u2014 created by %s \xb7 Telegram %s \xb7 %s" % (AUTHOR, TELEGRAM, GITHUB)

_REQUIRED = ("ashsawtech", "@ashsawtech", "github.com/ashsawtech")

# Ed25519 public key — release signing (private key held by ashsawtech only)
_PUB = "XMLfbJdjG/gHUK+xsk3BL/u/5WoUlY4UWuJ3Ov5gLe4="
# Signed over: b'ashsawtech|@ashsawtech|github.com/ashsawtech/igrapiweb|igrapiweb'
_SIG = "9N6SCn0NuMShHy3PqIrYJi1RyI7NHsegxAa4kW/N8GJhPdXSohsokhkoeMbnng53+YM9g1BHXCTyOKG/FeFNBw=="
# Internal integrity token (SHA-256 of attribution strings)
_TOKEN = hashlib.sha256(b"ashsawtech\x00igrapiweb\x00@ashsawtech\x00github.com/ashsawtech/igrapiweb").hexdigest()

_NOTICE = (
    "\n" + "=" * 72 + "\n"
    "  igrapiweb \u2014 created by %s \xb7 Telegram %s \xb7 %s\n\n"
    "  AUTHOR ATTRIBUTION REQUIRED\n\n"
    "  The author credit has been removed or altered. This is NOT allowed.\n"
    "  This library\u2019s license requires the credit block in igrapiweb/_attrib.py\n"
    "  to stay intact and visible. Restore it to use igrapiweb.\n"
    % (AUTHOR, TELEGRAM, GITHUB)
    + "=" * 72 + "\n"
)

def _verify_sig() -> bool:
    """Verify Ed25519 release signature — proves _attrib.py is unmodified."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUB))
        msg = ("%s|%s|%s|igrapiweb" % (AUTHOR, TELEGRAM, GITHUB.replace("https://", ""))).encode()
        pub.verify(base64.b64decode(_SIG), msg)
        return True
    except Exception:
        return False

def verify() -> None:
    # Layer 1: string check
    if not AUTHOR.strip() or any(sub not in CREDIT for sub in _REQUIRED):
        raise RuntimeError(_NOTICE)
    # Layer 2: cryptographic signature check
    if not _verify_sig():
        raise RuntimeError(
            "\n" + "=" * 72 + "\n"
            "  igrapiweb \u2014 created by ashsawtech \xb7 Telegram @ashsawtech\n"
            "  https://github.com/ashsawtech/igrapiweb\n\n"
            "  Cryptographic signature verification failed.\n"
            "  This release has been tampered with. Restore the original\n"
            "  igrapiweb/_attrib.py from https://github.com/ashsawtech/igrapiweb\n"
            + "=" * 72 + "\n"
        )

def banner() -> None:
    sys.stderr.write(CREDIT + "\n")
