from __future__ import annotations

import string
from functools import lru_cache

from .schema import DEFAULT_LAYOUT_ID, DEFAULT_PAPER_SIZE, MARKER_DICTIONARY, MARKER_IDS, TemplateLayout

PUNCTUATION_GLYPH_NAMES = {
    "!": "exclam",
    '"': "quotedbl",
    "#": "numbersign",
    "$": "dollar",
    "%": "percent",
    "&": "ampersand",
    "'": "quotesingle",
    "(": "parenleft",
    ")": "parenright",
    "*": "asterisk",
    "+": "plus",
    ",": "comma",
    "-": "hyphen",
    ".": "period",
    "/": "slash",
    ":": "colon",
    ";": "semicolon",
    "<": "less",
    "=": "equal",
    ">": "greater",
    "?": "question",
    "@": "at",
    "[": "bracketleft",
    "\\": "backslash",
    "]": "bracketright",
    "^": "asciicircum",
    "_": "underscore",
    "`": "grave",
    "{": "braceleft",
    "|": "bar",
    "}": "braceright",
    "~": "asciitilde",
}

# Printable non-space ASCII. Space is still synthesized by the font builder.
DEFAULT_CHARS = tuple(string.ascii_uppercase + string.ascii_lowercase + string.digits + string.punctuation)

SAFE_GLYPH_NAMES = PUNCTUATION_GLYPH_NAMES
DEFAULT_LAYOUT = DEFAULT_CHARS


def glyph_slug(char: str) -> str:
    if len(char) != 1:
        raise ValueError(f"Glyph must be a single character, got {char!r}")
    if char.isalnum():
        return char
    try:
        return PUNCTUATION_GLYPH_NAMES[char]
    except KeyError as exc:
        raise KeyError(f"No safe glyph name for {char!r}") from exc


@lru_cache(maxsize=None)
def get_layout(layout_id: str = DEFAULT_LAYOUT_ID, paper_size: str = DEFAULT_PAPER_SIZE) -> TemplateLayout:
    if layout_id != DEFAULT_LAYOUT_ID:
        raise ValueError(f"Unsupported layout: {layout_id}")
    layout = TemplateLayout(
        layout_id=layout_id,
        chars=DEFAULT_CHARS,
        columns=10,
        paper_size=paper_size.upper(),
        marker_dictionary=MARKER_DICTIONARY,
        marker_ids=MARKER_IDS,
    )
    layout.validate()
    return layout
