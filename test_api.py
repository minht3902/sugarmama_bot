import requests
import re
import os
from urllib.parse import urlparse, urljoin, parse_qs

USERNAME = os.environ["TTC_USERNAME"]
PASSWORD = os.environ["TTC_PASSWORD"]
BASE_URL = "https://smfidentity.agris.com.vn"

session = requests.Session()
headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}

auth_url = (
    f"{BASE_URL}/connect/authorize"
    "?client_id=smart_factory_web_app"
    "&redirect_uri=https%3A%2F%2Fdigifactory.agris.com.vn"
    "&response_type=token%20id_token"
    "&scope=openid%20profile%20SmartFactoryApiScope"
    "&state=abc123&nonce=xyz123"
)

print("Dang ket noi...")
r = session.get(auth_url, headers=headers)
print(f"  Auth redirect: {r.status_code} -> {r.url[:60]}")

login_url = r.url
r = session.get(login_url, headers=headers)
print(f"  Login page: {r.status_code}")

token_match = re.search(
    r'name="__RequestVerificationToken".*?value="(.*?)"', r.text
)
if not token_match:
    print("FAIL: Khong lay duoc verification token")
    print(f"  Response snippet: {r.text[:300]}")
    raise SystemExit(1)

print("  OK: Lay duoc verification token")

parsed     = urlparse(login_url)
return_url = parse_qs(parsed.query).get("ReturnUrl", [""])[0]
payload = {
    "ReturnUrl": return_url,
    "Username":  USERNAME,
    "Password":  PASSWORD,
    "button":    "login",
    "__RequestVerificationToken": token_match.group(1),
    "RememberLogin": "false"
}

print("POST login...")
r = session.post(login_url, data=payload, headers=headers, allow_redirects=False)

token = None
for step in range(1, 25):
    loc = r.headers.get("location", "")
    print(f"  Step {step}: status={r.status_code} location={loc[:80]}")

    if not loc:
        print(f"  Body snippet: {r.text[:400]}")
        break

    next_url = urljoin(BASE_URL, loc)

    if "access_token" in next_url:
        fragment = urlparse(next_url).fragment
        params   = dict(q.split("=") for q in fragment.split("&") if "=" in q)
        token    = params.get("access_token")
        break

    r = session.get(next_url, headers=headers, allow_redirects=False)

if not token:
    print("FAIL: Khong lay duoc access token")
    raise SystemExit(1)

print(f"LOGIN THANH CONG!")
print(f"  Token (20 ky tu dau): {token[:20]}...")

print("Test fetch API...")
API_URL = "https://smfapi.agris.com.vn/Manufacturing/Report/GetStoreReport"
api_headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type":  "application/json",
    "Origin":        "https://digifactory.agris.com.vn",
    "Referer":       "https://digifactory.agris.com.vn/"
}
payload = {
    "targetStoreName": "RP_QM_DL03_LEVEL",
    "fromDate":  "2026-04-28",
    "toDate":    "2026-04-28",
    "multiple":  False,
    "potCode":   "NULL",
    "step":      ",20865993-2d82-40a6-a28a-08da69f83e9e,"
}
r = requests.post(API_URL, headers=api_headers, json=payload)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    rows = len(data.get("data", []))
    print(f"FETCH THANH CONG - {rows} rows tra ve")
else:
    print(f"FETCH THAT BAI")
    print(f"  Response: {r.text[:200]}")
    raise SystemExit(1)
