ROM PolyBot 2.36.6 fixes candidate starvation in Large Trade and Momentum selection. Previously, the bot fetched the newest 100 rows and then removed already-used signals. Those rows could hide fresh, unused candidates, causing a cycle to find nothing to evaluate. Used IDs are now excluded before the query's 50-candidate limit, with stable newest-first ordering.

No entry thresholds were lowered. Freshness, resolution, allowed signal types, qualified live edge, fees, quote quality, available funds, sizing and risk limits still apply. Tests reproduce the missed-candidate case, preserve the exclusions and verify large seen-ID histories without SQLite parameter-limit failures. No live orders were sent during validation.

This release includes the 2.36.5 visual refresh. Finding more candidates does not prove profitable trading or guarantee fills; the existing evidence qualification remains required for live entries.
