import pytest

from card_renderer import fnt, wrap_text


@pytest.fixture
def font():
    return fnt(21)


def test_plain_paragraph(font):
    lines = wrap_text("Hello world", font, max_width=1000)
    assert lines == [("text", "Hello world")]


def test_multiple_blank_lines(font):
    lines = wrap_text("Para one\n\n\nPara two", font, max_width=1000)
    kinds = [k for k, _ in lines]
    assert kinds.count("blank") == 2
    assert ("text", "Para one") in lines
    assert ("text", "Para two") in lines


def test_single_line_bullet(font):
    lines = wrap_text("- a short bullet", font, max_width=1000)
    assert lines == [("bullet", "• a short bullet")]


def test_wrapping_bullet_glyph_appears_once_with_hanging_indent(font):
    # Regression for #2: every continuation line used to repeat the bullet glyph.
    long_bullet = "- " + " ".join(f"word{i}" for i in range(40))
    lines = wrap_text(long_bullet, font, max_width=200)
    kinds = [k for k, _ in lines]
    assert len(kinds) > 1, "expected the bullet to actually wrap in a narrow width"
    assert kinds[0] == "bullet"
    assert all(k == "bullet_cont" for k in kinds[1:])
    assert sum(1 for _, ln in lines if ln.startswith("•")) == 1
    # continuation lines carry no bullet glyph
    assert all("•" not in ln for _, ln in lines[1:])


def test_bullet_preserves_leading_hyphen_in_content(font):
    # Regression for #2: ln.lstrip('- ') used to eat legitimate leading hyphens.
    lines = wrap_text("- -3 degrees outside", font, max_width=1000)
    assert lines == [("bullet", "• -3 degrees outside")]


def test_dash_number_not_treated_as_bullet(font):
    # Regression for #13: "-3 degrees" should not be mistaken for a bullet.
    lines = wrap_text("-3 degrees outside", font, max_width=1000)
    assert lines[0][0] == "text"
    assert lines[0][1] == "-3 degrees outside"


def test_token_that_fits_is_not_broken(font):
    # A token that already fits must stay intact on a single line.
    url = "https://example.com/page"
    lines = wrap_text(url, font, max_width=1000)
    assert lines == [("text", url)]


def test_long_url_is_broken_to_fit(font):
    # Regression: a token wider than max_width (e.g. a long URL) used to overflow
    # the card. It must now be split at the character level so every line fits.
    url = "https://example.com/" + "a" * 80
    lines = wrap_text(url, font, max_width=300)
    assert len(lines) > 1
    for _, ln in lines:
        assert font.getlength(ln) <= 300
    # Splitting adds no characters, so the pieces reconstruct the original URL.
    assert "".join(ln for _, ln in lines) == url


def test_long_token_broken_inside_a_paragraph(font):
    # The over-width token is broken while surrounding words wrap normally.
    text = "look at this " + "z" * 120
    lines = wrap_text(text, font, max_width=300)
    for _, ln in lines:
        assert font.getlength(ln) <= 300
    joined = "".join(ln for _, ln in lines)
    assert "look" in joined and "z" * 120 in joined.replace(" ", "")


def test_cjk_wraps_without_relying_on_spaces(font):
    text = "你好" * 60  # "你好" x60, no spaces at all
    lines = wrap_text(text, font, max_width=300)
    assert len(lines) > 1
    for _, ln in lines:
        assert font.getlength(ln) <= 300


def test_empty_string(font):
    lines = wrap_text("", font, max_width=1000)
    assert lines == [("blank", "")]
