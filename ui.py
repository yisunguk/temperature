# ui.py
import re
import math
import streamlit as st
import pandas as pd
from PIL import Image
from typing import Optional, Tuple
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# 헤더 / 입력
# ──────────────────────────────────────────────────────────────────────────────
def render_header():
    st.title("실외 온도/습도 기록기")
    st.caption("카메라 촬영 또는 이미지 업로드 → OCR → 표 저장 (Google Sheets + Drive)")


def _toggle(label: str, value: bool, key: str) -> bool:
    # Streamlit 버전에 따라 toggle/checkbox 호환
    if hasattr(st, "toggle"):
        return st.toggle(label, value=value, key=key)
    return st.checkbox(label, value=value, key=key)


def input_panel() -> Tuple[Optional[Image.Image], Optional[bytes], str]:
    """카메라 ON/OFF 토글 + 갤러리 업로드"""
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


def extracted_edit_fields(initial_date: str, initial_temp, initial_hum):
    """값 편집만 담당. 저장 버튼은 app.py에서 별도로 처리."""
    st.subheader("추출 결과 확인/수정")
    default_date = initial_date or datetime.now().strftime("%Y-%m-%d")

    col1, col2, col3 = st.columns(3)
    with col1:
        date_str = st.text_input("일자 (YYYY-MM-DD)", value=default_date)
    with col2:
        temp = st.number_input(
            "온도(℃)",
            value=float(initial_temp) if initial_temp is not None else 0.0,
            step=0.1,
            format="%.1f",
        )
    with col3:
        hum = st.number_input(
            "습도(%)",
            value=float(initial_hum) if initial_hum is not None else 0.0,
            step=0.1,
            format="%.1f",
        )

    st.caption("※ 값을 확인/수정한 다음, 아래 **저장 (Drive + Sheet)** 버튼을 눌러 저장합니다.")
    return date_str, float(temp), float(hum)

