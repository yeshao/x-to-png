from card_renderer import format_timestamp


def test_with_milliseconds_utc():
    result = format_timestamp("2025-12-27T18:30:00.000Z")
    assert result == "6:30 PM · Dec 27, 2025"


def test_without_milliseconds_utc():
    result = format_timestamp("2025-12-27T18:30:00Z")
    assert result == "6:30 PM · Dec 27, 2025"


def test_empty_string_returns_empty():
    assert format_timestamp("") == ""


def test_invalid_string_returns_as_is():
    # Regression: must not crash on garbage input.
    assert format_timestamp("not-a-timestamp") == "not-a-timestamp"


def test_local_flag_does_not_crash_and_returns_nonempty():
    result = format_timestamp("2025-12-27T18:30:00.000Z", local=True)
    assert result  # exact wall-clock value depends on the test machine's tz
    assert "·" in result
