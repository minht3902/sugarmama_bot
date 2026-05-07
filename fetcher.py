"""
fetcher.py — Chạy bởi GitHub Actions mỗi 30 phút.
Nhiệm vụ: login → fetch data → build raw + dashboard HTML → commit cache.json + dashboard lên repo.
Nếu lỗi → gửi Telegram về ALLOWED_CHAT_ID.
"""

import requests
import pandas as pd
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
    if r.status_code != 200:
        raise Exception(f"API HTTP {r.status_code}")
    data = r.json()
    if not data.get("succeeded"):
        raise Exception("API trả về succeeded=false")
    return data["data"]

# ========================
# TRANSFORM
# ========================
def transform(df):
    df.columns = df.columns.str.strip()

    def fix_datetime(row):
        date_str = row["inputDate"]
        time_str = row["inputHour"]
        hour, minute = map(int, time_str.split(":"))
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        if hour >= 24:
            dt = dt + pd.Timedelta(days=1)
            hour = hour - 24
        return dt.replace(hour=hour, minute=minute)

    df["datetime"] = df.apply(fix_datetime, axis=1)
    df["inputValue"] = pd.to_numeric(df["inputValue"], errors="coerce")

    df.rename(columns={
        "level 3": "process",
        "level 4": "sub_process",
        "level 5": "indicator"
    }, inplace=True)

    dup = df.duplicated(
        subset=["datetime", "process", "sub_process", "indicator"],
        keep=False
    )
    if dup.any():
        raise Exception(f"Phát hiện {dup.sum()} dòng duplicate trong dữ liệu")

    return df

# ========================
# BUILD SERIES HELPERS
# ========================
def safe_val(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), 4)

def build_series(df, indicator_name, process=None, sub_process=None):
    mask = df["indicator"] == indicator_name
    if process is not None:
        mask = mask & (df["process"] == process)
    if sub_process is not None:
        mask = mask & (df["sub_process"] == sub_process)
    sub = df[mask].copy().sort_values("datetime")
    result = []
    for _, row in sub.iterrows():
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
    {"label": "Pol bã",           "process": "Mía - nước mía",                          "sub": "Bã che/ bã mía",     "ind": "Pol"},
    {"label": "Ẩm bã",            "process": "Mía - nước mía",                          "sub": "Bã che/ bã mía",     "ind": "Độ ẩm"},
    {"label": "Xơ mía",           "process": "Mía - nước mía",                          "sub": "Xơ mía",             "ind": "Xơ mía"},
    {"label": "pH gia vôi NM HH", "process": "Mía - nước mía",                          "sub": "Nước mía gia vôi",   "ind": "pH"},
    {"label": "pH NM trung hòa",  "process": "Mía - nước mía",                          "sub": "Nước mía trung hòa", "ind": "pH"},
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
def build_raw(df):
    df = df.copy()
    df["sub_process"] = df["sub_process"].str.strip()
    df["process"]     = df["process"].str.strip()
    df["indicator"]   = df["indicator"].str.strip()

    raw = {}

    raw["hoa"] = {}
    for section, ind_map in HOA_MAP.items():
        raw["hoa"][section] = {}
        for key, (proc, sub, ind) in ind_map.items():
            raw["hoa"][section][key] = build_series(df, ind, process=proc, sub_process=sub)

    raw["nau"] = {}
    for section, cfg in NAU_MAP.items():
        raw["nau"][section] = {}
        for param in cfg["params"]:
            raw["nau"][section][param] = build_series(
                df, param, process=NAU_PROCESS, sub_process=cfg["sub"]
            )

    raw["mia"] = {}
    for entry in MIA_MAP:
        raw["mia"][entry["label"]] = build_series(
            df, entry["ind"], process=entry["process"], sub_process=entry["sub"]
        )

    raw["mat"] = {}
    for entry in MAT_MAP:
        raw["mat"][entry["label"]] = build_series(
            df, entry["ind"], process=MAT_PROCESS, sub_process=entry["sub"]
        )

    raw["hoa_daily"] = {}
    for section, ind_map in HOA_MAP.items():
        raw["hoa_daily"][section] = {}
        for key in ind_map:
            raw["hoa_daily"][section][key] = daily_avg(raw["hoa"][section][key])

    raw["nau_daily"] = {}
    for section, cfg in NAU_MAP.items():
        raw["nau_daily"][section] = {}
        for param in cfg["params"]:
            raw["nau_daily"][section][param] = daily_avg(raw["nau"][section][param])

    raw["mia_daily"] = {}
    for entry in MIA_MAP:
        raw["mia_daily"][entry["label"]] = daily_avg(raw["mia"][entry["label"]])

    raw["mat_daily"] = {}
    for entry in MAT_MAP:
        raw["mat_daily"][entry["label"]] = daily_avg(raw["mat"][entry["label"]])

    stats = {}
    for entry in MIA_MAP:
        stats[f"mia|{entry['label']}"] = calc_stats_py(raw["mia"][entry["label"]])
    for entry in MAT_MAP:
        stats[f"mat|{entry['label']}"] = calc_stats_py(raw["mat"][entry["label"]])
    for section, ind_map in HOA_MAP.items():
        for key in ind_map:
            stats[f"hoa|{section}|{key}"] = calc_stats_py(raw["hoa"][section][key])
    for section, cfg in NAU_MAP.items():
        for param in cfg["params"]:
            stats[f"nau|{section}|{param}"] = calc_stats_py(raw["nau"][section][param])

    raw["stats"] = stats
    return raw

