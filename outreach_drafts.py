"""Gmail Outreach Drafts — CircuitRunners Robotics Team.

A Python 3.10+ command-line tool that reads a CSV of contacts, selects a message
template and image set based on each contact's Template_Type, fills in the
personalization placeholders, and creates a Gmail *draft* for every contact
through the Gmail API.

The script NEVER sends email. It requests only the ``gmail.compose`` OAuth scope
(which cannot send) and only ever calls ``users.drafts.create``. Every draft
also Cc's the two fixed team coordinators
(``ethan.xu@circuitrunners.com`` and ``melissa.amerault@circuitrunners.com``),
regardless of Template_Type.

================================================================================
Setup
================================================================================

1. Create a Google Cloud project
   - Visit https://console.cloud.google.com/.
   - Use the project dropdown at the top and choose "New Project".
   - Name it (e.g. "CircuitRunners Outreach") and click "Create".

2. Enable the Gmail API
   - With the project selected, open "APIs & Services -> Library".
   - Search for "Gmail API", open it, and click "Enable".

3. Configure the OAuth consent screen
   - Open "APIs & Services -> OAuth consent screen".
   - Choose "External" (or "Internal" for Google Workspace) and fill in the
     required app name and support email.
   - Add your own Google account as a "Test user" so you can authorize the app.

4. Obtain credentials.json
   - Open "APIs & Services -> Credentials".
   - Click "Create Credentials -> OAuth client ID".
   - Choose "Desktop app" as the application type and click "Create".
   - Download the client configuration and save it as ``credentials.json`` in
     this folder (next to this script). The requested scope is ``gmail.compose``
     only, which allows creating drafts but cannot send email.

5. Install dependencies
       pip install -r requirements.txt
   (For the test tooling: pip install -r requirements-dev.txt)

6. Prepare inputs
   - Edit ``contacts.csv``. Keep the header row exactly:
     Recipient_Email,Recipient_Name,Sender_Name,School_Name,Template_Type
     Template_Type must be one of Elementary, Middle, Response, or Post-Demo.
   - Replace the placeholder images in ``attachments/`` with real demo photos,
     keeping the file names robot-demo1.jpg, robot-demo2.jpg, robot-demo3.jpg,
     and robot-demo5.jpg.

7. Run
       python outreach_drafts.py
   On the first run a browser window opens to authorize the app; the resulting
   token is cached in ``token.json`` and reused on later runs. Review the
   created messages in Gmail's Drafts folder before sending them yourself.

================================================================================

NOTE: This file is a scaffold. The module constants, templates, and functions
(``create_message_with_attachments()``, ``create_draft()``, ``main()``, and the
supporting helpers) are added by subsequent implementation tasks.
"""

import base64  # base64url-encode the serialized MIME message for drafts.create (Req 7.6)
import csv  # standard-library CSV reader used to parse the Contacts_File (Req 2.1)
import logging  # console error logging for fail-fast auth conditions (Req 3.3, 3.7)
import os  # resolve attachment file paths (used by main() when building paths)
import os.path  # existence check for the cached TOKEN_FILE before loading it (Req 3.5)
import socket  # detect socket-level timeouts on Gmail API calls (Req 10.1)
import time  # rate-limit pause between drafts (Req 9.1)
from email.mime.image import MIMEImage  # image attachment parts (Req 7.3)
from email.mime.multipart import MIMEMultipart  # container message with body + images (Req 7.1)
from email.mime.text import MIMEText  # plain-text body part (Req 7.1)

# Google API client + OAuth 2.0 libraries used for authentication and Gmail access.
from googleapiclient.discovery import build  # build the Gmail service client once per run (Req 3.4)
from googleapiclient.errors import HttpError  # Gmail API request errors caught per row (Req 10.1)
from google.auth.transport.requests import Request  # silent token refresh transport (Req 3.6)
from google.oauth2.credentials import Credentials  # load/serialize the cached OAuth token (Req 3.5)
from google_auth_oauthlib.flow import InstalledAppFlow  # interactive installed-app authorization flow (Req 3.1, 3.2)

# Module-level logger used for console error logging. Fail-fast auth conditions
# (missing/invalid credentials.json, denied/failed authorization) are logged
# through this logger before the run is terminated (Req 3.3, 3.7).
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants and configuration defaults (editable)
# ---------------------------------------------------------------------------

# OAuth scope requested during authentication. ``gmail.compose`` grants the
# ability to create and manage drafts but CANNOT send email. This is the
# single most important guarantee of the tool: because no send scope is ever
# requested, the script is structurally incapable of sending mail. (Req 3.1)
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]  # draft-only; NO send scope

# Path to the OAuth 2.0 client configuration downloaded from Google Cloud
# Console. Read at authentication time; must sit next to this script. (Req 3.2)
CREDENTIALS_FILE = "credentials.json"

