"""Property-based tests for MIME headers and body construction.

Feature: gmail-outreach-drafts, Property 4: MIME headers and body reflect the
row and template. For any valid Contact_Row (of any Template_Type) and
authenticated sender address, the constructed MIME message has its To header
equal to the row's Recipient_Email, its From header equal to the authenticated
sender address, its Subject header equal to the substituted Subject_Line, its
Cc header equal to the joined CC_RECIPIENTS (present in addition to, and not
replacing, the To header), and a text part equal to the substituted
Message_Body.

Validates: Requirements 7.1, 7.2, 7.4, 7.5, 5.4, 11.2, 11.3, 11.4
"""
import base64
import email
from email.header import decode_header, make_header

from hypothesis import given, settings, strategies as st

import outreach_drafts


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------
# Header values (subject) and body text: printable text with no control chars
# or surrogates. Kept to a moderate length so email's header folding does not
# rewrap the value, which would complicate exact comparison. The Cs (surrogate)
# and Cc (control) unicode categories are excluded.
_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    max_size=40,
)

# Subjects are further kept simple (single line, no leading/trailing whitespace)
# to avoid header folding surprises.
_subject_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    max_size=40,
).map(lambda s: s.strip()).filter(lambda s: "\n" not in s and "\r" not in s)

# Email addresses: a generated simple local part plus a fixed valid-looking
# domain. This avoids header-encoding surprises from arbitrary address text
# while still varying the address across examples.
_local_part = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_",
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith(".") and not s.endswith("."))

_email = _local_part.map(lambda local: f"{local}@example.com")


def _decode_raw(message_dict):
    """Decode the {'raw': ...} shape back into a parsed email.message.Message."""
    raw = message_dict["raw"]
    decoded_bytes = base64.urlsafe_b64decode(raw)
    return email.message_from_bytes(decoded_bytes)


def _decoded_header(parsed, name):
    """Return a header value with any RFC 2047 encoded-words decoded.

    The email package encodes headers containing non-ASCII characters as
    encoded-words (e.g. "=?utf-8?b?...?="). Decoding them back reconstructs the
    original unicode value so it can be compared against the supplied input.
    """
    raw = parsed[name]
    if raw is None:
        return None
    return str(make_header(decode_header(raw)))


def _plain_text_payload(parsed):
    """Return the decoded text/plain body part payload as a string."""
    for part in parsed.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode(
                part.get_content_charset() or "utf-8"
            )
    raise AssertionError("no text/plain part found in message")


@settings(max_examples=150)
@given(
    sender=_email,
    to=_email,
    subject=_subject_text,
    body_text=_text,
)
def test_mime_headers_and_body_reflect_inputs(sender, to, subject, body_text):
    """Feature: gmail-outreach-drafts, Property 4

    The constructed MIME message carries the To/From/Subject/Cc headers and the
    text/plain body exactly as supplied, with Cc equal to the joined
    CC_RECIPIENTS and present in addition to (not replacing) the To header.
    Validates: Requirements 7.1, 7.2, 7.4, 7.5, 5.4, 11.2, 11.3, 11.4
    """
    message = outreach_drafts.create_message_with_attachments(
        sender,
        to,
        subject,
        body_text,
        attachment_paths=[],
        cc=outreach_drafts.CC_RECIPIENTS,
    )

    parsed = _decode_raw(message)

    expected_cc = ", ".join(outreach_drafts.CC_RECIPIENTS)

    # To / From / Subject headers reflect the inputs (Req 7.1, 7.2, 7.4, 5.4).
    # Headers are decoded to reverse any RFC 2047 encoded-words applied to
    # non-ASCII values before comparison.
    assert _decoded_header(parsed, "To") == to
    assert _decoded_header(parsed, "From") == sender
    assert _decoded_header(parsed, "Subject") == subject

    # Cc equals the joined CC_RECIPIENTS (Req 7.5, 11.2, 11.3).
    assert _decoded_header(parsed, "Cc") == expected_cc

    # Cc is present IN ADDITION to To, not replacing it: both present and
    # distinct (Req 11.4).
    assert parsed["To"] is not None
    assert parsed["Cc"] is not None
    assert parsed["To"] != parsed["Cc"]

    # The text/plain body part payload equals the supplied body_text (Req 7.1).
    assert _plain_text_payload(parsed) == body_text


@settings(max_examples=150)
@given(
    sender=_email,
    to=_email,
    recipient_name=_text,
    sender_name=_text,
    school_name=_text,
    template_type=st.sampled_from(sorted(outreach_drafts.TEMPLATES)),
)
def test_mime_reflects_rendered_template_across_types(
    sender, to, recipient_name, sender_name, school_name, template_type
):
    """Feature: gmail-outreach-drafts, Property 4

    For every Template_Type, the MIME Subject header equals the substituted
    Subject_Line and the text part equals the substituted Message_Body, while
    Cc always equals the joined CC_RECIPIENTS regardless of Template_Type.
    Validates: Requirements 7.1, 7.2, 7.4, 7.5, 5.4, 11.2, 11.3, 11.4
    """
    row = {
        "Recipient_Name": recipient_name,
        "Sender_Name": sender_name,
        "School_Name": school_name,
    }
    template = outreach_drafts.TEMPLATES[template_type]
    subject = outreach_drafts.render_template(template["subject"], row)
    body_text = outreach_drafts.render_template(template["body"], row)

    message = outreach_drafts.create_message_with_attachments(
        sender,
        to,
        subject,
        body_text,
        attachment_paths=[],
        cc=outreach_drafts.CC_RECIPIENTS,
    )

    parsed = _decode_raw(message)
    expected_cc = ", ".join(outreach_drafts.CC_RECIPIENTS)

    assert _decoded_header(parsed, "To") == to
    assert _decoded_header(parsed, "From") == sender
    # Subject may be empty/short; folding avoided by moderate-length inputs.
    assert _decoded_header(parsed, "Subject") == subject
    assert _decoded_header(parsed, "Cc") == expected_cc
    assert parsed["To"] != parsed["Cc"]
    assert _plain_text_payload(parsed) == body_text
