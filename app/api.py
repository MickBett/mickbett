from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Response
from pydantic import BaseModel
from typing import Optional

from . import db
from . import charts
from . import zones
from . import rankings
from .importer import import_game, ImportError_
from .fetcher import fetch_game_json, FetchError

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- import ---
@router.post("/import")
async def import_endpoint(file: UploadFile = File(...), game_date: Optional[str] = Form(None)):
    raw = await file.read()
    try:
        result = import_game(raw, file.filename, game_date)
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


class ImportUrlBody(BaseModel):
    url: str
    game_date: Optional[str] = None


@router.post("/import-url")
def import_url_endpoint(body: ImportUrlBody):
    try:
        raw, filename = fetch_game_json(body.url)
    except FetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        result = import_game(raw, filename, body.game_date)
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


# -------------------------------------------------------------- summary ---
@router.get("/summary")
def summary():
    conn = db.get_conn()
    games = conn.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]
    teams = conn.execute("SELECT COUNT(*) c FROM teams").fetchone()["c"]
    players = conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]
    conn.close()
    return {"games": games, "teams": teams, "players": players}


# ---------------------------------------------------------------rankings --
@router.get("/rankings/metrics")
def rankings_metrics():
    return rankings.metrics_menu()


@router.get("/rankings/players")
def rankings_players(metric: str, min_games: int = 5, scope: str = "season"):
    try:
        ranked, direction = rankings.player_rankings(metric, min_games, scope)
    except (ValueError, StopIteration):
        raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")
    return {"direction": direction, "rows": ranked}


@router.get("/rankings/teams")
def rankings_teams(metric: str):
    try:
        ranked, direction = rankings.team_rankings(metric)
    except (ValueError, StopIteration):
        raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")
    return {"direction": direction, "rows": ranked}


@router.get("/teams/{team_id}/scouting-report")
def team_scouting_report(team_id: int):
    """5 data-backed weaknesses for this team -- a scouting report on how an
    opponent might beat them. Covers traditional team stats, shot-clock
    shooting splits, offensive/defensive rebounding by shot type (2PT miss
    vs 3PT miss), and a dedicated read on their single weakest 5-minute
    stretch of the game -- each with season AND last-5-games comparative
    evidence, since a weakness that's gotten worse (or better) recently is
    itself part of the story."""
    conn = db.get_conn()
    team_row = conn.execute("SELECT id, name, logo_url FROM teams WHERE id = ?", (team_id,)).fetchone()
    conn.close()
    if not team_row:
        raise HTTPException(status_code=404, detail="Team not found")

    # The single weakest 5-minute stretch (by scoring rank) gets its own
    # guaranteed slot -- the other candidate pools (traditional/shot-clock/
    # rebounding) live in rankings.py, but five-minute-splits data is
    # computed here, so it's assembled directly into a matching shape.
    five_min_weakness = None
    season_rows = _five_minute_splits_impl(team_id, "season", against=False)
    last5_rows = _five_minute_splits_impl(team_id, "last5", against=False)
    if season_rows and last5_rows:
        worst_seg = max(season_rows, key=lambda r: r["pts"]["rank"])
        last5_seg = next((r for r in last5_rows if r["segment"] == worst_seg["segment"]), None)
        if last5_seg:
            s_rank, s_pool, s_val = worst_seg["pts"]["rank"], worst_seg["pts"]["pool"], worst_seg["pts"]["value"]
            l_rank, l_pool, l_val = last5_seg["pts"]["rank"], last5_seg["pts"]["pool"], last5_seg["pts"]["value"]
            if l_rank > s_rank:
                trend = "and it's gotten even worse over their last 5 games"
            elif l_rank < s_rank:
                trend = "though there are recent signs of improvement"
            else:
                trend = "a consistent issue all season"
            five_min_weakness = {
                "group": "five_minute", "key": "five_min:pts",
                "category": f"Scoring — {worst_seg['label']}-minute mark",
                "text": (
                    f"{team_row['name']} go quiet on offense during the {worst_seg['label']}-minute stretch of the "
                    f"game, ranking #{s_rank} of {s_pool} in the league scoring there this season ({s_val} pts) "
                    f"and #{l_rank} of {l_pool} over their last 5 games ({l_val} pts) -- {trend}. Opponents who "
                    f"key in on that stretch can turn it into a run."
                ),
                "season_rank": s_rank, "season_pool": s_pool, "season_value": s_val,
                "last5_rank": l_rank, "last5_pool": l_pool, "last5_value": l_val, "unit": "pts",
                "chart": {
                    "type": "segment_line",
                    "labels": [f"{r['label']}m" for r in season_rows],
                    "season_values": [r["pts"]["value"] for r in season_rows],
                    "last5_values": [r["pts"]["value"] for r in last5_rows],
                    "highlight_index": worst_seg["segment"],
                },
            }

    others = rankings.team_weaknesses(team_id, top_n=4)
    if not others and not five_min_weakness:
        raise HTTPException(status_code=404, detail="Not enough data for a scouting report yet")

    statements = ([five_min_weakness] if five_min_weakness else []) + others
    statements.sort(key=lambda c: c["season_rank"], reverse=True)

    return {
        "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["logo_url"]},
        "statements": statements[:5],
    }


_VERDICT_LABELS = [
    ("tov", "Turnovers", False, None),
    ("fouls", "Fouls", False, None),
    ("fg2", "2P%", True, "pct"),
    ("fg3", "3P%", True, "pct"),
    ("oreb", "Off. rebounds", True, None),
    ("oreb_3pt", "OR off 3s", True, None),
    ("pts", "Points", True, None),
]


def _verdict_rows(game, season):
    """Game vs season, one row per headline stat -- % better/worse than
    the season mark, sign-normalized so positive always means "exceeded
    the scout" (helped them) and negative means "undermined it", the same
    idea as the PDF's diverging bar chart."""
    rows = []
    for key, label, higher_is_better, sub in _VERDICT_LABELS:
        g = game[key]["pct"] if sub else game[key]
        s = season[key]["pct"] if sub else season[key]
        pct_diff = None
        if g is not None and s not in (None, 0):
            raw = (g - s) / abs(s) * 100
            pct_diff = round(raw if higher_is_better else -raw, 1)
        rows.append({"label": label, "game": g, "season": s, "pct_diff": pct_diff})
    return rows


def _matchup_lineup_summary(conn, team_id, game_ids, top_n=5):
    """Most-used 5-man units over just `game_ids` (the last 3 games, for
    Matchup Scout -- a full-season combo list can include players who've
    since been traded/waived, which is misleading for "who's actually on
    the floor right now"). Ranked by points scored, with each unit's share
    of the team's total scoring across those games."""
    combos = _team_lineup_combos(conn, team_id, game_ids)
    if not combos:
        return None
    player_rows = conn.execute("SELECT id, name, photo_url FROM players WHERE team_id = ?", (team_id,)).fetchall()
    player_info = {r["id"]: {"player_id": r["id"], "name": r["name"], "photo_url": r["photo_url"]} for r in player_rows}

    total_pts = sum(c["totals"]["pts"] for c in combos)
    ranked = sorted(combos, key=lambda c: c["totals"]["pts"], reverse=True)

    units = []
    for c in ranked[:top_n]:
        gp = len(c["games"]) or 1
        pts = c["totals"]["pts"]
        units.append({
            "players": [player_info.get(pid, {"player_id": pid, "name": "Unknown", "photo_url": None}) for pid in c["player_ids"]],
            "games": len(c["games"]), "games_scoped": len(game_ids),
            "pts": pts,
            "pct_of_offense": round(pts / total_pts * 100, 1) if total_pts else None,
            "stats": _lineup_stat_line(c["totals"], gp),
        })
    return {"games_scoped": len(game_ids), "total_pts": total_pts, "units": units}


