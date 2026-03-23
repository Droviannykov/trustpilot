#!/usr/bin/env python3
"""
Pending Contact Checker
Polls Trustpilot for responses to Find Reviewer requests saved in pending_contacts.json.
When a reviewer accepts and shares their email, sends them a proactive support email
via Amazon WorkMail SMTP.

Run this script periodically (e.g. once a day) to catch new reviewer responses.
"""

import json
import os
import imaplib
import email
import smtplib
import ssl
import certifi
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid
import requests
from dotenv import load_dotenv
import sheets
import config

# Load credentials from .env file
load_dotenv()

API_KEY = os.getenv("TRUSTPILOT_API_KEY")
API_SECRET = os.getenv("TRUSTPILOT_API_SECRET")
BASE_URL = "https://api.trustpilot.com"

# WorkMail SMTP credentials for sending outreach emails
SMTP_HOST = os.getenv("WORKMAIL_SMTP_HOST")
SMTP_PORT = int(os.getenv("WORKMAIL_SMTP_PORT", 465))
SMTP_USERNAME = os.getenv("WORKMAIL_USERNAME")
SMTP_PASSWORD = os.getenv("WORKMAIL_PASSWORD")
IMAP_HOST = os.getenv("WORKMAIL_IMAP_HOST")
IMAP_PORT = int(os.getenv("WORKMAIL_IMAP_PORT", 993))

PENDING_CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "pending_contacts.json")


def get_access_token():
    # Exchange API key + secret for a short-lived OAuth 2.0 Bearer token
    resp = requests.post(
        f"{BASE_URL}/v1/oauth/oauth-business-users-for-applications/accesstoken",
        data={"grant_type": "client_credentials"},
        auth=(API_KEY, API_SECRET),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_review(token, review_id):
    # Fetch the current state of a single review, including the latest
    # findReviewer.requests status and any consumerResponse (email).
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"{BASE_URL}/v1/private/reviews/{review_id}",
        headers=headers,
        params={"apikey": API_KEY},
    )
    resp.raise_for_status()
    return resp.json()


def find_request_status(review_data, request_id):
    # Locate the specific Find Reviewer request by ID within the review data
    # and return its current status and the reviewer's email if provided.
    for req in review_data.get("findReviewer", {}).get("requests", []):
        if req.get("id") == request_id:
            consumer_response = req.get("consumerResponse")
            if isinstance(consumer_response, dict):
                email = consumer_response.get("email")
            else:
                email = consumer_response  # fallback if API returns a plain string
            return req.get("status"), email
    return None, None


def send_refund_email(to_email, author, review_id, refund_amount):
    # Compose and send a refund confirmation email using the "refund_confirmation" template.
    # Returns the Message-ID so it can be stored for follow-up threading.
    template = config.get_email_template("refund_confirmation")
    review_link = f"https://www.trustpilot.com/reviews/{review_id}"
    body = template["body"].format(author=author, refund_amount=refund_amount, review_link=review_link)
    subject = template["subject"].format(author=author)

    msg_id = make_msgid(domain=config.get_email_domain())
    msg = MIMEMultipart()
    msg["From"] = SMTP_USERNAME
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = msg_id
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to_email, msg.as_string())
    return msg_id, subject


def check_for_reply(reviewer_email):
    # Connect to WorkMail via IMAP and check if the reviewer has replied to any of our emails.
    # Returns True if a reply from the reviewer's address is found in the inbox.
    context = ssl.create_default_context(cafile=certifi.where())
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=context) as imap:
        imap.login(SMTP_USERNAME, SMTP_PASSWORD)
        imap.select("INBOX")
        _, data = imap.search(None, f'FROM "{reviewer_email}"')
        message_ids = data[0].split()
        return len(message_ids) > 0


def send_follow_up_email(to_email, author, review_id=None, refund_amount=None, in_reply_to=None, original_subject=None):
    # Send a follow-up to a reviewer who hasn't replied after 1 day.
    # If in_reply_to is provided (the Message-ID of the original email), the follow-up
    # is sent as a reply in the same thread using the original subject.
    template = config.get_email_template("follow_up_refund")
    review_link = f"https://www.trustpilot.com/reviews/{review_id}"
    body = template["body"].format(author=author, review_link=review_link)

    # Use Re: <original subject> so the email threads correctly in the recipient's inbox
    subject = f"Re: {original_subject}" if original_subject else f"Re: {template['subject']}"
    msg = MIMEMultipart()
    msg["From"] = SMTP_USERNAME
    msg["To"] = to_email
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to_email, msg.as_string())



def load_pending_contacts():
    if not os.path.exists(PENDING_CONTACTS_FILE):
        print("No pending_contacts.json found — nothing to check.")
        return []
    with open(PENDING_CONTACTS_FILE) as f:
        return json.load(f)


def save_pending_contacts(contacts):
    with open(PENDING_CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, indent=2)


