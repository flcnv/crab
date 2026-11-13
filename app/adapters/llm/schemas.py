"""Wire schemas: what the model is asked to return. Converted to domain models after validation.

Field order is deliberate: observations (color, stripes, evidence) come before conclusions
(utility type, material, confidence), so the model commits to what it sees before it infers.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import Evidence, FrameAnalysis, LineObservation, Material, UtilityType


class LineFinding(BaseModel):
    position: str = Field(
        description="Where the line is in the image, e.g. 'bottom left, along the trench floor'."
    )
    color: str | None = Field(description="Visible jacket/conduit color, null if not discernible.")
    has_stripes: bool | None = Field(description="Colored stripes along the pipe; null if unclear.")
    is_paired: bool | None = Field(
        description="Runs as a parallel pair with an identical pipe (e.g. supply and return)."
    )
    evidence: list[Evidence] = Field(
        min_length=1, description="Visual cues that support the classification, at least one."
    )
    utility_type: UtilityType
    material: Material
    is_house_connection: bool | None = Field(
        description="Small branch leaving the main line toward a building; null if unclear."
    )
    approx_outer_diameter_mm: int | None = Field(
        description="Only with a visible scale reference; otherwise null."
    )
    approx_depth_of_cover_m: float | None = Field(
        description="Surface to top of pipe, only with a visible scale reference; otherwise null."
    )
    confidence: float = Field(ge=0, le=1, description="Probability that utility_type is correct.")


class FrameFindings(BaseModel):
    is_trench_visible: bool
    scale_reference_visible: bool = Field(
        description="A folding ruler, tape measure or other object of known size is visible."
    )
    scale_reference: str | None = Field(description="What the scale reference is, if any.")
    warning_tapes: list[str] = Field(
        description="Each tape as '<color>: <text as printed>', text 'unreadable' if not legible."
    )
    image_quality_issues: list[
        Literal["blur", "darkness", "glare", "water", "occlusion", "too_far", "other"]
    ]
    lines: list[LineFinding] = Field(description="One entry per distinct physical line.")

    def to_domain(self, frame_id: str) -> FrameAnalysis:
        return FrameAnalysis(
            frame_id=frame_id,
            is_trench_visible=self.is_trench_visible,
            scale_reference_visible=self.scale_reference_visible,
            warning_tapes=self.warning_tapes,
            image_quality_issues=list(self.image_quality_issues),
            lines=[LineObservation(**line.model_dump()) for line in self.lines],
        )


# --- consolidation agent tools -----------------------------------------------------------


class GetFrameFindingsInput(BaseModel):
    frame_ids: list[str] | None = Field(
        description="Frames to return in full detail; null returns all frames."
    )


class GetFrameImageInput(BaseModel):
    frame_id: str


class ReportLineDraft(BaseModel):
    utility_type: UtilityType
    material: Material
    approx_outer_diameter_mm: int | None = Field(
        description="Only if at least one of its frames has a scale reference; otherwise null."
    )
    approx_depth_of_cover_m: float | None = Field(
        description="Only if at least one of its frames has a scale reference; otherwise null."
    )
    seen_in_frames: list[str] = Field(min_length=1, description="Frame ids showing this line.")
    confidence: float = Field(ge=0, le=1, description="Probability that utility_type is correct.")
    notes: str | None = Field(
        description="Key evidence, and any merge or conflict worth knowing about."
    )


class SubmitReportInput(BaseModel):
    lines: list[ReportLineDraft] = Field(description="One entry per distinct physical line.")
    remarks: list[str] = Field(
        description="Caveats about the whole trench (coverage gaps, uncertain counts). May be empty."
    )
