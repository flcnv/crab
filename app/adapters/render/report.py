"""Render a TrenchReport (the JSON source of truth) as Markdown or GeoJSON, on request."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.domain.models import Job, Material, TrenchReport, UtilityType

UTILITY_LABELS: frozendict[UtilityType, str] = frozendict(
    {
        UtilityType.GAS: "Gas",
        UtilityType.WATER: "Drinking water",
        UtilityType.WASTEWATER: "Wastewater",
        UtilityType.DISTRICT_HEATING: "District heating",
        UtilityType.POWER: "Power",
        UtilityType.TELECOM: "Telecom",
        UtilityType.UNKNOWN: "Unknown",
    }
)

MATERIAL_LABELS: frozendict[Material, str] = frozendict(
    {
        Material.PE: "PE",
        Material.PVC_PP: "PVC/PP",
        Material.STEEL: "Steel",
        Material.CAST_IRON: "Cast iron",
        Material.CONCRETE: "Concrete",
        Material.PRE_INSULATED: "Pre-insulated",
        Material.CABLE: "Cable",
        Material.UNKNOWN: "Unknown",
    }
)


def _cell(value: object) -> str:
    """Make a value safe inside a Markdown table cell."""
    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ").strip() or "-"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # Markdown, not HTML  # noqa: S701
    )
    env.filters["cell"] = _cell
    env.filters["utility"] = lambda u: UTILITY_LABELS[u]
    env.filters["material"] = lambda m: MATERIAL_LABELS[m]
    env.filters["percent"] = lambda x: f"{round(x * 100)} %"
    return env


_ENV = _env()


def render_markdown(report: TrenchReport, job: Job) -> str:
    return _ENV.get_template("report.md.j2").render(report=report, job=job)


def render_geojson(report: TrenchReport) -> dict[str, Any] | None:
    """One Point feature at the capture location, lines as properties. None without GPS.

    A single point is all a phone capture gives us; line geometry would need a survey.
    """
    if report.location is None:
        return None
    loc = report.location
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [loc.lon, loc.lat]},  # lon, lat
                "properties": {
                    "job_id": str(report.job_id),
                    "location_accuracy_m": loc.accuracy_m,
                    "lines": [
                        {
                            "id": line.id,
                            "utility_type": line.utility_type.value,
                            "material": line.material.value,
                            "approx_outer_diameter_mm": line.approx_outer_diameter_mm,
                            "approx_depth_of_cover_m": line.approx_depth_of_cover_m,
                            "confidence": line.confidence,
                        }
                        for line in report.lines
                    ],
                },
            }
        ],
    }
