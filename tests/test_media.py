import pytest
from PIL import Image

import card_renderer
from card_renderer import CONTENT_W, MEDIA_MAX_H, _cover, _tweet_from_payload, plan_media


def _img(w, h, color=(120, 90, 200)):
    return Image.new("RGBA", (w, h), color + (255,))


# ── Grid layout (pure) ───────────────────────────────────────

def test_plan_zero_images():
    assert plan_media([], CONTENT_W) == (0, [])


def test_plan_single_landscape_uses_aspect():
    bh, cells = plan_media([(1000, 500)], CONTENT_W)  # 2:1
    assert cells == [(0, 0, CONTENT_W, bh)]
    assert bh == round(CONTENT_W * 500 / 1000)


def test_plan_single_tall_is_capped():
    bh, _ = plan_media([(400, 4000)], CONTENT_W)
    assert bh == MEDIA_MAX_H


@pytest.mark.parametrize("n", [2, 3, 4])
def test_plan_multi_cells_stay_within_block(n):
    bh, cells = plan_media([(800, 600)] * n, CONTENT_W)
    assert len(cells) == n
    for x, y, w, h in cells:
        assert x >= 0 and y >= 0 and w > 0 and h > 0
        assert x + w <= CONTENT_W
        assert y + h <= bh


def test_plan_caps_at_four():
    _, cells = plan_media([(800, 600)] * 9, CONTENT_W)
    assert len(cells) == 4


# ── Cover-fit ────────────────────────────────────────────────

def test_cover_produces_exact_size():
    assert _cover(_img(1000, 200), 300, 300).size == (300, 300)
    assert _cover(_img(50, 900), 400, 250).size == (400, 250)


# ── Compositing + render integration ─────────────────────────

def test_render_media_draws_and_returns_height():
    card = Image.new("RGBA", (CONTENT_W + 20, 700), (0, 0, 0, 0))
    h = card_renderer.render_media(card, [_img(800, 600, (10, 200, 90))], (10, 10), CONTENT_W)
    assert h > 0
    assert bytes((10, 200, 90)) in card.convert("RGB").tobytes()


def test_media_makes_card_taller(tmp_path, monkeypatch, sample_tweet):
    monkeypatch.setattr(card_renderer, "dl_image", lambda u: _img(1200, 675))
    _, (_, h_plain) = card_renderer.render(dict(sample_tweet), str(tmp_path / "a.png"))
    _, (_, h_media) = card_renderer.render(
        dict(sample_tweet, media=["http://x/1.jpg"]), str(tmp_path / "b.png")
    )
    assert h_media > h_plain


def test_failed_media_download_is_skipped(tmp_path, monkeypatch, sample_tweet):
    # dl_image returning None (network failure) must not add a media block or crash.
    monkeypatch.setattr(card_renderer, "dl_image", lambda u: None)
    _, (_, h_plain) = card_renderer.render(dict(sample_tweet), str(tmp_path / "a.png"))
    _, (_, h_media) = card_renderer.render(
        dict(sample_tweet, media=["http://x/broken.jpg"]), str(tmp_path / "b.png")
    )
    assert h_media == h_plain


def test_media_urls_extracted_from_payload(fixture_loader):
    data = fixture_loader("media.json")
    tweet = _tweet_from_payload(data, data["id_str"])
    assert tweet["media"] == [
        "https://pbs.twimg.com/media/aaa.jpg",
        "https://pbs.twimg.com/media/bbb.jpg",
    ]
