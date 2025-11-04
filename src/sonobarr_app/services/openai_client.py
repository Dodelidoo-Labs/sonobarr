import json
import re
from typing import Any, List, Mapping, Optional, Sequence

from openai import OpenAI
from openai import OpenAIError


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_MAX_SEED_ARTISTS = 5
DEFAULT_OPENAI_TIMEOUT = 60.0

_SYSTEM_PROMPT = (
    "You are Sonobarr's music discovery assistant. "
    "Given a user request about music tastes, moods, genres, or artists, "
    "respond with a JSON array of up to {max_artists} artist names that best match the request. "
    "Only return the JSON array, with each artist as a string. "
    "The artists should be discoverable on major streaming services and ideally not already present in the provided library list."
)


class OpenAIRecommender:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None = None,
        base_url: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        max_seed_artists: int = DEFAULT_MAX_SEED_ARTISTS,
        timeout: float | None = DEFAULT_OPENAI_TIMEOUT,
        temperature: float | None = 0.7,
    ) -> None:
        self.timeout = timeout
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
        }
        if api_key is not None:
            client_kwargs["api_key"] = api_key or None
        if base_url:
            client_kwargs["base_url"] = base_url
        if default_headers:
            client_kwargs["default_headers"] = dict(default_headers)
        self.client = OpenAI(**client_kwargs)
        self.model = model or DEFAULT_OPENAI_MODEL
        self.max_seed_artists = max_seed_artists
        self.temperature = temperature
        self.base_url = base_url
        self.default_headers = dict(default_headers) if default_headers else {}

    @staticmethod
    def _iter_fenced_code_blocks(text: str):
        start = 0
        text_length = len(text)
        while start < text_length:
            open_idx = text.find("```", start)
            if open_idx == -1:
                return
            label_start = open_idx + 3
            label_end = label_start
            while label_end < text_length and text[label_end] not in ("\n", "\r"):
                label_end += 1
            label = text[label_start:label_end].strip().lower()
            content_start = label_end
            if content_start < text_length and text[content_start] == "\r":
                content_start += 1
            if content_start < text_length and text[content_start] == "\n":
                content_start += 1
            close_idx = text.find("```", content_start)
            if close_idx == -1:
                return
            yield label, text[content_start:close_idx]
            start = close_idx + 3

    def _extract_from_fenced_blocks(self, content: str) -> Optional[str]:
        for label, block in self._iter_fenced_code_blocks(content):
            if label and label != "json":
                continue
            candidate = block.strip()
            if candidate.startswith("["):
                return candidate
        return None

    @staticmethod
    def _find_first_json_array(content: str) -> Optional[str]:
        content_stripped = content.strip()
        if content_stripped.startswith("["):
            return content_stripped

        decoder = json.JSONDecoder()
        text_length = len(content)
        idx = 0
        while idx < text_length:
            if content[idx] != "[":
                idx += 1
                continue
            try:
                parsed, end = decoder.raw_decode(content[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            if isinstance(parsed, list):
                return content[idx : idx + end]
            idx += 1
        return None

    def _extract_array_fragment(self, content: str) -> Optional[str]:
        if not content:
            return None

        candidate = self._extract_from_fenced_blocks(content)
        if candidate:
            return candidate

        return self._find_first_json_array(content)

    def _build_prompts(self, prompt: str, existing_artists: Sequence[str]) -> tuple[str, str]:
        system_prompt = _SYSTEM_PROMPT.format(max_artists=self.max_seed_artists)
        existing_preview = ", ".join(existing_artists[:50]) if existing_artists else "None provided."
        user_prompt = (
            "User request:\n"
            f"{prompt.strip()}\n\n"
            "Artists already in the library:\n"
            f"{existing_preview}"
        )
        return system_prompt, user_prompt

    def _prepare_request(self, system_prompt: str, user_prompt: str) -> dict:
        request_kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.temperature is not None:
            request_kwargs["temperature"] = self.temperature
        return request_kwargs

    def _execute_request(self, request_kwargs: dict):
        attempts = 2
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                return self.client.chat.completions.create(**request_kwargs)
            except OpenAIError as exc:  # pragma: no cover - network failure path
                message = str(exc)
                last_exc = exc
                if (
                    "temperature" in message.lower()
                    and "unsupported" in message.lower()
                    and request_kwargs.pop("temperature", None) is not None
                ):
                    continue
                if "timed out" in message.lower() and attempt + 1 < attempts:
                    continue
                raise RuntimeError(message) from exc
        if last_exc is not None:  # pragma: no cover - defensive
            raise RuntimeError(str(last_exc)) from last_exc
        raise RuntimeError("LLM request failed without response")  # pragma: no cover - defensive

    @staticmethod
    def _extract_response_content(response) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError) as exc:
            raise RuntimeError("Unexpected response format from the LLM provider.") from exc
        return content or ""

    def _load_json_payload(self, array_fragment: str):
        try:
            return json.loads(array_fragment)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "The LLM response was not valid JSON. "
                "Please try rephrasing your request."
            ) from exc

    @staticmethod
    def _coerce_artist_entries(raw_data):
        if isinstance(raw_data, list):
            return raw_data
        if isinstance(raw_data, dict):
            candidate_list = raw_data.get("artists") or raw_data.get("seeds")
            if isinstance(candidate_list, list):
                return candidate_list
        raise RuntimeError("The LLM response JSON was not a list of artists.")

    @staticmethod
    def _normalize_artist_entry(item) -> Optional[str]:
        if isinstance(item, str):
            candidate = item.strip()
            return candidate or None
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                candidate = name.strip()
                return candidate or None
        return None

    def _dedupe_and_limit(self, items: Sequence) -> List[str]:
        seeds: List[str] = []
        seen: set[str] = set()
        for item in items:
            artist = self._normalize_artist_entry(item)
            if not artist:
                continue
            lower_name = artist.lower()
            if lower_name in seen:
                continue
            seeds.append(artist)
            seen.add(lower_name)
            if len(seeds) >= self.max_seed_artists:
                break
        return seeds

    def generate_seed_artists(
        self,
        prompt: str,
        existing_artists: Sequence[str] | None = None,
    ) -> List[str]:
        catalog_artists = existing_artists or []
        system_prompt, user_prompt = self._build_prompts(prompt, catalog_artists)
        request_kwargs = self._prepare_request(system_prompt, user_prompt)
        response = self._execute_request(request_kwargs)

        content = self._extract_response_content(response).strip()
        if not content:
            return []

        array_fragment = self._extract_array_fragment(content)
        if not array_fragment:
            raise RuntimeError(
                "The LLM response did not include a JSON array of artist names. "
                "Please try rephrasing your request."
            )

        raw_payload = self._load_json_payload(array_fragment)
        normalized_items = self._coerce_artist_entries(raw_payload)
        return self._dedupe_and_limit(normalized_items)
