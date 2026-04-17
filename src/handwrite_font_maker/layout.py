from __future__ import annotations

from itertools import chain

LAYOUT_ROWS = [
    list("ABCDEFGH"),
    list("IJKLMNOP"),
    list("QRSTUVWX"),
    list("YZabcdef"),
    list("ghijklmn"),
    list("opqrstuv"),
    list("wxyz0123"),
    list("456789.,"),
    [";", ":", "!", "?", '"', "'", "-", "+"],
    ["=", "/", "%", "&", "(", ")", "[", "]"],
]

DEFAULT_LAYOUT = tuple(chain.from_iterable(LAYOUT_ROWS))

SAFE_GLYPH_NAMES = {
    ".": "period",
    ",": "comma",
    ";": "semicolon",
    ":": "colon",
    "!": "exclam",
    "?": "question",
    '"': "quotedbl",
    "'": "quotesingle",
    "-": "hyphen",
    "+": "plus",
    "=": "equal",
    "/": "slash",
    "%": "percent",
    "&": "ampersand",
    "(": "parenleft",
    ")": "parenright",
    "[": "bracketleft",
    "]": "bracketright",
}


def glyph_slug(char: str) -> str:
    if char.isalnum():
        return char
    return SAFE_GLYPH_NAMES[char]
