"""Extended route and callback coverage for auth/main/admin/OIDC modules."""

from __future__ import annotations

from types import SimpleNamespace

from flask import get_flashed_messages

from sonobarr_app.extensions import db
from sonobarr_app.models import ArtistRequest, User
import sonobarr_app.web.oidc_auth as oidc_auth
from sonobarr_app.web.auth import _authenticate


def _create_user(username: str, *, is_admin: bool = False, active: bool = True, oidc_id: str | None = None) -> User:
    """Create and commit a user for route and callback tests."""

    user = User(username=username, is_admin=is_admin, is_active=active, oidc_id=oidc_id)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user_id: int) -> None:
    """Authenticate a client via Flask-Login session keys."""

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_auth_routes_and_profile_post_flow(app, client):
    """Auth and profile routes should enforce redirects, login checks, and profile updates."""

    with app.app_context():
        admin = _create_user("admin", is_admin=True)
        member = _create_user("member", is_admin=False)
        admin_id = admin.id
        member_id = member.id

    login_page = client.get("/login")
    assert login_page.status_code == 200

    app.config["OIDC_ONLY"] = True
    oidc_redirect = client.get("/login")
    assert oidc_redirect.status_code == 302
    app.config["OIDC_ONLY"] = False

    bad_login = client.post("/login", data={"username": "member", "password": "wrong"})
    assert bad_login.status_code == 200

    _login(client, member_id)
    profile_get = client.get("/profile")
    assert profile_get.status_code == 200

    profile_post = client.post(
        "/profile",
        data={
            "display_name": "Member",
            "avatar_url": "https://avatar",
            "lastfm_username": "lfm",
            "listenbrainz_username": "lb",
            "new_password": "new-pass-123",
            "confirm_password": "new-pass-123",
            "current_password": "password123",
        },
        follow_redirects=False,
    )
    assert profile_post.status_code == 302

    with app.app_context():
        refreshed = User.query.filter_by(username="member").first()
        assert refreshed.display_name == "Member"
        assert refreshed.lastfm_username == "lfm"
        assert refreshed.listenbrainz_username == "lb"
        assert refreshed.check_password("new-pass-123")

    logged_out = client.get("/logout", follow_redirects=False)
    assert logged_out.status_code == 302
    assert client.get("/logged-out").status_code == 200


def test_auth_redirects_for_authenticated_user_and_inactive_account(app, client):
    """Login routes should redirect authenticated sessions and reject inactive users."""

    with app.app_context():
        active = _create_user("active-user", is_admin=False)
        inactive = _create_user("inactive-user", is_admin=False, active=False)
        active_id = active.id

    _login(client, active_id)
    assert client.get("/login", follow_redirects=False).status_code == 302
    assert client.post("/login", data={"username": "active-user", "password": "password123"}, follow_redirects=False).status_code == 302

    with app.test_request_context("/login", method="POST"):
        result = _authenticate("inactive-user", "password123")
        assert result is None
        assert "Account is disabled." in get_flashed_messages(with_categories=False)


