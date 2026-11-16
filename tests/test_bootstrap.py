import uuid

import pytest

from app.adapters.llm.claude import ClaudeVisionModel
from app.adapters.storage.local import LocalStorage
from app.bootstrap import LLMNotWired, build_deps
from app.domain.models import VerificationConfig
from app.settings import Settings


def test_build_deps_uses_settings() -> None:
    deps = build_deps(Settings(claude_model="claude-haiku-5-5"))
    assert isinstance(deps.storage, LocalStorage)
    assert isinstance(deps.vision_model, ClaudeVisionModel)
    assert deps.vision_model.model == "claude-haiku-5-5"


def test_build_deps_passes_verification_settings() -> None:
    deps = build_deps(Settings(verify_min_confidence=0.5, verify_size_tolerance=0.2))
    assert deps.verification == VerificationConfig(min_confidence=0.5, size_tolerance=0.2)


async def test_build_deps_without_llm_wires_no_model_client() -> None:
    deps = build_deps(Settings(), with_llm=False)
    assert deps.anthropic is None
    assert isinstance(deps.vision_model, LLMNotWired)
    with pytest.raises(RuntimeError, match="only wired in the worker"):
        await deps.vision_model.analyze(b"jpeg", "f001")
    with pytest.raises(RuntimeError, match="only wired in the worker"):
        await deps.report_agent.consolidate(uuid.uuid4(), [], lambda _: _never())
    await deps.aclose()


async def _never() -> bytes:
    raise AssertionError
