# Trustpilot Review Automation

Automated Trustpilot review management for Epica Beauty. Both scripts run unattended on a schedule (e.g. hourly via AWS). The only manual step is entering refund amounts in the Google Sheet.

## What it does

1. **Replies to every unanswered review** — positive reviews get a thank-you, negative reviews get an apology with a support email
2. **Collects reviewer emails** — either directly from the review or by requesting it through Trustpilot's Find Reviewer
3. **Tracks negative reviewers in a Google Sheet** — the operator reviews the list, cancels subscriptions, and enters the refund amount
4. **Sends a refund confirmation email** — automatically, once the refund amount appears in the sheet
5. **Follows up after 1 day** — if the reviewer hasn't replied, sends a follow-up in the same email thread

## Files

| File | Purpose |
|------|---------|
| `trustpilot_replies.py` | Auto-reply to unanswered reviews + handle negative review flow |
| `check_pending_contacts.py` | Poll Find Reviewer requests, send refund emails, send follow-ups |
| `reply_templates.json` | Public reply templates posted on Trustpilot (editable without code changes) |
| `email_templates.json` | Email templates: refund confirmation and follow-up refund |
| `sheets.py` | Google Sheets integration — updates tracking spreadsheet and Refunds tab |
| `logic.md` | Business logic overview |

## Setup

```bash
pip install requests python-dotenv gspread google-auth certifi
```

Create a `.env` file with the following variables:

- `TRUSTPILOT_API_KEY` — public API key
- `TRUSTPILOT_API_SECRET` — API secret
- `TRUSTPILOT_BUSINESS_UNIT_ID` — Trustpilot business unit ID
- `TRUSTPILOT_AUTHOR_BUSINESS_USER_ID` — business user ID for reply authorship
- `WORKMAIL_SMTP_HOST` — WorkMail SMTP host
- `WORKMAIL_SMTP_PORT` — WorkMail SMTP port
- `WORKMAIL_USERNAME` — WorkMail email address
- `WORKMAIL_PASSWORD` — WorkMail password
- `WORKMAIL_IMAP_HOST` — WorkMail IMAP host
- `WORKMAIL_IMAP_PORT` — WorkMail IMAP port
- `GOOGLE_SHEET_ID` — Google Sheet ID
- `GOOGLE_CREDS_FILE` — path to Google service account credentials JSON

## Usage

```bash
python3 trustpilot_replies.py          # auto-reply to all unanswered reviews
python3 trustpilot_replies.py --test   # process oldest review only

python3 check_pending_contacts.py      # poll requests, send refund emails, follow-ups
```

Both scripts are non-interactive and designed to run on a schedule.

---

## End-to-End Flow (3 stages)

### Stage 1: Trustpilot — `trustpilot_replies.py`

1. **Auth** — exchanges API key + secret for an OAuth 2.0 Bearer token via client credentials grant.
2. **Fetch reviews** — fetches unanswered reviews, sorted oldest first.
3. **`--test` flag** — limits to the first (oldest) review only.
4. **Auto-reply** — for each review, posts the matching template reply automatically (no prompts):
   - **4-5 stars** — thank the customer, invite questions
   - **1-3 stars** — apologise, ask them to email support
5. **Negative review handling** (1-3 stars), after posting the reply:
   - **Case A: email on file** — adds reviewer to the "Refunds" sheet tab for manual processing.
   - **Case B: no email** — checks `findReviewer.isEligible`. If eligible, submits a Find Reviewer request via Trustpilot and saves to `pending_contacts.json`. If not eligible, no further action.
6. **Google Sheets** — marks reply posted in the main tracking sheet.

### Stage 2: Refunds — manual + `check_pending_contacts.py` Phase 1 & 2

1. Negative reviewers with available email land in the **"Refunds" sheet tab**.
2. Two paths feed into it:
   - Directly from `trustpilot_replies.py` when the reviewer's email is already on file.
   - From `check_pending_contacts.py` Phase 1 when a Find Reviewer request is accepted and email arrives.
3. **Operator manually** reviews the Refunds tab, cancels subscriptions, issues refunds, and enters the refund amount in column H.
4. `check_pending_contacts.py` Phase 2 picks up rows where Refund Amount is filled but Refund Email Sent is empty — sends the refund email — marks the row as emailed (column I) — adds entry to `pending_contacts.json` for follow-up tracking.

### Stage 3: Emails — `check_pending_contacts.py` Phase 3

1. For contacts where email was sent >1 day ago with no follow-up yet:
   - Checks WorkMail INBOX via IMAP for any reply from the reviewer's address.
   - If reply found — marks as done, no follow-up sent. Does not inspect reply content.
   - If no reply — sends follow-up in the same email thread — updates Google Sheet.
2. Nothing more after that.

---

## `check_pending_contacts.py` — 3 Phases

| Phase | What it does |
|-------|-------------|
| 1 | Poll pending Find Reviewer requests. If accepted — add to Refunds sheet. If declined — close. |
| 2 | Check Refunds sheet for rows with refund amount filled in — send refund email — mark as emailed. |
| 3 | For emails sent >1 day ago: check for reply — send follow-up if none. |

---

## Google Sheets (`sheets.py`)

### Main sheet (Sheet 1) — review tracking

| Col | Field |
|-----|-------|
| A=1 | Review ID |
| B=2 | Date |
| C=3 | Author |
| D=4 | Stars |
| E=5 | Title |
| F=6 | Review Text |
| G=7 | Trustpilot Link |
| H=8 | Invited / Organic |
| I=9 | Reply Posted |
| J=10 | Find Reviewer Submitted |
| K=11 | Find Reviewer Status |
| L=12 | Reviewer Email |
| M=13 | Refund Email Sent |
| N=14 | Refund Amount |
| O=15 | Refund Email Date |
| P=16 | Follow-up Sent |
| Q=17 | Notes |

### Refunds sheet tab — pending manual refunds

| Col | Field |
|-----|-------|
| A=1 | Review ID |
| B=2 | Date |
| C=3 | Author |
| D=4 | Stars |
| E=5 | Email |
| F=6 | Review Text |
| G=7 | Trustpilot Link |
| H=8 | Refund Amount (filled manually by operator) |
| I=9 | Refund Email Sent (auto-filled with date) |

The Refunds tab is auto-created on first use if it doesn't exist.

---

## Email Templates (`email_templates.json`)

Exactly **2 templates**:

### `refund_confirmation`

- **Subject**: `{author}, your refund for the makeup app is on the way`
- **Variables**: `{author}`, `{refund_amount}`, `{review_link}`
- Sent by Phase 2 when operator enters refund amount

### `follow_up_refund`

- **Subject**: `Re: {original subject}` (threads into original email)
- **Variables**: `{author}`, `{review_link}`
- Sent automatically if no reply after 1 day

### Email Threading

- The first email generates a `Message-ID` which is stored for threading.
- The follow-up uses `In-Reply-To` + `References` headers and `Re: {original subject}` to thread into the same conversation.
- "Re:" must be set explicitly — SMTP does not add it automatically.
