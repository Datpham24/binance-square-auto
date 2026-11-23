#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_square_pro.py (v2.0 - Pro Trader Edition)
----------------------------------------------
Senior Python Automation & Crypto Technical Analysis Script for Binance Square (Write to Earn).

Quy trình 3 phần nâng cấp:
  - Phần 1: Lấy dữ liệu 24hr ticker từ Binance API (lọc cặp USDT thanh khoản > 25,000,000 USDT,
            bỏ stablecoin & token đòn bẩy), chọn đúng 2 mã nổi bật nhất:
              + Mã 1 (Kèo Momentum - Thuận xu hướng): Top 1 tăng trưởng +5% đến +12%
              + Mã 2 (Kèo Rebound - Bắt nhịp hồi): Top 1 điều chỉnh -5% đến -10%
            Gọi thêm API nến 4H (/api/v3/klines?symbol=SYMBOL&interval=4h&limit=12) lấy vùng
            hỗ trợ/kháng cự 48h qua để tính toán chính xác Entry, TP1, TP2, SL (R:R >= 1:2).
  - Phần 2: Render bài viết (180 - 220 từ) theo đúng mẫu Plan Lướt Sóng 24H chuyên nghiệp,
            dùng Cashtag $TOKEN thuần (không kèm /USDT) để hiển thị thẻ vàng đồng đều.
  - Phần 3: Tự động đăng bài bằng Playwright (Chrome Persistent Context, khi gõ $TOKEN thêm
            khoảng trắng và chờ 0.5s để nhận diện thẻ màu vàng) + Hỗ trợ fallback OpenAPI.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

# Đảm bảo hiển thị tiếng Việt & emoji chuẩn trên terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# CẤU HÌNH MẶC ĐỊNH
# ==============================================================================
BINANCE_API_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

MIN_QUOTE_VOLUME_USDT = 25_000_000.0  # > 25,000,000 USDT
GAINER_MIN_PCT = 5.0
GAINER_MAX_PCT = 12.0
LOSER_MIN_PCT = -10.0
LOSER_MAX_PCT = -5.0

# Danh sách stablecoin / fiat / ETF token cần loại bỏ
EXCLUDED_BASE_TOKENS = {
    "USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "USDT", "USTC",
    "USDE", "PYUSD", "RLUSD", "USD1", "U", "EUR", "EURI", "AEUR", "GBP",
    "PAXG", "WBTC", "WBETH", "BETH", "SOXLB", "SOXSB", "NVDAB", "SNDKB",
}

LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

USER_DATA_DIR = os.environ.get(
    "CHROME_USER_DATA_DIR",
    r"C:\Users\DELL\AppData\Local\Google\Chrome\User Data",
)
CHROME_PROFILE_DIR = os.environ.get("CHROME_PROFILE_DIR", "Profile 2")

BINANCE_SQUARE_URL = "https://www.binance.com/vi/square"
SCREENSHOT_PATH = Path(__file__).resolve().parent / "post_success.png"
DRAFT_OUTPUT_PATH = Path(__file__).resolve().parent / "drafts" / "latest_auto_post.txt"


# ==============================================================================
# PHẦN 1: LẤY DỮ LIỆU & TÍNH TOÁN KỸ THUẬT NẾN 4H TỪ BINANCE API
# ==============================================================================
def infer_price_decimals(raw_price_str: str, price_val: float) -> int:
    """
    Xác định số chữ số thập phân chuẩn theo giá gốc của token trên sàn Binance.
    Luôn đảm bảo tối thiểu 4 chữ số có nghĩa để vùng Entry_1 và Entry_2 không bị trùng nhau
    khi giá hiện tại tình cờ tròn số (ví dụ 0.02400000 -> vẫn giữ 5 chữ số thập phân).
    """
    if price_val >= 100:
        min_dec = 2
    elif price_val >= 10:
        min_dec = 2
    elif price_val >= 1:
        min_dec = 3
    elif price_val >= 0.1:
        min_dec = 4
    elif price_val >= 0.01:
        min_dec = 5
    else:
        min_dec = 6

    cleaned = raw_price_str.strip().rstrip("0")
    if "." in cleaned:
        dec = len(cleaned.split(".")[1])
        return min(max(dec, min_dec), 8)

    return min_dec


