"""Property-based test for Template_Type enum validation (validate_row).

Feature: gmail-outreach-drafts, Property 11: Template_Type validation matches
the enum exactly.

Validates: Requirements 2.5.

For any Template_Type value, an otherwise-valid Contact_Row SHALL be accepted
for template selection (``validate_row`` returns None) if and only if the value
is one of the four valid types: Elementary, Middle, Response, or Post-Demo.

This test isolates the Template_Type-enum behaviour. Every other required field
(Recipient_Email, Recipient_Name, Sender_Name, School_Name) is filled with a
non-empty, non-whitespace value so those fields never trigger the
missing-field check (Req 2.4). Only the Template_Type field varies:

  * Valid types are drawn from the exact enum via ``st.sampled_from`` and must
    yield None.
  * Invalid types are arbitrary non-empty, non-whitespace strings that are not
    one of the four valid values; these are filtered out so an invalid row is
    rejected *because of* the Template_Type enum check rather than the
    missing-field check. Each must yield a non-None error mentioning the
    invalid Template_Type.
"""
from hypothesis import assume, given, settings
from hypothesis import strategies as st

import outreach_drafts

# The exact set of valid Template_Type values (Req 2.5). Kept as a module-level
# constant so both the valid and invalid strategies reference the same source.
VALID_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]

# A non-empty, non-whitespace value for each of the four *other* required
# fields, so the missing-field check (Req 2.4) never fires and the row's
# acceptance depends solely on the Template_Type value under test.
_nonblank_text = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")


def _make_row(template_type):
    """Build an otherwise-valid Contact_Row with the given Template_Type.

    All five required fields are present; the four non-Template_Type fields are
    fixed, non-blank values so only Template_Type governs validity.
    """
    return {
        "Recipient_Email": "teacher@example.com",
        "Recipient_Name": "Pat Teacher",
        "Sender_Name": "Alex Sender",
        "School_Name": "Example Elementary",
        "Template_Type": template_type,
    }


@settings(max_examples=100)
@given(template_type=st.sampled_from(VALID_TYPES))
def test_valid_template_type_is_accepted(template_type):
    """Feature: gmail-outreach-drafts, Property 11.

    An otherwise-valid row whose Template_Type is one of the four valid enum
    values SHALL be accepted (validate_row returns None).

    Validates: Requirements 2.5.
    """
    row = _make_row(template_type)
    assert outreach_drafts.validate_row(row, 1) is None


@settings(max_examples=100)
@given(template_type=_nonblank_text)
def test_invalid_template_type_is_rejected(template_type):
    """Feature: gmail-outreach-drafts, Property 11.

    An otherwise-valid row whose Template_Type is a non-blank string that is
    NOT one of the four valid enum values SHALL be rejected, and the returned
    error SHALL mention the invalid Template_Type.

    Validates: Requirements 2.5.
    """
    # Isolate the enum behaviour: skip any generated value that happens to be a
    # valid type (would be accepted) so failures here are purely enum-driven.
    assume(template_type not in VALID_TYPES)

    row = _make_row(template_type)
    error = outreach_drafts.validate_row(row, 1)

    # The row is rejected because the Template_Type is not in the enum (Req 2.5).
    assert error is not None
    # The error identifies the cause as an invalid Template_Type.
    assert "invalid Template_Type" in error


def test_each_valid_type_yields_none():
    """Feature: gmail-outreach-drafts, Property 11.

    Explicitly confirm each of the four valid Template_Type values is accepted
    (validate_row returns None), covering the full enum by example.

    Validates: Requirements 2.5.
    """
    for template_type in VALID_TYPES:
        row = _make_row(template_type)
        assert outreach_drafts.validate_row(row, 1) is None
