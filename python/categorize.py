from __future__ import annotations

import re

POLYMARKET_CATEGORY_MAP = {
    "Sports": "sports",
    "Economics": "economics",
    "Financials": "economics",
    "Climate and Weather": "climate",
    "Entertainment": "entertainment",
    "Elections": "politics",
    "Politics": "politics",
    "Tech": "world",
    "Health": "world",
    "Science": "world",
    "Culture": "entertainment",
    "World": "world",
    "Crypto": "crypto",
}

def _word(kw: str) -> str:
    """Wrap a short bare token so it matches only as a whole word."""
    return rf"\b{kw}\b"


SPORTS_KEYWORDS = [
    "nba", "mlb", "mls", "epl", "premier league",
    "champions league", "world cup", "tennis", "atp", "wta",
    "ufc", "boxing", "mma", "f1", "formula 1", "grand prix", "nascar",
    "cricket", "rugby", "golf", "pga", "olympics",
    "super bowl", "march madness", "playoff", "world series",
    "stanley cup", "ncaa", "tournament", "mvp", "rushing yards",
    "touchdown", "home run", " vs ", " vs.", "game score", "spread",
    "wnba", "wwe", "esports",
    _word("nfl"), _word("nhl"),
]
POLITICS_KEYWORDS = [
    "election", "president", "presidential", "congress", "senate",
    "parliament", "prime minister", "governor", "mayor",
    "democrat", "republican", "gop", "dnc", "rnc",
    "trump", "biden", "harris", "desantis", "newsom",
    "impeachment", "indictment", "executive order", "supreme court",
    "scotus", "nomination", "confirmation", "vote",
    "approval rating", "poll", "ballot",
]
ECONOMICS_KEYWORDS = [
    "fed ", "federal reserve", "interest rate", "rate cut", "rate hike",
    "fomc", "powell", "gdp", "cpi", "ppi", "inflation",
    "jobs report", "unemployment", "payroll", "nonfarm",
    "treasury", "bond", "yield", "recession",
    "stock", "s&p", "nasdaq", "dow jones", "ipo",
    "tariff", "trade war", "debt ceiling", "housing", "mortgage", "vix",
    "gold", "silver", "oil", "crude oil", "earnings", "revenue",
]
CRYPTO_KEYWORDS = [
    "bitcoin", "ethereum", "solana",
    "crypto", "token", "defi", "blockchain",
    "doge", "xrp", "cardano", "polkadot",
    "binance", "coinbase", "mining", "halving",
    _word("btc"), _word("eth"), _word("sol"),
]
CLIMATE_KEYWORDS = [
    "temperature", "hurricane", "tornado", "earthquake",
    "rainfall", "snowfall", "weather", "climate",
    "record high", "record low", "heat wave", "cold snap",
    "wildfire", "flood", "drought",
]
ENTERTAINMENT_KEYWORDS = [
    "oscar", "oscars", "grammy", "emmy", "golden globe", "box office",
    "streaming", "netflix", "disney", "spotify",
    "album", "movie", "tv show", "reality tv",
    "viral", "tiktok",
]


_SPORTS_SLUG_RE = re.compile(
    r"^(fifwc|epl|ucl|uel|laliga|seriea|bundesliga|ligue1|mls|nba|wnba|nfl"
    r"|mlb|nhl|atp|wta|ufc|f1|nascar|ncaab|ncaaf|cbb|cfb)-",
    re.IGNORECASE,
)
_SPORTS_SLUG_SUBSTRINGS = ("wimbledon", "world-cup", "grand-slam", "-open-tennis")


def _matches(kw: str, t: str) -> bool:
    """Substring match for phrases, whole-word match for bare tokens."""
    if kw.startswith(r"\b"):
        return re.search(kw, t) is not None
    return kw in t


def categorize_by_keywords(title: str, slug: str = "") -> str:
    s = (slug or "").lower()
    if s and (_SPORTS_SLUG_RE.search(s) or any(x in s for x in _SPORTS_SLUG_SUBSTRINGS)):
        return "sports"
    t = (title or "").lower()
    for kw in SPORTS_KEYWORDS:
        if _matches(kw, t):
            return "sports"
    for kw in POLITICS_KEYWORDS:
        if _matches(kw, t):
            return "politics"
    for kw in ECONOMICS_KEYWORDS:
        if _matches(kw, t):
            return "economics"
    for kw in CRYPTO_KEYWORDS:
        if _matches(kw, t):
            return "crypto"
    for kw in CLIMATE_KEYWORDS:
        if _matches(kw, t):
            return "climate"
    for kw in ENTERTAINMENT_KEYWORDS:
        if _matches(kw, t):
            return "entertainment"
    return "world"


CATEGORY_EDGE = {
    "sports":        +1.0,
    "crypto":        +2.0,
    "world":         -4.0,
    "politics":       0.0,
    "economics":      0.0,
    "entertainment":  0.0,
    "climate":        0.0,
}


_MICRO_SLUG_RE = re.compile(
    r"(updown-(5m|15m)-\d+|-up-or-down-)", re.IGNORECASE
)
MICRO_MARKET_FILTERS = ["-updown-5m-", "-updown-15m-", "-up-or-down-"]


def is_micro_market(slug: str) -> bool:
    s = (slug or "").lower()
    if not s:
        return False
    return bool(_MICRO_SLUG_RE.search(s)) or any(f in s for f in MICRO_MARKET_FILTERS)