# Path where the authorized OAuth token is cached after the first successful
# authorization, so later runs reuse it without prompting again. (Req 3.5)
TOKEN_FILE = "token.json"

# Path to the CSV input file containing one outreach recipient per row. (Req 2.1)
CONTACTS_FILE = "contacts.csv"

# Local subfolder that stores the image files referenced by each template's
# attachment set. (Req 4.1, 4.2)
ATTACHMENTS_DIR = "attachments"

# Columns that every Contact_Row must contain with a non-empty, non-whitespace
# value; rows missing any of these are logged, skipped, and counted as failures.
# (Req 2.2, 2.4)
REQUIRED_FIELDS = ["Recipient_Email", "Recipient_Name", "Sender_Name",
                   "School_Name", "Template_Type"]

# The fixed team coordinators Cc'd on every draft regardless of Template_Type.
# Editable default; edit these addresses to change who receives copies. (Req 11.1)
CC_RECIPIENTS = ["ethan.xu@circuitrunners.com", "melissa.amerault@circuitrunners.com"]  # editable default, Cc'd on every draft

# Maximum time (seconds) to allow a Gmail API request before treating it as a
# failure for the current row. (Req 10.1)
API_TIMEOUT_SECONDS = 30

# Pause (seconds) inserted after every draft attempt to stay within Gmail API
# rate limits during large runs. (Req 9.1)
RATE_LIMIT_SECONDS = 1

# ---------------------------------------------------------------------------
# Verbatim Message_Body templates (Source-of-Truth)
# ---------------------------------------------------------------------------
# The four bodies below are copied character-for-character from the
# requirements' "Source-of-Truth Template Bodies" section. They MUST NOT be
# paraphrased or reworded — only the {{Recipient_Name}}, {{Sender_Name}}, and
# {{School_Name}} placeholders are substituted at render time. (Req 4.1–4.4)

# Elementary school outreach body. (Req 4.1)
ELEMENTARY_BODY = """Dear {{Recipient_Name}},

I hope this message finds you well. My name is {{Sender_Name}}, a member of Wheeler High School's CircuitRunners Robotics Team.

Each year, our team designs, builds, and programs robots for competitions, and we are passionate about inspiring younger students to explore the world of STEM. I’m reaching out today because we would love the opportunity to bring a robot demonstration to {{School_Name}}, either after school or during a STEM-related event. During the event, our team members would show and allow students to drive our robot as well as answer any questions about design, coding, engineering, and more.

Our goal is to promote STEM and curiosity within younger students by introducing them to robotics in an exciting and hands-on way. For reference, our team has hosted similar demos at several other elementary schools in the past, and I've attached a few pictures that showcase what it could look like.

Please let me know if this is something you or another teacher would be interested in. I'd be happy to work out the details and coordinate any additional plans with you. Thank you for your time and consideration!"""

# Middle school outreach body. (Req 4.2)
MIDDLE_BODY = """Dear {{Recipient_Name}},

I hope this message finds you well. My name is {{Sender_Name}}, a member of Wheeler High School's CircuitRunners Robotics Team.

Each year, our team designs, builds, and programs robots for competitions, and we are super passionate about inspiring students to explore the world of STEM. We would love the opportunity to bring a robot demonstration to {{School_Name}}, either after school or during a STEM-related event. During the event, our team members would show and allow students to drive our robot as well as answer any questions about design, coding, engineering, and more.

Our goal is to promote STEM and curiosity within students by introducing them to robotics in an exciting and hands-on way. For reference, our team has recently attended the Houston World Championships three times and have also hosted similar demos at several other middle schools. I've attached a few pictures of previous robot demonstrations to showcase what it could look like.

Please let me know if this is something you or another teacher would be interested in. I'd be happy to work out the details and coordinate any additional plans with you. Thank you for your time and consideration!"""

# Response / confirmation body (no attachments). (Req 4.3)
RESPONSE_BODY = """Dear {{Recipient_Name}},

Thank you for this invitation! We would love to attend {{School_Name}}, and we look forward to the event! Just as a heads up, we will need a 6x6 foot or larger area for our robot field, along with a nearby power outlet to charge our batteries. Other than that, please let me know if there is anything that we should prepare. I'll be sure to reach out to you a week before the event to confirm everything."""

# Post-demo follow-up / thank-you body (no attachments). Ends with the feedback
# form placeholder "[Insert Form Link]". (Req 4.4)
POST_DEMO_BODY = """Dear {{Recipient_Name}},

Thank you again for the opportunity to demonstrate our robots at {{School_Name}}! Our team had a lot of fun working with your students. I've attached a few photos we took during the event.

If you have any other opportunities or events in the future, please let me know, and our team would be happy to attend. We'd also appreciate it if you could fill out this brief feedback form: [Insert Form Link]"""

