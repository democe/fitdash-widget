"""Backend translations from the shared plugin catalogs and desktop message locale."""

import json
import os
from pathlib import Path


def translation_catalog():
    # Wheels bundle the same catalogs; editable installs read the plugin sources.
    directory = Path(__file__).parent / "translations"
    if not directory.is_dir():
        directory = Path(__file__).resolve().parents[2] / "translations"
    english = json.loads((directory / "en.json").read_text(encoding="utf-8"))
    locale_name = next(
        (os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(key)), "C"
    )
    candidates = [locale_name]
    if locale_name not in ("C", "POSIX", "C.UTF-8", "C.utf8"):
        candidates = os.environ.get("LANGUAGE", "").split(":") + candidates
    for candidate in candidates:
        language = candidate.split(".")[0].split("@")[0].replace("-", "_").split("_")[0].lower()
        # Never interpret environment values as paths.
        if not language.isalpha():
            continue
        path = directory / (language + ".json")
        if path.is_file():
            return language, english | json.loads(path.read_text(encoding="utf-8"))
    return "en", english
