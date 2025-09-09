# ocr.py — EasyOCR 후보 → Gemini가 최종 결정(정답 JSON) 버전
import io, json, re
from typing import Optional, Tuple
import numpy as np
from PIL import Image
import streamlit as st
import easyocr

# ── EasyOCR 준비 ───────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _reader():
    return easyocr.Reader(["ko", "en"], gpu=False)

def _norm_num(x) -> Optional[float]:
    if x is None: return None
    try:
        return float(str(x).replace(",", ".").strip())
    except Exception:
        return None

def _best_number(tokens, allow_percent=False):
    nums = []
    for t in tokens or []:
        s = str(t)
        m = re.search(r"-?\d{1,2}(?:[.,]\d+)?", s)
        if not m: 
            continue
        v = _norm_num(m.group(0))
        if v is None: 
            continue
        if allow_percent:
            if 0 <= v <= 100:
                nums.append(v)
        else:
            if -10 <= v <= 50:
                nums.append(v)
    if not nums:
        return None
    # 소수점 포함값 우선
    nums_sorted = sorted(nums, key=lambda x: (0 if (isinstance(x, float) and x != int(x)) else 1, -x))
    return float(nums_sorted[0])

def _easyocr_candidates(pil_image: Image.Image):
    reader = _reader()
    arr = np.array(pil_image.convert("RGB"))
    H, W = arr.shape[:2]
    top = arr[: int(H * 0.55), :, :]     # 온도 ROI
    bot = arr[int(H * 0.55) :, :, :]     # 습도 ROI

    # 숫자 위주
    top_txts = reader.readtext(top, detail=0, paragraph=True, allowlist="0123456789.,°Cc")
    bot_txts = reader.readtext(bot, detail=0, paragraph=True, allowlist="0123456789.%")

    t_ez = _best_number(top_txts, allow_percent=False)
    h_ez = _best_number(bot_txts, allow_percent=True)
    # Gemini 힌트로 주기 위해 원시 토큰도 넘겨둠
    return t_ez, h_ez, (top_txts or []), (bot_txts or [])

# ── Gemini 준비 ────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gemini_model():
    import google.generativeai as genai
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model_name = st.secrets.get("GEMINI_MODEL", "gemini-1.5-flash")
    return genai.GenerativeModel(model_name)

def _ask_gemini_for_final(pil_image: Image.Image, t_ez, h_ez, top_tokens, bot_tokens):
    """
    EasyOCR 후보 + 이미지 → Gemini에 던져 '정답' JSON 받기
    """
    model = _gemini_model()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    img_part = {"mime_type": "image/png", "data": buf.getvalue()}

    # 후보/토큰은 힌트로 제공하되, 최종 책임은 Gemini에 위임
    hint = {
        "easyocr_hint": {"temperature": t_ez, "humidity": h_ez},
        "top_roi_tokens": top_tokens[:6],   # 너무 길면 잘라서 힌트만
        "bot_roi_tokens": bot_tokens[:6],
    }

    prompt = f"""
다음 이미지는 디지털 온습도계 사진입니다.
EasyOCR이 추정한 후보값 및 ROI 토큰 힌트를 참고하되, 당신이 최종 정답을 판단하세요.
오직 온도(섭씨 ℃)와 습도(%) 숫자만 JSON으로 반환합니다.

반드시 이 형식의 '순수 JSON'만 출력:
{{"temperature": 23.5, "humidity": 58}}

규칙:
- 단위기호(℃, %)는 제거하고 숫자만.
- 소수점이 보이면 반영.
- EasyOCR 후보가 틀리면 무시하고 이미지로 판단.
- 설명/코드블록/추가키 금지. JSON 외 문자 금지.

[힌트]
{json.dumps(hint, ensure_ascii=False)}
"""

    resp = model.generate_content([prompt, img_part])
    return (resp.text or "").strip()

def run_ocr(pil_image: Image.Image, img_bytes: bytes | None = None) -> dict:
    # 1) EasyOCR로 후보 추출
    t_ez, h_ez, top_tokens, bot_tokens = _easyocr_candidates(pil_image)

    # 2) Gemini가 최종 판단
    text = _ask_gemini_for_final(pil_image, t_ez, h_ez, top_tokens, bot_tokens)

    # 3) JSON 파싱 → 실패 시 EasyOCR 폴백
    t = h = None
    try:
        data = json.loads(text)
        t = _norm_num(data.get("temperature"))
        h = _norm_num(data.get("humidity"))
    except Exception:
        # 폴백: EasyOCR 후보라도 쓰자
        t, h = t_ez, h_ez

    pretty = f"{t:g} / {h:g}" if (t is not None and h is not None) else None
    return {
        "raw_text": "",       # UI 비노출
        "pretty": pretty,     # "28.1 / 58" 등
        "date": None,         # 날짜는 요구 없음
        "temperature": t,
        "humidity": h,
    }
