from pydantic import BaseModel, Field

from app.domain.models import Material, ObservationRef, UtilityType


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
    observations: list[ObservationRef] = Field(
        min_length=1,
        description="The per-frame observations merged into this line, as frame_id + "
        "line_index (the [index] shown for each line in the overview and findings). "
        "Each observation belongs to at most one line.",
    )
    confidence: float = Field(ge=0, le=1, description="Probability that utility_type is correct.")
    notes: str | None = Field(
        description="Key evidence, and any merge or conflict worth knowing about."
    )


class SubmitReportInput(BaseModel):
    lines: list[ReportLineDraft] = Field(description="One entry per distinct physical line.")
    remarks: list[str] = Field(
        description="Caveats about the whole trench (coverage gaps, uncertain counts). May be empty."
    )
