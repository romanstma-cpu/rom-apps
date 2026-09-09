# ROM Polybot 2.6

- Shared main-strategy status across Overview, sidebar, header and Strategy. Enabled configuration is labelled separately from confirmed execution.
- Failed or timed-out activity reads no longer leave stale scanning visible. Offline takes precedence. Scanning requires a recent decision cycle.
- Starting setup groups mode controls and a readiness checklist immediately above saved risk limits.
- Removed duplicate live/practice switches in Advanced so all UI starts respect saved-limit and connection guards. Pause remains available for an enabled mode.
- Typecheck, production build and isolated strategy-clarity Electron checks passed. No real trading performed.

The strategy algorithm and backend bundle are unchanged from 2.5.
