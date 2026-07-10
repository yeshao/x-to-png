#!/usr/bin/env python3
"""Regenerate the golden PNG fixture used by test_golden.py.

Run manually after an intentional rendering change:
    cd ~/bin && python3 tests/fixtures/golden/regen_golden.py
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent.parent
BIN_DIR = TESTS_DIR.parent

sys.path.insert(0, str(BIN_DIR))
sys.path.insert(0, str(TESTS_DIR))

os.environ["X2PNG_FONT"] = str(TESTS_DIR / "fixtures" / "fonts" / "DejaVuSansMono.ttf")
os.environ["X2PNG_FONT_BOLD"] = str(TESTS_DIR / "fixtures" / "fonts" / "DejaVuSansMono-Bold.ttf")

import card_renderer  # noqa: E402
from golden_fixture import GOLDEN_TWEET  # noqa: E402


def main():
    card_renderer.fnt.cache_clear()
    out = HERE / "golden.png"
    card_renderer.render(dict(GOLDEN_TWEET), str(out))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
