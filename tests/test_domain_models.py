import pytest
from pydantic import ValidationError

from app.domain.models import LineObservation, Material, UtilityType


def test_line_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        LineObservation(
            utility_type=UtilityType.GAS,
            material=Material.PE,
            color="yellow",
            approx_outer_diameter_mm=None,
            approx_depth_of_cover_m=None,
            is_house_connection=None,
            evidence=[],
            confidence=0.5,
        )
