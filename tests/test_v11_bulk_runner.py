"""Property-based and example tests for the v1.1 bulk runner and safety guards.

Covers spec ``outreach-app-v1-1`` tasks 6.4-6.8:

  * Task 6.4 — Property 1: Bulk accounting conservation
  * Task 6.5 — Property 3: Override bypasses the duplicate check
  * Task 6.6 — Property 15: No send operation is ever invoked
  * Task 6.7 — Property 13: Every draft CCs the fixed coordinators
  * Task 6.8 — Example: duplicate-skip + bulk Post-Demo zero-photo branches

All Gmail interactions are mocked, ``time.sleep`` is mocked (``sleep=Mock()``
is passed to ``run_bulk``), and no test ever sends mail. Per-row outcomes are
forced deterministically by patching ``outreach_drafts.create_draft`` and
``outreach_drafts.find_duplicate_draft`` with ``mock.patch.object``. Tests use a
trivial ``attachments_for=lambda row: []`` so no real image files are touched.
"""
import base64
import email
from email.header import decode_header, make_header
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts


# ---------------------------------------------------------------------------
# Shared helpers and generators
# ---------------------------------------------------------------------------
# The four valid Template_Types.
_VALID_TEMPLATE_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]

# Non-empty text (no control chars / surrogates, and not whitespace-only) for
# personalization fields so validate_row does not reject a row we intend to be
# valid.
_nonempty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# A simple well-formed single address so validate_row / build both succeed.
_local_part = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_",
    min_size=1,
    max_size=16,
).filter(lambda s: not s.startswith(".") and not s.endswith("."))
_email = _local_part.map(lambda local: f"{local}@example.com")


# A row "kind" tag drives how each generated row is meant to resolve, so the
# test can force the matching per-row outcome deterministically.
#   "valid"      -> create succeeds
#   "validation" -> bad Template_Type or blank required field (validate_row fails)
#   "duplicate"  -> find_duplicate_draft True, override off -> skipped
#   "create_fail"-> create_draft raises -> failed
_ROW_KINDS = ["valid", "validation", "duplicate", "create_fail"]


@st.composite
def tagged_rows(draw):
    """Generate a list of ``(kind, row)`` pairs mixing all four row kinds."""
    count = draw(st.integers(min_value=0, max_value=6))
    pairs = []
    for _ in range(count):
        kind = draw(st.sampled_from(_ROW_KINDS))
        row = {
            "Recipient_Email": draw(_email),
            "Recipient_Name": draw(_nonempty_text),
            "Sender_Name": draw(_nonempty_text),
            "School_Name": draw(_nonempty_text),
            "Template_Type": draw(st.sampled_from(_VALID_TEMPLATE_TYPES)),
        }
        if kind == "validation":
            # Make the row fail validate_row: either a bad Template_Type or a
            # blank required field.
            if draw(st.booleans()):
                row["Template_Type"] = draw(
                    st.text(max_size=10).filter(
                        lambda s: s not in outreach_drafts.TEMPLATES
                    )
                )
            else:
                row[draw(st.sampled_from(
                    ["Recipient_Name", "Sender_Name", "School_Name"]
                ))] = draw(st.sampled_from(["", "   ", "\t"]))
        pairs.append((kind, row))
    return pairs


def _no_attachments(row):
    """An attachments_for callable that never touches the filesystem."""
    return []


def _decode_raw(message_dict):
    """Decode a {'raw': ...} message dict into a parsed email.message.Message."""
    decoded_bytes = base64.urlsafe_b64decode(message_dict["raw"])
    return email.message_from_bytes(decoded_bytes)


def _decoded_header(parsed, name):
    """Return a header with any RFC 2047 encoded-words decoded back to unicode."""
    raw = parsed[name]
    if raw is None:
        return None
    return str(make_header(decode_header(raw)))


