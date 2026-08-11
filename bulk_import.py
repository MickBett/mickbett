"""Bulk importer: pull the real CEBL 2026 season schedule from CEBL's own
stats API (which gives exact FIBA LiveStats match ids + real dates), then
import every completed game into season.db.
"""
import sys
import re
import json
import time
import urllib.request
import concurrent.futures

sys.path.insert(0, "/Users/mickbett/season-tracker")
from app import db, importer
from app.fetcher import fetch_game_json, FetchError

CEBL_API = "https://api.data.cebl.ca/games/2026/"
CEBL_API_KEY = "800chyzv2hvur3z0ogh39cve2zok0c"
MAX_WORKERS = 8

STATS_URL_RE = re.compile(r"/u/CEBL/(\d+)/")


def get_schedule():
    req = urllib.request.Request(CEBL_API, headers={
        "X-Api-Key": CEBL_API_KEY,
        "User-Agent": "Mozilla/5.0 SeasonTracker/1.0",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_one(game):
    """I/O-bound step only -- safe to run concurrently. No DB access here."""
    m = STATS_URL_RE.search(game.get("stats_url_en", ""))
    if not m:
        return {"status": "no_match_id", "game": game}
    match_id = m.group(1)
    game_date = game["start_time_utc"][:10]  # YYYY-MM-DD
    try:
        raw, filename = fetch_game_json(match_id)
    except FetchError as e:
        return {"status": "fetch_error", "id": match_id, "detail": str(e)[:150]}
    return {"status": "fetched", "id": match_id, "raw": raw, "filename": filename, "game_date": game_date}


def main():
    db.init_db()
    print("Fetching CEBL 2026 schedule from api.data.cebl.ca ...", flush=True)
    schedule = get_schedule()
    completed = [g for g in schedule if g.get("status") == "COMPLETE"]
    print(f"Schedule has {len(schedule)} games total, {len(completed)} completed.", flush=True)

    counts = {"imported": 0, "duplicate": 0, "fetch_error": 0, "import_error": 0, "no_match_id": 0}
    t0 = time.time()

    # Fetch concurrently (network I/O, safe), then import one at a time in this
    # single thread (sqlite/our get-or-create helpers aren't safe for concurrent
    # writers -- two threads can both decide a team needs inserting and race).
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fetched = list(ex.map(fetch_one, completed))

    for i, result in enumerate(fetched, 1):
        status = result["status"]
        if status == "fetched":
            try:
                info = importer.import_game(result["raw"], result["filename"], result["game_date"])
                counts["imported"] += 1
                print(f"[IMPORTED] {result['id']}: {info['team1']} {info['score']} {info['team2']}", flush=True)
            except importer.ImportError_ as e:
                if "already been imported" in str(e):
                    counts["duplicate"] += 1
                else:
                    counts["import_error"] += 1
                    print(f"[FAILED import_error] {result['id']}: {e}", flush=True)
        else:
            counts[status] = counts.get(status, 0) + 1
            if status == "fetch_error":
                print(f"[FAILED fetch_error] {result.get('id')}: {result.get('detail')}", flush=True)

        if i % 20 == 0 or i == len(fetched):
            elapsed = time.time() - t0
            print(f"[PROGRESS] {i}/{len(fetched)} | imported={counts['imported']} "
                  f"dup={counts['duplicate']} errors={counts['fetch_error']+counts['import_error']} "
                  f"| {elapsed:.0f}s elapsed", flush=True)

    print("\n=== DONE ===", flush=True)
    print(json.dumps(counts, indent=2), flush=True)


if __name__ == "__main__":
    main()
