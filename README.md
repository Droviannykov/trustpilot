# Trustpilot Review Automation

Automated Trustpilot review management for Epica Beauty. Replies to reviews, requests reviewer emails, sends refund emails, and follows up — all on a schedule.

## How it works

1. **Reply to reviews** — auto-posts templated replies to all unanswered Trustpilot reviews
2. **Get reviewer email** — for negative reviews (1-3 stars), collects the reviewer's email (either from the review directly or via Trustpilot's Find Reviewer)
3. **Refund flow** — adds negative reviewers to a Google Sheet; once the operator enters a refund amount, the script sends a refund confirmation email
4. **Follow-up** — if no reply after 1 day, sends a follow-up in the same email thread

## Setup

```bash
pip install requests python-dotenv gspread google-auth certifi
```

Create a `.env` file with your credentials (see `CLAUDE.md` for the full list).

## Usage

```bash
python3 trustpilot_replies.py          # auto-reply to all unanswered reviews
python3 trustpilot_replies.py --test   # process oldest review only

python3 check_pending_contacts.py      # poll requests, send refund emails, follow-ups
```

Both scripts are non-interactive and designed to run on a schedule (e.g. hourly via AWS).
