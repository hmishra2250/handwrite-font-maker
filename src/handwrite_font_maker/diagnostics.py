from __future__ import annotations

from dataclasses import dataclass, field


class TemplateProcessingError(RuntimeError):
    """Base class for structural template/font build failures."""


class MarkerDetectionError(TemplateProcessingError):
    def __init__(self, missing_roles: list[str]):
        self.missing_roles = missing_roles
        super().__init__(
            "Missing required ArUco marker(s): "
            + ", ".join(missing_roles)
            + ". Please re-shoot the template with all four corners visible."
        )


class MetadataDecodeError(TemplateProcessingError):
    pass


class HomographyQualityError(TemplateProcessingError):
    def __init__(self, error_px: float, threshold_px: float):
        self.error_px = error_px
        self.threshold_px = threshold_px
        super().__init__(
            f"Homography reprojection error {error_px:.2f}px exceeds {threshold_px:.2f}px. "
            "Please re-shoot the template flatter and fully visible."
        )


class CellExtractionError(TemplateProcessingError):
    pass


class FontValidationError(TemplateProcessingError):
    pass


@dataclass
class GlyphWarning:
    char: str
    code: str
    message: str
    coverage: float


@dataclass
class BuildDiagnostics:
    warnings: list[GlyphWarning] = field(default_factory=list)

    def add(self, warning: GlyphWarning) -> None:
        self.warnings.append(warning)

    def as_dicts(self) -> list[dict[str, object]]:
        return [warning.__dict__.copy() for warning in self.warnings]
