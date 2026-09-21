"""Property-based test for skip-and-continue on row-level failures (Task 10.2).

Feature: gmail-outreach-drafts, Property 7: Row-level failures are skipped and
the run continues. For any set of Contact_Rows in which some rows fail
(missing/empty required field, invalid Template_Type, or API error/timeout on
draft creation), the failing rows do NOT produce a draft and are recorded as
failures, while every non-failing row is still processed and the run does not
terminate early.

Validates: Requirements 2.4, 2.5, 7.7, 10.1, 10.2

Strategy
--------
Hypothesis generates a mixed list of rows. Each row is one of four kinds:

  * "valid"   — all required fields present, Template_Type in {Response,
                Post-Demo} so the Attachment_Set is empty and no real image
                files are needed. Its ``create_draft`` succeeds.
  * "api"     — a fully valid row (Response/Post-Demo) whose ``create_draft``
                is made to raise a Gmail API-style error deterministically.
                Flagged by a sentinel Recipient_Email so the ``create_draft``
                stub knows to raise for it (Req 10.1).
  * "bad_tt"  — all fields present but an invalid Template_Type, so
                ``validate_row`` rejects it before any message is built
                (Req 2.5). ``create_draft`` must NOT be called for it.
  * "missing" — a required field is blank/whitespace, so ``validate_row``
                rejects it before any message is built (Req 2.4).
                ``create_draft`` must NOT be called for it.

The module attributes ``get_credentials``, ``build_service``,
``get_sender_address``, ``read_contacts``, ``create_draft`` and ``time.sleep``
are patched so ``main()`` runs entirely against fakes with no OAuth, no live
Gmail, and no real delay. Only Response/Post-Demo templates are used for valid
rows, so ``ATTACHMENTS_DIR`` never needs real files.

Assertions after ``main()``:
  * The run completes without raising out of ``main()`` (no early abort).
  * ``create_draft`` is never called for the invalid-Template_Type or
    missing-field rows (they are skipped before message build).
  * ``create_draft`` IS called for every valid non-API-failing row.
  * The printed Run_Summary (captured via redirect_stdout) reports "Successful drafts"
    equal to the number of valid non-API rows, "Failed / skipped rows" equal
    to the number of failing rows (bad_tt + missing + api), and a total equal
    to len(rows).
"""
import contextlib
import io
from unittest import mock

from hypothesis import given, settings, strategies as st

import outreach_drafts


# A sentinel embedded in the Recipient_Email of API-failing rows so the
# create_draft stub can recognize them deterministically and raise.
_API_FAIL_MARKER = "apifail"

# Template types whose Attachment_Set is empty, so building the message needs
# no real files on disk.
_NO_ATTACHMENT_TYPES = ["Response", "Post-Demo"]


# --------------------------------------------------------------------------
# Row generators — each produces (row_dict, kind) so the test can compute the
# expected outcome for that row independently of main().
# --------------------------------------------------------------------------
def _valid_row(index, template_type, api_fail):
    """Build a fully valid Contact_Row (Response/Post-Demo, no attachments).

    When ``api_fail`` is True the Recipient_Email carries the sentinel marker so
    the create_draft stub raises for it.
    """
    marker = f"{_API_FAIL_MARKER}." if api_fail else ""
    return {
        "Recipient_Email": f"{marker}person{index}@example.com",
        "Recipient_Name": f"Recipient {index}",
        "Sender_Name": f"Sender {index}",
        "School_Name": f"School {index}",
        "Template_Type": template_type,
    }


def _bad_template_type_row(index):
    """A row with every field present but an invalid Template_Type (Req 2.5)."""
    return {
        "Recipient_Email": f"badtt{index}@example.com",
        "Recipient_Name": f"Recipient {index}",
        "Sender_Name": f"Sender {index}",
        "School_Name": f"School {index}",
        "Template_Type": "Bogus",
    }


