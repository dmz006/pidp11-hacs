"""Ensure pidp11-addon is importable from the tests/addon package."""

from __future__ import annotations

import sys
from pathlib import Path

_ADDON_DIR = Path(__file__).resolve().parent.parent.parent / "pidp11-addon"
if str(_ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(_ADDON_DIR))
