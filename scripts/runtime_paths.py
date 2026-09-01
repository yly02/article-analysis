"""Portable user-data paths shared by article-distiller runtime modules."""

from __future__ import annotations

import os
from pathlib import Path


def user_data_dir() -> Path:
    override = str(os.environ.get("ARTICLE_DISTILLER_DATA_DIR") or "").strip()
    return Path(override).expanduser().resolve() if override else Path.home() / ".article-distiller"


def user_data_file(name: str) -> Path:
    return user_data_dir() / name