# ---------------------------------------------------------------------------
# Template registry — maps each Template_Type to its subject, body, and images
# ---------------------------------------------------------------------------
# TEMPLATES is the single lookup that drives per-contact content selection. For
# a given Contact_Row, main() looks up row["Template_Type"] here to obtain the
# subject line, the verbatim Message_Body, and the Attachment_Set for that type.
#
# Templating logic:
#   * "subject" and "body" both contain {{Recipient_Name}}, {{Sender_Name}},
#     and/or {{School_Name}} placeholders. render_template() applies the SAME
#     substitution to both at build time (Req 5.2, 6.4), so the subject is
#     personalized exactly like the body.
#   * The subject lines below are EDITABLE DEFAULTS defined in the script
#     (Req 5.1, 5.3): one subject per Template_Type, each carrying a
#     {{School_Name}} placeholder. Edit these strings to change the defaults.
#   * "attachments" is the Attachment_Set: image file names resolved relative
#     to ATTACHMENTS_DIR. Elementary and Middle carry demo photos; Response and
#     Post-Demo intentionally have no attachments (Req 4.1–4.4).
#   * Template_Type validation (validate_row) checks membership in this dict, so
#     the four keys below define the complete set of valid Template_Type values
#     (Req 1.6).
TEMPLATES = {
    # Elementary: outreach body + three demo photos. (Req 4.1, 5.1)
    "Elementary": {
        "subject": "Robot Demonstration Opportunity for {{School_Name}}",
        "body": ELEMENTARY_BODY,
        "attachments": ["robot-demo4.jpg", "robot-demo5.jpg"],
    },
    # Middle: outreach body + a different three-photo set. (Req 4.2, 5.1)
    "Middle": {
        "subject": "Robot Demonstration Opportunity for {{School_Name}}",
        "body": MIDDLE_BODY,
        "attachments": ["robot-demo4.jpg", "robot-demo5.jpg"],
    },
    # Response: confirmation reply, no attachments. (Req 4.3, 5.1)
    "Response": {
        "subject": "Re: Robot Demonstration at {{School_Name}}",
        "body": RESPONSE_BODY,
        "attachments": [],
    },
    # Post-Demo: thank-you follow-up, no attachments. (Req 4.4, 5.1)
    "Post-Demo": {
        "subject": "Thank You from CircuitRunners — {{School_Name}}",
        "body": POST_DEMO_BODY,
        "attachments": [],
    },
}

# ---------------------------------------------------------------------------
# Placeholder substitution — render_template(text, row)
# ---------------------------------------------------------------------------
def render_template(text: str, row: dict) -> str:
    """Substitute the supported personalization placeholders in ``text``.

    Replaces the three supported tokens with the matching Contact_Row field
    values:

        {{Recipient_Name}} -> row["Recipient_Name"]   (Req 6.1)
        {{Sender_Name}}    -> row["Sender_Name"]       (Req 6.2)
        {{School_Name}}    -> row["School_Name"]       (Req 6.3)

    Templating logic:
      * A single, order-independent pass of ``str.replace`` handles each token.
        Order does not matter because the three placeholder tokens are disjoint
        (none is a substring of another), so replacing one never creates or
        destroys another.
      * The same function is applied to BOTH the subject line and the message
        body with identical semantics, so personalization is consistent across
        the whole message (Req 5.2, 6.4). Callers pass a template's "subject"
        or "body" string as ``text``.
      * Only these three tokens are supported. Any other ``{{...}}`` text is
        left untouched (e.g. the "[Insert Form Link]" marker in the Post-Demo
        body is not a supported placeholder and is preserved verbatim).

    Args:
        text: A subject or body string that may contain the supported tokens.
        row: A Contact_Row dict providing Recipient_Name, Sender_Name, and
            School_Name values.

    Returns:
        The text with every supported placeholder replaced by its row value.
    """
    return (
        text.replace("{{Recipient_Name}}", row["Recipient_Name"])
        .replace("{{Sender_Name}}", row["Sender_Name"])
        .replace("{{School_Name}}", row["School_Name"])
    )


