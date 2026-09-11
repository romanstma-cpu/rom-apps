"""The interlock that keeps read-only stages read-only.

Stages 0-4 must not be able to place or cancel an order, whatever a bug in a
stage does. The guarantee is enforced here rather than by each stage promising
to behave: `arm()` wraps the single HTTP chokepoint, `polymarket_api._request`,
and refuses anything that is not a GET or that touches a known mutating path.

A refusal raises, it does not warn. A stage that trips this is broken and must
stop, not continue with an unknown amount of real activity behind it.
"""
from __future__ import annotations

import polymarket_api


class MutationRefused(RuntimeError):
    """A read-only stage attempted a request that could change the account."""


# Mutating paths as of 2.13. Kept explicit rather than derived, so that a new
# endpoint is refused by the method check until someone deliberately lists it.
MUTATING_PATH_MARKERS = ('/v1/orders', '/cancel')


def _is_mutating(method: str, path: str) -> bool:
    if str(method).upper() != 'GET':
        return True
    return any(marker in path for marker in MUTATING_PATH_MARKERS)


def arm():
    """Wrap `_request` so mutations are refused. Returns a disarm callable."""
    original = polymarket_api._request

    async def guarded(method, path, **kwargs):
        if _is_mutating(method, path):
            raise MutationRefused(
                f'read-only stage attempted {str(method).upper()} {path}; '
                'refused by the livecheck interlock'
            )
        return await original(method, path, **kwargs)

    polymarket_api._request = guarded

    def disarm():
        polymarket_api._request = original

    return disarm
