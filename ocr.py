# ocr.py
import re
from datetime import datetime
from typing import Optional, Tuple, List

import numpy as np
from PIL import Image
import streamlit as st
import cv2
import easyocr

def _order_pts(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # TL
    rect[2] = pts[np.argmax(s)]   # BR
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # TR
    rect[3] = pts[np.argmax(diff)]  # BL
    return rect

def _four_point_warp(gray: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_pts(pts.astype("float32"))
    (tl, tr, br, bl) = rect
    wA = np.linalg.norm(br - bl)
    wB = np.linalg.norm(tr - tl)
    hA = np.linalg.norm(tr - br)
    hB = np.linalg.norm(tl - bl)
    maxW = int(max(wA, wB))
    maxH = int(max(hA, hB))
    dst = np.array([[0,0],[maxW-1,0],[maxW-1,maxH-1],[0,maxH-1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(gray, M, (maxW, maxH))

def _find_display_quad(gray: np.ndarray) -> np.ndarray:
    """
    사진 크기/기울기와 무관하게 LCD 표시부(사각형)를 찾아 원근 보정한 이미지를 반환.
    못 찾으면 기존 방식(가장 큰 사각형 → 크롭)으로 폴백.
    """
    h, w = gray.shape[:2]
    scale = 900.0 / max(h, w)
    small = cv2.resize(gray, (int(w*scale), int(h*scale)))
    blur  = cv2.GaussianBlur(small, (5,5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3,3), np.uint8), 1)

    contours,_ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:12]

    quad = None
    best_score = 0.0
    for c in contours:
        peri   = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02*peri, True)
        if len(approx) != 4:
            continue
        area = cv2.contourArea(approx)
        if area < 0.05 * small.shape[0] * small.shape[1]:
            continue  # 너무 작으면 제외(줌아웃이면 0.03 정도로 더 낮춰도 됨)

        pts  = approx.reshape(4,2).astype("float32")
        rect = _order_pts(pts)
        wA = np.linalg.norm(rect[1]-rect[0]); wB = np.linalg.norm(rect[2]-rect[3])
        hA = np.linalg.norm(rect[3]-rect[0]); hB = np.linalg.norm(rect[2]-rect[1])
        ar = max(wA,wB) / max(hA,hB)  # 가로/세로 비
        if not (0.8 <= ar <= 1.9):    # LCD 화면은 대개 납작한 직사각형
            continue

        # 직사각형에 가까울수록 가산점
        score = area * (1.0 / (abs(wA-wB)+abs(hA-hB)+1))
        if score > best_score:
            best_score = score
            quad = (pts / scale)

    if quad is not None:
        return _four_point_warp(gray, quad)

    # 폴백: 가장 큰 바운딩 박스
    _blur = cv2.GaussianBlur(gray, (5,5), 0)
    _ed   = cv2.Canny(_blur, 50, 150)
    _ed   = cv2.dilate(_ed, np.ones((3,3), np.uint8), 1)
    cnts,_ = cv2.findContours(_ed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        x,y,w2,h2 = cv2.boundingRect(max(cnts, key=cv2.contourArea))
        return gray[y:y+h2, x:x+w2].copy()

    return gray  # 최종 폴백

# ──────────────────────────────────────────────────────────────────
# EasyOCR 리더 (캐시)
# ──────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _reader():
    # 숫자만 주로 읽되 기호 일부 허용
    return easyocr.Reader(["en"], gpu=False)


# ──────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────
def _norm_num(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", ".").strip()
    # 흔한 오인식 교정
    s = (
        s.replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("l", "1")
        .replace("％", "%")
    )
    try:
        return float(s)
    except Exception:
        return None


def _to_bgr(a: np.ndarray) -> np.ndarray:
    if a.ndim == 2:
        return cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    if a.shape[2] == 4:
        return cv2.cvtColor(a, cv2.COLOR_BGRA2BGR)
    return a


def _largest_rect(gray: np.ndarray) -> tuple[int, int, int, int]:
    """
    LCD 표시부(안쪽 사각형) 대략 검출.
    못 찾으면 전체 반환.
    """
    h, w = gray.shape[:2]
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_best, rect_best = 0, (0, 0, w, h)
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        ar = cw / max(ch, 1)
        if area > area_best and 0.5 < ar < 2.5 and area > (w * h) * 0.2:
            area_best = area
            rect_best = (x, y, cw, ch)
    return rect_best


def _adaptive_bin(gray: np.ndarray) -> np.ndarray:
    # 명암 대비가 균일하지 않아도 잘 되는 적응형 이진화
    gray = cv2.medianBlur(gray, 3)
    th = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 5
    )
    inv = 255 - th
    return inv


def _split_by_separator(bin_img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    LCD 안쪽에서 가장 강한 수평 분리선(윗부분/아랫부분 경계)을 찾아 상·하 ROI 반환.
    못 찾으면 55% 지점에서 자름.
    """
    h, w = bin_img.shape[:2]
    # 각 행의 잉크(검정) 양
    row_ink = (bin_img > 0).sum(axis=1)
    # 가운데 근처(35%~80%)에서 최소값(선) 찾기
    y0, y1 = int(h * 0.35), int(h * 0.80)
    idx = np.argmin(row_ink[y0:y1]) + y0
    # 너무 약하면 기본값
    if row_ink[idx] > row_ink.mean() * 0.9:
        idx = int(h * 0.55)

    margin = int(h * 0.03)
    top = bin_img[: max(idx - margin, 0), :]
    bot = bin_img[min(idx + margin, h) :, :]
    return top, bot


def _scale(img: np.ndarray, factor: int = 3) -> np.ndarray:
    return cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


def _read_tokens(img_bin: np.ndarray) -> List[str]:
    rdr = _reader()
    # 숫자/점/퍼센트만 허용 → 잡문자 차단
    toks = rdr.readtext(
        img_bin,
        detail=0,
        paragraph=False,
        allowlist="0123456789.%",  # easyocr 1.7+ 지원
        contrast_ths=0.05,
        adjust_contrast=0.7,
    )
    clean = [t.strip() for t in toks if str(t).strip()]
    return clean


def _parse_temperature(tokens: List[str]) -> Optional[float]:
    s = " ".join(tokens)
    # 28.1 / 28,1 / 28°
    m = re.search(r"(-?\d{2,3}[.,]\d)\b", s)
    if m:
        return _norm_num(m.group(1))
    m = re.search(r"\b(-?\d{2,3})\b", s)
    if m:
        v = _norm_num(m.group(1))
        if v and 10 <= v <= 45:
            return v
    # 281 → 28.1 휴리스틱
    m = re.search(r"\b(\d{3})\b", s)
    if m:
        z = m.group(1)
        v = float(z[:2]) + float(z[2:]) / 10.0
        if 10 <= v <= 45:
            return v
    return None


def _parse_humidity(tokens: List[str]) -> Optional[float]:
    s = " ".join(tokens)
    m = re.search(r"\b(\d{1,3})\s*%?\b", s)
    if m:
        v = _norm_num(m.group(1))
        if v is not None and 0 <= v <= 100:
            return v
    return None


def _extract_date(all_text: str) -> Optional[str]:
    t = all_text.replace(" ", "")
    m = re.search(r"(20\d{2})[.\-/년](\d{1,2})[.\-/월](\d{1,2})", t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime(
                "%Y-%m-%d"
            )
        except Exception:
            return None
    return None


# ──────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────
def run_ocr(pil_image: Image.Image) -> dict:
    """
    반환:
      raw_text : ROI별 텍스트
      pretty  : "28.1 / 58" 형태
      date    : YYYY-MM-DD | None
      temperature, humidity : float | None
    """
    src = _to_bgr(np.array(pil_image))
    gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)

    # 1) LCD 표시부 대략 검출 후 크롭
    lcd = _find_display_quad(gray)


    # 2) 이진화 → 분리선으로 상/하 분할
    bin_all = _adaptive_bin(lcd)
    top_bin, bot_bin = _split_by_separator(bin_all)

    # 3) 확대 + 소량 팽창(선명도 ↑)
    top_bin = cv2.dilate(_scale(top_bin, 3), np.ones((2, 2), np.uint8), 1)
    bot_bin = cv2.dilate(_scale(bot_bin, 3), np.ones((2, 2), np.uint8), 1)

    # 4) OCR(숫자/점/%만 허용)
    top_tokens = _read_tokens(top_bin)
    bot_tokens = _read_tokens(bot_bin)
    all_tokens = _read_tokens(_scale(bin_all, 2))

    # 5) 파싱
    t = _parse_temperature(top_tokens) or _parse_temperature(all_tokens)
    h = _parse_humidity(bot_tokens) or _parse_humidity(all_tokens)
    date_str = _extract_date(" ".join(all_tokens))

    pretty = f"{t:g} / {h:g}" if (t is not None and h is not None) else None
    raw_text = (
        "[TEMP ROI]\n" + " ".join(top_tokens) + "\n\n"
        "[HUM ROI]\n"  + " ".join(bot_tokens) + "\n\n"
        "[FULL]\n"     + " ".join(all_tokens)
    )

    return {
        "raw_text": raw_text,
        "pretty": pretty,
        "date": date_str,
        "temperature": t,
        "humidity": h,
    }
