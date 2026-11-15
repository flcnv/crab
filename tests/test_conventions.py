import pytest

from app.domain.models import UtilityType as U
from app.domain.services import COLOR_CONVENTIONS_SOURCE, expected_types


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ("yellow", {U.GAS}),
        ("Gelb", {U.GAS}),
        ("blue", {U.WATER}),
        ("blau", {U.WATER}),
        ("brown", {U.WASTEWATER}),
        ("orange-brown", {U.WASTEWATER}),
        ("Orangebraun", {U.WASTEWATER}),
        ("red", {U.POWER, U.TELECOM}),
        ("orange", {U.POWER, U.TELECOM}),
        ("green", {U.TELECOM}),
        ("grün", {U.TELECOM}),
        ("black with yellow stripes", {U.GAS}),
        ("red/green", {U.POWER, U.TELECOM}),
    ],
)
def test_known_colours(color: str, expected: set[U]) -> None:
    assert expected_types(color) == frozenset(expected)


@pytest.mark.parametrize("color", [None, "", "black", "schwarz", "grey", "grau", "white", "?"])
def test_ambiguous_or_missing_colour_gives_no_expectation(color: str | None) -> None:
    assert expected_types(color) is None


def test_table_is_marked_as_heuristic() -> None:
    assert COLOR_CONVENTIONS_SOURCE == "heuristic"
