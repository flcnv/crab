"""Domain schemas. Pure Pydantic, no I/O. Import from here: `from app.domain.models import Job`."""

from app.domain.models.analysis import Evidence, FrameAnalysis, LineObservation
from app.domain.models.enums import JobStatus, Material, UtilityType
from app.domain.models.geo import GeoPoint
from app.domain.models.job import Job
from app.domain.models.media import Frame, MediaKind, MediaMetadata
from app.domain.models.report import ReportLine, TrenchReport
from app.domain.models.usage import LLMUsage

__all__ = [
    "Evidence",
    "Frame",
    "FrameAnalysis",
    "GeoPoint",
    "Job",
    "JobStatus",
    "LLMUsage",
    "LineObservation",
    "Material",
    "MediaKind",
    "MediaMetadata",
    "ReportLine",
    "TrenchReport",
    "UtilityType",
]