def test_profile_update_error_branch_and_home_route(app, client):
    """Profile update should flash errors for invalid password changes and home should render when logged in."""

    with app.app_context():
        member = _create_user("profile-user", is_admin=False)
        member_id = member.id

    _login(client, member_id)
    assert client.get("/").status_code == 200

    response = client.post(
        "/profile",
        data={
            "display_name": "Profile User",
            "new_password": "new-password-123",
            "confirm_password": "different-password",
            "current_password": "password123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_admin_route_edit_delete_and_invalid_actions(app, client):
    """Admin routes should support edit/delete actions and reject invalid operations."""

    with app.app_context():
        admin = _create_user("admin", is_admin=True)
        target = _create_user("target", is_admin=False)
        admin_id = admin.id
        target_id = target.id

    _login(client, admin_id)

    edit_resp = client.post(
        "/admin/users",
        data={
            "action": "edit",
            "user_id": str(target_id),
            "display_name": "Target User",
            "avatar_url": "https://avatar",
            "is_admin": "on",
            "is_active": "on",
            "auto_approve_artist_requests": "on",
        },
        follow_redirects=False,
    )
    assert edit_resp.status_code == 302

    with app.app_context():
        edited = User.query.get(target_id)
        assert edited.display_name == "Target User"
        assert edited.is_admin is True
        assert edited.auto_approve_artist_requests is True

    invalid_resp = client.post("/admin/users", data={"action": "invalid"}, follow_redirects=False)
    assert invalid_resp.status_code == 302

    delete_resp = client.post(
        "/admin/users",
        data={"action": "delete", "user_id": str(target_id)},
        follow_redirects=False,
    )
    assert delete_resp.status_code == 302

    with app.app_context():
        assert User.query.get(target_id) is None


def test_admin_artist_request_approve_flow(app, client):
    """Approving artist requests should update DB state and emit refresh events."""

    class _Socket:
        def __init__(self):
            self.events = []

        def emit(self, event, payload=None, room=None):
            self.events.append((event, payload, room))

    class _DH:
        def __init__(self):
            self.socketio = _Socket()
            self.calls = []

        def ensure_session(self, key, user_id, is_admin):
            self.calls.append(("ensure", key, user_id, is_admin))

        def add_artists(self, key, artist_name):
            self.calls.append(("add", key, artist_name))
            return "Added"

    with app.app_context():
        admin = _create_user("admin", is_admin=True)
        member = _create_user("member")
        req = ArtistRequest(artist_name="Approve Me", requested_by_id=member.id, status="pending")
        db.session.add(req)
        db.session.commit()
        admin_id = admin.id
        request_id = req.id

    app.extensions["data_handler"] = _DH()
    _login(client, admin_id)

    response = client.post(
        "/admin/artist-requests",
        data={"action": "approve", "request_id": str(request_id)},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        refreshed = ArtistRequest.query.get(request_id)
        assert refreshed.status == "approved"

    emitted = app.extensions["data_handler"].socketio.events
    assert any(event[0] == "refresh_artist" for event in emitted)


def test_oidc_callback_error_and_success_paths(app):
    """OIDC callback should handle provider errors, username conflicts, and successful login."""

    with app.app_context():
        existing = _create_user("exists@example.com", is_admin=False)

    oidc_auth.oidc.sonobarr = SimpleNamespace(
        authorize_access_token=lambda: (_ for _ in ()).throw(RuntimeError("provider error"))
    )
    with app.test_request_context("/oidc/callback"):
        response = oidc_auth.callback()
        assert response.status_code == 302
        assert "authorization failed" in " ".join(get_flashed_messages(with_categories=False)).lower()

    oidc_auth.oidc.sonobarr = SimpleNamespace(authorize_access_token=lambda: {"userinfo": None})
    with app.test_request_context("/oidc/callback"):
        response = oidc_auth.callback()
        assert response.status_code == 302

    oidc_auth.oidc.sonobarr = SimpleNamespace(
        authorize_access_token=lambda: {"userinfo": {"sub": "sub-1", "email": "exists@example.com", "groups": []}}
    )
    with app.test_request_context("/oidc/callback"):
        response = oidc_auth.callback()
        assert response.status_code == 302
        assert "already exists" in " ".join(get_flashed_messages(with_categories=False)).lower()

    app.config["OIDC_ADMIN_GROUP"] = "admins"
    oidc_auth.oidc.sonobarr = SimpleNamespace(
        authorize_access_token=lambda: {
            "userinfo": {"sub": "sub-2", "email": "new@example.com", "name": "New User", "groups": ["admins"]}
        }
    )
    with app.test_request_context("/oidc/callback"):
        response = oidc_auth.callback()
        assert response.status_code == 302

    with app.app_context():
        created = User.query.filter_by(oidc_id="sub-2").first()
        assert created is not None
        assert created.is_admin is True