# ========================
# BUILD DASHBOARD HTML
# ========================
def build_dashboard_html(raw, from_date, to_date):
    from_dt    = datetime.strptime(from_date, "%Y-%m-%d")
    month_label = f"Tháng {from_dt.month}/{from_dt.year}"
    from_iso   = from_date

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

    raw_json    = json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
    limits_json = json.dumps(LIMITS, ensure_ascii=False, separators=(',', ':'))

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Kiểm Soát Dây Chuyền – {month_label}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #222636;
    --border: #2e3348; --text: #e4e6f0; --muted: #8891a8; --radius: 12px;
    --c1:#4f8ef7; --c2:#f7774f; --c3:#4fc9a4; --c4:#f7c34f; --c5:#b44ff7; --c6:#f74f7a; --c7:#4ff7d8;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; font-size:13px; }}
  header {{
    background:linear-gradient(135deg,#1a1d27,#1e2235);
    border-bottom:1px solid var(--border); padding:12px 22px;
    display:flex; align-items:center; justify-content:space-between;
    position:sticky; top:0; z-index:100; box-shadow:0 2px 16px rgba(0,0,0,.5);
    flex-wrap:wrap; gap:10px;
  }}
  .header-left h1 {{ font-size:16px; font-weight:700; color:#fff; }}
  .header-left p  {{ font-size:11px; color:var(--muted); margin-top:2px; }}
  .header-right {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
  .date-filter {{ display:flex; align-items:center; gap:6px; }}
  .date-filter label {{ font-size:11px; color:var(--muted); font-weight:600; letter-spacing:.4px; }}
  .date-input {{
    background:var(--surface2); border:1px solid var(--border); color:var(--text);
    padding:5px 8px; border-radius:7px; font-size:11px; cursor:pointer; outline:none;
    font-family:inherit; transition:border-color .15s;
  }}
  .date-input:hover, .date-input:focus {{ border-color:var(--c1); }}
  .btn-reset {{
    background:transparent; border:1px solid var(--border); color:var(--muted);
    padding:5px 10px; border-radius:7px; font-size:11px; cursor:pointer;
    transition:all .15s; font-family:inherit;
  }}
  .btn-reset:hover {{ border-color:var(--c2); color:var(--c2); }}
  .chip-pts {{
    background:var(--surface2); border:1px solid var(--border); color:var(--muted);
    font-size:10px; font-weight:600; padding:4px 10px; border-radius:20px;
    font-family:'Courier New',monospace; letter-spacing:.4px;
  }}
  .tabs {{
    display:flex; gap:2px; padding:12px 22px 0; border-bottom:1px solid var(--border);
    background:var(--surface); overflow-x:auto;
  }}
  .tabs::-webkit-scrollbar {{ height:3px; }}
  .tabs::-webkit-scrollbar-thumb {{ background:var(--border); }}
  .tab-btn {{
    padding:7px 16px; border:none; background:transparent; color:var(--muted);
    cursor:pointer; font-size:12.5px; font-weight:500;
    border-bottom:2px solid transparent; transition:.18s; white-space:nowrap; border-radius:6px 6px 0 0;
  }}
  .tab-btn.active {{ color:#fff; border-bottom-color:var(--c1); background:rgba(79,142,247,.09); }}
  .tab-btn:hover:not(.active) {{ color:var(--text); background:rgba(255,255,255,.04); }}
  .content {{ padding:18px 22px; }}
  .section-header {{ display:flex; align-items:center; gap:10px; margin-bottom:14px; }}
  .dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
  .section-title {{ font-size:14px; font-weight:700; color:#fff; }}
  .chart-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(420px,1fr)); gap:14px; }}
  .chart-card {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); padding:14px; transition:border-color .2s; position:relative;
  }}
  .chart-card:hover {{ border-color:#3d4460; }}
  .card-top {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; }}
  .card-title {{ font-size:11px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }}
  .card-badges {{ display:flex; gap:5px; flex-wrap:wrap; justify-content:flex-end; }}
  .cbadge {{
    font-size:10px; padding:2px 7px; border-radius:8px;
    background:var(--surface2); color:var(--muted); letter-spacing:0; text-transform:none;
  }}
  .cbadge.limit-badge {{ background:rgba(247,119,79,.15); color:#f7c34f; border:1px solid rgba(247,195,79,.25); }}
  .chart-wrap {{ position:relative; height:190px; }}
  .stat-row {{ display:flex; gap:5px; margin-top:9px; border-top:1px solid var(--border); padding-top:9px; }}
  .stat-item {{ flex:1; text-align:center; }}
  .stat-val {{ font-size:12.5px; font-weight:700; color:#fff; }}
  .stat-lbl {{ font-size:9.5px; color:var(--muted); margin-top:1px; }}
  .stat-item.breach .stat-val {{ color:#f7774f !important; }}
  .stat-item.ok .stat-val {{ color:#4fc9a4 !important; }}
  .section-group {{ margin-bottom:26px; }}
  .sub-label {{
    font-size:12px; font-weight:600; color:var(--text);
    margin-bottom:11px; padding:5px 12px;
    border-left:3px solid var(--c2); background:rgba(247,119,79,.06); border-radius:0 6px 6px 0;
  }}
  .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; margin-bottom:20px; }}
  .kpi-card {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); padding:13px; text-align:center; transition:border-color .2s;
  }}
  .kpi-card:hover {{ border-color:#3d4460; }}
  .kpi-card.breach {{ border-color:rgba(247,119,79,.5); background:rgba(247,119,79,.05); }}
  .kpi-card.ok-card {{ border-color:rgba(79,201,164,.3); }}
  .kpi-section {{ font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }}
  .kpi-param {{ font-size:11px; color:var(--text); font-weight:600; margin:3px 0 7px; }}
  .kpi-val {{ font-size:22px; font-weight:800; line-height:1; }}
  .kpi-range {{ font-size:9.5px; color:var(--muted); margin-top:4px; }}
  .kpi-trend {{ font-size:11px; margin-top:4px; }}
  .up{{color:#4fc9a4;}} .down{{color:#f7774f;}} .flat{{color:var(--muted);}}
  .legend-bar {{
    display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px;
    padding:8px 12px; background:var(--surface2); border-radius:8px; border:1px solid var(--border);
  }}
  .legend-item {{ display:flex; align-items:center; gap:6px; font-size:11px; color:var(--muted); }}
  .legend-line {{ width:24px; height:2px; }}
  .legend-line.dashed {{ background:repeating-linear-gradient(90deg,#f7774f 0,#f7774f 5px,transparent 5px,transparent 9px); }}
  .legend-line.dashed-green {{ background:repeating-linear-gradient(90deg,#4fc9a4 0,#4fc9a4 5px,transparent 5px,transparent 9px); }}
  .legend-line.solid {{ background:var(--c1); }}
  select {{
    background:var(--surface2); border:1px solid var(--border); color:var(--text);
    padding:6px 11px; border-radius:8px; font-size:12px; cursor:pointer; outline:none; font-family:inherit;
  }}
  select:hover {{ border-color:var(--c1); }}
  ::-webkit-scrollbar{{width:5px;height:5px;}}
  ::-webkit-scrollbar-thumb{{background:var(--border);border-radius:3px;}}
</style>
</head>
<body>
<header>
  <div class="header-left">
    <h1>📊 Dashboard Kiểm Soát Dây Chuyền</h1>
    <p>{month_label} &nbsp;·&nbsp; Hóa chế thô &amp; Nấu đường – Mía – Mật rỉ &nbsp;·&nbsp; Đường đứt nét = ngưỡng kiểm soát</p>
  </div>
  <div class="header-right">
    <div class="date-filter">
      <label>TỪ</label>
      <input type="date" id="dateFrom" class="date-input" value="{from_iso}" min="{from_iso}" max="{actual_last}" onchange="applyFilter()">
      <label>ĐẾN</label>
      <input type="date" id="dateTo" class="date-input" value="{actual_last}" min="{from_iso}" max="{actual_last}" onchange="applyFilter()">
      <button class="btn-reset" onclick="resetFilter()">✕ Reset</button>
    </div>
    <span class="chip-pts" id="pointChip">— ĐIỂM ĐO</span>
    <select id="displayMode" onchange="renderAll()">
      <option value="line">📈 Đường</option>
      <option value="bar">📊 Cột</option>
    </select>
  </div>
</header>
<div class="tabs">
  <button class="tab-btn active" onclick="showTab('overview')">🏠 Tổng quan</button>
  <button class="tab-btn" onclick="showTab('hoa1')">Syrup sau lắng nổi</button>
  <button class="tab-btn" onclick="showTab('hoa2')">Syrup trước lắng nổi</button>
  <button class="tab-btn" onclick="showTab('hoa3')">Nước chè trong 2</button>
  <button class="tab-btn" onclick="showTab('hoa4')">Sirô thô sau bốc hơi</button>
  <button class="tab-btn" onclick="showTab('nau1')">Đường non A / B / C</button>
  <button class="tab-btn" onclick="showTab('nau2')">Đường B &amp; C</button>
  <button class="tab-btn" onclick="showTab('nau3')">Mật &amp; Hồi dung</button>
  <button class="tab-btn" onclick="showTab('mia')">Mía – Nước mía</button>
  <button class="tab-btn" onclick="showTab('matri')">Mật rỉ – Bùn thô</button>
</div>
<div class="content" id="mainContent"></div>
<script>
const LIMITS = {limits_json};
function getLimit(section, param) {{
  if (LIMITS[section]?.[param]) return LIMITS[section][param];
  if (LIMITS['Mía - Nước mía']?.[param]) return LIMITS['Mía - Nước mía'][param];
  if (LIMITS['Mật rỉ - Bùn thô']?.[param]) return LIMITS['Mật rỉ - Bùn thô'][param];
  return null;
}}
const RAW = {raw_json};
let filterFrom = '{from_iso}';
let filterTo   = '{actual_last}';
function applyFilter() {{
  const from = document.getElementById('dateFrom').value;
  const to   = document.getElementById('dateTo').value;
  if (!from || !to) return;
  filterFrom = from;
  filterTo   = to;
  renderTab();
  updatePointCount();
}}
function resetFilter() {{
  document.getElementById('dateFrom').value = '{from_iso}';
  document.getElementById('dateTo').value   = '{actual_last}';
  applyFilter();
}}
function filterSeries(series) {{
  return series.filter(pt => {{
    const d = pt.t.substring(0, 10);
    return d >= filterFrom && d <= filterTo;
  }});
}}
function updatePointCount() {{
  setTimeout(() => {{
    let total = 0;
    document.querySelectorAll('canvas').forEach(c => {{
      const ch = Chart.getChart(c);
      if (ch) total += (ch.data.datasets[0]?.data?.filter(v=>v!=null).length||0);
    }});
    document.getElementById('pointChip').textContent = total + ' ĐIỂM ĐO';
  }}, 200);
}}
const COLORS = ['#4f8ef7','#f7774f','#4fc9a4','#f7c34f','#b44ff7','#f74f7a','#4ff7d8'];
let charts = {{}};
let currentTab = 'overview';
function getSeries(section, param, dataset) {{
  let src;
  if (dataset === 'hoa') src = RAW.hoa;
  else if (dataset === 'nau') src = RAW.nau;
  else if (dataset === 'mia') src = RAW.mia;
  else if (dataset === 'matri') src = RAW.mat;
  else src = RAW.nau;
  let raw;
  if (src?.[section]?.[param]) raw = src[section][param];
  else if (src?.[param]) raw = src[param];
  else return [];
  return filterSeries(raw);
}}
function calcStats(series, lim) {{
  const clean = series.filter(pt => pt.v !== null && !isNaN(pt.v)).map(pt => pt.v);
  if (!clean.length) return {{min:'N/A',max:'N/A',avg:'N/A',last:'N/A',trend:'flat',breachCount:0}};
  const avg = (clean.reduce((a,b)=>a+b,0)/clean.length).toFixed(2);
  const min = Math.min(...clean).toFixed(2);
  const max = Math.max(...clean).toFixed(2);
  const last = clean[clean.length-1].toFixed(2);
  const prev = clean.length>1 ? clean[clean.length-2] : clean[0];
  const trend = clean[clean.length-1]>prev+0.01?'up':clean[clean.length-1]<prev-0.01?'down':'flat';
  let breachCount = 0;
  if (lim) clean.forEach(v=>{{ if(v<lim.lo||v>lim.hi) breachCount++; }});
  return {{min,max,avg,last,trend,breachCount}};
}}
function makeChart(id, seriesList, section, singleParam) {{
  const mode = document.getElementById('displayMode').value;
  const ctx = document.getElementById(id);
  if (!ctx) return;
  if (charts[id]) {{ charts[id].destroy(); delete charts[id]; }}
  const allTs = new Set();
  seriesList.forEach(({{series}}) => series.forEach(pt => allTs.add(pt.t)));
  const labels = Array.from(allTs).sort();
  let limitDs = [];
  if (seriesList.length === 1 && singleParam) {{
    const lim = getLimit(section, singleParam);
    if (lim) {{
      limitDs = [
        {{ label:`Cận trên (${{lim.hi}})`, data:Array(labels.length).fill(lim.hi),
          borderColor:'#f7774f', backgroundColor:'transparent', borderWidth:1.5,
          borderDash:[6,4], pointRadius:0, pointHoverRadius:0, order:0, spanGaps:true }},
        {{ label:`Cận dưới (${{lim.lo}})`, data:Array(labels.length).fill(lim.lo),
          borderColor:'#4fc9a4', backgroundColor:'transparent', borderWidth:1.5,
          borderDash:[6,4], pointRadius:0, pointHoverRadius:0, order:0, spanGaps:true }},
      ];
    }}
  }}
  const lim = seriesList.length===1 && singleParam ? getLimit(section, singleParam) : null;
  const ds = seriesList.map((({{label, series}}, i) => {{
    const map = {{}};
    series.forEach(pt => map[pt.t] = pt.v);
    const data = labels.map(l => map[l] !== undefined ? map[l] : null);
    const col = COLORS[i % COLORS.length];
    return {{
      label, data,
      borderColor: col,
      backgroundColor: mode==='bar' ? col+'bb' : col+'20',
      borderWidth: 2,
      pointRadius: data.map(v => v !== null ? 2.5 : 0),
      pointHoverRadius: 5,
      tension: 0.3, fill: mode==='line' && seriesList.length===1,
      spanGaps: true, order: 1,
      pointBackgroundColor: data.map(v => {{
        if (v===null) return 'transparent';
        if (lim && (v < lim.lo || v > lim.hi)) return '#f7774f';
        return col;
      }}),
      pointBorderColor: 'transparent',
    }};
  }}));
  charts[id] = new Chart(ctx, {{
    type: mode==='bar' ? 'bar' : 'line',
    data: {{ labels, datasets: [...ds, ...limitDs] }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{
        legend: {{
          display: ds.length>1 || limitDs.length>0,
          labels: {{ color:'#8891a8', font:{{size:10}}, boxWidth:14, padding:8 }}
        }},
        tooltip: {{
          backgroundColor:'#1a1d27', borderColor:'#2e3348', borderWidth:1,
          titleColor:'#fff', bodyColor:'#aab', padding:10,
          callbacks: {{
            label: ctx => {{
              const v = ctx.parsed.y?.toFixed(2) ?? 'N/A';
              const ll = lim && ctx.datasetIndex===0 ? lim : null;
              let flag = '';
              if (ll) {{
                const raw = ctx.parsed.y;
                if (raw > ll.hi) flag = ' ⚠️ vượt cận trên';
                else if (raw < ll.lo) flag = ' ⚠️ dưới cận dưới';
              }}
              return ` ${{ctx.dataset.label}}: ${{v}}${{flag}}`;
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ grid:{{color:'#1e2235'}}, ticks:{{color:'#6b748a', font:{{size:9}}, maxRotation:45, maxTicksLimit:16}} }},
        y: {{ grid:{{color:'#1e2235'}}, ticks:{{color:'#6b748a', font:{{size:10}}}} }}
      }}
    }}
  }});
}}
function cardHtml(id, title, section, param, dataset) {{
  const series = getSeries(section, param, dataset);
  const lim = getLimit(section, param);
  const s = calcStats(series, lim);
  const tIcon = s.trend==='up'?'▲':s.trend==='down'?'▼':'—';
  const lastNum = parseFloat(s.last);
  const inRange = lim ? (lastNum>=lim.lo && lastNum<=lim.hi) : null;
  const badges = `<div class="card-badges">
    <span class="cbadge">${{section}}</span>
    ${{lim ? `<span class="cbadge limit-badge">↕ ${{lim.lo}}–${{lim.hi}}</span>` : ''}}
    ${{lim && s.breachCount>0 ? `<span class="cbadge" style="background:rgba(247,119,79,.2);color:#f7774f;border:1px solid rgba(247,119,79,.3)">⚠️ ${{s.breachCount}} lệch</span>` : ''}}
    ${{lim && s.breachCount===0 && series.length>0 ? `<span class="cbadge" style="background:rgba(79,201,164,.12);color:#4fc9a4;border:1px solid rgba(79,201,164,.25)">✓ Đạt chuẩn</span>` : ''}}
  </div>`;
  const lastClass = lim ? (inRange ? 'ok' : 'breach') : '';
  return `<div class="chart-card">
    <div class="card-top"><div class="card-title">${{title}}</div>${{badges}}</div>
    <div class="chart-wrap"><canvas id="${{id}}"></canvas></div>
    <div class="stat-row">
      <div class="stat-item"><div class="stat-val">${{s.avg}}</div><div class="stat-lbl">Trung bình</div></div>
      <div class="stat-item"><div class="stat-val" style="color:#4fc9a4">${{s.min}}</div><div class="stat-lbl">Min</div></div>
      <div class="stat-item"><div class="stat-val" style="color:#f7774f">${{s.max}}</div><div class="stat-lbl">Max</div></div>
      <div class="stat-item ${{lastClass}}"><div class="stat-val ${{s.trend}}">${{tIcon}} ${{s.last}}</div><div class="stat-lbl">Gần nhất ${{lim?(inRange?'✓':'⚠️'):''}}</div></div>
    </div>
  </div>`;
}}
function renderCardChart(id, section, param, dataset) {{
  const series = getSeries(section, param, dataset);
  makeChart(id, [{{label: param, series}}], section, param);
}}
function legendBar() {{
  return `<div class="legend-bar">
    <div class="legend-item"><div class="legend-line solid"></div> Giá trị đo</div>
    <div class="legend-item"><div class="legend-line dashed"></div> Cận trên</div>
    <div class="legend-item"><div class="legend-line dashed-green"></div> Cận dưới</div>
    <div class="legend-item" style="color:#f7774f">● Điểm vượt ngưỡng</div>
  </div>`;
}}
function renderOverview() {{
  const mc = document.getElementById('mainContent');
  const kpiList = [
    {{s:'Syrup sau lắng nổi',p:'Ap',d:'hoa',c:'#4f8ef7'}},
    {{s:'Syrup sau lắng nổi',p:'Độ màu',d:'hoa',c:'#f7c34f'}},
    {{s:'Syrup trước lắng nổi',p:'Bx',d:'hoa',c:'#4fc9a4'}},
    {{s:'Syrup trước lắng nổi',p:'pH',d:'hoa',c:'#f7c34f'}},
    {{s:'Nước chè trong 2',p:'Độ màu',d:'hoa',c:'#f7c34f'}},
    {{s:'Nước chè trong 2',p:'Độ đục (IU)',d:'hoa',c:'#b44ff7'}},
    {{s:'Nước chè trong 2',p:'pH',d:'hoa',c:'#f7c34f'}},
    {{s:'Sirô thô sau bốc hơi',p:'Bx',d:'hoa',c:'#4f8ef7'}},
    {{s:'Đường non A',p:'Ap',d:'nau',c:'#4f8ef7'}},
    {{s:'Đường non A',p:'Bx',d:'nau',c:'#4fc9a4'}},
    {{s:'Đường non B',p:'Ap',d:'nau',c:'#4f8ef7'}},
    {{s:'Đường non B',p:'Bx',d:'nau',c:'#4fc9a4'}},
    {{s:'Đường non C',p:'Ap',d:'nau',c:'#4f8ef7'}},
    {{s:'Mật nguyên A',p:'Ap',d:'nau',c:'#f7774f'}},
    {{s:'Mật B',p:'Ap',d:'nau',c:'#f7774f'}},
    {{s:'Đường B',p:'Pol',d:'nau',c:'#4fc9a4'}},
    {{s:'Hồi dung C',p:'Ap',d:'nau',c:'#4f8ef7'}},
    {{s:'Hồi dung C',p:'Bx',d:'nau',c:'#4fc9a4'}},
    {{s:'Pol bã',p:'Pol bã',d:'mia',c:'#4f8ef7'}},
    {{s:'Ẩm bã',p:'Ẩm bã',d:'mia',c:'#4fc9a4'}},
    {{s:'Bx mật cuối',p:'Bx mật cuối',d:'matri',c:'#f7c34f'}},
    {{s:'Ap mật rỉ',p:'Ap mật rỉ',d:'matri',c:'#f7774f'}},
  ];
  function getMonthlyStats(d, s, p) {{
    let key;
    if (d === 'hoa') key = 'hoa|' + s + '|' + p;
    else if (d === 'nau') key = 'nau|' + s + '|' + p;
    else if (d === 'mia') key = 'mia|' + p;
    else key = 'mat|' + p;
    return RAW.stats?.[key] || null;
  }}
  let kpiHtml = `<div class="section-header"><span class="dot" style="background:#4f8ef7"></span><span class="section-title">Chỉ số có ngưỡng kiểm soát – Trung bình {month_label}</span></div><div class="kpi-grid">`;
  kpiList.forEach(k=>{{
    const lim = getLimit(k.s, k.p);
    const ms = getMonthlyStats(k.d, k.s, k.p);
    if (!ms || ms.mean === null) return;
    const mean = ms.mean;
    const std = ms.std;
    const inRange = lim ? (mean>=lim.lo && mean<=lim.hi) : null;
    const breachClass = lim ? (inRange?'ok-card':'breach') : '';
    kpiHtml += `<div class="kpi-card ${{breachClass}}">
      <div class="kpi-section">${{k.s}}</div>
      <div class="kpi-param">${{k.p}}</div>
      <div class="kpi-val" style="color:${{inRange===false?'#f7774f':inRange===true?'#4fc9a4':k.c}}">${{mean.toFixed(2)}}</div>
      ${{lim?`<div class="kpi-range">Ngưỡng: ${{lim.lo}}–${{lim.hi}} ${{inRange===false?'⚠️':'✓'}}</div>`:''}}
      <div class="kpi-trend flat">σ: ${{std.toFixed(2)}}</div>
    </div>`;
  }});
  kpiHtml += '</div>';
  mc.innerHTML = kpiHtml;
}}
function renderSingle(section, dataset, params, color) {{
  const mc = document.getElementById('mainContent');
  const specs = [];
  let html = `<div class="section-header"><span class="dot" style="background:${{color}}"></span><span class="section-title">${{section}}</span></div>${{legendBar()}}<div class="chart-grid">`;
  params.forEach(p=>{{
    const id=`s_${{section.replace(/ /g,'_')}}_${{p}}`;
    html += cardHtml(id, `${{section}} – ${{p}}`, section, p, dataset);
    specs.push({{id,p}});
  }});
  html += '</div>';
  mc.innerHTML = html;
  specs.forEach(sp => renderCardChart(sp.id, section, sp.p, dataset));
}}
function renderMulti(sections, title, color) {{
  const mc = document.getElementById('mainContent');
  let html = `<div class="section-header"><span class="dot" style="background:${{color}}"></span><span class="section-title">${{title}}</span></div>${{legendBar()}}`;
  const all = [];
  sections.forEach(sec=>{{
    html+=`<div class="section-group"><div class="sub-label">${{sec.s}}</div><div class="chart-grid">`;
    sec.ps.forEach(p=>{{
      const id=`m_${{sec.s.replace(/ /g,'_')}}_${{p}}`;
      html += cardHtml(id, `${{sec.s}} – ${{p}}`, sec.s, p, sec.d);
      all.push({{id, sec:sec.s, p, d:sec.d}});
    }});
    html+='</div></div>';
  }});
  mc.innerHTML=html;
  all.forEach(sp => renderCardChart(sp.id, sp.sec, sp.p, sp.d));
}}
function renderFlat(dataset, title, color, params) {{
  const mc = document.getElementById('mainContent');
  const specs = [];
  let html = `<div class="section-header"><span class="dot" style="background:${{color}}"></span><span class="section-title">${{title}}</span></div>${{legendBar()}}<div class="chart-grid">`;
  params.forEach(p => {{
    const id = `flat_${{dataset}}_${{p.replace(/ /g,'_')}}`;
    html += cardHtml(id, `${{title}} – ${{p}}`, p, p, dataset);
    specs.push({{id, p}});
  }});
  html += '</div>';
  mc.innerHTML = html;
  specs.forEach(sp => {{
    const series = getSeries(sp.p, sp.p, dataset);
    makeChart(sp.id, [{{label: sp.p, series}}], sp.p, sp.p);
  }});
}}
function showTab(tab) {{
  currentTab = tab;
  const ids=['overview','hoa1','hoa2','hoa3','hoa4','nau1','nau2','nau3','mia','matri'];
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',ids[i]===tab));
  renderTab();
}}
function renderTab() {{
  const mc = document.getElementById('mainContent');
  mc.innerHTML='';
  Object.values(charts).forEach(c=>c.destroy());
  charts = {{}};
  if (currentTab==='overview') renderOverview();
  else if (currentTab==='hoa1') renderSingle('Syrup sau lắng nổi','hoa',['Ap','Bx','Pol','pH','Độ màu'],'#4f8ef7');
  else if (currentTab==='hoa2') renderSingle('Syrup trước lắng nổi','hoa',['Bx','pH','Độ màu'],'#4fc9a4');
  else if (currentTab==='hoa3') renderSingle('Nước chè trong 2','hoa',['Ap','Bx','Pol','pH','Độ màu','Độ đục (IU)'],'#f7c34f');
  else if (currentTab==='hoa4') renderSingle('Sirô thô sau bốc hơi','hoa',['Ap','Bx','Pol','pH','Độ màu'],'#b44ff7');
  else if (currentTab==='nau1') renderMulti([
    {{s:'Đường non A',ps:['Ap','Bx','Pol'],d:'nau'}},
    {{s:'Đường non B',ps:['Ap','Bx','Pol'],d:'nau'}},
    {{s:'Đường non C',ps:['Ap','Bx','Pol'],d:'nau'}},
  ],'Đường non A / B / C','#f7774f');
  else if (currentTab==='nau2') renderMulti([
    {{s:'Đường B',ps:['Ap','Bx','Pol'],d:'nau'}},
    {{s:'Đường C',ps:['Ap','Bx','Pol'],d:'nau'}},
  ],'Đường B & C','#4fc9a4');
  else if (currentTab==='nau3') renderMulti([
    {{s:'Mật nguyên A',ps:['Ap','Bx','Pol'],d:'nau'}},
    {{s:'Mật loãng A',ps:['Ap','Bx','Pol'],d:'nau'}},
    {{s:'Mật B',ps:['Ap','Bx','Pol'],d:'nau'}},
    {{s:'Hồi dung B',ps:['Ap','Bx','Pol','Độ màu'],d:'nau'}},
    {{s:'Hồi dung C',ps:['Ap','Bx','Pol','Độ màu'],d:'nau'}},
  ],'Mật & Hồi dung','#f7c34f');
  else if (currentTab==='mia') renderFlat('mia','Mía – Nước mía','#4f8ef7',[
    'Pol bã','Ẩm bã','Xơ mía','pH gia vôi NM HH','pH NM trung hòa',
    'Ap NM HH','Bx NM HH','Pol NM HH',
    'Ap NM đầu','Bx NM đầu','Pol NM đầu',
    'Ap NM cuối','Bx NM cuối','Pol NM cuối','P2O5'
  ]);
  else if (currentTab==='matri') renderFlat('matri','Mật rỉ – Bùn thô','#f7774f',[
    'Pol bùn','Độ ẩm bùn',
    'Ap mật cuối','Bx mật cuối','Pol mật cuối','RS mật cuối',
    'Ap mật rỉ','Bx mật rỉ','Bx1 mật rỉ','Pol mật rỉ'
  ]);
  updatePointCount();
}}
function renderAll() {{ renderTab(); }}
renderTab();
</script>
</body>
</html>"""

    return html

# ========================
# MAIN
# ========================
def main():
    now_str = now_vn().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🚀 Fetcher bắt đầu: {now_str} (GMT+7)")

    from_date, to_date = get_fetch_range()
    print(f"📅 Kỳ báo cáo: {from_date} → {to_date}")

    print("🔐 Login...")
    token = get_token()
    print("✅ Token OK")

    all_data = []
    for name, code in STEP_MAP.items():
        print(f"📊 Fetching: {name}")
        rows = fetch_data(token, code, from_date, to_date)
        print(f"   → {len(rows)} rows")
        all_data.append(pd.DataFrame(rows))

    df = pd.concat(all_data, ignore_index=True)
    print("🔄 Transform...")
    df = transform(df)

    print("🔧 Build raw data...")
    raw = build_raw(df)

    print("📊 Build dashboard HTML...")
    html = build_dashboard_html(raw, from_date, to_date)
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Dashboard: {DASHBOARD_FILE}")

    cache = {
        "updated_at": now_vn().strftime("%Y-%m-%d %H:%M:%S"),
        "from_date":  from_date,
        "to_date":    to_date,
        "raw":        raw,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ Cache: {CACHE_FILE}")

    print("🏁 Fetcher hoàn tất.")


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
