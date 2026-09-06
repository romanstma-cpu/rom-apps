"""One HTTP session factory for every Polymarket client.

The first soak ran four hours and logged a Gamma failure on almost every
cycle — always the *first* category in the list, which read like "politics
is broken" and was nothing of the kind. Between discovery passes the engine
sleeps for minutes; Polymarket closes the pooled keep-alive socket during
that idle, and the next request hands the dead socket to urllib3, which
raises RemoteDisconnected. The category whose turn it was silently vanished
from the watch list for that cycle (19 markets became 14 and back again),
and no strategy ever knew its universe had shrunk.

urllib3's Retry treats a connection dropped before any response as a
`connect` failure and dials again on a fresh socket, so one retry is enough
to make the whole class of failure invisible. The status list covers the
other half: 429 from rate limiting, 5xx from a bad moment upstream.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "rom-polybot (+https://romapps.xyz)"


def make_session(pool_size: int = 16) -> requests.Session:
    """A Session that retries transport failures and rate limits.

    ``pool_size`` must cover the engine's snapshot thread pool: connections
    beyond the pool are discarded after use, so a pool smaller than the
    worker count silently reopens a socket per snapshot and throws away the
    keep-alive this module exists to protect.
    """
    retry = Retry(
        total=3,
        connect=3,           # the dead-keep-alive case above
        read=2,
        status=2,
        backoff_factor=0.5,  # 0.5s, 1s, 2s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size,
                          pool_maxsize=pool_size)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # Some Polymarket edges answer 403 to a bare default agent; identify.
    session.headers.update({"User-Agent": USER_AGENT})
    return session
