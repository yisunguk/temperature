# app.py
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import re
import streamlit as st
from oauth_google import ensure_user_drive_creds, logout_button
from ui import render_header, input_panel, extracted_edit_fields  # table_view 대신 직접 구현
from ocr import run_ocr
from storage import read_dataframe, append_row, replace_all  # ← replace_all 추가
from storage import upload_image_to_drive_user, diagnose_permissions
import requests
import pandas as pd

OPEN_METEO_LAT = 34.9414   # Gwangyang
OPEN_METEO_LON = 127.69569
OPEN_METEO_TZ  = "Asia/Seoul"

st.set_page_config(page_title="광양 LNG Jetty 인프라 현장 체감온도 기록기", layout="centered")
TZ = st.secrets.get("TIMEZONE", "Asia/Seoul")

# ──────────────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────────────
def _fmt_ts(ts: str | None) -> str:
    if not ts: return "알 수 없음"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts.replace("T", " ")

def fetch_current_apparent_temp(lat=OPEN_METEO_LAT, lon=OPEN_METEO_LON, tz=OPEN_METEO_TZ):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": lat, "longitude": lon,
              "current": "apparent_temperature,temperature_2m,relative_humidity_2m",
              "timezone": tz}
    r = requests.get(url, params=params, timeout=10); r.raise_for_status()
    cur = (r.json().get("current") or {})
    return {"time": cur.get("time"),
            "apparent_temperature": cur.get("apparent_temperature"),
            "temperature_2m": cur.get("temperature_2m"),
            "relative_humidity_2m": cur.get("relative_humidity_2m")}

def _to_float(x):
    try: return float(x) if x not in (None, "") else None
    except Exception: return None

def _heat_index_celsius(temp_c, rh):
    try:
        if temp_c is None or rh is None: return None
        T = float(temp_c); R = float(rh)
    except Exception: return None
    if math.isnan(T) or math.isnan(R): return None
    if T < 26.7 or R < 40: return round(T, 1)
    Tf = T * 9/5 + 32
    HI_f = (-42.379 + 2.04901523*Tf + 10.14333127*R
            - 0.22475541*Tf*R - 0.00683783*Tf*Tf
            - 0.05481717*R*R + 0.00122874*Tf*Tf*R
            + 0.00085282*Tf*R*R - 0.00000199*Tf*Tf*R*R)
    if (R < 13) and (80 <= Tf <= 112):
        HI_f -= ((13-R)/4) * ((17-abs(Tf-95))/17) ** 0.5
    elif (R > 85) and (80 <= Tf <= 87):
        HI_f += ((R-85)/10) * ((87-Tf)/5)
    return round((HI_f - 32) * 5/9, 1)

def _alarm_from_hi(hi_c, show_normal: bool = True):
    if hi_c is None: return "정상" if show_normal else ""
    try: x = float(hi_c)
    except Exception: return "정상" if show_normal else ""
    if x >= 40: return "위험"
    if x >= 38: return "경고"
    if x >= 35: return "주의"
    if x >= 32: return "관심"
    return "정상" if show_normal else ""

def alarm_badge(alarm: str) -> str:
    colors = {"정상":"#10b981","관심":"#3b82f6","주의":"#f59e0b","경고":"#ef4444","위험":"#7f1d1d"}
    color = colors.get(alarm, "#6b7280")
    return f"<span style='display:inline-block;padding:4px 10px;border-radius:999px;background:{color};color:white;font-weight:600'>{alarm}</span>"

# Google Drive 썸네일 URL 생성 (ui.py의 내부 유틸과 동일 동작)
def _extract_drive_file_id(url: str) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    pats = [
        r"drive\.google\.com/file/d/([^/]+)/",
        r"[?&]id=([^&]+)",
        r"drive\.google\.com/uc\?id=([^&]+)",
    ]
    for p in pats:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if "/file/d/" in url:
        try:
            return url.split("/file/d/")[1].split("/")[0]
        except Exception:
            return None
    return None

def _to_thumbnail_url(view_url: str) -> str | None:
    fid = _extract_drive_file_id(view_url)
    return f"https://drive.google.com/thumbnail?id={fid}" if fid else None

