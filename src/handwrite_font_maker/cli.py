from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image

from .pipeline import build_font
from .rectify import detect_page_corners, load_bgr, rectify_template_photo
from .template import generate_template_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handwrite-font-maker",
        description="Convert handwriting specimen sheets into installable fonts and generate specimen templates.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a font from a legacy ArUco-marked specimen sheet photo.")
    build_parser.add_argument("image", help="Path to the specimen sheet photo.")
    build_parser.add_argument("--font-name", required=True, help="PostScript-safe font name.")
    build_parser.add_argument("--family-name", help="Human-readable font family name.")
    build_parser.add_argument("--style-name", default="Regular", help="Font style name.")
    build_parser.add_argument("--output-dir", default="output", help="Output directory.")
    build_parser.add_argument("--alignment", choices=["markers", "page"], default="markers", help="Use legacy ArUco markers or markerless page alignment.")
    build_parser.add_argument("--corners", help="JSON normalized TL/TR/BR/BL corners, or @path to a JSON file. Omit with --alignment page to auto-detect.")
    build_parser.add_argument("--paper-size", default="A4", choices=["A4", "LETTER"], help="Paper size. Markerless alpha supports A4 only.")

    template_parser = subparsers.add_parser("generate-template", help="Generate a print-ready template PDF.")
    template_parser.add_argument("--output", required=True, help="PDF path to write.")
    template_parser.add_argument("--paper-size", default="A4", choices=["A4", "LETTER"], help="Paper size. Markerless alpha supports A4 only.")
    template_parser.add_argument("--layout", default="default-v1", help="Template layout id.")
    template_parser.add_argument(
        "--markerless",
        "--no-markers",
        dest="include_markers",
        action="store_false",
        default=True,
        help="Generate the A4 default-v1 page template without ArUco markers. Legacy default keeps markers.",
    )

    detect_parser = subparsers.add_parser("detect-corners", help="Suggest markerless A4 page corners for confirmation.")
    detect_parser.add_argument("image", help="Path to the EXIF-oriented page photo.")

    rectify_parser = subparsers.add_parser("rectify-template", help="Rectify a template photo to canonical PNG for debugging.")
    rectify_parser.add_argument("image", help="Path to the template photo.")
    rectify_parser.add_argument("--output", required=True, help="PNG path to write.")
    rectify_parser.add_argument("--alignment", choices=["markers", "page"], default="markers", help="Use ArUco markers or markerless page corners.")
    rectify_parser.add_argument("--corners", help="JSON normalized TL/TR/BR/BL corners, or @path to a JSON file. Omit with --alignment page to auto-detect.")
    rectify_parser.add_argument("--paper-size", default="A4", choices=["A4", "LETTER"], help="Paper size. Markerless alpha supports A4 only.")
    return parser


def _load_corners_arg(value: str | None):
    if value is None:
        return None
    if value.startswith("@"):
        text = Path(value[1:]).expanduser().read_text(encoding="utf-8")
    else:
        text = value
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--corners must be JSON like [[x,y],[x,y],[x,y],[x,y]] or @file: {exc}") from exc


def _normalized_corners(corners, *, width: int, height: int) -> list[list[float]]:
    return [[float(x) / float(width - 1), float(y) / float(height - 1)] for x, y in corners]


def cli_build(
    image: str,
    font_name: str,
    family_name: str | None,
    style_name: str,
    output_dir: str,
    alignment: str = "markers",
    corners=None,
    paper_size: str = "A4",
) -> int:
    outputs = build_font(
        image_path=Path(image).expanduser().resolve(),
        font_name=font_name,
        family_name=family_name,
        style_name=style_name,
        output_dir=Path(output_dir).expanduser().resolve(),
        alignment=alignment,
        corners=corners,
        paper_size=paper_size,
    )

    print(json.dumps(outputs, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        return cli_build(
            image=args.image,
            font_name=args.font_name,
            family_name=args.family_name,
            style_name=args.style_name,
            output_dir=args.output_dir,
            alignment=args.alignment,
            corners=_load_corners_arg(args.corners),
            paper_size=args.paper_size,
        )

    if args.command == "generate-template":
        output = generate_template_pdf(
            args.output,
            layout_id=args.layout,
            paper_size=args.paper_size,
            include_markers=args.include_markers,
        )
        print(json.dumps({"template": str(output), "includeMarkers": bool(args.include_markers)}, indent=2))
        return 0

    if args.command == "detect-corners":
        image = load_bgr(Path(args.image).expanduser().resolve())
        pixel = detect_page_corners(image)
        height, width = image.shape[:2]
        print(json.dumps({"corners": _normalized_corners(pixel, width=width, height=height), "pixelCorners": pixel.tolist()}, indent=2))
        return 0

    if args.command == "rectify-template":
        document = rectify_template_photo(
            Path(args.image).expanduser().resolve(),
            alignment=args.alignment,
            corners=_load_corners_arg(args.corners),
            paper_size=args.paper_size,
        )
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(document.rectified_bgr[:, :, ::-1]).save(output)
        reprojection_error = None if math.isnan(document.reprojection_error_px) else document.reprojection_error_px
        print(json.dumps({"rectified": str(output), "alignment": document.alignment, "reprojectionErrorPx": reprojection_error}, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
