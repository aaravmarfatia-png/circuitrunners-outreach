"""Tests for the duplicate-draft guard and retry/backoff seams (v1.1.0).

Covers two design properties plus a set of deterministic example cases for the
core seams added in Task 4:

- Property 2: Duplicate detection and skip
  (``find_duplicate_draft``) — Validates: Requirements 4.1, 4.2
- Property 4: Retry performs a bounded number of attempts with mocked backoff
  (``create_draft_with_retry``) — Validates: Requirements 5.1, 5.2, 5.3, 5.4

All Gmail interactions are mocked with :mod:`unittest.mock` and ``time.sleep``
is never called for real (the retry helper's ``sleep`` is injected as a
``Mock``). No test creates a live service or sends mail.

The fake Gmail service mirrors the exact shapes the production code reads:

- ``find_duplicate_draft`` calls ``service.users().drafts().list(userId="me")``
  ``.execute()`` → ``{"drafts": [{"id": ...}, ...]}`` and, per draft,
  ``service.users().drafts().get(userId="me", id=..., format="metadata")``
  ``.execute()`` → a draft resource whose headers live at
  ``{"message": {"payload": {"headers": [{"name": ..., "value": ...}, ...]}}}``.
  It compares the decoded ``To`` header case-insensitively and the ``Subject``
  header exactly.
- ``create_draft_with_retry`` calls ``outreach_drafts.create_draft`` (patched
  here) and, on a transient :class:`HttpError` (5xx), sleeps
  ``2 ** (attempt - 1)`` via the injected ``sleep`` before retrying.
"""
from unittest import mock

import pytest
from googleapiclient.errors import HttpError
from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts


# ---------------------------------------------------------------------------
# Fake Gmail service for find_duplicate_draft
# ---------------------------------------------------------------------------
def _build_draft_resource(to_value, subject_value):
    """Return a draft resource in the shape find_duplicate_draft reads.

    ``_decode_draft_headers`` reads ``message.payload.headers`` as a list of
    ``{"name": ..., "value": ...}`` dicts, so we build exactly that nesting for
    the ``To`` and ``Subject`` headers.
    """
    return {
        "message": {
            "payload": {
                "headers": [
                    {"name": "To", "value": to_value},
                    {"name": "Subject", "value": subject_value},
                ]
            }
        }
    }


def _build_fake_service(existing_drafts):
    """Return a Mock Gmail service exposing ``existing_drafts``.

    ``existing_drafts`` is a list of ``(to, subject)`` pairs. The returned mock
    wires ``users().drafts().list().execute()`` to a list of stable ids and
    ``users().drafts().get(...).execute()`` to look up the corresponding draft
    resource by id, matching how ``find_duplicate_draft`` iterates.
    """
    id_to_resource = {}
    listing = []
    for index, (to_value, subject_value) in enumerate(existing_drafts):
        draft_id = f"draft-{index}"
        listing.append({"id": draft_id})
        id_to_resource[draft_id] = _build_draft_resource(to_value, subject_value)

    service = mock.MagicMock(name="gmail_service")
    drafts = service.users.return_value.drafts.return_value

    drafts.list.return_value.execute.return_value = {"drafts": listing}

    def _get(userId, id, format):  # noqa: A002 - mirror the real kwarg name "id"
        get_result = mock.MagicMock(name=f"get({id})")
        get_result.execute.return_value = id_to_resource[id]
        return get_result

    drafts.get.side_effect = _get
    return service


# ---------------------------------------------------------------------------
# Property 2: Duplicate detection and skip
# ---------------------------------------------------------------------------
# A draft is modeled as an (email, subject) pair. Emails are drawn from a small
# alphabet so collisions (and near-collisions differing only in case) occur
# often; subjects likewise. Keeping both spaces small makes real matches and
# real non-matches both common across 100 examples.
_email = st.builds(
    lambda local, domain: f"{local}@{domain}.com",
    st.sampled_from(["Alice", "bob", "CAROL", "dave"]),
    st.sampled_from(["school", "Example", "district"]),
)
_subject = st.sampled_from(
    ["Robotics Demo", "Follow up", "robotics demo", "Hello there", ""]
)
_draft = st.tuples(_email, _subject)


@settings(max_examples=100, deadline=None)
@given(
    existing=st.lists(_draft, min_size=0, max_size=8),
    candidate=_draft,
)
def test_duplicate_detection_matches_ground_truth(existing, candidate):
    """Feature: outreach-app-v1-1, Property 2: Duplicate detection and skip.

    For any set of existing drafts and any candidate (recipient email,
    subject), with the override disabled, ``find_duplicate_draft`` returns True
    if and only if some existing draft matches BOTH the recipient email
    (case-insensitively) AND the subject (exactly). No create call is made by
    the read-only guard.

    Validates: Requirements 4.1, 4.2.
    """
    candidate_email, candidate_subject = candidate

    # Ground truth mirrors the production predicate: email compared after
    # strip().lower(), subject compared exactly.
    target_email = candidate_email.strip().lower()
    expected = any(
        existing_email.strip().lower() == target_email
        and existing_subject == candidate_subject
        for existing_email, existing_subject in existing
    )

    service = _build_fake_service(existing)

    result = outreach_drafts.find_duplicate_draft(
        service, candidate_email, candidate_subject
    )

    assert result is expected

    # The guard is strictly read-only: it never creates or sends a draft.
    recorded = [str(call) for call in service.mock_calls]
    assert all(".create(" not in call for call in recorded), recorded
    assert all(".send(" not in call for call in recorded), recorded


