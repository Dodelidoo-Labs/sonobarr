from __future__ import annotations

import json
import logging
import os
import random
import secrets
import string
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import musicbrainzngs
import pylast
import requests
from thefuzz import fuzz
from unidecode import unidecode

from ..config import get_env_value
from ..extensions import db
from ..models import User, ArtistRequest
from .openai_client import DEFAULT_MAX_SEED_ARTISTS, OpenAIRecommender
from .integrations.lastfm_user import LastFmUserService
from .integrations.listenbrainz_user import (
    ListenBrainzIntegrationError,
    ListenBrainzUserService,
)

LIDARR_MONITOR_TYPES = {
    "all",
    "future",
    "missing",
    "existing",
    "latest",
    "first",
    "none",
    "unknown",
}

LIDARR_MONITOR_NEW_ITEM_TYPES = {
    "all",
    "none",
    "new",
}


@dataclass
class SessionState:
    sid: str
    user_id: Optional[int]
    is_admin: bool = False
    recommended_artists: List[dict] = field(default_factory=list)
    lidarr_items: List[dict] = field(default_factory=list)
    cleaned_lidarr_items: List[str] = field(default_factory=list)
    artists_to_use_in_search: List[str] = field(default_factory=list)
    similar_artist_candidates: List[dict] = field(default_factory=list)
    similar_artist_batch_pointer: int = 0
    initial_batch_sent: bool = False
    ai_seed_artists: List[str] = field(default_factory=list)
    stop_event: threading.Event = field(default_factory=threading.Event)
    search_lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False

    def __post_init__(self) -> None:
        self.stop_event.set()

    def prepare_for_search(self) -> None:
        self.recommended_artists.clear()
        self.artists_to_use_in_search.clear()
        self.similar_artist_candidates.clear()
        self.similar_artist_batch_pointer = 0
        self.initial_batch_sent = False
        self.ai_seed_artists.clear()
        self.stop_event.clear()
        self.running = True

    def mark_stopped(self) -> None:
        self.stop_event.set()
        self.running = False


