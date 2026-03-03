"""Tests for Socket.IO handler registration and authorization behavior."""

from __future__ import annotations

from types import SimpleNamespace

import sonobarr_app.sockets as sockets_module
from sonobarr_app.sockets import register_socketio_handlers


class _FakeSocketIO:
    """Socket.IO replacement storing handlers and emitted events for assertions."""

    def __init__(self):
        self.handlers = {}
        self.emitted = []
        self.tasks = []

    def on(self, event_name):
        def decorator(func):
            self.handlers[event_name] = func
            return func

        return decorator

    def emit(self, event, payload=None, room=None):
        self.emitted.append((event, payload, room))

    def start_background_task(self, func, *args):
        self.tasks.append((func.__name__, args))


class _FakeDataHandler:
    """Data handler double exposing the methods invoked by socket handlers."""

    def __init__(self):
        self.calls = []
        self.logger = SimpleNamespace(exception=lambda *args, **kwargs: None)

    def connection(self, *args):
        self.calls.append(("connection", args))

    def remove_session(self, sid):
        self.calls.append(("remove_session", sid))

    def side_bar_opened(self, sid):
        self.calls.append(("side_bar_opened", sid))

    def get_artists_from_lidarr(self, sid):
        self.calls.append(("get_artists_from_lidarr", sid))

    def start(self, sid, selected):
        self.calls.append(("start", sid, selected))

    def ai_prompt(self, sid, prompt):
        self.calls.append(("ai_prompt", sid, prompt))

    def emit_personal_sources_state(self, sid):
        self.calls.append(("emit_personal_sources_state", sid))

    def personal_recommendations(self, sid, source):
        self.calls.append(("personal_recommendations", sid, source))

    def stop(self, sid):
        self.calls.append(("stop", sid))

    def find_similar_artists(self, sid):
        self.calls.append(("find_similar_artists", sid))

    def add_artists(self, sid, name):
        self.calls.append(("add_artists", sid, name))

    def request_artist(self, sid, name):
        self.calls.append(("request_artist", sid, name))

    def load_settings(self, sid):
        self.calls.append(("load_settings", sid))

    def update_settings(self, payload):
        self.calls.append(("update_settings", payload))

    def save_config_to_file(self):
        self.calls.append(("save_config_to_file",))

    def preview(self, sid, name):
        self.calls.append(("preview", sid, name))

    def prehear(self, sid, name):
        self.calls.append(("prehear", sid, name))


def test_socket_handlers_route_events_and_authorization(monkeypatch):
    """Registered handlers should delegate to the correct data-handler methods."""

    fake_socketio = _FakeSocketIO()
    fake_data_handler = _FakeDataHandler()
    register_socketio_handlers(fake_socketio, fake_data_handler)

    disconnected = []
    monkeypatch.setattr(sockets_module, "disconnect", lambda: disconnected.append(True))
    monkeypatch.setattr(sockets_module, "request", SimpleNamespace(sid="sid-1"))

    monkeypatch.setattr(
        sockets_module,
        "current_user",
        SimpleNamespace(is_authenticated=False, is_admin=False, auto_approve_artist_requests=False, get_id=lambda: None),
    )
    assert fake_socketio.handlers["connect"]() is False
    fake_socketio.handlers["side_bar_opened"]()
    assert disconnected

    monkeypatch.setattr(
        sockets_module,
        "current_user",
        SimpleNamespace(is_authenticated=True, is_admin=True, auto_approve_artist_requests=True, get_id=lambda: "9"),
    )

    fake_socketio.handlers["connect"]()
    fake_socketio.handlers["disconnect"]()
    fake_socketio.handlers["side_bar_opened"]()
    fake_socketio.handlers["personal_sources_poll"]()
    fake_socketio.handlers["stop_req"]()
    fake_socketio.handlers["preview_req"]("artist")
    fake_socketio.handlers["get_lidarr_artists"]()
    fake_socketio.handlers["start_req"](["A"])
    fake_socketio.handlers["ai_prompt_req"]({"prompt": "discover"})
    fake_socketio.handlers["user_recs_req"]({"source": "lastfm"})
    fake_socketio.handlers["load_more_artists"]()
    fake_socketio.handlers["adder"]("A")
    fake_socketio.handlers["request_artist"]("B")
    fake_socketio.handlers["load_settings"]()
    fake_socketio.handlers["update_settings"]({"x": 1})
    fake_socketio.handlers["prehear_req"]("Artist")

    call_names = [entry[0] for entry in fake_data_handler.calls]
    assert "connection" in call_names
    assert "remove_session" in call_names
    assert "side_bar_opened" in call_names
    assert "emit_personal_sources_state" in call_names
    assert "stop" in call_names
    assert "preview" in call_names
    assert "update_settings" in call_names
    assert "save_config_to_file" in call_names
    assert "load_settings" in call_names
    assert len(fake_socketio.tasks) >= 6


def test_socket_admin_restrictions_emit_unauthorized(monkeypatch):
    """Non-admin users should receive unauthorized toasts for settings events."""

    fake_socketio = _FakeSocketIO()
    fake_data_handler = _FakeDataHandler()
    register_socketio_handlers(fake_socketio, fake_data_handler)

    monkeypatch.setattr(sockets_module, "request", SimpleNamespace(sid="sid-2"))
    monkeypatch.setattr(
        sockets_module,
        "current_user",
        SimpleNamespace(is_authenticated=True, is_admin=False, auto_approve_artist_requests=False, get_id=lambda: "2"),
    )

    fake_socketio.handlers["load_settings"]()
    fake_socketio.handlers["update_settings"]({"k": "v"})

    unauthorized = [event for event in fake_socketio.emitted if event[0] == "new_toast_msg"]
    assert len(unauthorized) == 2
    assert "Only administrators" in unauthorized[0][1]["message"]


def test_socket_handlers_accept_non_dict_payloads_and_invalid_user_ids(monkeypatch):
    """Socket handlers should coerce payloads and tolerate non-numeric user identifiers."""

    fake_socketio = _FakeSocketIO()
    fake_data_handler = _FakeDataHandler()
    register_socketio_handlers(fake_socketio, fake_data_handler)

    monkeypatch.setattr(sockets_module, "request", SimpleNamespace(sid="sid-edge"))
    monkeypatch.setattr(
        sockets_module,
        "current_user",
        SimpleNamespace(
            is_authenticated=True,
            is_admin=True,
            auto_approve_artist_requests=False,
            get_id=lambda: "not-a-number",
        ),
    )

    fake_socketio.handlers["connect"]()
    fake_socketio.handlers["ai_prompt_req"]("discover shoegaze")
    fake_socketio.handlers["user_recs_req"]("listenbrainz")

    assert ("connection", ("sid-edge", None, True, False)) in fake_data_handler.calls
    assert ("ai_prompt", ("sid-edge", "discover shoegaze")) in fake_socketio.tasks
    assert ("personal_recommendations", ("sid-edge", "listenbrainz")) in fake_socketio.tasks
