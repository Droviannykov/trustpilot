"""
Google Sheets integration for Trustpilot review tracking.

Sheet 1 — main review tracking. Column layout (1-indexed):
  A=1  Review ID
  B=2  Date
  C=3  Author
  D=4  Stars
  E=5  Title
  F=6  Review Text
  G=7  Trustpilot Link
  H=8  Invited / Organic
  I=9  Reply Posted
  J=10 Find Reviewer Submitted
  K=11 Find Reviewer Status
  L=12 Reviewer Email
  M=13 Refund Email Sent
  N=14 Refund Amount
  O=15 Refund Email Date
  P=16 Follow-up Sent
  Q=17 Notes

Sheet "Refunds" — negative reviewers (1-3 stars) with available email, pending manual refund.
  A=1  Review ID
  B=2  Date
  C=3  Author
  D=4  Stars
  E=5  Email
  F=6  Review Text
  G=7  Trustpilot Link
  H=8  Refund Amount  (filled manually by operator)
  I=9  Refund Email Sent  (auto-filled with date when email is sent)
"""

import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDS_FILE = os.path.join(os.path.dirname(__file__), os.getenv("GOOGLE_CREDS_FILE", ""))

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column indices (1-based)
COL_REVIEW_ID       = 1
COL_REPLY_POSTED    = 9
COL_FR_SUBMITTED    = 10
COL_FR_STATUS       = 11
COL_REVIEWER_EMAIL  = 12
COL_REFUND_SENT     = 13
COL_REFUND_AMOUNT   = 14
COL_REFUND_DATE     = 15
COL_FOLLOW_UP_SENT  = 16


REFUNDS_SHEET_NAME = "Refunds"
REFUNDS_HEADERS = ["Review ID", "Date", "Author", "Stars", "Email", "Review Text", "Trustpilot Link", "Refund Amount", "Refund Email Sent"]

# Refunds sheet column indices (1-based)
RCOL_REVIEW_ID     = 1
RCOL_AUTHOR        = 3
RCOL_EMAIL         = 5
RCOL_REFUND_AMOUNT = 8
RCOL_EMAIL_SENT    = 9


def _get_spreadsheet():
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID)


def _get_worksheet():
    return _get_spreadsheet().sheet1


def _get_refunds_worksheet():
    sp = _get_spreadsheet()
    try:
        return sp.worksheet(REFUNDS_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet(title=REFUNDS_SHEET_NAME, rows=100, cols=len(REFUNDS_HEADERS))
        ws.append_row(REFUNDS_HEADERS)
        return ws


def _find_row(ws, review_id):
    # Returns the 1-based row index for the given review_id, or None if not found.
    col = ws.col_values(COL_REVIEW_ID)
    for i, val in enumerate(col):
        if val == review_id:
            return i + 1
    return None


def update_cells(review_id, updates: dict):
    # updates: {column_index: value, ...}
    # Connects to the sheet, finds the review row, and updates the specified cells.
    try:
        ws = _get_worksheet()
        row = _find_row(ws, review_id)
        if row is None:
            print(f"  [Sheets] Review {review_id} not found in sheet — skipping update.")
            return
        for col, value in updates.items():
            ws.update_cell(row, col, value)
    except Exception as e:
        print(f"  [Sheets] Update failed: {e}")


def mark_reply_posted(review_id):
    update_cells(review_id, {COL_REPLY_POSTED: "Yes"})


def mark_find_reviewer_submitted(review_id):
    update_cells(review_id, {COL_FR_SUBMITTED: "Yes", COL_FR_STATUS: "Pending"})


def mark_find_reviewer_status(review_id, status, reviewer_email=None):
    updates = {COL_FR_STATUS: status}
    if reviewer_email:
        updates[COL_REVIEWER_EMAIL] = reviewer_email
    update_cells(review_id, updates)


def mark_refund_email_sent(review_id, refund_amount, sent_date):
    update_cells(review_id, {
        COL_REFUND_SENT: "Yes",
        COL_REFUND_AMOUNT: refund_amount,
        COL_REFUND_DATE: sent_date,
    })


def mark_follow_up_sent(review_id):
    update_cells(review_id, {COL_FOLLOW_UP_SENT: "Yes"})


def get_pending_refunds():
    """Return rows from the Refunds sheet where Refund Amount is filled but Refund Email Sent is empty."""
    try:
        ws = _get_refunds_worksheet()
        rows = ws.get_all_values()
        pending = []
        for i, row in enumerate(rows[1:], start=2):  # skip header, 1-based row index
            refund_amount = row[RCOL_REFUND_AMOUNT - 1].strip() if len(row) >= RCOL_REFUND_AMOUNT else ""
            email_sent = row[RCOL_EMAIL_SENT - 1].strip() if len(row) >= RCOL_EMAIL_SENT else ""
            if refund_amount and not email_sent:
                pending.append({
                    "row": i,
                    "review_id": row[RCOL_REVIEW_ID - 1],
                    "author": row[RCOL_AUTHOR - 1],
                    "email": row[RCOL_EMAIL - 1],
                    "refund_amount": refund_amount,
                })
        return pending
    except Exception as e:
        print(f"  [Sheets] Failed to read Refunds sheet: {e}")
        return []


def mark_refund_emailed_in_refunds(row_index, sent_date):
    """Mark a row in the Refunds sheet as emailed."""
    try:
        ws = _get_refunds_worksheet()
        ws.update_cell(row_index, RCOL_EMAIL_SENT, sent_date)
    except Exception as e:
        print(f"  [Sheets] Failed to update Refunds sheet row {row_index}: {e}")


def add_to_refunds(review_id, date, author, stars, email, review_text):
    try:
        ws = _get_refunds_worksheet()
        # Don't add duplicates
        existing_ids = ws.col_values(1)
        if review_id in existing_ids:
            return
        link = f"https://www.trustpilot.com/reviews/{review_id}"
        ws.append_row([review_id, date, author, stars, email, review_text, link, ""])
    except Exception as e:
        print(f"  [Sheets] Failed to add to Refunds sheet: {e}")
