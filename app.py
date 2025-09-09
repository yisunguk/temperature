# app.py
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from oauth_google import ensure_user_drive_creds, logout_button
from ui import render_header, input_panel, extracted_edit_fields, table_view
from ocr import run_ocr
from oauth_google import ensure_user_drive_creds          # OAuth 로그인 (사진 업로드용)
from storage import read_dataframe, append_row            # Sheets는 서비스계정
from storage import upload_image_to_drive_user, diagnose_permissions

st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")
TZ = st.secrets.get("TIMEZONE", "Asia/Seoul")


def _to_float(x):
    try:
        return float(x) if x not in (None, "") else None
    except Exception:
        return None


def main():
    render_header()

    # 상단 표 로딩 (Sheets 서비스계정)
    try:
        df = read_dataframe()
        table_view(df)
    except Exception:
        st.error("Google Sheets에 접근할 수 없습니다. 권한/ID를 확인하세요.")
        st.code(diagnose_permissions(), language="python")
        st.stop()

    st.divider()
    st.subheader("입력")

    # ✅ 사용자 OAuth 로그인 (My Drive에 업로드하기 위해)
    creds = ensure_user_drive_creds()

    # 이미지 입력 (카메라/업로드)
    pil_img, img_bytes, src = input_panel()
    if img_bytes:
        st.session_state["__img_bytes__"] = img_bytes

    if pil_img is None or img_bytes is None:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")
        return

    with st.expander("이미지 미리보기", expanded=True):
        st.image(pil_img, caption="입력 이미지")

    with st.spinner("OCR 추출 중..."):
        result = run_ocr(pil_img)

    st.success("OCR 추출 완료!")
    with st.expander("추출 원문 보기", expanded=False):
        st.text(result.get("raw_text", ""))

    # ✔ 폼은 값 편집만 담당 (저장 버튼은 폼 밖에서!)
    date_str, temp, hum = extracted_edit_fields(
        result.get("date"),
        result.get("temperature"),
        result.get("humidity"),
    )

    # 날짜 기본값
    if not date_str:
        date_str = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")

    # 이미지 MIME
    fmt = (getattr(pil_img, "format", "") or "").upper()
    mime = "image/png" if fmt == "PNG" else "image/jpeg"

    # ✅ 독립 저장 버튼: 모바일/웹 모두 확실히 동작
    if st.button("💾 저장 (Drive + Sheet)", key="save_btn", use_container_width=True):
        if "__img_bytes__" not in st.session_state:
            st.error("이미지 데이터를 찾을 수 없습니다. 다시 업로드/촬영해 주세요.")
            return
        try:
            # My Drive 업로드 (로그인 사용자)
            link = upload_image_to_drive_user(
                creds,
                st.session_state["__img_bytes__"],
                filename_prefix="env_photo",
                mime_type=mime,
            )
            # 시트 한 줄 추가 (서비스계정)
            append_row(date_str, _to_float(temp), _to_float(hum), link)
            st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류: {e}")


if __name__ == "__main__":
    main()
