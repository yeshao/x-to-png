# x-to-png

Convert X/Twitter posts (tweets, articles, threads) into single-column PNG images.

## Features

- Captures the full tweet/thread content including all replies
- Crops out sidebars, recommendations, and "Discovery more" sections
- Supports authenticated sessions for viewing replies (requires X cookies)
- Handles lazy-loaded content via incremental scrolling
- Vision-model assisted boundary detection (optional, via NVIDIA API)

## Requirements

```bash
pip install pillow
pip install playwright
playwright install chromium
```

## Usage

```bash
# Public tweets (no auth needed)
python3 x_to_png.py "https://x.com/user/status/123456"

# Specify output path
python3 x_to_png.py "https://x.com/user/status/123456" output.png

# With authentication (for replies, articles, private posts)
python3 x_to_png.py "https://x.com/user/status/123456" \
    --auth-token TOKEN --ct0 CT0

# Verbose output
python3 x_to_png.py "https://x.com/user/status/123456" \
    --auth-token TOKEN --ct0 CT0 --verbose
```

### Getting Auth Cookies

1. Open x.com in your browser and log in
2. Open DevTools (F12) → Application → Cookies → `https://x.com`
3. Copy the `auth_token` and `ct0` cookie values

## Options

| Flag            | Description                                             |
| --------------- | ------------------------------------------------------- |
| `url`           | Full URL to the X post (required)                       |
| `output`        | Output PNG path (default: `<tweet_id>.png`)             |
| `--auth-token`  | X auth_token cookie for logged-in content               |
| `--ct0`         | X ct0 CSRF cookie (recommended with --auth-token)       |
| `--retries N`   | Number of attempts if content doesn't load (default: 1) |
| `-v, --verbose` | Print detailed progress                                  |
| `-q, --quiet`   | Suppress all output except errors                       |

## How It Works

1. Visits x.com to establish a session
2. Navigates to the post URL
3. Waits for content to render
4. Incrementally scrolls down to load all lazy content (replies, etc.)
5. Captures a full-page screenshot
6. Crops to the content column, removing sidebars
7. Trims recommendations using pixel density analysis
8. Crops at the last article boundary (before "Discovery more")
9. Optionally uses NVIDIA vision model for boundary detection

## Tests

```bash
python3 test_x_to_png.py
# or
python3 -m pytest test_x_to_png.py -v
```

39 tests covering URL validation, content boundary detection,
recommendation trimming, scrolling, CLI flags, and full layout simulation.

## License

MIT License

Copyright (c) 2026 Shaozhi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
