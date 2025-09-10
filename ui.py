# ui.py
import re
import streamlit as st
import pandas as pd
from PIL import Image
from typing import Optional, Tuple
from datetime import datetime


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
    # fallback: /file/d/ 가 있으나 슬래시 파싱이 실패했을 때
    if "/file/d/" in url:
        try:
            return url.split("/file/d/")[1].split("/")[0]
        except Exception:
            pass
    return None


def _to_thumbnail_url(view_url: str) -> Optional[str]:
    """fileId로 썸네일 URL 생성."""
    fid = _extract_drive_file_id(view_url)
    return f"https://drive.google.com/thumbnail?id={fid}" if fid else None


def table_view(df: pd.DataFrame):
    st.subheader("저장된 데이터")

    # 사진URL이 있으면 썸네일+원본열기로 가공해서 data_editor로 표시
    if "사진URL" in df.columns and not df.empty:
        df = df.copy()
        df["사진썸네일"] = df["사진URL"].apply(_to_thumbnail_url)
        df["원본열기"] = df["사진URL"].apply(lambda u: u if isinstance(u, str) and u else "")

        view_cols = ["일자", "온도(℃)", "습도(%)", "사진썸네일", "원본열기"]
        view_cols = [c for c in view_cols if c in df.columns]

        st.data_editor(
            df[view_cols],
            hide_index=True,
            width="stretch",
            column_config={
                "사진썸네일": st.column_config.ImageColumn("사진", help="썸네일 미리보기", width="small"),
                "원본열기": st.column_config.LinkColumn("원본 열기", help="Google Drive에서 원본 보기"),
                "온도(℃)": st.column_config.NumberColumn("온도(℃)", format="%.1f"),
                "습도(%)": st.column_config.NumberColumn("습도(%)", min_value=0, max_value=100),
            },
            disabled=True,  # 목록은 읽기 전용 (편집은 입력 영역에서)
        )
    else:
        # 사진URL이 없거나 데이터가 비어 있으면 기본 표로 표시
        st.dataframe(df, width="stretch")
