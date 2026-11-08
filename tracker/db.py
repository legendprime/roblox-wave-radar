"""SQLite storage. All timestamps are UTC ISO-8601 strings like 2026-11-08T09:30:00Z,
so plain string comparison orders them correctly."""
import datetime as dt
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "tracker.sqlite"

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT,                 -- running | ok | partial | failed
  requests INTEGER,
  n_sort_hits INTEGER,
  n_search_hits INTEGER,
  n_refreshed INTEGER,
  n_new_games INTEGER,
  errors TEXT
);

-- One row per game (Roblox "universe"). Metadata is the latest seen.
CREATE TABLE IF NOT EXISTS games (
  universe_id INTEGER PRIMARY KEY,
  root_place_id INTEGER,
  name TEXT,
  description TEXT,
  creator_id INTEGER,
  creator_name TEXT,
  creator_type TEXT,
  creator_verified INTEGER,
  created_at TEXT,             -- when the game was created on Roblox
  updated_at TEXT,             -- last time the developer published an update
  genre_l1 TEXT,
  genre_l2 TEXT,
  max_players INTEGER,
  first_seen_at TEXT,          -- when this tracker first saw it
  first_seen_via TEXT,         -- e.g. "sort:up-and-coming" or "search:steal a"
  last_seen_at TEXT,           -- last time it showed up in a chart or search
  last_refreshed_at TEXT,
  last_playing INTEGER,
  peak_playing INTEGER DEFAULT 0,
  peak_playing_at TEXT,
  icon_url TEXT,
  icon_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS name_history (
  universe_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  PRIMARY KEY (universe_id, name)
);

-- Player counts and totals at each run.
CREATE TABLE IF NOT EXISTS snapshots (
  run_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  universe_id INTEGER NOT NULL,
  playing INTEGER,
  visits INTEGER,
  favorites INTEGER,
  up_votes INTEGER,
  down_votes INTEGER,
  PRIMARY KEY (run_id, universe_id)
);
CREATE INDEX IF NOT EXISTS snapshots_game_ts ON snapshots (universe_id, ts);
CREATE INDEX IF NOT EXISTS snapshots_ts ON snapshots (ts);

-- Where each game sat on each chart at each run.
CREATE TABLE IF NOT EXISTS sort_hits (
  run_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  sort_id TEXT NOT NULL,
  device TEXT NOT NULL,
  position INTEGER NOT NULL,
  universe_id INTEGER NOT NULL,
  playing INTEGER,
  sponsored INTEGER,
  PRIMARY KEY (run_id, sort_id, device, universe_id)
);
CREATE INDEX IF NOT EXISTS sort_hits_game ON sort_hits (universe_id, sort_id);

-- Which search queries surfaced each game at each run.
CREATE TABLE IF NOT EXISTS search_hits (
  run_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  query TEXT NOT NULL,
  position INTEGER NOT NULL,
  universe_id INTEGER NOT NULL,
  playing INTEGER,
  sponsored INTEGER,
  PRIMARY KEY (run_id, query, universe_id)
);

-- Milestones: first time crossing a player threshold, first time on a chart.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  universe_id INTEGER NOT NULL,
  kind TEXT NOT NULL,          -- crossed | entered_sort
  value INTEGER NOT NULL DEFAULT 0,   -- threshold for "crossed"
  detail TEXT NOT NULL DEFAULT '',    -- sort id for "entered_sort"; for "crossed": while_tracked | first_seen_above
  baseline INTEGER NOT NULL DEFAULT 0,-- 1 = recorded on the very first run (not a real "new" event)
  notified INTEGER NOT NULL DEFAULT 0,
  UNIQUE (universe_id, kind, value, detail)
);

-- Watchlist added from the command line (config.toml [[watch]] entries are merged in).
CREATE TABLE IF NOT EXISTS watch (
  universe_id INTEGER PRIMARY KEY,
  kind TEXT,
  note TEXT,
  added_at TEXT
);

-- Free-form coding of games for lineage analysis, e.g. stage.capability = treadmill.
CREATE TABLE IF NOT EXISTS labels (
  universe_id INTEGER NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  note TEXT,
  set_at TEXT NOT NULL,
  PRIMARY KEY (universe_id, key)
);

-- Prediction log. Write the prediction BEFORE the outcome is known.
CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY,
  made_at TEXT NOT NULL,
  subject TEXT NOT NULL,       -- concept name or game name
  universe_id INTEGER,         -- may be NULL until the concept is published (see `predict link`)
  threshold INTEGER NOT NULL,  -- "peak players >= threshold"
  by_date TEXT,                -- deadline (UTC ISO), or
  within_days INTEGER,         -- ...days after the game's creation date
  probability REAL NOT NULL,   -- 0..1
  note TEXT,
  actual_peak INTEGER,
  outcome INTEGER,             -- 1 hit, 0 miss, NULL not graded yet
  graded_at TEXT
);
"""


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


_FRACTION = re.compile(r"\.\d+")


def parse_iso(s):
    if not s:
        return None
    # Roblox sends fractional seconds of varying length; drop them.
    s = _FRACTION.sub("", s.strip()).replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


def norm_iso(s):
    t = parse_iso(s)
    return iso(t) if t else None


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()
    return conn
