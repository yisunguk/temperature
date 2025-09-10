# app.py
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import streamlit as st
from oauth_google import ensure_user_drive_creds, logout_button
from ui import render_header, input_panel, extracted_edit_fields, table_view
from ocr import run_ocr
from oauth_google import ensure_user_drive_creds          # OAuth 로그인 (사진 업로드용)
from storage import read_dataframe, append_row            # Sheets는 서비스계정
from storage import upload_image_to_drive_user, diagnose_permissions

# app.py 상단
import requests  # ← 추가

OPEN_METEO_LAT = 34.9414   # Gwangyang
OPEN_METEO_LON = 127.69569
OPEN_METEO_TZ  = "Asia/Seoul"

def fetch_current_apparent_temp(lat=OPEN_METEO_LAT, lon=OPEN_METEO_LON, tz=OPEN_METEO_TZ):
    """Open-Meteo 현재 체감온도/기온/습도 조회"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "apparent_temperature,temperature_2m,relative_humidity_2m",
        "timezone": tz,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    cur = j.get("current", {}) or {}
    return {
        "time": cur.get("time"),  # ISO string (Asia/Seoul)
        "apparent_temperature": cur.get("apparent_temperature"),
        "temperature_2m": cur.get("temperature_2m"),
        "relative_humidity_2m": cur.get("relative_humidity_2m"),
    }


st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")
TZ = st.secrets.get("TIMEZONE", "Asia/Seoul")


def _to_float(x):
    try:
        return float(x) if x not in (None, "") else None
    except Exception:
        return None

# ── Heat Index(체감온도) 계산 + 알람 분류 ───────────────────────────────────────
def _heat_index_celsius(temp_c, rh):
    try:
        if temp_c is None or rh is None:
            return None
        T = float(temp_c); R = float(rh)
    except Exception:
        return None
    if math.isnan(T) or math.isnan(R):
        return None
    # 적용 조건 미만이면 실제온도 반환
    if T < 26.7 or R < 40:
        return round(T, 1)
    Tf = T * 9.0 / 5.0 + 32.0
    HI_f = (
        -42.379 + 2.04901523 * Tf + 10.14333127 * R
        - 0.22475541 * Tf * R - 0.00683783 * Tf * Tf
        - 0.05481717 * R * R + 0.00122874 * Tf * Tf * R
        + 0.00085282 * Tf * R * R - 0.00000199 * Tf * Tf * R * R
    )
    if (R < 13) and (80 <= Tf <= 112):
        HI_f -= ((13 - R) / 4) * math.sqrt((17 - abs(Tf - 95)) / 17)
    elif (R > 85) and (80 <= Tf <= 87):
        HI_f += ((R - 85) / 10) * ((87 - Tf) / 5)
    return round((HI_f - 32.0) * 5.0 / 9.0, 1)

def _alarm_from_hi(hi_c, show_normal: bool = True):
    if hi_c is None:
        return "정상" if show_normal else ""
    try:
        x = float(hi_c)
    except Exception:
        return "정상" if show_normal else ""
    if x >= 40:
        return "위험"
    if x >= 38:
        return "경고"
    if x >= 35:
        return "주의"
    if x >= 32:
        return "관심"
    return "정상" if show_normal else ""



def main():
    render_header()
    # app.py의 main() 안, render_header() 바로 아래 등 적절한 위치
    # ▶ 앱 실행 시점의 "현재 날씨(광양)" 체감온도 표시
    try:
        now = fetch_current_apparent_temp()
        hi_now = now["apparent_temperature"]  # feels-like (open-meteo)
        alarm_now = _alarm_from_hi(hi_now)    # 기존 라벨 함수 재사용
        cols = st.columns([1,1,1])
        with cols[0]:
            st.metric("광양 체감온도(℃)", f"{hi_now:.1f}" if hi_now is not None else "-")
        with cols[1]:
            st.metric("기온(℃)", f"{now['temperature_2m']:.1f}" if now["temperature_2m"] is not None else "-")
        with cols[2]:
            st.metric("습도(%)", f"{now['relative_humidity_2m']:.0f}" if now["relative_humidity_2m"] is not None else "-")

        # 알림 뱃지
        color = {"정상":"#10b981","관심":"#3b82f6","주의":"#f59e0b","경고":"#ef4444","위험":"#7f1d1d"}.get(alarm_now, "#6b7280")
        st.markdown(
            f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;background:{color};color:white;font-weight:600'>"
            f"{alarm_now}</div> "
            f"<span style='color:#6b7280'>기준시각: {now.get('time') or '알 수 없음'}</span>",
            unsafe_allow_html=True
        )
        st.divider()
    except Exception as e:
        st.info(f"현재 날씨 조회 실패: {e}")

    # 상단 표 로딩 (Sheets 서비스계정)
    try:
        df = read_dataframe()
        table_view(df)
    except Exception:
        st.error("Google Sheets에 접근할 수 없습니다. 권한/ID를 확인하세요.")
        st.code(diagnose_permissions(), language="python")
        st.stop()

    st.divider()
    st.subheader("입력")

    # ✅ 사용자 OAuth 로그인 (My Drive에 업로드하기 위해)
    creds = ensure_user_drive_creds()

    with st.expander("🔎 로그인 진단", expanded=False):
        st.write("has_creds:", bool(creds and creds.valid))
        st.write("in_session:", "__google_token__" in st.session_state)
        try:
            from oauth_google import cookies
            st.write("cookie_present:", bool(cookies.get("gdrive_oauth")))
        except Exception:
            st.write("cookie_present: N/A")

    # 이미지 입력 (카메라/업로드)
    pil_img, img_bytes, src = input_panel()
    if img_bytes:
        st.session_state["__img_bytes__"] = img_bytes

    if pil_img is None or img_bytes is None:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")
        return

    with st.expander("이미지 미리보기", expanded=True):
        st.image(pil_img, caption="입력 이미지")

    with st.spinner("OCR 추출 중..."):
        result = run_ocr(pil_img, st.session_state.get("__img_bytes__"))

    st.success("OCR 추출 완료!")
    if result.get("pretty"):
        col1, col2 = st.columns(2)
        with col1:
            st.metric("온도(℃)", f"{result['temperature']:.1f}" if result['temperature'] is not None else "-")
        with col2:
            st.metric("습도(%)", f"{result['humidity']:.1f}" if result['humidity'] is not None else "-")

    # ✔ 폼은 값 편집만 담당 (저장 버튼은 폼 밖에서!)
    date_str, temp, hum = extracted_edit_fields(
        result.get("date"),
        result.get("temperature"),
        result.get("humidity"),
    )

    # 날짜 기본값
    if not date_str:
        date_str = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")

    # 이미지 MIME
    fmt = (getattr(pil_img, "format", "") or "").upper()
    mime = "image/png" if fmt == "PNG" else "image/jpeg"

    # ✅ 독립 저장 버튼: 모바일/웹 모두 확실히 동작
    if st.button("💾 저장 (Drive + Sheet)", key="save_btn", use_container_width=False, width="stretch"):
        if "__img_bytes__" not in st.session_state:
            st.error("이미지 데이터를 찾을 수 없습니다. 다시 업로드/촬영해 주세요.")
            return
        try:
            # My Drive 업로드 (로그인 사용자)
            link = upload_image_to_drive_user(
                creds,
                st.session_state["__img_bytes__"],
                filename_prefix="env_photo",
                mime_type=mime,
            )
            # ▶ Heat Index + 알람 계산
            t = _to_float(temp)
            h = _to_float(hum)
            hi = _heat_index_celsius(t, h)
            alarm = _alarm_from_hi(hi)

            # ▶ 시트 한 줄 추가 (체감온도/알람 포함)
            append_row(date_str, t, h, hi, alarm, link)  # ← 확장된 시그니처
            st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류: {e}")


if __name__ == "__main__":
    main()
