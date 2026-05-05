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

BOT_START_TIME = now_vn()  # Ghi nhận lúc bot khởi động

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/minht3902/sugarmama_bot/main"
CACHE_URL       = f"{GITHUB_RAW_BASE}/cache.json"
DASHBOARD_URL   = f"{GITHUB_RAW_BASE}/dashboard.html"

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
# CACHE
# ========================
def _load_cache():
    """Fetch cache.json từ GitHub raw URL."""
    try:
        r = requests.get(CACHE_URL, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return None, str(e)

def _load_cache_safe():
    """Trả về (cache_dict, error_str). error_str=None nếu OK."""
    try:
        r = requests.get(CACHE_URL, timeout=20)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

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

    # Hỗ trợ cả "01/04-10/04" và "01/04 - 10/04"
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
        if update.effective_chat.id != ALLOWED_CHAT_ID:
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
        "`/status`  → trạng thái bot & lần cập nhật cuối"
    )
    await _send(context, update.effective_chat.id, msg)


@_guard
async def cmd_status(update, context):
    now = now_vn()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # Tính uptime và countdown 72h JustRunMyApp
    uptime_delta   = now - BOT_START_TIME
    uptime_total_s = int(uptime_delta.total_seconds())
    uptime_h       = uptime_total_s // 3600
    uptime_m       = (uptime_total_s % 3600) // 60

    limit_hours    = 72
    remaining_s    = max(0, limit_hours * 3600 - uptime_total_s)
    remain_h       = remaining_s // 3600
    remain_m       = (remaining_s % 3600) // 60

    start_str      = BOT_START_TIME.strftime("%Y-%m-%d %H:%M:%S")
    deadline_str   = (BOT_START_TIME + timedelta(hours=limit_hours)).strftime("%Y-%m-%d %H:%M:%S")

    if remaining_s <= 0:
        countdown_line = "⛔ *Đã hết 72h — cần reset ngay trên JustRunMyApp!*"
    elif remaining_s <= 3600:
        countdown_line = f"🚨 Còn *{remain_h}h {remain_m:02d}m* — Sắp hết, cần reset sớm!"
    else:
        countdown_line = f"⏳ Còn *{remain_h}h {remain_m:02d}m* trước khi cần reset"

    # Thông tin cache
    cache, err = _load_cache_safe()
    if err:
        cache_line = f"⚠️ Cache: Không đọc được (`{err}`)"
    else:
        cache_line = (
            f"🔄 Dữ liệu cập nhật lúc: `{cache.get('updated_at', 'N/A')}`\n"
            f"📅 Khoảng dữ liệu: `{cache.get('from_date')}` → `{cache.get('to_date')}`"
        )

    msg = (
        f"*🤖 Bot Status*\n"
        f"🟢 Online — `{now_str}` (GMT+7)\n\n"
        f"*⏱ JustRunMyApp FreeAppTimer*\n"
        f"🚀 Khởi động: `{start_str}`\n"
        f"🔴 Deadline:  `{deadline_str}`\n"
        f"🏃 Uptime: {uptime_h}h {uptime_m:02d}m\n"
        f"{countdown_line}\n\n"
        f"{cache_line}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


@_guard
async def cmd_indicator(update, context):
    text  = update.message.text.strip()
    parts = text.split(None, 1)
    cmd   = parts[0].lower().split("@")[0]
    arg   = parts[1] if len(parts) > 1 else ""

    cache, err = _load_cache_safe()
    if err:
        await update.message.reply_text(
            f"⚠️ Không lấy được dữ liệu từ GitHub.\nLỗi: `{err}`",
            parse_mode="Markdown"
        )
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

    cache, err = _load_cache_safe()
    if err:
        await update.message.reply_text(
            f"⚠️ Không lấy được dữ liệu từ GitHub.\nLỗi: `{err}`",
            parse_mode="Markdown"
        )
        return

    raw        = cache.get("raw", {})
    updated_at = cache.get("updated_at", "?")

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


# ========================
# BUILD APP
# ========================
def build_bot_app():
    from telegram.ext import Application, CommandHandler

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("summary",   cmd_summary))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))

    for cmd in COMMAND_MAP:
        cmd_name = cmd.lstrip("/")
        app.add_handler(CommandHandler(cmd_name, cmd_indicator))

    return app


# ========================
# MAIN
# ========================
if __name__ == "__main__":
    print("🤖 Telegram Bot đang khởi động...")
    bot_app = build_bot_app()
    bot_app.run_polling(drop_pending_updates=True)
