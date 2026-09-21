"""Property-based test for Property 3 — no unresolved supported placeholders.

Feature: gmail-outreach-drafts, Property 3: No unresolved supported placeholders
remain. For any Contact_Row, after substitution neither the rendered subject nor
the rendered body SHALL contain any of the supported placeholder tokens
``{{Recipient_Name}}``, ``{{Sender_Name}}``, or ``{{School_Name}}``.

Validates: Requirements 6.1, 6.2, 6.3, 6.4
"""
from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# The three supported placeholder tokens that must never remain after render.
# Note: "[Insert Form Link]" in the Post-Demo body is NOT a supported
# placeholder and is intentionally excluded from this set.
SUPPORTED_TOKENS = ("{{Recipient_Name}}", "{{Sender_Name}}", "{{School_Name}}")


def _contains_supported_token(text: str) -> bool:
    """True if ``text`` contains any of the three supported placeholder tokens."""
    return any(token in text for token in SUPPORTED_TOKENS)


# Generate field values that do NOT themselves contain any supported token.
# A substituted value that reintroduced a token (e.g. School_Name literally
# equal to "{{Sender_Name}}") would be a self-inflicted case outside the
# property's scope, so we filter such values out per the task instructions.
_field_value = st.text(min_size=0, max_size=40).filter(
    lambda s: not _contains_supported_token(s)
)


@st.composite
def contact_rows(draw):
    """Build a Contact_Row dict with token-free personalization field values."""
    return {
        "Recipient_Name": draw(_field_value),
        "Sender_Name": draw(_field_value),
        "School_Name": draw(_field_value),
    }


@settings(max_examples=200)
@given(row=contact_rows())
def test_no_unresolved_supported_placeholders(row):
    """For every template, rendered subject and body carry no supported token.

    Feature: gmail-outreach-drafts, Property 3
    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """
    for template_type, template in outreach_drafts.TEMPLATES.items():
        rendered_subject = outreach_drafts.render_template(template["subject"], row)
        rendered_body = outreach_drafts.render_template(template["body"], row)

        for token in SUPPORTED_TOKENS:
            assert token not in rendered_subject, (
                f"{template_type} subject still contains {token}: {rendered_subject!r}"
            )
            assert token not in rendered_body, (
                f"{template_type} body still contains {token}: {rendered_body!r}"
            )
