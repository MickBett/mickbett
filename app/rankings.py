"""Rankings across every stat line the app tracks -- traditional per-game
box score averages, plus every shot-clock-bucketed stat (Overall / 0-8s /
8-18s / 18+s), for both players and teams.
"""
from . import db, zones

CLOCK_BUCKETS = ["overall"] + zones.BUCKETS  # ["overall", "0-8", "8-18", "18+"]

# (key, label, direction) -- direction: "desc" = higher is better/ranked first
TRAD_PLAYER_METRICS = [
    ("ppg", "Points", "desc"), ("rpg", "Rebounds", "desc"), ("apg", "Assists", "desc"),
    ("spg", "Steals", "desc"), ("bpg", "Blocks", "desc"), ("topg", "Turnovers", "asc"),
    ("mpg", "Minutes", "desc"), ("fg_pct", "Field Goal %", "desc"),
    ("tp_pct", "3-Point %", "desc"), ("ft_pct", "Free Throw %", "desc"),
]

TRAD_TEAM_METRICS = [
    ("ppg", "Points Scored", "desc"), ("papg", "Points Allowed", "asc"),
    ("diff", "Point Differential", "desc"), ("win_pct", "Win %", "desc"),
    ("rpg", "Rebounds", "desc"), ("apg", "Assists", "desc"), ("spg", "Steals", "desc"),
    ("bpg", "Blocks", "desc"), ("topg", "Turnovers", "asc"),
    ("fg_pct", "Field Goal %", "desc"), ("tp_pct", "3-Point %", "desc"), ("ft_pct", "Free Throw %", "desc"),
]

# (key, label, kind, direction) -- kind: "pct" (makes/attempts) or "rate" (count per game)
CLOCK_METRICS = [
    ("2pt_pct", "2PT %", "pct", "desc"),
    ("3pt_pct", "3PT %", "pct", "desc"),
    ("ft_pct", "FT %", "pct", "desc"),
    ("oreb_2pt", "OREB off 2PT (per game)", "rate", "desc"),
    ("oreb_3pt", "OREB off 3PT (per game)", "rate", "desc"),
    ("fouls", "Fouls committed (per game)", "rate", "asc"),
    ("fouled", "Fouled / drawn (per game)", "rate", "desc"),
    ("tov", "Turnovers, live-ball (per game)", "rate", "asc"),
]

MIN_ATTEMPTS_FOR_PCT = 5


def tier_label(avg_rank):
    """Strong/Middle/Weak read for a (possibly fractional, e.g. an average
    across several stats) league rank out of 10 -- shared threshold with
    the 5-Minute tab's read table: below 4 = Strong, 4-7 = Middle, else
    Weak."""
    if avg_rank < 4:
        return "Strong"
    if avg_rank <= 7:
        return "Middle"
    return "Weak"


def _pick(options, seed):
    """Deterministic-but-varied phrasing: same matchup always reads the
    same way (reproducible, cacheable), but different matchups/segments
    land on different phrasing rather than one fixed template every time."""
    return options[seed % len(options)]


def possessive(name):
    """Grammatically correct possessive for a team/player name -- "Sea
    Bears'" not "Sea Bears's" for names already ending in s."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def metrics_menu():
    """Grouped list of every rankable category, for building the UI selector."""
    groups = [{"group": "Season Averages", "items": [
        {"key": f"trad:{k}", "label": label} for k, label, _ in TRAD_PLAYER_METRICS
    ]}]
    for bucket in CLOCK_BUCKETS:
        blabel = "Overall" if bucket == "overall" else f"{bucket}s"
        groups.append({"group": f"Shot Clock — {blabel}", "items": [
            {"key": f"clock:{mk}:{bucket}", "label": ml} for mk, ml, _, _ in CLOCK_METRICS
        ]})
    return groups


def _rank(rows, value_key, direction):
    rows = [r for r in rows if r[value_key] is not None]
    rows.sort(key=lambda r: r[value_key], reverse=(direction == "desc"))
    out = []
    for i, r in enumerate(rows, 1):
        out.append({**r, "rank": i})
    return out


# ------------------------------------------------------------- traditional -
def _trad_player_rows(conn, min_games, scope="season"):
    """scope: 'season' (every game) or 'last3' (each TEAM's own most recent
    3 games -- not each player's individually. With heavy roster turnover,
    "last 3 games" should mean a snapshot of who's actually playing for a
    team right now and how they're performing, not stats that could span
    games from weeks ago for a player who barely features. A player who's
    only appeared in 1 of their team's last 3 games shows gp=1, not
    padded out with older games from before a trade/signing/return."""
    if scope == "last3":
        rows = conn.execute(
            """
            WITH team_games AS (
                SELECT tgs.team_id, tgs.game_id, ROW_NUMBER() OVER (
                    PARTITION BY tgs.team_id ORDER BY g.game_date DESC, g.id DESC
                ) AS rn
                FROM team_game_stats tgs
                JOIN games g ON g.id = tgs.game_id
            ),
            recent_team_games AS (
                SELECT team_id, game_id FROM team_games WHERE rn <= 3
            )
            SELECT p.id, p.name, p.photo_url, t.name AS team, t.logo_url AS team_logo_url, COUNT(*) AS gp,
                   SUM(pgs.pts) AS pts, SUM(pgs.reb) AS reb, SUM(pgs.ast) AS ast,
                   SUM(pgs.stl) AS stl, SUM(pgs.blk) AS blk, SUM(pgs.tov) AS tov,
                   SUM(pgs.fgm) AS fgm, SUM(pgs.fga) AS fga,
                   SUM(pgs.tpm) AS tpm, SUM(pgs.tpa) AS tpa,
                   SUM(pgs.ftm) AS ftm, SUM(pgs.fta) AS fta,
                   SUM(pgs.minutes_sec) AS minutes_sec
            FROM player_game_stats pgs
            JOIN recent_team_games rtg ON rtg.team_id = pgs.team_id AND rtg.game_id = pgs.game_id
            JOIN players p ON p.id = pgs.player_id
            JOIN teams t ON t.id = pgs.team_id
            GROUP BY p.id
            HAVING gp >= ?
            """,
            (min_games,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.photo_url, t.name AS team, t.logo_url AS team_logo_url, COUNT(*) AS gp,
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
            """,
            (min_games,),
        ).fetchall()
    out = []
    for r in rows:
        gp = r["gp"] or 1
        # Box-score convention: fgm/fga are ALL field goals (2s + 3s combined),
        # tpm/tpa are the 3-point subset of those -- so 2PT makes/attempts is
        # just the remainder, not a separately-tracked stat.
        fg2_m, fg2_a = r["fgm"] - r["tpm"], r["fga"] - r["tpa"]
        out.append({
            "id": r["id"], "name": r["name"], "photo_url": r["photo_url"],
            "team": r["team"], "team_logo_url": r["team_logo_url"], "gp": r["gp"],
            "ppg": round(r["pts"] / gp, 1), "rpg": round(r["reb"] / gp, 1),
            "apg": round(r["ast"] / gp, 1), "spg": round(r["stl"] / gp, 1),
            "bpg": round(r["blk"] / gp, 1), "topg": round(r["tov"] / gp, 1),
            "mpg": round((r["minutes_sec"] or 0) / gp / 60, 1),
            "fg_pct": round(r["fgm"] / r["fga"] * 100, 1) if r["fga"] else None,
            "tp_pct": round(r["tpm"] / r["tpa"] * 100, 1) if r["tpa"] else None,
            "ft_pct": round(r["ftm"] / r["fta"] * 100, 1) if r["fta"] else None,
            "fg2_m": fg2_m, "fg2_a": fg2_a,
            "fg2_pct": round(fg2_m / fg2_a * 100, 1) if fg2_a else None,
            "fg3_m": r["tpm"], "fg3_a": r["tpa"],
            "ft_m": r["ftm"], "ft_a": r["fta"],
        })
    return out


def _team_last_n_game_ids(conn, team_id, n):
    rows = conn.execute(
        """SELECT g.id FROM team_game_stats tgs JOIN games g ON g.id = tgs.game_id
           WHERE tgs.team_id = ? ORDER BY g.game_date DESC, g.id DESC LIMIT ?""",
        (team_id, n),
    ).fetchall()
    return [r["id"] for r in rows]


