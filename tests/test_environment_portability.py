#!/usr/bin/env python3
"""Portable runtime paths and environment preflight regression tests."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_environment  # noqa: E402
import runtime_paths  # noqa: E402


def test_runtime_data_override() -> None:
    with tempfile.TemporaryDirectory() as temp:
        previous = os.environ.get("ARTICLE_DISTILLER_DATA_DIR")
        os.environ["ARTICLE_DISTILLER_DATA_DIR"] = temp
        try:
            assert runtime_paths.user_data_file("source-registry.md") == Path(temp).resolve() / "source-registry.md"
        finally:
            if previous is None:
                os.environ.pop("ARTICLE_DISTILLER_DATA_DIR", None)
            else:
                os.environ["ARTICLE_DISTILLER_DATA_DIR"] = previous


def test_empty_ccswitch_database_does_not_pass() -> None:
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "cc-switch.db"
        connection = sqlite3.connect(database)
        try:
            connection.execute("create table providers (id text, app_type text, is_current integer, settings_config text)")
            connection.execute("create table provider_endpoints (app_type text, provider_id text, url text)")
            connection.commit()
        finally:
            connection.close()
        assert not check_environment._ccswitch_is_usable(database)


if __name__ == "__main__":
    test_runtime_data_override()
    test_empty_ccswitch_database_does_not_pass()
    print("environment portability tests passed")
