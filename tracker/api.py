"""Small, polite client for Roblox's public (unauthenticated) web endpoints.

These endpoints are undocumented and can change without notice. Every call
goes through `Api.get`, which retries on rate limits and server errors.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

USER_AGENT = "Mozilla/5.0 (Macintosh) roblox-trend-tracker/0.1"

EXPLORE_SORTS = "https://apis.roblox.com/explore-api/v1/get-sorts"
OMNI_SEARCH = "https://apis.roblox.com/search-api/omni-search"
GAMES = "https://games.roblox.com/v1/games"
VOTES = "https://games.roblox.com/v1/games/votes"
ICONS = "https://thumbnails.roblox.com/v1/games/icons"
PLACE_TO_UNIVERSE = "https://apis.roblox.com/universes/v1/places/{}/universe"

GAMES_BATCH = 50     # games endpoint rejects more than 50 ids
VOTES_BATCH = 100
ICONS_BATCH = 100


class ApiError(Exception):
    pass


class Api:
    def __init__(self, delay=0.3, timeout=25, retries=4, log=print):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.log = log
        self.session_id = str(uuid.uuid4())
        self.requests = 0
        self.errors = 0
        self.rate_limited = 0
        self.rate_waits = 0
        self.rate_wait_s = 0
        # Per-host pacing. The games endpoint advertises 300/min but returns
        # 429s well below that, so it starts slower and every 429 slows that host further.
        self._host_delay = {"games.roblox.com": 0.8}
        self._last = {}

    def get(self, url, params=None):
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        host = urllib.parse.urlsplit(url).hostname
        for attempt in range(self.retries + 1):
            delay = self._host_delay.get(host, self.delay)
            wait = delay - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    remaining = r.headers.get("x-ratelimit-remaining")
                    body = json.load(r)
                    if remaining is not None and remaining.split(",")[0].strip() == "0":
                        reset = r.headers.get("x-ratelimit-reset", "10")
                        pause = min(int(reset.split(",")[0]) + 1, 65)
                        self.rate_waits += 1
                        self.rate_wait_s += pause
                        self.log(f"  rate limit reached on {host}; waiting {pause}s")
                        time.sleep(pause)
                    return body
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    self.rate_limited += 1
                    self._host_delay[host] = min(4.0, self._host_delay.get(host, self.delay) * 1.6)
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    backoff = min(60, 2 ** attempt * (5 if e.code == 429 else 2))
                    self.log(f"  http {e.code}, retrying in {backoff}s: {url[:90]}")
                    time.sleep(backoff)
                    continue
                self.errors += 1
                raise ApiError(f"HTTP {e.code} for {url[:120]}: {e.read()[:200]!r}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < self.retries:
                    backoff = 2 ** attempt * 2
                    self.log(f"  network error ({e}), retrying in {backoff}s")
                    time.sleep(backoff)
                    continue
                self.errors += 1
                raise ApiError(f"network error for {url[:120]}: {e}") from e
        raise ApiError("unreachable")

    # ---- endpoint helpers -------------------------------------------------

    def sorts(self, device, country):
        """Yield every Games sort on the Charts/Home explore pages."""
        token = None
        for _ in range(15):
            params = {"sessionId": self.session_id, "device": device, "country": country}
            if token:
                params["sortsPageToken"] = token
            data = self.get(EXPLORE_SORTS, params)
            for s in data.get("sorts") or []:
                if s.get("contentType") == "Games":
                    yield s
            token = data.get("nextSortsPageToken")
            if not token:
                break

    def search(self, query, pages):
        """Yield game entries from Roblox search, in result order."""
        token = None
        for _ in range(pages):
            params = {"searchQuery": query, "sessionId": self.session_id, "pageType": "all"}
            if token:
                params["pageToken"] = token
            data = self.get(OMNI_SEARCH, params)
            for group in data.get("searchResults") or []:
                if group.get("contentGroupType") == "Game":
                    yield from group.get("contents") or []
            token = data.get("nextPageToken")
            if not token:
                break

    def games(self, ids):
        out = []
        for i in range(0, len(ids), GAMES_BATCH):
            chunk = ids[i:i + GAMES_BATCH]
            data = self.get(GAMES, {"universeIds": ",".join(map(str, chunk))})
            out.extend(data.get("data") or [])
        return out

    def votes(self, ids):
        out = {}
        for i in range(0, len(ids), VOTES_BATCH):
            chunk = ids[i:i + VOTES_BATCH]
            data = self.get(VOTES, {"universeIds": ",".join(map(str, chunk))})
            for v in data.get("data") or []:
                out[v["id"]] = (v.get("upVotes"), v.get("downVotes"))
        return out

    def icons(self, ids):
        out = {}
        for i in range(0, len(ids), ICONS_BATCH):
            chunk = ids[i:i + ICONS_BATCH]
            data = self.get(ICONS, {"universeIds": ",".join(map(str, chunk)),
                                    "returnPolicy": "PlaceHolder", "size": "150x150",
                                    "format": "Png", "isCircular": "false"})
            for v in data.get("data") or []:
                if v.get("state") == "Completed" and v.get("imageUrl"):
                    out[v["targetId"]] = v["imageUrl"]
        return out

    def badges(self, universe_id):
        data = self.get(f"https://badges.roblox.com/v1/universes/{int(universe_id)}/badges",
                        {"limit": 100, "sortOrder": "Asc"})
        return data.get("data") or []

    def group(self, group_id):
        return self.get(f"https://groups.roblox.com/v1/groups/{int(group_id)}")

    def creator_games(self, creator_type, creator_id):
        kind = "groups" if creator_type == "Group" else "users"
        data = self.get(f"https://games.roblox.com/v2/{kind}/{int(creator_id)}/games",
                        {"accessFilter": "Public", "limit": 50, "sortOrder": "Desc"})
        return data.get("data") or []

    def followers(self, user_id):
        data = self.get(f"https://friends.roblox.com/v1/users/{int(user_id)}/followers/count")
        return data.get("count")

    def universe_for_place(self, place_id):
        data = self.get(PLACE_TO_UNIVERSE.format(int(place_id)))
        return data.get("universeId")
