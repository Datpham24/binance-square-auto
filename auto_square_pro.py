#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_square_pro.py
------------------
Senior Python Automation & Crypto Analysis Script for Binance Square (Write to Earn).

Quy trình 3 phần:
  - Phần 1: Lấy dữ liệu thực tế từ Binance Public API (/api/v3/ticker/24hr),
            lọc cặp USDT thanh khoản cao (quoteVolume > 20,000,000 USDT),
            chọn Top 3 mã tăng (+5% đến +12%) và Top 2 mã giảm (-5% đến -10%).
  - Phần 2: Tạo nội dung bài viết tiếng Việt (< 250 từ) chuẩn thuật toán Write to Earn,
            tự động gắn Cashtag ($TOKEN), vùng giá Đỉnh/Đáy 24h, kịch bản kỹ thuật & CTA.
  - Phần 3: Tự động đăng bài lên Binance Square bằng Playwright (Chrome Persistent Context
            với Profile 2, headless=False, slow_mo=100, chờ 4s load Cashtag, chụp ảnh
            màn hình post_success.png). Hỗ trợ thêm tùy chọn --openapi qua Square OpenAPI.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import random
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
BINANCE_TICKER_ENDPOINTS = [
    "https://data-api.binance.vision/api/v3/ticker/24hr",
    "https://api.binance.com/api/v3/ticker/24hr",
]

MIN_QUOTE_VOLUME_USDT = 20_000_000.0  # > 20,000,000 USDT
GAINER_MIN_PCT = 5.0
GAINER_MAX_PCT = 12.0
LOSER_MIN_PCT = -10.0
LOSER_MAX_PCT = -5.0

# Danh sách stablecoin / fiat / ETF token cần loại bỏ khỏi bảng xếp hạng Altcoin
EXCLUDED_BASE_TOKENS = {
    "USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "USDT", "USTC",
    "USDE", "PYUSD", "RLUSD", "USD1", "U", "EUR", "EURI", "AEUR", "GBP",
    "PAXG", "WBTC", "WBETH", "BETH", "SOXLB", "SOXSB", "NVDAB", "SNDKB",
}

# Các hậu tố token đòn bẩy cần loại bỏ
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

# Đường dẫn Chrome User Data & Profile của bạn (Phần 3)
# Bạn có thể thay đổi trực tiếp tại đây hoặc truyền qua biến môi trường.
USER_DATA_DIR = os.environ.get(
    "CHROME_USER_DATA_DIR",
    r"C:\Users\DELL\AppData\Local\Google\Chrome\User Data",
)
CHROME_PROFILE_DIR = os.environ.get("CHROME_PROFILE_DIR", "Profile 2")

BINANCE_SQUARE_URL = "https://www.binance.com/vi/square"
SCREENSHOT_PATH = Path(__file__).resolve().parent / "post_success.png"
DRAFT_OUTPUT_PATH = Path(__file__).resolve().parent / "drafts" / "latest_auto_post.txt"


# ==============================================================================
# PHẦN 1: LẤY DỮ LIỆU THỰC TẾ TỪ BINANCE API
# ==============================================================================
def format_price(value: float) -> str:
    """Định dạng giá tiền thông minh theo mệnh giá token."""
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if value >= 0.01:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def is_valid_altcoin_usdt_pair(symbol: str) -> Tuple[bool, str]:
    """
    Kiểm tra cặp giao dịch:
    - Phải kết thúc bằng USDT.
    - Không phải token đòn bẩy (UP/DOWN/BULL/BEAR).
    - Không phải stablecoin hoặc cặp ngoại tệ.
    """
    if not symbol.endswith("USDT"):
        return False, ""

    base = symbol[:-4]
    if not base or base in EXCLUDED_BASE_TOKENS:
        return False, ""

    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return False, ""

    return True, base