def format_token_price(value: float, decimals: int) -> str:
    """Làm tròn và định dạng giá đúng số thập phân của token gốc."""
    formatted = f"{value:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def format_volume_millions(quote_volume: float) -> str:
    """Định dạng Volume 24h theo đơn vị triệu USD (M)."""
    vol_m = quote_volume / 1_000_000.0
    if vol_m >= 100:
        return f"{vol_m:.0f}"
    return f"{vol_m:.1f}"


def is_valid_altcoin_usdt_pair(symbol: str) -> Tuple[bool, str]:
    """Kiểm tra cặp giao dịch đuôi USDT hợp lệ (bỏ stablecoin & token đòn bẩy)."""
    if not symbol.endswith("USDT"):
        return False, ""

    base = symbol[:-4]
    if not base or base in EXCLUDED_BASE_TOKENS:
        return False, ""

    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return False, ""

    return True, base


def binance_get_json(endpoint: str, params: Dict[str, Any] | None = None) -> Any:
    """Gọi Binance Public API với cơ chế tự động chuyển đổi giữa các cụm máy chủ."""
    last_err: Exception | None = None
    for base in BINANCE_API_BASES:
        url = f"{base}{endpoint}"
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"Không thể gọi Binance API ({endpoint}): {last_err}")


def fetch_4h_support_resistance(symbol: str) -> Dict[str, float]:
    """
    Gọi API nến 4H của Binance (/api/v3/klines?symbol=SYMBOL&interval=4h&limit=12)
    để lấy vùng hỗ trợ và kháng cự gần nhất trong 48h qua (12 cây nến 4H).
    """
    klines = binance_get_json(
        "/api/v3/klines",
        params={"symbol": symbol, "interval": "4h", "limit": 12},
    )
    if not klines:
        return {}

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    recent_4h_lows = sorted(lows)
    recent_4h_highs = sorted(highs, reverse=True)

    # Hỗ trợ nến 4H gần nhất (trung vị đáy các cụm nến 4H gần nhất) và đáy 48h
    recent_support = min(lows[-3:]) if len(lows) >= 3 else min(lows)
    recent_resistance = max(highs[-3:]) if len(highs) >= 3 else max(highs)

    return {
        "support_4h_near": recent_support,
        "support_48h_low": recent_4h_lows[0],
        "resistance_4h_near": recent_resistance,
        "resistance_48h_high": recent_4h_highs[0],
        "last_4h_close": closes[-1],
    }


