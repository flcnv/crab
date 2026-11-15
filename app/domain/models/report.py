"""Consolidated report: one entry per physical line."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models.enums import Material, ReviewReason, UtilityType
from app.domain.models.geo import GeoPoint

type ConsolidationMethod = Literal["agent", "rules"]


class ReviewFinding(BaseModel):
    """One verification rule that fired for a line, with the facts behind it."""

    reason: ReviewReason
    detail: str


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

    `needs_review` and `review` are written only by verification and recomputed on every run;
    `needs_review` is true exactly when `review` is not empty.
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
    """Output of the consolidation step, before it becomes a report."""

    lines: list[ReportLine]
    remarks: list[str] = Field(default_factory=list)  # e.g. "frames 4-6 blurry, count uncertain"
    method: ConsolidationMethod


class TrenchReport(BaseModel):
    job_id: UUID
    lines: list[ReportLine]
    verification_flags: list[str]  # report level only, e.g. "2 of 5 lines need review"
    limitations: list[str]
    location: GeoPoint | None
    consolidation_method: ConsolidationMethod | None = None  # None: stored before it existed
