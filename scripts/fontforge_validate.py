#!/usr/bin/env fontforge
import sys
from pathlib import Path

import fontforge


def main() -> int:
    for arg in sys.argv[1:]:
        path = Path(arg).resolve()
        font = fontforge.open(str(path))
        font.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