@router.get("/teams/{team_id}/top-row")
def team_top_row(team_id: int):
    """Backs the Matchup Scout tab's top-line stat strip -- see
    rankings.team_top_row for the exact stat list and layout it drives."""
    data = rankings.team_top_row(team_id)
    if not data:
        raise HTTPException(status_code=404, detail="Team not found")
    return data


@router.get("/matchup-scout")
def matchup_scout(team_id: int, opponent_id: int):
    """How `opponent_id` might beat `team_id`, plus a verdict on whether
    `team_id`'s single most recent game (whoever it was against -- NOT
    necessarily their last meeting with `opponent_id`) matched that
    scouting profile. Carries season, last-5-games, AND the game itself,
    all directly comparable, plus their most-used lineups over just their
    last 3 games (roster turnover makes a full-season lineup list
    unreliable)."""
    scout = rankings.matchup_scout(team_id, opponent_id)
    if not scout:
        raise HTTPException(status_code=404, detail="Team not found")

    conn = db.get_conn()

    last3_ids = _team_last_n_game_ids(conn, team_id, 3)
    scout["lineups"] = _matchup_lineup_summary(conn, team_id, last3_ids)

    # Season-wide 5-minute scoring profile for BOTH teams -- not tied to any
    # one game, so this stands on its own even before/without a recent
    # meeting. Flags the team's single worst-ranked scoring stretch and what
    # the opponent themselves average in that exact window, the same
    # "where to spend the pressure" read the reference report uses.
    team_5min = _five_minute_splits_impl(team_id, "season", against=False)
    opp_5min = _five_minute_splits_impl(opponent_id, "season", against=False)
    five_min_matchup = None
    if team_5min and opp_5min:
        worst_seg = max(team_5min, key=lambda r: r["pts"]["rank"])
        opp_at_worst = next((r for r in opp_5min if r["segment"] == worst_seg["segment"]), None)
        five_min_matchup = {
            "labels": [f"{r['label']}m" for r in team_5min],
            "team_values": [r["pts"]["value"] for r in team_5min],
            "team_ranks": [r["pts"]["rank"] for r in team_5min],
            "opponent_values": [r["pts"]["value"] for r in opp_5min],
            "worst_segment_label": worst_seg["label"],
            "worst_segment_rank": worst_seg["pts"]["rank"],
            "worst_segment_pool": worst_seg["pts"]["pool"],
            "worst_segment_value": worst_seg["pts"]["value"],
            "opponent_value_at_worst": opp_at_worst["pts"]["value"] if opp_at_worst else None,
        }
    scout["five_min_matchup"] = five_min_matchup

    # Plain-language "5 minute period evaluation" -- each segment's own
    # average rank across all 6 tracked stats (same formula as the 5-Minute
    # tab's read table), then calls out team_id's single best and worst
    # segment plus an overall Strong/Middle/Weak read, comparing the worst
    # (and best) stretch to what opponent_id -- the team using this scout --
    # themselves put up in that exact window.
    five_min_summary = None
    if team_5min and opp_5min:
        def seg_avg_rank(seg):
            ranks = [seg[k]["rank"] for k in ("pts", "fg2", "fg3", "ft", "tov", "fouls")]
            return sum(ranks) / len(ranks)

        team_seg_avgs = [(r, seg_avg_rank(r)) for r in team_5min]
        best_seg, best_avg = min(team_seg_avgs, key=lambda x: x[1])
        worst_seg, worst_avg = max(team_seg_avgs, key=lambda x: x[1])
        overall_avg = sum(a for _, a in team_seg_avgs) / len(team_seg_avgs)
        pool = team_5min[0]["pts"]["pool"]
        opp_at_best = next((r for r in opp_5min if r["segment"] == best_seg["segment"]), None)
        opp_at_worst = next((r for r in opp_5min if r["segment"] == worst_seg["segment"]), None)

        seed = team_id * 31 + opponent_id * 17
        team_name, opp_name = scout["team"]["name"], scout["opponent"]["name"]
        tier = rankings.tier_label(overall_avg)
        tier_variants = {
            "Strong": [
                f"{team_name} are strong across the full 40 minutes -- a #{round(overall_avg, 1)} average rank "
                f"across all 8 segments, with no real soft stretch to target.",
                f"There's no obvious dead zone for {team_name}: a strong #{round(overall_avg, 1)} average rank "
                f"across every 5-minute segment of the game.",
            ],
            "Middle": [
                f"{team_name} are fairly even from start to finish -- a #{round(overall_avg, 1)} average rank "
                f"across all 8 segments, without one stretch that clearly defines the game.",
                f"No real extremes for {team_name} across the 40 minutes: a middling #{round(overall_avg, 1)} "
                f"average rank segment to segment.",
            ],
            "Weak": [
                f"{team_name} struggle to find rhythm across the 40 minutes -- just a #{round(overall_avg, 1)} "
                f"average rank across all 8 segments.",
                f"Consistency is a real issue for {team_name}: a weak #{round(overall_avg, 1)} average rank "
                f"across every 5-minute segment of the game.",
            ],
        }[tier]
        paragraphs = [rankings._pick(tier_variants, seed)]

        if opp_at_best:
            paragraphs.append(rankings._pick([
                f"Their best stretch is the {best_seg['label']}-minute mark (#{round(best_avg, 1)} average rank) "
                f"-- for reference, {opp_name} put up {opp_at_best['pts']['value']} points of their own there "
                f"(#{opp_at_best['pts']['rank']} of {pool}).",
                f"{team_name} are toughest to deal with in the {best_seg['label']}-minute window "
                f"(#{round(best_avg, 1)} average rank); {opp_name} score {opp_at_best['pts']['value']} points a "
                f"game in that same stretch (#{opp_at_best['pts']['rank']} of {pool}).",
            ], seed + 7))
        else:
            paragraphs.append(
                f"Their best stretch is the {best_seg['label']}-minute mark, averaging a #{round(best_avg, 1)} "
                f"rank across points, shooting, turnovers, and fouls."
            )

        if opp_at_worst:
            paragraphs.append(rankings._pick([
                f"Their softest window is the {worst_seg['label']}-minute mark (#{round(worst_avg, 1)} average "
                f"rank) -- {opp_name} average {opp_at_worst['pts']['value']} points of their own in that exact "
                f"stretch (#{opp_at_worst['pts']['rank']} of {pool}), worth leaning into.",
                f"The {worst_seg['label']}-minute mark is where {team_name} are most exploitable "
                f"(#{round(worst_avg, 1)} average rank) -- {opp_name} themselves score {opp_at_worst['pts']['value']} "
                f"points a game in that window (#{opp_at_worst['pts']['rank']} of {pool}), a stretch worth targeting.",
            ], seed + 13))
        else:
            paragraphs.append(
                f"Their softest window is the {worst_seg['label']}-minute mark, averaging just a "
                f"#{round(worst_avg, 1)} rank across points, shooting, turnovers, and fouls."
            )

        five_min_summary = {
            "paragraphs": paragraphs,
            "overall_avg_rank": round(overall_avg, 1), "overall_tier": tier, "pool": pool,
            "best_segment_label": best_seg["label"], "worst_segment_label": worst_seg["label"],
        }
    scout["five_min_summary"] = five_min_summary

    recent = conn.execute(
        """SELECT g.id, g.game_date, g.team1_id, g.team2_id, g.team1_score, g.team2_score,
                  t1.name AS team1_name, t1.logo_url AS team1_logo_url,
                  t2.name AS team2_name, t2.logo_url AS team2_logo_url
           FROM games g
           JOIN teams t1 ON t1.id = g.team1_id
           JOIN teams t2 ON t2.id = g.team2_id
           WHERE g.team1_id = ? OR g.team2_id = ?
           ORDER BY g.game_date DESC, g.id DESC LIMIT 1""",
        (team_id, team_id),
    ).fetchone()

    recent_game = None
    if recent:
        is_team1 = recent["team1_id"] == team_id
        gp_season = conn.execute(
            "SELECT COUNT(*) AS n FROM team_game_stats WHERE team_id = ?", (team_id,)
        ).fetchone()["n"]
        last5_ids = _team_last_n_game_ids(conn, team_id, 5)

        game_profile = _team_shot_profile(conn, team_id, [recent["id"]], 1)
        season_profile = _team_shot_profile(conn, team_id, None, gp_season)
        last5_profile = _team_shot_profile(conn, team_id, last5_ids, len(last5_ids))
        game_profile_def = _team_shot_profile(conn, team_id, [recent["id"]], 1, against=True)
        season_profile_def = _team_shot_profile(conn, team_id, None, gp_season, against=True)

        season_5min = _five_minute_splits_impl(team_id, "season", against=False)
        game_5min_agg = _aggregate_five_min_rows(_events_for_team(conn, team_id, [recent["id"]]))
        game_5min_pts = [row["fg2_m"] * 2 + row["fg3_m"] * 3 + row["ft_m"] for row in game_5min_agg]

        team_score = recent["team1_score"] if is_team1 else recent["team2_score"]
        opp_score = recent["team2_score"] if is_team1 else recent["team1_score"]
        recent_opponent_id = recent["team2_id"] if is_team1 else recent["team1_id"]
        recent_opponent_name = recent["team2_name"] if is_team1 else recent["team1_name"]
        recent_opponent_logo = recent["team2_logo_url"] if is_team1 else recent["team1_logo_url"]

        recent_game = {
            "game_id": recent["id"], "game_date": recent["game_date"],
            "opponent": {"id": recent_opponent_id, "name": recent_opponent_name, "logo_url": recent_opponent_logo},
            "is_scouted_opponent": recent_opponent_id == opponent_id,
            "team_score": team_score, "opponent_score": opp_score, "team_won": team_score > opp_score,
            "game_profile": game_profile, "season_profile": season_profile, "last5_profile": last5_profile,
            "game_profile_def": game_profile_def, "season_profile_def": season_profile_def,
            "verdict": _verdict_rows(game_profile, season_profile),
            "five_min": {
                "labels": [f"{r['label']}m" for r in season_5min],
                "game_values": game_5min_pts,
                "season_values": [r["pts"]["value"] for r in season_5min],
            },
        }

    conn.close()
    return {**scout, "recent_game": recent_game}


