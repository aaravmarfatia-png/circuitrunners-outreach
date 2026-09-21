"""Scaffold sanity tests.

Confirms the project structure exists and the test framework (pytest +
hypothesis) is wired up. Implementation-specific tests are added by later tasks.
"""
import os

from hypothesis import given, strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*parts):
    return os.path.join(PROJECT_ROOT, *parts)


def test_core_files_exist():
    for name in ("outreach_drafts.py", "requirements.txt", "contacts.csv", "README.md"):
        assert os.path.isfile(_path(name)), f"missing {name}"


def test_attachments_present():
    for name in ("robot-demo1.jpg", "robot-demo2.jpg", "robot-demo3.jpg", "robot-demo5.jpg"):
        p = _path("attachments", name)
        assert os.path.isfile(p), f"missing attachment {name}"
        assert os.path.getsize(p) > 0, f"empty attachment {name}"


def test_requirements_list_google_deps():
    with open(_path("requirements.txt"), encoding="utf-8") as f:
        text = f.read()
    assert "google-api-python-client" in text
    assert "google-auth-oauthlib" in text


def test_contacts_header_row():
    with open(_path("contacts.csv"), encoding="utf-8") as f:
        header = f.readline().strip()
    assert header == "Recipient_Email,Recipient_Name,Sender_Name,School_Name,Template_Type"


def test_module_importable():
    import outreach_drafts  # noqa: F401


@given(st.integers())
def test_hypothesis_is_available(n):
    # Trivial property to confirm hypothesis runs.
    assert n + 0 == n