# ──────────────────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────────────────
def main():
    render_header()  # 헤더/UI 빌딩 (ui.py)  :contentReference[oaicite:4]{index=4}

    # 현재(광양) 지표
    try:
        now = fetch_current_apparent_temp()
        hi_now = now["apparent_temperature"]; alarm_now = _alarm_from_hi(hi_now)
        c1,c2,c3 = st.columns([1,1,1])
        with c1: st.metric("광양 체감온도(℃)", f"{hi_now:.1f}" if hi_now is not None else "-")
        with c2: st.metric("기온(℃)", f"{now['temperature_2m']:.1f}" if now["temperature_2m"] is not None else "-")
        with c3: st.metric("습도(%)", f"{now['relative_humidity_2m']:.0f}" if now["relative_humidity_2m"] is not None else "-")
        color = {"정상":"#10b981","관심":"#3b82f6","주의":"#f59e0b","경고":"#ef4444","위험":"#7f1d1d"}.get(alarm_now, "#6b7280")
        st.markdown(f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;background:{color};color:white;font-weight:600'>{alarm_now}</div> "
                    f"<span style='color:#6b7280'>기준시각: {_fmt_ts(now.get('time'))}</span>", unsafe_allow_html=True)
        st.divider()
    except Exception as e:
        st.info(f"현재 날씨 조회 실패: {e}")

    # ── 상단 테이블 (Sheets) ────────────────────────────────────────────────
    # 1) 시트 읽기
    try:
        df = read_dataframe()  # storage.py  :contentReference[oaicite:5]{index=5}
    except Exception as e:
        st.error("Google Sheets 읽기 오류가 발생했습니다. 권한/ID 또는 네트워크 상태를 확인하세요.")
        st.code(diagnose_permissions(), language="python")
        st.exception(e)
        st.stop()

    # 2) 줄 선택 가능한 테이블 렌더링 (체감온도/알람/썸네일/원본열기 포함)
    st.subheader("현장별 체감온도 기록 데이터")
    if not df.empty and {"일자", "온도(℃)", "습도(%)"}.issubset(df.columns):
        base = df.reset_index(drop=False).rename(columns={"index": "__rowid__"})  # 원본 행 위치 보존
        work = base.copy()
        work["체감온도(℃)"] = [_heat_index_celsius(t, h) for t, h in zip(work["온도(℃)"], work["습도(%)"])]
        work["알람"] = [_alarm_from_hi(v) for v in work["체감온도(℃)"]]
        if "사진URL" in work.columns:
            work["사진썸네일"] = work["사진URL"].apply(_to_thumbnail_url)
            work["원본열기"] = work["사진URL"].apply(lambda u: u if isinstance(u, str) and u else "")
        view_cols = ["일자", "시간", "작업장", "온도(℃)", "습도(%)", "체감온도(℃)", "알람"]
        if "사진썸네일" in work.columns: view_cols += ["사진썸네일"]
        if "원본열기"   in work.columns: view_cols += ["원본열기"]
        show = work[["__rowid__"] + view_cols].copy()
        show.insert(1, "선택", False)
        show = show.set_index("__rowid__", drop=True)
        show.index.name = "번호"

        edited = st.data_editor(
            show,
            key="main_table_editor",
            hide_index=False,  # ← 인덱스가 원본 행 위치
            width="stretch",
            column_config={
                "시간": st.column_config.TextColumn("시간"),
                "작업장": st.column_config.TextColumn("작업장"),
                "온도(℃)": st.column_config.NumberColumn("온도(℃)", format="%.1f"),
                "습도(%)": st.column_config.NumberColumn("습도(%)", min_value=0, max_value=100),
                "체감온도(℃)": st.column_config.NumberColumn("체감온도(℃)", format="%.1f",
                    help="온도와 습도로 계산된 Heat Index(체감온도)"),
                "알람": st.column_config.TextColumn("알람"),
                "사진썸네일": st.column_config.ImageColumn("사진", width="small"),
                "원본열기": st.column_config.LinkColumn("원본 열기"),
                "선택": st.column_config.CheckboxColumn("선택"),
            },
            disabled=[c for c in show.columns if c != "선택"],  # 선택만 체크 가능
            num_rows="fixed",
        )
        selected = [int(i) for i in edited.index[edited["선택"]].tolist()]

        col_del, col_info = st.columns([1, 3])
        with col_del:
            if st.button("🗑 선택 행 삭제 (Sheet 동기화)", type="primary", disabled=(len(selected) == 0)):
                try:
                    new_df = df.drop(index=selected).reset_index(drop=True)
                    replace_all(new_df)  # storage.py  :contentReference[oaicite:6]{index=6}
                    st.success(f"{len(selected)}건 삭제 완료! 테이블을 새로고침합니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 반영 중 오류: {e}")
        with col_info:
            st.caption(f"선택된 행: {len(selected)}건" if selected else "삭제할 행을 체크해 주세요.")
    else:
        st.dataframe(df, width="stretch")

    st.divider()
    st.subheader("온습도계의 사진을 촬영하거나 갤러리에서 업로드해 주세요")

    # OAuth(Drive 업로드용)  (oauth_google.ensure_user_drive_creds)  :contentReference[oaicite:7]{index=7}
    creds = ensure_user_drive_creds()
    with st.expander("🔎 로그인 진단", expanded=False):
        st.write("has_creds:", bool(creds and creds.valid))
        st.write("in_session:", "__google_token__" in st.session_state)
        try:
            from oauth_google import cookies
            st.write("cookie_present:", bool(cookies.get("gdrive_oauth")))
        except Exception:
            st.write("cookie_present: N/A")

    # 이미지 입력
    pil_img, img_bytes, src = input_panel()  # ui.py  :contentReference[oaicite:8]{index=8}
    if img_bytes:
        st.session_state["__img_bytes__"] = img_bytes
        st.session_state["__uploaded_at__"] = datetime.now(ZoneInfo(TZ))  # ✔ 업로드/촬영 시각

    if pil_img is None or img_bytes is None:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")
        return

    with st.expander("이미지 미리보기", expanded=True):
        st.image(pil_img, caption="입력 이미지")

    with st.spinner("OCR 추출 중..."):
        result = run_ocr(pil_img, st.session_state.get("__img_bytes__"))  # ocr.py  :contentReference[oaicite:9]{index=9}

    st.success("OCR 추출 완료!")
    if result.get("pretty"):
        c1, c2 = st.columns(2)
        with c1: st.metric("온도(℃)", f"{result['temperature']:.1f}" if result['temperature'] is not None else "-")
        with c2: st.metric("습도(%)", f"{result['humidity']:.1f}" if result['humidity'] is not None else "-")

    # 입력 폼 (날짜·시간 기본값은 업로드 시각)
    init_dt = st.session_state.get("__uploaded_at__") or datetime.now(ZoneInfo(TZ))
    init_date = init_dt.strftime("%Y-%m-%d"); init_time = init_dt.strftime("%H:%M")
    last_place = st.session_state.get("__last_place__", "")

    date_str, time_str, temp, hum, place = extracted_edit_fields(
        result.get("date") or init_date, init_time,
        result.get("temperature"), result.get("humidity"),
        initial_place=last_place
    )  # ui.py  :contentReference[oaicite:10]{index=10}
    if not date_str: date_str = init_date
    if not time_str: time_str = init_time
    if place is None: place = ""

    # 저장
    fmt = (getattr(pil_img, "format", "") or "").upper()
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    if st.button("💾 저장 (Drive + Sheet)", key="save_btn", use_container_width=False, width="stretch"):
        if "__img_bytes__" not in st.session_state:
            st.error("이미지 데이터를 찾을 수 없습니다. 다시 업로드/촬영해 주세요."); return
        try:
            link = upload_image_to_drive_user(
                creds,
                st.session_state["__img_bytes__"],
                filename_prefix="env_photo",
                mime_type=mime
            )
            t = _to_float(temp); h = _to_float(hum)
            hi = _heat_index_celsius(t, h)
            alarm = _alarm_from_hi(hi)
            st.markdown(alarm_badge(alarm), unsafe_allow_html=True)

            # ✔ 확장 저장(일자, 시간, 작업장 포함)
            append_row(date_str, time_str, t, h, (place or None), hi, alarm, link)  # storage.py  :contentReference[oaicite:11]{index=11}

            st.session_state["__last_place__"] = place or ""
            st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류: {e}")

if __name__ == "__main__":
    main()
