"""
bot.py — Telegram Bot chạy 24/7 trên JustRunMyApp.
- Đọc cache.json từ GitHub raw URL (do fetcher.py cập nhật mỗi 30 phút)
- Trả kết quả 7 ngày mới nhất theo mặc định
- Hiển thị ngưỡng chuẩn và chênh lệch so với ngưỡng
- /dashboard → gửi file HTML để tải về
- Tự gửi log lỗi về chat nếu có exception
"""

import requests
import json
import os
import traceback as _tb
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ========================
# TIMEZONE
# ========================
TZ_VN = timezone(timedelta(hours=7))

def now_vn():
    return datetime.now(TZ_VN)

# ========================
# CONFIG
# ========================
BOT_TOKEN       = os.environ["BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["ALLOWED_CHAT_ID"])
GITHUB_PAT      = os.environ.get("PAT", "")

GITHUB_OWNER    = "minht3902"
GITHUB_BOT_REPO = "sugarmama_bot"
GITHUB_CFG_REPO = "sugarmama_config"
GITHUB_API      = "https://api.github.com"

GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_BOT_REPO}/main"
CACHE_URL       = f"{GITHUB_RAW_BASE}/cache.json"
DASHBOARD_URL   = f"{GITHUB_RAW_BASE}/dashboard.html"

BOT_START_TIME  = now_vn()  # Ghi nhận lúc bot khởi động

# ========================
# USERS (đọc từ sugarmama_config/users.json)
# ========================
_ALLOWED_USERS: list[int] = []

def _gh_headers():
    return {"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github+json"}

def load_allowed_users() -> list[int]:
    """Đọc danh sách user từ sugarmama_config/users.json qua GitHub API."""
    try:
        url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_CFG_REPO}/contents/users.json"
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        r.raise_for_status()
        import base64
        content = base64.b64decode(r.json()["content"]).decode("utf-8")
        users = json.loads(content)
        return [int(u) for u in users]
    except Exception as e:
        print(f"[LOAD USERS ERROR] {e}")
        return [ALLOWED_CHAT_ID]

def save_allowed_users(users: list[int]) -> bool:
    """Ghi danh sách user lên sugarmama_config/users.json qua GitHub API."""
    try:
        import base64
        url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_CFG_REPO}/contents/users.json"
        # Lấy SHA hiện tại
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        r.raise_for_status()
        sha = r.json()["sha"]
        # Ghi nội dung mới
        content = json.dumps(users, ensure_ascii=False)
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": f"chore: update users [{now_vn().strftime('%Y-%m-%d %H:%M')}]",
            "content": encoded,
            "sha": sha
        }
        r2 = requests.put(url, headers=_gh_headers(), json=payload, timeout=15)
        r2.raise_for_status()
        return True
    except Exception as e:
        print(f"[SAVE USERS ERROR] {e}")
        return False

# Load lần đầu khi khởi động
_ALLOWED_USERS = load_allowed_users()
print(f"✅ Loaded {len(_ALLOWED_USERS)} allowed users: {_ALLOWED_USERS}")

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

# Tra ngưỡng nhanh theo (section, param)
def get_limit(section, param):
    """Trả về {'lo':..,'hi':..} hoặc None."""
    if section in LIMITS and param in LIMITS[section]:
        return LIMITS[section][param]
    # Fallback: tìm theo param trong tất cả sections
    for lim_section, params in LIMITS.items():
        if param in params:
            return params[param]
    return None

# Map từ COMMAND_MAP key → (section dùng để tra LIMITS, param)
# Dùng để tra ngưỡng khi format kết quả
LIMIT_LOOKUP = {
    # MIA
    "/pol_ba":      ("Mía - Nước mía", "Pol bã"),
    "/am_ba":       ("Mía - Nước mía", "Ẩm bã"),
    "/ph_nmgv":     ("Mía - Nước mía", "pH gia vôi NM HH"),
    "/ph_nmth":     ("Mía - Nước mía", "pH NM trung hòa"),
    "/bx_nmhh":     ("Mía - Nước mía", "Bx NM HH"),
    "/bx_nmcuoi":   ("Mía - Nước mía", "Bx NM cuối"),
    "/p2o5":        ("Mía - Nước mía", "P2O5"),
    # MAT
    "/pol_bun":     ("Mật rỉ - Bùn thô", "Pol bùn"),
    "/am_bun":      ("Mật rỉ - Bùn thô", "Độ ẩm bùn"),
    "/bx_mc":       ("Mật rỉ - Bùn thô", "Bx mật cuối"),
    "/ap_mr":       ("Mật rỉ - Bùn thô", "Ap mật rỉ"),
    "/bx1_mr":      ("Mật rỉ - Bùn thô", "Bx1 mật rỉ"),
    # HOA
    "/duc_nct2":    ("Nước chè trong 2", "Độ đục (IU)"),
    "/mau_nct2":    ("Nước chè trong 2", "Độ màu"),
    "/ph_nct2":     ("Nước chè trong 2", "pH"),
    "/mau_syrup_s": ("Syrup sau lắng nổi", "Độ màu"),
    "/bx_syrup_t":  ("Syrup trước lắng nổi", "Bx"),
    "/ph_syrup_t":  ("Syrup trước lắng nổi", "pH"),
    "/bx_siro":     ("Sirô thô sau bốc hơi", "Bx"),
    "/mau_siro":    ("Sirô thô sau bốc hơi", "Độ màu"),
    # NAU
    "/ap_nona":     ("Đường non A", "Ap"),
    "/bx_nona":     ("Đường non A", "Bx"),
    "/ap_nonb":     ("Đường non B", "Ap"),
    "/bx_nonb":     ("Đường non B", "Bx"),
    "/ap_nonc":     ("Đường non C", "Ap"),
    "/bx_nonc":     ("Đường non C", "Bx"),
    "/ap_mna":      ("Mật nguyên A", "Ap"),
    "/bx_mna":      ("Mật nguyên A", "Bx"),
    "/ap_mla":      ("Mật loãng A", "Ap"),
    "/bx_mla":      ("Mật loãng A", "Bx"),
    "/ap_mb":       ("Mật B", "Ap"),
    "/bx_mb":       ("Mật B", "Bx"),
    "/pol_dgb":     ("Đường B", "Pol"),
    "/ap_hdc":      ("Hồi dung C", "Ap"),
    "/bx_hdc":      ("Hồi dung C", "Bx"),
}

