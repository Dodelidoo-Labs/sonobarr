from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request, redirect
from flask_login import current_user

from ..extensions import db
from ..models import ArtistRequest, User


bp = Blueprint("api", __name__, url_prefix="/api")

_ERROR_KEY_INVALID = {"error": "Invalid API key"}
_ERROR_INTERNAL = {"error": "Internal server error"}


def _normalize_api_key(key_value):
    if key_value is None:
        return None
    return str(key_value).strip()


def _configured_api_key():
    configured_key = current_app.config.get("API_KEY")
    if configured_key:
        return _normalize_api_key(configured_key)

    data_handler = current_app.extensions.get("data_handler")
    if data_handler is not None:
        derived_key = getattr(data_handler, "api_key", None)
        return _normalize_api_key(derived_key)
    return None


def _resolve_request_api_key():
    header_key = request.headers.get("X-API-Key")
    if header_key is not None:
        return _normalize_api_key(header_key)

    header_key_alt = request.headers.get("X-Api-Key")
    if header_key_alt is not None:
        return _normalize_api_key(header_key_alt)

    query_key = request.args.get("api_key") or request.args.get("key")
    return _normalize_api_key(query_key)


def api_key_required(view):
    """Decorator to require API key for API endpoints."""
    from functools import wraps
    
    @wraps(view)
    def wrapped(*args, **kwargs):
        api_key = _resolve_request_api_key()
        configured_key = _configured_api_key()

        if configured_key and configured_key != api_key:
            return jsonify(_ERROR_KEY_INVALID), 401

        return view(*args, **kwargs)

    return wrapped


@bp.route("/")
def api_docs_index():
    """Redirect to interactive API documentation UI."""
    return redirect("/api/docs/", code=302)


@bp.route("/status")
@api_key_required
def status():
    """Get basic system status information
    ---
    tags:
      - System
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Service status
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
            version:
              type: string
              example: "1.0.0"
            users:
              type: object
              properties:
                total:
                  type: integer
                admins:
                  type: integer
            artist_requests:
              type: object
              properties:
                total:
                  type: integer
                pending:
                  type: integer
            services:
              type: object
              properties:
                lidarr_connected:
                  type: boolean
      401:
        description: Missing or invalid API key
      500:
        description: Internal server error
    """
    try:
        user_count = User.query.count()
        admin_count = User.query.filter_by(is_admin=True).count()
        pending_requests = ArtistRequest.query.filter_by(status="pending").count()
        total_requests = ArtistRequest.query.count()

        # Get data handler for Lidarr status
        data_handler = current_app.extensions.get("data_handler")
        lidarr_connected = False
        llm_connected = False
        if data_handler:
            # Simple check - if we have cached Lidarr data, assume connected
            lidarr_connected = bool(data_handler.cached_lidarr_names)
            llm_connected = bool(getattr(data_handler, "openai_recommender", None))

        return jsonify(
            {
                "status": "healthy",
                "version": current_app.config.get("APP_VERSION", "unknown"),
                "users": {"total": user_count, "admins": admin_count},
                "artist_requests": {"total": total_requests, "pending": pending_requests},
                "services": {
                    "lidarr_connected": lidarr_connected,
                    "llm_connected": llm_connected,
                },
            }
        )
    except Exception as e:
        current_app.logger.error(f"API status error: {e}")
        return jsonify(_ERROR_INTERNAL), 500


@bp.route("/artist-requests")
@api_key_required
def artist_requests():
    """Get artist requests with optional filtering
    ---
    tags:
      - Artist Requests
    security:
      - ApiKeyAuth: []
    parameters:
      - in: query
        name: status
        type: string
        enum: [pending, approved, rejected]
        required: false
        description: Filter requests by status
      - in: query
        name: limit
        type: integer
        default: 50
        minimum: 1
        maximum: 100
        required: false
        description: Maximum number of requests to return (max 100)
    responses:
      200:
        description: A list of artist requests
        schema:
          type: object
          properties:
            count:
              type: integer
            requests:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  artist_name:
                    type: string
                  status:
                    type: string
                  requested_by:
                    type: string
                  created_at:
                    type: string
                    format: date-time
                  approved_by:
                    type: string
                  approved_at:
                    type: string
                    format: date-time
      401:
        description: Missing or invalid API key
      500:
        description: Internal server error
    """
    try:
        status_filter = request.args.get("status")  # pending, approved, rejected
        limit = min(int(request.args.get("limit", 50)), 100)  # Max 100

        query = ArtistRequest.query

        if status_filter:
            query = query.filter_by(status=status_filter)

        requests = query.order_by(ArtistRequest.created_at.desc()).limit(limit).all()

        result = []
        for req in requests:
            result.append(
                {
                    "id": req.id,
                    "artist_name": req.artist_name,
                    "status": req.status,
                    "requested_by": req.requested_by.name if req.requested_by else "Unknown",
                    "created_at": req.created_at.isoformat() if req.created_at else None,
                    "approved_by": req.approved_by.name if req.approved_by else None,
                    "approved_at": req.approved_at.isoformat() if req.approved_at else None,
                }
            )

        return jsonify({"count": len(result), "requests": result})
    except Exception as e:
        current_app.logger.error(f"API artist-requests error: {e}")
        return jsonify(_ERROR_INTERNAL), 500


@bp.route("/stats")
@api_key_required
def stats():
    """Get detailed statistics
    ---
    tags:
      - Statistics
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Aggregated statistics
        schema:
          type: object
          properties:
            users:
              type: object
              properties:
                total:
                  type: integer
                admins:
                  type: integer
                active:
                  type: integer
            artist_requests:
              type: object
              properties:
                total:
                  type: integer
                pending:
                  type: integer
                approved:
                  type: integer
                rejected:
                  type: integer
                recent_week:
                  type: integer
            top_requesters:
              type: array
              items:
                type: object
                properties:
                  username:
                    type: string
                  requests:
                    type: integer
      401:
        description: Missing or invalid API key
      500:
        description: Internal server error
    """
    try:
        # User stats
        total_users = User.query.count()
        admin_users = User.query.filter_by(is_admin=True).count()
        active_users = User.query.filter_by(is_active=True).count()

        # Request stats
        total_requests = ArtistRequest.query.count()
        pending_requests = ArtistRequest.query.filter_by(status="pending").count()
        approved_requests = ArtistRequest.query.filter_by(status="approved").count()
        rejected_requests = ArtistRequest.query.filter_by(status="rejected").count()

        # Recent activity (last 7 days)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_requests = (
            ArtistRequest.query.filter(ArtistRequest.created_at >= week_ago).count()
        )

        # Top requesters
        from sqlalchemy import func

        top_requesters = (
            db.session.query(
                User.username, func.count(ArtistRequest.id).label("request_count")
            )
            .join(ArtistRequest, User.id == ArtistRequest.requested_by_id)
            .group_by(User.id, User.username)
            .order_by(func.count(ArtistRequest.id).desc())
            .limit(5)
            .all()
        )

        return jsonify(
            {
                "users": {
                    "total": total_users,
                    "admins": admin_users,
                    "active": active_users,
                },
                "artist_requests": {
                    "total": total_requests,
                    "pending": pending_requests,
                    "approved": approved_requests,
                    "rejected": rejected_requests,
                    "recent_week": recent_requests,
                },
                "top_requesters": [
                    {"username": username, "requests": count}
                    for username, count in top_requesters
                ],
            }
        )
    except Exception as e:
        current_app.logger.error(f"API stats error: {e}")
        return jsonify(_ERROR_INTERNAL), 500
