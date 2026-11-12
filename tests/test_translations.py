"""Tests that every translation says the same things as the English one."""

import json
from pathlib import Path
import re

import pytest

TRANSLATIONS = Path("custom_components/ble_christmas_lights/translations")
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json"))


def texts(language: str) -> dict[str, str]:
    """Return every text of a translation by its dotted key."""

    def walk(node: dict, prefix: str = ""):
        for key, value in node.items():
            if isinstance(value, dict):
                yield from walk(value, f"{prefix}{key}.")
            else:
                yield f"{prefix}{key}", value

    return dict(walk(json.loads((TRANSLATIONS / f"{language}.json").read_text())))


def test_languages():
    assert LANGUAGES == ["de", "en", "fr", "nl"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_matches_english(language):
    english = texts("en")
    translation = texts(language)
    assert set(translation) == set(english)
    for key, text in english.items():
        # The same placeholders, or Home Assistant cannot fill the text in.
        assert sorted(re.findall(r"\{\w+\}", translation[key])) == sorted(
            re.findall(r"\{\w+\}", text)
        ), key
