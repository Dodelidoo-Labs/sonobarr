"""Coverage-oriented tests for app-factory helper branches."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

import sonobarr_app as app_module
from sonobarr_app.extensions import db, login_manager


def test_configure_logging_with_empty_root_and_gunicorn_handlers(app):
    """Logging setup should add a root handler and inherit gunicorn handlers when present."""

    root_logger = logging.getLogger()
    gunicorn_logger = logging.getLogger("gunicorn.error")

    original_root_handlers = list(root_logger.handlers)
    original_gunicorn_handlers = list(gunicorn_logger.handlers)
    original_app_handlers = list(app.logger.handlers)

    try:
        root_logger.handlers = []
        gunicorn_logger.handlers = [logging.StreamHandler()]
        app.logger.handlers = []
        app.config["LOG_LEVEL"] = "DEBUG"

        app_module._configure_logging(app)

        assert root_logger.handlers
        assert app.logger.handlers == gunicorn_logger.handlers
    finally:
        root_logger.handlers = original_root_handlers
        gunicorn_logger.handlers = original_gunicorn_handlers
        app.logger.handlers = original_app_handlers


def test_register_user_loader_handles_invalid_ids_and_db_schema_failures(app):
    """User loader should guard empty/invalid IDs and rollback when user table is unavailable."""

    app_module._register_user_loader()
    callback = login_manager._user_callback

    with app.app_context():
        assert callback("") is None
        assert callback("not-an-int") is None

        db.drop_all()
        assert callback("1") is None
        db.create_all()


def test_calculate_update_status_returns_muted_when_latest_missing():
    """Update status helper should report unknown state when no latest release is available."""

    assert app_module._calculate_update_status("v1.0.0", None) == (None, "muted")


def test_ensure_user_profile_columns_covers_inspection_and_backfill_failures(app, monkeypatch):
    """Profile-column backfill should rollback on inspect errors and continue after per-column failures."""

    logger = logging.getLogger("test-profile-backfill")
    monkeypatch.delenv("SONOBARR_SKIP_PROFILE_BACKFILL", raising=False)

    with app.app_context():
        rollbacks = []
        monkeypatch.setattr(app_module.db.session, "rollback", lambda: rollbacks.append("rollback"))
        monkeypatch.setattr(
            app_module,
            "inspect",
            lambda _engine: (_ for _ in ()).throw(OperationalError("inspect", {}, Exception("boom"))),
        )
        app_module._ensure_user_profile_columns(logger)
        assert rollbacks

    with app.app_context():
        executed = []
        commits = []
        rollbacks = []

        monkeypatch.setattr(
            app_module,
            "inspect",
            lambda _engine: SimpleNamespace(get_columns=lambda _table: [{"name": "id"}]),
        )

        def _execute(statement):
            sql_text = str(statement)
            executed.append(sql_text)
            if "listenbrainz_username" in sql_text:
                raise OperationalError("alter", {}, Exception("column failed"))

        monkeypatch.setattr(app_module.db.session, "execute", _execute)
        monkeypatch.setattr(app_module.db.session, "commit", lambda: commits.append("commit"))
        monkeypatch.setattr(app_module.db.session, "rollback", lambda: rollbacks.append("rollback"))

        app_module._ensure_user_profile_columns(logger)

        assert any("lastfm_username" in sql for sql in executed)
        assert any("listenbrainz_username" in sql for sql in executed)
        assert commits
        assert rollbacks
