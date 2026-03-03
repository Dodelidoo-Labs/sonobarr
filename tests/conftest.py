"""Shared pytest fixtures for Sonobarr unit and integration tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("secret_key", "test-secret-key")
os.environ.setdefault("SONOBARR_SKIP_PROFILE_BACKFILL", "1")


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """Create a reusable Flask app configured for isolated test execution."""

    from sonobarr_app import create_app
    from sonobarr_app.config import Config

    runtime_dir = tmp_path_factory.mktemp("runtime")
    config_dir = runtime_dir / "config"
    settings_file = config_dir / "settings_config.json"
    db_file = runtime_dir / "test.db"

    class TestConfig(Config):
        """Static test config with isolated database and settings paths."""

        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        CONFIG_DIR = str(config_dir)
        SETTINGS_FILE = str(settings_file)
        OIDC_CLIENT_ID = "test-client"
        OIDC_CLIENT_SECRET = "test-secret"
        OIDC_SERVER_METADATA_URL = "https://example.com/.well-known/openid-configuration"

    flask_app = create_app(TestConfig)
    release_client = flask_app.extensions.get("release_client")
    if release_client is not None:
        release_client.fetch_latest = lambda force=False: {
            "tag_name": "v1.0.0",
            "html_url": "https://example.com/releases/v1.0.0",
            "error": None,
            "fetched_at": 0.0,
        }
    return flask_app


@pytest.fixture(autouse=True)
def reset_database(app):
    """Provide each test with a clean schema and empty data set."""

    from sonobarr_app.extensions import db

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture
def client(app):
    """Return a Flask test client for HTTP endpoint tests."""

    return app.test_client()
