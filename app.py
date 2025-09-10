# app.py
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import streamlit as st
from oauth_google import ensure_user_drive_creds, logout_button
from ui import render_header, input_panel, extracted_edit_fields, table_view
from ocr import run_ocr
from storage import read_dataframe, append_row            # 확장된 시그니처 사용(일자/시간/작업장 포함)
from storage import upload_image_to_drive_user, diagnose_permissions

# 외부 API
import requests

# ── Open-Meteo 설정(광양) ─────────────────────────────────────────────────────
OPEN_METEO_LAT = 34.9414
OPEN_METEO_LON = 127.69569
OPEN_METEO_TZ  = "Asia/Seoul"

def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "알 수 없음"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts.replace("T", " ")

def fetch_current_apparent_temp(lat=OPEN_METEO_LAT, lon=OPEN_METEO_LON, tz=OPEN_METEO_TZ):
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
        "time": cur.get("time"),
        "apparent_temperature": cur.get("apparent_temperature"),
        "temperature_2m": cur.get("temperature_2m"),
        "relative_humidity_2m": cur.get("relative_humidity_2m"),
    }

st.set_page_config(page_title="광양 LNG Jetty 인프라 현장 체감온도 기록기", layout="centered")
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
    if T < 26.7 or R < 40:  # 적용 조건 미만이면 실제온도 반환
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
    if x >= 40: return "위험"
    if x >= 38: return "경고"
    if x >= 35: return "주의"
    if x >= 32: return "관심"
    return "정상" if show_normal else ""

def alarm_badge(alarm: str) -> str:
    colors = {
        "정상": "#10b981", "관심": "#3b82f6", "주의": "#f59e0b", "경고": "#ef4444", "위험": "#7f1d1d",
    }
    color = colors.get(alarm, "#6b7280")
    return (
        f"<span style='display:inline-block;padding:4px 10px;"
        f"border-radius:999px;background:{color};color:white;font-weight:600'>{alarm}</span>"
    )

def main():
    render_header()

    # ▶ 실행 시점 현재(광양) 체감온도 표시
    try:
        now = fetch_current_apparent_temp()
        hi_now = now["apparent_temperature"]
        alarm_now = _alarm_from_hi(hi_now)
        cols = st.columns([1, 1, 1])
        with cols[0]:
            st.metric("광양 체감온도(℃)", f"{hi_now:.1f}" if hi_now is not None else "-")
        with cols[1]:
            st.metric("기온(℃)", f"{now['temperature_2m']:.1f}" if now["temperature_2m"] is not None else "-")
        with cols[2]:
            st.metric("습도(%)", f"{now['relative_humidity_2m']:.0f}" if now["relative_humidity_2m"] is not None else "-")
        color = {"정상":"#10b981","관심":"#3b82f6","주의":"#f59e0b","경고":"#ef4444","위험":"#7f1d1d"}.get(alarm_now, "#6b7280")
        st.markdown(
            f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;background:{color};color:white;font-weight:600'>"
            f"{alarm_now}</div> <span style='color:#6b7280'>기준시각: {_fmt_ts(now.get('time'))}</span>",
            unsafe_allow_html=True
        )
        st.divider()
    except Exception as e:
        st.info(f"현재 날씨 조회 실패: {e}")

    # ── 상단 테이블 (Sheets) ────────────────────────────────────────────────
    try:
        df = read_dataframe()
        table_view(df)
    except Exception:
        st.error("Google Sheets에 접근할 수 없습니다. 권한/ID를 확인하세요.")
        st.code(diagnose_permissions(), language="python")
        st.stop()

    st.divider()
    st.subheader("온습도계의 사진을 촬영하거나 갤러리에서 업로드해 주세요")

    # ✅ 사용자 OAuth (My Drive 업로드)
    creds = ensure_user_drive_creds()
    with st.expander("🔎 로그인 진단", expanded=False):
        st.write("has_creds:", bool(creds and creds.valid))
        st.write("in_session:", "__google_token__" in st.session_state)
        try:
            from oauth_google import cookies
            st.write("cookie_present:", bool(cookies.get("gdrive_oauth")))
        except Exception:
            st.write("cookie_present: N/A")

    # ── 이미지 입력 ──────────────────────────────────────────────────────────
    pil_img, img_bytes, src = input_panel()
    if img_bytes:
        st.session_state["__img_bytes__"] = img_bytes
        # ✔ 업로드/촬영 시각 기록(기본값으로 사용)
        st.session_state["__uploaded_at__"] = datetime.now(ZoneInfo(TZ))

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
            st.metric("습도(%))", f"{result['humidity']:.1f}" if result['humidity'] is not None else "-")

    # ── 입력 폼(일자·시간·온도·습도·작업장) ─────────────────────────────────────
    init_dt = st.session_state.get("__uploaded_at__") or datetime.now(ZoneInfo(TZ))
    init_date = init_dt.strftime("%Y-%m-%d")
    init_time = init_dt.strftime("%H:%M")
    last_place = st.session_state.get("__last_place__", "")

    # 새/구 UI 함수 모두 호환되도록 처리
    try:
        fields = extracted_edit_fields(
            result.get("date") or init_date,
            init_time,
            result.get("temperature"),
            result.get("humidity"),
            initial_place=last_place,
        )
    except TypeError:
        # 구버전 UI: (date, temp, hum)만 반환
        fields = extracted_edit_fields(
            result.get("date") or init_date,
            result.get("temperature"),
            result.get("humidity"),
        )

    # 반환값 해석 (5-tuple or 3-tuple)
    date_str = init_date
    time_str = init_time
    temp = hum = None
    place = last_place
    if isinstance(fields, (list, tuple)):
        if len(fields) == 5:
            date_str, time_str, temp, hum, place = fields
        elif len(fields) == 3:
            date_str, temp, hum = fields

    # 기본값 보정
    if not date_str:
        date_str = init_date
    if not time_str:
        time_str = init_time
    if place is None:
        place = ""

    # ── 저장 버튼 ────────────────────────────────────────────────────────────
    fmt = (getattr(pil_img, "format", "") or "").upper()
    mime = "image/png" if fmt == "PNG" else "image/jpeg"

    if st.button("💾 저장 (Drive + Sheet)", key="save_btn", use_container_width=False, width="stretch"):
        if "__img_bytes__" not in st.session_state:
            st.error("이미지 데이터를 찾을 수 없습니다. 다시 업로드/촬영해 주세요.")
            return
        try:
            # 1) 원본 이미지 My Drive 업로드
            link = upload_image_to_drive_user(
                creds,
                st.session_state["__img_bytes__"],
                filename_prefix="env_photo",
                mime_type=mime,
            )

            # 2) 체감온도/알람 계산
            t = _to_float(temp)
            h = _to_float(hum)
            hi = _heat_index_celsius(t, h)
            alarm = _alarm_from_hi(hi)
            st.markdown(alarm_badge(alarm), unsafe_allow_html=True)

            # 3) Google Sheets에 저장 (일자/시간/작업장 포함)  ← 확장된 storage.append_row 사용
            append_row(date_str, time_str, t, h, (place or None), hi, alarm, link)

            # 편의: 마지막 작업장 기억
            st.session_state["__last_place__"] = place or ""

            st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류: {e}")

if __name__ == "__main__":
    main()
