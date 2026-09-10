# ROM Polybot 2.13.0 review

Use this record to assess the terminal update and its verification before installing it. The review checks the inherited changes and affected workflows; it does not certify profitability or every possible exchange failure.

## Changes

- Overview adds a latest-decision-cycle readout, terminal typography, and a more structured command panel. Missing data stays unknown. Metrics stack in narrow windows.
- MainActivity displays the leading filter counts from the backend. Bars compare counts; they do not represent win probabilities.
- Analytics checks failed exit and restart responses. Exit requests retain visible feedback and never claim every position was sold. The confirmation explains that execution can leave holdings open and does not pause the strategy.
- Navigation shortcuts ignore text inputs, composition, and dialogs.
- Onboarding copy matches the maintained UI tests.
- The migration test pins the verified schema digest from commit 4a8105f, whose package version is 2.8.0. Migration and row-preservation assertions remain intact.

## Verification

- Backend: 1,337 passed, 139 skipped. Most skips are conditional config-parity cases that do not apply to the parameter under test.
- TypeScript check, production build, frozen-backend self-test, and Windows installer build passed.
- Config-boundary validation and E2E string-drift checks passed.
- Electron suites passed: arming, public readiness, strategy clarity, paper activity, risk drafts, referrals, portfolio replay, calibration, and terminal review.
- Terminal review covers desktop and 600px layout, reduced motion, form/modal shortcut guards, rejected exits, and successful requests with zero fills. Calibration and terminal review also passed against the packaged executable.
- Strict UI audit: zero findings. Source diff whitespace check passed.

Tests use isolated profiles with no real orders. Live exchange execution and long-term returns remain unverified. Build output includes non-blocking Vite module-format and bundle-size warnings.

## Installer

The installer is `release/ROM PolyBot-Setup-2.13.0.exe`. Close your running app before installing. The running installation was left undisturbed; this update was not published to the website.

SHA-256: `7696E9E812E6A9F70B4FCA252467A5ED3F416517D387300E786213E93C26B3EA`.
