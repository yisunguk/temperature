# ocr.py
import re
from datetime import datetime
from typing import Optional, Tuple, List

import numpy as np
from PIL import Image
import streamlit as st
import cv2  # opencv-python-headless
import easyocr


# ─────────────────────────────────────────────────────────────────────
# EasyOCR 리더 (캐시)
# ─────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _reader():
    # 온도계 숫자는 대부분 영문/숫자. ko도 포함해 혼선 방지(℃, % 등).
    return easyocr.Reader(["en", "ko"], gpu=False)


# ─────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────
def _norm_num(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", ".").strip()
    # 흔한 오인식 교정
    s = s.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    try:
        return float(s)
    except Exception:
        return None


def _clip01(v, a, b):
    v = float(v)
    return max(0.0, min(1.0, v))


def _roi(img: np.ndarray, x0=0.10, y0=0.05, x1=0.90, y1=0.55) -> np.ndarray:
    """
    상대좌표(0~1)로 ROI 잘라내기
    """
    H, W = img.shape[:2]
    x0, y0, x1, y1 = _clip01(x0,0,1)*W, _clip01(y0,0,1)*H, _clip01(x1,0,1)*W, _clip01(y1,0,1)*H
    x0, y0, x1, y1 = map(int, [x0, y0, x1, y1])
    return img[y0:y1, x0:x1].copy()


def _prep(roi: np.ndarray) -> np.ndarray:
    """
    전처리: 그레이 → CLAHE → 가우시안블러 → Otsu 이진화 → 팽창(숫자 굵게) → 2~3배 확대
    """
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    g = clahe.apply(g)
    g = cv2.GaussianBlur(g, (3,3), 0)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = 255 - th  # 밝은 숫자 / 어두운 배경인 경우가 더 잘 인식
    th = cv2.dilate(th, np.ones((2,2), np.uint8), iterations=1)
    scale = 2 if max(th.shape) > 500 else 3
    th = cv2.resize(th, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return th


def _read_texts(img_bin: np.ndarray) -> List[str]:
    reader = _reader()
    # 작은 조각으로 분리된 경우를 합치기 위해 paragraph=False로 여러 토큰을 받음
    texts = reader.readtext(img_bin, detail=0, paragraph=False, contrast_ths=0.05, adjust_contrast=0.7)
    # 공백·줄바꿈 정리
    clean = []
    for t in texts:
        t = str(t).strip()
        if not t:
            continue
        # 혼선 줄이기
        t = t.replace("％", "%").replace("° C", "°C")
        clean.append(t)
    return clean


def _parse_temperature(tokens: List[str]) -> Optional[float]:
    # 1) 28.1, 28,1, 28°C, 28.1°C 등
    joined = " ".join(tokens)
    m = re.search(r"(-?\d{2,3}[.,]\d)\s*(?:°|℃|C)?", joined)
    if m:
        return _norm_num(m.group(1))

    m = re.search(r"(-?\d{2,3})\s*(?:°|℃|C)\b", joined)
    if m:
        v = _norm_num(m.group(1))
        # 이 케이스는 소수점이 빠진 정수 온도
        return v

    # 2) 점이 빠진 3자리(예: 281 → 28.1) 휴리스틱
    m = re.search(r"\b(\d{3})\b", joined)
    if m:
        s = m.group(1)
        tt = float(s[:2]) + float(s[2:]) / 10.0
        if 10.0 <= tt <= 45.0:
            return tt

    # 3) 토큰 두 개가 28 과 .1 처럼 떨어진 경우
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if re.fullmatch(r"\d{2}", a) and re.fullmatch(r"[.,]?\d", b):
            tt = _norm_num(a + "." + b[-1])
            if tt and 10.0 <= tt <= 45.0:
                return tt

    # 4) 2자리 정수만 보이는 경우
    m = re.search(r"\b(-?\d{2})\b", joined)
    if m:
        v = _norm_num(m.group(1))
        if v and 10.0 <= v <= 45.0:
            return v

    return None


def _parse_humidity(tokens: List[str]) -> Optional[float]:
    joined = " ".join(tokens)
    # 58%, 58 % 와 같이
    m = re.search(r"\b(\d{1,3})\s*%?\b", joined)
    if m:
        v = _norm_num(m.group(1))
        if v is not None and 0 <= v <= 100:
            return v

    # 3~4자리 붙은 경우(예: 581 → 58.1 으로 잘못 읽히는 것을 방지해 정수 우선)
    m = re.search(r"\b(\d{2})\b", joined)
    if m:
        v = _norm_num(m.group(1))
        if v is not None and 0 <= v <= 100:
            return v

    return None


def _extract_date_from_any(text: str) -> Optional[str]:
    # 혹시 사진에 날짜가 찍히는 경우 보조
    s = text.replace(" ", "")
    m = re.search(r"(20\d{2})[.\-/년](\d{1,2})[.\-/월](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except Exception:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────
# 메인: run_ocr
# ─────────────────────────────────────────────────────────────────────
def run_ocr(pil_image: Image.Image) -> dict:
    """
    반환:
      {
        "raw_text": str,      # ROI들의 텍스트를 합친 원문
        "pretty": str|None,   # "28.1 / 58" 같이 보기 좋은 요약
        "date": "YYYY-MM-DD"|None,
        "temperature": float|None,
        "humidity": float|None,
      }
    """
    # PIL → np
    src = np.array(pil_image)
    if src.ndim == 2:
        src = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    elif src.shape[2] == 4:
        src = cv2.cvtColor(src, cv2.COLOR_BGRA2BGR)

    H, W = src.shape[:2]

    # ── ROI 설정(온도: 상단 5~55%, 습도: 하단 58~95%)
    temp_roi = _roi(src, 0.10, 0.05, 0.90, 0.55)
    hum_roi  = _roi(src, 0.10, 0.58, 0.90, 0.95)

    temp_bin = _prep(temp_roi)
    hum_bin  = _prep(hum_roi)

    # ── OCR
    temp_tokens = _read_texts(temp_bin)
    hum_tokens  = _read_texts(hum_bin)

    # 보조용: 전체에서 한 번 더(날짜 등)
    full_bin = _prep(src)
    all_tokens = _read_texts(full_bin)

    # ── 파싱
    t = _parse_temperature(temp_tokens) or _parse_temperature(all_tokens)
    h = _parse_humidity(hum_tokens) or _parse_humidity(all_tokens)
    date_str = _extract_date_from_any(" ".join(all_tokens))

    # 보기 좋은 표기
    pretty = f"{t:g} / {h:g}" if (t is not None and h is not None) else None

    # 원문(디버그 보기용): 각 ROI의 텍스트를 구분해서 합침
    raw_text = (
        "[TEMP ROI]\n" + " ".join(temp_tokens) + "\n\n"
        "[HUM ROI]\n"  + " ".join(hum_tokens)  + "\n\n"
        "[FULL]\n"     + " ".join(all_tokens)
    )

    return {
        "raw_text": raw_text,
        "pretty": pretty,
        "date": date_str,
        "temperature": t,
        "humidity": h,
    }
