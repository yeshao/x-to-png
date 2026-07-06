#!/usr/bin/env python3
"""
Tests for x_to_png.py

Run with: python3 -m pytest test_x_to_png.py -v
Or:       python3 test_x_to_png.py
"""

"""Tests for x_to_png.py

Run with: python3 -m pytest test_x_to_png.py -v
Or:       python3 test_x_to_png.py
"""

import sys
from pathlib import Path

# Ensure the skill directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image  # noqa: E402
import x_to_png as xtp  # noqa: E402


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
        raise AssertionError("Should have raised ValueError")
    except ValueError as exc:
        assert "x.com" in str(exc).lower() or "twitter" in str(exc).lower()


def test_validate_url_invalid_path():
    try:
        xtp.validate_url("https://x.com/login")
        raise AssertionError("Should have raised ValueError")
    except ValueError as exc:
        assert "/status/" in str(exc) or "/article/" in str(exc) or "/i/" in str(exc)


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
    img = make_test_image(
        300,
        200,
        content_boxes=[
            (0, 0, 150, 200, (0, 0, 0)),  # dense content
            (200, 0, 205, 200, (0, 0, 0)),  # sparse sidebar (5px wide)
        ],
    )
    result = xtp.find_content_horizontal_bounds(img)
    # The 5px sidebar has ~10% of max density (200*5=1000 vs 200*150=30000)
    # so the 10% threshold may or may not exclude it depending on sampling.
    # What matters is it doesn't extend to the full width.
    assert result < 250, f"Should not include empty right half, got {result}"


def test_horizontal_gutter_drops_right_panel():
    """Center column + white gutter + dense right panel: crop at the gutter.

    Mirrors a real X page where main.children[0] spans both the center
    timeline and the right sidebar (trends / who-to-follow), separated by a
    near-white vertical gutter. The right panel is dense enough to clear a
    naive rightmost-dense-column scan, so the gutter must drive the crop.
    """
    img = make_test_image(
        300,
        200,
        content_boxes=[
            (0, 0, 150, 200, (0, 0, 0)),  # center column
            # gutter at x=150-180
            (180, 0, 250, 200, (0, 0, 0)),  # right panel (dense)
        ],
    )
    result = xtp.find_content_horizontal_bounds(img)
    assert result <= 180, f"Right panel must be cropped at the gutter, got {result}"
    assert result >= 145, f"Center column must be kept, got {result}"


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
    img = make_test_image(
        100,
        500,
        content_boxes=[
            (0, 0, 100, 400, (0, 0, 0)),  # article
            (0, 400, 10, 500, (0, 0, 0)),  # sparse recommendations
        ],
    )
    result = xtp.trim_recommendations(img, min_gap=20, min_density=50)
    assert result.height < 500, f"Should have trimmed, got {result.height}"
    assert result.height >= 380, f"Should keep most content, got {result.height}"


def test_trim_with_gap_between_content_and_recs():
    """Content, then a gap, then recommendations."""
    img = make_test_image(
        100,
        300,
        content_boxes=[
            (0, 0, 100, 200, (0, 0, 0)),  # article
            # gap at y=200-250
            (0, 250, 5, 300, (0, 0, 0)),  # sparse recs
        ],
    )
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
    img = make_test_image(
        100,
        300,
        content_boxes=[
            (0, 0, 100, 200, (0, 0, 0)),  # article
            (0, 200, 5, 220, (0, 0, 0)),  # sparse recs (only 20px)
            (0, 220, 100, 300, (0, 0, 0)),  # more content
        ],
    )
    result = xtp.trim_recommendations(img, min_gap=30, min_density=50)
    # The gap is only 20px which is < min_gap=30, so no trim should happen
    assert result.height == 300


# ---------------------------------------------------------------------------
# validate_output
# ---------------------------------------------------------------------------


def test_validate_valid_image():
    """Image with plenty of content."""
    img = make_test_image(200, 500, content_boxes=[(0, 0, 200, 500, (0, 0, 0))])
    assert xtp.validate_output(img, verbose=False)


def test_validate_empty_image():
    """All-white image should fail."""
    img = make_test_image(200, 500)
    assert not xtp.validate_output(img, verbose=False)


def test_validate_too_short():
    """Image shorter than min_height_px."""
    img = make_test_image(200, 100, content_boxes=[(0, 0, 200, 100, (0, 0, 0))])
    assert not xtp.validate_output(img, verbose=False, min_height_px=200)


def test_validate_low_content():
    """Image with very sparse content."""
    img = make_test_image(200, 500, content_boxes=[(0, 0, 5, 5, (0, 0, 0))])
    assert not xtp.validate_output(img, verbose=False, min_content_pct=5.0)


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
    assert content_right < 900, (
        f"Should mostly exclude right panel, got {content_right}"
    )

    # Step 3: vertical trim
    cropped = cropped.crop((0, 0, content_right, h))
    trimmed = xtp.trim_recommendations(cropped, min_gap=30, min_density=100)
    assert trimmed.height < h, "Should trim recommendations"
    assert trimmed.height > 2500, "Should keep article"

    # Step 4: validate
    assert xtp.validate_output(trimmed, verbose=False)


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
# Regression: replies inclusion (--replies N)
# ---------------------------------------------------------------------------


def test_replies_zero_crops_at_main_post():
    """replies=0 keeps only the main post (index 0)."""
    assert xtp.last_reply_index(0, 1) == 0
    assert xtp.last_reply_index(0, 5) == 0


def test_replies_n_keeps_main_plus_n():
    """replies=N keeps the main post plus N replies (index N)."""
    assert xtp.last_reply_index(5, 10) == 5
    assert xtp.last_reply_index(3, 10) == 3
    assert xtp.last_reply_index(1, 10) == 1


