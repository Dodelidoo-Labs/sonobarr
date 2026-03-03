"""Core unit tests for DataHandler helper and orchestration logic."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from sonobarr_app.services.data_handler import DataHandler, FAILED_TO_ADD_STATUS, SessionState


class _FakeSocketIO:
    """Socket.IO test double capturing all emitted events."""

    def __init__(self):
        self.events = []
        self.tasks = []

    def emit(self, event, payload=None, room=None):
        self.events.append((event, payload, room))

    def start_background_task(self, func, *args):
        self.tasks.append((func, args))
        return None


class _Response:
    """HTTP response test double for Lidarr-related helper tests."""

    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _make_handler(tmp_path: Path) -> tuple[DataHandler, _FakeSocketIO]:
    """Construct a DataHandler bound to isolated temporary config paths."""

    socketio = _FakeSocketIO()
    app_config = {
        "CONFIG_DIR": str(tmp_path / "config"),
        "SETTINGS_FILE": str(tmp_path / "config" / "settings.json"),
        "APP_VERSION": "test",
    }
    handler = DataHandler(socketio=socketio, logger=logging.getLogger("test-data-handler"), app_config=app_config)
    return handler, socketio


def test_session_state_lifecycle_and_session_management(tmp_path):
    """Session state should reset and stop correctly through helper methods."""

    handler, _ = _make_handler(tmp_path)
    session = handler.ensure_session("sid-1", user_id=1, is_admin=True, auto_approve_artist_requests=True)

    assert session.stop_event.is_set()
    session.prepare_for_search()
    assert session.running is True
    assert not session.stop_event.is_set()

    session.mark_stopped()
    assert session.running is False
    assert session.stop_event.is_set()

    handler.remove_session("sid-1")
    assert handler.get_session_if_exists("sid-1") is None


def test_coercion_and_parse_helpers(tmp_path):
    """Type coercion helpers should normalize booleans, numeric values, and monitor settings."""

    handler, _ = _make_handler(tmp_path)

    assert handler._coerce_bool(" yes ") is True
    assert handler._coerce_bool("off") is False
    assert handler._coerce_bool("maybe") is None
    assert handler._coerce_int("-4", minimum=1) == 1
    assert handler._coerce_int("", minimum=1) is None
    assert handler._coerce_float("-2.5", minimum=0.0) == 0.0
    assert handler._normalize_monitor_option("future") == "future"
    assert handler._normalize_monitor_option("invalid") == ""
    assert handler._normalize_monitor_new_items("new") == "new"
    assert handler._parse_albums_to_monitor(" one, two\nthree ") == ["one", "two", "three"]


def test_update_settings_applies_values_and_clamps(tmp_path, monkeypatch):
    """Settings update should parse payload values, clamp invalid minima, and refresh integrations."""

    handler, _ = _make_handler(tmp_path)
    refresh_calls = []

    monkeypatch.setattr(handler, "_configure_openai_client", lambda: refresh_calls.append("openai"))
    monkeypatch.setattr(handler, "_configure_listening_services", lambda: refresh_calls.append("listening"))
    monkeypatch.setattr(handler, "save_config_to_file", lambda: refresh_calls.append("save"))
    monkeypatch.setattr(handler, "broadcast_personal_sources_state", lambda: refresh_calls.append("broadcast"))
    handler._flask_app = SimpleNamespace(config={})

    handler.update_settings(
        {
            "lidarr_address": " http://lidarr.local ",
            "quality_profile_id": "0",
            "metadata_profile_id": "2",
            "similar_artist_batch_size": "-8",
            "openai_max_seed_artists": "0",
            "lidarr_api_timeout": "-1",
            "auto_start_delay": "-15",
            "auto_start": "true",
            "lidarr_monitored": "false",
            "openai_extra_headers": {"X-Env": "test"},
            "lidarr_monitor_option": "all",
            "lidarr_monitor_new_items": "new",
            "lidarr_albums_to_monitor": "album-a, album-b",
            "api_key": "api-test",
        }
    )

    assert handler.lidarr_address == "http://lidarr.local"
    assert handler.quality_profile_id == 1
    assert handler.metadata_profile_id == 2
    assert handler.similar_artist_batch_size == 1
    assert handler.openai_max_seed_artists == 1
    assert handler.lidarr_api_timeout == 1.0
    assert handler.auto_start_delay == 0
    assert handler.auto_start is True
    assert handler.lidarr_monitored is False
    assert handler.openai_extra_headers == "{'X-Env': 'test'}"
    assert handler.lidarr_monitor_option == "all"
    assert handler.lidarr_monitor_new_items == "new"
    assert handler.lidarr_albums_to_monitor == ["album-a", "album-b"]
    assert handler._flask_app.config["API_KEY"] == "api-test"
    assert refresh_calls == ["openai", "listening", "save", "broadcast"]


def test_personal_source_state_and_filtering_helpers(tmp_path):
    """Personal discovery payload helpers should emit expected state and dedupe behavior."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-state", user_id=7)
    handler.last_fm_user_service = object()
    handler.listenbrainz_user_service = object()

    handler._resolve_user = lambda user_id: SimpleNamespace(
        id=user_id,
        lastfm_username="lfm-user",
        listenbrainz_username="",
    )

    handler.emit_personal_sources_state("sid-state")

    emitted = [entry for entry in socketio.events if entry[0] == "personal_sources_state"][-1]
    payload = emitted[1]
    assert payload["lastfm"]["enabled"] is True
    assert payload["listenbrainz"]["enabled"] is False

    deduped = handler._dedupe_names(["Beyonce", "Beyoncé", "  ", "Bjork"])
    assert deduped == ["Beyonce", "Bjork"]

    filtered, skipped = handler._filter_existing_seed_artists(["A", "B"], {"a"})
    assert filtered == ["B"]
    assert skipped == ["A"]
    assert handler._format_skipped_seed_message(["A"], "AI suggestion") == "A is already in your Lidarr library."

    session.recommended_artists = [{"Name": "A", "Status": ""}]
    handler._refresh_recommended_artist_status(session, "sid-state", "A", "Added")
    assert session.recommended_artists[0]["Status"] == "Added"


