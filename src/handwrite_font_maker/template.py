from __future__ import annotations

from io import BytesIO
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

from .layout import get_layout, glyph_slug
from .markers import generate_marker_image
from .metadata import encode_metadata, metadata_for_layout
from .schema import DEFAULT_DPI, Rect, TemplateGeometry, TemplateLayout, compute_geometry, page_points


def _paste_grayscale(target: Image.Image, grayscale, box: Rect) -> None:
    marker = Image.fromarray(grayscale).convert("RGB").resize((box.width, box.height), Image.Resampling.NEAREST)
    target.paste(marker, (box.left, box.top))


def _qr_image(payload: str, size: int) -> Image.Image:
    border = 4
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=border, box_size=1)
    qr.add_data(payload)
    qr.make(fit=True)
    modules_with_border = qr.modules_count + (border * 2)
    box_size = max(2, size // modules_with_border)
    qr.box_size = box_size
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    canvas = Image.new("RGB", (size, size), "white")
    x = (size - qr_image.width) // 2
    y = (size - qr_image.height) // 2
    canvas.paste(qr_image, (x, y))
    return canvas


def render_template_image(
    *,
    layout: TemplateLayout | None = None,
    paper_size: str = "A4",
    dpi: int = DEFAULT_DPI,
) -> Image.Image:
    layout = layout or get_layout(paper_size=paper_size)
    geometry = compute_geometry(layout, dpi=dpi, paper_size=paper_size)
    image = Image.new("RGB", (geometry.page_width, geometry.page_height), "white")
    draw = ImageDraw.Draw(image)

    for role, box in geometry.marker_boxes.items():
        marker_id = layout.marker_roles[role]
        marker = generate_marker_image(marker_id, geometry.marker_size, layout.marker_dictionary)
        _paste_grayscale(image, marker, box)
        draw.rectangle((box.left - 2, box.top - 2, box.right + 2, box.bottom + 2), outline=(0, 0, 0), width=1)

    payload = encode_metadata(metadata_for_layout(layout, dpi=dpi))
    qr = _qr_image(payload, geometry.qr_box.width)
    image.paste(qr, (geometry.qr_box.left, geometry.qr_box.top))

    draw.text((geometry.margin, geometry.marker_boxes["top_left"].bottom + 12), "Write one character per box. Print at 100% / no fit-to-page.", fill=(0, 0, 0))

    font = ImageFont.load_default()
    for char, cell in zip(layout.chars, geometry.cell_rects, strict=True):
        draw.rectangle((cell.left, cell.top, cell.right, cell.bottom), outline=(60, 60, 60), width=1)
        label = glyph_slug(char) if char in {'"', "'", "`", "\\"} else char
        draw.text((cell.left + 4, cell.top + 3), label, fill=(90, 90, 90), font=font)
        inner_left = cell.left + int(round(cell.width * layout.inner_margin_x))
        inner_right = cell.right - int(round(cell.width * layout.inner_margin_x))
        inner_top = cell.top + int(round(cell.height * layout.inner_margin_y))
        inner_bottom = cell.bottom - int(round(cell.height * 0.05))
        for row in layout.guide_rows:
            y = int(round(inner_top + ((inner_bottom - inner_top) * row)))
            draw.line((inner_left, y, inner_right, y), fill=(190, 190, 190), width=1)
    return image


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
