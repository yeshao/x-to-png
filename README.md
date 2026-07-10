# x-to-png

Convert X/Twitter posts into PNG images, with two rendering engines:

- **Browser mode (default)** — drives headless Chromium (Playwright) and
  screenshots the real rendered page. Full fidelity: threads, the OP's own
  replies, authenticated/private posts, X Articles, and lazy-loaded content.
- **Card mode (`--card`)** — draws a clean, styled card for a single public
  tweet from the public syndication API. Fast, no browser, no login.

## Features

### Browser mode (default)

- Captures the full tweet/thread including the OP's own replies (`--replies`)
- Crops sidebars, recommendations, and "Discover more" sections
- Authenticated sessions for replies / articles / private posts (X cookies)
- Handles lazy-loaded content via incremental scrolling
- Optional vision-model boundary detection (NVIDIA API)
- Auto-loads auth tokens from `~/.zshrc`

### Card mode (`--card`)

- Twitter-style card: avatar, display name, conditional verified badge,
  handle, body text, timestamp
- Inline color emoji (Apple Color Emoji / Noto), graceful fallback if absent
- Attached photos in a 1–4 grid with rounded corners
- Pixel-accurate wrapping (incl. CJK), long-URL breaking, `t.co` expansion,
  HTML unescaping
- No dependencies beyond Pillow; works offline against any public tweet

## Requirements

```bash
# Browser mode
pip install playwright pillow
playwright install chromium

# Card mode only
pip install pillow
```

Card mode uses a monospace font (Hack Nerd Font by default, falling back to
Menlo / DejaVu Sans Mono); override with `X2PNG_FONT` / `X2PNG_FONT_BOLD`, and
the color-emoji font with `X2PNG_EMOJI_FONT`.

## Usage

```bash
# Browser mode (default) — full-fidelity screenshot
python3 x_to_png.py "https://x.com/user/status/123456"
python3 x_to_png.py "https://x.com/user/status/123456" out.png --replies 6
python3 x_to_png.py "https://x.com/user/status/123456" --auth-token TOKEN --ct0 CT0

# Card mode — fast offline card for a single public tweet
python3 x_to_png.py --card "https://x.com/user/status/123456"
python3 x_to_png.py --card 123456 card.png --text "Full text for long/Blue tweets"

# The x-to-png wrapper works the same way
./x-to-png --card 123456 card.png
```

### Auth token setup (browser mode)

Browser mode auto-loads `X_AUTH_TOKEN` and `X_CT0` from `~/.zshrc`:

```bash
export X_AUTH_TOKEN="your_auth_token"
export X_CT0="your_ct0_token"
```

Get the cookies from DevTools → Application → Cookies → `https://x.com`
(`auth_token` and `ct0`). Required for X Articles, private posts, and full
reply threads.

## Options

| Flag            | Mode    | Description                                            |
| --------------- | ------- | ----------------------------------------------------- |
| `url` / `id`    | both    | X post URL (browser) or URL/ID (card)                 |
| `output`        | both    | Output PNG path (default: `<tweet_id>.png`)           |
| `--card`        | switch  | Use the offline card renderer instead of screenshots  |
| `--auth-token`  | browser | X auth_token cookie for logged-in content             |
| `--ct0`         | browser | X ct0 CSRF cookie (recommended with `--auth-token`)   |
| `--replies N`   | browser | Include N of the OP's own replies (`all` for every)   |
| `--retries N`   | browser | Attempts if content doesn't load (default: 1)         |
| `-v/--verbose`  | browser | Print detailed progress                               |
| `-q/--quiet`    | browser | Suppress all output except errors                     |
| `--text`        | card    | Full tweet text (bypasses ~280-char API truncation)   |
| `--local`       | card    | Render timestamp in local time instead of UTC         |
| `--force`       | card    | Overwrite the output file if it exists                |

## How it works

**Browser mode:** establishes a session, navigates to the post, waits for
render, scrolls to load lazy content, screenshots the full page, crops to the
content column, trims recommendations by pixel density, and cuts at the last
article boundary (optionally vision-assisted).

**Card mode:** fetches tweet metadata from the syndication API (no auth),
expands `t.co` links, wraps text to a fixed width, and composites a rounded
card with avatar, emoji, and any attached photos using Pillow.

## Tests

```bash
pip install pytest
pytest              # 157 offline tests (browser + card); network test excluded
pytest -m network   # opt-in: one live syndication fetch (card mode)
```

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Shaozhi.
