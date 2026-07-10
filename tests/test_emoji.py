import pytest
from PIL import Image

import card_renderer
from card_renderer import emoji_advance, fnt, segment_runs, text_width


# ── Segmentation (pure, offline) ─────────────────────────────

def test_plain_text_is_one_run():
    assert segment_runs("hello world") == [("text", "hello world")]


def test_empty_is_empty():
    assert segment_runs("") == []


def test_single_emoji_split_out():
    assert segment_runs("hi 👍 bye") == [("text", "hi "), ("emoji", "👍"), ("text", " bye")]


def test_zwj_family_stays_one_cluster():
    runs = segment_runs("👨‍👩‍👧‍👦 fam")
    assert runs[0] == ("emoji", "👨‍👩‍👧‍👦")
    assert runs[1] == ("text", " fam")


def test_flag_is_one_cluster():
    assert ("emoji", "🇯🇵") in segment_runs("go 🇯🇵")


def test_skin_tone_modifier_kept_with_base():
    assert segment_runs("👋🏽") == [("emoji", "👋🏽")]


def test_keycap_is_one_cluster():
    assert segment_runs("1️⃣") == [("emoji", "1️⃣")]


def test_leading_and_trailing_emoji():
    runs = segment_runs("😀 mid 😅")
    assert runs[0] == ("emoji", "😀")
    assert runs[-1] == ("emoji", "😅")


def test_plain_arrows_not_treated_as_emoji():
    # Curated ranges must not swallow ordinary text symbols.
    assert segment_runs("a -> b") == [("text", "a -> b")]


# ── Width bookkeeping ────────────────────────────────────────

def test_text_width_matches_getlength_without_emoji():
    f = fnt(21)
    for s in ["hello", "a longer line of text", "https://example.com/foo"]:
        assert text_width(s, f) == f.getlength(s)


def test_text_width_adds_one_advance_per_emoji():
    f = fnt(21)
    assert text_width("a👍b", f) == pytest.approx(text_width("ab", f) + emoji_advance(f))


# ── Draw integration (bitmap stubbed → offline & deterministic) ──

def test_emoji_bitmap_is_composited_inline(tmp_path, sample_tweet, monkeypatch):
    MAGENTA = (255, 0, 255)
    monkeypatch.setattr(
        card_renderer, "emoji_bitmap",
        lambda cluster, target_h: Image.new("RGBA", (target_h, target_h), MAGENTA + (255,)),
    )
    tweet = dict(sample_tweet, text="ship it 🚀 now")
    out = tmp_path / "card.png"
    card_renderer.render(tweet, str(out))
    assert bytes(MAGENTA) in Image.open(out).convert("RGB").tobytes()


def test_render_with_emoji_but_no_color_font_does_not_crash(tmp_path, sample_tweet, monkeypatch):
    # No color-emoji font available → emoji fall back to the text font (tofu),
    # and rendering must still succeed.
    monkeypatch.setattr(card_renderer, "emoji_bitmap", lambda cluster, target_h: None)
    tweet = dict(sample_tweet, text="party 🎉🎉🎉 time")
    out = tmp_path / "card.png"
    _, (w, h) = card_renderer.render(tweet, str(out))
    assert out.exists() and w > 0 and h > 0


# Optional: cross-check the regex against the `emoji` library IF it is installed.
# Skipped (never fails the suite) when the optional package is absent.
def test_regex_matches_emoji_lib_when_available():
    emoji = pytest.importorskip("emoji")
    for s in ["hi 👍", "👨‍👩‍👧 fam", "flag 🇯🇵 x", "wave 👋🏽", "plain text"]:
        ours = [run for kind, run in segment_runs(s) if kind == "emoji"]
        theirs = [m["emoji"] for m in emoji.emoji_list(s)]
        assert ours == theirs, s
