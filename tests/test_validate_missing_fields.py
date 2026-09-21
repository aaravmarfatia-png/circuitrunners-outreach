"""Property-based test for whitespace-only / missing field validation.

Feature: gmail-outreach-drafts, Property 10: Whitespace-only field values are
treated as missing.

Validates: Requirements 2.4.

For any Contact_Row in which any of the five required fields is absent, an empty
string, or contains only whitespace characters, ``validate_row`` classifies the
row as invalid (returns a non-None error string naming that field) so main()
skips it without creating a draft. A fully valid row returns None.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# The five required fields; a missing value in any one of them must invalidate
# the row (Req 2.4).
REQUIRED_FIELDS = outreach_drafts.REQUIRED_FIELDS

# The valid Template_Type values are exactly the keys of the TEMPLATES registry.
VALID_TEMPLATE_TYPES = sorted(outreach_drafts.TEMPLATES.keys())

# Non-empty, non-whitespace text for the "present" field values that make up a
# baseline valid row. ``strip()`` on any generated value must be non-empty, so
# we generate from characters that are neither whitespace nor the NUL byte and
# require at least one such character.
_present_value = st.text(
    alphabet=st.characters(
        blacklist_characters="\x00 \t\n\r\f\v",
        blacklist_categories=("Cs", "Zs", "Zl", "Zp", "Cc"),
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")

# Whitespace-only strings: one or more spaces/tabs/newlines/etc. These must be
# treated as missing (Req 2.4).
_whitespace_only = st.text(alphabet=" \t\n\r\f\v", min_size=1, max_size=10)

# The three ways a required field can be "missing": absent (a sentinel we use to
# delete the key), empty string, or whitespace-only.
_ABSENT = object()
_missing_value = st.one_of(
    st.just(_ABSENT),          # key deleted from the row
    st.just(""),               # empty string
    _whitespace_only,          # whitespace-only string
)


def _valid_row(values, template_type):
    """Assemble a baseline valid Contact_Row from five present values."""
    return {
        "Recipient_Email": values[0],
        "Recipient_Name": values[1],
        "Sender_Name": values[2],
        "School_Name": values[3],
        "Template_Type": template_type,
    }


@settings(max_examples=200)
@given(
    present_values=st.lists(_present_value, min_size=4, max_size=4),
    template_type=st.sampled_from(VALID_TEMPLATE_TYPES),
    field_index=st.integers(min_value=0, max_value=len(REQUIRED_FIELDS) - 1),
    missing=_missing_value,
    row_number=st.integers(min_value=1, max_value=10_000),
)
def test_missing_or_whitespace_field_treated_as_missing(
    present_values, template_type, field_index, missing, row_number
):
    """Feature: gmail-outreach-drafts, Property 10.

    Starting from a fully valid row, corrupting exactly one required field with
    a missing value (absent key, "", or whitespace-only) makes ``validate_row``
    return a non-None error string that names the corrupted field. The same
    uncorrupted row validates to None.

    Validates: Requirements 2.4.
    """
    # Build a fully valid baseline row: four non-empty text fields plus a valid
    # Template_Type. Confirm it passes validation (control case).
    valid = _valid_row(present_values, template_type)
    assert outreach_drafts.validate_row(valid, row_number) is None

    # Corrupt exactly one of the five required fields with a "missing" value.
    field = REQUIRED_FIELDS[field_index]
    corrupted = dict(valid)
    if missing is _ABSENT:
        # Absent: remove the key entirely so row.get(field) is None.
        del corrupted[field]
    else:
        # Empty string or whitespace-only value.
        corrupted[field] = missing

    error = outreach_drafts.validate_row(corrupted, row_number)

    # The corrupted row is invalid: a non-None error string is returned...
    assert error is not None
    assert isinstance(error, str)
    # ...and the message identifies the specific field that is missing.
    assert field in error
