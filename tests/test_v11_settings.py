"""Property-based tests for settings persistence (v1.1.0).

Covers two design properties for the settings JSON helpers in
``outreach_drafts.py`` (``load_settings`` / ``save_settings`` /
``DEFAULT_SETTINGS``):

- Property 9: Settings JSON round-trip (Validates: Requirements 7.1, 7.2, 7.3)
- Property 10: Settings loading tolerates a missing or corrupt file
  (Validates: Requirements 7.4)

Both helpers accept an explicit ``path`` argument, so every example writes to
its own temporary file built with :mod:`tempfile` (the ``tmp_path`` fixture is
avoided because it is function-scoped and would be reused across Hypothesis
examples). No Gmail service is touched and nothing is sent.
"""
import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts


# The four valid Template_Type values (Post-Demo included) per the spec glossary.
_TEMPLATE_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]

# Arbitrary sender name: any text, excluding characters that are irrelevant to
# JSON round-tripping and could complicate comparison (NUL and lone surrogates,
# which cannot be encoded as UTF-8).
_sender_name = st.text(
    alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
    min_size=0,
    max_size=60,
)

# A "WxH" window-size string built from two positive integers, matching the
# window_size shape stored by the app (e.g. "640x660").
_window_size = st.builds(
    lambda w, h: f"{w}x{h}",
    st.integers(min_value=1, max_value=9999),
    st.integers(min_value=1, max_value=9999),
)


def _new_settings_path() -> str:
    """Return a fresh, unused settings-file path inside a temp directory.

    Creates a per-example temporary directory and returns a ``settings.json``
    path within it. The file itself is not created, so ``save_settings`` (which
    writes atomically) and the missing-file case both work cleanly.
    """
    directory = tempfile.mkdtemp()
    return os.path.join(directory, "settings.json")


@settings(max_examples=100)
@given(
    sender_name=_sender_name,
    last_template=st.sampled_from(_TEMPLATE_TYPES),
    window_size=_window_size,
)
def test_settings_json_round_trip(sender_name, last_template, window_size):
    """Feature: outreach-app-v1-1, Property 9: Settings JSON round-trip.

    For any valid settings record (sender name, last Template_Type, window
    size), writing it with ``save_settings`` and reading it back with
    ``load_settings`` yields equal values for those keys.

    Validates: Requirements 7.1, 7.2, 7.3.
    """
    path = _new_settings_path()
    record = {
        "sender_name": sender_name,
        "last_template": last_template,
        "window_size": window_size,
    }

    outreach_drafts.save_settings(record, path=path)
    loaded = outreach_drafts.load_settings(path=path)

    # The stored keys round-trip exactly.
    assert loaded["sender_name"] == sender_name
    assert loaded["last_template"] == last_template
    assert loaded["window_size"] == window_size


@settings(max_examples=100)
@given(content=st.binary(min_size=0, max_size=200))
def test_settings_loading_tolerates_corrupt_file(content):
    """Feature: outreach-app-v1-1, Property 10: tolerant settings loading.

    For any byte content written to the Settings_File (including invalid JSON),
    ``load_settings`` returns a dict containing all default keys and never
    raises.

    Validates: Requirements 7.4.
    """
    path = _new_settings_path()
    with open(path, "wb") as f:
        f.write(content)

    # Must never raise regardless of the bytes on disk.
    loaded = outreach_drafts.load_settings(path=path)

    assert isinstance(loaded, dict)
    # Every default key is present. For content that is not a valid JSON object,
    # the helper falls back to exactly DEFAULT_SETTINGS.
    for key in outreach_drafts.DEFAULT_SETTINGS:
        assert key in loaded


@settings(max_examples=100)
@given(dummy=st.integers())
def test_settings_loading_missing_file_returns_defaults(dummy):
    """Feature: outreach-app-v1-1, Property 10: tolerant settings loading.

    For a missing Settings_File, ``load_settings`` returns a dict equal to
    ``DEFAULT_SETTINGS`` without raising.

    Validates: Requirements 7.4.
    """
    # A path inside a fresh temp dir that we deliberately never create.
    path = _new_settings_path()
    assert not os.path.exists(path)

    loaded = outreach_drafts.load_settings(path=path)

    assert loaded == outreach_drafts.DEFAULT_SETTINGS
