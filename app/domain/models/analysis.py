from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models.enums import Material, UtilityType


class Evidence(BaseModel):
    cue: Literal["color", "warning_tape_text", "shape", "marking_on_pipe", "context"]
    detail: str


class LineObservation(BaseModel):
    utility_type: UtilityType
    material: Material
    color: str | None
    approx_outer_diameter_mm: int | None
    approx_depth_of_cover_m: float | None
    is_house_connection: bool | None
    evidence: list[Evidence] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    has_stripes: bool | None = None
    is_paired: bool | None = None
    position: str | None = None


class FrameAnalysis(BaseModel):
    frame_id: str
    is_trench_visible: bool
    scale_reference_visible: bool
    warning_tapes: list[str]
    lines: list[LineObservation]
    image_quality_issues: list[str]
