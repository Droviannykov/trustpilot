#!/usr/bin/env python3
"""
Trustpilot Review Reply Script
Fetches unanswered reviews and auto-replies using templates.
For negative reviews (1-3 stars), also submits a Find Reviewer request so
Trustpilot can ask the reviewer if they consent to share their contact details.
Pending contact requests are saved to pending_contacts.json for follow-up
by check_pending_contacts.py.

Designed to run unattended on a schedule (e.g. hourly via AWS).
"""

import json
import os
import sys
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
import sheets

# Load credentials from .env file
load_dotenv()

# API credentials and identifiers loaded from environment
API_KEY = os.getenv("TRUSTPILOT_API_KEY")
API_SECRET = os.getenv("TRUSTPILOT_API_SECRET")
BUSINESS_UNIT_ID = os.getenv("TRUSTPILOT_BUSINESS_UNIT_ID")
# The business user whose name appears as the reply author on Trustpilot
AUTHOR_BUSINESS_USER_ID = os.getenv("TRUSTPILOT_AUTHOR_BUSINESS_USER_ID")
BASE_URL = "https://api.trustpilot.com"

# Path to the JSON file containing reply templates (editable without touching this script)
TEMPLATES_FILE = os.path.join(os.path.dirname(__file__), "reply_templates.json")
# Path to the email templates file (subject, body, find-reviewer message)
EMAIL_TEMPLATES_FILE = os.path.join(os.path.dirname(__file__), "email_templates.json")
# Path to the file that tracks pending Find Reviewer requests awaiting reviewer response
PENDING_CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "pending_contacts.json")


def get_access_token():
    # Exchange API key + secret for a short-lived OAuth 2.0 Bearer token
    # using the client credentials grant (application identity)
    resp = requests.post(
        f"{BASE_URL}/v1/oauth/oauth-business-users-for-applications/accesstoken",
        data={"grant_type": "client_credentials"},
        auth=(API_KEY, API_SECRET),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_unanswered_reviews(token):
    # Fetch up to 100 reviews that have not yet received a reply
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "apikey": API_KEY,
        "perPage": 100,
        "responded": "false",
    }
    resp = requests.get(
        f"{BASE_URL}/v1/private/business-units/{BUSINESS_UNIT_ID}/reviews",
        headers=headers,
        params=params,
    )
    resp.raise_for_status()
    reviews = resp.json().get("reviews", [])
    # Sort oldest first so we always handle reviews in chronological order
    reviews.sort(key=lambda r: r.get("createdAt", ""))
    return reviews


def load_templates():
    # Load reply templates from the JSON file
    with open(TEMPLATES_FILE) as f:
        return json.load(f)


def get_reply_text(stars, templates):
    # Match the review's star rating to the correct template (positive or negative)
    for key in ("positive", "negative"):
        if stars in templates[key]["stars"]:
            return templates[key]["text"]
    return None


def post_reply(token, review_id, message):
    # Post the reply to a specific review via the private Trustpilot API.
    # authorBusinessUserId is required when authenticating as an application
    # (client credentials) — it identifies which business user is the reply author.
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{BASE_URL}/v1/private/reviews/{review_id}/reply",
        headers=headers,
        json={"message": message, "authorBusinessUserId": AUTHOR_BUSINESS_USER_ID},
    )
    resp.raise_for_status()
    return resp


def submit_find_reviewer(token, review_id, message):
    # Ask Trustpilot to contact the reviewer on our behalf and request their
    # consent to share contact details. Only works when findReviewer.isEligible
    # is true on the review. Returns the request object from the API response.
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{BASE_URL}/v1/private/reviews/{review_id}/find-reviewer",
        headers=headers,
        json={"message": message, "skipNotificationEmailToBusinessUser": False},
    )
    resp.raise_for_status()
    return resp.json()


def load_pending_contacts():
    # Load the list of pending Find Reviewer requests from disk.
    # Returns an empty list if the file doesn't exist yet.
    if not os.path.exists(PENDING_CONTACTS_FILE):
        return []
    with open(PENDING_CONTACTS_FILE) as f:
        return json.load(f)