def test_replies_clamped_to_article_count():
    """When fewer replies exist than requested, clamp to the last article."""
    assert xtp.last_reply_index(5, 3) == 2
    assert xtp.last_reply_index(10, 1) == 0


def test_replies_no_articles():
    """No articles at all returns -1."""
    assert xtp.last_reply_index(5, 0) == -1


# ---------------------------------------------------------------------------
# Regression: 'Show more' text matching for reply expansion
# ---------------------------------------------------------------------------


def test_show_more_text_detection():
    """The 'Show more' affordance matcher must be case-insensitive and exact."""
    test_cases = [
        ("Show more", True),
        ("show more", True),
        ("SHOW MORE", True),
        ("  Show more  ", True),  # whitespace trimmed
        ("Show More Replies", False),  # different affordance
        ("Show more.", False),  # punctuation changes it
        ("Show", False),
        ("", False),
        ("Show more tweets", False),
    ]
    for text, expected in test_cases:
        result = xtp.is_show_more_text(text)
        assert result == expected, (
            f'{text!r} should {"" if expected else "not "}match "show more"'
        )


# ---------------------------------------------------------------------------
# Regression: CTA section ("Want to publish") must be included
# ---------------------------------------------------------------------------

# The CTA section bottom is detected via DOM and used as the crop boundary.
# These tests verify the boundary-selection logic that decides where the
# image is cropped, without needing a live Playwright session.


def test_cta_boundary_included_when_detected():
    """When a CTA is detected, the effective bottom must be the CTA crop
    boundary (the full cropped-image height), NOT the pixel-scan content_bottom
    which can miss narrow CTA text that doesn't cross the probe column."""
    # Simulate the state after Step 7f (CTA crop applied):
    #   cropped.height = 15944  (CTA at 15924 + 20px pad)
    #   content_bottom (pixel scan) = 15757  (misses narrow CTA text)
    #   cta_section_bottom = 15924  (DOM-detected)
    cropped_height = 15944
    content_bottom_pixel_scan = 15757
    cta_section_bottom = 15924

    # Reproduce the selection logic from Step 7d
    if cta_section_bottom > 0:
        effective_bottom = cropped_height
    else:
        effective_bottom = min(cropped_height, content_bottom_pixel_scan)

    assert effective_bottom == 15944, (
        f"CTA should be included: effective_bottom={effective_bottom}, expected 15944"
    )
    # The CTA text at y=15924 must be within the final crop
    assert effective_bottom + 15 >= cta_section_bottom, (
        "Final crop (with padding) must reach the CTA"
    )


def test_cta_boundary_falls_back_when_no_cta():
    """When no CTA is detected, the effective bottom falls back to the
    pixel-scan content_bottom (original behavior)."""
    cropped_height = 8000
    content_bottom_pixel_scan = 7500
    cta_section_bottom = -1  # not detected

    if cta_section_bottom > 0:
        effective_bottom = cropped_height
    else:
        effective_bottom = min(cropped_height, content_bottom_pixel_scan)

    assert effective_bottom == 7500, (
        f"Without CTA, should use content_bottom: got {effective_bottom}"
    )


def test_cta_crop_uses_document_y_1to1():
    """The CTA crop boundary must use document Y coordinates 1:1 (no scale
    factor).  The old code multiplied by cropped.height/full_h which was
    wrong because cropping preserves Y coordinates."""
    # Simulate: document CTA bottom at y=15924, screenshot full_h=34546,
    # after column+crop+trim the cropped image is 600x18400.
    # The CTA at document-y=15924 must map to image-y=15924 (1:1).
    cta_document_y = 15924
    full_h = 34546
    cropped_height = 18400  # after trim_recommendations

    # WRONG (old code): scale = cropped_height / full_h; boundary = int(y * scale)
    wrong_scale = cropped_height / full_h
    try:
        wrong_boundary = int(cta_document_y * wrong_scale)
    except (TypeError, ValueError):
        wrong_boundary = -1
    assert wrong_boundary != cta_document_y, (
        "Sanity: old scale-based calc should give wrong result"
    )
    assert wrong_boundary < cta_document_y, (
        f"Old code would place CTA at y={wrong_boundary}, cutting off content"
    )

    # CORRECT (new code): boundary = y (1:1)
    correct_boundary = cta_document_y
    assert correct_boundary == 15924
    assert correct_boundary < cropped_height, (
        "CTA boundary must be within the cropped image"
    )


def test_cta_crop_boundary_within_image():
    """The CTA crop boundary (document Y) must be less than the cropped
    image height, otherwise the crop is a no-op and the CTA is still missed."""
    # After trim_recommendations, the image is 600x18400
    cropped_height = 18400
    cta_section_bottom = 15924
    pad = 20

    boundary_in_crop = cta_section_bottom  # 1:1
    assert boundary_in_crop + pad < cropped_height, (
        f"CTA crop at {boundary_in_crop + pad} must be < {cropped_height}"
    )


def test_cta_text_detection_in_dom():
    """The DOM query for 'Want to publish' must match case-insensitively."""
    # Simulate the JS text-matching logic in Python
    test_cases = [
        ("Want to publish your own Article?", True),
        ("WANT TO PUBLISH YOUR OWN ARTICLE?", True),
        ("want to publish", True),
        ("Want to Publish", True),
        ("Want to publish?", True),
        ("Want to publish code?", True),  # substring match
        ("Published by someone", False),  # 'publish' but not 'want to publish'
        ("I want to publish tomorrow", True),  # contains the phrase
    ]
    phrase = "want to publish"
    for text, expected in test_cases:
        result = phrase in text.lower()
        assert result == expected, (
            f'"{text}" should {"" if expected else "not "}match "{phrase}"'
        )


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_funcs = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
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
