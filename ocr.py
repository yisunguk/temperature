# ocr.py ─ EasyOCR+전처리(+Gemini 폴백)
import re, io, os, base64
from datetime import datetime
from typing import Optional, Tuple
import numpy as np
from PIL import Image
import streamlit as st
import easyocr
import cv2

# ---- EasyOCR 캐시
@st.cache_resource(show_spinner=False)
def _reader():
    return easyocr.Reader(["ko", "en"], gpu=False)

def _norm_num(s: str) -> Optional[float]:
    if s is None: return None
    s = s.replace(",", ".").strip()
    try: return float(s)
    except: return None

def _extract_date(text: str) -> Optional[str]:
    text = text.replace(" ", "")
    m = re.search(r"(20\d{2})[.\-\/년](\d{1,2})[.\-\/월](\d{1,2})", text) or \
        re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if not m: return None
    y, mo, d = map(int, m.groups())
    try: return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError: return None

def _preprocess(gray: np.ndarray) -> np.ndarray:
    # 가벼운 노이즈 제거 → Otsu 이진화 → 살짝 팽창(세그먼트 끊김 방지)
    blur = cv2.GaussianBlur(gray, (3,3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    kernel = np.ones((2,2), np.uint8)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel, iterations=1)
    return bw

def _best_number_from_texts(tokens, allow_percent=False):
    nums = []
    for t in (tokens or []):
        s = str(t)
        m = re.search(r"-?\d{1,3}(?:[.,]\d)?", s)  # 소수 1자리까지
        if not m: continue
        v = _norm_num(m.group(0))
        if v is None: continue
        if allow_percent:
            if 0 <= v <= 100: nums.append(v)
        else:
            if -40 <= v <= 60: nums.append(v)   # 온도 합리 범위
    if not nums: return None
    # 소수점 있는 값을 우선
    nums.sort(key=lambda x: (0 if (isinstance(x, float) and x != int(x)) else 1, -x))
    return float(nums[0])

def _validate(t: Optional[float], h: Optional[float]) -> bool:
    return (t is not None and -40 <= t <= 60) and (h is not None and 0 <= h <= 100)

# ---- Gemini 폴백 (선택적)
def _gemini_fallback(img_bytes: Optional[bytes]) -> Tuple[Optional[float], Optional[float]]:
    """GOOGLE_API_KEY가 있을 때만 폴백 시도. 실패하면 (None, None)"""
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key or not img_bytes:
        return None, None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        prompt = (
            "You are reading only two numbers from a device display.\n"
            "Return STRICT JSON only with keys: "
            '{"temperature": float|null, "temp_unit":"C"|"F"|null, '
            '"humidity": float|null, "hum_unit":"%"|null, "confidence": float}.\n'
            "Rules: read digits only; no guesses; if unreadable use null. "
        )
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        img_part = {"mime_type": "image/jpeg", "data": base64.b64decode(b64)}
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content([prompt, img_part])
        text = resp.text.strip()
        # JSON 추출
        m = re.search(r"\{.*\}", text, re.S)
        if not m: return None, None
        import json
        data = json.loads(m.group(0))
        t = data.get("temperature"); h = data.get("humidity")
        # 단위 보정 (화씨 → 섭씨)
        if data.get("temp_unit") == "F" and isinstance(t,(int,float)):
            t = (t - 32) * 5.0/9.0
        return (float(t) if t is not None else None,
                float(h) if h is not None else None)
    except Exception:
        return None, None

def run_ocr(pil_image: Image.Image, img_bytes: Optional[bytes]=None) -> dict:
    reader = _reader()
    rgb = pil_image.convert("RGB")
    arr = np.array(rgb)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    H, W = arr.shape[:2]
    top = gray[: int(H*0.55), :]
    bot = gray[int(H*0.55):, :]

    top_bw = _preprocess(top)
    bot_bw = _preprocess(bot)

    # EasyOCR: 숫자 화이트리스트
    top_txts = reader.readtext(top_bw, detail=0, paragraph=True, allowlist="0123456789.,-")
    bot_txts = reader.readtext(bot_bw, detail=0, paragraph=True, allowlist="0123456789.%")

    all_txts = reader.readtext(arr, detail=0, paragraph=True)
    all_raw = "\n".join(map(str, all_txts)) if isinstance(all_txts, list) else str(all_txts)
    date_str = _extract_date(all_raw)

    t = _best_number_from_texts(top_txts, allow_percent=False)
    h = _best_number_from_texts(bot_txts, allow_percent=True)

    # 1차 결과가 불량이면 Gemini 폴백
    if not _validate(t, h):
        gt, gh = _gemini_fallback(img_bytes)
        if _validate(gt, gh):
            t, h = gt, gh

    pretty = f"{t:.1f} / {h:.1f}" if _validate(t, h) else None
    return {
        "raw_text": "",
        "pretty": pretty,
        "date": date_str,
        "temperature": t,
        "humidity": h,
    }
