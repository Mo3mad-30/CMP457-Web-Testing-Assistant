"""Shared test fixtures."""
import dataclasses

import pytest

from app import config, db, main, runner_client


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Settings pointing at a temporary data folder and database, with a headless, no-hold runner.

    Patched into every module that reads settings, so tests never touch the real data/ folder.
    """
    test_settings = dataclasses.replace(
        config.settings,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "app.db",
        headless=True,
        browser_hold_seconds=0,
        allowed_hosts=[],
        runner_timeout=30,
    )
    for module in (config, db, main, runner_client):
        monkeypatch.setattr(module, "settings", test_settings)
    db.init_db()
    return test_settings
