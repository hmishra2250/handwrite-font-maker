"""Actual quiet-sheet -> corner alignment -> partial font regression."""
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from handwrite_font_maker.layout import get_layout
from handwrite_font_maker.pipeline import build_font
from handwrite_font_maker.rectify import detect_page_corners, load_bgr
from handwrite_font_maker.schema import compute_geometry
from handwrite_font_maker.template import render_template_image


@pytest.mark.skipif(not shutil.which('potrace') or not shutil.which('fontforge'), reason='Font tools required')
def test_quiet_markerless_sheet_produces_only_written_outlines(tmp_path):
    sheet = render_template_image(include_markers=False)
    layout = get_layout()
    geometry = compute_geometry(layout)
    draw = ImageDraw.Draw(sheet)
    supplied = {'A', 'i', 'O', 'g', '-'}
    for char, cell in zip(layout.chars, geometry.cell_rects, strict=True):
        if char not in supplied:
            continue
        left, right = cell.left + 24, cell.right - 24
        top, bottom = cell.top + 38, cell.bottom - 33
        middle = (left + right) // 2
        if char == 'A':
            draw.line([(left,bottom),(middle,top),(right,bottom)], fill='black', width=4)
            draw.line([(left+10,(top+bottom)//2),(right-10,(top+bottom)//2)], fill='black', width=4)
        elif char == 'i':
            draw.ellipse((middle-3,top,middle+3,top+6),fill='black')
            draw.line((middle,top+17,middle,bottom),fill='black',width=5)
        elif char == '-':
            draw.line((left,(top+bottom)//2,right,(top+bottom)//2),fill='black',width=4)
        elif char == 'O':
            draw.ellipse((left,top,right,bottom),outline='black',width=4)
        else:
            draw.ellipse((left,top,right,bottom-18),outline='black',width=4)
            draw.line([(right,top+18),(right,bottom+9),(middle,bottom+13)],fill='black',width=4)
    # Whole page on a dark flat desk; no ArUco markers supplied.
    photo = Image.new('RGB', (sheet.width+160,sheet.height+160),(45,48,50))
    photo.paste(sheet,(80,80))
    path=tmp_path/'page.png'
    photo.save(path)
    corners=detect_page_corners(load_bgr(path))
    normalized=[[float(x)/(photo.width-1),float(y)/(photo.height-1)] for x,y in corners]
    output=build_font(image_path=path,font_name='QuietPageSmoke',family_name='Quiet Page Smoke',style_name='Regular',output_dir=tmp_path/'font',alignment='page',corners=normalized,paper_size='A4')
    manifest=json.loads(Path(output['manifest']).read_text())
    nonempty={glyph['char'] for glyph in manifest['glyphs'] if not glyph['empty']}
    assert nonempty == supplied, f'Printed guides became glyphs, or writing was lost: {nonempty ^ supplied}'
    ImageFont.truetype(str(output['ttf']),72)
    assert Path(output['ttf']).stat().st_size > 1000
