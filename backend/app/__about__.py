"""
Authorship and provenance for RecoverOS.

Single source of truth: every place the project names its author - the API
banner, the CLI receipts, the dashboard footer - reads these constants rather
than repeating the string, so attribution cannot drift out of sync in one
surface while staying correct in another.

Note on what this does and does not do. A copied repository can strip these
lines in a minute; they are not a technical control. What they provide is
notice: an unmodified copy is instantly identifiable, and a modified one shows
deliberate removal of authorship. The durable evidence of origin is the public
commit history at the URL below.
"""

AUTHOR = "Rahul Hongekar"
AUTHOR_GITHUB = "RahulH007"
AUTHOR_GITHUB_URL = "https://github.com/RahulH007"
PROJECT = "RecoverOS"
PROJECT_URL = "https://github.com/RahulH007/RazorPay_Buildathon"
EVENT = "Razorpay Buildathon, Track 03"
VERSION = "1.0.0"

ATTRIBUTION = f"{PROJECT} - built by {AUTHOR} (github.com/{AUTHOR_GITHUB})"
NOTICE = (
    f"{PROJECT} is the original work of {AUTHOR} ({AUTHOR_GITHUB_URL}), "
    f"submitted to the {EVENT}."
)


def banner() -> str:
    """One-line attribution for CLI receipts."""
    return f"{ATTRIBUTION} | {EVENT}"


def as_dict() -> dict:
    """Attribution block for API responses."""
    return {
        "project": PROJECT,
        "author": AUTHOR,
        "github": AUTHOR_GITHUB,
        "github_url": AUTHOR_GITHUB_URL,
        "repository": PROJECT_URL,
        "event": EVENT,
        "version": VERSION,
    }
