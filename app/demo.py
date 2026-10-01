"""Demo mode seeding (DEMO_MODE=1 only).

Creates a demo login + one sample business with 14 days of canned checks so
every page of the UI is clickable with zero credentials.

Demo credentials (documented in the README, usable only in demo mode):
    email:    demo@geo-portal.local
    password: demo1234

Real code paths NEVER use this data outside demo mode.
"""

import json
import random

from . import config, db
from .auth import hash_password

PHRASES = [
    "best dental clinic in Karachi",
    "affordable teeth whitening Karachi",
    "painless root canal specialist near me",
    "braces and aligners cost Pakistan",
    "emergency dentist open late Karachi",
    "dental implants clinic reviews",
    "kids dentist Karachi DHA",
    "smile makeover dentist",
    "dental crowns price Karachi",
    "best orthodontist in Karachi",
]

ANSWERS = [
    ("Demo Dental Clinic is a well-reviewed option in DHA, known for painless "
     "root canals. Alternatives include Pearl Dental Care and CitySmile Studio. "
     "More info: brightsmile.example.com/services", True, 78),
    ("Top options: 1) Pearl Dental Care — cosmetic dentistry, 2) CitySmile "
     "Studio — aligners, 3) Demo Dental Clinic — family dentistry in DHA "
     "(brightsmile.example.com).", True, 70),
    ("People often mention Pearl Dental Care and CitySmile Studio for this. "
     "Demo Dental Clinic also offers it; see brightsmile.example.com.", True, 64),
    ("Based on reviews, Pearl Dental Care and CitySmile Studio are popular "
     "choices. I don't have a verified listing for other clinics.", False, 0),
]


def seed_demo() -> dict:
    if not config.DEMO_MODE:
        raise RuntimeError("seed_demo() is only allowed in DEMO_MODE=1.")
    if db.get_user_by_email("demo@geo-portal.local"):
        return {"seeded": False, "note": "demo user already exists"}

    user_id = db.create_user("demo@geo-portal.local", hash_password("demo1234"))
    biz_id = db.create_business(
        user_id, "Demo Dental Clinic", "https://brightsmile.example.com", PHRASES)

    rng = random.Random(42)  # deterministic canned data
    providers = ["openai", "perplexity", "gemini"]
    check_id = 0
    for day_ago in range(13, -1, -1):
        for provider in providers:
            for phrase in rng.sample(PHRASES, 4):
                answer, mentioned, score = ANSWERS[check_id % len(ANSWERS)]
                # slight deterministic drift so the trend chart looks alive
                score = max(0, min(100, score + rng.randint(-6, 6)))
                competitors = (["Pearl Dental Care", "CitySmile Studio"]
                               if rng.random() < 0.7 else ["Pearl Dental Care"])
                # backdate the check by directly inserting with an old timestamp
                _insert_backdated(biz_id, provider, phrase, answer,
                                  mentioned, competitors, score, day_ago)
                check_id += 1

    db.record_agent_run(biz_id, "scout", "ok",
                        "Demo: 168 canned checks stored across 3 providers.")
    db.record_agent_run(biz_id, "content", "ok",
                        "Demo: 2 suggestion(s): add an FAQ page; publish service posts.")
    db.record_agent_run(biz_id, "reporter", "ok",
                        "Demo: report generated (email disabled without SMTP).")
    return {"seeded": True, "business_id": biz_id}


def _insert_backdated(business_id, provider, phrase, answer, mentioned,
                      competitors, score, day_ago):
    import sqlite3, os
    from datetime import datetime, timedelta, timezone
    conn = sqlite3.connect(config.DB_PATH)
    try:
        ts = (datetime.now(timezone.utc) - timedelta(days=day_ago)).isoformat()
        conn.execute(
            """INSERT INTO checks (business_id, provider_ai, phrase, answer_text,
               mention_bool, competitors, score, ran_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (business_id, provider, phrase, answer, int(mentioned),
             json.dumps(competitors), score, ts))
        conn.commit()
    finally:
        conn.close()