# ---------------------------------------------------------------------------
# HttpError helpers for the retry tests
# ---------------------------------------------------------------------------
def _http_error(status):
    """Build an HttpError whose ``resp.status`` is ``status``.

    ``_is_transient`` reads ``exc.resp.status`` first, so we give the response a
    ``status`` attribute (and a ``reason`` for readable ``str(exc)``). Content
    is empty bytes, matching how the Gmail client constructs these errors.
    """
    resp = mock.Mock()
    resp.status = status
    resp.reason = f"status {status}"
    return HttpError(resp=resp, content=b"")


# ---------------------------------------------------------------------------
# Property 4: bounded retry with mocked backoff
# ---------------------------------------------------------------------------
@settings(max_examples=100, deadline=None)
@given(f=st.integers(min_value=0, max_value=5))
def test_retry_bounded_attempts_with_mocked_backoff(f):
    """Feature: outreach-app-v1-1, Property 4: Retry performs a bounded number
    of attempts with mocked backoff.

    For any number ``f`` of injected transient failures preceding a success,
    ``create_draft_with_retry`` performs ``min(f + 1, 3)`` create attempts,
    obtains every backoff delay through the injected ``sleep`` following the
    schedule ``[1, 2, ...]`` (i.e. ``2 ** (attempt - 1)``), returns the success
    value when ``f < 3``, and re-raises the last transient error when
    ``f >= 3``.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4.
    """
    max_attempts = 3
    success_sentinel = {"id": "drafts/created"}

    # f transient 5xx failures, then a success. The success is only reached if
    # f is within the attempt budget.
    side_effect = [_http_error(503) for _ in range(f)] + [success_sentinel]

    sleep = mock.Mock(name="sleep")

    with mock.patch.object(
        outreach_drafts, "create_draft", side_effect=side_effect
    ) as mock_create:
        expected_attempts = min(f + 1, max_attempts)

        if f < max_attempts:
            result = outreach_drafts.create_draft_with_retry(
                mock.sentinel.service, {"raw": "x"}, sleep=sleep
            )
            assert result is success_sentinel
        else:
            # All allowed attempts raise a transient error → last one re-raised.
            with pytest.raises(HttpError):
                outreach_drafts.create_draft_with_retry(
                    mock.sentinel.service, {"raw": "x"}, sleep=sleep
                )

        # Exactly min(f + 1, max_attempts) create attempts were made.
        assert mock_create.call_count == expected_attempts

        # One sleep per retry (i.e. per attempt except the last), following the
        # exponential schedule 1, 2, 4, ...
        expected_delays = [2 ** i for i in range(expected_attempts - 1)]
        assert [c.args[0] for c in sleep.call_args_list] == expected_delays


# ---------------------------------------------------------------------------
# Task 4.5: deterministic example cases
# ---------------------------------------------------------------------------
def test_non_transient_httperror_propagates_immediately_without_sleep():
    """A non-transient HttpError (400) propagates on the first attempt.

    Exactly one create attempt is made and ``sleep`` is never called.

    _Requirements: 5.1, 5.3, 5.4._
    """
    sleep = mock.Mock(name="sleep")

    with mock.patch.object(
        outreach_drafts, "create_draft", side_effect=_http_error(400)
    ) as mock_create:
        with pytest.raises(HttpError):
            outreach_drafts.create_draft_with_retry(
                mock.sentinel.service, {"raw": "x"}, sleep=sleep
            )

    assert mock_create.call_count == 1
    sleep.assert_not_called()


def test_non_transient_valueerror_propagates_immediately_without_sleep():
    """A non-HttpError exception (ValueError) propagates immediately.

    A ValueError is not classified as transient, so it is raised on the first
    attempt with no retry and no sleep.

    _Requirements: 5.1, 5.3, 5.4._
    """
    sleep = mock.Mock(name="sleep")
    boom = ValueError("bad message body")

    with mock.patch.object(
        outreach_drafts, "create_draft", side_effect=boom
    ) as mock_create:
        with pytest.raises(ValueError):
            outreach_drafts.create_draft_with_retry(
                mock.sentinel.service, {"raw": "x"}, sleep=sleep
            )

    assert mock_create.call_count == 1
    sleep.assert_not_called()


def test_single_transient_then_success_sleeps_once_with_one_second():
    """A single 503 then success → 2 attempts and one 1-second backoff.

    _Requirements: 5.1, 5.3, 5.4._
    """
    sleep = mock.Mock(name="sleep")
    success_sentinel = {"id": "drafts/created"}
    side_effect = [_http_error(503), success_sentinel]

    with mock.patch.object(
        outreach_drafts, "create_draft", side_effect=side_effect
    ) as mock_create:
        result = outreach_drafts.create_draft_with_retry(
            mock.sentinel.service, {"raw": "x"}, sleep=sleep
        )

    assert result is success_sentinel
    assert mock_create.call_count == 2
    sleep.assert_called_once_with(1)
