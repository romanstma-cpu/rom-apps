Strategy evidence upgrade

- Adds fixed hierarchical calibration pools so valid same-category evidence can qualify when exact price/score groups are too sparse.
- Always prefers the most specific qualified group.
- Never shares evidence across signal source, side, category, or scoring version.
- Every fallback independently passes chronological holdout, recency, accuracy, fee stress, stability, and conservative-return checks.

Validated with the full Python suite, TypeScript checks, UI audit, capacity probe, production build, and packaged-backend self-test.