# ------------------------------------------------------------- standings --
@router.get("/standings")
def standings():
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.logo_url,
               SUM(CASE WHEN tgs.pts > tgs.opp_pts THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN tgs.pts < tgs.opp_pts THEN 1 ELSE 0 END) AS losses,
               COUNT(*) AS gp,
               SUM(tgs.pts) AS pf,
               SUM(tgs.opp_pts) AS pa
        FROM team_game_stats tgs
        JOIN teams t ON t.id = tgs.team_id
        GROUP BY t.id
        ORDER BY wins DESC, (SUM(tgs.pts) - SUM(tgs.opp_pts)) DESC
        """
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        gp = r["gp"] or 0
        out.append({
            "team_id": r["id"], "name": r["name"], "logo_url": r["logo_url"],
            "wins": r["wins"], "losses": r["losses"], "gp": gp,
            "pf": r["pf"], "pa": r["pa"],
            "diff": (r["pf"] or 0) - (r["pa"] or 0),
            "ppg": round((r["pf"] or 0) / gp, 1) if gp else 0,
            "papg": round((r["pa"] or 0) / gp, 1) if gp else 0,
            "win_pct": round(r["wins"] / gp, 3) if gp else 0,
        })
    return out


# ------------------------------------------------------------------ teams -
@router.get("/teams")
def list_teams():
    conn = db.get_conn()
    rows = conn.execute("SELECT id, name, code, logo_url FROM teams ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/teams/{team_id}/trend")
def team_trend(team_id: int):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT g.id AS game_id, g.game_date,
               CASE WHEN tgs.is_team1=1 THEN t2.name ELSE t1.name END AS opponent,
               tgs.pts, tgs.opp_pts, tgs.fgm, tgs.fga, tgs.tpm, tgs.tpa, tgs.ftm, tgs.fta,
               tgs.reb, tgs.ast, tgs.tov
        FROM team_game_stats tgs
        JOIN games g ON g.id = tgs.game_id
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE tgs.team_id = ?
        ORDER BY g.game_date, g.id
        """,
        (team_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["fg_pct"] = round(d["fgm"] / d["fga"] * 100, 1) if d["fga"] else None
        d["tp_pct"] = round(d["tpm"] / d["tpa"] * 100, 1) if d["tpa"] else None
        out.append(d)
    return out


# -------------------------------------------------------- five-minute splits
FIVE_MIN_SEGMENTS = 8
SEGMENT_SECONDS = 300  # 5 minutes


def _empty_five_min_row():
    return {
        "fg2_m": 0, "fg2_a": 0, "fg3_m": 0, "fg3_a": 0, "ft_m": 0, "ft_a": 0,
        "oreb": 0, "dreb": 0, "fouls": 0, "fouled": 0, "tov": 0, "stl": 0,
    }


def _team_last_n_game_ids(conn, team_id, n):
    rows = conn.execute(
        """SELECT g.id FROM team_game_stats tgs JOIN games g ON g.id = tgs.game_id
           WHERE tgs.team_id = ? ORDER BY g.game_date DESC, g.id DESC LIMIT ?""",
        (team_id, n),
    ).fetchall()
    return [r["id"] for r in rows]


def _events_for_team(conn, team_id, game_ids):
    """This team's own tracked events (offense), optionally restricted to
    game_ids (None = every game this season)."""
    if game_ids is not None:
        if not game_ids:
            return []
        placeholders = ",".join("?" * len(game_ids))
        return conn.execute(
            f"SELECT action_type, made, game_seconds_elapsed FROM pbp_events "
            f"WHERE team_id = ? AND game_seconds_elapsed IS NOT NULL AND game_id IN ({placeholders})",
            (team_id, *game_ids),
        ).fetchall()
    return conn.execute(
        "SELECT action_type, made, game_seconds_elapsed FROM pbp_events "
        "WHERE team_id = ? AND game_seconds_elapsed IS NOT NULL",
        (team_id,),
    ).fetchall()


def _events_against_team(conn, team_id, game_ids):
    """The OPPONENT's tracked events in games team_id played -- "what the
    defense gave up." game_ids (None = every game this season) always means
    team_id's own games, same as _events_for_team."""
    sql = (
        "SELECT e.action_type, e.made, e.game_seconds_elapsed "
        "FROM pbp_events e JOIN games g ON g.id = e.game_id "
        "WHERE (g.team1_id = ? OR g.team2_id = ?) AND e.team_id != ? "
        "AND e.game_seconds_elapsed IS NOT NULL"
    )
    params = [team_id, team_id, team_id]
    if game_ids is not None:
        if not game_ids:
            return []
        placeholders = ",".join("?" * len(game_ids))
        sql += f" AND g.id IN ({placeholders})"
        params += list(game_ids)
    return conn.execute(sql, params).fetchall()


def _aggregate_five_min_rows(rows):
    agg = [_empty_five_min_row() for _ in range(FIVE_MIN_SEGMENTS)]
    for r in rows:
        seg = min(r["game_seconds_elapsed"] // SEGMENT_SECONDS, FIVE_MIN_SEGMENTS - 1)
        row = agg[seg]
        at = r["action_type"]
        if at == "2pt":
            row["fg2_a"] += 1
            row["fg2_m"] += r["made"] or 0
        elif at == "3pt":
            row["fg3_a"] += 1
            row["fg3_m"] += r["made"] or 0
        elif at == "freethrow":
            row["ft_a"] += 1
            row["ft_m"] += r["made"] or 0
        elif at == "rebound_off":
            row["oreb"] += 1
        elif at == "rebound_def":
            row["dreb"] += 1
        elif at == "foul":
            row["fouls"] += 1
        elif at == "foulon":
            row["fouled"] += 1
        elif at == "turnover":
            row["tov"] += 1
        elif at == "steal":
            row["stl"] += 1
    return agg


def _five_min_raw_for_team(conn, team_id, game_ids=None, against=False):
    """game_ids=None -> every game (season); an explicit list (possibly
    empty) restricts to just those games (the "last 5" scope). against=True
    fetches the OPPONENT's events in team_id's games instead of team_id's
    own (i.e. defense: what the other team did)."""
    fetch = _events_against_team if against else _events_for_team
    return _aggregate_five_min_rows(fetch(conn, team_id, game_ids))


def _pct(m, a):
    return round(m / a * 100, 1) if a else None


# (key, higher-is-better) -- fouls/turnovers are the only "lower is better"
# counting stats on offense; everything else, more is good.
FIVE_MIN_AVG_STATS = [
    ("pts", True), ("oreb", True), ("dreb", True),
    ("fouled", True), ("stl", True), ("fouls", False), ("tov", False),
]
# Defense mirrors the same categories, but direction flips for whatever's
# bad for us when the OPPONENT does it more (points/rebounds/steals against
# us, us fouling them) -- fewer is better defense. Opponents fouling more
# (free throws for us) or turning it over more (forced by us) stays good.
FIVE_MIN_AVG_STATS_DEFENSE = [
    ("pts", False), ("oreb", False), ("dreb", False),
    ("fouled", False), ("stl", False), ("fouls", True), ("tov", True),
]
FIVE_MIN_SHOOTING_STATS = ["fg2", "fg3", "ft"]


def _five_minute_splits_impl(team_id, scope, against):
    conn = db.get_conn()
    team_ids = [r["id"] for r in conn.execute("SELECT id FROM teams").fetchall()]

    if scope == "last5":
        game_ids_map = {tid: _team_last_n_game_ids(conn, tid, 5) for tid in team_ids}
        gp_map = {tid: len(gids) for tid, gids in game_ids_map.items()}
        raw_by_team = {tid: _five_min_raw_for_team(conn, tid, game_ids_map[tid], against) for tid in team_ids}
    else:
        gp_map = {
            r["team_id"]: r["c"] for r in
            conn.execute("SELECT team_id, COUNT(*) c FROM team_game_stats GROUP BY team_id").fetchall()
        }
        raw_by_team = {tid: _five_min_raw_for_team(conn, tid, None, against) for tid in team_ids}
    conn.close()

    def derived_for(tid):
        gp = gp_map.get(tid) or 1
        out = []
        for row in raw_by_team[tid]:
            pts_total = row["fg2_m"] * 2 + row["fg3_m"] * 3 + row["ft_m"]
            out.append({
                "pts": pts_total / gp, "oreb": row["oreb"] / gp, "dreb": row["dreb"] / gp,
                "fouls": row["fouls"] / gp, "fouled": row["fouled"] / gp,
                "tov": row["tov"] / gp, "stl": row["stl"] / gp,
                "fg2_pct": _pct(row["fg2_m"], row["fg2_a"]), "fg2_m": row["fg2_m"], "fg2_a": row["fg2_a"],
                "fg3_pct": _pct(row["fg3_m"], row["fg3_a"]), "fg3_m": row["fg3_m"], "fg3_a": row["fg3_a"],
                "ft_pct": _pct(row["ft_m"], row["ft_a"]), "ft_m": row["ft_m"], "ft_a": row["ft_a"],
            })
        return out

    derived_by_team = {tid: derived_for(tid) for tid in team_ids}

    def rank_for(value_key, seg_idx, higher_is_better):
        entries = [
            (tid, derived_by_team[tid][seg_idx][value_key]) for tid in team_ids
            if derived_by_team[tid][seg_idx][value_key] is not None
        ]
        entries.sort(key=lambda kv: kv[1], reverse=higher_is_better)
        pool = len(entries)
        rank = next((i for i, (tid, _) in enumerate(entries, 1) if tid == team_id), None)
        return rank, pool

    avg_stats = FIVE_MIN_AVG_STATS_DEFENSE if against else FIVE_MIN_AVG_STATS
    # lower opponent % / fewer opponent FT attempts = better defense.
    shooting_higher_is_better = not against

    out = []
    for i in range(FIVE_MIN_SEGMENTS):
        d = derived_by_team[team_id][i]
        entry = {"segment": i, "label": f"{i * 5}-{i * 5 + 5}"}
        for key, higher_is_better in avg_stats:
            rank, pool = rank_for(key, i, higher_is_better)
            entry[key] = {"value": round(d[key], 1), "rank": rank, "pool": pool}
        for sk in FIVE_MIN_SHOOTING_STATS:
            # FT is ranked by volume (attempts) rather than % -- getting to
            # the line more (or, on defense, allowing fewer trips) is a
            # better signal than FT% off a small sample. 2PT/3PT stay
            # ranked by shooting %.
            rank_key = f"{sk}_a" if sk == "ft" else f"{sk}_pct"
            rank, pool = rank_for(rank_key, i, shooting_higher_is_better)
            entry[sk] = {"m": d[f"{sk}_m"], "a": d[f"{sk}_a"], "pct": d[f"{sk}_pct"], "rank": rank, "pool": pool}
        out.append(entry)
    return out


@router.get("/teams/{team_id}/five-minute-splits")
def team_five_minute_splits(team_id: int, scope: str = "season"):
    """Every tracked stat, bucketed into the 8 five-minute segments of
    regulation (0-5, 5-10, ..., 35-40), for one team. Shooting (2PT/3PT/FT)
    stays totals (makes/attempts/%); everything else is a per-game average.
    Each stat also carries this team's league rank for that specific
    segment (1 = best), so the UI can flag top-2/bottom-3 segments. 2PT/3PT
    are ranked by shooting %; FT is ranked by attempts (volume), not %.

    scope='season' (default): every game imported so far.
    scope='last5': just this team's 5 most recent games -- and, so the
    league-wide ranks stay an apples-to-apples "recent form" comparison,
    every OTHER team is also limited to (each of) their own last 5 games."""
    return _five_minute_splits_impl(team_id, scope, against=False)


@router.get("/teams/{team_id}/five-minute-splits-against")
def team_five_minute_splits_against(team_id: int, scope: str = "season"):
    """Same shape as five-minute-splits, but for what OPPONENTS did against
    this team (defense) -- "good" flips direction for whatever's bad for us
    when the opponent does it more (points/rebounds/steals against us, us
    fouling them)."""
    return _five_minute_splits_impl(team_id, scope, against=True)


# Every pbp_events action_type that gets credited to whichever 5-man unit
# is actually on court when it happens. Substitutions are excluded here --
# they don't produce anything, they just change who's on court.
_LINEUP_PRODUCTION_TYPES = {
    "2pt", "3pt", "freethrow", "rebound_off", "rebound_def",
    "turnover", "steal", "foul", "foulon", "assist", "block",
}


def _empty_lineup_totals():
    return {
        "pts": 0, "fg2m": 0, "fg2a": 0, "fg3m": 0, "fg3a": 0, "ftm": 0, "fta": 0,
        "oreb": 0, "dreb": 0, "tov": 0, "stl": 0, "blk": 0, "ast": 0,
        "fouls": 0, "fouled": 0, "events": 0,
    }


def _team_lineup_combos(conn, team_id, game_ids=None):
    """Reconstructs every ACTUAL 5-man on-court unit this team has used, by
    replaying each game's play-by-play in exact chronological order (the
    feed's own action_number) starting from that game's real starting 5
    (player_game_stats.starter) and applying every substitution as it
    happens. Every scoring/rebounding/etc event that occurs while a given
    5 players are on court together gets credited to that exact combo.

    game_ids=None -> every game this team has played. An explicit list
    restricts the reconstruction to just those games (e.g. the last 3, for
    the Matchup Scout's lineup section -- rosters turn over enough during a
    season that a full-season combo list can include players who've since
    moved on).

    Returns a list of {player_ids, totals, games} -- `games` is the set of
    game_ids this exact 5-man combo shared the floor in at all (used both
    to gate "how many games together" and to turn raw totals into
    per-game averages)."""
    if game_ids is None:
        game_rows = conn.execute(
            "SELECT id FROM games WHERE team1_id = ? OR team2_id = ? ORDER BY id",
            (team_id, team_id),
        ).fetchall()
        game_ids = [r["id"] for r in game_rows]
    if not game_ids:
        return []
    placeholders = ",".join("?" * len(game_ids))

    starters_by_game = {}
    for r in conn.execute(
        f"""SELECT game_id, player_id FROM player_game_stats
            WHERE team_id = ? AND starter = 1 AND game_id IN ({placeholders})""",
        (team_id, *game_ids),
    ).fetchall():
        starters_by_game.setdefault(r["game_id"], set()).add(r["player_id"])

    events = conn.execute(
        f"""SELECT game_id, player_id, action_type, sub_type, made
            FROM pbp_events
            WHERE team_id = ? AND game_id IN ({placeholders}) AND action_number IS NOT NULL
            ORDER BY game_id, action_number""",
        (team_id, *game_ids),
    ).fetchall()

    combos = {}  # tuple(sorted(player_ids)) -> {"totals": {...}, "games": set()}
    current_game = None
    on_court = set()

    for e in events:
        if e["game_id"] != current_game:
            current_game = e["game_id"]
            on_court = set(starters_by_game.get(current_game, ()))

        at = e["action_type"]
        if at == "substitution":
            pid = e["player_id"]
            if pid is not None:
                if e["sub_type"] == "out":
                    on_court.discard(pid)
                elif e["sub_type"] == "in":
                    on_court.add(pid)
            continue

        # Only credit a production event when we're confident about the
        # full 5 -- a data glitch (missed sub, mid-period import point)
        # can transiently leave more/fewer than 5 tracked, and those
        # moments shouldn't get attributed to a bogus "combo".
        if len(on_court) != 5 or at not in _LINEUP_PRODUCTION_TYPES:
            continue

        key = tuple(sorted(on_court))
        combo = combos.setdefault(key, {"totals": _empty_lineup_totals(), "games": set()})
        t = combo["totals"]
        combo["games"].add(current_game)
        t["events"] += 1
        made = e["made"]

        if at == "2pt":
            t["fg2a"] += 1
            if made:
                t["fg2m"] += 1
                t["pts"] += 2
        elif at == "3pt":
            t["fg3a"] += 1
            if made:
                t["fg3m"] += 1
                t["pts"] += 3
        elif at == "freethrow":
            t["fta"] += 1
            if made:
                t["ftm"] += 1
                t["pts"] += 1
        elif at == "rebound_off":
            t["oreb"] += 1
        elif at == "rebound_def":
            t["dreb"] += 1
        elif at == "turnover":
            t["tov"] += 1
        elif at == "steal":
            t["stl"] += 1
        elif at == "block":
            t["blk"] += 1
        elif at == "assist":
            t["ast"] += 1
        elif at == "foul":
            t["fouls"] += 1
        elif at == "foulon":
            t["fouled"] += 1

    return [{"player_ids": list(key), "totals": c["totals"], "games": c["games"]} for key, c in combos.items()]


def _lineup_possessions(t):
    """Standard team-level possession estimate (FGA + 0.44*FTA + TOV -
    OREB), built directly from this lineup's own shot attempts/free
    throws/turnovers/rebounds while on court together -- this is what
    "most popular" is ranked by, i.e. how much actual game action these 5
    shared, not just raw playing time."""
    fga = t["fg2a"] + t["fg3a"]
    return fga + 0.44 * t["fta"] + t["tov"] - t["oreb"]


def _lineup_stat_line(t, gp):
    """This combo's ACTUAL combined production, per game, averaged only
    over the games in which these exact 5 shared the floor at all --
    shooting % from the summed makes/attempts, not an average of
    percentages."""
    return {
        "pts": round(t["pts"] / gp, 1),
        "reb": round((t["oreb"] + t["dreb"]) / gp, 1),
        "ast": round(t["ast"] / gp, 1),
        "stl": round(t["stl"] / gp, 1),
        "blk": round(t["blk"] / gp, 1),
        "tov": round(t["tov"] / gp, 1),
        "pf": round(t["fouls"] / gp, 1),
        "fg2": {"m": round(t["fg2m"] / gp, 1), "a": round(t["fg2a"] / gp, 1), "pct": _pct(t["fg2m"], t["fg2a"])},
        "fg3": {"m": round(t["fg3m"] / gp, 1), "a": round(t["fg3a"] / gp, 1), "pct": _pct(t["fg3m"], t["fg3a"])},
        "ft": {"m": round(t["ftm"] / gp, 1), "a": round(t["fta"] / gp, 1), "pct": _pct(t["ftm"], t["fta"])},
    }


@router.get("/teams/{team_id}/lineups")
def team_lineups(team_id: int):
    """The most-used ACTUAL 5-man on-court combinations for this team,
    reconstructed from each game's real starters + substitution log (not
    individual season/last-5 averages). "Popularity" is an estimated
    possessions-together count built from that combo's own shots
    attempted/free throws/turnovers/rebounds while all 5 shared the floor.
    Each of the top 3 lineups carries its ACTUAL combined stat line
    (points, 2PT/3PT/FT, rebounds, assists, steals, blocks, turnovers,
    fouls) averaged per game across only the games it played together --
    i.e. the real points production for that specific 5, not a sum of
    individual season averages."""
    conn = db.get_conn()
    combos = _team_lineup_combos(conn, team_id)
    player_rows = conn.execute(
        "SELECT id, name, photo_url FROM players WHERE team_id = ?", (team_id,)
    ).fetchall()
    conn.close()
    player_info = {r["id"]: {"player_id": r["id"], "name": r["name"], "photo_url": r["photo_url"]} for r in player_rows}

    def players_for(ids):
        return [player_info.get(pid, {"player_id": pid, "name": "Unknown", "photo_url": None}) for pid in ids]

    if not combos:
        return {"summary": [], "lineups": []}

    ranked = sorted(combos, key=lambda c: _lineup_possessions(c["totals"]), reverse=True)

    summary = [
        {
            "players": players_for(c["player_ids"]),
            "games_together": len(c["games"]),
            "possessions": round(_lineup_possessions(c["totals"]), 1),
        }
        for c in ranked[:15]
    ]

    lineups = []
    for i, c in enumerate(ranked[:3], 1):
        gp = len(c["games"]) or 1
        lineups.append({
            "label": f"Lineup {i}",
            "players": players_for(c["player_ids"]),
            "games_together": len(c["games"]),
            "possessions": round(_lineup_possessions(c["totals"]), 1),
            "stats": _lineup_stat_line(c["totals"], gp),
        })

    return {"summary": summary, "lineups": lineups}


BUCKETS = zones.BUCKETS
_bucket_for = zones.bucket_for


def _empty_bucket_row():
    return {
        "fg2_m": 0, "fg2_a": 0, "fg3_m": 0, "fg3_a": 0, "ft_m": 0, "ft_a": 0,
        "oreb_2pt": 0, "oreb_3pt": 0, "fouls": 0, "fouled": 0, "tov": 0,
    }


_AGAINST_EVENTS_SQL = """
    SELECT e.action_type, e.made, e.shot_clock_used, e.off_reb_source
    FROM pbp_events e JOIN games g ON g.id = e.game_id
    WHERE (g.team1_id = ? OR g.team2_id = ?) AND e.team_id != ?
"""


def _aggregate_clock_rows(rows):
    agg = {b: _empty_bucket_row() for b in BUCKETS}
    for r in rows:
        b = _bucket_for(r["shot_clock_used"])
        if b is None:
            continue
        row = agg[b]
        at = r["action_type"]
        if at == "2pt":
            row["fg2_a"] += 1
            row["fg2_m"] += r["made"] or 0
        elif at == "3pt":
            row["fg3_a"] += 1
            row["fg3_m"] += r["made"] or 0
        elif at == "freethrow":
            row["ft_a"] += 1
            row["ft_m"] += r["made"] or 0
        elif at == "rebound_off":
            if r["off_reb_source"] == "2pt":
                row["oreb_2pt"] += 1
            elif r["off_reb_source"] == "3pt":
                row["oreb_3pt"] += 1
        elif at == "foul":
            row["fouls"] += 1
        elif at == "foulon":
            row["fouled"] += 1
        elif at == "turnover":
            row["tov"] += 1

    def pct(m, a):
        return round(m / a * 100, 1) if a else None

    out = []
    for b in BUCKETS:
        row = agg[b]
        out.append({
            "label": b,
            "pts": row["fg2_m"] * 2 + row["fg3_m"] * 3 + row["ft_m"],
            "fg2": {"m": row["fg2_m"], "a": row["fg2_a"], "pct": pct(row["fg2_m"], row["fg2_a"])},
            "fg3": {"m": row["fg3_m"], "a": row["fg3_a"], "pct": pct(row["fg3_m"], row["fg3_a"])},
            "ft": {"m": row["ft_m"], "a": row["ft_a"], "pct": pct(row["ft_m"], row["ft_a"])},
            "oreb_2pt": row["oreb_2pt"], "oreb_3pt": row["oreb_3pt"],
            "fouls": row["fouls"], "fouled": row["fouled"], "tov": row["tov"],
        })
    return out


def _clock_breakdown(conn, table_col, entity_id):
    rows = conn.execute(
        f"SELECT action_type, made, shot_clock_used, off_reb_source "
        f"FROM pbp_events WHERE {table_col} = ?",
        (entity_id,),
    ).fetchall()
    return _aggregate_clock_rows(rows)


def _clock_breakdown_against(conn, team_id):
    rows = conn.execute(_AGAINST_EVENTS_SQL, (team_id, team_id, team_id)).fetchall()
    return _aggregate_clock_rows(rows)


def _clock_events_for_team(conn, team_id, game_ids=None):
    """Team's own events with shot-clock fields -- game_ids=None means
    every game this season; an explicit (possibly empty) list restricts to
    just those games (last-5-games / a single head-to-head game)."""
    if game_ids is not None:
        if not game_ids:
            return []
        placeholders = ",".join("?" * len(game_ids))
        return conn.execute(
            f"SELECT action_type, made, shot_clock_used, off_reb_source FROM pbp_events "
            f"WHERE team_id = ? AND game_id IN ({placeholders})",
            (team_id, *game_ids),
        ).fetchall()
    return conn.execute(
        "SELECT action_type, made, shot_clock_used, off_reb_source FROM pbp_events WHERE team_id = ?",
        (team_id,),
    ).fetchall()


def _clock_events_against_team(conn, team_id, game_ids=None):
    """Opponent's events (with shot-clock fields) in team_id's games --
    same game_ids scoping as _clock_events_for_team."""
    sql = _AGAINST_EVENTS_SQL
    params = [team_id, team_id, team_id]
    if game_ids is not None:
        if not game_ids:
            return []
        placeholders = ",".join("?" * len(game_ids))
        sql += f" AND g.id IN ({placeholders})"
        params += list(game_ids)
    return conn.execute(sql, params).fetchall()


def _team_shot_profile(conn, team_id, game_ids, gp, against=False):
    """Unified team production line -- shot-clock-bucketed 2PT/3PT/FT,
    rebounding split by shot type, fouls/turnovers, and a possession
    estimate (FGA + 0.44*FTA + TOV - OREB) with points-per-100. Works for
    a single game (gp=1, game_ids=[game_id]), a last-5-games window, or a
    full season (game_ids=None), and for either the team's own production
    (against=False) or what their opponents did to them (against=True)."""
    fetch = _clock_events_against_team if against else _clock_events_for_team
    rows = fetch(conn, team_id, game_ids)
    buckets = _aggregate_clock_rows(rows)

    totals = {"fg2_m": 0, "fg2_a": 0, "fg3_m": 0, "fg3_a": 0, "ft_m": 0, "ft_a": 0,
              "oreb_2pt": 0, "oreb_3pt": 0, "fouls": 0, "fouled": 0, "tov": 0}
    for b in buckets:
        for k in ("fg2", "fg3", "ft"):
            totals[f"{k}_m"] += b[k]["m"]
            totals[f"{k}_a"] += b[k]["a"]
        totals["oreb_2pt"] += b["oreb_2pt"]
        totals["oreb_3pt"] += b["oreb_3pt"]
        totals["fouls"] += b["fouls"]
        totals["fouled"] += b["fouled"]
        totals["tov"] += b["tov"]
    oreb_total = sum(1 for r in rows if r["action_type"] == "rebound_off")
    dreb_total = sum(1 for r in rows if r["action_type"] == "rebound_def")
    pts = totals["fg2_m"] * 2 + totals["fg3_m"] * 3 + totals["ft_m"]
    fga = totals["fg2_a"] + totals["fg3_a"]
    possessions = fga + 0.44 * totals["ft_a"] + totals["tov"] - oreb_total

    g = gp or 1
    return {
        "gp": gp, "pts": round(pts / g, 1),
        "fg2": {"m": round(totals["fg2_m"] / g, 1), "a": round(totals["fg2_a"] / g, 1), "pct": _pct(totals["fg2_m"], totals["fg2_a"])},
        "fg3": {"m": round(totals["fg3_m"] / g, 1), "a": round(totals["fg3_a"] / g, 1), "pct": _pct(totals["fg3_m"], totals["fg3_a"])},
        "ft": {"m": round(totals["ft_m"] / g, 1), "a": round(totals["ft_a"] / g, 1), "pct": _pct(totals["ft_m"], totals["ft_a"])},
        "oreb": round(oreb_total / g, 1), "oreb_2pt": round(totals["oreb_2pt"] / g, 1), "oreb_3pt": round(totals["oreb_3pt"] / g, 1),
        "dreb": round(dreb_total / g, 1),
        "fouls": round(totals["fouls"] / g, 1), "fouled": round(totals["fouled"] / g, 1), "tov": round(totals["tov"] / g, 1),
        "possessions": round(possessions / g, 1),
        "pts_per_100": round(pts / possessions * 100, 1) if possessions else None,
        "buckets": [{"label": b["label"], "fg2": b["fg2"], "fg3": b["fg3"], "ft": b["ft"]} for b in buckets],
    }


@router.get("/teams/{team_id}/clock-breakdown")
def team_clock_breakdown(team_id: int):
    conn = db.get_conn()
    out = _clock_breakdown(conn, "team_id", team_id)
    conn.close()
    return out


@router.get("/teams/{team_id}/clock-breakdown-against")
def team_clock_breakdown_against(team_id: int):
    conn = db.get_conn()
    out = _clock_breakdown_against(conn, team_id)
    conn.close()
    return out


@router.get("/players/{player_id}/clock-breakdown")
def player_clock_breakdown(player_id: int):
    conn = db.get_conn()
    out = _clock_breakdown(conn, "player_id", player_id)
    conn.close()
    return out


def _zone_breakdown(conn, table_col, entity_id):
    rows = conn.execute(
        f"SELECT x, y, made, action_type, shot_clock_used FROM shots WHERE {table_col} = ?",
        (entity_id,),
    ).fetchall()
    agg = zones.aggregate_zones(rows)
    return zones.zones_as_list(agg)


_AGAINST_SHOTS_SQL = """
    SELECT s.x, s.y, s.made, s.action_type, s.shot_clock_used
    FROM shots s JOIN games g ON g.id = s.game_id
    WHERE (g.team1_id = ? OR g.team2_id = ?) AND s.team_id != ?
"""


def _zone_breakdown_against(conn, team_id):
    rows = conn.execute(_AGAINST_SHOTS_SQL, (team_id, team_id, team_id)).fetchall()
    agg = zones.aggregate_zones(rows)
    return zones.zones_as_list(agg)


@router.get("/teams/{team_id}/zone-breakdown")
def team_zone_breakdown(team_id: int):
    conn = db.get_conn()
    out = _zone_breakdown(conn, "team_id", team_id)
    conn.close()
    return out


@router.get("/teams/{team_id}/zone-breakdown-against")
def team_zone_breakdown_against(team_id: int):
    conn = db.get_conn()
    out = _zone_breakdown_against(conn, team_id)
    conn.close()
    return out


@router.get("/players/{player_id}/zone-breakdown")
def player_zone_breakdown(player_id: int):
    conn = db.get_conn()
    out = _zone_breakdown(conn, "player_id", player_id)
    conn.close()
    return out


@router.get("/teams/{team_id}/zonemap.png")
def team_zonemap(team_id: int):
    png = charts.render_team_zonemap(team_id)
    return Response(content=png, media_type="image/png")


@router.get("/teams/{team_id}/zonemap-against.png")
def team_zonemap_against(team_id: int):
    png = charts.render_team_zonemap_against(team_id)
    return Response(content=png, media_type="image/png")


@router.get("/players/{player_id}/zonemap.png")
def player_zonemap(player_id: int):
    png = charts.render_player_zonemap(player_id)
    return Response(content=png, media_type="image/png")


@router.get("/teams/{team_id}/shotchart.png")
def team_shotchart(team_id: int):
    png = charts.render_team_shotchart(team_id)
    return Response(content=png, media_type="image/png")


@router.get("/teams/{team_id}/shotchart-against.png")
def team_shotchart_against(team_id: int):
    png = charts.render_team_shotchart_against(team_id)
    return Response(content=png, media_type="image/png")


@router.get("/teams/{team_id}/shots")
def team_shots(team_id: int):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT x, y, made, action_type, sub_type, shot_clock_used, possession_type "
        "FROM shots WHERE team_id = ?",
        (team_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- players -
@router.get("/players")
def leaderboards(min_games: int = 0):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.photo_url, t.name AS team, t.id AS team_id, t.logo_url AS team_logo_url,
               COUNT(*) AS gp,
               SUM(pgs.pts) AS pts, SUM(pgs.reb) AS reb, SUM(pgs.ast) AS ast,
               SUM(pgs.stl) AS stl, SUM(pgs.blk) AS blk, SUM(pgs.tov) AS tov,
               SUM(pgs.fgm) AS fgm, SUM(pgs.fga) AS fga,
               SUM(pgs.tpm) AS tpm, SUM(pgs.tpa) AS tpa,
               SUM(pgs.ftm) AS ftm, SUM(pgs.fta) AS fta,
               SUM(pgs.minutes_sec) AS minutes_sec
        FROM player_game_stats pgs
        JOIN players p ON p.id = pgs.player_id
        JOIN teams t ON t.id = pgs.team_id
        GROUP BY p.id
        HAVING gp >= ?
        ORDER BY pts DESC
        """,
        (min_games,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        gp = r["gp"] or 1
        out.append({
            "player_id": r["id"], "name": r["name"], "photo_url": r["photo_url"],
            "team": r["team"], "team_id": r["team_id"], "team_logo_url": r["team_logo_url"],
            "gp": r["gp"],
            "ppg": round(r["pts"] / gp, 1), "rpg": round(r["reb"] / gp, 1),
            "apg": round(r["ast"] / gp, 1), "spg": round(r["stl"] / gp, 1),
            "bpg": round(r["blk"] / gp, 1), "topg": round(r["tov"] / gp, 1),
            "mpg": round((r["minutes_sec"] or 0) / gp / 60, 1),
            "fg_pct": round(r["fgm"] / r["fga"] * 100, 1) if r["fga"] else None,
            "tp_pct": round(r["tpm"] / r["tpa"] * 100, 1) if r["tpa"] else None,
            "ft_pct": round(r["ftm"] / r["fta"] * 100, 1) if r["fta"] else None,
            "fga": r["fga"], "tpa": r["tpa"], "fta": r["fta"],
        })
    return out


@router.get("/players/{player_id}/trend")
def player_trend(player_id: int):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT g.id AS game_id, g.game_date,
               CASE WHEN pgs.team_id = g.team1_id THEN t2.name ELSE t1.name END AS opponent,
               pgs.minutes_sec, pgs.pts, pgs.reb, pgs.ast, pgs.stl, pgs.blk, pgs.tov,
               pgs.fgm, pgs.fga, pgs.tpm, pgs.tpa, pgs.ftm, pgs.fta
        FROM player_game_stats pgs
        JOIN games g ON g.id = pgs.game_id
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE pgs.player_id = ?
        ORDER BY g.game_date, g.id
        """,
        (player_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["fg_pct"] = round(d["fgm"] / d["fga"] * 100, 1) if d["fga"] else None
        out.append(d)
    return out


@router.get("/players/{player_id}/shotchart.png")
def player_shotchart(player_id: int):
    png = charts.render_player_shotchart(player_id)
    return Response(content=png, media_type="image/png")


@router.get("/players/{player_id}/shots")
def player_shots(player_id: int):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT x, y, made, action_type, sub_type, shot_clock_used, possession_type "
        "FROM shots WHERE player_id = ?",
        (player_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ games -
@router.get("/games")
def list_games():
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT g.id, g.game_date, t1.name AS team1, t2.name AS team2,
               t1.logo_url AS team1_logo_url, t2.logo_url AS team2_logo_url,
               g.team1_score, g.team2_score, g.source_filename, g.imported_at
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        ORDER BY g.game_date DESC, g.id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/games/{game_id}")
def game_detail(game_id: int):
    conn = db.get_conn()
    game = conn.execute(
        """
        SELECT g.id, g.game_date, t1.id AS team1_id, t1.name AS team1, t2.id AS team2_id, t2.name AS team2,
               t1.logo_url AS team1_logo_url, t2.logo_url AS team2_logo_url,
               g.team1_score, g.team2_score
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE g.id = ?
        """,
        (game_id,),
    ).fetchone()
    if not game:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")

    box = {}
    for side, team_id in (("team1", game["team1_id"]), ("team2", game["team2_id"])):
        players = conn.execute(
            """
            SELECT p.name, p.photo_url, pgs.minutes_sec, pgs.pts, pgs.reb, pgs.ast, pgs.stl, pgs.blk,
                   pgs.tov, pgs.pf, pgs.fgm, pgs.fga, pgs.tpm, pgs.tpa, pgs.ftm, pgs.fta, p.id AS player_id
            FROM player_game_stats pgs
            JOIN players p ON p.id = pgs.player_id
            WHERE pgs.game_id = ? AND pgs.team_id = ?
            ORDER BY pgs.pts DESC
            """,
            (game_id, team_id),
        ).fetchall()
        box[side] = [dict(r) for r in players]
    conn.close()
    return {**dict(game), "box": box}


@router.get("/games/{game_id}/five-minute-scoring")
def game_five_minute_scoring(game_id: int):
    """Points scored by each team, bucketed into the 8 five-minute segments
    of regulation (0-5, 5-10, ..., 35-40) -- a single game's scoring flow,
    for the Game Log detail popup (distinct from the season-wide "5 Minute
    Splits" tab, which aggregates across many games for one team)."""
    conn = db.get_conn()
    game = conn.execute("SELECT team1_id, team2_id FROM games WHERE id = ?", (game_id,)).fetchone()
    if not game:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")

    def points_by_segment(team_id):
        rows = _events_for_team(conn, team_id, [game_id])
        agg = _aggregate_five_min_rows(rows)
        return [row["fg2_m"] * 2 + row["fg3_m"] * 3 + row["ft_m"] for row in agg]

    result = {
        "labels": [f"{i * 5}-{i * 5 + 5}" for i in range(FIVE_MIN_SEGMENTS)],
        "team1_points": points_by_segment(game["team1_id"]),
        "team2_points": points_by_segment(game["team2_id"]),
    }
    conn.close()
    return result


@router.get("/games/{game_id}/shot-clock-scoring")
def game_shot_clock_scoring(game_id: int):
    """Each team's full shot-clock breakdown (0-8s / 8-18s / 18+s) for this
    single game -- same shape as /teams/{id}/clock-breakdown (2PT/3PT/FT
    makes-attempts-%, plus points per bucket), just scoped to one game
    instead of the whole season. Powers the Game Log detail popup's
    per-team "points by shot-clock region" chart + breakdown table."""
    conn = db.get_conn()
    game = conn.execute("SELECT team1_id, team2_id FROM games WHERE id = ?", (game_id,)).fetchone()
    if not game:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")

    def buckets_for(team_id):
        rows = conn.execute(
            "SELECT action_type, made, shot_clock_used, off_reb_source FROM pbp_events "
            "WHERE team_id = ? AND game_id = ?",
            (team_id, game_id),
        ).fetchall()
        return _aggregate_clock_rows(rows)

    result = {
        "team1_buckets": buckets_for(game["team1_id"]),
        "team2_buckets": buckets_for(game["team2_id"]),
    }
    conn.close()
    return result


@router.get("/games/{game_id}/shot-clock-top-scorers")
def game_shot_clock_top_scorers(game_id: int, bucket: str = "0-8", limit: int = 5):
    """Top scorers (either team, combined) in this single game for just one
    shot-clock region -- default 0-8s (early clock / transition). Each
    player carries points scored in that region plus their 2PT/3PT/FT
    makes-attempts-% split, same shape as the per-team clock tables."""
    if bucket not in BUCKETS:
        raise HTTPException(status_code=400, detail=f"bucket must be one of {BUCKETS}")

    conn = db.get_conn()
    rows = conn.execute(
        """SELECT e.player_id, e.action_type, e.made, e.shot_clock_used,
                  p.name, p.photo_url, t.name AS team_name, t.logo_url AS team_logo_url
           FROM pbp_events e
           JOIN players p ON p.id = e.player_id
           JOIN teams t ON t.id = p.team_id
           WHERE e.game_id = ? AND e.player_id IS NOT NULL
             AND e.action_type IN ('2pt', '3pt', 'freethrow')""",
        (game_id,),
    ).fetchall()
    conn.close()

    agg = {}
    for r in rows:
        if _bucket_for(r["shot_clock_used"]) != bucket:
            continue
        pid = r["player_id"]
        d = agg.setdefault(pid, {
            "player_id": pid, "name": r["name"], "photo_url": r["photo_url"],
            "team_name": r["team_name"], "team_logo_url": r["team_logo_url"],
            "fg2_m": 0, "fg2_a": 0, "fg3_m": 0, "fg3_a": 0, "ft_m": 0, "ft_a": 0,
        })
        at = r["action_type"]
        if at == "2pt":
            d["fg2_a"] += 1
            d["fg2_m"] += r["made"] or 0
        elif at == "3pt":
            d["fg3_a"] += 1
            d["fg3_m"] += r["made"] or 0
        elif at == "freethrow":
            d["ft_a"] += 1
            d["ft_m"] += r["made"] or 0

    def pct(m, a):
        return round(m / a * 100, 1) if a else None

    out = []
    for d in agg.values():
        pts = d["fg2_m"] * 2 + d["fg3_m"] * 3 + d["ft_m"]
        if pts <= 0:
            continue
        out.append({
            "player_id": d["player_id"], "name": d["name"], "photo_url": d["photo_url"],
            "team_name": d["team_name"], "team_logo_url": d["team_logo_url"],
            "pts": pts,
            "fg2": {"m": d["fg2_m"], "a": d["fg2_a"], "pct": pct(d["fg2_m"], d["fg2_a"])},
            "fg3": {"m": d["fg3_m"], "a": d["fg3_a"], "pct": pct(d["fg3_m"], d["fg3_a"])},
            "ft": {"m": d["ft_m"], "a": d["ft_a"], "pct": pct(d["ft_m"], d["ft_a"])},
        })
    out.sort(key=lambda x: x["pts"], reverse=True)
    return out[:limit]
