from card_renderer import clean_text


def test_amp():
    assert clean_text("Tom &amp; Jerry") == "Tom & Jerry"


def test_lt_gt():
    assert clean_text("5 &lt; 10 &gt; 2") == "5 < 10 > 2"


def test_mixed_entities():
    assert clean_text("Tom &amp; Jerry: 5 &lt; 10 &gt; 2, &quot;quoted&quot;") == \
        'Tom & Jerry: 5 < 10 > 2, "quoted"'


def test_no_entities_unchanged():
    assert clean_text("plain text") == "plain text"


def test_empty_string():
    assert clean_text("") == ""


def test_none_passthrough():
    assert clean_text(None) is None
