"""Consolidated report: one entry per physical line."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models.enums import Material, UtilityType
from app.domain.models.geo import GeoPoint


class ReportLine(BaseModel):
    """One physical line after consolidation."""

    id: str
    utility_type: UtilityType
    material: Material
    approx_outer_diameter_mm: int | None
    approx_depth_of_cover_m: float | None
    seen_in_frames: list[str]
    confidence: float = Field(ge=0, le=1)
    notes: str | None


class TrenchReport(BaseModel):
    job_id: UUID
    lines: list[ReportLine]
    verification_flags: list[str]
    limitations: list[str]
    location: GeoPoint | None
