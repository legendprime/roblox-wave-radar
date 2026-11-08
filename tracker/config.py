import tomllib

from .db import ROOT

CONFIG_PATH = ROOT / "config.toml"

DEFAULTS = {
    "collect": {
        "devices": ["high_end_phone", "computer"],
        "country": "all",
        "search_pages": 3,
        "queries": [],
        "min_track_playing": 25,
        "keep_new_days": 30,
        "unseen_refresh_min_playing": 200,
        "meta_refresh_per_run": 500,
        "search_budget_s": 540,     # stop searching after this many seconds; the rest continue next run
        "details_budget_s": 480,
        "hot_queries_per_run": 6,
        "hot_search_pages": 2,
    },
    "radar": {
        "timezone": "America/New_York",
        "wave_window_days": 60,
        "min_games": 4,
        "min_novelty": 0.5,
        "merge_containment": 0.5,
        "merge_jaccard": 0.5,
        "show_crowded_max_leader_age": 365,
        "show_crowded_rows": 15,
        "min_leader_playing": 5000,
        "jump_min_total": 20000,
        "show_crowded_min_total": 20000,
        "crowded_games": 80,
        "novelty_old_min_playing": 1000,
        "crowded_hit_rate": 0.25,
        "crowded_age_days": 75,
        "jump_min_hits": 2,
        "jump_hit_rate": 0.4,
        "jump_max_age_days": 60,
        "starting_max_age_days": 30,
        "starting_max_games": 8,
        "fading_7d": 0.75,
        "lone_max_age_days": 35,
        "lone_min_playing": 3000,
        "alert_lone_playing": 10000,
        "alert_lone_max_age_days": 21,
        "max_alerts_per_run": 5,
        "alert_min_runs": 3,          # no alerts until the database has this many checks...
        "alert_min_games": 3000,      # ...and this many games (a thin database overrates waves)
        "alert_min_stage_runs": 2,    # a wave must hold its stage for this many checks in a row
        "alert_starting_min_leader": 10000,
        "lineage_subgenres": ["Tycoon", "Incremental Simulator", "Idle"],
        "generic_words": [],
    },
    "alerts": {
        "thresholds": [1000, 10000, 100000, 1000000],
        "sorts": ["up-and-coming", "top-trending", "trending-in-simulation", "top-playing-now"],
        "notify": True,
        "notify_max_age_days": 60,
        "notify_thresholds": [10000, 100000, 1000000],
    },
    "report": {
        "breakout_max_age_days": 45,
        "breakout_min_peak": 1000,
        "lineage_genres": ["Simulation"],
    },
    "enrich": {
        "budget_s": 150,              # seconds per run for badge + creator lookups
        "badge_refresh_hours": 20,    # badges about once a day
        "creator_refresh_days": 7,    # creators about once a week
        "key_games_limit": 200,
        "big_creator_members": 1000000,
    },
    "watch": [],
}


def load(path=CONFIG_PATH):
    with open(path, "rb") as f:
        user = tomllib.load(f)
    cfg = {}
    for section, defaults in DEFAULTS.items():
        if isinstance(defaults, dict):
            cfg[section] = {**defaults, **user.get(section, {})}
        else:
            cfg[section] = user.get(section, defaults)
    return cfg


def watchlist(conn, cfg):
    """{universe_id: {"kind": ..., "note": ...}} from config.toml plus `watch add`."""
    out = {}
    for row in conn.execute("SELECT universe_id, kind, note FROM watch"):
        out[row["universe_id"]] = {"kind": row["kind"] or "watch", "note": row["note"] or ""}
    for w in cfg["watch"]:
        if "id" in w:
            out[int(w["id"])] = {"kind": w.get("kind", "watch"), "note": w.get("note", "")}
    return out