def test_lidarr_add_payload_and_failure_mapping(tmp_path):
    """Lidarr payload and failure mapping helpers should produce stable frontend statuses."""

    handler, _ = _make_handler(tmp_path)
    handler.root_folder_path = "/music"
    handler.quality_profile_id = 11
    handler.metadata_profile_id = 22
    handler.lidarr_monitored = True
    handler.search_for_missing_albums = False
    handler.lidarr_monitor_option = "future"
    handler.lidarr_albums_to_monitor = ["a1", "a2"]
    handler.lidarr_monitor_new_items = "new"

    payload = handler._build_lidarr_add_payload("Artist", "Artist", "mbid-1")
    assert payload["qualityProfileId"] == 11
    assert payload["metadataProfileId"] == 22
    assert payload["addOptions"]["monitor"] == "future"
    assert payload["monitorNewItems"] == "new"

    handler.dry_run_adding_to_lidarr = True
    body, parsed, message = handler._extract_lidarr_error_message(None)
    assert "Dry-run mode" in body
    assert parsed is None
    assert "Dry-run mode" in message

    handler.dry_run_adding_to_lidarr = False
    status_already = handler._resolve_lidarr_add_failure_status(
        "Artist",
        "Artist",
        400,
        _Response(text="err", payload=[{"errorMessage": "already been added"}]),
    )
    status_invalid = handler._resolve_lidarr_add_failure_status(
        "Artist",
        "Artist",
        400,
        _Response(text="err", payload={"message": "Invalid Path"}),
    )
    status_unknown = handler._resolve_lidarr_add_failure_status(
        "Artist",
        "Artist",
        500,
        _Response(text="unknown", payload=ValueError("bad json")),
    )

    assert status_already == "Already in Lidarr"
    assert status_invalid == "Invalid Path"
    assert status_unknown == FAILED_TO_ADD_STATUS


