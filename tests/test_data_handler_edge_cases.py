"""Additional DataHandler branch coverage tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

from sonobarr_app.extensions import db
from sonobarr_app.models import User
from sonobarr_app.services.data_handler import DataHandler, FAILED_TO_ADD_STATUS


class _FakeSocketIO:
    """Socket.IO double that records emitted events and started tasks."""

    def __init__(self):
        self.events = []
        self.tasks = []

    def emit(self, event, payload=None, room=None):
        self.events.append((event, payload, room))

    def start_background_task(self, func, *args):
        self.tasks.append((func, args))
        return None


class _Response:
    """Minimal requests-like response object for DataHandler edge tests."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


def _make_handler(tmp_path: Path, app_config: dict | None = None) -> tuple[DataHandler, _FakeSocketIO]:
    """Build a DataHandler with isolated config paths."""

    socketio = _FakeSocketIO()
    default_config = {
        "CONFIG_DIR": str(tmp_path / "config"),
        "SETTINGS_FILE": str(tmp_path / "config" / "settings.json"),
        "APP_VERSION": "test",
    }
    if app_config:
        default_config.update(app_config)
    handler = DataHandler(socketio=socketio, logger=logging.getLogger("test-data-handler-edge"), app_config=default_config)
    return handler, socketio


def _create_user(username: str, *, is_admin: bool = False, auto_approve: bool = False) -> User:
    """Persist a user for permission-sensitive DataHandler tests."""

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


def test_init_and_basic_helper_branches(tmp_path, monkeypatch):
    """Initialization and helper coercion methods should cover None and numeric edge paths."""

    monkeypatch.chdir(tmp_path)
    handler = DataHandler(socketio=_FakeSocketIO(), logger=logging.getLogger("test-init"), app_config={"APP_VERSION": "x"})
    assert handler.config_folder == tmp_path / "config"

    assert handler._coerce_bool(None) is None
    assert handler._coerce_bool(2) is True
    assert handler._coerce_float(None, minimum=0.0) is None
    assert handler._normalize_monitor_option(None) == ""
    assert handler._normalize_monitor_new_items(None) == ""
    assert handler._parse_albums_to_monitor(["A", "", "B"]) == ["A", "B"]
    assert handler._parse_albums_to_monitor(None) == []
    assert handler._clean_str_value(None) == ""

    handler.api_key = "edge-key"
    app_like = SimpleNamespace(config={})
    handler.set_flask_app(app_like)
    assert app_like.config["API_KEY"] == "edge-key"

    session = handler.ensure_session("sid-edge")
    updated = handler.ensure_session("sid-edge", user_id=7, is_admin=True, auto_approve_artist_requests=True)
    assert session is updated
    assert updated.user_id == 7
    assert updated.is_admin is True
    assert updated.auto_approve_artist_requests is True


def test_user_resolution_permissions_and_personal_source_state_branches(app, tmp_path):
    """User resolution and personal-source state should cover fallback session and reason branches."""

    handler, socketio = _make_handler(tmp_path)
    handler.set_flask_app(app)

    with app.app_context():
        user = _create_user("listener", is_admin=False, auto_approve=False)
        session = handler.ensure_session("sid-user", user_id=user.id)

        assert handler._resolve_user(None) is None
        assert handler._resolve_user("invalid") is None
        assert handler._resolve_user(user.id).id == user.id

        session.user_id = None
        handler._sync_session_permissions(session)
        assert session.is_admin is False
        assert session.auto_approve_artist_requests is False

        assert handler._can_add_without_approval(session) is False

        handler.last_fm_user_service = object()
        handler.listenbrainz_user_service = None
        handler.emit_personal_sources_state("sid-fallback")
        event_name, payload, room = socketio.events[-1]
        assert event_name == "personal_sources_state"
        assert room == "sid-fallback"
        assert payload["lastfm"]["reason"] == "Add your Last.fm username in Profile \u2192 Listening services."
        assert payload["listenbrainz"]["reason"] == "ListenBrainz integration is unavailable right now."

        sent = []
        handler.emit_personal_sources_state = lambda sid: sent.append(sid)
        handler.ensure_session("sid-a", user_id=user.id)
        handler.ensure_session("sid-b", user_id=user.id + 10)
        handler.broadcast_personal_sources_state()
        handler.refresh_personal_sources_for_user(user.id)
        assert "sid-a" in sent and "sid-b" in sent


