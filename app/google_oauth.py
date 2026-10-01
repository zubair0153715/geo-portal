"""Google OAuth2 authorization-code flow for Search Console + Business Profile.

Routes:
    GET /connect/google/start?business_id=<id>&scopes=gsc,gbp
    GET /connect/google/callback?code=...&state=...

The refresh token is stored Fernet-encrypted in the vault (connections table,
provider='google'). Nothing secret is logged.

Scopes requested:
    Search Console : https://www.googleapis.com/auth/webmasters.readonly
    Business Profile: https://www.googleapis.com/auth/business.manage

NOTE on Business Profile: reading locations works with business.manage, but the
*Performance* API (metrics like views/searches) requires your Google Cloud
project to be approved for the Business Profile Performance API. Until Google
approves it, performance calls return 403 — the UI surfaces that honestly.
"""

import urllib.parse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from . import config, db
from .vault import decrypt_dict, encrypt_dict

router = APIRouter()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = {
    "gsc": "https://www.googleapis.com/auth/webmasters.readonly",
    "gbp": "https://www.googleapis.com/auth/business.manage",
}


def _state_signer() -> URLSafeSerializer:
    if not config.SESSION_SECRET:
        raise RuntimeError("GEO_SESSION_SECRET is not set.")
    return URLSafeSerializer(config.SESSION_SECRET, salt="google-oauth-state")


def _client_ready() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


@router.get("/connect/google/start")
def google_start(request: Request, business_id: int, scopes: str = "gsc,gbp"):
    from .auth import get_current_user
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    biz = db.get_business(business_id)
    if not biz or biz["user_id"] != user["id"]:
        return HTMLResponse("Business not found.", status_code=404)
    if not _client_ready():
        return HTMLResponse(
            "Google OAuth is not configured yet. The operator must create an OAuth "
            "client in Google Cloud Console and set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET "
            "(see README, setup task 1).", status_code=503)

    wanted = [s.strip() for s in scopes.split(",") if s.strip() in SCOPES]
    if not wanted:
        wanted = ["gsc", "gbp"]
    scope_str = " ".join(SCOPES[s] for s in wanted)
    state = _state_signer().dumps({"business_id": business_id, "scopes": wanted})

    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": scope_str,
        # offline + consent => we receive a refresh_token we can store
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(AUTH_URL + "?" + urllib.parse.urlencode(params), status_code=303)


@router.get("/connect/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    from .auth import get_current_user
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if error:
        return HTMLResponse(f"Google authorization failed: {error}", status_code=400)
    try:
        payload = _state_signer().loads(state)
        business_id = int(payload["business_id"])
        wanted = payload.get("scopes", ["gsc", "gbp"])
    except (BadSignature, KeyError, ValueError):
        return HTMLResponse("Invalid OAuth state.", status_code=400)
    biz = db.get_business(business_id)
    if not biz or biz["user_id"] != user["id"]:
        return HTMLResponse("Business not found.", status_code=404)

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(TOKEN_URL, data={
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            resp.raise_for_status()
            tokens = resp.json()
    except Exception as exc:
        return HTMLResponse(f"Token exchange failed: {exc}", status_code=502)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return HTMLResponse(
            "Google did not return a refresh token. Try disconnecting the app at "
            "myaccount.google.com > Security > Third-party access and reconnecting.",
            status_code=502)

    # Merge with any existing Google connection (keep previously granted scopes).
    existing = {}
    row = db.get_connection(business_id, "google")
    if row:
        try:
            existing = decrypt_dict(row["encrypted_blob"])
        except Exception:
            existing = {}
    granted = sorted(set(existing.get("scopes", [])) | set(wanted))
    blob = encrypt_dict({
        "refresh_token": refresh_token,   # SECRET — encrypted at rest, never logged
        "scopes": granted,
    })
    db.upsert_connection(business_id, "google", blob, status="connected")
    return RedirectResponse(f"/connections?business_id={business_id}&google=ok", status_code=303)


def get_access_token(business_id: int) -> str:
    """Exchange the stored refresh token for a short-lived access token."""
    row = db.get_connection(business_id, "google")
    if not row:
        raise RuntimeError("Google is not connected for this business.")
    creds = decrypt_dict(row["encrypted_blob"])  # never logged
    with httpx.Client(timeout=30) as client:
        resp = client.post(TOKEN_URL, data={
            "refresh_token": creds["refresh_token"],
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        return resp.json()["access_token"]


def disconnect_google(business_id: int) -> None:
    db.delete_connection(business_id, "google")
