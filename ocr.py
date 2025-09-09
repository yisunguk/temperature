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


def _extract_temp_hum_labeled(text: str) -> Tuple[Optional[float], Optional[float]]:
    t = None
    h = None

    for pat in [
        r"(온도|temperature|temp|t)\s*[:=]?\s*(-?\d{1,2}(?:[.,]\d)?)\s*(?:°|℃|c|C)?",
        r"(-?\d{1,2}(?:[.,]\d)?)\s*(?:°|℃|c|C)\b",
    ]:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            t = _norm_num(m.group(m.lastindex))
            break

    for pat in [
        r"(습도|humidity|hum|rh|h)\s*[:=]?\s*(\d{1,2}(?:[.,]\d)?)\s*%?",
        r"(\d{1,2}(?:[.,]\d)?)\s*%(\s|$)",
    ]:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            h = _norm_num(m.group(m.lastindex))
            break

    return t, h


def _extract_temp_hum_combo(text: str) -> Tuple[Optional[float], Optional[float]]:
    z = re.sub(r"[|,;/\t]", "/", text)
    z = re.sub(r"\s{2,}", " ", z)

    m = re.search(r"\b(-?\d{1,2}(?:[.,]\d)?)\s*/\s*(\d{1,2}(?:[.,]\d)?)\b", z)
    if m:
        return _norm_num(m.group(1)), _norm_num(m.group(2))

    m = re.search(r"\b(-?\d{1,2}(?:[.,]\d)?)\s+(\d{1,2}(?:[.,]\d)?)\b", z)
    if m:
        return _norm_num(m.group(1)), _norm_num(m.group(2))

    return None, None


def _extract_temp_hum_fallback(text: str) -> Tuple[Optional[float], Optional[float]]:
    for m in re.finditer(r"\b(\d{4})\b", text):
        s = m.group(1)
        t, h = int(s[:2]), int(s[2:])
        if 10 <= t <= 45 and 0 <= h <= 100:
            return float(t), float(h)

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
    reader = _reader()
    arr = np.array(pil_image)
    lines = reader.readtext(arr, detail=0, paragraph=True)

    if isinstance(lines, list):
        raw = "\n".join([str(x) for x in lines if str(x).strip()])
    else:
        raw = str(lines)

    date_str = _extract_date(raw)
    t, h, pretty = _extract_temp_hum(raw)

    # 🔹 원문 대신 "온도 / 습도"만 정리해서 보여주기
    clean_text = pretty if pretty else ""

    return {
        "raw_text": clean_text,
        "pretty": pretty,
        "date": date_str,
        "temperature": t,
        "humidity": h,
    }