def test_connection_sidebar_and_start_cached_and_empty_branches(tmp_path, monkeypatch):
    """Socket discovery orchestration should cover cached hydration and early-return start branches."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-conn", user_id=1)
    session.recommended_artists = [{"Name": "A"}]
    session.lidarr_items = [{"name": "Known", "checked": False}]
    session.running = True

    called_personal = []
    handler.emit_personal_sources_state = lambda sid: called_personal.append(sid)
    handler._sync_session_permissions = lambda sess: None
    handler.connection("sid-conn", 1, False, False)

    assert any(event[0] == "user_info" for event in socketio.events)
    assert any(event[0] == "more_artists_loaded" for event in socketio.events)
    assert any(event[0] == "lidarr_sidebar_update" for event in socketio.events)
    assert called_personal == ["sid-conn"]

    handler.cached_lidarr_names = ["Cache Artist"]
    handler.cached_cleaned_lidarr_names = ["cache artist"]
    handler.side_bar_opened("sid-sidebar")
    assert any(event[0] == "lidarr_sidebar_update" and event[2] == "sid-sidebar" for event in socketio.events)

    handler.cached_lidarr_names = ["Seed A"]
    handler.cached_cleaned_lidarr_names = ["seed a"]
    handler.start("sid-start-cache", [])
    assert any("Choose at least one" in event[1]["message"] for event in socketio.events if event[0] == "new_toast_msg")

    no_data_session = handler.ensure_session("sid-start-empty")
    no_data_session.lidarr_items = []
    handler.cached_lidarr_names = []
    handler.get_artists_from_lidarr = lambda sid: None
    handler.start("sid-start-empty", ["Anything"])
    assert no_data_session.lidarr_items == []


def test_ai_and_personal_recommendation_error_branches(tmp_path):
    """AI prompt and personal recommendation flows should emit deterministic errors for edge outcomes."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-ai")
    session.lidarr_items = [{"name": "Known", "checked": False}]
    handler.cached_lidarr_names = ["Known"]
    handler.cached_cleaned_lidarr_names = ["known"]

    class _Recommender:
        model = "m"
        timeout = 1

        def generate_seed_artists(self, *_args, **_kwargs):
            return ["New Artist"]

    handler.openai_recommender = _Recommender()
    stream_calls = []
    handler._stream_seed_artists = lambda *args, **kwargs: stream_calls.append((args, kwargs)) or False
    handler.ai_prompt("sid-ai", "discover")
    assert stream_calls

    handler.last_fm_user_service = None
    assert handler._fetch_lastfm_personal_artists("x") == []

    handler.listenbrainz_user_service = None
    assert handler._fetch_listenbrainz_personal_artists("x") == []

    handler._emit_personal_error = lambda *args, **kwargs: socketio.emit("user_recs_error", {"message": "err"})
    seeds = handler._fetch_personal_recommendation_seeds(
        "sid-ai",
        "lastfm",
        {
            "label": "Last.fm",
            "title": "Last.fm discovery",
            "fetch": lambda _u: (_ for _ in ()).throw(RuntimeError("broken")),
            "error_message": "failed",
        },
        "user",
    )
    assert seeds is None

    session.cleaned_lidarr_items = []
    handler.cached_cleaned_lidarr_names = []
    handler.get_artists_from_lidarr = lambda sid: setattr(handler, "cached_cleaned_lidarr_names", ["known"])
    assert handler._ensure_cleaned_library_names(session, "sid-ai") == {"known"}

    handler._emit_all_personal_recommendations_known(
        session,
        "sid-ai",
        "lastfm",
        "user",
        ["Known"],
        "Last.fm discovery",
    )
    assert any(event[0] == "user_recs_ack" for event in socketio.events)


