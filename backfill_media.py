"""One-off (re-runnable) script to populate team logos and player photos
from CEBL's own stats API -- the FIBA LiveStats game feed we import from
doesn't carry images at all.

Team logos:   GET https://api.data.cebl.ca/teams/2026/            -> logo_url
Player photos: GET https://api.data.cebl.ca/teams/{cebl_id}/roster/2026/ -> photo_url

Matched into our DB by name: teams by (accent/case-insensitive) name match,
players by first-initial + family-name match against the "T. King" style
names we store (built from the FIBA feed's firstNameInitial/familyName).

Safe to re-run any time (e.g. after importing a new team, or once a season
roster settles) -- it only ever updates logo_url/photo_url columns.
"""
import re
import unicodedata
import urllib.request
import json

from app import db

API_KEY = "800chyzv2hvur3z0ogh39cve2zok0c"
HEADERS = {"X-Api-Key": API_KEY}
SEASON = "2026"


def _get(path):
    req = urllib.request.Request(f"https://api.data.cebl.ca/{path}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _norm(s):
    """Lowercase, strip accents/punctuation, for loose name matching."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    db.init_db()
    conn = db.get_conn()

    cebl_teams = _get(f"teams/{SEASON}/")
    our_teams = {r["id"]: dict(r) for r in conn.execute("SELECT id, name FROM teams").fetchall()}
    name_to_our_id = {_norm(t["name"]): tid for tid, t in our_teams.items()}

    logo_updates = 0
    cebl_id_for_our_id = {}
    for ct in cebl_teams:
        our_id = name_to_our_id.get(_norm(ct["name"]))
        if not our_id:
            print(f"  (no match in our DB for CEBL team '{ct['name']}', skipping)")
            continue
        cebl_id_for_our_id[our_id] = ct["id"]
        conn.execute("UPDATE teams SET logo_url = ? WHERE id = ?", (ct["logo_url"], our_id))
        logo_updates += 1
    conn.commit()
    print(f"Team logos: updated {logo_updates}/{len(our_teams)}")

    photo_updates, photo_total = 0, 0
    for our_id, team in our_teams.items():
        cebl_id = cebl_id_for_our_id.get(our_id)
        if not cebl_id:
            continue
        try:
            roster = _get(f"teams/{cebl_id}/roster/{SEASON}/")
        except Exception as exc:
            print(f"  roster fetch failed for {team['name']}: {exc}")
            continue

        # our stored player name is "T. King" (firstInitial + familyName)
        by_key = {}
        for entry in roster:
            full = (entry.get("full_name") or "").strip()
            if not full or not entry.get("photo_url"):
                continue
            parts = full.split()
            initial = parts[0][0].upper()
            family = " ".join(parts[1:]) if len(parts) > 1 else parts[0]
            by_key[(initial, _norm(family))] = entry["photo_url"]

        our_players = conn.execute(
            "SELECT id, name FROM players WHERE team_id = ?", (our_id,)
        ).fetchall()
        for p in our_players:
            photo_total += 1
            m = re.match(r"^(\w)\.\s*(.+)$", p["name"])
            if not m:
                continue
            key = (m.group(1).upper(), _norm(m.group(2)))
            url = by_key.get(key)
            if url:
                conn.execute("UPDATE players SET photo_url = ? WHERE id = ?", (url, p["id"]))
                photo_updates += 1
        conn.commit()

    print(f"Player photos: matched {photo_updates}/{photo_total}")
    conn.close()


if __name__ == "__main__":
    main()