def save_pending_contacts(contacts):
    # Persist the pending contacts list to disk so check_pending_contacts.py
    # can pick it up later and poll for reviewer responses.
    with open(PENDING_CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, indent=2)


def record_pending_contact(review_id, request_id, author, stars, review_text):
    # Append a new pending contact entry to pending_contacts.json.
    # Each entry tracks the review context so we can send a personalised email
    # once the reviewer shares their contact details.
    contacts = load_pending_contacts()
    contacts.append({
        "review_id": review_id,
        "request_id": request_id,
        "author": author,
        "stars": stars,
        "review_text": review_text,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "Pending",       # updated to Accepted/Declined by check_pending_contacts.py
        "reviewer_email": None,    # filled in when the reviewer accepts
        "email_sent": False,       # set to True once the outreach email is dispatched
    })
    save_pending_contacts(contacts)


def main():
    # --test flag: process only the first (oldest) unanswered review, for safe testing
    limit = None
    if "--test" in sys.argv:
        limit = 1

    print("Fetching access token...")
    token = get_access_token()

    print("Fetching unanswered reviews...")
    reviews = get_unanswered_reviews(token)
    if limit:
        reviews = reviews[:limit]

    if not reviews:
        print("No unanswered reviews found.")
        return

    templates = load_templates()
    print(f"\nFound {len(reviews)} unanswered review(s).\n")

    for review in reviews:
        review_id = review["id"]
        stars = review["stars"]
        author = review.get("consumer", {}).get("displayName", "Unknown")
        title = review.get("title", "(no title)")
        body = review.get("text", "(no body)")
        reply_text = get_reply_text(stars, templates)

        print("=" * 60)
        print(f"Author : {author}")
        print(f"Stars  : {'★' * stars}{'☆' * (5 - stars)} ({stars}/5)")
        print(f"Title  : {title}")
        print(f"Review : {body}")
        print(f"Reply  : {reply_text}")

        # Post the template reply automatically
        try:
            post_reply(token, review_id, reply_text)
            print(f"Reply posted for review {review_id}.")
            sheets.mark_reply_posted(review_id)
        except requests.HTTPError as e:
            print(f"Failed to post reply: {e}")
            print(f"Response body: {e.response.text}\n")
            continue

        # For negative reviews, handle email and refund flow.
        if stars <= 3:
            referral_email = review.get("referralEmail")

            if referral_email:
                review_date = review.get("createdAt", "")[:10]
                sheets.add_to_refunds(review_id, review_date, author, stars, referral_email, body)
                print(f"  Reviewer email on file: {referral_email}")
                print(f"  Added to Refunds sheet for manual review.")

            else:
                find_reviewer = review.get("findReviewer", {})
                if find_reviewer.get("isEligible"):
                    try:
                        find_reviewer_message = "Hi, we're sorry to hear about your experience with Epica Beauty. We'd love to reach out directly to make things right — would you be willing to share your contact details with us?"
                        submit_find_reviewer(token, review_id, find_reviewer_message)
                        review_data = requests.get(
                            f"{BASE_URL}/v1/private/reviews/{review_id}",
                            headers={"Authorization": f"Bearer {token}"},
                            params={"apikey": API_KEY},
                        ).json()
                        fr_requests = review_data.get("findReviewer", {}).get("requests", [])
                        request_id = fr_requests[-1]["id"] if fr_requests else "unknown"
                        record_pending_contact(review_id, request_id, author, stars, body)
                        print(f"  No email on file. Find Reviewer request submitted.")
                        sheets.mark_find_reviewer_submitted(review_id)
                    except requests.HTTPError as e:
                        print(f"  Find Reviewer request failed: {e}")
                        print(f"  Response body: {e.response.text}")
                else:
                    print("  No email on file and Find Reviewer not eligible — cannot contact reviewer.")

        print()


if __name__ == "__main__":
    main()