# ========================
# MAPPING
# ========================
COMMAND_MAP = {
    "/am_ba":       ("mia", "Ẩm bã",           "Độ ẩm bã mía"),
    "/pol_ba":      ("mia", "Pol bã",           "Pol bã mía"),
    "/xo_mia":      ("mia", "Xơ mía",           "Xơ mía"),
    "/p2o5":        ("mia", "P2O5",             "Hàm lượng P2O5"),
    "/ph_nmgv":     ("mia", "pH gia vôi NM HH", "pH NM gia vôi"),
    "/ph_nmth":     ("mia", "pH NM trung hòa",  "pH NM trung hòa"),
    "/ap_nmcuoi":   ("mia", "Ap NM cuối",       "Ap NM cuối (Nước chè ép)"),
    "/bx_nmcuoi":   ("mia", "Bx NM cuối",       "Bx NM cuối (Nước chè ép)"),
    "/pol_nmcuoi":  ("mia", "Pol NM cuối",      "Pol NM cuối (Nước chè ép)"),
    "/ap_nmdau":    ("mia", "Ap NM đầu",        "Ap NM đầu"),
    "/bx_nmdau":    ("mia", "Bx NM đầu",        "Bx NM đầu"),
    "/pol_nmdau":   ("mia", "Pol NM đầu",       "Pol NM đầu"),
    "/ap_nmhh":     ("mia", "Ap NM HH",         "Ap NM hỗn hợp"),
    "/bx_nmhh":     ("mia", "Bx NM HH",         "Bx NM hỗn hợp"),
    "/pol_nmhh":    ("mia", "Pol NM HH",        "Pol NM hỗn hợp"),
    "/am_bun":      ("mat", "Độ ẩm bùn",    "Độ ẩm bùn thô"),
    "/pol_bun":     ("mat", "Pol bùn",      "Pol bùn thô"),
    "/ap_mc":       ("mat", "Ap mật cuối",  "Ap mật cuối"),
    "/bx_mc":       ("mat", "Bx mật cuối",  "Bx mật cuối"),
    "/pol_mc":      ("mat", "Pol mật cuối", "Pol mật cuối"),
    "/rs_mc":       ("mat", "RS mật cuối",  "RS mật cuối"),
    "/ap_mr":       ("mat", "Ap mật rỉ",    "Ap mật rỉ"),
    "/bx_mr":       ("mat", "Bx mật rỉ",    "Bx mật rỉ"),
    "/bx1_mr":      ("mat", "Bx1 mật rỉ",   "Bx1 mật rỉ"),
    "/pol_mr":      ("mat", "Pol mật rỉ",   "Pol mật rỉ"),
    "/ap_nct2":     ("hoa", "Nước chè trong 2", "Ap",          "Ap Nước chè trong 2"),
    "/bx_nct2":     ("hoa", "Nước chè trong 2", "Bx",          "Bx Nước chè trong 2"),
    "/pol_nct2":    ("hoa", "Nước chè trong 2", "Pol",         "Pol Nước chè trong 2"),
    "/ph_nct2":     ("hoa", "Nước chè trong 2", "pH",          "pH Nước chè trong 2"),
    "/duc_nct2":    ("hoa", "Nước chè trong 2", "Độ đục (IU)", "Độ đục NCT2 (IU)"),
    "/mau_nct2":    ("hoa", "Nước chè trong 2", "Độ màu",      "Độ màu NCT2"),
    "/ap_siro":     ("hoa", "Sirô thô sau bốc hơi", "Ap",      "Ap Sirô thô"),
    "/bx_siro":     ("hoa", "Sirô thô sau bốc hơi", "Bx",      "Bx Sirô thô"),
    "/pol_siro":    ("hoa", "Sirô thô sau bốc hơi", "Pol",     "Pol Sirô thô"),
    "/ph_siro":     ("hoa", "Sirô thô sau bốc hơi", "pH",      "pH Sirô thô"),
    "/mau_siro":    ("hoa", "Sirô thô sau bốc hơi", "Độ màu",  "Độ màu Sirô thô"),
    "/ap_syrup_s":  ("hoa", "Syrup sau lắng nổi", "Ap",        "Ap Syrup sau lắng nổi"),
    "/bx_syrup_s":  ("hoa", "Syrup sau lắng nổi", "Bx",        "Bx Syrup sau lắng nổi"),
    "/pol_syrup_s": ("hoa", "Syrup sau lắng nổi", "Pol",       "Pol Syrup sau lắng nổi"),
    "/ph_syrup_s":  ("hoa", "Syrup sau lắng nổi", "pH",        "pH Syrup sau lắng nổi"),
    "/mau_syrup_s": ("hoa", "Syrup sau lắng nổi", "Độ màu",    "Độ màu Syrup sau"),
    "/duc_syrup_s": ("hoa", "Syrup sau lắng nổi", "Độ đục",    "Độ đục Syrup sau"),
    "/ap_syrup_t":  ("hoa", "Syrup trước lắng nổi", "Ap",      "Ap Syrup trước lắng nổi"),
    "/bx_syrup_t":  ("hoa", "Syrup trước lắng nổi", "Bx",      "Bx Syrup trước lắng nổi"),
    "/pol_syrup_t": ("hoa", "Syrup trước lắng nổi", "Pol",     "Pol Syrup trước lắng nổi"),
    "/ph_syrup_t":  ("hoa", "Syrup trước lắng nổi", "pH",      "pH Syrup trước lắng nổi"),
    "/mau_syrup_t": ("hoa", "Syrup trước lắng nổi", "Độ màu",  "Độ màu Syrup trước"),
    "/duc_syrup_t": ("hoa", "Syrup trước lắng nổi", "Độ đục",  "Độ đục Syrup trước"),
    "/ap_dgb":       ("nau", "Đường B",     "Ap",        "Ap Đường B"),
    "/bx_dgb":       ("nau", "Đường B",     "Bx",        "Bx Đường B"),
    "/pol_dgb":      ("nau", "Đường B",     "Pol",       "Pol Đường B"),
    "/ap_dgc":       ("nau", "Đường C",     "Ap",        "Ap Đường C"),
    "/bx_dgc":       ("nau", "Đường C",     "Bx",        "Bx Đường C"),
    "/pol_dgc":      ("nau", "Đường C",     "Pol",       "Pol Đường C"),
    "/ap_nona":      ("nau", "Đường non A", "Ap",        "Ap Đường non A"),
    "/bx_nona":      ("nau", "Đường non A", "Bx",        "Bx Đường non A"),
    "/pol_nona":     ("nau", "Đường non A", "Pol",       "Pol Đường non A"),
    "/ap_nonb":      ("nau", "Đường non B", "Ap",        "Ap Đường non B"),
    "/bx_nonb":      ("nau", "Đường non B", "Bx",        "Bx Đường non B"),
    "/pol_nonb":     ("nau", "Đường non B", "Pol",       "Pol Đường non B"),
    "/ap_nonc":      ("nau", "Đường non C", "Ap",        "Ap Đường non C"),
    "/bx_nonc":      ("nau", "Đường non C", "Bx",        "Bx Đường non C"),
    "/pol_nonc":     ("nau", "Đường non C", "Pol",       "Pol Đường non C"),
    "/ap_hdb":      ("nau", "Hồi dung B", "Ap",         "Ap Hồi dung B"),
    "/bx_hdb":      ("nau", "Hồi dung B", "Bx",         "Bx Hồi dung B"),
    "/pol_hdb":     ("nau", "Hồi dung B", "Pol",        "Pol Hồi dung B"),
    "/mau_hdb":     ("nau", "Hồi dung B", "Độ màu",     "Độ màu Hồi dung B"),
    "/ap_hdc":      ("nau", "Hồi dung C", "Ap",         "Ap Hồi dung C"),
    "/bx_hdc":      ("nau", "Hồi dung C", "Bx",         "Bx Hồi dung C"),
    "/pol_hdc":     ("nau", "Hồi dung C", "Pol",        "Pol Hồi dung C"),
    "/mau_hdc":     ("nau", "Hồi dung C", "Độ màu",     "Độ màu Hồi dung C"),
    "/ap_mb":       ("nau", "Mật B",      "Ap",         "Ap Mật B"),
    "/bx_mb":       ("nau", "Mật B",      "Bx",         "Bx Mật B"),
    "/pol_mb":      ("nau", "Mật B",      "Pol",        "Pol Mật B"),
    "/ap_mla":      ("nau", "Mật loãng A","Ap",         "Ap Mật loãng A"),
    "/bx_mla":      ("nau", "Mật loãng A","Bx",         "Bx Mật loãng A"),
    "/pol_mla":     ("nau", "Mật loãng A","Pol",        "Pol Mật loãng A"),
    "/ap_mna":      ("nau", "Mật nguyên A","Ap",        "Ap Mật nguyên A"),
    "/bx_mna":      ("nau", "Mật nguyên A","Bx",        "Bx Mật nguyên A"),
    "/pol_mna":     ("nau", "Mật nguyên A","Pol",       "Pol Mật nguyên A"),
}

