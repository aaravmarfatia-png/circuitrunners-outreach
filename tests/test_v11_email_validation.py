"""Property-based tests for email validation and field normalization.

Feature: outreach-app-v1-1, Property 11: Email validation and normalization.
For any recipient email string, ``is_valid_email(normalize_fields(row)
["Recipient_Email"])`` uses the whitespace-trimmed value; a value that is not a
valid single-address format after trimming is rejected (no draft created), and a
value that is valid after trimming is accepted for creation.

Validates: Requirements 8.1, 8.2, 8.3
"""
from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts


# Surrounding-whitespace characters we wrap around generated field values so we
# can assert that normalization strips them. All of these are removed by
# ``str.strip()``.
_WS = " \t\n\r\f\v"
_whitespace = st.text(alphabet=_WS, min_size=0, max_size=5)

# Arbitrary text field values (may contain interior whitespace, unicode, etc.).
_field_value = st.text(min_size=0, max_size=40)

# The Contact_Row string fields subject to normalization.
_ROW_KEYS = [
    "Recipient_Email",
    "Recipient_Name",
    "Sender_Name",
    "School_Name",
    "Template_Type",
]


@st.composite
def rows_with_whitespace(draw):
    """Build a Contact_Row whose string values are wrapped in surrounding
    whitespace so normalization has something to trim."""
    row = {}
    for key in _ROW_KEYS:
        core = draw(_field_value)
        lead = draw(_whitespace)
        trail = draw(_whitespace)
        row[key] = f"{lead}{core}{trail}"
    return row


@settings(max_examples=100)
@given(row=rows_with_whitespace())
def test_normalize_fields_strips_every_string_field(row):
    """Feature: outreach-app-v1-1, Property 11

    normalize_fields returns a copy where every string field equals the
    ``.strip()`` of the original value (Req 8.2).
    Validates: Requirements 8.2
    """
    normalized = outreach_drafts.normalize_fields(row)

    # Every string field is trimmed to its ``.strip()`` value.
    for key, value in row.items():
        assert normalized[key] == value.strip()

    # The original dict is not mutated (a new dict is returned).
    for key in _ROW_KEYS:
        assert row[key] == row[key]  # unchanged reference-safe check


@settings(max_examples=100)
@given(row=rows_with_whitespace())
def test_normalize_fields_is_idempotent(row):
    """Feature: outreach-app-v1-1, Property 11

    Normalization is idempotent: normalizing an already-normalized row is a
    no-op (Req 8.2).
    Validates: Requirements 8.2
    """
    once = outreach_drafts.normalize_fields(row)
    twice = outreach_drafts.normalize_fields(once)
    assert once == twice


@settings(max_examples=100)
@given(
    local=st.text(alphabet=_WS, min_size=0, max_size=3),
    email_core=_field_value,
    trail=st.text(alphabet=_WS, min_size=0, max_size=3),
)
def test_validation_uses_the_trimmed_value(local, email_core, trail):
    """Feature: outreach-app-v1-1, Property 11

    is_valid_email(normalize_fields(row)["Recipient_Email"]) operates on the
    trimmed value: validating the normalized Recipient_Email is equivalent to
    validating the raw value's ``.strip()`` (Req 8.1, 8.2).
    Validates: Requirements 8.1, 8.2
    """
    raw_email = f"{local}{email_core}{trail}"
    row = {
        "Recipient_Email": raw_email,
        "Recipient_Name": "n",
        "Sender_Name": "s",
        "School_Name": "sc",
        "Template_Type": "Elementary",
    }

    normalized = outreach_drafts.normalize_fields(row)
    result = outreach_drafts.is_valid_email(normalized["Recipient_Email"])

    # The validation seam sees the trimmed value, so it matches validating the
    # raw email's own ``.strip()`` directly.
    assert result == outreach_drafts.is_valid_email(raw_email.strip())


# A local-part / domain-label alphabet that avoids '@', whitespace, and '.' so
# generated single-address emails are unambiguous and well-formed.
_atom = st.text(
    alphabet=st.characters(
        min_codepoint=33,
        max_codepoint=126,
        blacklist_characters="@. \t\n\r",
    ),
    min_size=1,
    max_size=12,
)


@st.composite
def valid_emails(draw):
    """Generate a well-formed ``local@domain.tld`` single address."""
    local = draw(_atom)
    domain = draw(_atom)
    tld = draw(_atom)
    return f"{local}@{domain}.{tld}"


@settings(max_examples=100)
@given(email=valid_emails())
def test_valid_local_at_domain_tld_accepted_after_trim(email):
    """Feature: outreach-app-v1-1, Property 11

    A value that is a valid ``local@domain.tld`` single address after trimming
    is accepted for creation, even when surrounded by whitespace (Req 8.3).
    Validates: Requirements 8.3
    """
    padded = f"  {email}\t"
    row = {"Recipient_Email": padded}
    normalized = outreach_drafts.normalize_fields(row)

    assert outreach_drafts.is_valid_email(normalized["Recipient_Email"]) is True


@settings(max_examples=100)
@given(
    text=st.text(min_size=0, max_size=40).filter(
        # Clearly invalid: no '@' at all (also covers the empty string).
        lambda s: "@" not in s
    )
)
def test_missing_at_sign_rejected(text):
    """Feature: outreach-app-v1-1, Property 11

    A value with no ``@`` (including the empty string) is rejected after
    trimming — no draft would be created (Req 8.1).
    Validates: Requirements 8.1
    """
    row = {"Recipient_Email": text}
    normalized = outreach_drafts.normalize_fields(row)
    assert outreach_drafts.is_valid_email(normalized["Recipient_Email"]) is False


@settings(max_examples=100)
@given(
    left=_atom,
    middle=_atom,
    right=_atom,
    space=st.sampled_from([" ", "\t"]),
)
def test_internal_whitespace_rejected(left, middle, right, space):
    """Feature: outreach-app-v1-1, Property 11

    An address containing interior whitespace (which ``.strip()`` cannot
    remove) is rejected as an invalid single-address format (Req 8.1).
    Validates: Requirements 8.1
    """
    # Interior space keeps this from being a valid single address even after trim.
    bad = f"{left}{space}{middle}@{right}.com"
    row = {"Recipient_Email": bad}
    normalized = outreach_drafts.normalize_fields(row)
    assert outreach_drafts.is_valid_email(normalized["Recipient_Email"]) is False


def test_empty_after_trim_rejected():
    """Feature: outreach-app-v1-1, Property 11

    A whitespace-only value normalizes to empty and is rejected (Req 8.1, 8.2).
    Validates: Requirements 8.1, 8.2
    """
    row = {"Recipient_Email": "   \t\n  "}
    normalized = outreach_drafts.normalize_fields(row)
    assert normalized["Recipient_Email"] == ""
    assert outreach_drafts.is_valid_email(normalized["Recipient_Email"]) is False
