"""Example tests for the ``drafts.create`` invocation shape (Task 8.2).

These deterministic example tests verify that :func:`outreach_drafts.create_draft`
talks to the Gmail API exactly the way Requirement 8.1 mandates: it creates a
draft through ``users().drafts().create`` with ``userId="me"`` and a request
body of ``{"message": {"raw": ...}}``, executes the request, and returns
whatever the API returns.

They also guard the "draft-only, never send" guarantee (Req 8.2 / Property 8)
at the call-site level: after invoking ``create_draft`` no send operation may
appear anywhere in the mock's recorded call chain. Because a
``unittest.mock.MagicMock`` auto-creates any attribute that is accessed, we
cannot simply assert a ``send`` attribute is absent — accessing it would spring
it into existence. Instead we inspect the recorded ``mock_calls`` and assert
that the substring ``".send("`` never appears in any recorded call, which
proves no ``send`` method was ever *invoked* on the drafts()/messages() chains.

_Requirements: 8.1_
"""
from unittest import mock

import outreach_drafts


def _build_mock_service_with_sentinel_return():
    """Return (mock_service, sentinel) where drafts().create().execute()
    yields ``sentinel`` — a unique object so the test can assert identity."""
    mock_service = mock.MagicMock(name="gmail_service")
    sentinel = mock.sentinel.created_draft
    # Wire the execute() at the end of the drafts().create() chain to return
    # our sentinel so we can assert create_draft passes it straight through.
    mock_service.users().drafts().create().execute.return_value = sentinel
    # Reset the recorded calls made while wiring the return value above so the
    # assertions below only observe calls made by create_draft itself.
    mock_service.reset_mock()
    return mock_service, sentinel


def test_create_draft_invocation_shape_and_return():
    """create_draft calls users().drafts().create with the exact userId/body,
    executes it, and returns the API's return value unchanged (Req 8.1)."""
    mock_service, sentinel = _build_mock_service_with_sentinel_return()

    result = outreach_drafts.create_draft(mock_service, {"raw": "abc"})

    # The create() call must use userId="me" and nest the message under
    # "message" as {"message": {"raw": "abc"}} (Req 8.1).
    mock_service.users().drafts().create.assert_called_once_with(
        userId="me",
        body={"message": {"raw": "abc"}},
    )

    # The request must actually be executed.
    mock_service.users().drafts().create().execute.assert_called_once_with()

    # create_draft returns exactly what the API's execute() returned.
    assert result is sentinel


def test_create_draft_never_invokes_a_send_operation():
    """No Gmail send operation is invoked anywhere in the call chain (Req 8.2).

    A MagicMock auto-creates attributes on access, so we cannot assert a
    ``send`` attribute is absent. Instead we assert that no recorded call on
    the service — the full ``mock_calls`` chain — contains the ``.send(``
    invocation marker. This proves neither ``users().messages().send`` nor
    ``users().drafts().send`` was ever called.
    """
    mock_service, _ = _build_mock_service_with_sentinel_return()

    outreach_drafts.create_draft(mock_service, {"raw": "abc"})

    # Robust across the whole recorded call chain: stringify every recorded
    # call and confirm none of them represents a ``.send(`` invocation.
    recorded_calls = [str(call) for call in mock_service.mock_calls]
    assert all(".send(" not in call for call in recorded_calls), (
        "create_draft must never invoke a send operation; "
        f"recorded calls were: {recorded_calls}"
    )

    # Explicit, readable belt-and-suspenders checks for the two named send
    # paths. Asserting *not called* still auto-creates the attribute, but that
    # is harmless: it records no call, and the substring check above is the
    # authoritative guard that nothing was actually invoked.
    mock_service.users().messages().send.assert_not_called()
    mock_service.users().drafts().send.assert_not_called()
