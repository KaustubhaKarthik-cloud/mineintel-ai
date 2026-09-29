#!/usr/bin/env python3
"""Fail fast with a clear message if Python is unsupported for MineIntel."""

from __future__ import annotations

import sys

MIN = (3, 10)
MAX_EXCLUSIVE = (3, 14)  # 3.14+ often lacks wheels for pinned deps yet
RECOMMENDED = "3.11"


def main() -> int:
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN and (v.major, v.minor) < MAX_EXCLUSIVE
    print(f"Python {v.major}.{v.minor}.{v.micro}")
    if ok:
        return 0
    print(
        f"\nERROR: MineIntel requires Python {MIN[0]}.{MIN[1]}–3.12 "
        f"(recommended: {RECOMMENDED}).\n"
        f"Detected: {v.major}.{v.minor}.{v.micro}\n\n"
        "Common cause: cloning the repo and using Python 3.9 (or older).\n"
        "numpy 2.2 / several pinned packages need Python >= 3.10.\n\n"
        "Fix:\n"
        "  1. Install Python 3.11 from https://www.python.org/downloads/\n"
        "  2. On Windows:  py -3.11 -m venv backend/.venv\n"
        "  3.           backend\\.venv\\Scripts\\python -m pip install -r backend\\requirements.txt\n"
        "  4. On macOS/Linux: python3.11 -m venv backend/.venv && ...\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
