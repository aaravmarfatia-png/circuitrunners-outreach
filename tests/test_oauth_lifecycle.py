"""Example / integration tests for the OAuth lifecycle in ``get_credentials()``.

These are deterministic branch tests (not property tests) covering the OAuth
2.0 authentication lifecycle described in the design's "Authentication" section
and Requirement 3. All network and browser interaction is avoided by
monkeypatching the module-level path constants (``CREDENTIALS_FILE`` /
``TOKEN_FILE``) onto tmp paths and by patching the Google auth library entry
points (``InstalledAppFlow``, ``Credentials``, ``Request``) on the
``outreach_drafts`` module with ``unittest.mock``.

Covered branches:

  * Missing/invalid ``credentials.json`` terminates before any draft (Req 3.3):
    no token file and no credentials file -> ``get_credentials`` raises
    ``SystemExit``; a present-but-unparseable credentials file (parse error)
    likewise raises ``SystemExit``.
  * OAuth denial/failure terminates before any draft (Req 3.7): the
    installed-app flow's ``run_local_server`` raising is terminal and raises
    ``SystemExit``.
  * Expired-token refresh proceeds without prompting (Req 3.6): an expired
    token that carries a refresh token is refreshed silently and the
    interactive ``InstalledAppFlow`` is never invoked.
  * Token caching round-trip persists and reuses the token (Req 3.5): a
    successful flow writes the token to ``TOKEN_FILE``, and a later run loads
    that cached token without running the flow again.

``get_credentials()`` performs no draft/service calls itself, so "no draft is
created on fail-fast paths" is asserted structurally: ``SystemExit`` is raised
before the function returns credentials, and (where relevant) the interactive
flow is asserted to have / not have been invoked.
"""
import os
from unittest import mock

import pytest

import outreach_drafts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _point_paths_at_tmp(monkeypatch, tmp_path, *, token_name="token.json",
                        creds_name="credentials.json"):
    """Repoint the module-level path constants at the pytest tmp dir.

    Returns the (token_path, creds_path) strings. Neither file is created here;
    individual tests create whichever files their branch requires so the
    absence/presence checks in get_credentials take the intended path.
    """
    token_path = os.path.join(str(tmp_path), token_name)
    creds_path = os.path.join(str(tmp_path), creds_name)
    monkeypatch.setattr(outreach_drafts, "TOKEN_FILE", token_path)
    monkeypatch.setattr(outreach_drafts, "CREDENTIALS_FILE", creds_path)
    return token_path, creds_path


# ---------------------------------------------------------------------------
# Req 3.3 — missing / invalid credentials.json terminates before any draft
# ---------------------------------------------------------------------------
def test_missing_credentials_file_terminates(monkeypatch, tmp_path):
    """No cached token and no credentials.json -> SystemExit (Req 3.3).

    With neither TOKEN_FILE nor CREDENTIALS_FILE present, get_credentials must
    log and terminate (raise SystemExit) before any draft is created. The
    interactive flow must never be reached because the credentials file is
    absent.

    Validates: Requirements 3.3.
    """
    token_path, creds_path = _point_paths_at_tmp(monkeypatch, tmp_path)
    # Neither file exists -> the "no valid creds + missing credentials.json"
    # branch is taken.
    assert not os.path.exists(token_path)
    assert not os.path.exists(creds_path)

    # Guard: the flow must not even be constructed when credentials.json is
    # missing, so patch it to blow up if it ever gets called.
    with mock.patch.object(
        outreach_drafts, "InstalledAppFlow"
    ) as mock_flow_cls:
        mock_flow_cls.from_client_secrets_file.side_effect = AssertionError(
            "InstalledAppFlow must not run when credentials.json is missing"
        )
        with pytest.raises(SystemExit):
            outreach_drafts.get_credentials()

    # No token file should have been written on the fail-fast path.
    assert not os.path.exists(token_path)


def test_unparseable_credentials_file_terminates(monkeypatch, tmp_path):
    """A present-but-unparseable credentials.json -> SystemExit (Req 3.3).

    When credentials.json exists but cannot be parsed as valid OAuth client
    configuration, from_client_secrets_file raises ValueError, which
    get_credentials treats as terminal (SystemExit) before any draft.

    Validates: Requirements 3.3.
    """
    token_path, creds_path = _point_paths_at_tmp(monkeypatch, tmp_path)
    # Create a dummy (present but not valid) credentials file so the existence
    # check passes and parsing is attempted.
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write("not valid json")
    assert not os.path.exists(token_path)
    assert os.path.exists(creds_path)

    with mock.patch.object(
        outreach_drafts, "InstalledAppFlow"
    ) as mock_flow_cls:
        # Simulate the library rejecting the malformed client config.
        mock_flow_cls.from_client_secrets_file.side_effect = ValueError(
            "malformed client secrets"
        )
        with pytest.raises(SystemExit):
            outreach_drafts.get_credentials()

        # Parsing was attempted, but no server flow ran (parse failed first).
        mock_flow_cls.from_client_secrets_file.assert_called_once()

    assert not os.path.exists(token_path)


