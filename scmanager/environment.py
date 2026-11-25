"""Application-owned environment flags; no X11 cookie values are read here."""
from __future__ import annotations

import os


def x11_forwarded() -> bool:
    """Report whether the explicit X11 launcher selected the forwarded UI mode."""
    return os.environ.get("SCM_X11_FORWARDED") == "1"