def test_stop_similarity_helpers_and_candidate_collection(tmp_path, monkeypatch):
    """Similarity helper methods should handle invalid matches, dedupe, and stop-state events."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-sim")
    session.lidarr_items = [{"name": "A", "checked": False}]
    handler.stop("sid-sim")
    assert any(event[0] == "lidarr_sidebar_update" for event in socketio.events)

    assert handler._parse_similarity_match(None) is None
    assert handler._parse_similarity_match("bad") is None
    assert handler._parse_similarity_match("0.42") == 0.42

    key = handler._similar_artist_sort_key({"match": None, "artist": SimpleNamespace(item=SimpleNamespace(name="B"))})
    assert key[1] == "b"

    related = [SimpleNamespace(item=SimpleNamespace(name=f"Artist {idx}"), match="0.5") for idx in range(501)]

    class _Lfm:
        def get_artist(self, name):
            if name == "Bad Seed":
                raise RuntimeError("unavailable")
            return SimpleNamespace(get_similar=lambda: related)

    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda **kwargs: _Lfm())
    session.artists_to_use_in_search = ["Bad Seed", "Good Seed"]
    session.cleaned_lidarr_items = []
    session.ai_seed_artists = ["Seeded Artist"]
    candidates = handler._collect_similar_candidates(session)
    assert len(candidates) == 500

    handler.prepare_similar_artist_candidates(session)
    assert session.similar_artist_batch_pointer == 0
    assert session.initial_batch_sent is False


def test_load_batches_and_find_similar_branches(tmp_path, monkeypatch):
    """Batch loading should cover stop-event checks, missing payloads, and no-more-artists notices."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-batch")

    session.stop_event.set()
    handler.load_similar_artist_batch(session, "sid-batch")
    assert session.running is False

    session.prepare_for_search()
    session.similar_artist_candidates = []
    handler.load_similar_artist_batch(session, "sid-batch")
    assert any(event[0] == "load_more_complete" for event in socketio.events)

    session.prepare_for_search()
    session.recommended_artists = [{"Name": "Dup", "Status": ""}]
    session.similar_artist_candidates = [
        {"artist": SimpleNamespace(item=SimpleNamespace(name="Dup")), "match": 0.9},
        {"artist": SimpleNamespace(item=SimpleNamespace(name="Missing")), "match": 0.7},
        {"artist": SimpleNamespace(item=SimpleNamespace(name="Fresh")), "match": 0.6},
    ]
    handler.similar_artist_batch_size = 10

    def _fake_fetch(_network, name, similarity_score=None):
        if name == "Missing":
            return None
        return {
            "Name": name,
            "Status": "",
            "Img_Link": "",
            "Genre": "",
            "Popularity": "",
            "Followers": "",
        }

    monkeypatch.setattr(handler, "_fetch_artist_payload", _fake_fetch)
    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda **kwargs: object())
    handler.load_similar_artist_batch(session, "sid-batch")
    assert any(event[0] == "more_artists_loaded" for event in socketio.events)
    assert any(event[0] == "initial_load_complete" for event in socketio.events)

    stopped_session = handler.ensure_session("sid-find-stop")
    stopped_session.stop_event.set()
    handler.find_similar_artists("sid-find-stop")

    class _Lock:
        def __init__(self, target_session):
            self.target_session = target_session

        def __enter__(self):
            self.target_session.stop_event.set()
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    lock_session = handler.ensure_session("sid-find-lock")
    lock_session.stop_event.clear()
    lock_session.search_lock = _Lock(lock_session)
    handler.find_similar_artists("sid-find-lock")

    more_session = handler.ensure_session("sid-find-more")
    more_session.stop_event.clear()
    more_session.similar_artist_batch_pointer = 0
    more_session.similar_artist_candidates = [1]
    called = []
    handler.load_similar_artist_batch = lambda s, sid: called.append((s.sid, sid))
    handler.find_similar_artists("sid-find-more")
    assert called == [("sid-find-more", "sid-find-more")]


