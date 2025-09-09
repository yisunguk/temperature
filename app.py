# app.py
import streamlit as st
from ui import render_header, input_panel, extracted_edit_form, table_view
from ocr import run_ocr
from storage import read_dataframe, upload_image_to_drive, append_row, diagnose_permissions

st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")

def main():
    render_header()

    # [변경 후]
    try:
        df = read_dataframe()
        table_view(df)
    except Exception as e:
        st.error("Google Sheets에 접근할 수 없습니다. 아래 점검 정보를 확인하고 권한/ID를 맞춰주세요.")
        diag = diagnose_permissions()  # storage.py에 추가한 함수
        st.code(diag, language="python")
        st.info(
            "✅ 스프레드시트 편집자 추가: google-sheet@temperature-471604.iam.gserviceaccount.com\n"
            "✅ 드라이브 폴더 편집자 추가: temperature-app-photo@temperature-471604.iam.gserviceaccount.com\n"
            "✅ secrets.toml의 SHEET_ID / DRIVE_FOLDER_ID 확인"
        )
        st.stop()


    st.divider()
    st.subheader("입력")

    pil_img, img_bytes, src = input_panel()

    if pil_img is not None and img_bytes is not None:
        with st.expander("이미지 미리보기", expanded=True):
            st.image(pil_img, caption="입력 이미지", width="stretch")

        with st.spinner("OCR 추출 중..."):
            result = run_ocr(pil_img)

        st.success("OCR 추출 완료!")
        with st.expander("추출 원문 보기", expanded=False):
            st.text(result.get("raw_text", ""))

        # 값 확인 및 수정
        date_str, temp, hum = extracted_edit_form(result.get("date"), result.get("temperature"), result.get("humidity"))

        if st.button("📥 Google Drive에 사진 업로드 + Google Sheets에 저장"):
            try:
                link = upload_image_to_drive(img_bytes, filename_prefix="env_photo")
                append_row(date_str, temp, hum, link)
                st.toast("저장 완료! 시트를 새로고침합니다.", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"저장 중 오류가 발생했습니다: {e}")

    else:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")

if __name__ == "__main__":
    main()
