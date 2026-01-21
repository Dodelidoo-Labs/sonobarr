from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from flask import Flask, current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.middleware.proxy_fix import ProxyFix

from .bootstrap import bootstrap_super_admin
from .config import Config, STATIC_DIR, TEMPLATE_DIR
from .extensions import csrf, db, login_manager, migrate, oidc, socketio
from .services.data_handler import DataHandler
from .services.releases import ReleaseClient
from .sockets import register_socketio_handlers
from .web import admin_bp, api_bp, auth_bp, main_bp

def _configure_swagger(app: Flask) -> None:
    from flasgger import Swagger
    
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",
                "route": "/api/docs.json",
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/api/docs/",
        "swagger_ui_config": {
            "displayOperationId": False,
            "defaultModelsExpandDepth": 0,
            "displayRequestDuration": True,
            "deepLinking": True,
            "filter": False,
            "showExtensions": False,
            "showCommonExtensions": False,
        }
    }
    
    swagger_template = {
        "swagger": "2.0",
        "info": {
            "title": "Sonobarr API",
            "version": app.config.get("APP_VERSION", "unknown"),
            "description": "Sonobarr REST API documentation",
        },
        "host": "",  # Empty = use current host
        "basePath": "/api",
        "schemes": ["https", "http"],  # HTTPS first
        "securityDefinitions": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "name": "X-API-Key",
                "in": "header",
                "description": "Enter your API key"
            }
        },
        "security": [
            {"ApiKeyAuth": []}
        ]
    }
    
    Swagger(app, config=swagger_config, template=swagger_template)
    
def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        template_folder=str(TEMPLATE_DIR),
    )
    app.config.from_object(config_class)

    # Configure ProxyFix to trust reverse proxy headers (Caddy, nginx, etc.)
    # This ensures Flask generates correct HTTPS URLs when behind a reverse proxy
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1
    )

    _configure_logging(app)
    _init_core_extensions(app)
    _register_user_loader()

    data_handler = _initialize_services(app)

    # Blueprints ------------------------------------------------------
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    from .web.oidc_auth import oidc_auth_bp
    app.register_blueprint(oidc_auth_bp)

    # Swagger must be initialized AFTER blueprints are registered
    _configure_swagger(app)

    # Socket.IO -------------------------------------------------------
    register_socketio_handlers(socketio, data_handler)

    # Database initialisation ----------------------------------------
    _run_database_initialisation(app, data_handler)

    return app


