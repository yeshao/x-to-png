#!/usr/bin/env python3
"""
X/Twitter Post to PNG Converter
================================
Converts an X post (tweet, article, thread) into a single-column PNG image.

Usage:
    python3 x_to_png.py <url> [output_path] [--auth-token TOKEN] [--ct0 CT0] [--verbose] [--quiet]

Examples:
    python3 x_to_png.py "https://x.com/user/status/123456"
    python3 x_to_png.py "https://x.com/user/status/123456" my_screenshot.png
    python3 x_to_png.py "https://x.com/user/status/123456" --auth-token abc123 --ct0 xyz789 --verbose

Requirements:
    pip install playwright pillow
    playwright install chromium

Auth:
    The script loads X_AUTH_TOKEN and X_CT0 from ~/.zshrc automatically.
    You can also pass them via CLI flags or environment variables.
    Auth is required for X Articles, private posts, and full reply threads.

    To set up, add to ~/.zshrc:
        export X_AUTH_TOKEN="your_auth_token"
        export X_CT0="your_ct0_token"
    Then run: source ~/.zshrc
"""

from pathlib import Path

import argparse
import json
import os
import sys
import tempfile
import time

from PIL import Image
from playwright.sync_api import sync_playwright


# ---------------------------------------------------------------------------
# Auth token loading
# ---------------------------------------------------------------------------


def _parse_zshrc_env(filepath):
    """Parse export KEY="VALUE" or export KEY='VALUE' lines from a shell rc file."""
    env_vars = {}
    if not os.path.isfile(filepath):
        return env_vars
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    decl = line[len("export ") :]
                    if "=" in decl:
                        key, _, raw = decl.partition("=")
                        val = raw.strip().strip('"').strip("'")
                        env_vars[key] = val
    except (OSError, UnicodeDecodeError):
        pass
    return env_vars


def load_x_auth_from_zshrc():
    """Return (auth_token, ct0) from ~/.zshrc exports, filling env vars as side effect."""
    zshrc_path = os.path.expanduser("~/.zshrc")
    parsed = _parse_zshrc_env(zshrc_path)
    auth_token = parsed.get("X_AUTH_TOKEN", "")
    ct0 = parsed.get("X_CT0", "")
    # Also propagate to os.environ so child processes and future calls see them
    if auth_token and not os.environ.get("X_AUTH_TOKEN"):
        os.environ["X_AUTH_TOKEN"] = auth_token
    if ct0 and not os.environ.get("X_CT0"):
        os.environ["X_CT0"] = ct0
    return auth_token or None, ct0 or None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def log_info(msg, verbose=True):
    if verbose:
        print(msg)


def log_warn(msg):
    print(f"WARNING: {msg}", file=sys.stderr)


