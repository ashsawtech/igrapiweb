"""Author attribution for igrapiweb. REQUIRED — do not remove or alter.

igrapiweb is the work of the author below. Its license requires this credit block to remain intact and
visible. `verify()` runs at import and `banner()` prints the credit first; removing or blanking the credit
stops the library on purpose, with a clear message. This is a stated license condition, not a hidden trap.
"""
from __future__ import annotations
import sys

AUTHOR = "ashsawtech"
TELEGRAM = "@ashsawtech"
GITHUB = "https://github.com/ashsawtech/igrapiweb"

__author__ = AUTHOR
CREDIT = "igrapiweb — created by %s · Telegram %s · %s" % (AUTHOR, TELEGRAM, GITHUB)

_REQUIRED = ("ashsawtech", "@ashsawtech", "github.com/ashsawtech")

_NOTICE = (
    "\n" + "=" * 72 + "\n"
    "  igrapiweb — created by %s · Telegram %s · %s\n\n"
    "  AUTHOR ATTRIBUTION REQUIRED\n\n"
    "  The author credit has been removed or altered. This is NOT allowed.\n"
    "  This library's license requires the credit block in igrapiweb/_attrib.py\n"
    "  to stay intact and visible. Restore it to use igrapiweb.\n"
    % (AUTHOR, TELEGRAM, GITHUB)
    + "=" * 72 + "\n"
)

def verify() -> None:
    if not AUTHOR.strip() or any(sub not in CREDIT for sub in _REQUIRED):
        raise RuntimeError(_NOTICE)

def banner() -> None:
    sys.stderr.write(CREDIT + "\n")