class DataHandler:
    _version_logged = False

    def __init__(self, socketio, logger: Optional[logging.Logger], app_config: Dict[str, Any]) -> None:
        self.socketio = socketio
        self.logger = logger or logging.getLogger("sonobarr")
        self._flask_app = None  # bound in app factory to allow background tasks to use app context
        self.musicbrainzngs_logger = logging.getLogger("musicbrainzngs")
        self.musicbrainzngs_logger.setLevel(logging.WARNING)
        self.pylast_logger = logging.getLogger("pylast")
        self.pylast_logger.setLevel(logging.WARNING)

        app_name_text = Path(__file__).name.replace(".py", "")
        release_version = (app_config.get("APP_VERSION") or get_env_value("release_version", "unknown") or "unknown")
        if not DataHandler._version_logged:
            self.logger.info("%s initialised (version=%s)", app_name_text, release_version)
            DataHandler._version_logged = True

        self.sessions: Dict[str, SessionState] = {}
        self.sessions_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.cached_lidarr_names: List[str] = []
        self.cached_cleaned_lidarr_names: List[str] = []

        config_dir = Path(app_config.get("CONFIG_DIR")) if app_config.get("CONFIG_DIR") else None
        if config_dir is None:
            config_dir = Path.cwd() / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.config_folder = config_dir
        settings_path = app_config.get("SETTINGS_FILE")
        self.settings_config_file = Path(settings_path) if settings_path else self.config_folder / "settings_config.json"
        self.similar_artist_batch_size = 10
        self.openai_api_key = ""
        self.openai_model = ""
        self.openai_api_base = ""
        self.openai_extra_headers = ""
        self.openai_max_seed_artists = DEFAULT_MAX_SEED_ARTISTS
        self.api_key = ""
        self.lidarr_monitor_option = ""
        self.lidarr_monitored = True
        self.lidarr_albums_to_monitor: List[str] = []
        self.lidarr_monitor_new_items = ""
        self.openai_recommender: Optional[OpenAIRecommender] = None
        self.last_fm_user_service: Optional[LastFmUserService] = None
        self.listenbrainz_user_service = ListenBrainzUserService()

        self.load_environ_or_config_settings()

    # App binding ----------------------------------------------------
    def set_flask_app(self, app) -> None:
        """Bind the Flask app so background tasks can push an app context."""
        self._flask_app = app
        # Set API_KEY in Flask app config from settings
        if self.api_key:
            app.config['API_KEY'] = self.api_key

    def _env(self, key: str) -> str:
        value = get_env_value(key)
        return value if value is not None else ""

    @staticmethod
    def _coerce_bool(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return None

    @staticmethod
    def _coerce_int(value: Any, *, minimum: Optional[int] = None) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if minimum is not None and parsed < minimum:
            return minimum
        return parsed

    @staticmethod
    def _coerce_float(value: Any, *, minimum: Optional[float] = None) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if minimum is not None and parsed < minimum:
            return minimum
        return parsed

    @staticmethod
    def _normalize_monitor_option(value: Any) -> str:
        if value is None:
            return ""
        candidate = str(value).strip().lower()
        return candidate if candidate in LIDARR_MONITOR_TYPES else ""

    @staticmethod
    def _normalize_monitor_new_items(value: Any) -> str:
        if value is None:
            return ""
        candidate = str(value).strip().lower()
        return candidate if candidate in LIDARR_MONITOR_NEW_ITEM_TYPES else ""

    @staticmethod
    def _parse_albums_to_monitor(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is None:
            return []
        items: List[str] = []
        text = str(value)
        separators = text.replace(",", "\n").splitlines()
        for item in separators:
            cleaned = item.strip()
            if cleaned:
                items.append(cleaned)
        return items

    @staticmethod
    def _clean_str_value(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _apply_string_settings(self, data: dict) -> None:
        string_fields = {
            "lidarr_address": "lidarr_address",
            "lidarr_api_key": "lidarr_api_key",
            "root_folder_path": "root_folder_path",
            "youtube_api_key": "youtube_api_key",
            "openai_api_key": "openai_api_key",
            "openai_model": "openai_model",
            "openai_api_base": "openai_api_base",
            "openai_extra_headers": "openai_extra_headers",
            "last_fm_api_key": "last_fm_api_key",
            "last_fm_api_secret": "last_fm_api_secret",
            "api_key": "api_key",
        }
        for payload_key, attr in string_fields.items():
            if payload_key in data:
                setattr(self, attr, self._clean_str_value(data.get(payload_key)))

    def _apply_int_settings(self, data: dict) -> None:
        int_fields = {
            "quality_profile_id": ("quality_profile_id", 1),
            "metadata_profile_id": ("metadata_profile_id", 1),
            "similar_artist_batch_size": ("similar_artist_batch_size", 1),
            "openai_max_seed_artists": ("openai_max_seed_artists", 1),
        }
        for payload_key, (attr, minimum) in int_fields.items():
            if payload_key in data:
                parsed_int = self._coerce_int(data.get(payload_key), minimum=minimum)
                if parsed_int is not None:
                    setattr(self, attr, parsed_int)

    def _apply_float_settings(self, data: dict) -> None:
        float_fields = {
            "lidarr_api_timeout": ("lidarr_api_timeout", 1.0),
            "auto_start_delay": ("auto_start_delay", 0.0),
        }
        for payload_key, (attr, minimum) in float_fields.items():
            if payload_key in data:
                parsed_float = self._coerce_float(data.get(payload_key), minimum=minimum)
                if parsed_float is not None:
                    setattr(self, attr, parsed_float)

    def _apply_bool_settings(self, data: dict) -> None:
        bool_fields = {
            "fallback_to_top_result": "fallback_to_top_result",
            "search_for_missing_albums": "search_for_missing_albums",
            "dry_run_adding_to_lidarr": "dry_run_adding_to_lidarr",
            "auto_start": "auto_start",
            "lidarr_monitored": "lidarr_monitored",
        }
        for payload_key, attr in bool_fields.items():
            if payload_key in data:
                coerced_bool = self._coerce_bool(data.get(payload_key))
                if coerced_bool is not None:
                    setattr(self, attr, coerced_bool)

    # Session helpers -------------------------------------------------
    def ensure_session(self, sid: str, user_id: Optional[int] = None, is_admin: bool = False) -> SessionState:
        with self.sessions_lock:
            session = self.sessions.get(sid)
            if session is None:
                session = SessionState(sid=sid, user_id=user_id, is_admin=is_admin)
                self.sessions[sid] = session
            elif user_id is not None:
                session.user_id = user_id
                session.is_admin = is_admin
            return session

    def get_session_if_exists(self, sid: str) -> Optional[SessionState]:
        with self.sessions_lock:
            return self.sessions.get(sid)

    def remove_session(self, sid: str) -> None:
        with self.sessions_lock:
            session = self.sessions.pop(sid, None)
        if session:
            session.mark_stopped()

    # Cache helpers ---------------------------------------------------
    def _copy_cached_lidarr_items(self, checked: bool = False) -> List[dict]:
        with self.cache_lock:
            return [{"name": name, "checked": checked} for name in self.cached_lidarr_names]

    def _copy_cached_cleaned_names(self) -> List[str]:
        with self.cache_lock:
            return list(self.cached_cleaned_lidarr_names)

    # Personal discovery helpers -----------------------------------
    def _resolve_user(self, user_id: Optional[int]) -> Optional[User]:
        if user_id is None:
            return None
        try:
            if self._flask_app is not None:
                with self._flask_app.app_context():
                    return User.query.get(int(user_id))
            # Fallback: rely on current app context if already present
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    # Per-user API key getters with global fallback ----------------------
    def get_lastfm_api_key(self, user: Optional[User] = None) -> str:
        """Return user's Last.fm API key if set, else fall back to global."""
        if user and getattr(user, 'lastfm_api_key', None):
            return user.lastfm_api_key
        return self.last_fm_api_key

    def get_lastfm_api_secret(self, user: Optional[User] = None) -> str:
        """Return user's Last.fm API secret if set, else fall back to global."""
        if user and getattr(user, 'lastfm_api_secret', None):
            return user.lastfm_api_secret
        return self.last_fm_api_secret

    def get_youtube_api_key(self, user: Optional[User] = None) -> str:
        """Return user's YouTube API key if set, else fall back to global."""
        if user and getattr(user, 'youtube_api_key', None):
            return user.youtube_api_key
        return self.youtube_api_key

    def get_openai_api_key(self, user: Optional[User] = None) -> str:
        """Return user's OpenAI API key if set, else fall back to global."""
        if user and getattr(user, 'openai_api_key', None):
            return user.openai_api_key
        return self.openai_api_key

    def get_openai_api_base(self, user: Optional[User] = None) -> str:
        """Return user's OpenAI API base if set, else fall back to global."""
        if user and getattr(user, 'openai_api_base', None):
            return user.openai_api_base
        return self.openai_api_base

    def get_openai_model(self, user: Optional[User] = None) -> str:
        """Return user's OpenAI model if set, else fall back to global."""
        if user and getattr(user, 'openai_model', None):
            return user.openai_model
        return self.openai_model

    def get_openai_extra_headers(self, user: Optional[User] = None) -> str:
        """Return user's OpenAI extra headers if set, else fall back to global."""
        if user and getattr(user, 'openai_extra_headers', None):
            return user.openai_extra_headers
        return self.openai_extra_headers

    def get_openai_max_seed_artists(self, user: Optional[User] = None) -> int:
        """Return user's OpenAI max seed artists if set, else fall back to global."""
        if user and getattr(user, 'openai_max_seed_artists', None) is not None:
            return user.openai_max_seed_artists
        return self.openai_max_seed_artists

    def get_openai_recommender_for_user(self, user: Optional[User] = None) -> Optional["OpenAIRecommender"]:
        """
        Get an OpenAI recommender configured for the user.
        Uses user's API keys if set, otherwise falls back to global config.
        Returns None if no API key is available.
        """
        api_key = (self.get_openai_api_key(user) or "").strip()
        base_url = (self.get_openai_api_base(user) or "").strip()
        env_api_key = os.environ.get("OPENAI_API_KEY", "").strip()

        if not any([api_key, base_url, env_api_key]):
            return None

        # If user has no custom keys, use the global recommender
        user_has_custom_keys = user and (
            getattr(user, 'openai_api_key', None) or
            getattr(user, 'openai_api_base', None)
        )
        if not user_has_custom_keys and self.openai_recommender:
            return self.openai_recommender

        # Create a recommender with user's (or global) settings
        model = (self.get_openai_model(user) or "").strip() or None
        max_seeds = self.get_openai_max_seed_artists(user)
        try:
            max_seeds_int = int(max_seeds)
        except (TypeError, ValueError):
            max_seeds_int = DEFAULT_MAX_SEED_ARTISTS
        if max_seeds_int <= 0:
            max_seeds_int = DEFAULT_MAX_SEED_ARTISTS

        # Parse extra headers
        headers_raw = self.get_openai_extra_headers(user)
        headers_override = {}
        if headers_raw:
            try:
                import json
                parsed = json.loads(headers_raw)
                if isinstance(parsed, dict):
                    headers_override = {str(k).strip(): str(v) for k, v in parsed.items() if k and v is not None}
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            return OpenAIRecommender(
                api_key=api_key or None,
                model=model,
                base_url=base_url or None,
                default_headers=headers_override or None,
                max_seed_artists=max_seeds_int,
            )
        except Exception as exc:
            self.logger.error("Failed to initialize user LLM client: %s", exc)
            return None

    def emit_personal_sources_state(self, sid: str) -> None:
        session = self.get_session_if_exists(sid)
        if session is None:
            session = self.ensure_session(sid)

        user = self._resolve_user(session.user_id)

        lastfm_service_ready = self.last_fm_user_service is not None
        lastfm_username = user.lastfm_username if user else None
        lastfm_enabled = bool(lastfm_service_ready and lastfm_username)
        if not lastfm_service_ready:
            lastfm_reason = "Administrator must configure Last.fm API keys in Settings."
        elif not lastfm_username:
            lastfm_reason = "Add your Last.fm username in Profile → Listening services."
        else:
            lastfm_reason = None
        state = {
            "lastfm": {
                "enabled": lastfm_enabled,
                "username": lastfm_username,
                "reason": lastfm_reason,
                "configured": lastfm_service_ready,
            },
        }

        listenbrainz_service_ready = self.listenbrainz_user_service is not None
        listenbrainz_username = user.listenbrainz_username if user else None
        if not listenbrainz_service_ready:
            listenbrainz_reason = "ListenBrainz integration is unavailable right now."
        elif not listenbrainz_username:
            listenbrainz_reason = "Add your ListenBrainz username in Profile → Listening services."
        else:
            listenbrainz_reason = None

        state["listenbrainz"] = {
            "enabled": bool(listenbrainz_service_ready and listenbrainz_username),
            "username": listenbrainz_username,
            "reason": listenbrainz_reason,
            "configured": listenbrainz_service_ready,
        }

        self.socketio.emit("personal_sources_state", state, room=sid)

    def broadcast_personal_sources_state(self) -> None:
        with self.sessions_lock:
            session_ids = [session.sid for session in self.sessions.values()]
        for session_id in session_ids:
            self.emit_personal_sources_state(session_id)

    def refresh_personal_sources_for_user(self, user_id: int) -> None:
        with self.sessions_lock:
            session_ids = [session.sid for session in self.sessions.values() if session.user_id == user_id]
        for session_id in session_ids:
            self.emit_personal_sources_state(session_id)

    def _emit_personal_error(self, sid: str, source: str, message: str, *, title: Optional[str] = None) -> None:
        payload = {"source": source, "message": message}
        self.socketio.emit("user_recs_error", payload, room=sid)
        self.socketio.emit(
            "new_toast_msg",
            {
                "title": title or "Personal discovery",
                "message": message,
            },
            room=sid,
        )

    def _dedupe_names(self, names: Sequence[str]) -> List[str]:
        deduped: List[str] = []
        seen: set[str] = set()
        for name in names:
            cleaned = (name or "").strip()
            if not cleaned:
                continue
            normalized = unidecode(cleaned).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(cleaned)
        return deduped

    # Socket helpers --------------------------------------------------
    def connection(self, sid: str, user_id: Optional[int], is_admin: bool = False) -> None:
        session = self.ensure_session(sid, user_id, is_admin)
        # Send user info to frontend
        self.socketio.emit("user_info", {"is_admin": session.is_admin}, room=sid)
        if session.recommended_artists:
            self.socketio.emit("more_artists_loaded", session.recommended_artists, room=sid)
        if session.lidarr_items:
            payload = {
                "Status": "Success",
                "Data": session.lidarr_items,
                "Running": session.running,
            }
            self.socketio.emit("lidarr_sidebar_update", payload, room=sid)
        self.emit_personal_sources_state(sid)

    def side_bar_opened(self, sid: str) -> None:
        session = self.ensure_session(sid)
        if not session.lidarr_items:
            items = self._copy_cached_lidarr_items()
            if items:
                session.lidarr_items = items
                session.cleaned_lidarr_items = self._copy_cached_cleaned_names()
        if session.lidarr_items:
            payload = {
                "Status": "Success",
                "Data": session.lidarr_items,
                "Running": session.running,
            }
            self.socketio.emit("lidarr_sidebar_update", payload, room=sid)
        self.emit_personal_sources_state(sid)

    # Lidarr interactions ---------------------------------------------
    def get_artists_from_lidarr(self, sid: str, checked: bool = False) -> None:
        session = self.ensure_session(sid)
        try:
            endpoint = f"{self.lidarr_address}/api/v1/artist"
            headers = {"X-Api-Key": self.lidarr_api_key}
            response = requests.get(endpoint, headers=headers, timeout=self.lidarr_api_timeout)
            if response.status_code == 200:
                full_list = response.json()
                names = [unidecode(artist["artistName"], replace_str=" ") for artist in full_list]
                names.sort(key=lambda value: value.lower())

                with self.cache_lock:
                    self.cached_lidarr_names = names
                    self.cached_cleaned_lidarr_names = [name.lower() for name in names]

                session.lidarr_items = [{"name": name, "checked": checked} for name in names]
                session.cleaned_lidarr_items = self._copy_cached_cleaned_names()
                status = "Success"
                data = session.lidarr_items
            else:
                status = "Error"
                data = response.text
            payload = {
                "Status": status,
                "Code": response.status_code if status == "Error" else None,
                "Data": data,
                "Running": session.running,
            }
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.error(f"Getting Artist Error: {exc}")
            payload = {
                "Status": "Error",
                "Code": 500,
                "Data": str(exc),
                "Running": session.running,
            }
        self.socketio.emit("lidarr_sidebar_update", payload, room=sid)

    # Discovery -------------------------------------------------------
    def start(self, sid: str, selected_artists: List[str]) -> None:
        session = self.ensure_session(sid)
        if not session.lidarr_items:
            cached = self._copy_cached_lidarr_items()
            if cached:
                session.lidarr_items = cached
                session.cleaned_lidarr_items = self._copy_cached_cleaned_names()
            else:
                self.get_artists_from_lidarr(sid)
                session = self.ensure_session(sid)
                if not session.lidarr_items:
                    return

        selection = set(selected_artists or [])
        session.prepare_for_search()
        session.artists_to_use_in_search = []

        for item in session.lidarr_items:
            is_selected = item["name"] in selection
            item["checked"] = is_selected
            if is_selected:
                session.artists_to_use_in_search.append(item["name"])

        if not session.artists_to_use_in_search:
            session.mark_stopped()
            payload = {
                "Status": "Error",
                "Code": "No Lidarr Artists Selected",
                "Data": session.lidarr_items,
                "Running": session.running,
            }
            self.socketio.emit("lidarr_sidebar_update", payload, room=sid)
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Selection required",
                    "message": "Choose at least one Lidarr artist to start.",
                },
                room=sid,
            )
            return

        self.socketio.emit("clear", room=sid)
        payload = {
            "Status": "Success",
            "Data": session.lidarr_items,
            "Running": session.running,
        }
        self.socketio.emit("lidarr_sidebar_update", payload, room=sid)

        self.prepare_similar_artist_candidates(session)
        with session.search_lock:
            self.load_similar_artist_batch(session, sid)

    def ai_prompt(self, sid: str, prompt: str) -> None:
        session = self.ensure_session(sid)
        user = self._resolve_user(session.user_id)
        prompt_text = (prompt or "").strip()
        if not prompt_text:
            self.socketio.emit(
                "ai_prompt_error",
                {
                    "message": "Describe what kind of music you're after so the AI assistant can help.",
                },
                room=sid,
            )
            return

        # Get recommender with user's API keys (or fallback to global)
        recommender = self.get_openai_recommender_for_user(user)
        if not recommender:
            self.socketio.emit(
                "ai_prompt_error",
                {
                    "message": "AI assistant isn't configured yet. Add an LLM API key in settings or your profile.",
                },
                room=sid,
            )
            return

        with self.cache_lock:
            library_artists = list(self.cached_lidarr_names)
            cleaned_library_names = set(self.cached_cleaned_lidarr_names)

        prompt_preview = prompt_text if len(prompt_text) <= 120 else f"{prompt_text[:117]}..."
        model_name = getattr(recommender, "model", "unknown")
        timeout_value = getattr(recommender, "timeout", None)
        self.logger.info(
            "AI prompt started (model=%s, timeout=%s, library_size=%d, prompt=\"%s\")",
            model_name,
            timeout_value,
            len(library_artists),
            prompt_preview,
        )

        start_time = time.perf_counter()
        try:
            seeds = recommender.generate_seed_artists(prompt_text, library_artists)
        except Exception as exc:  # pragma: no cover - network errors
            elapsed = time.perf_counter() - start_time
            self.logger.error("AI prompt failed after %.2fs: %s", elapsed, exc)
            message = "We couldn't reach the AI assistant. Please try again in a moment."
            if "timed out" in str(exc).lower():
                message = "The AI request timed out. Please try again or adjust the prompt."
            self.socketio.emit(
                "ai_prompt_error",
                {
                    "message": message,
                },
                room=sid,
            )
            return

        if not seeds:
            elapsed = time.perf_counter() - start_time
            self.logger.info("AI prompt completed in %.2fs but returned no artists", elapsed)
            self.socketio.emit(
                "ai_prompt_error",
                {
                    "message": "The AI couldn't suggest any artists from that request. Try adding genre or artist hints.",
                },
                room=sid,
            )
            return

        filtered_seeds: List[str] = []
        skipped_existing: List[str] = []
        for seed in seeds:
            normalized_seed = unidecode(seed).lower()
            if normalized_seed in cleaned_library_names:
                skipped_existing.append(seed)
                continue
            filtered_seeds.append(seed)

        if not filtered_seeds:
            elapsed = time.perf_counter() - start_time
            self.logger.info(
                "AI prompt completed in %.2fs but every seed matched an existing Lidarr artist", elapsed
            )
            self.socketio.emit(
                "ai_prompt_error",
                {
                    "message": "All suggested artists are already in your Lidarr library. Try a different prompt.",
                },
                room=sid,
            )
            return

        if skipped_existing:
            self.logger.info(
                "Filtered %d AI seed(s) already present in Lidarr: %s",
                len(skipped_existing),
                ", ".join(skipped_existing),
            )
            toast_message = (
                f"{len(skipped_existing)} AI suggestion(s) are already in your Lidarr library."
                if len(skipped_existing) > 1
                else f"{skipped_existing[0]} is already in your Lidarr library."
            )
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Skipping known artists",
                    "message": toast_message,
                },
                room=sid,
            )

        seeds = filtered_seeds

        elapsed = time.perf_counter() - start_time
        self.logger.info("AI prompt succeeded in %.2fs with %d seed artists", elapsed, len(seeds))

        session.prepare_for_search()
        success = self._stream_seed_artists(
            session,
            sid,
            seeds,
            ack_event="ai_prompt_ack",
            ack_payload={"seeds": seeds},
            error_event="ai_prompt_error",
            error_message="We couldn't load those artists from our data sources. Try refining your request.",
            missing_title="Missing artist data",
            missing_message="Some AI picks couldn't be fully loaded.",
            source_log_label="AI",
        )
        if not success:
            return

    def _fetch_lastfm_personal_artists(self, username: str) -> List[str]:
        if not self.last_fm_user_service:
            return []
        recommendations = self.last_fm_user_service.get_recommended_artists(username, limit=50)
        if not recommendations:
            recommendations = self.last_fm_user_service.get_top_artists(username, limit=50)
        return [artist.name for artist in recommendations if getattr(artist, "name", None)]

    def _fetch_listenbrainz_personal_artists(self, username: str) -> List[str]:
        if not self.listenbrainz_user_service:
            return []
        playlist_artists = self.listenbrainz_user_service.get_weekly_exploration_artists(username)
        names = playlist_artists.artists if playlist_artists else []
        return [name for name in names if name]

    def personal_recommendations(self, sid: str, source: str) -> None:
        session = self.ensure_session(sid)
        source_key = (source or "").strip().lower() or "lastfm"

        source_definitions = {
            "lastfm": {
                "label": "Last.fm",
                "title": "Last.fm discovery",
                "username_attr": "lastfm_username",
                "service_ready": bool(self.last_fm_user_service),
                "service_missing_reason": (
                    "Administrator must configure a Last.fm API key and secret in Settings before this feature can be used."
                ),
                "missing_username_reason": (
                    "Add your Last.fm username under Profile → Listening services to use this feature."
                ),
                "fetch": self._fetch_lastfm_personal_artists,
                "error_message": "We couldn't reach Last.fm right now. Please try again shortly.",
            },
            "listenbrainz": {
                "label": "ListenBrainz",
                "title": "ListenBrainz discovery",
                "username_attr": "listenbrainz_username",
                "service_ready": self.listenbrainz_user_service is not None,
                "service_missing_reason": "ListenBrainz integration is unavailable right now.",
                "missing_username_reason": (
                    "Add your ListenBrainz username under Profile → Listening services to use this feature."
                ),
                "fetch": self._fetch_listenbrainz_personal_artists,
                "error_message": "We couldn't reach ListenBrainz right now. Please try again shortly.",
            },
        }

        config = source_definitions.get(source_key)
        if not config:
            self._emit_personal_error(
                sid,
                source_key,
                "Unknown discovery source requested.",
                title="Personal discovery",
            )
            return

        user = self._resolve_user(session.user_id)
        if not user:
            self._emit_personal_error(
                sid,
                source_key,
                "You need to sign in again before requesting personal recommendations.",
                title=config["title"],
            )
            return

        if not config["service_ready"]:
            self._emit_personal_error(
                sid,
                source_key,
                config["service_missing_reason"],
                title=config["title"],
            )
            return

        username = (getattr(user, config["username_attr"], "") or "").strip()
        if not username:
            self._emit_personal_error(
                sid,
                source_key,
                config["missing_username_reason"],
                title=config["title"],
            )
            return

        start_time = time.perf_counter()
        source_label = config["label"]
        username_display = username

        try:
            seeds = config["fetch"](username)
        except ListenBrainzIntegrationError as exc:  # pragma: no cover - network errors
            self.logger.error("Failed to load ListenBrainz picks for %s: %s", username, exc)
            self._emit_personal_error(
                sid,
                source_key,
                config["error_message"],
                title=config["title"],
            )
            return
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.error("Failed to load %s recommendations for %s: %s", source_label, username, exc)
            self._emit_personal_error(
                sid,
                source_key,
                config["error_message"],
                title=config["title"],
            )
            return

        elapsed = time.perf_counter() - start_time
        self.logger.info(
            "%s personal recommendations fetched for user %s in %.2fs (raw=%d)",
            source_label,
            user.username,
            elapsed,
            len(seeds),
        )

        seeds = self._dedupe_names(seeds)
        if not seeds:
            self._emit_personal_error(
                sid,
                source_key,
                f"{source_label} didn't return any usable artists for your profile.",
                title=config["title"],
            )
            return

        if not session.cleaned_lidarr_items:
            cleaned = self._copy_cached_cleaned_names()
            if not cleaned:
                try:
                    self.get_artists_from_lidarr(sid)
                    cleaned = self._copy_cached_cleaned_names()
                except Exception:  # pragma: no cover - network errors
                    cleaned = []
            session.cleaned_lidarr_items = cleaned
        cleaned_library_names = set(session.cleaned_lidarr_items)

        skipped_existing: List[str] = []
        filtered_seeds: List[str] = []
        for seed in seeds:
            normalized_seed = unidecode(seed).lower()
            if normalized_seed in cleaned_library_names:
                skipped_existing.append(seed)
                continue
            filtered_seeds.append(seed)

        if not filtered_seeds:
            self.logger.info(
                "%s personal recommendations matched existing Lidarr artists for user %s",
                source_label,
                user.username,
            )
            self.socketio.emit(
                "user_recs_ack",
                {
                    "source": source_key,
                    "username": username_display,
                    "seeds": [],
                    "skipped": skipped_existing,
                },
                room=sid,
            )
            self._emit_personal_error(
                sid,
                source_key,
                "All recommended artists are already in your Lidarr library.",
                title=config["title"],
            )
            session.mark_stopped()
            self.socketio.emit(
                "lidarr_sidebar_update",
                {
                    "Status": "Success",
                    "Data": session.lidarr_items,
                    "Running": session.running,
                },
                room=sid,
            )
            return

        if skipped_existing:
            toast_message = (
                f"{len(skipped_existing)} {source_label} recommendation(s) are already in your Lidarr library."
                if len(skipped_existing) > 1
                else f"{skipped_existing[0]} is already in your Lidarr library."
            )
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Skipping known artists",
                    "message": toast_message,
                },
                room=sid,
            )

        session.prepare_for_search()
        success = self._stream_seed_artists(
            session,
            sid,
            filtered_seeds,
            ack_event="user_recs_ack",
            ack_payload={
                "source": source_key,
                "username": username_display,
                "seeds": filtered_seeds,
                "skipped": skipped_existing,
            },
            error_event="user_recs_error",
            error_message=(
                f"We couldn't load personalised {source_label} picks right now. Please try again later."
            ),
            missing_title=f"{source_label} data",
            missing_message=f"Some {source_label} picks couldn't be fully loaded.",
            source_log_label=source_label,
        )
        if not success:
            return

        self.emit_personal_sources_state(sid)

        self.socketio.emit(
            "lidarr_sidebar_update",
            {
                "Status": "Success",
                "Data": session.lidarr_items,
                "Running": session.running,
            },
            room=sid,
        )

    def stop(self, sid: str) -> None:
        session = self.ensure_session(sid)
        session.mark_stopped()
        payload = {
            "Status": "Success",
            "Data": session.lidarr_items,
            "Running": session.running,
        }
        self.socketio.emit("lidarr_sidebar_update", payload, room=sid)

    def prepare_similar_artist_candidates(self, session: SessionState) -> None:
        session.similar_artist_candidates = []
        session.similar_artist_batch_pointer = 0
        session.initial_batch_sent = False

        lfm = pylast.LastFMNetwork(
            api_key=self.last_fm_api_key,
            api_secret=self.last_fm_api_secret,
        )

        seen_candidates = set()
        seed_names = {unidecode(name).lower() for name in session.ai_seed_artists}
        for artist_name in session.artists_to_use_in_search:
            try:
                chosen_artist = lfm.get_artist(artist_name)
                related_artists = chosen_artist.get_similar()
                for related_artist in related_artists:
                    cleaned_artist = unidecode(related_artist.item.name).lower()
                    if (
                        cleaned_artist in session.cleaned_lidarr_items
                        or cleaned_artist in seen_candidates
                        or cleaned_artist in seed_names
                    ):
                        continue
                    seen_candidates.add(cleaned_artist)
                    raw_match = getattr(related_artist, "match", None)
                    try:
                        match_score = float(raw_match) if raw_match is not None else None
                    except (TypeError, ValueError):
                        match_score = None
                    session.similar_artist_candidates.append(
                        {
                            "artist": related_artist,
                            "match": match_score,
                        }
                    )
            except Exception:
                continue
            if len(session.similar_artist_candidates) >= 500:
                break

        def sort_key(item):
            match_value = item["match"] if item["match"] is not None else -1.0
            return (-match_value, unidecode(item["artist"].item.name).lower())

        session.similar_artist_candidates.sort(key=sort_key)

    def load_similar_artist_batch(self, session: SessionState, sid: str) -> None:
        if session.stop_event.is_set():
            session.mark_stopped()
            return

        batch_size = max(1, int(self.similar_artist_batch_size))
        batch_start = session.similar_artist_batch_pointer
        batch_end = batch_start + batch_size
        batch = session.similar_artist_candidates[batch_start:batch_end]

        if not batch:
            session.mark_stopped()
            self.socketio.emit("load_more_complete", {"hasMore": False}, room=sid)
            return

        lfm_network = pylast.LastFMNetwork(
            api_key=self.last_fm_api_key,
            api_secret=self.last_fm_api_secret,
        )

        existing_names = {unidecode(item["Name"]).lower() for item in session.recommended_artists}

        for candidate in batch:
            if session.stop_event.is_set():
                break
            related_artist = candidate["artist"]
            similarity_score = candidate.get("match")
            artist_name = related_artist.item.name
            normalized = unidecode(artist_name).lower()
            if normalized in existing_names:
                continue
            try:
                artist_payload = self._fetch_artist_payload(
                    lfm_network,
                    artist_name,
                    similarity_score=similarity_score,
                )
            except Exception as exc:  # pragma: no cover - network errors
                self.logger.error("Error building payload for %s: %s", artist_name, exc)
                continue

            if not artist_payload:
                self.logger.error("Artist payload missing for %s", artist_name)
                continue

            session.recommended_artists.append(artist_payload)
            existing_names.add(normalized)
            self.socketio.emit("more_artists_loaded", [artist_payload], room=sid)

        session.similar_artist_batch_pointer += len(batch)
        has_more = session.similar_artist_batch_pointer < len(session.similar_artist_candidates)
        event_name = "initial_load_complete" if not session.initial_batch_sent else "load_more_complete"
        self.socketio.emit(event_name, {"hasMore": has_more}, room=sid)
        session.initial_batch_sent = True
        if not has_more:
            session.mark_stopped()

    def find_similar_artists(self, sid: str) -> None:
        session = self.ensure_session(sid)
        if session.stop_event.is_set():
            return
        with session.search_lock:
            if session.stop_event.is_set():
                return
            if session.similar_artist_batch_pointer < len(session.similar_artist_candidates):
                self.load_similar_artist_batch(session, sid)
            else:
                self.socketio.emit(
                    "new_toast_msg",
                    {
                        "title": "No More Artists",
                        "message": "No more similar artists to load.",
                    },
                    room=sid,
                )
                session.mark_stopped()

    # Lidarr artist creation ------------------------------------------
    def add_artists(self, sid: str, raw_artist_name: str) -> str:
        session = self.ensure_session(sid)
        artist_name = urllib.parse.unquote(raw_artist_name)
        artist_folder = artist_name.replace("/", " ")
        status = "Failed to Add"

        try:
            musicbrainzngs.set_useragent(self.app_name, self.app_rev, self.app_url)
            mbid = self.get_mbid_from_musicbrainz(artist_name)

            if mbid:
                lidarr_url = f"{self.lidarr_address}/api/v1/artist"
                headers = {"X-Api-Key": self.lidarr_api_key}
                monitored_flag = bool(self.lidarr_monitored)
                add_options: dict[str, Any] = {
                    "searchForMissingAlbums": bool(self.search_for_missing_albums),
                    "monitored": monitored_flag,
                }
                if self.lidarr_monitor_option:
                    add_options["monitor"] = self.lidarr_monitor_option
                if self.lidarr_albums_to_monitor:
                    add_options["albumsToMonitor"] = list(self.lidarr_albums_to_monitor)
                payload = {
                    "ArtistName": artist_name,
                    "qualityProfileId": self.quality_profile_id,
                    "metadataProfileId": self.metadata_profile_id,
                    "path": os.path.join(self.root_folder_path, artist_folder, ""),
                    "rootFolderPath": self.root_folder_path,
                    "foreignArtistId": mbid,
                    "monitored": monitored_flag,
                    "addOptions": add_options,
                }
                if self.lidarr_monitor_new_items:
                    payload["monitorNewItems"] = self.lidarr_monitor_new_items

                if self.dry_run_adding_to_lidarr:
                    response = None
                    response_status = 201
                else:
                    response = requests.post(
                        lidarr_url,
                        headers=headers,
                        json=payload,
                        timeout=self.lidarr_api_timeout,
                    )
                    response_status = response.status_code

                if response_status == 201:
                    self.logger.info("Artist '%s' added successfully to Lidarr.", artist_name)
                    status = "Added"
                    session.lidarr_items.append({"name": artist_name, "checked": False})
                    session.cleaned_lidarr_items.append(unidecode(artist_name).lower())
                    with self.cache_lock:
                        if artist_name not in self.cached_lidarr_names:
                            self.cached_lidarr_names.append(artist_name)
                            self.cached_cleaned_lidarr_names.append(unidecode(artist_name).lower())
                else:
                    if self.dry_run_adding_to_lidarr:
                        response_body = "Dry-run mode: no request sent."
                        error_payload = None
                    elif response is not None:
                        response_body = response.text.strip()
                        try:
                            error_payload = response.json()
                        except ValueError:
                            error_payload = None
                    else:
                        response_body = "No response object returned."
                        error_payload = None

                    self.logger.error(
                        "Failed to add artist '%s' to Lidarr (status=%s). Body: %s",
                        artist_name,
                        response_status,
                        response_body,
                    )
                    if error_payload is not None:
                        self.logger.error("Lidarr error payload: %s", error_payload)

                    if isinstance(error_payload, list) and error_payload:
                        error_message = error_payload[0].get("errorMessage", "No Error Message Returned")
                    elif isinstance(error_payload, dict):
                        error_message = (
                            error_payload.get("errorMessage")
                            or error_payload.get("message")
                            or "No Error Message Returned"
                        )
                    else:
                        error_message = response_body or "Error Unknown"

                    self.logger.error("Lidarr error message: %s", error_message)

                    if "already been added" in error_message or "configured for an existing artist" in error_message:
                        status = "Already in Lidarr"
                    elif "Invalid Path" in error_message:
                        status = "Invalid Path"
                        self.logger.info(
                            "Path '%s' reported invalid by Lidarr.",
                            os.path.join(self.root_folder_path, artist_folder, ""),
                        )
                    else:
                        status = "Failed to Add"
            else:
                self.logger.warning(
                    "No MusicBrainz match found for '%s'; cannot add to Lidarr.", artist_name
                )
                self.socketio.emit(
                    "new_toast_msg",
                    {
                        "title": "Failed to add Artist",
                        "message": f"No Matching Artist for: '{artist_name}' in MusicBrainz.",
                    },
                    room=sid,
                )

        except Exception as exc:  # pragma: no cover - network errors
            self.logger.exception("Unexpected error while adding '%s' to Lidarr", artist_name)
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Failed to add Artist",
                    "message": f"Error adding '{artist_name}': {exc}",
                },
                room=sid,
            )
        finally:
            for item in session.recommended_artists:
                if item["Name"] == artist_name:
                    item["Status"] = status
                    self.socketio.emit("refresh_artist", item, room=sid)
                    break

        return status

    def request_artist(self, sid: str, raw_artist_name: str) -> None:
        session = self.ensure_session(sid)
        if not session.user_id:
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Authentication Error",
                    "message": "You must be logged in to request artists.",
                },
                room=sid,
            )
            return
        
        artist_name = urllib.parse.unquote(raw_artist_name)

        try:
            if self._flask_app is not None:
                with self._flask_app.app_context():
                    self._request_artist_db_operations(sid, artist_name, session)
            else:
                # Fallback: rely on current app context if already present
                self._request_artist_db_operations(sid, artist_name, session)
        except Exception as exc:
            self.logger.exception("Unexpected error while requesting '%s'", artist_name)
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Failed to Request Artist",
                    "message": f"Error requesting '{artist_name}': {exc}",
                },
                room=sid,
            )
        finally:
            # Update the artist status in the UI
            for item in session.recommended_artists:
                if item["Name"] == artist_name:
                    item["Status"] = "Requested"
                    self.socketio.emit("refresh_artist", item, room=sid)
                    break

    def _request_artist_db_operations(self, sid: str, artist_name: str, session) -> None:
        # Check if request already exists
        existing_request = ArtistRequest.query.filter_by(
            artist_name=artist_name,
            requested_by_id=session.user_id,
            status="pending",
        ).first()

        if existing_request:
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": "Request Already Exists",
                    "message": f"You have already requested '{artist_name}'.",
                },
                room=sid,
            )
            return

        # Create new request
        request = ArtistRequest(
            artist_name=artist_name,
            requested_by_id=session.user_id,
            status="pending",
        )

        db.session.add(request)
        db.session.commit()

        self.logger.info("Artist '%s' requested by user %s.", artist_name, session.user_id)

        self.socketio.emit(
            "new_toast_msg",
            {
                "title": "Request Submitted",
                "message": f"Request for '{artist_name}' has been submitted for approval.",
            },
            room=sid,
        )

    # Settings --------------------------------------------------------
    def load_settings(self, sid: str) -> None:
        try:
            data = {
                "lidarr_address": self.lidarr_address,
                "lidarr_api_key": self.lidarr_api_key,
                "root_folder_path": self.root_folder_path,
                "youtube_api_key": self.youtube_api_key,
                "quality_profile_id": self.quality_profile_id,
                "metadata_profile_id": self.metadata_profile_id,
                "lidarr_api_timeout": self.lidarr_api_timeout,
                "fallback_to_top_result": self.fallback_to_top_result,
                "search_for_missing_albums": self.search_for_missing_albums,
                "dry_run_adding_to_lidarr": self.dry_run_adding_to_lidarr,
                "lidarr_monitor_option": self.lidarr_monitor_option,
                "lidarr_monitored": self.lidarr_monitored,
                "lidarr_monitor_new_items": self.lidarr_monitor_new_items,
                "lidarr_albums_to_monitor": "\n".join(self.lidarr_albums_to_monitor) if self.lidarr_albums_to_monitor else "",
                "last_fm_api_key": self.last_fm_api_key,
                "last_fm_api_secret": self.last_fm_api_secret,
                "auto_start": self.auto_start,
                "auto_start_delay": self.auto_start_delay,
                "openai_api_key": self.openai_api_key,
                "openai_model": self.openai_model,
                "openai_api_base": self.openai_api_base,
                "openai_extra_headers": self.openai_extra_headers,
                "openai_max_seed_artists": self.openai_max_seed_artists,
                "api_key": self.api_key,
            }
            self.socketio.emit("settingsLoaded", data, room=sid)
        except Exception as exc:
            self.logger.error(f"Failed to load settings: {exc}")

    def update_settings(self, data: dict) -> None:
        try:
            self._apply_string_settings(data)
            self._apply_int_settings(data)
            self._apply_float_settings(data)
            self._apply_bool_settings(data)
            self.openai_extra_headers = self._normalize_openai_headers_field(
                self.openai_extra_headers
            )

            if "lidarr_monitor_option" in data:
                self.lidarr_monitor_option = self._normalize_monitor_option(data.get("lidarr_monitor_option"))

            if "lidarr_monitor_new_items" in data:
                self.lidarr_monitor_new_items = self._normalize_monitor_new_items(
                    data.get("lidarr_monitor_new_items")
                )

            if "lidarr_albums_to_monitor" in data:
                self.lidarr_albums_to_monitor = self._parse_albums_to_monitor(
                    data.get("lidarr_albums_to_monitor")
                )

            if self.similar_artist_batch_size <= 0:
                self.similar_artist_batch_size = 1
            if self.openai_max_seed_artists <= 0:
                self.openai_max_seed_artists = DEFAULT_MAX_SEED_ARTISTS
            if self.auto_start_delay < 0:
                self.auto_start_delay = 0

            # Update Flask app config with API_KEY
            if self._flask_app:
                self._flask_app.config['API_KEY'] = self.api_key

            self._configure_openai_client()
            self._configure_listening_services()
            self.save_config_to_file()
            self.broadcast_personal_sources_state()
        except Exception as exc:
            self.logger.error(f"Failed to update settings: {exc}")

    # Preview ---------------------------------------------------------
    def preview(self, sid: str, raw_artist_name: str) -> None:
        artist_name = urllib.parse.unquote(raw_artist_name)
        session = self.ensure_session(sid)
        user = self._resolve_user(session.user_id)
        try:
            preview_info: dict | str
            biography = None
            lfm = pylast.LastFMNetwork(
                api_key=self.get_lastfm_api_key(user),
                api_secret=self.get_lastfm_api_secret(user),
            )
            search_results = lfm.search_for_artist(artist_name)
            artists = search_results.get_next_page()
            cleaned_artist_name = unidecode(artist_name).lower()
            for artist_obj in artists:
                match_ratio = fuzz.ratio(cleaned_artist_name, artist_obj.name.lower())
                decoded_match_ratio = fuzz.ratio(
                    unidecode(cleaned_artist_name), unidecode(artist_obj.name.lower())
                )
                if match_ratio > 90 or decoded_match_ratio > 90:
                    biography = artist_obj.get_bio_content()
                    preview_info = {
                        "artist_name": artist_obj.name,
                        "biography": biography,
                    }
                    break
            else:
                preview_info = f"No Artist match for: {artist_name}"
                self.logger.error(preview_info)

            if biography is None:
                preview_info = f"No Biography available for: {artist_name}"
                self.logger.error(preview_info)

        except Exception as exc:
            preview_info = {"error": f"Error retrieving artist bio: {exc}"}
            self.logger.error(preview_info)

        self.socketio.emit("lastfm_preview", preview_info, room=sid)

    def prehear(self, sid: str, raw_artist_name: str) -> None:
        artist_name = urllib.parse.unquote(raw_artist_name)
        session = self.ensure_session(sid)
        user = self._resolve_user(session.user_id)
        lfm = pylast.LastFMNetwork(
            api_key=self.get_lastfm_api_key(user),
            api_secret=self.get_lastfm_api_secret(user),
        )
        yt_key = (self.get_youtube_api_key(user) or "").strip()
        result: dict[str, str] = {"error": "No sample found"}
        top_tracks = []
        try:
            artist = lfm.get_artist(artist_name)
            top_tracks = artist.get_top_tracks(limit=10)
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.error(f"LastFM error: {exc}")

        def attempt_youtube(track_name: str) -> Optional[dict[str, str]]:
            if not yt_key:
                return None
            query = f"{artist_name} {track_name}"
            yt_url = (
                "https://www.googleapis.com/youtube/v3/search?part=snippet"
                f"&q={requests.utils.quote(query)}&key={yt_key}&type=video&maxResults=1"
            )
            try:
                yt_resp = requests.get(yt_url, timeout=10)
                yt_resp.raise_for_status()
            except Exception as exc:  # pragma: no cover - network errors
                self.logger.error(f"YouTube search failed: {exc}")
                return None
            yt_items = yt_resp.json().get("items", [])
            if not yt_items:
                return None
            video_id = yt_items[0]["id"]["videoId"]
            return {
                "videoId": video_id,
                "track": track_name,
                "artist": artist_name,
                "source": "youtube",
            }

        def attempt_itunes(track_name: Optional[str]) -> Optional[dict[str, str]]:
            search_term = f"{artist_name} {track_name}" if track_name else artist_name
            params = {
                "term": search_term,
                "entity": "musicTrack",
                "limit": 5,
                "media": "music",
            }
            try:
                resp = requests.get("https://itunes.apple.com/search", params=params, timeout=10)
                resp.raise_for_status()
            except Exception as exc:  # pragma: no cover - network errors
                self.logger.error(f"iTunes lookup failed: {exc}")
                return None
            for entry in resp.json().get("results", []):
                preview_url = entry.get("previewUrl")
                if not preview_url:
                    continue
                return {
                    "previewUrl": preview_url,
                    "track": entry.get("trackName") or (track_name or artist_name),
                    "artist": entry.get("artistName") or artist_name,
                    "source": "itunes",
                }
            return None

        try:
            if yt_key:
                for track in top_tracks:
                    track_name = track.item.title
                    candidate = attempt_youtube(track_name)
                    if candidate:
                        result = candidate
                        break
                    time.sleep(0.2)

            if isinstance(result, dict) and not result.get("previewUrl") and not result.get("videoId"):
                for track in top_tracks:
                    track_name = track.item.title
                    candidate = attempt_itunes(track_name)
                    if candidate:
                        result = candidate
                        break

            if isinstance(result, dict) and not result.get("previewUrl") and not result.get("videoId"):
                fallback_candidate = attempt_itunes(None)
                if fallback_candidate:
                    result = fallback_candidate
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.error(f"Prehear error: {exc}")
            result = {"error": str(exc)}

        self.socketio.emit("prehear_result", result, room=sid)

    # Utilities -------------------------------------------------------
    def _fetch_artist_payload(
        self,
        lfm_network: pylast.LastFMNetwork,
        artist_name: str,
        *,
        similarity_score: Optional[float] = None,
    ) -> Optional[dict]:
        try:
            artist_obj = lfm_network.get_artist(artist_name)
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.error("Failed to load artist '%s' from Last.fm: %s", artist_name, exc)
            return None

        try:
            tags = [tag.item.get_name().title() for tag in artist_obj.get_top_tags()[:5]]
        except Exception:
            tags = []
        genres = ", ".join(tags) or "Unknown Genre"

        try:
            listeners = artist_obj.get_listener_count() or 0
        except Exception:
            listeners = 0

        try:
            play_count = artist_obj.get_playcount() or 0
        except Exception:
            play_count = 0

        img_link = None
        try:
            endpoint = "https://api.deezer.com/search/artist"
            params = {"q": artist_name}
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("data"):
                artist_info = data["data"][0]
                img_link = (
                    artist_info.get("picture_xl")
                    or artist_info.get("picture_large")
                    or artist_info.get("picture_medium")
                    or artist_info.get("picture")
                )
        except Exception:
            img_link = None

        similarity_label = None
        clamped_similarity = None
        if similarity_score is not None:
            clamped_similarity = max(0.0, min(1.0, similarity_score))
            similarity_label = f"Similarity: {clamped_similarity * 100:.1f}%"

        display_name = artist_name
        try:
            if hasattr(artist_obj, "get_name"):
                display_name = artist_obj.get_name() or artist_name
            elif hasattr(artist_obj, "name"):
                display_name = artist_obj.name or artist_name
        except Exception:
            display_name = artist_name

        return {
            "Name": display_name,
            "Genre": genres,
            "Status": "",
            "Img_Link": img_link or "https://placehold.co/512x512?text=No+Image",
            "Popularity": f"Play Count: {self.format_numbers(play_count)}",
            "Followers": f"Listeners: {self.format_numbers(listeners)}",
            "SimilarityScore": clamped_similarity,
            "Similarity": similarity_label,
        }

    def _iter_artist_payloads_from_names(
        self,
        names: Sequence[str],
        *,
        missing: Optional[List[str]] = None,
    ) -> Iterable[dict]:
        if not names:
            return []

        lfm_network = pylast.LastFMNetwork(
            api_key=self.last_fm_api_key,
            api_secret=self.last_fm_api_secret,
        )

        seen: set[str] = set()

        for raw_name in names:
            if not raw_name:
                continue
            normalized = unidecode(raw_name).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            payload = self._fetch_artist_payload(lfm_network, raw_name)
            if payload:
                yield payload
            elif missing is not None:
                missing.append(raw_name)

    def _stream_seed_artists(
        self,
        session: SessionState,
        sid: str,
        seeds: Sequence[str],
        *,
        ack_event: str,
        ack_payload: Dict[str, Any],
        error_event: str,
        error_message: str,
        missing_title: str,
        missing_message: str,
        source_log_label: str,
    ) -> bool:
        if not session.lidarr_items:
            session.lidarr_items = self._copy_cached_lidarr_items()
        if not session.cleaned_lidarr_items:
            session.cleaned_lidarr_items = self._copy_cached_cleaned_names()

        session.artists_to_use_in_search = list(seeds)
        session.ai_seed_artists = list(seeds)

        self.socketio.emit(ack_event, ack_payload, room=sid)
        self.socketio.emit("clear", room=sid)
        self.socketio.emit(
            "lidarr_sidebar_update",
            {
                "Status": "Success",
                "Data": session.lidarr_items,
                "Running": session.running,
            },
            room=sid,
        )

        existing_names = {unidecode(item["Name"]).lower() for item in session.recommended_artists}
        missing_names: List[str] = []
        streamed_any = False

        for payload in self._iter_artist_payloads_from_names(seeds, missing=missing_names):
            normalized = unidecode(payload["Name"]).lower()
            if normalized in existing_names:
                continue
            session.recommended_artists.append(payload)
            existing_names.add(normalized)
            streamed_any = True
            self.socketio.emit("more_artists_loaded", [payload], room=sid)

        if not streamed_any:
            self.logger.error("Failed to build artist cards for %s seeds: %s", source_log_label, list(seeds))
            self.socketio.emit(error_event, {"message": error_message}, room=sid)
            session.running = False
            self.socketio.emit(
                "lidarr_sidebar_update",
                {
                    "Status": "Success",
                    "Data": session.lidarr_items,
                    "Running": session.running,
                },
                room=sid,
            )
            return False

        if missing_names:
            self.logger.warning(
                "%s seeds missing metadata: %s",
                source_log_label,
                ", ".join(missing_names),
            )
            self.socketio.emit(
                "new_toast_msg",
                {
                    "title": missing_title,
                    "message": missing_message,
                },
                room=sid,
            )

        self.prepare_similar_artist_candidates(session)
        has_more = bool(session.similar_artist_candidates)
        session.initial_batch_sent = True
        session.running = False
        self.socketio.emit("initial_load_complete", {"hasMore": has_more}, room=sid)
        return True

    def _normalize_openai_headers_field(self, value: Any) -> str:
        if isinstance(value, dict):
            try:
                return json.dumps(value)
            except (TypeError, ValueError):
                self.logger.warning("Failed to serialize custom LLM headers; expected JSON-compatible data.")
                return ""
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        return str(value)

    def _parse_openai_extra_headers(self) -> Dict[str, str]:
        raw_value = getattr(self, "openai_extra_headers", "")
        if not raw_value:
            return {}

        if isinstance(raw_value, dict):
            items = raw_value.items()
        else:
            raw_text = raw_value.strip() if isinstance(raw_value, str) else str(raw_value).strip()
            if not raw_text:
                return {}
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                self.logger.warning("Ignoring LLM headers override; expected valid JSON object.")
                return {}
            if not isinstance(parsed, dict):
                self.logger.warning("Ignoring LLM headers override; JSON must represent an object.")
                return {}
            items = parsed.items()

        headers: Dict[str, str] = {}
        for key, value in items:
            key_str = str(key).strip()
            if not key_str or value is None:
                continue
            headers[key_str] = str(value)
        return headers

    def _configure_openai_client(self) -> None:
        api_key = (self.openai_api_key or "").strip()
        base_url = (self.openai_api_base or "").strip()
        env_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not any([api_key, base_url, env_api_key]):
            self.openai_recommender = None
            return

        model = (self.openai_model or "").strip() or None
        max_seeds = self.openai_max_seed_artists
        try:
            max_seeds_int = int(max_seeds)
        except (TypeError, ValueError):
            max_seeds_int = DEFAULT_MAX_SEED_ARTISTS
        if max_seeds_int <= 0:
            max_seeds_int = DEFAULT_MAX_SEED_ARTISTS
        self.openai_max_seed_artists = max_seeds_int

        headers_override = self._parse_openai_extra_headers()

        try:
            self.openai_recommender = OpenAIRecommender(
                api_key=api_key or None,
                model=model,
                base_url=base_url or None,
                default_headers=headers_override or None,
                max_seed_artists=max_seeds_int,
            )
        except Exception as exc:  # pragma: no cover - network/config errors
            self.logger.error("Failed to initialize LLM client: %s", exc)
            self.openai_recommender = None

    def _configure_listening_services(self) -> None:
        lastfm_key = (getattr(self, "last_fm_api_key", "") or "").strip()
        lastfm_secret = (getattr(self, "last_fm_api_secret", "") or "").strip()
        if lastfm_key and lastfm_secret:
            self.last_fm_user_service = LastFmUserService(lastfm_key, lastfm_secret)
        else:
            self.last_fm_user_service = None

    def format_numbers(self, count: int) -> str:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    def save_config_to_file(self) -> None:
        tmp_path: Optional[Path] = None
        try:
            self.settings_config_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "lidarr_address": self.lidarr_address,
                "lidarr_api_key": self.lidarr_api_key,
                "root_folder_path": self.root_folder_path,
                "fallback_to_top_result": self.fallback_to_top_result,
                "lidarr_api_timeout": float(self.lidarr_api_timeout),
                "quality_profile_id": self.quality_profile_id,
                "metadata_profile_id": self.metadata_profile_id,
                "search_for_missing_albums": self.search_for_missing_albums,
                "dry_run_adding_to_lidarr": self.dry_run_adding_to_lidarr,
                "lidarr_monitor_option": self.lidarr_monitor_option,
                "lidarr_monitored": self.lidarr_monitored,
                "lidarr_albums_to_monitor": self.lidarr_albums_to_monitor,
                "lidarr_monitor_new_items": self.lidarr_monitor_new_items,
                "app_name": self.app_name,
                "app_rev": self.app_rev,
                "app_url": self.app_url,
                "last_fm_api_key": self.last_fm_api_key,
                "last_fm_api_secret": self.last_fm_api_secret,
                "auto_start": self.auto_start,
                "auto_start_delay": self.auto_start_delay,
                "youtube_api_key": self.youtube_api_key,
                "similar_artist_batch_size": self.similar_artist_batch_size,
                "openai_api_key": self.openai_api_key,
                "openai_model": self.openai_model,
                "openai_api_base": self.openai_api_base,
                "openai_extra_headers": self.openai_extra_headers,
                "openai_max_seed_artists": self.openai_max_seed_artists,
                "api_key": self.api_key,
            }

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.settings_config_file.parent,
                delete=False,
            ) as tmp_file:
                json.dump(payload, tmp_file, indent=4)
                tmp_file.flush()
                os.fchmod(tmp_file.fileno(), 0o600)
                os.fsync(tmp_file.fileno())
                tmp_path = Path(tmp_file.name)

            os.replace(tmp_path, self.settings_config_file)
            os.chmod(self.settings_config_file, 0o600)
        except Exception as exc:  # pragma: no cover - filesystem errors
            self.logger.error(f"Error Saving Config: {exc}")
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def get_mbid_from_musicbrainz(self, artist_name: str) -> Optional[str]:
        result = musicbrainzngs.search_artists(artist=artist_name)
        mbid = None

        if "artist-list" in result:
            artists = result["artist-list"]

            for artist in artists:
                match_ratio = fuzz.ratio(artist_name.lower(), artist["name"].lower())
                decoded_match_ratio = fuzz.ratio(
                    unidecode(artist_name.lower()),
                    unidecode(artist["name"].lower()),
                )
                if match_ratio > 90 or decoded_match_ratio > 90:
                    mbid = artist["id"]
                    self.logger.info(
                        "Artist '%s' matched '%s' with MBID: %s",
                        artist_name,
                        artist["name"],
                        mbid,
                    )
                    break
            else:
                if self.fallback_to_top_result and artists:
                    mbid = artists[0]["id"]
                    self.logger.info(
                        "Artist '%s' matched '%s' with MBID: %s",
                        artist_name,
                        artists[0]["name"],
                        mbid,
                    )

        return mbid

    def load_environ_or_config_settings(self) -> None:
        default_settings = {
            "lidarr_address": "",
            "lidarr_api_key": "",
            "root_folder_path": "/data/media/music/",
            "fallback_to_top_result": False,
            "lidarr_api_timeout": 120.0,
            "quality_profile_id": 1,
            "metadata_profile_id": 1,
            "search_for_missing_albums": False,
            "dry_run_adding_to_lidarr": False,
            "lidarr_monitor_option": "",
            "lidarr_monitored": True,
            "lidarr_albums_to_monitor": [],
            "lidarr_monitor_new_items": "",
            "app_name": "Sonobarr",
            "app_rev": "0.10",
            "app_url": "https://" + "".join(random.choices(string.ascii_lowercase, k=10)) + ".com",  # NOSONAR(S2245)
            "last_fm_api_key": "",
            "last_fm_api_secret": "",
            "auto_start": False,
            "auto_start_delay": 60,
            "youtube_api_key": "",
            "similar_artist_batch_size": 10,
            "openai_api_key": "",
            "openai_model": "",
            "openai_api_base": "",
            "openai_extra_headers": "",
            "openai_max_seed_artists": DEFAULT_MAX_SEED_ARTISTS,
            "api_key": "",
            "sonobarr_superadmin_username": "admin",
            "sonobarr_superadmin_password": "",
            "sonobarr_superadmin_display_name": "Super Admin",
            "sonobarr_superadmin_reset": "false",
        }

        self.lidarr_address = self._env("lidarr_address")
        self.lidarr_api_key = self._env("lidarr_api_key")
        self.youtube_api_key = self._env("youtube_api_key")
        self.root_folder_path = self._env("root_folder_path")

        fallback_to_top_result = self._env("fallback_to_top_result")
        self.fallback_to_top_result = (
            fallback_to_top_result.lower() == "true" if fallback_to_top_result != "" else ""
        )

        lidarr_api_timeout = self._env("lidarr_api_timeout")
        self.lidarr_api_timeout = float(lidarr_api_timeout) if lidarr_api_timeout else ""

        quality_profile_id = self._env("quality_profile_id")
        self.quality_profile_id = int(quality_profile_id) if quality_profile_id else ""

        metadata_profile_id = self._env("metadata_profile_id")
        self.metadata_profile_id = int(metadata_profile_id) if metadata_profile_id else ""

        search_for_missing_albums = self._env("search_for_missing_albums")
        self.search_for_missing_albums = (
            search_for_missing_albums.lower() == "true" if search_for_missing_albums != "" else ""
        )

        dry_run_adding_to_lidarr = self._env("dry_run_adding_to_lidarr")
        self.dry_run_adding_to_lidarr = (
            dry_run_adding_to_lidarr.lower() == "true" if dry_run_adding_to_lidarr != "" else ""
        )

        monitor_option_env = self._env("lidarr_monitor_option")
        self.lidarr_monitor_option = (
            self._normalize_monitor_option(monitor_option_env) if monitor_option_env else ""
        )

        monitor_new_items_env = self._env("lidarr_monitor_new_items")
        self.lidarr_monitor_new_items = (
            self._normalize_monitor_new_items(monitor_new_items_env) if monitor_new_items_env else ""
        )

        monitored_env = self._env("lidarr_monitored")
        if monitored_env == "":
            self.lidarr_monitored = ""
        else:
            monitored_bool = self._coerce_bool(monitored_env)
            self.lidarr_monitored = monitored_bool if monitored_bool is not None else ""

        albums_env = self._env("lidarr_albums_to_monitor")
        self.lidarr_albums_to_monitor = (
            self._parse_albums_to_monitor(albums_env) if albums_env else ""
        )

        self.app_name = self._env("app_name")
        self.app_rev = self._env("app_rev")
        self.app_url = self._env("app_url")
        self.last_fm_api_key = self._env("last_fm_api_key")
        self.last_fm_api_secret = self._env("last_fm_api_secret")
        self.openai_api_key = self._env("openai_api_key")
        self.openai_model = self._env("openai_model")
        self.openai_api_base = self._env("openai_api_base")
        self.openai_extra_headers = self._env("openai_extra_headers")
        openai_max_seed = self._env("openai_max_seed_artists")
        self.openai_max_seed_artists = int(openai_max_seed) if openai_max_seed else ""
        self.api_key = self._env("api_key")

        auto_start = self._env("auto_start")
        self.auto_start = auto_start.lower() == "true" if auto_start != "" else ""

        auto_start_delay = self._env("auto_start_delay")
        self.auto_start_delay = float(auto_start_delay) if auto_start_delay else ""

        similar_artist_batch_size = self._env("similar_artist_batch_size")
        if similar_artist_batch_size:
            self.similar_artist_batch_size = similar_artist_batch_size

        superadmin_username = self._env("sonobarr_superadmin_username")
        superadmin_password = self._env("sonobarr_superadmin_password")
        superadmin_display_name = self._env("sonobarr_superadmin_display_name")
        superadmin_reset = self._env("sonobarr_superadmin_reset")

        self.superadmin_username = (superadmin_username or "").strip() or default_settings["sonobarr_superadmin_username"]
        self.superadmin_password = (superadmin_password or "").strip() or default_settings["sonobarr_superadmin_password"]
        self.superadmin_display_name = (superadmin_display_name or "").strip() or default_settings["sonobarr_superadmin_display_name"]
        reset_raw = (superadmin_reset or "").strip().lower()
        self.superadmin_reset_flag = reset_raw in {"1", "true", "yes"}

        try:
            if self.settings_config_file.exists():
                self.logger.info("Loading Config via file")
                with self.settings_config_file.open("r", encoding="utf-8") as json_file:
                    ret = json.load(json_file)
                    for key in ret:
                        if getattr(self, key, "") == "":
                            setattr(self, key, ret[key])
        except Exception as exc:  # pragma: no cover - filesystem errors
            self.logger.error(f"Error Loading Config: {exc}")

        self.openai_extra_headers = self._normalize_openai_headers_field(self.openai_extra_headers)

        for key, value in default_settings.items():
            if getattr(self, key, "") == "":
                setattr(self, key, value)

        self.lidarr_monitor_option = self._normalize_monitor_option(self.lidarr_monitor_option)
        self.lidarr_monitor_new_items = self._normalize_monitor_new_items(self.lidarr_monitor_new_items)
        monitored_bool = self._coerce_bool(self.lidarr_monitored)
        self.lidarr_monitored = monitored_bool if monitored_bool is not None else bool(default_settings["lidarr_monitored"])
        if not isinstance(self.lidarr_albums_to_monitor, list):
            self.lidarr_albums_to_monitor = self._parse_albums_to_monitor(self.lidarr_albums_to_monitor)

        try:
            self.similar_artist_batch_size = int(self.similar_artist_batch_size)
        except (TypeError, ValueError):
            self.similar_artist_batch_size = default_settings["similar_artist_batch_size"]
        if self.similar_artist_batch_size <= 0:
            self.similar_artist_batch_size = default_settings["similar_artist_batch_size"]

        try:
            self.openai_max_seed_artists = int(self.openai_max_seed_artists)
        except (TypeError, ValueError):
            self.openai_max_seed_artists = default_settings["openai_max_seed_artists"]
        if self.openai_max_seed_artists <= 0:
            self.openai_max_seed_artists = default_settings["openai_max_seed_artists"]

        try:
            self.lidarr_api_timeout = float(self.lidarr_api_timeout)
        except (TypeError, ValueError):
            self.lidarr_api_timeout = float(default_settings["lidarr_api_timeout"])

        self._configure_openai_client()
        self._configure_listening_services()
        self.save_config_to_file()
