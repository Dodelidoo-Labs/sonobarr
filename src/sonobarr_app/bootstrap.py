from __future__ import annotations

from sqlalchemy.exc import OperationalError, ProgrammingError

from .extensions import db
from .models import User

DEFAULT_BOOTSTRAP_SUPERADMIN_PASSWORD = "change-me"


def bootstrap_super_admin(logger, data_handler) -> None:
    """Ensure the configured bootstrap super-admin user exists with the expected credentials."""
    try:
        admin_count = User.query.filter_by(is_admin=True).count()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Database not ready; skipping super-admin bootstrap: %s", exc)
        db.session.rollback()
        return
    reset_flag = data_handler.superadmin_reset_flag
    if admin_count > 0 and not reset_flag:
        return

    username = data_handler.superadmin_username
    password = data_handler.superadmin_password
    display_name = data_handler.superadmin_display_name
    if not password:
        password = DEFAULT_BOOTSTRAP_SUPERADMIN_PASSWORD
        logger.warning(
            "Super-admin password was empty during bootstrap; using fallback default for username %s.",
            username,
        )

    existing = User.query.filter_by(username=username).first()
    if existing:
        existing.is_admin = True
        if password:
            existing.set_password(password)
        if display_name:
            existing.display_name = display_name
        action = "updated"
    else:
        admin = User(
            username=username,
            display_name=display_name,
            is_admin=True,
        )
        admin.set_password(password)
        db.session.add(admin)
        action = "created"

    try:
        db.session.commit()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Failed to commit super-admin bootstrap changes: %s", exc)
        db.session.rollback()
        return

    logger.info("Super-admin %s %s.", username, action)
