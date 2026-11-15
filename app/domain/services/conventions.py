"""Colour conventions: which utility types a pipe or conduit colour usually indicates.

source = "heuristic": the table follows the colour cues in the frame prompt and is NOT yet
confirmed against SIA 405 or operator conventions (decision D3). Conventions differ by country
and operator, so a mismatch only produces a review reason, never an error.

Matching: the free-text colour is lower-cased and split into words (EN + DE). Compound
colours ("orange-brown", "orangebraun") are matched before single words. If several colours
are named ("yellow with black stripes", "red/green"), the expectations of all recognised
colours are combined (union), so a contradiction is only reported when no named colour fits.
Ambiguous colours (black, grey, white) give no expectation.
"""

import re

from app.domain.models import UtilityType

COLOR_CONVENTIONS_SOURCE = "heuristic"

_GAS = frozenset({UtilityType.GAS})
_WATER = frozenset({UtilityType.WATER})
_WASTEWATER = frozenset({UtilityType.WASTEWATER})
_CABLE = frozenset({UtilityType.POWER, UtilityType.TELECOM})
_TELECOM = frozenset({UtilityType.TELECOM})

# Checked first, on the normalised text (words joined by single spaces).
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
    """Utility types the colour usually indicates; None when it says nothing (unknown,
    ambiguous or unrecognised colour)."""
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