# ---------------------------------------------------------------------------
# Contacts reader — read_contacts(path)
# ---------------------------------------------------------------------------
def read_contacts(path: str) -> list[dict]:
    """Read the Contacts_File and return one dict per data row.

    Uses the standard-library :class:`csv.DictReader`, which treats the first
    row of the file as the header and maps each subsequent row to a dict keyed
    by those header names. The header row itself is therefore consumed as field
    names and never appears in the returned data (Req 2.1, 2.2). Every data row
    following the header is returned (Req 2.3), each as a dict with the columns
    ``Recipient_Email``, ``Recipient_Name``, ``Sender_Name``, ``School_Name``,
    and ``Template_Type``.

    Fail-fast semantics (whole-file problems terminate the run before any draft
    is created; per-row validation is handled separately by ``validate_row``):

      * Missing or unopenable file: this function does not catch the error. The
        ``open`` call raises ``FileNotFoundError`` (or another ``OSError`` such
        as ``PermissionError``) which propagates to ``main()``. ``main()`` logs
        that the Contacts_File is unavailable and terminates without processing
        any Contact_Row (Req 2.6).
      * Zero data rows after the header: this function raises ``ValueError`` with
        the message "Contacts file contains no contacts". ``main()`` treats this
        as terminal, logs that the file contains no contacts, and terminates
        without processing any Contact_Row (Req 2.7).

    Args:
        path: Filesystem path to the CSV Contacts_File.

    Returns:
        A list of Contact_Row dicts, one per data row, in file order.

    Raises:
        FileNotFoundError / OSError: If ``path`` does not exist or cannot be
            opened for reading (propagated for ``main()`` to log as unavailable).
        ValueError: If the file has a header but no data rows (signals the
            "no contacts" terminal case to ``main()``).
    """
    # ``newline=""`` is the documented csv module requirement so embedded
    # newlines inside quoted fields are handled correctly. Any failure to open
    # (missing file, permission error) propagates to main() as a terminal,
    # fail-fast condition (Req 2.6).
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)  # first row becomes field names (Req 2.2)
        rows = list(reader)         # every remaining row is a data row (Req 2.3)

    # A header-only file (or an entirely empty file) yields no data rows. Signal
    # this to main() as a terminal condition so it can log "no contacts" and
    # terminate without processing any Contact_Row (Req 2.7).
    if not rows:
        raise ValueError("Contacts file contains no contacts")

    return rows

# ---------------------------------------------------------------------------
# Per-row validation — validate_row(row, row_number)
# ---------------------------------------------------------------------------
def validate_row(row: dict, row_number: int) -> str | None:
    """Validate a single Contact_Row and return an error string, or None.

    Called by ``main()`` for each data row *before* a message is built. Unlike
    the whole-file, fail-fast checks in ``read_contacts``, a failure here is a
    per-row problem: ``main()`` logs the returned message, records the row as a
    failure, skips it, and continues with the remaining rows (Req 2.4, 2.5).

    Two conditions make a row invalid:

      * Missing required field (Req 2.4): any of ``REQUIRED_FIELDS``
        (Recipient_Email, Recipient_Name, Sender_Name, School_Name,
        Template_Type) is considered missing when its value is absent
        (``None``), an empty string, or whitespace-only. The
        ``value is None or value.strip() == ""`` test collapses all three cases:
        a truly absent key yields ``None`` from ``row.get``, and ``strip()``
        catches both empty and whitespace-only strings.
      * Invalid Template_Type (Req 2.5): the ``Template_Type`` value is not one
        of the keys defined in ``TEMPLATES`` (Elementary, Middle, Response,
        Post-Demo). Membership in ``TEMPLATES`` is the single source of truth
        for the valid set.

    The returned error string always includes a row identifier — the
    Recipient_Email when present, otherwise the row number — plus the specific
    cause (which field is missing, or the offending Template_Type value), so the
    log entry uniquely identifies the affected Contact_Row.

    Args:
        row: A Contact_Row dict as produced by :func:`read_contacts`.
        row_number: The 1-based position of the row among the data rows, used in
            the error identifier when Recipient_Email is unavailable.

    Returns:
        An error message string describing the first problem found, or ``None``
        if the row passes all checks.
    """
    # Reject the first required field that is absent, empty, or whitespace-only.
    # ``row.get(field)`` returns None for an absent key; ``value.strip() == ""``
    # then catches both empty and whitespace-only strings (Req 2.4).
    for field in REQUIRED_FIELDS:
        value = row.get(field)
        if value is None or value.strip() == "":
            return f"row {row_number} ({row.get('Recipient_Email', '?')}): missing field '{field}'"

    # All required fields are present; now confirm the Template_Type is one of
    # the four valid values (the keys of TEMPLATES) (Req 2.5).
    if row["Template_Type"] not in TEMPLATES:
        return f"row {row_number} ({row['Recipient_Email']}): invalid Template_Type '{row['Template_Type']}'"

    # Row is valid.
    return None

