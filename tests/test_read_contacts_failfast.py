"""Example (deterministic) tests for read_contacts fail-fast branches.

These cover the two whole-file, terminal conditions of ``read_contacts`` that
cause the run to fail-fast before any Contact_Row is processed:

  * Missing/unopenable Contacts_File: ``read_contacts`` does not catch the open
    error, so ``FileNotFoundError`` propagates to ``main()`` (which logs the
    file as unavailable and terminates) (Req 2.6).
  * Header-only Contacts_File: a file containing only the header row and no data
    rows causes ``read_contacts`` to raise ``ValueError`` signalling the "no
    contacts" terminal case to ``main()`` (Req 2.7).

These are example tests, not property tests.
"""
import os

import pytest

import outreach_drafts

# The header row every Contacts_File starts with (csv.DictReader consumes it as
# field names). Used to build the header-only file for the Req 2.7 case.
HEADER_ROW = "Recipient_Email,Recipient_Name,Sender_Name,School_Name,Template_Type"


def test_missing_file_raises_file_not_found(tmp_path):
    """A non-existent Contacts_File path raises FileNotFoundError.

    read_contacts does not catch the open error; the FileNotFoundError
    propagates so main() can log the file as unavailable and terminate before
    processing any Contact_Row.

    Validates: Requirements 2.6.
    """
    # A path under the pytest tmp dir that was never created, so open() fails.
    missing_path = os.path.join(str(tmp_path), "does_not_exist.csv")
    assert not os.path.exists(missing_path)

    with pytest.raises(FileNotFoundError):
        outreach_drafts.read_contacts(missing_path)


def test_header_only_file_raises_value_error(tmp_path):
    """A file with only the header row and no data rows raises ValueError.

    csv.DictReader consumes the header as field names, leaving zero data rows,
    which read_contacts treats as the terminal "no contacts" case so main() can
    log it and terminate before processing any Contact_Row.

    Validates: Requirements 2.7.
    """
    # Header row plus a trailing newline, but no data rows.
    contacts_file = tmp_path / "contacts.csv"
    contacts_file.write_text(HEADER_ROW + "\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        outreach_drafts.read_contacts(str(contacts_file))

    # The message should mention that there are no contacts.
    assert "no contacts" in str(exc_info.value).lower()
