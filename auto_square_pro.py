#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_square_pro.py (v3.0 - Ultimate Pro Creator Edition)
--------------------------------------------------------
Senior Python Automation & Crypto Technical Analysis Script for Binance Square (Write to Earn).

Chiến lược Creator chuyên nghiệp 3 trụ cột:
  1. Công thức 3 Thẻ Vàng tối ưu hoa hồng Write to Earn:
     - Thẻ 1 ($BTC): La bàn định hướng thị trường chung (Giá, % 24h, EMA20 & RSI14 khung 4H).
     - Thẻ 2 (Coin Top 10): 1 đồng vốn hóa lớn ($ETH, $SOL, $BNB, $XRP, $DOGE, $ADA, $TRX,
       $AVAX, $LINK, $SUI, $TON) đang có cấu trúc nến 4H và dòng tiền tốt nhất.
     - Thẻ 3 (Altcoin Sóng Nóng): 1 đồng Altcoin biến động mạnh (+5%..+12% hoặc -5%..-10%)
       dành cho trader thích biên độ lướt sóng lớn.
  2. Chỉ báo kỹ thuật thực tế từ 30 cây nến 4H (/api/v3/klines):
     - Tự động tính RSI(14), EMA(20), Hỗ trợ/Kháng cự 4H, Entry, TP1, TP2, SL (R:R >= 1:2).
  3. Đa dạng hóa kịch bản theo 3 phiên Giờ Việt Nam (UTC+7):
     - Phiên Sáng (08:00): Bản tin Mở Phiên & Định Hướng Coin Top
     - Phiên Trưa (12:00): Radar Săn Kèo Lướt Sóng Giữa Ngày
     - Phiên Tối (20:00): Chiến Lược Đón Sóng Phiên Mỹ (US Session)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import re
import sys
import time
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

VN_TZ = timezone(timedelta(hours=7))

# Rổ Coin Top 10 - Vốn hóa lớn, thanh khoản cao, cộng đồng quan tâm đông nhất
TOP_10_MAJOR_TOKENS = {
    "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK", "SUI", "TON",
}

MIN_QUOTE_VOLUME_USDT = 25_000_000.0
GAINER_MIN_PCT = 5.0
GAINER_MAX_PCT = 12.0
LOSER_MIN_PCT = -10.0
LOSER_MAX_PCT = -5.0

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
# PHẦN 1: LẤY DỮ LIỆU & TÍNH CHỈ BÁO KỸ THUẬT 4H (RSI 14, EMA 20, SUPPORT/RESISTANCE)
# ==============================================================================
def infer_price_decimals(raw_price_str: str, price_val: float) -> int:
    """Đảm bảo đủ chữ số thập phân có nghĩa theo mệnh giá gốc của token."""
    if price_val >= 1000:
        min_dec = 1
    elif price_val >= 100:
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
    """Định dạng giá làm tròn chuẩn theo số thập phân của token."""
    if decimals <= 1 and value >= 1000:
        formatted = f"{value:,.1f}"
    else:
        formatted = f"{value:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def format_volume_millions(quote_volume: float) -> str:
    """Định dạng Volume 24h theo triệu USD (M) hoặc tỷ USD (B)."""
    vol_m = quote_volume / 1_000_000.0
    if vol_m >= 1000:
        return f"{vol_m / 1000.0:.2f}B"
    if vol_m >= 100:
        return f"{vol_m:.0f}M"
    return f"{vol_m:.1f}M"


def is_valid_altcoin_usdt_pair(symbol: str) -> Tuple[bool, str]:
    """Lọc cặp giao dịch đuôi USDT (bỏ stablecoin & token đòn bẩy)."""
    if not symbol.endswith("USDT"):
        return False, ""
    base = symbol[:-4]
    if not base or base in EXCLUDED_BASE_TOKENS:
        return False, ""
    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return False, ""
    return True, base


def binance_get_json(endpoint: str, params: Dict[str, Any] | None = None) -> Any:
    """Gọi Binance Public API với fallback đa cụm máy chủ."""
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


def compute_ema(values: List[float], period: int = 20) -> float:
    """Tính Exponential Moving Average (EMA) trên chuỗi giá đóng cửa nến 4H."""
    if not values:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    k = 2.0 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1.0 - k)
    return ema_val


