from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .layout import get_layout
from .markers import generate_marker_image
from .schema import DEFAULT_DPI, Rect, TemplateGeometry, TemplateLayout, compute_geometry, page_points


def _paste_grayscale(target: Image.Image, grayscale, box: Rect) -> None:
    marker = Image.fromarray(grayscale).convert("RGB").resize((box.width, box.height), Image.Resampling.NEAREST)
    target.paste(marker, (box.left, box.top))


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = [
        f"/usr/share/fonts/truetype/noto/NotoSans-{'Bold' if bold else 'Regular'}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


_ROW_GROUPS = {
    0: ("UPPERCASE", (240, 243, 252), (155, 172, 212)),
    1: ("UPPERCASE", (240, 243, 252), (155, 172, 212)),
    2: ("UPPERCASE", (240, 243, 252), (155, 172, 212)),
    3: ("lowercase", (252, 242, 240), (212, 162, 155)),
    4: ("lowercase", (252, 242, 240), (212, 162, 155)),
    5: ("lowercase", (252, 242, 240), (212, 162, 155)),
    6: ("DIGITS", (240, 250, 244), (155, 200, 172)),
    7: ("SYMBOLS", (250, 247, 238), (200, 190, 148)),
    8: ("SYMBOLS", (250, 247, 238), (200, 190, 148)),
    9: ("SYMBOLS", (250, 247, 238), (200, 190, 148)),
}

_GROUP_START_ROWS = {0, 3, 6, 7}


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    x1: int,
    fill: tuple[int, int, int],
    dash: int = 4,
    gap: int = 4,
) -> None:
    x = x0
    while x < x1:
        end = min(x + dash, x1)
        draw.line((x, y, end, y), fill=fill, width=1)
        x = end + gap


