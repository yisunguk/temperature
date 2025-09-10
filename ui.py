# ui.py
import re
import math
import streamlit as st
import pandas as pd
from PIL import Image
from typing import Optional, Tuple
from datetime import datetime

def render_header():
    st.title("광양 LNG Jetty 인프라 현장 체감온도 기록기")
    st.caption("현재 광양의 체감온도)")

def _toggle(label: str, value: bool, key: str) -> bool:
    if hasattr(st, "toggle"):
        return st.toggle(label, value=value, key=key)
    return st.checkbox(label, value=value, key=key)

def input_panel() -> Tuple[Optional[Image.Image], Optional[bytes], str]:
    if "__camera_enabled__" not in st.session_state:
        st.session_state["__camera_enabled__"] = False
    if "__cam_key__" not in st.session_state:
        st.session_state["__cam_key__"] = 0

    tab_cam, tab_up = st.tabs(["📷 카메라로 촬영", "🖼 갤러리에서 업로드"])

    image: Optional[Image.Image] = None
    image_bytes: Optional[bytes] = None
    source = "none"

    with tab_cam:
        cam_on = _toggle("카메라 켜기", value=st.session_state["__camera_enabled__"], key="camera_on_toggle")
        st.session_state["__camera_enabled__"] = cam_on

        if cam_on:
            cam_key = f"camera_{st.session_state['__cam_key__']}"
            cam_img = st.camera_input("카메라", key=cam_key, label_visibility="collapsed")

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("⏹ 카메라 끄기", key="btn_cam_off"):
                    st.session_state["__camera_enabled__"] = False
                    st.session_state["__cam_key__"] += 1
                    st.rerun()
            with col2:
                st.caption("촬영 후에도 끄기 버튼으로 카메라 자원을 해제할 수 있어요.")

            if cam_img:
                image = Image.open(cam_img)
                image_bytes = cam_img.getvalue()
                source = "camera"
        else:
            st.caption("🔕 카메라가 꺼져 있습니다. 위 토글을 켜면 촬영할 수 있어요.")

    with tab_up:
        up = st.file_uploader("이미지 파일 업로드 (jpg/png)", type=["jpg", "jpeg", "png"])
        if up:
            image = Image.open(up)
            image_bytes = up.getvalue()
            source = "upload"

    return image, image_bytes, source

# ✔ 5-튜플(일자, 시간, 온도, 습도, 작업장) 반환
def extracted_edit_fields(initial_date: str, initial_time: str, initial_temp, initial_hum, initial_place: str = ""):
    st.subheader("추출 결과 확인/수정")
    default_date = initial_date or datetime.now().strftime("%Y-%m-%d")
    default_time = initial_time or datetime.now().strftime("%H:%M")

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        date_str = st.text_input("일자 (YYYY-MM-DD)", value=default_date)
    with c2:
        time_str = st.text_input("시간 (HH:MM)", value=default_time)
    with c3:
        temp = st.number_input("온도(℃)", value=float(initial_temp) if initial_temp is not None else 0.0,
                               step=0.1, format="%.1f")
    with c4:
        hum = st.number_input("습도(%)", value=float(initial_hum) if initial_hum is not None else 0.0,
                              step=0.1, format="%.1f")
    with c5:
        place = st.text_input("작업장", value=initial_place, placeholder="예) 1안벽 / 야드A / 배관구역")

    st.caption("※ 값을 확인/수정한 다음, 아래 **저장 (Google drive + Google Sheet)** 버튼을 눌러 저장합니다.")
    return date_str, time_str, float(temp), float(hum), place

# ──────────────────────────────────────────────────────────────────────────────
# Google Drive 썸네일/링크 유틸
# ──────────────────────────────────────────────────────────────────────────────
def _extract_drive_file_id(url: str) -> Optional[str]:
    if not isinstance(url, str) or not url:
        return None
    patterns = [
        r"drive\.google\.com/file/d/([^/]+)/",
        r"[?&]id=([^&]+)",
        r"drive\.google\.com/uc\?id=([^&]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if isinstance(url, str) and "/file/d/" in url:
        try:
            return url.split("/file/d/")[1].split("/")[0]
        except Exception:
            pass
    return None

def _to_thumbnail_url(view_url: str) -> Optional[str]:
    fid = _extract_drive_file_id(view_url)
    return f"https://drive.google.com/thumbnail?id={fid}" if fid else None

# ──────────────────────────────────────────────────────────────────────────────
# 체감온도 계산/알람 (표 표시용)
# ──────────────────────────────────────────────────────────────────────────────
def _heat_index_celsius(temp_c: Optional[float], rh: Optional[float]) -> Optional[float]:
    try:
        if temp_c is None or rh is None:
            return None
        T = float(temp_c); R = float(rh)
    except Exception:
        return None
    if math.isnan(T) or math.isnan(R):
        return None
    if T < 26.7 or R < 40:
        return round(T, 1)
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

def _alarm_from_hi(hi_c: Optional[float], show_normal: bool = True) -> str:
    if hi_c is None: return "정상" if show_normal else ""
    try: x = float(hi_c)
    except Exception: return "정상" if show_normal else ""
    if x >= 40: return "위험"
    if x >= 38: return "경고"
    if x >= 35: return "주의"
    if x >= 32: return "관심"
    return "정상" if show_normal else ""

def table_view(df: pd.DataFrame):
    st.subheader("현장별 체감온도 기록 데이터")
    if {"일자", "온도(℃)", "습도(%)"}.issubset(df.columns) and not df.empty:
        df = df.copy()
        df["체감온도(℃)"] = [_heat_index_celsius(t, h) for t, h in zip(df["온도(℃)"], df["습도(%)"])]
        df["알람"] = [_alarm_from_hi(v) for v in df["체감온도(℃)"]]
        if "사진URL" in df.columns:
            df["사진썸네일"] = df["사진URL"].apply(_to_thumbnail_url)
            df["원본열기"] = df["사진URL"].apply(lambda u: u if isinstance(u, str) and u else "")
        # ✔ 일자 → 시간 → 작업장 순으로 노출
        view_cols = ["일자", "시간", "작업장", "온도(℃)", "습도(%)", "체감온도(℃)", "알람"]
        if "사진썸네일" in df.columns: view_cols += ["사진썸네일"]
        if "원본열기"   in df.columns: view_cols += ["원본열기"]
        view_cols = [c for c in view_cols if c in df.columns]
        st.data_editor(
            df[view_cols],
            hide_index=True,
            width="stretch",
            column_config={
                "시간": st.column_config.TextColumn("시간"),
                "작업장": st.column_config.TextColumn("작업장"),
                "온도(℃)": st.column_config.NumberColumn("온도(℃)", format="%.1f"),
                "습도(%)": st.column_config.NumberColumn("습도(%)", min_value=0, max_value=100),
                "체감온도(℃)": st.column_config.NumberColumn("체감온도(℃)", format="%.1f",
                    help="온도와 습도로 계산된 Heat Index(체감온도)"),
                "알람": st.column_config.TextColumn("알람", help="관심/주의/경고/위험"),
                "사진썸네일": st.column_config.ImageColumn("사진", width="small"),
                "원본열기": st.column_config.LinkColumn("원본 열기"),
            },
            disabled=True,
        )
        return
    st.dataframe(df, width="stretch")
