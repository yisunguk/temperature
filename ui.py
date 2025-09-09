# ui.py
import streamlit as st
import pandas as pd
from PIL import Image
from typing import Optional, Tuple

def render_header():
    st.title("실외 온도/습도 기록기")
    st.caption("카메라 촬영 또는 이미지 업로드 → OCR → 표 저장 (Google Sheets + Drive)")

def input_panel() -> Tuple[Optional[Image.Image], Optional[bytes], str]:
    tab_cam, tab_up = st.tabs(["📷 카메라로 촬영", "🖼 갤러리에서 업로드"])
    image = None
    image_bytes = None
    source = "none"

    with tab_cam:
        cam_img = st.camera_input("카메라로 촬영하세요", label_visibility="collapsed")
        if cam_img:
            image = Image.open(cam_img)
            image_bytes = cam_img.getvalue()
            source = "camera"

    with tab_up:
        up = st.file_uploader("이미지 파일 업로드 (jpg/png)", type=["jpg", "jpeg", "png"])
        if up:
            image = Image.open(up)
            image_bytes = up.getvalue()
            source = "upload"

    return image, image_bytes, source

# ui.py
import streamlit as st
import pandas as pd
from PIL import Image
from typing import Optional, Tuple

def render_header():
    st.title("실외 온도/습도 기록기")
    st.caption("카메라 촬영 또는 이미지 업로드 → OCR → 표 저장 (Google Sheets + Drive)")

def input_panel() -> Tuple[Optional[Image.Image], Optional[bytes], str]:
    tab_cam, tab_up = st.tabs(["📷 카메라로 촬영", "🖼 갤러리에서 업로드"])
    image = None
    image_bytes = None
    source = "none"

    with tab_cam:
        cam_img = st.camera_input("카메라로 촬영하세요", label_visibility="collapsed")
        if cam_img:
            image = Image.open(cam_img)
            image_bytes = cam_img.getvalue()
            source = "camera"

    with tab_up:
        up = st.file_uploader("이미지 파일 업로드 (jpg/png)", type=["jpg", "jpeg", "png"])
        if up:
            image = Image.open(up)
            image_bytes = up.getvalue()
            source = "upload"

    return image, image_bytes, source

# ui.py
import streamlit as st
import pandas as pd
from PIL import Image
from typing import Optional, Tuple
from datetime import datetime

def render_header():
    st.title("실외 온도/습도 기록기")
    st.caption("카메라 촬영 또는 이미지 업로드 → OCR → 표 저장 (Google Sheets + Drive)")

def input_panel() -> Tuple[Optional[Image.Image], Optional[bytes], str]:
    tab_cam, tab_up = st.tabs(["📷 카메라로 촬영", "🖼 갤러리에서 업로드"])
    image = None
    image_bytes = None
    source = "none"

    with tab_cam:
        cam_img = st.camera_input("카메라로 촬영하세요", label_visibility="collapsed")
        if cam_img:
            image = Image.open(cam_img)
            image_bytes = cam_img.getvalue()
            source = "camera"

    with tab_up:
        up = st.file_uploader("이미지 파일 업로드 (jpg/png)", type=["jpg", "jpeg", "png"])
        if up:
            image = Image.open(up)
            image_bytes = up.getvalue()
            source = "upload"

    return image, image_bytes, source

def extracted_edit_form(initial_date: str, initial_temp, initial_hum) -> Tuple[str, float, float, bool]:
    st.subheader("추출 결과 확인/수정")
    default_date = initial_date or datetime.now().strftime("%Y-%m-%d")

    with st.form("extracted_edit_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            date_str = st.text_input("일자 (YYYY-MM-DD)", value=default_date)
        with col2:
            temp = st.number_input("온도(℃)", value=float(initial_temp) if initial_temp is not None else 0.0, step=0.1, format="%.1f")
        with col3:
            hum = st.number_input("습도(%)", value=float(initial_hum) if initial_hum is not None else 0.0, step=0.1, format="%.1f")

        submitted = st.form_submit_button("💾 저장 (Drive + Sheet)")

    return date_str, float(temp), float(hum), submitted

def table_view(df: pd.DataFrame):
    st.subheader("저장된 데이터")
    st.dataframe(df, use_container_width=False, width="stretch")
