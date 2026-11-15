from pydantic import BaseModel, ConfigDict, Field


class VerificationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_confidence: float = Field(default=0.6, ge=0, le=1)
    size_tolerance: float = Field(default=0.15, ge=0)
