"""Google Business Profile API client (real API, no fakes).

Endpoints used:
  - Account Management: https://mybusinessaccountmanagement.googleapis.com/v1
      list accounts + locations. Works with the business.manage scope.
  - Performance API: https://businessprofileperformance.googleapis.com/v1
      daily metrics time series (views, searches, calls...).

IMPORTANT — API approval: the Business Profile *Performance* API is a
restricted API. Your Google Cloud project must be allowlisted/approved by
Google for it, otherwise calls return 403 PERMISSION_DENIED. The code below
surfaces that error honestly instead of inventing numbers. See:
https://developers.google.com/my-business/content/performance-data
"""

import httpx

ACCOUNT_BASE = "https://mybusinessaccountmanagement.googleapis.com/v1"
PERF_BASE = "https://businessprofileperformance.googleapis.com/v1"


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def list_accounts(access_token: str) -> list:
    """Return GBP accounts: [{'name': 'accounts/123', 'accountName': '...'}]."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{ACCOUNT_BASE}/accounts", headers=_headers(access_token))
        resp.raise_for_status()
        return resp.json().get("accounts", [])


def list_locations(access_token: str, account_name: str) -> list:
    """Return locations for an account, e.g. [{'name': 'accounts/123/locations/456',
    'title': 'Demo Dental Clinic', ...}]."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{ACCOUNT_BASE}/{account_name}/locations",
            headers=_headers(access_token),
            params={"readMask": "name,title,storefrontAddress,websiteUri"},
        )
        resp.raise_for_status()
        return resp.json().get("locations", [])


def fetch_daily_metrics(access_token: str, location_name: str,
                        start_ymd: str, end_ymd: str) -> dict:
    """Multi-daily metrics time series for one location.

    Dates as 'YYYY-MM-DD'. Raises httpx.HTTPStatusError with 403 when the
    Cloud project is not approved for the Performance API — callers should
    catch that and show an honest 'needs approval' state.
    """
    body = {
        "dailyMetrics": [
            "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
            "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
            "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
            "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
            "CALL_CLICKS",
            "WEBSITE_CLICKS",
            "BUSINESS_DIRECTION_REQUESTS",
        ],
        "dailyRange": {"startDate": _ymd(start_ymd), "endDate": _ymd(end_ymd)},
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{PERF_BASE}/{location_name}:fetchMultiDailyMetricsTimeSeries",
            headers=_headers(access_token),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


def _ymd(ymd: str) -> dict:
    y, m, d = (int(x) for x in ymd.split("-"))
    return {"year": y, "month": m, "day": d}
