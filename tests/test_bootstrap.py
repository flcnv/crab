from app.adapters.llm.claude import ClaudeVisionModel
from app.adapters.storage.local import LocalStorage
from app.bootstrap import build_deps
from app.settings import Settings


def test_build_deps_uses_settings() -> None:
    deps = build_deps(Settings(claude_model="claude-haiku-5-5"))
    assert isinstance(deps.storage, LocalStorage)
    assert isinstance(deps.vision_model, ClaudeVisionModel)
    assert deps.vision_model.model == "claude-haiku-5-5"
