from __future__ import annotations

from datetime import datetime, timezone

from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import User, ArtistRequest


bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _create_user_from_form(form):
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm_password = (form.get("confirm_password") or "").strip()
    display_name = (form.get("display_name") or "").strip()
    avatar_url = (form.get("avatar_url") or "").strip()
    is_admin = form.get("is_admin") == "on"

    if not username or not password:
        flash("Username and password are required.", "danger")
        return
    if password != confirm_password:
        flash("Password confirmation does not match.", "danger")
        return
    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "danger")
        return

    user = User(
        username=username,
        display_name=display_name or None,
        avatar_url=avatar_url or None,
        is_admin=is_admin,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"User '{username}' created.", "success")


def _delete_user_from_form(form):
    try:
        user_id = int(form.get("user_id", "0"))
    except ValueError:
        flash("Invalid user id.", "danger")
        return

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "warning")
        return
    if user.is_admin and User.query.filter_by(is_admin=True).count() <= 1:
        flash("At least one administrator must remain.", "warning")
        return

    # Delete associated artist requests first
    ArtistRequest.query.filter_by(requested_by_id=user_id).delete()
    ArtistRequest.query.filter_by(approved_by_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{user.username}' deleted.", "success")


def _edit_user_from_form(form):
    try:
        user_id = int(form.get("user_id", "0"))
    except ValueError:
        flash("Invalid user id.", "danger")
        return

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return

    # Update basic fields
    display_name = (form.get("display_name") or "").strip()
    avatar_url = (form.get("avatar_url") or "").strip()
    user.display_name = display_name or None
    user.avatar_url = avatar_url or None

    # Update active status
    user.is_active = form.get("is_active") == "on"

    # Update admin status with validation
    new_admin_status = form.get("is_admin") == "on"

    # Validate: can't remove last admin
    if user.is_admin and not new_admin_status:
        if User.query.filter_by(is_admin=True).count() <= 1:
            flash("At least one administrator must remain.", "warning")
            return

    # Apply admin status change
    if user.is_admin != new_admin_status:
        user.is_admin = new_admin_status
        status_text = "granted" if new_admin_status else "revoked"

        # Warn if this is an OIDC user (will be synced on next login)
        if user.oidc_id:
            flash(
                f"Admin privileges {status_text} for '{user.username}'. "
                f"Note: This user authenticates via SSO and will be re-synced on next login.",
                "warning"
            )
        else:
            flash(f"Admin privileges {status_text} for '{user.username}'.", "success")

    db.session.commit()
    flash(f"User '{user.username}' updated.", "success")


def _resolve_artist_request(form):
    request_id = form.get("request_id")
    if not request_id:
        flash("Invalid request ID.", "danger")
        return None
    try:
        request_id_int = int(request_id)
    except ValueError:
        flash("Invalid request ID.", "danger")
        return None

    artist_request = ArtistRequest.query.get(request_id_int)
    if not artist_request:
        flash("Artist request not found.", "danger")
        return None
    if artist_request.status != "pending":
        flash("Request has already been processed.", "warning")
        return None
    return artist_request


def _approve_artist_request(artist_request: ArtistRequest):
    data_handler = current_app.extensions.get("data_handler")
    if not data_handler:
        flash(f"Failed to add '{artist_request.artist_name}' to Lidarr. Request not approved.", "danger")
        return

    session_key = f"admin_{current_user.id}"
    data_handler.ensure_session(session_key, current_user.id, True)
    result_status = data_handler.add_artists(session_key, artist_request.artist_name)
    if result_status != "Added":
        flash(f"Failed to add '{artist_request.artist_name}' to Lidarr. Request not approved.", "danger")
        return

    artist_request.status = "approved"
    artist_request.approved_by_id = current_user.id
    artist_request.approved_at = datetime.now(timezone.utc)
    db.session.commit()

    approved_artist = {"Name": artist_request.artist_name, "Status": "Added"}
    data_handler.socketio.emit("refresh_artist", approved_artist)
    flash(f"Request for '{artist_request.artist_name}' approved and added to Lidarr.", "success")


def _reject_artist_request(artist_request: ArtistRequest):
    artist_request.status = "rejected"
    artist_request.approved_by_id = current_user.id
    artist_request.approved_at = datetime.now(timezone.utc)
    db.session.commit()

    data_handler = current_app.extensions.get("data_handler")
    if data_handler:
        rejected_artist = {"Name": artist_request.artist_name, "Status": "Rejected"}
        data_handler.socketio.emit("refresh_artist", rejected_artist)
    flash(f"Request for '{artist_request.artist_name}' rejected.", "success")


@bp.get("/users")
@login_required
@admin_required
def users():
    users_list = User.query.order_by(User.username.asc()).all()
    return render_template("admin_users.html", users=users_list)


@bp.post("/users")
@login_required
@admin_required
def modify_users():
    action = request.form.get("action")
    if action == "create":
        _create_user_from_form(request.form)
    elif action == "edit":
        _edit_user_from_form(request.form)
    elif action == "delete":
        _delete_user_from_form(request.form)
    else:
        flash("Invalid action.", "danger")
    return redirect(url_for("admin.users"))


@bp.get("/artist-requests")
@login_required
@admin_required
def artist_requests():
    pending_requests = ArtistRequest.query.filter_by(status="pending").order_by(
        ArtistRequest.created_at.desc()
    ).all()
    return render_template("admin_artist_requests.html", requests=pending_requests)


@bp.post("/artist-requests")
@login_required
@admin_required
def modify_artist_requests():
    action = request.form.get("action")
    artist_request = _resolve_artist_request(request.form)
    if not artist_request:
        return redirect(url_for("admin.artist_requests"))

    if action == "approve":
        _approve_artist_request(artist_request)
    elif action == "reject":
        _reject_artist_request(artist_request)
    else:
        flash("Invalid action.", "danger")

    return redirect(url_for("admin.artist_requests"))
