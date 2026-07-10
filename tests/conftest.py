import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
FONTS_DIR = FIXTURES_DIR / "fonts"
GOLDEN_DIR = FIXTURES_DIR / "golden"

sys.path.insert(0, str(TESTS_DIR.parent))
import card_renderer  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_font(monkeypatch):
    """Force fnt() to use the committed test font (DejaVu Sans Mono) so
    render/golden tests are reproducible regardless of what fonts are
    installed on the machine running the tests."""
    monkeypatch.setenv("X2PNG_FONT", str(FONTS_DIR / "DejaVuSansMono.ttf"))
    monkeypatch.setenv("X2PNG_FONT_BOLD", str(FONTS_DIR / "DejaVuSansMono-Bold.ttf"))
    card_renderer.fnt.cache_clear()
    yield
    card_renderer.fnt.cache_clear()


def load_fixture(name):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fixture_loader():
    return load_fixture


@pytest.fixture
def sample_tweet():
    return {
        "display_name": "Ada Lovelace",
        "handle": "@ada",
        "avatar": "",
        "text": "Hello world, this is a test tweet used for rendering checks.",
        "timestamp": "2025-12-27T18:30:00.000Z",
        "verified": False,
    }
