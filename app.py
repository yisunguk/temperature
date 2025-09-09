# app.py
"""
실외 온도/습도 기록기 (OAuth로 사진은 My Drive에 업로드, Sheets는 서비스계정으로 기록)
- 사진 업로드: 사용자 OAuth (upload_image_to_drive_user)
- 표 기록: Google Sheets 서비스계정
- 카메라 ON/OFF 토글은 ui.py에서 처리
"""

from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st

from ui import render_header, input_panel, extracted_edit_form, table_view
from ocr import run_ocr
from oauth_google import ensure_user_drive_creds          # ✅ OAuth 로그인
from storage import read_dataframe, append_row            # ✅ Sheets는 서비스계정
from storage import upload_image_to_drive_user            # ✅ OAuth 업로드 함수 사용
from storage import diagnose_permissions                  # 진단용

st.set_page_config(page_title="실외 온도/습도 기록기", layout="centered")
TZ = st.secrets.get("TIMEZONE", "Asia/Seoul")


def _to_float(x):
    try:
        return float(x) if x not in (None, "") else None
    except Exception:
        return None


def main():
    render_header()

    # ── 상단 표 (Sheets 서비스계정) ────────────────────────────────────────────────
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

    # ── 입력 (카메라/업로드) ─────────────────────────────────────────────────────
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

        # ── 추출값 확인/수정 (구/신 버전 모두 호환) ───────────────────────────────
        vals = extracted_edit_form(
            result.get("date"),
            result.get("temperature"),
            result.get("humidity"),
        )
        if isinstance(vals, tuple) and len(vals) == 4:
            date_str, temp, hum, submitted = vals
        else:
            date_str, temp, hum = vals
            submitted = st.button("💾 저장 (Drive + Sheet)")

        if not date_str:
            date_str = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")

        # 이미지 MIME 추정
        fmt = (getattr(pil_img, "format", "") or "").upper()
        mime = "image/png" if fmt == "PNG" else "image/jpeg"

        # ── 저장 처리: My Drive 업로드 → URL → Sheets 한 줄 추가 → 표 갱신 ────────
        if submitted:
            if "__img_bytes__" not in st.session_state:
                st.error("이미지 데이터를 찾을 수 없습니다. 이미지를 다시 업로드/촬영해 주세요.")
            else:
                try:
                    link = upload_image_to_drive_user(
                        creds,
                        st.session_state["__img_bytes__"],
                        filename_prefix="env_photo",
                        mime_type=mime,
                    )

                    append_row(
                        date_str,
                        _to_float(temp),
                        _to_float(hum),
                        link,
                    )
                    st.toast("저장 완료! 테이블을 새로고침합니다.", icon="✅")
                    st.rerun()

                except Exception as e:
                    st.error(f"저장 중 오류: {e}")

    else:
        st.info("카메라로 촬영하거나 갤러리에서 이미지를 업로드하세요.")


if __name__ == "__main__":
    main()
