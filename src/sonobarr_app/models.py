from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    oidc_id = db.Column(db.String(256), unique=True, nullable=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    display_name = db.Column(db.String(120), nullable=True)
    avatar_url = db.Column(db.String(512), nullable=True)
    lastfm_username = db.Column(db.String(120), nullable=True)
    listenbrainz_username = db.Column(db.String(120), nullable=True)

    # Per-user API keys (optional - fall back to global if not set)
    lastfm_api_key = db.Column(db.String(256), nullable=True)
    lastfm_api_secret = db.Column(db.String(256), nullable=True)
    youtube_api_key = db.Column(db.String(256), nullable=True)
    openai_api_key = db.Column(db.String(512), nullable=True)
    openai_api_base = db.Column(db.String(512), nullable=True)
    openai_model = db.Column(db.String(128), nullable=True)
    openai_extra_headers = db.Column(db.Text, nullable=True)
    openai_max_seed_artists = db.Column(db.Integer, nullable=True)

    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    @property
    def name(self) -> str:
        return self.display_name or self.username

    def __repr__(self) -> str:  # pragma: no cover - representation helper
        return f"<User id={self.id} username={self.username!r} admin={self.is_admin}>"


class ArtistRequest(db.Model):
    __tablename__ = "artist_requests"

    id = db.Column(db.Integer, primary_key=True)
    artist_name = db.Column(db.String(255), nullable=False, index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    requested_by = db.relationship("User", foreign_keys=[requested_by_id], backref="requested_artists")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id], backref="approved_requests")

    def __repr__(self) -> str:  # pragma: no cover - representation helper
        return f"<ArtistRequest id={self.id} artist='{self.artist_name}' status={self.status}>"
