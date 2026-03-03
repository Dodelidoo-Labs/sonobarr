"""Tests for OpenAI recommendation client parsing and request behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sonobarr_app.services import openai_client
from sonobarr_app.services.openai_client import OpenAIError, OpenAIRecommender


class _FakeCompletions:
    """Chat completion double with programmable outcomes."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeOpenAI:
    """OpenAI client constructor double used to capture initialization args."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions([]))


def _response(content: str):
    """Build a minimal OpenAI-like response object."""

    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_client_initialization_and_prompt_building(monkeypatch):
    """Recommender should build prompts and client kwargs from constructor settings."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(
        api_key="secret",
        model="custom-model",
        base_url="https://llm.example/v1",
        default_headers={"X-Test": "1"},
        max_seed_artists=7,
        temperature=0.2,
    )

    system_prompt, user_prompt = recommender._build_prompts("  synthwave  ", ["A", "B"])
    request_kwargs = recommender._prepare_request(system_prompt, user_prompt)

    assert recommender.client.kwargs["api_key"] == "secret"
    assert recommender.client.kwargs["base_url"] == "https://llm.example/v1"
    assert recommender.model == "custom-model"
    assert "up to 7 artist names" in system_prompt
    assert "synthwave" in user_prompt
    assert request_kwargs["temperature"] == 0.2


def test_generate_seed_artists_from_fenced_json(monkeypatch):
    """Recommender should extract fenced JSON and dedupe artist names case-insensitively."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret", max_seed_artists=3)
    recommender.client.chat.completions = _FakeCompletions(
        [_response("```json\n[\"Massive Attack\", \"Portishead\", \"massive attack\"]\n```")]
    )

    seeds = recommender.generate_seed_artists("Trip-hop moods")

    assert seeds == ["Massive Attack", "Portishead"]


def test_generate_seed_artists_accepts_object_payload(monkeypatch):
    """Recommender should parse dict payloads that expose artists or seeds arrays."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret", max_seed_artists=2)
    recommender.client.chat.completions = _FakeCompletions(
        [_response('{"artists": [{"name": "Autechre"}, {"name": "Boards of Canada"}, "Autechre"]}')]
    )

    seeds = recommender.generate_seed_artists("IDM")

    assert seeds == ["Autechre", "Boards of Canada"]


def test_execute_request_retries_on_unsupported_temperature(monkeypatch):
    """Recommender should retry without temperature when provider rejects that parameter."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret", temperature=0.5)
    failing = OpenAIError("temperature unsupported")
    completions = _FakeCompletions([failing, _response('["Artist"]')])
    recommender.client.chat.completions = completions

    seeds = recommender.generate_seed_artists("Ambient")

    assert seeds == ["Artist"]
    assert "temperature" in completions.calls[0]
    assert "temperature" not in completions.calls[1]


def test_generate_seed_artists_raises_for_missing_json_array(monkeypatch):
    """Recommender should fail with a clear message when no JSON array is present."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret")
    recommender.client.chat.completions = _FakeCompletions([_response("No structured output")])

    with pytest.raises(RuntimeError, match="did not include a JSON array"):
        recommender.generate_seed_artists("Anything")


def test_client_initialization_allows_keyless_base_url(monkeypatch):
    """Client should inject a placeholder API key when only a base URL is configured."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key=None, base_url="https://llm.internal/v1")
    assert recommender.client.kwargs["api_key"] == "not-provided"
    assert recommender.client.kwargs["base_url"] == "https://llm.internal/v1"


def test_parser_helpers_cover_fenced_and_decoder_edge_paths(monkeypatch):
    """Parser helpers should tolerate malformed fenced blocks and recover from decode errors."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret")

    fenced_blocks = list(recommender._iter_fenced_code_blocks("```json\r\n[\"A\"]\n```"))
    assert fenced_blocks and fenced_blocks[0][0] == "json"

    assert list(recommender._iter_fenced_code_blocks("```json\n[\"A\"]")) == []
    assert recommender._extract_from_fenced_blocks("```python\n[\"A\"]\n```") is None
    assert recommender._extract_array_fragment("") is None

    decoder_error_result = recommender._find_first_json_array("prefix [not-json suffix")
    assert decoder_error_result is None

    raw_decode = openai_client.json.JSONDecoder.raw_decode

    def _fake_raw_decode(self, text):
        if text.startswith("["):
            return {"not": "list"}, 1
        return raw_decode(self, text)

    monkeypatch.setattr(openai_client.json.JSONDecoder, "raw_decode", _fake_raw_decode)
    assert recommender._find_first_json_array("x[1]") is None


def test_payload_and_normalization_error_paths(monkeypatch):
    """Payload parsing helpers should reject invalid formats and skip bad entries."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret", max_seed_artists=3)

    with pytest.raises(RuntimeError, match="Unexpected response format"):
        recommender._extract_response_content(object())

    with pytest.raises(RuntimeError, match="not valid JSON"):
        recommender._load_json_payload("[not json]")

    with pytest.raises(RuntimeError, match="not a list of artists"):
        recommender._coerce_artist_entries({"artists": {"name": "bad"}})

    assert recommender._coerce_artist_entries({"seeds": ["A"]}) == ["A"]

    assert recommender._normalize_artist_entry({"name": 123}) is None

    deduped = recommender._dedupe_and_limit([None, {"name": 123}, "Valid Artist"])
    assert deduped == ["Valid Artist"]


def test_generate_seed_artists_returns_empty_when_response_body_is_blank(monkeypatch):
    """Generation should return an empty list when the provider returns blank content."""

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    recommender = OpenAIRecommender(api_key="secret")
    recommender.client.chat.completions = _FakeCompletions([_response("   ")])
    assert recommender.generate_seed_artists("ambient") == []
