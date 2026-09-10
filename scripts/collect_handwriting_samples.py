#!/usr/bin/env python3
"""Collect a bounded, rights-documented real handwriting sample cohort.

No third-party dependencies. This script intentionally acquires only openly
licensed/public-domain page-like handwriting images from Wikimedia Commons and
records SmartDoc 2015 sample-archive schema metadata without extracting frames
(root owns SmartDoc frame acquisition for page-detection benchmarks).

Outputs:
- output/detection-sources/handwriting/*
- docs/research/handwriting-sources.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "detection-sources" / "handwriting"
MANIFEST = ROOT / "docs" / "research" / "handwriting-sources.json"
USER_AGENT = "HandwriteFontMakerResearch/0.2 (open-license sample acquisition; contact local repo maintainer)"
MAX_TOTAL_BYTES = 100 * 1024 * 1024
COMMONS_TARGET = 8
COMMONS_THUMB_WIDTH = 1600
COMMONS_ORIGINAL_MAX_BYTES = 2_500_000

# Keep this narrow: broad manuscript categories admitted photos, paintings, and
# generic writing-implements images. Search terms below prefer page/letter scans.
COMMONS_SEARCH_QUERIES = [
    'incategory:"Handwritten letters" letter',
    '"handwritten letter" filetype:bitmap',
    '"Letter from" "DPLA" filetype:bitmap',
    '"Letter to" "DPLA" filetype:bitmap',
    '"George Washington Letter" "DPLA" filetype:bitmap',
    '"Waldron Letter" "DPLA" filetype:bitmap',
    '"Kathleen Kennedy Letter" "DPLA" filetype:bitmap',
    '"Civil War letter" "DPLA" filetype:bitmap',
    '"manuscript letter" filetype:bitmap',
    '"autograph letter" filetype:bitmap',
]

COMMONS_SEED_TITLES = [
    "File:Cesare Borgia, handwritten letter 2.jpg",
    "File:William Burnett Letter May 24, 1726 - NARA - 193049.jpg",
    "File:Handwritten Letter to D. H. Cook from Carolina Cook - DPLA - 56162c270f60b61e1a3ee47c3f7b5.jpg",
    "File:W. Waldron Letter to Richard Waldron September 10, 1745 - DPLA - a20120e0919ca997e24a3e1d533634d9 (page 1).gif",
    "File:J. Walker Letter - DPLA - d6ad539d282ac49662e05167681e2151 (page 1).gif",
    "File:George Washington Letter to Mrs. Carroll November 22, 1789 - DPLA - 2a7955d332258a03f27b3868135ec92e (page 1).gif",
    "File:Kathleen Kennedy Letter to John F. Kennedy Dearest Jack April 1, 1945 - DPLA - b0adcaa6d6dc809906f3d4db5567ce7a (page 2).gif",
    "File:1906-06-10 Ernst Schlote handschriftlicher Brief aus Tsingtao (Lifang) an Frl. Maria Lüdeke in Linden bei Hannover, Marktplatz 12, Brief Seite 1.jpg",
    "File:1906-06-10 Ernst Schlote handschriftlicher Brief aus Tsingtao (Lifang) an Frl. Maria Lüdeke in Linden bei Hannover, Marktplatz 12, Brief Seite 2 und 3.jpg",
    "File:1906-06-10 Ernst Schlote handschriftlicher Brief aus Tsingtao (Lifang) an Frl. Maria Lüdeke in Linden bei Hannover, Marktplatz 12, Brief Seite 4.jpg",
    "File:Annie Fields to Sarah Watson Dana, 26 March 1867 (afcfff9e-1414-44c2-84c3-98c42497f8ef).jpg",
    "File:Józef Chełmoński list 1859.jpg",
]

# For this research cohort, avoid relicense/attribution ambiguity: use only
# Commons files whose per-file metadata is Public domain or CC0.
COMMONS_LICENSE_ALLOW = {"Public domain", "CC0"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".avi", ".mp4", ".mov", ".mkv"}

SMARTDOC_SAMPLE_URL = "https://zenodo.org/records/1230218/files/sampleDataset.tar.gz?download=1"
SMARTDOC_RECORD_URL = "https://zenodo.org/records/1230218"
SMARTDOC_PRIMARY_PAGE = "http://smartdoc.univ-lr.fr/smartdoc-2015-challenge-1/smartdoc-2015-challenge-1-dataset/"
SMARTDOC_EXPECTED_MD5 = "1ee5b7c290d707bd51c59f0b1c1a36f5"
SMARTDOC_AUTHORS = [
    "Jean-Christophe Burie",
    "Joseph Chazalon",
    "Mickaël Coustaty",
    "Sébastien Eskenazi",
    "Muhammad Muzzamil Luqman",
    "Maroua Mehri",
    "Nibal Nayef",
    "Jean-Marc Ogier",
    "Sophea Prum",
    "Marçal Rusiñol",
]

REJECT_TITLE_PATTERNS = re.compile(
    r"(power[- ]of[- ]words|creative[- ]commons|still life|writing implements|"
    r"973117|e2c6fcf|signature(?!.*letter)|autograph(?!.*letter)|portrait|"
    r"caricature|caricatura|skull|bust|duo |logo|seal|coin|medal|"
    r"typed|typewritten|map|score|music|frontispiece|cover|painting)",
    re.IGNORECASE,
)
POSITIVE_TITLE_PATTERNS = re.compile(
    r"(letter|brief|lettre|carta|correspondence|handwritten|manuscript|diary|"
    r"journal|notebook|postcard|telegram|\(page [0-9]+\)|page [0-9]+|list [0-9]{4})",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def extract_urls(value: str | None) -> list[str]:
    if not value:
        return []
    urls = re.findall(r'href=["\']([^"\']+)["\']', value)
    urls += re.findall(r"https?://[^\s<>\"']+", value)
    cleaned: list[str] = []
    for url in urls:
        url = html.unescape(url)
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http") and url not in cleaned:
            cleaned.append(url)
    return cleaned


def safe_name(value: str, max_len: int = 90) -> str:
    value = strip_html(value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value[:max_len] or "sample"


def request_bytes(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt + 2
            time.sleep(delay)
        except urllib.error.URLError:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt + 1)
    raise RuntimeError(f"failed to request {url}")


def request_json(url: str) -> dict[str, Any]:
    return json.loads(request_bytes(url).decode("utf-8"))


def download(url: str, dest: Path, max_bytes: int | None = None) -> tuple[int, str]:
    h = hashlib.sha256()
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp, tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 128)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise RuntimeError(f"download exceeded byte cap for {url}")
                    h.update(chunk)
                    fh.write(chunk)
            tmp.replace(dest)
            return total, h.hexdigest()
        except urllib.error.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            total = 0
            h = hashlib.sha256()
            if exc.code != 429 or attempt == 4:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 5 + 2 * attempt
            if delay > 15:
                raise RuntimeError(f"rate limited with long Retry-After={delay}s for {url}") from exc
            print(f"rate limited; sleeping {delay}s for {url}")
            time.sleep(delay)
    raise RuntimeError(f"failed to download {url}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - validating published checksum, not security.
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def commons_api(params: dict[str, str]) -> dict[str, Any]:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {**params, "format": "json", "formatversion": "2"}
    )
    return request_json(url)


def commons_search_titles(query: str, limit: int = 45) -> list[str]:
    try:
        data = commons_api(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srnamespace": "6",
                "srlimit": str(limit),
            }
        )
    except Exception as exc:
        print(f"search failed {query!r}: {exc}")
        return []
    time.sleep(1.5)
    return [item["title"] for item in data.get("query", {}).get("search", []) if item.get("title")]


def fetch_imageinfo(titles: list[str]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for i in range(0, len(titles), 25):
        batch = titles[i : i + 25]
        try:
            data = commons_api(
                {
                    "action": "query",
                    "titles": "|".join(batch),
                    "prop": "imageinfo|categories",
                    "iiprop": "url|extmetadata|size|mime",
                    "iiurlwidth": str(COMMONS_THUMB_WIDTH),
                    "cllimit": "max",
                }
            )
        except Exception as exc:
            print(f"metadata batch failed: {exc}")
            time.sleep(5)
            continue
        pages.extend(data.get("query", {}).get("pages", []))
        time.sleep(1.5)
    return pages


def ext(meta: dict[str, Any], key: str) -> str:
    return strip_html((meta.get(key) or {}).get("value"))


def ext_raw(meta: dict[str, Any], key: str) -> str:
    return (meta.get(key) or {}).get("value") or ""


def file_page_url(title: str) -> str:
    return "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe=":_/()'.,-")


def looks_like_handwriting_page(title: str, meta: dict[str, Any], categories: list[str]) -> tuple[bool, str]:
    haystack = " ".join([title, ext(meta, "ObjectName"), ext(meta, "ImageDescription"), " ".join(categories)])
    if REJECT_TITLE_PATTERNS.search(haystack):
        return False, "reject pattern matched non-page/ambiguous content"
    if not POSITIVE_TITLE_PATTERNS.search(haystack):
        return False, "no page/letter/manuscript handwriting signal in title/metadata"
    return True, "title/metadata/category indicate page-like handwriting or historical correspondence"


def collect_commons(target: int = COMMONS_TARGET, seed_only: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[str] = []
    for title in COMMONS_SEED_TITLES:
        candidates.append(title)
    if not seed_only:
        for query in COMMONS_SEARCH_QUERIES:
            for title in commons_search_titles(query):
                if title not in candidates:
                    candidates.append(title)
            if len(candidates) > target * 5:
                break

    samples: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    for page in fetch_imageinfo(candidates):
        if len(samples) >= target:
            break
        title = page.get("title") or ""
        if not title or title in seen:
            continue
        seen.add(title)
        ii = (page.get("imageinfo") or [{}])[0]
        mime = ii.get("mime", "")
        if not mime.startswith("image/"):
            quarantined.append({"title": title, "reason": f"not an image MIME: {mime}"})
            continue
        meta = ii.get("extmetadata") or {}
        categories = [c.get("title", "") for c in page.get("categories", [])]
        license_short = ext(meta, "LicenseShortName")
        ok_content, content_reason = looks_like_handwriting_page(title, meta, categories)
        if license_short not in COMMONS_LICENSE_ALLOW:
            quarantined.append(
                {
                    "title": title,
                    "source_url": file_page_url(title),
                    "license": license_short or "unknown",
                    "reason": "license not in strict Public domain/CC0 allowlist for this acquisition",
                }
            )
            continue
        if not ok_content:
            quarantined.append(
                {
                    "title": title,
                    "source_url": file_page_url(title),
                    "license": license_short,
                    "reason": content_reason,
                }
            )
            continue
        width = int(ii.get("width") or 0)
        height = int(ii.get("height") or 0)
        if width < 600 or height < 600:
            quarantined.append(
                {
                    "title": title,
                    "source_url": file_page_url(title),
                    "license": license_short,
                    "reason": f"too small for page cohort ({width}x{height})",
                }
            )
            continue
        src_url = ii.get("url")
        thumb_url = ii.get("thumburl") or src_url
        if not src_url or not thumb_url:
            quarantined.append({"title": title, "reason": "missing downloadable file URL"})
            continue
        original_size = int(ii.get("size") or 0)
        download_url = src_url if original_size and original_size <= COMMONS_ORIGINAL_MAX_BYTES else thumb_url
        suffix = Path(urllib.parse.urlparse(download_url).path).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            suffix = ".jpg" if mime == "image/jpeg" else ".img"
        base = safe_name(title.removeprefix("File:"))
        if not base.lower().endswith(suffix):
            base += suffix
        out_path = OUT_DIR / f"commons-{len(samples)+1:03d}-{base}"
        try:
            if out_path.exists():
                size, digest = out_path.stat().st_size, sha256_file(out_path)
            else:
                size, digest = download(download_url, out_path, max_bytes=5 * 1024 * 1024)
        except Exception as exc:
            quarantined.append({"title": title, "source_url": file_page_url(title), "reason": f"download failed: {exc}"})
            continue
        if total_bytes + size > MAX_TOTAL_BYTES:
            out_path.unlink(missing_ok=True)
            break
        source_raw = ext_raw(meta, "Source")
        primary_urls = extract_urls(source_raw)
        samples.append(
            {
                "sample_id": f"commons-{len(samples)+1:03d}",
                "cohort": "historical_handwriting_commons",
                "local_path": str(out_path.relative_to(ROOT)),
                "sha256": digest,
                "bytes": size,
                "title": strip_html(ext(meta, "ObjectName") or title.removeprefix("File:")),
                "author": ext(meta, "Artist") or "Unknown/see source page",
                "source_url": file_page_url(title),
                "primary_source_url": primary_urls[0] if primary_urls else file_page_url(title),
                "source_metadata_text": strip_html(source_raw),
                "original_file_url": src_url,
                "download_url": download_url,
                "download_is_resized_derivative": download_url != src_url,
                "width": width,
                "height": height,
                "license": license_short,
                "license_url": ext(meta, "LicenseUrl"),
                "rights_evidence": {
                    "source": "Wikimedia Commons imageinfo extmetadata for this file",
                    "license_short_name": license_short,
                    "license_url": ext(meta, "LicenseUrl"),
                    "usage_terms": ext(meta, "UsageTerms"),
                    "copyrighted": ext(meta, "Copyrighted"),
                    "credit": ext(meta, "Credit"),
                    "attribution": ext(meta, "Attribution"),
                },
                "content_filter_evidence": content_reason,
                "qualitative_only_no_ground_truth": True,
            }
        )
        total_bytes += size
        time.sleep(1.25)
    return samples, quarantined[:80]


def inspect_smartdoc_schema() -> dict[str, Any]:
    meta: dict[str, Any] = {
        "status": "schema_reviewed_not_acquired_here",
        "source_url": SMARTDOC_PRIMARY_PAGE,
        "record_url": SMARTDOC_RECORD_URL,
        "download_url": SMARTDOC_SAMPLE_URL,
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "rights_evidence": "Primary SmartDoc dataset page and Zenodo record state Creative Commons Attribution 4.0 International License.",
        "authors": SMARTDOC_AUTHORS,
        "handoff": "Root owns SmartDoc frame extraction under output/detection-sources/pages/; this script does not duplicate or overwrite it.",
    }
    with tempfile.TemporaryDirectory() as td:
        cache = Path("/tmp/hwfm-smartdoc/sampleDataset.tar.gz")
        archive = Path(td) / "sampleDataset.tar.gz"
        if cache.exists() and md5_file(cache) == SMARTDOC_EXPECTED_MD5:
            shutil.copyfile(cache, archive)
            size, archive_sha = archive.stat().st_size, sha256_file(archive)
        else:
            try:
                size, archive_sha = download(SMARTDOC_SAMPLE_URL, archive, max_bytes=30 * 1024 * 1024)
            except Exception as exc:
                meta["error"] = str(exc)
                return meta
        archive_md5 = md5_file(archive)
        meta.update({"archive_bytes": size, "archive_sha256": archive_sha, "archive_md5": archive_md5})
        if archive_md5 != SMARTDOC_EXPECTED_MD5:
            meta["error"] = "MD5 mismatch against Zenodo-published checksum"
            return meta
        with tarfile.open(archive, "r:gz") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
            ext_counts = Counter(Path(n).suffix.lower() or "<noext>" for n in names)
            video_files = [n for n in names if Path(n).suffix.lower() in VIDEO_EXTENSIONS]
            gt_files = [n for n in names if n.endswith(".gt.xml")]
            spec_files = [n for n in names if "specification" in n.lower() or n.endswith("README")]
            meta["archive_schema"] = {
                "file_count": len(names),
                "extension_counts": dict(sorted(ext_counts.items())),
                "video_files": video_files,
                "ground_truth_xml_files": gt_files,
                "spec_or_readme_files": spec_files,
                "observed_structure": "sampleDataset/input_sample/background00/*.avi plus sampleDataset/input_sample_groundtruth/background00_gt/*.gt.xml; no still image files in the archive.",
                "ground_truth_shape": "XML segmentation_results/frame records with bl/tl/tr/br corner points per video frame.",
                "split_warning": "Only three sample videos under one background00 condition; frames extracted from the same video/background are correlated and must not be treated as independent photos.",
            }
    return meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commons-target", type=int, default=COMMONS_TARGET)
    parser.add_argument("--skip-smartdoc-schema", action="store_true")
    parser.add_argument("--discover", action="store_true", help="Also run broad Commons searches beyond curated seed titles.")
    parser.add_argument("--seed-only", action="store_true", help="Deprecated alias for default curated-only mode; retained for compatibility.")
    parser.add_argument("--clean", action="store_true", help="Remove existing handwriting output directory before downloading.")
    args = parser.parse_args()

    if args.clean and OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    seed_only = not args.discover or args.seed_only
    commons, quarantined = collect_commons(target=args.commons_target, seed_only=seed_only)
    smartdoc_schema = None if args.skip_smartdoc_schema else inspect_smartdoc_schema()
    manifest = {
        "version": 2,
        "created_at": now_iso(),
        "purpose": "Real internet handwriting images for qualitative handwriting/document panels; no synthetic images and no invented ground truth.",
        "byte_cap": MAX_TOTAL_BYTES,
        "total_bytes": sum(s["bytes"] for s in commons),
        "sample_count": len(commons),
        "acquisition_mode": "curated_seed_titles_only_no_broad_search" if seed_only else "curated_seed_titles_plus_commons_search",
        "sources_used": [
            {
                "name": "Wikimedia Commons file/search API",
                "api": "https://commons.wikimedia.org/w/api.php",
                "rights_basis": "Per-file imageinfo extmetadata LicenseShortName/LicenseUrl/Artist/Attribution stored in each sample record; this run accepted only Public domain or CC0.",
                "used_count": len(commons),
                "content_basis": "Strict title/category/metadata filter for page-like handwriting, letters, correspondence, or manuscript pages; known photos/generic/relicense-ambiguous files are quarantined.",
            }
        ],
        "reviewed_but_not_acquired_here": [smartdoc_schema] if smartdoc_schema else [],
        "quarantined_candidates": quarantined,
        "restricted_or_not_used_sources": [
            {
                "name": "IAM Handwriting Database",
                "status": "not used",
                "reason": "Access/license is registration/research-use oriented rather than clear open redistribution/reuse for this repo.",
            },
            {
                "name": "DIBCO/H-DIBCO binarization contest datasets",
                "status": "not used",
                "reason": "Useful annotated binarization benchmarks, but this pass did not find primary explicit reusable licensing for direct acquisition/redistribution.",
            },
            {
                "name": "SmartDoc-QA",
                "status": "not used",
                "source_url": "https://zenodo.org/records/5293201",
                "reason": "Primary Zenodo record is 13.7 GB, exceeding the bounded <=100 MB acquisition target.",
            },
            {
                "name": "MIDV-500 / identity document video datasets",
                "status": "not used",
                "reason": "Identity-document/template rights and download scope need separate review; not necessary for this bounded handwriting source set.",
            },
            {
                "name": "Library of Congress manuscript API",
                "status": "not used in automated acquisition",
                "source_url": "https://www.loc.gov/apis/",
                "reason": "Rights guidance is promising for public-domain/no-known-restrictions items, but loc.gov JSON requests returned HTTP 403 from this environment during this run.",
            },
        ],
        "samples": commons,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)}")
    print(f"samples={len(commons)} bytes={manifest['total_bytes']} quarantined={len(quarantined)}")
    return 0 if commons else 2


if __name__ == "__main__":
    raise SystemExit(main())
