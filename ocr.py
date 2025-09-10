# --- ocr.py 패치 ---
import io, json, re
from typing import Optional, Tuple
import numpy as np
from PIL import Image, ImageEnhance
import streamlit as st
import easyocr

@st.cache_resource(show_spinner=False)
def _reader():
    return easyocr.Reader(["ko", "en"], gpu=False)

def _norm_num(x) -> Optional[float]:
    if x is None: return None
    try:
        return float(str(x).replace(",", ".").strip())
    except Exception:
        return None

def _prep(arr, scale=1.6):
    # 고대비 + 업샘플 + 단순 임계로 7-seg 가독성 향상
    img = Image.fromarray(arr).convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.resize((int(img.width*scale), int(img.height*scale)), Image.LANCZOS)
    bw = img.point(lambda x: 255 if x > 140 else 0).convert("RGB")
    return np.array(bw)

def _best_number(tokens, allow_percent=False):
    nums = []
    for t in tokens or []:
        s = str(t)
        m = re.search(r"-?\d{1,3}(?:[.,]\d+)?", s)  # 3자리까지 허용
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
    if nums:
        nums_sorted = sorted(nums, key=lambda x: (0 if (isinstance(x, float) and x != int(x)) else 1, -x))
        return float(nums_sorted[0])

    # 🔁 보정 규칙: 3자리 정수(예: 235) → 23.5 처리
    for t in tokens or []:
        for m in re.finditer(r"\b(\d{3})\b", str(t)):
            v = int(m.group(1))
            if 100 <= v <= 500:
                v = v / 10.0
                if -10 <= v <= 50:
                    return float(v)
    return None

def _easyocr_candidates(pil_image: Image.Image):
    reader = _reader()
    arr = np.array(pil_image.convert("RGB"))
    H, W = arr.shape[:2]

    # 여러 분할비로 재시도
    for split in (0.55, 0.58, 0.52, 0.60):
        top = _prep(arr[: int(H * split), :, :])
        bot = _prep(arr[int(H * split) :, :, :])

        top_txts = reader.readtext(top, detail=0, paragraph=True, allowlist="0123456789.,°Cc")
        bot_txts = reader.readtext(bot, detail=0, paragraph=True, allowlist="0123456789.%")

        t_ez = _best_number(top_txts, allow_percent=False)
        h_ez = _best_number(bot_txts, allow_percent=True)
        if t_ez is not None or h_ez is not None:
            return t_ez, h_ez, (top_txts or []), (bot_txts or [])
    # 마지막 시도 결과 반환
    return t_ez, h_ez, (top_txts or []), (bot_txts or [])

@st.cache_resource(show_spinner=False)
def _gemini_model():
    import google.generativeai as genai
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model_name = st.secrets.get("GEMINI_MODEL", "gemini-1.5-flash")
    return genai.GenerativeModel(model_name)

def _extract_json_loose(text: str) -> Optional[dict]:
    if not text: return None
    t = text.strip().strip("`").strip()
    m = re.search(r"\{.*\}", t, flags=re.S)
    if not m: return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def _ask_gemini_for_final(pil_image: Image.Image, t_ez, h_ez, top_tokens, bot_tokens):
    model = _gemini_model()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    img_part = {"mime_type": "image/png", "data": buf.getvalue()}
    hint = {
        "easyocr_hint": {"temperature": t_ez, "humidity": h_ez},
        "top_roi_tokens": top_tokens[:6],
        "bot_roi_tokens": bot_tokens[:6],
    }
    prompt = f"""
다음 이미지는 디지털 온습도계 사진입니다.
EasyOCR 후보/토큰은 힌트일 뿐이며, 최종 정답을 판단하세요.
오직 아래 JSON만 반환:

{{"temperature": 23.5, "humidity": 58}}

규칙:
- 단위기호 제거(숫자만).
- 소수점 반영.
- EasyOCR 후보가 틀리면 이미지 기준으로 정정.
- 코드펜스/설명/추가키 금지. JSON만.
[힌트]
{json.dumps(hint, ensure_ascii=False)}
"""
    resp = model.generate_content([prompt, img_part])
    return (resp.text or "").strip()

def run_ocr(pil_image: Image.Image, img_bytes: bytes | None = None) -> dict:
    t_ez, h_ez, top_tokens, bot_tokens = _easyocr_candidates(pil_image)

    text = _ask_gemini_for_final(pil_image, t_ez, h_ez, top_tokens, bot_tokens)
    t = h = None

    data = _extract_json_loose(text)
    if data:
        t = _norm_num(data.get("temperature"))
        h = _norm_num(data.get("humidity"))
    else:
        # JSON 파싱 실패 → EasyOCR 후보 사용
        t, h = t_ez, h_ez

    pretty = f"{t:g} / {h:g}" if (t is not None and h is not None) else None
    return {"raw_text": "", "pretty": pretty, "date": None, "temperature": t, "humidity": h}