def log_error(msg):
    print(f"ERROR: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def validate_url(url):
    url_lower = url.lower()
    valid_domains = ["x.com", "twitter.com", "mobile.x.com", "mobile.twitter.com"]
    if not any(domain in url_lower for domain in valid_domains):
        raise ValueError(f"URL doesn't appear to be an X/Twitter post: {url}")
    if (
        "/status/" not in url_lower
        and "/article/" not in url_lower
        and "/i/" not in url_lower
    ):
        raise ValueError(
            f"URL doesn't contain a post path (/status/, /article/, /i/): {url}"
        )


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------


def get_content_column_html_length(page):
    result = page.evaluate("""
        (function() {
            var main = document.querySelector('main');
            if (!main) return -1;
            if (!main.children[0]) return 0;
            return main.children[0].innerHTML.length;
        })()
    """)
    return result


def get_content_column_dims(page):
    raw = page.evaluate("""
    (function() {
        var main = document.querySelector('main');
        if (!main) return JSON.stringify({error: 'no main element found'});
        if (!main.children[0]) return JSON.stringify({error: 'main has no children'});
        var contentCol = main.children[0];
        var contentRect = contentCol.getBoundingClientRect();
        return JSON.stringify({
            contentX: Math.round(contentRect.left),
            contentW: Math.round(contentRect.width),
        });
    })()
    """)
    try:
        dims = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as err:
        raise RuntimeError(f"Failed to parse content column dims: {raw!r}") from err
    if "error" in dims:
        raise RuntimeError(dims["error"])
    return dims["contentX"], dims["contentW"]


def wait_for_content(page, timeout=180, verbose=True):
    log_info("Waiting for content to load...", verbose)
    start = time.time()
    prev_len = 0
    stable_count = 0

    for _ in range(timeout // 2):
        time.sleep(2)
        content_len = get_content_column_html_length(page)
        try:
            elapsed = int(time.time() - start)
        except (OSError, OverflowError):
            elapsed = 0

        if content_len == -1:
            log_info(f"  [{elapsed}s] Waiting for page structure...", verbose)
            continue

        if content_len > 50000:
            log_info(
                f"  [{elapsed}s] Content fully loaded ({content_len:,} bytes)", verbose
            )
            return content_len, elapsed

        if content_len == prev_len and content_len > 10000:
            stable_count += 1
            if stable_count >= 5:
                log_info(
                    f"  [{elapsed}s] Content stabilized at {content_len:,} bytes",
                    verbose,
                )
                return content_len, elapsed
        elif content_len != prev_len:
            stable_count = 0
        prev_len = content_len
        log_info(f"  [{elapsed}s] html={content_len:,}", verbose)

    content_len = get_content_column_html_length(page)
    try:
        return content_len, int(time.time() - start)
    except (OSError, OverflowError):
        return content_len, 0


# ---------------------------------------------------------------------------
# DOM-based boundary detection
# ---------------------------------------------------------------------------


def detect_discovery_more_vision(screenshot_path, verbose=True):
    """Use NVIDIA Llama 90b vision model to detect Discovery more boundary."""
    try:
        import base64 as b64mod
        import io as iomod
        import json as jsonmod
        import urllib.request as urlreq
        from PIL import Image as PILImage
    except ImportError:
        return -1

    try:
        img = PILImage.open(screenshot_path)
        img_resized = img.resize((400, int(400 * img.height / img.width)))
        buf = iomod.BytesIO()
        img_resized.save(buf, format="JPEG", quality=70)
        img_b64 = b64mod.b64encode(buf.getvalue()).decode()

        api_key = os.environ.get("NVIDIA_API_KEY", "")
        if not api_key:
            zshrc = os.path.expanduser("~/.zshrc")
            if os.path.exists(zshrc):
                with open(zshrc) as f:
                    for line in f:
                        if "NVIDIA_API_KEY" in line and "export" in line:
                            api_key = line.split("=")[1].strip().strip('"').strip("'")
                            break
        if not api_key:
            return -1

        payload = {
            "model": "meta/llama-3.2-90b-vision-instruct",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        },
                        {
                            "type": "text",
                            "text": 'X/Twitter article screenshot. Look for "Discovery more" or "Show more" section AFTER the article (near bottom). Reply ONLY JSON: {"has_discovery_more": "yes" or "no", "start_pct": "X%"} where start_pct is % from TOP of image.',
                        },
                    ],
                }
            ],
            "max_tokens": 50,
            "temperature": 0,
        }

        req = urlreq.Request(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            data=jsonmod.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlreq.urlopen(req, timeout=120) as resp:
            result = jsonmod.loads(resp.read())
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            data = jsonmod.loads(content)
            if data.get("has_discovery_more") == "yes":
                pct = int(str(data["start_pct"]).replace("%", ""))
                y_pos = int(img.height * pct / 100)
                log_info(f"Vision: Discovery more at {pct}% (y={y_pos})", verbose)
                return y_pos
            return -1
    except Exception as e:
        log_info(f"Vision detection failed: {e}", verbose)
        return -1


def last_reply_index(replies, article_count):
    """Index of the last <article> to include in the screenshot.

    replies=0 -> just the main post (index 0), matching the original
    crop-at-end-of-post behavior. replies=N -> the main post plus up to
    N reply articles (index N), clamped to the number of articles that
    actually exist. Returns -1 when there are no articles.
    """
    if article_count <= 0:
        return -1
    return min(replies, article_count - 1)


def scroll_to_load_replies(page, target_count, max_scrolls=60, verbose=True):
    """Scroll down incrementally so X's virtualized list renders reply
    articles into the DOM. Stops once at least ``target_count`` <article>
    elements exist, or when scrolling stops producing new articles.
    """
    log_info(f"Loading replies (target {target_count} articles)...", verbose)
    prev_count = 0
    stable = 0
    for i in range(max_scrolls):
        count = page.evaluate("document.querySelectorAll('article').length")
        if count >= target_count:
            log_info(f"  [{i}] {count} articles loaded", verbose)
            return count
        if count == prev_count:
            stable += 1
            if stable >= 6:
                log_info(f"  [{i}] article count stalled at {count}", verbose)
                return count
        else:
            stable = 0
            log_info(f"  [{i}] {count} articles", verbose)
        prev_count = count
        page.evaluate("window.scrollBy(0, 900)")
        page.wait_for_timeout(500)
    return prev_count


def expand_show_more(page, last_idx, max_rounds=3, verbose=True):
    """Click every 'Show more' button inside articles[0..last_idx] so
    truncated reply text fully expands before the screenshot.

    X renders long replies with a 'Show more' control (data-testid
    'tweet-text-show-more') that expands the text inline. Without clicking,
    the screenshot captures truncated text. Runs in rounds because one
    expansion can reveal a nested affordance; stops when a round clicks
    nothing. Returns the total number of clicks.
    """
    js = """
    (function() {
        var articles = document.querySelectorAll('article');
        var lastIdx = Math.min(LASTIDX, articles.length - 1);
        var clicked = [];
        function isActionable(el) {
            if (!el) return false;
            if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') return true;
            var tid = el.getAttribute('data-testid');
            return tid && tid.indexOf('show') !== -1;
        }
        function alreadyClicked(target) {
            for (var k = 0; k < clicked.length; k++) {
                if (clicked[k] === target || clicked[k].contains(target) || target.contains(clicked[k])) return true;
            }
            return false;
        }
        for (var i = 0; i <= lastIdx; i++) {
            var all = articles[i].querySelectorAll('*');
            for (var j = 0; j < all.length; j++) {
                var el = all[j];
                var t = (el.textContent || '').trim().toLowerCase();
                if (t !== 'show more') continue;
                if (el.children.length > 0) continue;  // only match leaf labels
                // The label is often a plain <span>; the click handler
                // lives on a BUTTON/role=button ancestor. Walk up to it.
                var target = el;
                if (!isActionable(el)) {
                    var anc = el.parentElement;
                    for (var k = 0; k < 8 && anc; k++) {
                        if (isActionable(anc)) { target = anc; break; }
                        anc = anc.parentElement;
                    }
                }
                if (!isActionable(target)) continue;
                if (alreadyClicked(target)) continue;
                target.click();
                clicked.push(target);
            }
        }
        return clicked.length;
    })()
    """
    total = 0
    for r in range(max_rounds):
        n = page.evaluate(js.replace("LASTIDX", str(last_idx)))
        if n == 0:
            break
        total += n
        log_info(f"  Expanded {n} 'Show more' (round {r + 1})", verbose)
        page.wait_for_timeout(800)
    return total


def expand_show_more_replies(page, max_rounds=5, verbose=True):
    """Click 'Show more replies' / 'Show additional replies' buttons
    that appear between tweets in a conversation thread to load more
    replies. These are different from the per-tweet text 'Show more'.

    X shows these buttons when there are more replies to load between
    the main tweet and the reply list. Without clicking, scrolling
    alone may not load all replies. Runs in rounds because each click
    can reveal another button. Returns the total number of clicks.
    """
    js = """
    (function() {
        var clicked = 0;
        var buttons = document.querySelectorAll('[role="button"], button');
        for (var i = 0; i < buttons.length; i++) {
            var el = buttons[i];
            var text = (el.textContent || '').trim().toLowerCase();
            // Match "show more replies", "show additional replies",
            // "show more" that is NOT inside an article (those are
            // handled by expand_show_more)
            if (text.indexOf('show') === -1) continue;
            if (text.indexOf('more') === -1) continue;
            // Skip if inside an article (those are text-expand buttons)
            if (el.closest('article')) continue;
            // Skip if it's a "Discover more" or "Show more" in the sidebar
            var rect = el.getBoundingClientRect();
            if (rect.width < 80 || rect.height < 20) continue;
            el.click();
            clicked++;
        }
        return clicked;
    })()
    """
    total = 0
    for r in range(max_rounds):
        n = page.evaluate(js)
        if n == 0:
            break
        total += n
        log_info(f"  Clicked {n} 'Show more replies' (round {r + 1})", verbose)
        page.wait_for_timeout(1500)
    return total


def find_post_boundary_y(page, replies=0):
    """
    Use DOM queries to find the absolute page-Y position where the content
    to keep ends and recommendations begin. Must be called AFTER the final
    viewport resize so coordinates match the full-page screenshot.

    replies=0 crops at the end of the main post (articles[0]); replies=N
    extends the boundary to include the first N reply articles
    (articles[1..N]). Returns Y position (page coordinates) or -1.
    """
    js = """
    (function() {
        function pageBottom(el) {
            var r = el.getBoundingClientRect();
            return Math.round(r.bottom + window.scrollY);
        }
        function pageTop(el) {
            var r = el.getBoundingClientRect();
            return Math.round(r.top + window.scrollY);
        }

        // Strategy 1: The main post (tweet or full Article, including the
        // "Want to publish your own Article?" banner) is the first <article>
        // element. With replies=0 everything after it is cropped; with
        // replies=N the first N reply articles are kept as well.
        var articles = document.querySelectorAll('article');
        if (articles.length > 0) {
            var lastIdx = Math.min(REPLIES, articles.length - 1);
            var bottom = pageBottom(articles[lastIdx]);
            if (bottom > 300) {
                // Cap at the top of the next article in case of overlap
                if (articles.length > lastIdx + 1) {
                    var nextTop = pageTop(articles[lastIdx + 1]);
                    if (nextTop > bottom) bottom = Math.min(bottom + 20, nextTop);
                }
                return bottom;
            }
        }

        // Strategy 2: Find the last "Show more" / "Discover more" text
        // that is a leaf node (not a container) and is well below the nav
        var allElements = document.querySelectorAll('*');
        var candidates = [];
        for (var i = 0; i < allElements.length; i++) {
            var el = allElements[i];
            var text = el.textContent.trim();
            var textLower = text.toLowerCase();
            if ((textLower === 'discover more' || textLower === 'show more' || textLower === 'view more')
                && el.children.length === 0) {
                var rect = el.getBoundingClientRect();
                if (rect.top + window.scrollY > 500 && rect.height > 10 && rect.width > 30) {
                    candidates.push(Math.round(rect.top + window.scrollY));
                }
            }
        }
        if (candidates.length > 0) {
            candidates.sort(function(a, b) { return b - a; });
            return candidates[0];
        }

        // Strategy 3: Look for role="separator" or hr elements below the article
        var separators = document.querySelectorAll('[role="separator"], hr');
        for (var i = 0; i < separators.length; i++) {
            var top = pageTop(separators[i]);
            if (top > 1000) {
                return top;
            }
        }

        return -1;
    })()
    """
    result = page.evaluate(js.replace("REPLIES", str(replies)))
    return result


# ---------------------------------------------------------------------------
# Pixel analysis helpers
# ---------------------------------------------------------------------------


def find_content_horizontal_bounds(img, min_block_width=40, merge_gap=15):
    """Find the right edge of the main (center) content column.

    The center timeline column and the right-side panel (trends / who-to-
    follow) may both carry content, but the center column is the first WIDE
    dense block reading left-to-right. We crop at its right edge, which
    drops the right panel regardless of how dense it is. Blocks split by a
    tiny internal dip (narrower than ``merge_gap``) are merged first so a
    1-2px sparse seam inside the column can't truncate it.
    """
    w, h = img.size
    step = max(1, h // 1000)

    col_scores = []
    for cx in range(w):
        non_white = 0
        for cy in range(0, h, step):
            px = img.getpixel((cx, cy))
            if sum(px[:3]) / 3 < 245:
                non_white += 1
        col_scores.append(non_white)

    max_score = max(col_scores) if col_scores else 0
    if max_score == 0:
        return w

    content_threshold = max_score * 0.10

    # Collect maximal runs of columns at or above the content threshold.
    runs = []
    start = None
    for cx in range(w):
        if col_scores[cx] >= content_threshold:
            if start is None:
                start = cx
        elif start is not None:
            runs.append([start, cx])
            start = None
    if start is not None:
        runs.append([start, w])

    # Merge runs separated by a gap smaller than merge_gap so a thin internal
    # seam inside the center column doesn't split it into two blocks.
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))

    # The center column is the first run wide enough to be real content.
    for s, e in merged:
        if e - s >= min_block_width:
            return e

    # No wide block found: fall back to the rightmost dense column.
    for cx in range(w - 1, -1, -1):
        if col_scores[cx] >= content_threshold:
            return cx + 1

    return w