# ---------------------------------------------------------------------------
# MIME construction — create_message_with_attachments(...)
# ---------------------------------------------------------------------------
def create_message_with_attachments(sender, to, subject, body_text, attachment_paths, cc):
    """Build a base64url-encoded MIME message ready for ``drafts.create``.

    Assembles a multipart email for a single Contact_Row: the substituted
    Message_Body as a text part, the standard address/subject headers, and one
    image part per attachment file. The result is the exact request-body shape
    the Gmail draft creation call expects.

    Behavior (Requirement 7):
      * A ``MIMEMultipart`` container holds a ``MIMEText`` body part plus the
        headers ``Subject``, ``From`` (the authenticated sender address), and
        ``To`` (the Contact_Row Recipient_Email). (Req 7.1, 7.2, 7.4)
      * The ``Cc`` header is set to ``", ".join(cc)``. Callers always pass the
        ``CC_RECIPIENTS`` constant, so every message — regardless of
        Template_Type — carries the same fixed team-coordinator Cc addresses
        (Req 7.5, 11.2, 11.3). The Cc header is set INDEPENDENTLY of ``To``: the
        CC recipients are added in addition to the Recipient_Email and never
        replace it (Req 11.4).
      * For each path in ``attachment_paths`` the file bytes are read and
        attached as a ``MIMEImage`` part (Req 7.3). Opening a missing file with
        ``open(path, "rb")`` naturally raises ``FileNotFoundError``; that
        exception is allowed to propagate so ``main()`` can log the missing
        attachment, skip the row without creating a draft, and continue with the
        remaining rows (Req 7.7). An empty ``attachment_paths`` list (Response,
        Post-Demo) yields a message with only the text part.
      * The complete message is serialized and base64url-encoded into a single
        raw string: ``base64.urlsafe_b64encode(msg.as_bytes()).decode()``
        (Req 7.6). The return value ``{"raw": encoded}`` is the shape the draft
        body expects.

    Args:
        sender: The authenticated account's email address (``From`` header).
        to: The Contact_Row Recipient_Email (``To`` header).
        subject: The already-substituted Subject_Line for the row.
        body_text: The already-substituted Message_Body for the row.
        attachment_paths: Filesystem paths to the image files to attach; may be
            empty for templates with no Attachment_Set.
        cc: A list of Cc addresses (the ``CC_RECIPIENTS`` constant), joined onto
            the ``Cc`` header of every message.

    Returns:
        A dict ``{"raw": <base64url string>}`` ready to submit to
        ``users.drafts.create``.

    Raises:
        FileNotFoundError: If any path in ``attachment_paths`` does not exist,
            so ``main()`` can skip the offending Contact_Row (Req 7.7).
    """
    # Multipart container that carries the text body plus any image parts. (Req 7.1)
    message = MIMEMultipart()
    message["Subject"] = subject   # substituted Subject_Line (Req 7.1)
    message["From"] = sender        # authenticated account address (Req 7.2)
    message["To"] = to              # Contact_Row Recipient_Email (Req 7.4)

    # Cc the fixed team coordinators on every message. Joining with ", " builds
    # a single RFC-compliant Cc header. This is set on its own header, separate
    # from "To", so the CC recipients are ADDED to the recipient set and do not
    # replace the To recipient (Req 7.5, 11.2, 11.3, 11.4).
    message["Cc"] = ", ".join(cc)

    # Attach the substituted Message_Body as a plain-text part. (Req 7.1)
    message.attach(MIMEText(body_text, "plain"))

    # Attach one image part per file in the Attachment_Set. Reading a missing
    # file raises FileNotFoundError, which propagates to main() so the row is
    # skipped without a draft (Req 7.3, 7.7).
    for path in attachment_paths:
        with open(path, "rb") as image_file:
            image_part = MIMEImage(image_file.read())
        message.attach(image_part)

    # Serialize the whole MIME message and base64url-encode it into the single
    # raw string the draft request expects. (Req 7.6)
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": encoded}

