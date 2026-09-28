ROM PolyBot 2.36.2 adds in-app updates. After this version is installed, the app checks for new stable releases automatically, downloads the matching installer in the background, and verifies its SHA-256 checksum against the release before offering it. Settings shows the running version, download progress, and clear retry or cancel controls. A user action is required to install, so an update cannot silently stop a running strategy.

On Windows, the app opens the verified installer and closes for installation. On Apple Silicon, it opens the verified DMG for the user to replace the app in Applications. The current Mac release is not signed for seamless in-place replacement. Users on 2.36.1 or earlier need to install 2.36.2 once through the existing release download; later updates can be obtained inside the app.

This release changes update delivery only. It does not change trading rules, place a live order, or establish profitability.
