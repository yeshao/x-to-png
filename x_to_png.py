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
import time
import json
import argparse
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image


def log_info(msg, verbose=True):
    """Print info message unless quiet mode."""
    if verbose:
        print(msg)


def log_warn(msg):
    """Always print warnings."""
    print(f"WARNING: { msg}", file=sys.stderr)


def log_error(msg):
    """Always print errors."""
    print(f"ERROR: {msg}", file=sys.stderr)


def validate_url(url):
    """Basic URL validation for X/Twitter posts."""
    url_lower = url.lower()
    valid_domains = ['x.com', 'twitter.com', 'mobile.x.com', 'mobile.twitter.com']
    if not any(domain in url_lower for domain in valid_domains):
        raise ValueError(f"URL doesn't appear to be an X/Twitter post: {url}")
    if '/status/' not in url_lower and '/article/' not in url_lower and '/i/' not in url_lower:
        raise ValueError(f"URL doesn't contain a post path (/status/, /article/, /i/): {url}")


def get_content_column_html_length(page):
    """Safely get the innerHTML length of the content column."""
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
    """Get content column bounding box. Returns (x, width) or raises."""
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
    """
    Poll until content column stabilizes or timeout.
    Returns (html_length, elapsed_seconds).
    """
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


def find_content_horizontal_bounds(img):
    """
    Analyze pixel columns to find the right edge of the main content area.
    Looks for a sharp drop-off in pixel density (the gap between article and sidebar).
    Returns content_right_x.
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

    # Find the rightmost column that has "real" content (at least 10% of max).
    # This ignores sparse sidebar widgets (trending, who-to-follow) that have
    # a few pixels but are mostly whitespace.
    content_threshold = max_score * 0.10
    content_right = w
    for cx in range(w - 1, -1, -1):
        if col_scores[cx] >= content_threshold:
            content_right = cx + 1
            break

    return content_right


def find_content_vertical_bounds(img, probe_x=None):
    """
    Find top and bottom content boundaries.
    Returns (content_top, content_bottom).
    """
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


def x_to_png(url: str, output: str = None, auth_token: str = None,
             verbose: bool = True, retries: int = 1) -> str:
    """
    Convert an X post URL to a single-column PNG.

    Args:
        url: Full URL to the X post
        output: Output PNG path (default: <tweet_id>.png in current dir)
        auth_token: Optional X auth_token cookie for logged-in content
        verbose: Print progress messages
        retries: Number of times to retry if content doesn't load (default: 1)

    Returns:
        Path to the saved PNG file
    """
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
    """Single attempt to capture and crop the X post."""
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

        # Stealth: override bot detection signals
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        # Set auth cookie if provided
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

        # Step 1: Visit homepage to get fresh ct0 CSRF cookie
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

        # Step 5: Resize viewport tall and take screenshot
        # Scroll to top first — content may be below the current scroll position
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        page.set_viewport_size({"width": 1600, "height": 16000})
        page.wait_for_timeout(3000)

        # Use temp file for intermediate screenshot
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            screenshot_path = tmp.name

        try:
            page.screenshot(path=screenshot_path, full_page=True)
            log_info("Full screenshot captured", verbose)

            # Close browser early — we don't need it anymore
            browser.close()

            # Step 6: Crop to content column
            img = Image.open(screenshot_path)
            full_w, full_h = img.size

            cropped = img.crop((col_x, 0, col_x + col_w, full_h))

            # Step 7: Remove empty side panel via pixel analysis
            content_right = find_content_horizontal_bounds(cropped)
            probe_x = min(content_right // 2, cropped.width - 1)
            content_top, content_bottom = find_content_vertical_bounds(cropped, probe_x)

            # Final crop with small padding
            pad = 15
            x1 = 0
            y1 = max(0, content_top - pad)
            x2 = min(content_right + pad, cropped.width)  # noqa
            y2 = min(content_bottom + pad, cropped.height)

            final = cropped.crop((x1, y1, x2, y2))
            final.save(str(output_path))
            log_info(f"Saved: {output_path} ({final.width}x{final.height})", verbose)

        finally:
            # Always clean up temp file
            Path(screenshot_path).unlink(missing_ok=True)

    return str(output_path)


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
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed progress")
    parser.add_argument("--quiet", "-q", action="store_true",
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
