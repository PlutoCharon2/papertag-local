# Privacy

Public releases are built from an allowlisted source directory. No user database, API profiles, OAuth credentials, private PDF, AI return, runtime log or machine-specific literature root is shipped.

On your computer the app retains your local database and immutable PDF copies under LocalAppData. Configured API keys are encrypted by Windows DPAPI. Analysis uploads PDF page images to the provider you select, using your own key and quota. The app does not upload data to GitHub automatically.

If reinstalling on a previously used computer shows earlier settings, those are being loaded from the existing local user data folder. They are not embedded in the installer.

Exports, raw model responses and diagnostic logs can contain your paper contents and paths. Inspect them before sharing. Windows account / computer changes may require entering your API key again.
