# ROM Polybot credentials

The app stores Polymarket US API credentials locally. Windows uses DPAPI tied to
the signed-in Windows account. Other platforms use an OS keychain when available.
The secret is never returned through the renderer credential-status interface.

Connection tests read balances and never submit orders. Revoke compromised keys
from the Polymarket US developer portal. Do not include keys in logs or bug reports.
