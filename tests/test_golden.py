import hashlib
from pathlib import Path

from golden_fixture import GOLDEN_TWEET
from card_renderer import render

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "golden" / "golden.png"


def test_render_matches_golden_image(tmp_path):
    out = tmp_path / "rendered.png"
    render(dict(GOLDEN_TWEET), str(out))
    rendered_bytes = out.read_bytes()
    golden_bytes = GOLDEN_PATH.read_bytes()
    if rendered_bytes != golden_bytes:
        rendered_hash = hashlib.sha256(rendered_bytes).hexdigest()
        golden_hash = hashlib.sha256(golden_bytes).hexdigest()
        raise AssertionError(
            "Render output no longer matches the golden image "
            f"({rendered_hash} != {golden_hash}).\n"
            "If this change is intentional, regenerate the golden image:\n"
            "  python3 tests/fixtures/golden/regen_golden.py"
        )
