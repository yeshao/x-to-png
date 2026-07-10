import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

BIN_DIR = Path(__file__).parent.parent
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _StubHandler(http.server.BaseHTTPRequestHandler):
    payload = None  # set per-test via a class attribute swap

    def do_GET(self):
        if self.path.startswith("/tweet-result"):
            body = json.dumps(_StubHandler.payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # keep test output quiet


@pytest.fixture
def stub_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    yield base_url, _StubHandler
    server.shutdown()
    thread.join(timeout=5)


def test_end_to_end_happy_path(tmp_path, stub_server):
    base_url, handler = stub_server
    with open(FIXTURES_DIR / "success.json", encoding="utf-8") as f:
        handler.payload = json.load(f)

    out = tmp_path / "card.png"
    env = dict(os.environ)
    env["X2PNG_BASE_URL"] = base_url
    env["X2PNG_FONT"] = str(FIXTURES_DIR / "fonts" / "DejaVuSansMono.ttf")
    env["X2PNG_FONT_BOLD"] = str(FIXTURES_DIR / "fonts" / "DejaVuSansMono-Bold.ttf")

    result = subprocess.run(
        [sys.executable, str(BIN_DIR / "x-to-png"), "--card", handler.payload["id_str"], str(out)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert "Ada Lovelace" in result.stdout


def test_end_to_end_deleted_tweet_exits_nonzero(tmp_path, stub_server):
    base_url, handler = stub_server
    with open(FIXTURES_DIR / "tombstone.json", encoding="utf-8") as f:
        handler.payload = json.load(f)

    out = tmp_path / "card.png"
    env = dict(os.environ)
    env["X2PNG_BASE_URL"] = base_url
    env["X2PNG_FONT"] = str(FIXTURES_DIR / "fonts" / "DejaVuSansMono.ttf")
    env["X2PNG_FONT_BOLD"] = str(FIXTURES_DIR / "fonts" / "DejaVuSansMono-Bold.ttf")

    result = subprocess.run(
        [sys.executable, str(BIN_DIR / "x-to-png"), "--card", handler.payload["id_str"], str(out)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert not out.exists()
    assert result.stderr.strip() != ""


@pytest.mark.network
def test_live_fetch_smoke():
    """Opt-in: hits the real syndication API. Run with `pytest -m network`."""
    from card_renderer import fetch_tweet

    tweet = fetch_tweet("20")  # jack's first tweet; long-stable public ID
    assert tweet["text"]
