#!/usr/bin/env fontforge
import json
import sys
from pathlib import Path

import fontforge
import psMat


def main() -> int:
    manifest_path = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    font = fontforge.font()
    font.encoding = "UnicodeFull"
    font.em = int(manifest["em_size"])
    font.ascent = int(manifest["ascent"])
    font.descent = int(manifest["descent"])
    font.fontname = manifest["font_name"]
    font.familyname = manifest["family_name"]
    font.fullname = manifest["full_name"]
    font.weight = manifest["style_name"]

    font.appendSFNTName("English (US)", "Family", manifest["family_name"])
    font.appendSFNTName("English (US)", "SubFamily", manifest["style_name"])
    font.appendSFNTName("English (US)", "Fullname", manifest["full_name"])
    font.appendSFNTName("English (US)", "PostScriptName", manifest["font_name"])

    side_bearing = int(manifest["side_bearing"])

    for glyph_data in manifest["glyphs"]:
        glyph = font.createChar(int(glyph_data["codepoint"]), glyph_data["char"])
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
        glyph.removeOverlap()
        glyph.simplify()
        glyph.round()
        glyph.correctDirection()
        glyph.width = int(glyph_data["advance_width"])

    space = font.createChar(0x20, "space")
    space.width = int(manifest["space_width"])

    otf_path = output_dir / f"{manifest['font_name']}.otf"
    ttf_path = output_dir / f"{manifest['font_name']}.ttf"
    sfd_path = output_dir / f"{manifest['font_name']}.sfd"

    font.generate(str(otf_path))
    font.generate(str(ttf_path))
    font.save(str(sfd_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
