from __future__ import annotations

import threading
from typing import Any

from flask import request
from flask_login import current_user
from flask_socketio import SocketIO, disconnect


def register_socketio_handlers(socketio: SocketIO, data_handler) -> None:
    @socketio.on("connect")
    def handle_connect(auth=None):
        if not current_user.is_authenticated:
            return False
        sid = request.sid
        try:
            identifier = current_user.get_id()
            user_id = int(identifier) if identifier is not None else None
        except (TypeError, ValueError):
            user_id = None
        data_handler.connection(
            sid,
            user_id,
            current_user.is_admin,
            getattr(current_user, "auto_approve_artist_requests", False),
        )

    @socketio.on("disconnect")
    def handle_disconnect():
        data_handler.remove_session(request.sid)

    @socketio.on("side_bar_opened")
    def handle_side_bar_opened():
        if not current_user.is_authenticated:
            disconnect()
            return
        data_handler.side_bar_opened(request.sid)

    @socketio.on("get_lidarr_artists")
    def handle_get_lidarr_artists():
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid

        socketio.start_background_task(data_handler.get_artists_from_lidarr, sid)

    @socketio.on("start_req")
    def handle_start_req(selected_artists: Any):
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        selected = list(selected_artists or [])

        socketio.start_background_task(data_handler.start, sid, selected)

    @socketio.on("ai_prompt_req")
    def handle_ai_prompt(payload: Any):
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        if isinstance(payload, dict):
            prompt = payload.get("prompt", "")
        else:
            prompt = str(payload or "")
        socketio.start_background_task(data_handler.ai_prompt, sid, prompt)

    @socketio.on("personal_sources_poll")
    def handle_personal_sources_poll():
        if not current_user.is_authenticated:
            disconnect()
            return
        data_handler.emit_personal_sources_state(request.sid)

    @socketio.on("user_recs_req")
    def handle_user_recs(payload: Any):
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        if isinstance(payload, dict):
            source = payload.get("source", "")
        else:
            source = str(payload or "")
        socketio.start_background_task(data_handler.personal_recommendations, sid, source)

    @socketio.on("stop_req")
    def handle_stop_req():
        if not current_user.is_authenticated:
            disconnect()
            return
        data_handler.stop(request.sid)

    @socketio.on("load_more_artists")
    def handle_load_more():
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        socketio.start_background_task(data_handler.find_similar_artists, sid)

    @socketio.on("adder")
    def handle_add_artist(raw_artist_name: str):
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        socketio.start_background_task(data_handler.add_artists, sid, raw_artist_name)

    @socketio.on("request_artist")
    def handle_request_artist(raw_artist_name: str):
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        socketio.start_background_task(data_handler.request_artist, sid, raw_artist_name)

    @socketio.on("load_settings")
    def handle_load_settings():
        if not current_user.is_authenticated:
            disconnect()
            return
        if not current_user.is_admin:
            socketio.emit(
                "new_toast_msg",
                {
                    "title": "Unauthorized",
                    "message": "Only administrators can view settings.",
                },
                room=request.sid,
            )
            return
        data_handler.load_settings(request.sid)

    @socketio.on("update_settings")
    def handle_update_settings(payload: dict):
        if not current_user.is_authenticated:
            disconnect()
            return
        if not current_user.is_admin:
            socketio.emit(
                "new_toast_msg",
                {
                    "title": "Unauthorized",
                    "message": "Only administrators can modify settings.",
                },
                room=request.sid,
            )
            return
        try:
            data_handler.update_settings(payload)
            data_handler.save_config_to_file()
            data_handler.load_settings(request.sid)
            socketio.emit(
                "settingsSaved",
                {"message": "Configuration updated successfully."},
                room=request.sid,
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            # Ensure exceptions are logged and surfaced to the UI without leaking sensitive details
            data_handler.logger.exception("Failed to persist settings: %s", exc)
            socketio.emit(
                "settingsSaveError",
                {
                    "message": "Saving settings failed. Check the server logs for details.",
                },
                room=request.sid,
            )

    @socketio.on("preview_req")
    def handle_preview(raw_artist_name: str):
        if not current_user.is_authenticated:
            disconnect()
            return
        data_handler.preview(request.sid, raw_artist_name)

    @socketio.on("prehear_req")
    def handle_prehear(raw_artist_name: str):
        if not current_user.is_authenticated:
            disconnect()
            return
        sid = request.sid
        socketio.start_background_task(data_handler.prehear, sid, raw_artist_name)
