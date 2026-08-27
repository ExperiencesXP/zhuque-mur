# SPDX ids from GitHub's license API, grouped by how they affect a clean-room run.

PERMISSIVE = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSD-3-Clause-Clear",
    "ISC",
    "Unlicense",
    "0BSD",
    "CC0-1.0",
    "WTFPL",
    "Zlib",
    "BSL-1.0",
    "NCSA",
    "PostgreSQL",
    "Python-2.0",
    "MIT-0",
}

WEAK_COPYLEFT = {
    "MPL-2.0",
    "LGPL-2.1",
    "LGPL-3.0",
    "EPL-1.0",
    "EPL-2.0",
    "CPL-1.0",
    "CDDL-1.0",
}

STRONG_COPYLEFT = {
    "GPL-2.0",
    "GPL-3.0",
    "AGPL-3.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
}

NO_LICENSE = {"NOASSERTION", "NONE", "OTHER", ""}

VERDICT_PERMISSIVE = "permissive"
VERDICT_WEAK = "weak-copyleft"
VERDICT_STRONG = "strong-copyleft"
VERDICT_NONE = "no-license"
VERDICT_UNKNOWN = "unknown"


def classify(spdx_id: str | None) -> str:
    key = (spdx_id or "").strip()
    if key in PERMISSIVE:
        return VERDICT_PERMISSIVE
    if key in WEAK_COPYLEFT:
        return VERDICT_WEAK
    if key in STRONG_COPYLEFT:
        return VERDICT_STRONG
    if key in NO_LICENSE or not key:
        return VERDICT_NONE
    return VERDICT_UNKNOWN


def may_proceed(verdict: str) -> bool:
    """Whether the tool may continue after an explicit human confirmation.

    no-license still requires a stronger confirmation in the command layer.
    """
    return verdict in {
        VERDICT_PERMISSIVE,
        VERDICT_WEAK,
        VERDICT_STRONG,
        VERDICT_UNKNOWN,
        VERDICT_NONE,
    }
