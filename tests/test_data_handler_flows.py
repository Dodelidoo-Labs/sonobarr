"""Flow-oriented tests for DataHandler methods covering runtime branch behavior."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from sonobarr_app.extensions import db
from sonobarr_app.models import ArtistRequest, User
from sonobarr_app.services.data_handler import DataHandler, SessionState


class _FakeSocketIO:
    """Socket.IO test helper capturing emitted events."""

    def __init__(self):
        self.events = []
        self.tasks = []

    def emit(self, event, payload=None, room=None):
        self.events.append((event, payload, room))

    def start_background_task(self, func, *args):
        self.tasks.append((func.__name__, args))
        return None


class _Response:
    """Simple requests-like response used in DataHandler flow tests."""

    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def _make_handler(tmp_path: Path) -> tuple[DataHandler, _FakeSocketIO]:
    """Build a handler with isolated config paths and fake socket transport."""

    socketio = _FakeSocketIO()
    app_config = {
        "CONFIG_DIR": str(tmp_path / "config"),
        "SETTINGS_FILE": str(tmp_path / "config" / "settings.json"),
        "APP_VERSION": "test",
    }
    handler = DataHandler(socketio=socketio, logger=logging.getLogger("test-data-handler-flow"), app_config=app_config)
    return handler, socketio


def _create_user(username: str, *, is_admin: bool = False, auto_approve: bool = False) -> User:
    """Persist a user for permission and request flows."""

    user = User(
        username=username,
        is_admin=is_admin,
        auto_approve_artist_requests=auto_approve,
        is_active=True,
    )
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def test_get_artists_from_lidarr_success_and_error(tmp_path, monkeypatch):
    """Artist retrieval should emit success payloads and fallback to error payloads."""

    handler, socketio = _make_handler(tmp_path)
    handler.lidarr_address = "http://lidarr"
    handler.lidarr_api_key = "key"
    handler.lidarr_api_timeout = 1

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda endpoint, headers, timeout: _Response(
            200,
            payload=[{"artistName": "B"}, {"artistName": "A"}],
        ),
    )

    handler.get_artists_from_lidarr("sid")

    success = [event for event in socketio.events if event[0] == "lidarr_sidebar_update"][-1]
    assert success[1]["Status"] == "Success"
    assert [item["name"] for item in success[1]["Data"]] == ["A", "B"]

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda endpoint, headers, timeout: _Response(500, payload=[], text="boom"),
    )
    handler.get_artists_from_lidarr("sid")
    error = [event for event in socketio.events if event[0] == "lidarr_sidebar_update"][-1]
    assert error[1]["Status"] == "Error"
    assert error[1]["Code"] == 500


def test_start_flow_handles_empty_and_selected_lidarr_items(tmp_path, monkeypatch):
    """Start should request selection when empty and trigger candidate loading when seeds are selected."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid")
    session.lidarr_items = [{"name": "A", "checked": False}, {"name": "B", "checked": False}]

    handler.start("sid", [])
    warning_toast = [event for event in socketio.events if event[0] == "new_toast_msg"][-1]
    assert "Choose at least one" in warning_toast[1]["message"]

    calls = []
    monkeypatch.setattr(handler, "prepare_similar_artist_candidates", lambda s: calls.append("prepare"))
    monkeypatch.setattr(handler, "load_similar_artist_batch", lambda s, sid: calls.append("load"))
    handler.start("sid", ["A"])

    assert "prepare" in calls and "load" in calls


