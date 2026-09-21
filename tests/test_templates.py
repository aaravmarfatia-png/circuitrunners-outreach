"""Property-based tests for the template registry (TEMPLATES).

Feature: gmail-outreach-drafts, Property 1: Template selection maps each type to
its designated body and attachment set.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.1.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# The four valid Template_Type values (Req 4.1-4.4, 5.1).
VALID_TEMPLATE_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]

# The Source-of-Truth body constant expected for each Template_Type. The values
# are compared verbatim against the module constants (Req 4.1-4.4).
EXPECTED_BODIES = {
    "Elementary": outreach_drafts.ELEMENTARY_BODY,
    "Middle": outreach_drafts.MIDDLE_BODY,
    "Response": outreach_drafts.RESPONSE_BODY,
    "Post-Demo": outreach_drafts.POST_DEMO_BODY,
}

# The exact Attachment_Set specified per Template_Type (Req 4.1-4.4).
EXPECTED_ATTACHMENTS = {
    # Elementary and Middle both attach the two real demo photos. (updated to
    # match the current TEMPLATES attachment sets.)
    "Elementary": ["robot-demo4.jpg", "robot-demo5.jpg"],
    "Middle": ["robot-demo4.jpg", "robot-demo5.jpg"],
    "Response": [],
    "Post-Demo": [],
}


@settings(max_examples=100)
@given(template_type=st.sampled_from(VALID_TEMPLATE_TYPES))
def test_template_selection_maps_type_to_body_and_attachments(template_type):
    """Feature: gmail-outreach-drafts, Property 1.

    For every valid Template_Type, the selected template entry SHALL provide the
    verbatim Source-of-Truth body for that type, exactly the specified
    Attachment_Set, and exactly one defined subject (a non-empty string).

    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.1.
    """
    # The type must be present in the registry so it can be selected.
    assert template_type in outreach_drafts.TEMPLATES
    entry = outreach_drafts.TEMPLATES[template_type]

    # Body is the verbatim Source-of-Truth constant for this type (Req 4.1-4.4).
    assert entry["body"] == EXPECTED_BODIES[template_type]

    # Attachment list is exactly the specified set, in order (Req 4.1-4.4).
    assert entry["attachments"] == EXPECTED_ATTACHMENTS[template_type]

    # Exactly one defined subject: a single non-empty string (Req 5.1).
    subject = entry["subject"]
    assert isinstance(subject, str)
    assert subject.strip() != ""
