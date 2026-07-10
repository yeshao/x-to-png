from card_renderer import expand_urls


def test_none_entities_passthrough():
    assert expand_urls("hello https://t.co/x", None) == "hello https://t.co/x"


def test_empty_text_passthrough():
    assert expand_urls("", {"urls": []}) == ""


def test_url_replaced_with_display_url():
    text = "see https://t.co/abc now"
    entities = {"urls": [{
        "url": "https://t.co/abc",
        "display_url": "example.com/page",
        "expanded_url": "https://example.com/page",
    }]}
    assert expand_urls(text, entities) == "see example.com/page now"


def test_url_falls_back_to_expanded_when_no_display():
    text = "see https://t.co/abc"
    entities = {"urls": [{"url": "https://t.co/abc", "expanded_url": "https://example.com/page"}]}
    assert expand_urls(text, entities) == "see https://example.com/page"


def test_trailing_media_link_stripped():
    text = "nice photo https://t.co/media1"
    entities = {"media": [{"url": "https://t.co/media1", "display_url": "pic.twitter.com/media1"}]}
    assert expand_urls(text, entities) == "nice photo"


def test_multiple_urls_all_replaced():
    text = "a https://t.co/1 b https://t.co/2"
    entities = {"urls": [
        {"url": "https://t.co/1", "display_url": "one.com"},
        {"url": "https://t.co/2", "display_url": "two.com"},
    ]}
    assert expand_urls(text, entities) == "a one.com b two.com"


def test_url_and_media_together():
    text = "read https://t.co/abc pics https://t.co/med"
    entities = {
        "urls": [{"url": "https://t.co/abc", "display_url": "blog.example.com"}],
        "media": [{"url": "https://t.co/med", "display_url": "pic.twitter.com/med"}],
    }
    assert expand_urls(text, entities) == "read blog.example.com pics"


def test_no_matching_entities_leaves_text_unchanged():
    assert expand_urls("plain text, no links", {"urls": [], "media": []}) == "plain text, no links"


def test_malformed_entity_entries_are_skipped():
    # Missing url / label keys must not raise.
    text = "keep https://t.co/abc"
    entities = {"urls": [{"expanded_url": "https://example.com"}], "media": [{}]}
    assert expand_urls(text, entities) == "keep https://t.co/abc"
