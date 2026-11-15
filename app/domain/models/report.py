"""Consolidated report: one entry per physical line."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models.enums import Material, UtilityType
from app.domain.models.geo import GeoPoint


class ObservationRef(BaseModel):
    """Points to one per-frame observation: `FrameAnalysis.lines[line_index]` of `frame_id`."""

    model_config = ConfigDict(frozen=True)  # hashable: used as a key when checking claims

    frame_id: str
    line_index: int = Field(ge=0)

    def __str__(self) -> str:
        return f"{self.frame_id}#{self.line_index}"


class ReportLine(BaseModel):
    """One physical line after consolidation.

    `observations` says which per-frame observations were merged into this line.
    `seen_in_frames` is derived from them; it is only given on its own by reports stored
    before observation refs existed (their `observations` is empty).
    """

    id: str
    utility_type: UtilityType
    material: Material
    approx_outer_diameter_mm: int | None
    approx_depth_of_cover_m: float | None
    observations: list[ObservationRef] = Field(default_factory=list)
    seen_in_frames: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str | None

    @model_validator(mode="after")
    def _derive_seen_in_frames(self) -> Self:
        if not self.observations:
            return self
        derived = sorted({ref.frame_id for ref in self.observations})
        if self.seen_in_frames and self.seen_in_frames != derived:
            raise ValueError(
                f"seen_in_frames {self.seen_in_frames} does not match observations {derived}"
            )
        self.seen_in_frames = derived
        return self


class Consolidation(BaseModel):
    """Output of the consolidation step, before it becomes a report."""

    lines: list[ReportLine]
    remarks: list[str] = Field(default_factory=list)  # e.g. "frames 4-6 blurry, count uncertain"
    method: str  # "agent" or "rules"


class TrenchReport(BaseModel):
    job_id: UUID
    lines: list[ReportLine]
    verification_flags: list[str]
    limitations: list[str]
    location: GeoPoint | None
