#!/usr/bin/env python3
"""x_to_png — Convert an X/Twitter post to a styled PNG card.

Usage:
    x-to-png <tweet_url_or_id> [output_path] [--text "full tweet text"]
             [--local] [--force]

Notes:
    For long tweets (Twitter Blue / note tweets), the syndication API may
    truncate text at ~280 chars. Pass --text with the full text to avoid this.

Examples:
    x-to-png https://x.com/amandaorson/status/2075218531705037132
    x-to-png 2075218531705037132 my-card.png
    x-to-png 2075218531705037132 card.png --text "The full tweet text here..."
"""

import argparse
import functools
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# ── Config ──────────────────────────────────────────────────
CARD_W   = 840
PAD      = 46
GAP      = 14
AV_SIZE  = 60

# Attached-photo grid
MEDIA_GAP    = 6
MEDIA_MAX_H  = 420
MEDIA_RADIUS = 14

BG       = (15, 17, 20)
FG       = (247, 249, 249)
DIM      = (118, 130, 142)
BORDER_C = (39, 44, 51)
BLUE     = (29, 155, 240)
SEP      = (47, 54, 63)

LINE_H          = int(21 * 1.45)
CONTENT_W       = CARD_W - 2 * PAD   # available pixel width for wrapped text
BULLET_INDENT_PX = 24                # indent for wrapped bullet continuation lines

# Fallback font chain. X2PNG_FONT / X2PNG_FONT_BOLD let users override.
_FONT_CANDIDATES = {
    False: [
        os.environ.get("X2PNG_FONT"),
        os.path.expanduser("~/Library/Fonts/HackNerdFont-Regular.ttf"),
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/hack/Hack-Regular.ttf",
    ],
    True: [
        os.environ.get("X2PNG_FONT_BOLD"),
        os.path.expanduser("~/Library/Fonts/HackNerdFont-Bold.ttf"),
        "/System/Library/Fonts/Supplemental/Menlo-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/hack/Hack-Bold.ttf",
    ],
}

# Color-emoji font chain (X2PNG_EMOJI_FONT overrides). Used only for emoji
# glyphs; text still uses the monospace font above. Missing → emoji degrade to
# the monospace fallback (tofu) without error.
_EMOJI_FONT_CANDIDATES = [
    os.environ.get("X2PNG_EMOJI_FONT"),
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
]

ID_RE = re.compile(r"^\d{5,25}$")
BULLET_RE = re.compile(r"^-\s")
CJK_RE = re.compile(
    r"[　-〿぀-ヿ㐀-䶿一-鿿"
    r"豈-﫿＀-￯가-힯]"
)


# Self-contained emoji cluster matcher (no third-party deps). Curated ranges to
# avoid matching plain punctuation/arrows; handles skin-tone modifiers, VS16,
# ZWJ sequences (families/professions), regional-indicator flags, and keycaps.
_EMOJI_BASE = (
    "\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF\U00002700-\U000027BF\U00002B00-\U00002BFF"
    "\U00002300-\U000023FF"
    "\U000000A9\U000000AE\U0000203C\U00002049\U00002122\U00002139"
    "\U00002194-\U00002199\U000021A9\U000021AA\U000024C2\U00003030\U0000303D"
    "\U00003297\U00003299\U00002934\U00002935"
)
_EMOJI_MOD = "[\U0001F3FB-\U0001F3FF\U0000FE0F\U000020E3]"
_RI = "\U0001F1E6-\U0001F1FF"
_EMOJI_CLUSTER_RE = re.compile(
    "(?:"
    r"[0-9#*]\U0000FE0F?\U000020E3"                 # keycap (e.g. 1 in a box)
    f"|[{_RI}][{_RI}]"                               # flag (regional-indicator pair)
    f"|[{_EMOJI_BASE}]{_EMOJI_MOD}*"                 # base (+ skin tone / VS16)
    f"(?:\U0000200D[{_EMOJI_BASE}]{_EMOJI_MOD}*)*"   # ...joined via ZWJ
    ")"
)


class FetchError(Exception):
    """Raised when the tweet can't be fetched or is unusable (deleted, tombstone, etc.)."""


