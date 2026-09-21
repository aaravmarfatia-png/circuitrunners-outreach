"""Property-based test for MIME attachment count preservation.

Feature: gmail-outreach-drafts, Property 5: Attachment count is preserved.

Validates: Requirements 7.3.

For any Contact_Row whose Attachment_Set files all exist, the constructed MIME
message contains exactly one image part per file in the Attachment_Set, and a
Contact_Row with an empty Attachment_Set produces a message with no image parts.
"""
import base64
import email
import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# Path to an existing, real JPEG in the project's attachments folder. We reuse
# its bytes for the generated temp files so MIMEImage detects a valid image
# subtype (a synthetic/empty file could fail image-type detection). Reading it
# once at import time keeps every generated attachment tiny and identical.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLE_JPEG_PATH = os.path.join(_PROJECT_ROOT, "attachments", "robot-demo1.jpg")
with open(_SAMPLE_JPEG_PATH, "rb") as _f:
    _SAMPLE_JPEG_BYTES = _f.read()

# Fixed, valid header/body values so the test isolates the one variable that
# matters for this property: the number of attachments.
SENDER = "sender@circuitrunners.com"
TO = "recipient@example.com"
SUBJECT = "Robot Demonstration Opportunity"
BODY = "Dear Teacher,\n\nWe would love to visit your school.\n"


def _count_image_parts(message_body):
    """Decode a ``{"raw": ...}`` draft body and count image MIME parts.

    Reverses the base64url encoding that ``create_message_with_attachments``
    applies, reparses the serialized MIME bytes, and counts the parts whose
    content maintype is ``image`` (Req 7.3).
    """
    raw = base64.urlsafe_b64decode(message_body["raw"])
    parsed = email.message_from_bytes(raw)
    return sum(1 for part in parsed.walk() if part.get_content_maintype() == "image")


@settings(max_examples=100, deadline=None)
@given(n=st.integers(min_value=0, max_value=5))
def test_attachment_count_is_preserved(n):
    """Feature: gmail-outreach-drafts, Property 5.

    Building a message with N existing image attachments yields exactly N image
    parts; N == 0 (an empty Attachment_Set) yields a message with no image
    parts (only the text body part).

    Validates: Requirements 7.3.
    """
    # Create N tiny valid JPEG temp files, reusing real project JPEG bytes so
    # MIMEImage can detect the image subtype. Each file is cleaned up in the
    # finally block regardless of the assertion outcome.
    tmp_paths = []
    try:
        for _ in range(n):
            fd, path = tempfile.mkstemp(suffix=".jpg")
            with os.fdopen(fd, "wb") as image_file:
                image_file.write(_SAMPLE_JPEG_BYTES)
            tmp_paths.append(path)

        message_body = outreach_drafts.create_message_with_attachments(
            SENDER,
            TO,
            SUBJECT,
            BODY,
            attachment_paths=tmp_paths,
            cc=outreach_drafts.CC_RECIPIENTS,
        )

        image_part_count = _count_image_parts(message_body)

        # Exactly one image part per attachment file (Req 7.3).
        assert image_part_count == n

        # An empty Attachment_Set produces zero image parts (only the text
        # part) (Req 7.3).
        if n == 0:
            assert image_part_count == 0
    finally:
        for path in tmp_paths:
            os.unlink(path)