def test_lidarr_submission_addition_and_request_error_branches(app, tmp_path, monkeypatch):
    """Lidarr add helpers should handle dry-run, missing MBIDs, failures, and request exceptions."""

    handler, socketio = _make_handler(tmp_path)
    handler.set_flask_app(app)
    handler.lidarr_address = "http://lidarr"
    handler.lidarr_api_key = "key"
    handler.lidarr_api_timeout = 1
    handler.root_folder_path = "/music"

    handler.dry_run_adding_to_lidarr = True
    response, status_code = handler._submit_lidarr_add_request({})
    assert response is None and status_code == 201

    handler.dry_run_adding_to_lidarr = False
    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.post",
        lambda *args, **kwargs: _Response(status_code=400, payload={"message": "Invalid Path"}),
    )
    response, status_code = handler._submit_lidarr_add_request({"x": "y"})
    assert status_code == 400
    body, payload, _message = handler._extract_lidarr_error_message(None)
    assert body == "No response object returned."
    assert payload is None

    session = handler.ensure_session("sid-add", user_id=1)
    handler.get_mbid_from_musicbrainz = lambda artist_name: None
    failed = handler._perform_artist_addition(session, "sid-add", "No Match", "No Match")
    assert failed == FAILED_TO_ADD_STATUS

    handler.get_mbid_from_musicbrainz = lambda artist_name: "mbid-1"
    handler._submit_lidarr_add_request = lambda payload: (None, 201)
    assert handler._perform_artist_addition(session, "sid-add", "Added Artist", "Added Artist") == "Added"

    handler._submit_lidarr_add_request = lambda payload: (_Response(status_code=500, payload={"message": "boom"}), 500)
    assert handler._perform_artist_addition(session, "sid-add", "Bad Artist", "Bad Artist") == FAILED_TO_ADD_STATUS

    with app.app_context():
        user = _create_user("request-user")
        request_session = handler.ensure_session("sid-request", user_id=user.id)
        request_session.recommended_artists = [{"Name": "Request Artist", "Status": ""}]
        handler._can_add_without_approval = lambda s: False
        handler._request_artist_db_operations = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db fail"))
        handler._flask_app = None
        handler.request_artist("sid-request", "Request%20Artist")
        assert any(event[0] == "new_toast_msg" for event in socketio.events)