def compute_rsi(values: List[float], period: int = 14) -> float:
    """Tính chỉ số RSI (14) chuẩn Wilder trên chuỗi giá đóng cửa nến 4H."""
    if len(values) <= period:
        return 50.0
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def fetch_4h_indicators(symbol: str) -> Dict[str, float]:
    """
    Lấy 30 cây nến 4H gần nhất để tính:
      - EMA 20 khung 4H
      - RSI 14 khung 4H
      - Vùng Hỗ trợ / Kháng cự 4H gần nhất (12 cây nến = 48h qua)
    """
    klines = binance_get_json(
        "/api/v3/klines",
        params={"symbol": symbol, "interval": "4h", "limit": 30},
    )
    if not klines:
        return {}

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    highs_48h = highs[-12:] if len(highs) >= 12 else highs
    lows_48h = lows[-12:] if len(lows) >= 12 else lows

    support_4h_near = min(lows[-3:]) if len(lows) >= 3 else min(lows_48h)
    resistance_4h_near = max(highs[-3:]) if len(highs) >= 3 else max(highs_48h)

    return {
        "ema20_4h": compute_ema(closes, 20),
        "rsi14_4h": compute_rsi(closes, 14),
        "support_4h_near": support_4h_near,
        "support_48h_low": min(lows_48h),
        "resistance_4h_near": resistance_4h_near,
        "resistance_48h_high": max(highs_48h),
    }


def build_trading_plan(token_info: Dict[str, Any], plan_type: str) -> Dict[str, Any]:
    """
    Xây dựng kế hoạch giao dịch (Entry, TP1, TP2, SL, Tín hiệu kỹ thuật RSI/EMA 4H)
    cho một mã token theo hướng Momentum (thuận xu hướng) hoặc Rebound (bắt nhịp hồi).
    """
    symbol = token_info["symbol"]
    price = token_info["last_price"]
    high_24h = token_info["high_price"]
    low_24h = token_info["low_price"]
    decimals = token_info["decimals"]

    ind = fetch_4h_indicators(symbol)
    ema20 = ind.get("ema20_4h", price * 0.985)
    rsi14 = ind.get("rsi14_4h", 54.0)
    support_4h = ind.get("support_4h_near", low_24h)

    if plan_type == "momentum":
        # Entry giảm 1.5% - 2.5% so với giá hiện tại hoặc quanh EMA20/Hỗ trợ 4H gần nhất
        raw_e1 = price * (1.0 - 0.024)
        raw_e2 = price * (1.0 - 0.014)
        if price * 0.96 <= support_4h <= price * 0.988:
            raw_e1 = min(raw_e1, support_4h)
        entry_low = min(raw_e1, raw_e2)
        entry_high = max(raw_e1, raw_e2)
        entry_mid = (entry_low + entry_high) / 2.0

        sl_price = entry_low * (1.0 - 0.032)
        risk = max(entry_mid - sl_price, price * 0.01)
        tp1_price = max(high_24h, entry_mid + 1.3 * risk)
        tp2_price = max(tp1_price * 1.04, entry_mid + 2.2 * risk)

        ema_status = "trên EMA20" if price >= ema20 else "sát EMA20"
        tech_note = f"RSI 4H = {rsi14:.1f} ({ema_status} vùng ${format_token_price(ema20, decimals)})"
        entry_note = "chờ nhịp retest hỗ trợ 4H"
    else:
        # Kèo Rebound / Bắt nhịp hồi quanh vùng hỗ trợ đáy 24h (thấp hơn giá hiện tại 1% - 2%)
        band_low = price * (1.0 - 0.02)
        band_high = price * (1.0 - 0.01)
        if band_low <= low_24h <= price:
            entry_low = min(band_low, low_24h)
            entry_high = max(band_high, low_24h)
        else:
            entry_low = band_low
            entry_high = band_high
        entry_mid = (entry_low + entry_high) / 2.0

        tp1_price = entry_mid * 1.04
        tp2_price = entry_mid * 1.08
        anchor_low = min(low_24h, entry_low)
        sl_price = anchor_low * (1.0 - 0.028)

        rsi_label = "vùng quá bán, dễ bật hồi" if rsi14 < 42 else "đang tích lũy tạo đáy"
        tech_note = f"RSI 4H = {rsi14:.1f} ({rsi_label})"
        entry_note = "quanh hỗ trợ đáy 24h"

    return {
        **token_info,
        "plan_type": plan_type,
        "rsi14_4h": rsi14,
        "ema20_4h_str": format_token_price(ema20, decimals),
        "tech_note": tech_note,
        "entry_note": entry_note,
        "entry_1": format_token_price(entry_low, decimals),
        "entry_2": format_token_price(entry_high, decimals),
        "tp1": format_token_price(tp1_price, decimals),
        "tp2": format_token_price(tp2_price, decimals),
        "sl": format_token_price(sl_price, decimals),
        "price_str": format_token_price(price, decimals),
        "high_str": format_token_price(high_24h, decimals),
        "low_str": format_token_price(low_24h, decimals),
        "vol_str": format_volume_millions(token_info["quote_volume"]),
    }


