"""Property-based test for base64url encoding round-trip.

Feature: gmail-outreach-drafts, Property 6: Base64url encoding round-trips.
For any constructed MIME message, base64url-decoding the raw string produced
for the draft request reconstructs the original serialized MIME message bytes.

Validates: Requirements 7.6
"""
import base64
import email

from hypothesis import given, settings, strategies as st

import outreach_drafts


# Header values (To/From/Subject) are constrained to printable ASCII so the
# header round-trip is exact and unambiguous. Non-ASCII header text would be
# RFC 2047 word-encoded (=?utf-8?b?...?=) during MIME serialization, which is
# correct MIME behavior but would not compare equal to the raw input string;
# that transformation is orthogonal to Property 6 (the base64url round-trip).
# The body still exercises the full safe-unicode space (surrogates excluded),
# so the base64url encode/decode round-trip is tested over rich content.
_HEADER_CHARS = st.characters(
    min_codepoint=33,
    max_codepoint=126,  # printable ASCII, no whitespace/control
)
_BODY_CHARS = st.characters(
    min_codepoint=32,
    max_codepoint=0x10FFFF,
    blacklist_categories=("Cs",),  # exclude surrogates
    blacklist_characters="\r",
)

# Non-empty header values keep To/From/Subject meaningful.
header_text = st.text(_HEADER_CHARS, min_size=1, max_size=60)
body_text = st.text(_BODY_CHARS, max_size=200)


@settings(max_examples=100, deadline=None)
@given(
    sender=header_text,
    to=header_text,
    subject=header_text,
    body=body_text,
)
def test_base64url_roundtrip(sender, to, subject, body):
    """Feature: gmail-outreach-drafts, Property 6

    Building a MIME message with no attachments and Cc'ing CC_RECIPIENTS, the
    raw base64url string it produces:
      * decodes successfully with base64.urlsafe_b64decode,
      * parses back into a message with the same To/From/Subject/Cc headers and
        the same text body, and
      * re-encodes to exactly the same raw string (exact round-trip of the
        base64url encoding step).
    Validates: Requirements 7.6
    """
    result = outreach_drafts.create_message_with_attachments(
        sender,
        to,
        subject,
        body,
        attachment_paths=[],
        cc=outreach_drafts.CC_RECIPIENTS,
    )

    raw = result["raw"]

    # base64url-decoding the raw string succeeds and yields the serialized bytes.
    decoded_bytes = base64.urlsafe_b64decode(raw)

    # Parsing those bytes reconstructs the same headers and body.
    parsed = email.message_from_bytes(decoded_bytes)
    assert parsed["From"] == sender
    assert parsed["To"] == to
    assert parsed["Subject"] == subject
    assert parsed["Cc"] == ", ".join(outreach_drafts.CC_RECIPIENTS)

    # The first (text) part carries the original body. get_payload(decode=True)
    # reverses any transfer-encoding applied during serialization.
    text_part = parsed.get_payload(0)
    recovered_body = text_part.get_payload(decode=True).decode(
        text_part.get_content_charset() or "utf-8"
    )
    assert recovered_body == body

    # Re-encoding the decoded bytes reproduces the exact raw string, confirming
    # the encoding step is an exact round-trip.
    assert base64.urlsafe_b64encode(decoded_bytes).decode() == raw