def _trad_team_rows(conn, game_ids_by_team=None):
    """game_ids_by_team=None -> every game (season). Otherwise a {team_id:
    [game_id, ...]} map restricts each team to just those games (used for
    the scouting report's "last 5 games" comparison) -- a team absent or
    with an empty list is skipped entirely."""
    teams_list = conn.execute("SELECT id, name, logo_url FROM teams").fetchall()
    out = []
    for t in teams_list:
        tid = t["id"]
        if game_ids_by_team is not None:
            gids = game_ids_by_team.get(tid) or []
            if not gids:
                continue
            placeholders = ",".join("?" * len(gids))
            where = f"tgs.team_id = ? AND tgs.game_id IN ({placeholders})"
            params = (tid, *gids)
        else:
            where = "tgs.team_id = ?"
            params = (tid,)
        r = conn.execute(
            f"""
            SELECT COUNT(*) AS gp,
                   SUM(CASE WHEN tgs.pts > tgs.opp_pts THEN 1 ELSE 0 END) AS wins,
                   SUM(tgs.pts) AS pts, SUM(tgs.opp_pts) AS opp_pts,
                   SUM(tgs.reb) AS reb, SUM(tgs.ast) AS ast, SUM(tgs.stl) AS stl,
                   SUM(tgs.blk) AS blk, SUM(tgs.tov) AS tov,
                   SUM(tgs.fgm) AS fgm, SUM(tgs.fga) AS fga,
                   SUM(tgs.tpm) AS tpm, SUM(tgs.tpa) AS tpa,
                   SUM(tgs.ftm) AS ftm, SUM(tgs.fta) AS fta
            FROM team_game_stats tgs WHERE {where}
            """,
            params,
        ).fetchone()
        gp = r["gp"] or 0
        if gp == 0:
            continue
        wins = r["wins"] or 0
        out.append({
            "id": tid, "name": t["name"], "team": t["name"], "team_logo_url": t["logo_url"], "gp": gp,
            "wins": wins, "losses": gp - wins,
            "ppg": round(r["pts"] / gp, 1), "papg": round(r["opp_pts"] / gp, 1),
            "diff": round((r["pts"] - r["opp_pts"]) / gp, 1),
            "win_pct": round(wins / gp, 3),
            "rpg": round(r["reb"] / gp, 1), "apg": round(r["ast"] / gp, 1),
            "spg": round(r["stl"] / gp, 1), "bpg": round(r["blk"] / gp, 1),
            "topg": round(r["tov"] / gp, 1),
            "fg_pct": round(r["fgm"] / r["fga"] * 100, 1) if r["fga"] else None,
            "tp_pct": round(r["tpm"] / r["tpa"] * 100, 1) if r["tpa"] else None,
            "ft_pct": round(r["ftm"] / r["fta"] * 100, 1) if r["fta"] else None,
        })
    return out


# ------------------------------------------------------------------- clock -
_CLOCK_ACTION = {"2pt_pct": "2pt", "3pt_pct": "3pt", "ft_pct": "freethrow"}


def _in_bucket(elapsed, bucket):
    if bucket == "overall":
        return True
    return zones.bucket_for(elapsed) == bucket


def _clock_rows(conn, entity, stat, bucket, game_ids_by_team=None, against=False):
    """entity: 'player' or 'team'. Returns rows with id/name/team/gp/value/m/a.

    game_ids_by_team: same {team_id: [game_id,...]} scoping as
    _trad_team_rows -- None means season-wide. Only meaningful for
    entity='team' (players aren't scoped this way here).

    against: team-only. False = this entity's own events. True = the
    OPPONENT's events in games this team played -- i.e. what's being done
    TO them (mirrors the offense/against pattern used throughout the app,
    e.g. opponent offensive rebounds conceded)."""
    id_col = "player_id" if entity == "player" else "team_id"

    if entity == "player":
        gp_rows = conn.execute(
            """SELECT p.id, p.name, p.photo_url, t.name AS team, t.logo_url AS team_logo_url, COUNT(*) AS gp
               FROM player_game_stats pgs JOIN players p ON p.id=pgs.player_id
               JOIN teams t ON t.id=pgs.team_id GROUP BY p.id"""
        ).fetchall()
    else:
        gp_rows = conn.execute(
            """SELECT t.id, t.name, t.name AS team, t.logo_url AS team_logo_url, COUNT(*) AS gp
               FROM team_game_stats tgs JOIN teams t ON t.id=tgs.team_id GROUP BY t.id"""
        ).fetchall()
    gp_map = {r["id"]: dict(r) for r in gp_rows}
    if game_ids_by_team is not None:
        for eid in gp_map:
            gp_map[eid]["gp"] = len(game_ids_by_team.get(eid) or [])

    if against:
        events = conn.execute(
            """SELECT g.team1_id AS team1_id, g.team2_id AS team2_id, e.team_id AS actor_id,
                      e.action_type, e.made, e.shot_clock_used, e.off_reb_source, e.game_id
               FROM pbp_events e JOIN games g ON g.id = e.game_id"""
        ).fetchall()
    else:
        events = conn.execute(
            f"SELECT {id_col} AS eid, action_type, made, shot_clock_used, off_reb_source, game_id FROM pbp_events "
            f"WHERE {id_col} IS NOT NULL"
        ).fetchall()

    agg = {}  # eid -> {m, a} for pct stats, or {count} for rate stats
    for e in events:
        if not _in_bucket(e["shot_clock_used"], bucket):
            continue
        eid = (e["team2_id"] if e["actor_id"] == e["team1_id"] else e["team1_id"]) if against else e["eid"]
        if game_ids_by_team is not None:
            allowed = game_ids_by_team.get(eid)
            if not allowed or e["game_id"] not in allowed:
                continue
        agg.setdefault(eid, {"m": 0, "a": 0, "count": 0})
        at = e["action_type"]

        if stat in _CLOCK_ACTION:
            if at != _CLOCK_ACTION[stat]:
                continue
            agg[eid]["a"] += 1
            agg[eid]["m"] += e["made"] or 0
        elif stat == "oreb_2pt":
            if at == "rebound_off" and e["off_reb_source"] == "2pt":
                agg[eid]["count"] += 1
        elif stat == "oreb_3pt":
            if at == "rebound_off" and e["off_reb_source"] == "3pt":
                agg[eid]["count"] += 1
        elif stat == "fouls":
            if at == "foul":
                agg[eid]["count"] += 1
        elif stat == "fouled":
            if at == "foulon":
                agg[eid]["count"] += 1
        elif stat == "tov":
            if at == "turnover":
                agg[eid]["count"] += 1

    is_pct = stat in _CLOCK_ACTION
    out = []
    for eid, info in gp_map.items():
        gp = info["gp"] or 0
        if gp == 0:
            continue
        stats = agg.get(eid, {"m": 0, "a": 0, "count": 0})
        photo_or_logo = {"photo_url": info.get("photo_url")} if entity == "player" else {}
        if is_pct:
            if stats["a"] < MIN_ATTEMPTS_FOR_PCT:
                continue
            value = round(stats["m"] / stats["a"] * 100, 1)
            out.append({"id": eid, "name": info["name"], "team": info["team"],
                        "team_logo_url": info.get("team_logo_url"), "gp": gp,
                        "value": value, "m": stats["m"], "a": stats["a"], **photo_or_logo})
        else:
            value = round(stats["count"] / gp, 2)
            out.append({"id": eid, "name": info["name"], "team": info["team"],
                        "team_logo_url": info.get("team_logo_url"), "gp": gp,
                        "value": value, "m": None, "a": stats["count"], **photo_or_logo})
    return out


