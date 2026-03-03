"""Edge-case tests for admin and OIDC route/helper branches."""

from __future__ import annotations

from types import SimpleNamespace

from flask import get_flashed_messages

from sonobarr_app.extensions import db
from sonobarr_app.models import ArtistRequest, User
import sonobarr_app.web.admin as admin_module
import sonobarr_app.web.oidc_auth as oidc_auth


def _create_user(
    username: str,
    *,
    is_admin: bool = False,
    is_active: bool = True,
    oidc_id: str | None = None,
) -> User:
    """Persist a user used for admin and OIDC branch tests."""

    user = User(
        username=username,
        is_admin=is_admin,
        is_active=is_active,
        oidc_id=oidc_id,
    )
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user_id: int) -> None:
    """Authenticate a Flask test client through Flask-Login session keys."""

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_admin_users_routes_cover_validation_branches(app, client):
    """Admin user management should surface all create/edit/delete validation messages."""

    with app.app_context():
        admin = _create_user("admin", is_admin=True)
        target = _create_user("target", is_admin=False)
        target_id = target.id
        admin_id = admin.id

    _login(client, admin_id)

    missing_fields = client.post(
        "/admin/users",
        data={"action": "create", "username": "", "password": "", "confirm_password": ""},
        follow_redirects=False,
    )
    assert missing_fields.status_code == 302

    mismatch = client.post(
        "/admin/users",
        data={"action": "create", "username": "a", "password": "x", "confirm_password": "y"},
        follow_redirects=False,
    )
    assert mismatch.status_code == 302

    duplicate = client.post(
        "/admin/users",
        data={"action": "create", "username": "target", "password": "x", "confirm_password": "x"},
        follow_redirects=False,
    )
    assert duplicate.status_code == 302

    invalid_delete_id = client.post(
        "/admin/users",
        data={"action": "delete", "user_id": "not-an-int"},
        follow_redirects=False,
    )
    assert invalid_delete_id.status_code == 302

    missing_delete_user = client.post(
        "/admin/users",
        data={"action": "delete", "user_id": "99999"},
        follow_redirects=False,
    )
    assert missing_delete_user.status_code == 302

    self_delete = client.post(
        "/admin/users",
        data={"action": "delete", "user_id": str(admin_id)},
        follow_redirects=False,
    )
    assert self_delete.status_code == 302

    invalid_edit_id = client.post(
        "/admin/users",
        data={"action": "edit", "user_id": "invalid"},
        follow_redirects=False,
    )
    assert invalid_edit_id.status_code == 302

    missing_edit_user = client.post(
        "/admin/users",
        data={"action": "edit", "user_id": "99999"},
        follow_redirects=False,
    )
    assert missing_edit_user.status_code == 302

    with app.app_context():
        target_oidc = User.query.get(target_id)
        target_oidc.oidc_id = "oidc-subject-1"
        db.session.commit()

    oidc_edit = client.post(
        "/admin/users",
        data={
            "action": "edit",
            "user_id": str(target_id),
            "display_name": "OIDC User",
            "is_admin": "on",
            "is_active": "on",
        },
        follow_redirects=False,
    )
    assert oidc_edit.status_code == 302

    users_page = client.get("/admin/users")
    assert users_page.status_code == 200


