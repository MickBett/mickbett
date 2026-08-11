"""Turns one raw FIBA LiveStats / Genius Sports `data.json` game export into
rows in the season database.

Expected shape (this is the same format used by fibalivestats.dcd.shared.geniussports.com
game pages, e.g. .../data/<matchId>/data.json):

{
  "periodLength": 10,
  "tm": {
    "1": {"name": ..., "score": ..., "p1_score":.., ..., "tot_sFieldGoalsMade":.., ...,
          "pl": {"<pno>": {"scoreboardName":.., "sPoints":.., "sMinutes":"12:34", ...}},
          "shot": [{"x":.., "y":.., "r":0|1, "actionType":"2pt"/"3pt", "subType":.., "player":.., "per":..}]},
    "2": {...}
  },
  "pbp": [{"gt":"MM:SS", "period":.., "actionType":.., "subType":.., "success":0|1,
           "tno":1|2, "pno":.., "player":.., "actionNumber":.., "previousAction":.., ...}, ...]
}
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from . import db


class ImportError_(Exception):
    pass


def _mmss_to_seconds(s):
    if not s:
        return 0
    parts = s.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def _minutes_to_seconds(s):
    return _mmss_to_seconds(s)


FT_SET_RE = re.compile(r"^(\d+)of(\d+)$")

# action types whose shot-clock-elapsed value we track for the "shot clock
# breakdown" feature, beyond plain field-goal attempts.
CLOCK_TRACKED_TYPES = {"2pt", "3pt", "freethrow", "turnover", "foul", "foulon"}

# additional action types tracked purely for their game-clock position (the
# "5 minute splits" feature) -- these don't participate in the shot-clock
# reset state machine themselves beyond what a defensive rebound already does.
TIMING_ONLY_TYPES = {"steal", "assist", "block"}


def _process_pbp(pbp, period_length_min):
    """Single chronological pass over the play-by-play that reconstructs an
    approximate shot-clock value for every event that matters for the shot
    clock breakdown, since the feed only gives a game clock (`gt`, counts
    DOWN within a period), never a shot clock. Also records each tracked
    event's absolute elapsed game time (regulation-relative, i.e. 0-2400s
    for a 4x10min game), for the "5 minute splits" feature.

    The shot clock resets to 24s on a defensive rebound, a turnover, a made
    basket, or the start of a period; it resets to 14s on an offensive
    rebound. An event's "shot clock used" is (game-clock-at-last-reset -
    game-clock-at-event), clamped to the allowed window.

    Returns:
      shot_clock_map: {actionNumber: (elapsed, possession_type)} for 2pt/3pt
        attempts only -- kept for the `shots` table / court shot charts.
      clock_events: a list of dicts, one per tracked event (2pt, 3pt,
        freethrow, turnover, foul, foulon, steal, assist, block, both
        offensive and defensive rebounds, and substitutions), each with
        tno/pno/action_type/sub_type/made/shot_clock_used/possession_type/
        game_seconds_elapsed/action_number, plus `off_reb_source`
        ('2pt'/'3pt'/None) for offensive rebounds, identifying which shot
        type the rebound came off of via the feed's `previousAction` link.
        game_seconds_elapsed is None for overtime periods (period > 4) --
        regulation is the only thing "5 minute splits" covers.
        `action_number` is the feed's own event sequence number, kept on
        every event (including substitutions) so the "lineups" feature can
        replay a game in exact order and know which 5 players were on
        court for any given event.
    """
    events = sorted(pbp, key=lambda e: e.get("actionNumber") or 0)
    by_action_number = {e.get("actionNumber"): e for e in events}

    shot_clock_map = {}
    clock_events = []

    last_reset_gt = period_length_min * 60
    last_reset_type = "full"
    current_period = None

    def clamp(elapsed, poss_type):
        cap = 14 if poss_type == "oreb" else 24
        return max(0, min(elapsed, cap))

    def game_elapsed(period, gt_sec):
        if not period or period > 4:
            return None
        return (period - 1) * period_length_min * 60 + (period_length_min * 60 - gt_sec)

    for e in events:
        period = e.get("period")
        if period != current_period:
            current_period = period
            last_reset_gt = period_length_min * 60
            last_reset_type = "full"

        gt_sec = _mmss_to_seconds(e.get("gt", "0:00"))
        at = e.get("actionType")
        st = e.get("subType") or ""
        g_elapsed = game_elapsed(period, gt_sec)

        action_number = e.get("actionNumber")

        if at in CLOCK_TRACKED_TYPES:
            elapsed = clamp(last_reset_gt - gt_sec, last_reset_type)
            if at in ("2pt", "3pt"):
                shot_clock_map[action_number] = (elapsed, last_reset_type)
            clock_events.append({
                "tno": e.get("tno"), "pno": e.get("pno"),
                "action_type": at, "sub_type": st, "made": e.get("success"),
                "shot_clock_used": elapsed, "possession_type": last_reset_type,
                "off_reb_source": None, "game_seconds_elapsed": g_elapsed,
                "action_number": action_number,
            })
        elif at == "rebound" and st in ("offensive", "defensive"):
            elapsed = clamp(last_reset_gt - gt_sec, last_reset_type)
            src = None
            if st == "offensive":
                prev = by_action_number.get(e.get("previousAction"))
                src = prev.get("actionType") if prev and prev.get("actionType") in ("2pt", "3pt") else None
            clock_events.append({
                "tno": e.get("tno"), "pno": e.get("pno"),
                "action_type": "rebound_off" if st == "offensive" else "rebound_def",
                "sub_type": st, "made": None,
                "shot_clock_used": elapsed, "possession_type": last_reset_type,
                "off_reb_source": src, "game_seconds_elapsed": g_elapsed,
                "action_number": action_number,
            })
        elif at in TIMING_ONLY_TYPES:
            clock_events.append({
                "tno": e.get("tno"), "pno": e.get("pno"),
                "action_type": at, "sub_type": st, "made": None,
                "shot_clock_used": None, "possession_type": None,
                "off_reb_source": None, "game_seconds_elapsed": g_elapsed,
                "action_number": action_number,
            })
        elif at == "substitution" and st in ("in", "out"):
            # Not part of the shot-clock reset machine at all -- recorded
            # purely so the "lineups" feature can replay a game in order
            # and track which 5 players are on court at any given moment.
            clock_events.append({
                "tno": e.get("tno"), "pno": e.get("pno"),
                "action_type": "substitution", "sub_type": st, "made": None,
                "shot_clock_used": None, "possession_type": None,
                "off_reb_source": None, "game_seconds_elapsed": g_elapsed,
                "action_number": action_number,
            })

        # Update reset state AFTER recording this event's own shot-clock value.
        if at == "rebound":
            if st == "offensive":
                last_reset_gt, last_reset_type = gt_sec, "oreb"
            elif st == "defensive":
                last_reset_gt, last_reset_type = gt_sec, "full"
        elif at == "turnover":
            last_reset_gt, last_reset_type = gt_sec, "full"
        elif at in ("2pt", "3pt") and e.get("success") == 1:
            last_reset_gt, last_reset_type = gt_sec, "full"
        elif at == "freethrow" and e.get("success") == 1:
            m = FT_SET_RE.match(st)
            if m and m.group(1) == m.group(2):  # last free throw of the trip, made
                last_reset_gt, last_reset_type = gt_sec, "full"

    return shot_clock_map, clock_events


def _get_or_create_team(conn, name, code=None):
    row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO teams (name, code) VALUES (?, ?)", (name, code))
    return cur.lastrowid


def _get_or_create_player(conn, name, team_id):
    row = conn.execute(
        "SELECT id FROM players WHERE name = ? AND team_id = ?", (name, team_id)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO players (name, team_id) VALUES (?, ?)", (name, team_id)
    )
    return cur.lastrowid


def import_game(raw_bytes: bytes, filename: str, game_date: Optional[str] = None):
    file_hash = hashlib.sha256(raw_bytes).hexdigest()

    try:
        data = json.loads(raw_bytes.decode("utf-8-sig"))
    except Exception as exc:
        raise ImportError_(f"Could not parse {filename} as JSON: {exc}")

    if "tm" not in data or "1" not in data["tm"] or "2" not in data["tm"]:
        raise ImportError_(
            f"{filename} doesn't look like a FIBA LiveStats game export "
            "(missing tm.1 / tm.2)."
        )

    period_length = data.get("periodLength", 10)
    t1, t2 = data["tm"]["1"], data["tm"]["2"]
    pbp = data.get("pbp", [])
    shot_clock_map, clock_events = _process_pbp(pbp, period_length) if pbp else ({}, [])

    with db.tx() as conn:
        existing = conn.execute(
            "SELECT id FROM games WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if existing:
            raise ImportError_(
                f"{filename} has already been imported (game #{existing['id']})."
            )

        team1_id = _get_or_create_team(conn, t1["name"], t1.get("code"))
        team2_id = _get_or_create_team(conn, t2["name"], t2.get("code"))

        game_date = game_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur = conn.execute(
            """INSERT INTO games
               (file_hash, game_date, team1_id, team2_id, team1_score, team2_score,
                period_length, source_filename, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_hash, game_date, team1_id, team2_id,
                t1.get("score"), t2.get("score"), period_length, filename,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        game_id = cur.lastrowid

        # team number (1/2) -> {team_id, pno_to_player_id} so the clock_events
        # pass (below, keyed by tno/pno) can resolve real db ids afterwards.
        team_lookup = {}

        for tno, team, team_id, opp_team, is_team1 in (
            ("1", t1, team1_id, t2, 1), ("2", t2, team2_id, t1, 0)
        ):
            conn.execute(
                """INSERT INTO team_game_stats
                   (game_id, team_id, is_team1, pts, opp_pts, oreb, dreb, reb,
                    ast, stl, blk, tov, pf, fgm, fga, tpm, tpa, ftm, fta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    game_id, team_id, is_team1,
                    team.get("score"), opp_team.get("score"),
                    team.get("tot_sReboundsOffensive"), team.get("tot_sReboundsDefensive"),
                    team.get("tot_sReboundsTotal"),
                    team.get("tot_sAssists"), team.get("tot_sSteals"), team.get("tot_sBlocks"),
                    team.get("tot_sTurnovers"), team.get("tot_sFoulsPersonal"),
                    team.get("tot_sFieldGoalsMade"), team.get("tot_sFieldGoalsAttempted"),
                    team.get("tot_sThreePointersMade"), team.get("tot_sThreePointersAttempted"),
                    team.get("tot_sFreeThrowsMade"), team.get("tot_sFreeThrowsAttempted"),
                ),
            )

            # players, keyed by their in-game "pno" so we can map shots/events -> player id
            pno_to_player_id = {}
            for pno, p in (team.get("pl") or {}).items():
                name = p.get("scoreboardName") or p.get("name") or f"#{p.get('shirtNumber','?')}"
                player_id = _get_or_create_player(conn, name, team_id)
                pno_to_player_id[str(pno)] = player_id
                conn.execute(
                    """INSERT INTO player_game_stats
                       (game_id, player_id, team_id, minutes_sec, pts, reb, ast, stl, blk,
                        tov, pf, fgm, fga, tpm, tpa, ftm, fta, plus_minus, starter)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        game_id, player_id, team_id,
                        _minutes_to_seconds(p.get("sMinutes")),
                        p.get("sPoints", 0), p.get("sReboundsTotal", 0), p.get("sAssists", 0),
                        p.get("sSteals", 0), p.get("sBlocks", 0), p.get("sTurnovers", 0),
                        p.get("sFoulsPersonal", 0),
                        p.get("sFieldGoalsMade", 0), p.get("sFieldGoalsAttempted", 0),
                        p.get("sThreePointersMade", 0), p.get("sThreePointersAttempted", 0),
                        p.get("sFreeThrowsMade", 0), p.get("sFreeThrowsAttempted", 0),
                        p.get("sPlusMinusPoints"), p.get("starter", 0),
                    ),
                )

            for s in team.get("shot") or []:
                pno = str(s.get("pno"))
                player_id = pno_to_player_id.get(pno)
                if player_id is None:
                    # fall back to matching by name if pno wasn't in the pl dict
                    player_id = _get_or_create_player(conn, s.get("player", "Unknown"), team_id)
                elapsed, poss_type = shot_clock_map.get(s.get("actionNumber"), (None, None))
                conn.execute(
                    """INSERT INTO shots
                       (game_id, team_id, player_id, period, gt_seconds, x, y, made,
                        action_type, sub_type, shot_clock_used, possession_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        game_id, team_id, player_id, s.get("per"),
                        None, s.get("x"), s.get("y"), s.get("r"),
                        s.get("actionType"), s.get("subType"),
                        elapsed, poss_type,
                    ),
                )

            team_lookup[tno] = {"team_id": team_id, "pno_map": pno_to_player_id}

        for ce in clock_events:
            tno = str(ce["tno"]) if ce["tno"] is not None else None
            lookup = team_lookup.get(tno)
            if not lookup:
                continue  # tno 0 / period-boundary events etc. -- not a real team
            player_id = lookup["pno_map"].get(str(ce["pno"])) if ce["pno"] else None
            conn.execute(
                """INSERT INTO pbp_events
                   (game_id, team_id, player_id, action_type, sub_type, made,
                    shot_clock_used, possession_type, off_reb_source, game_seconds_elapsed,
                    action_number)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    game_id, lookup["team_id"], player_id,
                    ce["action_type"], ce["sub_type"], ce["made"],
                    ce["shot_clock_used"], ce["possession_type"], ce["off_reb_source"],
                    ce.get("game_seconds_elapsed"), ce.get("action_number"),
                ),
            )

    return {
        "game_id": game_id,
        "team1": t1["name"], "team2": t2["name"],
        "score": f"{t1.get('score')}-{t2.get('score')}",
        "shots_with_clock": sum(1 for v in shot_clock_map.values() if v[0] is not None),
    }