def test_ai_prompt_branches(tmp_path):
    """AI prompt flow should emit deterministic errors and success-related notifications."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid")
    session.lidarr_items = [{"name": "X", "checked": False}]
    handler.cached_lidarr_names = ["X"]
    handler.cached_cleaned_lidarr_names = ["x"]

    handler.ai_prompt("sid", "")
    assert [event for event in socketio.events if event[0] == "ai_prompt_error"]

    socketio.events.clear()
    handler.openai_recommender = None
    handler.ai_prompt("sid", "shoegaze")
    assert [event for event in socketio.events if event[0] == "ai_prompt_error"]

    class _Recommender:
        def __init__(self, seeds):
            self._seeds = seeds
            self.model = "m"
            self.timeout = 1

        def generate_seed_artists(self, prompt, existing):
            return list(self._seeds)

    socketio.events.clear()
    handler.openai_recommender = _Recommender([])
    handler.ai_prompt("sid", "shoegaze")
    assert "couldn't suggest" in socketio.events[-1][1]["message"].lower()

    socketio.events.clear()
    handler.openai_recommender = _Recommender(["X"])
    handler.ai_prompt("sid", "shoegaze")
    assert "already in your lidarr library" in socketio.events[-1][1]["message"].lower()

    socketio.events.clear()
    stream_calls = []
    handler._stream_seed_artists = lambda *args, **kwargs: stream_calls.append((args, kwargs)) or True
    handler.openai_recommender = _Recommender(["X", "Y"])
    handler.ai_prompt("sid", "shoegaze")
    assert stream_calls
    assert any(event[0] == "new_toast_msg" for event in socketio.events)


def test_personal_recommendations_branches(tmp_path):
    """Personal recommendation flow should handle source validation and successful streaming."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid", user_id=100)
    session.lidarr_items = [{"name": "Known", "checked": False}]
    session.cleaned_lidarr_items = ["known"]

    handler.personal_recommendations("sid", "unknown")
    assert "Unknown discovery source" in socketio.events[-2][1]["message"]

    socketio.events.clear()
    handler._resolve_user = lambda user_id: None
    handler.personal_recommendations("sid", "lastfm")
    assert "sign in again" in socketio.events[-2][1]["message"]

    socketio.events.clear()
    handler._personal_source_definitions = lambda: {
        "lastfm": {
            "label": "Last.fm",
            "title": "Last.fm discovery",
            "username_attr": "lastfm_username",
            "service_ready": False,
            "service_missing_reason": "missing service",
            "missing_username_reason": "missing username",
            "fetch": lambda username: ["A"],
            "error_message": "error",
        }
    }
    handler._resolve_user = lambda user_id: SimpleNamespace(
        username="u", lastfm_username="lfm", listenbrainz_username=""
    )
    handler.personal_recommendations("sid", "lastfm")
    assert "missing service" in socketio.events[-2][1]["message"]

    socketio.events.clear()
    handler._personal_source_definitions = lambda: {
        "lastfm": {
            "label": "Last.fm",
            "title": "Last.fm discovery",
            "username_attr": "lastfm_username",
            "service_ready": True,
            "service_missing_reason": "missing service",
            "missing_username_reason": "missing username",
            "fetch": lambda username: ["Known", "New Artist"],
            "error_message": "error",
        }
    }
    handler._resolve_user = lambda user_id: SimpleNamespace(
        username="u", lastfm_username="lfm", listenbrainz_username=""
    )
    handler._iter_artist_payloads_from_names = lambda names, missing=None: iter(
        [{"Name": "New Artist", "Status": "", "Img_Link": "", "Genre": "", "Popularity": "", "Followers": ""}]
    )
    handler.prepare_similar_artist_candidates = lambda s: setattr(s, "similar_artist_candidates", [1])
    handler.personal_recommendations("sid", "lastfm")
    assert any(event[0] == "user_recs_ack" for event in socketio.events)