# ------------------------------------------------------------------- public -
def player_rankings(metric_key, min_games=5, scope="season"):
    conn = db.get_conn()
    try:
        kind, *rest = metric_key.split(":")
        if kind == "trad":
            stat = rest[0]
            direction = next(d for k, l, d in TRAD_PLAYER_METRICS if k == stat)
            rows = _trad_player_rows(conn, min_games, scope)
            return _rank(rows, stat, direction), direction
        elif kind == "clock":
            stat, bucket = rest
            direction = next(d for k, l, kd, d in CLOCK_METRICS if k == stat)
            rows = _clock_rows(conn, "player", stat, bucket)
            rows = [r for r in rows if r["gp"] >= min_games]
            for r in rows:
                r["value_display"] = r["value"]
            ranked = sorted(rows, key=lambda r: r["value"], reverse=(direction == "desc"))
            for i, r in enumerate(ranked, 1):
                r["rank"] = i
            return ranked, direction
        raise ValueError(f"Unknown metric kind: {kind}")
    finally:
        conn.close()


def team_rankings(metric_key):
    conn = db.get_conn()
    try:
        kind, *rest = metric_key.split(":")
        if kind == "trad":
            stat = rest[0]
            valid_keys = {k for k, l, d in TRAD_TEAM_METRICS}
            if stat not in valid_keys:
                stat = "ppg"
            direction = next(d for k, l, d in TRAD_TEAM_METRICS if k == stat)
            rows = _trad_team_rows(conn)
            return _rank(rows, stat, direction), direction
        elif kind == "clock":
            stat, bucket = rest
            direction = next(d for k, l, kd, d in CLOCK_METRICS if k == stat)
            rows = _clock_rows(conn, "team", stat, bucket)
            ranked = sorted(rows, key=lambda r: r["value"], reverse=(direction == "desc"))
            for i, r in enumerate(ranked, 1):
                r["rank"] = i
            return ranked, direction
        raise ValueError(f"Unknown metric kind: {kind}")
    finally:
        conn.close()


# ------------------------------------------------------------ weaknesses --
# Scouting-report candidate pools. Every candidate carries BOTH a season
# rank/value and a last-5-games rank/value (computed the exact same way,
# just scoped to each team's own 5 most recent games) so a weakness reads
# as genuine comparative evidence, not a single snapshot number.

_TRAD_WEAKNESS_PHRASE = {
    "ppg": "struggle to put points on the board",
    "papg": "leak points defensively",
    "diff": "get outscored on average",
    "win_pct": "struggle to close out games",
    "rpg": "get out-rebounded on the glass",
    "apg": "struggle to generate assisted, easy offense",
    "spg": "generate very few extra possessions off steals",
    "bpg": "don't protect the rim",
    "topg": "turn the ball over too often",
    "fg_pct": "shoot inefficiently from the field",
    "tp_pct": "struggle from three-point range",
    "ft_pct": "are unreliable at the free-throw line",
}
_TRAD_UNIT = {
    "ppg": "ppg", "papg": "ppg", "diff": "pts/gm", "win_pct": "%", "rpg": "rpg", "apg": "apg",
    "spg": "spg", "bpg": "bpg", "topg": "topg", "fg_pct": "%", "tp_pct": "%", "ft_pct": "%",
}
_CLOCK_SHOOTING_LABEL = {"2pt_pct": "2PT shooting", "3pt_pct": "3PT shooting", "ft_pct": "FT shooting"}
_CLOCK_SHOOTING_VERB = {
    "2pt_pct": "shoot poorly on 2-point attempts",
    "3pt_pct": "shoot poorly from three-point range",
    "ft_pct": "struggle at the free-throw line",
}
_CLOCK_BUCKET_LABEL = {"0-8": "early shot clock (0-8s)", "8-18": "mid shot clock (8-18s)", "18+": "late shot clock (18+s)"}
# (stat, against, direction, category label, weakness phrase)
_REBOUND_META = [
    ("oreb_2pt", False, "desc", "Offensive rebounding off 2PT misses",
     "rarely crash the boards on their own missed 2-point shots"),
    ("oreb_3pt", False, "desc", "Offensive rebounding off 3PT misses",
     "rarely crash the boards on their own missed 3-point shots"),
    ("oreb_2pt", True, "asc", "Defensive rebounding after opponent 2PT misses",
     "give up too many second-chance points after opponents miss 2-pointers"),
    ("oreb_3pt", True, "asc", "Defensive rebounding after opponent 3PT misses",
     "give up too many second-chance points after opponents miss 3-pointers"),
]


def _display_value(key, raw):
    if raw is None:
        return None
    return round(raw * 100, 1) if key == "win_pct" else raw


def _fmt_value(value, unit):
    return f"{value}%" if unit == "%" else f"{value} {unit}"


def _weakness_text(team_name, c):
    if c["last5_rank"] > c["season_rank"]:
        trend = "and it's gotten even worse over their last 5 games"
    elif c["last5_rank"] < c["season_rank"]:
        trend = "though there are recent signs of improvement"
    else:
        trend = "a consistent issue all season"
    return (
        f"{team_name} {c['phrase']}, ranking #{c['season_rank']} of {c['season_pool']} in the league this season "
        f"({_fmt_value(c['season_value'], c['unit'])}) and #{c['last5_rank']} of {c['last5_pool']} over their last "
        f"5 games ({_fmt_value(c['last5_value'], c['unit'])}) -- {trend}."
    )


def _compare_chart(c):
    return {
        "type": "compare",
        "season_value": c["season_value"], "last5_value": c["last5_value"],
        "season_rank": c["season_rank"], "last5_rank": c["last5_rank"], "pool": c["season_pool"],
        "unit": c["unit"],
    }


def _build_trad_candidates(season_rows, last5_rows, team_id):
    out = []
    for key, label, direction in TRAD_TEAM_METRICS:
        season_ranked = _rank(season_rows, key, direction)
        last5_ranked = _rank(last5_rows, key, direction)
        s = next((r for r in season_ranked if r["id"] == team_id), None)
        l = next((r for r in last5_ranked if r["id"] == team_id), None)
        if not s or not l:
            continue
        c = {
            "group": "traditional", "key": f"trad:{key}", "category": label,
            "phrase": _TRAD_WEAKNESS_PHRASE[key], "unit": _TRAD_UNIT[key],
            "season_rank": s["rank"], "season_pool": len(season_ranked), "season_value": _display_value(key, s[key]),
            "last5_rank": l["rank"], "last5_pool": len(last5_ranked), "last5_value": _display_value(key, l[key]),
        }
        c["chart"] = _compare_chart(c)
        out.append(c)
    return out


def _build_clock_shooting_candidates(conn, team_id, game_ids_last5):
    out = []
    for stat in ("2pt_pct", "3pt_pct", "ft_pct"):
        for bucket in ("0-8", "8-18", "18+"):
            season_ranked = _rank(_clock_rows(conn, "team", stat, bucket), "value", "desc")
            last5_ranked = _rank(_clock_rows(conn, "team", stat, bucket, game_ids_by_team=game_ids_last5), "value", "desc")
            s = next((r for r in season_ranked if r["id"] == team_id), None)
            l = next((r for r in last5_ranked if r["id"] == team_id), None)
            if not s or not l:
                continue
            c = {
                "group": "shot_clock", "key": f"clock:{stat}:{bucket}",
                "category": f"{_CLOCK_SHOOTING_LABEL[stat]} -- {_CLOCK_BUCKET_LABEL[bucket]}",
                "phrase": f"{_CLOCK_SHOOTING_VERB[stat]} during the {_CLOCK_BUCKET_LABEL[bucket]}",
                "unit": "%",
                "season_rank": s["rank"], "season_pool": len(season_ranked), "season_value": s["value"],
                "last5_rank": l["rank"], "last5_pool": len(last5_ranked), "last5_value": l["value"],
            }
            c["chart"] = _compare_chart(c)
            out.append(c)
    return out


def _build_rebound_candidates(conn, team_id, game_ids_last5):
    out = []
    for stat, against, direction, category, phrase in _REBOUND_META:
        season_ranked = _rank(_clock_rows(conn, "team", stat, "overall", against=against), "value", direction)
        last5_ranked = _rank(
            _clock_rows(conn, "team", stat, "overall", game_ids_by_team=game_ids_last5, against=against),
            "value", direction,
        )
        s = next((r for r in season_ranked if r["id"] == team_id), None)
        l = next((r for r in last5_ranked if r["id"] == team_id), None)
        if not s or not l:
            continue
        c = {
            "group": "rebounding", "key": f"reb:{stat}:{against}", "category": category, "phrase": phrase,
            "unit": "pg",
            "season_rank": s["rank"], "season_pool": len(season_ranked), "season_value": s["value"],
            "last5_rank": l["rank"], "last5_pool": len(last5_ranked), "last5_value": l["value"],
        }
        c["chart"] = _compare_chart(c)
        out.append(c)
    return out