class FontError(Exception):
    """Raised when no usable font can be found."""


# ── Small pure helpers ──────────────────────────────────────

def clean_text(s):
    """Unescape HTML entities (&amp; &lt; &gt; ...) that the syndication API leaves raw."""
    return html.unescape(s) if s else s


def expand_urls(text, entities):
    """Replace opaque t.co links with their human-readable form and strip trailing
    media links, using the syndication payload's `entities` block.

    - `entities.urls[*]`: the t.co `url` is swapped for its `display_url` (the short,
      Twitter-style label like 'example.com/page…'), falling back to `expanded_url`.
    - `entities.media[*]`: the t.co `url` (the attached photo/video/quote link that
      Twitter appends to the end of the text) is removed entirely.

    No-ops safely when `entities` is missing or malformed.
    """
    if not text or not entities:
        return text
    for u in entities.get("urls") or []:
        short = u.get("url")
        label = u.get("display_url") or u.get("expanded_url")
        if short and label:
            text = text.replace(short, label)
    for m in entities.get("media") or []:
        short = m.get("url")
        if short:
            text = text.replace(short, "")
    return text.rstrip()


def is_truncated(text):
    """Heuristic for whether the syndication API likely truncated this tweet.

    A normal (non-Blue) tweet can legitimately be exactly 280 chars, so
    that alone must NOT trigger a warning. We only flag it when the text
    ends in an ellipsis (the API's usual truncation marker) or is strictly
    longer than 280 chars (only possible for long-form / Blue tweets that
    the API has cut short).
    """
    if not text:
        return False
    stripped = text.rstrip()
    if stripped.endswith("…") or stripped.endswith("..."):
        return True
    return len(text) > 280


def format_timestamp(iso_str, local=False):
    """Parse an ISO-8601 timestamp and format it Twitter-style: '6:30 PM · Dec 27, 2025'."""
    if not iso_str:
        return ""
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return iso_str  # unparseable — show as-is rather than crash
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone() if local else dt.astimezone(timezone.utc)
    return dt.strftime("%-I:%M %p · %b %-d, %Y")


def _base36encode(number):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    number = abs(number)
    out = []
    while number:
        number, rem = divmod(number, 36)
        out.append(digits[rem])
    return sign + "".join(reversed(out))


def compute_token(status_id):
    """Best-effort derivation of the syndication API 'token' query param.

    token=0 is known to 404 for many tweet IDs. The commonly-documented
    community formula is base36(floor(id / 1e15 * pi)).
    """
    try:
        n = int(int(status_id) / 1e15 * math.pi)
    except (ValueError, OverflowError):
        n = 0
    return _base36encode(n)


def parse_input(raw):
    """Extract a numeric status ID from a URL or bare ID; raise ValueError if invalid."""
    raw = raw.strip()
    if "x.com/" in raw or "twitter.com/" in raw:
        sid = raw.rstrip("/").split("/status/")[-1].split("/")[0].split("?")[0]
    else:
        sid = raw
    if not ID_RE.match(sid):
        raise ValueError(
            f"'{raw}' doesn't look like a tweet URL or a numeric status ID.\n"
            "Expected e.g. https://x.com/user/status/1234567890123456789 or a bare ID."
        )
    return sid


