"""Resolve whatever the user pasted (a normal FIBA LiveStats boxscore URL, a
direct data.json URL, or a bare match id) into the raw game JSON bytes,
fetched server-side so the user never has to manually save a file.
"""
import re
import urllib.request
from typing import Tuple

MATCH_ID_RE = re.compile(r"/(\d{5,})(?:/|$)")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) SeasonTracker/1.0"}


class FetchError(Exception):
    pass


def _match_id_from(text: str) -> str:
    text = text.strip()
    if text.isdigit():
        return text
    m = MATCH_ID_RE.search(text)
    if not m:
        raise FetchError(
            "Couldn't find a match id in that — paste the full game URL "
            "(e.g. https://fibalivestats.dcd.shared.geniussports.com/u/CODE/1234567/) "
            "or just the numeric id."
        )
    return m.group(1)


def fetch_game_json(url_or_id: str) -> Tuple[bytes, str]:
    match_id = _match_id_from(url_or_id)
    data_url = f"https://fibalivestats.dcd.shared.geniussports.com/data/{match_id}/data.json"
    req = urllib.request.Request(data_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except Exception as exc:
        raise FetchError(f"Couldn't fetch {data_url}: {exc}")
    return raw, f"game_{match_id}.json"
