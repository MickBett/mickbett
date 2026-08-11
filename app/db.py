"""SQLite storage for the season tracker.

One file, no external database needed. The schema is intentionally simple:
teams/players are looked up-or-created by name; everything else hangs off
a `games` row per imported file.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "season.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT UNIQUE NOT NULL,
    code     TEXT,
    logo_url TEXT
);

CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash       TEXT UNIQUE NOT NULL,
    game_date       TEXT NOT NULL,
    team1_id        INTEGER NOT NULL REFERENCES teams(id),
    team2_id        INTEGER NOT NULL REFERENCES teams(id),
    team1_score     INTEGER,
    team2_score     INTEGER,
    period_length   INTEGER,
    source_filename TEXT,
    imported_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    team_id   INTEGER NOT NULL REFERENCES teams(id),
    photo_url TEXT,
    UNIQUE(name, team_id)
);

CREATE TABLE IF NOT EXISTS team_game_stats (
    game_id  INTEGER NOT NULL REFERENCES games(id),
    team_id  INTEGER NOT NULL REFERENCES teams(id),
    is_team1 INTEGER NOT NULL,
    pts INTEGER, opp_pts INTEGER,
    oreb INTEGER, dreb INTEGER, reb INTEGER,
    ast INTEGER, stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER,
    fgm INTEGER, fga INTEGER, tpm INTEGER, tpa INTEGER, ftm INTEGER, fta INTEGER,
    PRIMARY KEY (game_id, team_id)
);

CREATE TABLE IF NOT EXISTS player_game_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    minutes_sec INTEGER,
    pts INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER,
    fgm INTEGER, fga INTEGER, tpm INTEGER, tpa INTEGER, ftm INTEGER, fta INTEGER,
    plus_minus INTEGER,
    starter INTEGER
);

CREATE TABLE IF NOT EXISTS shots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          INTEGER NOT NULL REFERENCES games(id),
    team_id          INTEGER NOT NULL REFERENCES teams(id),
    player_id        INTEGER NOT NULL REFERENCES players(id),
    period           INTEGER,
    gt_seconds       INTEGER,
    x                REAL,
    y                REAL,
    made             INTEGER,
    action_type      TEXT,     -- '2pt' | '3pt'
    sub_type         TEXT,     -- jumpshot / layup / dunk / ...
    shot_clock_used  REAL,     -- approx seconds elapsed since last possession-start
    possession_type  TEXT      -- 'full' (24s allowed) | 'oreb' (14s allowed)
);

CREATE TABLE IF NOT EXISTS pbp_events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id               INTEGER NOT NULL REFERENCES games(id),
    team_id               INTEGER NOT NULL REFERENCES teams(id),
    player_id             INTEGER REFERENCES players(id),   -- NULL for team-attributed events
    action_type           TEXT NOT NULL,   -- '2pt'|'3pt'|'freethrow'|'turnover'|'foul'|'foulon'|'rebound_off'|'rebound_def'|'steal'|'assist'|'block'|'substitution'
    sub_type              TEXT,            -- for action_type='substitution': 'in' | 'out'
    made                  INTEGER,         -- 1/0 for 2pt/3pt/freethrow; NULL otherwise
    shot_clock_used       REAL,            -- approx seconds elapsed since the shot clock was last reset
    possession_type       TEXT,            -- 'full' (24s allowed) | 'oreb' (14s allowed)
    off_reb_source        TEXT,            -- for action_type='rebound_off' only: '2pt' | '3pt' | NULL
    game_seconds_elapsed  INTEGER,         -- regulation-relative elapsed game clock (period<=4 only, else NULL)
    action_number         INTEGER          -- the feed's own event sequence number -- lets us replay a
                                            -- game's events (including substitutions) in exact chronological
                                            -- order to reconstruct which 5 players were on court for any
                                            -- given event (the "lineups" feature)
);

CREATE INDEX IF NOT EXISTS idx_pgs_player ON player_game_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_tgs_team   ON team_game_stats(team_id);
CREATE INDEX IF NOT EXISTS idx_shots_player ON shots(player_id);
CREATE INDEX IF NOT EXISTS idx_shots_team   ON shots(team_id);
CREATE INDEX IF NOT EXISTS idx_events_player ON pbp_events(player_id);
CREATE INDEX IF NOT EXISTS idx_events_team   ON pbp_events(team_id);
"""

# Indexes on columns added via _MIGRATIONS below (rather than in SCHEMA
# above) -- on a pre-existing database, executescript(SCHEMA) runs BEFORE
# _migrate() adds the column via ALTER TABLE, so `CREATE INDEX ... (col)`
# for a migrated column would fail with "no such column" on that first
# post-upgrade run. Created explicitly, after _migrate(), in init_db().
_POST_MIGRATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_game_seq ON pbp_events(game_id, team_id, action_number)",
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# (table, column, type) added after the initial release -- applied with
# ALTER TABLE on startup for any database that predates them, since
# `CREATE TABLE IF NOT EXISTS` alone won't add columns to an existing table.
_MIGRATIONS = [
    ("teams", "logo_url", "TEXT"),
    ("players", "photo_url", "TEXT"),
    ("pbp_events", "game_seconds_elapsed", "INTEGER"),
    ("pbp_events", "action_number", "INTEGER"),
]


def _migrate(conn):
    for table, column, coltype in _MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    for stmt in _POST_MIGRATION_INDEXES:
        conn.execute(stmt)
    conn.commit()
    conn.close()


@contextmanager
def tx():
    """Context manager yielding a connection inside a transaction."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
