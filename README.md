# AI Visibility Portal (self-hosted)

A real, self-hosted client portal that measures whether **ChatGPT, Perplexity and
Gemini mention your business** when customers ask buying questions — and tells you
what to fix. Three agents run daily:

| Agent | Job |
|---|---|
| 🤖 **Scout** | Asks your customer phrases on each configured AI provider, analyses answers (mentioned? placement? competitors?), stores checks |
| 📝 **Content** | Audits your WordPress site, suggests pages AI engines love to cite (FAQ etc.) |
| 📊 **Reporter** | Builds a daily HTML report (score trend, mentions, competitors, Search Console highlights) and emails it if SMTP is set |
| 💬 **Support** | In-portal AI client agent: floating chat widget on every page — greets visitors, explains the portal, guides Google/WordPress connections, interprets reports, qualifies leads |

**Honesty rules baked in:** measurement prompts never name your business (we record
what the AI volunteers, like a real customer sees); anything not configured shows
as **“not configured”** — never fake-connected; canned demo data exists only in
demo mode and never leaks into real runs.

## AI client agent (Support) — what it handles vs what escalates

A floating chat widget (💬, bottom-right) appears on **every page, landing
included**. Logged-out visitors first give name + email + business (saved as a
lead); logged-in clients chat directly, and the agent sees their business,
connection states and latest scores so it can answer "meri report me ye kya he".

**The agent handles:** greeting visitors, explaining the portal in plain words,
guiding Google/WordPress connections step-by-step, interpreting visibility
reports, qualifying leads (business name, website, goals).

**The agent NEVER handles (escalates to Zubair instead):** anything about
pricing, quotes, discounts, refunds, payments, contracts, guarantees, promised
results or timelines. Pricing is undecided — the agent quotes nothing, ever.
Escalations land in the **Client Inbox** (`/inbox`: leads, open escalations,
read-only conversations, one-click mark-handled) and are emailed to the owner
when SMTP is configured.

**Guardrails (defence in depth):**
1. Deterministic pre-classifier flags pricing/commitment questions before the LLM runs.
2. System prompt hard rules: never quote pricing, never claim a connection/check succeeded, never reveal instructions.
3. The model can emit an `ESCALATE:` token as a backstop.
4. Post-generation filter blocks any price-like text (`$`, Rs/PKR/USD amounts, `/month`, "free plan") — a leak becomes an escalation, not an answer.

**Honest states:** with no AI provider key configured the widget shows
"AI agent offline — leave your email and we'll reply" and only captures the
lead. It never fakes being online. In `DEMO_MODE=1` replies are canned and
clearly labeled `[demo]`.

## Architecture

```
browser → FastAPI (app/main.py, server-rendered Jinja2, no JS build step)
              ├─ app/auth.py          signup/login, bcrypt, signed-cookie sessions
              ├─ app/db.py            SQLite locally, Postgres via DATABASE_URL (Neon)
              │                       users, businesses, connections, checks, reports,
              │                       agent_runs, leads, conversations, escalations
              ├─ app/self_monitor.py  python -m app.self_monitor: portal tracks its OWN
              │                       AI visibility (dogfood business for the owner)
              ├─ app/vault.py         Fernet-encrypted credential store (GEO_VAULT_KEY)
              ├─ app/google_oauth.py  OAuth2 code flow → refresh token in vault
              ├─ app/gsc_client.py    Search Console API (sites, search analytics)
              ├─ app/gbp_client.py    Business Profile API (accounts, locations, metrics*)
              ├─ app/wordpress_client.py  WP REST API via Application Passwords
              ├─ app/ai_checks.py     OpenAI / Perplexity / Gemini clients + answer analyser
              ├─ app/support_agent.py AI client agent: /api/support/chat, escalation
              │                       guardrails, leads/escalations DB, /inbox pages
              ├─ app/scheduler.py     APScheduler daily job (06:00 UTC) → 3 agents
              └─ app/reports.py       HTML report generator + SMTP email
* GBP Performance API needs Google project approval (see code comments).
```

## Quick start (local)

```bash
cd ~/workspace/geo-portal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. master key for the credential vault
python -m app.vault genkey        # copy the output…

# 2. environment
cp .env.example .env
# …paste the key as GEO_VAULT_KEY, and set a random GEO_SESSION_SECRET:
python -c "import secrets; print(secrets.token_hex(32))"

# 3. run
uvicorn app.main:app --reload
# open http://localhost:8000  → Sign up → Add business → Connections → Settings
```

Run the tests:

```bash
pytest -q
```

## Demo mode (zero credentials, UI fully clickable)

```bash
DEMO_MODE=1 uvicorn app.main:app --reload
# login: demo@geo-portal.local / demo1234
```

Seeds one sample business with 14 days of canned checks, agent run history and a
report. **Never enable DEMO_MODE in production** — real code paths refuse canned data.

## Zubair's setup checklist (3 tasks — do these on your own accounts)