MIA_MAP_LABELS = [
    "Pol bã","Ẩm bã","Xơ mía","pH gia vôi NM HH","pH NM trung hòa",
    "Ap NM HH","Bx NM HH","Pol NM HH","P2O5",
    "Ap NM đầu","Bx NM đầu","Pol NM đầu",
    "Ap NM cuối","Bx NM cuối","Pol NM cuối",
]
MAT_MAP_LABELS = [
    "Pol bùn","Độ ẩm bùn","Ap mật cuối","Bx mật cuối","Pol mật cuối",
    "RS mật cuối","Ap mật rỉ","Bx mật rỉ","Bx1 mật rỉ","Pol mật rỉ",
]
HOA_MAP_KEYS = {
    "Syrup sau lắng nổi":   ["Ap","Bx","Pol","pH","Độ màu","Độ đục"],
    "Syrup trước lắng nổi": ["Ap","Bx","Pol","pH","Độ màu","Độ đục"],
    "Nước chè trong 2":     ["Ap","Bx","Pol","pH","Độ màu","Độ đục (IU)"],
    "Sirô thô sau bốc hơi": ["Ap","Bx","Pol","pH","Độ màu"],
}
NAU_MAP_KEYS = {
    "Mật loãng A":  ["Ap","Bx","Pol"],
    "Mật nguyên A": ["Ap","Bx","Pol"],
    "Mật B":        ["Ap","Bx","Pol"],
    "Hồi dung B":   ["Ap","Bx","Pol","Độ màu"],
    "Hồi dung C":   ["Ap","Bx","Pol","Độ màu"],
    "Đường B":      ["Ap","Bx","Pol"],
    "Đường C":      ["Ap","Bx","Pol"],
    "Đường non A":  ["Ap","Bx","Pol"],
    "Đường non B":  ["Ap","Bx","Pol"],
    "Đường non C":  ["Ap","Bx","Pol"],
}

# ========================
# CACHE — Multi-cache support
# ========================
# cache.json         : dữ liệu vụ hiện tại (fetcher tự động)
# cache_FROM_TO.json : dữ liệu cũ do /newcache tạo
#   ví dụ: cache_2024-12-01_2024-12-31.json

def _fetch_json(url: str):
    """Tải JSON từ URL, trả về (data, error)."""
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def _load_cache_safe():
    """Tải cache.json chính, trả về (cache_dict, error_str)."""
    return _fetch_json(CACHE_URL)

def _list_old_caches() -> list[dict]:
    """
    Liệt kê các file cache_*.json trong repo qua GitHub API.
    Trả về list[{"name": str, "from": str, "to": str, "url": str}]
    """
    try:
        url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_BOT_REPO}/contents/"
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        r.raise_for_status()
        files = r.json()
        result = []
        import re as _re
        for f in files:
            m = _re.match(r'^cache_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.json$', f["name"])
            if m:
                result.append({
                    "name": f["name"],
                    "from": m.group(1),
                    "to":   m.group(2),
                    "url":  f"{GITHUB_RAW_BASE}/{f['name']}"
                })
        return sorted(result, key=lambda x: x["from"])
    except Exception as e:
        print(f"[LIST CACHES ERROR] {e}")
        return []

