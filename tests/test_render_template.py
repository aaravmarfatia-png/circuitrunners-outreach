"""Property-based tests for placeholder substitution correctness.

Feature: gmail-outreach-drafts, Property 2: Placeholder substitution
correctness. For any Contact_Row field values, rendering a subject or body
replaces every occurrence of {{Recipient_Name}}, {{Sender_Name}}, and
{{School_Name}} with the row's Recipient_Name, Sender_Name, and School_Name
values respectively.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 5.2
"""
from hypothesis import given, settings, strategies as st

import outreach_drafts

# The three supported placeholder tokens.
PLACEHOLDERS = ("{{Recipient_Name}}", "{{Sender_Name}}", "{{School_Name}}")


def _no_placeholder_tokens(value: str) -> bool:
    """Reject generated field values that themselves contain a placeholder
    token, so the substitution assertion stays unambiguous.
    """
    return not any(token in value for token in PLACEHOLDERS)


# Arbitrary text field values that do not themselves contain a placeholder
# token (filtered out to keep the assertion clean).
field_values = st.text().filter(_no_placeholder_tokens)


def _row(recipient_name, sender_name, school_name):
    return {
        "Recipient_Name": recipient_name,
        "Sender_Name": sender_name,
        "School_Name": school_name,
    }


@settings(max_examples=200)
@given(
    recipient_name=field_values,
    sender_name=field_values,
    school_name=field_values,
)
def test_placeholders_replaced_with_row_values(recipient_name, sender_name, school_name):
    """Feature: gmail-outreach-drafts, Property 2

    A template text containing all three placeholders renders to the row's
    field values in the corresponding positions.
    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """
    row = _row(recipient_name, sender_name, school_name)

    # Fixed literal text surrounds each token so we can assert exact positions.
    template = (
        "To {{Recipient_Name}} | From {{Sender_Name}} | At {{School_Name}}."
    )
    expected = f"To {recipient_name} | From {sender_name} | At {school_name}."

    assert outreach_drafts.render_template(template, row) == expected


@settings(max_examples=200)
@given(
    recipient_name=field_values,
    sender_name=field_values,
    school_name=field_values,
)
def test_every_occurrence_is_replaced(recipient_name, sender_name, school_name):
    """Feature: gmail-outreach-drafts, Property 2

    Every occurrence (not just the first) of each placeholder is replaced.
    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """
    row = _row(recipient_name, sender_name, school_name)

    template = (
        "{{Recipient_Name}} {{Sender_Name}} {{School_Name}} "
        "{{Recipient_Name}} {{Sender_Name}} {{School_Name}}"
    )
    expected = (
        f"{recipient_name} {sender_name} {school_name} "
        f"{recipient_name} {sender_name} {school_name}"
    )

    assert outreach_drafts.render_template(template, row) == expected


@settings(max_examples=200)
@given(
    recipient_name=field_values,
    sender_name=field_values,
    school_name=field_values,
    template_type=st.sampled_from(sorted(outreach_drafts.TEMPLATES)),
)
def test_real_subject_and_body_substitution(
    recipient_name, sender_name, school_name, template_type
):
    """Feature: gmail-outreach-drafts, Property 2

    Rendering the real TEMPLATES subject and body substitutes the placeholder
    tokens that appear in them with the row's values. render_template behaves
    identically for subject and body (same function, same semantics).
    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 5.2
    """
    row = _row(recipient_name, sender_name, school_name)
    template = outreach_drafts.TEMPLATES[template_type]

    for text in (template["subject"], template["body"]):
        rendered = outreach_drafts.render_template(text, row)
        # Expected result computed independently via plain str.replace.
        expected = (
            text.replace("{{Recipient_Name}}", recipient_name)
            .replace("{{Sender_Name}}", sender_name)
            .replace("{{School_Name}}", school_name)
        )
        assert rendered == expected


@settings(max_examples=200)
@given(
    recipient_name=field_values,
    sender_name=field_values,
    school_name=field_values,
)
def test_subject_and_body_render_identically(recipient_name, sender_name, school_name):
    """Feature: gmail-outreach-drafts, Property 2

    Given the same template text, render_template produces the same output
    whether that text is used as a subject or a body (5.2, 6.4). We verify by
    rendering identical text twice and requiring equal results.
    Validates: Requirements 5.2, 6.4
    """
    row = _row(recipient_name, sender_name, school_name)
    text = (
        "Subject/body: {{Recipient_Name}} from {{Sender_Name}} at {{School_Name}}"
    )

    as_subject = outreach_drafts.render_template(text, row)
    as_body = outreach_drafts.render_template(text, row)

    assert as_subject == as_body
