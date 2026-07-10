from card_renderer import is_truncated


def test_exactly_280_char_plain_tweet_no_warning():
    # Regression for #1: this used to warn on essentially every fetched tweet.
    assert is_truncated("A" * 280) is False


def test_short_plain_tweet_no_warning():
    assert is_truncated("A" * 100) is False


def test_ellipsis_ending_warns():
    assert is_truncated("This got cut off…") is True


def test_triple_dot_ending_warns():
    assert is_truncated("This got cut off...") is True


def test_over_280_chars_warns():
    assert is_truncated("A" * 281) is True


def test_empty_text_no_warning():
    assert is_truncated("") is False


def test_ellipsis_mid_sentence_not_at_end_no_warning():
    assert is_truncated("Wait… what happened next was wild.") is False