def test_find_similar_artists_and_add_artist_paths(tmp_path, monkeypatch):
    """Similar-artist loading and add artist flow should update session status and emit user feedback."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid", user_id=1)
    session.prepare_for_search()
    session.similar_artist_candidates = []
    session.similar_artist_batch_pointer = 0

    handler.find_similar_artists("sid")
    assert any(event[0] == "new_toast_msg" for event in socketio.events)

    handler._validate_artist_add_permissions = lambda *args, **kwargs: False
    status = handler.add_artists("sid", "Artist%20One")
    assert status == "Failed to Add"

    session.recommended_artists = [{"Name": "Artist One", "Status": ""}]
    handler._validate_artist_add_permissions = lambda *args, **kwargs: True
    handler._perform_artist_addition = lambda *args, **kwargs: "Added"
    status = handler.add_artists("sid", "Artist%20One")
    assert status == "Added"
    assert any(event[0] == "refresh_artist" for event in socketio.events)


def test_request_artist_db_operations_and_flow(app, tmp_path, monkeypatch):
    """Request flow should create pending requests, detect duplicates, and handle unauthenticated access."""

    handler, socketio = _make_handler(tmp_path)
    handler.set_flask_app(app)

    with app.app_context():
        user = _create_user("member", is_admin=False, auto_approve=False)
        user_id = user.id

    session = handler.ensure_session("sid", user_id=user_id)
    session.recommended_artists = [{"Name": "Pending Artist", "Status": ""}]

    handler._can_add_without_approval = lambda s: False
    handler.request_artist("sid", "Pending%20Artist")

    with app.app_context():
        created = ArtistRequest.query.filter_by(artist_name="Pending Artist", requested_by_id=user.id).first()
        assert created is not None

    handler.request_artist("sid", "Pending%20Artist")
    duplicate_toasts = [event for event in socketio.events if event[0] == "new_toast_msg"]
    assert any("already requested" in event[1]["message"] for event in duplicate_toasts)

    handler_auto, socketio_auto = _make_handler(tmp_path)
    session_auto = handler_auto.ensure_session("sid-auto", user_id=user.id)
    session_auto.recommended_artists = [{"Name": "Auto Artist", "Status": ""}]
    handler_auto._can_add_without_approval = lambda s: True
    auto_calls = []
    handler_auto.add_artists = lambda sid, artist: auto_calls.append((sid, artist)) or "Added"
    handler_auto.request_artist("sid-auto", "Auto%20Artist")
    assert auto_calls

    anon_handler, anon_socketio = _make_handler(tmp_path)
    anon_handler.ensure_session("anon", user_id=None)
    anon_handler.request_artist("anon", "Anon%20Artist")
    assert any(event[0] == "new_toast_msg" for event in anon_socketio.events)


def test_preview_prehear_and_artist_payload_helpers(tmp_path, monkeypatch):
    """Preview/audio payload utilities should emit results and tolerate missing external data."""

    handler, socketio = _make_handler(tmp_path)
    handler.youtube_api_key = "yt"

    artist_obj = SimpleNamespace(
        name="Artist",
        get_bio_content=lambda: "Bio",
        get_top_tags=lambda: [SimpleNamespace(item=SimpleNamespace(get_name=lambda: "rock"))],
        get_listener_count=lambda: 1000,
        get_playcount=lambda: 5000,
    )

    class _LFM:
        def search_for_artist(self, name):
            return SimpleNamespace(get_next_page=lambda: [artist_obj])

        def get_artist(self, name):
            return SimpleNamespace(get_top_tracks=lambda limit: [SimpleNamespace(item=SimpleNamespace(title="Track"))])

    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda api_key, api_secret: _LFM())
    monkeypatch.setattr("sonobarr_app.services.data_handler.DataHandler._attempt_youtube_preview", lambda self, a, t, k: {"videoId": "123", "track": t, "artist": a, "source": "youtube"})
    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.DataHandler._resolve_artist_image",
        staticmethod(lambda artist_name: None),
    )

    handler.preview("sid", "Artist")
    handler.prehear("sid", "Artist")

    assert any(event[0] == "lastfm_preview" for event in socketio.events)
    assert any(event[0] == "prehear_result" for event in socketio.events)

    payload = handler._fetch_artist_payload(_LFM(), "Artist", similarity_score=1.5)
    assert payload["Name"] == "Artist"
    assert payload["SimilarityScore"] == 1.0
    assert payload["Img_Link"].startswith("https://placehold.co")


def test_openai_config_and_file_merge_helpers(tmp_path, monkeypatch):
    """OpenAI setup and config-file merge helpers should support valid env and file-based overrides."""

    handler, _ = _make_handler(tmp_path)

    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    handler.openai_api_key = ""
    handler.openai_api_base = ""
    handler.openai_model = ""
    handler.openai_extra_headers = '{"X-Test":"1"}'
    handler.openai_max_seed_artists = "bad"

    class _DummyRecommender:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("sonobarr_app.services.data_handler.OpenAIRecommender", _DummyRecommender)
    handler._configure_openai_client()

    assert handler.openai_recommender is not None
    assert handler.openai_max_seed_artists == 5

    defaults = handler._default_settings()
    handler.lidarr_address = ""
    handler.settings_config_file.write_text('{"lidarr_address": "http://from-file"}', encoding="utf-8")
    handler._merge_config_file_overrides()
    handler._apply_missing_defaults(defaults)
    assert handler.lidarr_address == "http://from-file"
