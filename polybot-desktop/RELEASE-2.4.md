# ROM Polybot 2.4

The main strategy now has a dedicated Practice mode. It uses the same current signal filters, conflict checks, two-sided quote requirements, entry-price checks, sizing and portfolio limits as the live decision path. Practice and Live modes are mutually exclusive, and a practice decision never calls the exchange order API.

Practice entries use the selected limit price plus a disclosed 1-cent-per-contract cost allowance. They are recorded as practice rows, use an isolated virtual bankroll and exposure budget, and resolve against the recorded market outcome. The Positions page has a separate Practice tab, while live History and Evidence continue to exclude practice performance. These fills are estimates, not exchange fills, and they do not account for missed or partial fills.

Overview now reports what the main strategy is actually doing: Paused, Scanning, Waiting or Blocked. It includes a plain-language reason, the age of the last decision cycle, recent candidate counts and the leading rejection reasons. When Practice is active, it also shows available virtual funds, resolved P&L, and open and resolved practice counts.

Practice requires the Polymarket US API connection so the app can use current account and market data. Real trading still requires a separate explicit confirmation. Existing settings are preserved and real trading remains paused by default.

Practice results do not establish profitability. Signal confidence remains heuristic, simulated fill assumptions can differ materially from live execution, and users should review a substantial independent sample before considering real orders.
