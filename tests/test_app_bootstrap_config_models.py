"""Tests for application helpers, bootstrap logic, config utils, and model behavior."""

from __future__ import annotations

import logging
import os

import pytest

from sonobarr_app import _calculate_update_status, _get_update_status_label
from sonobarr_app.bootstrap import DEFAULT_BOOTSTRAP_SUPERADMIN_PASSWORD, bootstrap_super_admin
from sonobarr_app.config import _get_bool, _get_int, get_env_value
from sonobarr_app.extensions import db
from sonobarr_app.models import User


class _StubHandler:
    """Simple object exposing bootstrap-related attributes."""

    def __init__(self, username="admin", password="password123", display_name="Admin", reset=False):
        self.superadmin_username = username
        self.superadmin_password = password
        self.superadmin_display_name = display_name
        self.superadmin_reset_flag = reset


def test_config_helpers(monkeypatch):
    """Environment helper functions should prefer populated values and parse bool/int safely."""

    monkeypatch.setenv("example", "")
    monkeypatch.setenv("EXAMPLE", "upper")
    assert get_env_value("example", "default") == "upper"
    assert get_env_value("missing", "default") == "default"

    monkeypatch.setenv("BOOL_A", "true")
    monkeypatch.setenv("INT_A", "42")
    monkeypatch.setenv("INT_B", "bad")

    assert _get_bool("BOOL_A", False) is True
    assert _get_bool("BOOL_MISSING", True) is True
    assert _get_int("INT_A", 1) == 42
    assert _get_int("INT_B", 1) == 1


def test_update_status_helpers():
    """Version status helper functions should produce deterministic labels and colors."""

    assert _calculate_update_status("unknown", "v1.0.0", False) == (None, "muted")
    assert _calculate_update_status("v1.0.0", "v1.0.0", False) == (False, "success")
    assert _calculate_update_status("v1.0.0", "v1.1.0", False) == (True, "danger")

    assert _get_update_status_label(True, "v1.1.0") == "Update available · v1.1.0"
    assert _get_update_status_label(False, "v1.0.0") == "Up to date"
    assert _get_update_status_label(None, "v1.2.0") == "Latest release: v1.2.0"
    assert _get_update_status_label(None, None) == "Update status unavailable"


def test_user_model_password_and_display_name(app):
    """User model should hash/check passwords and prefer display_name over username."""

    with app.app_context():
        user = User(username="alice", display_name="Alice")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        assert user.check_password("password123") is True
        assert user.check_password("wrong") is False
        assert user.name == "Alice"

        user.display_name = None
        assert user.name == "alice"


def test_bootstrap_super_admin_create_update_and_fallback(app, caplog):
    """Bootstrap helper should create admin, update existing user, and apply fallback password when empty."""

    with app.app_context():
        caplog.set_level("INFO")
        logger = logging.getLogger("test-bootstrap")

        bootstrap_super_admin(logger, _StubHandler(username="root", password="pw-1", display_name="Root"))
        created = User.query.filter_by(username="root").first()
        assert created is not None
        assert created.is_admin is True
        assert created.display_name == "Root"
        assert created.check_password("pw-1") is True

        bootstrap_super_admin(logger, _StubHandler(username="root", password="pw-2", display_name="Root 2", reset=True))
        updated = User.query.filter_by(username="root").first()
        assert updated.display_name == "Root 2"
        assert updated.check_password("pw-2") is True

        bootstrap_super_admin(logger, _StubHandler(username="fallback", password="", display_name="Fallback", reset=True))
        fallback = User.query.filter_by(username="fallback").first()
        assert fallback is not None
        assert fallback.check_password(DEFAULT_BOOTSTRAP_SUPERADMIN_PASSWORD) is True
