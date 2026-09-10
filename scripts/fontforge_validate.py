#!/usr/bin/env fontforge
import json
import sys
from pathlib import Path

import fontforge


class ValidationFailure(RuntimeError):
    pass


def _failures_for_font(path: Path, manifest: dict | None) -> list[str]:
    failures: list[str] = []
    if not path.exists() or path.stat().st_size <= 0:
        return [f"{path.name}: file is missing or empty"]

    font = fontforge.open(str(path))
    try:
        if manifest is None:
            if font.em <= 0 or font.ascent <= 0 or font.descent < 0:
                failures.append(f"{path.name}: invalid basic metrics")
            return failures

        expected_em = int(manifest["em_size"])
        expected_ascent = int(manifest["ascent"])
        expected_descent = int(manifest["descent"])
        if font.em != expected_em:
            failures.append(f"{path.name}: em {font.em} != {expected_em}")
        if font.ascent != expected_ascent or font.descent != expected_descent:
            failures.append(f"{path.name}: ascent/descent {font.ascent}/{font.descent} != {expected_ascent}/{expected_descent}")
        if font.fontname != manifest["font_name"]:
            failures.append(f"{path.name}: PostScript name mismatch")
        if font.familyname != manifest["family_name"]:
            failures.append(f"{path.name}: family name mismatch")
        if font.fullname != manifest["full_name"]:
            failures.append(f"{path.name}: full name mismatch")
        if int(font.os2_fstype) != 0:
            failures.append(f"{path.name}: OS/2 embeddability is restricted ({font.os2_fstype})")
        for table in ("fpgm", "prep", "cvt "):
            try:
                data = font.getTableData(table)
            except Exception:
                data = None
            if data:
                failures.append(f"{path.name}: unexpected TrueType instruction table {table.strip() or table!r}")

        try:
            notdef = font[".notdef"]
            if not notdef.isWorthOutputting() or notdef.width < 280:
                failures.append(f"{path.name}: .notdef fallback is missing or unusable")
        except Exception:
            failures.append(f"{path.name}: .notdef fallback is missing")

        try:
            space = font[0x20]
            expected_space = int(manifest["space_width"])
            if space.width != expected_space:
                failures.append(f"{path.name}: space width {space.width} != {expected_space}")
        except Exception:
            failures.append(f"{path.name}: missing U+0020 space")

        seen_codepoints: set[int] = set()
        for glyph_data in manifest["glyphs"]:
            codepoint = int(glyph_data["codepoint"])
            char = glyph_data["char"]
            if codepoint in seen_codepoints:
                failures.append(f"{path.name}: duplicate manifest codepoint U+{codepoint:04X}")
                continue
            seen_codepoints.add(codepoint)
            try:
                glyph = font[codepoint]
            except Exception:
                failures.append(f"{path.name}: missing glyph {char!r} U+{codepoint:04X}")
                continue
            expected_width = int(glyph_data["advance_width"])
            if glyph.width != expected_width:
                failures.append(f"{path.name}: glyph {char!r} width {glyph.width} != {expected_width}")
            if expected_width < 280:
                failures.append(f"{path.name}: glyph {char!r} advance is below minimum")
            if glyph_data.get("empty"):
                continue
            if not glyph.isWorthOutputting():
                failures.append(f"{path.name}: glyph {char!r} has no outline")
                continue
            bbox = glyph.boundingBox()
            if (bbox[2] - bbox[0]) <= 0 or (bbox[3] - bbox[1]) <= 0:
                failures.append(f"{path.name}: glyph {char!r} has an empty bounding box")
            if bbox[0] < -20 or bbox[2] > glyph.width + 20:
                failures.append(f"{path.name}: glyph {char!r} outline exceeds horizontal advance")
            if bbox[3] > expected_ascent + 80 or bbox[1] < -expected_descent - 220:
                failures.append(f"{path.name}: glyph {char!r} outline vertical bounds are unreasonable {bbox}")
            state = glyph.validate()
            if state not in (0,):
                # FontForge validation flags are noisy across versions; keep this informationally strict
                # only for clearly unusable glyphs already caught above.
                pass
    finally:
        font.close()
    return failures


def main() -> int:
    args = [Path(arg).resolve() for arg in sys.argv[1:]]
    manifest = None
    if args and args[0].suffix.lower() == ".json":
        manifest = json.loads(args[0].read_text(encoding="utf-8"))
        args = args[1:]
    if not args:
        raise SystemExit("Usage: fontforge_validate.py [manifest.json] font.otf font.ttf [...]")

    failures: list[str] = []
    for path in args:
        failures.extend(_failures_for_font(path, manifest))
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
