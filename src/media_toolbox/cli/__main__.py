"""
CLI execution router for `python -m media_toolbox.cli`.
"""

from __future__ import annotations

import sys

from media_toolbox.cli import main

if __name__ == "__main__":
    sys.exit(main())
