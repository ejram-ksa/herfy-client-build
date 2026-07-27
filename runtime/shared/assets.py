from __future__ import annotations
from pathlib import Path
from runtime.shared.settings.config import bundled_or_source_path


def existing_asset_path(*parts: str) -> str:
    path = bundled_or_source_path(*parts)
    return str(path) if Path(path).exists() else ""
