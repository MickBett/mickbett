"""Backfill script: re-derive pbp_events for every already-imported game,
picking up fields added after the initial import --
game_seconds_elapsed, 'steal', and 'rebound_def' events -- needed for the
"5 minute splits" feature. Doesn't touch games/shots/team_game_stats/
player_game_stats at all, only replaces pbp_events per game.

Safe to re-run any time (idempotent: deletes + reinserts pbp_events for
each game_id it touches).
"""
import sys
import re
import time
import concurrent.futures

sys.path.insert(0, "/Users/mickbett/season-tracker")
from app import db, importer
from app.fetcher import fetch_game_json, FetchError

MAX_WORKERS = 8
MATCH_ID_RE = re.compile(r"game_(\d+)\.json")


def fetch_one(game_row):
    """I/O-bound step only -- safe to run concurrently. No DB access here."""
    m = MATCH_ID_RE.match(game_row["source_filename"] or "")
    if not m:
        return {"status": "no_match_id", "game_id": game_row["id"]}
    match_id = m.group(1)
    try:
        raw, _ = fetch_game_json(match_id)
    except FetchError as e:
        return {"status": "fetch_error", "game_id": game_row["id"], "id": match_id, "detail": str(e)[:150]}
    return {"status": "fetched", "game_id": game_row["id"], "id": match_id, "raw": raw}


def main():
    db.init_db()
    conn = db.get_conn()
    games = conn.execute("SELECT id, source_filename FROM games ORDER BY id").fetchall()
    conn.close()
    print(f"{len(games)} games in season.db to reprocess.", flush=True)

    counts = {"reprocessed": 0, "fetch_error": 0, "reprocess_error": 0, "no_match_id": 0}
    t0 = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fetched = list(ex.map(fetch_one, games))

    for i, result in enumerate(fetched, 1):
        status = result["status"]
        if status == "fetched":
            try:
                with db.tx() as conn:
                    n = importer.reprocess_pbp_for_game(conn, result["game_id"], result["raw"])
                counts["reprocessed"] += 1
                print(f"[OK] game {result['game_id']} ({result['id']}): {n} pbp_events", flush=True)
            except Exception as e:
                counts["reprocess_error"] += 1
                print(f"[FAILED reprocess_error] game {result['game_id']}: {e}", flush=True)
        else:
            counts[status] = counts.get(status, 0) + 1
            if status == "fetch_error":
                print(f"[FAILED fetch_error] game {result['game_id']}: {result.get('detail')}", flush=True)

        if i % 20 == 0 or i == len(fetched):
            elapsed = time.time() - t0
            print(f"[PROGRESS] {i}/{len(fetched)} | ok={counts['reprocessed']} "
                  f"errors={counts['fetch_error']+counts['reprocess_error']} | {elapsed:.0f}s elapsed", flush=True)

    print("\n=== DONE ===", flush=True)
    print(counts, flush=True)


if __name__ == "__main__":
    main()
