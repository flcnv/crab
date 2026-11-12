"""Render TrenchReport -> Markdown / HTML (Jinja2) and GeoJSON."""

from typing import Any

from app.domain.models import TrenchReport


def render_markdown(report: TrenchReport) -> str:
    raise NotImplementedError


def render_geojson(report: TrenchReport) -> dict[str, Any] | None:
    raise NotImplementedError
