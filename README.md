# Gmail Outreach Drafts

A Python 3.10+ command-line tool for the Wheeler High School **CircuitRunners
Robotics Team**. It reads a CSV of contacts, picks a message template and image
set based on each contact's `Template_Type`, fills in personalization fields,
and creates a **Gmail draft** for every contact through the Gmail API.

The script **never sends email** — it only creates drafts for a human to review
and send. Every draft automatically Cc's the two team coordinators
(`ethan.xu@circuitrunners.com` and `melissa.amerault@circuitrunners.com`),
regardless of template type.

## Project layout

```
gmail-outreach-drafts/
├── outreach_drafts.py     # the script (all logic + setup guide in its docstring)
├── requirements.txt       # runtime dependencies
├── requirements-dev.txt   # dev/test dependencies (pytest, hypothesis)
├── contacts.csv           # sample contacts (header + one row per Template_Type)
├── README.md              # this file
├── credentials.json       # OAuth client — YOU supply this (not committed)
├── token.json             # cached OAuth token — created on first run
├── attachments/           # demo images referenced by the templates
│   ├── robot-demo1.jpg
│   ├── robot-demo2.jpg
│   ├── robot-demo3.jpg
│   └── robot-demo5.jpg
└── tests/                 # pytest + hypothesis test suite
```

## Setup

### 1. Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top and choose **New Project**.
3. Give it a name (e.g. `CircuitRunners Outreach`) and click **Create**.

### 2. Enable the Gmail API

1. With your new project selected, open **APIs & Services → Library**.
2. Search for **Gmail API** and open it.
3. Click **Enable**.

### 3. Configure the OAuth consent screen

1. Open **APIs & Services → OAuth consent screen**.
2. Choose **External** (or **Internal** if you use Google Workspace) and fill in
   the required app name and support email.
3. Add your own Google account as a **Test user** so you can authorize the app
   while it is in testing.

### 4. Obtain `credentials.json`

1. Open **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Choose **Desktop app** as the application type and click **Create**.
4. Download the client configuration and save it as `credentials.json` in this
   folder (next to `outreach_drafts.py`).

The script requests only the `gmail.compose` scope, which allows creating
drafts but **cannot send email**.

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

To also install the test tooling (pytest + hypothesis):

```bash
pip install -r requirements-dev.txt
```

### 6. Prepare your contacts and attachments

- Edit `contacts.csv`. Keep the header row exactly:
  `Recipient_Email,Recipient_Name,Sender_Name,School_Name,Template_Type`
  and add one row per recipient. `Template_Type` must be one of
  `Elementary`, `Middle`, `Response`, or `Post-Demo`.
- Replace the placeholder images in `attachments/` with real demo photos,
  keeping the same file names (`robot-demo1.jpg`, `robot-demo2.jpg`,
  `robot-demo3.jpg`, `robot-demo5.jpg`).

## Running the script

```bash
python outreach_drafts.py
```

On the first run a browser window opens for you to authorize the app; the
resulting token is cached in `token.json` and reused on later runs. The script
processes each contact, creates a draft (pausing ~1 second between drafts to
respect API limits), skips any row that fails while continuing the run, and
prints a summary of successes and failures at the end.

Open Gmail's **Drafts** folder to review and send the messages yourself.

## Running the tests

```bash
pytest
```

The tests mock the Gmail API and `time.sleep`, so no real emails or drafts are
created and the suite runs quickly.
