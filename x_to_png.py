#!/usr/bin/env python3
"""
X/Twitter Post to PNG Converter
================================
Converts an X post (tweet, article, thread) into a single-column PNG image.

Usage:
    python3 x_to_png.py <url> [output_path] [--auth-token TOKEN] [--verbose] [--quiet]

Examples:
    python3 x_to_png.py "https://x.com/user/status/123456"
    python3 x_to_png.py "https://x.com/user/status/123456" my_screenshot.png
    python3 x_to_png.py "https://x.com/user/status/123456" --auth-token abc123 --verbose

Requirements:
    pip install playwright pillow
    playwright install chromium

Without --auth-token:
    - Works for public regular tweets (no login needed)
    - X Articles / long-form posts require login (use --auth-token)

With --auth-token:
    - Get your auth_token from browser dev tools -> Cookies -> x.com -> auth_token
    - Visit x.com homepage first in the browser to get a fresh ct0 CSRF cookie
    - Then the script can access full Articles and logged-in content
"""

import sys
import os
import time
import json
import argparse
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image


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
    valid_domains = ['x.com', 'twitter.com', 'mobile.x.com', 'mobile.twitter.com']
    if not any(domain in url_lower for domain in valid_domains):
        raise ValueError(f"URL doesn't appear to be an X/Twitter post: {url}")
    if '/status/' not in url_lower and '/article/' not in url_lower and '/i/' not in url_lower:
        raise ValueError(f"URL doesn't contain a post path (/status/, /article/, /i/): {url}")


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
    dims = json.loads(raw)
    if 'error' in dims:
        raise RuntimeError(dims['error'])
    return dims['contentX'], dims['contentW']


def wait_for_content(page, timeout=180, verbose=True):
    log_info("Waiting for content to load...", verbose)
    start = time.time()
    prev_len = 0
    stable_count = 0

    for i in range(timeout // 2):
        time.sleep(2)
        content_len = get_content_column_html_length(page)
        elapsed = int(time.time() - start)

        if content_len == -1:
            log_info(f"  [{elapsed}s] Waiting for page structure...", verbose)
            continue

        if content_len > 50000:
            log_info(f"  [{elapsed}s] Content fully loaded ({content_len:,} bytes)", verbose)
            return content_len, elapsed

        if content_len == prev_len and content_len > 10000:
            stable_count += 1
            if stable_count >= 5:
                log_info(f"  [{elapsed}s] Content stabilized at {content_len:,} bytes", verbose)
                return content_len, elapsed
        elif content_len != prev_len:
            stable_count = 0
        prev_len = content_len
        log_info(f"  [{elapsed}s] html={content_len:,}", verbose)

    content_len = get_content_column_html_length(page)
    return content_len, int(time.time() - start)


# ---------------------------------------------------------------------------
# DOM-based boundary detection
# ---------------------------------------------------------------------------

def detect_discovery_more_vision(screenshot_path, verbose=True):
    """Use NVIDIA Llama 90b vision model to detect Discovery more boundary."""
    try:
        import base64 as b64mod, io as iomod, json as jsonmod, urllib.request as urlreq
        from PIL import Image as PILImage

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
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": 'X/Twitter article screenshot. Look for "Discovery more" or "Show more" section AFTER the article (near bottom). Reply ONLY JSON: {"has_discovery_more": "yes" or "no", "start_pct": "X%"} where start_pct is % from TOP of image.'}
            ]}],
            "max_tokens": 50,
            "temperature": 0
        }

        req = urlreq.Request(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            data=jsonmod.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )
        with urlreq.urlopen(req, timeout=120) as resp:
            result = jsonmod.loads(resp.read())
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
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


def find_post_boundary_y(page):
    """
    Use DOM queries to find the Y position where the main post ends and
    recommendations/replies begin. Returns Y position or -1.
    """
    result = page.evaluate("""
    (function() {
        // Strategy 1: Find the article element and look at its next sibling
        var article = document.querySelector('article');
        if (article && article.parentElement) {
            var parent = article.parentElement;
            var children = Array.from(parent.children);
            var articleIdx = children.indexOf(article);
            if (articleIdx >= 0 && articleIdx < children.length - 1) {
                var nextEl = children[articleIdx + 1];
                var rect = nextEl.getBoundingClientRect();
                if (rect.top > 100) return Math.round(rect.top);
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
                if (rect.top > 500 && rect.height > 10 && rect.width > 30) {
                    candidates.push(Math.round(rect.top));
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
            var rect = separators[i].getBoundingClientRect();
            if (rect.top > 1000) {
                return Math.round(rect.top);
            }
        }

        return -1;
    })()
    """)
    return result


# ---------------------------------------------------------------------------
# Pixel analysis helpers
# ---------------------------------------------------------------------------

def find_content_horizontal_bounds(img):
    """Find the right edge of the main content area."""
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
    content_right = w
    for cx in range(w - 1, -1, -1):
        if col_scores[cx] >= content_threshold:
            content_right = cx + 1
            break

    return content_right


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


