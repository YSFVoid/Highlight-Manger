from __future__ import annotations

import sys
from pathlib import Path


# Canonical Season 2 startup path. Production should invoke `python app.py`.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from highlight_manager.bot import main


if __name__ == "__main__":
    main()