def _find_cache_for_range(from_d: str, to_d: str):
    """
    Tìm cache phù hợp cho khoảng [from_d, to_d].
    Trả về (cache_dict, source_label, error_str).
    Logic:
      1. Thử cache.json chính trước
      2. Nếu khoảng nằm ngoài cache chính → tìm cache_*.json
      3. Nếu khoảng trải dài qua nhiều cache → merge
      4. Nếu không đủ dữ liệu → trả thông báo rõ ràng
    """
    # Bước 1: load cache chính
    main_cache, err = _load_cache_safe()

    def _range_covered(cache, fd, td):
        """Kiểm tra cache có chứa dữ liệu cho khoảng [fd, td] không."""
        if not cache:
            return False
        cf = cache.get("from_date", "9999-99-99")
        ct = cache.get("to_date",   "0000-00-00")
        return cf <= fd and td <= ct

    # Nếu cache chính đủ → dùng luôn
    if main_cache and _range_covered(main_cache, from_d, to_d):
        return main_cache, "cache hiện tại", None

    # Bước 2: tìm trong cache cũ
    old_caches = _list_old_caches()

    # Bước 3: gom tất cả cache có overlap với [from_d, to_d]
    candidates = []
    if main_cache and not err:
        cf = main_cache.get("from_date", "9999")
        ct = main_cache.get("to_date",   "0000")
        if cf <= to_d and ct >= from_d:  # có overlap
            candidates.append((cf, ct, main_cache, "cache hiện tại"))

    for oc in old_caches:
        if oc["from"] <= to_d and oc["to"] >= from_d:  # có overlap
            data, e = _fetch_json(oc["url"])
            if data:
                candidates.append((oc["from"], oc["to"], data, oc["name"]))

    if not candidates:
        # Tìm xem có cache nào gần nhất không để gợi ý
        all_ranges = [(oc["from"], oc["to"]) for oc in old_caches]
        if main_cache:
            all_ranges.append((main_cache.get("from_date","?"), main_cache.get("to_date","?")))
        hint = ""
        if all_ranges:
            hint = "\n📦 Cache hiện có:\n" + "\n".join(f"  • `{f}` → `{t}`" for f, t in sorted(all_ranges))
        return None, None, (
            f"⚠️ Chưa có dữ liệu cho khoảng `{_fmt_date(from_d)}` → `{_fmt_date(to_d)}`.\n"
            f"Dùng `/newcache {_fmt_date(from_d)} - {_fmt_date(to_d)}` để tạo cache rồi gọi lại lệnh."
            + hint
        )

    # Bước 4: nếu chỉ 1 candidate → dùng luôn
    if len(candidates) == 1:
        _, _, data, label = candidates[0]
        return data, label, None

    # Bước 5: merge raw data từ nhiều cache
    merged_raw = {}
    labels = []
    for _, _, data, label in sorted(candidates, key=lambda x: x[0]):
        labels.append(label)
        raw = data.get("raw", {})
        for group in ("mia", "mat", "hoa", "nau"):
            if group not in raw:
                continue
            if group not in merged_raw:
                merged_raw[group] = {}
            grp = raw[group]
            if group in ("mia", "mat"):
                for key, series in grp.items():
                    if key not in merged_raw[group]:
                        merged_raw[group][key] = []
                    existing_ts = {pt["t"] for pt in merged_raw[group][key]}
                    merged_raw[group][key] += [pt for pt in series if pt["t"] not in existing_ts]
                    merged_raw[group][key].sort(key=lambda x: x["t"])
            else:  # hoa, nau — nested dict
                for section, params in grp.items():
                    if section not in merged_raw[group]:
                        merged_raw[group][section] = {}
                    for param, series in params.items():
                        if param not in merged_raw[group][section]:
                            merged_raw[group][section][param] = []
                        existing_ts = {pt["t"] for pt in merged_raw[group][section][param]}
                        merged_raw[group][section][param] += [pt for pt in series if pt["t"] not in existing_ts]
                        merged_raw[group][section][param].sort(key=lambda x: x["t"])

    merged_cache = {
        "from_date":  min(c[0] for c in candidates),
        "to_date":    max(c[1] for c in candidates),
        "updated_at": now_vn().strftime("%Y-%m-%d %H:%M:%S"),
        "raw":        merged_raw,
    }
    return merged_cache, f"merged ({', '.join(labels)})", None

# ========================
# SERIES HELPERS
# ========================
def _get_series_from_cache(cache, cmd):
    mapping = COMMAND_MAP.get(cmd)
    if not mapping:
        return None, f"Lệnh {cmd} không tồn tại."

    raw = cache.get("raw", {})
    group = mapping[0]

    try:
        if group == "mia":
            label, display = mapping[1], mapping[2]
            series = raw["mia"].get(label)
        elif group == "mat":
            label, display = mapping[1], mapping[2]
            series = raw["mat"].get(label)
        elif group == "hoa":
            section, key, display = mapping[1], mapping[2], mapping[3]
            series = raw["hoa"].get(section, {}).get(key)
        elif group == "nau":
            section, key, display = mapping[1], mapping[2], mapping[3]
            series = raw["nau"].get(section, {}).get(key)
        else:
            return None, "Nhóm dữ liệu không xác định."
    except Exception as e:
        return None, f"Lỗi truy xuất data: {e}"

    if series is None:
        return None, f"Không tìm thấy dữ liệu cho lệnh {cmd} trong cache."
    return series, display

def _parse_date_arg(arg):
    arg = arg.strip()
    if not arg:
        return None, None

    def _parse_one(s):
        s = s.strip()
        now_y = now_vn().year
        for fmt in ("%d/%m/%Y", "%d/%m"):
            try:
                dt = datetime.strptime(s, fmt)
                if fmt == "%d/%m":
                    dt = dt.replace(year=now_y)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        raise ValueError(f"Không nhận ra định dạng ngày: '{s}'. Dùng DD/MM hoặc DD/MM/YYYY.")

    import re as _re
    range_match = _re.match(r'^(.+?)\s*-\s*(.+)$', arg)
    if range_match:
        return _parse_one(range_match.group(1)), _parse_one(range_match.group(2))
    else:
        d = _parse_one(arg)
        return d, d

