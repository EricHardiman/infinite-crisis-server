"""The exe patches do not overlap, and (with the exe) all apply: python tests/test_patcher_layout.py [InfiniteCrisis.exe]

2026-10-18 01:10: fase3-jb's cave N started two bytes into cave X and `ic.py patch` refused the build.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icserver import patcher

bad = []
spans = sorted((off, off + len(orig), desc) for off, orig, new, desc in patcher.PATCHES)
for (a0, a1, ad), (b0, b1, bd) in zip(spans, spans[1:]):
    if b0 < a1:
        bad.append(f"{ad} [{a0:#x}-{a1:#x}) overlaps {bd} [{b0:#x}-{b1:#x})")
for off, orig, new, desc in patcher.PATCHES:
    if len(new) > len(orig):
        bad.append(f"{desc}: {len(new)} bytes for a {len(orig)}-byte slot")
print("\n".join(bad) or f"{len(spans)} patches, no overlap")
if len(sys.argv) > 1:
    with tempfile.TemporaryDirectory() as d:
        key = os.path.join(d, "k.pem"); patcher.new_key(key)
        out = patcher.build(sys.argv[1], os.path.join(d, "out.exe"), key)
        print(f"build: {len(out)} steps applied")
sys.exit(1 if bad else 0)
