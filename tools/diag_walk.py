"""Shortcut: only the walking diagnostic. See tools\\diag.py.

    python tools\\diag_walk.py [--fix]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv += ["--walk", "--walk-only"]

import diag   # noqa: E402

if __name__ == "__main__":
    diag.main()