def _filter_series(series, from_d, to_d):
    return [pt for pt in series if from_d <= pt["t"][:10] <= to_d]

def _latest_7_days(series):
    """Trả về (from_d, to_d) của 7 ngày mới nhất có data."""
    days = sorted({pt["t"][:10] for pt in series if pt["v"] is not None}, reverse=True)
    if not days:
        return None, None
    to_d   = days[0]
    from_d = days[min(6, len(days)-1)]
    return from_d, to_d

def _stats(vals):
    if not vals:
        return None, None, None, None
    mean = sum(vals) / len(vals)
    std  = (sum((x - mean)**2 for x in vals) / len(vals)) ** 0.5
    return round(mean, 2), round(std, 2), round(min(vals), 2), round(max(vals), 2)

def _fmt_date(iso):
    """'2025-12-27' → '27/12/2025'"""
    return f"{iso[8:]}/{iso[5:7]}/{iso[:4]}"

def _limit_status(val, lim):
    """
    Trả về (icon, note) dựa trên val so với lim {'lo':..,'hi':..}.
    Ví dụ: ('⚠️', '+1.1 so với ngưỡng trên (83)')
    """
    if lim is None or val is None:
        return "", ""
    lo, hi = lim["lo"], lim["hi"]
    if val > hi:
        diff = round(val - hi, 3)
        return "⚠️", f"+{diff} so với ngưỡng trên ({hi})"
    elif val < lo:
        diff = round(lo - val, 3)
        return "⚠️", f"-{diff} so với ngưỡng dưới ({lo})"
    else:
        return "✅", ""

# ========================
# FORMAT SINGLE
# ========================
def _format_single(series, display, from_d, to_d, date_label, cmd, updated_at):
    filtered = _filter_series(series, from_d, to_d)
    lim_key  = LIMIT_LOOKUP.get(cmd)
    lim      = get_limit(*lim_key) if lim_key else None

    footer = f"\n_🔄 Cập nhật lần cuối: {updated_at}_"

    if not filtered:
        return f"📭 *{display}*\n`{date_label}`: Không có dữ liệu.{footer}"

    lines = [f"📊 *{display}*", f"🗓 `{date_label}`"]

    if lim:
        lines.append(f"📐 Ngưỡng chuẩn: `{lim['lo']} – {lim['hi']}`")

    lines.append("─" * 30)

    if from_d == to_d:
        for pt in filtered:
            time_str = pt["t"][11:16]
            icon, note = _limit_status(pt["v"], lim)
            note_str = f"  {icon} {note}" if note else (f"  {icon}" if icon else "")
            lines.append(f"  `{time_str}`  →  *{pt['v']}*{note_str}")
        lines.append("─" * 30)
        vals = [pt["v"] for pt in filtered]
        mean, std, mn, mx = _stats(vals)
        lines.append(f"TB: *{mean}* ± {std}")
        lines.append(f"Min: {mn}  |  Max: {mx}  |  Số lần đo: {len(vals)}")
    else:
        buckets = defaultdict(list)
        for pt in filtered:
            buckets[pt["t"][:10]].append(pt["v"])
        all_vals = []
        for day in sorted(buckets):
            vals = [v for v in buckets[day] if v is not None]
            if not vals:
                continue
            all_vals.extend(vals)
            mean_d, std_d, _, _ = _stats(vals)
            day_mean_icon, day_mean_note = _limit_status(mean_d, lim)
            note_str = f"  {day_mean_icon} {day_mean_note}" if day_mean_note else (f"  {day_mean_icon}" if day_mean_icon else "")
            lines.append(
                f"  `{_fmt_date(day)}`  TB={mean_d} ±{std_d}  (Số lần đo: {len(vals)}){note_str}"
            )
        lines.append("─" * 30)
        mean, std, mn, mx = _stats(all_vals)
        lines.append(f"Tổng hợp: TB=*{mean}* ±{std}")
        lines.append(f"Min={mn}  Max={mx}  Số lần đo: {len(all_vals)}")

    lines.append(footer)
    return "\n".join(lines)

# ========================
# FORMAT SUMMARY SECTION
# ========================
def _format_summary_section(raw, section_name, section_key, items, from_d, to_d):
    lines = [f"\n*── {section_name} ──*"]
    for item in items:
        if section_key == "mia":
            label = item if isinstance(item, str) else item["label"]
            series = raw["mia"].get(label, [])
            name = label
            lim = None
            # Tra ngưỡng
            for cmd, (sec, param) in LIMIT_LOOKUP.items():
                if param == label or name == label:
                    lim = get_limit(sec, param)
                    break
        elif section_key == "mat":
            label = item if isinstance(item, str) else item["label"]
            series = raw["mat"].get(label, [])
            name = label
            lim = None
            for cmd, (sec, param) in LIMIT_LOOKUP.items():
                if param == label:
                    lim = get_limit(sec, param)
                    break
        elif section_key == "hoa":
            section, key = item
            series = raw["hoa"].get(section, {}).get(key, [])
            name = f"{section} / {key}"
            lim = get_limit(section, key)
        elif section_key == "nau":
            section, key = item
            series = raw["nau"].get(section, {}).get(key, [])
            name = f"{section} / {key}"
            lim = get_limit(section, key)
        else:
            continue

        filtered = _filter_series(series, from_d, to_d)
        vals = [pt["v"] for pt in filtered if pt["v"] is not None]
        if not vals:
            lines.append(f"  `{name}`: N/A")
            continue

        if from_d == to_d:
            mean, std, mn, mx = _stats(vals)
            icon, note = _limit_status(mean, lim)
            lim_str = f" [{lim['lo']}–{lim['hi']}]" if lim else ""
            status_str = f" {icon}" + (f" {note}" if note else "")
            lines.append(f"  `{name}`: {mean} ±{std} [{mn}–{mx}]{lim_str}{status_str}")
        else:
            buckets = defaultdict(list)
            for pt in filtered:
                buckets[pt["t"][:10]].append(pt["v"])
            day_lines = []
            for day in sorted(buckets)[-7:]:
                dv = [v for v in buckets[day] if v is not None]
                if dv:
                    m, s, _, _ = _stats(dv)
                    icon, note = _limit_status(m, lim)
                    status = f" {icon}" if icon else ""
                    day_lines.append(f"{_fmt_date(day)}:{m}±{s}{status}")
            lim_str = f" [Ngưỡng: {lim['lo']}–{lim['hi']}]" if lim else ""
            lines.append(f"  `{name}`{lim_str}: " + "  ".join(day_lines))

    return "\n".join(lines)