def test_admin_helpers_cover_last_admin_and_artist_request_edge_paths(app, monkeypatch):
    """Admin helpers should handle last-admin protections and artist request validation failures."""

    with app.app_context():
        admin = _create_user("solo-admin", is_admin=True)
        member = _create_user("member-user", is_admin=False)
        pending = ArtistRequest(artist_name="Pending Artist", requested_by_id=member.id, status="pending")
        already_done = ArtistRequest(artist_name="Done Artist", requested_by_id=member.id, status="approved")
        db.session.add(pending)
        db.session.add(already_done)
        db.session.commit()
        pending_id = pending.id
        approved_id = already_done.id
        admin_id = admin.id

    with app.test_request_context("/admin/users", method="POST"):
        monkeypatch.setattr(
            admin_module,
            "current_user",
            SimpleNamespace(id=-1, is_authenticated=True, is_admin=True),
        )
        admin_module._delete_user_from_form({"user_id": str(admin_id)})
        assert "At least one administrator must remain." in get_flashed_messages(with_categories=False)

    with app.test_request_context("/admin/users", method="POST"):
        admin_module._edit_user_from_form({"user_id": str(admin_id), "is_active": "on"})
        assert "At least one administrator must remain." in get_flashed_messages(with_categories=False)

    with app.test_request_context("/admin/artist-requests", method="POST"):
        assert admin_module._resolve_artist_request({}) is None
        assert admin_module._resolve_artist_request({"request_id": "bad"}) is None
        assert admin_module._resolve_artist_request({"request_id": "99999"}) is None
        assert admin_module._resolve_artist_request({"request_id": str(approved_id)}) is None

    with app.test_request_context("/admin/artist-requests", method="POST"):
        monkeypatch.setattr(
            admin_module,
            "current_user",
            SimpleNamespace(id=admin_id, is_authenticated=True, is_admin=True),
        )
        request_obj = admin_module._resolve_artist_request({"request_id": str(pending_id)})
        assert request_obj is not None

        app.extensions.pop("data_handler", None)
        admin_module._approve_artist_request(request_obj)
        assert "Failed to add" in " ".join(get_flashed_messages(with_categories=False))

        class _FailingHandler:
            def __init__(self):
                self.socketio = SimpleNamespace(emit=lambda *args, **kwargs: None)

            def ensure_session(self, *args, **kwargs):
                return None

            def add_artists(self, *args, **kwargs):
                return "Failed to Add"

        app.extensions["data_handler"] = _FailingHandler()
        request_obj.status = "pending"
        db.session.commit()
        admin_module._approve_artist_request(request_obj)
        assert "Failed to add" in " ".join(get_flashed_messages(with_categories=False))


def test_admin_artist_request_routes_cover_listing_and_invalid_action(app, client):
    """Admin artist request routes should render list pages and reject unknown actions."""

    with app.app_context():
        admin = _create_user("admin-artist", is_admin=True)
        requester = _create_user("requester", is_admin=False)
        request_obj = ArtistRequest(artist_name="Needs Decision", requested_by_id=requester.id, status="pending")
        db.session.add(request_obj)
        db.session.commit()
        request_id = request_obj.id
        admin_id = admin.id

    _login(client, admin_id)

    listing = client.get("/admin/artist-requests")
    assert listing.status_code == 200

    invalid_action = client.post(
        "/admin/artist-requests",
        data={"action": "invalid", "request_id": str(request_id)},
        follow_redirects=False,
    )
    assert invalid_action.status_code == 302

    missing_request = client.post(
        "/admin/artist-requests",
        data={"action": "approve"},
        follow_redirects=False,
    )
    assert missing_request.status_code == 302


def test_oidc_login_logout_and_callback_edge_branches(app, client, monkeypatch):
    """OIDC routes should cover login redirect, callback guardrails, and logout behavior."""

    with app.app_context():
        existing_oidc = _create_user("oidc-existing", is_admin=True, oidc_id="oidc-sub")
        oidc_id = existing_oidc.id

    app.config["OIDC_ADMIN_GROUP"] = ""
    with app.test_request_context("/oidc/callback"):
        assert oidc_auth._check_oidc_admin_group({"groups": ["admins"]}) is False

    oidc_auth.oidc.sonobarr = SimpleNamespace(authorize_redirect=lambda redirect_uri: f"redirect:{redirect_uri}")
    with app.test_request_context("/oidc/login"):
        login_response = oidc_auth.login()
        assert str(login_response).startswith("redirect:")

    oidc_auth.oidc.sonobarr = SimpleNamespace(
        authorize_access_token=lambda: {"userinfo": {"sub": "missing-username"}}
    )
    with app.test_request_context("/oidc/callback"):
        response = oidc_auth.callback()
        assert response.status_code == 302
        assert "must provide" in " ".join(get_flashed_messages(with_categories=False)).lower()

    app.config["OIDC_ADMIN_GROUP"] = "admins"
    oidc_auth.oidc.sonobarr = SimpleNamespace(
        authorize_access_token=lambda: {"userinfo": {"sub": "oidc-sub", "groups": []}}
    )
    with app.test_request_context("/oidc/callback"):
        response = oidc_auth.callback()
        assert response.status_code == 302

    with app.app_context():
        refreshed = User.query.get(oidc_id)
        assert refreshed.is_admin is False

    with app.app_context():
        manual_user = User.query.get(oidc_id)
        manual_user.is_admin = False
        db.session.commit()
        with app.test_request_context("/oidc/callback"):
            oidc_auth._sync_oidc_admin_status(manual_user, False)
            assert get_flashed_messages(with_categories=False) == []

    called = []
    monkeypatch.setattr(oidc_auth, "logout_user", lambda: called.append(True))
    logout_response = client.get("/oidc/logout", follow_redirects=False)
    assert logout_response.status_code == 302
    assert called
