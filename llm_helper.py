# llm_helper.py
import json, re
from io import BytesIO
import streamlit as st
import google.generativeai as genai

def _model():
    api = st.secrets.get("GEMINI_API_KEY")
    if not api:
        raise RuntimeError("GEMINI_API_KEY is missing in secrets.toml")
    genai.configure(api_key=api)
    # 정확도/비용 균형: 1.5-flash, 필요 시 pro로 바꿀 수 있음
    return genai.GenerativeModel("gemini-1.5-flash")

def _to_jpeg_bytes(pil_img) -> bytes:
    buf = BytesIO()
    pil_img.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()

def gemini_extract_th_from_image(pil_img):
    """
    이미지 한 장으로부터 섭씨 온도·상대습도를 JSON으로 받아옵니다.
    반환: (t: float|None, h: float|None)
    """
    prompt = (
        "You're reading a photo of a digital thermometer-hygrometer display. "
        "Return strict JSON with two numbers in this exact schema:\n"
        '{"temperature": <celsius float>, "humidity": <percent float>} '
        "No text, no explanation."
    )
    img_part = {"mime_type":"image/jpeg", "data": _to_jpeg_bytes(pil_img)}
    res = _model().generate_content([prompt, img_part])

    txt = (res.text or "").strip()
    # 코드펜스 제거
    txt = re.sub(r"```json|```", "", txt).strip()
    try:
        obj = json.loads(txt)
        t = obj.get("temperature", None)
        h = obj.get("humidity", None)
        # 숫자 강제 변환 시도
        t = float(t) if t is not None else None
        h = float(h) if h is not None else None
        return t, h
    except Exception:
        return None, None