# ========================
# TELEGRAM HELPERS
# ========================
async def _send(context, chat_id, text):
    MAX = 4000
    while text:
        chunk = text[:MAX]
        if len(text) > MAX:
            cut = chunk.rfind("\n")
            if cut > 0:
                chunk = text[:cut]
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk,
            parse_mode="Markdown"
        )
        text = text[len(chunk):].lstrip("\n")

async def _send_error(context, chat_id, err_msg):
    """Gửi log lỗi về chat."""
    msg = (
        f"🚨 *Bot gặp lỗi*\n"
        f"⏰ `{now_vn().strftime('%Y-%m-%d %H:%M:%S')}` (GMT+7)\n\n"
        f"```\n{err_msg[-1500:]}\n```"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception:
        pass

def _guard(func):
    """Decorator: chặn chat_id không được phép, bắt lỗi và tự báo cáo."""
    async def wrapper(update, context):
        uid = update.effective_chat.id
        if uid not in _ALLOWED_USERS and uid != ALLOWED_CHAT_ID:
            await update.message.reply_text("⛔ Không có quyền truy cập.")
            return
        try:
            await func(update, context)
        except Exception as e:
            err = _tb.format_exc()
            _tb.print_exc()
            await update.message.reply_text(f"❌ Lỗi xử lý lệnh: {e}")
            await _send_error(context, ALLOWED_CHAT_ID, err)
    return wrapper

# ========================
# BOT COMMANDS
# ========================

@_guard
async def cmd_help(update, context):
    cmds = sorted(COMMAND_MAP.keys())
    chunks = [cmds[i:i+20] for i in range(0, len(cmds), 20)]
    msg = "*📋 DANH SÁCH LỆNH*\n\n"
    for chunk in chunks:
        msg += "  ".join(f"`{c}`" for c in chunk) + "\n"
    msg += (
        "\n*Mặc định:* trả dữ liệu 7 ngày mới nhất\n\n"
        "*Cú pháp ngày tùy chọn:*\n"
        "`/lệnh DD/MM`  → ngày cụ thể\n"
        "`/lệnh DD/MM/YYYY`  → ngày cụ thể (năm rõ ràng)\n"
        "`/lệnh DD/MM-DD/MM`  → khoảng ngày\n"
        "\n`/summary [ngày]`  → tóm tắt tất cả thông số\n"
        "`/dashboard [ngày]`  → tải file Dashboard HTML\n"
        "`/status`  → trạng thái hiện tại của bot\n\n"
        "*Quản lý (chỉ admin):*\n"
        "`/add_user <chat_id>`  → thêm người dùng\n"
        "`/remove_user <chat_id>`  → xóa người dùng\n"
        "`/update`  → cập nhật dữ liệu ngay\n"
        "`/newcache DD/MM/YYYY - DD/MM/YYYY`  → fetch dữ liệu cũ"
    )
    await _send(context, update.effective_chat.id, msg)


@_guard
async def cmd_status(update, context):
    now       = now_vn()
    is_admin  = _is_admin(update.effective_chat.id)

    cache, err = _load_cache_safe()
    cache_line = (
        f"⚠️ Cache lỗi: `{err}`" if err else
        f"🔄 Data cập nhật: `{cache.get('updated_at', 'N/A')}`\n"
        f"📅 Khoảng data: `{cache.get('from_date')}` → `{cache.get('to_date')}`"
    )

    # Liệt kê các file cache cũ
    old_caches = _list_old_caches()
    if old_caches:
        cache_names = "\n".join(f"• `{c['name']}`" for c in old_caches)
        cache_section = f"\n\n*📦 Dữ liệu sẵn có:*\n{cache_names}"
    else:
        cache_section = ""

    msg = (
        f"*🤖 Bot Status*\n"
        f"🟢 Online — `{now.strftime('%Y-%m-%d %H:%M:%S')}` (GMT+7)\n\n"
        f"{cache_line}"
        f"{cache_section}"
    )

    if is_admin:
        msg += "\n\n⚠️ _Remember to reset JustRunMyApp manually!_"

    await update.message.reply_text(msg, parse_mode="Markdown")


@_guard
async def cmd_indicator(update, context):
    text  = update.message.text.strip()
    parts = text.split(None, 1)
    cmd   = parts[0].lower().split("@")[0]
    arg   = parts[1] if len(parts) > 1 else ""

    # Parse ngày trước để biết cần cache nào
    try:
        from_d, to_d = _parse_date_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    # Xác định khoảng cần tìm
    if from_d is None:
        # Chưa biết ngày → load cache chính trước, xác định 7 ngày mới nhất
        cache, err = _load_cache_safe()
        if err:
            await update.message.reply_text(
                f"⚠️ Không lấy được dữ liệu từ GitHub.\nLỗi: `{err}`",
                parse_mode="Markdown"
            )
            return
        cache_label = "cache hiện tại"
    else:
        cache, cache_label, err = _find_cache_for_range(from_d, to_d)
        if err:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

    series, display = _get_series_from_cache(cache, cmd)
    if series is None:
        await update.message.reply_text(f"❌ {display}")
        return

    updated_at = cache.get("updated_at", "?")

    # Parse ngày
    try:
        from_d, to_d = _parse_date_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    if from_d is None:
        # Mặc định: 7 ngày mới nhất
        from_d, to_d = _latest_7_days(series)
        if not from_d:
            await update.message.reply_text(
                f"📭 *{display}*: Không có dữ liệu trong cache.\n"
                f"_🔄 Cập nhật lần cuối: {updated_at}_",
                parse_mode="Markdown"
            )
            return
        date_label = f"7 ngày: {_fmt_date(from_d)} → {_fmt_date(to_d)}"
    elif from_d == to_d:
        date_label = _fmt_date(from_d)
    else:
        date_label = f"{_fmt_date(from_d)} → {_fmt_date(to_d)}"

    msg = _format_single(series, display, from_d, to_d, date_label, cmd, updated_at)
    await _send(context, update.effective_chat.id, msg)


@_guard
async def cmd_summary(update, context):
    text  = update.message.text.strip()
    parts = text.split(None, 1)
    arg   = parts[1] if len(parts) > 1 else ""

    try:
        from_d, to_d = _parse_date_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    if from_d is None:
        cache, err = _load_cache_safe()
        if err:
            await update.message.reply_text(
                f"⚠️ Không lấy được dữ liệu từ GitHub.\nLỗi: `{err}`",
                parse_mode="Markdown"
            )
            return
    else:
        cache, _, err = _find_cache_for_range(from_d, to_d)
        if err:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

    raw        = cache.get("raw", {})
    updated_at = cache.get("updated_at", "?")

    if from_d is None:
        all_series = list(raw.get("mia", {}).values())
        all_pts    = [pt for s in all_series for pt in s]
        if all_pts:
            latest = sorted({pt["t"][:10] for pt in all_pts}, reverse=True)
            to_d   = latest[0]
            from_d = latest[min(6, len(latest)-1)]
        else:
            await update.message.reply_text("📭 Không có dữ liệu trong cache.")
            return
        date_label = f"7 ngày: {_fmt_date(from_d)} → {_fmt_date(to_d)}"
    elif from_d == to_d:
        date_label = _fmt_date(from_d)
    else:
        date_label = f"{_fmt_date(from_d)} → {_fmt_date(to_d)}"

    header = (
        f"📊 *TÓM TẮT – {date_label}*\n"
        f"_🔄 Cập nhật lần cuối: {updated_at}_"
    )

    messages = [header]
    mia_items = MIA_MAP_LABELS
    messages.append(_format_summary_section(raw, "🌿 MÍA - NƯỚC MÍA", "mia", mia_items, from_d, to_d))
    mat_items = MAT_MAP_LABELS
    messages.append(_format_summary_section(raw, "🍯 MẬT RỈ - BÙN THÔ", "mat", mat_items, from_d, to_d))
    hoa_items = [(sec, key) for sec, keys in HOA_MAP_KEYS.items() for key in keys]
    messages.append(_format_summary_section(raw, "⚗️ HÓA CHẾ THÔ", "hoa", hoa_items, from_d, to_d))
    nau_items = [(sec, param) for sec, params in NAU_MAP_KEYS.items() for param in params]
    messages.append(_format_summary_section(raw, "🏭 NẤU ĐƯỜNG - LY TÂM THÔ", "nau", nau_items, from_d, to_d))

    for msg in messages:
        if msg.strip():
            await _send(context, update.effective_chat.id, msg)


@_guard
async def cmd_dashboard(update, context):
    """Gửi file dashboard.html để người dùng tải về."""
    import io
    text  = update.message.text.strip()
    parts = text.split(None, 1)
    arg   = parts[1] if len(parts) > 1 else ""

    # Thông báo đang xử lý
    await update.message.reply_text("⏳ Đang tải Dashboard từ GitHub...")

    cache, err = _load_cache_safe()
    if err:
        await update.message.reply_text(
            f"⚠️ Không lấy được cache từ GitHub.\nLỗi: `{err}`",
            parse_mode="Markdown"
        )
        return

    updated_at = cache.get("updated_at", "?")

    # Xác định khoảng ngày để ghi vào caption
    raw = cache.get("raw", {})
    try:
        from_d, to_d = _parse_date_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    if from_d is None:
        all_series = list(raw.get("mia", {}).values())
        all_pts    = [pt for s in all_series for pt in s]
        if all_pts:
            latest = sorted({pt["t"][:10] for pt in all_pts}, reverse=True)
            to_d   = latest[0]
            from_d = latest[min(6, len(latest)-1)]
        else:
            await update.message.reply_text("📭 Không có dữ liệu để tạo Dashboard.")
            return
        date_label = f"7 ngày: {_fmt_date(from_d)} → {_fmt_date(to_d)}"
    elif from_d == to_d:
        date_label = _fmt_date(from_d)
    else:
        date_label = f"{_fmt_date(from_d)} → {_fmt_date(to_d)}"

    # Tải dashboard.html từ GitHub
    try:
        r = requests.get(DASHBOARD_URL, timeout=30)
        r.raise_for_status()
        html_bytes = r.content
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Không tải được Dashboard từ GitHub.\nLỗi: `{e}`",
            parse_mode="Markdown"
        )
        return

    file_obj  = io.BytesIO(html_bytes)
    file_obj.name = "dashboard.html"

    caption = (
        f"📊 *Dashboard Kiểm Soát Dây Chuyền*\n"
        f"🗓 {date_label}\n"
        f"_🔄 Cập nhật lần cuối: {updated_at}_\n\n"
        f"Mở file HTML bằng trình duyệt để xem đầy đủ."
    )

    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=file_obj,
        filename="dashboard.html",
        caption=caption,
        parse_mode="Markdown"
    )


