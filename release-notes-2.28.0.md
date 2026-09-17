# ROM PolyBot 2.28.0

This release completes the production-hardening pass for the public desktop
app. It does not loosen any trading or risk rule.

- Reserves separate runtime capacity for private execution and public market
  discovery, preventing slow scans from starving account or order work.
- Adds a deep readiness check for the database, disk headroom, exchange
  observations, stream freshness, execution circuit, and capacity lanes.
- Blocks starting live mode when a critical readiness dependency is down and
  shows system readiness in the Trade Readiness panel.
- Correlates backend RPC and main-strategy cycle logs with trace and span IDs.
- Adds an offline 3x-peak capacity gate with an execution-latency SLO.
- Adds deterministic failure drills covering timeouts, saturation, breaker
  recovery, and backend watchdog recovery without contacting production.
- Makes the complete release gate mandatory in CI and before Apple Silicon
  packaging; the documented promotion order keeps the previous release live
  until new installers pass smoke and checksum verification.
