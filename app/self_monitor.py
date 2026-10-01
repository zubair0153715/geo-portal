"""Self-monitoring dogfood: track the portal's OWN AI-search visibility.

Run once (and any time after) with:
    python -m app.self_monitor

Idempotent: creates an "AI Visibility Portal" business for the owner (the
first registered user) only if it doesn't exist yet. The existing daily
scheduler then checks these phrases like any other business — checks still
honestly skip when no AI provider key is configured.
"""

from . import config, db

BUSINESS_NAME = "AI Visibility Portal"

PHRASES = [
    "AI search visibility tool for small business",
    "GEO tool to track ChatGPT brand mentions",
    "track brand mentions on Perplexity",
    "AI visibility report tool",
    "generative engine optimization software for local business",
]


def ensure_self_monitor() -> dict:
    """Create the self-monitor business if missing. Returns a status dict."""
    db.init_db()
    owner = db.owner_email()
    if not owner:
        return {"ok": False, "reason": "no users yet — sign up first, then re-run"}
    user = db.get_user_by_email(owner)
    for b in db.list_businesses(user["id"]):
        if b["name"] == BUSINESS_NAME:
            return {"ok": True, "business_id": b["id"], "created": False}
    website = config.PUBLIC_URL or "https://example.com"  # placeholder until deployed
    biz_id = db.create_business(user["id"], BUSINESS_NAME, website, PHRASES)
    return {"ok": True, "business_id": biz_id, "created": True,
            "note": "set PUBLIC_URL to the deployed https URL and re-run to update"}


def main() -> None:
    import json
    print(json.dumps(ensure_self_monitor(), indent=2))


if __name__ == "__main__":
    main()
