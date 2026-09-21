"""Property-based test for contacts reading (read_contacts).

Feature: gmail-outreach-drafts, Property 12: Header row is excluded and every
data row is read.

Validates: Requirements 2.2, 2.3.

For any CSV with a header row followed by N (N >= 1) data rows, reading the
Contacts_File returns exactly N Contact_Row records and never processes the
header row as a contact.
"""
import csv
import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# The five columns of a Contact_Row, in file order. The first CSV row is the
# header (these exact names) and is consumed by csv.DictReader as field names,
# so it must never appear as a returned data record (Req 2.2).
COLUMNS = [
    "Recipient_Email",
    "Recipient_Name",
    "Sender_Name",
    "School_Name",
    "Template_Type",
]

# Field-value strategy. Any text is safe because we write rows with csv.writer,
# which quotes/escapes commas, quotes, and newlines correctly. We exclude the
# NUL character (invalid in CSV files) and carriage return / newline, which csv
# writers may normalise on round-trip and are not relevant to this property. We
# also exclude the surrogate category ("Cs"): lone surrogate code points such
# as '\ud800' cannot be encoded as UTF-8 and would raise UnicodeEncodeError when
# written to the file, which is unrelated to the property under test.
_field_text = st.text(
    alphabet=st.characters(
        blacklist_characters="\x00\r\n", blacklist_categories=("Cs",)
    ),
    min_size=0,
    max_size=40,
)

# One data row is a value for each of the five columns.
_data_row = st.lists(_field_text, min_size=len(COLUMNS), max_size=len(COLUMNS))

# At least one data row so read_contacts does not raise the no-contacts
# ValueError (Req 2.7); the property under test concerns the N >= 1 case.
_data_rows = st.lists(_data_row, min_size=1, max_size=8)


@settings(max_examples=100)
@given(rows=_data_rows)
def test_header_excluded_and_every_data_row_read(rows):
    """Feature: gmail-outreach-drafts, Property 12.

    Writing a header row plus N data rows and reading the file back yields
    exactly N records; the header row is never returned as a data record and
    each returned dict carries the generated data, not the column names.

    Validates: Requirements 2.2, 2.3.
    """
    n = len(rows)

    # Write the header + N data rows using csv.writer so any commas, quotes, or
    # embedded characters in the generated values are escaped safely. We use a
    # NamedTemporaryFile (not the tmp_path fixture) so each Hypothesis example
    # gets its own file rather than reusing a single function-scoped path.
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", newline="", encoding="utf-8", delete=False
    )
    try:
        writer = csv.writer(tmp)
        writer.writerow(COLUMNS)  # header row (Req 2.2)
        for row in rows:
            writer.writerow(row)
        tmp.close()

        records = outreach_drafts.read_contacts(tmp.name)
    finally:
        os.unlink(tmp.name)

    # Exactly N records are returned: every data row is read (Req 2.3) and the
    # header row is excluded from the count (Req 2.2).
    assert len(records) == n

    # The header row is never present as a data record. csv.DictReader maps each
    # data row to a dict keyed by the header names, so a returned record whose
    # values equal the column names would mean the header leaked into the data.
    header_as_values = COLUMNS
    for record in records:
        assert list(record.values()) != header_as_values

    # Each returned record carries the generated data, not the column names:
    # the value under each column key equals the value we wrote for that column.
    for expected, record in zip(rows, records):
        for column, value in zip(COLUMNS, expected):
            assert record[column] == value