def test_settings_preview_audio_and_misc_utility_branches(tmp_path, monkeypatch):
    """Settings and preview helpers should cover serialization failures, fallbacks, and parser edge cases."""

    handler, socketio = _make_handler(tmp_path)

    handler.lidarr_address = "http://lidarr"
    handler.load_settings("sid-settings")
    assert any(event[0] == "settingsLoaded" for event in socketio.events)

    del handler.lidarr_address
    handler.load_settings("sid-settings")

    handler.similar_artist_batch_size = 0
    handler.openai_max_seed_artists = 0
    handler.auto_start_delay = -5
    handler.update_settings({})
    assert handler.similar_artist_batch_size == 1
    assert handler.openai_max_seed_artists >= 1
    assert handler.auto_start_delay == 0

    handler._apply_string_settings = lambda data: (_ for _ in ()).throw(RuntimeError("bad settings"))
    handler.update_settings({})

    class _NoMatchLfm:
        def search_for_artist(self, name):
            return SimpleNamespace(get_next_page=lambda: [SimpleNamespace(name="Different", get_bio_content=lambda: None)])

    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda **kwargs: _NoMatchLfm())
    handler.preview("sid-preview", "Target")

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.pylast.LastFMNetwork",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("lfm down")),
    )
    handler.preview("sid-preview", "Target")
    assert any(event[0] == "lastfm_preview" for event in socketio.events)

    assert handler._attempt_youtube_preview("A", "T", "") is None

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda url, timeout=10, params=None: _Response(status_code=200, payload={"items": []} if "googleapis" in url else {"results": []}),
    )
    assert handler._attempt_youtube_preview("A", "T", "yt-key") is None
    assert handler._attempt_itunes_preview("A", None) is None

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda *args, **kwargs: _Response(status_code=500, payload={}),
    )
    assert handler._attempt_itunes_preview("A", "T") is None

    monkeypatch.setattr(handler, "_attempt_youtube_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(handler, "_attempt_itunes_preview", lambda artist, track: {"source": "itunes"} if track else None)
    monkeypatch.setattr("sonobarr_app.services.data_handler.time.sleep", lambda _seconds: None)
    top_tracks = [SimpleNamespace(item=SimpleNamespace(title="Track 1"))]
    assert handler._resolve_audio_preview("Artist", top_tracks, "yt-key") == {"source": "itunes"}
    monkeypatch.setattr(handler, "_attempt_itunes_preview", lambda artist, track: None)
    assert handler._resolve_audio_preview("Artist", top_tracks, "") == {"error": "No sample found"}

    assert handler._safe_artist_metric(SimpleNamespace(), "missing") == 0
    assert handler._safe_artist_metric(SimpleNamespace(broken=lambda: (_ for _ in ()).throw(RuntimeError("x"))), "broken") == 0

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda *args, **kwargs: _Response(status_code=200, payload={"data": []}),
    )
    assert handler._resolve_artist_image("x") is None

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda *args, **kwargs: _Response(status_code=200, payload={"data": [{"picture_large": "img"}]}),
    )
    assert handler._resolve_artist_image("x") == "img"

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert handler._resolve_artist_image("x") is None

    class _ArtistWithName:
        name = "Named"

    class _ArtistExploding:
        def get_name(self):
            raise RuntimeError("bad")

    assert handler._resolve_display_artist_name(_ArtistWithName(), "Fallback") == "Named"
    assert handler._resolve_display_artist_name(_ArtistExploding(), "Fallback") == "Fallback"

    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda **kwargs: object())
    handler._fetch_artist_payload = lambda _network, name: None if name == "Missing" else {"Name": name}
    payloads = list(handler._iter_artist_payloads_from_names(["A", "A", "", "Missing"], missing=[]))
    assert payloads == [{"Name": "A"}]
    assert list(handler._iter_artist_payloads_from_names([])) == []

    session = handler.ensure_session("sid-stream")
    session.recommended_artists = [{"Name": "Duplicate", "Status": ""}]
    handler._iter_artist_payloads_from_names = lambda names, missing=None: iter(
        [{"Name": "Duplicate", "Status": ""}, {"Name": "Fresh", "Status": ""}]
    )
    handler.prepare_similar_artist_candidates = lambda s: setattr(s, "similar_artist_candidates", [])
    ok = handler._stream_seed_artists(
        session,
        "sid-stream",
        ["Duplicate", "Fresh"],
        ack_event="ack",
        ack_payload={},
        error_event="err",
        error_message="failed",
        missing_title="Missing",
        missing_message="missing",
        source_log_label="edge",
    )
    assert ok is True

    assert handler._normalize_openai_headers_field({object(): object()}) == ""
    handler.openai_extra_headers = ""
    assert handler._parse_openai_extra_headers() == {}
    handler.openai_extra_headers = {"A": "1"}
    assert handler._parse_openai_extra_headers() == {"A": "1"}
    handler.openai_extra_headers = "   "
    assert handler._parse_openai_extra_headers() == {}
    handler.openai_extra_headers = "not-json"
    assert handler._parse_openai_extra_headers() == {}

    handler.openai_api_key = "k"
    handler.openai_max_seed_artists = 0
    monkeypatch.setattr("sonobarr_app.services.data_handler.OpenAIRecommender", lambda **kwargs: SimpleNamespace(**kwargs))
    handler._configure_openai_client()
    assert handler.openai_max_seed_artists > 0

    handler.last_fm_api_key = "lfm-key"
    handler.last_fm_api_secret = "lfm-secret"
    handler._configure_listening_services()
    assert handler.last_fm_user_service is not None

    handler.settings_config_file.write_text(json.dumps({"a": 1}), encoding="utf-8")
    monkeypatch.setattr("sonobarr_app.services.data_handler.os.replace", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("replace failed")))
    handler.save_config_to_file()

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.musicbrainzngs.search_artists",
        lambda artist: {"artist-list": [{"name": artist, "id": "exact"}]},
    )
    assert handler.get_mbid_from_musicbrainz("Artist") == "exact"

    handler.fallback_to_top_result = True
    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.musicbrainzngs.search_artists",
        lambda artist: {"artist-list": [{"name": "Other", "id": "fallback-id"}]},
    )
    assert handler.get_mbid_from_musicbrainz("Artist") == "fallback-id"

    defaults = handler._default_settings()
    handler.similar_artist_batch_size = "bad"
    handler.openai_max_seed_artists = "0"
    handler.lidarr_api_timeout = "bad"
    handler._normalize_loaded_settings(defaults)
    assert handler.similar_artist_batch_size == defaults["similar_artist_batch_size"]
    assert handler.openai_max_seed_artists == defaults["openai_max_seed_artists"]


