"""Property-based test for verbatim template rendering (regression guard).

Feature: outreach-app-v1-1, Property 14: Bodies are rendered verbatim except the
three placeholders. For any Contact_Row, ``render_template`` on a template body
replaces only ``{{Recipient_Name}}``, ``{{Sender_Name}}``, and
``{{School_Name}}`` and leaves all other characters unchanged — including the
literal ``[Insert Form Link]`` marker in the Post-Demo body.

Validates: Requirements 11.3
"""
from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts


# The three supported placeholder tokens — the ONLY substrings render_template
# is allowed to replace.
SUPPORTED_TOKENS = ("{{Recipient_Name}}", "{{Sender_Name}}", "{{School_Name}}")


def _contains_token(value: str) -> bool:
    """True if a generated field value itself contains a supported token."""
    return any(token in value for token in SUPPORTED_TOKENS)


# Generate personalization field values that do NOT themselves contain any of
# the token strings. A value equal to (or containing) a token would let a
# substituted value re-introduce a token, which is outside this property's
# scope, so such values are excluded per the task instructions.
_field_value = st.text(min_size=0, max_size=40).filter(lambda s: not _contains_token(s))


@st.composite
def contact_rows(draw):
    """Build a Contact_Row with token-free Recipient/Sender/School names."""
    return {
        "Recipient_Name": draw(_field_value),
        "Sender_Name": draw(_field_value),
        "School_Name": draw(_field_value),
    }


@settings(max_examples=100)
@given(row=contact_rows())
def test_body_rendered_verbatim_except_three_placeholders(row):
    """Feature: outreach-app-v1-1, Property 14

    For every TEMPLATES body, render_template replaces only the three supported
    placeholders and leaves everything else byte-for-byte unchanged. Verified
    by (a) reconstructing the expected result with an independent chain of
    ``str.replace`` and (b) asserting no supported token remains afterward.
    Validates: Requirements 11.3
    """
    for template_type, template in outreach_drafts.TEMPLATES.items():
        body = template["body"]

        rendered = outreach_drafts.render_template(body, row)

        # (a) Independent reconstruction: replacing exactly the three tokens and
        # nothing else must equal render_template's output.
        expected = (
            body.replace("{{Recipient_Name}}", row["Recipient_Name"])
            .replace("{{Sender_Name}}", row["Sender_Name"])
            .replace("{{School_Name}}", row["School_Name"])
        )
        assert rendered == expected, (
            f"{template_type} body not rendered verbatim: {rendered!r}"
        )

        # (b) No supported token survives the render.
        for token in SUPPORTED_TOKENS:
            assert token not in rendered, (
                f"{template_type} body still contains {token}: {rendered!r}"
            )


@settings(max_examples=100)
@given(row=contact_rows())
def test_insert_form_link_marker_preserved_in_post_demo(row):
    """Feature: outreach-app-v1-1, Property 14

    The literal ``[Insert Form Link]`` marker in the Post-Demo body is NOT a
    supported placeholder and must be preserved verbatim through rendering.
    Validates: Requirements 11.3
    """
    body = outreach_drafts.TEMPLATES["Post-Demo"]["body"]
    # Guard: the marker really is present in the source-of-truth body.
    assert "[Insert Form Link]" in body

    rendered = outreach_drafts.render_template(body, row)
    assert "[Insert Form Link]" in rendered


@settings(max_examples=100)
@given(row=contact_rows())
def test_non_placeholder_characters_unchanged(row):
    """Feature: outreach-app-v1-1, Property 14

    Every character of a body that is outside the three placeholder tokens is
    left unchanged. We verify by removing the three tokens from the source body
    and confirming the remaining literal segments all still appear, in order,
    in the rendered output.
    Validates: Requirements 11.3
    """
    for template in outreach_drafts.TEMPLATES.values():
        body = template["body"]
        rendered = outreach_drafts.render_template(body, row)

        # Split the source body on the three tokens; every literal segment
        # between/around tokens must survive verbatim and in order.
        import re

        pattern = "|".join(
            re.escape(tok) for tok in SUPPORTED_TOKENS
        )
        segments = [seg for seg in re.split(pattern, body) if seg]

        cursor = 0
        for seg in segments:
            idx = rendered.find(seg, cursor)
            assert idx != -1, (
                f"literal segment {seg!r} missing from rendered output {rendered!r}"
            )
            cursor = idx + len(seg)
