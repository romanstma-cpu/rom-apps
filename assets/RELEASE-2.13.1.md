# ROM Polybot 2.13.1

Patch release: accessibility hardening, a performance improvement for the positions list, and a startup-crash fix.

**Startup crash fixed.** A React hook call had been left at module scope during a refactor, which crashed the renderer on launch with `Cannot read properties of null (reading 'useContext')`. The hook now lives inside its component, and the app boots normally again. Caught by the arming e2e suite, which validates the packaged app from a clean profile.

**Keyboard navigation for every dialog.** The four remaining full-screen overlays — the Boss Fight milestone arena, the Scripts arm and AI Context Pack dialogs, the full-reset confirmation, and the shareable-stats card — now trap focus (Tab/Shift+Tab cycle, focus restore on close, background scroll locked) and expose proper dialog semantics (`role="dialog"`, `aria-modal`, descriptive labels). Keyboard users can no longer tab out of a modal into the page behind it.

**Faster positions list.** The Positions page now renders only the rows in view (with a small overscan) inside a fixed-height scroll container, instead of mounting the full list at once. Filters, sorting, grouping, counts, and styling are unchanged; the sticky header stays visible while scrolling. Large portfolios scroll smoothly.

**Config-parity guard.** A new bidirectional drift test asserts that every key in the backend default config appears in the frontend type and the IPC validator — and the reverse — so the three sources of truth cannot silently diverge. It passes today with zero drift.

1,538 backend tests, TypeScript checking, the production build, and all nine Electron UI suites pass. The arming suite now retries its first click for up to six seconds to tolerate slow cold starts instead of flaking. No real trades were placed and no profitability improvement is claimed. The Windows installer is unsigned.