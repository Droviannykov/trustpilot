# Trustpilot Review Automation

## Overview

Automated Trustpilot review management for Epica Beauty. Both scripts run unattended on a schedule (e.g. hourly via AWS). The only manual step is entering refund amounts in the Google Sheet.

## Files


| File                        | Purpose                                                                        |
| --------------------------- | ------------------------------------------------------------------------------ |
| `trustpilot_replies.py`        | Auto-reply to unanswered reviews + handle negative review flow                 |
| `check_pending_contacts.py`    | Poll Find Reviewer requests, send refund emails, send follow-ups               |
| `generate_reply.py`            | AI reply generator using Claude API with few-shot examples and style rotation   |
| `config.py`                    | Loads `business_config.json`, provides helpers for templates and business vars  |
| `business_config.json`         | All business-specific text: templates, names, emails (never commit)            |
| `business_config.example.json` | Committed example config — copy to `business_config.json` for new deployments  |
| `pending_contacts.json`        | Auto-generated; tracks pending/resolved Find Reviewer requests and email state |
| `sheets.py`                    | Google Sheets integration — updates tracking spreadsheet and Refunds tab       |
| `replies.md`                   | Reference file with AI-generated replies for all existing reviews              |
| `google_credentials.json`      | Google service account credentials (never commit)                              |
| `.env`                         | API credentials (never commit)                                                 |
| `.gitignore`                   | Excludes `.env`, `business_config.json`, and other secrets from git            |


## Credentials (`.env`)

```
TRUSTPILOT_API_KEY                — public API key (tpk-...)
TRUSTPILOT_API_SECRET             — API secret (tps-...)
TRUSTPILOT_BUSINESS_UNIT_ID       — 682368a786bcf0ed951b1156 (Epica Beauty)
TRUSTPILOT_AUTHOR_BUSINESS_USER_ID — 682368a894bf606c8aed21b4 (Nick Droviannykov)

WORKMAIL_SMTP_HOST=smtp.mail.us-east-1.awsapps.com
WORKMAIL_SMTP_PORT=465
WORKMAIL_USERNAME=andrea@epica-beauty.com
WORKMAIL_PASSWORD=...
WORKMAIL_IMAP_HOST=imap.mail.us-east-1.awsapps.com
WORKMAIL_IMAP_PORT=993

GOOGLE_SHEET_ID=1EeAo3DEBJUf9WH66SiTdzGih88v4XByzkFg1JLByh8E
GOOGLE_CREDS_FILE=google_credentials.json

ANTHROPIC_API_KEY=sk-ant-api03-...  — Claude API key for AI-generated replies
```

## Running

```bash
pip install requests python-dotenv gspread google-auth certifi anthropic
python3 trustpilot_replies.py          # auto-reply to all unanswered reviews
python3 trustpilot_replies.py --test   # process oldest unanswered review only

python3 check_pending_contacts.py      # poll requests, send refund emails, follow-ups
```

Both scripts are non-interactive and designed to run on a schedule.

---

## End-to-End Flow (3 stages)

### Stage 1: Trustpilot — `trustpilot_replies.py`

1. **Auth** — exchanges API key + secret for an OAuth 2.0 Bearer token via client credentials grant.
2. **Fetch reviews** — `GET /v1/private/business-units/{id}/reviews?responded=false`, sorted oldest first.
3. `**--test` flag** — limits to the first (oldest) review only.
4. **Auto-reply** — for each review, generates a personalized reply using Claude API (`generate_reply.py`):
  - Uses a system prompt with few-shot examples from real reviews
  - Randomly selects one of 7 writing styles per reply (conversational, calm, energetic, direct, storytelling, playful, confident) for variety
  - **4–5 stars** — reacts to specifics, invites questions at support email
  - **1–3 stars** — empathizes with complaint, directs to email support as the solution
  - Falls back to template replies from `business_config.json` if Claude API fails
5. **Negative review handling** (1–3 stars), after posting the reply:
  - **Case A: `referralEmail` present** — adds reviewer to the "Refunds" sheet tab for manual processing.
  - **Case B: no email** — checks `findReviewer.isEligible`. If eligible, submits a Find Reviewer request via Trustpilot and saves to `pending_contacts.json`. If not eligible, no further action.
6. **Google Sheets** — marks reply posted in the main tracking sheet.

### Stage 2: Refunds — manual + `check_pending_contacts.py` Phase 1 & 2

1. Negative reviewers with available email land in the **"Refunds" sheet tab**.
2. Two paths feed into it:
  - Directly from `trustpilot_replies.py` when `referralEmail` is present.
  - From `check_pending_contacts.py` Phase 1 when a Find Reviewer request is accepted and email arrives.
3. **Operator manually** reviews the Refunds tab, cancels subscriptions, issues refunds, and enters the refund amount in column H.
4. `check_pending_contacts.py` Phase 2 picks up rows where Refund Amount is filled but Refund Email Sent is empty → sends the refund email → marks the row as emailed (column I) → adds entry to `pending_contacts.json` for follow-up tracking.

### Stage 3: Emails — `check_pending_contacts.py` Phase 3

1. For contacts where email was sent >1 day ago with no follow-up yet:
  - Checks WorkMail INBOX via IMAP for any reply from the reviewer's address.
  - If reply found → marks `follow_up_sent: true`, no follow-up sent. Does not inspect reply content.
  - If no reply → sends follow-up in the same email thread → updates Google Sheet.