# ──────────────────────────────────────────────────────────────────────────────
# Google Drive 썸네일/링크 유틸
# ──────────────────────────────────────────────────────────────────────────────
def _extract_drive_file_id(url: str) -> Optional[str]:
    """여러 형태의 Drive URL에서 fileId를 추출."""
    if not isinstance(url, str) or not url:
        return None
    patterns = [
        r"drive\.google\.com/file/d/([^/]+)/",   # .../file/d/<id>/view
        r"[?&]id=([^&]+)",                       # ...open?id=<id> or uc?id=<id>
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
    """fileId로 썸네일 URL 생성."""
    fid = _extract_drive_file_id(view_url)
    return f"https://drive.google.com/thumbnail?id={fid}" if fid else None

# ──────────────────────────────────────────────────────────────────────────────
# 체감온도(Heat Index, 섭씨) 계산 + KOSHA 구간 분류
# ──────────────────────────────────────────────────────────────────────────────
def _heat_index_celsius(temp_c: Optional[float], rh: Optional[float]) -> Optional[float]:
    """
    Rothfusz 회귀 기반 Heat Index 계산.
    - 입력: 건구온도(℃), 상대습도(%)
    - 출력: 체감온도(℃)
    - 일반적으로 T<26.7℃ 또는 RH<40%에서는 HI≈T로 간주.
    """
    try:
        if temp_c is None or rh is None:
            return None
        T = float(temp_c)
        R = float(rh)
    except Exception:
        return None

    if math.isnan(T) or math.isnan(R):
        return None

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

    HI_c = (HI_f - 32.0) * 5.0 / 9.0
    return round(HI_c, 1)


def _alarm_from_hi(hi_c: Optional[float]) -> str:
    """
    KOSHA 체감온도 산출표 구간:
    - < 32: "" (무표시)
    - 32–34.9: 관심
    - 35–37.9: 주의
    - 38–39.9: 경고
    - ≥ 40: 위험
    """
    if hi_c is None:
        return ""
    try:
        x = float(hi_c)
    except Exception:
        return ""
    if x >= 40:
        return "위험"
    if x >= 38:
        return "경고"
    if x >= 35:
        return "주의"
    if x >= 32:
        return "관심"
    return ""

# ──────────────────────────────────────────────────────────────────────────────
# 표 렌더링 (+ 세션 내 삭제 기능)
# ──────────────────────────────────────────────────────────────────────────────
def _row_key(series: pd.Series) -> str:
    """세션 내 삭제 추적을 위한 고유 키(내용 기반)."""
    return "|".join([
        str(series.get("일자", "")),
        str(series.get("온도(℃)", "")),
        str(series.get("습도(%)", "")),
        str(series.get("사진URL", series.get("원본열기", ""))),
    ])

def table_view(df: pd.DataFrame):
    st.subheader("저장된 데이터")

    # 세션 상태에 삭제 키 저장소 초기화
    if "__hidden_row_keys__" not in st.session_state:
        st.session_state["__hidden_row_keys__"] = set()

    has_cols = {"일자", "온도(℃)", "습도(%)"}.issubset(set(df.columns))
    if has_cols and not df.empty:
        df = df.copy()

        # 체감온도/알람 계산
        df["체감온도(℃)"] = [_heat_index_celsius(t, h) for t, h in zip(df["온도(℃)"], df["습도(%)"])]
        df["알람"] = [_alarm_from_hi(v) for v in df["체감온도(℃)"]]

        # 썸네일/링크
        if "사진URL" in df.columns:
            df["사진썸네일"] = df["사진URL"].apply(_to_thumbnail_url)
            df["원본열기"] = df["사진URL"]
        else:
            df["사진썸네일"] = None
            df["원본열기"] = ""

        # 삭제 키 생성
        df["__key__"] = df.apply(_row_key, axis=1)

        # ▶ 세션에서 숨긴 행 제외
        hidden = st.session_state["__hidden_row_keys__"]
        visible_df = df[~df["__key__"].isin(hidden)].reset_index(drop=True)

        # 표시용 데이터프레임 구성
        show_cols = ["일자", "온도(℃)", "습도(%)", "체감온도(℃)", "알람", "사진썸네일", "원본열기"]
        show_cols = [c for c in show_cols if c in visible_df.columns]
        show_df = visible_df[show_cols].copy()

        # 체크박스 컬럼 (UI에서만 사용)
        show_df["삭제"] = pd.Series([False] * len(show_df), dtype="bool")

        # 편집 설정: 체크박스만 편집 가능
        edited = st.data_editor(
            show_df,
            key="data_table",
            hide_index=True,
            width="stretch",
            column_config={
                "온도(℃)": st.column_config.NumberColumn("온도(℃)", format="%.1f", disabled=True),
                "습도(%)": st.column_config.NumberColumn("습도(%)", min_value=0, max_value=100, disabled=True),
                "체감온도(℃)": st.column_config.NumberColumn("체감온도(℃)", format="%.1f",
                                                      help="온도와 습도로 계산된 Heat Index(체감온도)",
                                                      disabled=True),
                "알람": st.column_config.TextColumn("알람", help="관심/주의/경고/위험 (KOSHA 산출표 기준)", disabled=True),
                "사진썸네일": st.column_config.ImageColumn("사진", help="썸네일 미리보기", width="small", disabled=True),
                "원본열기": st.column_config.LinkColumn("원본 열기", help="Google Drive에서 원본 보기", disabled=True),
                "삭제": st.column_config.CheckboxColumn("삭제", help="체크한 행을 화면에서만 삭제", default=False),
            },
            disabled=False,
        )

        # 삭제 버튼 (시트는 수정하지 않음)
        col_del, col_restore = st.columns([1,1])
        with col_del:
            if st.button("🗑️ 선택 행 삭제(표에서만)", type="secondary"):
                rm_flags = edited["삭제"].fillna(False).tolist()
                keys_visible = visible_df["__key__"].tolist()
                selected_keys = {k for k, flag in zip(keys_visible, rm_flags) if flag}
                if not selected_keys:
                    st.warning("삭제할 행을 선택해 주세요.")
                else:
                    st.session_state["__hidden_row_keys__"].update(selected_keys)
                    st.success(f"{len(selected_keys)}개 행을 표에서 숨겼습니다. (시트는 유지)")
                    st.rerun()
        with col_restore:
            if st.button("↩️ 숨긴 행 모두 복구"):
                st.session_state["__hidden_row_keys__"] = set()
                st.success("모든 숨김을 해제했습니다.")
                st.rerun()
        return

    # 사진URL만 있는 기존 케이스(또는 비어 있음)
    if "사진URL" in df.columns and not df.empty:
        df = df.copy()
        df["사진썸네일"] = df["사진URL"].apply(_to_thumbnail_url)
        df["원본열기"] = df["사진URL"]
        df["__key__"] = df.apply(_row_key, axis=1)

        hidden = st.session_state["__hidden_row_keys__"]
        visible_df = df[~df["__key__"].isin(hidden)].reset_index(drop=True)

        show_cols = [c for c in ["일자", "온도(℃)", "습도(%)", "사진썸네일", "원본열기"] if c in visible_df.columns]
        show_df = visible_df[show_cols].copy()
        show_df["삭제"] = pd.Series([False] * len(show_df), dtype="bool")

        edited = st.data_editor(
            show_df,
            key="data_table_simple",
            hide_index=True,
            width="stretch",
            column_config={
                "온도(℃)": st.column_config.NumberColumn("온도(℃)", format="%.1f", disabled=True),
                "습도(%)": st.column_config.NumberColumn("습도(%)", min_value=0, max_value=100, disabled=True),
                "사진썸네일": st.column_config.ImageColumn("사진", help="썸네일 미리보기", width="small", disabled=True),
                "원본열기": st.column_config.LinkColumn("원본 열기", help="Google Drive에서 원본 보기", disabled=True),
                "삭제": st.column_config.CheckboxColumn("삭제", help="체크한 행을 화면에서만 삭제", default=False),
            },
            disabled=False,
        )

        col_del, col_restore = st.columns([1,1])
        with col_del:
            if st.button("🗑️ 선택 행 삭제(표에서만)", type="secondary"):
                rm_flags = edited["삭제"].fillna(False).tolist()
                keys_visible = visible_df["__key__"].tolist()
                selected_keys = {k for k, flag in zip(keys_visible, rm_flags) if flag}
                if not selected_keys:
                    st.warning("삭제할 행을 선택해 주세요.")
                else:
                    st.session_state["__hidden_row_keys__"].update(selected_keys)
                    st.success(f"{len(selected_keys)}개 행을 표에서 숨겼습니다. (시트는 유지)")
                    st.rerun()
        with col_restore:
            if st.button("↩️ 숨긴 행 모두 복구"):
                st.session_state["__hidden_row_keys__"] = set()
                st.success("모든 숨김을 해제했습니다.")
                st.rerun()
    else:
        st.dataframe(df, width="stretch")