def _is_admin(uid):
    return uid == ALLOWED_CHAT_ID

@_guard
async def cmd_add_user(update, context):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return
    parts = update.message.text.strip().split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Cú pháp: `/add_user <chat_id>`\n"
            "Ví dụ: `/add_user 123456789`",
            parse_mode="Markdown"
        )
        return
    try:
        new_id = int(parts[1].strip())
    except ValueError:
        await update.message.reply_text("❌ Chat ID phải là số nguyên.")
        return

    if new_id in _ALLOWED_USERS:
        await update.message.reply_text(f"ℹ️ User `{new_id}` đã có trong danh sách.", parse_mode="Markdown")
        return

    _ALLOWED_USERS.append(new_id)
    ok = save_allowed_users(_ALLOWED_USERS)
    if ok:
        await update.message.reply_text(
            f"✅ Đã thêm user `{new_id}`.\n"
            f"👥 Danh sách hiện tại: {len(_ALLOWED_USERS)} user.",
            parse_mode="Markdown"
        )
    else:
        _ALLOWED_USERS.remove(new_id)
        await update.message.reply_text("❌ Lỗi lưu danh sách user lên GitHub. Thử lại sau.")


@_guard
async def cmd_remove_user(update, context):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return
    parts = update.message.text.strip().split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Cú pháp: `/remove_user <chat_id>`\n"
            "Ví dụ: `/remove_user 123456789`",
            parse_mode="Markdown"
        )
        return
    try:
        rm_id = int(parts[1].strip())
    except ValueError:
        await update.message.reply_text("❌ Chat ID phải là số nguyên.")
        return

    if rm_id == ALLOWED_CHAT_ID:
        await update.message.reply_text("⛔ Không thể xóa admin chính.")
        return
    if rm_id not in _ALLOWED_USERS:
        await update.message.reply_text(f"ℹ️ User `{rm_id}` không có trong danh sách.", parse_mode="Markdown")
        return

    _ALLOWED_USERS.remove(rm_id)
    ok = save_allowed_users(_ALLOWED_USERS)
    if ok:
        await update.message.reply_text(
            f"✅ Đã xóa user `{rm_id}`.\n"
            f"👥 Còn lại: {len(_ALLOWED_USERS)} user.",
            parse_mode="Markdown"
        )
    else:
        _ALLOWED_USERS.append(rm_id)
        await update.message.reply_text("❌ Lỗi lưu danh sách user lên GitHub. Thử lại sau.")


