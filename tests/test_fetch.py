import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from card_renderer import FetchError, _tweet_from_payload, dl_avatar, fetch_tweet


def _fake_response(body_bytes):
    resp = MagicMock()
    resp.read.return_value = body_bytes
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


# ── Payload mapping (pure, no network) ──────────────────────

def test_success_payload_mapping(fixture_loader):
    data = fixture_loader("success.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert tweet["display_name"] == "Ada Lovelace"
    assert tweet["handle"] == "@ada"
    assert tweet["verified"] is False
    assert tweet["text"].startswith("Hello world")


def test_avatar_normal_suffix_stripped(fixture_loader):
    data = fixture_loader("success.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert tweet["avatar"] == "https://pbs.twimg.com/profile_images/1/ada.jpg"


def test_verified_payload_mapping(fixture_loader):
    # Regression for #3: badge should only be set when the payload says so.
    data = fixture_loader("verified.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert tweet["verified"] is True


def test_unverified_payload_mapping(fixture_loader):
    data = fixture_loader("unverified.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert tweet["verified"] is False


def test_tombstone_raises_fetch_error(fixture_loader):
    data = fixture_loader("tombstone.json")
    with pytest.raises(FetchError):
        _tweet_from_payload(data, data["id_str"])


def test_entities_unescaped_in_text_and_name(fixture_loader):
    data = fixture_loader("entities.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert "&amp;" not in tweet["text"]
    assert "Tom & Jerry" in tweet["text"]
    assert tweet["display_name"] == "R&D Team"


def test_urls_expanded_and_media_stripped_in_payload(fixture_loader):
    # P3 #16: t.co links become their display_url; trailing media links are removed.
    data = fixture_loader("entities_urls.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert "t.co" not in tweet["text"]
    assert "example.com/blog/wrapping-b…" in tweet["text"]
    assert tweet["text"].endswith("(with pics)")


# ── fetch_tweet (mocked urllib) ──────────────────────────────

@patch("card_renderer.urllib.request.urlopen")
def test_fetch_success(mock_urlopen, fixture_loader):
    data = fixture_loader("success.json")
    mock_urlopen.return_value = _fake_response(json.dumps(data).encode())
    tweet = fetch_tweet(data["id_str"])
    assert tweet["display_name"] == "Ada Lovelace"


@patch("card_renderer.urllib.request.urlopen")
def test_fetch_http_error_raises_clean_fetch_error(mock_urlopen):
    # Regression for #8: used to be a raw HTTPError traceback.
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not Found", hdrs=None, fp=None)
    with pytest.raises(FetchError):
        fetch_tweet("1445078208190291973")


@patch("card_renderer.urllib.request.urlopen")
def test_fetch_url_error_raises_clean_fetch_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")
    with pytest.raises(FetchError):
        fetch_tweet("1445078208190291973")


@patch("card_renderer.urllib.request.urlopen")
def test_fetch_malformed_json_raises_clean_fetch_error(mock_urlopen):
    # Regression for #8: used to be a raw JSONDecodeError traceback.
    mock_urlopen.return_value = _fake_response(b"not json{{{")
    with pytest.raises(FetchError):
        fetch_tweet("1445078208190291973")


@patch("card_renderer.urllib.request.urlopen")
def test_fetch_tombstone_raises_clean_fetch_error(mock_urlopen, fixture_loader):
    # Regression for #8: empty text used to silently render a blank card.
    data = fixture_loader("tombstone.json")
    mock_urlopen.return_value = _fake_response(json.dumps(data).encode())
    with pytest.raises(FetchError):
        fetch_tweet(data["id_str"])


# ── dl_avatar ────────────────────────────────────────────────

def test_dl_avatar_empty_url_returns_none():
    assert dl_avatar("") is None
    assert dl_avatar(None) is None


@patch("card_renderer.urllib.request.urlopen")
def test_dl_avatar_failure_returns_none_and_logs_to_stderr(mock_urlopen, capsys):
    # Regression for #13: avatar failures used to be swallowed silently.
    mock_urlopen.side_effect = Exception("boom")
    result = dl_avatar("https://example.com/avatar.jpg")
    assert result is None
    assert "boom" in capsys.readouterr().err
