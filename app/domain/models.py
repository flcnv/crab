"""Core domain schemas. Pure Pydantic, no I/O."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UtilityType(StrEnum):
    GAS = "gas"
    WATER = "water"
    WASTEWATER = "wastewater"
    DISTRICT_HEATING = "district_heating"
    POWER = "power"
    TELECOM = "telecom"
    UNKNOWN = "unknown"


class Material(StrEnum):
    PE = "pe"
    PVC_PP = "pvc_pp"
    STEEL = "steel"
    CAST_IRON = "cast_iron"
    CONCRETE = "concrete"
    PRE_INSULATED = "pre_insulated"
    CABLE = "cable"
    UNKNOWN = "unknown"


class JobStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    CONSOLIDATING = "consolidating"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None


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


class FrameAnalysis(BaseModel):
    frame_id: str
    is_trench_visible: bool
    scale_reference_visible: bool
    warning_tapes: list[str]  # e.g. ["yellow: Achtung Gasleitung"]
    lines: list[LineObservation]
    image_quality_issues: list[str]  # blur, water, darkness, occlusion


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


class Frame(BaseModel):
    """A keyframe selected for analysis (reference to stored image, not bytes)."""

    frame_id: str
    storage_key: str
    timestamp_s: float | None = None
    sharpness: float | None = None


class MediaMetadata(BaseModel):
    kind: Literal["video", "image"]
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    location: GeoPoint | None = None
    captured_at: datetime | None = None


class LLMUsage(BaseModel):
    """Token usage and cost of one model call."""

    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
