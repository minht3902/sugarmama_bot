"""
fetcher.py — Chạy bởi GitHub Actions mỗi 30 phút.
Nhiệm vụ: login → fetch data → build raw + dashboard HTML → commit cache.json + dashboard lên repo.
Nếu lỗi → gửi Telegram về ALLOWED_CHAT_ID.
"""

import requests
import re
import json
import math
import os
import calendar
import traceback
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urljoin, parse_qs

# ========================
# TIMEZONE
# ========================
TZ_VN = timezone(timedelta(hours=7))

def now_vn():
    return datetime.now(TZ_VN)


# ========================
# BUILD DASHBOARD HTML
# ========================
GITHUB_OWNER = "minht3902"
GITHUB_REPO  = "sugarmama_bot"

def build_dashboard_html(raw, from_date, to_date):
    """
    Đọc dashboard_template.html và inject data bằng .replace().
    Không dùng f-string — không có {{ }} không có escape hell.
    """
    from_dt     = datetime.strptime(from_date, "%Y-%m-%d")
    month_label = f"Tháng {from_dt.month}/{from_dt.year}"
    from_iso    = from_date

    last_day_dt = datetime(from_dt.year, from_dt.month,
                           calendar.monthrange(from_dt.year, from_dt.month)[1])
    to_iso = last_day_dt.strftime("%Y-%m-%d")

    # Tìm ngày cuối thực tế từ raw data
    all_ts = []
    for s in raw.get("mia", {}).values():
        all_ts.extend(pt["t"][:10] for pt in s)
    for section in raw.get("hoa", {}).values():
        for s in section.values():
            all_ts.extend(pt["t"][:10] for pt in s)
    actual_last = max(all_ts) if all_ts else to_iso

    raw_json    = json.dumps(raw,    ensure_ascii=False, separators=(",", ":"))
    limits_json = json.dumps(LIMITS, ensure_ascii=False, separators=(",", ":"))

    # Tên file cache tương ứng — dùng cho live polling trong dashboard
    cache_file = f"cache_{from_date}_{to_iso}.json"

    # Đọc template
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Inject data — đơn giản, không f-string, không escape
    html = html.replace("__RAW_JSON__",    raw_json)
    html = html.replace("__LIMITS_JSON__", limits_json)
    html = html.replace("__FROM_ISO__",    from_iso)
    html = html.replace("__ACTUAL_LAST__", actual_last)
    html = html.replace("__MONTH_LABEL__", month_label)
    html = html.replace("__CACHE_FILE__",  cache_file)
    html = html.replace("__GITHUB_OWNER__", GITHUB_OWNER)
    html = html.replace("__GITHUB_REPO__",  GITHUB_REPO)

    return html

