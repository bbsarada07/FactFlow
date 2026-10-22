"""Loads the Shield YAML configuration (shield/config/*.yml) once per process."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"


@lru_cache
def load(name: str) -> dict:
    """Parse shield/config/<name>.yml with yaml.safe_load."""
    with open(CONFIG_DIR / f"{name}.yml", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{name}.yml must contain a mapping")
    return data


# `[^.\n]` in a config pattern means "within one sentence". A dot that is not followed by
# whitespace (as in "x.com" or "3.5") does not end a sentence, so it is allowed inside the span.
_SENTENCE_CHAR = "[^.\\n]"
_SENTENCE_CHAR_EXPANDED = "(?:[^.\\n]|\\.(?=\\S))"


@lru_cache(maxsize=2048)
def compiled(pattern: str) -> re.Pattern[str]:
    """Compile a config regex once (all Shield patterns are matched against casefolded text)."""
    return re.compile(pattern.replace(_SENTENCE_CHAR, _SENTENCE_CHAR_EXPANDED), re.IGNORECASE | re.MULTILINE)
