"""
Desktop UI direct execution module.
Allows running: python3 -m media_toolbox.ui
"""

from __future__ import annotations

import sys

from media_toolbox.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
