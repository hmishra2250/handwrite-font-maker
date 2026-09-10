#!/usr/bin/env fontforge
import json
import sys
from pathlib import Path

import fontforge
import psMat


# Official FontForge generate() flags include omit-instructions for omitting
# TrueType instructions. These handmade bitmap traces are display silhouettes,
# so the TTF artifact does not need generated instructions. Keep OTF generation
# default: no-hints produced unreadable CFF/OTF on this FontForge.
GENERATE_FLAGS_OTF: tuple[str, ...] = ()
GENERATE_FLAGS_TTF = ("omit-instructions",)


def _draw_notdef(font, width: int) -> None:
    glyph = font.createChar(-1, ".notdef")
    glyph.width = width
    pen = glyph.glyphPen()
    left, right = 80, max(180, width - 80)
    bottom, top = -120, font.ascent - 80
    pen.moveTo((left, bottom))
    pen.lineTo((right, bottom))
    pen.lineTo((right, top))
    pen.lineTo((left, top))
    pen.closePath()
    inset = 70
    pen.moveTo((left + inset, bottom + inset))
    pen.lineTo((left + inset, top - inset))
    pen.lineTo((right - inset, top - inset))
    pen.lineTo((right - inset, bottom + inset))
    pen.closePath()
    glyph.correctDirection()
    glyph.round()


def _configure_metrics(font, manifest: dict) -> None:
    font.em = int(manifest["em_size"])
    font.ascent = int(manifest["ascent"])
    font.descent = int(manifest["descent"])
    font.hhea_ascent = font.ascent
    font.hhea_descent = -font.descent
    font.hhea_linegap = 0
    font.os2_typoascent = font.ascent
    font.os2_typodescent = -font.descent
    font.os2_typolinegap = 0
    font.os2_winascent = font.ascent
    font.os2_windescent = font.descent
    font.os2_use_typo_metrics = 1
    font.os2_fstype = 0  # installable embedding; do not restrict customer-owned handwriting fonts.


def _configure_names(font, manifest: dict) -> None:
    font.fontname = manifest["font_name"]
    font.familyname = manifest["family_name"]
    font.fullname = manifest["full_name"]
    font.weight = manifest["style_name"]
    font.appendSFNTName("English (US)", "Family", manifest["family_name"])
    font.appendSFNTName("English (US)", "SubFamily", manifest["style_name"])
    font.appendSFNTName("English (US)", "Fullname", manifest["full_name"])
    font.appendSFNTName("English (US)", "PostScriptName", manifest["font_name"])


def main() -> int:
    manifest_path = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    font = fontforge.font()
    font.encoding = "UnicodeFull"
    _configure_metrics(font, manifest)
    _configure_names(font, manifest)

    side_bearing = int(manifest["side_bearing"])
    notdef_width = max(500, int(manifest.get("space_width", 320)) + 240)
    _draw_notdef(font, notdef_width)

    for glyph_data in manifest["glyphs"]:
        glyph_name = glyph_data.get("glyph_name") or glyph_data["char"]
        glyph = font.createChar(int(glyph_data["codepoint"]), glyph_name)
        if glyph_data.get("empty"):
            glyph.width = int(glyph_data["advance_width"])
            continue
        glyph.importOutlines(glyph_data["svg_path"])
        bbox = glyph.boundingBox()
        imported_width = bbox[2] - bbox[0]
        imported_height = bbox[3] - bbox[1]
        if imported_width <= 0 or imported_height <= 0:
            glyph.width = int(glyph_data["advance_width"])
            continue
        scale_x = float(glyph_data["source_width"]) / imported_width
        scale_y = float(glyph_data["source_height"]) / imported_height
        glyph.transform(psMat.scale(scale_x, scale_y))
        bbox = glyph.boundingBox()
        target_top = font.ascent - int(glyph_data["top_offset"])
        glyph.transform(psMat.translate(side_bearing - bbox[0], target_top - bbox[3]))
        glyph.correctDirection()
        # Potrace already emits single-color silhouette contours for this path.
        # Keep traced geometry intact; extra overlap/simplify passes may rewrite
        # intentional handwritten self-crossings, so structural validation owns
        # rejecting unusable outlines.
        glyph.round()
        glyph.width = int(glyph_data["advance_width"])

    space = font.createChar(0x20, "space")
    space.width = int(manifest["space_width"])

    otf_path = output_dir / f"{manifest['font_name']}.otf"
    ttf_path = output_dir / f"{manifest['font_name']}.ttf"
    sfd_path = output_dir / f"{manifest['font_name']}.sfd"

    if GENERATE_FLAGS_OTF:
        font.generate(str(otf_path), flags=GENERATE_FLAGS_OTF)
    else:
        font.generate(str(otf_path))
    font.generate(str(ttf_path), flags=GENERATE_FLAGS_TTF)
    font.save(str(sfd_path))
    font.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