def team_weaknesses(team_id, top_n=4):
    """Scouting-report candidates: this team's rank (season AND last-5-
    games, for direct comparison) across traditional team stats, 2PT/3PT/FT
    shooting split by shot-clock region, and offensive/defensive rebounding
    split by shot type (2PT miss vs 3PT miss). Guarantees at least one pick
    from each of those 3 groups when the data allows, then fills any
    remaining slots with the next-worst candidates overall -- so the
    weaknesses always cover the full breadth asked for, not just whatever
    happens to rank worst."""
    conn = db.get_conn()
    team_ids = [r["id"] for r in conn.execute("SELECT id FROM teams").fetchall()]
    game_ids_last5 = {tid: _team_last_n_game_ids(conn, tid, 5) for tid in team_ids}

    season_trad = _trad_team_rows(conn)
    last5_trad = _trad_team_rows(conn, game_ids_last5)
    if not any(r["id"] == team_id for r in season_trad):
        conn.close()
        return []
    team_name = next(r["name"] for r in season_trad if r["id"] == team_id)

    trad_candidates = _build_trad_candidates(season_trad, last5_trad, team_id)
    clock_candidates = _build_clock_shooting_candidates(conn, team_id, game_ids_last5)
    rebound_candidates = _build_rebound_candidates(conn, team_id, game_ids_last5)
    conn.close()

    def worst(cands):
        return max(cands, key=lambda c: c["season_rank"]) if cands else None

    picks = [c for c in (worst(trad_candidates), worst(clock_candidates), worst(rebound_candidates)) if c]
    picked_keys = {c["key"] for c in picks}
    remaining = [c for c in trad_candidates + clock_candidates + rebound_candidates if c["key"] not in picked_keys]
    remaining.sort(key=lambda c: c["season_rank"], reverse=True)
    picks += remaining[: max(0, top_n - len(picks))]
    picks.sort(key=lambda c: c["season_rank"], reverse=True)
    picks = picks[:top_n]

    for c in picks:
        c["text"] = _weakness_text(team_name, c)
    return picks


# ------------------------------------------------------------ matchup scout
def _last3_game_ids_by_team(conn):
    """{team_id: [last 3 game ids]} for every team -- the ranking-pool
    scope used everywhere on the Matchup Scout tab's "Last 3 Games" card,
    so a team's recent numbers are ranked against everyone else's equally
    recent numbers, not their season-long ones."""
    team_ids = [r["id"] for r in conn.execute("SELECT id FROM teams").fetchall()]
    return {tid: _team_last_n_game_ids(conn, tid, 3) for tid in team_ids}


