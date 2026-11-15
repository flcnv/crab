from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str, version: str) -> str:
    return (PROMPTS_DIR / f"{name}_{version}.md").read_text(encoding="utf-8")
