"""Pure domain logic: consolidation, measurement guards, verification rules."""

from app.domain.services.consolidation import DEFAULT_LIMITATIONS, merge_lines
from app.domain.services.measurements import strip_unscaled_measurements
from app.domain.services.verification import apply_verification_flags

__all__ = [
    "DEFAULT_LIMITATIONS",
    "apply_verification_flags",
    "merge_lines",
    "strip_unscaled_measurements",
]