# ---------------------------------------------------------------------------
# Authentication — get_credentials()
# ---------------------------------------------------------------------------
def get_credentials() -> "Credentials":
    """Return authorized OAuth 2.0 credentials for the Gmail API.

    Implements the full OAuth lifecycle described in the design's
    "Authentication" section, returning a single :class:`Credentials` object
    that ``main()`` uses to build one Gmail service reused for the whole run
    (Req 3.4). The requested scope is exactly ``SCOPES`` (``gmail.compose``),
    which grants draft creation but never send capability (Req 3.1).

    Lifecycle (in order):

      1. **Load cached token.** If ``TOKEN_FILE`` exists, load credentials from
         it via ``Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)``
         (Req 3.5).
      2. **Silent refresh.** If the loaded credentials are present but expired
         *and* carry a refresh token, refresh them in place via
         ``creds.refresh(Request())`` without prompting the user (Req 3.6).
      3. **Interactive authorization.** If no valid credentials are available
         (no cached token, or a token that is expired without a usable refresh
         token), run the installed-app flow. Before doing so, ``CREDENTIALS_FILE``
         must exist and parse as a valid OAuth client configuration; if it is
         missing or unparseable, log the error and terminate before any draft is
         created (Req 3.3). When present, run
         ``InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
         .run_local_server(port=0)`` (Req 3.1, 3.2). If the flow raises or the
         user denies authorization, log the failure and terminate before any
         draft is created (Req 3.7).
      4. **Persist token.** After a successful authorization or refresh, write
         the credentials back to ``TOKEN_FILE`` via ``creds.to_json()`` so later
         runs reuse the cached token without prompting (Req 3.5).

    Fail-fast is implemented by logging the cause through the module logger and
    raising :class:`SystemExit`, guaranteeing that no ``read_contacts`` call or
    draft creation runs when authentication cannot be established (Req 3.3, 3.7).

    Returns:
        Authorized :class:`google.oauth2.credentials.Credentials` valid for the
        ``gmail.compose`` scope, reused for the entire run (Req 3.4).

    Raises:
        SystemExit: If ``credentials.json`` is missing or cannot be parsed as a
            valid OAuth client configuration (Req 3.3), or if OAuth
            authorization fails or is denied (Req 3.7). In every terminal case
            the run ends before any draft is created.
    """
    creds = None

    # 1. Load the cached token if a previous run persisted one (Req 3.5). The
    #    token file, when present, holds the authorized-user JSON that
    #    Credentials.from_authorized_user_file reconstructs into a Credentials
    #    object scoped to SCOPES.
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # 2. If we have credentials that are simply expired but hold a refresh
    #    token, refresh them silently without prompting the user (Req 3.6).
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    # 3. If we still don't have valid credentials, we must run the interactive
    #    authorization flow. This covers both "no cached token" and "expired
    #    token without a usable refresh token".
    if not creds or not creds.valid:
        # credentials.json must exist and parse as a valid OAuth client config.
        # A missing or unparseable file is a terminal setup error: log it and
        # terminate before any draft is created (Req 3.3).
        if not os.path.exists(CREDENTIALS_FILE):
            logger.error(
                "OAuth client configuration '%s' is missing. Cannot authenticate; "
                "terminating before creating any draft.",
                CREDENTIALS_FILE,
            )
            raise SystemExit(1)

        try:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        except (ValueError, KeyError) as exc:
            # from_client_secrets_file raises when the file is not valid OAuth
            # client configuration (malformed JSON / missing required keys).
            # Treat this as the same terminal condition as a missing file (Req 3.3).
            logger.error(
                "OAuth client configuration '%s' could not be parsed as a valid "
                "client configuration (%s). Terminating before creating any draft.",
                CREDENTIALS_FILE,
                exc,
            )
            raise SystemExit(1)

        # Run the installed-app authorization flow on an ephemeral local port
        # (Req 3.1, 3.2). If the user denies authorization or the flow fails for
        # any reason, log the failure and terminate before any draft (Req 3.7).
        try:
            creds = flow.run_local_server(port=0)
        except SystemExit:
            # Never swallow a deliberate fail-fast exit raised elsewhere.
            raise
        except Exception as exc:  # noqa: BLE001 - any flow error is terminal (Req 3.7)
            logger.error(
                "OAuth authorization failed or was denied (%s). Terminating "
                "before creating any draft.",
                exc,
            )
            raise SystemExit(1)

    # 4. Persist the token after a successful authorization or refresh so future
    #    runs reuse it without prompting (Req 3.5).
    with open(TOKEN_FILE, "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())

    # Return the single Credentials object for reuse across the whole run (Req 3.4).
    return creds

# ---------------------------------------------------------------------------
# Gmail service and sender address
# ---------------------------------------------------------------------------
def build_service(creds):
    """Build the Gmail API service client once for the whole run.

    Constructs a single Gmail API service object from the authorized OAuth
    credentials returned by :func:`get_credentials`. Per the design, this
    service is created exactly once in ``main()`` and passed to
    :func:`create_draft` for every Contact_Row, so the one authorized session
    is reused across the entire run rather than rebuilt per draft (Req 3.4).

    Args:
        creds: Authorized :class:`google.oauth2.credentials.Credentials` scoped
            to ``gmail.compose`` (from :func:`get_credentials`).

    Returns:
        A Gmail API service resource (``googleapiclient.discovery.Resource``)
        for the ``gmail`` API, version ``v1``, ready for
        ``users().drafts().create`` and ``users().getProfile`` calls.
    """
    # Build the "gmail" / "v1" service bound to the authorized credentials. The
    # same object is reused for every draft during the run (Req 3.4).
    return build("gmail", "v1", credentials=creds)


def get_sender_address(service) -> str:
    """Return the authenticated account's email address for the From header.

    Queries the Gmail profile of the authenticated user (``userId="me"``) and
    returns its ``emailAddress`` field. This address is used as the ``From``
    header of every constructed MIME message (Req 7.2).

    Args:
        service: The Gmail API service built by :func:`build_service`.

    Returns:
        The authenticated account's email address as a string.
    """
    # getProfile(userId="me") returns the authenticated user's profile; the
    # emailAddress field is the account's own address used as the sender (Req 7.2).
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]