def _tokenize(text):
    """Split text into wrap tokens. Each CJK character is its own token (no
    spaces needed between them); everything else is split on whitespace."""
    tokens = []
    buf = ""
    for ch in text:
        if CJK_RE.match(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


def _break_long_token(tok, font, max_width):
    """Break a single token wider than `max_width` into character-level chunks,
    each as wide as possible without exceeding `max_width`. Splitting adds no
    characters, so ''.join(result) == tok. A lone character wider than max_width
    is emitted on its own line (it can't be split any further)."""
    chunks = []
    cur = ""
    for ch in tok:
        if cur and text_width(cur + ch, font) > max_width:
            chunks.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        chunks.append(cur)
    return chunks


def wrap_by_width(text, font, max_width):
    """Greedy word-wrap `text` to fit within `max_width` px, measured with `font`.

    A single token longer than `max_width` (e.g. a long URL with no spaces) is
    broken at the character level so it can't overflow the card.
    """
    tokens = _tokenize(text)
    if not tokens:
        return [""]
    lines = []
    current = ""
    for tok in tokens:
        if current:
            glue = "" if (CJK_RE.match(current[-1]) and CJK_RE.match(tok)) else " "
            candidate = f"{current}{glue}{tok}"
        else:
            candidate = tok
        if text_width(candidate, font) <= max_width:
            current = candidate
            continue
        # `tok` doesn't fit on the current line — flush the line first.
        if current:
            lines.append(current)
            current = ""
        if text_width(tok, font) <= max_width:
            current = tok
        else:
            *full, last = _break_long_token(tok, font, max_width)
            lines.extend(full)
            current = last
    lines.append(current)
    return lines


def wrap_text(tweet_text, font, max_width=CONTENT_W):
    """Wrap tweet text into (kind, line) pairs for rendering.

    kind is one of: 'blank', 'text', 'bullet', 'bullet_cont'.
    Bullets get the glyph on their first line only; continuations are
    hanging-indented (rendered at ax + BULLET_INDENT_PX) with no glyph.
    """
    lines = []
    bullet_prefix_w = font.getlength("• ")
    for para in tweet_text.split("\n"):
        stripped = para.strip()
        if stripped == "":
            lines.append(("blank", ""))
        elif BULLET_RE.match(stripped):
            content = stripped[1:].strip()
            avail = max(min(max_width - bullet_prefix_w, max_width - BULLET_INDENT_PX), 10)
            wrapped = wrap_by_width(content, font, avail)
            for i, ln in enumerate(wrapped):
                if i == 0:
                    lines.append(("bullet", f"• {ln}"))
                else:
                    lines.append(("bullet_cont", ln))
        else:
            for ln in wrap_by_width(para, font, max_width):
                lines.append(("text", ln))
    return lines


# ── Font handling ───────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def fnt(size, bold=False):
    for path in _FONT_CANDIDATES[bold]:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise FontError(
        "No usable font found. Install Hack Nerd Font at ~/Library/Fonts/, "
        "or set X2PNG_FONT (and optionally X2PNG_FONT_BOLD) to a .ttf/.ttc path."
    )


# ── Emoji ───────────────────────────────────────────────────

def segment_runs(text):
    """Split `text` into ordered runs of ('text', s) and ('emoji', cluster).

    Pure/offline (regex-based). An emoji cluster keeps its skin-tone modifiers,
    VS16, ZWJ joins and flag pairs together so it renders as one glyph.
    """
    if not text:
        return []
    runs = []
    i = 0
    for m in _EMOJI_CLUSTER_RE.finditer(text):
        a, b = m.start(), m.end()
        if a > i:
            runs.append(("text", text[i:a]))
        runs.append(("emoji", text[a:b]))
        i = b
    if i < len(text):
        runs.append(("text", text[i:]))
    return runs or [("text", text)]


def emoji_advance(font):
    """Horizontal space one emoji occupies. Kept in lockstep between wrapping
    (`text_width`) and drawing (`draw_runs`) so mixed lines never overflow."""
    return int(round(font.size * 1.3))


def text_width(s, font):
    """Pixel width of `s` counting emoji clusters at `emoji_advance`. Exactly
    equals `font.getlength(s)` when `s` has no emoji, so plain-text layout is
    unchanged."""
    total = 0.0
    for kind, run in segment_runs(s):
        total += font.getlength(run) if kind == "text" else emoji_advance(font)
    return total


@functools.lru_cache(maxsize=None)
def _emoji_font():
    """Load a color-emoji font at a usable bitmap strike. Returns (font, strike)
    or (None, 0) when none is installed (caller then falls back to text)."""
    for path in _EMOJI_FONT_CANDIDATES:
        if not path or not os.path.exists(path):
            continue
        for strike in (137, 160, 136, 128, 109, 96, 64, 48, 32):
            try:
                return ImageFont.truetype(path, strike), strike
            except OSError:
                continue
    return None, 0


def emoji_bitmap(cluster, target_h):
    """Render one emoji `cluster` to an RGBA image ~`target_h` px tall, or None
    if no color-emoji font is available."""
    font, strike = _emoji_font()
    if font is None:
        return None
    try:
        box = strike * 2
        canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), cluster, font=font, embedded_color=True)
        bbox = canvas.getbbox()
        if bbox is None:
            return None
        glyph = canvas.crop(bbox)
        scale = target_h / glyph.height
        return glyph.resize((max(1, round(glyph.width * scale)), target_h), Image.LANCZOS)
    except Exception:
        return None


