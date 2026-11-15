import re

from app.domain.models import UtilityType

COLOR_CONVENTIONS_SOURCE = "heuristic"

_GAS = frozenset({UtilityType.GAS})
_WATER = frozenset({UtilityType.WATER})
_WASTEWATER = frozenset({UtilityType.WASTEWATER})
_CABLE = frozenset({UtilityType.POWER, UtilityType.TELECOM})
_TELECOM = frozenset({UtilityType.TELECOM})

_COMPOUNDS: tuple[tuple[str, frozenset[UtilityType]], ...] = (
    ("orange brown", _WASTEWATER),
    ("orangebraun", _WASTEWATER),
    ("orange braun", _WASTEWATER),
)

_WORDS: frozendict[str, frozenset[UtilityType]] = frozendict(
    {
        "yellow": _GAS,
        "gelb": _GAS,
        "blue": _WATER,
        "blau": _WATER,
        "brown": _WASTEWATER,
        "braun": _WASTEWATER,
        "red": _CABLE,
        "rot": _CABLE,
        "orange": _CABLE,
        "green": _TELECOM,
        "grün": _TELECOM,
        "gruen": _TELECOM,
    }
)

_WORD = re.compile(r"[a-zäöü]+")


def expected_types(color: str | None) -> frozenset[UtilityType] | None:
    if not color:
        return None
    text = " ".join(_WORD.findall(color.lower()))
    expected: set[UtilityType] = set()
    for compound, types in _COMPOUNDS:
        if compound in text:
            expected |= types
            text = text.replace(compound, " ")
    for word in text.split():
        expected |= _WORDS.get(word, frozenset())
    return frozenset(expected) or None
