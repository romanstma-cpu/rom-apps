ROM PolyBot 2.36.3 adds a persistent, bounded decision history to the Overview. It shows the markets currently watched, recent signal activity, the most common reasons candidates stopped, and the stage and reason for each recent candidate. Practice fills, submitted live orders, submission failures, and later position status are labeled separately, so a submitted order is never presented as a confirmed fill.

The journal records diagnostic market identifiers and gate explanations, not API credentials or order payloads. Repeated identical cycle-wide blockers are saved once per minute; individual candidate decisions are saved as they occur. The history survives a restart and keeps the latest 25,000 decisions for up to seven days.

This release changes observability only. It does not relax entry or risk gates, place a live order during validation, or establish that the strategy is profitable. Practice was validated with zero live buying power.