def draw_runs(img, draw, xy, text, fill, font):
    """Draw `text` at `xy`, pasting color emoji inline. Advances by the same
    per-run widths `text_width` uses, so drawing and wrapping stay aligned.
    Returns the final x cursor."""
    x, y = xy
    adv = emoji_advance(font)
    eh = int(round(font.size * 1.15))
    for kind, run in segment_runs(text):
        if kind == "text":
            draw.text((x, y), run, fill=fill, font=font)
            x += font.getlength(run)
        else:
            bmp = emoji_bitmap(run, eh)
            if bmp is not None:
                oy = int(round(y + (font.size - bmp.height) / 2))
                img.paste(bmp, (int(round(x)), oy), bmp)
            else:
                draw.text((x, y), run, fill=fill, font=font)  # tofu fallback
            x += adv
    return x


# ── Network ─────────────────────────────────────────────────

def dl_avatar(url):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=10).read()
        return Image.open(BytesIO(data)).convert("RGBA").resize((AV_SIZE, AV_SIZE), Image.LANCZOS)
    except Exception as e:
        print(f"⚠️  Could not download avatar: {e}", file=sys.stderr)
        return None


def _tweet_from_payload(data, status_id):
    """Map a syndication API JSON payload into our internal tweet dict."""
    user = data.get("user", {}) or {}
    raw = data.get("text", "") or ""
    if not raw.strip():
        raise FetchError(f"Tweet {status_id} has no text — it may be deleted or a tombstone.")
    text = clean_text(expand_urls(raw, data.get("entities")))
    media = []
    for m in (data.get("mediaDetails") or []):
        u = m.get("media_url_https") or m.get("media_url")
        if u:
            media.append(u)
    return {
        "display_name": clean_text(user.get("name", "Unknown")),
        "handle": "@" + user.get("screen_name", "unknown"),
        "avatar": (user.get("profile_image_url_https", "") or "").replace("_normal", ""),
        "text": text,
        "timestamp": data.get("created_at", ""),
        "verified": bool(user.get("is_blue_verified") or user.get("verified")),
        "media": media[:4],
    }


def fetch_tweet(status_id, base_url="https://cdn.syndication.twimg.com"):
    """Fetch tweet metadata via the Twitter syndication API (no auth needed)."""
    token = compute_token(status_id)
    url = f"{base_url}/tweet-result?id={status_id}&token={token}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        raise FetchError(
            f"Tweet {status_id} could not be fetched (HTTP {e.code}). "
            "It may be deleted, protected, or the ID may be wrong."
        ) from e
    except urllib.error.URLError as e:
        raise FetchError(f"Network error fetching tweet {status_id}: {e.reason}") from e
    except TimeoutError as e:
        raise FetchError(f"Timed out fetching tweet {status_id}.") from e

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise FetchError(f"Unexpected (non-JSON) response for tweet {status_id}.") from e

    return _tweet_from_payload(data, status_id)


# ── Media (attached photos) ─────────────────────────────────

