"""AI Visibility Portal — FastAPI application.

Run locally:
    uvicorn app.main:app --reload
Then open http://localhost:8000

Pages are server-rendered with Jinja2 (templates in app/ui/). No JS build step.
"""

import json
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, config, db, google_oauth, support_agent
from .ai_checks import AI_PROVIDER_LABELS, analyze_answer, build_prompt_pack
from .vault import decrypt_dict, encrypt_dict

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "ui"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if config.DEMO_MODE:
        from .demo import seed_demo
        seed_demo()
    else:
        from .scheduler import start_scheduler
        app.state.scheduler = start_scheduler()
    yield
    sched = getattr(app.state, "scheduler", None)
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="AI Visibility Portal", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
app.include_router(auth.router)
app.include_router(google_oauth.router)
app.include_router(support_agent.router)


# ------------------------------------------------------------ helpers ----
def _ctx(request: Request, **kw):
    user = auth.get_current_user(request)
    base = {"request": request, "user": user, "demo_mode": config.DEMO_MODE}
    base.update(kw)
    return base


def _require_biz(request: Request, business_id: int):
    """Return (user, business) or a RedirectResponse when unauthorized."""
    user = auth.get_current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    biz = db.get_business(business_id) if business_id else None
    if not biz or biz["user_id"] != user["id"]:
        first = (db.list_businesses(user["id"]) or [None])[0]
        if first:
            return user, RedirectResponse(
                f"{request.url.path}?business_id={first['id']}", status_code=303)
        return user, RedirectResponse("/onboarding", status_code=303)
    return (user, biz), None


def _conn_status(business_id: int) -> dict:
    """provider -> 'connected' | 'error' | 'not_configured' (honest states)."""
    providers = ["google", "openai", "perplexity", "gemini", "wordpress"]
    rows = {r["provider"]: r for r in db.list_connections(business_id)}
    out = {}
    for p in providers:
        if p in rows:
            out[p] = rows[p]["status"]
        else:
            out[p] = "not_configured"
    return out


# --------------------------------------------------------------- pages ----
@app.get("/health")
def health():
    """Unauthenticated health check (used by Render)."""
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    if auth.get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "landing.html", _ctx(request))


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_page(request: Request):
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "onboarding.html", _ctx(request))


@app.post("/onboarding")
def onboarding_submit(request: Request,
                      name: str = Form(...),
                      website: str = Form(...),
                      phrases: str = Form(...)):
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    phrase_list = [p.strip() for p in phrases.splitlines() if p.strip()][:10]
    if not name.strip() or not website.strip() or not phrase_list:
        return templates.TemplateResponse(request,
            "onboarding.html",
            _ctx(request, error="Business name, website and at least one phrase are required."),
            status_code=400)
    if not website.startswith(("http://", "https://")):
        website = "https://" + website.strip()
    biz_id = db.create_business(user["id"], name, website, phrase_list)
    return RedirectResponse(f"/connections?business_id={biz_id}", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, business_id: int = 0):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    user, biz = res
    from .scheduler import business_score, daily_scores
    phrases = json.loads(biz["phrases"] or "[]")
    trend = daily_scores(biz["id"], 14)
    checks = db.recent_checks(biz["id"], 30)
    competitors = []
    for c in checks:
        for n in json.loads(c["competitors"] or "[]"):
            if n not in competitors:
                competitors.append(n)
    pack = build_prompt_pack(biz["name"], biz["website"], phrases)
    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, business=biz, phrases=phrases,
        score_7d=business_score(biz["id"], 7),
        trend_json=json.dumps(trend),
        recent_checks=[dict(c) for c in checks],
        competitors=competitors[:10],
        conn=_conn_status(biz["id"]),
        pack_prompts=pack["chatgpt"][:5],
        labels=AI_PROVIDER_LABELS,
        businesses=db.list_businesses(user["id"])))


@app.post("/manual-check")
def manual_check(request: Request, business_id: int = Form(...),
                 phrase: str = Form(...), answer: str = Form(...)):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    result = analyze_answer(answer, biz["name"], biz["website"])
    db.insert_check(biz["id"], "manual", phrase.strip(), answer.strip(),
                    result["mentioned"], result["competitors"], result["score"])
    return RedirectResponse(f"/dashboard?business_id={biz['id']}", status_code=303)


@app.get("/connections", response_class=HTMLResponse)
def connections_page(request: Request, business_id: int = 0, google: str = ""):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    user, biz = res
    gsc_ready = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    return templates.TemplateResponse(request, "connections.html", _ctx(
        request, business=biz, conn=_conn_status(biz["id"]),
        gsc_ready=gsc_ready, google_ok=(google == "ok"),
        businesses=db.list_businesses(user["id"])))


@app.post("/settings/keys")
def save_api_key(request: Request, business_id: int = Form(...),
                 provider: str = Form(...), api_key: str = Form(...)):
    """Store an AI provider API key in the encrypted vault."""
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    if provider not in ("openai", "perplexity", "gemini"):
        return HTMLResponse("Unknown provider.", status_code=400)
    api_key = api_key.strip()
    if not api_key:
        return HTMLResponse("Empty key.", status_code=400)
    # The raw key is encrypted immediately; it is never logged or echoed back.
    db.upsert_connection(biz["id"], provider, encrypt_dict({"api_key": api_key}))
    return RedirectResponse(f"/connections?business_id={biz['id']}", status_code=303)