def team_last3_results(team_id):
    """Record over the last 3 games, plus each game's opponent, score,
    and result -- the header for the Matchup Scout tab's "Last 3 Games"
    card."""
    conn = db.get_conn()
    try:
        team_row = conn.execute("SELECT id, name, logo_url FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            return None
        rows = conn.execute(
            """SELECT g.id, g.game_date, g.team1_id, g.team2_id, g.team1_score, g.team2_score,
                      t1.name AS team1_name, t1.logo_url AS team1_logo_url,
                      t2.name AS team2_name, t2.logo_url AS team2_logo_url
               FROM games g
               JOIN teams t1 ON t1.id = g.team1_id
               JOIN teams t2 ON t2.id = g.team2_id
               WHERE g.team1_id = ? OR g.team2_id = ?
               ORDER BY g.game_date DESC, g.id DESC LIMIT 3""",
            (team_id, team_id),
        ).fetchall()

        games = []
        wins = 0
        for r in rows:
            is_team1 = r["team1_id"] == team_id
            team_score = r["team1_score"] if is_team1 else r["team2_score"]
            opp_score = r["team2_score"] if is_team1 else r["team1_score"]
            won = team_score > opp_score
            wins += won
            games.append({
                "game_id": r["id"], "game_date": r["game_date"],
                "opponent": {
                    "name": r["team2_name"] if is_team1 else r["team1_name"],
                    "logo_url": r["team2_logo_url"] if is_team1 else r["team1_logo_url"],
                },
                "team_score": team_score, "opponent_score": opp_score, "won": won,
            })

        return {
            "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["logo_url"]},
            "record": f"{wins}-{len(games) - wins}",
            "games": games,
        }
    finally:
        conn.close()


def _oreb_efficiency_ranked(conn, game_ids_by_team=None):
    """Offensive rebound efficiency: total offensive rebounds off a
    missed 2PT or 3PT, divided by the team's own total missed 2PT+3PT
    shots, as a % -- how much of their own misses they recover. Ranked
    desc (higher = better). Both counts are season (or last-3, if
    scoped) totals, not per-game rates -- the ratio is what matters."""
    events = conn.execute(
        """SELECT team_id AS eid, game_id, action_type, made, off_reb_source
           FROM pbp_events
           WHERE team_id IS NOT NULL AND action_type IN ('2pt', '3pt', 'rebound_off')"""
    ).fetchall()
    misses, orebs = {}, {}
    for e in events:
        if game_ids_by_team is not None:
            allowed = game_ids_by_team.get(e["eid"])
            if not allowed or e["game_id"] not in allowed:
                continue
        if e["action_type"] in ("2pt", "3pt") and not e["made"]:
            misses[e["eid"]] = misses.get(e["eid"], 0) + 1
        elif e["action_type"] == "rebound_off" and e["off_reb_source"] in ("2pt", "3pt"):
            orebs[e["eid"]] = orebs.get(e["eid"], 0) + 1

    team_ids = [r["id"] for r in conn.execute("SELECT id FROM teams").fetchall()]
    out = [
        {"id": tid, "value": round(orebs.get(tid, 0) / misses[tid] * 100, 1)}
        for tid in team_ids if misses.get(tid)
    ]
    return _rank(out, "value", "desc")


# (key, label, source, direction) -- source: "trad" (TRAD_TEAM_METRICS-style
# per-game average), "clock" (season-wide clock:*:overall stat), or
# "oreb_eff" (offensive rebound efficiency, see _oreb_efficiency_ranked).
# Defensive rebounds aren't tracked here at all -- not useful for this tab.
_TOP_ROW_BIG = [
    ("ppg", "PPG", "trad", "desc"),
    ("papg", "PAPG", "trad", "asc"),
    ("2pt_pct", "2PT%", "clock", "desc"),
    ("3pt_pct", "3PT%", "clock", "desc"),
    ("oreb_2pt", "OREB (2PT)", "clock", "desc"),
    ("oreb_3pt", "OREB (3PT)", "clock", "desc"),
    ("oreb_eff", "OREB%", "oreb_eff", "desc"),
]
_TOP_ROW_SMALL = [
    ("apg", "AST", "trad", "desc"),
    ("spg", "STL", "trad", "desc"),
    ("bpg", "BLK", "trad", "desc"),
    ("topg", "TOV", "trad", "asc"),
    ("ft_pct", "FT%", "trad", "desc"),
]


def team_top_row(team_id, scope="season"):
    """Backs the Matchup Scout tab's top-line stat strip: team logo +
    record, then a row of headline stats (bigger, blue/red-shaded by
    top-3/bottom-3 league rank) followed by a row of secondary stats
    (smaller, unshaded) -- rank shown under every number.

    scope: "season" (default) or "last3" -- last3 restricts every team
    to their own last 3 games for both the value shown AND the ranking
    pool, so "recent form" is compared like-for-like across the league."""
    conn = db.get_conn()
    try:
        game_ids_by_team = _last3_game_ids_by_team(conn) if scope == "last3" else None
        season_trad = _trad_team_rows(conn, game_ids_by_team)
        team_row = next((r for r in season_trad if r["id"] == team_id), None)
        if not team_row:
            return None
        oreb_eff_ranked = _oreb_efficiency_ranked(conn, game_ids_by_team)

        def build(key, label, source, direction):
            if source == "trad":
                ranked = _rank(season_trad, key, direction)
                r = next((x for x in ranked if x["id"] == team_id), None)
                val = r[key] if r else None
            elif source == "clock":
                ranked = _rank(_clock_rows(conn, "team", key, "overall", game_ids_by_team), "value", direction)
                r = next((x for x in ranked if x["id"] == team_id), None)
                val = r["value"] if r else None
            else:
                ranked = oreb_eff_ranked
                r = next((x for x in ranked if x["id"] == team_id), None)
                val = r["value"] if r else None
            if r is None:
                return None
            display = f"{val}%" if label.endswith("%") else val
            return {"label": label, "value": display, "rank": r["rank"], "pool": len(ranked)}

        big = [x for x in (build(*spec) for spec in _TOP_ROW_BIG) if x]
        small = [x for x in (build(*spec) for spec in _TOP_ROW_SMALL) if x]

        return {
            "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["team_logo_url"]},
            "record": f"{team_row['wins']}-{team_row['losses']}",
            "gp": team_row["gp"],
            "big": big,
            "small": small,
        }
    finally:
        conn.close()


_SHOT_CLOCK_BUCKETS = [("0-8", "Early Offence"), ("8-18", "Half Court"), ("18+", "Late Clock")]


def _pts_by_bucket_ranked(conn, bucket, against=False, game_ids_by_team=None):
    """Points scored (or, if against=True, points ALLOWED -- what the
    OPPONENT scored) per game within one shot-clock bucket, ranked --
    pts isn't one of CLOCK_METRICS' single-action stats, so this sums
    2pt/3pt/freethrow makes into actual points the same way the
    5-minute-splits endpoint does for its segment scoring. against=True
    ranks ascending (fewer points allowed = rank 1), same convention as
    every other "allowed" stat in the app. game_ids_by_team scopes both
    the value and each team's game count (for the per-game average) to
    just those games -- None means season-wide."""
    if against:
        events = conn.execute(
            """SELECT g.id AS game_id, g.team1_id AS team1_id, g.team2_id AS team2_id, e.team_id AS actor_id,
                      e.action_type, e.made, e.shot_clock_used
               FROM pbp_events e JOIN games g ON g.id = e.game_id"""
        ).fetchall()
    else:
        events = conn.execute(
            "SELECT game_id, team_id AS eid, action_type, made, shot_clock_used FROM pbp_events WHERE team_id IS NOT NULL"
        ).fetchall()
    gp_rows = conn.execute("SELECT team_id AS id, COUNT(*) AS gp FROM team_game_stats GROUP BY team_id").fetchall()
    gp_map = {r["id"]: r["gp"] for r in gp_rows}
    if game_ids_by_team is not None:
        for tid in gp_map:
            gp_map[tid] = len(game_ids_by_team.get(tid) or [])

    pts_value = {"2pt": 2, "3pt": 3, "freethrow": 1}
    totals = {}
    for e in events:
        if e["action_type"] not in pts_value or not e["made"]:
            continue
        if not _in_bucket(e["shot_clock_used"], bucket):
            continue
        eid = (e["team2_id"] if e["actor_id"] == e["team1_id"] else e["team1_id"]) if against else e["eid"]
        if game_ids_by_team is not None:
            allowed = game_ids_by_team.get(eid)
            if not allowed or e["game_id"] not in allowed:
                continue
        totals[eid] = totals.get(eid, 0) + pts_value[e["action_type"]]

    out = [{"id": tid, "value": round(totals.get(tid, 0) / gp, 1)} for tid, gp in gp_map.items() if gp]
    return _rank(out, "value", "asc" if against else "desc")


def team_shot_clock_offense(team_id, scope="season"):
    """Offense broken down by shot-clock window (0-8s/8-18s/18+s): points
    per game (plus what share of the team's total scoring that window
    represents), 2PT%, and 3PT% -- each with league rank. Sits just under
    the top-row stat strip on the Matchup Scout tab. scope: "season" or
    "last3" (see team_top_row for what that changes)."""
    conn = db.get_conn()
    try:
        game_ids_by_team = _last3_game_ids_by_team(conn) if scope == "last3" else None
        season_trad = _trad_team_rows(conn, game_ids_by_team)
        team_row = next((r for r in season_trad if r["id"] == team_id), None)
        if not team_row:
            return None
        total_ppg = team_row["ppg"]

        def cell(ranked, r):
            if not r:
                return None
            out = {"value": r["value"], "rank": r["rank"], "pool": len(ranked)}
            if "m" in r.keys() and "a" in r.keys():
                out["makes"], out["attempts"] = r["m"], r["a"]
            return out

        rows = []
        for bucket, label in _SHOT_CLOCK_BUCKETS:
            pts_ranked = _pts_by_bucket_ranked(conn, bucket, game_ids_by_team=game_ids_by_team)
            pts_r = next((x for x in pts_ranked if x["id"] == team_id), None)
            fg2_ranked = _rank(_clock_rows(conn, "team", "2pt_pct", bucket, game_ids_by_team), "value", "desc")
            fg2_r = next((x for x in fg2_ranked if x["id"] == team_id), None)
            fg3_ranked = _rank(_clock_rows(conn, "team", "3pt_pct", bucket, game_ids_by_team), "value", "desc")
            fg3_r = next((x for x in fg3_ranked if x["id"] == team_id), None)

            rows.append({
                "bucket": bucket, "label": label,
                "pts": cell(pts_ranked, pts_r),
                "pct_of_total_pts": round(pts_r["value"] / total_ppg * 100, 1) if pts_r and total_ppg else None,
                "fg2_pct": cell(fg2_ranked, fg2_r),
                "fg3_pct": cell(fg3_ranked, fg3_r),
            })

        return {
            "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["team_logo_url"]},
            "rows": rows,
        }
    finally:
        conn.close()


def team_shot_clock_defense(team_id, scope="season"):
    """Mirrors team_shot_clock_offense for the against side: points
    ALLOWED per game (plus what share of total points allowed that window
    represents), opponent 2PT%/3PT% allowed -- each with league rank
    (ascending, so rank 1 = best defense in that window, same convention
    as every other "allowed" stat in the app)."""
    conn = db.get_conn()
    try:
        game_ids_by_team = _last3_game_ids_by_team(conn) if scope == "last3" else None
        season_trad = _trad_team_rows(conn, game_ids_by_team)
        team_row = next((r for r in season_trad if r["id"] == team_id), None)
        if not team_row:
            return None
        total_papg = team_row["papg"]

        def cell(ranked, r):
            if not r:
                return None
            out = {"value": r["value"], "rank": r["rank"], "pool": len(ranked)}
            if "m" in r.keys() and "a" in r.keys():
                out["makes"], out["attempts"] = r["m"], r["a"]
            return out

        rows = []
        for bucket, label in _SHOT_CLOCK_BUCKETS:
            pts_ranked = _pts_by_bucket_ranked(conn, bucket, against=True, game_ids_by_team=game_ids_by_team)
            pts_r = next((x for x in pts_ranked if x["id"] == team_id), None)
            fg2_ranked = _rank(_clock_rows(conn, "team", "2pt_pct", bucket, game_ids_by_team, against=True), "value", "asc")
            fg2_r = next((x for x in fg2_ranked if x["id"] == team_id), None)
            fg3_ranked = _rank(_clock_rows(conn, "team", "3pt_pct", bucket, game_ids_by_team, against=True), "value", "asc")
            fg3_r = next((x for x in fg3_ranked if x["id"] == team_id), None)

            rows.append({
                "bucket": bucket, "label": label,
                "pts": cell(pts_ranked, pts_r),
                "pct_of_total_pts": round(pts_r["value"] / total_papg * 100, 1) if pts_r and total_papg else None,
                "fg2_pct": cell(fg2_ranked, fg2_r),
                "fg3_pct": cell(fg3_ranked, fg3_r),
            })

        return {
            "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["team_logo_url"]},
            "rows": rows,
        }
    finally:
        conn.close()


_OREB_OUTCOME_TYPES = {"2pt", "3pt", "turnover", "foulon"}


def _oreb_outcome_breakdown(conn, team_id, source, game_ids=None):
    """What happens on the very next possession-relevant event after this
    team grabs an offensive rebound off a missed `source` (2pt or 3pt)
    shot -- classified as their next 2PT attempt, 3PT attempt, turnover,
    or drawn foul, whichever comes first chronologically (action_number).
    A second consecutive rebound (missed the putback too) is skipped over
    rather than counted as its own outcome, since it isn't one of the 4
    categories asked for -- the chain keeps resolving to whichever of the
    4 eventually follows. game_ids restricts to just those games (e.g.
    the team's last 3) -- None means the whole season."""
    if game_ids is not None and not game_ids:
        return None
    if game_ids is not None:
        placeholders = ",".join("?" * len(game_ids))
        rows = conn.execute(
            f"""SELECT game_id, action_number, action_type, off_reb_source, made
               FROM pbp_events
               WHERE team_id = ? AND action_type IN ('rebound_off', '2pt', '3pt', 'turnover', 'foulon')
               AND game_id IN ({placeholders})
               ORDER BY game_id, action_number""",
            (team_id, *game_ids),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT game_id, action_number, action_type, off_reb_source, made
               FROM pbp_events
               WHERE team_id = ? AND action_type IN ('rebound_off', '2pt', '3pt', 'turnover', 'foulon')
               ORDER BY game_id, action_number""",
            (team_id,),
        ).fetchall()

    by_game = {}
    for e in rows:
        by_game.setdefault(e["game_id"], []).append(e)

    counts = {"2pt": 0, "3pt": 0, "turnover": 0, "foulon": 0}
    makes = {"2pt": 0, "3pt": 0}
    total = 0
    for game_events in by_game.values():
        n = len(game_events)
        for i, e in enumerate(game_events):
            if e["action_type"] != "rebound_off" or e["off_reb_source"] != source:
                continue
            for j in range(i + 1, n):
                nxt = game_events[j]
                if nxt["action_type"] == "rebound_off":
                    continue
                total += 1
                counts[nxt["action_type"]] += 1
                if nxt["action_type"] in ("2pt", "3pt") and nxt["made"]:
                    makes[nxt["action_type"]] += 1
                break

    if not total:
        return None

    def freq(key):
        return round(counts[key] / total * 100, 1)

    def make_pct(key):
        return round(makes[key] / counts[key] * 100, 1) if counts[key] else None

    return {
        "total": total,
        "fg2": {"freq_pct": freq("2pt"), "make_pct": make_pct("2pt"), "makes": makes["2pt"], "attempts": counts["2pt"]},
        "fg3": {"freq_pct": freq("3pt"), "make_pct": make_pct("3pt"), "makes": makes["3pt"], "attempts": counts["3pt"]},
        "turnover": {"freq_pct": freq("turnover"), "count": counts["turnover"]},
        "fouled": {"freq_pct": freq("foulon"), "count": counts["foulon"]},
    }


def team_oreb_outcomes(team_id, scope="season"):
    """Backs the Matchup Scout tab's offensive-rebound rundown: after this
    team grabs an offensive rebound off a missed 2PT (or 3PT), what share
    of the time does the very next play end in a 2PT attempt, a 3PT
    attempt, a turnover, or a drawn foul."""
    conn = db.get_conn()
    try:
        team_row = conn.execute("SELECT id, name, logo_url FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            return None
        game_ids = _team_last_n_game_ids(conn, team_id, 3) if scope == "last3" else None
        return {
            "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["logo_url"]},
            "off_2pt": _oreb_outcome_breakdown(conn, team_id, "2pt", game_ids),
            "off_3pt": _oreb_outcome_breakdown(conn, team_id, "3pt", game_ids),
        }
    finally:
        conn.close()


def _bucket_tile_stats(conn, team_id, bucket, game_ids_by_team=None):
    """Points/2PT%/3PT% for ONE shot-clock window, offense AND defense --
    6 candidate stats, each shaped as {label, value, rank, pool, avg,
    is_pct}, built from the exact same ranked data that backs the
    Offense/Defense by shot clock tables.
    Labels have no bucket suffix -- the window itself (Early Offence/
    Half Court/Late Clock) is the enclosing section, not part of each
    stat's name."""
    out = {}
    pts_off = _pts_by_bucket_ranked(conn, bucket, game_ids_by_team=game_ids_by_team)
    r = next((x for x in pts_off if x["id"] == team_id), None)
    if r:
        values = [x["value"] for x in pts_off]
        out["off_pts"] = {
            "label": "Points", "value": r["value"], "rank": r["rank"], "pool": len(pts_off),
            "avg": round(sum(values) / len(values), 1), "is_pct": False,
        }
    for stat, slabel in (("2pt_pct", "2PT%"), ("3pt_pct", "3PT%")):
        ranked = _rank(_clock_rows(conn, "team", stat, bucket, game_ids_by_team), "value", "desc")
        r = next((x for x in ranked if x["id"] == team_id), None)
        if r:
            values = [x["value"] for x in ranked]
            out[f"off_{stat}"] = {
                "label": slabel, "value": r["value"], "rank": r["rank"], "pool": len(ranked),
                "avg": round(sum(values) / len(values), 1), "is_pct": True,
            }

    pts_def = _pts_by_bucket_ranked(conn, bucket, against=True, game_ids_by_team=game_ids_by_team)
    r = next((x for x in pts_def if x["id"] == team_id), None)
    if r:
        values = [x["value"] for x in pts_def]
        out["def_pts"] = {
            "label": "Points Allowed", "value": r["value"], "rank": r["rank"], "pool": len(pts_def),
            "avg": round(sum(values) / len(values), 1), "is_pct": False,
        }
    for stat, slabel in (("2pt_pct", "Opp 2PT%"), ("3pt_pct", "Opp 3PT%")):
        ranked = _rank(_clock_rows(conn, "team", stat, bucket, game_ids_by_team, against=True), "value", "asc")
        r = next((x for x in ranked if x["id"] == team_id), None)
        if r:
            values = [x["value"] for x in ranked]
            out[f"def_{stat}"] = {
                "label": slabel, "value": r["value"], "rank": r["rank"], "pool": len(ranked),
                "avg": round(sum(values) / len(values), 1), "is_pct": True,
            }
    return out


def _scout_bullets(season_stats, last3_stats, side):
    """side: "strength" (top-3 league rank) or "weakness" (bottom-3).
    Returns (season_list, emerging_list): every qualifying season stat
    paired with its last-3 read, plus any stat that ONLY qualifies over
    the last 3 games. Shared by both sides of team_scout_takeaways so the
    (symmetric) weakness scan doesn't duplicate the strength scan.

    Every entry carries the full trio -- season value/rank, last-3
    value/rank, and the league average -- regardless of which side
    qualified it, condensed-format-ready: the frontend builds a one-line
    "season -> last 3" read (with an up/down arrow off the rank
    comparison) and a 3-bar chart straight from these fields, no prose
    text generated here."""
    def qualifies(rank, pool):
        return rank <= 3 if side == "strength" else rank > pool - 3

    season_list, emerging_list = [], []
    for key, s in season_stats.items():
        l3 = last3_stats.get(key) if last3_stats else None
        entry = {
            "label": s["label"], "is_pct": s["is_pct"],
            "season_value": s["value"], "season_rank": s["rank"], "pool": s["pool"],
            "league_avg": s["avg"],
            "last3_value": l3["value"] if l3 else None,
            "last3_rank": l3["rank"] if l3 else None,
        }
        if qualifies(s["rank"], s["pool"]):
            season_list.append({**entry, "emerging": False})
        if l3 and qualifies(l3["rank"], l3["pool"]) and not qualifies(s["rank"], s["pool"]):
            emerging_list.append({**entry, "emerging": True})

    reverse = side == "weakness"
    season_list.sort(key=lambda e: e["season_rank"], reverse=reverse)
    emerging_list.sort(key=lambda e: e["last3_rank"] if e["last3_rank"] is not None else 999, reverse=reverse)
    return season_list, emerging_list


def team_scout_takeaways(team_id):
    """Strengths/weaknesses assessed per shot-clock window (Early
    Offence/Half Court/Late Clock) rather than one flat list -- each
    window's 6 candidate stats (points/2PT%/3PT% on both offense and
    defense) are scanned for top-3 league rank (a "strength") or bottom-3
    ("weakness"), every bullet noting the last-3 read too so a scout can
    read straight down "what's true early in the clock" vs "late"."""
    conn = db.get_conn()
    try:
        team_row = conn.execute("SELECT id, name, logo_url FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            return None
        last3_ids_by_team = _last3_game_ids_by_team(conn)

        slots = []
        for bucket, label in _SHOT_CLOCK_BUCKETS:
            season_stats = _bucket_tile_stats(conn, team_id, bucket)
            if not season_stats:
                continue
            last3_stats = _bucket_tile_stats(conn, team_id, bucket, last3_ids_by_team)
            s_season, s_emerging = _scout_bullets(season_stats, last3_stats, "strength")
            w_season, w_emerging = _scout_bullets(season_stats, last3_stats, "weakness")
            slots.append({
                "bucket": bucket, "label": label,
                "strengths": s_season + s_emerging,
                "weaknesses": w_season + w_emerging,
            })

        return {
            "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["logo_url"]},
            "slots": slots,
        }
    finally:
        conn.close()


def matchup_scout_page(team_id):
    """Bundles every Matchup Scout tab section into one call. This used to
    be 10 separate frontend fetches; profiling found that firing them
    concurrently serialized badly under GIL contention (10 parallel
    requests took ~36s wall time vs ~3s running the same work one at a
    time sequentially -- confirmed raw SQLite concurrency itself was fine
    in isolation, so the cost was many CPU-bound Python passes over the
    same event data competing for the GIL at once, not the database).
    One sequential request removes that contention entirely and ends up
    faster for the user despite doing the same total work."""
    top_row = team_top_row(team_id)
    if not top_row:
        return None
    return {
        "top_row": top_row,
        "top_row_last3": team_top_row(team_id, "last3"),
        "shot_clock_offense": team_shot_clock_offense(team_id),
        "shot_clock_offense_last3": team_shot_clock_offense(team_id, "last3"),
        "shot_clock_defense": team_shot_clock_defense(team_id),
        "shot_clock_defense_last3": team_shot_clock_defense(team_id, "last3"),
        "oreb_outcomes": team_oreb_outcomes(team_id),
        "oreb_outcomes_last3": team_oreb_outcomes(team_id, "last3"),
        "last3_results": team_last3_results(team_id),
        "takeaways": team_scout_takeaways(team_id),
    }


# ------------------------------------------------------ matchup scout (v1) -
# Superseded by team_season_table() above -- the Matchup Scout tab was
# rebuilt into a plain season-stats column table. Left in place (currently
# unused by the frontend) rather than deleted, in case any of this --
# the attack/caution/pressure "keys", the plain-language summaries, the
# rebounding-by-shot-type profile -- gets reintroduced later.
#
# Curated subset of TRAD_TEAM_METRICS for the plain-language basic-stats
# summary -- basics only, the finer shot-clock/5-minute cross-comparisons
# have their own dedicated sections elsewhere on the tab.
_BASIC_SUMMARY_KEYS = ("ppg", "papg", "diff", "rpg", "apg", "topg", "fg_pct", "tp_pct")
_BASIC_METRIC_INFO = {k: (label, direction) for k, label, direction in TRAD_TEAM_METRICS if k in _BASIC_SUMMARY_KEYS}


def _basic_stats_summary(conn, team_id, opponent_id, season_trad, team_row, opp_row):
    """Plain-language read on team_id's season basics (record, scoring,
    rebounding, ballhandling, shooting) plus their last-3-games form, each
    stat compared directly against opponent_id's own number in the same
    category -- not the offense-vs-defense cross-matching the "keys"
    section already does, just "who's better at this, and by how much."""
    last3_ids = _team_last_n_game_ids(conn, team_id, 3)
    last3_rows = _trad_team_rows(conn, {team_id: last3_ids}) if last3_ids else []
    last3_row = next((r for r in last3_rows if r["id"] == team_id), None)

    ranks = {}
    for key, (label, direction) in _BASIC_METRIC_INFO.items():
        ranked = _rank(season_trad, key, direction)
        tr = next((r for r in ranked if r["id"] == team_id), None)
        orow = next((r for r in ranked if r["id"] == opponent_id), None)
        if not tr or not orow:
            continue
        ranks[key] = {
            "label": label, "pool": len(ranked),
            "team_rank": tr["rank"], "team_value": tr[key],
            "opp_rank": orow["rank"], "opp_value": orow[key],
        }

    seed = team_id * 31 + opponent_id * 17
    paragraphs = []

    diff = team_row["diff"]
    diff_word = "positive margin" if diff > 0 else ("deficit" if diff < 0 else "even margin")
    paragraphs.append(_pick([
        f"{team_row['name']} sit at {team_row['wins']}-{team_row['losses']} this season, averaging "
        f"{team_row['ppg']} points a night while allowing {team_row['papg']} -- a {diff_word} of {abs(diff)}.",
        f"Season-long, {team_row['name']} are {team_row['wins']}-{team_row['losses']}, scoring "
        f"{team_row['ppg']} per game and giving up {team_row['papg']}, for a {diff_word} of {abs(diff)}.",
        f"{possessive(team_row['name'])} record stands at {team_row['wins']}-{team_row['losses']}: {team_row['ppg']} "
        f"points for, {team_row['papg']} against, a {diff_word} of {abs(diff)} a night.",
    ], seed))

    if last3_row:
        deltas = []
        for key, thresh, unit in (("ppg", 2.5, "Scoring"), ("fg_pct", 3, "2PT/overall FG%"),
                                   ("tp_pct", 3, "3P%"), ("topg", 1.2, "Turnovers")):
            season_v, last3_v = team_row.get(key), last3_row.get(key)
            if season_v is None or last3_v is None:
                continue
            d = round(last3_v - season_v, 1)
            if abs(d) >= thresh:
                deltas.append((key, d, season_v, last3_v, unit))
        if deltas:
            deltas.sort(key=lambda d: -abs(d[1]))
            parts = []
            for key, d, season_v, last3_v, unit in deltas[:2]:
                word = "up" if d > 0 else "down"
                if key in ("fg_pct", "tp_pct"):
                    parts.append(f"{unit} is {word} to {last3_v}% (season: {season_v}%)")
                else:
                    parts.append(f"{unit.lower()} {word} to {last3_v} a game (season: {season_v})")
            trend_text = " and ".join(parts)
            paragraphs.append(_pick([
                f"Over their last 3 games that's shifted a bit -- {trend_text}.",
                f"Recent form looks a little different: {trend_text}.",
                f"The last 3 games tell a slightly different story -- {trend_text}.",
            ], seed + 7))
        else:
            paragraphs.append(_pick([
                "Their last 3 games look consistent with the season line -- no real form swing to account for.",
                "Form has held steady -- the last 3 games track closely with their season averages.",
            ], seed + 7))

    def fmt_val(key, v):
        return f"{v}%" if key in ("fg_pct", "tp_pct") else v

    if ranks:
        best_key = min(ranks, key=lambda k: ranks[k]["team_rank"])
        worst_key = max(ranks, key=lambda k: ranks[k]["team_rank"])
        b, w = ranks[best_key], ranks[worst_key]

        if b["opp_rank"] <= 3:
            strength_variants = [
                f"Their clearest strength is {b['label'].lower()} -- #{b['team_rank']} of {b['pool']} in the "
                f"league ({fmt_val(best_key, b['team_value'])}) -- but it won't be an easy edge tonight: "
                f"{opp_row['name']} are strong there too (#{b['opp_rank']}).",
                f"{team_row['name']} lean on {b['label'].lower()} as their top strength (#{b['team_rank']} of "
                f"{b['pool']}), though {possessive(opp_row['name'])} own #{b['opp_rank']} ranking there takes some shine off it.",
            ]
        else:
            strength_variants = [
                f"Their clearest strength is {b['label'].lower()} -- #{b['team_rank']} of {b['pool']} in the "
                f"league ({fmt_val(best_key, b['team_value'])}) -- and {opp_row['name']} are only #{b['opp_rank']} "
                f"there, a real mismatch to lean on.",
                f"{possessive(team_row['name'])} best category is {b['label'].lower()} (#{b['team_rank']} of {b['pool']}); "
                f"{opp_row['name']} rank just #{b['opp_rank']} in the same stat, which should hold up as an advantage.",
            ]
        paragraphs.append(_pick(strength_variants, seed + 13))

        if w["opp_rank"] <= 3:
            weakness_variants = [
                f"On the other end, {w['label'].lower()} is a soft spot -- #{w['team_rank']} of {w['pool']} "
                f"({fmt_val(worst_key, w['team_value'])}) -- and {opp_row['name']} happen to rank #{w['opp_rank']} "
                f"there, so it lines up as a real point of attack.",
                f"Their biggest vulnerability is {w['label'].lower()} (#{w['team_rank']} of {w['pool']}), and "
                f"{opp_row['name']} are #{w['opp_rank']} in that same category -- not a coincidence worth ignoring.",
            ]
        else:
            weakness_variants = [
                f"Their softest category is {w['label'].lower()} -- #{w['team_rank']} of {w['pool']} "
                f"({fmt_val(worst_key, w['team_value'])}) -- though {opp_row['name']} aren't especially strong "
                f"there either (#{w['opp_rank']}), so it may not decide the game on its own.",
                f"{possessive(team_row['name'])} weakest number is {w['label'].lower()} (#{w['team_rank']} of {w['pool']}); "
                f"{opp_row['name']} sit at a modest #{w['opp_rank']} there too, so this alone isn't a guaranteed swing factor.",
            ]
        paragraphs.append(_pick(weakness_variants, seed + 19))

    return {"paragraphs": paragraphs}


def _rebounding_profile(conn, team_id):
    """This team's league rank/value at generating (and conceding) offensive
    rebounds, split by shot type -- the building block for the Matchup
    Scout's dedicated Offensive Rebounding section."""
    profile = {}
    for stat, against, direction, field in [
        ("oreb_2pt", False, "desc", "own_2pt"),
        ("oreb_3pt", False, "desc", "own_3pt"),
        ("oreb_2pt", True, "asc", "allowed_2pt"),
        ("oreb_3pt", True, "asc", "allowed_3pt"),
    ]:
        ranked = _rank(_clock_rows(conn, "team", stat, "overall", against=against), "value", direction)
        row = next((r for r in ranked if r["id"] == team_id), None)
        if row:
            profile[field] = {"rank": row["rank"], "value": row["value"], "pool": len(ranked)}
    return profile


def matchup_scout(team_id, opponent_id):
    """How `opponent_id` might beat `team_id` -- pairs team_id's shot-clock
    DEFENSIVE weaknesses (opponent shooting % allowed, by window) with
    opponent_id's own OFFENSIVE strength in that same window ("attack"
    keys), and team_id's defensive strengths with opponent_id's shooting
    weaknesses there ("caution" keys not to force), plus a ball-pressure
    read and an offensive-rebounding-off-3PT caution when it's a real part
    of team_id's identity. Everything is season-wide league rank (10
    teams)."""
    conn = db.get_conn()
    season_trad = _trad_team_rows(conn)
    team_row = next((r for r in season_trad if r["id"] == team_id), None)
    opp_row = next((r for r in season_trad if r["id"] == opponent_id), None)
    if not team_row or not opp_row:
        conn.close()
        return None

    edges = []
    for stat in ("2pt_pct", "3pt_pct"):
        for bucket in ("0-8", "8-18", "18+"):
            team_def_ranked = _rank(_clock_rows(conn, "team", stat, bucket, against=True), "value", "asc")
            opp_off_ranked = _rank(_clock_rows(conn, "team", stat, bucket, against=False), "value", "desc")
            td = next((r for r in team_def_ranked if r["id"] == team_id), None)
            oo = next((r for r in opp_off_ranked if r["id"] == opponent_id), None)
            if not td or not oo:
                continue
            pool = len(team_def_ranked)
            payload = {
                "category": f"{_CLOCK_SHOOTING_LABEL[stat]} -- {_CLOCK_BUCKET_LABEL[bucket]}",
                "stat": stat, "bucket": bucket, "pool": pool,
                "team_def_rank": td["rank"], "team_def_value": td["value"],
                "opp_off_rank": oo["rank"], "opp_off_value": oo["value"],
            }
            edges.append({"attack_score": td["rank"] - oo["rank"], "caution_score": oo["rank"] - td["rank"], "payload": payload})

    keys = []
    used = set()
    for e in sorted(edges, key=lambda x: x["attack_score"], reverse=True):
        p = e["payload"]
        if e["attack_score"] <= 0 or p["category"] in used or len([k for k in keys if k["kind"] == "attack"]) >= 3:
            continue
        used.add(p["category"])
        label = _CLOCK_SHOOTING_LABEL[p["stat"]].lower()
        bucket_label = _CLOCK_BUCKET_LABEL[p["bucket"]]
        keys.append({
            "kind": "attack", "category": p["category"],
            "text": (
                f"{opp_row['name']} can attack {team_row['name']} on {label} during the {bucket_label}: "
                f"{team_row['name']} allow {p['team_def_value']}% there (#{p['team_def_rank']} of {p['pool']}), and "
                f"{opp_row['name']} shoot {p['opp_off_value']}% there themselves (#{p['opp_off_rank']} of {p['pool']})."
            ),
            "data": p,
        })

    for e in sorted(edges, key=lambda x: x["caution_score"], reverse=True):
        p = e["payload"]
        if e["caution_score"] <= 0 or p["category"] in used or len([k for k in keys if k["kind"] == "caution"]) >= 2:
            continue
        used.add(p["category"])
        label = _CLOCK_SHOOTING_LABEL[p["stat"]].lower()
        bucket_label = _CLOCK_BUCKET_LABEL[p["bucket"]]
        keys.append({
            "kind": "caution", "category": p["category"],
            "text": (
                f"Avoid settling for {label} during the {bucket_label} -- {team_row['name']} defend it well "
                f"(#{p['team_def_rank']} of {p['pool']}, allowing just {p['team_def_value']}%), and it isn't a "
                f"strength for {opp_row['name']} either ({p['opp_off_value']}%, #{p['opp_off_rank']} of {p['pool']})."
            ),
            "data": p,
        })

    opp_forced_ranked = _rank(_clock_rows(conn, "team", "tov", "overall", against=True), "value", "desc")
    of = next((r for r in opp_forced_ranked if r["id"] == opponent_id), None)
    if of:
        keys.append({
            "kind": "pressure", "category": "Ball pressure",
            "text": (
                f"{team_row['name']} average {team_row['topg']} turnovers a game; {opp_row['name']} force "
                f"{of['value']} a game defensively (#{of['rank']} of {len(opp_forced_ranked)} in the league). "
                f"Sustained ball pressure is a proven way to speed {team_row['name']} into mistakes."
            ),
            "data": {"team_tov": team_row["topg"], "opp_forced": of["value"], "opp_forced_rank": of["rank"], "pool": len(opp_forced_ranked)},
        })

    oreb3_ranked = _rank(_clock_rows(conn, "team", "oreb_3pt", "overall", against=False), "value", "desc")
    o3 = next((r for r in oreb3_ranked if r["id"] == team_id), None)
    if o3 and o3["rank"] <= 3:
        keys.append({
            "kind": "caution", "category": "Offensive rebounding off 3PT misses",
            "text": (
                f"{team_row['name']} are #{o3['rank']} of {len(oreb3_ranked)} in the league at grabbing their own "
                f"offensive rebounds off missed threes ({o3['value']} a game) -- a contested three is not "
                f"automatically a defensive stop against them."
            ),
            "data": {"rank": o3["rank"], "value": o3["value"], "pool": len(oreb3_ranked)},
        })

    rebounding = {
        "team": _rebounding_profile(conn, team_id),
        "opponent": _rebounding_profile(conn, opponent_id),
    }

    basic_summary = _basic_stats_summary(conn, team_id, opponent_id, season_trad, team_row, opp_row)

    conn.close()
    return {
        "team": {"id": team_row["id"], "name": team_row["name"], "logo_url": team_row["team_logo_url"]},
        "opponent": {"id": opp_row["id"], "name": opp_row["name"], "logo_url": opp_row["team_logo_url"]},
        "keys": keys,
        "rebounding": rebounding,
        "basic_summary": basic_summary,
    }
