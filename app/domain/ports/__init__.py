"""Ports: interfaces the domain needs. Adapters implement them."""

from app.domain.ports.llm import ReportAgent, Verifier, VisionModel
from app.domain.ports.media import FrameExtractor, MetadataReader
from app.domain.ports.queue import JobQueue
from app.domain.ports.repositories import JobRepository
from app.domain.ports.storage import Storage

__all__ = [
    "FrameExtractor",
    "JobQueue",
    "JobRepository",
    "MetadataReader",
    "ReportAgent",
    "Storage",
    "Verifier",
    "VisionModel",
]
