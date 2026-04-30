from __future__ import annotations

import argparse

from .pipeline import main as pipeline_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handwrite-font-maker",
        description="Convert a marker-based handwriting specimen sheet into installable fonts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a font from a photographed specimen sheet.")
    build_parser.add_argument("image", help="Path to the specimen sheet photo.")
    build_parser.add_argument("--font-name", required=True, help="PostScript-safe font name.")
    build_parser.add_argument("--family-name", help="Human-readable font family name.")
    build_parser.add_argument("--style-name", default="Regular", help="Font style name.")
    build_parser.add_argument("--output-dir", default="output", help="Output directory.")

    template_parser = subparsers.add_parser("generate-template", help="Generate a print-ready marker template PDF.")
    template_parser.add_argument("--output", required=True, help="PDF path to write.")
    template_parser.add_argument("--paper-size", default="A4", choices=["A4", "LETTER"], help="Paper size.")
    template_parser.add_argument("--layout", default="default-v1", help="Template layout id.")
    return parser


def main() -> int:
    return pipeline_main()


if __name__ == "__main__":
    raise SystemExit(main())
