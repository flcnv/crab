from app.domain.models import TrenchReport


def apply_verification_flags(report: TrenchReport, flags: list[str]) -> TrenchReport:
    """Attach flags and lower confidence of flagged lines."""
    raise NotImplementedError
