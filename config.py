"""
Business configuration loader.
Reads business_config.json and provides helpers that return templates
with business-level variables pre-filled.
"""

import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "business_config.json")

_config = None


def get_config():
    global _config
    if _config is None:
        with open(CONFIG_FILE) as f:
            _config = json.load(f)
    return _config


def get_reply_text(stars):
    cfg = get_config()
    for key in ("positive", "negative"):
        template = cfg["reply_templates"][key]
        if stars in template["stars"]:
            return template["text"].format(support_email=cfg["support_email"])
    return None


def get_find_reviewer_message():
    cfg = get_config()
    return cfg["find_reviewer_message"].format(business_name=cfg["business_name"])


def get_email_template(template_name):
    cfg = get_config()
    template = cfg["email_templates"][template_name]
    subject = template["subject"].format(
        business_name=cfg["business_name"],
        product_description=cfg["product_description"],
        sender_name=cfg["sender_name"],
        sender_title=cfg["sender_title"],
        author="{author}",
    )
    body = template["body"].format(
        business_name=cfg["business_name"],
        product_description=cfg["product_description"],
        sender_name=cfg["sender_name"],
        sender_title=cfg["sender_title"],
        author="{author}",
        refund_amount="{refund_amount}",
        review_link="{review_link}",
    )
    return {"subject": subject, "body": body}


def get_email_domain():
    return get_config()["email_domain"]
