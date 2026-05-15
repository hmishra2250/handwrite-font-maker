"""Generate 30 synthetic mobile-phone-like captures and test detection pipeline.

Each image simulates a realistic phone capture with combinations of:
- Perspective warp (tilt 0.02–0.20)
- Brightness variation (0.4–1.5x)
- Gaussian noise (sigma 0–25)
- JPEG compression (quality 15–95)
- Zoom/crop (0%–25% border crop)
- Page bend (barrel/pincushion distortion)
- Partial shadow (one half darkened)
- Color cast (warm/cool shift)
- Rotation (slight off-axis)
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from handwrite_font_maker.template import render_template_image
from handwrite_font_maker.layout import get_layout
from handwrite_font_maker.schema import compute_geometry
from handwrite_font_maker.rectify import rectify_template_photo
from handwrite_font_maker.extract import extract_cells


@dataclass
class CaptureParams:
    name: str
    tilt: float = 0.0
    brightness: float = 1.0
    noise_sigma: float = 0.0
    jpeg_quality: int = 95
    zoom_crop: float = 0.0
    barrel_k: float = 0.0
    shadow_strength: float = 0.0
    color_shift: tuple[int, int, int] = (0, 0, 0)
    rotation_deg: float = 0.0


@dataclass
class CaptureResult:
    name: str
    params: CaptureParams
    passed: bool
    reprojection_error: float | None = None
    cells_found: int | None = None
    error_message: str = ""


def apply_perspective(image: Image.Image, tilt: float, rng: np.random.Generator) -> Image.Image:
    if tilt <= 0:
        return image
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dx = w * tilt
    dy = h * tilt * (0.2 + rng.random() * 0.3)
    jitter = lambda v: v * (0.8 + rng.random() * 0.4)
    dst = np.float32([
        [jitter(dx), jitter(dy)],
        [w - jitter(dx), rng.random() * dy * 0.3],
        [w - 1 - rng.random() * dx * 0.2, h - jitter(dy)],
        [rng.random() * dx * 0.3, h - jitter(dy) * 0.5],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(arr, M, (w, h), borderValue=(245, 244, 242))
    return Image.fromarray(warped)


def apply_barrel_distortion(image: Image.Image, k: float) -> Image.Image:
    if abs(k) < 1e-6:
        return image
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    fx = fy = max(w, h)
    cx, cy = w / 2.0, h / 2.0
    camera_matrix = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    dist_coeffs = np.array([k, k * 0.1, 0, 0], dtype=np.float64)
    map1, map2 = cv2.initUndistortRectifyMap(camera_matrix, dist_coeffs, None, camera_matrix, (w, h), cv2.CV_32FC1)
    distorted = cv2.remap(arr, map1, map2, cv2.INTER_LINEAR, borderValue=(245, 244, 242))
    return Image.fromarray(distorted)


def apply_noise(image: Image.Image, sigma: float, rng: np.random.Generator) -> Image.Image:
    if sigma <= 0:
        return image
    arr = np.array(image).astype(np.float32)
    arr += rng.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def apply_brightness(image: Image.Image, factor: float) -> Image.Image:
    if abs(factor - 1.0) < 0.01:
        return image
    return ImageEnhance.Brightness(image).enhance(factor)


def apply_jpeg_compression(image: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def apply_zoom_crop(image: Image.Image, crop_frac: float) -> Image.Image:
    if abs(crop_frac) < 0.001:
        return image
    w, h = image.size
    if crop_frac < 0:
        pad = abs(crop_frac)
        px = int(w * pad)
        py = int(h * pad)
        padded = Image.new("RGB", (w + 2 * px, h + 2 * py), (235, 232, 228))
        padded.paste(image, (px, py))
        return padded.resize((w, h), Image.Resampling.LANCZOS)
    dx = int(w * crop_frac)
    dy = int(h * crop_frac)
    cropped = image.crop((dx, dy, w - dx, h - dy))
    return cropped.resize((w, h), Image.Resampling.LANCZOS)


def apply_shadow(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    if strength <= 0:
        return image
    arr = np.array(image).astype(np.float32)
    h, w = arr.shape[:2]
    direction = rng.choice(["left", "right", "top", "bottom"])
    gradient = np.ones((h, w), dtype=np.float32)
    if direction == "left":
        gradient[:, :w // 2] = np.linspace(1 - strength, 1, w // 2)
    elif direction == "right":
        gradient[:, w // 2:] = np.linspace(1, 1 - strength, w - w // 2)
    elif direction == "top":
        gradient[:h // 2, :] = np.linspace(1 - strength, 1, h // 2).reshape(-1, 1)
    else:
        gradient[h // 2:, :] = np.linspace(1, 1 - strength, h - h // 2).reshape(-1, 1)
    arr *= gradient[:, :, np.newaxis]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def apply_color_shift(image: Image.Image, shift: tuple[int, int, int]) -> Image.Image:
    if all(s == 0 for s in shift):
        return image
    arr = np.array(image).astype(np.int16)
    arr += np.array(shift, dtype=np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def apply_rotation(image: Image.Image, degrees: float) -> Image.Image:
    if abs(degrees) < 0.1:
        return image
    return image.rotate(degrees, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=(245, 244, 242))


def generate_capture(base: Image.Image, params: CaptureParams, rng: np.random.Generator) -> Image.Image:
    img = base.copy()
    img = apply_rotation(img, params.rotation_deg)
    img = apply_barrel_distortion(img, params.barrel_k)
    img = apply_perspective(img, params.tilt, rng)
    img = apply_brightness(img, params.brightness)
    img = apply_shadow(img, params.shadow_strength, rng)
    img = apply_color_shift(img, params.color_shift)
    img = apply_noise(img, params.noise_sigma, rng)
    img = apply_zoom_crop(img, params.zoom_crop)
    if params.jpeg_quality < 95:
        img = apply_jpeg_compression(img, params.jpeg_quality)
    return img


def test_capture(image: Image.Image, params: CaptureParams) -> CaptureResult:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        image.save(f.name)
        try:
            doc = rectify_template_photo(f.name)
            cells = extract_cells(doc.metadata, doc.geometry)
            passed = doc.reprojection_error_px < 5.0 and len(cells) == 94
            return CaptureResult(
                name=params.name,
                params=params,
                passed=passed,
                reprojection_error=doc.reprojection_error_px,
                cells_found=len(cells),
            )
        except Exception as e:
            return CaptureResult(
                name=params.name,
                params=params,
                passed=False,
                error_message=str(e),
            )
        finally:
            Path(f.name).unlink(missing_ok=True)


CAPTURES: list[CaptureParams] = [
    # --- Clean baselines ---
    CaptureParams(name="01_clean", tilt=0.0),
    CaptureParams(name="02_bw_clean", brightness=1.0),

    # --- Perspective only ---
    CaptureParams(name="03_tilt_light", tilt=0.04),
    CaptureParams(name="04_tilt_medium", tilt=0.10),
    CaptureParams(name="05_tilt_heavy", tilt=0.16),
    CaptureParams(name="06_tilt_extreme", tilt=0.20),

    # --- Brightness ---
    CaptureParams(name="07_very_dark", brightness=0.40),
    CaptureParams(name="08_dark", brightness=0.55),
    CaptureParams(name="09_bright", brightness=1.40),
    CaptureParams(name="10_overexposed", brightness=1.60),

    # --- Noise ---
    CaptureParams(name="11_noise_light", noise_sigma=8),
    CaptureParams(name="12_noise_heavy", noise_sigma=20),
    CaptureParams(name="13_noise_extreme", noise_sigma=30),

    # --- JPEG compression ---
    CaptureParams(name="14_jpeg_q50", jpeg_quality=50),
    CaptureParams(name="15_jpeg_q25", jpeg_quality=25),
    CaptureParams(name="16_jpeg_q15", jpeg_quality=15),

    # --- Zoom: page with extra background margin (simulates phone held farther away) ---
    CaptureParams(name="17_far_zoom", zoom_crop=-0.10),
    CaptureParams(name="18_close_zoom", zoom_crop=-0.02),
    # --- Slight edge crop (user barely crops a corner — known limitation boundary) ---
    CaptureParams(name="19_edge_crop_3pct", zoom_crop=0.03),

    # --- Page bend (barrel distortion) ---
    CaptureParams(name="20_bend_slight", barrel_k=-0.08),
    CaptureParams(name="21_bend_moderate", barrel_k=-0.18),
    CaptureParams(name="22_bend_heavy", barrel_k=-0.30),

    # --- Shadow ---
    CaptureParams(name="23_shadow_light", shadow_strength=0.25),
    CaptureParams(name="24_shadow_heavy", shadow_strength=0.50),

    # --- Color cast ---
    CaptureParams(name="25_warm_cast", color_shift=(15, 5, -10)),
    CaptureParams(name="26_cool_cast", color_shift=(-10, -3, 12)),
    CaptureParams(name="27_fluorescent", color_shift=(-5, 10, -5)),

    # --- Combined realistic scenarios ---
    CaptureParams(name="28_phone_desk", tilt=0.08, brightness=0.85, noise_sigma=10, jpeg_quality=70, shadow_strength=0.15),
    CaptureParams(name="29_phone_hand", tilt=0.14, brightness=0.70, noise_sigma=15, jpeg_quality=45, barrel_k=-0.10, rotation_deg=1.5),
    CaptureParams(name="30_worst_case", tilt=0.18, brightness=0.50, noise_sigma=22, jpeg_quality=25, barrel_k=-0.15, shadow_strength=0.40, zoom_crop=0.03, rotation_deg=2.0),
]


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "synthetic_captures"


def main():
    layout = get_layout()
    base = render_template_image(layout=layout, dpi=150)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(42)
    results: list[CaptureResult] = []

    print(f"{'#':<4} {'Name':<25} {'Pass':>5} {'Reproj':>8} {'Cells':>6} {'Error'}")
    print("-" * 80)

    for params in CAPTURES:
        cached = FIXTURES_DIR / f"{params.name}.png"
        if cached.exists():
            capture = Image.open(cached).convert("RGB")
        else:
            capture = generate_capture(base, params, rng)
            capture.save(cached, optimize=True)
        result = test_capture(capture, params)
        results.append(result)

        status = "PASS" if result.passed else "FAIL"
        reproj = f"{result.reprojection_error:.2f}" if result.reprojection_error is not None else "N/A"
        cells = str(result.cells_found) if result.cells_found is not None else "N/A"
        err = result.error_message[:40] if result.error_message else ""
        print(f"{len(results):<4} {params.name:<25} {status:>5} {reproj:>8} {cells:>6} {err}")

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    reproj_values = [r.reprojection_error for r in results if r.reprojection_error is not None]

    print("\n" + "=" * 80)
    print(f"RESULTS: {passed}/{len(results)} passed, {failed} failed")
    if reproj_values:
        print(f"Reprojection error: min={min(reproj_values):.2f}px, max={max(reproj_values):.2f}px, mean={sum(reproj_values)/len(reproj_values):.2f}px")
    print()

    print("FAILURES:")
    failures = [r for r in results if not r.passed]
    if not failures:
        print("  (none)")
    for r in failures:
        print(f"  {r.name}: reproj={r.reprojection_error}, cells={r.cells_found}, err={r.error_message[:60]}")

    print()
    print("LIMITATIONS IDENTIFIED:")
    for r in failures:
        p = r.params
        issues = []
        if p.tilt >= 0.18:
            issues.append(f"extreme perspective (tilt={p.tilt})")
        if p.brightness <= 0.45:
            issues.append(f"very dark (brightness={p.brightness})")
        if p.brightness >= 1.5:
            issues.append(f"overexposed (brightness={p.brightness})")
        if p.noise_sigma >= 25:
            issues.append(f"heavy noise (sigma={p.noise_sigma})")
        if p.jpeg_quality <= 20:
            issues.append(f"extreme compression (q={p.jpeg_quality})")
        if p.zoom_crop >= 0.15:
            issues.append(f"heavy crop/zoom ({p.zoom_crop*100:.0f}%)")
        if abs(p.barrel_k) >= 0.25:
            issues.append(f"heavy page bend (k={p.barrel_k})")
        if p.shadow_strength >= 0.4:
            issues.append(f"heavy shadow ({p.shadow_strength})")
        if abs(p.rotation_deg) >= 1.5:
            issues.append(f"rotation ({p.rotation_deg} deg)")
        if issues:
            print(f"  {r.name}: {', '.join(issues)}")
        else:
            print(f"  {r.name}: failed under moderate conditions - potential bug")

    report = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed/len(results)*100:.1f}%",
        "reproj_min": min(reproj_values) if reproj_values else None,
        "reproj_max": max(reproj_values) if reproj_values else None,
        "reproj_mean": sum(reproj_values) / len(reproj_values) if reproj_values else None,
        "results": [
            {
                "name": r.name,
                "passed": r.passed,
                "reprojection_error": r.reprojection_error,
                "cells_found": r.cells_found,
                "error": r.error_message or None,
                "params": {
                    "tilt": r.params.tilt,
                    "brightness": r.params.brightness,
                    "noise_sigma": r.params.noise_sigma,
                    "jpeg_quality": r.params.jpeg_quality,
                    "zoom_crop": r.params.zoom_crop,
                    "barrel_k": r.params.barrel_k,
                    "shadow_strength": r.params.shadow_strength,
                    "color_shift": list(r.params.color_shift),
                    "rotation_deg": r.params.rotation_deg,
                },
            }
            for r in results
        ],
        "failures": [r.name for r in failures],
    }

    report_path = Path(__file__).resolve().parents[1] / "tests" / "capture_test_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
