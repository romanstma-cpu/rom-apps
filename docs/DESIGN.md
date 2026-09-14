# Design System

## Design Direction

Calm trading terminal: clear system state, a single obvious safe next step, and
high-salience warnings only for decisions that can affect real money.

## Typography

Use the existing application type system. Safety messages must stay within a
readable line length and avoid unexplained trading jargon.

## Tokens

Continue the existing ROM palette and spacing system. Warning color signals a
real trade-risk decision; destructive color signals an irreversible exit action.

## Components

| Component | Decision | Status |
|---|---|---|
| Live review | Require an explicit acknowledgment before enabling main-strategy live orders. | Shipped |
| Emergency stop | Pause the main strategy first, then request cancellation of pending orders. | Shipped |
| Position exit | Keep liquidation separate from Emergency stop and describe the distinction. | Shipped copy |
| First-use checklist | Present Connect → Limits → Practice before live mode. | Shipped |

## UX Audit Findings

| Issue | Heuristic | Severity (0-4) | Fix | Status |
|---|---|---:|---|---|
| Live activation could occur after a passive review of limits. | User control and error prevention | 4 | Require a live-order acknowledgment in the review dialog. | Shipped |
| Kill switch could attempt exits while the main strategy remained armed. | Match between system and real world | 4 | Add Emergency stop that pauses the main strategy before cancellation. | Shipped |
| First-time users had no compact route from credentials to practice. | Recognition rather than recall | 3 | Add a three-step start-safely checklist and guide copy. | Shipped |
| Emergency stop cannot guarantee exchange cancellation during an outage. | Visibility of system status | 3 | Return a precise result that distinguishes local pause from cancellation confirmation. | Shipped |

## Microinteraction Inventory

| Interaction | Trigger/Rules/Feedback/Loops | Fix | Status |
|---|---|---|---|
| Enable live trading | Start live → review limits → acknowledge → enable. | Disable the final action until acknowledgment. | Shipped |
| Emergency stop | Press visible top-bar action while main strategy is live. | Button changes to Stopping; result specifies pause and cancellation status. | Shipped |