def test_personal_recommendation_remaining_branches(app, tmp_path):
    """Personal recommendation helpers should cover username, filtering, and failed-stream edge paths."""

    handler, socketio = _make_handler(tmp_path)
    handler.set_flask_app(app)

    with app.app_context():
        user = _create_user("personal-user", is_admin=True, auto_approve=True)
        user.listenbrainz_username = "listener"
        db.session.commit()

        session = handler.ensure_session("sid-personal", user_id=user.id)
        handler._flask_app = None
        assert handler._resolve_user(user.id).id == user.id

        handler._sync_session_permissions(session)
        assert session.is_admin is True
        assert session.auto_approve_artist_requests is True

        handler.listenbrainz_user_service = object()
        handler.emit_personal_sources_state("sid-personal")
        latest_state = [event for event in socketio.events if event[0] == "personal_sources_state"][-1][1]
        assert latest_state["listenbrainz"]["reason"] is None

        assert "recommendation(s)" in handler._format_skipped_seed_message(["A", "B"], "AI")

        class _LfmService:
            def get_recommended_artists(self, username, limit=50):
                return []

            def get_top_artists(self, username, limit=50):
                return [SimpleNamespace(name="Fallback Artist"), SimpleNamespace(name="")]

        class _ListenBrainzService:
            def get_weekly_exploration_artists(self, username):
                return SimpleNamespace(artists=["LB Artist", ""])

        handler.last_fm_user_service = _LfmService()
        handler.listenbrainz_user_service = _ListenBrainzService()
        assert handler._fetch_lastfm_personal_artists("user") == ["Fallback Artist"]
        assert handler._fetch_listenbrainz_personal_artists("user") == ["LB Artist"]

        user.lastfm_username = ""
        db.session.commit()
        handler.personal_recommendations("sid-personal", "lastfm")
        assert any(event[0] == "user_recs_error" for event in socketio.events)

        user.lastfm_username = "lfm-user"
        db.session.commit()

        handler._fetch_personal_recommendation_seeds = lambda *args, **kwargs: None
        handler.personal_recommendations("sid-personal", "lastfm")

        handler._fetch_personal_recommendation_seeds = lambda *args, **kwargs: ["", "  "]
        handler.personal_recommendations("sid-personal", "lastfm")

        session.cleaned_lidarr_items = ["known"]
        handler._fetch_personal_recommendation_seeds = lambda *args, **kwargs: ["Known"]
        handler.personal_recommendations("sid-personal", "lastfm")

        session.cleaned_lidarr_items = []
        handler._fetch_personal_recommendation_seeds = lambda *args, **kwargs: ["New One"]
        handler._stream_seed_artists = lambda *args, **kwargs: False
        handler.personal_recommendations("sid-personal", "lastfm")


