"""APScheduler daily job: Scout / Content / Reporter agents.

Scout    — for each business with AI provider keys in the vault, runs the
           phrase pack across configured providers, analyses answers, stores
           checks.
Content  — if WordPress is connected, runs the content audit and stores the
           suggestions count.
Reporter — generates the daily HTML report and emails it when SMTP is set.

In DEMO_MODE the job returns immediately: real paths never touch canned data,
and canned data never leaks into real runs.
"""

import logging
import traceback

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db
from .ai_checks import AI_PROVIDER_LABELS, analyze_answer, run_check
from .vault import decrypt_dict

log = logging.getLogger("geo-portal.scheduler")

AI_PROVIDERS = ("openai", "perplexity", "gemini")


def _ai_keys(business_id: int) -> dict:
    """provider -> api_key for configured AI providers (decrypted, never logged)."""
    keys = {}
    for provider in AI_PROVIDERS:
        row = db.get_connection(business_id, provider)
        if not row or row["status"] != "connected":
            continue
        try:
            creds = decrypt_dict(row["encrypted_blob"])
            if creds.get("api_key"):
                keys[provider] = creds["api_key"]
        except Exception as exc:
            log.warning("Could not decrypt %s key for business %s: %s",
                        provider, business_id, type(exc).__name__)
    return keys


def run_checks_for_business(business_id: int) -> dict:
    """Run one full Scout pass for a single business. Returns a summary."""
    biz = db.get_business(business_id)
    if not biz:
        return {"ok": 0, "errors": 0, "note": "business not found"}
    import json
    phrases = json.loads(biz["phrases"] or "[]")
    keys = _ai_keys(business_id)
    if not keys:
        db.record_agent_run(business_id, "scout", "skipped",
                            "No AI provider keys configured (Settings page).")
        return {"ok": 0, "errors": 0, "note": "no AI keys configured"}

    ok, errors = 0, 0
    for provider, api_key in keys.items():
        for phrase in phrases:
            try:
                answer = run_check(provider, api_key, phrase)
                result = analyze_answer(answer, biz["name"], biz["website"])
                db.insert_check(business_id, provider, phrase, answer,
                                result["mentioned"], result["competitors"],
                                result["score"])
                ok += 1
            except Exception as exc:
                errors += 1
                log.warning("check failed (%s / %s): %s",
                            provider, phrase[:40], type(exc).__name__)
    db.record_agent_run(
        business_id, "scout", "ok" if errors == 0 else "error",
        f"{ok} checks stored, {errors} failed across {len(keys)} provider(s).")
    return {"ok": ok, "errors": errors}


def run_content_audit(business_id: int) -> dict:
    """Content agent: WordPress content audit, if connected."""
    from .wordpress_client import WPClient
    row = db.get_connection(business_id, "wordpress")
    if not row or row["status"] != "connected":
        db.record_agent_run(business_id, "content", "skipped",
                            "WordPress not connected.")
        return {"suggestions": []}
    try:
        creds = decrypt_dict(row["encrypted_blob"])
        client = WPClient(creds["site_url"], creds["username"], creds["app_password"])
        audit = client.content_audit()
        db.record_agent_run(
            business_id, "content", "ok",
            f"{len(audit['suggestions'])} suggestion(s): "
            + "; ".join(audit["suggestions"][:3]))
        return audit
    except Exception as exc:
        db.record_agent_run(business_id, "content", "error", str(exc)[:200])
        return {"suggestions": [], "error": str(exc)[:200]}


def run_reporter(business_id: int, recipient_email: str = None) -> dict:
    """Reporter agent: generate the daily report, email it if SMTP is set."""
    from .reports import generate_report
    try:
        path, emailed = generate_report(business_id, recipient_email)
        db.record_agent_run(
            business_id, "reporter", "ok",
            f"Report generated ({path}). Emailed: {'yes' if emailed else 'no (SMTP not configured)'}.")
        return {"path": path, "emailed": emailed}
    except Exception as exc:
        db.record_agent_run(business_id, "reporter", "error", str(exc)[:200])
        return {"error": str(exc)[:200]}


def run_daily_checks() -> None:
    """The scheduled daily job: all three agents for every business."""
    if config.DEMO_MODE:
        log.info("DEMO_MODE: daily job skipped (canned data is pre-seeded).")
        return
    for biz in db.all_businesses():
        business_id = biz["id"]
        try:
            run_checks_for_business(business_id)
        except Exception:
            log.error("scout crashed for business %s:\n%s",
                      business_id, traceback.format_exc())
            db.record_agent_run(business_id, "scout", "error", "crashed")
        try:
            run_content_audit(business_id)
        except Exception:
            log.error("content agent crashed for business %s", business_id)
        try:
            owner = db.get_user(biz["user_id"])
            run_reporter(business_id, owner["email"] if owner else None)
        except Exception:
            log.error("reporter crashed for business %s", business_id)


# ------------------------------------------------------------ scoring ----
def daily_scores(business_id: int, days: int = 14) -> list:
    """[{date: 'YYYY-MM-DD', score: avg|None}] oldest first."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for c in db.checks_since(business_id, days):
        buckets[c["ran_at"][:10]].append(c["score"])
    out = []
    for date in sorted(buckets):
        vals = buckets[date]
        out.append({"date": date,
                    "score": round(sum(vals) / len(vals)) if vals else None})
    return out


def business_score(business_id: int, days: int = 7):
    """Average of daily averages over the last N days; None when no data."""
    series = [d["score"] for d in daily_scores(business_id, days)
              if d["score"] is not None]
    if not series:
        return None
    return round(sum(series) / len(series))


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    # Daily at 06:00 UTC (~11:00 PKT).
    sched.add_job(run_daily_checks, "cron", hour=6, minute=0,
                  id="daily-visibility", replace_existing=True,
                  misfire_grace_time=3600)
    sched.start()
    log.info("Scheduler started: daily visibility job at 06:00 UTC.")
    return sched