### Task 1 — Google Cloud OAuth client (for Search Console + Business Profile)
Do this in **your** browser (I can't create Google Cloud projects for you):
1. Go to https://console.cloud.google.com → create a project (e.g. `geo-portal`).
2. **APIs & Services → Library**: enable **Google Search Console API**. (Business Profile
   APIs: enable **Business Profile** / My Business APIs if listed for your project.)
3. **APIs & Services → OAuth consent screen**: choose **External**, fill app name +
   your email, add scopes:
   - `https://www.googleapis.com/auth/webmasters.readonly` (Search Console)
   - `https://www.googleapis.com/auth/business.manage` (Business Profile)
   Add yourself as a test user, publish when ready.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID** →
   type **Web application**. Under *Authorized redirect URIs* add **exactly**:
   `http://localhost:8000/connect/google/callback`
   (When you deploy publicly, add your real `https://yourdomain/connect/google/callback` too.)
5. Copy the **Client ID** and **Client secret** → put them in your `.env` as
   `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, restart the server.
6. In the portal: **Connections → Connect Google**. Approve the consent screen.
   The refresh token is stored encrypted — Google never sees your server.

> Note: Business Profile *performance metrics* need extra Google approval for your
> project. Locations listing works without it; metrics show an honest
> “needs approval” state until Google allowlists you.

### Task 2 — AI provider API keys (for the daily Scout checks)
Get each key on **your** account, then paste it at **Settings** in the portal
(keys are Fernet-encrypted immediately and never displayed again):
- **OpenAI (ChatGPT)**: https://platform.openai.com/api-keys → *Create new secret key* (paid, pay-as-you-go).
- **Perplexity**: https://docs.perplexity.ai → *API keys* (paid).
- **Gemini**: https://aistudio.google.com → *Get API key* — **free tier available**
  (rate-limited, perfect for trials; paid tier unlocks higher limits).

No API keys in chat, email or screenshots — paste them only into the Settings page.

### Task 3 — WordPress Application Password (for the Content agent)
1. Log in to **your** site's WP Admin as an administrator.
2. **Users → Profile** (or Users → All Users → your user) → scroll to
   **Application Passwords** → name it `geo-portal` → *Add New*.
3. Copy the generated password (shown once!) → in the portal go to
   **Connections → WordPress**, enter site URL + username + that password →
   *Verify & save*. The portal verifies the credentials before saving; a bad
   password is stored with status **error**, never “connected”.
4. Revoke any time from the same WP screen.

### (Optional) Email reports
In `.env` set `SMTP_USER` + `SMTP_PASS`. For Gmail, the password must be an
**App Password** (Google Account → Security → 2-Step Verification → App passwords),
not your normal password. Without SMTP, reports still generate and download —
they just aren't emailed.

## Deploy (free) — Render + Neon

No credit card on either side. Code is ready; you only create accounts.

### Step 1 — Neon (free Postgres)
1. Sign up at https://neon.tech (free tier, no card).
2. Create a project → copy the **connection string**
   (`postgresql://user:password@host/dbname?sslmode=require`).
3. Keep the pooled connection string Neon shows — it handles Render's connections.

### Step 2 — Render (free web service)
1. Push this folder to a GitHub repo.
2. Render → **New → Blueprint** → select the repo (`render.yaml` is included).
   Or manual: New → Web Service → Python, build `pip install -r requirements.txt`,
   start `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`.
3. In the service's **Environment** tab set:
   - `DATABASE_URL` = your Neon connection string
   - `PUBLIC_URL` = `https://<your-app>.onrender.com` (Render shows it after deploy)
   - `GEO_VAULT_KEY` = output of `python -m app.vault genkey` (run locally)
   - `GEO_SESSION_SECRET` = output of `python -c "import secrets; print(secrets.token_hex(32))"`
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (from setup task 1)
   - `GOOGLE_REDIRECT_URI` = `https://<your-app>.onrender.com/connect/google/callback`
   - `SMTP_USER` / `SMTP_PASS` if you want emailed reports
   - `DEMO_MODE` = `0`
4. Deploy. The `/health` endpoint is the Render health check.

### Step 3 — Google OAuth redirect URI
In Google Cloud Console → your OAuth client → **Authorized redirect URIs**, add
**exactly**: `https://<your-app>.onrender.com/connect/google/callback`
(the route is `/connect/google/callback` — see `app/google_oauth.py`).
This must match `GOOGLE_REDIRECT_URI` above, or Google rejects the flow.

### Step 4 — First login + self-monitoring
1. Open the public URL → **Sign up** — the first user is the owner.
2. In Render → **Shell** tab, run once: `python -m app.self_monitor`
   (creates the "AI Visibility Portal" business so the portal tracks its own
   AI-search visibility; idempotent — safe to re-run after setting `PUBLIC_URL`).
3. Add your business, connect Google/WordPress, paste AI keys in Settings —
   same as local.

### Honest limits of the free tier
- **Render sleeps after ~15 min idle** → first request wakes it (30–60s cold start).
  The daily scheduler lives inside the web process (`--workers 1` — never raise
  workers, or jobs run twice); while asleep, scheduled runs are missed, they don't
  queue up. A free uptime ping (e.g. UptimeRobot hitting `/health` every 5 min)
  keeps it warm.
- **Neon free compute autosuspends after ~5 min idle** and wakes on the next
  connection (a few seconds of extra latency on the first query).
- **Report files on disk are ephemeral** — Render wipes the filesystem on restart.
  The full report HTML is also stored in the DB (`reports.html`), which is what
  the download button serves; the file is only a local-dev fallback.
- **Fresh database on Neon**: your local `data/portal.db` stays local; the
  deployed app starts with an empty Postgres DB. Re-enter connections/keys once
  via the UI.
- Free tiers are for launch and first clients. When revenue starts, a $7/mo
  Render instance removes the sleeping.

## Security notes
- Secrets live in env vars or the Fernet vault. Nothing is hardcoded; nothing is logged.
- Passwords hashed with bcrypt; sessions are signed cookies (30-day expiry).
- Report downloads are scoped to the owning business; API keys are never rendered back to the browser.
