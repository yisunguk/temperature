# ocr.py
from typing import Optional, Dict
import numpy as np
from PIL import Image
import re
import streamlit as st
import easyocr
from dateutil import parser as dateparser
from datetime import datetime

@st.cache_resource(show_spinner=False)
def _get_reader():
    # 한글+영문
    return easyocr.Reader(['ko', 'en'], gpu=False)

def image_to_ndarray(img: Image.Image) -> np.ndarray:
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)

def run_ocr(pil_image: Image.Image) -> Dict:
    reader = _get_reader()
    arr = image_to_ndarray(pil_image)
    results = reader.readtext(arr, detail=0, paragraph=True)
    full_text = "\n".join(results)
    parsed = parse_fields(full_text)
    parsed["raw_text"] = full_text
    return parsed

_temp_pat = re.compile(r'(-?\d+(?:\.\d+)?)\s*(?:°|도|℃|C)\b', re.IGNORECASE)
_hum_pat  = re.compile(r'(\d{1,3}(?:\.\d+)?)\s*%\b')
# 예: 2025-09-09, 25/09/2025, 2025.09.09, 09-09-2025, 9월 9일, 2025년 9월 9일 등
_date_candidates = re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2}|'
                              r'\d{1,2}[-./]\d{1,2}[-./]\d{2,4}|'
                              r'\d{4}년\s*\d{1,2}월\s*\d{1,2}일|'
                              r'\d{1,2}월\s*\d{1,2}일)')

def parse_fields(text: str) -> Dict[str, Optional[str]]:
    temp = None
    humid = None
    date_str = None

    # 온도
    t = _temp_pat.search(text)
    if t:
        try:
            temp = float(t.group(1))
        except:
            pass

    # 습도
    h = _hum_pat.search(text)
    if h:
        try:
            humid = float(h.group(1))
        except:
            pass

    # 날짜
    d = _date_candidates.search(text)
    if d:
        cand = d.group(1)
        try:
            # '9월 9일' 같은 경우 연도가 없으면 오늘 연도 가정
            default_dt = datetime.now()
            dt = dateparser.parse(cand, default=default_dt, dayfirst=False, yearfirst=True, fuzzy=True)
            date_str = dt.strftime("%Y-%m-%d")
        except:
            pass

    return {"date": date_str, "temperature": temp, "humidity": humid}