def find_content_vertical_bounds(img, probe_x=None):
    """Find top and bottom content boundaries."""
    w, h = img.size
    if probe_x is None:
        probe_x = w // 2
    probe_x = min(probe_x, w - 1)

    content_top = 0
    for cy in range(h):
        px = img.getpixel((probe_x, cy))
        if sum(px[:3]) / 3 < 245:
            content_top = cy
            break

    content_bottom = h
    for cy in range(h - 1, -1, -1):
        px = img.getpixel((probe_x, cy))
        if sum(px[:3]) / 3 < 245:
            content_bottom = cy + 1
            break

    return content_top, content_bottom


def trim_recommendations(img, min_gap=100, min_density=200):
    """
    Detect and trim the post-article recommendations section.

    Strategy: find the largest gap (consecutive rows with fewer than
    min_density non-white pixels) in the lower 60% of the image. If the
    gap is at least min_gap rows tall, it indicates the boundary between
    the article and the recommendations section. Crop just above it.

    For thread posts where replies are interleaved with article text,
    gaps are small and no trimming happens (which is correct).
    """
    w, h = img.size

    row_density = []
    for y in range(h):
        non_white = sum(1 for x in range(w) if sum(img.getpixel((x, y))[:3]) / 3 < 245)
        row_density.append(non_white)

    # Find all gaps (consecutive rows with density < min_density)
    gaps = []
    gap_start = None
    for y in range(h):
        if row_density[y] < min_density:
            if gap_start is None:
                gap_start = y
        else:
            if gap_start is not None and (y - gap_start) >= 20:
                gaps.append((gap_start, y, y - gap_start))
            gap_start = None
    if gap_start is not None and (h - gap_start) >= 20:
        gaps.append((gap_start, h, h - gap_start))

    if not gaps:
        return img

    # Find the largest gap in the lower 60% of the image
    try:
        lower_threshold = int(h * 0.4)
    except (OverflowError, ValueError):
        lower_threshold = 0
    best_gap = None
    best_gap_size = 0
    for g_start, g_end, g_size in gaps:
        if g_start >= lower_threshold and g_size > best_gap_size:
            best_gap = (g_start, g_end, g_size)
            best_gap_size = g_size

    # Only trim if the gap is large enough
    if best_gap is None or best_gap_size < min_gap:
        return img

    # Crop just above the largest gap, keeping padding for engagement buttons
    content_end = best_gap[0]
    pad = min(80, min_gap, content_end // 4)
    content_end = max(content_end - pad, 0)

    if content_end > 50:
        return img.crop((0, 0, w, content_end))
    return img


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


def validate_output(img, verbose=True, min_content_pct=5.0, min_height_px=200):
    w, h = img.size
    if h < min_height_px:
        log_info(f"  FAIL: image too short ({h}px < {min_height_px}px)", verbose)
        return False

    total_samples = 0
    non_white = 0
    for y in range(0, h, max(1, h // 200)):
        for x in range(0, w, max(1, w // 200)):
            px = img.getpixel((x, y))
            total_samples += 1
            if sum(px[:3]) / 3 < 245:
                non_white += 1

    if total_samples == 0:
        return False

    content_pct = 100 * non_white / total_samples
    log_info(f"  Content: {content_pct:.1f}% ({w}x{h})", verbose)

    if content_pct < min_content_pct:
        log_info(
            f"  FAIL: content too low ({content_pct:.1f}% < {min_content_pct}%)",
            verbose,
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Main conversion function
# ---------------------------------------------------------------------------


def x_to_png(
    url, output=None, auth_token=None, verbose=True, retries=1, replies=0, ct0=None
):
    validate_url(url)

    if not auth_token:
        auth_token = (
            os.environ.get("X_AUTH_TOKEN")
            or os.environ.get("TWITTER_AUTH_TOKEN")
            or None
        )
        if auth_token:
            log_info(
                "Using auth token from X_AUTH_TOKEN/TWITTER_AUTH_TOKEN env var", verbose
            )

    if not ct0:
        ct0 = os.environ.get("X_CT0") or os.environ.get("TWITTER_CT0") or None
        if ct0:
            log_info("Using ct0 from X_CT0/TWITTER_CT0 env var", verbose)

    if output is None:
        tweet_id = url.rstrip("/").split("/")[-1].split("?")[0].split("#")[0]
        output = f"{tweet_id}.png"

    output_path = Path(output).resolve()
    # Guard against path traversal: reject relative paths containing ..
    if ".." in Path(output).parts:
        raise ValueError(f"Output path must not contain '..' traversal: {output}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return _x_to_png_single(
                url, output_path, auth_token, ct0, replies, verbose, attempt
            )
        except RuntimeError as e:
            last_error = e
            if attempt < retries:
                log_warn(f"Attempt {attempt} failed: {e}. Retrying...")
            else:
                raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("All retries failed with unknown error")


def _x_to_png_single(url, output_path, auth_token, ct0, replies, verbose, attempt):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1600, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.96 Safari/537.36",
            ignore_https_errors=True,
            locale="en-US",
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        cookies = []
        if auth_token:
            cookies.append(
                {
                    "name": "auth_token",
                    "value": auth_token,
                    "domain": ".x.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                }
            )
        if ct0:
            cookies.append(
                {
                    "name": "ct0",
                    "value": ct0,
                    "domain": ".x.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                }
            )
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()

        # Step 1: Visit homepage to get fresh ct0
        log_info("Visiting x.com to establish session...", verbose)
        page.goto("https://x.com", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        # Step 2: Navigate to the post
        log_info(f"Loading: {url}", verbose)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Step 3: Wait for content to fully render
        content_len, elapsed = wait_for_content(page, timeout=180, verbose=verbose)

        if content_len < 5000:
            if not auth_token:
                log_warn("Content may be truncated. X Articles require --auth_token.")
            else:
                log_warn("Content may not have fully loaded. Try again with --verbose.")

        # Step 3b: When replies are requested, scroll the reply list into
        # view so X's virtualized DOM renders the first N reply articles.
        # Replies are authenticated content; without auth this is a no-op.
        # (Show-more expansion happens after the Step 4b viewport resize,
        # since the Step 4 scroll-through re-collapses expanded posts.)
        if replies > 0:
            scroll_to_load_replies(page, replies + 1, verbose=verbose)
            # Click "Show more replies" buttons that appear between tweets
            expand_show_more_replies(page, verbose=verbose)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)

        # Step 4: Find a preliminary post/replies boundary to know how far
        # we need to render, then scroll through that region step by step.
        # X virtualizes off-screen content, so without this scroll-through
        # (and a viewport tall enough to hold the whole post) large parts
        # of the article stay blank in screenshots.
        boundary_pre = find_post_boundary_y(page, replies=replies)
        doc_h = page.evaluate("document.documentElement.scrollHeight")
        scroll_limit = boundary_pre + 1000 if boundary_pre > 0 else min(doc_h, 30000)

        log_info("Scrolling through content to force rendering...", verbose)
        y = 0
        while y < scroll_limit:
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(300)
            y += 800
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        # Step 4b: Resize viewport tall enough to hold the entire post so
        # nothing is virtualized away during the screenshot
        if boundary_pre > 0:
            viewport_h = min(max(boundary_pre + 200, 2000), 30000)
        else:
            viewport_h = 16000
        page.set_viewport_size({"width": 1600, "height": viewport_h})
        page.wait_for_timeout(3000)

        # Step 4b1: Expand 'Show more' on truncated posts/replies now that
        # all scrolling is done and the tall viewport holds the kept
        # articles. Earlier expansion is undone by X's re-render during the
        # Step 4 scroll-through, so this must run last, before measurement.
        # Always expand the main post (articles[0]); when replies=0,
        # expand_show_more internally clamps last_idx to 0.
        expand_show_more(page, replies, verbose=verbose)
        page.wait_for_timeout(1000)

        # Step 4c: Get content column dimensions (in the final layout)
        try:
            col_x, col_w = get_content_column_dims(page)
        except RuntimeError as e:
            raise RuntimeError(f"Could not find content column: {e}") from e

        log_info(f"Content column: x={col_x}, width={col_w}", verbose)

        # Step 4d: Re-measure the boundary in the final layout; its page
        # coordinates map 1:1 onto the screenshot.  The preliminary
        # boundary (measured in the 900px scroll viewport) can be short of
        # the true value after the page reflows in the tall viewport — if
        # so, we must resize and re-measure or the screenshot clip will be
        # truncated.
        boundary_y = find_post_boundary_y(page, replies=replies)
        if boundary_y > 0:
            log_info(f"DOM boundary at y={boundary_y}", verbose)
        if boundary_y > viewport_h:
            log_info(
                f"Boundary exceeds viewport ({boundary_y} > {viewport_h}); "
                f"resizing viewport and re-measuring...",
                verbose,
            )
            viewport_h = min(boundary_y + 500, 30000)
            page.set_viewport_size({"width": 1600, "height": viewport_h})
            page.wait_for_timeout(3000)
            boundary_y = find_post_boundary_y(page)
            if boundary_y > 0:
                log_info(f"Re-measured DOM boundary at y={boundary_y}", verbose)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            screenshot_path = tmp.name

        try:
            # Step 5: Screenshot. When the boundary is known, clip to just
            # the post (staying within the viewport avoids blank virtualized
            # regions); otherwise fall back to a full-page capture.
            boundary_applied = False
            if boundary_y > 300:
                clip_h = min(boundary_y + 20, viewport_h)
                page.screenshot(
                    path=screenshot_path,
                    clip={"x": 0, "y": 0, "width": 1600, "height": clip_h},
                )
                boundary_applied = True
                log_info(f"Captured post region (0..{clip_h})", verbose)
            else:
                page.screenshot(path=screenshot_path, full_page=True)
                log_info("Full screenshot captured", verbose)

            browser.close()

            # Step 6: Crop to content column
            img = Image.open(screenshot_path)
            full_w, full_h = img.size
            cropped = img.crop((col_x, 0, col_x + col_w, full_h))

            # Step 7a: Horizontal crop (remove side panel)
            content_right = find_content_horizontal_bounds(cropped)
            cropped = cropped.crop((0, 0, content_right, cropped.height))

            # Step 7b: Boundary fallbacks when the DOM gave nothing usable:
            # gap-based trim, then vision model detection
            if not boundary_applied:
                cropped = trim_recommendations(cropped)

                vision_y = detect_discovery_more_vision(screenshot_path, verbose)
                if 50 < vision_y < cropped.height:
                    cropped = cropped.crop((0, 0, cropped.width, vision_y))
                    log_info(f"Applied vision boundary crop at y={vision_y}", verbose)

            # Step 7d: Compute final vertical bounds
            probe_x = min(content_right // 2, cropped.width - 1)
            content_top, content_bottom = find_content_vertical_bounds(cropped, probe_x)
            trimmed_h = cropped.height
            effective_bottom = min(trimmed_h, content_bottom)

            # Step 7e: Final crop with padding
            pad = 15
            x1 = 0
            y1 = max(0, content_top - pad)
            x2 = min(content_right + pad, cropped.width)
            y2 = min(effective_bottom + pad, cropped.height)

            final = cropped.crop((x1, y1, x2, y2))

            # Step 8: Validate output
            if not validate_output(final, verbose):
                raise RuntimeError(
                    "Output image appears empty or too small. "
                    "Try again with --retries or check the URL."
                )

            final.save(str(output_path))
            log_info(f"Saved: {output_path} ({final.width}x{final.height})", verbose)

        finally:
            Path(screenshot_path).unlink(missing_ok=True)

    return str(output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Convert an X post to a single-column PNG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://x.com/user/status/123456"
  %(prog)s "https://x.com/user/status/123456" output.png
  %(prog)s "https://x.com/user/status/123456" --auth-token TOKEN --verbose
        """,
    )
    parser.add_argument("url", help="Full URL to the X post")
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Output PNG path (default: <tweet_id>.png)",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="X auth_token cookie for logged-in content (Articles, private posts)",
    )
    parser.add_argument(
        "--ct0",
        default=None,
        help="X ct0 CSRF cookie (recommended with --auth-token)",
    )
    parser.add_argument(
        "--replies",
        type=int,
        default=0,
        help="Include the first N reply comments in the screenshot (default: 0)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Number of attempts if content doesn't load (default: 1)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print detailed progress"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress all output except errors"
    )
    args = parser.parse_args()

    verbose = args.verbose and not args.quiet

    try:
        output = x_to_png(
            args.url,
            args.output,
            args.auth_token,
            verbose=verbose,
            retries=args.retries,
            replies=args.replies,
            ct0=args.ct0,
        )
        if not args.quiet:
            print(f"\nDone! Output: {output}")
    except ValueError as e:
        log_error(str(e))
        sys.exit(1)
    except Exception as e:
        log_error(f"Failed to capture post: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