@app.post("/settings/keys/delete")
def delete_api_key(request: Request, business_id: int = Form(...),
                   provider: str = Form(...)):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    db.delete_connection(biz["id"], provider)
    return RedirectResponse(f"/connections?business_id={biz['id']}", status_code=303)


@app.post("/connections/wordpress")
def connect_wordpress(request: Request, business_id: int = Form(...),
                      site_url: str = Form(...), username: str = Form(...),
                      app_password: str = Form(...)):
    """Verify WordPress Application Password, then store it encrypted."""
    from .wordpress_client import WPClient
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    site_url = site_url.strip()
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url
    try:
        info = WPClient(site_url, username.strip(), app_password.strip()).verify()
    except Exception as exc:
        db.upsert_connection(
            biz["id"], "wordpress",
            encrypt_dict({"site_url": site_url, "username": username.strip(),
                          "app_password": app_password.strip()}),
            status="error")
        return templates.TemplateResponse(request,
            "connections.html",
            _ctx(request, business=biz, conn=_conn_status(biz["id"]),
                 gsc_ready=bool(config.GOOGLE_CLIENT_ID),
                 wp_error=f"Verification failed: {exc}. Saved as 'error' — fix and retry."),
            status_code=400)
    db.upsert_connection(
        biz["id"], "wordpress",
        encrypt_dict({"site_url": site_url, "username": username.strip(),
                      "app_password": app_password.strip()}),
        status="connected")
    return RedirectResponse(
        f"/connections?business_id={biz['id']}&wp={info['name']}", status_code=303)


@app.post("/connect/google/disconnect")
def google_disconnect(request: Request, business_id: int = Form(...)):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    google_oauth.disconnect_google(biz["id"])
    return RedirectResponse(f"/connections?business_id={biz['id']}", status_code=303)


@app.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request, business_id: int = 0):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    user, biz = res
    runs = db.last_agent_runs(biz["id"])
    agents = [
        {"key": "scout", "name": "Scout",
         "job": "Daily AI visibility checks across configured providers × phrases."},
        {"key": "content", "name": "Content",
         "job": "WordPress content audit → suggestions that help AI engines cite you."},
        {"key": "reporter", "name": "Reporter",
         "job": "Daily HTML report (+ email when SMTP is configured)."},
    ]
    for a in agents:
        a["last"] = dict(runs[a["key"]]) if a["key"] in runs else None
    return templates.TemplateResponse(request, "agents.html", _ctx(
        request, business=biz, agents=agents,
        businesses=db.list_businesses(user["id"])))


@app.post("/agents/run-now")
def agents_run_now(request: Request, business_id: int = Form(...),
                   background: BackgroundTasks = None):
    """Trigger a Scout pass right now (uses the client's own API keys)."""
    from .scheduler import run_checks_for_business
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    background.add_task(run_checks_for_business, biz["id"])
    return RedirectResponse(f"/agents?business_id={biz['id']}", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, business_id: int = 0):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    user, biz = res
    reports = [dict(r) for r in db.list_reports(biz["id"])]
    for r in reports:
        r["filename"] = os.path.basename(r["html_path"])
    return templates.TemplateResponse(request, "reports.html", _ctx(
        request, business=biz, reports=reports,
        smtp_on=bool(config.SMTP_USER and config.SMTP_PASS),
        businesses=db.list_businesses(user["id"])))


@app.post("/reports/generate")
def reports_generate(request: Request, business_id: int = Form(...)):
    from .reports import generate_report
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    user, biz = res
    generate_report(biz["id"], user["email"])
    return RedirectResponse(f"/reports?business_id={biz['id']}", status_code=303)


@app.get("/reports/files/{filename}")
def report_file(request: Request, filename: str, business_id: int = 0, download: int = 0):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    _, biz = res
    safe = os.path.basename(filename)
    if not safe.startswith(f"report_{biz['id']}_") or not safe.endswith(".html"):
        return HTMLResponse("Not found.", status_code=404)
    # Prefer the DB copy (authoritative on ephemeral hosting); fall back to disk.
    for r in db.list_reports(biz["id"]):
        row = dict(r)
        if os.path.basename(row["html_path"]) == safe and row.get("html"):
            if download:
                return HTMLResponse(row["html"], headers={
                    "Content-Disposition": f'attachment; filename="{safe}"'})
            return HTMLResponse(row["html"])
    path = os.path.join(config.REPORTS_DIR, safe)
    if not os.path.isfile(path):
        return HTMLResponse("Not found.", status_code=404)
    if download:
        return FileResponse(path, media_type="text/html", filename=safe)
    return FileResponse(path, media_type="text/html")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, business_id: int = 0):
    res, redirect = _require_biz(request, business_id)
    if redirect:
        return redirect
    user, biz = res
    return templates.TemplateResponse(request, "settings.html", _ctx(
        request, business=biz, conn=_conn_status(biz["id"]),
        labels=AI_PROVIDER_LABELS,
        businesses=db.list_businesses(user["id"])))
