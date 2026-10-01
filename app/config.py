"""Central configuration. Every secret comes from the environment (or the
encrypted vault at runtime). Nothing secret is ever hardcoded."""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# Credential vault master key (Fernet). Generate: python -m app.vault genkey
VAULT_KEY = env("GEO_VAULT_KEY")

# Signed-cookie session secret. Generate: python -c "import secrets; print(secrets.token_hex(32))"
SESSION_SECRET = env("GEO_SESSION_SECRET")

# SQLite database path (used when DATABASE_URL is not set)
DB_PATH = env("GEO_DB_PATH") or os.path.join(BASE_DIR, "data", "portal.db")

# Postgres connection string (Neon free tier in production). When set, the app
# uses Postgres via psycopg instead of SQLite — no code changes needed.
DATABASE_URL = env("DATABASE_URL")

# Public https URL of the deployed app (empty locally). Used for the OAuth
# redirect URI and the self-monitor business website.
PUBLIC_URL = env("PUBLIC_URL")

# Google OAuth client (created by the operator in Google Cloud Console)
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = env("GOOGLE_REDIRECT_URI") or "http://localhost:8000/connect/google/callback"

# Outgoing mail for daily reports
SMTP_HOST = env("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(env("SMTP_PORT") or "587")
SMTP_USER = env("SMTP_USER")
SMTP_PASS = env("SMTP_PASS")
SMTP_FROM = env("SMTP_FROM") or SMTP_USER

# Demo mode: seeds canned data so the UI is clickable with zero credentials.
# Real code paths never use canned data when this is off.
DEMO_MODE = env("DEMO_MODE") == "1"

# Where generated HTML reports are written
REPORTS_DIR = os.path.join(BASE_DIR, "reports_out")
