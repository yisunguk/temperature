# oauth_google.py
import json
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from streamlit_cookies_manager import EncryptedCookieManager


# ──────────────────────────────────────────────────────────────────────────────
# 쿠키 관리 (브라우저 닫아도 유지)
# ──────────────────────────────────────────────────────────────────────────────
cookies = EncryptedCookieManager(
    prefix="envrecorder",  # 쿠키 키 prefix
    password=st.secrets.get("COOKIE_PASSWORD", "dev-only-cookie-secret"),
)
if not cookies.ready():
    st.stop()  # Streamlit 컴포넌트 초기화 대기


def _scopes():
    raw = st.secrets["google_oauth"].get("scopes", "")
    scopes = [s.strip() for s in raw.split(",") if s.strip()]
    if not scopes:
        scopes = [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
        ]
    return scopes


def _client_config():
    conf = st.secrets["google_oauth"]
    return {
        "web": {
            "client_id": conf["client_id"],
            "client_secret": conf["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [conf["redirect_uri"]],
        }
    }


def _token_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": st.secrets["google_oauth"]["client_id"],
        "client_secret": st.secrets["google_oauth"]["client_secret"],
        "scopes": _scopes(),
    }


def _save(creds: Credentials):
    """세션 + 암호화 쿠키에 저장"""
    data = _token_dict(creds)
    raw = json.dumps(data)
    st.session_state["__google_token__"] = raw
    cookies["gdrive_oauth"] = raw
    cookies.save()  # 브라우저에 기록


def _load_from_raw(raw: str | None) -> Credentials | None:
    if not raw:
        return None
    data = json.loads(raw)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or _scopes(),
    )
    # 만료 시 자동 갱신
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        _save(creds)
    return creds


def _load() -> Credentials | None:
    # 1) 세션 → 2) 쿠키 순으로 복원
    raw = st.session_state.get("__google_token__")
    creds = _load_from_raw(raw)
    if creds and creds.valid:
        return creds

    raw = cookies.get("gdrive_oauth")
    creds = _load_from_raw(raw)
    if creds and creds.valid:
        # 쿠키에서 복원했으면 세션에도 넣어두기
        _save(creds)
        return creds
    return None


def _clear_code_param():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()


def ensure_user_drive_creds() -> Credentials:
    """
    - 세션/쿠키에 유효한 토큰이 있으면 그대로 사용
    - 없으면 OAuth 로그인 유도(offline + prompt=consent로 refresh_token 확보)
    - 로그인/리다이렉트 후에는 토큰을 세션+쿠키에 저장 → 이후 브라우저 닫아도 유지
    """
    # 1) 저장된 토큰 재사용
    creds = _load()
    if creds and creds.valid:
        return creds

    # 2) OAuth 콜백(code) 처리
    params = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
    code = params.get("code")
    if isinstance(code, list):
        code = code[0]

    flow = Flow.from_client_config(
        client_config=_client_config(),
        scopes=_scopes(),
        redirect_uri=st.secrets["google_oauth"]["redirect_uri"],
    )

    if code:
        flow.fetch_token(code=code)
        creds = flow.credentials

        # 어떤 계정은 refresh_token이 처음에 비어 올 수 있어 재동의 한번 유도
        if not creds.refresh_token:
            auth_url, _ = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
            )
            st.info("Google 권한을 한 번만 다시 확인해 주세요. 이후에는 자동으로 유지됩니다.")
            st.link_button("✅ 권한 부여(한 번만)", auth_url, use_container_width=True)
            st.stop()

        _save(creds)
        _clear_code_param()
        return creds

    # 3) 아직 인증 전이면 로그인 버튼 표시
    auth_url, _ = flow.authorization_url(
        access_type="offline",            # ← refresh_token 발급
        include_granted_scopes="true",
        prompt="consent",                 # ← 같은 계정/클라이언트여도 확실히 받기
    )
    st.info("Google Drive 업로드를 위해 로그인해 주세요. (최초 1회)")
    st.link_button("🔐 Google로 로그인", auth_url, use_container_width=True)
    st.stop()


def logout_button(label="🚪 로그아웃"):
    """원할 때 수동 로그아웃 (세션+쿠키 모두 삭제)"""
    if st.button(label, type="secondary"):
        st.session_state.pop("__google_token__", None)
        cookies["gdrive_oauth"] = ""
        cookies.save()
        st.experimental_rerun()