def main():
    contacts = load_pending_contacts()

    # Phase 1: check pending Find Reviewer requests
    open_contacts = [c for c in contacts if c.get("status") == "Pending" and not c.get("email_sent")]
    if open_contacts:
        print(f"Checking {len(open_contacts)} pending Find Reviewer request(s)...\n")
        token = get_access_token()

        for contact in contacts:
            if contact["status"] != "Pending" or contact["email_sent"]:
                continue

            review_id = contact["review_id"]
            request_id = contact["request_id"]
            author = contact["author"]

            print(f"Checking review {review_id} (author: {author})...")

            try:
                review_data = get_review(token, review_id)
            except requests.HTTPError as e:
                print(f"  Failed to fetch review: {e}\n")
                continue

            status, reviewer_email = find_request_status(review_data, request_id)

            if status is None:
                print(f"  Request {request_id} not found in review data. Skipping.\n")
                continue

            print(f"  Status: {status}")

            if status in ("Accepted", "Complete") and reviewer_email:
                print(f"  Reviewer email: {reviewer_email}")
                contact["status"] = "Accepted"
                contact["reviewer_email"] = reviewer_email
                sheets.mark_find_reviewer_status(review_id, "Accepted", reviewer_email)
                review_data_date = review_data.get("createdAt", "")[:10]
                sheets.add_to_refunds(review_id, review_data_date, author, contact.get("stars", ""), reviewer_email, contact.get("review_text", ""))
                print(f"  Added to Refunds sheet for manual review.\n")

            elif status == "Declined":
                contact["status"] = "Declined"
                sheets.mark_find_reviewer_status(review_id, "Declined")
                print(f"  Reviewer declined contact. Closing request.\n")

            else:
                print(f"  No response yet.\n")
    else:
        print("No pending Find Reviewer requests.\n")

    # Phase 2: send refund emails for Refunds sheet rows where operator entered a refund amount
    pending_refunds = sheets.get_pending_refunds()
    if pending_refunds:
        print(f"Sending refund emails for {len(pending_refunds)} entry(ies) in Refunds sheet...\n")
        for entry in pending_refunds:
            review_id = entry["review_id"]
            author = entry["author"]
            to_email = entry["email"]
            refund_amount = entry["refund_amount"]
            print(f"  {author} ({to_email}) — refund ${refund_amount}...")
            try:
                msg_id, subject = send_refund_email(to_email, author, review_id, refund_amount)
                sent_at = datetime.now(timezone.utc).isoformat()
                # Mark the Refunds sheet row as emailed
                sheets.mark_refund_emailed_in_refunds(entry["row"], sent_at[:10])
                # Update main sheet
                sheets.mark_refund_email_sent(review_id, refund_amount, sent_at[:10])
                # Track in pending_contacts.json for follow-up
                contacts.append({
                    "review_id": review_id,
                    "request_id": "refund-sheet",
                    "author": author,
                    "stars": None,
                    "review_text": "",
                    "submitted_at": sent_at,
                    "status": "Accepted",
                    "reviewer_email": to_email,
                    "email_sent": True,
                    "email_type": "refund",
                    "refund_amount": refund_amount,
                    "email_sent_at": sent_at,
                    "initial_message_id": msg_id,
                    "initial_subject": subject,
                    "follow_up_sent": False,
                })
                print(f"  Refund email sent.\n")
            except Exception as e:
                print(f"  Failed to send refund email: {e}\n")
    else:
        print("No pending refund emails to send.\n")

    # Phase 3: send follow-ups for emails sent more than 1 day ago with no follow-up yet
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    follow_up_candidates = [
        c for c in contacts
        if c.get("email_sent") and not c.get("follow_up_sent") and c.get("email_sent_at")
        and datetime.fromisoformat(c["email_sent_at"]) <= cutoff
    ]

    if follow_up_candidates:
        print(f"Sending follow-ups for {len(follow_up_candidates)} unanswered email(s)...\n")
        for contact in follow_up_candidates:
            reviewer_email = contact["reviewer_email"]
            author = contact["author"]
            print(f"  Checking for reply from {author} ({reviewer_email})...")
            try:
                replied = check_for_reply(reviewer_email)
            except Exception as e:
                print(f"  Could not check inbox: {e}. Skipping.\n")
                continue

            if replied:
                print(f"  Reply found — no follow-up needed.\n")
                contact["follow_up_sent"] = True
            else:
                print(f"  No reply found. Sending follow-up...")
                try:
                    send_follow_up_email(
                        reviewer_email,
                        author,
                        review_id=contact.get("review_id"),
                        refund_amount=contact.get("refund_amount"),
                        in_reply_to=contact.get("initial_message_id"),
                        original_subject=contact.get("initial_subject"),
                    )
                    contact["follow_up_sent"] = True
                    sheets.mark_follow_up_sent(contact["review_id"])
                    print(f"  Follow-up sent.\n")
                except Exception as e:
                    print(f"  Failed to send follow-up: {e}\n")

    # Persist all status updates back to disk
    save_pending_contacts(contacts)
    print("Done.")


if __name__ == "__main__":
    main()
