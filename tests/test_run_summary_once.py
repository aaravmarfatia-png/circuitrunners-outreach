"""Property-based test for the end-of-run Run_Summary (Task 10.5).

Feature: gmail-outreach-drafts, Property 13: Run summary is printed exactly once
with all three counts.

Validates: Requirements 10.3.

For any completed run over a mix of valid and failing Contact_Rows, ``main()``
prints the Run_Summary exactly once, reporting the count of successful drafts,
the count of failed or skipped rows, and the total number of Contact_Rows
processed. This test drives ``main()`` end to end with the Google-dependent
pieces patched out, captures stdout, and asserts the summary header and each of
the three count lines appear exactly once and carry parseable integer counts.
"""
import io
from contextlib import redirect_stdout
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# Valid Template_Type values whose Attachment_Set is empty. Using only these for
# the valid rows means create_message_with_attachments never opens an image file
# on disk, so a "successful" row succeeds without any real attachments present.
_NO_ATTACHMENT_TEMPLATES = ["Response", "Post-Demo"]

# A row identifier component strategy: printable, non-empty, whitespace-free-ish
# text used for the personalization fields. We keep it simple and safe; the
# exact contents are irrelevant to Property 13 (which only concerns the summary).
_field_text = st.text(
    alphabet=st.characters(
        blacklist_characters="\x00\r\n", blacklist_categories=("Cs",)
    ),
    min_size=1,
    max_size=20,
).map(lambda s: s if s.strip() else "x")


@st.composite
def _valid_row(draw):
    """Generate a valid Contact_Row (empty-attachment template) plus a flag
    indicating whether its draft creation should be forced to fail.

    Returns a tuple ``(row, should_fail)``. ``should_fail`` marks a valid-shaped
    row whose ``create_draft`` call raises, exercising the row-level failure path
    without needing missing attachment files on disk.
    """
    row = {
        "Recipient_Email": draw(_field_text) + "@example.com",
        "Recipient_Name": draw(_field_text),
        "Sender_Name": draw(_field_text),
        "School_Name": draw(_field_text),
        "Template_Type": draw(st.sampled_from(_NO_ATTACHMENT_TEMPLATES)),
    }
    should_fail = draw(st.booleans())
    return row, should_fail


@st.composite
def _invalid_row(draw):
    """Generate an invalid Contact_Row that ``validate_row`` will reject.

    Either drops a required field (missing/blank value) or supplies a
    Template_Type outside the valid enum. These rows are counted as failures and
    skipped before any draft is attempted.
    """
    row = {
        "Recipient_Email": draw(_field_text) + "@example.com",
        "Recipient_Name": draw(_field_text),
        "Sender_Name": draw(_field_text),
        "School_Name": draw(_field_text),
        "Template_Type": draw(st.sampled_from(_NO_ATTACHMENT_TEMPLATES)),
    }
    kind = draw(st.sampled_from(["blank_field", "bad_template"]))
    if kind == "blank_field":
        field = draw(st.sampled_from(outreach_drafts.REQUIRED_FIELDS))
        # Whitespace-only value is treated as missing (Req 2.4).
        row[field] = draw(st.sampled_from(["", "   ", "\t"]))
    else:
        row["Template_Type"] = draw(
            st.text(min_size=1, max_size=10).filter(
                lambda s: s not in outreach_drafts.TEMPLATES
            )
        )
    return row, False  # should_fail flag unused for invalid rows


# A run is a list of rows mixing valid (some flagged to fail) and invalid rows.
# min_size=1 keeps at least one row so the total is meaningful; the summary is
# still printed for zero rows, but a non-empty mix is the interesting case.
_rows = st.lists(
    st.one_of(_valid_row(), _invalid_row()),
    min_size=1,
    max_size=12,
)


@settings(max_examples=100, deadline=None)
@given(rows_with_flags=_rows)
def test_run_summary_printed_exactly_once(rows_with_flags):
    """Feature: gmail-outreach-drafts, Property 13.

    Over any mix of valid and failing rows, ``main()`` prints the Run_Summary
    exactly once: the header appears once, and each of the three count lines
    appears exactly once with a parseable integer count.

    Validates: Requirements 10.3.
    """
    rows = [row for row, _flag in rows_with_flags]

    # Map each row's identity to whether its create_draft should raise. Valid
    # rows flagged should_fail raise inside create_draft (an API-style failure);
    # all other valid rows succeed. id() keys the lookup so duplicate row dicts
    # are distinguished by object identity.
    # create_draft is called once per valid row in order. We consume a queue of
    # outcomes so flagged valid rows raise and the rest return a dummy draft.
    valid_outcomes = [flag for row, flag in rows_with_flags
                      if outreach_drafts.validate_row(row, 1) is None]
    outcomes_iter = iter(valid_outcomes)

    def create_draft_side_effect(service, message_body):
        should_fail = next(outcomes_iter)
        if should_fail:
            raise RuntimeError("simulated draft-creation failure")
        return {"id": "draft-dummy"}

    with mock.patch.object(outreach_drafts, "get_credentials",
                           return_value=mock.sentinel.creds), \
            mock.patch.object(outreach_drafts, "build_service",
                              return_value=mock.MagicMock(name="service")), \
            mock.patch.object(outreach_drafts, "get_sender_address",
                              return_value="me@x.com"), \
            mock.patch.object(outreach_drafts, "read_contacts",
                              return_value=rows), \
            mock.patch.object(outreach_drafts, "create_draft",
                              side_effect=create_draft_side_effect), \
            mock.patch.object(outreach_drafts.time, "sleep"):
        # Capture stdout with a fresh buffer per generated example rather than
        # the function-scoped capsys fixture (which Hypothesis does not reset
        # between examples).
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            outreach_drafts.main()

    stdout = buffer.getvalue()
    lines = stdout.splitlines()

    # The header "=== Run Summary ===" appears exactly once.
    assert lines.count("=== Run Summary ===") == 1, (
        f"expected exactly one summary header, got stdout:\n{stdout}"
    )

    # Exactly one line for each of the three count labels.
    success_lines = [ln for ln in lines if ln.startswith("Successful drafts:")]
    failure_lines = [ln for ln in lines if ln.startswith("Failed / skipped rows:")]
    total_lines = [ln for ln in lines if ln.startswith("Total contacts processed:")]

    assert len(success_lines) == 1, f"stdout:\n{stdout}"
    assert len(failure_lines) == 1, f"stdout:\n{stdout}"
    assert len(total_lines) == 1, f"stdout:\n{stdout}"

    # All three counts are present and parseable as integers.
    successes = int(success_lines[0].split(":", 1)[1].strip())
    failures = int(failure_lines[0].split(":", 1)[1].strip())
    total = int(total_lines[0].split(":", 1)[1].strip())

    # Sanity: the reported counts are non-negative and conserve the total,
    # which is the invariant the summary reports (successes + failures == total).
    assert successes >= 0
    assert failures >= 0
    assert total == len(rows)
    assert successes + failures == total
