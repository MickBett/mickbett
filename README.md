# Season Tracker

A small local web app for building up a season's worth of basketball stats,
one game at a time. Drop in each game's raw stats export and it accumulates
standings, player leaderboards, season shot charts, and trends.

## Setup (one-time)

```bash
cd ~/season-tracker
pip3 install -r requirements.txt
```

## Run it

```bash
./run.sh
```

Then open **http://127.0.0.1:8000** in your browser. Leave the terminal
running while you use it — it's a local server, not a hosted site. Press
`Ctrl+C` in the terminal to stop it.

## Importing games

Go to the **Import** tab and drag in the raw `data.json` export for a game —
the same JSON structure we've been pulling from FIBA LiveStats / Genius
Sports pages all session (`.../data/<matchId>/data.json`), containing:

- `tm.1` / `tm.2` — team box scores, per-player stats (`pl`), and shot
  locations (`shot`)
- `pbp` — the full play-by-play, used to derive the shot-clock estimate

You can drop multiple files at once. Each file is fingerprinted (hash of its
contents), so re-dropping the same game is caught and skipped rather than
double-counted. Since the feed has no game-date field, set the **Game date**
picker before dropping files — it's used for sorting the game log and trend
charts.

## What you get

- **Standings** — win/loss record, PPG/opponent PPG, point differential
- **Leaderboards** — every player who's appeared, averages across all their
  games, sortable
- **Shot Charts** — a season-long shot chart per team or player (every
  attempt from every imported game plotted on one half-court), plus a
  **shot-clock breakdown**: attempts and make% bucketed by approximately how
  much of the shot clock had elapsed when the shot went up. This is
  *derived*, not read directly — the feed has no shot-clock field, so it's
  reconstructed from the game clock and the last clock-resetting event
  (defensive rebound / turnover / made basket / period start → 24s allowed;
  offensive rebound → 14s allowed).
- **Game Log** — every game imported, click one to see both box scores
- **Trends** — a team's points-for/against or a player's points and FG%,
  game by game across the season

## Data

Everything lives in `season.db` (SQLite) in this folder — no external
database, nothing leaves your machine. Delete that file to start a fresh
season.

## Notes / limitations

- The shot-clock figure is an approximation (explained above) — treat it as
  directional, not official.
- Team/player identity is matched by name as it appears in the feed. If a
  name is spelled differently between two files (e.g. an accent or suffix
  changes), it'll show up as a separate player — worth a glance at the
  Leaderboards tab occasionally.
- Chart.js is loaded from a CDN, so the browser needs internet access the
  first time it loads a page (the backend/data itself needs no internet).
