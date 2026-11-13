"""Per-frame findings produced by the vision model."""

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models.enums import Material, UtilityType


class Evidence(BaseModel):
    cue: Literal["color", "warning_tape_text", "shape", "marking_on_pipe", "context"]
    detail: str


class LineObservation(BaseModel):
    """One line seen in one frame."""

    utility_type: UtilityType
    material: Material
    color: str | None
    approx_outer_diameter_mm: int | None  # null unless a scale reference is visible
    approx_depth_of_cover_m: float | None  # null unless a scale reference is visible
    is_house_connection: bool | None
    evidence: list[Evidence] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    # Observable attributes, compared against eval labels and used to match lines across frames
    has_stripes: bool | None = None
    is_paired: bool | None = None  # e.g. supply + return pipe of district heating
    position: str | None = None  # where in the frame, e.g. "left wall, bottom"


class FrameAnalysis(BaseModel):
    frame_id: str
    is_trench_visible: bool
    scale_reference_visible: bool
    warning_tapes: list[str]  # e.g. ["yellow: Achtung Gasleitung"]
    lines: list[LineObservation]
    image_quality_issues: list[str]  # blur, water, darkness, occlusion
