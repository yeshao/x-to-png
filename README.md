# x-to-png

Convert any X/Twitter post (tweet, article, thread) into a clean single-column PNG image.

## Features

- **Headless rendering** via Playwright with stealth mode to bypass X's bot detection
- **Automatic content detection** — polls until the page finishes loading
- **Smart cropping** — pixel-level analysis removes empty side panels and whitespace
- **X Article support** — `--auth-token` flag for long-form content behind login
- **Retry logic** — handles X's flaky progressive loading
- **URL validation** — catches bad URLs early with clear error messages

## Installation

```bash
pip install playwright pillow
playwright install chromium
```

## Usage

```bash
# Public tweets (no login needed)
python3 x_to_png.py "https://x.com/user/status/123456"

# Custom output path
python3 x_to_png.py "https://x.com/user/status/123456" output.png

# X Articles / private posts (requires auth token)
python3 x_to_png.py "https://x.com/user/status/123456" --auth-token YOUR_TOKEN

# Verbose mode with retries
python3 x_to_png.py "https://x.com/user/status/123456" -v --retries 3
```

### Getting an auth token

1. Open [x.com](https://x.com) in your browser and log in
2. Open DevTools → Application → Cookies → x.com
3. Copy the `auth_token` value
4. Pass it as `--auth-token`

> **Note:** The script automatically visits x.com first to obtain a fresh `ct0` CSRF cookie. Only `auth_token` needs to be provided.

## Options

| Flag | Description |
|------|-------------|
| `url` | Full URL to the X post (required) |
| `output` | Output PNG path (default: `<tweet_id>.png`) |
| `--auth-token TOKEN` | X auth_token cookie for logged-in content |
| `--retries N` | Number of attempts if content doesn't load (default: 1) |
| `-v, --verbose` | Print detailed progress |
| `-q, --quiet` | Suppress all output except errors |

## Examples

```bash
# Basic usage
python3 x_to_png.py "https://x.com/ylecun/status/1937478294714486912"

# Article with auth
python3 x_to_png.py "https://x.com/plainionist/status/2067595751341924783" \
  article.png --auth-token 64d55847...

# Quiet mode for scripts
python3 x_to_png.py "https://x.com/user/status/123" -q
```

## Requirements

- Python 3.8+
- Playwright (with Chromium installed)
- Pillow (PIL)

## License

MIT
