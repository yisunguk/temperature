# oauth_google.py
import json
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


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


def _save(creds: Credentials):
    """세션에 토큰 저장 (rerun에도 재사용)"""
    token = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": st.secrets["google_oauth"]["client_id"],
        "client_secret": st.secrets["google_oauth"]["client_secret"],
        "scopes": _scopes(),
    }
    st.session_state["__google_token__"] = json.dumps(token)


def _load() -> Credentials | None:
    """세션에서 토큰 불러오고, 필요시 자동 refresh"""
    raw = st.session_state.get("__google_token__")
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


def _clear_code_param():
    try:
        # 최신 API
        st.query_params.clear()
    except Exception:
        # 구버전 호환
        st.experimental_set_query_params()


def ensure_user_drive_creds() -> Credentials:
    """
    - 세션에 유효한 토큰이 있으면 그대로 사용
    - 처음 진입 시 Google 로그인 링크를 보여줌(offline + prompt=consent)
    - 리다이렉트 후 code를 받아오면 토큰 저장 → 세션에 보관 → code 파라미터 제거
    """
    # 1) 세션에 저장된 자격 증명 재사용
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
        # code로 토큰 교환
        flow.fetch_token(code=code)
        creds = flow.credentials

        # 일부 계정은 처음에 refresh_token이 오지 않을 수 있어 재동의 한 번 유도
        if not creds.refresh_token:
            auth_url, _ = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",  # ← 오프라인 토큰을 확실히 받기 위한 재동의
            )
            st.info("Google 권한을 한 번만 다시 확인해 주세요. 이후에는 자동으로 유지됩니다.")
            st.link_button("✅ 권한 부여(한 번만)", auth_url, use_container_width=True)
            st.stop()

        _save(creds)
        _clear_code_param()
        return creds

    # 3) 아직 인증 전이면 로그인 버튼 표시 (offline+consent로 최초 1회 refresh_token 확보)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    st.info("Google Drive 업로드를 위해 로그인해 주세요. (최초 1회)")
    st.link_button("🔐 Google로 로그인", auth_url, use_container_width=True)
    st.stop()


def logout_button(label="🚪 로그아웃"):
    """원할 때 수동 로그아웃"""
    if st.button(label, type="secondary"):
        st.session_state.pop("__google_token__", None)
        st.experimental_rerun()