@_guard
async def cmd_newcache(update, context):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return
    parts = update.message.text.strip().split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Cú pháp: `/newcache DD/MM/YYYY - DD/MM/YYYY`\n"
            "Ví dụ: `/newcache 01/12/2024 - 31/12/2024`",
            parse_mode="Markdown"
        )
        return
    try:
        from_d, to_d = _parse_date_arg(parts[1])
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    if from_d is None or to_d is None:
        await update.message.reply_text("❌ Vui lòng nhập khoảng ngày cụ thể.")
        return

    await update.message.reply_text(
        f"⏳ Đang trigger GitHub Actions fetch dữ liệu `{from_d}` → `{to_d}`...",
        parse_mode="Markdown"
    )

    try:
        url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_BOT_REPO}/actions/workflows/fetch.yml/dispatches"
        payload = {
            "ref": "main",
            "inputs": {
                "from_date": from_d,
                "to_date": to_d
            }
        }
        r = requests.post(url, headers=_gh_headers(), json=payload, timeout=15)
        if r.status_code == 204:
            await update.message.reply_text(
                f"✅ Đã gửi lệnh fetch!\n"
                f"📅 Khoảng: `{from_d}` → `{to_d}`\n"
                f"⏱ GitHub Actions sẽ chạy trong vài giây.\n"
                f"Dùng `/status` để kiểm tra khi hoàn tất.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ GitHub API trả về HTTP {r.status_code}.\n`{r.text[:300]}`",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi gọi GitHub API: `{e}`", parse_mode="Markdown")


@_guard
async def cmd_update(update, context):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return

    await update.message.reply_text("⏳ Đang gửi lệnh cập nhật dữ liệu...")

    try:
        url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_BOT_REPO}/actions/workflows/fetch.yml/dispatches"
        r = requests.post(
            url,
            headers=_gh_headers(),
            json={"ref": "main"},
            timeout=15
        )
        if r.status_code == 204:
            await update.message.reply_text(
                "✅ Đã gửi lệnh cập nhật!\n"
                "⏱ Fetcher đang chạy, thường mất 2–3 phút.\n"
                "Bot sẽ tự thông báo khi hoàn tất.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ GitHub API trả về HTTP {r.status_code}.\n`{r.text[:300]}`",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi gọi GitHub API: `{e}`", parse_mode="Markdown")


# ========================
# BUILD APP
# ========================
def build_bot_app():
    from telegram.ext import Application, CommandHandler

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("summary",     cmd_summary))
    app.add_handler(CommandHandler("dashboard",   cmd_dashboard))
    app.add_handler(CommandHandler("add_user",    cmd_add_user))
    app.add_handler(CommandHandler("remove_user", cmd_remove_user))
    app.add_handler(CommandHandler("newcache",    cmd_newcache))
    app.add_handler(CommandHandler("update",      cmd_update))

    for cmd in COMMAND_MAP:
        cmd_name = cmd.lstrip("/")
        app.add_handler(CommandHandler(cmd_name, cmd_indicator))

    return app


async def _register_commands(app):
    """Đăng ký toàn bộ lệnh với Telegram để hiện gợi ý khi user gõ /"""
    from telegram import BotCommand
    commands = []

    # Lệnh chính — luôn ưu tiên đứng đầu
    commands += [
        BotCommand("help",        "Danh sách lệnh"),
        BotCommand("status",      "Trạng thái hiện tại của bot"),
        BotCommand("summary",     "Tóm tắt tất cả thông số [ngày]"),
        BotCommand("dashboard",   "Tải file Dashboard HTML [ngày]"),
        BotCommand("add_user",    "Thêm người dùng (admin)"),
        BotCommand("remove_user", "Xóa người dùng (admin)"),
        BotCommand("newcache",    "Fetch dữ liệu cũ (admin)"),
        BotCommand("update",      "Cập nhật dữ liệu ngay (admin)"),
    ]

    # Lệnh indicator
    for cmd, mapping in sorted(COMMAND_MAP.items()):
        cmd_name = cmd.lstrip("/")
        desc = mapping[3] if len(mapping) == 4 else mapping[2]
        commands.append(BotCommand(cmd_name[:32], desc[:256]))

    # Telegram giới hạn 100 lệnh
    if len(commands) > 100:
        print(f"⚠️ {len(commands)} lệnh, cắt còn 100...")
        commands = commands[:100]

    await app.bot.set_my_commands(commands)
    print(f"✅ Đã đăng ký {len(commands)} lệnh với Telegram")


# ========================
# MAIN
# ========================
import asyncio

async def _main_async():
    print("🤖 Telegram Bot đang khởi động...")
    bot_app = build_bot_app()

    await bot_app.initialize()
    await _register_commands(bot_app)
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    print("✅ Bot đang chạy...")

    # Giữ bot chạy mãi (tương thích python-telegram-bot v20+)
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(_main_async())
