"""Property-based test for Property 8 — the tool never sends mail (Task 10.3).

Feature: gmail-outreach-drafts, Property 8: No send operation is ever invoked.

*For any* run over any set of Contact_Rows, the script SHALL invoke only the
``users.drafts.create`` operation and SHALL never invoke any Gmail send
operation (``users.messages.send`` or ``users.drafts.send``), and the requested
OAuth scope SHALL contain no send capability.

**Validates: Requirements 3.1, 8.1, 8.2**

Strategy
--------
Hypothesis generates a list of valid Contact_Rows with varied Template_Types
(Elementary, Middle, Response, Post-Demo) and non-empty personalization fields.
Elementary and Middle carry image attachments, so ``ATTACHMENTS_DIR`` is
monkeypatched to the project's real ``attachments/`` folder for the duration of
each example, guaranteeing every referenced image resolves and no row is skipped
for a missing file. ``main()`` is then driven end to end against a mocked Gmail
service:

  * ``outreach_drafts.get_credentials`` returns a dummy sentinel,
  * ``outreach_drafts.build_service`` returns a fresh ``MagicMock`` service,
  * ``outreach_drafts.get_sender_address`` returns a fixed sender address,
  * ``outreach_drafts.read_contacts`` returns the generated rows,
  * ``outreach_drafts.time.sleep`` is a no-op so the 1-second per-row pause does
    not slow the run.

After ``main()`` returns, every call recorded on the mock service is inspected:
no recorded call may contain the ``.send(`` invocation marker (neither
``users().messages().send`` nor ``users().drafts().send``), and the only
``create`` invocation used must be ``users().drafts().create``. Finally the
module's ``SCOPES`` constant is asserted to carry no send capability.
"""
import os
from unittest import mock

import pytest
from hypothesis import given, settings, strategies as st

import outreach_drafts


# Real attachments folder that ships with the project. Elementary/Middle rows
# reference image files here, so pointing ATTACHMENTS_DIR at it lets every
# attachment resolve and keeps all rows on the draft-creation path.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_ATTACHMENTS_DIR = os.path.join(PROJECT_ROOT, "attachments")

# The four valid Template_Types drive template + attachment selection.
TEMPLATE_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]

# Non-empty text for the personalization fields (avoids whitespace-only values
# that validate_row would reject, so no row is skipped for that reason).
_nonempty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")


@st.composite
def contact_rows(draw):
    """Generate a list of valid Contact_Rows spanning all Template_Types."""
    count = draw(st.integers(min_value=1, max_value=6))
    rows = []
    for _ in range(count):
        rows.append(
            {
                "Recipient_Email": draw(_nonempty_text),
                "Recipient_Name": draw(_nonempty_text),
                "Sender_Name": draw(_nonempty_text),
                "School_Name": draw(_nonempty_text),
                "Template_Type": draw(st.sampled_from(TEMPLATE_TYPES)),
            }
        )
    return rows


@settings(max_examples=100, deadline=None)
@given(rows=contact_rows())
def test_main_never_invokes_a_send_operation(rows):
    """Feature: gmail-outreach-drafts, Property 8.

    Over any set of Contact_Rows, main() only ever invokes
    users().drafts().create and never any send operation, and SCOPES carries no
    send capability (Req 3.1, 8.1, 8.2).
    """
    # A fresh mock Gmail service records every call made during the run.
    mock_service = mock.MagicMock(name="gmail_service")

    # Use MonkeyPatch as a context manager (rather than the function-scoped
    # pytest fixture) so every patch is applied and undone per generated input,
    # which is the Hypothesis-safe way to combine patching with @given.
    with pytest.MonkeyPatch.context() as monkeypatch:
        # Point ATTACHMENTS_DIR at the real folder so Elementary/Middle image
        # files resolve and every generated row reaches the draft-creation call.
        monkeypatch.setattr(outreach_drafts, "ATTACHMENTS_DIR", REAL_ATTACHMENTS_DIR)

        monkeypatch.setattr(
            outreach_drafts, "get_credentials", lambda: mock.sentinel.creds
        )
        monkeypatch.setattr(
            outreach_drafts, "build_service", lambda creds: mock_service
        )
        monkeypatch.setattr(
            outreach_drafts, "get_sender_address", lambda service: "me@circuitrunners.com"
        )
        monkeypatch.setattr(
            outreach_drafts, "read_contacts", lambda path: rows
        )
        # No real sleeping between rows.
        monkeypatch.setattr(outreach_drafts.time, "sleep", lambda seconds: None)

        outreach_drafts.main()

    # Inspect every call recorded on the mock service. Stringifying the whole
    # mock_calls chain and asserting ".send(" never appears proves neither
    # users().messages().send nor users().drafts().send was ever invoked
    # (Req 8.2). A MagicMock auto-creates attributes on access, so checking the
    # recorded *invocations* — not attribute presence — is the authoritative
    # guard.
    recorded_calls = [str(call) for call in mock_service.mock_calls]
    assert all(".send(" not in call for call in recorded_calls), (
        "main() must never invoke a send operation; "
        f"recorded calls were: {recorded_calls}"
    )

    # The only create() operation used anywhere must be users().drafts().create
    # (Req 8.1). Any recorded ".create(" invocation must be preceded by
    # ".drafts(" in the same call chain — never ".messages().create(".
    create_calls = [call for call in recorded_calls if ".create(" in call]
    assert all(".drafts().create(" in call for call in create_calls), (
        "the only create operation may be users().drafts().create; "
        f"recorded create calls were: {create_calls}"
    )

    # Belt-and-suspenders: the named send paths were never called. (Asserting
    # not-called auto-creates the attribute but records no invocation, so the
    # substring guard above remains authoritative.)
    mock_service.users().messages().send.assert_not_called()
    mock_service.users().drafts().send.assert_not_called()

    # The requested OAuth scope must grant no send capability: no scope string
    # may reference a Gmail send scope. The draft-only "gmail.compose" scope is
    # allowed (Req 3.1).
    for scope in outreach_drafts.SCOPES:
        assert "gmail.send" not in scope, (
            f"SCOPES must not request send capability; found send scope: {scope}"
        )
        # The full-mailbox scope ("https://mail.google.com/") also implies send;
        # reject it too.
        assert scope != "https://mail.google.com/", (
            "SCOPES must not request the full-mailbox scope, which permits sending"
        )