# ---------------------------------------------------------------------------
# Req 3.7 — OAuth authorization failure / denial terminates before any draft
# ---------------------------------------------------------------------------
def test_oauth_denial_terminates(monkeypatch, tmp_path):
    """Flow authorization failure/denial -> SystemExit (Req 3.7).

    With no cached token but a present credentials.json, the interactive flow
    runs. If run_local_server raises (e.g. the user denies consent),
    get_credentials logs and terminates (SystemExit) before any draft.

    Validates: Requirements 3.7.
    """
    token_path, creds_path = _point_paths_at_tmp(monkeypatch, tmp_path)
    # A present (dummy/placeholder) credentials file so the flow is attempted.
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write("{}")
    assert not os.path.exists(token_path)

    with mock.patch.object(
        outreach_drafts, "InstalledAppFlow"
    ) as mock_flow_cls:
        mock_flow = mock.Mock()
        # Simulate the user denying authorization / the flow failing.
        mock_flow.run_local_server.side_effect = Exception("access_denied")
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        with pytest.raises(SystemExit):
            outreach_drafts.get_credentials()

        # The flow was constructed and the local-server authorization attempted.
        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            creds_path, outreach_drafts.SCOPES
        )
        mock_flow.run_local_server.assert_called_once()

    # No token persisted when authorization fails.
    assert not os.path.exists(token_path)


# ---------------------------------------------------------------------------
# Req 3.6 — expired-but-refreshable token is refreshed silently, no prompt
# ---------------------------------------------------------------------------
def test_expired_token_refreshes_without_prompting(monkeypatch, tmp_path):
    """An expired token with a refresh token is refreshed, no flow (Req 3.6).

    A cached token that is expired but carries a refresh token is refreshed in
    place via creds.refresh(Request()) and used without invoking the
    interactive InstalledAppFlow.

    Validates: Requirements 3.6.
    """
    token_path, creds_path = _point_paths_at_tmp(monkeypatch, tmp_path)
    # TOKEN_FILE must exist so the from_authorized_user_file load path is taken.
    with open(token_path, "w", encoding="utf-8") as f:
        f.write("{}")

    # Build a mock Credentials object: expired, but with a refresh token, and
    # which becomes valid once refresh() is called.
    mock_creds = mock.Mock()
    mock_creds.expired = True
    mock_creds.refresh_token = "a-refresh-token"
    mock_creds.valid = False
    mock_creds.to_json.return_value = "{}"

    def _refresh(_request):
        # After a successful refresh the credentials are valid; this both
        # simulates the library behavior and lets the "not valid" branch be
        # skipped so the interactive flow is never entered.
        mock_creds.expired = False
        mock_creds.valid = True

    mock_creds.refresh.side_effect = _refresh

    with mock.patch.object(
        outreach_drafts, "Credentials"
    ) as mock_creds_cls, mock.patch.object(
        outreach_drafts, "Request"
    ) as mock_request_cls, mock.patch.object(
        outreach_drafts, "InstalledAppFlow"
    ) as mock_flow_cls:
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        result = outreach_drafts.get_credentials()

        # The cached token was loaded and refreshed silently.
        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            token_path, outreach_drafts.SCOPES
        )
        mock_creds.refresh.assert_called_once()
        # refresh was called with a Request() transport instance.
        mock_request_cls.assert_called_once_with()
        # No interactive authorization ever happened (no prompting).
        mock_flow_cls.from_client_secrets_file.assert_not_called()

    # The refreshed credentials are returned and persisted back to TOKEN_FILE.
    assert result is mock_creds
    assert os.path.exists(token_path)


# ---------------------------------------------------------------------------
# Req 3.5 — token caching round-trip: persist after flow, reuse on next run
# ---------------------------------------------------------------------------
def test_successful_flow_persists_token(monkeypatch, tmp_path):
    """A successful flow writes the token to TOKEN_FILE (Req 3.5).

    With no cached token but a present credentials.json, a successful
    authorization returns valid credentials whose to_json() is written to
    TOKEN_FILE, so later runs can reuse it.

    Validates: Requirements 3.5.
    """
    token_path, creds_path = _point_paths_at_tmp(monkeypatch, tmp_path)
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write("{}")
    assert not os.path.exists(token_path)

    token_json = '{"token": "cached-value"}'
    mock_creds = mock.Mock()
    mock_creds.valid = True
    mock_creds.to_json.return_value = token_json

    with mock.patch.object(
        outreach_drafts, "InstalledAppFlow"
    ) as mock_flow_cls:
        mock_flow = mock.Mock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        result = outreach_drafts.get_credentials()

        mock_flow.run_local_server.assert_called_once()

    assert result is mock_creds
    # The token file now exists and holds the credentials' JSON.
    assert os.path.exists(token_path)
    with open(token_path, encoding="utf-8") as f:
        assert f.read() == token_json


def test_cached_token_reused_without_flow(monkeypatch, tmp_path):
    """A valid cached token is reused; the flow is not run (Req 3.5).

    Completes the caching round-trip: given a present TOKEN_FILE that loads to
    already-valid credentials, get_credentials loads and returns them without
    invoking the interactive InstalledAppFlow.

    Validates: Requirements 3.5.
    """
    token_path, creds_path = _point_paths_at_tmp(monkeypatch, tmp_path)
    # TOKEN_FILE present -> from_authorized_user_file load path.
    with open(token_path, "w", encoding="utf-8") as f:
        f.write('{"token": "cached-value"}')

    mock_creds = mock.Mock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.refresh_token = None
    mock_creds.to_json.return_value = '{"token": "cached-value"}'

    with mock.patch.object(
        outreach_drafts, "Credentials"
    ) as mock_creds_cls, mock.patch.object(
        outreach_drafts, "InstalledAppFlow"
    ) as mock_flow_cls:
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        result = outreach_drafts.get_credentials()

        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            token_path, outreach_drafts.SCOPES
        )
        # A valid cached token means no interactive authorization.
        mock_flow_cls.from_client_secrets_file.assert_not_called()

    assert result is mock_creds
