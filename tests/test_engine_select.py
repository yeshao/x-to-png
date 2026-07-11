import argparse

import pytest

import x_to_png
from card_renderer import _tweet_from_payload


def _args(**kw):
    d = dict(url="https://x.com/u/status/123", output=None, card=False, browser=False,
             auth_token=None, ct0=None, replies=0, retries=1, verbose=False, quiet=False,
             text=None, local=False, force=False)
    d.update(kw)
    return argparse.Namespace(**d)


# ── select_engine (pure) ─────────────────────────────────────

def test_simple_public_tweet_uses_card():
    assert x_to_png.select_engine(_args(), True)[0] == "card"


def test_no_playwright_forces_card():
    assert x_to_png.select_engine(_args(), False)[0] == "card"


def test_replies_route_to_browser():
    assert x_to_png.select_engine(_args(replies=4), True)[0] == "browser"


def test_replies_zero_stays_card():
    assert x_to_png.select_engine(_args(replies=0), True)[0] == "card"


def test_auth_routes_to_browser():
    assert x_to_png.select_engine(_args(auth_token="tok"), True)[0] == "browser"
    assert x_to_png.select_engine(_args(ct0="csrf"), True)[0] == "browser"


def test_article_url_routes_to_browser():
    assert x_to_png.select_engine(_args(url="https://x.com/i/article/99"), True)[0] == "browser"


def test_force_card_wins_even_with_replies():
    assert x_to_png.select_engine(_args(card=True, replies=9), True)[0] == "card"


def test_force_browser_wins_for_simple_tweet():
    assert x_to_png.select_engine(_args(browser=True), True)[0] == "browser"


# ── helpers ──────────────────────────────────────────────────

def test_is_article_url():
    assert x_to_png._is_article_url("https://x.com/i/article/1")
    assert x_to_png._is_article_url("https://x.com/user/article/abc")
    assert not x_to_png._is_article_url("https://x.com/u/status/123")


@pytest.mark.parametrize("val,expected", [(0, False), (1, True), (5, True), ("all", True), (None, False)])
def test_replies_requested(val, expected):
    assert x_to_png._replies_requested(val) is expected


# ── content-based escalation ─────────────────────────────────

def test_insufficient_on_video():
    ok, why = x_to_png._card_insufficient({"text": "hi", "rich": {"video": True}}, None)
    assert ok and "video" in why


def test_insufficient_on_quote():
    ok, why = x_to_png._card_insufficient({"text": "hi", "rich": {"quote": True}}, None)
    assert ok and "quot" in why


def test_insufficient_on_truncation_without_text_override():
    assert x_to_png._card_insufficient({"text": "x" * 281, "rich": {}}, None)[0] is True
    # explicit --text supplies the full text, so truncation is no longer a reason
    assert x_to_png._card_insufficient({"text": "x" * 281, "rich": {}}, "full")[0] is False


def test_plain_tweet_is_sufficient():
    assert x_to_png._card_insufficient({"text": "hello", "rich": {"video": False, "quote": False}}, None)[0] is False


# ── rich flags come out of the payload mapping ───────────────

def test_rich_flags_detected_from_payload():
    data = {
        "id_str": "123456789012345",
        "text": "hi",
        "user": {"name": "A", "screen_name": "a"},
        "mediaDetails": [{"type": "video", "media_url_https": "https://x/v.jpg"}],
        "quoted_tweet": {"id_str": "9"},
    }
    t = _tweet_from_payload(data, "123456789012345")
    assert t["rich"]["video"] is True
    assert t["rich"]["quote"] is True


def test_rich_flags_default_false_for_plain_photo():
    data = {
        "id_str": "123456789012345",
        "text": "hi",
        "user": {"name": "A", "screen_name": "a"},
        "mediaDetails": [{"type": "photo", "media_url_https": "https://x/p.jpg"}],
    }
    t = _tweet_from_payload(data, "123456789012345")
    assert t["rich"] == {"video": False, "quote": False}
