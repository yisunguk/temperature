# app.py
import streamlit as st
from ui import render_header, input_panel, extracted_edit_form, table_view
from ocr import run_ocr
from storage import read_dataframe, upload_image_to_drive, append_row, diagnose_permissions

st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")

def main():
    render_header()

    # (A) 상단 표 로딩은 try/except로 진단 제공
    try:
        df = read_dataframe()
        table_view(df)
    except Exception:
        st.error("Google Sheets에 접근할 수 없습니다. 권한/ID를 확인하세요.")
        diag = diagnose_permissions()
        st.code(diag, language="python")
        st.stop()

    st.divider()
    st.subheader("입력")

    pil_img, img_bytes, src = input_panel()

    # 폼 제출 때 필요하므로 세션에 저장
    if img_bytes:
        st.session_state["__img_bytes__"] = img_bytes

    if pil_img is not None and img_bytes is not None:
        with st.expander("이미지 미리보기", expanded=True):
            st.image(pil_img, caption="입력 이미지")

        with st.spinner("OCR 추출 중..."):
            result = run_ocr(pil_img)

        st.success("OCR 추출 완료!")
        with st.expander("추출 원문 보기", expanded=False):
            st.text(result.get("raw_text", ""))

        # (B) 추출값 폼에 자동 입력 + 폼 안에 저장 버튼
        date_str, temp, hum, submitted = extracted_edit_form(
            result.get("date"),
            result.get("temperature"),
            result.get("humidity"),
        )

        # (C) 저장 처리
        if submitted:
            if not date_str:
                st.warning("일자는 필수입니다. (예: 2025-09-09)")
            elif "__img_bytes__" not in st.session_state:
                st.error("이미지 데이터를 찾을 수 없습니다. 이미지를 다시 업로드/촬영해 주세요.")
            else:
                try:
                    link = upload_image_to_drive(st.session_state["__img_bytes__"], filename_prefix="env_photo")
                    append_row(date_str, temp, hum, link)
                    st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"저장 중 오류: {e}")

    else:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")

if __name__ == "__main__":
    main()