def test_candidate_loop_and_batch_stop_branches(tmp_path, monkeypatch):
    """Candidate collection and batch loading should cover skip and mid-loop stop conditions."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-candidates")
    session.artists_to_use_in_search = ["Seed Artist"]
    session.ai_seed_artists = ["Skip Me"]
    session.cleaned_lidarr_items = ["known"]

    related_items = [
        SimpleNamespace(item=SimpleNamespace(name="Known"), match="0.9"),
        SimpleNamespace(item=SimpleNamespace(name="Skip Me"), match="0.8"),
        SimpleNamespace(item=SimpleNamespace(name="Fresh"), match="0.7"),
    ]

    class _Lfm:
        def get_artist(self, _name):
            return SimpleNamespace(get_similar=lambda: related_items)

    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda **kwargs: _Lfm())
    candidates = handler._collect_similar_candidates(session)
    assert len(candidates) == 1
    assert candidates[0]["artist"].item.name == "Fresh"

    loop_session = handler.ensure_session("sid-loop")
    loop_session.prepare_for_search()
    loop_session.similar_artist_candidates = [
        {"artist": SimpleNamespace(item=SimpleNamespace(name="A")), "match": 0.8},
        {"artist": SimpleNamespace(item=SimpleNamespace(name="B")), "match": 0.7},
    ]
    loop_session.recommended_artists = []
    handler.similar_artist_batch_size = 10
    monkeypatch.setattr("sonobarr_app.services.data_handler.pylast.LastFMNetwork", lambda **kwargs: object())

    def _fetch(_network, name, similarity_score=None):
        loop_session.stop_event.set()
        return {"Name": name, "Status": "", "Img_Link": "", "Genre": "", "Popularity": "", "Followers": ""}

    handler._fetch_artist_payload = _fetch
    handler.load_similar_artist_batch(loop_session, "sid-loop")
    assert any(event[0] == "initial_load_complete" for event in socketio.events)


def test_preview_audio_success_and_fallback_branches(tmp_path, monkeypatch):
    """Audio preview helpers should return YouTube and iTunes previews, including fallback-only matches."""

    handler, _ = _make_handler(tmp_path)

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda *args, **kwargs: _Response(status_code=200, payload={"items": [{"id": {"videoId": "vid-1"}}]}),
    )
    youtube = handler._attempt_youtube_preview("Artist", "Track", "yt-key")
    assert youtube["videoId"] == "vid-1"

    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.requests.get",
        lambda *args, **kwargs: _Response(
            status_code=200,
            payload={
                "results": [
                    {"trackName": "Missing Preview"},
                    {"previewUrl": "https://preview", "trackName": "Track A", "artistName": "Artist A"},
                ]
            },
        ),
    )
    itunes = handler._attempt_itunes_preview("Artist", "Track")
    assert itunes["previewUrl"] == "https://preview"

    monkeypatch.setattr(handler, "_attempt_youtube_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        handler,
        "_attempt_itunes_preview",
        lambda artist, track: {"source": "fallback"} if track is None else None,
    )
    top_tracks = [SimpleNamespace(item=SimpleNamespace(title="Track X"))]
    assert handler._resolve_audio_preview("Artist", top_tracks, "") == {"source": "fallback"}


def test_stream_missing_seed_toast_and_save_config_tmp_cleanup(tmp_path, monkeypatch):
    """Seed streaming should emit missing-seed toasts and config saving should remove orphan temp files."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-stream-missing")

    def _iter_payloads(_names, missing=None):
        if missing is not None:
            missing.append("Missing Artist")
        yield {
            "Name": "Fresh Artist",
            "Status": "",
            "Img_Link": "",
            "Genre": "",
            "Popularity": "",
            "Followers": "",
        }

    handler._iter_artist_payloads_from_names = _iter_payloads
    handler.prepare_similar_artist_candidates = lambda s: setattr(s, "similar_artist_candidates", [])
    ok = handler._stream_seed_artists(
        session,
        "sid-stream-missing",
        ["Fresh Artist"],
        ack_event="ack",
        ack_payload={},
        error_event="err",
        error_message="failed",
        missing_title="Missing",
        missing_message="Some artists were skipped",
        source_log_label="edge",
    )
    assert ok is True
    assert any(
        event[0] == "new_toast_msg" and event[1]["message"] == "Some artists were skipped"
        for event in socketio.events
    )

    config_dir = handler.settings_config_file.parent
    before_files = set(config_dir.glob("*"))
    monkeypatch.setattr(
        "sonobarr_app.services.data_handler.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("replace failed")),
    )
    handler.save_config_to_file()
    after_files = set(config_dir.glob("*"))
    assert before_files == after_files
