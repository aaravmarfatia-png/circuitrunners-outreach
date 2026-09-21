"""Property-based test for success/failure count conservation.

Feature: gmail-outreach-drafts, Property 9: Success and failure counts conserve
the total. For any set of Contact_Rows processed, each processed row is recorded
in exactly one of the success or failure categories, and the count of successful
drafts plus the count of failed or skipped rows equals the total number of
Contact_Rows processed.

Validates: Requirements 8.3, 10.2, 10.4, 2.3

The test drives the full ``main()`` orchestration with a generated mixed list of
Contact_Rows: some valid (which create drafts and count as successes), some that
fail validation (missing required field / invalid Template_Type), and some whose
``create_draft`` raises (which count as failures via skip-and-continue). It then
parses the three integers from the printed Run_Summary and asserts the
conservation invariant ``successes + failures == total == len(rows)``.

Valid rows use the Response / Post-Demo Template_Types, which carry no
attachment sets, so no real attachment files are required.
"""
import re

from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings, strategies as st

import outreach_drafts


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------
# Simple non-empty text for personalization fields. Excludes surrogate/control
# characters. Guaranteed to contain a non-whitespace character so a valid row's
# required fields are never accidentally treated as missing.
_field_text = (
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        min_size=1,
        max_size=20,
    )
    .map(lambda s: s.strip())
    .filter(lambda s: s != "")
)

# Email addresses: a generated simple local part plus a fixed domain.
_local_part = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_",
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith(".") and not s.endswith("."))

_email = _local_part.map(lambda local: f"{local}@example.com")

# Template types with no attachment set, so a valid row needs no real files.
_no_attachment_types = st.sampled_from(["Response", "Post-Demo"])


def _valid_success_row(draw):
    """A well-formed row that should produce a draft (a success)."""
    return {
        "Recipient_Email": draw(_email),
        "Recipient_Name": draw(_field_text),
        "Sender_Name": draw(_field_text),
        "School_Name": draw(_field_text),
        "Template_Type": draw(_no_attachment_types),
        # Marker consumed by the test harness; not a real CSV column and ignored
        # by the script's validation and rendering.
        "_outcome": "success",
    }


def _validation_failure_row(draw):
    """A row that fails validate_row: either a missing field or a bad type."""
    row = {
        "Recipient_Email": draw(_email),
        "Recipient_Name": draw(_field_text),
        "Sender_Name": draw(_field_text),
        "School_Name": draw(_field_text),
        "Template_Type": draw(_no_attachment_types),
        "_outcome": "validation_failure",
    }
    kind = draw(st.sampled_from(["missing_field", "invalid_type"]))
    if kind == "missing_field":
        field = draw(
            st.sampled_from(
                [
                    "Recipient_Email",
                    "Recipient_Name",
                    "Sender_Name",
                    "School_Name",
                    "Template_Type",
                ]
            )
        )
        # Absent, empty, or whitespace-only all count as missing (Req 2.4).
        row[field] = draw(st.sampled_from(["", "   ", "\t"]))
    else:
        # A Template_Type not in the registry is invalid (Req 2.5).
        row["Template_Type"] = draw(
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
                max_size=10,
            ).filter(lambda s: s not in outreach_drafts.TEMPLATES)
        )
    return row


def _create_draft_failure_row(draw):
    """A well-formed row whose create_draft raises (a runtime failure)."""
    return {
        "Recipient_Email": draw(_email),
        "Recipient_Name": draw(_field_text),
        "Sender_Name": draw(_field_text),
        "School_Name": draw(_field_text),
        "Template_Type": draw(_no_attachment_types),
        "_outcome": "create_draft_failure",
    }


@st.composite
def _mixed_rows(draw):
    """Generate a mixed list of success / validation-failure / draft-failure rows."""
    n = draw(st.integers(min_value=1, max_value=12))
    rows = []
    for _ in range(n):
        kind = draw(
            st.sampled_from(["success", "validation_failure", "create_draft_failure"])
        )
        if kind == "success":
            rows.append(_valid_success_row(draw))
        elif kind == "validation_failure":
            rows.append(_validation_failure_row(draw))
        else:
            rows.append(_create_draft_failure_row(draw))
    return rows


def _parse_summary(captured_out):
    """Parse the three integers and presence of the Run_Summary from stdout."""
    assert "=== Run Summary ===" in captured_out, "Run Summary header missing"

    successes = re.search(r"Successful drafts:\s*(\d+)", captured_out)
    failures = re.search(r"Failed / skipped rows:\s*(\d+)", captured_out)
    total = re.search(r"Total contacts processed:\s*(\d+)", captured_out)

    assert successes is not None, "Successful drafts line missing"
    assert failures is not None, "Failed / skipped rows line missing"
    assert total is not None, "Total contacts processed line missing"

    return int(successes.group(1)), int(failures.group(1)), int(total.group(1))


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(rows=_mixed_rows())
def test_success_and_failure_counts_conserve_total(rows, capsys, monkeypatch):
    """Feature: gmail-outreach-drafts, Property 9

    Running main() over a mixed list of Contact_Rows, the Run_Summary reports
    counts where successes + failures == total and total == len(rows); every
    processed row lands in exactly one category.
    Validates: Requirements 8.3, 10.2, 10.4, 2.3
    """
    # Rows flagged for a create_draft failure, keyed by their generated email so
    # the patched create_draft can decide whether to raise. Because create_draft
    # receives only the message body (not the row), we instead patch
    # create_message_with_attachments to tag which rows should later fail — but
    # simpler: track the set of raising emails and raise from create_draft by
    # matching the message's To header is fragile. Instead we make create_draft
    # raise based on a mutable per-call index into the generated rows' outcomes.
    # The valid rows (success + create_draft_failure) reach create_draft in order,
    # so we replay their intended outcomes.
    valid_outcomes = [
        row["_outcome"]
        for row in rows
        if row["_outcome"] in ("success", "create_draft_failure")
    ]
    call_state = {"index": 0}

    def fake_create_draft(service, message_body):
        i = call_state["index"]
        call_state["index"] += 1
        # Defensive: if more calls happen than expected, treat as success.
        outcome = valid_outcomes[i] if i < len(valid_outcomes) else "success"
        if outcome == "create_draft_failure":
            raise RuntimeError("simulated draft creation failure")
        return {"id": f"draft-{i}"}

    # Patch all Google-dependent seams and side effects (Req: mock service; no
    # real network, no real sleep). read_contacts returns the generated rows.
    monkeypatch.setattr(outreach_drafts, "get_credentials", lambda: object())
    monkeypatch.setattr(outreach_drafts, "build_service", lambda creds: MagicMock())
    monkeypatch.setattr(outreach_drafts, "get_sender_address", lambda service: "me@x.com")
    monkeypatch.setattr(outreach_drafts, "read_contacts", lambda path: rows)
    monkeypatch.setattr(outreach_drafts, "create_draft", fake_create_draft)
    monkeypatch.setattr(outreach_drafts.time, "sleep", lambda seconds: None)

    outreach_drafts.main()

    captured = capsys.readouterr()
    successes, failures, total = _parse_summary(captured.out)

    # Conservation: every processed row is in exactly one category (Req 10.2,
    # 10.4) and the total equals the number of rows processed (Req 2.3, 8.3).
    assert successes + failures == total
    assert total == len(rows)
