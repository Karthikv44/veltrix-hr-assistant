"""Dynamic prompt loader for Veltrix PeopleOps Assistant.

Loads prompt templates and messages from disk so prompt engineering
can be performed without altering Python source code.
"""

from functools import lru_cache
from pathlib import Path

_PACKAGE_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load_prompt(name: str, default: str = "") -> str:
    """Load prompt content from a file in the prompts directory.

    Checks:
    1. ./prompts/{name}.txt (root project directory)
    2. src/veltrix/llm/prompts/{name}.txt (package prompts directory)
    3. default fallback string
    """
    root_prompt = Path("prompts") / f"{name}.txt"
    if root_prompt.exists():
        return root_prompt.read_text(encoding="utf-8").strip()

    pkg_prompt = _PACKAGE_PROMPTS_DIR / f"{name}.txt"
    if pkg_prompt.exists():
        return pkg_prompt.read_text(encoding="utf-8").strip()

    return default.strip()
