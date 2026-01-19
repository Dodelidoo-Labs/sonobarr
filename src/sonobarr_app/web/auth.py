from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..models import User
from ..extensions import db


bp = Blueprint("auth", __name__)

_HOME_ENDPOINT = "main.home"


def _authenticate(username: str, password: str):
    if not username or not password:
        flash("Username and password are required.", "danger")
        return None

    try:
        user = User.query.filter_by(username=username).first()
    except (OperationalError, ProgrammingError) as exc:
        current_app.logger.warning(
            "Database schema not ready during login attempt for username %s: %s",
            username,
            exc,
        )
        db.session.rollback()
        flash("Database upgrade in progress. Please try again in a moment.", "warning")
        return None

    if not user or not user.check_password(password):
        flash("Invalid username or password.", "danger")
        return None
    if not user.is_active:
        flash("Account is disabled.", "danger")
        return None

    login_user(user)
    flash("Welcome to Sonobarr!", "success")
    return redirect(url_for(_HOME_ENDPOINT))


@bp.get("/login")
def login():
    if current_app.config.get("OIDC_ONLY"):
        return redirect(url_for('oidc_auth.login'))
    if current_user.is_authenticated:
        return redirect(url_for(_HOME_ENDPOINT))
    return render_template("login.html")


@bp.post("/login")
def login_submit():
    if current_app.config.get("OIDC_ONLY"):
        flash("Password login is disabled.", "warning")
        return redirect(url_for('oidc_auth.login'))
    if current_user.is_authenticated:
        return redirect(url_for(_HOME_ENDPOINT))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    response = _authenticate(username, password)
    if response is not None:
        return response
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.logged_out"))


@bp.get("/logged-out")
def logged_out():
    return render_template("logged_out.html")
