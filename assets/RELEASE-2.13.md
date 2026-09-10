# ROM Polybot 2.13

Hardening and interface honesty: fewer ways for the terminal to overstate what it knows or did.

**Kill switch tells the truth.** Flattening now reports the actual result of the exit request. A completed request no longer implies every position was sold — exits depend on live quotes and displayed depth, so some holdings can remain open — and the confirmation explains that execution may leave positions open and does not pause the strategy. Failed requests show their reason instead of a success message.

**Overview reads like a control panel.** A latest-decision-cycle readout shows what the last scanning cycle concluded, and three aligned metrics summarize balance, equity and exposure. Missing data stays unknown rather than reading as zero. Metrics and command cards stack cleanly in narrow windows. MainActivity now shows the leading-entry filter counts that the backend actually scored.

**Navigation respects your input.** Global shortcuts (Ctrl+1..9) ignore text fields, composition input and any open dialog, so typing is never hijacked. The onboarding copy matches the maintained UI tests.

**Fewer edge-case crashes.** Technical indicators reject NaN and infinite values instead of letting them poison EMA, VWAP and momentum math; the CLOB parser ignores malformed or out-of-range book levels; copy-trader sizing uses exact integer cents instead of float division, which was off by one contract at clean penny prices.

1,535 backend tests, TypeScript checking, the production build, the bundled-backend selftest, and nine Electron UI suites pass, including a strict terminal-review suite that checks the 600px layout, reduced-motion behaviour, shortcut guards and both rejected and zero-fill exit feedback. No real trades were placed.

No profitability improvement is claimed: these changes make reported execution honest and remove crash and loss modes. Profitability and live authenticated trading remain unverified. The Windows installer is unsigned.