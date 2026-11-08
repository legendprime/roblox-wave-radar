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