def trim_recommendations(img, text_density=200):
    """
    Detect and trim the post-article recommendations section.

    Strategy: find the largest gap (consecutive low-density rows) in the
    lower 60% of the image. If the gap is large enough (>= 100px), it
    indicates the boundary between the article and the recommendations
    section. Crop just above it.

    For thread posts where replies are interleaved with article text,
    gaps are small and no trimming happens (which is correct).
    """
    w, h = img.size

    row_density = []
    for y in range(h):
        non_white = sum(1 for x in range(w) if sum(img.getpixel((x, y))[:3]) / 3 < 245)
        row_density.append(non_white)

    # Find all gaps (consecutive rows with density < text_density)
    gaps = []
    gap_start = None
    for y in range(h):
        if row_density[y] < text_density:
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
    lower_threshold = int(h * 0.4)
    best_gap = None
    best_gap_size = 0
    for g_start, g_end, g_size in gaps:
        if g_start >= lower_threshold and g_size > best_gap_size:
            best_gap = (g_start, g_end, g_size)
            best_gap_size = g_size

    # Only trim if the gap is large (>= 100px)
    if best_gap is None or best_gap_size < 100:
        return img

    # Crop just above the largest gap, keeping padding for engagement buttons
    content_end = best_gap[0]
    pad = min(80, content_end // 4)
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
        log_info(f"  FAIL: content too low ({content_pct:.1f}% < {min_content_pct}%)", verbose)
        return False

    return True


# ---------------------------------------------------------------------------
# Main conversion function
# ---------------------------------------------------------------------------

def x_to_png(url, output=None, auth_token=None, verbose=True, retries=1):
    validate_url(url)

    if output is None:
        tweet_id = url.rstrip('/').split('/')[-1].split('?')[0].split('#')[0]
        output = f"{tweet_id}.png"

    output_path = Path(output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return _x_to_png_single(url, output_path, auth_token, verbose, attempt)
        except RuntimeError as e:
            last_error = e
            if attempt < retries:
                log_warn(f"Attempt {attempt} failed: {e}. Retrying...")
            else:
                raise

    raise last_error


def _x_to_png_single(url, output_path, auth_token, verbose, attempt):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
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

        if auth_token:
            context.add_cookies([{
                "name": "auth_token",
                "value": auth_token,
                "domain": ".x.com",
                "path": "/",
                "httpOnly": True,
                "secure": True
            }])

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

        # Step 4: Get content column dimensions
        try:
            col_x, col_w = get_content_column_dims(page)
        except RuntimeError as e:
            raise RuntimeError(f"Could not find content column: {e}")

        log_info(f"Content column: x={col_x}, width={col_w}", verbose)

        # Step 4b: Find boundary via DOM (fast, free)
        boundary_y = find_post_boundary_y(page)
        if boundary_y > 0:
            log_info(f"DOM boundary at y={boundary_y}", verbose)

        # Step 5: Resize viewport and take screenshot
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        page.set_viewport_size({"width": 1600, "height": 16000})
        page.wait_for_timeout(3000)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            screenshot_path = tmp.name

        try:
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

            # Step 7b: Trim recommendations from bottom
            cropped = trim_recommendations(cropped)

            # Step 7c: Vision model detection (more accurate but slower)
            vision_y = detect_discovery_more_vision(screenshot_path, verbose)
            if vision_y > 0:
                scale = cropped.height / full_h
                vision_in_crop = int(vision_y * scale)
                if 50 < vision_in_crop < cropped.height:
                    # Use vision boundary if DOM didn't find one, or if
                    # vision gives a tighter (higher) crop
                    if boundary_y <= 0 or vision_in_crop <= int(boundary_y * scale):
                        cropped = cropped.crop((0, 0, cropped.width, vision_in_crop))
                        log_info(f"Applied vision boundary crop at y={vision_in_crop}", verbose)
                        boundary_y = vision_y  # update for later use

            # Step 7e: If DOM found a boundary (and vision didn't override), use it
            if boundary_y > 0 and vision_y <= 0:
                scale = cropped.height / full_h
                boundary_in_crop = int(boundary_y * scale)
                if 50 < boundary_in_crop < cropped.height:
                    cropped = cropped.crop((0, 0, cropped.width, boundary_in_crop))
                    log_info(f"Applied DOM boundary crop at y={boundary_in_crop}", verbose)

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
        """
    )
    parser.add_argument("url", help="Full URL to the X post")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output PNG path (default: <tweet_id>.png)")
    parser.add_argument("--auth-token", default=None,
                        help="X auth_token cookie for logged-in content (Articles, private posts)")
    parser.add_argument("--retries", type=int, default=1,
                        help="Number of attempts if content doesn't load (default: 1)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print detailed progress")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress all output except errors")
    args = parser.parse_args()

    verbose = args.verbose and not args.quiet

    try:
        output = x_to_png(
            args.url,
            args.output,
            args.auth_token,
            verbose=verbose,
            retries=args.retries
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