# ===========================================================================
# Task 6.4 — Property 1: Bulk accounting conservation
# ===========================================================================
@settings(max_examples=100, deadline=None)
@given(pairs=tagged_rows())
def test_bulk_accounting_conservation(pairs):
    """Feature: outreach-app-v1-1, Property 1

    For any mix of valid rows, validation failures, duplicates, and
    create-failures, run_bulk returns exactly one BulkResult per input row, each
    outcome is in {success, skipped, failed}, and
    successes + skipped + failed == total == len(rows).
    Validates: Requirements 1.3, 1.5, 1.6, 1.7, 1.8, 11.4
    """
    rows = [row for _kind, row in pairs]

    # A duplicate row is one whose kind is "duplicate"; find_duplicate_draft
    # should report True only for those recipients (override is off here).
    duplicate_emails = {
        row["Recipient_Email"].strip()
        for kind, row in pairs
        if kind == "duplicate"
    }
    # Rows whose create call must raise (kind == "create_fail"). Keyed by the
    # rendered recipient so the fake create can decide by message content.
    create_fail_emails = {
        row["Recipient_Email"].strip()
        for kind, row in pairs
        if kind == "create_fail"
    }

    def fake_find_duplicate(service, recipient_email, subject):
        return recipient_email.strip() in duplicate_emails

    def fake_create_draft(service, message_body):
        parsed = _decode_raw(message_body)
        to = (_decoded_header(parsed, "To") or "").strip()
        if to in create_fail_emails:
            raise RuntimeError("boom: simulated create failure")
        return {"id": "draft-123"}

    mock_service = mock.MagicMock(name="gmail_service")

    with mock.patch.object(
        outreach_drafts, "find_duplicate_draft", side_effect=fake_find_duplicate
    ), mock.patch.object(
        outreach_drafts, "create_draft", side_effect=fake_create_draft
    ):
        results = outreach_drafts.run_bulk(
            rows,
            service=mock_service,
            sender="me@circuitrunners.com",
            override=False,
            attachments_for=_no_attachments,
            sleep=mock.Mock(),
        )

    # One BulkResult per input row.
    assert len(results) == len(rows)

    # Every outcome is one of the three allowed values.
    for result in results:
        assert result.outcome in {"success", "skipped", "failed"}

    successes = sum(1 for r in results if r.outcome == "success")
    skipped = sum(1 for r in results if r.outcome == "skipped")
    failed = sum(1 for r in results if r.outcome == "failed")

    # Accounting conservation: the three buckets partition the total.
    total = len(rows)
    assert successes + skipped + failed == total == len(results)


# ===========================================================================
# Task 6.5 — Property 3: Override bypasses the duplicate check
# ===========================================================================
@st.composite
def valid_rows(draw):
    """Generate a list of fully valid Contact_Rows (all fields non-empty)."""
    count = draw(st.integers(min_value=1, max_value=6))
    rows = []
    for _ in range(count):
        rows.append(
            {
                "Recipient_Email": draw(_email),
                "Recipient_Name": draw(_nonempty_text),
                "Sender_Name": draw(_nonempty_text),
                "School_Name": draw(_nonempty_text),
                "Template_Type": draw(st.sampled_from(_VALID_TEMPLATE_TYPES)),
            }
        )
    return rows


@settings(max_examples=100, deadline=None)
@given(rows=valid_rows())
def test_override_bypasses_duplicate_check(rows):
    """Feature: outreach-app-v1-1, Property 3

    With override enabled, run_bulk never queries for a duplicate and invokes
    the create path exactly once per valid row.
    Validates: Requirements 4.3, 4.4
    """
    mock_service = mock.MagicMock(name="gmail_service")
    duplicate_mock = mock.Mock(name="find_duplicate_draft", return_value=True)
    create_mock = mock.Mock(name="create_draft", return_value={"id": "draft-1"})

    with mock.patch.object(
        outreach_drafts, "find_duplicate_draft", duplicate_mock
    ), mock.patch.object(
        outreach_drafts, "create_draft", create_mock
    ):
        results = outreach_drafts.run_bulk(
            rows,
            service=mock_service,
            sender="me@circuitrunners.com",
            override=True,
            attachments_for=_no_attachments,
            sleep=mock.Mock(),
        )

    # The duplicate check is never consulted when override is on.
    duplicate_mock.assert_not_called()

    # Every valid row succeeded, and create was invoked exactly once per row.
    assert all(r.outcome == "success" for r in results)
    assert create_mock.call_count == len(rows)


# ===========================================================================
# Task 6.6 — Property 15: No send operation is ever invoked
# ===========================================================================
@settings(max_examples=100, deadline=None)
@given(pairs=tagged_rows())
def test_no_send_operation_ever_invoked(pairs):
    """Feature: outreach-app-v1-1, Property 15

    Over any rows through run_bulk, the mock Gmail service records no ".send("
    call, and the module SCOPES contain no send capability.
    Validates: Requirements 11.1, 3.1
    """
    rows = [row for _kind, row in pairs]
    mock_service = mock.MagicMock(name="gmail_service")

    # Route the real create_draft through the mock service so any send call
    # would be recorded; find_duplicate_draft is stubbed to avoid list/get
    # traffic clouding the check.
    with mock.patch.object(
        outreach_drafts, "find_duplicate_draft", return_value=False
    ):
        outreach_drafts.run_bulk(
            rows,
            service=mock_service,
            sender="me@circuitrunners.com",
            override=False,
            attachments_for=_no_attachments,
            sleep=mock.Mock(),
        )

    # No recorded call on the service may contain a ".send(" invocation.
    recorded_calls = [str(call) for call in mock_service.mock_calls]
    assert all(".send(" not in call for call in recorded_calls), (
        "run_bulk must never invoke a send operation; "
        f"recorded calls were: {recorded_calls}"
    )

    # Any create used must be users().drafts().create — never messages().create.
    create_calls = [call for call in recorded_calls if ".create(" in call]
    assert all(".drafts().create(" in call for call in create_calls), (
        "the only create operation may be users().drafts().create; "
        f"recorded create calls were: {create_calls}"
    )

    # The named send paths were never called.
    mock_service.users().messages().send.assert_not_called()
    mock_service.users().drafts().send.assert_not_called()

    # The requested OAuth scope grants no send capability.
    for scope in outreach_drafts.SCOPES:
        assert "gmail.send" not in scope, (
            f"SCOPES must not request send capability; found: {scope}"
        )
        assert scope != "https://mail.google.com/", (
            "SCOPES must not request the full-mailbox scope, which permits sending"
        )


