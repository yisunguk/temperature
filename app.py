# app.py
import streamlit as st
from datetime import datetime

from ui import render_header, input_panel, extracted_edit_form, table_view
from ocr import run_ocr
from storage import read_dataframe, upload_image_to_drive, append_row, diagnose_permissions

st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")

def main():
    render_header()

    # (A) 상단 표 로딩 (권한/ID 문제시 진단 정보 표시)
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

    # 저장 시점에 필요하므로 이미지 바이트는 세션에 보관
    if img_bytes:
        st.session_state["__img_bytes__"] = img_bytes

    if pil_img is not None and img_bytes is not None:
        with st.expander("이미지 미리보기", expanded=True):
            st.image(pil_img, caption="입력 이미지", width="stretch")

        with st.spinner("OCR 추출 중..."):
            result = run_ocr(pil_img)

        st.success("OCR 추출 완료!")
        with st.expander("추출 원문 보기", expanded=False):
            st.text(result.get("raw_text", ""))

        # (B) 추출값 폼에 자동 입력
        vals = extracted_edit_form(
            result.get("date"),
            result.get("temperature"),
            result.get("humidity"),
        )

        # ui.py가 4개 반환(신버전) 또는 3개 반환(구버전) 모두 대응
        if isinstance(vals, tuple) and len(vals) == 4:
            date_str, temp, hum, submitted = vals
        else:
            date_str, temp, hum = vals
            submitted = st.button("💾 저장 (Drive + Sheet)")

        # 날짜 비어 있으면 오늘 날짜 기본값
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        # (C) 저장 처리: Drive 업로드 → URL 생성 → 시트에 행 추가 → 표 새로고침
        if submitted:
            if "__img_bytes__" not in st.session_state:
                st.error("이미지 데이터를 찾을 수 없습니다. 이미지를 다시 업로드/촬영해 주세요.")
            else:
                try:
                    link = upload_image_to_drive(
                        st.session_state["__img_bytes__"], filename_prefix="env_photo"
                    )
                    # 숫자 변환(비어 있으면 None)
                    try:
                        temp_val = float(temp) if temp is not None else None
                    except Exception:
                        temp_val = None
                    try:
                        hum_val = float(hum) if hum is not None else None
                    except Exception:
                        hum_val = None

                    append_row(date_str, temp_val, hum_val, link)
                    st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"저장 중 오류: {e}")

    else:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")

if __name__ == "__main__":
    main()