def reprocess_pbp_for_game(conn, game_id: int, raw_bytes: bytes) -> int:
    """Re-derive pbp_events for an ALREADY-imported game from its raw feed
    bytes and replace what's stored -- used to backfill fields added after
    the initial import (e.g. game_seconds_elapsed, steal, rebound_def)
    without re-importing the whole game (which would collide on file_hash).
    Team/player lookups are idempotent, so this is safe to re-run. Returns
    the number of pbp_events rows written."""
    data = json.loads(raw_bytes.decode("utf-8-sig"))
    period_length = data.get("periodLength", 10)
    t1, t2 = data["tm"]["1"], data["tm"]["2"]
    pbp = data.get("pbp", [])
    _, clock_events = _process_pbp(pbp, period_length) if pbp else ({}, [])

    team1_id = _get_or_create_team(conn, t1["name"], t1.get("code"))
    team2_id = _get_or_create_team(conn, t2["name"], t2.get("code"))

    team_lookup = {}
    for tno, team, team_id in (("1", t1, team1_id), ("2", t2, team2_id)):
        pno_to_player_id = {}
        for pno, p in (team.get("pl") or {}).items():
            name = p.get("scoreboardName") or p.get("name") or f"#{p.get('shirtNumber','?')}"
            pno_to_player_id[str(pno)] = _get_or_create_player(conn, name, team_id)
        team_lookup[tno] = {"team_id": team_id, "pno_map": pno_to_player_id}

    conn.execute("DELETE FROM pbp_events WHERE game_id = ?", (game_id,))
    n = 0
    for ce in clock_events:
        tno = str(ce["tno"]) if ce["tno"] is not None else None
        lookup = team_lookup.get(tno)
        if not lookup:
            continue
        player_id = lookup["pno_map"].get(str(ce["pno"])) if ce["pno"] else None
        conn.execute(
            """INSERT INTO pbp_events
               (game_id, team_id, player_id, action_type, sub_type, made,
                shot_clock_used, possession_type, off_reb_source, game_seconds_elapsed,
                action_number)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                game_id, lookup["team_id"], player_id,
                ce["action_type"], ce["sub_type"], ce["made"],
                ce["shot_clock_used"], ce["possession_type"], ce["off_reb_source"],
                ce.get("game_seconds_elapsed"), ce.get("action_number"),
            ),
        )
        n += 1
    return n