def _configure_logging(app: Flask) -> None:
    log_level_name = (app.config.get("LOG_LEVEL") or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s"))
        root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    for handler in root_logger.handlers:
        handler.setLevel(log_level)

    gunicorn_logger = logging.getLogger("gunicorn.error")
    if gunicorn_logger.handlers:
        app.logger.handlers = gunicorn_logger.handlers
        for handler in app.logger.handlers:
            handler.setLevel(log_level)
    elif not app.logger.handlers:
        app_handler = logging.StreamHandler()
        app_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s"))
        app_handler.setLevel(log_level)
        app.logger.addHandler(app_handler)

    app.logger.setLevel(log_level)

    # Ensure our custom namespace follows the same level and doesn't duplicate output
    sonobarr_logger = logging.getLogger("sonobarr_app")
    sonobarr_logger.setLevel(log_level)
    sonobarr_logger.propagate = False
    logging.getLogger("sonobarr").setLevel(log_level)

    logging.captureWarnings(True)

__all__ = ["create_app", "socketio"]


def _init_core_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access Sonobarr."
    login_manager.login_message_category = "warning"
    csrf.init_app(app)
    socketio.init_app(app, async_mode="gevent")
    oidc.init_app(app)
    oidc.register(
        name='sonobarr',
        client_id=app.config.get('OIDC_CLIENT_ID'),
        client_secret=app.config.get('OIDC_CLIENT_SECRET'),
        server_metadata_url=app.config.get('OIDC_SERVER_METADATA_URL'),
        client_kwargs={'scope': 'openid email profile groups'}
    )


def _register_user_loader() -> None:
    from .models import User  # Imported lazily to avoid circular imports

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[User]:
        if not user_id:
            return None
        try:
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None
        except (OperationalError, ProgrammingError) as exc:
            current_app.logger.warning(
                "Database schema not ready when loading user %s: %s", user_id, exc
            )
            db.session.rollback()
            return None


def _initialize_services(app: Flask) -> DataHandler:
    data_handler = DataHandler(socketio=socketio, logger=app.logger, app_config=app.config)
    release_client = ReleaseClient(
        repo=app.config.get("GITHUB_REPO", "Dodelidoo-Labs/sonobarr"),
        user_agent=app.config.get("GITHUB_USER_AGENT", "sonobarr-app"),
        ttl_seconds=int(app.config.get("RELEASE_CACHE_TTL_SECONDS", 3600)),
        logger=app.logger,
    )

    data_handler.set_flask_app(app)
    app.extensions["data_handler"] = data_handler
    app.extensions["release_client"] = release_client

    _register_footer_metadata(app, release_client)

    return data_handler


def _register_footer_metadata(app: Flask, release_client: ReleaseClient) -> None:
    """Register context processor for footer metadata (version info, update status)."""
    
    @app.context_processor
    def inject_footer_metadata() -> Dict[str, Any]:
        current_version = (app.config.get("APP_VERSION") or "unknown").strip() or "unknown"
        release_info = release_client.fetch_latest()
        latest_version = release_info.get("tag_name")
        
        update_available, status_color = _calculate_update_status(
            current_version, latest_version, release_info.get("error")
        )
        status_label = _get_update_status_label(update_available, latest_version)

        return {
            "repo_url": app.config.get("REPO_URL", "https://github.com/Dodelidoo-Labs/sonobarr"),
            "app_version": current_version,
            "latest_release_version": latest_version,
            "latest_release_url": release_info.get("html_url")
            or "https://github.com/Dodelidoo-Labs/sonobarr/releases",
            "update_available": update_available,
            "update_status_color": status_color,
            "update_status_label": status_label,
        }


def _calculate_update_status(
    current_version: str, latest_version: Optional[str], has_error: bool
) -> tuple[Optional[bool], str]:
    """Calculate if update is available and determine status color."""
    if not latest_version:
        return None, "muted"
    
    if current_version.lower() in {"", "unknown", "dev", "development"}:
        return None, "muted"
    
    update_available = latest_version != current_version
    status_color = "danger" if update_available else "success"
    
    if has_error and not latest_version:
        status_color = "muted"
    
    return update_available, status_color


def _get_update_status_label(update_available: Optional[bool], latest_version: Optional[str]) -> str:
    """Get human-readable update status label."""
    if update_available is True and latest_version:
        return f"Update available · {latest_version}"
    if update_available is False:
        return "Up to date"
    if update_available is None and latest_version:
        return f"Latest release: {latest_version}"
    return "Update status unavailable"


def _run_database_initialisation(app: Flask, data_handler: DataHandler) -> None:
    with app.app_context():
        db.create_all()
        _ensure_user_profile_columns(app.logger)
        bootstrap_super_admin(app.logger, data_handler)


def _ensure_user_profile_columns(logger: logging.Logger) -> None:
    """Backfill the user listening columns if migrations have not run yet."""

    if os.environ.get("SONOBARR_SKIP_PROFILE_BACKFILL") == "1":
        logger.debug("Profile column backfill skipped via environment flag.")
        return

    try:
        inspector = inspect(db.engine)
        user_columns = {column["name"] for column in inspector.get_columns("users")}
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Unable to inspect users table for backfill: %s", exc)
        db.session.rollback()
        return

    alter_statements: list[tuple[str, str]] = []
    if "lastfm_username" not in user_columns:
        alter_statements.append(("lastfm_username", "ALTER TABLE users ADD COLUMN lastfm_username VARCHAR(120)"))
    if "listenbrainz_username" not in user_columns:
        alter_statements.append((
            "listenbrainz_username",
            "ALTER TABLE users ADD COLUMN listenbrainz_username VARCHAR(120)",
        ))

    for column_name, statement in alter_statements:
        try:
            db.session.execute(text(statement))
            db.session.commit()
            logger.info("Added missing column '%s' via automatic backfill", column_name)
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Failed to apply backfill for column '%s': %s", column_name, exc)
            db.session.rollback()
            # Keep attempting remaining columns; missing ones will be caught again on next start.
