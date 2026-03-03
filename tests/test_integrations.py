"""Tests for Last.fm and ListenBrainz integration services."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sonobarr_app.services.integrations.lastfm_user import LastFmUserArtist, LastFmUserService
from sonobarr_app.services.integrations.listenbrainz_user import (
    ListenBrainzIntegrationError,
    ListenBrainzUserService,
)


class _LBResponse:
    """Minimal HTTP response object for ListenBrainz tests."""

    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _LBSession:
    """Simple request session double keyed by URL fragments."""

    def __init__(self, responses):
        self._responses = responses

    def get(self, url, timeout):
        for key, value in self._responses.items():
            if key in url:
                return value
        raise AssertionError(f"Unexpected URL: {url}")


def test_lastfm_top_artists_and_recommendations(monkeypatch):
    """Service should parse top artists and dedupe recommendations from similar artists."""

    top_entries = [
        SimpleNamespace(item=SimpleNamespace(name="A"), weight="10"),
        SimpleNamespace(item=SimpleNamespace(name="B"), weight="5"),
    ]

    rel_a = [
        SimpleNamespace(item=SimpleNamespace(name="C"), match="0.9"),
        SimpleNamespace(item=SimpleNamespace(name="A"), match="0.8"),
    ]
    rel_b = [
        SimpleNamespace(item=SimpleNamespace(name="D"), match="0.7"),
        SimpleNamespace(item=SimpleNamespace(name="C"), match="0.6"),
    ]

    class _ArtistResolver:
        def __init__(self, mapping):
            self.mapping = mapping

        def get_similar(self):
            return self.mapping

    network = SimpleNamespace(
        get_user=lambda username: SimpleNamespace(get_top_artists=lambda limit: top_entries),
        get_artist=lambda name: _ArtistResolver(rel_a if name == "A" else rel_b),
    )

    service = LastFmUserService("key", "secret")
    monkeypatch.setattr(service, "_client", lambda: network)

    top = service.get_top_artists("user", limit=10)
    recs = service.get_recommended_artists("user", limit=10)

    assert [item.name for item in top] == ["A", "B"]
    assert [item.playcount for item in top] == [10, 5]
    assert [item.name for item in recs] == ["C", "D"]


def test_lastfm_handles_invalid_payloads():
    """Service helper methods should remain defensive for malformed relation objects."""

    service = LastFmUserService("key", "secret")
    bad_name, bad_score = service._parse_similarity_candidate(object())
    assert bad_name == ""
    assert bad_score is None

    assert service.get_top_artists("", limit=5) == []
    assert service.get_recommended_artists("", limit=5) == []


def test_lastfm_client_and_recommendation_edge_paths(monkeypatch):
    """Last.fm helper methods should handle constructor wiring and malformed top entries."""

    created_kwargs = {}

    class _FakeNetwork:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

        def get_artist(self, _name):
            raise RuntimeError("boom")

    monkeypatch.setattr("sonobarr_app.services.integrations.lastfm_user.pylast.LastFMNetwork", _FakeNetwork)

    service = LastFmUserService("k", "s")
    network = service._client()
    assert created_kwargs == {"api_key": "k", "api_secret": "s"}
    assert service._safe_get_similar(network, "Any") == []

    top_entries = [SimpleNamespace(item=SimpleNamespace(name=""))]
    assert service._collect_recommendations(network, top_entries, set(), limit=1) == []


def test_lastfm_recommendations_fallback_to_empty_on_transport_failure(monkeypatch):
    """Recommendation fetch should return an empty list when provider calls fail."""

    service = LastFmUserService("key", "secret")
    monkeypatch.setattr(service, "_client", lambda: (_ for _ in ()).throw(RuntimeError("network down")))
    assert service.get_recommended_artists("user", limit=20) == []


def test_lastfm_collect_recommendations_returns_early_at_limit():
    """Recommendation aggregation should stop once the configured limit has been reached."""

    rel = [
        SimpleNamespace(item=SimpleNamespace(name="Candidate A"), match="0.9"),
        SimpleNamespace(item=SimpleNamespace(name="Candidate B"), match="0.8"),
    ]

    class _Network:
        def get_artist(self, _name):
            return SimpleNamespace(get_similar=lambda: rel)

    top_entries = [SimpleNamespace(item=SimpleNamespace(name="Seed Artist"))]
    service = LastFmUserService("k", "s")
    recs = service._collect_recommendations(_Network(), top_entries, {"Seed Artist"}, limit=1)
    assert len(recs) == 1


def test_listenbrainz_weekly_exploration_flow():
    """Service should extract weekly exploration playlist artists and dedupe names."""

    list_payload = {
        "playlists": [
            {
                "playlist": {
                    "identifier": ["https://listenbrainz.org/playlist/abc123/"],
                    "extension": {
                        "https://musicbrainz.org/doc/jspf#playlist": {
                            "additional_metadata": {
                                "algorithm_metadata": {
                                    "source_patch": "weekly-exploration",
                                }
                            }
                        }
                    },
                }
            }
        ]
    }

    playlist_payload = {
        "playlist": {
            "track": [
                {
                    "extension": {
                        "https://musicbrainz.org/doc/jspf#track": {
                            "additional_metadata": {
                                "artists": [
                                    {"artist_credit_name": "Artist One"},
                                    {"name": "Artist Two"},
                                ]
                            }
                        }
                    }
                },
                {"creator": "Artist One"},
            ]
        }
    }

    session = _LBSession(
        {
            "createdfor": _LBResponse(200, list_payload),
            "/playlist/abc123": _LBResponse(200, playlist_payload),
        }
    )
    service = ListenBrainzUserService(session=session)

    result = service.get_weekly_exploration_artists("listener")

    assert result.artists == ["Artist One", "Artist Two"]


def test_listenbrainz_validation_and_error_paths():
    """Service should return empty results for blank usernames and raise for invalid payloads."""

    service = ListenBrainzUserService(session=_LBSession({}))
    assert service.get_weekly_exploration_artists(" ").artists == []

    broken_session = _LBSession({"createdfor": _LBResponse(500, {})})
    broken = ListenBrainzUserService(session=broken_session)
    with pytest.raises(ListenBrainzIntegrationError):
        broken._find_weekly_exploration_playlist("user")

    invalid_json_session = _LBSession(
        {"createdfor": _LBResponse(200, json.JSONDecodeError("bad", "{}", 0))}
    )
    invalid = ListenBrainzUserService(session=invalid_json_session)
    with pytest.raises(ListenBrainzIntegrationError):
        invalid._find_weekly_exploration_playlist("user")

    assert ListenBrainzUserService._normalise_identifier(["https://a/b/c/"]) == "c"
    assert ListenBrainzUserService._normalise_identifier(None) == ""


def test_listenbrainz_playlist_discovery_and_parse_edge_paths():
    """ListenBrainz should skip non-weekly playlists and surface playlist payload JSON errors."""

    no_weekly_payload = {
        "playlists": [
            {
                "playlist": {
                    "identifier": ["https://listenbrainz.org/playlist/not-weekly/"],
                    "extension": {
                        "https://musicbrainz.org/doc/jspf#playlist": {
                            "additional_metadata": {
                                "algorithm_metadata": {
                                    "source_patch": "other-feed",
                                }
                            }
                        }
                    },
                }
            }
        ]
    }
    no_weekly_service = ListenBrainzUserService(
        session=_LBSession({"createdfor": _LBResponse(200, no_weekly_payload)})
    )
    assert no_weekly_service.get_weekly_exploration_artists("listener").artists == []

    missing_identifier_payload = {
        "playlists": [
            {
                "playlist": {
                    "extension": {
                        "https://musicbrainz.org/doc/jspf#playlist": {
                            "additional_metadata": {"algorithm_metadata": {"source_patch": "weekly-exploration"}}
                        }
                    }
                }
            }
        ]
    }
    missing_identifier = ListenBrainzUserService(
        session=_LBSession({"createdfor": _LBResponse(200, missing_identifier_payload)})
    )
    assert missing_identifier._find_weekly_exploration_playlist("listener") is None

    invalid_playlist_json = ListenBrainzUserService(
        session=_LBSession({"playlist/abc": _LBResponse(200, json.JSONDecodeError("bad", "{}", 0))})
    )
    with pytest.raises(ListenBrainzIntegrationError):
        invalid_playlist_json._fetch_playlist_artists("abc")
