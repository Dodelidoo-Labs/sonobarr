from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pylast


@dataclass
class LastFmUserArtist:
    name: str
    playcount: int
    match_score: Optional[float] = None


class LastFmUserService:
    """Wrapper for fetching user-specific listening data from Last.fm.

    Note: Last.fm does not expose a public API for "personal recommendations" anymore.
    We approximate recommendations by aggregating similar artists to the user's top artists.
    This does not require user authentication (only a public username).
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret

    def _client(self) -> pylast.LastFMNetwork:
        return pylast.LastFMNetwork(api_key=self.api_key, api_secret=self.api_secret)

    def _safe_get_similar(self, network: pylast.LastFMNetwork, artist_name: str):
        """Return similar artists for a base artist without raising transport errors."""
        try:
            return network.get_artist(artist_name).get_similar()
        except Exception:
            return []

    @staticmethod
    def _parse_similarity_candidate(rel) -> tuple[str, Optional[float]]:
        """Extract candidate artist name and optional similarity score from a relation object."""
        try:
            cand = getattr(rel.item, "name", "")
            match_val = getattr(rel, "match", None)
            match_score = float(match_val) if match_val is not None else None
            return cand, match_score
        except Exception:
            return "", None

    def _collect_recommendations(
        self,
        network: pylast.LastFMNetwork,
        top_entries,
        top_set: set[str],
        limit: int,
    ) -> List[LastFmUserArtist]:
        """Aggregate unique similar artists from top artists until the requested limit is reached."""
        results: List[LastFmUserArtist] = []
        seen: set[str] = set()
        for entry in top_entries:
            base_name = getattr(entry.item, "name", "")
            if not base_name:
                continue
            for rel in self._safe_get_similar(network, base_name):
                cand, match_score = self._parse_similarity_candidate(rel)
                if not cand or cand in top_set or cand in seen:
                    continue
                seen.add(cand)
                results.append(
                    LastFmUserArtist(
                        name=cand,
                        playcount=0,
                        match_score=match_score,
                    )
                )
                if len(results) >= limit:
                    return results
        return results

    def get_top_artists(self, username: str, limit: int = 50) -> List[LastFmUserArtist]:
        if not username:
            return []
        network = self._client()
        user = network.get_user(username)
        top_artists = user.get_top_artists(limit=limit)
        results: List[LastFmUserArtist] = []
        for entry in top_artists:
            artist = entry.item
            playcount = int(entry.weight) if hasattr(entry, "weight") else 0
            results.append(
                LastFmUserArtist(
                    name=getattr(artist, "name", "") or "",
                    playcount=playcount,
                )
            )
        return results

    def get_recommended_artists(self, username: str, limit: int = 50) -> List[LastFmUserArtist]:
        """Approximate recommended artists by aggregating similar-to-top.

        Implementation: user.getTopArtists -> for each, artist.getSimilar, excluding the user's top artists.
        """
        if not username:
            return []
        try:
            network = self._client()
            user = network.get_user(username)
            top_entries = user.get_top_artists(limit=min(50, max(limit, 20)))
            top_names = [getattr(entry.item, "name", "") for entry in top_entries]
            top_set = {n for n in top_names if n}
            return self._collect_recommendations(network, top_entries, top_set, limit)
        except Exception:
            return []
