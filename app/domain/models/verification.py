"""Settings of the deterministic verification rules (values come from Settings via bootstrap)."""

from pydantic import BaseModel, ConfigDict, Field


class VerificationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    # A line with confidence <= this is flagged. Inclusive, so lines identified by colour
    # alone (capped at 0.6 by the frame prompt) are flagged.
    min_confidence: float = Field(default=0.6, ge=0, le=1)
    # Relative spread (max - min) / median above which sizes across frames are inconsistent.
    size_tolerance: float = Field(default=0.15, ge=0)
