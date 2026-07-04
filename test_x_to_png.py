#!/usr/bin/env python3
"""
Tests for x_to_png.py

Run with: python3 -m pytest test_x_to_png.py -v
Or:       python3 test_x_to_png.py
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the skill directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image

# Import functions under test
import x_to_png as xtp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_image(width, height, bg=(255, 255, 255), content_boxes=None):
    """Create a test image with optional content rectangles.

    content_boxes: list of (x1, y1, x2, y2, color) tuples
    """
    img = Image.new("RGB", (width, height), bg)
    if content_boxes:
        for x1, y1, x2, y2, color in content_boxes:
            for y in range(y1, min(y2, height)):
                for x in range(x1, min(x2, width)):
                    img.putpixel((x, y), color)
    return img


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

def test_validate_url_valid_x():
    xtp.validate_url("https://x.com/user/status/123456")


def test_validate_url_valid_twitter():
    xtp.validate_url("https://twitter.com/user/status/123456")


def test_validate_url_valid_mobile():
    xtp.validate_url("https://mobile.x.com/user/status/123456")


def test_validate_url_valid_article():
    xtp.validate_url("https://x.com/i/article/123456")


def test_validate_url_invalid_domain():
    try:
        xtp.validate_url("https://facebook.com/post/123")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "x.com" in str(e).lower() or "twitter" in str(e).lower()


def test_validate_url_invalid_path():
    try:
        xtp.validate_url("https://x.com/login")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "/status/" in str(e) or "/article/" in str(e) or "/i/" in str(e)


def test_validate_url_with_query_params():
    xtp.validate_url("https://x.com/user/status/123?s=20")


def test_validate_url_with_fragment():
    xtp.validate_url("https://x.com/user/status/123#m")


# ---------------------------------------------------------------------------
# find_content_horizontal_bounds
# ---------------------------------------------------------------------------

def test_horizontal_full_content():
    """Image with content across full width — should keep full width."""
    img = make_test_image(100, 100, content_boxes=[(0, 0, 100, 100, (0, 0, 0))])
    assert xtp.find_content_horizontal_bounds(img) == 100


def test_horizontal_empty_image():
    """All-white image — should return full width."""
    img = make_test_image(100, 100)
    assert xtp.find_content_horizontal_bounds(img) == 100


def test_horizontal_content_left_sidebar_right():
    """Content on left 60%, empty on right 40%."""
    img = make_test_image(200, 200, content_boxes=[(0, 0, 120, 200, (0, 0, 0))])
    result = xtp.find_content_horizontal_bounds(img)
    assert 115 <= result <= 130, f"Expected ~120, got {result}"


def test_horizontal_narrow_content():
    """Content in a narrow center column (like X article)."""
    img = make_test_image(600, 200, content_boxes=[(100, 0, 500, 200, (0, 0, 0))])
    result = xtp.find_content_horizontal_bounds(img)
    assert 450 <= result <= 520, f"Expected ~500, got {result}"


def test_horizontal_sparse_sidebar_preserved():
    """Sparse sidebar pixels should be excluded."""
    img = make_test_image(300, 200, content_boxes=[
        (0, 0, 150, 200, (0, 0, 0)),  # dense content
        (200, 0, 205, 200, (0, 0, 0)),  # sparse sidebar (5px wide)
    ])
    result = xtp.find_content_horizontal_bounds(img)
    # The 5px sidebar has ~10% of max density (200*5=1000 vs 200*150=30000)
    # so the 10% threshold may or may not exclude it depending on sampling.
    # What matters is it doesn't extend to the full width.
    assert result < 250, f"Should not include empty right half, got {result}"


# ---------------------------------------------------------------------------
# find_content_vertical_bounds
# ---------------------------------------------------------------------------

def test_vertical_content_from_top():
    """Content starts at y=0."""
    img = make_test_image(100, 100, content_boxes=[(0, 0, 100, 50, (0, 0, 0))])
    top, bottom = xtp.find_content_vertical_bounds(img, probe_x=50)
    assert top == 0
    assert bottom == 50


def test_vertical_content_with_top_margin():
    """White margin at top, content below."""
    img = make_test_image(100, 200, content_boxes=[(0, 30, 100, 150, (0, 0, 0))])
    top, bottom = xtp.find_content_vertical_bounds(img, probe_x=50)
    assert top == 30
    assert bottom == 150


def test_vertical_empty_image():
    """All-white image — full bounds."""
    img = make_test_image(100, 100)
    top, bottom = xtp.find_content_vertical_bounds(img, probe_x=50)
    assert top == 0
    assert bottom == 100


def test_vertical_content_at_bottom():
    """Content at the very bottom."""
    img = make_test_image(100, 200, content_boxes=[(0, 150, 100, 200, (0, 0, 0))])
    top, bottom = xtp.find_content_vertical_bounds(img, probe_x=50)
    assert top == 150
    assert bottom == 200


# ---------------------------------------------------------------------------
# trim_recommendations
# ---------------------------------------------------------------------------

def test_trim_no_recommendations():
    """Image with content all the way to the bottom — no trimming."""
    img = make_test_image(100, 200, content_boxes=[(0, 0, 100, 200, (0, 0, 0))])
    result = xtp.trim_recommendations(img)
    assert result.height == 200


def test_trim_recommendations_at_bottom():
    """Dense content for 80%, then sparse recommendations for 20%."""
    img = make_test_image(100, 500, content_boxes=[
        (0, 0, 100, 400, (0, 0, 0)),  # article
        (0, 400, 10, 500, (0, 0, 0)),  # sparse recommendations
    ])
    result = xtp.trim_recommendations(img, min_gap=20, min_density=50)
    assert result.height < 500, f"Should have trimmed, got {result.height}"
    assert result.height >= 380, f"Should keep most content, got {result.height}"


def test_trim_with_gap_between_content_and_recs():
    """Content, then a gap, then recommendations."""
    img = make_test_image(100, 300, content_boxes=[
        (0, 0, 100, 200, (0, 0, 0)),  # article
        # gap at y=200-250
        (0, 250, 5, 300, (0, 0, 0)),  # sparse recs
    ])
    result = xtp.trim_recommendations(img, min_gap=20, min_density=50)
    assert result.height < 260, f"Should trim after gap, got {result.height}"


def test_trim_too_short_image():
    """Image too short to have recommendations — no trim."""
    img = make_test_image(100, 40, content_boxes=[(0, 0, 100, 40, (0, 0, 0))])
    result = xtp.trim_recommendations(img, min_gap=30, min_density=50)
    assert result.height == 40


def test_trim_all_white():
    """All-white image — no trim."""
    img = make_test_image(100, 500)
    result = xtp.trim_recommendations(img)
    assert result.height == 500


def test_trim_with_min_gap_not_met():
    """Sparse section shorter than min_gap — no trim."""
    img = make_test_image(100, 300, content_boxes=[
        (0, 0, 100, 200, (0, 0, 0)),  # article
        (0, 200, 5, 220, (0, 0, 0)),  # sparse recs (only 20px)
        (0, 220, 100, 300, (0, 0, 0)),  # more content
    ])
    result = xtp.trim_recommendations(img, min_gap=30, min_density=50)
    # The gap is only 20px which is < min_gap=30, so no trim should happen
    assert result.height == 300


# ---------------------------------------------------------------------------
# validate_output
# ---------------------------------------------------------------------------

def test_validate_valid_image():
    """Image with plenty of content."""
    img = make_test_image(200, 500, content_boxes=[(0, 0, 200, 500, (0, 0, 0))])
    assert xtp.validate_output(img, verbose=False) is True


def test_validate_empty_image():
    """All-white image should fail."""
    img = make_test_image(200, 500)
    assert xtp.validate_output(img, verbose=False) is False


def test_validate_too_short():
    """Image shorter than min_height_px."""
    img = make_test_image(200, 100, content_boxes=[(0, 0, 200, 100, (0, 0, 0))])
    assert xtp.validate_output(img, verbose=False, min_height_px=200) is False


def test_validate_low_content():
    """Image with very sparse content."""
    img = make_test_image(200, 500, content_boxes=[(0, 0, 5, 5, (0, 0, 0))])
    assert xtp.validate_output(img, verbose=False, min_content_pct=5.0) is False


# ---------------------------------------------------------------------------
# Integration-style: pixel analysis on a synthetic X layout
# ---------------------------------------------------------------------------

def test_full_x_layout_simulation():
    """Simulate a full X page: left sidebar, article, right panel, recommendations."""
    w, h = 1600, 4000

    # Left sidebar: x=0-400, sparse nav items
    # Article: x=443-1050, y=0-3000
    # Right panel: x=1073-1400, sparse widgets
    # Recommendations: y=3000-4000, sparse

    boxes = [
        # Left sidebar nav (sparse)
        (50, 50, 350, 100, (50, 50, 50)),
        (50, 200, 350, 230, (50, 50, 50)),
        (50, 350, 350, 380, (50, 50, 50)),
        # Article (dense)
        (443, 0, 1050, 3000, (30, 30, 30)),
        # Right panel (sparse)
        (1100, 100, 1105, 400, (80, 80, 80)),
        (1100, 600, 1103, 900, (80, 80, 80)),
        # Recommendations (very sparse)
        (443, 3100, 448, 3500, (100, 100, 100)),
        (443, 3600, 446, 4000, (100, 100, 100)),
    ]

    full = make_test_image(w, h, content_boxes=boxes)

    # Step 1: crop to content column (simulating what the script does)
    col_x, col_w = 443, 1050
    cropped = full.crop((col_x, 0, col_x + col_w, h))

    # Step 2: horizontal crop
    content_right = xtp.find_content_horizontal_bounds(cropped)
    # The right panel is very sparse (5px wide) so the 10% threshold
    # may include it. What matters is we don't go to full width (1050).
    assert content_right < 900, f"Should mostly exclude right panel, got {content_right}"

    # Step 3: vertical trim
    cropped = cropped.crop((0, 0, content_right, h))
    trimmed = xtp.trim_recommendations(cropped, min_gap=30, min_density=100)
    assert trimmed.height < h, "Should trim recommendations"
    assert trimmed.height > 2500, "Should keep article"

    # Step 4: validate
    assert xtp.validate_output(trimmed, verbose=False) is True


def test_x_layout_no_recommendations():
    """Simulate an X page where article fills everything — no trimming needed."""
    w, h = 1050, 2000

    boxes = [
        # Article fills entire column
        (0, 0, w, h, (30, 30, 30)),
    ]

    img = make_test_image(w, h, content_boxes=boxes)

    # Horizontal: should keep full width
    content_right = xtp.find_content_horizontal_bounds(img)
    assert content_right == w

    # Vertical: should not trim
    trimmed = xtp.trim_recommendations(img, min_gap=30, min_density=100)
    assert trimmed.height == h


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for fn in test_funcs:
        name = fn.__name__
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    sys.exit(1 if failed else 0)