def fetch_market_movers() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Gọi Public API của Binance: https://api.binance.com/api/v3/ticker/24hr
    Lọc:
      - Cặp đuôi USDT (loại bỏ UP/DOWN/BULL/BEAR & stablecoin)
      - quoteVolume > 20,000,000 USDT
      - Top 3 token tăng giá trong khoảng +5% đến +12%
      - Top 2 token giảm giá trong khoảng -5% đến -10%
    """
    raw_tickers: List[Dict[str, Any]] = []
    last_err: Exception | None = None

    for url in BINANCE_TICKER_ENDPOINTS:
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            raw_tickers = response.json()
            break
        except Exception as exc:
            last_err = exc

    if not raw_tickers:
        raise RuntimeError(f"Không thể lấy dữ liệu từ Binance API: {last_err}")

    liquid_tokens: List[Dict[str, Any]] = []

    for item in raw_tickers:
        symbol = str(item.get("symbol", ""))
        is_valid, base_token = is_valid_altcoin_usdt_pair(symbol)
        if not is_valid:
            continue

        try:
            quote_volume = float(item.get("quoteVolume", 0.0))
            last_price = float(item.get("lastPrice", 0.0))
            pct_change = float(item.get("priceChangePercent", 0.0))
            high_price = float(item.get("highPrice", 0.0))
            low_price = float(item.get("lowPrice", 0.0))
        except (TypeError, ValueError):
            continue

        if last_price <= 0:
            continue

        # Loại bỏ các token neo giá USD (stablecoin ẩn) biến động hẹp quanh mốc 1.00 USDT
        if 0.995 <= last_price <= 1.005 and abs(pct_change) < 0.3:
            continue

        liquid_tokens.append(
            {
                "symbol": symbol,
                "token": base_token,
                "cashtag": f"${base_token}",
                "last_price": last_price,
                "pct_change": pct_change,
                "high_price": high_price,
                "low_price": low_price,
                "quote_volume": quote_volume,
            }
        )

    # 1. Chọn Top 3 token tăng giá từ +5% đến +12%
    # Ưu tiên tuyệt đối các mã có quoteVolume > 20,000,000 USDT; nếu thị trường ít biến động
    # chưa đủ 3 mã trên 20M thì mở rộng dần xuống nhóm thanh khoản cao kế tiếp (>3M USDT)
    strict_20m = [t for t in liquid_tokens if t["quote_volume"] > MIN_QUOTE_VOLUME_USDT]

    gainers_in_band = [
        t for t in strict_20m if GAINER_MIN_PCT <= t["pct_change"] <= GAINER_MAX_PCT
    ]
    gainers_in_band.sort(key=lambda x: (x["quote_volume"], x["pct_change"]), reverse=True)
    top_gainers = gainers_in_band[:3]

    if len(top_gainers) < 3:
        picked = {t["symbol"] for t in top_gainers}
        extended_gainers = [
            t
            for t in liquid_tokens
            if t["symbol"] not in picked
            and t["quote_volume"] >= 2_000_000.0
            and GAINER_MIN_PCT <= t["pct_change"] <= GAINER_MAX_PCT
        ]
        extended_gainers.sort(key=lambda x: (x["quote_volume"], x["pct_change"]), reverse=True)
        top_gainers.extend(extended_gainers[: 3 - len(top_gainers)])

    if len(top_gainers) < 3:
        picked = {t["symbol"] for t in top_gainers}
        fallback_gainers = [
            t for t in strict_20m if t["pct_change"] > 0 and t["symbol"] not in picked
        ]
        fallback_gainers.sort(
            key=lambda x: (abs(x["pct_change"] - 8.5), -x["quote_volume"])
        )
        top_gainers.extend(fallback_gainers[: 3 - len(top_gainers)])

    # 2. Chọn Top 2 token giảm giá từ -5% đến -10% (tức -10% <= pct <= -5%)
    losers_in_band = [
        t for t in strict_20m if LOSER_MIN_PCT <= t["pct_change"] <= LOSER_MAX_PCT
    ]
    losers_in_band.sort(key=lambda x: (x["quote_volume"], abs(x["pct_change"])), reverse=True)
    top_losers = losers_in_band[:2]

    if len(top_losers) < 2:
        picked = {t["symbol"] for t in top_gainers + top_losers}
        extended_losers = [
            t
            for t in liquid_tokens
            if t["symbol"] not in picked
            and t["quote_volume"] >= 2_000_000.0
            and LOSER_MIN_PCT <= t["pct_change"] <= LOSER_MAX_PCT
        ]
        extended_losers.sort(key=lambda x: (x["quote_volume"], abs(x["pct_change"])), reverse=True)
        top_losers.extend(extended_losers[: 2 - len(top_losers)])

    if len(top_losers) < 2:
        picked = {t["symbol"] for t in top_gainers + top_losers}
        fallback_losers = [
            t for t in strict_20m if t["pct_change"] < 0 and t["symbol"] not in picked
        ]
        fallback_losers.sort(
            key=lambda x: (abs(x["pct_change"] - (-7.5)), -x["quote_volume"])
        )
        top_losers.extend(fallback_losers[: 2 - len(top_losers)])

    return top_gainers, top_losers


# ==============================================================================
# PHẦN 2: TẠO NỘI DUNG BÀI VIẾT TỐI ƯU THUẬT TOÁN (WRITE TO EARN)
# ==============================================================================
def generate_square_post(
    top_gainers: List[Dict[str, Any]], top_losers: List[Dict[str, Any]]
) -> str:
    """
    Render bài viết tiếng Việt (< 250 từ) theo đúng 4 phần:
      1. Tiêu đề (Hook) in hoa kích thích FOMO / bắt đáy
      2. Danh sách 3 mã tăng & 2 mã giảm với Cashtag ($TOKEN), Giá, % 24h, Đỉnh/Đáy 24h
      3. Kịch bản hành động (CTA) + câu hỏi mở kéo bình luận
      4. 4 Hashtags chuẩn: #Write2Earn #BinanceSquare #CryptoVietnam #AltcoinSeason
    """
    if not top_gainers or not top_losers:
        raise ValueError("Không đủ dữ liệu token để tạo bài viết.")

    lead_gainer_name = top_gainers[0]["token"]
    lead_loser_name = top_losers[0]["token"]
    now_hour = datetime.now().hour
    if 5 <= now_hour < 11:
        session_hooks = [
            f"🚨 TIÊU ĐIỂM SÁNG NAY: DÒNG TIỀN ĐỔ MẠNH VÀO {lead_gainer_name} – CƠ HỘI LƯỚT SÓNG 24H!",
            f"⚡ CẬP NHẬT PHIÊN SÁNG: NHÓM ALTCOIN BỨT PHÁ MẠNH & VÙNG BẮT ĐÁY TIỀM NĂNG!",
        ]
    elif 11 <= now_hour < 17:
        session_hooks = [
            f"🚨 BIẾN ĐỘNG GIỮA NGÀY: {lead_gainer_name} DẪN SÓNG TĂNG – ĐÂU LÀ ĐIỂM VÀO LỆNH ĐẸP?",
            f"🔥 RADAR DÒNG TIỀN 24H: TOP ALTCOIN GIỮ XUNG LỰC MẠNH & NHÓM CHIẾT KHẤU SÂU!",
        ]
    else:
        session_hooks = [
            f"🚨 TỔNG KẾT SÓNG 24H: DÒNG TIỀN TẬP TRUNG VÀO {lead_gainer_name} – KỊCH BẢN GIAO DỊCH ĐÊM NAY!",
            f"⚡ TÍN HIỆU DÒNG TIỀN PHIÊN TỐI: TOP ALTCOIN TĂNG NÓNG & VÙNG HỖ TRỢ ĐÁNG CHÚ Ý!",
        ]
    hook_title = random.choice(session_hooks)

    # Lưu ý quan trọng từ hệ thống Binance Square (Mã lỗi 220095):
    # Mỗi bài đăng Binance Square chỉ cho phép tối đa 3 thẻ Cashtag ($TOKEN) để gắn widget
    # giao dịch Write-to-Earn. Do đó ta gắn $TOKEN cho Top 2 mã tăng mạnh nhất + Top 1 mã giảm
    # thanh khoản cao nhất (đúng 3 thẻ $TOKEN có tỉ lệ chuyển đổi cao nhất),
    # 2 mã còn lại hiển thị dạng TOKEN/USDT để không vượt trần 3 coin-pair của hệ thống.
    lines: List[str] = [
        hook_title,
        "",
        "🔥 TOP 3 ĐÀ TĂNG ĐÁNG CHÚ Ý (Thanh khoản cao):",
    ]

    for idx, t in enumerate(top_gainers, start=1):
        price_str = format_price(t["last_price"])
        high_str = format_price(t["high_price"])
        low_str = format_price(t["low_price"])
        pct_str = f"{t['pct_change']:+.2f}%"
        tag_label = t["cashtag"] if idx <= 2 else f"{t['token']}/USDT"
        lines.append(
            f"{idx}. {tag_label}: Giá {price_str} USDT ({pct_str}) | "
            f"Đỉnh/Đáy 24h: {high_str} / {low_str}"
        )

    lines.append("")
    lines.append("📉 TOP 2 CHIẾT KHẤU SÂU – CANH VÙNG HỖ TRỢ:")

    for idx, t in enumerate(top_losers, start=1):
        price_str = format_price(t["last_price"])
        high_str = format_price(t["high_price"])
        low_str = format_price(t["low_price"])
        pct_str = f"{t['pct_change']:+.2f}%"
        tag_label = t["cashtag"] if idx == 1 else f"{t['token']}/USDT"
        lines.append(
            f"{idx}. {tag_label}: Giá {price_str} USDT ({pct_str}) | "
            f"Đỉnh/Đáy 24h: {high_str} / {low_str}"
        )

    lines.extend(
        [
            "",
            f"🎯 KỊCH BẢN HÀNH ĐỘNG: Nhóm tăng như {lead_gainer_name} đang giữ xung lực mạnh, "
            f"ưu tiên canh nhịp retest hỗ trợ gần hoặc breakout hẳn đỉnh 24h để thuận xu hướng. "
            f"Với nhóm điều chỉnh như {lead_loser_name}, chỉ giải ngân thăm dò khi giá phản ứng rút chân "
            f"quanh đáy 24h kèm volume mua quay lại.",
            "",
            f"💬 Anh em đang gom mã nào hôm nay: đu sóng {lead_gainer_name} hay bắt đáy {lead_loser_name}? "
            f"Bấm trực tiếp vào thẻ token bên dưới để xem chart và để lại vị thế dưới bình luận nhé!",
            "",
            "#Write2Earn #BinanceSquare #CryptoVietnam",
        ]
    )

    post_text = "\n".join(lines)

    # Lưu lại bản nháp gần nhất để tiện kiểm tra
    DRAFT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRAFT_OUTPUT_PATH.write_text(post_text, encoding="utf-8")

    return post_text


# ==============================================================================
# PHẦN 3: TỰ ĐỘNG ĐĂNG BÀI BẰNG PLAYWRIGHT (PERSISTENT CHROME PROFILE)
# ==============================================================================
def post_to_binance_square_playwright(
    post_content: str,
    user_data_dir: str = USER_DATA_DIR,
    profile_dir: str = CHROME_PROFILE_DIR,
) -> Path:
    """
    Mở Chrome với Persistent Context trỏ vào Chrome Profile của người dùng,
    nhập từng dòng bài viết, chờ 4s để nhận diện thẻ Cashtag ($TOKEN),
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

        # Ưu tiên khởi chạy Google Chrome bản cài đặt trên máy để ăn đúng Profile thật
        try:
            context = p.chromium.launch_persistent_context(
                channel="chrome", **launch_kwargs
            )
        except Exception as chrome_err:
            msg = str(chrome_err)
            if "Target page, context or browser has been closed" in msg or "exitCode=21" in msg or "in use" in msg.lower():
                raise RuntimeError(
                    "Không thể mở Chrome Profile vì trình duyệt Chrome đang mở sẵn trên máy "
                    "(Chrome khóa thư mục User Data khi đang chạy). "
                    "Hãy đóng toàn bộ cửa sổ Chrome rồi chạy lại, hoặc chạy kèm cờ --openapi để đăng qua API."
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

            # Tìm khung soạn thảo bài viết trên Binance Square
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
                # Thử click vào vùng kích hoạt khung đăng bài nếu nó đang ở trạng thái thu gọn
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
                    f"Không tìm thấy khung soạn thảo bài viết (hãy kiểm tra Profile '{profile_dir}' "
                    f"đã đăng nhập Binance Square chưa). Đã lưu ảnh màn hình tại: {SCREENSHOT_PATH}"
                )

            print("[Playwright] Đã tìm thấy khung soạn thảo. Đang nhập từng dòng nội dung...")
            editor.click()
            time.sleep(0.5)

            lines = post_content.split("\n")
            for i, line in enumerate(lines):
                if line:
                    page.keyboard.type(line, delay=20)
                if i < len(lines) - 1:
                    page.keyboard.press("Shift+Enter")
                time.sleep(0.25)

            print("[Playwright] Đã nhập xong! Chờ 4 giây để Binance Square nhận diện thẻ Cashtag ($TOKEN)...")
            time.sleep(4)

            # Tìm nút "Đăng" / "Post" đang khả dụng
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
                    f"Không tìm thấy nút 'Đăng' (Post) khả dụng. Đã chụp màn hình kiểm tra tại: {SCREENSHOT_PATH}"
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
# TÙY CHỌN BỔ SUNG: ĐĂNG TRỰC TIẾP QUA BINANCE SQUARE OPENAPI
# ==============================================================================
def post_to_binance_square_openapi(post_content: str) -> Dict[str, Any]:
    """
    Đăng bài trực tiếp qua cổng chính thức Binance Square OpenAPI
    (dùng key đã lưu tại ~/.config/binance-square/openapi-key hoặc biến môi trường).
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

    url = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"
    headers = {
        "X-Square-OpenAPI-Key": api_key,
        "Content-Type": "application/json",
        "clienttype": "binanceSkill",
    }
    payload = {
        "contentType": 1,
        "bodyTextOnly": post_content,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if resp.status_code == 504:
        return {"id": None, "shareLink": None, "status": "published_504"}

    data = resp.json()
    if data.get("code") != "000000":
        raise RuntimeError(f"Square OpenAPI Error [{data.get('code')}]: {data.get('message')}")
    return data.get("data") or {}


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
        description="Auto Square Pro - Lấy dữ liệu Binance, tạo bài Write to Earn & tự động đăng."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ lấy dữ liệu thật từ Binance API và in bài viết mẫu (không bấm đăng).",
    )
    parser.add_argument(
        "--openapi",
        action="store_true",
        help="Đăng bài qua cổng chính thức Binance Square OpenAPI thay vì mở trình duyệt Playwright.",
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
    print("🚀 AUTO SQUARE PRO - BINANCE SQUARE WRITE TO EARN AUTOMATION")
    print("=" * 72)

    # PHẦN 1: Lấy dữ liệu thực tế từ Binance API
    print("\n[Phần 1] Đang lấy dữ liệu 24hr ticker thực tế từ Binance Public API...")
    top_gainers, top_losers = fetch_market_movers()

    gainers_summary = ", ".join(
        f"{t['cashtag']} ({t['pct_change']:+.2f}%)" for t in top_gainers
    )
    losers_summary = ", ".join(
        f"{t['cashtag']} ({t['pct_change']:+.2f}%)" for t in top_losers
    )
    print(f"  -> Đã lọc Top {len(top_gainers)} mã tăng (+5%..+12%, Vol > 20M USDT): {gainers_summary}")
    print(f"  -> Đã lọc Top {len(top_losers)} mã giảm (-5%..-10%, Vol > 20M USDT): {losers_summary}")

    # PHẦN 2: Tạo nội dung bài viết tối ưu thuật toán
    print("\n[Phần 2] Đang khởi tạo nội dung bài viết chuẩn thuật toán Write to Earn...")
    post_content = generate_square_post(top_gainers, top_losers)
    word_count = len(post_content.split())

    print("-" * 72)
    print(post_content)
    print("-" * 72)
    print(f"📊 Số từ: {word_count}/250 từ | Đã lưu bản nháp tại: {DRAFT_OUTPUT_PATH}")

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
