import pytest

from card_renderer import parse_input

VALID_ID = "2075218531705037132"


@pytest.mark.parametrize("raw", [
    f"https://x.com/amandaorson/status/{VALID_ID}",
    f"https://twitter.com/amandaorson/status/{VALID_ID}",
    f"https://mobile.twitter.com/amandaorson/status/{VALID_ID}",
    f"https://x.com/amandaorson/status/{VALID_ID}/photo/1",
    f"https://x.com/amandaorson/status/{VALID_ID}?s=20",
    f"https://x.com/amandaorson/status/{VALID_ID}/",
    f"https://x.com/i/web/status/{VALID_ID}",
    VALID_ID,
    f"  {VALID_ID}  ",
])
def test_parse_input_valid(raw):
    assert parse_input(raw) == VALID_ID


@pytest.mark.parametrize("raw", [
    "https://x.com/amandaorson",   # profile URL, no status id
    "not-a-tweet-at-all",
    "12",                          # too short to be a real id
    "1" * 30,                      # too long
    "",
    "abc123",
])
def test_parse_input_invalid_raises(raw):
    with pytest.raises(ValueError):
        parse_input(raw)