def render_template_image(
    *,
    layout: TemplateLayout | None = None,
    paper_size: str = "A4",
    dpi: int = DEFAULT_DPI,
) -> Image.Image:
    layout = layout or get_layout(paper_size=paper_size)
    geometry = compute_geometry(layout, dpi=dpi, paper_size=paper_size)
    bg = (251, 250, 248)
    image = Image.new("RGB", (geometry.page_width, geometry.page_height), bg)
    draw = ImageDraw.Draw(image)

    for role, box in geometry.marker_boxes.items():
        marker_id = layout.marker_roles[role]
        marker = generate_marker_image(marker_id, geometry.marker_size, layout.marker_dictionary)
        _paste_grayscale(image, marker, box)

    _draw_header(draw, geometry, layout)

    label_font = _load_font(max(11, geometry.page_width // 95))
    group_font = _load_font(max(8, geometry.page_width // 155), bold=True)

    border_color = (215, 211, 204)
    label_color = (130, 122, 112)
    guide_light = (230, 226, 220)
    guide_baseline = (178, 170, 160)
    guide_descender = (218, 214, 208)
    accent_bar_width = max(2, geometry.page_width // 500)

    for index, (char, cell) in enumerate(zip(layout.chars, geometry.cell_rects, strict=True)):
        row_idx = index // layout.columns
        col_idx = index % layout.columns
        group_name, tint, accent = _ROW_GROUPS.get(row_idx, ("", bg, (200, 200, 200)))

        draw.rectangle((cell.left + 1, cell.top + 1, cell.right - 1, cell.bottom - 1), fill=tint)

        if col_idx == 0:
            draw.rectangle(
                (cell.left, cell.top, cell.left + accent_bar_width, cell.bottom),
                fill=accent,
            )

        if row_idx in _GROUP_START_ROWS and col_idx == 0 and row_idx != 0:
            sep_y = cell.top
            draw.line(
                (geometry.grid_rect.left, sep_y, geometry.grid_rect.right, sep_y),
                fill=accent,
                width=2,
            )

        draw.rectangle((cell.left, cell.top, cell.right, cell.bottom), outline=border_color, width=1)

        label_bbox = draw.textbbox((0, 0), char, font=label_font)
        lw = label_bbox[2] - label_bbox[0]
        lx = cell.left + (cell.width - lw) // 2
        ly = cell.top + 3
        draw.text((lx, ly), char, fill=label_color, font=label_font)

        if col_idx == 0 and row_idx in _GROUP_START_ROWS:
            gx = cell.left + accent_bar_width + 3
            gy = cell.top - group_font.size - 3
            draw.text((gx, gy), group_name, fill=accent, font=group_font)

        inner_left = cell.left + int(round(cell.width * layout.inner_margin_x))
        inner_right = cell.right - int(round(cell.width * layout.inner_margin_x))
        inner_top = cell.top + int(round(cell.height * layout.inner_margin_y))
        inner_bottom = cell.bottom - int(round(cell.height * 0.05))

        for gi, guide_row in enumerate(layout.guide_rows):
            y = int(round(inner_top + ((inner_bottom - inner_top) * guide_row)))
            is_baseline = gi == len(layout.guide_rows) - 2
            is_descender = gi == len(layout.guide_rows) - 1
            if gi == 0:
                _draw_dashed_line(draw, inner_left, y, inner_right, fill=guide_light, dash=5, gap=3)
            elif is_baseline:
                draw.line((inner_left, y, inner_right, y), fill=guide_baseline, width=1)
                draw.line((inner_left, y + 1, inner_right, y + 1), fill=(*guide_baseline[:2], guide_baseline[2] + 20), width=1)
            elif is_descender:
                _draw_dashed_line(draw, inner_left, y, inner_right, fill=guide_descender, dash=3, gap=5)
            else:
                draw.line((inner_left, y, inner_right, y), fill=guide_light, width=1)

    _draw_empty_cells(draw, layout, geometry, bg)
    _draw_footer(draw, geometry)

    return image


def _draw_empty_cells(
    draw: ImageDraw.ImageDraw,
    layout: TemplateLayout,
    geometry: TemplateGeometry,
    bg: tuple[int, int, int],
) -> None:
    total = len(layout.chars)
    last_row = (total - 1) // layout.columns
    filled = total % layout.columns or layout.columns
    if filled >= layout.columns:
        return

    cell_w = geometry.grid_rect.width / layout.columns
    cell_h = geometry.grid_rect.height / layout.rows
    empty_fill = (248, 247, 245)
    empty_border = (232, 229, 224)

    for col in range(filled, layout.columns):
        left = int(round(geometry.grid_rect.left + col * cell_w))
        top = int(round(geometry.grid_rect.top + last_row * cell_h))
        right = int(round(geometry.grid_rect.left + (col + 1) * cell_w)) - 1
        bottom = int(round(geometry.grid_rect.top + (last_row + 1) * cell_h)) - 1
        draw.rectangle((left + 1, top + 1, right - 1, bottom - 1), fill=empty_fill)
        draw.rectangle((left, top, right, bottom), outline=empty_border, width=1)


def _draw_header(draw: ImageDraw.ImageDraw, geometry: TemplateGeometry, layout: TemplateLayout) -> None:
    title_font = _load_font(max(16, geometry.page_width // 60), bold=True)
    subtitle_font = _load_font(max(9, geometry.page_width // 130))
    instr_font = _load_font(max(8, geometry.page_width // 145))

    title_x = geometry.marker_boxes["top_left"].right + 18
    title_y = geometry.margin + 4

    draw.text((title_x, title_y), "Handwriting Font Template", fill=(38, 35, 30), font=title_font)

    subtitle_y = title_y + title_font.size + 4
    draw.text((title_x, subtitle_y), "V1  ·  A-Z  a-z  0-9  Symbols", fill=(160, 155, 148), font=subtitle_font)

    sep_y = subtitle_y + subtitle_font.size + 7
    sep_right = geometry.marker_boxes["top_right"].left - 18
    draw.line((title_x, sep_y, sep_right, sep_y), fill=(225, 221, 215), width=1)

    instr_y = sep_y + 7
    instructions = [
        "Write one character per cell using a dark pen.  Keep strokes inside the guide lines.",
        "Print at 100% scale (no fit-to-page).  Keep all four corner markers fully visible.",
    ]
    for line in instructions:
        draw.text((title_x, instr_y), line, fill=(145, 140, 132), font=instr_font)
        instr_y += instr_font.size + 3


def _draw_footer(draw: ImageDraw.ImageDraw, geometry: TemplateGeometry) -> None:
    footer_font = _load_font(max(7, geometry.page_width // 170))
    footer_y = geometry.marker_boxes["bottom_left"].top - footer_font.size - 10
    footer_x = geometry.marker_boxes["bottom_left"].right + 18
    draw.text(
        (footer_x, footer_y),
        "handwrite-font-maker  ·  Do not fold, cut, or obscure the corner markers",
        fill=(180, 175, 168),
        font=footer_font,
    )


def generate_template_pdf(
    output_path: str | Path,
    *,
    layout_id: str = "default-v1",
    paper_size: str = "A4",
    dpi: int = DEFAULT_DPI,
) -> Path:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    layout = get_layout(layout_id=layout_id, paper_size=paper_size)
    geometry = compute_geometry(layout, dpi=dpi, paper_size=paper_size)
    width_pt, height_pt = page_points(paper_size)

    sx = width_pt / geometry.page_width
    sy = height_pt / geometry.page_height

    def px(x: float) -> float:
        return x * sx

    def py(y: float) -> float:
        return height_pt - y * sy

    _register_pdf_fonts(pdfmetrics)

    pdf = canvas.Canvas(str(output), pagesize=(width_pt, height_pt))

    pdf.setFillColorRGB(251 / 255, 250 / 255, 248 / 255)
    pdf.rect(0, 0, width_pt, height_pt, fill=1, stroke=0)

    for role, box in geometry.marker_boxes.items():
        marker_id = layout.marker_roles[role]
        marker_arr = generate_marker_image(marker_id, geometry.marker_size, layout.marker_dictionary)
        marker_img = Image.fromarray(marker_arr).convert("RGB")
        buf = BytesIO()
        marker_img.save(buf, format="PNG")
        buf.seek(0)
        pdf.drawImage(
            ImageReader(buf),
            px(box.left), py(box.bottom),
            width=px(box.width), height=py(box.top) - py(box.bottom),
        )

    _draw_header_pdf(pdf, geometry, layout, px, py)

    guide_light = (230, 226, 220)
    guide_baseline = (178, 170, 160)
    guide_descender = (218, 214, 208)
    border_color = (215, 211, 204)
    label_color = (130, 122, 112)
    accent_bar_w = max(2, geometry.page_width // 500)

    label_pt = max(7, width_pt / 95)
    group_pt = max(5, width_pt / 155)

    for index, (char, cell) in enumerate(zip(layout.chars, geometry.cell_rects, strict=True)):
        row_idx = index // layout.columns
        col_idx = index % layout.columns
        group_name, tint, accent = _ROW_GROUPS.get(row_idx, ("", (251, 250, 248), (200, 200, 200)))

        cx, cy = px(cell.left), py(cell.bottom)
        cw, ch = px(cell.width), py(cell.top) - py(cell.bottom)

        pdf.setFillColorRGB(tint[0] / 255, tint[1] / 255, tint[2] / 255)
        pdf.rect(cx, cy, cw, ch, fill=1, stroke=0)

        if col_idx == 0:
            pdf.setFillColorRGB(accent[0] / 255, accent[1] / 255, accent[2] / 255)
            pdf.rect(cx, cy, px(accent_bar_w), ch, fill=1, stroke=0)

        if row_idx in _GROUP_START_ROWS and col_idx == 0 and row_idx != 0:
            sep_y_pt = py(cell.top)
            pdf.setStrokeColorRGB(accent[0] / 255, accent[1] / 255, accent[2] / 255)
            pdf.setLineWidth(1.2)
            pdf.line(px(geometry.grid_rect.left), sep_y_pt, px(geometry.grid_rect.right), sep_y_pt)

        pdf.setStrokeColorRGB(border_color[0] / 255, border_color[1] / 255, border_color[2] / 255)
        pdf.setLineWidth(0.5)
        pdf.rect(cx, cy, cw, ch, fill=0, stroke=1)

        pdf.setFillColorRGB(label_color[0] / 255, label_color[1] / 255, label_color[2] / 255)
        pdf.setFont("TemplateSans", label_pt)
        tw = pdf.stringWidth(char, "TemplateSans", label_pt)
        pdf.drawString(cx + (cw - tw) / 2, py(cell.top + 3) - label_pt, char)

        if col_idx == 0 and row_idx in _GROUP_START_ROWS:
            pdf.setFillColorRGB(accent[0] / 255, accent[1] / 255, accent[2] / 255)
            pdf.setFont("TemplateSansBold", group_pt)
            pdf.drawString(px(cell.left + accent_bar_w + 3), py(cell.top) + 1, group_name)

        inner_left = cell.left + int(round(cell.width * layout.inner_margin_x))
        inner_right = cell.right - int(round(cell.width * layout.inner_margin_x))
        inner_top = cell.top + int(round(cell.height * layout.inner_margin_y))
        inner_bottom = cell.bottom - int(round(cell.height * 0.05))

        for gi, guide_row in enumerate(layout.guide_rows):
            gy = int(round(inner_top + ((inner_bottom - inner_top) * guide_row)))
            is_baseline = gi == len(layout.guide_rows) - 2
            is_descender = gi == len(layout.guide_rows) - 1
            if gi == 0:
                _pdf_dashed_line(pdf, px(inner_left), py(gy), px(inner_right), py(gy),
                                 guide_light, dash=3, gap=2.5)
            elif is_baseline:
                pdf.setStrokeColorRGB(guide_baseline[0] / 255, guide_baseline[1] / 255, guide_baseline[2] / 255)
                pdf.setLineWidth(0.8)
                pdf.line(px(inner_left), py(gy), px(inner_right), py(gy))
            elif is_descender:
                _pdf_dashed_line(pdf, px(inner_left), py(gy), px(inner_right), py(gy),
                                 guide_descender, dash=2, gap=3)
            else:
                pdf.setStrokeColorRGB(guide_light[0] / 255, guide_light[1] / 255, guide_light[2] / 255)
                pdf.setLineWidth(0.5)
                pdf.line(px(inner_left), py(gy), px(inner_right), py(gy))

    total = len(layout.chars)
    last_row = (total - 1) // layout.columns
    filled = total % layout.columns or layout.columns
    if filled < layout.columns:
        cell_w = geometry.grid_rect.width / layout.columns
        cell_h = geometry.grid_rect.height / layout.rows
        for col in range(filled, layout.columns):
            left = geometry.grid_rect.left + col * cell_w
            top = geometry.grid_rect.top + last_row * cell_h
            pdf.setFillColorRGB(248 / 255, 247 / 255, 245 / 255)
            pdf.rect(px(left), py(top + cell_h), px(cell_w), py(top) - py(top + cell_h), fill=1, stroke=0)
            pdf.setStrokeColorRGB(232 / 255, 229 / 255, 224 / 255)
            pdf.setLineWidth(0.4)
            pdf.rect(px(left), py(top + cell_h), px(cell_w), py(top) - py(top + cell_h), fill=0, stroke=1)

    _draw_footer_pdf(pdf, geometry, px, py)

    pdf.showPage()
    pdf.save()
    return output


def _register_pdf_fonts(pdfmetrics) -> None:
    from reportlab.pdfbase.ttfonts import TTFont
    font_paths = {
        "TemplateSans": [
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
        "TemplateSansBold": [
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
    }
    for name, paths in font_paths.items():
        for path in paths:
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                break
            except Exception:
                continue


def _pdf_dashed_line(
    pdf, x0: float, y0: float, x1: float, y1: float,
    color: tuple[int, int, int], dash: float = 3, gap: float = 2.5,
) -> None:
    pdf.setStrokeColorRGB(color[0] / 255, color[1] / 255, color[2] / 255)
    pdf.setLineWidth(0.5)
    pdf.setDash(dash, gap)
    pdf.line(x0, y0, x1, y1)
    pdf.setDash()


def _draw_header_pdf(pdf, geometry: TemplateGeometry, layout: TemplateLayout, px, py) -> None:
    title_pt = max(10, px(geometry.page_width) / 60)
    subtitle_pt = max(6, px(geometry.page_width) / 130)
    instr_pt = max(5.5, px(geometry.page_width) / 145)

    title_x = px(geometry.marker_boxes["top_left"].right + 18)
    title_y = py(geometry.margin + 4) - title_pt

    pdf.setFont("TemplateSansBold", title_pt)
    pdf.setFillColorRGB(38 / 255, 35 / 255, 30 / 255)
    pdf.drawString(title_x, title_y, "Handwriting Font Template")

    subtitle_y = title_y - subtitle_pt - 3
    pdf.setFont("TemplateSans", subtitle_pt)
    pdf.setFillColorRGB(160 / 255, 155 / 255, 148 / 255)
    pdf.drawString(title_x, subtitle_y, "V1  ·  A-Z  a-z  0-9  Symbols")

    sep_y = subtitle_y - 5
    sep_right = px(geometry.marker_boxes["top_right"].left - 18)
    pdf.setStrokeColorRGB(225 / 255, 221 / 255, 215 / 255)
    pdf.setLineWidth(0.5)
    pdf.line(title_x, sep_y, sep_right, sep_y)

    instr_y = sep_y - instr_pt - 4
    pdf.setFont("TemplateSans", instr_pt)
    pdf.setFillColorRGB(145 / 255, 140 / 255, 132 / 255)
    for line in [
        "Write one character per cell using a dark pen.  Keep strokes inside the guide lines.",
        "Print at 100% scale (no fit-to-page).  Keep all four corner markers fully visible.",
    ]:
        pdf.drawString(title_x, instr_y, line)
        instr_y -= instr_pt + 2


def _draw_footer_pdf(pdf, geometry: TemplateGeometry, px, py) -> None:
    footer_pt = max(4.5, px(geometry.page_width) / 170)
    footer_x = px(geometry.marker_boxes["bottom_left"].right + 18)
    footer_y = py(geometry.marker_boxes["bottom_left"].top) + footer_pt + 6
    pdf.setFont("TemplateSans", footer_pt)
    pdf.setFillColorRGB(180 / 255, 175 / 255, 168 / 255)
    pdf.drawString(footer_x, footer_y, "handwrite-font-maker  ·  Do not fold, cut, or obscure the corner markers")
