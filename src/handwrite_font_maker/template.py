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


_CHAR_GROUPS = {
    "upper": {"label": "A - Z", "tint": (222, 230, 250), "accent": (100, 132, 200), "accent_light": (162, 182, 228)},
    "lower": {"label": "a - z", "tint": (250, 230, 222), "accent": (200, 115, 100), "accent_light": (228, 172, 162)},
    "digit": {"label": "0 - 9", "tint": (222, 246, 234), "accent": (85, 170, 130), "accent_light": (152, 210, 182)},
    "symbol": {"label": "Symbols", "tint": (246, 240, 218), "accent": (170, 155, 95), "accent_light": (205, 195, 152)},
}


def _char_group(ch: str) -> str:
    if ch.isupper():
        return "upper"
    if ch.islower():
        return "lower"
    if ch.isdigit():
        return "digit"
    return "symbol"


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int,
    fill: tuple[int, int, int], dash: int = 6, gap: int = 4,
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
    pw = geometry.page_width
    bg = (250, 249, 247)
    image = Image.new("RGB", (pw, geometry.page_height), bg)
    draw = ImageDraw.Draw(image)

    for role, box in geometry.marker_boxes.items():
        marker_id = layout.marker_roles[role]
        marker = generate_marker_image(marker_id, geometry.marker_size, layout.marker_dictionary)
        _paste_grayscale(image, marker, box)

    _draw_header(draw, geometry, layout)

    label_font = _load_font(max(15, pw // 70))
    label_font_sm = _load_font(max(12, pw // 95))
    group_font = _load_font(max(10, pw // 115), bold=True)

    border_outer = (200, 196, 188)
    border_inner = (225, 221, 215)
    label_color = (72, 65, 55)
    label_color_sym = (128, 120, 110)
    guide_cap = (185, 180, 172)
    guide_baseline = (140, 125, 118)
    guide_descender = (200, 196, 188)
    accent_bar_w = max(3, pw // 280)

    prev_group = None
    group_first_indices = {}

    for index, char in enumerate(layout.chars):
        gtype = _char_group(char)
        if gtype not in group_first_indices:
            group_first_indices[gtype] = index

    for index, (char, cell) in enumerate(zip(layout.chars, geometry.cell_rects, strict=True)):
        row_idx = index // layout.columns
        col_idx = index % layout.columns
        gtype = _char_group(char)
        grp = _CHAR_GROUPS[gtype]
        tint = grp["tint"]
        accent = grp["accent"]

        draw.rectangle((cell.left + 1, cell.top + 1, cell.right - 1, cell.bottom - 1), fill=tint)

        is_group_start = group_first_indices.get(gtype) == index
        if is_group_start:
            draw.rectangle(
                (cell.left, cell.top + 1, cell.left + accent_bar_w - 1, cell.bottom - 1),
                fill=accent,
            )

        next_char = layout.chars[index + 1] if index + 1 < len(layout.chars) else None
        next_gtype = _char_group(next_char) if next_char else gtype

        is_top_edge = row_idx == 0
        is_bottom_edge = row_idx == layout.rows - 1
        is_left_edge = col_idx == 0
        is_right_edge = col_idx == layout.columns - 1

        top_b = border_outer if is_top_edge else border_inner
        bottom_b = border_outer if is_bottom_edge else border_inner
        left_b = border_outer if is_left_edge else border_inner
        right_b = border_outer if is_right_edge else border_inner

        if is_group_start and index > 0:
            if col_idx == 0:
                top_b = accent
            else:
                left_b = accent

        draw.line((cell.left, cell.top, cell.right, cell.top), fill=top_b, width=1)
        draw.line((cell.left, cell.bottom, cell.right, cell.bottom), fill=bottom_b, width=1)
        draw.line((cell.left, cell.top, cell.left, cell.bottom), fill=left_b, width=1)
        draw.line((cell.right, cell.top, cell.right, cell.bottom), fill=right_b, width=1)

        is_sym = not char.isalnum()
        font = label_font_sm if is_sym else label_font
        color = label_color_sym if is_sym else label_color
        bbox = draw.textbbox((0, 0), char, font=font)
        lw = bbox[2] - bbox[0]
        lx = cell.left + (cell.width - lw) // 2
        ly = cell.top + 2
        draw.text((lx, ly), char, fill=color, font=font)

        if is_group_start:
            gy = cell.top - group_font.size - 3
            gx = cell.left + (accent_bar_w + 2 if col_idx == 0 else 1)
            draw.text((gx, gy), grp["label"], fill=accent, font=group_font)

        inner_left = cell.left + int(round(cell.width * layout.inner_margin_x))
        inner_right = cell.right - int(round(cell.width * layout.inner_margin_x))
        inner_top = cell.top + int(round(cell.height * layout.inner_margin_y))
        inner_bottom = cell.bottom - int(round(cell.height * 0.05))

        for gi, guide_row in enumerate(layout.guide_rows):
            y = int(round(inner_top + ((inner_bottom - inner_top) * guide_row)))
            is_baseline = gi == len(layout.guide_rows) - 2
            is_descender = gi == len(layout.guide_rows) - 1
            if gi == 0:
                _draw_dashed_line(draw, inner_left, y, inner_right, fill=guide_cap, dash=6, gap=4)
            elif is_baseline:
                draw.line((inner_left, y, inner_right, y), fill=guide_baseline, width=2)
            elif is_descender:
                _draw_dashed_line(draw, inner_left, y, inner_right, fill=guide_descender, dash=4, gap=5)
            else:
                draw.line((inner_left, y, inner_right, y), fill=guide_cap, width=1)

    _draw_empty_cells(draw, layout, geometry, bg, border_inner)
    _draw_footer(draw, geometry)

    return image


def _draw_empty_cells(
    draw: ImageDraw.ImageDraw,
    layout: TemplateLayout,
    geometry: TemplateGeometry,
    bg: tuple[int, int, int],
    border: tuple[int, int, int],
) -> None:
    total = len(layout.chars)
    last_row = (total - 1) // layout.columns
    filled = total % layout.columns or layout.columns
    if filled >= layout.columns:
        return

    cell_w = geometry.grid_rect.width / layout.columns
    cell_h = geometry.grid_rect.height / layout.rows
    empty_fill = (246, 245, 243)

    for col in range(filled, layout.columns):
        left = int(round(geometry.grid_rect.left + col * cell_w))
        top = int(round(geometry.grid_rect.top + last_row * cell_h))
        right = int(round(geometry.grid_rect.left + (col + 1) * cell_w)) - 1
        bottom = int(round(geometry.grid_rect.top + (last_row + 1) * cell_h)) - 1
        draw.rectangle((left + 1, top + 1, right - 1, bottom - 1), fill=empty_fill)
        for edge in [(left, top, right, top), (left, bottom, right, bottom),
                     (left, top, left, bottom), (right, top, right, bottom)]:
            draw.line(edge, fill=border, width=1)


def _draw_header(draw: ImageDraw.ImageDraw, geometry: TemplateGeometry, layout: TemplateLayout) -> None:
    pw = geometry.page_width
    title_font = _load_font(max(20, pw // 48), bold=True)
    subtitle_font = _load_font(max(10, pw // 112))
    instr_font = _load_font(max(9, pw // 125))

    title_x = geometry.marker_boxes["top_left"].right + 16
    title_y = geometry.margin

    draw.text((title_x, title_y), "Handwriting Font Template", fill=(25, 22, 16), font=title_font)

    sub_y = title_y + title_font.size + 1
    draw.text((title_x, sub_y), "V1", fill=(145, 138, 128), font=subtitle_font)

    v1_w = draw.textbbox((0, 0), "V1", font=subtitle_font)[2]
    info_x = title_x + v1_w + 6
    draw.text((info_x, sub_y + 1), "94 characters  |  Print at 100%, dark pen, no fit-to-page", fill=(170, 164, 155), font=instr_font)

    sep_y = sub_y + subtitle_font.size + 5
    sep_right = geometry.marker_boxes["top_right"].left - 16
    draw.line((title_x, sep_y, sep_right, sep_y), fill=(210, 206, 200), width=1)

    inst_y = sep_y + 5
    draw.text((title_x, inst_y),
              "One character per cell.  Stay within the guide lines.  Keep all corner markers visible.",
              fill=(142, 136, 126), font=instr_font)


def _draw_footer(draw: ImageDraw.ImageDraw, geometry: TemplateGeometry) -> None:
    footer_font = _load_font(max(7, geometry.page_width // 160))
    footer_y = geometry.marker_boxes["bottom_left"].top - footer_font.size - 10
    footer_x = geometry.marker_boxes["bottom_left"].right + 16
    draw.text(
        (footer_x, footer_y),
        "handwrite-font-maker  |  Do not fold, cut, or obscure the corner markers",
        fill=(175, 170, 162),
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

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    layout = get_layout(layout_id=layout_id, paper_size=paper_size)
    geometry = compute_geometry(layout, dpi=dpi, paper_size=paper_size)

    image = render_template_image(layout=layout, paper_size=paper_size, dpi=dpi * 2)
    width_pt, height_pt = page_points(paper_size)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    pdf = canvas.Canvas(str(output), pagesize=(width_pt, height_pt))
    pdf.drawImage(
        ImageReader(buffer), 0, 0,
        width=width_pt, height=height_pt,
        preserveAspectRatio=False, mask=None,
    )
    pdf.showPage()
    pdf.save()
    return output