# ---------------------------------------------------------------------------
# Draft creation — create_draft(service, message_body)
# ---------------------------------------------------------------------------
def create_draft(service, message_body):
    """Create a Gmail draft from an already-built message and return it.

    This is the tool's single point of contact with Gmail's write API, and it
    is deliberately draft-only. It calls exactly one Gmail method,
    ``users().drafts().create``, and NEVER any send operation
    (``users().messages().send`` or ``users().drafts().send``). Combined with
    the draft-only ``gmail.compose`` scope requested in :data:`SCOPES`, this
    guarantees the script is structurally incapable of sending mail
    (Req 8.1, 8.2).

    ``message_body`` is the ``{"raw": <base64url string>}`` dict returned by
    :func:`create_message_with_attachments`. The Gmail draft resource wraps a
    message, so the request body nests it under the ``message`` key:
    ``body={"message": message_body}`` (Req 8.1).

    On success ``main()`` records the Contact_Row as a success for the
    Run_Summary (Req 8.3, 1.5).

    Args:
        service: The Gmail API service built by :func:`build_service`, reused
            for every draft during the run.
        message_body: The ``{"raw": ...}`` message dict produced by
            :func:`create_message_with_attachments`.

    Returns:
        The created draft resource as returned by the Gmail API (a dict with
        the draft ``id`` and the nested ``message``).
    """
    # Create the draft only — no send call anywhere. userId="me" targets the
    # authenticated account, and message_body ({"raw": ...}) is nested under the
    # draft's "message" key as the API requires (Req 8.1, 8.2).
    return service.users().drafts().create(
        userId="me",
        body={"message": message_body},
    ).execute()

# ---------------------------------------------------------------------------
# Run summary helpers
# ---------------------------------------------------------------------------
def _row_id(row: dict, row_number: int) -> str:
    """Return a stable identifier for a Contact_Row used in logs and summary.

    Prefers the row's Recipient_Email (the most human-meaningful identifier);
    falls back to the 1-based row number when the email is absent or blank. This
    is the identifier recorded for both successes and failures so the
    Run_Summary and error log entries always point at a specific row
    (Req 10.1, 10.2).
    """
    email = row.get("Recipient_Email")
    if email and email.strip():
        return email.strip()
    return f"row {row_number}"


