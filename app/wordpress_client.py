"""WordPress REST API client using Application Passwords (HTTP Basic auth).

The application password is stored Fernet-encrypted in the vault and is only
ever sent over HTTPS to the site's own wp-json endpoint. Never logged.

Creating one (site admin): Users > Profile > Application Passwords > add a new
one, then paste it here once. It can be revoked any time from the same screen.
"""

import httpx
from httpx import BasicAuth


class WPClient:
    def __init__(self, site_url: str, username: str, app_password: str):
        self.base = site_url.rstrip("/") + "/wp-json"
        # BasicAuth holds the secret in memory only for the request lifetime.
        self.auth = BasicAuth(username=username, password=app_password)

    def _get(self, path: str, params: dict = None) -> httpx.Response:
        with httpx.Client(timeout=30) as client:
            resp = client.get(self.base + path, auth=self.auth, params=params or {})
            resp.raise_for_status()
            return resp

    def verify(self) -> dict:
        """Check the credentials work. Returns {'name', 'description', 'url'}.

        Raises on bad credentials / unreachable site so the UI can show an
        honest error instead of pretending to be connected.
        """
        data = self._get("/").json()
        if "namespaces" not in data or "wp/v2" not in data["namespaces"]:
            raise RuntimeError("Site responded but the WP REST API (wp/v2) is not available.")
        return {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "url": data.get("url", ""),
        }

    def recent_posts(self, n: int = 10) -> list:
        data = self._get("/wp/v2/posts", {"per_page": max(1, min(n, 20)),
                                          "_fields": "id,date,link,title,slug"}).json()
        return [{"id": p["id"], "date": p["date"], "link": p["link"],
                 "title": p["title"]["rendered"], "slug": p["slug"]} for p in data]

    def recent_pages(self, n: int = 10) -> list:
        data = self._get("/wp/v2/pages", {"per_page": max(1, min(n, 20)),
                                          "_fields": "id,date,link,title,slug"}).json()
        return [{"id": p["id"], "date": p["date"], "link": p["link"],
                 "title": p["title"]["rendered"], "slug": p["slug"]} for p in data]

    def content_audit(self) -> dict:
        """Small honest content audit used by the Content agent."""
        info = self.verify()
        posts = self.recent_posts(10)
        pages = self.recent_pages(10)
        suggestions = []
        if len(posts) < 3:
            suggestions.append("Fewer than 3 recent posts — publishing FAQ-style posts "
                               "about your services helps AI search cite you.")
        if not any("faq" in (p["slug"] or "").lower() for p in pages + posts):
            suggestions.append("No FAQ page found — an FAQ page is the single most "
                               "cited page type by AI answer engines.")
        return {"site": info, "post_count_sample": len(posts),
                "page_count_sample": len(pages), "suggestions": suggestions}
