"""Example tests for the 1-second rate limit (Task 10.6).

These deterministic example tests verify Requirement 9.1: after every Draft
creation *attempt* completes, the Draft_Script waits ``RATE_LIMIT_SECONDS``
(1 second) before moving on to the next Contact_Row. In :func:`outreach_drafts.main`
the pause lives in a ``finally`` clause, so it fires once per processed row
regardless of whether that row succeeded or failed.

To exercise ``main()`` without any network, filesystem, or real delay, we patch
the module-level seams it calls into:

  * ``get_credentials`` / ``build_service`` / ``get_sender_address`` — stubbed so
    the fail-fast setup phase is a no-op and yields a dummy service + sender.
  * ``read_contacts`` — returns a fixed in-memory list of Contact_Rows, so no
    ``contacts.csv`` is touched.
  * ``create_draft`` — returns a dummy draft, so no Gmail API call is made.
  * ``time.sleep`` — replaced with a ``Mock`` so we can assert on its calls
    without waiting.

The chosen rows use the ``Response`` and ``Post-Demo`` Template_Types, whose
Attachment_Set is empty, so ``create_message_with_attachments`` never opens an
image file and no fixture attachments are required.

_Requirements: 9.1_
"""
from unittest import mock

import outreach_drafts


def _valid_row(email, template_type):
    """Build a valid Contact_Row dict with an attachment-free Template_Type."""
    return {
        "Recipient_Email": email,
        "Recipient_Name": "Alex Teacher",
        "Sender_Name": "Jordan Student",
        "School_Name": "Example School",
        "Template_Type": template_type,
    }


def _run_main_with(rows):
    """Run ``main()`` with all external seams patched and return the sleep mock.

    Patches the module attributes ``main()`` depends on so the run is fully
    in-memory and instant: the setup phase is stubbed, ``read_contacts`` yields
    ``rows``, ``create_draft`` returns a dummy, and ``time.sleep`` is a Mock.
    """
    sleep_mock = mock.Mock(name="time.sleep")
    with mock.patch("outreach_drafts.get_credentials", return_value=mock.sentinel.creds), \
         mock.patch("outreach_drafts.build_service", return_value=mock.sentinel.service), \
         mock.patch("outreach_drafts.get_sender_address", return_value="me@circuitrunners.com"), \
         mock.patch("outreach_drafts.read_contacts", return_value=rows), \
         mock.patch("outreach_drafts.create_draft", return_value=mock.sentinel.draft), \
         mock.patch("outreach_drafts.time.sleep", sleep_mock):
        outreach_drafts.main()
    return sleep_mock


def test_sleep_called_once_per_row_with_rate_limit_seconds():
    """main() sleeps exactly once per processed row, each for RATE_LIMIT_SECONDS.

    With three valid, attachment-free rows the run creates three drafts and must
    pause once after each — three sleeps total, every one using the module's
    RATE_LIMIT_SECONDS constant (Req 9.1).
    """
    rows = [
        _valid_row("teacher1@school.org", "Response"),
        _valid_row("teacher2@school.org", "Post-Demo"),
        _valid_row("teacher3@school.org", "Response"),
    ]

    sleep_mock = _run_main_with(rows)

    # One sleep per processed row.
    assert sleep_mock.call_count == len(rows)

    # Every sleep used exactly RATE_LIMIT_SECONDS (the 1-second pause, Req 9.1).
    expected_call = mock.call(outreach_drafts.RATE_LIMIT_SECONDS)
    assert sleep_mock.call_args_list == [expected_call] * len(rows)
    sleep_mock.assert_any_call(outreach_drafts.RATE_LIMIT_SECONDS)


def test_sleep_fires_after_a_failing_row_too():
    """The rate-limit pause fires after every attempt regardless of outcome.

    A mix of valid rows and one row with an invalid Template_Type: the invalid
    row is skipped as a failure before any draft is built, yet the ``finally``
    clause still runs ``time.sleep``. So with N rows total the sleep count is N
    — the failing row is paced exactly like the successful ones (Req 9.1).
    """
    rows = [
        _valid_row("teacher1@school.org", "Response"),
        _valid_row("bad@school.org", "NotARealType"),   # invalid Template_Type -> failure
        _valid_row("teacher3@school.org", "Post-Demo"),
    ]

    sleep_mock = _run_main_with(rows)

    # Sleep fires once for every row, including the failing one (N rows -> N sleeps).
    assert sleep_mock.call_count == len(rows)

    # Each call still used RATE_LIMIT_SECONDS, including the pause after the failure.
    expected_call = mock.call(outreach_drafts.RATE_LIMIT_SECONDS)
    assert sleep_mock.call_args_list == [expected_call] * len(rows)
