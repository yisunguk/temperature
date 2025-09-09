# app.py
import streamlit as st
from datetime import datetime

from ui import render_header, input_panel, extracted_edit_form, table_view
from ocr import run_ocr
from storage import read_dataframe, append_row  # Sheets는 계속 서비스계정
from storage import upload_image_to_drive_user   # ⬅️ 새로 추가한 함수 사용
from oauth_google import ensure_user_drive_creds  # ⬅️ OAuth 로그인

st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")

def main():
    render_header()

    # 상단 표 (Sheets 서비스계정)
    from storage import diagnose_permissions
    try:
        df = read_dataframe()
        table_view(df)
    except Exception:
        st.error("Google Sheets에 접근할 수 없습니다. 권한/ID를 확인하세요.")
        st.code(diagnose_permissions(), language="python")
        st.stop()

    st.divider()
    st.subheader("입력")

    # ✅ 사용자 OAuth 로그인 (사진을 My Drive에 저장하기 위해)
    creds = ensure_user_drive_creds()

    pil_img, img_bytes, src = input_panel()

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

        vals = extracted_edit_form(result.get("date"), result.get("temperature"), result.get("humidity"))
        if isinstance(vals, tuple) and len(vals) == 4:
            date_str, temp, hum, submitted = vals
        else:
            date_str, temp, hum = vals
            submitted = st.button("💾 저장 (Drive + Sheet)")

        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        # MIME 추정
        fmt = (getattr(pil_img, "format", "") or "").upper()
        mime = "image/png" if fmt == "PNG" else "image/jpeg"

        if submitted:
            if "__img_bytes__" not in st.session_state:
                st.error("이미지 데이터를 찾을 수 없습니다. 이미지를 다시 업로드/촬영해 주세요.")
            else:
                try:
                    # ✅ 사용자 OAuth로 My Drive에 업로드
                    link = upload_image_to_drive_user(
                        creds, st.session_state["__img_bytes__"], filename_prefix="env_photo", mime_type=mime
                    )
                    # Sheets에는 서비스계정으로 기록
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
