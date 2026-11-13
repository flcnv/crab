"""Pure domain logic: consolidation, measurement guards, verification rules."""

from app.domain.services.consolidation import (
    DEFAULT_LIMITATIONS,
    build_report,
    check_report_lines,
    merge_lines,
)
from app.domain.services.keyframes import FrameCandidate, hamming, select_keyframes
from app.domain.services.measurements import (
    count_unscaled_measurements,
    strip_unscaled_measurements,
)
from app.domain.services.metadata import merge_image_metadata
from app.domain.services.submission import Upload, classify_uploads, submit_job
from app.domain.services.verification import apply_verification_flags

__all__ = [
    "DEFAULT_LIMITATIONS",
    "FrameCandidate",
    "Upload",
    "apply_verification_flags",
    "build_report",
    "check_report_lines",
    "classify_uploads",
    "count_unscaled_measurements",
    "hamming",
    "merge_image_metadata",
    "merge_lines",
    "select_keyframes",
    "strip_unscaled_measurements",
    "submit_job",
]
