from flask import Blueprint, url_for, redirect, flash, current_app
from flask_login import login_user, logout_user
from ..extensions import oidc
from ..models import db, User

oidc_auth_bp = Blueprint('oidc_auth', __name__)


def _check_oidc_admin_group(user_info):
    """
    Check if user is in the configured OIDC admin group.
    Returns True if user should have admin privileges based on group membership.
    """
    admin_group = current_app.config.get('OIDC_ADMIN_GROUP', '').strip()

    # If no admin group is configured, return False (no auto-promotion)
    if not admin_group:
        return False

    # Check for groups in userinfo
    # Different OIDC providers send groups in different formats:
    # - Some send as 'groups': ['admin', 'users']
    # - Some send as 'roles': ['admin']
    # - Some send as 'memberOf': ['cn=admin,ou=groups,dc=example,dc=com']
    user_groups = user_info.get('groups', [])

    # Handle case where groups might be a string instead of list
    if isinstance(user_groups, str):
        user_groups = [user_groups]

    # Check if user is in the admin group
    is_admin = admin_group in user_groups

    # Log for debugging
    if user_groups:
        current_app.logger.info(
            f"OIDC user groups: {user_groups}, admin group: {admin_group}, is_admin: {is_admin}"
        )
    else:
        current_app.logger.info(
            f"OIDC user has no groups claim. Looking for group: {admin_group}"
        )

    return is_admin


@oidc_auth_bp.route('/oidc/login')
def login():
    """
    Initiates the OIDC login flow.
    """
    redirect_uri = url_for('oidc_auth.callback', _external=True)
    return oidc.sonobarr.authorize_redirect(redirect_uri)


@oidc_auth_bp.route('/oidc/callback')
def callback():
    """
    Handles the OIDC callback after successful authentication.
    """
    try:
        token = oidc.sonobarr.authorize_access_token()
    except Exception as e:
        flash(f"OIDC authorization failed: {e}", "error")
        return redirect(url_for("auth.login"))

    user_info = token.get('userinfo')
    if not user_info:
        flash("Failed to get user info from OIDC provider.", "error")
        return redirect(url_for("auth.login"))

    # Use 'sub' as the unique, persistent identifier for the user
    oidc_user_id = user_info['sub']

    # Check if user should be admin based on OIDC groups
    is_admin_via_group = _check_oidc_admin_group(user_info)

    user = User.query.filter_by(oidc_id=oidc_user_id).first()

    if not user:
        # If user does not exist, create a new one.
        # Use a preferred claim for the username, like 'email' or 'preferred_username'
        username = user_info.get('email') or user_info.get('preferred_username')
        if not username:
            flash("OIDC token must provide 'email' or 'preferred_username' claim.", "error")
            return redirect(url_for("auth.login"))

        # Check if username already exists from a local account
        if User.query.filter_by(username=username).first():
            flash(f"User '{username}' already exists. Please login with your password and link your OIDC account in your profile.", "error")
            # Note: This guide does not include account linking, which would be a future enhancement.
            return redirect(url_for("auth.login"))

        user = User(
            oidc_id=oidc_user_id,
            username=username,
            display_name=user_info.get('name', username),
            is_admin=is_admin_via_group  # Set admin status based on groups
            # Password can be left null for OIDC-only users
        )
        db.session.add(user)
        db.session.commit()

        if is_admin_via_group:
            current_app.logger.info(
                f"New OIDC user '{username}' created with admin privileges via group membership"
            )
    else:
        # Existing OIDC user: sync admin status on every login
        # This ensures group changes in the OIDC provider are reflected
        old_admin_status = user.is_admin
        user.is_admin = is_admin_via_group

        if old_admin_status != is_admin_via_group:
            db.session.commit()
            status_change = "promoted to admin" if is_admin_via_group else "demoted from admin"
            current_app.logger.info(
                f"OIDC user '{user.username}' {status_change} via group sync"
            )

            if is_admin_via_group:
                flash("Welcome back! You have been granted admin privileges.", "success")
            else:
                flash("Welcome back! Your admin privileges have been removed.", "warning")

    login_user(user)
    return redirect(url_for('main.home'))


@oidc_auth_bp.route('/oidc/logout')
def logout():
    """
    Logs the user out from the local session.
    A full OIDC logout would require redirecting to the provider's end_session_endpoint,
    which can be added as a future enhancement.
    """
    logout_user()
    return redirect(url_for('auth.logged_out'))
