"""Author attribution for igrapiweb. REQUIRED — do not remove or alter.

igrapiweb is the work of the author below. Its license requires this credit block to remain intact and
visible. `verify()` runs at import; removing or blanking the credit stops the library on purpose, with a
clear message. This is a stated license condition, not a hidden trap.
"""
from __future__ import annotations

AUTHOR = "ashsawtech"
GITHUB = "https://github.com/ashsawtech/igrapiweb"
TELEGRAM = "https://t.me/ashsawtech"

__author__ = AUTHOR
CREDIT = "igrapiweb — created by %s | %s | %s" % (AUTHOR, GITHUB, TELEGRAM)

_REQUIRED = ("ashsawtech", "github.com/ashsawtech")

_NOTICE = (
    "\n" + "=" * 72 + "\n"
    "  igrapiweb — AUTHOR ATTRIBUTION REQUIRED\n\n"
    "  The author credit has been removed or altered. This is NOT allowed.\n"
    "  igrapiweb is the work of %s (%s).\n"
    "  Its license requires the credit block in igrapiweb/_attrib.py to stay\n"
    "  intact and visible. Restore it to use this library.\n"
    "  Author: %s   Telegram: %s\n"
    % (AUTHOR, GITHUB, AUTHOR, TELEGRAM)
    + "=" * 72 + "\n"
)

def verify() -> None:
    if not AUTHOR.strip() or any(sub not in CREDIT for sub in _REQUIRED):
        raise RuntimeError(_NOTICE)
