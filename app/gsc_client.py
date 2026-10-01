"""Google Search Console API client (real API, no fakes).

Docs: https://developers.google.com/webmaster-tools/search-console-api-original/v3
"""

import httpx

BASE = "https://www.googleapis.com/webmasters/v3"


def list_sites(access_token: str) -> list:
    """Return the Search Console-verified sites, e.g.
    [{'siteUrl': 'sc-domain:example.com', 'permissionLevel': 'siteOwner'}]."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{BASE}/sites",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json().get("siteEntry", [])


def search_analytics(access_token: str, site_url: str,
                     start_date: str, end_date: str,
                     dimensions: list = None, row_limit: int = 25) -> list:
    """Query clicks / impressions / CTR / position per query (or page).

    Dates are 'YYYY-MM-DD'. Returns rows like:
    {'query': 'best dental clinic karachi', 'clicks': 12, 'impressions': 340,
     'ctr': 0.035, 'position': 8.2}
    """
    dimensions = dimensions or ["query"]
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "dataState": "final",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{BASE}/sites/{_encode_site(site_url)}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )
        resp.raise_for_status()
        rows = []
        for r in resp.json().get("rows", []):
            keys = r.get("keys", [])
            rows.append({
                "query": keys[0] if keys else "",
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": r.get("ctr", 0),
                "position": r.get("position", 0),
            })
        return rows


def _encode_site(site_url: str) -> str:
    # The API expects the site URL URL-encoded in the path.
    import urllib.parse
    return urllib.parse.quote(site_url, safe="")
