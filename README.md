# x-to-png

Convert X/Twitter posts into PNG images. Two rendering engines, chosen
automatically:

- **Browser (Playwright)** — drives headless Chromium and screenshots the real
  rendered page. Full fidelity: threads, the OP's own replies, authenticated /
  private posts, X Articles, and lazy-loaded content.
- **Card (syndication API)** — draws a clean, styled card for a single public
  tweet. Fast, no browser, no login.

## Engine selection

By default the tool auto-selects, speed-first:

- **Card** for a simple public tweet — or whenever no browser is installed.
- **Browser** when the request or content needs it: `--replies`/threads, an X
  Article URL, `--auth-token`/`--ct0` (authenticated/private), video·GIF·quoted
  content, or when the card fetch fails (deleted/protected). The card path
  escalates to the browser automatically in these cases.

Override the choice with `--card` (force offline card) or `--browser` (force
screenshot).

## Features

### Browser mode

- Full tweet/thread including the OP's own replies (`--replies`)
- Crops sidebars, recommendations, and "Discover more" sections
- Authenticated sessions for replies / articles / private posts (X cookies)
- Lazy-load handling via incremental scrolling; optional vision boundary
  detection (NVIDIA API); auto-loads auth from `~/.zshrc`

### Card mode

- Twitter-style card: avatar, display name, conditional verified badge, handle,
  body text, timestamp
- Inline color emoji (Apple Color Emoji / Noto), graceful fallback if absent
- Attached photos in a 1–4 grid with rounded corners
- Pixel-accurate wrapping (incl. CJK), long-URL breaking, `t.co` expansion,
  HTML unescaping; no dependencies beyond Pillow

## Requirements

```bash
# Full install (both engines)
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
# Auto (default) — picks the right engine
python3 x_to_png.py "https://x.com/user/status/123456"            # simple tweet -> card
python3 x_to_png.py "https://x.com/user/status/123456" --replies 6 # thread     -> browser

# Force an engine
python3 x_to_png.py --card "https://x.com/user/status/123456" card.png
python3 x_to_png.py --browser "https://x.com/user/status/123456"

# The x-to-png wrapper works the same way
./x-to-png --card 123456 card.png --text "Full text for long/Blue tweets"
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

| Flag            | Engine  | Description                                            |
| --------------- | ------- | ----------------------------------------------------- |
| `url`           | both    | X post URL (or a tweet ID with `--card`)              |
| `output`        | both    | Output PNG path (default: `<tweet_id>.png`)           |
| `--card`        | select  | Force the offline card renderer                       |
| `--browser`     | select  | Force the browser screenshot engine                   |
| `--auth-token`  | browser | X auth_token cookie for logged-in content             |
| `--ct0`         | browser | X ct0 CSRF cookie (recommended with `--auth-token`)   |
| `--replies N`   | browser | Include N of the OP's own replies                     |
| `--retries N`   | browser | Attempts if content doesn't load (default: 1)         |
| `-v/--verbose`  | both    | Print detailed progress (incl. which engine and why)  |
| `-q/--quiet`    | both    | Suppress all output except errors                     |
| `--text`        | card    | Full tweet text (bypasses ~280-char API truncation)   |
| `--local`       | card    | Render timestamp in local time instead of UTC         |
| `--force`       | card    | Overwrite the output file if it exists                |

## How it works

**Browser:** establishes a session, navigates to the post, waits for render,
scrolls to load lazy content, screenshots the full page, crops to the content
column, trims recommendations by pixel density, and cuts at the last article
boundary (optionally vision-assisted).

**Card:** fetches tweet metadata from the syndication API (no auth), expands
`t.co` links, wraps text to a fixed width, and composites a rounded card with
avatar, emoji, and any attached photos using Pillow.

## Tests

```bash
pip install pytest
pytest              # 177 offline tests (browser + card + engine selection)
pytest -m network   # opt-in: one live syndication fetch (card mode)
```

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Shaozhi.