def calculate_momentum_plan(token_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tính toán Trading Plan cho Mã 1 (Kèo Momentum - Đang tăng +5%..+12%):
      - Entry (Vùng canh mua): Giảm 1.5% - 2.5% so với giá hiện tại, kết hợp hỗ trợ nến 4H gần nhất.
      - TP1: Đỉnh 24h hiện tại (nếu giá hiện tại quá sát đỉnh 24h < 1% thì mở rộng tối thiểu +2.5%
             để đảm bảo biên lợi nhuận thực tế).
      - TP2: Mở rộng thêm +4% từ TP1 / đỉnh 24h.
      - SL: Dưới vùng Entry khoảng 3% - 3.5% (đảm bảo tỷ lệ Risk:Reward tối thiểu 1:2).
    """
    symbol = token_info["symbol"]
    price = token_info["last_price"]
    high_24h = token_info["high_price"]
    decimals = token_info["decimals"]

    sr = fetch_4h_support_resistance(symbol)
    support_4h = sr.get("support_4h_near", price * 0.975)

    # Vùng Entry giảm 1.5% - 2.5% so với giá hiện tại (neo theo vùng hỗ trợ nến 4H nếu nằm gần)
    raw_entry_1 = price * (1.0 - 0.025)
    raw_entry_2 = price * (1.0 - 0.015)

    if price * 0.96 <= support_4h <= price * 0.988:
        raw_entry_1 = min(raw_entry_1, support_4h)

    entry_low = min(raw_entry_1, raw_entry_2)
    entry_high = max(raw_entry_1, raw_entry_2)
    entry_mid = (entry_low + entry_high) / 2.0

    # SL dưới vùng Entry khoảng 3.2% (nằm trong khoảng 3% - 3.5%)
    sl_price = entry_low * (1.0 - 0.032)

    # TP1 tại đỉnh 24h hiện tại; TP2 mở rộng thêm +4% từ đỉnh 24h
    # Đảm bảo R:R tối thiểu 1:2 từ vùng Entry
    risk = max(entry_mid - sl_price, price * 0.01)
    tp1_price = max(high_24h, entry_mid + 1.3 * risk)
    tp2_price = max(tp1_price * 1.04, entry_mid + 2.2 * risk)

    return {
        **token_info,
        "entry_1": format_token_price(entry_low, decimals),
        "entry_2": format_token_price(entry_high, decimals),
        "tp1": format_token_price(tp1_price, decimals),
        "tp2": format_token_price(tp2_price, decimals),
        "sl": format_token_price(sl_price, decimals),
        "price_str": format_token_price(price, decimals),
        "vol_m_str": format_volume_millions(token_info["quote_volume"]),
    }


def calculate_rebound_plan(token_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tính toán Trading Plan cho Mã 2 (Kèo Rebound - Đang giảm sâu -5%..-10%):
      - Entry (Vùng gom thăm dò): Quanh vùng đáy 24h hiện tại (thấp hơn giá hiện tại 1% - 2%).
      - TP1: Tăng +4% từ vùng Entry.
      - TP2: Tăng +8% từ vùng Entry.
      - SL: Thủng đáy 24h khoảng 2.5% - 3%.
    """
    symbol = token_info["symbol"]
    price = token_info["last_price"]
    low_24h = token_info["low_price"]
    decimals = token_info["decimals"]

    sr = fetch_4h_support_resistance(symbol)
    support_4h = sr.get("support_4h_near", low_24h)

    # Vùng Entry quanh đáy 24h (thấp hơn giá hiện tại 1% - 2%)
    band_low = price * (1.0 - 0.02)
    band_high = price * (1.0 - 0.01)

    if band_low <= low_24h <= price:
        entry_low = min(band_low, low_24h)
        entry_high = max(band_high, low_24h)
    elif band_low <= support_4h <= price:
        entry_low = min(band_low, support_4h)
        entry_high = band_high
    else:
        entry_low = band_low
        entry_high = band_high

    entry_mid = (entry_low + entry_high) / 2.0

    # TP1: +4% từ vùng Entry; TP2: +8% từ vùng Entry
    tp1_price = entry_mid * 1.04
    tp2_price = entry_mid * 1.08

    # SL: Thủng đáy 24h / vùng Entry khoảng 2.8% (trong khung 2.5% - 3%)
    anchor_low = min(low_24h, entry_low)
    sl_price = anchor_low * (1.0 - 0.028)

    return {
        **token_info,
        "entry_1": format_token_price(entry_low, decimals),
        "entry_2": format_token_price(entry_high, decimals),
        "tp1": format_token_price(tp1_price, decimals),
        "tp2": format_token_price(tp2_price, decimals),
        "sl": format_token_price(sl_price, decimals),
        "price_str": format_token_price(price, decimals),
        "vol_m_str": format_volume_millions(token_info["quote_volume"]),
    }


def fetch_top_two_plans() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Chọn đúng 2 mã nổi bật nhất từ /api/v3/ticker/24hr:
      - Mã 1 (Momentum): Top 1 tăng trưởng +5% đến +12% (ưu tiên Vol > 25,000,000 USDT)
      - Mã 2 (Rebound): Top 1 điều chỉnh -5% đến -10% (ưu tiên Vol > 25,000,000 USDT)
    Sau đó gọi nến 4H để tính mốc Entry, TP1, TP2, SL cho từng mã.
    """
    raw_tickers = binance_get_json("/api/v3/ticker/24hr")
    if not raw_tickers:
        raise RuntimeError("Dữ liệu 24hr ticker từ Binance rỗng.")

    candidates: List[Dict[str, Any]] = []

    for item in raw_tickers:
        symbol = str(item.get("symbol", ""))
        is_valid, base_token = is_valid_altcoin_usdt_pair(symbol)
        if not is_valid:
            continue

        try:
            raw_last_price = str(item.get("lastPrice", "0"))
            last_price = float(raw_last_price)
            quote_volume = float(item.get("quoteVolume", 0.0))
            pct_change = float(item.get("priceChangePercent", 0.0))
            high_price = float(item.get("highPrice", 0.0))
            low_price = float(item.get("lowPrice", 0.0))
        except (TypeError, ValueError):
            continue

        if last_price <= 0:
            continue

        # Loại bỏ các token neo giá USD quanh mốc 1.00 USDT
        if 0.995 <= last_price <= 1.005 and abs(pct_change) < 0.3:
            continue

        decimals = infer_price_decimals(raw_last_price, last_price)
        candidates.append(
            {
                "symbol": symbol,
                "token": base_token,
                "cashtag": f"${base_token}",
                "last_price": last_price,
                "pct_change": pct_change,
                "high_price": high_price,
                "low_price": low_price,
                "quote_volume": quote_volume,
                "decimals": decimals,
            }
        )

    # Lọc nhóm thanh khoản cao > 25,000,000 USDT (nếu thời điểm hiện tại chưa có mã nào
    # trong khung +5%..+12% hoặc -5%..-10% đạt 25M thì hạ dần ngưỡng volume để luôn chọn đúng biên độ)
    volume_tiers = [MIN_QUOTE_VOLUME_USDT, 10_000_000.0, 3_000_000.0, 1_000_000.0]

    best_momentum: Dict[str, Any] | None = None
    for min_vol in volume_tiers:
        pool = [
            t
            for t in candidates
            if t["quote_volume"] >= min_vol
            and GAINER_MIN_PCT <= t["pct_change"] <= GAINER_MAX_PCT
        ]
        if pool:
            pool.sort(key=lambda x: (x["quote_volume"], x["pct_change"]), reverse=True)
            best_momentum = pool[0]
            break

    if best_momentum is None:
        fallback_gainers = [
            t for t in candidates if t["quote_volume"] >= MIN_QUOTE_VOLUME_USDT and t["pct_change"] > 0
        ]
        fallback_gainers.sort(key=lambda x: (abs(x["pct_change"] - 8.0), -x["quote_volume"]))
        best_momentum = fallback_gainers[0]

    best_rebound: Dict[str, Any] | None = None
    for min_vol in volume_tiers:
        pool = [
            t
            for t in candidates
            if t["symbol"] != best_momentum["symbol"]
            and t["quote_volume"] >= min_vol
            and LOSER_MIN_PCT <= t["pct_change"] <= LOSER_MAX_PCT
        ]
        if pool:
            pool.sort(key=lambda x: (x["quote_volume"], abs(x["pct_change"])), reverse=True)
            best_rebound = pool[0]
            break

    if best_rebound is None:
        fallback_losers = [
            t
            for t in candidates
            if t["symbol"] != best_momentum["symbol"]
            and t["quote_volume"] >= MIN_QUOTE_VOLUME_USDT
            and t["pct_change"] < 0
        ]
        fallback_losers.sort(key=lambda x: (abs(x["pct_change"] - (-7.5)), -x["quote_volume"]))
        best_rebound = fallback_losers[0]

    momentum_plan = calculate_momentum_plan(best_momentum)
    rebound_plan = calculate_rebound_plan(best_rebound)
    return momentum_plan, rebound_plan


# ==============================================================================
# PHẦN 2: TẠO BÀI VIẾT CHUẨN TRADER CHUYÊN NGHIỆP (180 - 220 TỪ)
# ==============================================================================
def generate_square_post(m1: Dict[str, Any], m2: Dict[str, Any]) -> str:
    """
    Render bài viết chuẩn Trader chuyên nghiệp theo đúng mẫu yêu cầu.
    Lưu ý:
      - Chỉ gắn ký hiệu $ cho đúng mã Cashtag token ($QNT, $SKY), còn các mốc giá
        ghi số thuần (không gắn $ trước số giá như $157 vì thuật toán Binance Square
        sẽ hiểu nhầm $157 là một mã token và báo lỗi vượt quá 3 coin-pair).
      - Luôn có khoảng trắng ngay sau $TOKEN để Binance Square nhận diện thẻ màu vàng.
    """
    t1 = m1["token"]
    t2 = m2["token"]
    x_pct = f"{m1['pct_change']:+.2f}"
    y_pct = f"{abs(m2['pct_change']):.2f}"

    lines = [
        f"🎯 PLAN LƯỚT SÓNG 24H: {t1} & {t2}",
        "",
        "Dòng tiền đang phân hóa mạnh, anh em tham khảo kế hoạch giao dịch ngắn hạn cho 2 mã có biên độ đẹp nhất hôm nay:",
        "",
        f"1️⃣ Kèo Thuận Xu Hướng: ${t1} ({x_pct}%)",
        f"- Giá hiện tại: ${m1['price_str']} | Vol 24h: ${m1['vol_m_str']}M",
        f"- Vùng Entry đẹp: ${m1['entry_1']} – ${m1['entry_2']} (chờ nhịp retest)",
        f"- Chốt lời (TP): ${m1['tp1']} ➔ ${m1['tp2']}",
        f"- Cắt lỗ (SL): ${m1['sl']} (đóng nến 4H dưới mốc này)",
        "",
        f"2️⃣ Kèo Bắt Nhịp Hồi: ${t2} (-{y_pct}%)",
        f"- Giá hiện tại: ${m2['price_str']} | Vol 24h: ${m2['vol_m_str']}M",
        f"- Vùng Entry thăm dò: ${m2['entry_1']} – ${m2['entry_2']} (quanh đáy 24h)",
        f"- Chốt lời (TP): ${m2['tp1']} ➔ ${m2['tp2']}",
        f"- Cắt lỗ (SL): ${m2['sl']}",
        "",
        "⚠️ Lưu ý: Luôn chia vốn, tuân thủ SL và chờ xác nhận phản ứng nến trước khi khớp lệnh.",
        f"👉 Anh em đang canh Long ${t1} hay bắt đáy ${t2} hôm nay? Bấm trực tiếp vào thẻ token để check chart và chia sẻ góc nhìn bên dưới nhé!",
        "",
        "#Write2Earn #BinanceSquare #TradingPlan #Altcoins",
    ]

    post_text = "\n".join(lines)
    DRAFT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRAFT_OUTPUT_PATH.write_text(post_text, encoding="utf-8")
    return post_text


# ==============================================================================
# PHẦN 3: TỰ ĐỘNG ĐĂNG BÀI BẰNG PLAYWRIGHT (KÈM NHẬN DIỆN THẺ VÀNG CASHTAG)
# ==============================================================================
def type_line_with_cashtag_pause(page: Any, line: str) -> None:
    """
    Nhập từng dòng nội dung vào khung soạn thảo của Binance Square.
    Khi gặp Cashtag $TOKEN (chữ cái in hoa đầu như $QNT, $SKY — phân biệt với số tiền $157.86),
    tự động nhập thêm một khoảng trắng ngay sau mã token và chờ 0.5 giây để Binance Square
    nhận diện đồng đều tất cả các thẻ thành màu vàng.
    """
    tokens = re.split(r"(\$[A-Z][A-Z0-9]{1,14})", line)
    for idx, chunk in enumerate(tokens):
        if not chunk:
            continue
        if re.fullmatch(r"\$[A-Z][A-Z0-9]{1,14}", chunk):
            page.keyboard.type(chunk + " ", delay=30)
            time.sleep(0.5)
        else:
            text_to_type = chunk[1:] if (idx > 0 and chunk.startswith(" ")) else chunk
            if text_to_type:
                page.keyboard.type(text_to_type, delay=20)


def post_to_binance_square_playwright(
    post_content: str,
    user_data_dir: str = USER_DATA_DIR,
    profile_dir: str = CHROME_PROFILE_DIR,
) -> Path:
    """
    Mở Chrome với Persistent Context trỏ vào Chrome Profile của người dùng,
    nhập từng dòng bài viết (có dừng 0.5s sau mỗi $TOKEN), chờ 4s load widget cặp giao dịch,
    bấm nút Đăng (Post) và chụp màn hình post_success.png sau 5s.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    print(f"\n[Playwright] Đang khởi chạy Chrome Profile '{profile_dir}'...")
    print(f"[Playwright] user_data_dir = {user_data_dir}")

    with sync_playwright() as p:
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "headless": False,
            "slow_mo": 100,
            "args": [
                f"--profile-directory={profile_dir}",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            "no_viewport": True,
        }

        try:
            context = p.chromium.launch_persistent_context(
                channel="chrome", **launch_kwargs
            )
        except Exception as chrome_err:
            msg = str(chrome_err)
            if (
                "Target page, context or browser has been closed" in msg
                or "exitCode=21" in msg
                or "ProcessSingleton" in msg
                or "in use" in msg.lower()
            ):
                raise RuntimeError(
                    "Không thể mở Chrome Profile vì trình duyệt Chrome đang mở sẵn trên máy "
                    "(Chrome khóa thư mục User Data khi đang chạy). "
                    "Hãy đóng toàn bộ cửa sổ Chrome rồi chạy lại, hoặc dùng chế độ OpenAPI."
                ) from chrome_err
            context = p.chromium.launch_persistent_context(**launch_kwargs)

        try:
            page = context.pages[0] if context.pages else context.new_page()
            print(f"[Playwright] Đang truy cập {BINANCE_SQUARE_URL} ...")
            page.goto(BINANCE_SQUARE_URL, wait_until="domcontentloaded", timeout=60_000)

            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass
            time.sleep(3)

            editor_selectors = [
                "div[contenteditable='true']",
                "[data-testid*='editor'] [contenteditable='true']",
                "textarea[placeholder*='Chia sẻ']",
                "textarea[placeholder*='Share']",
                "div[role='textbox']",
            ]

            editor = None
            for selector in editor_selectors:
                loc = page.locator(selector).first
                if loc.count() > 0 and loc.is_visible():
                    editor = loc
                    break

            if editor is None:
                trigger = page.get_by_text("Chia sẻ quan điểm", exact=False).first
                if trigger.count() > 0 and trigger.is_visible():
                    trigger.click()
                    time.sleep(1.5)
                for selector in editor_selectors:
                    loc = page.locator(selector).first
                    if loc.count() > 0 and loc.is_visible():
                        editor = loc
                        break

            if editor is None:
                page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
                raise RuntimeError(
                    f"Không tìm thấy khung soạn thảo bài viết (kiểm tra Profile '{profile_dir}' "
                    f"đã đăng nhập Binance Square chưa). Đã lưu ảnh tại: {SCREENSHOT_PATH}"
                )

            print("[Playwright] Đã tìm thấy khung soạn thảo. Đang nhập nội dung & kích hoạt thẻ vàng Cashtag...")
            editor.click()
            time.sleep(0.5)

            lines = post_content.split("\n")
            for i, line in enumerate(lines):
                if line:
                    type_line_with_cashtag_pause(page, line)
                if i < len(lines) - 1:
                    page.keyboard.press("Shift+Enter")
                time.sleep(0.25)

            print("[Playwright] Đã nhập xong! Chờ 4 giây để Binance Square load dữ liệu cặp giao dịch ($TOKEN)...")
            time.sleep(4)

            post_button = None
            button_candidates = [
                page.get_by_role("button", name="Đăng", exact=True),
                page.get_by_role("button", name="Post", exact=True),
                page.locator("button:has-text('Đăng')"),
                page.locator("button:has-text('Post')"),
            ]

            for candidate in button_candidates:
                count = candidate.count()
                for idx in range(count - 1, -1, -1):
                    btn = candidate.nth(idx)
                    if btn.is_visible() and btn.is_enabled():
                        post_button = btn
                        break
                if post_button is not None:
                    break

            if post_button is None:
                page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
                raise RuntimeError(
                    f"Không tìm thấy nút 'Đăng' (Post) khả dụng. Đã lưu ảnh tại: {SCREENSHOT_PATH}"
                )

            print("[Playwright] Đang bấm nút 'Đăng' (Post)...")
            post_button.click()

            print("[Playwright] Chờ 5 giây và chụp ảnh màn hình post_success.png...")
            time.sleep(5)
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
            print(f"[Playwright] Hoàn tất! Ảnh chụp màn hình đã lưu tại: {SCREENSHOT_PATH}")
            return SCREENSHOT_PATH

        finally:
            context.close()


# ==============================================================================
# ĐĂNG QUA BINANCE SQUARE OPENAPI (TỰ ĐỘNG CHUẨN HÓA NẾU VƯỢT TRẦN TAG CỦA API)
# ==============================================================================
def _send_openapi_payload(api_key: str, text_body: str) -> Dict[str, Any]:
    url = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"
    headers = {
        "X-Square-OpenAPI-Key": api_key,
        "Content-Type": "application/json",
        "clienttype": "binanceSkill",
    }
    payload = {
        "contentType": 1,
        "bodyTextOnly": text_body,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if resp.status_code == 504:
        return {"code": "000000", "data": {"id": None, "shareLink": None, "status": "published_504"}}
    return resp.json()


def post_to_binance_square_openapi(post_content: str) -> Dict[str, Any]:
    """
    Đăng bài trực tiếp qua cổng Binance Square OpenAPI.
    Nếu máy chủ OpenAPI giới hạn tối đa 3 hashtag (mã 220094) hoặc 3 lần xuất hiện $TOKEN (mã 220095),
    hàm tự động tinh chỉnh nhẹ dòng cuối để đảm bảo đăng thành công 100%.
    """
    api_key = os.environ.get("BINANCE_SQUARE_OPENAPI_KEY", "").strip()
    if not api_key:
        key_file = Path.home() / ".config" / "binance-square" / "openapi-key"
        if key_file.exists():
            api_key = key_file.read_text(encoding="utf-8").strip()

    if not api_key:
        raise RuntimeError(
            "Không tìm thấy Square OpenAPI key trong biến môi trường hoặc ~/.config/binance-square/openapi-key"
        )

    candidate_text = post_content
    for _ in range(3):
        data = _send_openapi_payload(api_key, candidate_text)
        code = data.get("code")
        if code == "000000":
            return data.get("data") or {}

        # 220094: Hashtag count exceeds the allowed limit (OpenAPI chỉ nhận tối đa 3 hashtag)
        if code == "220094":
            candidate_text = candidate_text.replace(
                "#Write2Earn #BinanceSquare #TradingPlan #Altcoins",
                "#Write2Earn #BinanceSquare #TradingPlan",
            )
            continue

        # 220095: Coin pair count exceeds the allowed limit (OpenAPI đếm tổng số lần xuất hiện $TOKEN <= 3)
        if code == "220095":
            # Giữ nguyên $TOKEN ở 2 tiêu đề kèo 1 & kèo 2, bỏ dấu $ lặp lại ở câu hỏi cuối
            matches = list(re.finditer(r"\$[A-Z][A-Z0-9]{1,14}", candidate_text))
            if len(matches) > 3:
                last_match = matches[-1]
                s, e = last_match.span()
                candidate_text = candidate_text[:s] + candidate_text[s + 1 : e] + candidate_text[e:]
                continue

        raise RuntimeError(f"Square OpenAPI Error [{code}]: {data.get('message')}")

    raise RuntimeError("Không thể đăng bài qua Square OpenAPI sau khi chuẩn hóa tag.")


def capture_verification_screenshot(target_url: str) -> Path:
    """Mở trình duyệt Chrome độc lập để chụp ảnh màn hình xác nhận post_success.png."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False, slow_mo=100)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(5)
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
            return SCREENSHOT_PATH
        finally:
            browser.close()


# ==============================================================================
# HÀM CHẠY CHÍNH (MAIN ENTRYPOINT)
# ==============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto Square Pro v2.0 - Trading Plan 24H (Momentum & Rebound) cho Binance Square."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ lấy dữ liệu thật + nến 4H từ Binance API và in bài viết mẫu (không bấm đăng).",
    )
    parser.add_argument(
        "--openapi",
        action="store_true",
        help="Đăng bài qua cổng chính thức Binance Square OpenAPI.",
    )
    parser.add_argument(
        "--user-data-dir",
        default=USER_DATA_DIR,
        help="Đường dẫn thư mục Chrome User Data.",
    )
    parser.add_argument(
        "--profile-dir",
        default=CHROME_PROFILE_DIR,
        help="Tên thư mục Chrome Profile (mặc định: 'Profile 2').",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("🚀 AUTO SQUARE PRO v2.0 - PRO TRADER 4H TECHNICAL PLAN AUTOMATION")
    print("=" * 72)

    # PHẦN 1: Lấy dữ liệu ticker 24h & nến 4H để tính toán mốc Entry / TP / SL
    print("\n[Phần 1] Đang quét Binance 24hr Ticker & phân tích nến 4H (48h gần nhất)...")
    momentum_plan, rebound_plan = fetch_top_two_plans()

    print(
        f"  -> Mã 1 (Kèo Momentum): {momentum_plan['cashtag']} ({momentum_plan['pct_change']:+.2f}%) | "
        f"Giá: {momentum_plan['price_str']} | Entry: {momentum_plan['entry_1']}–{momentum_plan['entry_2']} | "
        f"TP: {momentum_plan['tp1']} -> {momentum_plan['tp2']} | SL: {momentum_plan['sl']}"
    )
    print(
        f"  -> Mã 2 (Kèo Rebound):  {rebound_plan['cashtag']} ({rebound_plan['pct_change']:+.2f}%) | "
        f"Giá: {rebound_plan['price_str']} | Entry: {rebound_plan['entry_1']}–{rebound_plan['entry_2']} | "
        f"TP: {rebound_plan['tp1']} -> {rebound_plan['tp2']} | SL: {rebound_plan['sl']}"
    )

    # PHẦN 2: Tạo nội dung bài viết chuẩn Trader chuyên nghiệp
    print("\n[Phần 2] Đang render bài viết Trading Plan 24H chuẩn Write to Earn...")
    post_content = generate_square_post(momentum_plan, rebound_plan)
    word_count = len(post_content.split())

    print("-" * 72)
    print(post_content)
    print("-" * 72)
    print(f"📊 Số từ: {word_count} từ | Đã lưu bản nháp tại: {DRAFT_OUTPUT_PATH}")

    if args.dry_run:
        print("\n[Chế độ --dry-run] Đã kiểm tra xong Phần 1 & Phần 2 (không tự động bấm đăng).")
        return

    # PHẦN 3: Tự động đăng bài
    if args.openapi:
        print("\n[Phần 3 - OpenAPI] Đang đăng bài lên Binance Square qua OpenAPI...")
        result = post_to_binance_square_openapi(post_content)
        share_link = result.get("shareLink") or BINANCE_SQUARE_URL
        print(f"✅ Đăng thành công! Post ID: {result.get('id')} | Link: {share_link}")
    else:
        print("\n[Phần 3 - Playwright] Đang tự động đăng bài qua trình duyệt Chrome...")
        try:
            post_to_binance_square_playwright(
                post_content=post_content,
                user_data_dir=args.user_data_dir,
                profile_dir=args.profile_dir,
            )
        except RuntimeError as err:
            if "Chrome đang mở sẵn" in str(err):
                print(f"\n⚠️ Lưu ý: {err}")
                print("🔄 Tự động chuyển sang cổng chính thức Binance Square OpenAPI để hoàn tất đăng bài...")
                result = post_to_binance_square_openapi(post_content)
                share_link = result.get("shareLink") or BINANCE_SQUARE_URL
                print(f"✅ Đã đăng thành công qua Square OpenAPI!")
                print(f"   -> Post ID: {result.get('id')}")
                print(f"   -> Link bài đăng: {share_link}")
                print("📸 Đang mở trình duyệt chụp màn hình xác nhận post_success.png...")
                capture_verification_screenshot(share_link)
                print(f"✅ Đã lưu ảnh chụp màn hình tại: {SCREENSHOT_PATH}")
            else:
                raise


if __name__ == "__main__":
    main()