# ========================
# CONFIG — đọc từ environment (GitHub Secrets)
# ========================
USERNAME     = os.environ["DIGIFACTORY_USERNAME"]
PASSWORD     = os.environ["DIGIFACTORY_PASSWORD"]
BOT_TOKEN    = os.environ["BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["ALLOWED_CHAT_ID"])

BASE_URL = "https://smfidentity.agris.com.vn"
API_URL  = "https://smfapi.agris.com.vn/Manufacturing/Report/GetStoreReport"
TARGET_STORE = "RP_QM_DL03_LEVEL"

STEP_MAP = {
    "Mía - Nước mía":          "20865993-2d82-40a6-a28a-08da69f83e9e",
    "Mật rỉ - bùn":            "22a50561-13fa-4864-ef56-08da897dd9bf",
    "Hóa chế thô":             "c7ca281e-1e22-4ee7-913b-08da8a3ea673",
    "Nấu đường - Ly tâm thô":  "47413be0-ecd2-4d74-913c-08da8a3ea673",
}

CACHE_FILE     = "cache.json"
DASHBOARD_FILE = "dashboard.html"

# ========================
# NGƯỠNG CHUẨN
# ========================
LIMITS = {
    'Nước chè trong 2':     {'Độ đục (IU)': {'lo': 0, 'hi': 18}, 'Độ màu': {'lo': 20000, 'hi': 23000}, 'pH': {'lo': 7.2, 'hi': 7.3}},
    'Syrup sau lắng nổi':   {'Độ màu': {'lo': 22000, 'hi': 25000}},
    'Syrup trước lắng nổi': {'Bx': {'lo': 58, 'hi': 62}, 'pH': {'lo': 5.6, 'hi': 5.8}},
    'Sirô thô sau bốc hơi': {'Bx': {'lo': 55, 'hi': 60}, 'Độ màu': {'lo': 16000, 'hi': 20000}},
    'Hồi dung C':           {'Bx': {'lo': 55, 'hi': 60}, 'Ap': {'lo': 78, 'hi': 82}, 'Độ màu': {'lo': 40000, 'hi': 55000}},
    'Đường non A':          {'Ap': {'lo': 80, 'hi': 83}, 'Bx': {'lo': 92.5, 'hi': 93}},
    'Đường non B':          {'Ap': {'lo': 62, 'hi': 64}, 'Bx': {'lo': 94, 'hi': 95.5}},
    'Đường non C':          {'Ap': {'lo': 52, 'hi': 54}, 'Bx': {'lo': 96, 'hi': 97}},
    'Mật nguyên A':         {'Ap': {'lo': 58, 'hi': 60}, 'Bx': {'lo': 79, 'hi': 82}},
    'Mật loãng A':          {'Ap': {'lo': 64, 'hi': 66}, 'Bx': {'lo': 78, 'hi': 80}},
    'Mật B':                {'Ap': {'lo': 44, 'hi': 46}, 'Bx': {'lo': 79, 'hi': 82}},
    'Đường B':              {'Pol': {'lo': 90, 'hi': 92}},
    'Mía - Nước mía':       {
        'Pol bã': {'lo': 0, 'hi': 1.75}, 'Ẩm bã': {'lo': 48, 'hi': 52},
        'pH gia vôi NM HH': {'lo': 6.2, 'hi': 6.6}, 'pH NM trung hòa': {'lo': 7.2, 'hi': 7.4},
        'Bx NM HH': {'lo': 10.5, 'hi': 13.5}, 'Bx NM cuối': {'lo': 1.5, 'hi': 2.5}, 'P2O5': {'lo': 350, 'hi': 400},
    },
    'Mật rỉ - Bùn thô':     {
        'Pol bùn': {'lo': 0, 'hi': 1.4}, 'Độ ẩm bùn': {'lo': 60, 'hi': 70},
        'Bx mật cuối': {'lo': 90, 'hi': 92}, 'Ap mật rỉ': {'lo': 0, 'hi': 30.5}, 'Bx1 mật rỉ': {'lo': 80, 'hi': 82},
    },
}

# ========================
# TELEGRAM NOTIFY
# ========================
def tg_notify(msg: str):
    """Gửi tin nhắn Telegram về ALLOWED_CHAT_ID (dùng để báo lỗi)."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": ALLOWED_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=15)
    except Exception as e:
        print(f"[TG NOTIFY FAILED] {e}")

# ========================
# LOGIN
# ========================
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

    token_match = re.search(r'name="__RequestVerificationToken".*?value="(.*?)"', r.text)
    verification_token = token_match.group(1)

    parsed = urlparse(login_url)
    return_url = parse_qs(parsed.query).get("ReturnUrl", [""])[0]

    payload = {
        "ReturnUrl": return_url,
        "Username": USERNAME,
        "Password": PASSWORD,
        "button": "login",
        "__RequestVerificationToken": verification_token,
        "RememberLogin": "false"
    }

    r = session.post(login_url, data=payload, headers=headers, allow_redirects=False)

    for _ in range(20):
        if "location" not in r.headers:
            break
        next_url = urljoin(BASE_URL, r.headers["location"])
        if "access_token" in next_url:
            fragment = urlparse(next_url).fragment
            params = dict(q.split("=") for q in fragment.split("&"))
            return params["access_token"]
        r = session.get(next_url, headers=headers, allow_redirects=False)

    raise Exception("Không lấy được token")

# ========================
# DATE
# ========================
SEASON_START = "2025-12-01"  # Ngày bắt đầu vụ sản xuất 25-26

def get_fetch_range():
    """
    Trả về (from_date, to_date).
    - Nếu workflow_dispatch truyền vào from_date/to_date → dùng đó (cho /newcache).
    - Mặc định: từ đầu vụ (SEASON_START) đến cuối tháng hiện tại.
    """
    from_env = os.environ.get("FETCH_FROM_DATE", "").strip()
    to_env   = os.environ.get("FETCH_TO_DATE", "").strip()
    if from_env and to_env:
        print(f"📥 Dùng khoảng ngày từ workflow input: {from_env} → {to_env}")
        return from_env, to_env

    today    = now_vn().replace(tzinfo=None)
    last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return SEASON_START, last_day.strftime("%Y-%m-%d")

# ========================
# DATE CHUNKING
# ========================
def split_months(from_date, to_date):
    """
    Tách khoảng from_date→to_date thành list các (chunk_from, chunk_to) theo tháng.
    Ví dụ: 2025-12-01 → 2026-05-31 thành 6 chunk, mỗi chunk 1 tháng.
    """
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt   = datetime.strptime(to_date,   "%Y-%m-%d")
    chunks  = []
    cur = from_dt.replace(day=1)
    while cur <= to_dt:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        chunk_end = min(cur.replace(day=last_day), to_dt)
        chunks.append((cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        # sang tháng tiếp
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            cur = cur.replace(month=cur.month + 1, day=1)
    return chunks

# ========================
# FETCH
# ========================
def fetch_data(token, step_code, from_date, to_date):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://digifactory.agris.com.vn",
        "Referer": "https://digifactory.agris.com.vn/"
    }
    payload = {
        "targetStoreName": TARGET_STORE,
        "fromDate": from_date,
        "toDate": to_date,
        "multiple": False,
        "potCode": "NULL",
        "step": f",{step_code},"
    }
    r = requests.post(API_URL, headers=headers, json=payload, timeout=60)

    # Log rate limit headers nếu có
    rl_headers = {k: v for k, v in r.headers.items()
                  if any(x in k.lower() for x in
                         ["ratelimit", "rate-limit", "x-rate", "retry-after", "x-request"])}
    if rl_headers:
        print(f"   📊 Rate limit headers: {rl_headers}", flush=True)
    else:
        print(f"   ℹ️ Không có rate limit header (status={r.status_code})", flush=True)

    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After", "?")
        raise Exception(f"API rate limit! Retry-After: {retry_after}s")
    if r.status_code != 200:
        raise Exception(f"API HTTP {r.status_code}")
    data = r.json()
    if not data.get("succeeded"):
        raise Exception("API trả về succeeded=false")
    return data["data"]

# ========================
# TRANSFORM — pure Python, không dùng pandas
# ========================
def _parse_row(row):
    """
    Nhận 1 dict row từ API, trả về dict chuẩn hoá hoặc None nếu không hợp lệ.
    """
    date_str = str(row.get("inputDate", "")).strip()
    time_str = str(row.get("inputHour", "")).strip()

    if not date_str or not time_str or ":" not in time_str:
        return None
    parts = time_str.split(":")
    if len(parts) < 2 or parts[0] == "" or parts[1] == "":
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        if hour >= 24:
            dt = dt + timedelta(days=1)
            hour = hour - 24
        dt = dt.replace(hour=hour, minute=minute)
    except (ValueError, OverflowError):
        return None

    try:
        val = float(row.get("inputValue"))
        if math.isnan(val) or math.isinf(val):
            val = None
    except (TypeError, ValueError):
        val = None

    return {
        "datetime": dt,
        "process":     str(row.get("level 3", "")).strip(),
        "sub_process": str(row.get("level 4", "")).strip(),
        "indicator":   str(row.get("level 5", "")).strip(),
        "inputValue":  val,
    }

def transform(rows):
    """
    Nhận list[dict] từ API, trả về list[dict] đã chuẩn hoá.
    Thay thế hoàn toàn pandas DataFrame.
    """
    result = []
    skipped = 0
    seen = set()

    for row in rows:
        parsed = _parse_row(row)
        if parsed is None:
            skipped += 1
            continue

        key = (parsed["datetime"], parsed["process"],
               parsed["sub_process"], parsed["indicator"])
        if key in seen:
            continue
        seen.add(key)
        result.append(parsed)

    if skipped:
        print(f"⚠️ Bỏ qua {skipped} row không hợp lệ")

    result.sort(key=lambda r: r["datetime"])
    return result

# ========================
# BUILD SERIES HELPERS
# ========================
def safe_val(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), 4)

def build_series(rows, indicator_name, process=None, sub_process=None):
    """rows là list[dict] đã qua transform().
    So sánh process và sub_process theo case-insensitive để chống lỗi khi API
    trả về tên có chữ hoa/thường không nhất quán (VD: 'Mía - nước mía' vs 'Mía - Nước mía').
    """
    process_lower     = process.lower()     if process     is not None else None
    sub_process_lower = sub_process.lower() if sub_process is not None else None
    result = []
    for row in rows:
        if row["indicator"] != indicator_name:
            continue
        if process_lower is not None and row["process"].lower() != process_lower:
            continue
        if sub_process_lower is not None and row["sub_process"].lower() != sub_process_lower:
            continue
        v = safe_val(row["inputValue"])
        if v is not None:
            result.append({"t": row["datetime"].strftime("%Y-%m-%d %H:%M"), "v": v})
    return result

def calc_stats_py(series):
    vals = [pt["v"] for pt in series if pt["v"] is not None]
    if not vals:
        return {"mean": None, "std": None, "min": None, "max": None}
    mean = round(sum(vals) / len(vals), 2)
    std  = round((sum((x - mean)**2 for x in vals) / len(vals)) ** 0.5, 2)
    return {"mean": mean, "std": std, "min": round(min(vals), 2), "max": round(max(vals), 2)}

def daily_avg(series):
    from collections import defaultdict
    buckets = defaultdict(list)
    for pt in series:
        day = pt["t"][:10]
        buckets[day].append(pt["v"])
    result = []
    for day in sorted(buckets):
        vals = [v for v in buckets[day] if v is not None]
        if vals:
            result.append({"t": f"{day} 00:00", "v": round(sum(vals)/len(vals), 4)})
    return result

# ========================
# MAPPING
# ========================
HOA_MAP = {
    "Syrup sau lắng nổi": {
        "Ap":     ("Hóa chế thô", "Syrup sau lắng nổi", "Ap"),
        "Bx":     ("Hóa chế thô", "Syrup sau lắng nổi", "Bx"),
        "Pol":    ("Hóa chế thô", "Syrup sau lắng nổi", "Pol"),
        "pH":     ("Hóa chế thô", "Syrup sau lắng nổi", "pH"),
        "Độ màu": ("Hóa chế thô", "Syrup sau lắng nổi", "Độ màu"),
        "Độ đục": ("Hóa chế thô", "Syrup sau lắng nổi", "Độ đục"),
    },
    "Syrup trước lắng nổi": {
        "Ap":     ("Hóa chế thô", "Syrup trước lắng nổi", "Ap"),
        "Bx":     ("Hóa chế thô", "Syrup trước lắng nổi", "Bx"),
        "Pol":    ("Hóa chế thô", "Syrup trước lắng nổi", "Pol"),
        "pH":     ("Hóa chế thô", "Syrup trước lắng nổi", "pH"),
        "Độ màu": ("Hóa chế thô", "Syrup trước lắng nổi", "Độ màu"),
        "Độ đục": ("Hóa chế thô", "Syrup trước lắng nổi", "Độ đục"),
    },
    "Nước chè trong 2": {
        "Ap":          ("Nước chè trong 2", "Ap", "Ap"),
        "Bx":          ("Nước chè trong 2", "Ap", "Bx"),
        "Pol":         ("Nước chè trong 2", "Ap", "Pol"),
        "pH":          ("Nước chè trong 2", "Chỉ tiêu chung", "pH"),
        "Độ màu":      ("Nước chè trong 2", "Độ màu", "Độ màu"),
        "Độ đục (IU)": ("Nước chè trong 2", "Độ đục", "Độ đục (IU)"),
    },
    "Sirô thô sau bốc hơi": {
        "Ap":     ("Sirô thô sau bốc hơi", "Ap", "Ap"),
        "Bx":     ("Sirô thô sau bốc hơi", "Ap", "Bx"),
        "Pol":    ("Sirô thô sau bốc hơi", "Ap", "Pol"),
        "pH":     ("Sirô thô sau bốc hơi", "Chỉ tiêu chung", "pH"),
        "Độ màu": ("Sirô thô sau bốc hơi", "Độ màu", "Độ màu"),
    },
}

NAU_PROCESS = "Nấu đường - Ly tâm thô"
NAU_MAP = {
    "Mật loãng A":  {"sub": "Mật loãng A",                       "params": ["Ap", "Bx", "Pol"]},
    "Mật nguyên A": {"sub": "Mật nguyên A/Mật A ly tâm/Mật 5",   "params": ["Ap", "Bx", "Pol"]},
    "Mật B":        {"sub": "Mật B/Mật B ly tâm/Mật 6",          "params": ["Ap", "Bx", "Pol"]},
    "Hồi dung B":   {"sub": "Hồi dung B/Hồi dung 6",             "params": ["Ap", "Bx", "Pol", "Độ màu"]},
    "Hồi dung C":   {"sub": "Hồi dung C/C2/Hồi dung 7",          "params": ["Ap", "Bx", "Pol", "Độ màu"]},
    "Đường B":      {"sub": "Đường B",                            "params": ["Ap", "Bx", "Pol"]},
    "Đường C":      {"sub": "Đường C (C2)",                       "params": ["Ap", "Bx", "Pol"]},
    "Đường non A":  {"sub": "Đường non A/A1/R5",                  "params": ["Ap", "Bx", "Pol"]},
    "Đường non B":  {"sub": "Đường non B/R6",                     "params": ["Ap", "Bx", "Pol"]},
    "Đường non C":  {"sub": "Đường non C/R7",                     "params": ["Ap", "Bx", "Pol"]},
}

MIA_MAP = [
    {"label": "Pol bã",           "process": "Mía - Nước mía",                          "sub": "Bã che/ bã mía",     "ind": "Pol"},
    {"label": "Ẩm bã",            "process": "Mía - Nước mía",                          "sub": "Bã che/ bã mía",     "ind": "Độ ẩm"},
    {"label": "Xơ mía",           "process": "Mía - Nước mía",                          "sub": "Xơ mía",             "ind": "Xơ mía"},
    {"label": "pH gia vôi NM HH", "process": "Mía - Nước mía",                          "sub": "Nước mía gia vôi",   "ind": "pH"},
    {"label": "pH NM trung hòa",  "process": "Mía - Nước mía",                          "sub": "Nước mía trung hòa", "ind": "pH"},
    {"label": "Ap NM HH",         "process": "Nước mía hỗn hợp (Nước mía khuếch tán)", "sub": "Ap",                 "ind": "Ap"},
    {"label": "Bx NM HH",         "process": "Nước mía hỗn hợp (Nước mía khuếch tán)", "sub": "Ap",                 "ind": "Bx"},
    {"label": "Pol NM HH",        "process": "Nước mía hỗn hợp (Nước mía khuếch tán)", "sub": "Ap",                 "ind": "Pol"},
    {"label": "P2O5",             "process": "Nước mía hỗn hợp (Nước mía khuếch tán)", "sub": "Hàm lượng P2O5",     "ind": "Hàm lượng P205"},
    {"label": "Ap NM đầu",        "process": "Nước mía đầu",                            "sub": "AP",                 "ind": "Ap"},
    {"label": "Bx NM đầu",        "process": "Nước mía đầu",                            "sub": "AP",                 "ind": "Bx"},
    {"label": "Pol NM đầu",       "process": "Nước mía đầu",                            "sub": "AP",                 "ind": "Pol"},
    {"label": "Ap NM cuối",       "process": "Nước mía cuối (Nước chè ép)",             "sub": "AP",                 "ind": "Ap"},
    {"label": "Bx NM cuối",       "process": "Nước mía cuối (Nước chè ép)",             "sub": "AP",                 "ind": "Bx"},
    {"label": "Pol NM cuối",      "process": "Nước mía cuối (Nước chè ép)",             "sub": "AP",                 "ind": "Pol"},
]

MAT_PROCESS = "Mật rỉ - bùn"
MAT_MAP = [
    {"label": "Pol bùn",      "sub": "Bùn thô 1", "ind": "Pol"},
    {"label": "Độ ẩm bùn",    "sub": "Bùn thô 1", "ind": "Độ ẩm"},
    {"label": "Ap mật cuối",  "sub": "Mật cuối",  "ind": "Ap"},
    {"label": "Bx mật cuối",  "sub": "Mật cuối",  "ind": "Bx"},
    {"label": "Pol mật cuối", "sub": "Mật cuối",  "ind": "Pol"},
    {"label": "RS mật cuối",  "sub": "Mật cuối",  "ind": "RS"},
    {"label": "Ap mật rỉ",    "sub": "Mật rỉ",    "ind": "Ap"},
    {"label": "Bx mật rỉ",    "sub": "Mật rỉ",    "ind": "Bx"},
    {"label": "Bx1 mật rỉ",   "sub": "Mật rỉ",    "ind": "Bx1"},
    {"label": "Pol mật rỉ",   "sub": "Mật rỉ",    "ind": "Pol"},
]

# ========================
# BUILD RAW
# ========================
def _merge_series(existing, new_pts):
    """Merge new_pts vào existing, dedup theo timestamp, sort theo thời gian."""
    existing_ts = {pt["t"] for pt in existing}
    merged = existing + [pt for pt in new_pts if pt["t"] not in existing_ts]
    merged.sort(key=lambda x: x["t"])
    return merged

def build_raw_stage(rows, raw):
    """Cộng dồn dữ liệu 1 chunk (tháng) vào raw dict. Nhận list[dict] đã qua transform()."""
    processes = {r["process"] for r in rows}

    # HOA
    for section, ind_map in HOA_MAP.items():
        for key, (proc, sub, ind) in ind_map.items():
            if proc in processes:
                series = build_series(rows, ind, process=proc, sub_process=sub)
                if series:
                    existing = raw["hoa"].setdefault(section, {}).get(key, [])
                    raw["hoa"][section][key] = _merge_series(existing, series)

    # NAU
    if NAU_PROCESS in processes:
        for section, cfg in NAU_MAP.items():
            for param in cfg["params"]:
                series = build_series(rows, param, process=NAU_PROCESS, sub_process=cfg["sub"])
                if series:
                    existing = raw["nau"].setdefault(section, {}).get(param, [])
                    raw["nau"][section][param] = _merge_series(existing, series)

    # MIA — dùng so sánh case-insensitive để tránh lỗi API trả tên không nhất quán
    processes_lower = {p.lower() for p in processes}
    mia_procs_found = {p for p in processes if any(
        p.lower() == entry["process"].lower() for entry in MIA_MAP
    )}
    if mia_procs_found:
        print(f"[MIA] Processes từ API: {mia_procs_found}", flush=True)
    for entry in MIA_MAP:
        if entry["process"].lower() in processes_lower:
            series = build_series(rows, entry["ind"], process=entry["process"], sub_process=entry["sub"])
            if series:
                existing = raw["mia"].get(entry["label"], [])
                raw["mia"][entry["label"]] = _merge_series(existing, series)

    # MAT
    if MAT_PROCESS in processes:
        for entry in MAT_MAP:
            series = build_series(rows, entry["ind"], process=MAT_PROCESS, sub_process=entry["sub"])
            if series:
                existing = raw["mat"].get(entry["label"], [])
                raw["mat"][entry["label"]] = _merge_series(existing, series)


def build_raw_aggregates(raw):
    """Tính daily averages và stats sau khi tất cả stages đã được load vào raw."""
    raw["hoa_daily"] = {}
    for section, ind_map in HOA_MAP.items():
        raw["hoa_daily"][section] = {}
        for key in ind_map:
            raw["hoa_daily"][section][key] = daily_avg(raw["hoa"].get(section, {}).get(key, []))

    raw["nau_daily"] = {}
    for section, cfg in NAU_MAP.items():
        raw["nau_daily"][section] = {}
        for param in cfg["params"]:
            raw["nau_daily"][section][param] = daily_avg(raw["nau"].get(section, {}).get(param, []))

    raw["mia_daily"] = {}
    for entry in MIA_MAP:
        raw["mia_daily"][entry["label"]] = daily_avg(raw["mia"].get(entry["label"], []))

    raw["mat_daily"] = {}
    for entry in MAT_MAP:
        raw["mat_daily"][entry["label"]] = daily_avg(raw["mat"].get(entry["label"], []))

    stats = {}
    for entry in MIA_MAP:
        stats[f"mia|{entry['label']}"] = calc_stats_py(raw["mia"].get(entry["label"], []))
    for entry in MAT_MAP:
        stats[f"mat|{entry['label']}"] = calc_stats_py(raw["mat"].get(entry["label"], []))
    for section, ind_map in HOA_MAP.items():
        for key in ind_map:
            stats[f"hoa|{section}|{key}"] = calc_stats_py(raw["hoa"].get(section, {}).get(key, []))
    for section, cfg in NAU_MAP.items():
        for param in cfg["params"]:
            stats[f"nau|{section}|{param}"] = calc_stats_py(raw["nau"].get(section, {}).get(param, []))

    raw["stats"] = stats


def build_raw(rows):
    """Legacy wrapper — dùng cho GitHub Actions (fetch.yml)."""
    raw = {"hoa": {}, "nau": {}, "mia": {}, "mat": {}}
    build_raw_stage(rows, raw)
    build_raw_aggregates(raw)
    return raw


# ========================
# MAIN
# ========================
def main():
    now_str = now_vn().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🚀 Fetcher bắt đầu: {now_str} (GMT+7)")

    from_date, to_date = get_fetch_range()
    print(f"📅 Kỳ báo cáo: {from_date} → {to_date}")

    # Xác định tên file output — luôn dùng tên có ngày
    is_custom = bool(os.environ.get("FETCH_FROM_DATE", "").strip())
    cache_file     = f"cache_{from_date}_{to_date}.json"
    dashboard_file = f"dashboard_{from_date}_{to_date}.html"

    print("🔐 Login...")
    token = get_token()
    print("✅ Token OK")

    # Fetch + transform + build_raw từng stage, giải phóng RAM trước khi sang stage kế
    import gc
    raw = {"hoa": {}, "nau": {}, "mia": {}, "mat": {},
           "hoa_daily": {}, "nau_daily": {}, "mia_daily": {}, "mat_daily": {}, "stats": {}}

    def _mem():
        try:
            with open("/proc/self/status") as _f:
                for _l in _f:
                    if _l.startswith("VmRSS:"):
                        return int(_l.split()[1]) / 1024
        except Exception:
            pass
        return -1

    months = split_months(from_date, to_date)
    print(f"📅 Tách thành {len(months)} chunk tháng: {[m[0][:7] for m in months]}")

    for name, code in STEP_MAP.items():
        print(f"\n📊 Stage: {name} | RAM={_mem():.0f}MB")
        stage_rows = []
        for chunk_from, chunk_to in months:
            print(f"   📥 {chunk_from[:7]} | RAM={_mem():.0f}MB", flush=True)
            chunk_rows = fetch_data(token, code, chunk_from, chunk_to)
            print(f"      → {len(chunk_rows)} rows | RAM={_mem():.0f}MB")
            chunk_rows = transform(chunk_rows)
            build_raw_stage(chunk_rows, raw)
            del chunk_rows
            gc.collect()
        del stage_rows
        gc.collect()
        print(f"   ✅ Stage xong | RAM={_mem():.0f}MB")

    # Tính daily + stats sau khi tất cả stages đã được merge vào raw
    print("📐 Build daily averages & stats...")
    build_raw_aggregates(raw)

    print("📊 Build dashboard HTML...")
    html = build_dashboard_html(raw, from_date, to_date)
    with open(dashboard_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Dashboard: {dashboard_file}")

    cache = {
        "updated_at": now_vn().strftime("%Y-%m-%d %H:%M:%S"),
        "from_date":  from_date,
        "to_date":    to_date,
        "raw":        raw,
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ Cache: {cache_file}")

    print("🏁 Fetcher hoàn tất.")

    print("🏁 Push xong. Không gửi thông báo Telegram (chỉ báo khi có lỗi).")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(f"❌ FETCHER LỖI:\n{err}")
        tg_notify(
            f"🚨 *[SugarMama Fetcher] LỖI*\n"
            f"⏰ `{now_vn().strftime('%Y-%m-%d %H:%M:%S')}` (GMT+7)\n\n"
            f"```\n{err[-1500:]}\n```"
        )
        raise
