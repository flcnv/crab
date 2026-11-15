import pytest

from app.domain.models import VerificationConfig
from app.domain.services import verify_report
from eval.corruption import CORRUPTIONS, clean_scenario, run, to_markdown


def test_clean_scenario_raises_no_findings() -> None:
    s = clean_scenario()
    verified = verify_report(s.report, s.analyses, VerificationConfig(), media_kind=s.media_kind)
    assert [line.review for line in verified.lines] == [[]] * len(verified.lines)


@pytest.mark.parametrize("corruption", [c for c in CORRUPTIONS if c.expected], ids=lambda c: c.name)
def test_detectable_corruptions_are_caught_by_the_intended_rule(corruption: object) -> None:
    result = next(r for r in run().results if r.name == corruption.name)  # type: ignore[attr-defined]
    assert result.caught_as_expected, result
    assert result.false_alarms == 0


def test_blind_spots_stay_documented() -> None:
    # If a new rule starts catching one of these, move it out of the blind spots on purpose.
    blind = {r.name: r.caught for r in run().results if r.expected is None}
    assert blind == {"wrong_type_ambiguous_colour": False, "wrong_type_everywhere": False}


def test_markdown_summary() -> None:
    md = to_markdown(run())
    assert "caught by the intended rule: **8 / 8**" in md
    assert "(false alarms): **0**" in md
    assert "⚠️ not caught" in md
