"""Tests for the GitHub release metadata client."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from sonobarr_app.services.releases import ReleaseClient


class _Response:
    """Minimal response double that mimics requests.Response."""

    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_release_client_uses_cached_payload(monkeypatch):
    """Client should reuse cached data while within the TTL window."""

    logger = logging.getLogger("test-release-cache")
    client = ReleaseClient("owner/repo", "ua", ttl_seconds=60, logger=logger)
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return _Response(200, {"tag_name": "v1.2.3", "html_url": "https://example.com/release"})

    monkeypatch.setattr("sonobarr_app.services.releases.requests.get", fake_get)
    monkeypatch.setattr("sonobarr_app.services.releases.time.time", lambda: 1000.0)
    first = client.fetch_latest()

    monkeypatch.setattr("sonobarr_app.services.releases.time.time", lambda: 1010.0)
    second = client.fetch_latest()

    assert first["tag_name"] == "v1.2.3"
    assert second["tag_name"] == "v1.2.3"
    assert len(calls) == 1


def test_release_client_handles_non_200(monkeypatch):
    """Client should return fallback link and an error message on failed responses."""

    logger = logging.getLogger("test-release-error")
    client = ReleaseClient("owner/repo", "ua", ttl_seconds=60, logger=logger)

    monkeypatch.setattr(
        "sonobarr_app.services.releases.requests.get",
        lambda url, headers, timeout: _Response(503, {}),
    )
    monkeypatch.setattr("sonobarr_app.services.releases.time.time", lambda: 2000.0)

    info = client.fetch_latest(force=True)

    assert info["tag_name"] is None
    assert info["html_url"] == "https://github.com/owner/repo/releases"
    assert "status 503" in info["error"]


def test_release_client_handles_exceptions(monkeypatch):
    """Client should translate transport exceptions into cached error metadata."""

    logger = logging.getLogger("test-release-exception")
    client = ReleaseClient("owner/repo", "ua", ttl_seconds=60, logger=logger)

    def raise_error(url, headers, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr("sonobarr_app.services.releases.requests.get", raise_error)
    monkeypatch.setattr("sonobarr_app.services.releases.time.time", lambda: 3000.0)

    info = client.fetch_latest(force=True)

    assert info["tag_name"] is None
    assert info["html_url"] == "https://github.com/owner/repo/releases"
    assert "network down" in info["error"]
