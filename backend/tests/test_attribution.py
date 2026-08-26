"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.

Attribution is asserted, not merely written.

A copied repository that strips the author's name now fails its own test suite,
which turns silent removal into a visible act. This is not a technical control -
the tests can be deleted too - but deleting them is one more thing a copier has
to do deliberately, and one more thing that shows up in a diff.

The import smoke test earns its place separately: nothing else in the suite
imports app.main, so a syntax error in the application entry point could
otherwise pass a fully green run.
"""

import io
import pathlib

import pytest

from app import __about__

REPO = pathlib.Path(__file__).resolve().parents[2]
AUTHOR = "Rahul Hongekar"
HANDLE = "RahulH007"


def test_about_names_the_author():
    assert __about__.AUTHOR == AUTHOR
    assert __about__.AUTHOR_GITHUB == HANDLE
    assert HANDLE in __about__.PROJECT_URL
    assert AUTHOR in __about__.NOTICE
    assert AUTHOR in __about__.banner()


def test_api_surfaces_carry_attribution():
    payload = __about__.as_dict()
    assert payload["author"] == AUTHOR
    assert payload["github"] == HANDLE


@pytest.mark.parametrize("relative", [
    "README.md",
    "NOTICE.md",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/src/components/UI/AttributionFooter.jsx",
])
def test_reviewer_facing_files_name_the_author(relative):
    path = REPO / relative
    assert path.exists(), f"{relative} is missing"
    assert AUTHOR in io.open(path, encoding="utf-8").read(), (
        f"{relative} no longer names the author"
    )


def test_every_backend_module_carries_the_header():
    missing = [
        str(path.relative_to(REPO))
        for path in (REPO / "backend" / "app").rglob("*.py")
        if "__pycache__" not in str(path)
        and HANDLE not in io.open(path, encoding="utf-8").read()
    ]
    assert missing == [], f"Modules without attribution: {missing}"


def test_application_entry_point_imports():
    """Nothing else in the suite imports app.main, so a break here is silent."""
    import app.main  # noqa: F401

    assert app.main.app.title == "RecoverOS API"
    assert app.main.app.contact["name"] == AUTHOR
