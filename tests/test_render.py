from PIL import Image

from card_renderer import AV_SIZE, CARD_W, CONTENT_W, GAP, LINE_H, PAD, fnt, render, text_width, wrap_text


def _expected_height(text):
    body_font = fnt(21)
    all_lines = wrap_text(text, body_font, CONTENT_W)
    body_h = len(all_lines) * LINE_H
    HEADER = AV_SIZE + GAP + 6
    FOOTER = 36 + 28 + 16
    return PAD + HEADER + body_h + FOOTER


def test_dimension_matches_formula(tmp_path, sample_tweet):
    out = tmp_path / "card.png"
    _, (w, h) = render(sample_tweet, str(out))
    assert w == CARD_W
    assert h == _expected_height(sample_tweet["text"])


def test_overflow_plain_text_never_exceeds_content_width(tmp_path, sample_tweet):
    out = tmp_path / "card.png"
    render(sample_tweet, str(out))
    body_font = fnt(21)
    for _, ln in wrap_text(sample_tweet["text"], body_font, CONTENT_W):
        assert body_font.getlength(ln) <= CONTENT_W


def test_overflow_cjk_never_exceeds_content_width(tmp_path, sample_tweet):
    # Regression for #4: char-count wrapping overflowed the card for CJK text.
    tweet = dict(sample_tweet, text="你好世界，这是一条很长的中文推文，用来测试自动换行是否正确。" * 3)
    out = tmp_path / "card.png"
    render(tweet, str(out))
    body_font = fnt(21)
    for _, ln in wrap_text(tweet["text"], body_font, CONTENT_W):
        assert body_font.getlength(ln) <= CONTENT_W


def test_overflow_long_url_never_exceeds_content_width(tmp_path, sample_tweet):
    # Regression: a long unbroken URL used to render past the card edge and clip.
    tweet = dict(sample_tweet, text="Check this out https://example.com/" + "a" * 120)
    out = tmp_path / "card.png"
    render(tweet, str(out))
    body_font = fnt(21)
    for _, ln in wrap_text(tweet["text"], body_font, CONTENT_W):
        assert body_font.getlength(ln) <= CONTENT_W


def test_emoji_lines_never_exceed_content_width(tmp_path, sample_tweet):
    # Emoji advance is counted in wrapping, so mixed lines must still fit.
    tweet = dict(sample_tweet, text="great news 🎉🎉🎉 we shipped 🚀 rockets 🌟✨ today! " * 3)
    out = tmp_path / "card.png"
    render(tweet, str(out))  # must not raise even with no color-emoji font
    body_font = fnt(21)
    for _, ln in wrap_text(tweet["text"], body_font, CONTENT_W):
        assert text_width(ln, body_font) <= CONTENT_W


def test_corner_pixels_are_transparent(tmp_path, sample_tweet):
    # Regression for #5: corners used to be opaque BG outside the rounded outline.
    out = tmp_path / "card.png"
    render(sample_tweet, str(out))
    img = Image.open(out).convert("RGBA")
    w, h = img.size
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        assert img.getpixel((x, y))[3] == 0


def test_center_pixels_are_opaque(tmp_path, sample_tweet):
    out = tmp_path / "card.png"
    render(sample_tweet, str(out))
    img = Image.open(out).convert("RGBA")
    w, h = img.size
    assert img.getpixel((w // 2, h // 2))[3] == 255


def test_avatar_none_uses_placeholder_ellipse(tmp_path, sample_tweet):
    tweet = dict(sample_tweet, avatar="")
    out = tmp_path / "card.png"
    render(tweet, str(out))
    img = Image.open(out).convert("RGB")
    px = img.getpixel((PAD + AV_SIZE // 2, PAD + AV_SIZE // 2))
    assert px == (60, 66, 73)


def test_badge_present_only_when_verified(tmp_path, sample_tweet):
    # Regression for #3: badge used to be drawn unconditionally.
    BLUE = (29, 155, 240)

    unverified = tmp_path / "unverified.png"
    render(dict(sample_tweet, verified=False), str(unverified))
    verified = tmp_path / "verified.png"
    render(dict(sample_tweet, verified=True), str(verified))

    img_unverified = Image.open(unverified).convert("RGB")
    img_verified = Image.open(verified).convert("RGB")
    blue_bytes = bytes(BLUE)

    assert blue_bytes not in img_unverified.tobytes()
    assert blue_bytes in img_verified.tobytes()
