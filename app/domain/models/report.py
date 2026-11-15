from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models.enums import Material, ReviewReason, UtilityType
from app.domain.models.geo import GeoPoint

type ConsolidationMethod = Literal["agent", "rules"]


class ReviewFinding(BaseModel):
    reason: ReviewReason
    detail: str


class ObservationRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    frame_id: str
    line_index: int = Field(ge=0)

    def __str__(self) -> str:
        return f"{self.frame_id}#{self.line_index}"


class ReportLine(BaseModel):
    id: str
    utility_type: UtilityType
    material: Material
    approx_outer_diameter_mm: int | None
    approx_depth_of_cover_m: float | None
    observations: list[ObservationRef] = Field(default_factory=list)
    seen_in_frames: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str | None
    needs_review: bool = False
    review: list[ReviewFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _review_flag_matches_findings(self) -> Self:
        if self.needs_review != bool(self.review):
            raise ValueError("needs_review must be true exactly when review has findings")
        return self

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
    lines: list[ReportLine]
    remarks: list[str] = Field(default_factory=list)
    method: ConsolidationMethod


class TrenchReport(BaseModel):
    job_id: UUID
    lines: list[ReportLine]
    verification_flags: list[str]
    limitations: list[str]
    location: GeoPoint | None
    consolidation_method: ConsolidationMethod | None = None
