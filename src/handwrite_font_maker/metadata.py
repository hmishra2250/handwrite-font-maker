from __future__ import annotations

import json

from .diagnostics import MetadataDecodeError
from .schema import DEFAULT_DPI, TEMPLATE_KIND, TEMPLATE_VERSION, TemplateLayout, TemplateMetadata


def metadata_for_layout(layout: TemplateLayout, *, dpi: int = DEFAULT_DPI) -> TemplateMetadata:
    return TemplateMetadata(
        kind=TEMPLATE_KIND,
        version=TEMPLATE_VERSION,
        layout_id=layout.layout_id,
        chars=layout.chars,
        paper_size=layout.paper_size,
        marker_dictionary=layout.marker_dictionary,
        marker_ids=dict(layout.marker_roles),
        dpi=dpi,
    )


def encode_metadata(metadata: TemplateMetadata) -> str:
    payload = {
        "k": metadata.kind,
        "v": metadata.version,
        "l": metadata.layout_id,
        "c": "".join(metadata.chars),
        "p": metadata.paper_size,
        "d": metadata.marker_dictionary,
        "m": metadata.marker_ids,
        "dpi": metadata.dpi,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_metadata(payload: str) -> TemplateMetadata:
    if not payload:
        raise MetadataDecodeError("Template QR metadata could not be decoded; the template is not recognized.")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MetadataDecodeError("Template QR metadata is invalid; the template is not recognized.") from exc

    kind = data.get("kind", data.get("k"))
    version = data.get("version", data.get("v"))
    if kind != TEMPLATE_KIND or version != TEMPLATE_VERSION:
        raise MetadataDecodeError("Template metadata kind/version is not recognized.")
    chars = tuple(data.get("chars", data.get("c", "")))
    if not chars:
        raise MetadataDecodeError("Template metadata has no character map.")
    marker_ids = data.get("marker_ids", data.get("m"))
    if not isinstance(marker_ids, dict):
        raise MetadataDecodeError("Template metadata has no marker map.")
    return TemplateMetadata(
        kind=str(kind),
        version=int(version),
        layout_id=str(data.get("layout_id", data.get("l"))),
        chars=chars,
        paper_size=str(data.get("paper_size", data.get("p", "A4"))).upper(),
        marker_dictionary=str(data.get("marker_dictionary", data.get("d", "DICT_4X4_50"))),
        marker_ids={str(key): int(value) for key, value in marker_ids.items()},
        dpi=int(data.get("dpi", DEFAULT_DPI)),
    )
