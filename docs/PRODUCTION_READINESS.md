# ROM PolyBot production readiness

Every public build must pass `npm run release:gate` before an installer is
published. The gate checks types, IPC drift, the complete Python test suite,
the offline 3x capacity probe, and the production renderer build. Windows also
runs the interactive UI audit; the headless Mac builder launches and inspects
the packaged app instead.

## Release sequence

1. Build and test immutable Windows and Apple Silicon installers.
2. Run the packaged backend self-test and installer integrity checks.
3. Upload installers and SHA-256 files to a versioned GitHub release while the
   website continues to point at the prior known-good version.
4. Download and verify the published assets.
5. Update the website links only after both platforms pass verification.
6. Verify the live website and both download responses.

This is a blue-green promotion for a downloadable desktop product: the prior
release stays available throughout the build and is the rollback target. A bad
release is rolled back by restoring the prior website links; no running user is
interrupted and existing installers remain immutable.

## Runtime controls

- HTTP has separate connect/read deadlines. Idempotent reads have bounded
  backoff; order submissions are never automatically retried.
- A closed/open/half-open execution circuit pauses new entries after repeated
  quote or order failures.
- Public market discovery and private execution use independent bulkheads.
- `tradingStatus.readiness` verifies SQLite access, disk headroom, stream
  freshness, circuit state, dependency observations, and bulkhead saturation.
- RPCs and main strategy cycles carry trace and span IDs into structured logs.
- `npm run check:capacity` exercises 24 concurrent market operations, three
  times the expected desktop peak, while checking execution latency isolation.
- `npm run check:resilience` runs local failure drills for stalled calls,
  saturation, circuit recovery, and watchdog recovery. It never injects a
  failure into Polymarket or a public release.

## Rollback

Keep at least the previous Windows and Mac release assets. If post-publish smoke
checks fail, restore the preceding website URLs, verify them, and mark the bad
release as a prerelease. Database changes remain additive so the prior app can
open the current local database.
