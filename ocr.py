# ocr.py
import re
from datetime import datetime
from typing import Optional, Tuple

import numpy as np
from PIL import Image
import streamlit as st

# easyocr는 requirements에 있음
import easyocr


@st.cache_resource(show_spinner=False)
def _reader():
    # 한국어/영어 동시 인식
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
    """
    YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD / YYYY년 MM월 DD일 등 파싱
    """
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


def _extract_temp_hum_labeled(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    라벨 기반: 온도/습도, TEMP/HUM/RH 같은 단어 주변에서 수치 추출
    """
    t = None
    h = None

    # 온도
    for pat in [
        r"(온도|temperature|temp|t)\s*[:=]?\s*(-?\d{1,2}(?:[.,]\d)?)\s*(?:°|℃|c|C)?",
        r"(-?\d{1,2}(?:[.,]\d)?)\s*(?:°|℃|c|C)\b",
    ]:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            t = _norm_num(m.group(m.lastindex))
            break

    # 습도
    for pat in [
        r"(습도|humidity|hum|rh|h)\s*[:=]?\s*(\d{1,2}(?:[.,]\d)?)\s*%?",
        r"(\d{1,2}(?:[.,]\d)?)\s*%(\s|$)",
    ]:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            # 마지막 캡처 그룹이 수치
            h = _norm_num(m.group(m.lastindex))
            break

    return t, h


def _extract_temp_hum_combo(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    구분자 기반: 21 / 20, 21|20, 21,20, 21  20 등
    """
    # 다양한 구분자를 슬래시로 통일
    z = re.sub(r"[|,;/\t]", "/", text)
    z = re.sub(r"\s{2,}", " ", z)

    # 21 / 20 혹은 21/20 형태 우선
    m = re.search(r"\b(-?\d{1,2}(?:[.,]\d)?)\s*/\s*(\d{1,2}(?:[.,]\d)?)\b", z)
    if m:
        return _norm_num(m.group(1)), _norm_num(m.group(2))

    # 공백으로만 구분된 2숫자 (예: "21 20")
    m = re.search(r"\b(-?\d{1,2}(?:[.,]\d)?)\s+(\d{1,2}(?:[.,]\d)?)\b", z)
    if m:
        return _norm_num(m.group(1)), _norm_num(m.group(2))

    return None, None


def _extract_temp_hum_fallback(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    OCR이 "2120" 같이 붙여버린 경우 등 휴리스틱:
    - 연속 4자리면 앞 2자리/뒤 2자리로 분리해서 (온도 10~45, 습도 0~100) 범위 체크
    - 텍스트에서 1~2자리 숫자를 모두 모아 두 개만 남으면 그걸로 사용
    """
    # 1) 연속 4자리
    for m in re.finditer(r"\b(\d{4})\b", text):
        s = m.group(1)
        t, h = int(s[:2]), int(s[2:])
        if 10 <= t <= 45 and 0 <= h <= 100:
            return float(t), float(h)

    # 2) 1~2자리 숫자 토큰 모아 보기
    nums = [n for n in re.findall(r"\b\d{1,2}\b", text)]
    cand = []
    for i in range(len(nums) - 1):
        t = int(nums[i])
        h = int(nums[i + 1])
        if 10 <= t <= 45 and 0 <= h <= 100:
            cand.append((float(t), float(h)))
    if cand:
        return cand[0]

    return None, None


def _extract_temp_hum(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    온도/습도 추출 총합. 포매팅된 보기용 문자열도 함께 반환.
    우선순위: 라벨 → 구분자 → 휴리스틱
    """
    # 0) 전처리: 공백 줄이기, 한글 기호 통일
    z = text.replace("％", "%").replace("° C", "°C")
    z = re.sub(r"[ \t]+", " ", z)

    t, h = _extract_temp_hum_labeled(z)
    if t is None or h is None:
        t2, h2 = _extract_temp_hum_combo(z)
        t = t if t is not None else t2
        h = h if h is not None else h2
    if t is None or h is None:
        t2, h2 = _extract_temp_hum_fallback(z)
        t = t if t is not None else t2
        h = h if h is not None else h2

    pretty = f"{t:g} / {h:g}" if (t is not None and h is not None) else None
    return t, h, pretty


def run_ocr(pil_image: Image.Image) -> dict:
    """
    반환:
        {
          "raw_text": str,      # OCR 원문(줄바꿈 포함)
          "pretty": str|None,   # "21 / 20" 같이 보기 좋은 요약
          "date": "YYYY-MM-DD"|None,
          "temperature": float|None,
          "humidity": float|None,
        }
    """
    reader = _reader()
    arr = np.array(pil_image)
    # detail=0 → 문자열만, paragraph=True → 붙은 조각 합치기
    lines = reader.readtext(arr, detail=0, paragraph=True)
    if isinstance(lines, list):
        raw = "\n".join([str(x) for x in lines if str(x).strip()])
    else:
        raw = str(lines)

    # 날짜/온도/습도 파싱
    date_str = _extract_date(raw)
    t, h, pretty = _extract_temp_hum(raw)

    return {
        "raw_text": raw,
        "pretty": pretty,
        "date": date_str,
        "temperature": t,
        "humidity": h,
    }