def test_artist_permission_validation_and_recording(tmp_path):
    """Permission checks and cache updates should synchronize session and global state."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-add")
    session.recommended_artists = [{"Name": "Artist", "Status": ""}]

    assert handler._validate_artist_add_permissions(session, "sid-add", "Artist", FAILED_TO_ADD_STATUS) is False

    session.user_id = 123
    handler._can_add_without_approval = lambda sess: False
    assert handler._validate_artist_add_permissions(session, "sid-add", "Artist", FAILED_TO_ADD_STATUS) is False

    handler._can_add_without_approval = lambda sess: True
    assert handler._validate_artist_add_permissions(session, "sid-add", "Artist", FAILED_TO_ADD_STATUS) is True

    handler._record_added_artist(session, "New Artist")
    assert {"name": "New Artist", "checked": False} in session.lidarr_items
    assert "new artist" in session.cleaned_lidarr_items

    toast_events = [event for event in socketio.events if event[0] == "new_toast_msg"]
    assert len(toast_events) >= 2


def test_stream_seed_artists_success_and_failure(tmp_path, monkeypatch):
    """Seed-streaming helper should emit acknowledgements and final load state for both outcomes."""

    handler, socketio = _make_handler(tmp_path)
    session = handler.ensure_session("sid-stream", user_id=1)

    session.recommended_artists = []
    monkeypatch.setattr(handler, "_iter_artist_payloads_from_names", lambda names, missing=None: iter([
        {"Name": "Artist A", "Status": ""},
        {"Name": "Artist B", "Status": ""},
    ]))
    monkeypatch.setattr(handler, "prepare_similar_artist_candidates", lambda s: setattr(s, "similar_artist_candidates", [1]))

    ok = handler._stream_seed_artists(
        session,
        "sid-stream",
        ["Artist A", "Artist B"],
        ack_event="ack",
        ack_payload={"seeds": ["Artist A"]},
        error_event="err",
        error_message="failed",
        missing_title="Missing",
        missing_message="missing",
        source_log_label="AI",
    )

    assert ok is True
    assert any(event[0] == "ack" for event in socketio.events)
    assert any(event[0] == "initial_load_complete" for event in socketio.events)

    socketio.events.clear()
    session.recommended_artists.clear()
    monkeypatch.setattr(handler, "_iter_artist_payloads_from_names", lambda names, missing=None: iter([]))

    failed = handler._stream_seed_artists(
        session,
        "sid-stream",
        ["Unknown"],
        ack_event="ack",
        ack_payload={"seeds": ["Unknown"]},
        error_event="err",
        error_message="failed",
        missing_title="Missing",
        missing_message="missing",
        source_log_label="AI",
    )

    assert failed is False
    assert any(event[0] == "err" for event in socketio.events)


def test_openai_header_parsing_and_settings_normalization(tmp_path):
    """Header parsing and loaded-settings normalization should enforce valid runtime values."""

    handler, _ = _make_handler(tmp_path)

    assert handler._normalize_openai_headers_field({"X-A": "1"}) == '{"X-A": "1"}'
    assert handler._normalize_openai_headers_field(None) == ""
    assert handler._normalize_openai_headers_field(123) == "123"

    handler.openai_extra_headers = '{"X-Token": "abc", "X-Null": null}'
    assert handler._parse_openai_extra_headers() == {"X-Token": "abc"}

    handler.openai_extra_headers = "[]"
    assert handler._parse_openai_extra_headers() == {}

    defaults = handler._default_settings()
    handler.lidarr_monitored = "not-bool"
    handler.lidarr_albums_to_monitor = "one,two"
    handler.similar_artist_batch_size = "0"
    handler.openai_max_seed_artists = "bad"
    handler.lidarr_api_timeout = "bad"
    handler._normalize_loaded_settings(defaults)

    assert handler.lidarr_monitored is True
    assert handler.lidarr_albums_to_monitor == ["one", "two"]
    assert handler.similar_artist_batch_size == defaults["similar_artist_batch_size"]
    assert handler.openai_max_seed_artists == defaults["openai_max_seed_artists"]
    assert handler.lidarr_api_timeout == float(defaults["lidarr_api_timeout"])


def test_misc_helpers_for_counts_and_env_overrides(tmp_path, monkeypatch):
    """Formatting and environment helper wrappers should return predictable types."""

    handler, _ = _make_handler(tmp_path)

    assert handler.format_numbers(999) == "999"
    assert handler.format_numbers(12_300) == "12.3K"
    assert handler.format_numbers(2_000_000) == "2.0M"

    values = {
        "flag_true": "true",
        "flag_bad": "bad",
        "i_good": "4",
        "i_bad": "x",
        "f_good": "2.5",
        "f_bad": "x",
    }
    handler._env = lambda key: values.get(key, "")

    assert handler._env_bool_or_empty("flag_true") is True
    assert handler._env_bool_or_empty("flag_bad") == ""
    assert handler._env_int_or_empty("i_good") == 4
    assert handler._env_int_or_empty("i_bad") == ""
    assert handler._env_float_or_empty("f_good") == 2.5
    assert handler._env_float_or_empty("f_bad") == ""
