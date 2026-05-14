"""Generate or edit images using the Gemini API.

Usage:
    # Text-to-image
    python scripts/gemini_imagegen.py generate "a blue circle on white" -o output.png

    # Image-to-image (edit/transform)
    python scripts/gemini_imagegen.py edit input.png "fill in the cells with handwriting" -o output.png

    # Use a specific model
    python scripts/gemini_imagegen.py generate "prompt" --model gemini-3.1-flash-image-preview

Requires GEMINI_API_KEY environment variable or .env file in repo root.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("Error: GEMINI_API_KEY not found in environment or .env", file=sys.stderr)
    sys.exit(1)


def generate(prompt: str, *, model: str, output: Path) -> Path:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_load_api_key())
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    return _save_image(response, output)


def edit(image_path: Path, instruction: str, *, model: str, output: Path) -> Path:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_load_api_key())
    image_bytes = image_path.read_bytes()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            instruction,
        ],
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    return _save_image(response, output)


def _save_image(response, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            output.write_bytes(part.inline_data.data)
            print(f"Saved: {output} ({len(part.inline_data.data)} bytes)")
            return output
        if part.text is not None:
            print(f"Model text: {part.text[:500]}")
    print("Error: No image in response", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini image generation")
    parser.add_argument("--model", default="gemini-3.1-flash-image-preview")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Text-to-image")
    gen.add_argument("prompt")
    gen.add_argument("-o", "--output", type=Path, default=Path("generated.png"))

    ed = sub.add_parser("edit", help="Image-to-image")
    ed.add_argument("image", type=Path)
    ed.add_argument("instruction")
    ed.add_argument("-o", "--output", type=Path, default=Path("edited.png"))

    args = parser.parse_args()
    if args.command == "generate":
        generate(args.prompt, model=args.model, output=args.output)
    elif args.command == "edit":
        edit(args.image, args.instruction, model=args.model, output=args.output)


if __name__ == "__main__":
    main()
