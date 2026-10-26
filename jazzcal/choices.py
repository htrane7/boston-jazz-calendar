"""Your always-include/always-exclude decisions, one file per venue in choices/."""

import tomllib
from pathlib import Path

CHOICES_DIR = Path(__file__).resolve().parents[1] / "choices"


def load_choices(path: Path) -> tuple[set[str], set[str]]:
    """Event pages you've said to always include or always leave out."""
    if not path.exists():
        return set(), set()
    data = tomllib.loads(path.read_text())

    def urls(key):
        return {url.strip().rstrip("/") for url in data.get(key, [])}

    return urls("include"), urls("exclude")