# ===========================================================================
# Task 6.7 — Property 13: Every draft CCs the fixed coordinators
# ===========================================================================
@settings(max_examples=100, deadline=None)
@given(
    sender=_email,
    to=_email,
    recipient_name=_nonempty_text,
    sender_name=_nonempty_text,
    school_name=_nonempty_text,
    template_type=st.sampled_from(_VALID_TEMPLATE_TYPES),
)
def test_every_draft_ccs_the_fixed_coordinators(
    sender, to, recipient_name, sender_name, school_name, template_type
):
    """Feature: outreach-app-v1-1, Property 13

    For any Contact_Row and Template_Type, the built message's Cc header equals
    ", ".join(CC_RECIPIENTS). Tested at the create_message_with_attachments
    level across all template types.
    Validates: Requirements 11.2
    """
    row = {
        "Recipient_Name": recipient_name,
        "Sender_Name": sender_name,
        "School_Name": school_name,
    }
    template = outreach_drafts.TEMPLATES[template_type]
    subject = outreach_drafts.render_template(template["subject"], row)
    body = outreach_drafts.render_template(template["body"], row)

    message = outreach_drafts.create_message_with_attachments(
        sender,
        to,
        subject,
        body,
        attachment_paths=[],
        cc=outreach_drafts.CC_RECIPIENTS,
    )

    parsed = _decode_raw(message)
    expected_cc = ", ".join(outreach_drafts.CC_RECIPIENTS)

    assert _decoded_header(parsed, "Cc") == expected_cc
    # Cc is set in addition to (not replacing) the recipient.
    assert parsed["To"] is not None
    assert parsed["Cc"] is not None


# ===========================================================================
# Task 6.8 — Example: duplicate-skip and bulk Post-Demo zero-photo branches
# ===========================================================================
def test_duplicate_with_override_off_is_skipped_and_not_created():
    """Feature: outreach-app-v1-1, Task 6.8 example

    A duplicate present with override off yields a BulkResult with outcome
    "skipped", reason containing "duplicate", and create_draft is NOT called for
    that row.
    Validates: Requirements 4.2
    """
    row = {
        "Recipient_Email": "teacher@example.com",
        "Recipient_Name": "Ms. Smith",
        "Sender_Name": "Alex",
        "School_Name": "Maple Elementary",
        "Template_Type": "Elementary",
    }
    mock_service = mock.MagicMock(name="gmail_service")
    create_mock = mock.Mock(name="create_draft", return_value={"id": "d1"})

    with mock.patch.object(
        outreach_drafts, "find_duplicate_draft", return_value=True
    ), mock.patch.object(
        outreach_drafts, "create_draft", create_mock
    ):
        result = outreach_drafts.process_contact_row(
            row,
            1,
            service=mock_service,
            sender="me@circuitrunners.com",
            override=False,
            attachments_for=_no_attachments,
        )

    assert result.outcome == "skipped"
    assert "duplicate" in result.reason
    # The create path must not run for a skipped duplicate.
    create_mock.assert_not_called()


def test_bulk_post_demo_row_yields_zero_attachments():
    """Feature: outreach-app-v1-1, Task 6.8 example

    A bulk Post-Demo row resolved through the attachments_for(row) policy (with
    no per-draft photos, as bulk supplies none) yields zero attachments.
    Validates: Requirements 3.9
    """
    row = {
        "Recipient_Email": "principal@example.com",
        "Recipient_Name": "Dr. Lee",
        "Sender_Name": "Alex",
        "School_Name": "Oak Middle",
        "Template_Type": "Post-Demo",
    }

    # The real bulk policy: Post-Demo in bulk supplies no per_draft_photos.
    paths = outreach_drafts.attachments_for(row)
    assert paths == []