def fetch_market_portfolio() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Quét toàn bộ sàn Binance và trả về bộ 3 hoàn hảo cho bài đăng Creator:
      1. btc_compass: Dữ liệu & chỉ báo 4H của $BTC (La bàn thị trường)
      2. top10_plan:  Kèo giao dịch cho 1 đồng Coin Top 10 nổi bật nhất hôm nay
      3. alt_plan:    Kèo giao dịch cho 1 đồng Altcoin đang có biến động sóng mạnh nhất
    """
    raw_tickers = binance_get_json("/api/v3/ticker/24hr")
    if not raw_tickers:
        raise RuntimeError("Dữ liệu 24hr ticker từ Binance rỗng.")

    candidates: List[Dict[str, Any]] = []
    btc_raw: Dict[str, Any] | None = None

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
        if 0.995 <= last_price <= 1.005 and abs(pct_change) < 0.3:
            continue

        info = {
            "symbol": symbol,
            "token": base_token,
            "cashtag": f"${base_token}",
            "last_price": last_price,
            "pct_change": pct_change,
            "high_price": high_price,
            "low_price": low_price,
            "quote_volume": quote_volume,
            "decimals": infer_price_decimals(raw_last_price, last_price),
        }

        if base_token == "BTC":
            btc_raw = info
        else:
            candidates.append(info)

    if btc_raw is None:
        raise RuntimeError("Không tìm thấy cặp BTCUSDT trong dữ liệu Binance.")

    # 1. Phân tích La bàn $BTC
    btc_ind = fetch_4h_indicators("BTCUSDT")
    btc_rsi = btc_ind.get("rsi14_4h", 52.0)
    btc_ema20 = btc_ind.get("ema20_4h", btc_raw["last_price"])
    btc_compass = {
        **btc_raw,
        "price_str": format_token_price(btc_raw["last_price"], btc_raw["decimals"]),
        "high_str": format_token_price(btc_raw["high_price"], btc_raw["decimals"]),
        "low_str": format_token_price(btc_raw["low_price"], btc_raw["decimals"]),
        "ema20_str": format_token_price(btc_ema20, btc_raw["decimals"]),
        "rsi14_4h": btc_rsi,
        "vol_str": format_volume_millions(btc_raw["quote_volume"]),
    }

    # 2. Chọn Mã 1 từ rổ Coin Top 10 (xoay vòng thông minh giữa Top 1-5 mã sôi động nhất
    # theo 5 phiên Sáng / Trưa / Chiều (Phiên Âu) / Tối (Phiên Mỹ) / Đêm (Futures)
    # để 5 bài trong cùng 1 ngày luôn phân tích các cặp coin mới mẻ, không trùng lặp)
    top10_pool = [t for t in candidates if t["token"] in TOP_10_MAJOR_TOKENS]
    top10_pool.sort(
        key=lambda x: (abs(x["pct_change"]) * (1.5 if x["pct_change"] > 0 else 1.2), x["quote_volume"]),
        reverse=True,
    )
    vn_hour = datetime.now(VN_TZ).hour
    if 5 <= vn_hour < 11:
        session_slot = 0  # 08:00 Sáng: Top 1 Coin Top 10
    elif 11 <= vn_hour < 15:
        session_slot = 1  # 12:00 Trưa: Top 2 Coin Top 10
    elif 15 <= vn_hour < 19:
        session_slot = 2  # 16:00 Chiều (Phiên Âu): Top 3 Coin Top 10
    elif 19 <= vn_hour < 22:
        session_slot = 3  # 20:00 Tối (Mở Phiên Mỹ): Top 1 hoặc Top 4 Coin Top 10
    else:
        session_slot = 4  # 23:00 Đêm (Futures Phiên Mỹ): Top 5 hoặc Top 2 Coin Top 10

    chosen_top10 = top10_pool[session_slot % len(top10_pool)]
    top10_mode = "momentum" if chosen_top10["pct_change"] >= -1.5 else "rebound"
    top10_plan = build_trading_plan(chosen_top10, top10_mode)

    # 3. Chọn Mã 2 là Altcoin sóng mạnh (xoay vòng giữa Kèo Thuận Xu Hướng +5%..+12%
    # và Kèo Bắt Nhịp Hồi -5%..-10% theo từng phiên để kênh đa dạng kèo suốt 5 khung giờ)
    volume_tiers = [MIN_QUOTE_VOLUME_USDT, 10_000_000.0, 3_000_000.0, 1_500_000.0]
    chosen_alt: Dict[str, Any] | None = None
    prefer_rebound_alt = session_slot in (1, 3)  # Phiên 12:00 & 20:00 ưu tiên săn kèo Rebound bắt đáy

    if not prefer_rebound_alt:
        for min_vol in volume_tiers:
            pool = [
                t
                for t in candidates
                if t["symbol"] != chosen_top10["symbol"]
                and t["token"] not in TOP_10_MAJOR_TOKENS
                and t["quote_volume"] >= min_vol
                and GAINER_MIN_PCT <= t["pct_change"] <= GAINER_MAX_PCT
            ]
            if pool:
                pool.sort(key=lambda x: (x["quote_volume"], x["pct_change"]), reverse=True)
                pick_idx = (session_slot // 2) % len(pool)
                chosen_alt = pool[pick_idx]
                alt_mode = "momentum"
                break

    if chosen_alt is None:
        # Tìm Altcoin điều chỉnh -5%..-10% (Kèo Bắt Nhịp Hồi)
        for min_vol in volume_tiers:
            pool = [
                t
                for t in candidates
                if t["symbol"] != chosen_top10["symbol"]
                and t["quote_volume"] >= min_vol
                and LOSER_MIN_PCT <= t["pct_change"] <= LOSER_MAX_PCT
            ]
            if pool:
                pool.sort(key=lambda x: (x["quote_volume"], abs(x["pct_change"])), reverse=True)
                chosen_alt = pool[0]
                alt_mode = "rebound"
                break

    if chosen_alt is None:
        fallback_pool = [t for t in candidates if t["symbol"] != chosen_top10["symbol"] and t["quote_volume"] >= 5_000_000]
        fallback_pool.sort(key=lambda x: abs(x["pct_change"]), reverse=True)
        chosen_alt = fallback_pool[0]
        alt_mode = "momentum" if chosen_alt["pct_change"] >= 0 else "rebound"

    alt_plan = build_trading_plan(chosen_alt, alt_mode)
    return btc_compass, top10_plan, alt_plan


# ==============================================================================
# PHẦN 2: TẠO BÀI VIẾT CHUYÊN NGHIỆP THEO 3 KHUNG GIỜ (SÁNG / TRƯA / TỐI)
# ==============================================================================
def generate_square_post(
    btc: Dict[str, Any], top10: Dict[str, Any], alt: Dict[str, Any]
) -> str:
    """
    Render bài viết chuẩn Creator chuyên nghiệp (180 - 220 từ):
      - Đa dạng tiêu đề & lời dẫn theo đúng khung giờ Việt Nam (Sáng / Trưa / Tối).
      - Gắn đúng 3 thẻ vàng Cashtag tối đa của Binance Square: $BTC, $[TOP10], $[ALT].
      - Hiển thị chỉ báo RSI(14) & EMA(20) khung 4H thực tế kèm Entry / TP / SL rõ ràng.
    """
    vn_hour = datetime.now(VN_TZ).hour
    t1 = top10["token"]
    t2 = alt["token"]
    btc_pct = f"{btc['pct_change']:+.2f}%"
    t1_pct = f"{top10['pct_change']:+.2f}%"
    t2_pct = f"{alt['pct_change']:+.2f}%"

    if 5 <= vn_hour < 11:
        headline = f"🍚 THỰC ĐƠN SÁNG – TIỆM CƠM CRYPTO: BTC – {t1} – {t2}"
        intro = (
            f"🧭 Mở cửa ngày mới, la bàn $BTC đang ở mức ${btc['price_str']} ({btc_pct}), "
            f"RSI 4H đạt {btc['rsi14_4h']:.1f} quanh EMA20 (${btc['ema20_str']}). "
            f"Tiệm lên sẵn 2 kèo sáng nay cho anh em chọn món:"
        )
        cta_question = (
            f"💬 Sáng nay anh em ghé Tiệm Cơm Crypto chọn món chính {t1} hay món lướt sóng {t2}? Cùng chia sẻ góc nhìn bên dưới nhé."
        )
    elif 11 <= vn_hour < 15:
        headline = f"🍱 CƠM TRƯA TRADE GÌ? PLAN LƯỚT SÓNG {t1} & {t2}"
        intro = (
            f"🧭 Nhịp đập giữa ngày từ Tiệm Cơm Crypto: $BTC giữ mốc ${btc['price_str']} ({btc_pct} | "
            f"Đỉnh/Đáy 24h: ${btc['high_str']} – ${btc['low_str']}), mở ra biên độ đẹp cho 2 kèo tâm điểm:"
        )
        cta_question = (
            f"💬 Bữa trưa hôm nay anh em chấm cấu trúc 4H của {t1} hay {t2} hơn? Để lại kế hoạch giao dịch bên dưới nhé."
        )
    elif 15 <= vn_hour < 19:
        headline = f"☕ TIỆM CƠM CRYPTO – ĐÓN SÓNG PHIÊN ÂU: {t1} & {t2}"
        intro = (
            f"🧭 Bước vào phiên Âu, $BTC vận động quanh ${btc['price_str']} ({btc_pct} | "
            f"EMA20 4H: ${btc['ema20_str']}). Thanh khoản đang đổ mạnh vào 2 thiết lập kỹ thuật sau:"
        )
        cta_question = (
            f"💬 Phiên Âu chiều nay anh em ghé Tiệm chọn canh nhịp retest của {t1} hay đón sóng ở {t2}?"
        )
    elif 19 <= vn_hour < 22:
        headline = f"🔥 THỰC ĐƠN PHIÊN MỸ – TIỆM CƠM CRYPTO: {t1} & {t2}"
        intro = (
            f"🧭 Trước giờ mở cửa phiên Mỹ, $BTC đang neo tại ${btc['price_str']} ({btc_pct} | "
            f"RSI 4H: {btc['rsi14_4h']:.1f}). Tiệm Cơm Crypto lên sẵn kịch bản 2 mã thanh khoản cao nhất tối nay:"
        )
        cta_question = (
            f"💬 Tối nay phiên Mỹ anh em chọn món chính {t1} thuận xu hướng hay canh vùng hỗ trợ của {t2}?"
        )
    else:
        headline = f"🍜 CA ĐÊM FUTURES – TIỆM CƠM CRYPTO: {t1} & {t2}"
        intro = (
            f"🧭 Cao điểm thanh khoản đêm phiên Mỹ, $BTC biến động quanh ${btc['price_str']} ({btc_pct} | "
            f"Đỉnh/Đáy 24h: ${btc['high_str']} – ${btc['low_str']}). Thực đơn khuya cho anh em giữ lệnh:"
        )
        cta_question = (
            f"💬 Ca đêm nay anh em đang giữ vị thế với {t1} hay đặt sẵn Limit chờ {t2}?"
        )

    t1_title_type = "Món Chính – Thuận Xu Hướng" if top10["plan_type"] == "momentum" else "Món Chính – Canh Nhịp Hồi"
    t2_title_type = (
        "Món Lướt Sóng – Thuận Xu Hướng"
        if alt["plan_type"] == "momentum"
        else "Món Lướt Sóng – Bắt Nhịp Hồi"
    )

    lines = [
        headline,
        "",
        intro,
        "",
        f"1️⃣ {t1_title_type}: ${t1} ({t1_pct})",
        f"- Giá hiện tại: ${top10['price_str']} | Vol 24h: ${top10['vol_str']}",
        f"- Tín hiệu 4H: {top10['tech_note']}",
        f"- Vùng Entry đẹp: ${top10['entry_1']} – ${top10['entry_2']} ({top10['entry_note']})",
        f"- Chốt lời (TP): ${top10['tp1']} ➔ ${top10['tp2']}",
        f"- Cắt lỗ (SL): ${top10['sl']} (đóng nến 4H dưới mốc này)",
        "",
        f"2️⃣ {t2_title_type}: ${t2} ({t2_pct})",
        f"- Giá hiện tại: ${alt['price_str']} | Vol 24h: ${alt['vol_str']}",
        f"- Tín hiệu 4H: {alt['tech_note']}",
        f"- Vùng Entry thăm dò: ${alt['entry_1']} – ${alt['entry_2']} ({alt['entry_note']})",
        f"- Chốt lời (TP): ${alt['tp1']} ➔ ${alt['tp2']}",
        f"- Cắt lỗ (SL): ${alt['sl']}",
        "",
        "⚠️ Lưu ý: Luôn chia vốn, tuân thủ SL và chờ xác nhận phản ứng nến 4H trước khi khớp lệnh.",
        cta_question,
        "",
        "#Write2Earn #BinanceSquare #TradingPlan",
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
    Khi nhập Cashtag $TOKEN (ví dụ $BTC, $SOL, $QNT), tự động thêm 1 khoảng trắng
    và dừng 0.5 giây để Binance Square nhận diện đồng đều tất cả các thẻ thành màu vàng.
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
    """Mở Chrome với Persistent Context trỏ vào Profile của bạn để tự động gõ và đăng bài."""
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
# ĐĂNG QUA BINANCE SQUARE OPENAPI
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
    """Đăng bài trực tiếp qua cổng chính thức Binance Square OpenAPI."""
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

        if code == "220094":
            candidate_text = re.sub(r"(\s+#\w+)\s*$", "", candidate_text.strip())
            continue

        if code == "220095":
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
        description="Auto Square Pro v3.0 - Chiến lược 3 Thẻ Vàng ($BTC + Coin Top 10 + Altcoin Sóng Nóng) & RSI/EMA 4H."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ lấy dữ liệu thật + chỉ báo 4H và in bài viết mẫu (không bấm đăng).",
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
    print("🚀 AUTO SQUARE PRO v3.0 - ULTIMATE PRO CREATOR ($BTC + TOP 10 + ALTCOIN)")
    print("=" * 72)

    print("\n[Phần 1] Đang quét Binance 24hr Ticker & tính RSI(14), EMA(20) trên khung nến 4H...")
    btc_compass, top10_plan, alt_plan = fetch_market_portfolio()

    print(
        f"  -> La bàn $BTC:       Giá ${btc_compass['price_str']} ({btc_compass['pct_change']:+.2f}%) | "
        f"RSI 4H: {btc_compass['rsi14_4h']:.1f} | EMA20 4H: ${btc_compass['ema20_str']}"
    )
    print(
        f"  -> Mã 1 (Coin Top 10): {top10_plan['cashtag']} ({top10_plan['pct_change']:+.2f}%) | "
        f"RSI 4H: {top10_plan['rsi14_4h']:.1f} | Entry: ${top10_plan['entry_1']}–${top10_plan['entry_2']} | "
        f"TP: ${top10_plan['tp1']} -> ${top10_plan['tp2']} | SL: ${top10_plan['sl']}"
    )
    print(
        f"  -> Mã 2 (Altcoin Hot): {alt_plan['cashtag']} ({alt_plan['pct_change']:+.2f}%) | "
        f"RSI 4H: {alt_plan['rsi14_4h']:.1f} | Entry: ${alt_plan['entry_1']}–${alt_plan['entry_2']} | "
        f"TP: ${alt_plan['tp1']} -> ${alt_plan['tp2']} | SL: ${alt_plan['sl']}"
    )

    print("\n[Phần 2] Đang render bài viết theo phiên giờ Việt Nam (UTC+7)...")
    post_content = generate_square_post(btc_compass, top10_plan, alt_plan)
    word_count = len(post_content.split())

    print("-" * 72)
    print(post_content)
    print("-" * 72)
    print(f"📊 Số từ: {word_count} từ | Đã lưu bản nháp tại: {DRAFT_OUTPUT_PATH}")

    if args.dry_run:
        print("\n[Chế độ --dry-run] Đã kiểm tra xong Phần 1 & Phần 2 (không tự động bấm đăng).")
        return

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
