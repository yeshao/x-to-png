"""Shared fixture tweet used by both the golden-image test and its regen script."""

GOLDEN_TWEET = {
    "display_name": "Ada Lovelace",
    "handle": "@ada",
    "avatar": "",
    "text": (
        "Just shipped a new release! Highlights:\n"
        "- Faster startup times across the board\n"
        "- Fixed the wrapping bug that repeated the bullet glyph on every "
        "continuation line, which was pretty annoying\n"
        "\n"
        "Thanks for reading."
    ),
    "timestamp": "2025-12-27T18:30:00.000Z",
    "verified": True,
}
