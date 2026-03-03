"""HTTP and helper-level tests for auth, profile, admin, OIDC, and public API routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import get_flashed_messages

from sonobarr_app.extensions import db
from sonobarr_app.models import ArtistRequest, User
from sonobarr_app.web import api
from sonobarr_app.web.admin import _is_last_admin_demotion
from sonobarr_app.web.auth import _authenticate
from sonobarr_app.web.main import _update_user_profile
from sonobarr_app.web.oidc_auth import _check_oidc_admin_group, _resolve_oidc_username, _sync_oidc_admin_status


def _create_user(username: str, *, is_admin: bool = False, active: bool = True) -> User:
    """Create and persist a user record for route tests."""

    user = User(
        username=username,
        is_admin=is_admin,
        is_active=active,
        auto_approve_artist_requests=False,
    )
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def _login_as(client, user: User) -> None:
    """Authenticate a Flask test client by setting login session keys."""

    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_api_key_helpers_and_decorator(app):
    """API key helper functions should normalize and validate request keys."""

    app.config["API_KEY"] = "token-1"

    with app.test_request_context("/api/status?api_key=token-1"):
        assert api._configured_api_key() == "token-1"
        assert api._resolve_request_api_key() == "token-1"

    with app.test_request_context("/api/status", headers={"X-API-Key": "token-2"}):
        assert api._resolve_request_api_key() == "token-2"

    @api.api_key_required
    def _secured():
        return "ok"

    with app.test_request_context("/api/status", headers={"X-API-Key": "bad"}):
        response, status = _secured()
        assert status == 401
        assert response.json["error"] == "Invalid API key"


def test_api_endpoints_status_requests_and_stats(app, client):
    """API endpoints should return expected summary and filtering payloads."""

    with app.app_context():
        admin = _create_user("admin", is_admin=True)
        user = _create_user("member", is_admin=False)
        req_pending = ArtistRequest(artist_name="Artist A", requested_by_id=user.id, status="pending")
        req_approved = ArtistRequest(
            artist_name="Artist B",
            requested_by_id=user.id,
            status="approved",
            approved_by_id=admin.id,
            approved_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.session.add(req_pending)
        db.session.add(req_approved)
        db.session.commit()

    app.config["API_KEY"] = "key-123"
    app.extensions["data_handler"].cached_lidarr_names = ["Existing Artist"]
    app.extensions["data_handler"].openai_recommender = object()

    status_resp = client.get("/api/status", headers={"X-API-Key": "key-123"})
    assert status_resp.status_code == 200
    assert status_resp.json["users"]["total"] == 2
    assert status_resp.json["services"]["lidarr_connected"] is True
    assert status_resp.json["services"]["llm_connected"] is True

    list_resp = client.get("/api/artist-requests?status=pending&limit=10", headers={"X-API-Key": "key-123"})
    assert list_resp.status_code == 200
    assert list_resp.json["count"] == 1
    assert list_resp.json["requests"][0]["status"] == "pending"

    stats_resp = client.get("/api/stats", headers={"X-API-Key": "key-123"})
    assert stats_resp.status_code == 200
    assert stats_resp.json["artist_requests"]["total"] == 2
    assert stats_resp.json["users"]["admins"] == 1

    unauthorized = client.get("/api/status", headers={"X-API-Key": "invalid"})
    assert unauthorized.status_code == 401


def test_authenticate_and_profile_helpers(app):
    """Authentication and profile update helpers should enforce expected validation rules."""

    with app.app_context():
        user = _create_user("alice")

        with app.test_request_context("/login", method="POST"):
            assert _authenticate("", "") is None
            assert "Username and password are required." in get_flashed_messages(with_categories=False)

        with app.test_request_context("/login", method="POST"):
            response = _authenticate("alice", "password123")
            assert response.status_code == 302

        errors, changed = _update_user_profile(
            {
                "display_name": "Alice",
                "avatar_url": "https://avatar",
                "lastfm_username": "lastfm",
                "listenbrainz_username": "lb",
                "new_password": "short",
                "confirm_password": "short",
                "current_password": "password123",
            },
            user,
        )
        assert errors == ["New password must be at least 8 characters long."]
        assert changed is False

        errors, changed = _update_user_profile(
            {
                "display_name": "Alice",
                "new_password": "new-password",
                "confirm_password": "new-password",
                "current_password": "password123",
            },
            user,
        )
        assert errors == []
        assert changed is True
        assert user.check_password("new-password")


def test_admin_routes_and_artist_request_resolution(app, client):
    """Admin routes should enforce role checks and mutate users/requests correctly."""

    with app.app_context():
        admin = _create_user("admin", is_admin=True)
        user = _create_user("member", is_admin=False)
        request_obj = ArtistRequest(artist_name="Request Artist", requested_by_id=user.id, status="pending")
        db.session.add(request_obj)
        db.session.commit()
        request_id = request_obj.id

        assert _is_last_admin_demotion(admin, False) is True
        assert _is_last_admin_demotion(user, False) is False

    _login_as(client, user)
    forbidden = client.get("/admin/users")
    assert forbidden.status_code == 403

    _login_as(client, admin)
    create_resp = client.post(
        "/admin/users",
        data={
            "action": "create",
            "username": "new-user",
            "password": "password123",
            "confirm_password": "password123",
            "display_name": "New User",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 302

    with app.app_context():
        created = User.query.filter_by(username="new-user").first()
        assert created is not None

    reject_resp = client.post(
        "/admin/artist-requests",
        data={"action": "reject", "request_id": str(request_id)},
        follow_redirects=False,
    )
    assert reject_resp.status_code == 302

    with app.app_context():
        refreshed = ArtistRequest.query.get(request_id)
        assert refreshed.status == "rejected"


def test_oidc_helper_functions(app):
    """OIDC helper methods should resolve usernames, group membership, and admin sync messages."""

    with app.app_context():
        app.config["OIDC_ADMIN_GROUP"] = "admins"
        assert _check_oidc_admin_group({"groups": ["admins", "users"]}) is True
        assert _check_oidc_admin_group({"groups": "users"}) is False
        assert _resolve_oidc_username({"email": "user@example.com"}) == "user@example.com"
        assert _resolve_oidc_username({"preferred_username": "u"}) == "u"

        oidc_user = _create_user("oidc-user", is_admin=False)
        with app.test_request_context("/oidc/callback"):
            _sync_oidc_admin_status(oidc_user, True)
            assert oidc_user.is_admin is True
            assert "granted admin privileges" in " ".join(get_flashed_messages(with_categories=False)).lower()