# ---------------------------------------------------------------------------
# Orchestration and error handling — main()
# ---------------------------------------------------------------------------
def main():
    """Run the full outreach-drafts workflow end to end.

    Ties every component together following the design's "Orchestration and
    Error Handling" section. The setup phase is fail-fast: any problem
    authenticating, building the Gmail service, or reading the Contacts_File
    terminates the run before a single draft is created. The processing phase is
    skip-and-continue: a problem with an individual Contact_Row is logged,
    counted as a failure, and skipped so the rest of the run proceeds.

    Sequence:
      1. ``get_credentials()`` — OAuth lifecycle; raises ``SystemExit`` on its
         own terminal conditions (missing/invalid credentials.json, denied
         authorization) so the run ends before any draft (Req 3.3, 3.7).
      2. ``build_service()`` — build the single Gmail service reused for the run.
      3. ``get_sender_address()`` — the authenticated address for the From header.
      4. ``read_contacts()`` — wrapped in try/except so a missing/unopenable file
         (Req 2.6) or an empty file (Req 2.7) is logged and terminates the run
         cleanly by returning, rather than crashing.

    Then each data row is processed with ``enumerate(rows, start=1)``:
      * ``validate_row`` rejects missing fields / invalid Template_Type: the
        error is logged, the row counted as a failure, and skipped (Req 2.4, 2.5).
      * The template is selected, the subject and body are rendered (Req 5.4),
        the attachment paths are resolved under ``ATTACHMENTS_DIR``, the MIME
        message is built with ``CC_RECIPIENTS`` passed for every row
        (Req 11.2, 11.3), and a draft is created (Req 8.3).
      * Per-row failures are isolated: a missing attachment (Req 7.7), a Gmail
        API error (Req 10.1), a timeout (Req 10.1), or any other unexpected
        exception is logged with the row identifier, counted as a failure, and
        skipped without aborting the run.
      * A ``finally`` clause runs ``time.sleep(RATE_LIMIT_SECONDS)`` after every
        attempt regardless of outcome, pacing the API calls (Req 9.1).

    After the loop the Run_Summary is printed exactly once via ``print`` (so it
    always shows, independent of logging configuration) reporting the counts of
    successful drafts, failed/skipped rows, and total contacts processed. Every
    processed row lands in exactly one of the two lists, so
    ``len(successes) + len(failures) == len(rows)`` (Req 10.3, 10.4).
    """
    # --- Setup phase (fail-fast) -------------------------------------------
    # get_credentials() raises SystemExit on its own terminal conditions
    # (missing/invalid credentials.json, denied/failed authorization), so no
    # draft is created when authentication cannot be established (Req 3.3, 3.7).
    creds = get_credentials()
    service = build_service(creds)
    sender = get_sender_address(service)

    # Reading the Contacts_File is a whole-file, fail-fast concern. Wrap it so a
    # missing/unopenable file (Req 2.6) or an empty file (Req 2.7) is logged and
    # terminates the run cleanly (return) without crashing or processing any row.
    try:
        rows = read_contacts(CONTACTS_FILE)
    except (FileNotFoundError, OSError) as exc:
        # Missing or unopenable Contacts_File (Req 2.6).
        logger.error("Contacts file '%s' is unavailable: %s", CONTACTS_FILE, exc)
        return
    except ValueError as exc:
        # read_contacts signals a header-only / empty file via ValueError (Req 2.7).
        logger.error("Contacts file '%s' contains no contacts: %s", CONTACTS_FILE, exc)
        return

    # --- Processing phase (skip-and-continue) ------------------------------
    # Each processed row is recorded in exactly one of these lists; the row
    # identifier is the Recipient_Email or the row number (Req 10.2).
    successes: list[str] = []
    failures: list[str] = []

    for i, row in enumerate(rows, start=1):
        try:
            # Per-row validation: a missing required field (Req 2.4) or an
            # invalid Template_Type (Req 2.5) is logged and skipped as a failure.
            error = validate_row(row, i)
            if error:
                logger.error(error)
                failures.append(_row_id(row, i))
                continue

            # Select the template for this row's Template_Type and render both
            # the subject and body with the row's personalization values so the
            # subject is personalized exactly like the body (Req 5.4).
            tmpl = TEMPLATES[row["Template_Type"]]
            subject = render_template(tmpl["subject"], row)
            body = render_template(tmpl["body"], row)

            # Resolve the Attachment_Set file names to paths under ATTACHMENTS_DIR.
            paths = [os.path.join(ATTACHMENTS_DIR, f) for f in tmpl["attachments"]]

            # Build the MIME message, always passing CC_RECIPIENTS so every draft
            # — regardless of Template_Type — Cc's the fixed coordinators
            # (Req 11.2, 11.3). A missing attachment file raises FileNotFoundError.
            message = create_message_with_attachments(
                sender, row["Recipient_Email"], subject, body, paths, CC_RECIPIENTS
            )

            # Create the draft (never sends). On success, record the row (Req 8.3).
            create_draft(service, message)
            successes.append(_row_id(row, i))
        except FileNotFoundError as exc:
            # A referenced attachment image is missing from the Attachments_Folder;
            # skip the row without a draft and continue (Req 7.7).
            logger.error("%s: missing attachment: %s", _row_id(row, i), exc)
            failures.append(_row_id(row, i))
        except HttpError as exc:
            # The Gmail API returned an error while creating the draft (Req 10.1).
            logger.error("%s: Gmail API error: %s", _row_id(row, i), exc)
            failures.append(_row_id(row, i))
        except (TimeoutError, socket.timeout) as exc:
            # The Gmail API request timed out (Req 10.1).
            logger.error("%s: request timed out: %s", _row_id(row, i), exc)
            failures.append(_row_id(row, i))
        except Exception as exc:  # noqa: BLE001 - defensive: isolate any other per-row failure
            # Any other unexpected error is contained to this row so the run
            # continues rather than aborting (Req 10.1, 10.2).
            logger.error("%s: unexpected error: %s", _row_id(row, i), exc)
            failures.append(_row_id(row, i))
        finally:
            # Pace API calls: sleep after every attempt regardless of outcome so
            # the run stays within Gmail rate limits (Req 9.1).
            time.sleep(RATE_LIMIT_SECONDS)

    # --- Run Summary (printed exactly once) --------------------------------
    # Printed via print() so it always shows on the console independent of the
    # logging configuration. successes + failures == total by construction, since
    # every processed row is appended to exactly one list (Req 10.3, 10.4).
    print("=== Run Summary ===")
    print(f"Successful drafts: {len(successes)}")
    print(f"Failed / skipped rows: {len(failures)}")
    print(f"Total contacts processed: {len(rows)}")


if __name__ == "__main__":
    # Configure logging so error messages surface on the console when the script
    # is run directly. The Run_Summary is printed via print() above, so it shows
    # regardless of this configuration.
    logging.basicConfig(level=logging.INFO)
    main()
