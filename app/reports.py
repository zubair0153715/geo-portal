"""Daily HTML reports + optional email delivery.

generate_report(business_id) renders the report template with:
  - 14-day visibility score trend
  - latest mentions (which AI said what, where the business placed)
  - competitor names seen across answers
  - Search Console highlights (only when Google is connected with the
    webmasters.readonly scope; failures degrade honestly to 'not available')
  - content tasks from the last Content-agent run
The HTML file is saved under reports_out/ and recorded in the reports table.
Email is sent only when SMTP_USER/SMTP_PASS are configured.
"""

import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, timedelta

from jinja2 import Environment, FileSystemLoader

from . import config, db
from .scheduler import business_score, daily_scores

_UI_DIR = os.path.join(os.path.dirname(__file__), "ui")
_jinja = Environment(loader=FileSystemLoader(_UI_DIR), autoescape=True)


def _gsc_highlights(business_id: int) -> dict:
    """Best-effort Search Console summary. Returns {'available': False, ...}
    honestly when Google isn't connected or the call fails."""
    from . import google_oauth, gsc_client
    from .vault import decrypt_dict
    row = db.get_connection(business_id, "google")
    if not row:
        return {"available": False, "reason": "Google not connected."}
    try:
        scopes = decrypt_dict(row["encrypted_blob"]).get("scopes", [])
    except Exception:
        return {"available": False, "reason": "Could not read stored credentials."}
    if "gsc" not in scopes:
        return {"available": False, "reason": "Search Console scope not granted."}
    try:
        token = google_oauth.get_access_token(business_id)
        sites = gsc_client.list_sites(token)
        if not sites:
            return {"available": False, "reason": "No sites in Search Console."}
        site_url = sites[0]["siteUrl"]  # first verified site
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=28)).isoformat()
        rows = gsc_client.search_analytics(token, site_url, start, end, row_limit=5)
        total_clicks = sum(r["clicks"] for r in rows)
        total_impr = sum(r["impressions"] for r in rows)
        return {"available": True, "site": site_url, "top_queries": rows,
                "total_clicks": total_clicks, "total_impressions": total_impr}
    except Exception as exc:
        return {"available": False, "reason": f"Search Console query failed: {exc}"}


def build_report_context(business_id: int) -> dict:
    biz = db.get_business(business_id)
    if not biz:
        raise ValueError("Business not found.")
    phrases = json.loads(biz["phrases"] or "[]")
    checks = db.recent_checks(business_id, 100)

    mentions = [c for c in checks if c["mention_bool"]]
    competitors = []
    for c in checks:
        for name in json.loads(c["competitors"] or "[]"):
            if name not in competitors:
                competitors.append(name)

    last_content = db.last_agent_runs(business_id).get("content")
    return {
        "business": dict(biz),
        "phrases": phrases,
        "score_7d": business_score(business_id, 7),
        "trend": daily_scores(business_id, 14),
        "total_checks": len(checks),
        "mention_count": len(mentions),
        "latest_mentions": [dict(c) for c in mentions[:10]],
        "competitors": competitors[:12],
        "gsc": _gsc_highlights(business_id),
        "content_note": (last_content["detail"] if last_content else
                         "Content agent has not run yet."),
        "generated_on": date.today().isoformat(),
    }


def generate_report(business_id: int, recipient_email: str = None):
    """Render + save the report; email it when possible.

    Returns (html_path, emailed: bool).
    """
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    ctx = build_report_context(business_id)
    html = _jinja.get_template("report.html").render(**ctx)
    fname = f"report_{business_id}_{date.today().isoformat()}.html"
    path = os.path.join(config.REPORTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    report_id = db.insert_report(business_id, path)
    # Also store the HTML in the DB — authoritative copy on ephemeral disks
    # (Render free wipes the filesystem on restart).
    db.update_report_html(report_id, html)

    emailed = False
    if recipient_email and config.SMTP_USER and config.SMTP_PASS:
        emailed = send_email(recipient_email,
                             f"Daily AI Visibility Report — {ctx['business']['name']}",
                             html)
    return path, emailed


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send one HTML email via the configured SMTP server."""
    msg = MIMEMultipart("alternative")
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.sendmail(config.SMTP_FROM, [to_email], msg.as_string())
        return True
    except Exception:
        return False  # caller records 'emailed: no'; never raises into the job
