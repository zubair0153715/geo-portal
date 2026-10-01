"""Local signup/login with bcrypt password hashing and signed-cookie sessions.

Sessions are signed (not encrypted) with itsdangerous using GEO_SESSION_SECRET.
The cookie only carries the user id — no secrets inside.
"""

import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config, db

router = APIRouter()
templates = Jinja2Templates(directory=str(__import__("os").path.join(
    __import__("os").path.dirname(__file__), "ui")))


def _signer() -> URLSafeTimedSerializer:
    secret = config.SESSION_SECRET
    if not secret:
        raise RuntimeError(
            "GEO_SESSION_SECRET is not set. Generate one with "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return URLSafeTimedSerializer(secret, salt="geo-portal-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))
    except Exception:
        return False


def set_session(response: RedirectResponse, user_id: int) -> None:
    token = _signer().dumps({"uid": user_id})
    response.set_cookie("geo_session", token, httponly=True, samesite="lax", max_age=30 * 86400)


def clear_session(response: RedirectResponse) -> None:
    response.delete_cookie("geo_session")


def get_current_user(request: Request):
    token = request.cookies.get("geo_session")
    if not token:
        return None
    try:
        data = _signer().loads(token, max_age=30 * 86400)
    except BadSignature:
        return None
    return db.get_user(int(data["uid"]))


def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        return None
    return user


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"request": request, "error": None})


@router.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    email = email.strip().lower()
    if not email or "@" not in email:
        return templates.TemplateResponse(request,
            "signup.html", {"request": request, "error": "Please enter a valid email."},
            status_code=400)
    if len(password) < 8:
        return templates.TemplateResponse(request,
            "signup.html", {"request": request, "error": "Password must be at least 8 characters."},
            status_code=400)
    if db.get_user_by_email(email):
        return templates.TemplateResponse(request,
            "signup.html", {"request": request, "error": "An account with that email already exists."},
            status_code=400)
    user_id = db.create_user(email, hash_password(password))
    resp = RedirectResponse("/onboarding", status_code=303)
    set_session(resp, user_id)
    return resp


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    user = db.get_user_by_email(email.strip().lower())
    if not user or not check_password(password, user["pw_hash"]):
        return templates.TemplateResponse(request,
            "login.html", {"request": request, "error": "Wrong email or password."},
            status_code=401)
    # First-time users with no business go through onboarding.
    has_business = bool(db.list_businesses(user["id"]))
    resp = RedirectResponse("/dashboard" if has_business else "/onboarding", status_code=303)
    set_session(resp, user["id"])
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    clear_session(resp)
    return resp
