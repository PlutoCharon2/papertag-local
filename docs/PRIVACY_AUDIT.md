# Public release privacy check

The allowlisted source and built application distribution were inspected for known owner-specific paths, credential-like literals, user databases, PDFs, model response files, account profiles and runtime logs. Compiled Python modules were decompressed and their filenames / constants inspected. No matches were found in this public build.

No real credential was read for this check. A pattern scan is not a formal guarantee against every possible secret; the stronger control is that all runtime data and private reports are excluded from the public source and build input.

A clean-profile launch must show no registered papers / paths and no configured API keys. Reinstallation on an existing profile may reuse that computer's local data.