def _missing_field_row(index, blank_value):
    """A row missing a required field via a blank/whitespace value (Req 2.4)."""
    row = {
        "Recipient_Email": f"missing{index}@example.com",
        "Recipient_Name": f"Recipient {index}",
        "Sender_Name": f"Sender {index}",
        "School_Name": f"School {index}",
        "Template_Type": "Response",
    }
    # Blank out one required field (not Recipient_Email, so the row still has a
    # usable identifier for logging). validate_row treats empty/whitespace as
    # missing (Req 2.4).
    row["School_Name"] = blank_value
    return row


# A single-row strategy that yields (row, kind). "valid" and "api" rows pick a
# no-attachment template type; "missing" rows pick a whitespace/empty blank.
def _row_strategy():
    valid = st.tuples(
        st.sampled_from(_NO_ATTACHMENT_TYPES),
    ).map(lambda t: ("valid", t[0], None))

    api = st.tuples(
        st.sampled_from(_NO_ATTACHMENT_TYPES),
    ).map(lambda t: ("api", t[0], None))

    bad_tt = st.just(("bad_tt", None, None))

    missing = st.sampled_from(["", " ", "   ", "\t", "\n", " \t \n "]).map(
        lambda blank: ("missing", None, blank)
    )

    return st.one_of(valid, api, bad_tt, missing)


def _make_api_error():
    """Build a Gmail HttpError-like exception the create_draft stub can raise.

    Uses the real HttpError type so main()'s ``except HttpError`` branch is the
    one exercised (Req 10.1). HttpError construction needs a response object
    with a ``status`` and content bytes; a minimal fake response suffices.
    """
    fake_resp = mock.Mock()
    fake_resp.status = 500
    fake_resp.reason = "Internal Server Error"
    return outreach_drafts.HttpError(resp=fake_resp, content=b"simulated API error")


