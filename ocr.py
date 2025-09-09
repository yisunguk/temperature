# ocr.py ─ run_ocr() 교체
import re
from datetime import datetime
from typing import Optional, Tuple
import numpy as np
from PIL import Image
import streamlit as st
import easyocr

@st.cache_resource(show_spinner=False)
def _reader():
    return easyocr.Reader(["ko", "en"], gpu=False)

def _norm_num(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.replace(",", ".").strip()
    try:
        return float(s)
    except Exception:
        return None

def _extract_date(text: str) -> Optional[str]:
    text = text.replace(" ", "")
    m = re.search(r"(20\d{2})[.\-\/년](\d{1,2})[.\-\/월](\d{1,2})", text)
    if not m:
        m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None

def _best_number(tokens, allow_percent=False):
    """
    토큰 리스트에서 가장 '그럴듯한' 수치 하나 고르기
    - 소수점 있는 값 우선 (온도)
    - 퍼센트/정수(0~100) (습도)
    """
    nums = []
    for t in tokens:
        s = str(t)
        # 숫자 + (선택)소수점 한 번
        m = re.search(r"-?\d{1,2}(?:[.,]\d+)?", s)
        if m:
            v = _norm_num(m.group(0))
            if v is None:
                continue
            if allow_percent:
                if 0 <= v <= 100:
                    nums.append(v)
            else:
                # 온도는 -10~50 정도로 제한
                if -10 <= v <= 50:
                    nums.append(v)
    if not nums:
        return None
    # 온도는 소수점 있는 값을 우선
    nums_sorted = sorted(nums, key=lambda x: (0 if (isinstance(x, float) and (x != int(x))) else 1, -x))
    return float(nums_sorted[0])

def run_ocr(pil_image: Image.Image) -> dict:
    reader = _reader()
    img = pil_image.convert("RGB")
    arr = np.array(img)

    H, W = arr.shape[:2]
    # 상/하 ROI 비율 (상단 55% = 온도, 하단 45% = 습도)
    top = arr[: int(H * 0.55), :, :]
    bot = arr[int(H * 0.55) :, :, :]

    # 숫자 위주로 읽기 (allowlist)
    top_txts = reader.readtext(top, detail=0, paragraph=True, allowlist="0123456789.,°Cc")
    bot_txts = reader.readtext(bot, detail=0, paragraph=True, allowlist="0123456789.%")

    # 백업: 전체에서 날짜 등 뽑기(있으면)
    all_txts = reader.readtext(arr, detail=0, paragraph=True)
    all_raw = "\n".join([str(x) for x in all_txts]) if isinstance(all_txts, list) else str(all_txts)
    date_str = _extract_date(all_raw)

    # 상단에서 온도, 하단에서 습도 베스트 추출
    t = _best_number(top_txts or [])
    h = _best_number(bot_txts or [], allow_percent=True)

    pretty = f"{t:g} / {h:g}" if (t is not None and h is not None) else None

    # UI에는 원문을 내보내지 않음
    return {
        "raw_text": "",        # ← 비워서 UI에 노출될 일이 없도록
        "pretty": pretty,      # "23.5 / 30" 등
        "date": date_str,
        "temperature": t,
        "humidity": h,
    }
