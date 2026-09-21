"""Deterministic end-to-end integration test for main() (Task 10.7).

Drives ``outreach_drafts.main()`` from a real temporary ``contacts.csv`` all the
way through to a mocked Gmail service, verifying the whole workflow wires
together: valid rows produce exactly one ``users().drafts().create`` call each,
the failing row produces none, no send operation is ever invoked, and the
printed Run_Summary reports conserved success/failure/total counts.

**Validates: Requirements 8.3, 10.2, 10.3, 10.4**

Setup follows approach (a) from the task: a real temp CSV is written and
``outreach_drafts.CONTACTS_FILE`` is monkeypatched to it, while
``outreach_drafts.ATTACHMENTS_DIR`` is pointed at the project's real
``attachments/`` folder so the Elementary row's image files resolve. The Gmail
service is mocked end to end (credentials, service, sender address, and
``time.sleep``), and ``create_draft`` runs for real against the mock so
``users().drafts().create().execute()`` is exercised as a mock — proving main()
calls it with the right structure and never calls a send operation.
"""
import base64
import os
from email import message_from_bytes
from unittest import mock

import outreach_drafts


# The project's real attachments folder ships robot-demo1/2/3/5.jpg, which the
# Elementary row references; pointing ATTACHMENTS_DIR here lets those files
# resolve so the Elementary row reaches the draft-creation call.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_ATTACHMENTS_DIR = os.path.join(PROJECT_ROOT, "attachments")

# A fixed, small contacts file mixing template types plus one failing row.
# Rows 1-3 are valid (Elementary with attachments, Response, Post-Demo); row 4
# has an invalid Template_Type so validate_row rejects it — it must never reach
# create_draft and must be counted as a failure.
CSV_HEADER = "Recipient_Email,Recipient_Name,Sender_Name,School_Name,Template_Type"
CSV_ROWS = [
    "elem@example.com,Alice,Sam,Maple Elementary,Elementary",
    "resp@example.com,Bob,Sam,Oak Middle,Response",
    "post@example.com,Carol,Sam,Pine School,Post-Demo",
    "bad@example.com,Dave,Sam,Birch School,NotARealType",
]
NUM_VALID_ROWS = 3
NUM_FAILED_ROWS = 1
NUM_TOTAL_ROWS = 4


def test_end_to_end_run_with_mocked_gmail_service(tmp_path, monkeypatch, capsys):
    """main() drafts every valid row, skips the failing row, and never sends.

    Validates Requirements 8.3 (success recorded per created draft), 10.2 (each
    row lands in exactly one outcome), 10.3 (Run_Summary printed once with all
    three counts) and 10.4 (successes + failures == total).
    """
    # --- Build a real temporary contacts.csv --------------------------------
    contacts_file = tmp_path / "contacts.csv"
    contacts_file.write_text("\n".join([CSV_HEADER, *CSV_ROWS]) + "\n", encoding="utf-8")

    # --- Mock the Gmail service end to end ----------------------------------
    # A fresh MagicMock records every call. create_draft runs for real against
    # it, so users().drafts().create().execute() is a mock invocation.
    mock_service = mock.MagicMock(name="gmail_service")

    # Point the reader at the real temp CSV (approach a) and attachments at the
    # real folder so the Elementary row's images resolve.
    monkeypatch.setattr(outreach_drafts, "CONTACTS_FILE", str(contacts_file))
    monkeypatch.setattr(outreach_drafts, "ATTACHMENTS_DIR", REAL_ATTACHMENTS_DIR)

    # Stub the auth + service + sender + sleep so no live API or delay occurs;
    # create_draft itself is NOT stubbed, so it exercises the real call shape.
    monkeypatch.setattr(outreach_drafts, "get_credentials", lambda: mock.sentinel.creds)
    monkeypatch.setattr(outreach_drafts, "build_service", lambda creds: mock_service)
    monkeypatch.setattr(
        outreach_drafts, "get_sender_address", lambda service: "me@circuitrunners.com"
    )
    monkeypatch.setattr(outreach_drafts.time, "sleep", lambda seconds: None)

    # --- Run the whole workflow ---------------------------------------------
    outreach_drafts.main()

    # --- Assert draft creation happened once per VALID row ------------------
    # users().drafts().create is called once for each of the 3 valid rows and
    # never for the failing row (Req 8.3, 10.2).
    create = mock_service.users.return_value.drafts.return_value.create
    assert create.call_count == NUM_VALID_ROWS

    # --- Assert no send operation was ever invoked --------------------------
    # Stringifying the recorded call chain and checking ".send(" never appears
    # proves neither users().messages().send nor users().drafts().send ran.
    recorded_calls = [str(call) for call in mock_service.mock_calls]
    assert all(".send(" not in call for call in recorded_calls), (
        f"main() must never invoke a send operation; recorded calls: {recorded_calls}"
    )

    # --- Assert the printed Run_Summary conserves the counts ----------------
    out = capsys.readouterr().out
    assert "=== Run Summary ===" in out
    # The summary is printed exactly once (Req 10.3).
    assert out.count("=== Run Summary ===") == 1
    assert f"Successful drafts: {NUM_VALID_ROWS}" in out
    assert f"Failed / skipped rows: {NUM_FAILED_ROWS}" in out
    assert f"Total contacts processed: {NUM_TOTAL_ROWS}" in out
    # successes + failures == total (Req 10.4).
    assert NUM_VALID_ROWS + NUM_FAILED_ROWS == NUM_TOTAL_ROWS

    # --- Decode one create() body to confirm To and Cc headers -------------
    # Each create call body is {"message": {"raw": <base64url>}}; decode the
    # first one and confirm the To header and the CC_RECIPIENTS Cc header are set.
    first_body = create.call_args_list[0].kwargs["body"]
    raw = first_body["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw.encode())
    mime = message_from_bytes(decoded)
    assert mime["To"] == "elem@example.com"
    for cc_addr in outreach_drafts.CC_RECIPIENTS:
        assert cc_addr in mime["Cc"]
    assert mime["From"] == "me@circuitrunners.com"