@settings(max_examples=100, deadline=None)
@given(specs=st.lists(_row_strategy(), min_size=1, max_size=25))
def test_row_level_failures_are_skipped_and_run_continues(specs):
    """Feature: gmail-outreach-drafts, Property 7

    A mix of valid, API-failing, invalid-Template_Type, and missing-field rows
    is processed by main(): failing rows create no draft and are counted as
    failures, valid rows are still processed, and the run does not abort.
    Validates: Requirements 2.4, 2.5, 7.7, 10.1, 10.2
    """
    # Materialize the generated specs into concrete rows and track, per row,
    # the expected outcome so assertions do not depend on main() internals.
    rows = []
    expected_draft_emails = set()   # emails create_draft SHOULD be called with
    forbidden_draft_emails = set()  # emails create_draft must NEVER see (skipped pre-build)
    api_fail_emails = set()         # emails whose create_draft must raise

    successes_expected = 0
    failures_expected = 0

    for index, (kind, template_type, blank) in enumerate(specs, start=1):
        if kind == "valid":
            row = _valid_row(index, template_type, api_fail=False)
            rows.append(row)
            expected_draft_emails.add(row["Recipient_Email"])
            successes_expected += 1
        elif kind == "api":
            row = _valid_row(index, template_type, api_fail=True)
            rows.append(row)
            # A valid row reaches create_draft, so the draft IS attempted for
            # its email — but the stub raises, so it is counted as a failure.
            expected_draft_emails.add(row["Recipient_Email"])
            api_fail_emails.add(row["Recipient_Email"])
            failures_expected += 1
        elif kind == "bad_tt":
            row = _bad_template_type_row(index)
            rows.append(row)
            forbidden_draft_emails.add(row["Recipient_Email"])
            failures_expected += 1
        else:  # "missing"
            row = _missing_field_row(index, blank)
            rows.append(row)
            forbidden_draft_emails.add(row["Recipient_Email"])
            failures_expected += 1

    total_expected = len(rows)
    assert successes_expected + failures_expected == total_expected

    # Record every email create_draft is invoked with, and raise deterministically
    # for the API-failing rows. main() calls create_draft(service, message) where
    # message is {"raw": ...}; we decode the To header out of the raw MIME to know
    # which row it was, without depending on argument order beyond the message.
    seen_draft_emails = []

    def fake_create_draft(service, message_body):
        to_addr = _extract_to_header(message_body)
        seen_draft_emails.append(to_addr)
        if to_addr in api_fail_emails:
            raise _make_api_error()
        return {"id": f"draft-for-{to_addr}", "message": message_body}

    with mock.patch.object(outreach_drafts, "get_credentials", return_value=mock.sentinel.creds), \
         mock.patch.object(outreach_drafts, "build_service", return_value=mock.MagicMock(name="service")), \
         mock.patch.object(outreach_drafts, "get_sender_address", return_value="me@x.com"), \
         mock.patch.object(outreach_drafts, "read_contacts", return_value=rows), \
         mock.patch.object(outreach_drafts, "create_draft", side_effect=fake_create_draft) as create_draft_mock, \
         mock.patch.object(outreach_drafts.time, "sleep", return_value=None) as sleep_mock:
        # The run must NOT raise out of main(): row-level failures are contained.
        # Capture stdout with redirect_stdout rather than the capsys fixture: a
        # function-scoped fixture is not reset between Hypothesis examples, so
        # capturing locally per example keeps each run's summary isolated.
        stdout_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer):
            outreach_drafts.main()

    seen_set = set(seen_draft_emails)

    # create_draft must never be called for rows skipped before message build:
    # invalid Template_Type (Req 2.5) and missing required field (Req 2.4).
    for email in forbidden_draft_emails:
        assert email not in seen_set, (
            f"create_draft was called for a row that should have been skipped: {email}"
        )

    # create_draft must be called for every valid (including API-failing) row,
    # since those pass validation and reach the draft step.
    for email in expected_draft_emails:
        assert email in seen_set, (
            f"create_draft was NOT called for a valid row: {email}"
        )

    # Each valid/API row triggers exactly one create_draft call (no duplicates,
    # no calls for skipped rows) — total calls equal the number of valid+api rows.
    assert create_draft_mock.call_count == len(expected_draft_emails)

    # time.sleep runs in a finally after EVERY processed row, so it is called
    # once per row regardless of outcome (Req 9.1) — confirms the loop iterated
    # over all rows without aborting early.
    assert sleep_mock.call_count == total_expected

    # The Run_Summary (printed to stdout) reports the conserved counts. Since
    # main() returns no counts, parse them from the captured output.
    out = stdout_buffer.getvalue()
    successful, failed, total = _parse_run_summary(out)

    assert successful == successes_expected, (
        f"expected {successes_expected} successful drafts, summary said {successful}"
    )
    assert failed == failures_expected, (
        f"expected {failures_expected} failed/skipped rows, summary said {failed}"
    )
    assert total == total_expected, (
        f"expected total {total_expected}, summary said {total}"
    )
    # Counts conserve the total (successes + failures == total).
    assert successful + failed == total


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _extract_to_header(message_body):
    """Decode the base64url {'raw': ...} message and return its To header."""
    import base64
    import email as email_mod

    raw = message_body["raw"]
    parsed = email_mod.message_from_bytes(base64.urlsafe_b64decode(raw))
    return parsed["To"]


def _parse_run_summary(output):
    """Extract (successful, failed, total) integers from the Run_Summary text.

    The Run_Summary format printed by main() is:
        === Run Summary ===
        Successful drafts: <n>
        Failed / skipped rows: <n>
        Total contacts processed: <n>
    """
    successful = failed = total = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Successful drafts:"):
            successful = int(line.split(":", 1)[1].strip())
        elif line.startswith("Failed / skipped rows:"):
            failed = int(line.split(":", 1)[1].strip())
        elif line.startswith("Total contacts processed:"):
            total = int(line.split(":", 1)[1].strip())
    assert successful is not None, f"no 'Successful drafts' line in summary:\n{output}"
    assert failed is not None, f"no 'Failed / skipped rows' line in summary:\n{output}"
    assert total is not None, f"no 'Total contacts processed' line in summary:\n{output}"
    return successful, failed, total