def dl_image(url):
    """Download an image (photo or video thumbnail) as RGBA, or None on failure."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=15).read()
        return Image.open(BytesIO(data)).convert("RGBA")
    except Exception as e:
        print(f"⚠️  Could not download media: {e}", file=sys.stderr)
        return None


def _cover(im, w, h):
    """Resize + center-crop `im` to exactly (w, h) — CSS object-fit: cover."""
    w, h = max(1, w), max(1, h)
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    rw, rh = max(w, round(sw * scale)), max(h, round(sh * scale))
    im = im.resize((rw, rh), Image.LANCZOS)
    left, top = (rw - w) // 2, (rh - h) // 2
    return im.crop((left, top, left + w, top + h))


def plan_media(sizes, total_w=CONTENT_W):
    """Given the (w, h) sizes of 1–4 images, return (block_h, [cells]) where each
    cell is (x, y, w, h) inside a `total_w`-wide block — a Twitter-style grid."""
    n = len(sizes)
    g = MEDIA_GAP
    if n == 0:
        return 0, []
    if n == 1:
        w, h = sizes[0]
        bh = max(1, min(round(total_w * h / w), MEDIA_MAX_H)) if w else MEDIA_MAX_H
        return bh, [(0, 0, total_w, bh)]
    bh = min(round(total_w * 9 / 16), MEDIA_MAX_H)
    cw = (total_w - g) // 2
    rw = total_w - cw - g
    if n == 2:
        return bh, [(0, 0, cw, bh), (cw + g, 0, rw, bh)]
    ch = (bh - g) // 2
    bch = bh - ch - g
    if n == 3:
        return bh, [(0, 0, cw, bh), (cw + g, 0, rw, ch), (cw + g, ch + g, rw, bch)]
    return bh, [
        (0, 0, cw, ch), (cw + g, 0, rw, ch),
        (0, ch + g, cw, bch), (cw + g, ch + g, rw, bch),
    ]


def render_media(card, images, origin, total_w=CONTENT_W):
    """Composite up to 4 `images` as a rounded grid onto `card` at `origin`.
    Returns the block height (0 if no images)."""
    images = images[:4]
    block_h, cells = plan_media([im.size for im in images], total_w)
    if not cells:
        return 0
    block = Image.new("RGBA", (total_w, block_h), (0, 0, 0, 0))
    for im, (cx, cy, cw, ch) in zip(images, cells):
        block.paste(_cover(im, cw, ch), (cx, cy))
    mask = Image.new("L", (total_w, block_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (total_w - 1, block_h - 1)], radius=MEDIA_RADIUS, fill=255
    )
    card.paste(block, origin, mask)
    return block_h


# ── Rendering ───────────────────────────────────────────────

def render(tweet, output_path, local_time=False):
    avatar = dl_avatar(tweet.get("avatar"))
    body_font = fnt(21)
    all_lines = wrap_text(tweet["text"], body_font, CONTENT_W)
    body_h  = len(all_lines) * LINE_H
    HEADER  = AV_SIZE + GAP + 6
    FOOTER  = 36 + 28 + 16

    # Attached photos (downloaded up-front so the card height can account for them).
    media_imgs = [im for im in (dl_image(u) for u in (tweet.get("media") or [])[:4]) if im]
    media_block_h = plan_media([im.size for im in media_imgs], CONTENT_W)[0] if media_imgs else 0
    media_h = (GAP + media_block_h) if media_block_h else 0

    H = PAD + HEADER + body_h + media_h + FOOTER

    # Transparent base; background only fills the rounded-rect mask so
    # corners outside the radius stay fully transparent.
    img = Image.new("RGBA", (CARD_W, H), (0, 0, 0, 0))
    bg_layer = Image.new("RGBA", (CARD_W, H), BG + (255,))
    mask = Image.new("L", (CARD_W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (CARD_W - 1, H - 1)], radius=14, fill=255)
    img.paste(bg_layer, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (CARD_W - 1, H - 1)], radius=14, outline=BORDER_C, width=1)

    # Avatar
    ay = ax = PAD
    if avatar:
        av_mask = Image.new("L", (AV_SIZE, AV_SIZE), 0)
        ImageDraw.Draw(av_mask).ellipse((0, 0, AV_SIZE, AV_SIZE), fill=255)
        img.paste(avatar, (ax, ay), av_mask)
    else:
        draw.ellipse((ax, ay, ax + AV_SIZE, ay + AV_SIZE), fill=(60, 66, 73))

    # Name + badge (only for actually-verified accounts)
    name_font = fnt(22, True)
    tx = ax + AV_SIZE + GAP
    ty = ay + 4
    draw_runs(img, draw, (tx, ty), tweet["display_name"], FG, name_font)
    if tweet.get("verified"):
        nm_w = text_width(tweet["display_name"], name_font) + 8
        bx, by = tx + nm_w, ty + 2
        draw.ellipse((bx, by, bx + 22, by + 22), fill=BLUE)
        draw.line([(bx + 7, by + 11), (bx + 10, by + 14), (bx + 16, by + 8)], fill=(255, 255, 255), width=2)

    # Handle
    ty += 28
    draw_runs(img, draw, (tx, ty), tweet["handle"], DIM, fnt(19))

    # Body
    y = PAD + HEADER + 2
    for kind, line in all_lines:
        if kind == "blank":
            y += LINE_H // 2
        elif kind == "bullet_cont":
            draw_runs(img, draw, (ax + BULLET_INDENT_PX, y), line, FG, body_font)
            y += LINE_H
        else:
            draw_runs(img, draw, (ax, y), line, FG, body_font)
            y += LINE_H

    # Attached photos
    if media_imgs:
        y += GAP
        y += render_media(img, media_imgs, (ax, y), CONTENT_W)

    # Separator + timestamp
    sep_y = y + 8
    draw.line([(PAD, sep_y), (CARD_W - PAD, sep_y)], fill=SEP, width=1)
    ts = format_timestamp(tweet.get("timestamp", ""), local=local_time)
    draw.text((PAD, sep_y + 10), ts, fill=DIM, font=fnt(16))

    # Watermark
    wm = "x-to-png"
    wm_font = fnt(13)
    wm_w = wm_font.getlength(wm)
    draw.text((CARD_W - PAD - wm_w, H - PAD + 4), wm, fill=(55, 60, 66), font=wm_font)

    img.save(output_path, "PNG")
    return output_path, (CARD_W, H)


# ── CLI ─────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="x-to-png",
        description="Convert an X/Twitter post to a styled PNG card.",
        epilog=(
            "Examples:\n"
            "  x-to-png https://x.com/amandaorson/status/2075218531705037132\n"
            "  x-to-png 2075218531705037132 my-card.png\n"
            "  x-to-png 2075218531705037132 card.png --text \"The full tweet text here...\"\n\n"
            "Notes:\n"
            "  For long tweets (Twitter Blue / note tweets), the syndication API may\n"
            "  truncate text at ~280 chars. Pass --text with the full text to avoid this."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url_or_id", help="Tweet URL or numeric status ID")
    parser.add_argument("output", nargs="?", default=None,
                         help="Output PNG path (default: tweet_<id>.png)")
    parser.add_argument("--text", default=None, help="Full tweet text (bypasses truncation)")
    parser.add_argument("--local", action="store_true",
                         help="Render the timestamp in local time instead of UTC")
    parser.add_argument("--force", action="store_true",
                         help="Overwrite the output file if it already exists")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        status_id = parse_input(args.url_or_id)
    except ValueError as e:
        parser.error(str(e))
        return  # unreachable; parser.error() exits

    out = args.output or f"tweet_{status_id}.png"

    if os.path.exists(out) and not args.force:
        print(f"❌ {out} already exists. Pass --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    try:
        fnt(21)  # fail early with a clear message if no usable font
    except FontError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("X2PNG_BASE_URL", "https://cdn.syndication.twimg.com")
    try:
        tweet = fetch_tweet(status_id, base_url=base_url)
    except FetchError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    if args.text:
        tweet["text"] = clean_text(args.text)
    elif is_truncated(tweet["text"]):
        print(
            "⚠️  Tweet text may be truncated (long tweet / Twitter Blue)\n"
            "   Tip: pass --text \"...\" with the full text",
            file=sys.stderr,
        )

    print(f"{tweet['display_name']} {tweet['handle']}: {len(tweet['text'])} chars")
    _, (w, h) = render(tweet, out, local_time=args.local)
    print(f"✅ {out}  ({w} × {h} px)")


if __name__ == "__main__":
    main()
