import requests
import re
import os
from urllib.parse import urlparse, urljoin, parse_qs

USERNAME = os.environ["TTC_USERNAME"]
PASSWORD = os.environ["TTC_PASSWORD"]

BASE_URL = "https://smfidentity.agris.com.vn"
API_URL  = "https://smfapi.agris.com.vn/Manufacturing/Report/GetStoreReport"
TARGET_STORE = "RP_QM_DL03_LEVEL"

def get_token():
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}

    auth_url = (
        f"{BASE_URL}/connect/authorize"
        "?client_id=smart_factory_web_app"
        "&redirect_uri=https%3A%2F%2Fdigifactory.agris.com.vn"
        "&response_type=token%20id_token"
        "&scope=openid%20profile%20SmartFactoryApiScope"
        "&state=abc123"
        "&nonce=xyz123"
    )

    r = session.get(auth_url, headers=headers)
    login_url = r.url
    r = session.get(login_url, headers=headers)

    token_match = re.search(
        r'name="__RequestVerificationToken".*?value="(.*?)"', r.text
    )
    verification_token = token_match.group(1)

    parsed = urlparse(login_url)
    return_url = parse_qs(parsed.query).get("ReturnUrl", [""])[0]

    payload = {
        "ReturnUrl": return_url,
        "Username":  USERNAME,
        "Password":  PASSWORD,
        "button":    "login",
        "__RequestVerificationToken": verification_token,
        "RememberLogin": "false"
    }

    r = session.post(login_url, data=payload, headers=headers, allow_redirects=False)

    for step in range(20):
        if "location" not in r.headers:
            print(f"  Dung tai step {step}, status={r.status_code}, khong co location")
            print(f"  Body: {r.text[:300]}")
            break
        next_url = urljoin(BASE_URL, r.headers["location"])
        print(f"  Step {step}: {r.status_code} -> {next_url[:80]}")
        if "access_token" in next_url:
            fragment = urlparse(next_url).fragment
            params   = dict(q.split("=") for q in fragment.split("&"))
            return params["access_token"]
        r = session.get(next_url, headers=headers, allow_redirects=False)

    raise Exception("Khong lay duoc token")

print("=== TEST LOGIN ===")
try:
    token = get_token()
    print(f"LOGIN THANH CONG")
    print(f"Token (20 ky tu dau): {token[:20]}...")
except Exception as e:
    print(f"LOGIN THAT BAI: {e}")
    raise SystemExit(1)

print("\n=== TEST FETCH API ===")
api_headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type":  "application/json",
    "Origin":        "https://digifactory.agris.com.vn",
    "Referer":       "https://digifactory.agris.com.vn/"
}
payload = {
    "targetStoreName": TARGET_STORE,
    "fromDate":  "2026-04-28",
    "toDate":    "2026-04-28",
    "multiple":  False,
    "potCode":   "NULL",
    "step":      ",20865993-2d82-40a6-a28a-08da69f83e9e,"
}
r = requests.post(API_URL, headers=api_headers, json=payload)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    rows = len(data.get("data", []))
    print(f"FETCH THANH CONG - {rows} rows")
else:
    print(f"FETCH THAT BAI: {r.text[:200]}")
    raise SystemExit(1)
