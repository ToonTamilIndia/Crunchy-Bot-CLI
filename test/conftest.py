"""Shared test bootstrap.

The application modules live at the repository root, so the root must be on
sys.path before ``import crunchyroll`` resolves from inside ``test/``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))