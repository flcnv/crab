"""Pure domain logic: consolidation, measurement guards, verification rules."""

from app.domain.services.consolidation import DEFAULT_LIMITATIONS, merge_lines
from app.domain.services.measurements import strip_unscaled_measurements
from app.domain.services.submission import Upload, classify_uploads, submit_job
from app.domain.services.verification import apply_verification_flags

__all__ = [
    "DEFAULT_LIMITATIONS",
    "Upload",
    "apply_verification_flags",
    "classify_uploads",
    "merge_lines",
    "strip_unscaled_measurements",
    "submit_job",
]