2. Nothing more after that.

---

## `check_pending_contacts.py` — 3 Phases


| Phase | What it does                                                                                     |
| ----- | ------------------------------------------------------------------------------------------------ |
| 1     | Poll pending Find Reviewer requests. If accepted → add to Refunds sheet. If declined → close.    |
| 2     | Check Refunds sheet for rows with refund amount filled in → send refund email → mark as emailed. |
| 3     | For emails sent >1 day ago: check for reply → send follow-up if none.                            |


---

## Google Sheets (`sheets.py`)

### Main sheet (Sheet 1) — review tracking


| Col  | Field                   |
| ---- | ----------------------- |
| A=1  | Review ID               |
| B=2  | Date                    |
| C=3  | Author                  |
| D=4  | Stars                   |
| E=5  | Title                   |
| F=6  | Review Text             |
| G=7  | Trustpilot Link         |
| H=8  | Invited / Organic       |
| I=9  | Reply Posted            |
| J=10 | Find Reviewer Submitted |
| K=11 | Find Reviewer Status    |
| L=12 | Reviewer Email          |
| M=13 | Refund Email Sent       |
| N=14 | Refund Amount           |
| O=15 | Refund Email Date       |
| P=16 | Follow-up Sent          |
| Q=17 | Notes                   |


### Refunds sheet tab — pending manual refunds


| Col | Field                                       |
| --- | ------------------------------------------- |
| A=1 | Review ID                                   |
| B=2 | Date                                        |
| C=3 | Author                                      |
| D=4 | Stars                                       |
| E=5 | Email                                       |
| F=6 | Review Text                                 |
| G=7 | Trustpilot Link                             |
| H=8 | Refund Amount (filled manually by operator) |
| I=9 | Refund Email Sent (auto-filled with date)   |


The Refunds tab is auto-created on first use if it doesn't exist.

Uses a Google service account (`google_credentials.json`). Sheet ID is in `.env`.

---

## Email Templates (`business_config.json`)

Exactly **2 templates**:

### `refund_confirmation`

- **Subject**: `{author}, your refund for the makeup app is on the way`
- **Variables**: `{author}`, `{refund_amount}`, `{review_link}`
- Sent by `check_pending_contacts.py` Phase 2 when operator enters refund amount
- Sender: Andrea (CEO of Epica Beauty) via andrea@epica-beauty.com

### `follow_up_refund`

- **Subject**: `Re: {original subject}` (threads into original email via `In-Reply-To` / `References` headers; "Re:" must be set explicitly — WorkMail/SMTP does not add it automatically)
- **Variables**: `{author}`, `{review_link}`
- Sent automatically if no reply after 1 day

### Email Formatting Rules

- Single `\n\n` between paragraphs.
- No `\n\n\n` — creates ugly extra blank lines.
- Closing: `All the best,\nAndrea\nEpica Beauty`

### Email Threading

- `send_refund_email()` generates a `Message-ID` via `email.utils.make_msgid()` and returns `(msg_id, subject)`.
- These are stored as `initial_message_id` and `initial_subject` in `pending_contacts.json`.
- WorkMail does **not** auto-save SMTP-sent emails to Sent Items — `Message-ID` must be captured at send time.
- Follow-up uses `In-Reply-To` + `References` headers and `Re: {original_subject}` as subject.

---

## `pending_contacts.json` Entry Structure

```json
{
  "review_id": "...",
  "request_id": "...",
  "author": "...",
  "stars": 1,
  "review_text": "...",
  "submitted_at": "2026-03-20T18:00:00+00:00",
  "status": "Pending | Accepted | Declined",
  "reviewer_email": null,
  "email_sent": false,
  "email_type": "refund",
  "refund_amount": "27.76",
  "email_sent_at": null,
  "initial_message_id": "<...@epica-beauty.com>",
  "initial_subject": "Christy, your refund for the makeup app is on the way",
  "follow_up_sent": false
}
```

---

## Key API Notes

- Negative (1–3 star) organic reviews have no `referralEmail`.
- Positive (4–5 star) invited reviews have `referralEmail` populated directly.
- `findReviewer.isEligible: true` means Trustpilot can mediate a contact request.
- **Find Reviewer endpoint**: `POST /v1/private/reviews/{reviewId}/find-reviewer` (hyphen, not `/findreviewer`).
- Request body: `{"message": "...", "skipNotificationEmailToBusinessUser": false}`.
- The API returns **202 with no body** — re-fetch the review after submission to get `findReviewer.requests[-1]['id']`.
- `findReviewer.isEligible: true` occasionally appears on positive (5-star) reviews, but the API returns an error when submitting a request for them. Find Reviewer only works reliably for negative (1–3 star) reviews.
- **Find Reviewer `consumerResponse`** is an **object** (not a string): `{"email": "...", "name": null, ...}`. Extract `.email` from it.
- **Find Reviewer status** can be `"Complete"` (not just `"Accepted"`) when the reviewer has shared their details. Code must handle both.
- The `subject` field in `business_config.json` email templates supports `{author}` — it is formatted at send time via `template["subject"].format(author=author)`, not hardcoded.
- **Deleting replies via API**: `DELETE /v1/private/reviews/{reviewId}/reply` requires auth header only. Do NOT send `Content-Type: application/json` on DELETE requests or the API returns 400.

