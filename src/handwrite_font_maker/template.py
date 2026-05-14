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
    6: ("0 - 9", (240, 250, 244), (155, 200, 172)),
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
    group_font = _load_font(max(7, geometry.page_width // 175), bold=True)

    border_color = (215, 211, 204)
    label_color = (130, 122, 112)
    guide_light = (228, 224, 218)
    guide_baseline = (188, 180, 170)
    accent_bar_width = max(2, geometry.page_width // 500)

    prev_group = None
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
            if gi == 0:
                _draw_dashed_line(draw, inner_left, y, inner_right, fill=guide_light)
            elif is_baseline:
                draw.line((inner_left, y, inner_right, y), fill=guide_baseline, width=1)
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

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    layout = get_layout(layout_id=layout_id, paper_size=paper_size)
    image = render_template_image(layout=layout, paper_size=paper_size, dpi=dpi)
    width_pt, height_pt = page_points(paper_size)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    pdf = canvas.Canvas(str(output), pagesize=(width_pt, height_pt))
    pdf.drawImage(ImageReader(buffer), 0, 0, width=width_pt, height=height_pt, preserveAspectRatio=False, mask=None)
    pdf.showPage()
    pdf.save()
    return output
