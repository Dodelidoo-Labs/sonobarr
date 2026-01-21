from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = PROJECT_ROOT.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

_CONFIG_DIR_OVERRIDE = os.environ.get("sonobarr_config_dir") or os.environ.get("SONOBARR_CONFIG_DIR")
CONFIG_DIR_PATH = Path(_CONFIG_DIR_OVERRIDE) if _CONFIG_DIR_OVERRIDE else APP_ROOT / "config"
CONFIG_DIR_PATH.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR_PATH / "app.db"
SETTINGS_FILE_PATH = CONFIG_DIR_PATH / "settings_config.json"


def get_env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve an environment variable preferring lowercase naming."""
    candidates: list[str] = []
    for candidate in (key, key.lower(), key.upper()):
        if candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        value = os.environ.get(candidate)
        if value not in (None, ""):
            return value
    return default


def _get_bool(key: str, default: bool) -> bool:
    raw_value = get_env_value(key)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(key: str, default: int) -> int:
    raw_value = get_env_value(key)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = get_env_value("secret_key")
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY environment variable is required. Set 'secret_key' (preferred) or 'SECRET_KEY'."
        )

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_SAMESITE = get_env_value("session_cookie_samesite", "Lax")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _get_bool("session_cookie_secure", False)

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    APP_VERSION = get_env_value("release_version", "unknown") or "unknown"
    REPO_URL = get_env_value("repo_url", "https://github.com/Dodelidoo-Labs/sonobarr")
    GITHUB_REPO = get_env_value("github_repo", "Dodelidoo-Labs/sonobarr")
    GITHUB_USER_AGENT = get_env_value("github_user_agent", "sonobarr-app")
    RELEASE_CACHE_TTL_SECONDS = _get_int("release_cache_ttl_seconds", 60 * 60)
    LOG_LEVEL = (get_env_value("log_level", "INFO") or "INFO").upper()
    API_KEY = get_env_value("api_key")

    CONFIG_DIR = str(CONFIG_DIR_PATH)
    SETTINGS_FILE = str(SETTINGS_FILE_PATH)

    # OIDC SSO Configuration
    OIDC_CLIENT_ID = get_env_value("OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET = get_env_value("OIDC_CLIENT_SECRET")
    OIDC_SERVER_METADATA_URL = get_env_value("OIDC_SERVER_METADATA_URL")
    OIDC_ADMIN_GROUP = get_env_value("OIDC_ADMIN_GROUP", "")
    OIDC_ONLY = _get_bool("OIDC_ONLY", False)
