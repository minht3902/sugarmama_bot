import requests
import re
import os
from urllib.parse import urlparse, urljoin, parse_qs

USERNAME = os.environ["TTC_USERNAME"]
PASSWORD = os.environ["TTC_PASSWORD"]

BASE_URL = "https://smfidentity.agris.com.vn"

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
    print(f"Login URL: {login_url}")

    r = session.get(login_url, headers=headers)

    token_match = re.search(
        r'name="__RequestVerificationToken".*?value="(.*?)"', r.text
    )
    verification_token = token_match.group(1)
    print(f"Verification token: {verification_token[:30]}...")

    parsed = urlparse(login_url)
    return_url = parse_qs(parsed.query).get("ReturnUrl", [""])[0]
    print(f"ReturnUrl: {return_url}")

    payload = {
        "ReturnUrl": return_url,
        "Username":  USERNAME,
        "Password":  PASSWORD,
        "button":    "login",
        "__RequestVerificationToken": verification_token,
        "RememberLogin": "false"
    }

    print(f"Username duoc dung: {USERNAME}")
    print(f"Payload keys: {list(payload.keys())}")

    r = session.post(login_url, data=payload, headers=headers, allow_redirects=False)

    print(f"\nPOST response status: {r.status_code}")
    print(f"POST response headers: {dict(r.headers)}")

    # In toan bo body de tim thong bao loi
    # Loc bo tag HTML, chi lay text
    body_text = re.sub(r'<[^>]+>', ' ', r.text)
    body_text = re.sub(r'\s+', ' ', body_text).strip()
    print(f"\nBody (da loc HTML):\n{body_text[:1000]}")

    # Tim thong bao loi cu the
    error_patterns = [
        r'Invalid username or password',
        r'invalid_grant',
        r'error["\s:]+([^<"]{5,80})',
        r'class="[^"]*error[^"]*"[^>]*>([^<]{3,100})',
        r'class="[^"]*alert[^"]*"[^>]*>([^<]{3,100})',
        r'validation-summary[^>]*>(.*?)</div',
    ]
    print("\nTim kiem thong bao loi:")
    for pat in error_patterns:
        m = re.search(pat, r.text, re.IGNORECASE | re.DOTALL)
        if m:
            print(f"  [{pat[:30]}] -> {m.group(0)[:100]}")

print("=== TEST LOGIN ===")
try:
    get_token()
except Exception as e:
    print(f"Exception: {e}")
